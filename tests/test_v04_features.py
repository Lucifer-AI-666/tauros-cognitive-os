"""v0.4: tools read-only, brief, decisions patch, LLM planner fallback."""

from pathlib import Path

from tauros.database import Database
from tauros.memory import MemoryManager
from tauros.models import DecisionCreate, MemoryCreate, MemoryPatch
from tauros.orchestrator import Orchestrator
from tauros.plan_models import PlanStep, StructuredPlan
from tauros.planner import Planner
from tauros.policy import PolicyEngine
from tauros.providers import LLMProvider
from tauros.security import generate_api_token
from tauros.settings import Settings
from tauros.tools import ToolRegistry


class FakeProvider(LLMProvider):
    def __init__(self, reply: str = "ok"):
        self.reply = reply
        self.calls = 0

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return self.reply


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "api_token": generate_api_token(),
        "skip_token_check": True,
        "database_path": tmp_path / "t.db",
        "workspace_allowlist": str(tmp_path / "ws"),
        "security_mode": "read_only",
        "host": "127.0.0.1",
        "allow_lan_bind": False,
        "max_plan_steps": 3,
    }
    base.update(kwargs)
    return Settings(**base)


def test_workspace_search_finds_text(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.md").write_text("hello TAUROS golden", encoding="utf-8")
    settings = _settings(tmp_path)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    # operator role for workspace_search
    out = tools.execute(
        "workspace_search",
        {"query": "golden", "path": str(ws), "_role": "operator", "_user_id": 1},
    )
    assert out["success"]
    assert out["data"]["match_count"] >= 1


def test_project_summary(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "README.md").write_text("# x", encoding="utf-8")
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    settings = _settings(tmp_path)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    out = tools.execute(
        "project_summary",
        {"path": str(ws), "_role": "operator", "_user_id": 1},
    )
    assert out["success"]
    assert "README.md" in out["data"]["markers"]


def test_user_denied_workspace_search(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = _settings(tmp_path)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    out = tools.execute(
        "workspace_search",
        {"query": "x", "path": str(ws), "_role": "user", "_user_id": 2},
    )
    assert not out["success"]
    assert out["policy"] == "blocked"


def test_planner_git_and_search_rules():
    p = Planner()
    plan = p.create("Mostra git status")
    assert plan.tool_calls and plan.tool_calls[0].name == "git_status"
    plan2 = p.create("Cerca nel workspace 'token'")
    assert plan2.tool_calls and plan2.tool_calls[0].name == "workspace_search"


def test_llm_planner_valid_json(tmp_path: Path):
    provider = FakeProvider(
        '{"intent":"sys","mode":"execute_read_only","rationale":"t","steps":'
        '[{"id":"s1","tool":"system_info","arguments":{},"risk":"low","purpose":"info"}]}'
    )
    p = Planner(provider=provider, max_steps=3)
    import asyncio

    plan = asyncio.run(p.create_llm("analizza lo stato del sistema host", use_tools=True))
    assert plan.source == "llm"
    assert plan.structured and plan.structured.steps[0].tool == "system_info"


def test_llm_planner_falls_back_on_garbage():
    provider = FakeProvider("non e json")
    p = Planner(provider=provider)
    import asyncio

    plan = asyncio.run(p.create_llm("Dammi informazioni sul sistema", use_tools=True))
    # rules match system_info when not open-ended... "informazioni sul sistema" is rules
    assert plan.structured
    assert plan.source in {"rules", "llm"}


def test_brief_and_decision_patch(tmp_path: Path):
    settings = _settings(tmp_path)
    (tmp_path / "ws").mkdir(exist_ok=True)
    db = Database(settings.database_path)
    mem = MemoryManager(db)
    mem.remember(
        MemoryCreate(content="devo finire il brief", kind="open_loop", status="active"),
        user_id=1,
    )
    did = db.add_decision("Scegli provider", "Groq e veloce", None, "open", None, user_id=1)
    updated = db.update_decision(did, {"status": "accepted"}, user_id=1)
    assert updated and updated["status"] == "accepted"

    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard, memory=mem)
    provider = FakeProvider("ciao")
    planner = Planner(provider=provider)
    orch = Orchestrator(settings, db, provider, mem, planner, tools, policy=policy)
    brief = orch.build_brief(1, is_operator=False)
    assert brief["counts"]["open_loops"] >= 1
    assert "narrative" in brief


def test_handwritten_plan_with_new_tools(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("alpha beta", encoding="utf-8")
    settings = _settings(tmp_path)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    from tauros.plan_executor import PlanExecutor
    from tauros.plan_validator import PlanValidator

    validator = PlanValidator(
        allowed_tools={t["name"] for t in tools.available()},
        max_steps=3,
        max_same_tool=2,
    )
    ex = PlanExecutor(tools=tools, policy=policy, validator=validator)
    plan = StructuredPlan(
        intent="search",
        mode="execute_read_only",
        steps=[
            PlanStep(
                id="s1",
                tool="workspace_search",
                arguments={"query": "alpha", "path": str(ws)},
                risk="low",
            )
        ],
    )
    # Plan executor uses role=user by default — workspace_search needs operator
    run = ex.run(plan, role="operator", user_id=1)
    assert run.validation.ok
    assert not run.stopped
    assert run.steps and run.steps[0].success


def test_memory_consolidate_skips_low_confidence(tmp_path: Path):
    db = Database(tmp_path / "c.db")
    mem = MemoryManager(db)
    c = mem.remember(
        MemoryCreate(
            content="fatto auto",
            kind="fact",
            status="candidate",
            confidence=0.5,
            source="conversation",
        ),
        user_id=1,
    )
    result = mem.consolidate(user_id=1)
    assert c["id"] not in result["promoted_ids"]


def test_degraded_reply_hides_provider_error(tmp_path: Path):
    """Hardening: {exc} non raggiunge la risposta utente; resta in audit con error_ref."""
    import asyncio

    from tauros.models import ChatRequest
    from tauros.providers import ProviderError

    class FailingProvider(LLMProvider):
        async def chat(self, messages: list[dict[str, str]]) -> str:
            raise ProviderError("upstream 403: corpo risposta segreto-XYZ")

    settings = _settings(tmp_path)
    (tmp_path / "ws").mkdir(exist_ok=True)
    db = Database(settings.database_path)
    mem = MemoryManager(db)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard, memory=mem)
    provider = FailingProvider()
    planner = Planner(provider=provider)
    orch = Orchestrator(settings, db, provider, mem, planner, tools, policy=policy)

    resp = asyncio.run(orch.chat(ChatRequest(message="ciao", session_id="s1"), user_id=1))
    assert "segreto-XYZ" not in resp.answer
    assert "Dettaglio tecnico" not in resp.answer
    assert "Riferimento errore" in resp.answer

    events = [r for r in db.list_audit() if r["event_type"] == "provider_error"]
    assert events, "evento provider_error mancante in audit"
    assert events[0]["details"]["error_ref"] in resp.answer
