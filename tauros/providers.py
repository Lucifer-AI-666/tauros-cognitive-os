from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import Callable

import httpx

from .settings import Settings

TokenProvider = Callable[[], str]


class ProviderError(RuntimeError):
    pass


async def http_post_retry(
    url: str,
    *,
    json: dict,
    headers: dict | None = None,
    timeout: float = 60.0,
    attempts: int = 3,
    trust_env: bool = False,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env) as client:
                return await client.post(url, headers=headers, json=json)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            await asyncio.sleep(0.4 * (attempt + 1))
    raise last_exc if last_exc else ProviderError("http retry: nessuna risposta")


class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.settings.model, "messages": messages, "stream": False}
        try:
            response = await http_post_retry(
                f"{self.settings.ollama_url}/api/chat",
                json=payload,
                timeout=120.0,
                attempts=3,
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Ollama non disponibile: {exc}") from exc


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI Chat Completions API — also used by Groq and other compatible gateways."""

    def __init__(
        self,
        settings: Settings,
        *,
        api_key: str,
        base_url: str,
        provider_name: str = "openai-compatible",
    ):
        self.settings = settings
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name

    async def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise ProviderError(f"API key non configurata per provider {self.provider_name}")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": 0.4,
        }
        url = f"{self.base_url}/chat/completions"
        try:
            response = await http_post_retry(
                url, json=payload, headers=headers, timeout=120.0, attempts=3
            )
            if response.status_code >= 400:
                body = (response.text or "")[:400]
                raise ProviderError(
                    f"{self.provider_name} HTTP {response.status_code}: {body}"
                )
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except ProviderError:
            raise
        except Exception as ext:
            raise ProviderError(f"{self.provider_name} non disponibile: {ext}") from ext


class DibProvider(LLMProvider):
    """DIB-OS Brain: cache tokenizzata + Ollama locale via /api/chat."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base = (settings.dib_url or "http://127.0.0.1:1988").rstrip("/")
        self.personality = (settings.dib_personality or "normale").strip() or "normale"

    def _model_for_dib(self) -> str | None:
        raw = (self.settings.model or "").strip()
        if not raw or raw in {"dib-os", "dib", "dib-brain"}:
            return None
        if raw.startswith("dib-"):
            raw = raw[4:]
        return raw or None

    async def chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict = {
            "messages": messages,
            "personality": self.personality,
            "force_ollama": False,
        }
        model = self._model_for_dib()
        if model:
            payload["model"] = model
        try:
            async with httpx.AsyncClient(timeout=90.0, trust_env=False) as client:
                response = await client.post(f"{self.base}/api/chat", json=payload)
        except Exception as exc:
            raise ProviderError(
                f"DIB-OS non raggiungibile su {self.base}. Avvia DIB Brain (porta 1988)."
            ) from exc
        if response.status_code >= 400:
            body = (response.text or "")[:300]
            raise ProviderError(f"dib HTTP {response.status_code}: {body}")
        try:
            data = response.json()
            content = ((data.get("message") or {}).get("content") or "").strip()
        except Exception as exc:
            raise ProviderError(f"Risposta DIB non valida: {exc}") from exc
        if not content:
            raise ProviderError("DIB ha restituito una risposta vuota")
        return content


# Default Groq chat models (override with TAUROS_MODEL)
GROQ_DEFAULT_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

VERTEX_DEFAULT_MODEL = "gemini-2.5-flash"
VERTEX_DEFAULT_LOCATION = "europe-west1"
_CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"


def resolve_vertex_project(settings: Settings) -> str:
    return (
        (settings.vertex_project or "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.environ.get("GCLOUD_PROJECT", "").strip()
        or os.environ.get("GCP_PROJECT", "").strip()
    )


def resolve_vertex_location(settings: Settings) -> str:
    return (settings.vertex_location or "").strip() or VERTEX_DEFAULT_LOCATION


def normalize_vertex_model(model: str) -> str:
    value = (model or "").strip()
    for prefix in ("google/", "publishers/google/models/", "models/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value or VERTEX_DEFAULT_MODEL


def vertex_api_root(location: str) -> str:
    loc = (location or VERTEX_DEFAULT_LOCATION).strip()
    if loc == "global":
        return "https://aiplatform.googleapis.com"
    return f"https://{loc}-aiplatform.googleapis.com"


def vertex_payload_from_messages(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.4,
) -> dict:
    system_parts: list[dict[str, str]] = []
    contents: list[dict] = []
    for message in messages:
        role = (message.get("role") or "user").strip().lower()
        text = message.get("content") or ""
        if role == "system":
            if text:
                system_parts.append({"text": text})
            continue
        vertex_role = "model" if role in {"assistant", "model"} else "user"
        contents.append({"role": vertex_role, "parts": [{"text": text}]})
    if not contents:
        contents.append({"role": "user", "parts": [{"text": ""}]})
    payload: dict = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    return payload


def extract_vertex_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        raise ProviderError("Vertex non ha restituito candidati")
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
    text = "".join(texts).strip()
    if not text:
        raise ProviderError("Vertex ha restituito una risposta vuota")
    return text


def adc_access_token() -> str:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise ProviderError(
            "Vertex richiede il pacchetto google-auth. Installa le dipendenze del progetto."
        ) from exc
    try:
        creds, _project = google.auth.default(scopes=[_CLOUD_PLATFORM])
        creds.refresh(Request())
    except Exception as exc:
        raise ProviderError(
            "Credenziali GCP non disponibili. Esegui "
            "`gcloud auth application-default login` "
            "oppure abilita l'addon minikube gcp-auth."
        ) from exc
    token = getattr(creds, "token", None)
    if not token:
        raise ProviderError("ADC non ha prodotto un access token")
    return str(token)


class VertexProvider(LLMProvider):
    """Gemini on Vertex AI via Application Default Credentials (incl. gcp-auth)."""

    def __init__(
        self,
        settings: Settings,
        *,
        token_provider: TokenProvider | None = None,
    ):
        self.settings = settings
        self.token_provider = token_provider or adc_access_token
        project = resolve_vertex_project(settings)
        if not project:
            raise ProviderError(
                "Vertex richiede un progetto GCP. Imposta TAUROS_VERTEX_PROJECT "
                "oppure GOOGLE_CLOUD_PROJECT (iniettato da gcp-auth)."
            )
        self.project = project
        self.location = resolve_vertex_location(settings)
        self.model = normalize_vertex_model(settings.model)
        os.environ.setdefault("GOOGLE_CLOUD_QUOTA_PROJECT", self.project)

    def generate_url(self) -> str:
        return (
            f"{vertex_api_root(self.location)}/v1/projects/{self.project}"
            f"/locations/{self.location}/publishers/google/models/{self.model}:generateContent"
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            token = self.token_provider()
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Impossibile ottenere il token ADC: {exc}") from exc
        payload = vertex_payload_from_messages(messages)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            response = await http_post_retry(
                self.generate_url(),
                json=payload,
                headers=headers,
                timeout=60.0,
                attempts=3,
                trust_env=False,
            )
        except Exception as last_exc:
            detail = f"{type(last_exc).__name__}: {last_exc!r}"
            raise ProviderError(f"vertex non disponibile: {detail}") from last_exc
        if response.status_code >= 400:
            body = (response.text or "")[:400]
            raise ProviderError(f"vertex HTTP {response.status_code}: {body}")
        try:
            return extract_vertex_text(response.json())
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Risposta Vertex non valida: {exc}") from exc


class FallbackProvider(LLMProvider):
    """Use primary, then secondary if the first engine is unreachable."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider):
        self.primary = primary
        self.secondary = secondary

    async def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            return await self.primary.chat(messages)
        except ProviderError:
            return await self.secondary.chat(messages)


def build_provider(settings: Settings) -> LLMProvider:
    name = settings.provider.lower().strip()

    if name == "ollama":
        return OllamaProvider(settings)

    if name == "groq":
        api_key = settings.groq_api_key or settings.openai_api_key
        base = settings.groq_base_url or GROQ_BASE_URL
        if not api_key:
            raise ProviderError(
                "Groq richiede TAUROS_GROQ_API_KEY (oppure TAUROS_OPENAI_API_KEY come fallback). "
                "Crea la chiave su https://console.groq.com/keys"
            )
        groq = OpenAICompatibleProvider(
            settings,
            api_key=api_key,
            base_url=base,
            provider_name="groq",
        )
        if (settings.ollama_url or "").strip():
            ollama_settings = settings.model_copy(update={"provider": "ollama", "model": "llama3.2:3b"})
            return FallbackProvider(groq, OllamaProvider(ollama_settings))
        return groq

    if name in {"openai", "openai-compatible"}:
        return OpenAICompatibleProvider(
            settings,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            provider_name=name,
        )

    if name in {"dib", "dib-os", "dibos"}:
        return DibProvider(settings)

    if name in {"vertex", "gemini", "vertex-ai"}:
        primary = VertexProvider(settings)
        groq_key = settings.groq_api_key or settings.openai_api_key
        if groq_key:
            groq_settings = settings.model_copy(update={"model": GROQ_DEFAULT_MODEL})
            secondary = OpenAICompatibleProvider(
                groq_settings,
                api_key=groq_key,
                base_url=settings.groq_base_url or GROQ_BASE_URL,
                provider_name="groq",
            )
            return FallbackProvider(primary, secondary)
        return primary

    raise ProviderError(
        f"Provider sconosciuto: {settings.provider}. "
        "Valori supportati: ollama, groq, openai, openai-compatible, vertex, dib"
    )
