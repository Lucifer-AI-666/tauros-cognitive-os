import logging
from pathlib import Path

import pytest

from tauros.database import Database
from tauros.memory import MemoryManager
from tauros.migrations import current_schema_version, run_migrations
from tauros.models import MemoryCreate
from tauros.policy import PolicyEngine
from tauros.security import (
    PathGuard,
    assert_strong_token,
    generate_api_token,
    is_weak_token,
    redact_obj,
    redact_text,
)
from tauros.settings import Settings
from tauros.tools import ToolRegistry


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "api_token": generate_api_token(),
        "skip_token_check": True,
        "database_path": tmp_path / "sec.db",
        "workspace_allowlist": str(tmp_path / "workspace"),
        "security_mode": "read_only",
        "host": "127.0.0.1",
        "allow_lan_bind": False,
        "max_file_bytes": 1024,
    }
    base.update(kwargs)
    return Settings(**base)


def test_weak_token_rejected():
    assert is_weak_token("change-me-now")
    assert is_weak_token("short")
    assert is_weak_token("")
    with pytest.raises(Exception):
        assert_strong_token("change-me-now")
    token = generate_api_token()
    assert not is_weak_token(token)
    assert_strong_token(token)


def test_lan_bind_requires_explicit_flag():
    with pytest.raises(Exception):
        Settings(
            api_token=generate_api_token(),
            host="0.0.0.0",
            allow_lan_bind=False,
            skip_token_check=True,
        )
    s = Settings(
        api_token=generate_api_token(),
        host="0.0.0.0",
        allow_lan_bind=True,
        skip_token_check=True,
    )
    assert s.allow_lan_bind is True


def test_path_traversal_blocked(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    guard = PathGuard(allowlist=[workspace], require_allowlist=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    decision = guard.resolve(str(outside))
    assert not decision.allowed
    # traversal style
    decision2 = guard.resolve(str(workspace / ".." / "secret.txt"))
    assert not decision2.allowed


def test_symlink_escape_blocked(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink non consentiti su questo ambiente Windows")
    guard = PathGuard(allowlist=[workspace], require_allowlist=True)
    decision = guard.resolve(str(link))
    assert not decision.allowed


def test_env_and_large_file_blocked(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = workspace / ".env"
    env.write_text("TAUROS_API_TOKEN=super-secret-value-here", encoding="utf-8")
    big = workspace / "notes.md"
    big.write_text("x" * 5000, encoding="utf-8")
    guard = PathGuard(allowlist=[workspace], max_file_bytes=100, require_allowlist=True)
    assert not guard.resolve(str(env)).allowed
    assert not guard.resolve(str(big)).allowed


def test_locked_mode_blocks_filesystem(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    settings = _settings(tmp_path, security_mode="locked", workspace_allowlist=str(ws))
    policy = PolicyEngine(settings)
    decision = policy.authorize_tool("list_directory", {"path": str(ws)})
    assert not decision.allowed


def test_unknown_tool_blocked(tmp_path: Path):
    settings = _settings(tmp_path)
    policy = PolicyEngine(settings)
    decision = policy.authorize_tool("run_shell", {"cmd": "whoami"})
    assert not decision.allowed
    decision2 = policy.authorize_tool("totally_unknown", {})
    assert not decision2.allowed


def test_secret_redaction():
    text = "Authorization: Bearer abcdef123456 and TAUROS_API_TOKEN=super-secret-token-value"
    red = redact_text(text)
    assert "abcdef123456" not in red
    assert "super-secret-token-value" not in red
    assert "[REDACTED]" in red
    obj = redact_obj({"api_token": "xyz", "nested": {"password": "p"}})
    assert obj["api_token"] == "[REDACTED]"
    assert obj["nested"]["password"] == "[REDACTED]"


def test_tool_limits_same_tool(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    settings = _settings(tmp_path, workspace_allowlist=str(ws), max_same_tool_calls=2)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    tools.reset_turn_limits()
    r1 = tools.execute("system_info", {})
    r2 = tools.execute("system_info", {})
    r3 = tools.execute("system_info", {})
    assert r1["success"] is True
    assert r2["success"] is True
    assert r3["success"] is False
    assert "Limite" in (r3.get("error") or "")


def test_migrations_and_backup(tmp_path: Path):
    db_path = tmp_path / "mig.db"
    result = run_migrations(db_path, backup=True)
    assert result.integrity_ok
    versions = current_schema_version(db_path)
    assert "001_initial" in versions
    assert "002_live_memory" in versions
    assert "003_hardening" in versions
    # second run is no-op
    result2 = run_migrations(db_path, backup=True)
    assert result2.applied == []


def test_candidate_not_truth_and_hash_dedup(tmp_path: Path):
    db = Database(tmp_path / "m.db")
    mm = MemoryManager(db)
    a = mm.soft_save_candidates("Ricorda che uso un Pixel")
    b = mm.soft_save_candidates("Ricorda che uso un Pixel")
    assert a and not b  # dedup
    assert mm.recall("Pixel") == []


def test_read_outside_allowlist_via_tool(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    secret = tmp_path / "nope.txt"
    secret.write_text("top secret", encoding="utf-8")
    settings = _settings(tmp_path, workspace_allowlist=str(ws))
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    result = tools.execute("read_text_file", {"path": str(secret)})
    assert result["success"] is False


def test_build_provider_groq():
    from tauros.providers import OpenAICompatibleProvider, ProviderError, build_provider

    s = Settings(
        provider="groq",
        model="llama-3.3-70b-versatile",
        groq_api_key="gsk_test_key_not_real_123456",
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
    )
    p = build_provider(s)
    from tauros.providers import FallbackProvider, OllamaProvider

    assert isinstance(p, FallbackProvider)
    assert isinstance(p.primary, OpenAICompatibleProvider)
    assert p.primary.provider_name == "groq"
    assert "groq.com" in p.primary.base_url
    assert isinstance(p.secondary, OllamaProvider)

    s2 = Settings(
        provider="groq",
        groq_api_key="",
        openai_api_key="",
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
    )
    with pytest.raises(ProviderError):
        build_provider(s2)


def test_build_provider_vertex(monkeypatch):
    from tauros.providers import ProviderError, VertexProvider, build_provider

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "dotted-lexicon-496211-k1")
    s = Settings(
        provider="vertex",
        model="gemini-2.0-flash-001",
        groq_api_key="",
        openai_api_key="",
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
    )
    p = build_provider(s)
    assert isinstance(p, VertexProvider)
    assert p.project == "dotted-lexicon-496211-k1"
    assert p.location == "europe-west1"
    assert p.model == "gemini-2.0-flash-001"

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    s2 = Settings(
        provider="vertex",
        vertex_project="",
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
    )
    with pytest.raises(ProviderError):
        build_provider(s2)
