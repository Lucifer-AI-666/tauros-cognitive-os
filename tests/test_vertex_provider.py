import asyncio
import json

import httpx
import pytest

from tauros.providers import (
    DibProvider,
    FallbackProvider,
    ProviderError,
    VertexProvider,
    build_provider,
    http_post_retry,
    extract_vertex_text,
    normalize_vertex_model,
    resolve_vertex_project,
    vertex_api_root,
    vertex_payload_from_messages,
)
from tauros.security import generate_api_token
from tauros.settings import Settings


def _settings(**kwargs) -> Settings:
    base = {
        "provider": "vertex",
        "model": "gemini-2.0-flash-001",
        "vertex_project": "dotted-lexicon-496211-k1",
        "vertex_location": "europe-west1",
        "groq_api_key": "",
        "openai_api_key": "",
        "api_token": generate_api_token(),
        "skip_token_check": True,
        "host": "127.0.0.1",
    }
    base.update(kwargs)
    return Settings(**base)


def test_normalize_vertex_model():
    assert normalize_vertex_model("google/gemini-2.0-flash-001") == "gemini-2.0-flash-001"
    assert normalize_vertex_model("publishers/google/models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert normalize_vertex_model("models/gemini-2.0-flash-001") == "gemini-2.0-flash-001"
    assert normalize_vertex_model("") == "gemini-2.5-flash"


def test_vertex_api_root_regional_and_global():
    assert vertex_api_root("europe-west1") == "https://europe-west1-aiplatform.googleapis.com"
    assert vertex_api_root("global") == "https://aiplatform.googleapis.com"


def test_resolve_vertex_project_prefers_settings_then_env(monkeypatch):
    settings = _settings(vertex_project="from-settings")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "from-env")
    assert resolve_vertex_project(settings) == "from-settings"
    settings = _settings(vertex_project="")
    assert resolve_vertex_project(settings) == "from-env"


def test_vertex_payload_maps_roles_and_system():
    payload = vertex_payload_from_messages(
        [
            {"role": "system", "content": "Sei TAUROS."},
            {"role": "user", "content": "Ciao"},
            {"role": "assistant", "content": "Pronto"},
            {"role": "user", "content": "Chi sei?"},
        ]
    )
    assert payload["systemInstruction"]["parts"][0]["text"] == "Sei TAUROS."
    roles = [item["role"] for item in payload["contents"]]
    assert roles == ["user", "model", "user"]
    assert payload["contents"][-1]["parts"][0]["text"] == "Chi sei?"


def test_extract_vertex_text():
    data = {"candidates": [{"content": {"parts": [{"text": "ok "}, {"text": "gemini"}]}}]}
    assert extract_vertex_text(data) == "ok gemini"
    with pytest.raises(ProviderError):
        extract_vertex_text({"candidates": []})


def test_vertex_chat_uses_adc_token_and_parses_response(monkeypatch):
    settings = _settings()
    provider = VertexProvider(settings, token_provider=lambda: "test-adc-token")
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ciao da vertex"}]}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    answer = asyncio.run(provider.chat([{"role": "user", "content": "ping"}]))
    assert answer == "ciao da vertex"
    assert captured["headers"]["Authorization"] == "Bearer test-adc-token"
    assert "dotted-lexicon-496211-k1" in captured["url"]
    assert captured["url"].endswith(":generateContent")
    assert captured["json"]["contents"][0]["parts"][0]["text"] == "ping"


def test_vertex_chat_surfaces_http_error_without_token(monkeypatch):
    provider = VertexProvider(_settings(), token_provider=lambda: "secret-token-value")

    class FakeResponse:
        status_code = 403
        text = json.dumps({"error": {"message": "PERMISSION_DENIED"}})

        def json(self):
            return {"error": {"message": "PERMISSION_DENIED"}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(ProviderError) as err:
        asyncio.run(provider.chat([{"role": "user", "content": "ping"}]))
    assert "403" in str(err.value)
    assert "secret-token-value" not in str(err.value)


def test_build_provider_dib():
    s = _settings(provider="dib", model="dib-os", dib_url="http://127.0.0.1:1988")
    p = build_provider(s)
    assert isinstance(p, DibProvider)
    assert p.base == "http://127.0.0.1:1988"


def test_http_post_retry_recovers_after_transport_error(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("boom")
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    resp = asyncio.run(http_post_retry("http://127.0.0.1/x", json={}))
    assert resp.status_code == 200
    assert calls["n"] == 3


def test_build_provider_vertex_wraps_groq_fallback():
    s = _settings(groq_api_key="gsk_test_key_not_real_123456")
    p = build_provider(s)
    assert isinstance(p, FallbackProvider)
    assert isinstance(p.primary, VertexProvider)


def test_history_for_llm_drops_degraded_replies():
    from tauros.orchestrator import _history_for_llm

    hist = [
        {"role": "user", "content": "ciao"},
        {
            "role": "assistant",
            "content": "Il motore linguistico non è raggiungibile. TAUROS resta operativo",
        },
        {"role": "user", "content": "ciao di nuovo"},
    ]
    clean = _history_for_llm(hist)
    assert len(clean) == 2
    assert clean[0]["role"] == "user"
    assert clean[1]["content"] == "ciao di nuovo"
