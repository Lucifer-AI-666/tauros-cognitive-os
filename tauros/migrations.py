"""Numbered SQLite migrations with backup + integrity checks."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("tauros.migrations")

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_initial",
        """
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          rationale TEXT NOT NULL,
          outcome TEXT,
          status TEXT NOT NULL DEFAULT 'open',
          revisit_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_type TEXT NOT NULL,
          actor TEXT NOT NULL,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          content TEXT NOT NULL,
          kind TEXT NOT NULL,
          importance INTEGER NOT NULL DEFAULT 5,
          tags_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1
        );
        """,
    ),
    (
        "002_live_memory",
        """
        -- Columns added idempotently by runner helpers when missing.
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
          content, tags, kind, content='memories', content_rowid='id',
          tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
          INSERT INTO memories_fts(rowid, content, tags, kind)
          VALUES (new.id, new.content, new.tags_json, new.kind);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
          INSERT INTO memories_fts(memories_fts, rowid, content, tags, kind)
          VALUES ('delete', old.id, old.content, old.tags_json, old.kind);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
          INSERT INTO memories_fts(memories_fts, rowid, content, tags, kind)
          VALUES ('delete', old.id, old.content, old.tags_json, old.kind);
          INSERT INTO memories_fts(rowid, content, tags, kind)
          VALUES (new.id, new.content, new.tags_json, new.kind);
        END;
        """,
    ),
    (
        "003_hardening",
        """
        -- content_hash / provenance columns added by helper when missing.
        CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
        CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(content_hash);
        CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
        """,
    ),
    (
        "004_users",
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          display_name TEXT,
          password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          is_guest INTEGER NOT NULL DEFAULT 0,
          role TEXT NOT NULL DEFAULT 'user',
          message_count INTEGER NOT NULL DEFAULT 0,
          max_messages INTEGER,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
          token TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id);
        """,
    ),
    (
        "005_telegram",
        """
        CREATE TABLE IF NOT EXISTS telegram_links (
          telegram_chat_id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_telegram_user ON telegram_links(user_id);
        """,
    ),
    (
        "006_audit_chain",
        """
        -- prev_hash / row_hash added by _ensure_columns when missing.
        CREATE INDEX IF NOT EXISTS idx_audit_id ON audit(id);
        """,
    ),
]


@dataclass
class MigrationResult:
    applied: list[str]
    backup_path: str | None
    integrity_ok: bool


class MigrationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _ensure_columns(con: sqlite3.Connection) -> None:
    mem_cols = _table_columns(con, "memories")
    if not mem_cols:
        return
    additions = {
        "source": "TEXT NOT NULL DEFAULT 'user'",
        "confidence": "REAL NOT NULL DEFAULT 1.0",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "access_count": "INTEGER NOT NULL DEFAULT 0",
        "last_accessed_at": "TEXT",
        "content_hash": "TEXT",
        "content_normalized": "TEXT",
        "supersedes_id": "INTEGER",
        "last_confirmed_at": "TEXT",
        "source_turn_id": "TEXT",
        "source_file": "TEXT",
        "user_id": "INTEGER",
    }
    for name, ddl in additions.items():
        if name not in mem_cols:
            con.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")

    dcols = _table_columns(con, "decisions")
    for name, ddl in {
        "status": "TEXT NOT NULL DEFAULT 'open'",
        "revisit_at": "TEXT",
        "updated_at": "TEXT",
        "user_id": "INTEGER",
    }.items():
        if name not in dcols:
            con.execute(f"ALTER TABLE decisions ADD COLUMN {name} {ddl}")
    if dcols or _table_columns(con, "decisions"):
        con.execute("UPDATE decisions SET updated_at=COALESCE(updated_at, created_at)")

    msg_cols = _table_columns(con, "messages")
    if msg_cols and "user_id" not in msg_cols:
        con.execute("ALTER TABLE messages ADD COLUMN user_id INTEGER")

    audit_cols = _table_columns(con, "audit")
    if audit_cols:
        if "prev_hash" not in audit_cols:
            con.execute("ALTER TABLE audit ADD COLUMN prev_hash TEXT")
        if "row_hash" not in audit_cols:
            con.execute("ALTER TABLE audit ADD COLUMN row_hash TEXT")


