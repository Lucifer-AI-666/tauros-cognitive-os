"""Validate structured plans before any tool runs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .plan_models import (
    PROPOSE_WRITE_TOOLS,
    READ_ONLY_TOOLS,
    WRITE_LIKE_TOOLS,
    PlanValidationIssue,
    PlanValidationResult,
    StructuredPlan,
)


class PlanValidator:
    def __init__(
        self,
        *,
        allowed_tools: set[str] | frozenset[str],
        max_steps: int = 3,
        max_same_tool: int = 2,
    ):
        self.allowed_tools = set(allowed_tools)
        self.max_steps = max(1, max_steps)
        self.max_same_tool = max(1, max_same_tool)

    def validate_raw(self, payload: dict[str, Any] | str) -> PlanValidationResult:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                return PlanValidationResult(
                    ok=False,
                    issues=[
                        PlanValidationIssue(
                            code="invalid_json",
                            message=f"JSON del piano non valido: {exc}",
                        )
                    ],
                )
        if not isinstance(payload, dict):
            return PlanValidationResult(
                ok=False,
                issues=[
                    PlanValidationIssue(
                        code="not_object",
                        message="Il piano deve essere un oggetto JSON",
                    )
                ],
            )
        try:
            plan = StructuredPlan.model_validate(payload)
        except ValidationError as exc:
            return PlanValidationResult(
                ok=False,
                issues=[
                    PlanValidationIssue(code="schema", message=err["msg"])
                    for err in exc.errors()
                ]
                or [PlanValidationIssue(code="schema", message=str(exc))],
            )
        return self.validate(plan)

    def validate(self, plan: StructuredPlan) -> PlanValidationResult:
        issues: list[PlanValidationIssue] = []

        if plan.mode == "chat" and plan.steps:
            issues.append(
                PlanValidationIssue(
                    code="chat_has_steps",
                    message="Modalità chat non ammette passaggi tool",
                )
            )

        if plan.mode == "plan":
            # plan-only: structure ok, but executor will not run tools
            pass

        if len(plan.steps) > self.max_steps:
            issues.append(
                PlanValidationIssue(
                    code="too_many_steps",
                    message=f"Massimo {self.max_steps} passaggi, ricevuti {len(plan.steps)}",
                )
            )

        seen_ids: set[str] = set()
        tool_counts: dict[str, int] = {}
        fingerprints: list[str] = []

        for step in plan.steps:
            if step.id in seen_ids:
                issues.append(
                    PlanValidationIssue(
                        code="duplicate_step_id",
                        message=f"id passaggio duplicato: {step.id}",
                        step_id=step.id,
                    )
                )
            seen_ids.add(step.id)

            if step.tool not in self.allowed_tools:
                issues.append(
                    PlanValidationIssue(
                        code="unknown_tool",
                        message=f"Tool non nel registro autorizzato: {step.tool}",
                        step_id=step.id,
                    )
                )

            if step.tool in WRITE_LIKE_TOOLS and plan.mode in {
                "chat",
                "plan",
                "execute_read_only",
                "propose_write",
            }:
                issues.append(
                    PlanValidationIssue(
                        code="write_in_readonly",
                        message=(
                            f"Scrittura diretta vietata in modalità {plan.mode}: {step.tool}. "
                            "Usa propose_write / propose_patch + approvazione UI."
                        ),
                        step_id=step.id,
                    )
                )

            if plan.mode == "execute_read_only" and step.tool not in READ_ONLY_TOOLS:
                if step.tool in self.allowed_tools:
                    issues.append(
                        PlanValidationIssue(
                            code="tool_not_readonly",
                            message=f"Tool non ammessi in sola lettura: {step.tool}",
                            step_id=step.id,
                        )
                    )

            if plan.mode == "propose_write" and step.tool not in PROPOSE_WRITE_TOOLS:
                issues.append(
                    PlanValidationIssue(
                        code="tool_not_propose",
                        message=f"Tool non ammesso in propose_write: {step.tool}",
                        step_id=step.id,
                    )
                )

            tool_counts[step.tool] = tool_counts.get(step.tool, 0) + 1
            if tool_counts[step.tool] > self.max_same_tool:
                issues.append(
                    PlanValidationIssue(
                        code="tool_repeat_limit",
                        message=(
                            f"Tool {step.tool} usato più di {self.max_same_tool} volte"
                        ),
                        step_id=step.id,
                    )
                )

            fp = plan.fingerprint_step(step)
            fingerprints.append(fp)

        # Immediate cycle: identical consecutive fingerprints
        for i in range(1, len(fingerprints)):
            if fingerprints[i] == fingerprints[i - 1]:
                issues.append(
                    PlanValidationIssue(
                        code="consecutive_cycle",
                        message="Passaggio identico al precedente (ciclo)",
                        step_id=plan.steps[i].id,
                    )
                )

        # Full-plan cycle: same fingerprint more than once with no progress signal
        counts: dict[str, int] = {}
        for fp in fingerprints:
            counts[fp] = counts.get(fp, 0) + 1
            if counts[fp] > 1:
                issues.append(
                    PlanValidationIssue(
                        code="repeated_fingerprint",
                        message="Passaggio ripetuto senza avanzamento",
                    )
                )
                break

        return PlanValidationResult(ok=not issues, issues=issues, plan=plan if not issues else plan)
