"""
Supervised writes: propose → preview → approve → backup → write → verify → rollback.

Never silent. Never permanent god mode. Audit always.
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .privileges import ConfirmationLevel, PrivilegeLevel, PrivilegeService
from .security import PathGuard, redact_obj
from .settings import Settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ProposalKind(str, Enum):
    CREATE = "create"
    REPLACE = "replace"
    PATCH = "patch"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"  # reserved
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class WriteProposal:
    id: str
    user_id: int
    actor: str
    path: str
    kind: ProposalKind
    content_before: str | None
    content_after: str
    patch_old: str | None = None
    patch_new: str | None = None
    purpose: str = ""
    risk: str = "medium"
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: str = field(default_factory=lambda: _now().isoformat())
    decided_at: str | None = None
    backup_path: str | None = None
    result_hash: str | None = None
    expected_hash: str | None = None
    error: str | None = None
    in_trust_zone: bool = False
    requires_strong: bool = False

    def to_public(self, *, include_full: bool = True) -> dict[str, Any]:
        before_preview = None
        after_preview = self.content_after
        if include_full:
            before_preview = self.content_before
        else:
            if self.content_before is not None:
                before_preview = self.content_before[:2000] + (
                    "…" if len(self.content_before) > 2000 else ""
                )
            after_preview = self.content_after[:2000] + (
                "…" if len(self.content_after) > 2000 else ""
            )
        return {
            "id": self.id,
            "user_id": self.user_id,
            "actor": self.actor,
            "path": self.path,
            "kind": self.kind.value,
            "status": self.status.value,
            "purpose": self.purpose,
            "risk": self.risk,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "backup_path": self.backup_path,
            "content_before": before_preview if include_full else before_preview,
            "content_after": after_preview if include_full else after_preview,
            "content_before_len": len(self.content_before or ""),
            "content_after_len": len(self.content_after or ""),
            "patch_old": self.patch_old,
            "patch_new": self.patch_new,
            "expected_hash": self.expected_hash or _sha256_text(self.content_after),
            "result_hash": self.result_hash,
            "error": self.error,
            "in_trust_zone": self.in_trust_zone,
            "requires_strong": self.requires_strong,
            "file_exists": self.content_before is not None,
            "diff_summary": self._diff_summary(),
        }

    def _diff_summary(self) -> dict[str, Any]:
        b = self.content_before or ""
        a = self.content_after or ""
        return {
            "lines_before": b.count("\n") + (1 if b else 0),
            "lines_after": a.count("\n") + (1 if a else 0),
            "chars_before": len(b),
            "chars_after": len(a),
            "changed": b != a,
            "kind": self.kind.value,
        }


class WriteService:
    """
    In-memory proposal queue + on-disk file snapshots under backup_dir/file_snaps.
    """

    MAX_CONTENT = 500_000

    def __init__(
        self,
        settings: Settings,
        path_guard: PathGuard,
        privileges: PrivilegeService,
        *,
        audit: Callable[[str, str, dict[str, Any]], None] | None = None,
    ):
        self.settings = settings
        self.path_guard = path_guard
        self.privileges = privileges
        self.audit = audit or (lambda *_a, **_k: None)
        self._lock = threading.RLock()
        self._proposals: dict[str, WriteProposal] = {}
        self.snap_dir = Path(settings.backup_dir) / "file_snaps"
        self.snap_dir.mkdir(parents=True, exist_ok=True)

    def list_proposals(
        self, user_id: int | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._proposals.values())
        if user_id is not None:
            items = [p for p in items if p.user_id == user_id]
        if status:
            items = [p for p in items if p.status.value == status]
        items.sort(key=lambda p: p.created_at, reverse=True)
        return [p.to_public(include_full=False) for p in items]

    def get(self, proposal_id: str) -> WriteProposal | None:
        with self._lock:
            return self._proposals.get(proposal_id)

    def _resolve_write_path(self, path: str) -> Path:
        # Write access: resolve with for_read=False still checks allowlist
        decision = self.path_guard.resolve(path, for_read=True)
        if not decision.allowed or not decision.path:
            raise PermissionError(decision.reason or "Path non autorizzato")
        target = decision.path
        # Extension / sensitive name checks already in path_guard for files
        return target

    def _assert_writable_mode(self, effective: PrivilegeLevel) -> None:
        mode = self.settings.security_mode
        if mode == "locked":
            raise PermissionError("Modalità locked: nessuna scrittura")
        if mode == "read_only" and effective < PrivilegeLevel.ADMINISTRATOR:
            raise PermissionError(
                "Modalità read_only: eleva ad ADMINISTRATOR per scritture supervisionate"
            )
        if effective < PrivilegeLevel.ADMINISTRATOR:
            raise PermissionError(
                "Serve livello ADMINISTRATOR (elevazione temporanea dalla console)"
            )

    def propose(
        self,
        *,
        user_id: int,
        actor: str,
        path: str,
        content: str | None = None,
        kind: str = "replace",
        old_text: str | None = None,
        new_text: str | None = None,
        purpose: str = "",
        role: str = "user",
    ) -> dict[str, Any]:
        if len(content or "") > self.MAX_CONTENT or len(new_text or "") > self.MAX_CONTENT:
            raise ValueError(f"Contenuto oltre {self.MAX_CONTENT} caratteri")

        target = self._resolve_write_path(path)
        # Block writing outside allowlist already done; prefer trust zones for lower friction
        in_zone = self.privileges.path_in_trust_zone(target)
        effective = self.privileges.effective_level(role, user_id)
        # Proposing requires at least OPERATOR (can draft); apply needs ADMIN
        if effective < PrivilegeLevel.OPERATOR and role not in {"owner", "admin", "operator"}:
            # Owner is already ADMIN base; plain user can propose only if elevated to OPERATOR+
            if effective < PrivilegeLevel.OPERATOR:
                raise PermissionError(
                    "Per proporre scritture serve almeno OPERATOR (eleva i privilegi)"
                )

        exists = target.exists() and target.is_file()
        before: str | None = None
        if exists:
            try:
                before = target.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise PermissionError(f"Impossibile leggere file attuale: {exc}") from exc

        kind_e = ProposalKind(kind)
        if kind_e == ProposalKind.CREATE:
            if exists:
                raise ValueError("File già esistente: usa replace o patch")
            if content is None:
                raise ValueError("content obbligatorio per create")
            after = content
        elif kind_e == ProposalKind.REPLACE:
            if content is None:
                raise ValueError("content obbligatorio per replace")
            after = content
            if not exists:
                kind_e = ProposalKind.CREATE
        elif kind_e == ProposalKind.PATCH:
            if before is None:
                raise ValueError("Patch richiede un file esistente")
            if not old_text:
                raise ValueError("patch richiede old_text")
            if new_text is None:
                raise ValueError("patch richiede new_text")
            if old_text not in before:
                raise ValueError("old_text non trovato nel file (patch non applicabile)")
            count = before.count(old_text)
            if count != 1:
                raise ValueError(
                    f"old_text compare {count} volte: la patch deve essere univoca"
                )
            after = before.replace(old_text, new_text, 1)
        else:
            raise ValueError(f"kind non supportato: {kind}")

        if before is not None and before == after:
            raise ValueError("Nessuna modifica: contenuto identico")

        # Parent for create must exist or be creatable under allowlist
        if kind_e == ProposalKind.CREATE:
            parent = target.parent
            if not parent.exists():
                # only allow single-level create under existing parent in allowlist
                if not parent.parent.exists():
                    raise ValueError("Directory padre assente: crea prima la cartella manualmente")
                # We'll create parent only if under allowlist
                pdec = self.path_guard.resolve(str(parent), for_read=True)
                if not pdec.allowed:
                    raise PermissionError("Directory padre non autorizzata")

        prop = WriteProposal(
            id=secrets.token_hex(8),
            user_id=user_id,
            actor=actor,
            path=str(target),
            kind=kind_e,
            content_before=before,
            content_after=after,
            patch_old=old_text,
            patch_new=new_text,
            purpose=purpose or f"{kind_e.value} {target.name}",
            risk="medium" if in_zone else "high",
            expected_hash=_sha256_text(after),
            in_trust_zone=in_zone,
            requires_strong=not in_zone,
        )
        with self._lock:
            self._proposals[prop.id] = prop

        self.audit(
            "write_proposed",
            actor,
            redact_obj(
                {
                    "proposal_id": prop.id,
                    "path": prop.path,
                    "kind": prop.kind.value,
                    "user_id": user_id,
                    "in_trust_zone": in_zone,
                    "diff": prop._diff_summary(),
                }
            ),
        )
        return prop.to_public(include_full=True)

    def reject(self, proposal_id: str, *, actor: str, user_id: int) -> dict[str, Any]:
        prop = self.get(proposal_id)
        if not prop:
            raise KeyError("Proposta non trovata")
        if prop.user_id != user_id:
            raise PermissionError("Non puoi rifiutare una proposta di un altro utente")
        if prop.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposta non pending (stato={prop.status.value})")
        prop.status = ProposalStatus.REJECTED
        prop.decided_at = _now().isoformat()
        self.audit(
            "write_rejected",
            actor,
            {"proposal_id": proposal_id, "path": prop.path, "user_id": user_id},
        )
        return prop.to_public(include_full=False)

    def _snapshot_file(self, path: Path, proposal_id: str) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        dest = self.snap_dir / f"{proposal_id}_{path.name}.bak"
        shutil.copy2(path, dest)
        return str(dest)

    def approve(
        self,
        proposal_id: str,
        *,
        actor: str,
        user_id: int,
        role: str,
        confirm: bool = False,
        strong_confirmation: str = "",
    ) -> dict[str, Any]:
        prop = self.get(proposal_id)
        if not prop:
            raise KeyError("Proposta non trovata")
        if prop.user_id != user_id:
            raise PermissionError("Non puoi approvare una proposta di un altro utente")
        if prop.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposta non pending (stato={prop.status.value})")

        effective = self.privileges.effective_level(role, user_id)
        self._assert_writable_mode(effective)

        if not confirm:
            raise PermissionError("Serve confirm=true per approvare la scrittura")

        if prop.requires_strong or not prop.in_trust_zone:
            phrase = self.privileges.strong_phrase
            if strong_confirmation.strip() != phrase:
                raise PermissionError(
                    f"Fuori trust zone: digita esattamente la frase forte: {phrase}"
                )

        # Path re-check at apply time
        target = self._resolve_write_path(prop.path)
        elev = self.privileges.get_elevation(user_id)
        if elev and elev.scope_path:
            try:
                scope = Path(elev.scope_path).expanduser().resolve()
                target.resolve().relative_to(scope)
            except (ValueError, OSError) as exc:
                raise PermissionError(
                    "Path fuori dallo scope dell'elevazione temporanea"
                ) from exc

        # Backup
        backup = self._snapshot_file(target, prop.id)
        prop.backup_path = backup

        try:
            if prop.kind == ProposalKind.CREATE:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise RuntimeError("File creato nel frattempo: abort")
            # Atomic-ish write (bytes = exact content, no newline translation)
            tmp = target.with_name(target.name + f".tauros_tmp_{prop.id}")
            payload = prop.content_after.encode("utf-8")
            tmp.write_bytes(payload)
            tmp.replace(target)

            # Verify
            written_bytes = target.read_bytes()
            written = written_bytes.decode("utf-8")
            got = _sha256_text(written)
            exp = prop.expected_hash or _sha256_text(prop.content_after)
            if got != exp:
                raise RuntimeError(
                    f"Verifica hash fallita: atteso {exp[:12]}… ottenuto {got[:12]}…"
                )
            prop.result_hash = got
            prop.status = ProposalStatus.APPLIED
            prop.decided_at = _now().isoformat()
            prop.error = None
        except Exception as exc:  # noqa: BLE001
            prop.error = str(exc)
            prop.status = ProposalStatus.FAILED
            prop.decided_at = _now().isoformat()
            # Rollback
            if backup and Path(backup).exists():
                try:
                    shutil.copy2(backup, target)
                    prop.status = ProposalStatus.ROLLED_BACK
                except OSError as rb_exc:
                    prop.error = f"{exc}; rollback fallito: {rb_exc}"
            elif prop.kind == ProposalKind.CREATE and target.exists():
                try:
                    target.unlink()
                    prop.status = ProposalStatus.ROLLED_BACK
                except OSError:
                    pass
            self.audit(
                "write_failed",
                actor,
                redact_obj(
                    {
                        "proposal_id": prop.id,
                        "path": prop.path,
                        "error": prop.error,
                        "backup_path": backup,
                        "status": prop.status.value,
                    }
                ),
            )
            raise RuntimeError(prop.error) from exc

        self.privileges.mark_single_op_used(user_id)
        self.audit(
            "write_applied",
            actor,
            redact_obj(
                {
                    "proposal_id": prop.id,
                    "path": prop.path,
                    "kind": prop.kind.value,
                    "backup_path": backup,
                    "result_hash": prop.result_hash,
                    "user_id": user_id,
                    "role": role,
                    "effective_level": effective.name,
                    "in_trust_zone": prop.in_trust_zone,
                }
            ),
        )
        return prop.to_public(include_full=True)

    def restore_backup(
        self,
        *,
        path: str,
        backup_path: str,
        user_id: int,
        actor: str,
        role: str,
        strong_confirmation: str,
    ) -> dict[str, Any]:
        effective = self.privileges.effective_level(role, user_id)
        self._assert_writable_mode(effective)
        if strong_confirmation.strip() != self.privileges.strong_phrase:
            raise PermissionError(
                f"Ripristino richiede frase forte: {self.privileges.strong_phrase}"
            )
        target = self._resolve_write_path(path)
        src = Path(backup_path)
        # Backup must live under our snap dir
        try:
            src.resolve().relative_to(self.snap_dir.resolve())
        except ValueError as exc:
            raise PermissionError("Backup path non valido (fuori file_snaps)") from exc
        if not src.is_file():
            raise FileNotFoundError("Backup non trovato")
        pre = self._snapshot_file(target, f"restore_{secrets.token_hex(4)}")
        shutil.copy2(src, target)
        self.audit(
            "write_restored",
            actor,
            {
                "path": str(target),
                "from_backup": str(src),
                "pre_restore_backup": pre,
                "user_id": user_id,
            },
        )
        return {
            "ok": True,
            "path": str(target),
            "restored_from": str(src),
            "pre_restore_backup": pre,
        }

    def snapshot(
        self, path: str, *, user_id: int, actor: str, role: str
    ) -> dict[str, Any]:
        effective = self.privileges.effective_level(role, user_id)
        if effective < PrivilegeLevel.OPERATOR:
            raise PermissionError("Snapshot richiede almeno OPERATOR")
        target = self._resolve_write_path(path)
        if not target.is_file():
            raise FileNotFoundError(f"File non trovato: {target}")
        snap_id = secrets.token_hex(6)
        dest = self._snapshot_file(target, snap_id)
        self.audit(
            "file_snapshot",
            actor,
            {"path": str(target), "backup_path": dest, "user_id": user_id},
        )
        return {"ok": True, "path": str(target), "backup_path": dest, "snapshot_id": snap_id}
