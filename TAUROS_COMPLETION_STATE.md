# TAUROS COMPLETION STATE

## CURRENT STATE

Execution spine, write ownership, privilege boundaries, memory, audit, and
brain runtime are recovered. CONTROLLED_ROOT remains a declarative capability
model. Baseline remains 105/105. `run_shell` is not in scope.

## WORKING

- Controlled execution spine:
  Planner -> PlanValidator -> PlanExecutor -> PolicyEngine ->
  PrivilegeService / PathGuard -> ToolRegistry -> Audit

- Tool execution has one identified runtime gateway:
  PlanExecutor -> ToolRegistry.execute()

- Supervised write engine:
  proposal -> privilege check -> confirmation -> snapshot ->
  atomic replacement -> SHA-256 verification -> rollback -> audit

- Supervised write ownership:
  WriteService.approve() and WriteService.reject() deny mismatched
  proposal user_id; API reject maps PermissionError to HTTP 403.
  Cross-user approve/reject tests pass.

- Privilege boundary model:
  BASE -> OPERATOR -> ADMINISTRATOR -> CONTROLLED_ROOT

- Permanent identity and temporary authority are separated.

- Guest:
  BASE only, elevation denied.

- User:
  BASE by default, max temporary elevation = OPERATOR.

- Operator:
  OPERATOR by default, may temporarily elevate up to CONTROLLED_ROOT.

- Owner/Admin:
  ADMINISTRATOR by default, may temporarily elevate up to CONTROLLED_ROOT.

- Elevation:
  strong confirmation required,
  time-limited,
  clamped to configured maximum,
  optionally path-scoped,
  optionally single-operation.

- Runtime tool surface remains restricted to bounded/read-oriented tools
  plus supervised write proposals and snapshots.

- Memory integrity:
  user-scoped remember/recall/correct/forget;
  candidates are not hard-recalled as facts;
  auto-extract stays candidate (confidence 0.72);
  consolidate does not auto-promote conversation extracts below 0.95;
  hash dedup is per-user;
  forget is logical deactivation (active=0, status=forgotten)
  and patches do not revive forgotten rows;
  planner has no arbitrary memory_write tool.

- Audit integrity:
  AUDIT_STATUS = WORKING
  EVENT_COVERAGE = GOOD
  SECRET_REDACTION = WORKING
  PLANNER_CAN_MODIFY_AUDIT = NO
  APPLICATION_APPEND_ONLY = YES
  DATABASE_IMMUTABILITY = NOT_PROVEN
  FORENSIC_TAMPER_EVIDENCE = NOT_PROVEN
  GET /audit is operator-only.

- Brain runtime / provider switching:
  BRAIN_RUNTIME_STATUS = WORKING
  PROVIDER_SWITCH_LIVE = YES
  MODEL_SWITCH_LIVE = YES
  OPERATOR_ONLY_SWITCH = YES
  PLANNER_CAN_SWITCH_PROVIDER = NO
  PROVIDER_ALLOWLIST = YES
  ROLLBACK_ON_PROVIDER_ERROR = YES
  PERSISTENT_OVERRIDE = YES
  TIMEOUTS = PRESENT
  RETRY = HTTP_TRANSPORT_3X
  FALLBACK = VERTEX_TO_GROQ_AND_GROQ_TO_OLLAMA
  DEGRADED_MODE = WORKING
  SECRET_IN_SWITCH_AUDIT = NO
  Boot: environment then optional data/brain.json override.
  PUT /brain requires require_operator; GET /brain does not mutate state.
  apply() builds and validates the provider, then assigns
  orchestrator.provider and planner.provider.

## PARTIAL

- CONTROLLED_ROOT capability layer:
  privilege model defines high-impact capabilities,
  but those capabilities are not currently exposed through ToolRegistry
  or the planner execution path.

## BROKEN

## PLACEHOLDER

## DUPLICATE

## ORPHAN

## MISSING

## UNKNOWN

## RISKS

- `.pytest_cache` is not writable (permission denied). Non-blocking.
- Strong phrase defaults to `CONFERMO ADMIN` and is hinted in privilege status.
  It is intentional confirmation, not a second factor. CONTROLLED_ROOT must
  therefore be gated by identity + allowed role + temporary session + scope + audit.
- Future implementation of CONTROLLED_ROOT tools must not map directly
  from privilege declaration to arbitrary execution.
  Each capability requires a dedicated, auditable, policy-bound executor.
- Memory `user_id=None` is an intentional internal/operator bypass.
  Keep it off all user-facing callers.
- Memory forget is logical deactivation, not forensic erase.
- Audit immutability is guaranteed by application structure, not by the database.
- No explicit negative test against UPDATE/DELETE on the audit table.
- Some WriteService events rely on Database.audit() as the last redaction gate.
- No forensic integrity / tamper-evidence demonstrated for audit.
- ~~Provider error details can reach the user as `Dettaglio tecnico: {exc}`~~
  RISOLTO in 0.4.4: la risposta degradata mostra solo un `error_ref` di
  correlazione; il dettaglio resta in audit come `provider_error` (redatto).
  Coperto da `test_degraded_reply_hides_provider_error`.
- LLM HTTP timeouts are high (120s for Ollama/OpenAI-compatible). Concurrency
  cancellation is not demonstrated.
- Retry is Vertex-only; fallback is Vertex→Groq only, not a general policy.
- Provider names are allowlisted; equivalent model-name allowlist is not proven.
- Switch/persistence races are not fully proven (save_brain failure after
  live assign, concurrent PUT /brain, chat during split Orchestrator/Planner
  update).
- Local `data/brain.json` is a boot trust boundary (filesystem, not remote API).
- Successful `brain_switch` is audited; failed switch event
  (`brain_switch_failed`) is not demonstrated.

## NEXT MILESTONE

Architecture recovery of the core rings is closed (spine, writes, privileges,
memory, audit, brain). Next work is hardening, not new power:
`{exc}` rimosso dalle risposte degrade in 0.4.4; do not implement `run_shell`.
Restano in coda: audit DB non forensic-immutable (tamper-evidence), model-name
allowlist, race switch/persistenza brain.
