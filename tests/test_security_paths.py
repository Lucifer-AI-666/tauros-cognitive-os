"""PathGuard barrier tests + simulated planner denial."""

from pathlib import Path

import pytest

from tauros.policy import PolicyEngine
from tauros.security import AccessLevel, PathGuard, generate_api_token, parse_path_list
from tauros.settings import Settings
from tauros.tools import ToolRegistry


def test_valid_nested_file_under_allowlist(tmp_path: Path):
    root = tmp_path / "Users" / "anouar" / "TaurosWorkspace"
    root.mkdir(parents=True)
    f = root / "docs" / "README.md"
    f.parent.mkdir(parents=True)
    f.write_text("# ok", encoding="utf-8")
    guard = PathGuard(allowlist=[root], require_allowlist=True)
    d = guard.resolve(str(f))
    assert d.allowed, d.reason
    assert d.allow_root is not None


def test_outside_and_dotdot_denied(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    assert not guard.resolve(str(outside)).allowed
    assert not guard.resolve(str(ws / ".." / "secret.txt")).allowed


def test_symlink_escape_and_internal(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "out.txt"
    outside.write_text("secret", encoding="utf-8")
    internal = ws / "in.md"
    internal.write_text("ok", encoding="utf-8")
    escape = ws / "escape.txt"
    alias = ws / "alias.md"
    try:
        escape.symlink_to(outside)
        alias.symlink_to(internal)
    except OSError:
        pytest.skip("symlink non supportati")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    assert not guard.resolve(str(escape)).allowed
    assert guard.resolve(str(alias)).allowed


def test_env_default_deny_unknown_ext_binary(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".env").write_text("K=v", encoding="utf-8")
    (ws / ".env.example").write_text("K=", encoding="utf-8")
    (ws / "x.xyz").write_text("no", encoding="utf-8")
    (ws / "fake.txt").write_bytes(b"\x00\xff binary")
    guard = PathGuard(allowlist=[ws], require_allowlist=True, max_file_bytes=100)
    assert not guard.resolve(str(ws / ".env")).allowed
    assert guard.resolve(str(ws / ".env.example")).allowed
    assert not guard.resolve(str(ws / "x.xyz")).allowed
    with pytest.raises(PermissionError, match="binario"):
        guard.open_text_verified(str(ws / "fake.txt"))


def test_component_forbidden_not_false_positive(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ok = ws / "tokenization notes.md"
    ok.write_text("ok", encoding="utf-8")
    ssh = ws / ".ssh" / "config"
    ssh.parent.mkdir()
    ssh.write_text("Host *", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    assert guard.resolve(str(ok)).allowed
    assert not guard.resolve(str(ssh)).allowed


def test_parse_path_list_no_comma_mangling(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b,with,comma"
    a.mkdir()
    b.mkdir()
    paths = parse_path_list(f'["{a.as_posix()}", "{b.as_posix()}"]')
    assert len(paths) == 2
    assert len(parse_path_list(f"{a}\n{b}")) == 2
    assert len(parse_path_list(f"{a};{b}")) == 2


def test_simulated_planner_denied_outside_file_is_auditable(tmp_path: Path):
    """Planner proposes read outside allowlist → policy denies → tool does not open."""
    ws = tmp_path / "TaurosWorkspace"
    ws.mkdir()
    outside = tmp_path / "passwd_copy.txt"
    outside.write_text("should-not-be-read", encoding="utf-8")

    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        workspace_allowlist=str(ws),
        security_mode="read_only",
        database_path=tmp_path / "x.db",
    )
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)

    # Simulated plan step
    plan_step = {
        "tool": "read_text_file",
        "arguments": {"path": str(outside)},
        "risk": "low",
    }
    decision = policy.authorize_tool(plan_step["tool"], plan_step["arguments"])
    assert not decision.allowed
    assert decision.path_decision is not None
    assert decision.path_decision["rule"] == "outside_allowlist"

    result = tools.execute(plan_step["tool"], plan_step["arguments"])
    assert result["success"] is False
    assert result["policy"] == "blocked"
    assert result.get("data") is None
    # File never opened as content
    assert "should-not-be-read" not in str(result)


def test_access_level_list_only(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "a.md"
    f.write_text("x", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], max_access=AccessLevel.LIST)
    assert not guard.resolve(str(f), access=AccessLevel.READ).allowed
