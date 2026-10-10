from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .security import parse_path_list

SecurityMode = Literal["locked", "read_only", "supervised"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TAUROS_", extra="ignore")

    name: str = "TAUROS"
    owner: str = "Owner"
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: str = ""
    database_path: Path = Path("./data/tauros.db")
    provider: str = "ollama"
    model: str = "llama3.2:3b"
    ollama_url: str = "http://127.0.0.1:11434"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    # Groq (OpenAI-compatible): https://console.groq.com
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Vertex AI Gemini — ADC / gcp-auth, no API key
    vertex_project: str = ""
    vertex_location: str = "europe-west1"
    # DIB-OS Brain (locale, cache tokenizzata + Ollama)
    dib_url: str = "http://127.0.0.1:1988"
    dib_personality: str = "heavy"
    allow_network_tools: bool = False
    allow_lan_bind: bool = False
    # Public internet exposure requires explicit opt-in (use behind HTTPS reverse proxy).
    allow_public_bind: bool = False
    # Comma-separated origins for CORS, e.g. https://tauros.example.com,https://app.vercel.app
    # Use * only for open public dashboard+API with bearer token (still required).
    cors_origins: str = "null,http://127.0.0.1:8000,http://localhost:8000"
    public_base_url: str = ""  # e.g. https://tauros.example.com — for PWA absolute URLs if needed
    security_mode: SecurityMode = "read_only"
    workspace_allowlist: str = ""
    workspace_blocklist: str = ""
    # Zone di fiducia amministrative (più libertà, meno conferma per azioni important)
    trust_zones: str = ""
    elevation_default_minutes: int = 15
    elevation_max_minutes: int = 60
    elevation_strong_phrase: str = "CONFERMO ADMIN"
    max_file_bytes: int = 2_000_000
    max_tool_output_chars: int = 100_000
    max_tool_steps: int = 8
    max_plan_steps: int = 3  # base; admin elevation can raise in planner later
    max_same_tool_calls: int = 3
    tool_timeout_seconds: int = 30
    log_level: str = "INFO"
    backup_dir: Path = Path("./data/backups")
    rules_path: Path = Path("./data/rules.json")
    skip_token_check: bool = False  # only for controlled tests
    guest_max_messages: int = 20
    allow_open_registration: bool = True
    # Telegram bot (optional multi-channel)
    telegram_bot_token: str = ""
    telegram_enabled: bool = False
    # LLM planner on by default when provider works; rules always fallback
    llm_planner: bool = True
    # Gmail / Google Sign-In
    google_client_id: str = ""  # OAuth Web Client ID (Google Cloud Console)
    gmail_user: str = ""  # es. tuo@gmail.com (SMTP mittente)
    gmail_app_password: str = ""  # password app Google (16 caratteri)
    otp_debug: bool = False  # su locale mostra il codice OTP nella risposta API
    # Un click da 127.0.0.1 entra come owner, senza token/password
    local_click_login: bool = False
    gmail_allowed_domains: str = "gmail.com,googlemail.com"

    @field_validator("host")
    @classmethod
    def default_loopback(cls, value: str) -> str:
        return (value or "127.0.0.1").strip()

    @field_validator("security_mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        mode = (value or "read_only").strip().lower()
        if mode not in {"locked", "read_only", "supervised"}:
            raise ValueError("TAUROS_SECURITY_MODE deve essere locked|read_only|supervised")
        return mode

    @model_validator(mode="after")
    def validate_bind_policy(self) -> Settings:
        host = self.host.strip().lower()
        loopback = host in {"127.0.0.1", "localhost", "::1"}
        if not loopback and not self.allow_lan_bind and not self.allow_public_bind:
            raise ValueError(
                "Bind di rete non loopback negato. Imposta TAUROS_ALLOW_LAN_BIND=true "
                "(LAN) oppure TAUROS_ALLOW_PUBLIC_BIND=true (internet, dietro HTTPS)."
            )
        if self.allow_public_bind and host in {"0.0.0.0", "::", "[::]"}:
            # Explicit public bind — ok, but CORS should not stay only localhost.
            pass
        return self

    def allowlist_paths(self) -> list[Path]:
        return parse_path_list(self.workspace_allowlist)

    def blocklist_paths(self) -> list[Path]:
        return parse_path_list(self.workspace_blocklist)

    def trust_zone_paths(self) -> list[Path]:
        return parse_path_list(self.trust_zones)

    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw == "*":
            return ["*"]
        # Prefer OS pathsep semantics only for path lists; CORS origins use comma/semicolon.
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        if self.public_base_url:
            base = self.public_base_url.rstrip("/")
            if base not in parts:
                parts.append(base)
        return parts or ["null", "http://127.0.0.1:8000", "http://localhost:8000"]


def load_settings(**overrides) -> Settings:
    return Settings(**overrides)


settings = Settings()

