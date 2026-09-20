from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .audit_chain import GENESIS, audit_row_hash, verify_audit_chain
from .migrations import run_migrations
from .security import content_hash, normalize_memory_text, redact_obj


class Database:
    def __init__(self, path: Path, run_migrate: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if run_migrate:
            run_migrations(self.path, backup=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_memory(
        self,
        content: str,
        kind: str,
        importance: int,
        tags: list[str],
        source: str,
        confidence: float,
        status: str,
        supersedes_id: int | None = None,
        source_turn_id: str | None = None,
        source_file: str | None = None,
        user_id: int | None = None,
    ) -> int:
        now = self.now()
        norm = normalize_memory_text(content)
        digest = content_hash(content)
        active = 0 if status in {"forgotten", "expired"} else 1
        confirmed = now if status == "active" else None
        with self.connect() as con:
            cur = con.execute(
                """INSERT INTO memories(
                    content, kind, importance, tags_json, source, confidence, status,
                    content_hash, content_normalized, supersedes_id, source_turn_id, source_file,
                    last_confirmed_at, created_at, updated_at, active, user_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    content,
                    kind,
                    importance,
                    json.dumps(tags, ensure_ascii=False),
                    source,
                    confidence,
                    status,
                    digest,
                    norm,
                    supersedes_id,
                    source_turn_id,
                    source_file,
                    confirmed,
                    now,
                    now,
                    active,
                    user_id,
                ),
            )
            new_id = int(cur.lastrowid)
            if supersedes_id:
                con.execute(
                    "UPDATE memories SET status='superseded', updated_at=? WHERE id=? AND status='active' AND (user_id IS ? OR ? IS NULL)",
                    (now, supersedes_id, user_id, user_id),
                )
            return new_id

    def find_by_hash(self, digest: str, include_candidates: bool = True, user_id: int | None = None) -> dict | None:
        statuses = ("active", "candidate") if include_candidates else ("active",)
        placeholders = ",".join("?" for _ in statuses)
        user_clause = "AND user_id=?" if user_id is not None else ""
        params: list[object] = [digest, *statuses]
        if user_id is not None:
            params.append(user_id)
        with self.connect() as con:
            row = con.execute(
                f"""SELECT * FROM memories
                    WHERE content_hash=? AND active=1 AND status IN ({placeholders}) {user_clause}
                    ORDER BY id DESC LIMIT 1""",
                params,
            ).fetchone()
        return self._memory_row(row) if row else None

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = ["".join(ch for ch in t if ch.isalnum() or ch in "_-'") for t in query.split()]
        tokens = [t for t in tokens if len(t) > 1][:12]
        return " OR ".join(f'"{t}"*' for t in tokens)


    def search_memories(
        self,
        query: str,
        limit: int = 8,
        include_candidates: bool = False,
        user_id: int | None = None,
    ) -> list[dict]:
        allowed = ("active", "candidate") if include_candidates else ("active",)
        placeholders = ",".join("?" for _ in allowed)
        fts = self._fts_query(query)
        user_sql = " AND m.user_id=?" if user_id is not None else ""
        user_sql_plain = " AND user_id=?" if user_id is not None else ""
        with self.connect() as con:
            if fts:
                try:
                    params: list[object] = [fts, *allowed]
                    if user_id is not None:
                        params.append(user_id)
                    params.append(limit)
                    rows = con.execute(
                        f"""SELECT m.*, bm25(memories_fts) AS lexical_rank
                        FROM memories_fts JOIN memories m ON m.id=memories_fts.rowid
                        WHERE memories_fts MATCH ? AND m.active=1 AND m.status IN ({placeholders}){user_sql}
                        ORDER BY (bm25(memories_fts) - m.importance * 0.35 - m.confidence * 0.8) ASC,
                                 m.updated_at DESC LIMIT ?""",
                        params,
                    ).fetchall()
                except sqlite3.OperationalError:
                    params = [*allowed]
                    if user_id is not None:
                        params.append(user_id)
                    params.append(limit)
                    rows = con.execute(
                        f"SELECT * FROM memories WHERE active=1 AND status IN ({placeholders}){user_sql_plain} "
                        "ORDER BY importance DESC, confidence DESC, updated_at DESC LIMIT ?",
                        params,
                    ).fetchall()
            else:
                params = [*allowed]
                if user_id is not None:
                    params.append(user_id)
                params.append(limit)
                rows = con.execute(
                    f"SELECT * FROM memories WHERE active=1 AND status IN ({placeholders}){user_sql_plain} "
                    "ORDER BY importance DESC, confidence DESC, updated_at DESC LIMIT ?",
                    params,
                ).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                q = ",".join("?" for _ in ids)
                con.execute(
                    f"UPDATE memories SET access_count=access_count+1, last_accessed_at=? WHERE id IN ({q})",
                    (self.now(), *ids),
                )
        return [self._memory_row(r) for r in rows]

    def list_memories(
        self,
        limit: int = 100,
        kind: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        user_id: int | None = None,
    ) -> list[dict]:
        where = ["active=1"]
        params: list[object] = []
        if user_id is not None:
            where.append("user_id=?")
            params.append(user_id)
        if kind:
            where.append("kind=?")
            params.append(kind)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(statuses)
        elif status:
            where.append("status=?")
            params.append(status)
        params.append(limit)
        with self.connect() as con:
            rows = con.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(where)} "
                "ORDER BY importance DESC, updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._memory_row(r) for r in rows]

    def update_memory(self, memory_id: int, updates: dict, user_id: int | None = None) -> dict | None:
        if user_id is not None and not self.get_memory(memory_id, user_id=user_id):
            return None
        allowed = {
            "content",
            "kind",
            "importance",
            "confidence",
            "status",
            "supersedes_id",
            "source_turn_id",
            "source_file",
        }
        fields, params = [], []
        for key, value in updates.items():
            if key == "tags":
                fields.append("tags_json=?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif key in allowed and value is not None:
                fields.append(f"{key}=?")
                params.append(value)
        if "content" in updates and updates["content"] is not None:
            fields.append("content_normalized=?")
            params.append(normalize_memory_text(updates["content"]))
            fields.append("content_hash=?")
            params.append(content_hash(updates["content"]))
        if not fields:
            return self.get_memory(memory_id, user_id=user_id)
        fields.append("updated_at=?")
        params.append(self.now())
        if updates.get("status") is not None:
            status = updates["status"]
            fields.append("active=?")
            params.append(0 if status in {"forgotten", "expired"} else 1)
            if status == "active":
                fields.append("last_confirmed_at=?")
                params.append(self.now())
        params.append(memory_id)
        with self.connect() as con:
            if user_id is not None:
                con.execute(
                    f"UPDATE memories SET {','.join(fields)} WHERE id=? AND user_id=?",
                    (*params, user_id),
                )
            else:
                con.execute(f"UPDATE memories SET {','.join(fields)} WHERE id=?", params)
        return self.get_memory(memory_id, user_id=user_id)

    def get_memory(self, memory_id: int, user_id: int | None = None) -> dict | None:
        with self.connect() as con:
            if user_id is not None:
                row = con.execute(
                    "SELECT * FROM memories WHERE id=? AND user_id=?", (memory_id, user_id)
                ).fetchone()
            else:
                row = con.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory_row(row) if row else None

    def deactivate_memory(self, memory_id: int, user_id: int | None = None) -> bool:
        with self.connect() as con:
            if user_id is not None:
                cur = con.execute(
                    "UPDATE memories SET active=0, status='forgotten', updated_at=? WHERE id=? AND user_id=?",
                    (self.now(), memory_id, user_id),
                )
            else:
                cur = con.execute(
                    "UPDATE memories SET active=0, status='forgotten', updated_at=? WHERE id=?",
                    (self.now(), memory_id),
                )
            return cur.rowcount > 0

    def add_message(self, session_id: str, role: str, content: str, user_id: int | None = None) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO messages(session_id, role, content, created_at, user_id) VALUES (?,?,?,?,?)",
                (session_id, role, content, self.now(), user_id),
            )

    def history(self, session_id: str, limit: int = 20, user_id: int | None = None) -> list[dict]:
        with self.connect() as con:
            if user_id is not None:
                rows = con.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, user_id, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def add_decision(
        self,
        title: str,
        rationale: str,
        outcome: str | None,
        status: str,
        revisit_at: str | None,
        user_id: int | None = None,
    ) -> int:
        now = self.now()
        with self.connect() as con:
            cur = con.execute(
                """INSERT INTO decisions(title, rationale, outcome, status, revisit_at, created_at, updated_at, user_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (title, rationale, outcome, status, revisit_at, now, now, user_id),
            )
            return int(cur.lastrowid)

    def list_decisions(self, limit: int = 100, status: str | None = None, user_id: int | None = None) -> list[dict]:
        with self.connect() as con:
            if user_id is not None and status:
                rows = con.execute(
                    "SELECT * FROM decisions WHERE status=? AND user_id=? ORDER BY created_at DESC LIMIT ?",
                    (status, user_id, limit),
                ).fetchall()
            elif user_id is not None:
                rows = con.execute(
                    "SELECT * FROM decisions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            elif status:
                rows = con.execute(
                    "SELECT * FROM decisions WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_decision(self, decision_id: int, user_id: int | None = None) -> dict | None:
        with self.connect() as con:
            if user_id is not None:
                row = con.execute(
                    "SELECT * FROM decisions WHERE id=? AND user_id=?",
                    (decision_id, user_id),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT * FROM decisions WHERE id=?", (decision_id,)
                ).fetchone()
        return dict(row) if row else None

    def update_decision(
        self, decision_id: int, fields: dict, user_id: int | None = None
    ) -> dict | None:
        allowed = {"title", "rationale", "outcome", "status", "revisit_at"}
        payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not payload:
            return self.get_decision(decision_id, user_id=user_id)
        payload["updated_at"] = self.now()
        sets = ", ".join(f"{k}=?" for k in payload)
        values = list(payload.values())
        with self.connect() as con:
            if user_id is not None:
                cur = con.execute(
                    f"UPDATE decisions SET {sets} WHERE id=? AND user_id=?",
                    (*values, decision_id, user_id),
                )
            else:
                cur = con.execute(
                    f"UPDATE decisions SET {sets} WHERE id=?",
                    (*values, decision_id),
                )
            if cur.rowcount == 0:
                return None
        return self.get_decision(decision_id, user_id=user_id)

    def link_telegram_user(self, user_id: int, telegram_chat_id: int) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO telegram_links(user_id, telegram_chat_id, created_at, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(telegram_chat_id) DO UPDATE SET
                     user_id=excluded.user_id,
                     updated_at=excluded.updated_at""",
                (user_id, int(telegram_chat_id), self.now(), self.now()),
            )

    def get_user_by_telegram(self, telegram_chat_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                """SELECT u.* FROM telegram_links t
                   JOIN users u ON u.id = t.user_id
                   WHERE t.telegram_chat_id=?""",
                (int(telegram_chat_id),),
            ).fetchone()
        return dict(row) if row else None

    def audit(self, event_type: str, actor: str, details: dict) -> None:
        safe = redact_obj(details)
        details_json = json.dumps(safe, ensure_ascii=False)
        created_at = self.now()
        with self.connect() as con:
            last = con.execute(
                "SELECT row_hash FROM audit WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev = last["row_hash"] if last and last["row_hash"] else GENESIS
            digest = audit_row_hash(prev, event_type, actor, details_json, created_at)
            con.execute(
                "INSERT INTO audit(event_type, actor, details_json, created_at, prev_hash, row_hash) "
                "VALUES (?,?,?,?,?,?)",
                (event_type, actor, details_json, created_at, prev, digest),
            )

    def verify_audit(self) -> dict:
        with self.connect() as con:
            return verify_audit_chain(con)

    def list_audit(self, limit: int = 100) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result

    def export_all(self) -> dict:
        with self.connect() as con:
            result = {}
            for table in ["users", "memories", "messages", "decisions", "audit", "schema_migrations"]:
                try:
                    rows = con.execute(f"SELECT * FROM {table}").fetchall()
                    result[table] = [dict(r) for r in rows]
                except sqlite3.Error:
                    result[table] = []
            return result

    def create_user(
        self,
        username: str,
        password_salt: str,
        password_hash: str,
        is_guest: bool,
        max_messages: int | None,
        role: str,
        display_name: str | None = None,
    ) -> int:
        now = self.now()
        with self.connect() as con:
            cur = con.execute(
                """INSERT INTO users(username, display_name, password_salt, password_hash, is_guest, role,
                   message_count, max_messages, active, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,0,?,1,?,?)""",
                (
                    username,
                    display_name or username,
                    password_salt,
                    password_hash,
                    1 if is_guest else 0,
                    role,
                    max_messages,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_user(self, user_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

    def create_session(self, user_id: int, expires_at) -> str:
        import secrets

        token = secrets.token_urlsafe(32)
        exp = expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)
        with self.connect() as con:
            con.execute(
                "INSERT INTO auth_sessions(token, user_id, expires_at, created_at) VALUES (?,?,?,?)",
                (token, user_id, exp, self.now()),
            )
        return token

    def get_session(self, token: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM auth_sessions WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM auth_sessions WHERE token=?", (token,))

    def increment_message_count(self, user_id: int) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE users SET message_count=message_count+1, updated_at=? WHERE id=?",
                (self.now(), user_id),
            )

    def assign_orphan_data_to_user(self, user_id: int) -> None:
        with self.connect() as con:
            con.execute("UPDATE memories SET user_id=? WHERE user_id IS NULL", (user_id,))
            con.execute("UPDATE messages SET user_id=? WHERE user_id IS NULL", (user_id,))
            con.execute("UPDATE decisions SET user_id=? WHERE user_id IS NULL", (user_id,))


    def integrity_ok(self) -> bool:
        with self.connect() as con:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")

    @staticmethod
    def _memory_row(row: sqlite3.Row) -> dict:
        item = dict(row)
        tags_raw = item.pop("tags_json", "[]")
        try:
            item["tags"] = json.loads(tags_raw) if tags_raw is not None else []
        except json.JSONDecodeError:
            item["tags"] = []
        item.pop("lexical_rank", None)
        return item
