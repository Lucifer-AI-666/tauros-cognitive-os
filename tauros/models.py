from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

MemoryKind = Literal[
    "preference",
    "fact",
    "person",
    "project",
    "decision",
    "lesson",
    "open_loop",
    "event",
    "temporary",
]

MemoryStatus = Literal[
    "candidate",
    "active",
    "superseded",
    "disputed",
    "expired",
    "forgotten",
    "resolved",  # legacy alias kept for compatibility
]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str = "default"
    use_tools: bool = True
    auto_memory: bool = True
    is_guest: bool = False
    # chat | plan | execute_read_only | propose_write (propose_write not executed yet)
    mode: str | None = None


class AuthRegister(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=200)


class AuthLogin(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class ElevateRequest(BaseModel):
    """Temporary privilege elevation — not permanent god mode."""

    level: str = Field(
        default="ADMINISTRATOR",
        description="OPERATOR | ADMINISTRATOR | CONTROLLED_ROOT",
    )
    minutes: int | None = Field(default=None, ge=1, le=120)
    strong_confirmation: str = Field(min_length=3, max_length=200)
    reason: str = Field(default="", max_length=500)
    scope_path: str | None = Field(default=None, max_length=2000)
    single_operation: bool = False


class WriteProposeRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    content: str | None = Field(default=None, max_length=500_000)
    kind: Literal["create", "replace", "patch"] = "replace"
    old_text: str | None = Field(default=None, max_length=200_000)
    new_text: str | None = Field(default=None, max_length=200_000)
    purpose: str = Field(default="", max_length=500)


class WriteApproveRequest(BaseModel):
    confirm: bool = True
    strong_confirmation: str = Field(default="", max_length=200)


class WriteRestoreRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    backup_path: str = Field(min_length=1, max_length=2000)
    strong_confirmation: str = Field(min_length=3, max_length=200)


class Trace(BaseModel):
    intent: str
    plan: list[dict[str, Any]] = Field(default_factory=list)
    memories: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = Field(default_factory=list)
    security_mode: str | None = None
    plan_mode: str | None = None
    plan_run: dict[str, Any] | None = None
    stop_reason: str | None = None
    planner_source: str | None = None


class DecisionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    rationale: str | None = Field(default=None, min_length=1, max_length=10000)
    outcome: str | None = Field(default=None, max_length=10000)
    status: Literal["open", "accepted", "rejected", "revisit", "closed"] | None = None
    revisit_at: datetime | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    provider: str
    model: str
    memories_used: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    trace: Trace


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    kind: MemoryKind = "fact"
    importance: int = Field(default=5, ge=1, le=10)
    tags: list[str] = Field(default_factory=list)
    source: str = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: MemoryStatus = "active"
    supersedes_id: int | None = None
    source_turn_id: str | None = None
    source_file: str | None = None


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    kind: MemoryKind | None = None
    importance: int | None = Field(default=None, ge=1, le=10)
    tags: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: MemoryStatus | None = None
    supersedes_id: int | None = None


class MemoryConfirmBatch(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=10000)
    outcome: str | None = Field(default=None, max_length=10000)
    revisit_at: datetime | None = None
    status: Literal["open", "accepted", "rejected", "revisit", "closed"] = "open"


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    timestamp: datetime
    event_type: str
    actor: str
    details: dict[str, Any]
