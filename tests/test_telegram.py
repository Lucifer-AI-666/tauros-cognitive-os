"""Telegram channel must not leak exception bodies to the user."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tauros.security import generate_api_token
from tauros.settings import Settings
from tauros.telegram_bot import TelegramBot


class _FailingOrch:
    async def chat(self, *args, **kwargs):
        raise RuntimeError("segreto-XYZ token=abc")


class _Db:
    def get_user_by_telegram(self, chat_id: int):
        return {"id": 1, "role": "user", "username": "tg_1"}


def test_telegram_chat_hides_exception(tmp_path: Path) -> None:
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        database_path=tmp_path / "t.db",
        workspace_allowlist=str(tmp_path / "ws"),
        telegram_bot_token="dummy-token-not-a-secret",
        host="127.0.0.1",
        allow_lan_bind=False,
    )
    sent: list[str] = []
    bot = TelegramBot(settings, orchestrator=_FailingOrch(), auth=object(), db=_Db())

    async def capture(chat_id: int, text: str) -> None:
        sent.append(text)

    bot.send_message = capture  # type: ignore[method-assign]

    asyncio.run(
        bot.handle_update(
            {"message": {"chat": {"id": 42}, "text": "ciao", "from": {"username": "u"}}}
        )
    )
    assert sent, "nessun messaggio Telegram inviato"
    body = sent[-1]
    assert "segreto-XYZ" not in body
    assert "token=abc" not in body
    assert "Errore TAUROS:" not in body
    assert "Riferimento errore:" in body
