from __future__ import annotations

import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .policy import PolicyEngine
from .security import PathGuard, redact_obj
from .settings import Settings


class ToolRegistry:
    def __init__(
        self,
        policy: PolicyEngine,
        settings: Settings | None = None,
        path_guard: PathGuard | None = None,
        memory: Any | None = None,
        writes: Any | None = None,
    ):
        self.policy = policy
        self.settings = settings
        self.path_guard = path_guard or getattr(policy, "path_guard", None)
        self.memory = memory
        self.writes = writes
        self.max_output_chars = settings.max_tool_output_chars if settings else 100_000
        self._current_user_id: int | None = None
        self._current_role: str = "user"
        self._current_actor: str = "tool"
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            "system_info": self.system_info,
            "list_directory": self.list_directory,
            "read_text_file": self.read_text_file,
            "disk_usage": self.disk_usage,
            "workspace_search": self.workspace_search,
            "git_status": self.git_status,
            "git_log": self.git_log,
            "git_diff": self.git_diff,
            "project_summary": self.project_summary,
            "memory_search": self.memory_search,
            "propose_write": self.propose_write,
            "propose_patch": self.propose_patch,
            "file_snapshot": self.file_snapshot,
        }
        self._call_counts: dict[str, int] = {}

    def reset_turn_limits(self) -> None:
        self._call_counts.clear()

    def available(self) -> list[dict[str, str]]:
        mode = self.settings.security_mode if self.settings else "read_only"
        tools = [
            {"name": "system_info", "description": "Informazioni locali sul sistema", "risk": "low"},
            {"name": "list_directory", "description": "Elenca una directory in sola lettura", "risk": "low"},
            {"name": "read_text_file", "description": "Legge un file di testo con limite", "risk": "low"},
            {"name": "disk_usage", "description": "Mostra lo spazio disco", "risk": "low"},
            {"name": "memory_search", "description": "Cerca nella memoria personale attiva/candidate", "risk": "low"},
            {"name": "workspace_search", "description": "Cerca testo nei file del workspace (allowlist)", "risk": "low"},
            {"name": "git_status", "description": "git status in sola lettura", "risk": "low"},
            {"name": "git_log", "description": "git log recente in sola lettura", "risk": "low"},
            {"name": "git_diff", "description": "git diff (working tree) in sola lettura", "risk": "low"},
            {"name": "project_summary", "description": "Riassunto struttura progetto (read-only)", "risk": "low"},
            {
                "name": "propose_write",
                "description": "Propone creazione/sostituzione file (NON scrive; serve approvazione UI)",
                "risk": "medium",
            },
            {
                "name": "propose_patch",
                "description": "Propone patch univoca old→new (NON scrive; serve approvazione UI)",
                "risk": "medium",
            },
            {
                "name": "file_snapshot",
                "description": "Crea copia di sicurezza di un file (rollback point)",
                "risk": "low",
            },
        ]
        if mode == "locked":
            return [t for t in tools if t["name"] in {"system_info", "memory_search"}]
        return tools

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        self._call_counts[name] = self._call_counts.get(name, 0) + 1
        max_same = self.settings.max_same_tool_calls if self.settings else 3
        if self._call_counts[name] > max_same:
            return self._result(
                False,
                name,
                started,
                error=f"Limite chiamate per tool superato ({max_same})",
                policy="blocked",
            )

        call_args = dict(arguments or {})
        role = str(call_args.pop("_role", "user"))
        user_id = int(call_args.pop("_user_id", 0) or 0)
        actor = str(call_args.pop("_actor", "tool"))
        confirmed = call_args.pop("_confirmed", None)
        self._current_user_id = user_id or None
        self._current_role = role
        self._current_actor = actor
        decision = self.policy.authorize_tool(
            name, call_args, role=role, user_id=user_id, confirmed=confirmed
        )
        if not decision.allowed:
            return self._result(False, name, started, error=decision.reason, policy="blocked")

        tool = self._tools.get(name)
        if not tool:
            return self._result(False, name, started, error="Strumento non registrato", policy="blocked")

        try:
            data = tool(**call_args)
            data = self._trim_output(data)
            return self._result(True, name, started, data=data, policy="allowed")
        except TypeError as exc:
            return self._result(False, name, started, error=f"Argomenti non validi: {exc}", policy="allowed")
        except Exception as exc:
            return self._result(False, name, started, error=str(exc), policy="allowed")

    def _trim_output(self, data: Any) -> Any:
        text = repr(data)
        if len(text) <= self.max_output_chars:
            return data
        if isinstance(data, dict):
            clipped = dict(data)
            clipped["truncated"] = True
            clipped["warning"] = f"Output tagliato oltre {self.max_output_chars} caratteri"
            if "content" in clipped and isinstance(clipped["content"], str):
                clipped["content"] = clipped["content"][: self.max_output_chars]
            if "matches" in clipped and isinstance(clipped["matches"], list):
                clipped["matches"] = clipped["matches"][:50]
            return clipped
        return {"truncated": True, "data": text[: self.max_output_chars]}

    def _result(
        self,
        success: bool,
        tool: str,
        started: float,
        data: Any = None,
        error: str | None = None,
        policy: str = "allowed",
    ) -> dict[str, Any]:
        payload = {
            "success": success,
            "ok": success,  # backward compatible with v0.2 UI
            "tool": tool,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "data": redact_obj(data) if data is not None else None,
            "result": redact_obj(data) if data is not None else None,
            "warnings": [],
            "error": error,
            "policy": policy,
        }
        return payload

    def _resolve_root(self, path: str | None, *, for_read: bool = True) -> Path:
        if path is None or not str(path).strip():
            if not self.path_guard or not self.path_guard.allowlist:
                raise PermissionError("Allowlist vuota: specifica un percorso autorizzato")
            return self.path_guard.allowlist[0]
        decision = self.path_guard.resolve(path, for_read=for_read) if self.path_guard else None
        if decision and not decision.allowed:
            raise PermissionError(decision.reason)
        return decision.path if decision and decision.path else Path(path).expanduser().resolve()

    def system_info(self) -> dict[str, Any]:
        return {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "hostname": platform.node(),
            "machine": platform.machine(),
        }

    def list_directory(self, path: str | None = None, limit: int = 200) -> dict[str, Any]:
        target = self._resolve_root(path, for_read=True)
        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Directory non trovata: {target}")

        items = []
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower())[: max(1, min(int(limit), 500))]:
            if self.path_guard:
                check = self.path_guard.resolve(str(child), for_read=False)
                if not check.allowed and "sensibile" in check.reason.casefold():
                    continue
            try:
                size = child.stat().st_size if child.is_file() else 0
            except OSError:
                size = 0
            items.append(
                {
                    "name": child.name,
                    "type": "directory" if child.is_dir() else "file",
                    "size": size,
                }
            )
        return {"path": str(target), "items": items}

    def read_text_file(self, path: str, max_chars: int = 20000) -> dict[str, Any]:
        max_chars = min(int(max_chars), self.max_output_chars)
        if self.path_guard:
            return self.path_guard.open_text_verified(path, max_chars=max_chars)
        target = Path(path).expanduser().resolve()
        data = target.read_text(encoding="utf-8", errors="replace")[:max_chars]
        return {
            "path": str(target),
            "content": data,
            "truncated": target.stat().st_size > len(data.encode("utf-8", errors="replace")),
        }

    def disk_usage(self, path: str | None = None) -> dict[str, Any]:
        target = self._resolve_root(path, for_read=False)
        total, used, free = shutil.disk_usage(target)
        return {"path": str(target), "total": total, "free": free, "used": used}

    def memory_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        if not self.memory:
            raise RuntimeError("Memoria non collegata a ToolRegistry")
        q = (query or "").strip()
        if not q:
            raise ValueError("query obbligatoria")
        lim = max(1, min(int(limit), 50))
        uid = self._current_user_id
        if hasattr(self.memory, "recall"):
            hits = self.memory.recall(q, lim, user_id=uid)
        else:
            hits = []
        return {"query": q, "count": len(hits), "items": hits}

    def workspace_search(
        self,
        query: str,
        path: str | None = None,
        max_files: int = 40,
        max_matches: int = 30,
    ) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            raise ValueError("query obbligatoria")
        root = self._resolve_root(path, for_read=True)
        if not root.is_dir():
            raise FileNotFoundError(f"Directory non trovata: {root}")

        skip_dirs = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            "dist",
            "build",
            ".tox",
            "data",
        }
        skip_suffix = {
            ".pyc",
            ".pyo",
            ".so",
            ".dll",
            ".exe",
            ".bin",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".ico",
            ".pdf",
            ".zip",
            ".gz",
            ".7z",
            ".db",
            ".sqlite",
            ".woff",
            ".woff2",
        }
        max_files = max(1, min(int(max_files), 200))
        max_matches = max(1, min(int(max_matches), 100))
        pattern = re.compile(re.escape(q), re.IGNORECASE)
        matches: list[dict[str, Any]] = []
        files_scanned = 0
        max_file_bytes = self.settings.max_file_bytes if self.settings else 2_000_000

        import os

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            for name in filenames:
                if files_scanned >= max_files or len(matches) >= max_matches:
                    break
                suffix = Path(name).suffix.lower()
                if suffix in skip_suffix:
                    continue
                if name.startswith(".") and name not in {".env.example", ".gitignore"}:
                    continue
                fpath = Path(dirpath) / name
                if self.path_guard:
                    check = self.path_guard.resolve(str(fpath), for_read=True)
                    if not check.allowed:
                        continue
                    fpath = check.path or fpath
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                if not fpath.is_file() or st.st_size > min(max_file_bytes, 400_000):
                    continue
                files_scanned += 1
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        matches.append(
                            {
                                "path": str(fpath),
                                "line": i,
                                "snippet": line.strip()[:240],
                            }
                        )
                        if len(matches) >= max_matches:
                            break
            if files_scanned >= max_files or len(matches) >= max_matches:
                break

        return {
            "query": q,
            "root": str(root),
            "files_scanned": files_scanned,
            "match_count": len(matches),
            "matches": matches,
            "truncated": files_scanned >= max_files or len(matches) >= max_matches,
        }

    def _run_git(self, path: str | None, args: list[str], timeout: int | None = None) -> dict[str, Any]:
        root = self._resolve_root(path, for_read=True)
        if not root.exists():
            raise FileNotFoundError(f"Path non trovato: {root}")
        # Find git root: if path is file, use parent
        cwd = root if root.is_dir() else root.parent
        timeout = timeout or (self.settings.tool_timeout_seconds if self.settings else 30)
        # Refuse write-like git args
        blocked = {
            "commit",
            "push",
            "pull",
            "checkout",
            "merge",
            "rebase",
            "reset",
            "clean",
            "add",
            "rm",
            "mv",
            "tag",
            "stash",
            "fetch",
            "clone",
            "init",
            "config",
        }
        if any(a.lstrip("-") in blocked for a in args):
            raise PermissionError(f"Comando git non ammesso in sola lettura: {args}")
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("git non installato o non nel PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"git timeout dopo {timeout}s") from exc
        out = (proc.stdout or "")[: self.max_output_chars]
        err = (proc.stderr or "")[: 2000]
        return {
            "path": str(cwd),
            "args": args,
            "exit_code": proc.returncode,
            "stdout": out,
            "stderr": err,
            "ok": proc.returncode == 0,
        }

    def git_status(self, path: str | None = None) -> dict[str, Any]:
        return self._run_git(path, ["status", "--short", "--branch"])

    def git_log(self, path: str | None = None, limit: int = 12) -> dict[str, Any]:
        lim = max(1, min(int(limit), 50))
        return self._run_git(
            path,
            ["log", f"-{lim}", "--pretty=format:%h %ad %an %s", "--date=short"],
        )

    def git_diff(self, path: str | None = None, max_chars: int = 30000) -> dict[str, Any]:
        result = self._run_git(path, ["diff", "--stat", "HEAD"])
        # Also include a truncated full diff if short
        full = self._run_git(path, ["diff", "HEAD"])
        content = (full.get("stdout") or "")[: max(1000, min(int(max_chars), self.max_output_chars))]
        result["diff_preview"] = content
        result["diff_truncated"] = len(full.get("stdout") or "") > len(content)
        return result

    def project_summary(self, path: str | None = None) -> dict[str, Any]:
        root = self._resolve_root(path, for_read=True)
        if not root.is_dir():
            raise FileNotFoundError(f"Directory non trovata: {root}")
        listing = self.list_directory(str(root), limit=80)
        markers = [
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "requirements.txt",
            "Dockerfile",
            "README.md",
            "README",
            ".git",
        ]
        found = []
        for m in markers:
            p = root / m
            if p.exists():
                found.append(m)
        git_branch = None
        if (root / ".git").exists():
            try:
                st = self.git_status(str(root))
                git_branch = (st.get("stdout") or "").splitlines()[0] if st.get("stdout") else None
            except Exception:  # noqa: BLE001
                git_branch = None
        return {
            "path": str(root),
            "top_level": listing.get("items", []),
            "markers": found,
            "git_head": git_branch,
        }

    def propose_write(
        self,
        path: str,
        content: str,
        kind: str = "replace",
        purpose: str = "",
    ) -> dict[str, Any]:
        """Draft only — never touches disk for the target content."""
        if not self.writes:
            raise RuntimeError("WriteService non collegato")
        if kind not in {"create", "replace"}:
            kind = "replace"
        return self.writes.propose(
            user_id=self._current_user_id or 0,
            actor=self._current_actor,
            path=path,
            content=content,
            kind=kind,
            purpose=purpose,
            role=self._current_role,
        )

    def propose_patch(
        self,
        path: str,
        old_text: str,
        new_text: str,
        purpose: str = "",
    ) -> dict[str, Any]:
        if not self.writes:
            raise RuntimeError("WriteService non collegato")
        return self.writes.propose(
            user_id=self._current_user_id or 0,
            actor=self._current_actor,
            path=path,
            kind="patch",
            old_text=old_text,
            new_text=new_text,
            purpose=purpose,
            role=self._current_role,
        )

    def file_snapshot(self, path: str) -> dict[str, Any]:
        if not self.writes:
            raise RuntimeError("WriteService non collegato")
        return self.writes.snapshot(
            path,
            user_id=self._current_user_id or 0,
            actor=self._current_actor,
            role=self._current_role,
        )
