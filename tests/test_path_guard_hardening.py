"""PathGuard + redaction + token strength — default deny barrier."""

from pathlib import Path

import pytest

from tauros.security import (
    AccessLevel,
    PathGuard,
    assert_strong_token,
    generate_api_token,
    is_weak_token,
    parse_path_list,
    redact_obj,
    redact_text,
)


def test_file_inside_allowlist_accepted(tmp_path: Path):
    ws = tmp_path / "TaurosWorkspace"
    ws.mkdir()
    f = ws / "README.md"
    f.write_text("# ok", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(f))
    assert d.allowed, d.reason
    assert d.allow_root is not None
    assert "TaurosWorkspace" in d.allow_root
    assert d.rule == "allowlist_match"


def test_parent_walk_does_not_block_valid_nested_file(tmp_path: Path):
    """Regression: do not climb past allow root and reject valid files."""
    root = tmp_path / "Users" / "anouar" / "TaurosWorkspace"
    root.mkdir(parents=True)
    f = root / "docs" / "notes.md"
    f.parent.mkdir(parents=True)
    f.write_text("hello", encoding="utf-8")
    guard = PathGuard(allowlist=[root], require_allowlist=True)
    d = guard.resolve(str(f))
    assert d.allowed, d.reason


def test_outside_allowlist_denied(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(outside))
    assert not d.allowed
    assert d.rule == "outside_allowlist"


def test_dotdot_escape_denied(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "out.txt").write_text("no", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(ws / ".." / "out.txt"))
    assert not d.allowed


def test_symlink_escape_denied(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = ws / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink non supportati")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(link))
    assert not d.allowed


def test_symlink_internal_allowed(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "real.md"
    target.write_text("inside", encoding="utf-8")
    link = ws / "alias.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink non supportati")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(link))
    assert d.allowed, d.reason


def test_env_denied_env_example_allowed(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    env = ws / ".env"
    env.write_text("KEY=secret", encoding="utf-8")
    example = ws / ".env.example"
    example.write_text("KEY=", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    assert not guard.resolve(str(env)).allowed
    assert guard.resolve(str(example)).allowed, guard.resolve(str(example)).reason


def test_file_too_large_denied(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    big = ws / "big.md"
    big.write_text("x" * 5000, encoding="utf-8")
    guard = PathGuard(allowlist=[ws], max_file_bytes=100, require_allowlist=True)
    d = guard.resolve(str(big))
    assert not d.allowed
    assert d.rule == "max_file_bytes"


def test_unknown_extension_default_deny(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "payload.xyz"
    f.write_text("data", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(f))
    assert not d.allowed
    assert "default_deny" in (d.rule or "")


def test_binary_renamed_as_txt_detected(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "fake.txt"
    f.write_bytes(b"\x00\x01\x02\xff\xfe binary payload here")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    with pytest.raises(PermissionError, match="binario"):
        guard.open_text_verified(str(f))


def test_ssh_dir_component_forbidden(tmp_path: Path):
    ws = tmp_path / "ws"
    ssh = ws / ".ssh"
    ssh.mkdir(parents=True)
    key = ssh / "config"
    key.write_text("Host *", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(key))
    assert not d.allowed


def test_tokenization_filename_not_false_positive(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "tokenization notes.md"
    f.write_text("ok", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(f))
    assert d.allowed, d.reason


def test_credentials_folder_name_blocked(tmp_path: Path):
    ws = tmp_path / "ws"
    cred = ws / "credentials"
    cred.mkdir(parents=True)
    f = cred / "notes.md"
    f.write_text("x", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], require_allowlist=True)
    d = guard.resolve(str(f))
    assert not d.allowed


def test_repetitive_token_rejected():
    assert is_weak_token("a" * 30)
    assert is_weak_token("aaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    with pytest.raises(Exception):
        assert_strong_token("a" * 32)
    tok = generate_api_token()
    assert not is_weak_token(tok)
    assert_strong_token(tok)


def test_redaction_simple_and_nested():
    text = "api_key=abcdefghijklmnop OpenAI sk-abcdefghijklmnopqrstuvwxyz"
    red = redact_text(text)
    assert "abcdefghijklmnop" not in red
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in red
    assert "[REDACTED]" in red

    # JWT-like
    jwt = "header eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature_tail_here_xxx"
    # use a more realistic JWT body
    jwt = (
        "token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    red_jwt = redact_text(jwt)
    assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c" not in red_jwt

    nested = {
        "api_token": "xyz",
        "nested": {"password": "p", "ok": "visible"},
        "list": [{"secret": "hide"}, "Authorization: Bearer abc.def.ghi"],
    }
    out = redact_obj(nested)
    assert out["api_token"] == "[REDACTED]"
    assert out["nested"]["password"] == "[REDACTED]"
    assert out["nested"]["ok"] == "visible"
    assert out["list"][0]["secret"] == "[REDACTED]"
    assert "Bearer [REDACTED]" in out["list"][1] or "[REDACTED]" in out["list"][1]


def test_parse_path_list_json_and_newlines(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b,with,comma"
    a.mkdir()
    b.mkdir()
    paths = parse_path_list(f'["{a.as_posix()}", "{b.as_posix()}"]')
    assert len(paths) == 2
    nl = parse_path_list(f"{a}\n{b}")
    assert len(nl) == 2


def test_access_level_enforced(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "a.md"
    f.write_text("x", encoding="utf-8")
    guard = PathGuard(allowlist=[ws], max_access=AccessLevel.LIST)
    d = guard.resolve(str(f), access=AccessLevel.READ)
    assert not d.allowed
    assert d.rule == "access_level"
