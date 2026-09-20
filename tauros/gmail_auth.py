"""Accesso con Gmail: OTP via email + Google Sign-In (ID token)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import httpx

from .auth import SESSION_DAYS, AuthService, hash_password
from .database import Database

logger = logging.getLogger("tauros.gmail_auth")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
OTP_TTL_SEC = 600
OTP_LEN = 6

# in-memory OTP store: email -> {code_hash, exp, attempts}
_otp_store: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email)))


def email_to_username(email: str) -> str:
    """Username stabile da email (SQLite users.username)."""
    e = normalize_email(email)
    # es. mario.rossi@gmail.com -> gmail_mario_rossi
    local, _, domain = e.partition("@")
    local = re.sub(r"[^a-z0-9._-]", "_", local)[:30]
    dom = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])[:12]
    return f"{dom}_{local}"[:40]


@dataclass
class GmailAuthConfig:
    google_client_id: str = ""
    gmail_user: str = ""  # mittente SMTP (il tuo Gmail)
    gmail_app_password: str = ""  # password app Google
    otp_debug: bool = True  # su localhost mostra/ritorna il codice
    allowed_domains: str = "gmail.com,googlemail.com"  # vuoto = tutti


class GmailAuthService:
    def __init__(self, db: Database, auth: AuthService, cfg: GmailAuthConfig):
        self.db = db
        self.auth = auth
        self.cfg = cfg

    def _domain_ok(self, email: str) -> bool:
        domains = [d.strip().lower() for d in (self.cfg.allowed_domains or "").split(",") if d.strip()]
        if not domains:
            return True
        return normalize_email(email).split("@")[-1] in domains

    def request_otp(self, email: str) -> dict[str, Any]:
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValueError("Email non valida")
        if not self._domain_ok(email):
            raise ValueError("Usa un indirizzo Gmail (@gmail.com)")

        code = "".join(secrets.choice("0123456789") for _ in range(OTP_LEN))
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        _otp_store[email] = {
            "hash": code_hash,
            "exp": time.time() + OTP_TTL_SEC,
            "attempts": 0,
        }

        sent = False
        send_error = None
        if self.cfg.gmail_user and self.cfg.gmail_app_password:
            try:
                self._send_gmail_otp(email, code)
                sent = True
            except Exception as exc:
                send_error = str(exc)
                logger.warning("SMTP Gmail fallito: %s", exc)
        else:
            send_error = "SMTP non configurato (TAUROS_GMAIL_USER / TAUROS_GMAIL_APP_PASSWORD)"

        out: dict[str, Any] = {
            "ok": True,
            "email": email,
            "sent": sent,
            "expires_in": OTP_TTL_SEC,
            "message": (
                f"Codice inviato a {email}"
                if sent
                else "Codice generato. Controlla il box sotto (modalità locale) o configura Gmail SMTP."
            ),
        }
        # In locale mostriamo il codice così entri subito senza SMTP
        if self.cfg.otp_debug:
            out["debug_code"] = code
            out["debug_note"] = "Solo sviluppo locale: inserisci questo codice"
        if send_error and not sent:
            out["smtp_hint"] = send_error
        return out

    def _send_gmail_otp(self, to_email: str, code: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"TAUROS — codice di accesso {code}"
        msg["From"] = self.cfg.gmail_user
        msg["To"] = to_email
        msg.set_content(
            f"Il tuo codice di accesso TAUROS è:\n\n    {code}\n\n"
            f"Valido {OTP_TTL_SEC // 60} minuti. Se non sei stato tu, ignora questa email.\n"
        )
        # App password Gmail: smtp.gmail.com:587 TLS
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(self.cfg.gmail_user, self.cfg.gmail_app_password.replace(" ", ""))
            smtp.send_message(msg)

    def verify_otp(self, email: str, code: str) -> dict[str, Any]:
        email = normalize_email(email)
        code = (code or "").strip().replace(" ", "")
        entry = _otp_store.get(email)
        if not entry:
            raise ValueError("Nessun codice richiesto per questa email (richiedi di nuovo)")
        if time.time() > float(entry["exp"]):
            _otp_store.pop(email, None)
            raise ValueError("Codice scaduto — richiedine uno nuovo")
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        if entry["attempts"] > 8:
            _otp_store.pop(email, None)
            raise ValueError("Troppi tentativi — richiedi un nuovo codice")
        expect = entry["hash"]
        got = hashlib.sha256(code.encode()).hexdigest()
        if not hmac.compare_digest(expect, got):
            raise ValueError("Codice non corretto")
        _otp_store.pop(email, None)
        return self._login_or_create_email(email, provider="gmail_otp")

    def login_google_id_token(self, id_token: str) -> dict[str, Any]:
        """Verifica ID token Google Identity Services."""
        if not self.cfg.google_client_id:
            raise ValueError(
                "Google Sign-In non configurato. Imposta TAUROS_GOOGLE_CLIENT_ID in .env"
            )
        id_token = (id_token or "").strip()
        if not id_token:
            raise ValueError("id_token mancante")

        # Verifica via tokeninfo (semplice; ok per localhost)
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": id_token},
            )
        if r.status_code != 200:
            raise ValueError("Token Google non valido o scaduto")
        info = r.json()
        aud = info.get("aud") or info.get("azp")
        if aud != self.cfg.google_client_id:
            raise ValueError("Token Google: client_id non corrisponde")
        if info.get("email_verified") not in (True, "true", "1"):
            raise ValueError("Email Google non verificata")
        email = normalize_email(info.get("email") or "")
        if not email:
            raise ValueError("Email assente nel token Google")
        if not self._domain_ok(email):
            raise ValueError("Usa un account Gmail")
        name = info.get("name") or email.split("@")[0]
        return self._login_or_create_email(email, provider="google", display_name=name)

    def _login_or_create_email(
        self,
        email: str,
        provider: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        username = email_to_username(email)
        user = self.db.get_user_by_username(username)
        if not user:
            # prova anche username = email grezza se mai usata
            user = self.db.get_user_by_username(email)
        if not user:
            salt, pw = hash_password(secrets.token_urlsafe(24))
            user_id = self.db.create_user(
                username=username,
                password_salt=salt,
                password_hash=pw,
                is_guest=False,
                max_messages=None,
                role="user",
                display_name=display_name or email.split("@")[0],
            )
            # salva email in audit / opzionale colonna
            try:
                with self.db.connect() as con:
                    con.execute(
                        "UPDATE users SET display_name=COALESCE(NULLIF(display_name,''), ?) WHERE id=?",
                        (display_name or email, user_id),
                    )
            except Exception:
                pass
            self.db.audit(
                "auth_gmail_register",
                username,
                {"email": email, "provider": provider},
            )
            user = self.db.get_user(user_id)
        assert user
        token = self.db.create_session(
            int(user["id"]),
            expires_at=_now() + timedelta(days=SESSION_DAYS),
        )
        self.db.audit(
            "auth_gmail_login",
            user["username"],
            {"email": email, "provider": provider},
        )
        pub = AuthService._public_user(user)
        pub["email"] = email
        return {"token": token, "user": pub, "email": email}
