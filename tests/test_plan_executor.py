"""Hand-written plans only — no LLM. Isolates executor vs planner failures."""

from pathlib import Path

from tauros.plan_executor import PlanExecutor
from tauros.plan_models import PlanStep, StructuredPlan
from tauros.plan_validator import PlanValidator
from tauros.policy import PolicyEngine
from tauros.security import generate_api_token
from tauros.settings import Settings
from tauros.tools import ToolRegistry


def _stack(tmp_path: Path, allow: Path | None = None):
    ws = allow or (tmp_path / "ws")
    ws.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        workspace_allowlist=str(ws),
        security_mode="read_only",
        max_plan_steps=3,
        max_same_tool_calls=2,
        database_path=tmp_path / "p.db",
    )
    policy = PolicyEngine(settings)
    tools = ToolRegistry(policy, settings, policy.path_guard)
    validator = PlanValidator(
        allowed_tools={t["name"] for t in tools.available()}
        | {"system_info", "disk_usage", "list_directory", "read_text_file"},
        max_steps=3,
        max_same_tool=2,
    )
    audit_log: list[tuple[str, dict]] = []

    def audit(event: str, actor: str, details: dict) -> None:
        audit_log.append((event, details))

    executor = PlanExecutor(tools=tools, policy=policy, validator=validator, audit=audit)
    return ws, executor, audit_log


def test_handwritten_readonly_plan_succeeds(tmp_path: Path):
    ws, executor, audit = _stack(tmp_path)
    (ws / "a.md").write_text("hello", encoding="utf-8")
    plan = StructuredPlan(
        intent="inspect_workspace",
        mode="execute_read_only",
        rationale="test manuale",
        steps=[
            PlanStep(id="s1", tool="list_directory", arguments={"path": str(ws)}, risk="low"),
            PlanStep(id="s2", tool="system_info", arguments={}, risk="low"),
        ],
    )
    run = executor.run(plan)
    assert run.validation.ok
    assert not run.stopped
    assert len(run.steps) == 2
    assert all(s.success for s in run.steps)
    assert any(e == "plan_completed" for e, _ in audit)
    assert any(e == "plan_approved" for e, _ in audit)


def test_handwritten_plan_stops_on_policy_deny(tmp_path: Path):
    ws, executor, audit = _stack(tmp_path)
    outside = tmp_path / "secret.md"
    outside.write_text("LEAK-ME", encoding="utf-8")
    plan = StructuredPlan(
        intent="attack_path",
        mode="execute_read_only",
        steps=[
            PlanStep(
                id="s1",
                tool="read_text_file",
                arguments={"path": str(outside)},
                risk="low",
                purpose="tentativo fuori allowlist",
            ),
            PlanStep(id="s2", tool="system_info", arguments={}, risk="low"),
        ],
    )
    run = executor.run(plan)
    assert run.validation.ok
    assert run.stopped
    assert run.stop_reason == "policy_denied"
    assert run.stop_step_id == "s1"
    assert len(run.steps) == 1
    assert run.steps[0].success is False
    assert run.steps[0].policy == "blocked"
    assert "LEAK-ME" not in str(run.model_dump())
    # second step never runs
    assert any(e == "plan_step_denied" for e, _ in audit)
    assert any(e == "plan_stopped" for e, _ in audit)


def test_invalid_json_plan_rejected(tmp_path: Path):
    _, executor, audit = _stack(tmp_path)
    run = executor.run("{not json")
    assert not run.validation.ok
    assert run.stopped
    assert run.stop_reason == "validation_failed"
    assert any(e == "plan_rejected" for e, _ in audit)


def test_too_many_steps_rejected(tmp_path: Path):
    _, executor, _ = _stack(tmp_path)
    steps = [
        PlanStep(id=f"s{i}", tool="system_info", arguments={}, risk="low") for i in range(5)
    ]
    # same tool repeated will also hit max_same_tool; use unique purposes but same tool
    # validator max_same_tool=2 so use 4 different tools mixed — only system_info allowed thrice fails
    plan = StructuredPlan(intent="spam", mode="execute_read_only", steps=steps)
    run = executor.run(plan)
    assert not run.validation.ok
    codes = {i.code for i in run.validation.issues}
    assert "too_many_steps" in codes or "tool_repeat_limit" in codes or "repeated_fingerprint" in codes


def test_write_tool_in_readonly_mode_rejected(tmp_path: Path):
    _, executor, _ = _stack(tmp_path)
    plan = {
        "intent": "evil",
        "mode": "execute_read_only",
        "steps": [
            {
                "id": "s1",
                "tool": "write_file",
                "arguments": {"path": "x"},
                "risk": "high",
            }
        ],
    }
    # write_file not in allowed tools either
    run = executor.run(plan)
    assert not run.validation.ok


def test_plan_mode_does_not_execute_tools(tmp_path: Path):
    _, executor, audit = _stack(tmp_path)
    plan = StructuredPlan(
        intent="preview",
        mode="plan",
        steps=[PlanStep(id="s1", tool="system_info", arguments={})],
    )
    run = executor.run(plan)
    assert run.validation.ok
    assert run.steps == []
    assert run.stop_reason == "mode_no_execute"
