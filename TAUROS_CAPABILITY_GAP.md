# TAUROS CAPABILITY GAP MAP

Source of truth: `TOOLS_BY_LEVEL` in `tauros/privileges.py` vs `ToolRegistry._tools` in `tauros/tools.py`.
Planner blocks: `WRITE_LIKE_TOOLS` in `tauros/plan_models.py`.
Baseline: 105/105. No runtime tools added.

Legend:

- **POLICY** = named in `TOOLS_BY_LEVEL` (and/or `policy.filesystem_tools`)
- **REGISTRY** = registered in `ToolRegistry._tools` (AI/plan executor can call it)
- **SAFE EXECUTOR** = implementation goes through PathGuard / policy / supervised writes
- **TESTS** = dedicated behavioral test of that capability, not just a name mention

---

## Runtime-ready (declared + registered + executor)

| Capability | Min privilege | POLICY | REGISTRY | Planner | Safe executor | Tests | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `system_info` | BASE | yes | yes | allowed (read-only) | local metadata only | yes (`test_core`, `test_plan_executor`, `test_security`) | none |
| `disk_usage` | BASE | yes | yes | allowed (read-only) | PathGuard via `_resolve_root` | yes (`test_disk_usage_is_cross_platform`) | none |
| `memory_search` | BASE | yes | yes | allowed (read-only / propose_write) | scoped `MemoryManager.recall(user_id)` | indirect (memory tests) | no dedicated tool-level test |
| `list_directory` | BASE | yes | yes | allowed (read-only) | PathGuard + skip sensitive children | yes (path guard / plan executor / rules) | none |
| `read_text_file` | BASE | yes | yes | allowed (read-only) | `PathGuard.open_text_verified` | yes (path guard / security) | none |
| `workspace_search` | OPERATOR | yes | yes | allowed (read-only) | PathGuard walk + skip dirs | yes (`test_v04_features`) | none |
| `git_status` | OPERATOR | yes | yes | allowed (read-only) | `git` subprocess, write-like args blocked | yes (planner rule test) | no dedicated executor test |
| `git_log` | OPERATOR | yes | yes | allowed (read-only) | same git sandbox | no dedicated test | test gap only |
| `git_diff` | OPERATOR | yes | yes | allowed (read-only) | same git sandbox | no dedicated test | test gap only |
| `project_summary` | OPERATOR | yes | yes | allowed (read-only) | PathGuard + list + git_status | yes (`test_project_summary`) | none |
| `propose_write` | OPERATOR | yes | yes | propose_write mode only | `WriteService.propose` (no disk write) | yes (`test_tool_propose_write_via_registry`) | none |
| `propose_patch` | OPERATOR | yes | yes | propose_write mode only | `WriteService.propose(kind=patch)` | yes (approve patch path) | tool-via-registry less covered than write |
| `file_snapshot` | OPERATOR | yes | yes | propose_write mode only | `WriteService.snapshot` under allowlist | yes (`test_restore_from_backup` uses snapshot) | none |

---

## Adjacent, not ToolRegistry (API / service executors)

These exist as **supervised write / backup services**, not as planner tools.

| Capability | Min privilege | POLICY | REGISTRY | Planner | Safe executor | Tests | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `file_restore` | ADMINISTRATOR | yes (policy list + TOOLS_BY_LEVEL) | no | blocked (`WRITE_LIKE_TOOLS`) | `WriteService.restore_backup` via `POST /writes/restore` | yes (`test_restore_from_backup`) | declared as tool, executed only via API |
| `write_file` | ADMINISTRATOR | yes | no | blocked | no direct tool; disk write only via `WriteService.approve` | yes (supervised writes) | name reserved; must stay unmapped to LLM |
| `tauros_backup` | ADMINISTRATOR | yes | no | not in planner allow-list | `backup.py` / migrations backup, not a tool | `test_migrations_and_backup` | DB backup ≠ operator tool |
| `tauros_restore` | ADMINISTRATOR | yes | no | blocked | not a ToolRegistry executor | no tool test | declared, unwired as tool |
| `tauros_migrate` | ADMINISTRATOR | yes | no | not in planner allow-list | `migrations.run_migrations` (process/internal) | `test_migrations_and_backup` | not an AI tool |
| `run_dev_command` | ADMINISTRATOR | yes | no | not in planner allow-list | none | none | declared only |

---

## CONTROLLED_ROOT — declared, not materialized

| Capability | POLICY | REGISTRY | Planner | Safe executor | Tests | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| `run_shell` | yes (ROOT) | **no** | blocked | **none** | policy deny (`test_security.test_unknown_tool` / `run_shell`) | theoretical |
| `install_package` | yes (ROOT) | **no** | blocked | **none** | none as executor | theoretical |
| `delete_file` | yes (ROOT) + `filesystem_tools` | **no** | blocked | **none** (only rollback `unlink` in writes) | policy deny (`test_core.test_policy_blocks_dangerous_tool`) | theoretical |
| `firewall_change` | yes (ROOT) + CRITICAL | **no** | not allowed | **none** | none | theoretical |
| `boot_change` | yes (ROOT) + CRITICAL | **no** | not allowed | **none** | none | theoretical |
| `credential_access` | yes (ROOT) + CRITICAL | **no** | not allowed | **none** | none | theoretical |
| `network_exfil` | yes (ROOT) + CRITICAL | **no** | not allowed | **none** | none | theoretical |
| `system_admin` | yes (ROOT) + CRITICAL | **no** | not allowed | **none** | none | theoretical |
| `format_disk` | yes (ROOT) + CRITICAL + DESTRUCTIVE | **no** | not allowed | **none** | none | theoretical |
| `mass_delete` | yes (ROOT) + CRITICAL + DESTRUCTIVE | **no** | not allowed | **none** | privilege confirmation only (`test_destructive_always_needs_preview`) | **policy can ALLOW with preview; no executor** |
| `drop_database` | yes (ROOT) + DESTRUCTIVE | **no** | not allowed | **none** | none | theoretical |
| `wipe_workspace` | yes (ROOT) + DESTRUCTIVE | **no** | not allowed | **none** | none | theoretical |

---

## Names that appear only as planner denylist (not even in TOOLS_BY_LEVEL)

| Name | Notes |
| --- | --- |
| `shell_write` | in `WRITE_LIKE_TOOLS` only |
| `execute_command` | in `WRITE_LIKE_TOOLS` only |

---

## Counts

| Class | Count |
| --- | --- |
| Declared in CONTROLLED_ROOT set | 30 names (includes inherited lower-level tools) |
| Unique names added at ADMINISTRATOR | 6 (`write_file`, `file_restore`, `tauros_backup`, `tauros_restore`, `tauros_migrate`, `run_dev_command`) |
| Unique names added at CONTROLLED_ROOT | 12 destructive/admin names |
| Actually in ToolRegistry | 13 |
| CONTROLLED_ROOT unique names with a live executor | 0 |

---

## Implication

CONTROLLED_ROOT is a **capability model**, not a live god-mode runtime.

Do **not** implement `run_shell` next. If any ROOT name is ever wired, it needs its own executor, policy binding, confirmation class, audit, and tests — never a direct map from `TOOLS_BY_LEVEL` to `subprocess`.

Closest real write power today is **not** CONTROLLED_ROOT. It is the supervised write path:

`propose_* / file_snapshot → WriteService.approve → backup → atomic write → hash → rollback`
with ownership, privilege, and confirmation already enforced.
