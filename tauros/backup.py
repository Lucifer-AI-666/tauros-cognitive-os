"""Backup / restore helpers."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .migrations import backup_database, integrity_check


def create_backup(db_path: Path, backup_dir: Path | None = None) -> Path | None:
    return backup_database(db_path, backup_dir)


def restore_backup(backup_path: Path, db_path: Path) -> dict:
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup non trovato: {backup_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # safety copy of current
    if db_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safety = db_path.with_suffix(db_path.suffix + f".pre-restore.{stamp}")
        shutil.copy2(db_path, safety)
    shutil.copy2(backup_path, db_path)
    con = sqlite3.connect(db_path)
    try:
        ok = integrity_check(con)
    finally:
        con.close()
    if not ok:
        raise RuntimeError("Ripristino completato ma integrity_check fallita")
    return {"restored_from": str(backup_path), "database": str(db_path), "integrity_ok": ok}


def list_backups(backup_dir: Path) -> list[dict]:
    if not backup_dir.exists():
        return []
    items = []
    for path in sorted(backup_dir.glob("*.bak"), reverse=True):
        items.append(
            {
                "path": str(path),
                "size": path.stat().st_size,
                "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return items
