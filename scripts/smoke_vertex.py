"""Live smoke test: Vertex AI via ADC (host or in-cluster gcp-auth)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tauros.providers import build_provider
from tauros.settings import Settings


def main() -> int:
    s = Settings()
    print("=== CONFIG ===")
    print(f"provider={s.provider}")
    print(f"model={s.model}")
    print(f"vertex_project={s.vertex_project or '(from env/ADC)'}")
    print(f"vertex_location={s.vertex_location}")
    print()

    if s.provider.lower().strip() not in {"vertex", "gemini", "vertex-ai"}:
        print("Imposta TAUROS_PROVIDER=vertex")
        return 2

    p = build_provider(s)

    async def ping() -> str:
        return await p.chat(
            [
                {"role": "system", "content": "Rispondi in italiano, massimo 2 frasi."},
                {
                    "role": "user",
                    "content": "Conferma che sei Gemini su Vertex AI e che le credenziali ADC funzionano.",
                },
            ]
        )

    print("=== VERTEX DIRECT ===")
    print(asyncio.run(ping()))
    print("=== RESULT: PASS ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("=== RESULT: FAIL ===")
        print(type(exc).__name__ + ":", exc)
        raise SystemExit(1) from exc
