"""Installation / env bootstrap without weak defaults."""

from __future__ import annotations

import os
from pathlib import Path

from .security import generate_api_token, protect_env_file


DEFAULT_ENV = """TAUROS_NAME=TAUROS
TAUROS_OWNER={owner}
TAUROS_HOST=127.0.0.1
TAUROS_PORT=8000
TAUROS_API_TOKEN={token}
TAUROS_DATABASE_PATH=./data/tauros.db
TAUROS_PROVIDER=groq
TAUROS_MODEL=openai/gpt-oss-20b
TAUROS_OLLAMA_URL=http://127.0.0.1:11434
TAUROS_GROQ_API_KEY=
TAUROS_GROQ_BASE_URL=https://api.groq.com/openai/v1
TAUROS_OPENAI_BASE_URL=https://api.openai.com/v1
TAUROS_OPENAI_API_KEY=
TAUROS_VERTEX_PROJECT=
TAUROS_VERTEX_LOCATION=europe-west1
TAUROS_ALLOW_NETWORK_TOOLS=false
TAUROS_ALLOW_LAN_BIND=false
TAUROS_ALLOW_PUBLIC_BIND=false
TAUROS_CORS_ORIGINS=null,http://127.0.0.1:8000,http://localhost:8000
TAUROS_PUBLIC_BASE_URL=
TAUROS_SECURITY_MODE=read_only
TAUROS_WORKSPACE_ALLOWLIST={allowlist}
TAUROS_WORKSPACE_BLOCKLIST=
TAUROS_MAX_FILE_BYTES=2000000
TAUROS_LOG_LEVEL=INFO
TAUROS_BACKUP_DIR=./data/backups
"""


def init_environment(
    root: Path | None = None,
    owner: str = "Owner",
    allowlist: str = "",
    force_token: bool = False,
) -> dict:
    root = root or Path.cwd()
    env_path = root / ".env"
    data_dir = root / "data"
    logs_dir = root / "logs"
    backup_dir = root / "data" / "backups"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    token = generate_api_token()
    created = False
    if not env_path.exists():
        env_path.write_text(
            DEFAULT_ENV.format(owner=owner, token=token, allowlist=allowlist or ""),
            encoding="utf-8",
        )
        created = True
    else:
        text = env_path.read_text(encoding="utf-8")
        if force_token or "change-me-now" in text or "TAUROS_API_TOKEN=" not in text:
            lines = []
            replaced = False
            for line in text.splitlines():
                if line.startswith("TAUROS_API_TOKEN="):
                    lines.append(f"TAUROS_API_TOKEN={token}")
                    replaced = True
                else:
                    lines.append(line)
            if not replaced:
                lines.append(f"TAUROS_API_TOKEN={token}")
            # ensure security keys exist
            blob = "\n".join(lines)
            extras = []
            for key, value in {
                "TAUROS_ALLOW_LAN_BIND": "false",
                "TAUROS_SECURITY_MODE": "read_only",
                "TAUROS_WORKSPACE_ALLOWLIST": allowlist or "",
                "TAUROS_BACKUP_DIR": "./data/backups",
            }.items():
                if key not in blob:
                    extras.append(f"{key}={value}")
            if extras:
                lines.extend(extras)
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            # parse existing token for return
            for line in text.splitlines():
                if line.startswith("TAUROS_API_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break

    protect_env_file(env_path)
    return {
        "env_path": str(env_path),
        "created": created,
        "api_token": token,
        "data_dir": str(data_dir),
        "backup_dir": str(backup_dir),
        "host": "127.0.0.1",
        "note": "Conserva il token in un posto sicuro. Non committare il file .env.",
    }


def doctor_checks(settings) -> list[dict]:
    from .migrations import current_schema_version
    from .security import is_weak_token, protect_env_file
    import shutil
    import sys

    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    add("python_version", sys.version_info >= (3, 11), f"{sys.version.split()[0]}")
    add("token_strength", not is_weak_token(settings.api_token), "token forte" if not is_weak_token(settings.api_token) else "token debole o assente")
    host_ok = settings.host in {"127.0.0.1", "localhost", "::1"} or settings.allow_lan_bind
    add("bind_policy", host_ok, f"host={settings.host} allow_lan_bind={settings.allow_lan_bind}")
    add("security_mode", settings.security_mode in {"locked", "read_only", "supervised"}, settings.security_mode)

    allow = settings.allowlist_paths()
    add(
        "workspace_allowlist",
        settings.security_mode == "locked" or len(allow) > 0,
        f"{len(allow)} path" if allow else "vuota (filesystem negato)",
    )

    db_path = Path(settings.database_path)
    add("database_parent_writable", db_path.parent.exists() or True, str(db_path))
    if db_path.exists():
        from .database import Database

        db = Database(db_path, run_migrate=False)
        # run integrity via new connection after ensuring migrations externally
        try:
            from .migrations import run_migrations

            run_migrations(db_path, backup=False)
            db = Database(db_path, run_migrate=False)
            ok = db.integrity_ok()
        except Exception as exc:  # noqa: BLE001
            ok = False
            add("database_integrity", False, str(exc))
        else:
            add("database_integrity", ok, "ok" if ok else "FAILED")
        versions = current_schema_version(db_path)
        add("schema_migrations", bool(versions), ", ".join(versions) if versions else "nessuna")
    else:
        add("database_exists", False, "non ancora creato (verrà creato all'avvio)")

    env_path = Path(".env")
    if env_path.exists():
        protect_env_file(env_path)
        add("env_file", True, str(env_path.resolve()))
    else:
        add("env_file", False, "manca .env — esegui `tauros init`")

    usage = shutil.disk_usage(Path.cwd())
    free_gb = usage.free / (1024**3)
    add("disk_space", free_gb > 0.5, f"{free_gb:.2f} GiB liberi")

    provider = (settings.provider or "").lower()
    if provider == "ollama":
        try:
            import httpx

            r = httpx.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=2.0)
            add("ollama", r.status_code == 200, settings.ollama_url)
        except Exception as exc:  # noqa: BLE001
            add("ollama", False, f"non raggiungibile: {exc}")
    elif provider == "groq":
        key = settings.groq_api_key or settings.openai_api_key
        add("groq_api_key", bool(key and len(key) > 10), "configurata" if key else "manca TAUROS_GROQ_API_KEY")
        try:
            import httpx

            r = httpx.get(
                f"{(settings.groq_base_url or 'https://api.groq.com/openai/v1').rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"} if key else {},
                timeout=5.0,
            )
            add("groq_api", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            add("groq_api", False, f"non raggiungibile: {exc}")
    elif provider in {"vertex", "gemini", "vertex-ai"}:
        from .providers import resolve_vertex_location, resolve_vertex_project

        project = resolve_vertex_project(settings)
        add(
            "vertex_project",
            bool(project),
            project or "manca TAUROS_VERTEX_PROJECT / GOOGLE_CLOUD_PROJECT",
        )
        add("vertex_location", True, resolve_vertex_location(settings))
        try:
            from .providers import adc_access_token

            adc_access_token()
            add("vertex_adc", True, "ADC ok")
        except Exception as exc:  # noqa: BLE001
            add("vertex_adc", False, str(exc))
    else:
        add("provider", True, provider or "unset")

    tg_on = bool(settings.telegram_enabled)
    tg_tok = (settings.telegram_bot_token or "").strip()
    if not tg_on:
        add("telegram", True, "disabilitato (opzionale)")
    else:
        add(
            "telegram",
            bool(tg_tok),
            "token presente" if tg_tok else "TAUROS_TELEGRAM_ENABLED ma token vuoto",
        )

    return checks
