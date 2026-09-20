"""v0.4.1 supervised writes + elevation gates."""

from pathlib import Path

import pytest

from tauros.privileges import PrivilegeLevel, PrivilegeService
from tauros.security import generate_api_token
from tauros.settings import Settings
from tauros.writes import WriteService
from tauros.policy import PolicyEngine
from tauros.tools import ToolRegistry


def _stack(tmp_path: Path, *, mode: str = "read_only"):
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        workspace_allowlist=str(ws),
        trust_zones=str(ws),
        security_mode=mode,
        database_path=tmp_path / "w.db",
        backup_dir=tmp_path / "backups",
    )
    priv = PrivilegeService.from_settings(settings)
    policy = PolicyEngine(settings, privileges=priv)
    audit: list[tuple[str, dict]] = []

    def _audit(event, actor, details):
        audit.append((event, details))

    writes = WriteService(settings, policy.path_guard, priv, audit=_audit)
    tools = ToolRegistry(policy, settings, policy.path_guard, writes=writes)
    return ws, settings, priv, policy, writes, tools, audit


def test_propose_does_not_write_disk(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    target = ws / "note.md"
    prop = writes.propose(
        user_id=1,
        actor="owner",
        path=str(target),
        content="hello supervised",
        kind="create",
        purpose="test",
        role="owner",
    )
    assert prop["status"] == "pending"
    assert not target.exists()
    assert any(e == "write_proposed" for e, _ in audit)


def test_approve_create_with_owner(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    target = ws / "created.md"
    prop = writes.propose(
        user_id=1,
        actor="owner",
        path=str(target),
        content="line1\n",
        kind="create",
        role="owner",
    )
    applied = writes.approve(
        prop["id"],
        actor="owner",
        user_id=1,
        role="owner",
        confirm=True,
        strong_confirmation="",  # trust zone
    )
    assert applied["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "line1\n"
    assert any(e == "write_applied" for e, _ in audit)


def test_approve_replace_with_backup_and_patch(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    target = ws / "edit.md"
    target.write_text("alpha beta gamma", encoding="utf-8")
    prop = writes.propose(
        user_id=1,
        actor="owner",
        path=str(target),
        kind="patch",
        old_text="beta",
        new_text="BETA",
        role="owner",
    )
    assert "alpha BETA gamma" in prop["content_after"]
    applied = writes.approve(
        prop["id"],
        actor="owner",
        user_id=1,
        role="owner",
        confirm=True,
    )
    assert applied["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "alpha BETA gamma"
    assert applied["backup_path"]
    assert Path(applied["backup_path"]).is_file()


def test_operator_needs_elevation_to_approve(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    target = ws / "x.md"
    prop = writes.propose(
        user_id=9,
        actor="op",
        path=str(target),
        content="x",
        kind="create",
        role="operator",
    )
    with pytest.raises(PermissionError, match="ADMINISTRATOR"):
        writes.approve(
            prop["id"],
            actor="op",
            user_id=9,
            role="operator",
            confirm=True,
        )
    priv.elevate(
        user_id=9,
        role="operator",
        target=PrivilegeLevel.ADMINISTRATOR,
        strong_confirmation="CONFERMO ADMIN",
        minutes=10,
        reason="test write",
        single_operation=True,
    )
    applied = writes.approve(
        prop["id"],
        actor="op",
        user_id=9,
        role="operator",
        confirm=True,
    )
    assert applied["status"] == "applied"
    # single op consumed
    assert priv.get_elevation(9) is None


def test_outside_trust_zone_needs_strong_phrase(tmp_path: Path):
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    outside.mkdir()
    ws.mkdir()
    # allow both but trust only ws
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        workspace_allowlist=f"{ws};{outside}",
        trust_zones=str(ws),
        security_mode="read_only",
        database_path=tmp_path / "w.db",
        backup_dir=tmp_path / "backups",
    )
    priv = PrivilegeService.from_settings(settings)
    policy = PolicyEngine(settings, privileges=priv)
    writes = WriteService(settings, policy.path_guard, priv)
    target = outside / "secret.md"
    prop = writes.propose(
        user_id=1,
        actor="owner",
        path=str(target),
        content="nope",
        kind="create",
        role="owner",
    )
    assert prop["requires_strong"] is True
    with pytest.raises(PermissionError, match="frase forte"):
        writes.approve(
            prop["id"],
            actor="owner",
            user_id=1,
            role="owner",
            confirm=True,
            strong_confirmation="sbagliato",
        )
    applied = writes.approve(
        prop["id"],
        actor="owner",
        user_id=1,
        role="owner",
        confirm=True,
        strong_confirmation="CONFERMO ADMIN",
    )
    assert applied["status"] == "applied"


def test_tool_propose_write_via_registry(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    out = tools.execute(
        "propose_write",
        {
            "path": str(ws / "via_tool.md"),
            "content": "from tool",
            "kind": "create",
            "_role": "operator",
            "_user_id": 3,
            "_actor": "test",
        },
    )
    assert out["success"], out.get("error")
    assert out["data"]["status"] == "pending"
    assert not (ws / "via_tool.md").exists()


def test_reject_proposal(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    prop = writes.propose(
        user_id=1,
        actor="owner",
        path=str(ws / "r.md"),
        content="x",
        kind="create",
        role="owner",
    )
    rejected = writes.reject(prop["id"], actor="owner", user_id=1)
    assert rejected["status"] == "rejected"
    with pytest.raises(ValueError):
        writes.approve(prop["id"], actor="owner", user_id=1, role="owner", confirm=True)


def test_restore_from_backup(tmp_path: Path):
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    target = ws / "snap.md"
    target.write_text("v1", encoding="utf-8")
    snap = writes.snapshot(str(target), user_id=1, actor="owner", role="owner")
    target.write_text("v2", encoding="utf-8")
    restored = writes.restore_backup(
        path=str(target),
        backup_path=snap["backup_path"],
        user_id=1,
        actor="owner",
        role="owner",
        strong_confirmation="CONFERMO ADMIN",
    )
    assert restored["ok"]
    assert target.read_text(encoding="utf-8") == "v1"


def test_user_cannot_approve_other_users_proposal(tmp_path: Path):
    """User A must not apply user B's pending proposal, even with owner privileges."""
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    target = ws / "owned_by_b.md"
    prop = writes.propose(
        user_id=2,
        actor="bob",
        path=str(target),
        content="only bob",
        kind="create",
        role="owner",
    )
    with pytest.raises(PermissionError):
        writes.approve(
            prop["id"],
            actor="alice",
            user_id=1,
            role="owner",
            confirm=True,
        )
    leftover = writes.get(prop["id"])
    assert leftover is not None
    assert leftover.status.value == "pending"
    assert leftover.user_id == 2
    assert not target.exists()


def test_user_cannot_reject_other_users_proposal(tmp_path: Path):
    """User A must not reject user B's pending proposal."""
    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    prop = writes.propose(
        user_id=2,
        actor="bob",
        path=str(ws / "owned_by_b.md"),
        content="only bob",
        kind="create",
        role="owner",
    )
    with pytest.raises(PermissionError):
        writes.reject(prop["id"], actor="alice", user_id=1)
    leftover = writes.get(prop["id"])
    assert leftover is not None
    assert leftover.status.value == "pending"
    assert leftover.user_id == 2


def test_approve_valueerror_returns_http_400_not_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ValueError from approve (e.g. already rejected) must map to HTTP 400, never NameError/500."""
    from fastapi import HTTPException

    from tauros.auth import AuthUser
    from tauros.models import WriteApproveRequest
    import tauros.api as api_mod

    ws, settings, priv, policy, writes, tools, audit = _stack(tmp_path)
    prop = writes.propose(
        user_id=1,
        actor="alice",
        path=str(ws / "once.md"),
        content="x",
        kind="create",
        role="owner",
    )
    writes.reject(prop["id"], actor="alice", user_id=1)
    monkeypatch.setattr(api_mod, "writes", writes)
    user = AuthUser(
        id=1,
        username="alice",
        is_guest=False,
        is_operator=False,
        message_count=0,
        max_messages=None,
        role="owner",
    )
    with pytest.raises(HTTPException) as raised:
        api_mod.approve_write(
            prop["id"],
            WriteApproveRequest(confirm=True, strong_confirmation=""),
            user,
        )
    assert raised.value.status_code == 400


def test_plan_validator_blocks_direct_write_in_propose_mode():
    from tauros.plan_models import PlanStep, StructuredPlan
    from tauros.plan_validator import PlanValidator

    v = PlanValidator(
        allowed_tools={"write_file", "propose_write", "read_text_file"},
        max_steps=3,
    )
    plan = StructuredPlan(
        intent="bad",
        mode="propose_write",
        steps=[
            PlanStep(id="s1", tool="write_file", arguments={"path": "x"}, risk="medium")
        ],
    )
    res = v.validate(plan)
    assert not res.ok
    assert any(i.code == "write_in_readonly" for i in res.issues)
