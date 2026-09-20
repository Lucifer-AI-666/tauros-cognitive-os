"""Structured plan data — pure data, never executable objects."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

PlanMode = Literal["chat", "plan", "execute_read_only", "propose_write"]
RiskLevel = Literal["low", "medium", "high", "critical"]

# Tools allowed in read-only multi-step plans (milestone 0.3+).
READ_ONLY_TOOLS = frozenset(
    {
        "system_info",
        "disk_usage",
        "list_directory",
        "read_text_file",
        "memory_search",
        "workspace_search",
        "git_status",
        "git_log",
        "git_diff",
        "project_summary",
    }
)

WRITE_LIKE_TOOLS = frozenset(
    {
        "write_file",
        "shell_write",
        "delete_file",
        "install_package",
        "run_shell",
        "execute_command",
        "file_restore",
    }
)

# Allowed when mode is propose_write (draft only — never raw disk write).
PROPOSE_WRITE_TOOLS = frozenset(
    {
        "propose_write",
        "propose_patch",
        "file_snapshot",
        "read_text_file",
        "list_directory",
        "workspace_search",
        "system_info",
        "memory_search",
        "project_summary",
    }
)


class PlanStep(BaseModel):
    """One planned action. Data only — no callables."""

    id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel = "low"
    purpose: str = Field(default="", max_length=500)

    @field_validator("tool")
    @classmethod
    def tool_slug(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not cleaned.replace("_", "").isalnum():
            raise ValueError(f"Nome tool non valido: {value!r}")
        return cleaned


class StructuredPlan(BaseModel):
    """JSON-serializable plan produced by a planner (rules or LLM)."""

    intent: str = Field(min_length=1, max_length=200)
    mode: PlanMode = "execute_read_only"
    steps: list[PlanStep] = Field(default_factory=list, max_length=32)
    rationale: str = Field(default="", max_length=2000)

    def fingerprint_step(self, step: PlanStep) -> str:
        import json

        args = json.dumps(step.arguments, sort_keys=True, ensure_ascii=False, default=str)
        return f"{step.tool}|{args}"


class PlanValidationIssue(BaseModel):
    code: str
    message: str
    step_id: str | None = None


class PlanValidationResult(BaseModel):
    ok: bool
    issues: list[PlanValidationIssue] = Field(default_factory=list)
    plan: StructuredPlan | None = None


class StepResult(BaseModel):
    step_id: str
    tool: str
    success: bool
    policy: str
    risk: str = "low"
    purpose: str = ""
    data: Any = None
    error: str | None = None
    duration_ms: int = 0
    path_decision: dict[str, Any] | None = None
    fingerprint: str = ""


class PlanRunResult(BaseModel):
    requested_plan: StructuredPlan
    approved_plan: StructuredPlan | None = None
    validation: PlanValidationResult
    steps: list[StepResult] = Field(default_factory=list)
    stopped: bool = False
    stop_reason: str | None = None
    stop_step_id: str | None = None
    mode: PlanMode = "execute_read_only"
