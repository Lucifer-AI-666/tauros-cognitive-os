"""User authentication: register, login, guest sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .database import Database


PBKDF2_ROUNDS = 200_000
SESSION_DAYS = 30
GUEST_SESSION_HOURS = 24
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})


def is_loopback_host(host: str | None) -> bool:
    value = (host or "").strip().lower().strip("[]")
    return value in LOOPBACK_HOSTS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


@dataclass
class AuthUser:
    id: int
    username: str
    is_guest: bool
    is_operator: bool
    message_count: int
    max_messages: int | None
    role: str

    @property
    def messages_remaining(self) -> int | None:
        if self.max_messages is None:
            return None
        return max(0, self.max_messages - self.message_count)


class AuthService:
    def __init__(self, db: Database, guest_max_messages: int = 20):
        self.db = db
        self.guest_max_messages = guest_max_messages

    def ensure_owner(self, owner_name: str = "owner") -> dict:
        """Bootstrap default owner account (no password login; used by operator token)."""
        existing = self.db.get_user_by_username("owner")
        if existing:
            return existing
        salt, pw = hash_password(secrets.token_urlsafe(24))
        user_id = self.db.create_user(
            username="owner",
            password_salt=salt,
            password_hash=pw,
            is_guest=False,
            max_messages=None,
            role="owner",
            display_name=owner_name,
        )
        # Attach orphan memories/messages to owner
        self.db.assign_orphan_data_to_user(user_id)
        return self.db.get_user(user_id)  # type: ignore[return-value]

    def register(self, username: str, password: str) -> dict:
        username = username.strip().lower()
        if len(username) < 3 or len(username) > 40:
            raise ValueError("Username tra 3 e 40 caratteri")
        if not username.replace("_", "").replace(".", "").isalnum():
            raise ValueError("Username: solo lettere, numeri, . e _")
        if len(password) < 8:
            raise ValueError("Password minimo 8 caratteri")
        if self.db.get_user_by_username(username):
            raise ValueError("Username già registrato")
        salt, pw = hash_password(password)
        user_id = self.db.create_user(
            username=username,
            password_salt=salt,
            password_hash=pw,
            is_guest=False,
            max_messages=None,
            role="user",
            display_name=username,
        )
        token = self.db.create_session(user_id, expires_at=_now() + timedelta(days=SESSION_DAYS))
        user = self.db.get_user(user_id)
        assert user
        return {"token": token, "user": self._public_user(user)}

    def login(self, username: str, password: str) -> dict:
        username = username.strip().lower()
        user = self.db.get_user_by_username(username)
        if not user or user.get("is_guest"):
            raise ValueError("Credenziali non valide")
        if not verify_password(password, user["password_salt"], user["password_hash"]):
            raise ValueError("Credenziali non valide")
        token = self.db.create_session(user["id"], expires_at=_now() + timedelta(days=SESSION_DAYS))
        return {"token": token, "user": self._public_user(user)}

    def local_owner_session(self, owner_name: str = "Owner") -> dict:
        """Session for the machine owner. Caller must verify loopback first."""
        owner = self.ensure_owner(owner_name)
        token = self.db.create_session(int(owner["id"]), expires_at=_now() + timedelta(days=SESSION_DAYS))
        public = self._public_user(owner)
        public["is_operator"] = True
        return {"token": token, "user": public}

    def guest(self) -> dict:
        uname = f"guest_{secrets.token_hex(4)}"
        salt, pw = hash_password(secrets.token_urlsafe(16))
        user_id = self.db.create_user(
            username=uname,
            password_salt=salt,
            password_hash=pw,
            is_guest=True,
            max_messages=self.guest_max_messages,
            role="guest",
            display_name="Ospite",
        )
        token = self.db.create_session(
            user_id, expires_at=_now() + timedelta(hours=GUEST_SESSION_HOURS)
        )
        user = self.db.get_user(user_id)
        assert user
        return {"token": token, "user": self._public_user(user)}

    def resolve_bearer(self, authorization: str | None, api_token: str) -> AuthUser | None:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        raw = authorization.split(" ", 1)[1].strip()
        if not raw:
            return None
        # Operator system token → owner user
        if api_token and hmac.compare_digest(raw, api_token):
            owner = self.ensure_owner()
            return AuthUser(
                id=int(owner["id"]),
                username=owner["username"],
                is_guest=False,
                is_operator=True,
                message_count=int(owner.get("message_count") or 0),
                max_messages=None,
                role="operator",
            )
        session = self.db.get_session(raw)
        if not session:
            return None
        exp = session.get("expires_at")
        if exp:
            try:
                if datetime.fromisoformat(exp) < _now():
                    self.db.delete_session(raw)
                    return None
            except ValueError:
                pass
        user = self.db.get_user(int(session["user_id"]))
        if not user or not user.get("active", 1):
            return None
        return AuthUser(
            id=int(user["id"]),
            username=user["username"],
            is_guest=bool(user.get("is_guest")),
            is_operator=user.get("role") in {"owner", "operator"},
            message_count=int(user.get("message_count") or 0),
            max_messages=user.get("max_messages"),
            role=user.get("role") or "user",
        )

    def logout(self, token: str) -> None:
        self.db.delete_session(token)

    def check_can_chat(self, user: AuthUser) -> None:
        if user.max_messages is not None and user.message_count >= user.max_messages:
            raise PermissionError(
                f"Limite ospite raggiunto ({user.max_messages} messaggi). "
                "Registrati per memoria persistente illimitata."
            )

    def bump_message(self, user_id: int) -> None:
        self.db.increment_message_count(user_id)

    @staticmethod
    def _public_user(user: dict) -> dict:
        max_m = user.get("max_messages")
        count = int(user.get("message_count") or 0)
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "is_guest": bool(user.get("is_guest")),
            "role": user.get("role") or "user",
            "message_count": count,
            "max_messages": max_m,
            "messages_remaining": None if max_m is None else max(0, int(max_m) - count),
        }
