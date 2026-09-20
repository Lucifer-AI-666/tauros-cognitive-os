from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .database import Database
from .memory import MemoryManager
from .models import ChatRequest, ChatResponse, Trace
from .plan_executor import PlanExecutor
from .plan_models import StructuredPlan
from .plan_validator import PlanValidator
from .planner import Planner
from .policy import PolicyEngine
from .providers import LLMProvider, ProviderError
from .security import redact_obj
from .settings import Settings
from .tools import ToolRegistry

_DEGRADED_MARKERS = (
    "Il motore linguistico non è raggiungibile",
    "motore esterno (Vertex) non è raggiungibile",
    "capacità di elaborazione linguistica è attualmente limitata",
)


def _history_for_llm(history: list[dict]) -> list[dict]:
    clean: list[dict] = []
    for item in history:
        text = item.get("content") or ""
        if any(marker in text for marker in _DEGRADED_MARKERS):
            continue
        clean.append(item)
    return clean


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        provider: LLMProvider,
        memory: MemoryManager,
        planner: Planner,
        tools: ToolRegistry,
        policy: PolicyEngine | None = None,
    ):
        self.settings = settings
        self.db = db
        self.provider = provider
        self.memory = memory
        self.planner = planner
        self.tools = tools
        self.policy = policy or getattr(tools, "policy", None)
        prompt_path = Path(__file__).parent.parent / "config" / "system_prompt.md"
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

        allowed = {t["name"] for t in tools.available()}
        allowed |= {
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
            "propose_write",
            "propose_patch",
            "file_snapshot",
        }
        self.plan_validator = PlanValidator(
            allowed_tools=allowed,
            max_steps=settings.max_plan_steps,
            max_same_tool=settings.max_same_tool_calls,
        )
        self.plan_executor = PlanExecutor(
            tools=tools,
            policy=self.policy if self.policy is not None else PolicyEngine(settings),
            validator=self.plan_validator,
            audit=lambda event, actor, details: self.db.audit(event, actor, details),
        )
        # Ensure planner shares allow-list and provider for LLM plans
        if isinstance(self.planner, Planner):
            self.planner.provider = self.provider
            self.planner.max_steps = settings.max_plan_steps
            self.planner.allowed_tools = allowed
            self.planner._validator = self.plan_validator

    async def chat(
        self,
        request: ChatRequest,
        user_id: int | None = None,
        role: str = "user",
        confirmed: str | None = None,
    ) -> ChatResponse:
        session_id = request.session_id
        if user_id is not None:
            session_id = f"u{user_id}:{request.session_id}"

        # Problem Agent (opzionale): arricchisce il contesto se REFRAME/INTEGRATE
        problem_prefix = ""
        try:
            from .problem_bridge import reframe_hint

            hint = reframe_hint(request.message)
            if hint:
                problem_prefix = hint + "\n\n"
                self.db.audit(
                    "problem_agent_hint",
                    role,
                    {"session_id": session_id, "hint": hint[:500]},
                )
        except Exception:
            problem_prefix = ""

        user_message = problem_prefix + request.message

        memories = self.memory.recall(user_message, 8, user_id=user_id)
        history = self.db.history(session_id, 16, user_id=user_id)

        use_tools = request.use_tools and self.settings.security_mode != "locked"
        if request.is_guest:
            use_tools = False

        # Hybrid planner: rules first, LLM when useful.
        # Smalltalk must not call the brain twice (plan + reply) — it kills local Ollama.
        from .problem_bridge import is_smalltalk

        # Hybrid planner: rules first, LLM when useful
        if (
            use_tools
            and getattr(self.planner, "create_llm", None)
            and not is_smalltalk(request.message)
        ):
            hint_bits = []
            if memories:
                hint_bits.append(
                    "memorie: "
                    + "; ".join(m["content"][:80] for m in memories[:4])
                )
            if self.settings.allowlist_paths():
                hint_bits.append(
                    "allowlist: "
                    + ", ".join(str(p) for p in self.settings.allowlist_paths()[:3])
                )
            legacy = await self.planner.create_llm(
                user_message,
                use_tools=True,
                available_tools=self.tools.available(),
                context_hint=" | ".join(hint_bits),
            )
        else:
            legacy = self.planner.create(user_message, use_tools)

        structured = legacy.structured or StructuredPlan(
            intent=legacy.intent, mode="chat", steps=[]
        )
        if request.mode in {"chat", "plan", "execute_read_only", "propose_write"}:
            structured = structured.model_copy(update={"mode": request.mode})

        # plan-only: validate but do not execute tools
        if structured.mode == "plan":
            plan_run = self.plan_executor.run(
                structured.model_copy(update={"mode": "plan"}),
                role=role or "user",
                user_id=user_id or 0,
                confirmed=confirmed,
            )
            tool_results = []
        else:
            plan_run = self.plan_executor.run(
                structured,
                role=role or "user",
                user_id=user_id or 0,
                confirmed=confirmed,
            )
            tool_results = [
                {
                    "success": s.success,
                    "ok": s.success,
                    "tool": s.tool,
                    "policy": s.policy,
                    "data": s.data,
                    "result": s.data,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                    "step_id": s.step_id,
                    "path_decision": s.path_decision,
                }
                for s in plan_run.steps
            ]

        if request.auto_memory:
            candidates = self.memory.soft_save_candidates(request.message, user_id=user_id)
        else:
            candidates = []

        context_parts: list[str] = []
        if memories:
            context_parts.append(
                "MEMORIE PERTINENTI E VERIFICABILI (solo status=active, di questo utente):\n"
                + "\n".join(
                    f"- [{m['kind']}|importanza {m['importance']}|confidenza {m['confidence']}|fonte {m.get('source')}] "
                    f"{m['content']}"
                    for m in memories
                )
            )
        if plan_run.approved_plan:
            context_parts.append(
                "PIANO OPERATIVO:\n"
                + f"intent={plan_run.approved_plan.intent} mode={plan_run.approved_plan.mode} "
                + f"source={getattr(legacy, 'source', 'rules')}\n"
                + "\n".join(
                    f"- {s.id}: {s.tool} {s.arguments} [{s.risk}]"
                    for s in plan_run.approved_plan.steps
                )
            )
        if tool_results:
            context_parts.append("RISULTATI STRUMENTI:\n" + repr(redact_obj(tool_results)))
        if plan_run.stopped:
            context_parts.append(
                f"PIANO INTERROTTO: reason={plan_run.stop_reason} step={plan_run.stop_step_id}. "
                "Non inventare risultati non presenti nella traccia."
            )
        if candidates:
            context_parts.append(
                "MEMORIE CANDIDATE APPENA RILEVATE: sono bozze, non trattarle come fatti confermati.\n"
                + "\n".join(f"- {m['content']}" for m in candidates)
            )
        context_parts.append(
            f"MODALITÀ SICUREZZA: {self.settings.security_mode}. "
            "Non inventare accesso a file o strumenti non presenti nella traccia."
        )
        if request.is_guest:
            context_parts.append(
                "Utente OSPITE: memoria temporanea, non promettere permanenza a lungo termine."
            )
        if structured.mode == "propose_write" or any(
            r.get("tool") in {"propose_write", "propose_patch"} for r in tool_results
        ):
            context_parts.append(
                "SCRITTURE SUPERVISIONATE: le proposte NON sono ancora su disco. "
                "Informa l'utente di aprire la console → Scritture, rivedere anteprima e approvare. "
                "Non affermare che il file è stato modificato finché status≠applied."
            )

        messages = [{"role": "system", "content": self.system_prompt}]
        if context_parts:
            messages.append({"role": "system", "content": "\n\n".join(context_parts)})
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in _history_for_llm(history)
        )
        # LLM riceve eventuale hint Problem Agent; in DB resta il messaggio utente originale
        messages.append({"role": "user", "content": user_message})

        self.db.add_message(session_id, "user", request.message, user_id=user_id)
        try:
            answer = await self.provider.chat(messages)
        except ProviderError as exc:
            # Il dettaglio tecnico resta in audit (redatto); l'utente riceve
            # solo un riferimento correlabile, non il corpo upstream.
            error_ref = uuid.uuid4().hex[:12]
            self.db.audit(
                "provider_error",
                "tauros",
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "error_ref": error_ref,
                    "error": str(exc),
                },
            )
            local = []
            if plan_run.steps:
                ok_n = sum(1 for s in plan_run.steps if s.success)
                local.append(f"{ok_n}/{len(plan_run.steps)} passaggi tool ok")
            if plan_run.stopped:
                local.append(f"piano fermato: {plan_run.stop_reason}")
            if memories:
                local.append(f"{len(memories)} memorie")
            detail = "; ".join(local) if local else "operazioni locali disponibili"
            answer = (
                "Il motore linguistico non è raggiungibile. TAUROS resta operativo in modalità degradata: "
                f"{detail}. Riferimento errore: {error_ref}"
            )
        self.db.add_message(session_id, "assistant", answer, user_id=user_id)

        plan_trace = []
        if plan_run.approved_plan:
            plan_trace = [
                {
                    "id": s.id,
                    "tool": s.tool,
                    "arguments": s.arguments,
                    "risk": s.risk,
                    "purpose": s.purpose,
                }
                for s in plan_run.approved_plan.steps
            ]
        elif plan_run.requested_plan:
            plan_trace = [
                {"id": s.id, "tool": s.tool, "arguments": s.arguments}
                for s in plan_run.requested_plan.steps
            ]

        trace = Trace(
            intent=structured.intent,
            plan=plan_trace,
            memories=[
                {
                    "id": m["id"],
                    "kind": m["kind"],
                    "importance": m["importance"],
                    "content": m["content"],
                    "source": m.get("source"),
                    "status": m.get("status"),
                    "confidence": m.get("confidence"),
                }
                for m in memories
            ],
            tools=tool_results,
            memory_candidates=candidates,
            security_mode=self.settings.security_mode,
            plan_mode=plan_run.mode,
            plan_run=redact_obj(plan_run.model_dump()),
            stop_reason=plan_run.stop_reason,
            planner_source=getattr(legacy, "source", "rules"),
        )
        self.db.audit(
            "chat",
            "user",
            {
                "session_id": session_id,
                "user_id": user_id,
                "trace": redact_obj(trace.model_dump()),
            },
        )
        return ChatResponse(
            answer=answer,
            session_id=request.session_id,
            provider=self.settings.provider,
            model=self.settings.model,
            memories_used=memories,
            tool_results=tool_results,
            trace=trace,
        )

    def run_plan(self, plan: StructuredPlan | dict[str, Any] | str):
        """Execute a hand-written or generated plan without LLM (tests / operator)."""
        return self.plan_executor.run(plan)

    def build_brief(self, user_id: int | None, *, is_operator: bool = False) -> dict[str, Any]:
        """Continuity brief: open loops, decisions, candidates, recent activity."""
        uid = None if is_operator else user_id
        if is_operator:
            loops = self.db.list_memories(
                20, kind="open_loop", statuses=["active", "candidate"]
            )
            candidates = self.db.list_memories(15, status="candidate")
            decisions_open = self.db.list_decisions(15, status="open")
            decisions_revisit = self.db.list_decisions(10, status="revisit")
            active = self.db.list_memories(10, status="active")
            audit = self.db.list_audit(8)
        else:
            loops = self.db.list_memories(
                20, kind="open_loop", statuses=["active", "candidate"], user_id=user_id
            )
            candidates = self.db.list_memories(15, status="candidate", user_id=user_id)
            decisions_open = self.db.list_decisions(15, status="open", user_id=user_id)
            decisions_revisit = self.db.list_decisions(10, status="revisit", user_id=user_id)
            active = self.db.list_memories(10, status="active", user_id=user_id)
            audit = []

        headlines: list[str] = []
        if loops:
            headlines.append(f"{len(loops)} open loop aperti")
        if candidates:
            headlines.append(f"{len(candidates)} memorie candidate da confermare")
        if decisions_open or decisions_revisit:
            headlines.append(
                f"{len(decisions_open)} decisioni open, {len(decisions_revisit)} da rivisitare"
            )
        if not headlines:
            headlines.append("Nessuna urgenza: sistema quieto")

        narrative = (
            "Brief TAUROS — continuità operativa.\n"
            + " · ".join(headlines)
            + ".\n"
            "Conferma le candidate prima di trattarle come fatti. "
            "Chiudi gli open loop o elevane l'importanza."
        )
        return {
            "generated_at": self.db.now(),
            "headlines": headlines,
            "narrative": narrative,
            "open_loops": loops[:12],
            "candidates": candidates[:12],
            "decisions_open": decisions_open,
            "decisions_revisit": decisions_revisit,
            "recent_active_memories": active[:8],
            "recent_audit": audit,
            "counts": {
                "open_loops": len(loops),
                "candidates": len(candidates),
                "decisions_open": len(decisions_open),
                "decisions_revisit": len(decisions_revisit),
            },
            "user_id": user_id,
            "scope": "operator" if is_operator else "user",
        }
