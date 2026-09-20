from pathlib import Path

from tauros.policy import PolicyEngine
from tauros.rules import RuleStore
from tauros.security import generate_api_token
from tauros.settings import Settings


def test_rule_deny_beats_privileges(tmp_path: Path):
    store = RuleStore(tmp_path / "rules.json")
    store.replace_all(
        [{"effect": "deny", "match": "tool", "value": "delete_file", "enabled": True}]
    )
    hit = store.evaluate("delete_file")
    assert hit and hit.rule.effect == "deny"
    assert store.evaluate("list_directory") is None


def test_path_prefix_match(tmp_path: Path):
    store = RuleStore(tmp_path / "rules.json")
    store.add({"effect": "deny", "match": "path", "value": str(tmp_path / "secret"), "enabled": True})
    assert store.evaluate("read_text_file", str(tmp_path / "secret" / "a.txt"))
    assert store.evaluate("read_text_file", str(tmp_path / "other" / "a.txt")) is None


def test_policy_engine_uses_user_rules(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        security_mode="supervised",
        workspace_allowlist=str(ws),
        rules_path=tmp_path / "rules.json",
    )
    engine = PolicyEngine(settings)
    engine.rules.replace_all(
        [{"effect": "deny", "match": "tool", "value": "list_directory", "enabled": True}]
    )
    decision = engine.authorize_tool("list_directory", {"path": str(ws)}, role="owner")
    assert decision.allowed is False
    assert "regola" in decision.reason
