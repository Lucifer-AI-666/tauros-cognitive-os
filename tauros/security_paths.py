"""Filesystem allowlist, default-deny types, verified open (TOCTOU-aware)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterable


FORBIDDEN_COMPONENTS = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".kube",
        ".docker",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        "credentials",
        "passwd",
        "shadow",
        "wallet.dat",
        "cookies",
        "login data",
        "private_key",
        "private-key",
        "token.json",
        "secrets.json",
        "serviceaccount",
    }
)

FORBIDDEN_FILE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".netrc",
        ".npmrc",
        ".pypirc",
    }
)

ALLOWED_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".rst",
        ".py",
        ".pyi",
        ".rs",
        ".go",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".json",
        ".jsonc",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".csv",
        ".tsv",
        ".log",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".xml",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".bat",
        ".cmd",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".java",
        ".kt",
        ".kts",
        ".swift",
        ".rb",
        ".php",
        ".r",
        ".lua",
        ".pl",
        ".pm",
        ".gradle",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".sample",
    }
)

ALLOWED_BASENAMES = frozenset(
    {
        "dockerfile",
        "makefile",
        "license",
        "licence",
        "readme",
        "changelog",
        "authors",
        "copying",
        "gemfile",
        "procfile",
        "jenkinsfile",
        "vagrantfile",
    }
)


class AccessLevel(IntEnum):
    LIST = 1
    READ = 2
    INDEX = 3
    PROPOSE_WRITE = 4
    WRITE = 5


def normalize_memory_text(content: str) -> str:
    return " ".join(content.casefold().split())


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize_memory_text(content).encode("utf-8")).hexdigest()


def protect_env_file(path: Path) -> None:
    """Restrict .env to current user (POSIX mode + Windows icacls)."""
    if not path.exists():
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if sys.platform != "win32":
        return
    try:
        user = os.environ.get("USERNAME") or os.getlogin()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r"],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["icacls", str(path), "/grant:r", f"{user}:(R,W)"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def parse_path_list(raw: str | Iterable[str] | None) -> list[Path]:
    """
    Parse workspace paths without mangling commas inside folder names.

    Accepted:
    - JSON array
    - newline-separated paths
    - OS path separator (Windows ``;``, POSIX ``:``)
    - ``;`` fallback on POSIX for cross-platform env values
    """
    if raw is None:
        return []
    if not isinstance(raw, str):
        return [Path(str(p).strip()).expanduser() for p in raw if str(p).strip()]

    text = raw.strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [Path(str(p)).expanduser() for p in data if str(p).strip()]
        except json.JSONDecodeError:
            pass

    if "\n" in text:
        parts = [ln.strip() for ln in text.splitlines() if ln.strip()]
    else:
        parts = [p.strip() for p in text.split(os.pathsep) if p.strip()]
        if os.pathsep != ";" and len(parts) <= 1 and ";" in text:
            alt_parts = [p.strip() for p in text.split(";") if p.strip()]
            if len(alt_parts) > 1:
                parts = alt_parts

    return [Path(p).expanduser() for p in parts]


def looks_like_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    textish = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126)
    return (textish / max(len(sample), 1)) < 0.85


@dataclass
class PathDecision:
    allowed: bool
    reason: str
    path: Path | None = None
    requested: str | None = None
    normalized: str | None = None
    allow_root: str | None = None
    rule: str | None = None
    risk: str = "low"
    size: int | None = None
    detected_type: str | None = None
    access_level: int = int(AccessLevel.READ)
    audit_id: str = field(default_factory=lambda: secrets.token_hex(8))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path) if self.path else None
        return data


class PathGuard:
    """Confine filesystem tools to an explicit allowlist (default deny)."""

    def __init__(
        self,
        allowlist: list[Path] | None = None,
        blocklist: list[Path] | None = None,
        max_file_bytes: int = 2_000_000,
        require_allowlist: bool = True,
        max_access: AccessLevel = AccessLevel.READ,
    ):
        self.allowlist = [p.expanduser().resolve() for p in (allowlist or [])]
        self.blocklist = [p.expanduser().resolve() for p in (blocklist or [])]
        self.max_file_bytes = max_file_bytes
        self.require_allowlist = require_allowlist
        self.max_access = max_access

    def _is_under(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _matching_root(self, path: Path) -> Path | None:
        for root in self.allowlist:
            if self._is_under(path, root) or path == root:
                return root
        return None

    def _deny(
        self,
        reason: str,
        *,
        requested: str | None = None,
        path: Path | None = None,
        rule: str,
        risk: str = "high",
        allow_root: Path | None = None,
        size: int | None = None,
        detected_type: str | None = None,
        access_level: AccessLevel = AccessLevel.READ,
    ) -> PathDecision:
        return PathDecision(
            allowed=False,
            reason=reason,
            path=path,
            requested=requested,
            normalized=str(path) if path else None,
            allow_root=str(allow_root) if allow_root else None,
            rule=rule,
            risk=risk,
            size=size,
            detected_type=detected_type,
            access_level=int(access_level),
        )

    def _component_forbidden(self, path: Path) -> str | None:
        for part in path.parts:
            name = part.casefold()
            if name.endswith(":\\") or (len(name) == 2 and name[1] == ":"):
                continue
            if name in FORBIDDEN_COMPONENTS:
                return f"Componente vietato: {part}"
            if name in FORBIDDEN_FILE_NAMES:
                return f"File vietato: {part}"
            if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
                return f"File ambiente vietato: {part}"
        return None

    def _extension_allowed(self, path: Path) -> tuple[bool, str]:
        name = path.name.casefold()
        if name in ALLOWED_BASENAMES or name.startswith("readme"):
            return True, "allowed_basename"
        if name.endswith(".env.example"):
            return True, "env_example"
        suffix = path.suffix.casefold()
        if not suffix:
            return False, "extensionless_denied"
        if suffix in ALLOWED_TEXT_EXTENSIONS:
            return True, f"allowed_ext:{suffix}"
        return False, f"default_deny_ext:{suffix}"

    def resolve(
        self,
        path_value: str,
        *,
        for_read: bool = True,
        access: AccessLevel = AccessLevel.READ,
    ) -> PathDecision:
        requested = str(path_value) if path_value is not None else ""
        if not requested.strip():
            return self._deny("Percorso vuoto", requested=requested, rule="empty_path")

        if access > self.max_access:
            return self._deny(
                f"Livello accesso {access.name} non consentito (max {self.max_access.name})",
                requested=requested,
                rule="access_level",
                risk="medium",
            )

        raw = Path(path_value).expanduser()
        try:
            candidate = raw if raw.is_absolute() else (Path.cwd() / raw)
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            return self._deny(
                f"Percorso non risolvibile: {exc}",
                requested=requested,
                rule="unresolvable",
            )

        if self.require_allowlist and not self.allowlist:
            return self._deny(
                "Nessuna allowlist configurata: accesso filesystem negato",
                requested=requested,
                path=resolved,
                rule="empty_allowlist",
            )

        # Only the final resolved path must sit under an allow root.
        # Do not climb parents past that root.
        root = self._matching_root(resolved) if self.allowlist else None
        if self.allowlist and root is None:
            try:
                if candidate.exists() and (
                    candidate.is_symlink()
                    or any(p.is_symlink() for p in [candidate, *candidate.parents])
                ):
                    return self._deny(
                        "Link simbolico esce dall'allowlist",
                        requested=requested,
                        path=resolved,
                        rule="symlink_escape",
                        risk="critical",
                    )
            except OSError:
                pass
            return self._deny(
                "Percorso fuori dall'allowlist",
                requested=requested,
                path=resolved,
                rule="outside_allowlist",
            )

        if self.blocklist and any(
            self._is_under(resolved, blocked) or resolved == blocked for blocked in self.blocklist
        ):
            return self._deny(
                "Percorso in blocklist",
                requested=requested,
                path=resolved,
                rule="blocklist",
                allow_root=root,
            )

        posix = resolved.as_posix().casefold()
        if posix.startswith("/proc") or posix.startswith("/sys"):
            return self._deny(
                "Percorso di sistema sensibile",
                requested=requested,
                path=resolved,
                rule="system_path",
                allow_root=root,
                risk="critical",
            )

        forbidden = self._component_forbidden(resolved)
        if forbidden:
            return self._deny(
                forbidden,
                requested=requested,
                path=resolved,
                rule="forbidden_component",
                allow_root=root,
                risk="high",
            )

        size: int | None = None
        detected: str | None = (
            "directory" if resolved.exists() and resolved.is_dir() else None
        )
        if for_read and resolved.exists() and resolved.is_file():
            try:
                size = resolved.stat().st_size
            except OSError as exc:
                return self._deny(
                    f"Impossibile leggere metadati: {exc}",
                    requested=requested,
                    path=resolved,
                    rule="stat_failed",
                    allow_root=root,
                )
            if size > self.max_file_bytes:
                return self._deny(
                    f"File troppo grande ({size} byte > limite {self.max_file_bytes})",
                    requested=requested,
                    path=resolved,
                    rule="max_file_bytes",
                    allow_root=root,
                    size=size,
                    risk="medium",
                )
            ok_ext, ext_rule = self._extension_allowed(resolved)
            if not ok_ext:
                return self._deny(
                    f"Estensione non autorizzata (default deny): {resolved.suffix or '(nessuna)'}",
                    requested=requested,
                    path=resolved,
                    rule=ext_rule,
                    allow_root=root,
                    size=size,
                    detected_type="unknown",
                    risk="medium",
                )
            detected = resolved.suffix.casefold() or "text"

        return PathDecision(
            allowed=True,
            reason="Percorso autorizzato",
            path=resolved,
            requested=requested,
            normalized=str(resolved),
            allow_root=str(root) if root else None,
            rule="allowlist_match",
            risk="low",
            size=size,
            detected_type=detected,
            access_level=int(access),
        )

    def open_text_verified(
        self,
        path_value: str,
        *,
        max_chars: int = 20000,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        """Open text with re-validation after open (TOCTOU mitigation) + binary sniff."""
        first = self.resolve(path_value, for_read=True, access=AccessLevel.READ)
        if not first.allowed or first.path is None:
            raise PermissionError(first.reason)

        path = first.path
        with path.open("rb") as handle:
            second = self.resolve(str(path), for_read=True, access=AccessLevel.READ)
            if not second.allowed or second.path is None:
                raise PermissionError(second.reason or "Rifiuto post-open")
            if second.path.resolve() != path.resolve():
                raise PermissionError("TOCTOU: il percorso è cambiato dopo l'apertura")

            head = handle.read(8192)
            if looks_like_binary(head):
                raise PermissionError("Contenuto binario rilevato (default deny)")

            rest = handle.read(max(0, max_chars * 4 - len(head)))
            data = (head + rest).decode(encoding, errors="replace")[:max_chars]
            try:
                size = path.stat().st_size
            except OSError:
                size = None

        return {
            "path": str(second.path),
            "content": data,
            "truncated": bool(size and size > len(data.encode("utf-8", errors="replace"))),
            "size": size,
            "audit_id": second.audit_id,
            "allow_root": second.allow_root,
            "rule": second.rule,
            "detected_type": second.detected_type or "text",
        }