def integrity_check(con: sqlite3.Connection) -> bool:
    row = con.execute("PRAGMA integrity_check").fetchone()
    return bool(row and row[0] == "ok")


def backup_database(db_path: Path, backup_dir: Path | None = None) -> Path | None:
    if not db_path.exists():
        return None
    target_dir = backup_dir or (db_path.parent / "backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = target_dir / f"{db_path.stem}.{stamp}.bak"
    shutil.copy2(db_path, dest)
    # Also copy WAL/SHM if present for consistency best-effort
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            shutil.copy2(side, target_dir / f"{side.name}.{stamp}.bak")
    return dest


def _bootstrap_migration_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          applied_at TEXT NOT NULL
        )
        """
    )


def _applied(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _stamp_legacy_if_needed(con: sqlite3.Connection) -> None:
    """If DB already has memories from pre-migration builds, stamp earlier steps."""
    applied = _applied(con)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "memories" in tables and "001_initial" not in applied:
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            ("001_initial", _now()),
        )
    if "memories_fts" in tables and "002_live_memory" not in applied:
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            ("002_live_memory", _now()),
        )


def run_migrations(db_path: Path, backup: bool = True) -> MigrationResult:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if backup and db_path.exists():
        backup_path = backup_database(db_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    applied_now: list[str] = []
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        _bootstrap_migration_table(con)
        _stamp_legacy_if_needed(con)
        done = _applied(con)

        for name, sql in MIGRATIONS:
            if name in done:
                continue
            try:
                # Columns first so later migrations can index them safely.
                if name != "001_initial":
                    # 001 creates base tables; ensure it runs before column helper.
                    tables = {
                        r[0]
                        for r in con.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    if "memories" not in tables:
                        con.executescript(dict(MIGRATIONS)["001_initial"])
                con.executescript(sql)
                _ensure_columns(con)
                if name == "002_live_memory":
                    try:
                        con.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
                    except sqlite3.OperationalError:
                        pass
                if name == "003_hardening":
                    rows = con.execute(
                        "SELECT id, content FROM memories WHERE content_hash IS NULL OR content_hash=''"
                    ).fetchall()
                    import hashlib

                    for row in rows:
                        norm = " ".join(row["content"].casefold().split())
                        digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()
                        con.execute(
                            "UPDATE memories SET content_normalized=?, content_hash=? WHERE id=?",
                            (norm, digest, row["id"]),
                        )
                if name == "006_audit_chain":
                    from tauros.audit_chain import backfill_audit_chain

                    backfill_audit_chain(con)
                if name == "004_users":
                    # Columns first (via _ensure_columns above), then indexes.
                    con.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_decisions_user ON decisions(user_id)")
                if not integrity_check(con):
                    raise MigrationError(f"Integrity check fallita dopo {name}")
                con.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                    (name, _now()),
                )
                con.commit()
                applied_now.append(name)
                logger.info("migration applied: %s", name)
            except Exception as exc:
                con.rollback()
                if backup_path and backup_path.exists():
                    con.close()
                    shutil.copy2(backup_path, db_path)
                    raise MigrationError(
                        f"Migrazione {name} fallita, backup ripristinato da {backup_path}: {exc}"
                    ) from exc
                raise MigrationError(f"Migrazione {name} fallita: {exc}") from exc

        # Always ensure columns for partially upgraded DBs
        _ensure_columns(con)
        con.commit()
        ok = integrity_check(con)
        if not ok:
            raise MigrationError("Integrity check fallita a fine migrazioni")
        return MigrationResult(
            applied=applied_now,
            backup_path=str(backup_path) if backup_path else None,
            integrity_ok=ok,
        )
    finally:
        con.close()


def current_schema_version(db_path: Path) -> list[str]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    try:
        _bootstrap_migration_table(con)
        rows = con.execute("SELECT name FROM schema_migrations ORDER BY id").fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()
