"""
Telegram channel for TAUROS — same orchestrator + per-user memory.

Usage:
  set TAUROS_TELEGRAM_BOT_TOKEN=...
  tauros telegram

Linking:
  In Telegram: /start <session_token>  or  /link <session_token>
  Without link, auto-creates account tg_<chat_id> with persistent memory.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

import httpx

from .auth import AuthService, hash_password
from .models import ChatRequest
from .settings import Settings

logger = logging.getLogger("tauros.telegram")

TG_API = "https://api.telegram.org"


class TelegramBot:
    def __init__(
        self,
        settings: Settings,
        *,
        orchestrator: Any,
        auth: AuthService,
        db: Any,
    ):
        self.settings = settings
        self.orchestrator = orchestrator
        self.auth = auth
        self.db = db
        self.token = (settings.telegram_bot_token or "").strip()
        self.offset = 0
        if not self.token:
            raise RuntimeError("TAUROS_TELEGRAM_BOT_TOKEN non configurato")

    def _url(self, method: str) -> str:
        return f"{TG_API}/bot{self.token}/{method}"

    async def api(self, method: str, **payload: Any) -> Any:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(self._url(method), json=payload)
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")
            return data.get("result")

    async def send_message(self, chat_id: int, text: str) -> None:
        chunk = (text or "(vuoto)")[:4000]
        await self.api("sendMessage", chat_id=chat_id, text=chunk)

    def _ensure_telegram_user(self, chat_id: int, username: str | None) -> dict:
        linked = self.db.get_user_by_telegram(chat_id)
        if linked:
            return linked
        uname = f"tg_{chat_id}"
        existing = self.db.get_user_by_username(uname)
        if existing:
            self.db.link_telegram_user(int(existing["id"]), chat_id)
            return existing
        salt, pw = hash_password(secrets.token_urlsafe(24))
        user_id = self.db.create_user(
            username=uname,
            password_salt=salt,
            password_hash=pw,
            is_guest=False,
            max_messages=None,
            role="user",
            display_name=username or uname,
        )
        self.db.link_telegram_user(user_id, chat_id)
        user = self.db.get_user(user_id)
        assert user
        return user

    def _link_token(self, chat_id: int, session_token: str) -> str:
        user = self.auth.resolve_bearer(
            f"Bearer {session_token.strip()}", self.settings.api_token
        )
        if not user:
            return "Token non valido o scaduto. Accedi su web e copia il token sessione."
        self.db.link_telegram_user(user.id, chat_id)
        return f"Collegato a account TAUROS: {user.username} (id {user.id})"

    async def handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat = msg.get("chat") or {}
        chat_id = int(chat.get("id"))
        text = (msg.get("text") or "").strip()
        if not text:
            await self.send_message(chat_id, "Invia un messaggio di testo.")
            return
        from_user = msg.get("from") or {}
        tg_username = from_user.get("username")

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                reply = self._link_token(chat_id, parts[1].strip())
            else:
                self._ensure_telegram_user(chat_id, tg_username)
                reply = (
                    "TAUROS online.\n"
                    "Comandi: /link <token_sessione> · /brief · /help\n"
                    "Scrivi pure: usa la memoria del tuo account collegato."
                )
            await self.send_message(chat_id, reply)
            return

        if text.startswith("/help"):
            await self.send_message(
                chat_id,
                "TAUROS Telegram\n"
                "/link TOKEN — collega sessione web\n"
                "/brief — continuità open loops/decisioni\n"
                "Altri messaggi → chat con memoria e policy.",
            )
            return

        if text.startswith("/link"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await self.send_message(chat_id, "Uso: /link <token_sessione_tauros>")
                return
            await self.send_message(chat_id, self._link_token(chat_id, parts[1]))
            return

        if text.startswith("/brief"):
            user_row = self._ensure_telegram_user(chat_id, tg_username)
            uid = int(user_row["id"])
            brief = self.orchestrator.build_brief(uid, is_operator=False)
            lines = [brief.get("narrative", "Brief"), ""]
            for loop in brief.get("open_loops", [])[:5]:
                lines.append(f"• loop: {loop.get('content', '')[:120]}")
            for d in brief.get("decisions_open", [])[:5]:
                lines.append(f"• decisione: {d.get('title', '')[:120]}")
            await self.send_message(chat_id, "\n".join(lines) or "Niente in agenda.")
            return

        user_row = self._ensure_telegram_user(chat_id, tg_username)
        uid = int(user_row["id"])
        role = str(user_row.get("role") or "user")
        try:
            result = await self.orchestrator.chat(
                ChatRequest(
                    message=text,
                    session_id=f"tg_{chat_id}",
                    use_tools=True,
                    auto_memory=True,
                ),
                user_id=uid,
                role=role,
            )
            await self.send_message(chat_id, result.answer)
        except Exception as exc:  # noqa: BLE001
            logger.exception("telegram chat failed")
            error_ref = secrets.token_hex(6)
            logger.error("telegram chat error_ref=%s detail=%s", error_ref, exc)
            await self.send_message(
                chat_id,
                "TAUROS non ha potuto completare il messaggio. "
                f"Riferimento errore: {error_ref}",
            )

    async def run_polling(self) -> None:
        logger.info("Telegram bot polling avviato")
        me = await self.api("getMe")
        logger.info("bot @%s", (me or {}).get("username"))
        while True:
            try:
                updates = await self.api(
                    "getUpdates",
                    offset=self.offset,
                    timeout=25,
                    allowed_updates=["message"],
                )
                for upd in updates or []:
                    self.offset = int(upd["update_id"]) + 1
                    await self.handle_update(upd)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("telegram poll error: %s", exc)
                await asyncio.sleep(3)


def run_telegram_bot() -> None:
    from .api import auth_service, db, orchestrator
    from .settings import settings

    if not settings.telegram_bot_token:
        raise SystemExit("Configura TAUROS_TELEGRAM_BOT_TOKEN nel .env")
    bot = TelegramBot(settings, orchestrator=orchestrator, auth=auth_service, db=db)
    asyncio.run(bot.run_polling())
