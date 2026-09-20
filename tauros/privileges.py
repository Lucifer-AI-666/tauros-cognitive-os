"""
Role-aware privileges: freedom with responsibility.

Not permanent god mode — temporary elevation, trust zones, graded confirmation.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

from .security import parse_path_list


class PrivilegeLevel(IntEnum):
    """Higher level = more capability, more responsibility."""

    BASE = 1  # chat, light read/search
    OPERATOR = 2  # full authorized read, index, git-style analysis
    ADMINISTRATOR = 3  # write proposals, config, backup/restore of TAUROS
    CONTROLLED_ROOT = 4  # high-risk ops — temporary unlock only


class ConfirmationLevel(str, Enum):
    NONE = "none"
    SIMPLE = "simple"  # click / short ack
    STRONG = "strong"  # typed phrase or re-auth
    PREVIEW_ROLLBACK = "preview_rollback"  # show plan + rollback before execute


class ActionClass(str, Enum):
    ROUTINE = "routine"
    IMPORTANT = "important"
    CRITICAL = "critical"
    DESTRUCTIVE = "destructive"


# Default ceiling for each account role (before temporary elevation).
ROLE_BASE_LEVEL: dict[str, PrivilegeLevel] = {
    "guest": PrivilegeLevel.BASE,
    "user": PrivilegeLevel.BASE,
    "operator": PrivilegeLevel.OPERATOR,
    "owner": PrivilegeLevel.ADMINISTRATOR,
    "admin": PrivilegeLevel.ADMINISTRATOR,
}

# Tools allowed at each level (cumulative: higher includes lower).
TOOLS_BY_LEVEL: dict[PrivilegeLevel, frozenset[str]] = {
    PrivilegeLevel.BASE: frozenset(
        {"system_info", "disk_usage", "memory_search", "list_directory", "read_text_file"}
    ),
    PrivilegeLevel.OPERATOR: frozenset(
        {
            "system_info",
            "disk_usage",
            "memory_search",
            "list_directory",
            "read_text_file",
            "workspace_search",
            "git_status",
            "git_log",
            "git_diff",
            "project_summary",
            "propose_write",
            "propose_patch",
            "file_snapshot",
        }
    ),
    PrivilegeLevel.ADMINISTRATOR: frozenset(
        {
            "system_info",
            "disk_usage",
            "memory_search",
            "list_directory",
            "read_text_file",
            "workspace_search",
            "git_status",
            "git_log",
            "git_diff",
            "project_summary",
            "propose_write",
            "propose_patch",
            "file_snapshot",
            "write_file",  # reserved — never direct from LLM; approve path only
            "file_restore",
            "tauros_backup",
            "tauros_restore",
            "tauros_migrate",
            "run_dev_command",
        }
    ),
    PrivilegeLevel.CONTROLLED_ROOT: frozenset(
        {
            "system_info",
            "disk_usage",
            "memory_search",
            "list_directory",
            "read_text_file",
            "workspace_search",
            "git_status",
            "git_log",
            "git_diff",
            "project_summary",
            "propose_write",
            "propose_patch",
            "file_snapshot",
            "write_file",
            "file_restore",
            "tauros_backup",
            "tauros_restore",
            "tauros_migrate",
            "run_dev_command",
            "run_shell",
            "install_package",
            "delete_file",
            "firewall_change",
            "boot_change",
            "credential_access",
            "network_exfil",
            "system_admin",
            "format_disk",
            "mass_delete",
            "drop_database",
            "wipe_workspace",
        }
    ),
}

# Always need strong / preview even for elevated admins.
ALWAYS_CRITICAL_TOOLS = frozenset(
    {
        "delete_file",
        "credential_access",
        "firewall_change",
        "boot_change",
        "network_exfil",
        "system_admin",
        "format_disk",
        "mass_delete",
    }
)

ALWAYS_DESTRUCTIVE_TOOLS = frozenset(
    {
        "format_disk",
        "mass_delete",
        "drop_database",
        "wipe_workspace",
    }
)

# Phrase required for STRONG confirmation elevation / critical ops.
DEFAULT_STRONG_PHRASE = "CONFERMO ADMIN"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ElevationSession:
    id: str
    user_id: int
    level: PrivilegeLevel
    expires_at: datetime
    scope_path: str | None = None  # optional project trust path
    single_operation: bool = False
    reason: str = ""
    consumed: bool = False

    def active(self) -> bool:
        if self.consumed and self.single_operation:
            return False
        return _now() < self.expires_at

    def to_public(self) -> dict[str, Any]:
        remaining = max(0, int((self.expires_at - _now()).total_seconds()))
        return {
            "id": self.id,
            "level": self.level.name,
            "level_value": int(self.level),
            "expires_at": self.expires_at.isoformat(),
            "seconds_remaining": remaining,
            "scope_path": self.scope_path,
            "single_operation": self.single_operation,
            "reason": self.reason,
            "active": self.active(),
        }


@dataclass
class PrivilegeDecision:
    allowed: bool
    reason: str
    risk: str = "low"
    confirmation: ConfirmationLevel = ConfirmationLevel.NONE
    action_class: ActionClass = ActionClass.ROUTINE
    effective_level: PrivilegeLevel = PrivilegeLevel.BASE
    requires_elevation_to: PrivilegeLevel | None = None
    in_trust_zone: bool = False
    path_decision: dict[str, Any] | None = None
    preview_required: bool = False
    rollback_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "confirmation": self.confirmation.value,
            "action_class": self.action_class.value,
            "effective_level": self.effective_level.name,
            "requires_elevation_to": (
                self.requires_elevation_to.name if self.requires_elevation_to else None
            ),
            "in_trust_zone": self.in_trust_zone,
            "path_decision": self.path_decision,
            "preview_required": self.preview_required,
            "rollback_hint": self.rollback_hint,
        }


@dataclass
class PrivilegeService:
    """In-memory elevation sessions + role defaults + trust zones."""

    trust_zones: list[Path] = field(default_factory=list)
    default_elevation_minutes: int = 15
    max_elevation_minutes: int = 60
    strong_phrase: str = DEFAULT_STRONG_PHRASE
    _elevations: dict[int, ElevationSession] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Any) -> PrivilegeService:
        zones = parse_path_list(getattr(settings, "trust_zones", "") or "")
        return cls(
            trust_zones=[z.expanduser().resolve() for z in zones],
            default_elevation_minutes=int(
                getattr(settings, "elevation_default_minutes", 15) or 15
            ),
            max_elevation_minutes=int(getattr(settings, "elevation_max_minutes", 60) or 60),
            strong_phrase=str(
                getattr(settings, "elevation_strong_phrase", DEFAULT_STRONG_PHRASE)
                or DEFAULT_STRONG_PHRASE
            ),
        )

    def base_level_for_role(self, role: str) -> PrivilegeLevel:
        return ROLE_BASE_LEVEL.get((role or "user").lower(), PrivilegeLevel.BASE)

    def get_elevation(self, user_id: int) -> ElevationSession | None:
        session = self._elevations.get(user_id)
        if not session:
            return None
        if not session.active():
            self._elevations.pop(user_id, None)
            return None
        return session

    def effective_level(self, role: str, user_id: int) -> PrivilegeLevel:
        base = self.base_level_for_role(role)
        elev = self.get_elevation(user_id)
        if elev and elev.level > base:
            return elev.level
        return base

    def elevate(
        self,
        *,
        user_id: int,
        role: str,
        target: PrivilegeLevel,
        minutes: int | None = None,
        strong_confirmation: str,
        reason: str = "",
        scope_path: str | None = None,
        single_operation: bool = False,
    ) -> ElevationSession:
        """
        Temporary elevation. Owner/admin can go to ADMINISTRATOR or CONTROLLED_ROOT.
        Requires strong confirmation phrase.
        """
        if strong_confirmation.strip() != self.strong_phrase:
            raise PermissionError(
                f"Conferma forte non valida. Digita esattamente: {self.strong_phrase}"
            )

        base = self.base_level_for_role(role)
        # Guests and plain users cannot elevate beyond operator without already being elevated path
        if role in {"guest", "user"} and target > PrivilegeLevel.OPERATOR:
            raise PermissionError("Questo account non può elevare a livello amministratore")
        if role in {"guest"}:
            raise PermissionError("Gli ospiti non possono elevare privilegi")

        if target < base:
            target = base

        if target > PrivilegeLevel.CONTROLLED_ROOT:
            target = PrivilegeLevel.CONTROLLED_ROOT

        # Only owner/admin may reach CONTROLLED_ROOT
        if target >= PrivilegeLevel.CONTROLLED_ROOT and role not in {
            "owner",
            "admin",
            "operator",
        }:
            raise PermissionError("CONTROLLED_ROOT riservato ad owner/admin/operator")

        mins = minutes if minutes is not None else self.default_elevation_minutes
        mins = max(1, min(int(mins), self.max_elevation_minutes))
        if single_operation:
            mins = max(mins, 5)

        session = ElevationSession(
            id=secrets.token_hex(8),
            user_id=user_id,
            level=target,
            expires_at=_now() + timedelta(minutes=mins),
            scope_path=scope_path,
            single_operation=single_operation,
            reason=reason or "elevazione amministrativa",
        )
        self._elevations[user_id] = session
        return session

    def revoke(self, user_id: int) -> bool:
        return self._elevations.pop(user_id, None) is not None

    def mark_single_op_used(self, user_id: int) -> None:
        session = self.get_elevation(user_id)
        if session and session.single_operation:
            session.consumed = True
            self._elevations.pop(user_id, None)

    def path_in_trust_zone(self, path: Path | None) -> bool:
        if path is None:
            return False
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return False
        for zone in self.trust_zones:
            try:
                resolved.relative_to(zone)
                return True
            except ValueError:
                if resolved == zone:
                    return True
        return False

    def classify_tool(self, tool: str) -> ActionClass:
        if tool in ALWAYS_DESTRUCTIVE_TOOLS:
            return ActionClass.DESTRUCTIVE
        if tool in ALWAYS_CRITICAL_TOOLS:
            return ActionClass.CRITICAL
        if tool in {"propose_write", "propose_patch", "file_snapshot"}:
            return ActionClass.ROUTINE  # draft / snapshot only; apply is separate API
        if tool.startswith("write_") or tool in {
            "write_file",
            "file_restore",
            "run_shell",
            "install_package",
            "tauros_restore",
        }:
            return ActionClass.IMPORTANT
        return ActionClass.ROUTINE

    def confirmation_for(
        self,
        action: ActionClass,
        *,
        effective: PrivilegeLevel,
        in_trust_zone: bool,
    ) -> ConfirmationLevel:
        if action == ActionClass.DESTRUCTIVE:
            return ConfirmationLevel.PREVIEW_ROLLBACK
        if action == ActionClass.CRITICAL:
            return ConfirmationLevel.STRONG
        if action == ActionClass.IMPORTANT:
            if effective >= PrivilegeLevel.ADMINISTRATOR and in_trust_zone:
                return ConfirmationLevel.NONE
            if effective >= PrivilegeLevel.ADMINISTRATOR:
                return ConfirmationLevel.SIMPLE
            return ConfirmationLevel.STRONG
        # routine
        return ConfirmationLevel.NONE

    def authorize_tool(
        self,
        *,
        tool: str,
        role: str,
        user_id: int,
        path: Path | None = None,
        confirmed: ConfirmationLevel | None = None,
    ) -> PrivilegeDecision:
        effective = self.effective_level(role, user_id)
        action = self.classify_tool(tool)
        in_zone = self.path_in_trust_zone(path) if path else False
        elev = self.get_elevation(user_id)
        if elev and elev.scope_path and path is not None:
            try:
                scope = Path(elev.scope_path).expanduser().resolve()
                path.relative_to(scope)
                in_zone = True
            except (ValueError, OSError):
                # path outside elevation scope — not automatic trust
                pass

        allowed_tools = TOOLS_BY_LEVEL.get(effective, TOOLS_BY_LEVEL[PrivilegeLevel.BASE])
        if tool not in allowed_tools:
            # Find minimum level that would allow
            need = None
            for level in PrivilegeLevel:
                if tool in TOOLS_BY_LEVEL[level]:
                    need = level
                    break
            return PrivilegeDecision(
                allowed=False,
                reason=(
                    f"Tool '{tool}' richiede livello {(need or PrivilegeLevel.ADMINISTRATOR).name}; "
                    f"attuale {effective.name}. Eleva i privilegi se sei autorizzato."
                ),
                risk="high",
                confirmation=ConfirmationLevel.STRONG,
                action_class=action,
                effective_level=effective,
                requires_elevation_to=need,
                in_trust_zone=in_zone,
            )

        conf = self.confirmation_for(action, effective=effective, in_trust_zone=in_zone)
        # If caller already provided adequate confirmation, allow
        if conf != ConfirmationLevel.NONE:
            order = [
                ConfirmationLevel.NONE,
                ConfirmationLevel.SIMPLE,
                ConfirmationLevel.STRONG,
                ConfirmationLevel.PREVIEW_ROLLBACK,
            ]
            if confirmed is None or order.index(confirmed) < order.index(conf):
                return PrivilegeDecision(
                    allowed=False,
                    reason=(
                        f"Azione {action.value}: serve conferma '{conf.value}' "
                        f"(livello {effective.name}"
                        + (", zona di fiducia" if in_zone else "")
                        + ")"
                    ),
                    risk="high" if action in {ActionClass.CRITICAL, ActionClass.DESTRUCTIVE} else "medium",
                    confirmation=conf,
                    action_class=action,
                    effective_level=effective,
                    in_trust_zone=in_zone,
                    preview_required=conf == ConfirmationLevel.PREVIEW_ROLLBACK,
                    rollback_hint=(
                        "Prepara backup/snapshot prima dell'esecuzione"
                        if conf == ConfirmationLevel.PREVIEW_ROLLBACK
                        else None
                    ),
                )

        return PrivilegeDecision(
            allowed=True,
            reason=f"Consentito a livello {effective.name}"
            + (" (zona di fiducia)" if in_zone else ""),
            risk="low" if action == ActionClass.ROUTINE else "medium",
            confirmation=ConfirmationLevel.NONE,
            action_class=action,
            effective_level=effective,
            in_trust_zone=in_zone,
        )

    def status(self, role: str, user_id: int) -> dict[str, Any]:
        elev = self.get_elevation(user_id)
        effective = self.effective_level(role, user_id)
        return {
            "role": role,
            "base_level": self.base_level_for_role(role).name,
            "effective_level": effective.name,
            "effective_level_value": int(effective),
            "elevation": elev.to_public() if elev else None,
            "trust_zones": [str(z) for z in self.trust_zones],
            "tools_available": sorted(TOOLS_BY_LEVEL[effective]),
            "strong_phrase_hint": "CONFERMO ADMIN (frase configurabile)",
            "philosophy": (
                "Più potere → più responsabilità. "
                "Niente god mode permanente. Elevazione temporanea e audit."
            ),
        }
