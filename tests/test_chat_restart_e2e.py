"""End-to-end API persistence: authentication, chat, process restart, history.

No external model, network service, or user credentials required. Each phase runs
in a separate Python process and shares only a temporary SQLite database.
"""

import os
import subprocess
import sys
import textwrap


_PHASE = textwrap.dedent("""
    import os
    from fastapi.testclient import TestClient
    from tauros.api import app, orchestrator, db

    class FakeProvider:
        async def chat(self, messages):
            history = [m["content"] for m in messages if m["role"] == "user"]
            if os.environ["TAUROS_TEST_PHASE"] == "second":
                assert "prima domanda" in history, f"History lost across restart: {history!r}"
                assert "seconda domanda" in history
                return "seconda risposta"
            assert history[-1] == "prima domanda"
            return "prima risposta"

    orchestrator.provider = FakeProvider()

    with TestClient(app) as client:
        if os.environ["TAUROS_TEST_PHASE"] == "first":
            registration = client.post("/auth/register", json={
                "username": "restartcheck", "password": "unique-test-password-123"
            })
            assert registration.status_code == 200, registration.text
            token = registration.json()["token"]
            message = "prima domanda"
            expected = "prima risposta"
        else:
            login = client.post("/auth/login", json={
                "username": "restartcheck", "password": "unique-test-password-123"
            })
            assert login.status_code == 200, login.text
            token = login.json()["token"]
            message = "seconda domanda"
            expected = "seconda risposta"

        headers = {"Authorization": f"Bearer {token}"}
        response = client.post("/chat", headers=headers, json={
            "message": message, "session_id": "same-session",
            "use_tools": False, "auto_memory": False,
        })
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == expected, response.text
        me = client.get("/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        user_id = me.json()["id"]
        rows = db.history(f"u{user_id}:same-session", 10, user_id=user_id)
        expected_messages = 2 if os.environ["TAUROS_TEST_PHASE"] == "first" else 4
        assert len(rows) == expected_messages, rows
        assert rows[-2]["content"] == message, rows
        assert rows[-1]["content"] == expected, rows
""")


def test_authenticated_chat_survives_process_restart(tmp_path):
    env = os.environ.copy()
    env.update(
        TAUROS_DATABASE_PATH=str(tmp_path / "chat.db"),
        TAUROS_API_TOKEN="strong-test-token-Alpha1234567890!",
        TAUROS_PROVIDER="ollama",  # fake provider is injected, no network
        TAUROS_SECURITY_MODE="locked",  # no filesystem tools or planner calls
        TAUROS_SKIP_TOKEN_CHECK="false",
        TAUROS_ALLOW_OPEN_REGISTRATION="true",
        TAUROS_LOCAL_CLICK_LOGIN="false",
    )
    for phase in ("first", "second"):
        env["TAUROS_TEST_PHASE"] = phase
        result = subprocess.run(
            [sys.executable, "-c", _PHASE],
            check=False, env=env, capture_output=True, text=True, timeout=45,
        )
        assert result.returncode == 0, (
            f"Phase {phase} failed (exit={result.returncode}):\\n"
            f"stdout: {result.stdout}\\nstderr: {result.stderr}"
        )
