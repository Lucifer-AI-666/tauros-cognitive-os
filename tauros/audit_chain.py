"""Append-only audit hash chain (tamper evidence, not a blockchain)."""

from __future__ import annotations

import hashlib
import sqlite3

GENESIS = "0" * 64


def audit_row_hash(
    prev_hash: str,
    event_type: str,
    actor: str,
    details_json: str,
    created_at: str,
) -> str:
    payload = "\n".join([prev_hash, event_type, actor, details_json, created_at]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def backfill_audit_chain(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(audit)").fetchall()}
    if "row_hash" not in cols or "prev_hash" not in cols:
        return
    rows = con.execute(
        "SELECT id, event_type, actor, details_json, created_at, prev_hash, row_hash "
        "FROM audit ORDER BY id ASC"
    ).fetchall()
    prev = GENESIS
    for row in rows:
        computed = audit_row_hash(
            prev, row["event_type"], row["actor"], row["details_json"], row["created_at"]
        )
        if row["row_hash"] != computed or row["prev_hash"] != prev:
            con.execute(
                "UPDATE audit SET prev_hash=?, row_hash=? WHERE id=?",
                (prev, computed, row["id"]),
            )
        prev = computed


def verify_audit_chain(con: sqlite3.Connection) -> dict:
    cols = {r[1] for r in con.execute("PRAGMA table_info(audit)").fetchall()}
    if "row_hash" not in cols:
        return {"ok": False, "checked": 0, "first_bad_id": None, "reason": "schema"}
    rows = con.execute(
        "SELECT id, event_type, actor, details_json, created_at, prev_hash, row_hash "
        "FROM audit ORDER BY id ASC"
    ).fetchall()
    prev = GENESIS
    for row in rows:
        expected = audit_row_hash(
            prev, row["event_type"], row["actor"], row["details_json"], row["created_at"]
        )
        if row["prev_hash"] != prev or row["row_hash"] != expected:
            return {
                "ok": False,
                "checked": row["id"],
                "first_bad_id": row["id"],
                "reason": "break",
            }
        prev = row["row_hash"]
    return {"ok": True, "checked": len(rows), "first_bad_id": None, "reason": None}
