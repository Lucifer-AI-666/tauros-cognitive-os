from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import __version__
from .backup import create_backup, list_backups, restore_backup
from .bootstrap import doctor_checks, init_environment
from .migrations import current_schema_version, run_migrations
from .models import ChatRequest, MemoryCreate
from .security import assert_strong_token, is_weak_token, redact_obj
from .settings import Settings, settings


def cmd_chat() -> None:
    from .api import orchestrator

    assert_strong_token(settings.api_token)
    print(f"{settings.name} v{__version__} [{settings.security_mode}]. Scrivi exit per uscire.")
    while True:
        try:
            text = input("Tu: ").strip()
        except EOFError:
            break
        if text.lower() in {"exit", "quit", "esci"}:
            break
        if not text:
            continue
        result = asyncio.run(orchestrator.chat(ChatRequest(message=text, session_id="cli")))
        print(f"TAUROS: {result.answer}\n")


def cmd_status() -> None:
    payload = {
        "name": settings.name,
        "version": __version__,
        "provider": settings.provider,
        "model": settings.model,
        "db": str(settings.database_path),
        "security_mode": settings.security_mode,
        "host": settings.host,
        "allow_lan_bind": settings.allow_lan_bind,
        "allowlist": [str(p) for p in settings.allowlist_paths()],
        "schema": current_schema_version(Path(settings.database_path)),
        "token_weak": is_weak_token(settings.api_token),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_doctor() -> int:
    checks = doctor_checks(settings)
    print(json.dumps({"version": __version__, "checks": checks}, indent=2, ensure_ascii=False))
    return 0 if all(c["ok"] for c in checks if c["check"] not in {"ollama", "database_exists"}) else 1


def cmd_init(args: argparse.Namespace) -> None:
    result = init_environment(
        root=Path.cwd(),
        owner=args.owner,
        allowlist=args.allowlist or "",
        force_token=args.rotate_token,
    )
    # Do not print full token unless freshly created/rotated
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\nProssimi passi:")
    print("  1. Verifica/modifica TAUROS_WORKSPACE_ALLOWLIST nel .env")
    print("  2. tauros doctor")
    print("  3. uvicorn tauros.api:app --host 127.0.0.1 --port 8000")


def cmd_migrate() -> None:
    result = run_migrations(Path(settings.database_path), backup=True)
    print(
        json.dumps(
            {
                "applied": result.applied,
                "backup_path": result.backup_path,
                "integrity_ok": result.integrity_ok,
                "schema": current_schema_version(Path(settings.database_path)),
            },
            indent=2,
        )
    )


def cmd_backup() -> None:
    path = create_backup(Path(settings.database_path), Path(settings.backup_dir))
    print(json.dumps({"backup": str(path) if path else None}, indent=2))


def cmd_restore(args: argparse.Namespace) -> None:
    result = restore_backup(Path(args.path), Path(settings.database_path))
    print(json.dumps(result, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tauros", description="TAUROS Cognitive OS")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chat", help="Chat interattiva locale")
    sub.add_parser("status", help="Stato configurazione")
    sub.add_parser("doctor", help="Controlli di salute e sicurezza")
    sub.add_parser("memories", help="Elenca memorie attive")
    sub.add_parser("migrate", help="Esegue migrazioni DB con backup")
    sub.add_parser("backup", help="Crea backup del database")
    sub.add_parser("backups", help="Elenca backup disponibili")
    sub.add_parser("telegram", help="Avvia bot Telegram (stessa memoria/policy)")
    sub.add_parser("brief", help="Stampa brief continuità (CLI, owner scope)")

    init_p = sub.add_parser("init", help="Crea .env con token sicuro")
    init_p.add_argument("--owner", default="Owner")
    init_p.add_argument("--allowlist", default="", help="Percorsi separati da virgola")
    init_p.add_argument("--rotate-token", action="store_true")

    restore_p = sub.add_parser("restore", help="Ripristina un backup")
    restore_p.add_argument("path")

    remember = sub.add_parser("remember", help="Salva una memoria attiva")
    remember.add_argument("content")
    remember.add_argument("--kind", default="fact")
    remember.add_argument("--importance", type=int, default=5)

    args = parser.parse_args(argv)

    if args.command == "init":
        cmd_init(args)
        return
    if args.command == "doctor":
        raise SystemExit(cmd_doctor())
    if args.command == "status":
        cmd_status()
        return
    if args.command == "migrate":
        cmd_migrate()
        return
    if args.command == "backup":
        cmd_backup()
        return
    if args.command == "backups":
        print(json.dumps(list_backups(Path(settings.backup_dir)), indent=2))
        return
    if args.command == "restore":
        cmd_restore(args)
        return
    if args.command == "chat":
        cmd_chat()
        return
    if args.command == "telegram":
        from .telegram_bot import run_telegram_bot

        run_telegram_bot()
        return

    # Commands that need DB / API modules
    from .api import db, memory, orchestrator

    if args.command == "memories":
        print(json.dumps(redact_obj(db.list_memories()), indent=2, ensure_ascii=False))
    elif args.command == "remember":
        item = MemoryCreate(content=args.content, kind=args.kind, importance=args.importance)
        print(json.dumps(memory.remember(item), indent=2, ensure_ascii=False))
    elif args.command == "brief":
        print(
            json.dumps(
                orchestrator.build_brief(None, is_operator=True),
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
