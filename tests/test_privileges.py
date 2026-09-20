from pathlib import Path

import pytest

from tauros.privileges import (
    ConfirmationLevel,
    PrivilegeLevel,
    PrivilegeService,
)
from tauros.policy import PolicyEngine
from tauros.security import generate_api_token
from tauros.settings import Settings


def test_owner_base_is_administrator():
    svc = PrivilegeService()
    assert svc.base_level_for_role("owner") == PrivilegeLevel.ADMINISTRATOR
    assert svc.effective_level("owner", 1) == PrivilegeLevel.ADMINISTRATOR


def test_guest_cannot_elevate():
    svc = PrivilegeService()
    with pytest.raises(PermissionError):
        svc.elevate(
            user_id=9,
            role="guest",
            target=PrivilegeLevel.ADMINISTRATOR,
            strong_confirmation="CONFERMO ADMIN",
        )


def test_elevation_requires_strong_phrase_and_expires():
    svc = PrivilegeService(default_elevation_minutes=15)
    with pytest.raises(PermissionError):
        svc.elevate(
            user_id=1,
            role="owner",
            target=PrivilegeLevel.CONTROLLED_ROOT,
            strong_confirmation="sbagliato",
        )
    session = svc.elevate(
        user_id=1,
        role="owner",
        target=PrivilegeLevel.CONTROLLED_ROOT,
        minutes=15,
        strong_confirmation="CONFERMO ADMIN",
        reason="manutenzione",
    )
    assert session.active()
    assert svc.effective_level("owner", 1) == PrivilegeLevel.CONTROLLED_ROOT
    assert svc.revoke(1) is True
    assert svc.effective_level("owner", 1) == PrivilegeLevel.ADMINISTRATOR


def test_user_denied_write_admin_can_with_confirmation(tmp_path: Path):
    ws = tmp_path / "core"
    ws.mkdir()
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        workspace_allowlist=str(ws),
        trust_zones=str(ws),
        security_mode="read_only",
        database_path=tmp_path / "p.db",
    )
    policy = PolicyEngine(settings)

    d_user = policy.authorize_tool(
        "write_file",
        {"path": str(ws / "a.md")},
        role="user",
        user_id=2,
    )
    assert not d_user.allowed

    # Owner has ADMINISTRATOR base — write is important; needs SIMPLE confirm outside pure routine
    d_admin = policy.authorize_tool(
        "write_file",
        {"path": str(ws / "a.md")},
        role="owner",
        user_id=1,
        confirmed=None,
    )
    # In trust zone + admin → confirmation NONE for IMPORTANT
    assert d_admin.allowed, d_admin.reason


def test_destructive_always_needs_preview(tmp_path: Path):
    svc = PrivilegeService()
    svc.elevate(
        user_id=1,
        role="owner",
        target=PrivilegeLevel.CONTROLLED_ROOT,
        strong_confirmation="CONFERMO ADMIN",
    )
    d = svc.authorize_tool(
        tool="mass_delete",
        role="owner",
        user_id=1,
        confirmed=None,
    )
    assert not d.allowed
    assert d.confirmation == ConfirmationLevel.PREVIEW_ROLLBACK
    d2 = svc.authorize_tool(
        tool="mass_delete",
        role="owner",
        user_id=1,
        confirmed=ConfirmationLevel.PREVIEW_ROLLBACK,
    )
    assert d2.allowed


def test_trust_zone_listed(tmp_path: Path):
    z = tmp_path / "TaurosCore"
    z.mkdir()
    svc = PrivilegeService(trust_zones=[z])
    assert svc.path_in_trust_zone(z / "x.py")
