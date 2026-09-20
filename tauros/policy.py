"""Policy engine: the model proposes, policy decides (role-aware)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .privileges import ConfirmationLevel, PrivilegeLevel, PrivilegeService
from .rules import RuleStore
from .security import AccessLevel, PathGuard
from .settings import Settings


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    risk: str = "low"
    path_decision: dict[str, Any] | None = None
    privilege: dict[str, Any] | None = None
    confirmation: str = "none"


class PolicyEngine:
    """
    Chain:
      1) privilege level / elevation / confirmation class
      2) PathGuard (workspace allowlist + trust zones)
      3) system locked mode still respected for non-elevated sessions
    """

    filesystem_tools = {
        "list_directory",
        "read_text_file",
        "disk_usage",
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
        "delete_file",
    }

    def __init__(
        self,
        settings: Settings,
        path_guard: PathGuard | None = None,
        privileges: PrivilegeService | None = None,
    ):
        self.settings = settings
        self.privileges = privileges or PrivilegeService.from_settings(settings)
        self.rules = RuleStore(Path(settings.rules_path))
        roots: list[Path] = []
        seen: set[str] = set()
        for p in list(settings.allowlist_paths()) + list(self.privileges.trust_zones):
            try:
                key = str(Path(p).expanduser().resolve())
            except OSError:
                key = str(p)
            if key not in seen:
                seen.add(key)
                roots.append(Path(p).expanduser())
        self.path_guard = path_guard or PathGuard(
            allowlist=roots,
            blocklist=settings.blocklist_paths(),
            max_file_bytes=settings.max_file_bytes,
            require_allowlist=True,
        )

    def authorize_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        role: str = "user",
        user_id: int = 0,
        confirmed: str | None = None,
    ) -> PolicyDecision:
        # Global system lock still blocks filesystem for non-admin effective levels
        mode = self.settings.security_mode
        effective = self.privileges.effective_level(role, user_id)
        if mode == "locked" and name in self.filesystem_tools:
            if effective < PrivilegeLevel.ADMINISTRATOR:
                return PolicyDecision(
                    False,
                    "Modalità sistema locked: eleva ad ADMINISTRATOR per sbloccare",
                    "medium",
                    confirmation=ConfirmationLevel.STRONG.value,
                )

        conf_enum: ConfirmationLevel | None = None
        if confirmed:
            try:
                conf_enum = ConfirmationLevel(confirmed)
            except ValueError:
                conf_enum = None

        path_value = arguments.get("path") or arguments.get("repo")
        path_obj = Path(str(path_value)).expanduser() if path_value else None

        hit = self.rules.evaluate(name, str(path_obj) if path_obj else None)
        if hit and hit.rule.effect == "deny":
            return PolicyDecision(False, hit.reason, "high", confirmation="none")

        priv = self.privileges.authorize_tool(
            tool=name,
            role=role,
            user_id=user_id,
            path=path_obj,
            confirmed=conf_enum,
        )
        if not priv.allowed:
            return PolicyDecision(
                False,
                priv.reason,
                priv.risk,
                privilege=priv.to_dict(),
                confirmation=priv.confirmation.value,
            )

        if name in self.filesystem_tools or path_value:
            if path_value:
                level = AccessLevel.LIST if name == "list_directory" else AccessLevel.READ
                decision = self.path_guard.resolve(
                    str(path_value), for_read=True, access=level
                )
                if not decision.allowed:
                    return PolicyDecision(
                        False,
                        decision.reason,
                        decision.risk or "high",
                        path_decision=decision.to_dict(),
                        privilege=priv.to_dict(),
                        confirmation=priv.confirmation.value,
                    )
                confirm = (
                    ConfirmationLevel.SIMPLE.value
                    if hit and hit.rule.effect == "confirm"
                    else ConfirmationLevel.NONE.value
                )
                return PolicyDecision(
                    True,
                    hit.reason if hit and hit.rule.effect == "confirm" else priv.reason,
                    priv.risk,
                    path_decision=decision.to_dict(),
                    privilege=priv.to_dict(),
                    confirmation=confirm,
                )
            if name in {"list_directory", "read_text_file"} and not self.path_guard.allowlist:
                return PolicyDecision(
                    False, "Allowlist/trust zone vuota: filesystem negato", "high"
                )

        confirm = (
            ConfirmationLevel.SIMPLE.value
            if hit and hit.rule.effect == "confirm"
            else priv.confirmation.value
        )
        return PolicyDecision(
            True,
            hit.reason if hit and hit.rule.effect == "confirm" else priv.reason,
            priv.risk,
            privilege=priv.to_dict(),
            confirmation=confirm,
        )
