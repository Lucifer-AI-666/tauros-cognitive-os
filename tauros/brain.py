"""Runtime AI brain: switch provider/model without restart."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .providers import ProviderError, build_provider
from .settings import Settings

BRAIN_CATALOG: list[dict[str, str]] = [
    {"provider": "dib", "id": "dib-os", "label": "DIB-OS Brain · locale tokenizzato"},
    {"provider": "dib", "id": "llama3.2:latest", "label": "DIB-OS · Llama 3.2 (Ollama)"},
    {"provider": "dib", "id": "mistral", "label": "DIB-OS · Mistral (Ollama)"},
    {"provider": "vertex", "id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash · Vertex"},
    {"provider": "vertex", "id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro · Vertex"},
    {"provider": "groq", "id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B · Groq"},
    {"provider": "groq", "id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B · Groq"},
    {"provider": "groq", "id": "qwen/qwen3.8-27b", "label": "Qwen 3.8 27B · Groq"},
    {"provider": "groq", "id": "groq/compound", "label": "Groq Compound"},
    {"provider": "ollama", "id": "llama3.2:3b", "label": "Llama 3.2 3B · Ollama locale"},
    {"provider": "ollama", "id": "llama3.1", "label": "Llama 3.1 · Ollama locale"},
    {"provider": "openai", "id": "gpt-4o", "label": "GPT-4o · OpenAI"},
    {"provider": "openai", "id": "gpt-4o-mini", "label": "GPT-4o mini · OpenAI"},
]

ALLOWED_PROVIDERS = frozenset(
    {"vertex", "gemini", "vertex-ai", "groq", "ollama", "openai", "openai-compatible", "dib", "dib-os", "dibos"}
)


def brain_path(settings: Settings) -> Path:
    return Path(settings.database_path).expanduser().resolve().parent / "brain.json"


def load_brain_override(settings: Settings) -> dict[str, str] | None:
    path = brain_path(settings)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    provider = str(data.get("provider") or "").strip()
    model = str(data.get("model") or "").strip()
    if not provider or not model:
        return None
    settings.provider = provider
    settings.model = model
    location = str(data.get("vertex_location") or "").strip()
    if location:
        settings.vertex_location = location
    return {"provider": provider, "model": model}


def save_brain(settings: Settings) -> None:
    path = brain_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": settings.provider,
        "model": settings.model,
        "vertex_location": settings.vertex_location,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def validate_brain(provider: str, model: str) -> tuple[str, str]:
    name = (provider or "").strip().lower()
    mid = (model or "").strip()
    if name not in ALLOWED_PROVIDERS:
        raise ValueError(
            "Provider non valido. Usa: vertex, groq, ollama, openai, openai-compatible"
        )
    if not mid or len(mid) > 120:
        raise ValueError("Modello mancante o troppo lungo")
    if name in {"gemini", "vertex-ai"}:
        name = "vertex"
    if name in {"dib-os", "dibos"}:
        name = "dib"
    # Remote providers: only catalog ids (retired Groq names 404).
    # ollama / dib / openai-compatible stay open for local or custom endpoints.
    if name in {"groq", "vertex", "openai"}:
        allowed = {c["id"] for c in BRAIN_CATALOG if c["provider"] == name}
        if mid not in allowed:
            raise ValueError(
                f"Modello '{mid}' non in catalogo per {name}. "
                f"Usa: {', '.join(sorted(allowed))}"
            )
    return name, mid


def current_brain(settings: Settings) -> dict[str, Any]:
    return {
        "provider": settings.provider,
        "model": settings.model,
        "vertex_location": settings.vertex_location,
        "catalog": BRAIN_CATALOG,
    }


class BrainRuntime:
    def __init__(self, settings: Settings, orchestrator, planner) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.planner = planner
        self._lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return current_brain(self.settings)

    def apply(self, provider: str, model: str) -> dict[str, Any]:
        name, mid = validate_brain(provider, model)
        with self._lock:
            previous = (self.settings.provider, self.settings.model)
            self.settings.provider = name
            self.settings.model = mid
            try:
                built = build_provider(self.settings)
            except ProviderError:
                self.settings.provider, self.settings.model = previous
                raise
            self.orchestrator.provider = built
            self.planner.provider = built
            save_brain(self.settings)
            return current_brain(self.settings)
