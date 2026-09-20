"""Live smoke test: Groq API + TAUROS orchestrator."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# project root on path when run as script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tauros.bootstrap import doctor_checks
from tauros.database import Database
from tauros.memory import MemoryManager
from tauros.models import ChatRequest
from tauros.orchestrator import Orchestrator
from tauros.planner import Planner
from tauros.policy import PolicyEngine
from tauros.providers import build_provider
from tauros.security import PathGuard
from tauros.settings import Settings
from tauros.tools import ToolRegistry


def main() -> int:
    s = Settings()
    print("=== CONFIG ===")
    print(f"provider={s.provider}")
    print(f"model={s.model}")
    print(f"groq_key_set={bool(s.groq_api_key)}")
    print(f"security_mode={s.security_mode}")
    print()

    print("=== DOCTOR ===")
    for c in doctor_checks(s):
        if c["check"] in {
            "token_strength",
            "security_mode",
            "groq_api_key",
            "groq_api",
            "python_version",
            "workspace_allowlist",
        }:
            flag = "OK" if c["ok"] else "FAIL"
            print(f"  [{flag}] {c['check']}: {c['detail']}")
    print()

    print("=== PROVIDER DIRECT ===")
    p = build_provider(s)

    async def ping() -> str:
        return await p.chat(
            [
                {"role": "system", "content": "Rispondi in italiano, massimo 2 frasi."},
                {
                    "role": "user",
                    "content": "Conferma che sei raggiungibile via API Groq e che il sistema host e TAUROS.",
                },
            ]
        )

    ans = asyncio.run(ping())
    print(ans)
    print()

    print("=== ORCHESTRATOR CHAT ===")
    db = Database(s.database_path)
    mem = MemoryManager(db)
    guard = PathGuard(
        allowlist=s.allowlist_paths(),
        blocklist=s.blocklist_paths(),
        max_file_bytes=s.max_file_bytes,
    )
    policy = PolicyEngine(s, guard)
    tools = ToolRegistry(policy, s, guard)
    orch = Orchestrator(s, db, p, mem, Planner(), tools)

    async def full():
        return await orch.chat(
            ChatRequest(
                message=(
                    "Ricorda che preferisco risposte brevi e dirette. "
                    "Poi dimmi in una riga chi sei."
                ),
                session_id="cli-test",
                use_tools=False,
                auto_memory=True,
            )
        )

    r = asyncio.run(full())
    print("answer:", r.answer)
    print("provider:", r.provider, "| model:", r.model)
    print("trace.intent:", r.trace.intent)
    print("trace.security_mode:", r.trace.security_mode)
    print("candidates:", len(r.trace.memory_candidates))
    if r.trace.memory_candidates:
        c0 = r.trace.memory_candidates[0]
        print(
            "  candidate:",
            c0.get("status"),
            c0.get("kind"),
            (c0.get("content") or "")[:100],
        )
    print()
    print("=== RESULT: PASS ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("=== RESULT: FAIL ===")
        print(type(exc).__name__ + ":", exc)
        raise SystemExit(1) from exc
