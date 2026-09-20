"""Hybrid planner: rule-based + optional LLM StructuredPlan (data only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import ToolCall
from .plan_models import PlanStep, StructuredPlan
from .plan_validator import PlanValidator
from .providers import LLMProvider, ProviderError


@dataclass
class Plan:
    """Legacy thin plan for backward-compatible single-tool routing."""

    intent: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    structured: StructuredPlan | None = None
    source: str = "rules"  # rules | llm | hybrid


PLANNER_SYSTEM = """Sei il planner di TAUROS Cognitive OS.
Produci SOLO un oggetto JSON valido (niente markdown, niente testo fuori dal JSON).
Schema:
{
  "intent": "string breve",
  "mode": "chat" | "plan" | "execute_read_only",
  "rationale": "string",
  "steps": [
    {
      "id": "s1",
      "tool": "nome_tool",
      "arguments": {},
      "risk": "low",
      "purpose": "perché"
    }
  ]
}

Regole:
- Mai tool di scrittura diretta (write_file, delete, shell, install).
- Tool ammessi: system_info, disk_usage, list_directory, read_text_file,
  memory_search, workspace_search, git_status, git_log, git_diff, project_summary,
  propose_write, propose_patch, file_snapshot.
- Se proponi una modifica file: mode=propose_write e usa solo propose_write/propose_patch.
- propose_write NON scrive su disco: crea una bozza da approvare in console.
- Massimo N_STEPS passaggi. Id univoci s1,s2,...
- Se è solo conversazione: mode=chat e steps=[].
- Preferisci execute_read_only se servono file/git/workspace in lettura.
- Non inventare path fuori dal contesto utente.
- arguments devono essere oggetti semplici (stringhe/numeri/bool).
"""


class Planner:
    """
    Deterministic rule planner + optional LLM JSON planner.

    Does NOT call tools. Does NOT hold executables.
    Emits JSON-serializable StructuredPlan instances.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        max_steps: int = 3,
        allowed_tools: set[str] | frozenset[str] | None = None,
    ):
        self.provider = provider
        self.max_steps = max(1, max_steps)
        self.allowed_tools = set(allowed_tools or {
            "system_info",
            "disk_usage",
            "list_directory",
            "read_text_file",
            "memory_search",
            "workspace_search",
            "git_status",
            "git_log",
            "git_diff",
            "project_summary",
            "propose_write",
            "propose_patch",
            "file_snapshot",
        })
        self._validator = PlanValidator(
            allowed_tools=self.allowed_tools,
            max_steps=self.max_steps,
            max_same_tool=2,
        )

    def create(self, message: str, use_tools: bool = True) -> Plan:
        structured = self.create_structured(message, use_tools=use_tools)
        legacy_calls = [
            ToolCall(name=s.tool, arguments=s.arguments) for s in structured.steps
        ]
        return Plan(
            intent=structured.intent,
            tool_calls=legacy_calls,
            structured=structured,
            source="rules",
        )

    def create_structured(self, message: str, use_tools: bool = True) -> StructuredPlan:
        text = message.lower().strip()
        if not use_tools:
            return StructuredPlan(
                intent="conversation",
                mode="chat",
                steps=[],
                rationale="Nessun tool richiesto",
            )

        if any(
            k in text
            for k in ["informazioni sul sistema", "che sistema", "hostname", "versione python"]
        ):
            return StructuredPlan(
                intent="inspect_system",
                mode="execute_read_only",
                rationale="Richiesta informazioni di sistema",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="system_info",
                        arguments={},
                        risk="low",
                        purpose="Leggere metadati host/python",
                    )
                ],
            )

        if any(k in text for k in ["spazio disco", "disco libero", "quanto spazio"]):
            return StructuredPlan(
                intent="inspect_disk",
                mode="execute_read_only",
                rationale="Richiesta spazio disco",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="disk_usage",
                        arguments={},
                        risk="low",
                        purpose="Misurare spazio disco",
                    )
                ],
            )

        if any(k in text for k in ["git status", "stato git", "stato del repo", "working tree"]):
            path = self._extract_path(message)
            args: dict[str, Any] = {}
            if path:
                args["path"] = path
            return StructuredPlan(
                intent="git_status",
                mode="execute_read_only",
                rationale="Stato repository git",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="git_status",
                        arguments=args,
                        risk="low",
                        purpose="git status --short",
                    )
                ],
            )

        if any(k in text for k in ["git log", "commit recenti", "cronologia git", "history git"]):
            path = self._extract_path(message)
            args = {"limit": 12}
            if path:
                args["path"] = path
            return StructuredPlan(
                intent="git_log",
                mode="execute_read_only",
                rationale="Log commit recenti",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="git_log",
                        arguments=args,
                        risk="low",
                        purpose="git log",
                    )
                ],
            )

        if any(k in text for k in ["git diff", "diff git", "modifiche non committate"]):
            path = self._extract_path(message)
            args = {}
            if path:
                args["path"] = path
            return StructuredPlan(
                intent="git_diff",
                mode="execute_read_only",
                rationale="Diff working tree",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="git_diff",
                        arguments=args,
                        risk="low",
                        purpose="git diff",
                    )
                ],
            )

        search_match = re.search(
            r"(?:cerca|search|trova)\s+(?:nel\s+workspace\s+|nei\s+file\s+|in\s+progetto\s+)?[\"']?(.+?)[\"']?\s*$",
            message,
            re.IGNORECASE,
        )
        if search_match and any(
            k in text for k in ["cerca", "search", "trova nel", "workspace", "nei file"]
        ):
            query = search_match.group(1).strip().strip("\"'")
            if query and len(query) < 200:
                return StructuredPlan(
                    intent="workspace_search",
                    mode="execute_read_only",
                    rationale="Ricerca testo workspace",
                    steps=[
                        PlanStep(
                            id="s1",
                            tool="workspace_search",
                            arguments={"query": query},
                            risk="low",
                            purpose=f"Cercare {query}",
                        )
                    ],
                )

        match = re.search(
            r"(?:elenca|mostra) (?:la )?cartella\s+(.+)$", message, re.IGNORECASE
        )
        if match:
            path = match.group(1).strip().strip("\"'")
            return StructuredPlan(
                intent="list_directory",
                mode="execute_read_only",
                rationale="Elenco directory in sola lettura",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="list_directory",
                        arguments={"path": path},
                        risk="low",
                        purpose=f"Elencare {path}",
                    )
                ],
            )

        if any(
            k in text
            for k in [
                "analizza cartella",
                "ispeziona progetto",
                "analizza progetto",
                "scansiona",
                "riassumi progetto",
                "project summary",
            ]
        ):
            path_match = re.search(r"(?:cartella|progetto|path)\s+(.+)$", message, re.IGNORECASE)
            path = path_match.group(1).strip().strip("\"'") if path_match else None
            args = {}
            if path:
                args["path"] = path
            return StructuredPlan(
                intent="inspect_project_readonly",
                mode="execute_read_only",
                rationale="Ispezione sola lettura progetto",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="project_summary",
                        arguments=args,
                        risk="low",
                        purpose="Riassunto struttura",
                    ),
                    PlanStep(
                        id="s2",
                        tool="git_status",
                        arguments=dict(args),
                        risk="low",
                        purpose="Stato git se presente",
                    ),
                ],
            )

        # Supervised write proposals (never direct write)
        create_m = re.search(
            r"(?:crea|scrivi|genera)\s+(?:un\s+)?(?:nuovo\s+)?file\s+[\"']?([^\s\"']+)[\"']?\s+(?:con|contenuto|testo)\s+(.+)$",
            message,
            re.IGNORECASE | re.DOTALL,
        )
        if create_m:
            path = create_m.group(1).strip()
            content = create_m.group(2).strip().strip("\"'")
            return StructuredPlan(
                intent="propose_create_file",
                mode="propose_write",
                rationale="Proposta creazione file — richiede approvazione umana",
                steps=[
                    PlanStep(
                        id="s1",
                        tool="propose_write",
                        arguments={"path": path, "content": content, "kind": "create"},
                        risk="medium",
                        purpose=f"Bozza creazione {path}",
                    )
                ],
            )

        if any(
            k in text
            for k in [
                "proponi scrittura",
                "proponi modifica",
                "modifica il file",
                "riscrivi il file",
                "propose write",
            ]
        ):
            path = self._extract_path(message) or ""
            return StructuredPlan(
                intent="propose_write_hint",
                mode="propose_write",
                rationale="Intento di scrittura supervisionata — senza content esplicito resta in plan",
                steps=[],
            )

        return StructuredPlan(
            intent="conversation",
            mode="chat",
            steps=[],
            rationale="Conversazione senza strumenti",
        )

    def _extract_path(self, message: str) -> str | None:
        m = re.search(
            r"(?:in|su|path|cartella|repo)\s+[\"']?([A-Za-z]:\\[^\s\"']+|/[^\s\"']+|\./[^\s\"']+)[\"']?",
            message,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else None

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        raw = (text or "").strip()
        if not raw:
            return None
        # Strip markdown fences if any
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
        # Find first {...} block
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    async def create_llm(
        self,
        message: str,
        *,
        use_tools: bool = True,
        available_tools: list[dict[str, str]] | None = None,
        context_hint: str = "",
    ) -> Plan:
        """Ask the LLM for a StructuredPlan; fall back to rules if invalid/unavailable."""
        rules = self.create(message, use_tools=use_tools)
        if not use_tools or self.provider is None:
            return rules

        # Saluti e chiacchiere: niente piano LLM, solo conversazione.
        compact = " ".join(message.split()).casefold().strip("!.? ")
        if len(compact) < 16 and not any(
            k in compact
            for k in ["file", "git", "disco", "sistema", "analizza", "cartella"]
        ):
            return rules

        # If rules already found a concrete multi-step or tool plan, prefer it
        # unless message looks open-ended / analytical.
        open_ended = any(
            k in message.lower()
            for k in [
                "analizza",
                "ispeziona",
                "perché",
                "come mai",
                "piano",
                "step",
                "indaga",
                "controlla",
                "verifica",
                "riassumi",
                "explore",
                "investigate",
            ]
        )
        if rules.structured and rules.structured.steps and not open_ended:
            return rules

        tool_names = sorted(self.allowed_tools)
        if available_tools:
            tool_names = sorted({t["name"] for t in available_tools} & self.allowed_tools)

        sys_prompt = PLANNER_SYSTEM.replace("N_STEPS", str(self.max_steps))
        user_payload = {
            "user_message": message,
            "available_tools": tool_names,
            "max_steps": self.max_steps,
            "context_hint": context_hint[:1500] if context_hint else "",
        }
        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ]
        try:
            raw = await self.provider.chat(messages)
        except ProviderError:
            return rules
        except Exception:  # noqa: BLE001
            return rules

        data = self._extract_json_object(raw)
        if not data:
            return rules

        # Force read-only mode for execution path
        mode = str(data.get("mode") or "execute_read_only")
        if mode not in {"chat", "plan", "execute_read_only", "propose_write"}:
            mode = "execute_read_only"
        if mode == "propose_write":
            mode = "plan"  # never execute writes from LLM planner
        data["mode"] = mode

        validation = self._validator.validate_raw(data)
        if not validation.ok or not validation.plan:
            # Soft repair: drop bad steps and re-validate
            if validation.plan and validation.plan.steps:
                cleaned_steps = [
                    s
                    for s in validation.plan.steps
                    if s.tool in self.allowed_tools
                ][: self.max_steps]
                repaired = validation.plan.model_copy(update={"steps": cleaned_steps})
                if repaired.mode == "execute_read_only" and not cleaned_steps:
                    repaired = repaired.model_copy(update={"mode": "chat"})
                v2 = self._validator.validate(repaired)
                if not v2.ok or not v2.plan:
                    return rules
                plan = v2.plan
            else:
                return rules
        else:
            plan = validation.plan

        # If LLM returned empty chat while rules had tools and not open-ended — keep rules
        if not plan.steps and rules.structured and rules.structured.steps and not open_ended:
            return rules

        legacy = [ToolCall(name=s.tool, arguments=s.arguments) for s in plan.steps]
        return Plan(
            intent=plan.intent,
            tool_calls=legacy,
            structured=plan,
            source="llm",
        )
