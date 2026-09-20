"""Execute validated plans one step at a time — never skips policy."""

from __future__ import annotations

import time
from typing import Any, Callable

from .plan_models import PlanRunResult, PlanStep, StepResult, StructuredPlan
from .plan_validator import PlanValidator
from .policy import PolicyEngine
from .security import redact_obj
from .tools import ToolRegistry


class PlanExecutor:
    """
    Chain: validate → policy per step → tool → audit callback.

    Stops on first policy denial or hard tool failure.
    """

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        policy: PolicyEngine,
        validator: PlanValidator,
        audit: Callable[[str, str, dict[str, Any]], None] | None = None,
    ):
        self.tools = tools
        self.policy = policy
        self.validator = validator
        self.audit = audit or (lambda *_a, **_k: None)

    def run(
        self,
        plan: StructuredPlan | dict[str, Any] | str,
        *,
        role: str = "user",
        user_id: int = 0,
        confirmed: str | None = None,
    ) -> PlanRunResult:
        if isinstance(plan, StructuredPlan):
            requested = plan
            validation = self.validator.validate(plan)
        else:
            validation = self.validator.validate_raw(plan)
            requested = validation.plan or StructuredPlan(intent="invalid", mode="plan", steps=[])

        self.audit(
            "plan_requested",
            "tauros",
            redact_obj({"plan": requested.model_dump(), "validation_ok": validation.ok}),
        )

        if not validation.ok or validation.plan is None:
            result = PlanRunResult(
                requested_plan=requested,
                approved_plan=None,
                validation=validation,
                stopped=True,
                stop_reason="validation_failed",
                mode=requested.mode,
            )
            self.audit("plan_rejected", "policy", redact_obj(result.model_dump()))
            return result

        approved = validation.plan
        if approved.mode in {"chat", "plan"}:
            # No execution — structure only
            out = PlanRunResult(
                requested_plan=requested,
                approved_plan=approved,
                validation=validation,
                stopped=False,
                stop_reason="mode_no_execute" if approved.mode == "plan" else None,
                mode=approved.mode,
            )
            self.audit("plan_approved_no_execute", "tauros", redact_obj(out.model_dump()))
            return out

        self.tools.reset_turn_limits()
        self.audit(
            "plan_approved",
            "tauros",
            redact_obj({"plan": approved.model_dump()}),
        )

        step_results: list[StepResult] = []
        seen_fp: set[str] = set()

        for step in approved.steps:
            fp = approved.fingerprint_step(step)
            if fp in seen_fp:
                sr = StepResult(
                    step_id=step.id,
                    tool=step.tool,
                    success=False,
                    policy="blocked",
                    risk=step.risk,
                    purpose=step.purpose,
                    error="Ciclo rilevato in esecuzione (fingerprint ripetuto)",
                    fingerprint=fp,
                )
                step_results.append(sr)
                run = PlanRunResult(
                    requested_plan=requested,
                    approved_plan=approved,
                    validation=validation,
                    steps=step_results,
                    stopped=True,
                    stop_reason="cycle_detected",
                    stop_step_id=step.id,
                    mode=approved.mode,
                )
                self.audit("plan_stopped", "tauros", redact_obj(run.model_dump()))
                return run
            seen_fp.add(fp)

            decision = self.policy.authorize_tool(
                step.tool,
                step.arguments,
                role=role,
                user_id=user_id,
                confirmed=confirmed,
            )
            path_decision = decision.path_decision
            if not decision.allowed:
                sr = StepResult(
                    step_id=step.id,
                    tool=step.tool,
                    success=False,
                    policy="blocked",
                    risk=decision.risk,
                    purpose=step.purpose,
                    error=decision.reason,
                    path_decision=path_decision,
                    fingerprint=fp,
                )
                step_results.append(sr)
                self.audit(
                    "plan_step_denied",
                    "policy",
                    redact_obj(
                        {
                            "step": step.model_dump(),
                            "reason": decision.reason,
                            "path_decision": path_decision,
                            "privilege": decision.privilege,
                            "confirmation": decision.confirmation,
                            "role": role,
                            "user_id": user_id,
                        }
                    ),
                )
                run = PlanRunResult(
                    requested_plan=requested,
                    approved_plan=approved,
                    validation=validation,
                    steps=step_results,
                    stopped=True,
                    stop_reason="policy_denied",
                    stop_step_id=step.id,
                    mode=approved.mode,
                )
                self.audit("plan_stopped", "tauros", redact_obj(run.model_dump()))
                return run

            started = time.perf_counter()
            exec_args = dict(step.arguments)
            exec_args["_role"] = role
            exec_args["_user_id"] = user_id
            exec_args["_actor"] = f"plan:{role}:{user_id}"
            if confirmed:
                exec_args["_confirmed"] = confirmed
            tool_out = self.tools.execute(step.tool, exec_args)
            duration = int((time.perf_counter() - started) * 1000)
            success = bool(tool_out.get("success") or tool_out.get("ok"))
            sr = StepResult(
                step_id=step.id,
                tool=step.tool,
                success=success,
                policy=str(tool_out.get("policy") or "allowed"),
                risk=step.risk,
                purpose=step.purpose,
                data=tool_out.get("data") if success else None,
                error=None if success else str(tool_out.get("error") or "tool_failed"),
                duration_ms=duration,
                path_decision=path_decision,
                fingerprint=fp,
            )
            step_results.append(sr)
            self.audit(
                "plan_step_executed",
                "tauros",
                redact_obj(
                    {
                        "step_id": step.id,
                        "tool": step.tool,
                        "success": success,
                        "duration_ms": duration,
                        "error": sr.error,
                    }
                ),
            )

            if not success:
                run = PlanRunResult(
                    requested_plan=requested,
                    approved_plan=approved,
                    validation=validation,
                    steps=step_results,
                    stopped=True,
                    stop_reason="tool_failed",
                    stop_step_id=step.id,
                    mode=approved.mode,
                )
                self.audit("plan_stopped", "tauros", redact_obj(run.model_dump()))
                return run

        run = PlanRunResult(
            requested_plan=requested,
            approved_plan=approved,
            validation=validation,
            steps=step_results,
            stopped=False,
            stop_reason=None,
            mode=approved.mode,
        )
        self.audit("plan_completed", "tauros", redact_obj({"steps": len(step_results)}))
        return run
