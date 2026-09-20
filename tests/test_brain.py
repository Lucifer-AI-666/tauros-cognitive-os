import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tauros.brain import BRAIN_CATALOG, BrainRuntime, load_brain_override, validate_brain
from tauros.providers import GROQ_DEFAULT_MODEL
from tauros.security import generate_api_token
from tauros.settings import Settings


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "api_token": generate_api_token(),
        "skip_token_check": True,
        "host": "127.0.0.1",
        "database_path": tmp_path / "t.db",
        "provider": "vertex",
        "model": "gemini-2.5-flash",
        "groq_api_key": "",
        "openai_api_key": "",
    }
    base.update(kwargs)
    return Settings(**base)


def test_validate_brain_normalizes_vertex_alias():
    assert validate_brain("gemini", "gemini-2.5-pro") == ("vertex", "gemini-2.5-pro")
    assert validate_brain("dib-os", "dib-os") == ("dib", "dib-os")
    with pytest.raises(ValueError):
        validate_brain("nope", "x")
    with pytest.raises(ValueError):
        validate_brain("vertex", "")


def test_validate_brain_rejects_retired_groq_models():
    with pytest.raises(ValueError, match="catalogo"):
        validate_brain("groq", "llama-3.3-70b-versatile")
    assert validate_brain("groq", "openai/gpt-oss-20b") == ("groq", "openai/gpt-oss-20b")
    assert validate_brain("ollama", "mistral:7b") == ("ollama", "mistral:7b")


def test_groq_catalog_uses_live_models():
    groq_ids = {c["id"] for c in BRAIN_CATALOG if c["provider"] == "groq"}
    assert GROQ_DEFAULT_MODEL in groq_ids
    assert "openai/gpt-oss-20b" in groq_ids
    retired = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"}
    assert groq_ids.isdisjoint(retired)


def test_brain_runtime_switches_and_persists(tmp_path: Path):
    settings = _settings(tmp_path)

    class Holder:
        provider = None

    orch = Holder()
    planner = Holder()
    runtime = BrainRuntime(settings, orch, planner)
    snap = runtime.apply("ollama", "llama3.2:3b")
    assert snap["provider"] == "ollama"
    assert snap["model"] == "llama3.2:3b"
    assert orch.provider is not None
    assert planner.provider is orch.provider
    assert (tmp_path / "brain.json").is_file()

    other = _settings(tmp_path, provider="vertex", model="gemini-2.5-flash")
    loaded = load_brain_override(other)
    assert loaded == {"provider": "ollama", "model": "llama3.2:3b"}
    assert other.provider == "ollama"
    assert other.model == "llama3.2:3b"


def test_brain_apply_serializes_concurrent_puts(tmp_path: Path):
    settings = _settings(tmp_path, provider="ollama", model="llama3.1")

    class Holder:
        provider = None

    orch = Holder()
    planner = Holder()
    runtime = BrainRuntime(settings, orch, planner)

    def one(mid: str):
        return runtime.apply("ollama", mid)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(one, m) for m in (["llama3.2:3b", "llama3.1"] * 8)]
        for f in futs:
            f.result()

    assert settings.provider == "ollama"
    assert settings.model in {"llama3.2:3b", "llama3.1"}
    assert orch.provider is planner.provider
    loaded = json.loads((tmp_path / "brain.json").read_text(encoding="utf-8"))
    assert loaded["provider"] == settings.provider
    assert loaded["model"] == settings.model
