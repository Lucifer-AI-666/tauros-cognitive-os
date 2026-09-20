"""User-editable rule base. The model proposes; these rules can still say no."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Effect = Literal["deny", "confirm", "allow"]
MatchKind = Literal["tool", "path"]


@dataclass
class Rule:
    id: str
    enabled: bool
    effect: Effect
    match: MatchKind
    value: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleHit:
    rule: Rule
    reason: str


def _norm_path(value: str) -> str:
    try:
        return str(Path(value).expanduser())
    except OSError:
        return value


class RuleStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(_default_payload())

    def _write(self, payload: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = _default_payload()
            self._write(data)
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            data = _default_payload()
        return data

    def list_rules(self) -> list[Rule]:
        return [r for r in (_parse_rule(item) for item in self._read().get("rules", [])) if r]

    def replace_all(self, items: list[dict[str, Any]]) -> list[Rule]:
        rules: list[Rule] = []
        for item in items:
            parsed = _parse_rule(item, mint_id=True)
            if parsed:
                rules.append(parsed)
        self._write({"version": 1, "rules": [r.to_dict() for r in rules]})
        return rules

    def add(self, item: dict[str, Any]) -> Rule:
        parsed = _parse_rule(item, mint_id=True)
        if not parsed:
            raise ValueError("Regola non valida")
        rules = self.list_rules()
        rules.append(parsed)
        self._write({"version": 1, "rules": [r.to_dict() for r in rules]})
        return parsed

    def delete(self, rule_id: str) -> bool:
        rules = self.list_rules()
        kept = [r for r in rules if r.id != rule_id]
        if len(kept) == len(rules):
            return False
        self._write({"version": 1, "rules": [r.to_dict() for r in kept]})
        return True

    def set_enabled(self, rule_id: str, enabled: bool) -> Rule | None:
        rules = self.list_rules()
        found = None
        for rule in rules:
            if rule.id == rule_id:
                rule.enabled = bool(enabled)
                found = rule
        if not found:
            return None
        self._write({"version": 1, "rules": [r.to_dict() for r in rules]})
        return found

    def evaluate(self, tool: str, path: str | None = None) -> RuleHit | None:
        tool_name = (tool or "").strip()
        path_n = _norm_path(path) if path else ""
        for rule in self.list_rules():
            if not rule.enabled:
                continue
            if rule.match == "tool":
                if rule.value in {"*", tool_name}:
                    return RuleHit(rule, f"regola {rule.id}: {rule.effect} tool {tool_name}")
            elif rule.match == "path" and path_n:
                prefix = _norm_path(rule.value)
                if path_n == prefix or path_n.startswith(prefix.rstrip("\\/") + "\\") or path_n.startswith(
                    prefix.rstrip("\\/") + "/"
                ):
                    return RuleHit(rule, f"regola {rule.id}: {rule.effect} path {path_n}")
        return None


def _parse_rule(item: Any, *, mint_id: bool = False) -> Rule | None:
    if not isinstance(item, dict):
        return None
    effect = str(item.get("effect") or "").strip().lower()
    match = str(item.get("match") or "").strip().lower()
    value = str(item.get("value") or "").strip()
    if effect not in {"deny", "confirm", "allow"}:
        return None
    if match not in {"tool", "path"}:
        return None
    if not value:
        return None
    rid = str(item.get("id") or "").strip()
    if not rid:
        if not mint_id:
            return None
        rid = "r" + secrets.token_hex(3)
    return Rule(
        id=rid,
        enabled=bool(item.get("enabled", True)),
        effect=effect,  # type: ignore[arg-type]
        match=match,  # type: ignore[arg-type]
        value=value,
        note=str(item.get("note") or "")[:300],
    )


def _default_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "rules": [
            {
                "id": "r-no-delete",
                "enabled": True,
                "effect": "deny",
                "match": "tool",
                "value": "delete_file",
                "note": "Niente cancellazioni automatiche.",
            },
            {
                "id": "r-confirm-write",
                "enabled": True,
                "effect": "confirm",
                "match": "tool",
                "value": "propose_write",
                "note": "Ogni scrittura proposta resta da approvare.",
            },
        ],
    }


# Perception / action registry — maps today's tools, reserves tomorrow's hands.
AGENT_CATALOG = [
    {
        "id": "brain.vertex",
        "kind": "brain",
        "status": "live",
        "title": "AI Brain (Vertex / fallback Groq)",
        "notes": "Adapter già in tauros.providers",
    },
    {
        "id": "brain.dib",
        "kind": "brain",
        "status": "live",
        "title": "DIB-OS Brain (cache tokenizzata + Ollama)",
        "notes": "POST http://127.0.0.1:1988/api/chat",
    },
    {
        "id": "perception.fs",
        "kind": "perception",
        "status": "live",
        "title": "File system",
        "tools": ["list_directory", "read_text_file", "disk_usage", "workspace_search"],
    },
    {
        "id": "perception.git",
        "kind": "perception",
        "status": "live",
        "title": "Git inspector",
        "tools": ["git_status", "git_log", "git_diff"],
    },
    {
        "id": "action.writes",
        "kind": "action",
        "status": "live",
        "title": "Scritture supervisionate",
        "tools": ["propose_write", "propose_patch", "file_snapshot"],
    },
    {
        "id": "perception.screen",
        "kind": "perception",
        "status": "planned",
        "title": "Screen / OCR",
        "notes": "Non ancora. Serve un modulo esterno, non l'LLM.",
    },
    {
        "id": "action.desktop",
        "kind": "action",
        "status": "planned",
        "title": "Desktop Agent (click/tastiera)",
        "notes": "Bloccato finché le regole non coprono UI automation.",
    },
    {
        "id": "action.browser",
        "kind": "action",
        "status": "planned",
        "title": "Browser Agent",
        "notes": "Stesso vincolo: prima Rule Enforcer, poi le mani.",
    },
    {
        "id": "action.shell",
        "kind": "action",
        "status": "planned",
        "title": "Shell Agent",
        "notes": "Volutamente assente. Troppo potere senza regole.",
    },
]
