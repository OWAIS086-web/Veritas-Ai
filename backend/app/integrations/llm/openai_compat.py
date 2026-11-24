"""OpenAI-compatible chat completions client (hosted APIs or a local Qwen2.5 server)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.llm.base import Completion, ProviderError

MAX_RETRIES = 2
logger = get_logger(__name__)


class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        models: list[str],
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url or not models:
            raise ProviderError("model provider is not configured")
        self.name = f"openai-compatible:{httpx.URL(base_url).host}"
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._models = models
        self._timeout = timeout
        self._transport = transport

    async def _call(
        self, client: httpx.AsyncClient, model: str, messages: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, int] | None]:
        resp = await client.post(
            self._url,
            headers=self._headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("model answer is not a JSON object")
        return parsed, _usage(body.get("usage"))

    async def complete_json(self, messages: list[dict[str, Any]]) -> Completion:
        attempts = 0
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for model in self._models:
                for retry in range(MAX_RETRIES + 1):
                    attempts += 1
                    try:
                        content, usage = await self._call(client, model, messages)
                        return Completion(content, model, self.name, attempts, usage)
                    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                        errors.append(f"{model}: {type(exc).__name__}")
                        logger.warning(
                            "llm_call_failed",
                            extra={
                                "model": model,
                                "attempt": retry + 1,
                                "error": type(exc).__name__,
                            },
                        )
                        if retry < MAX_RETRIES:
                            await asyncio.sleep(0.5 * 2**retry)
        raise ProviderError("all models failed: " + "; ".join(errors[-6:]))


def _usage(raw: Any) -> dict[str, int] | None:
    """The provider's own token counts, if it sent them as integers."""
    if not isinstance(raw, dict):
        return None
    out = {
        k: raw[k]
        for k in ("prompt_tokens", "completion_tokens")
        if isinstance(raw.get(k), int) and raw[k] >= 0
    }
    return out if len(out) == 2 else None


def configured_provider() -> OpenAICompatProvider | None:
    s = get_settings()
    if not s.llm_configured:
        return None
    return OpenAICompatProvider(s.llm_base_url, s.llm_api_key, s.llm_models, s.llm_timeout_seconds)


def configured_vision_provider() -> OpenAICompatProvider | None:
    """The vision model (VERITAS_VLM_MODEL, e.g. qwen2.5vl:7b) on the same OpenAI-compatible
    endpoint, or None when it isn't configured. No fallback to the text model: a text-only
    model can't read the images."""
    s = get_settings()
    if not s.llm_base_url or not s.vlm_model:
        return None
    return OpenAICompatProvider(s.llm_base_url, s.llm_api_key, [s.vlm_model], s.llm_timeout_seconds)


async def _listed_models() -> tuple[list[str] | None, str | None]:
    """Model ids the configured endpoint lists (GET {base}/models), or (None, error)."""
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.llm_api_key}"} if s.llm_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(s.llm_base_url.rstrip("/") + "/models", headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        return None, f"endpoint not reachable ({type(exc).__name__})"
    return [str(m.get("id")) for m in data if isinstance(m, dict)], None


async def models_status() -> dict[str, Any]:
    """Diagnostic for GET /system/models: configured models and whether the endpoint lists
    them. Returns the host only, and never the key; sends no document content."""
    s = get_settings()
    configured = [("text", s.llm_model), ("vision", s.vlm_model)] + [
        ("fallback", m) for m in s.llm_models[1:]
    ]
    configured = [(role, m) for role, m in configured if m]
    out: dict[str, Any] = {
        "configured": bool(s.llm_base_url and configured),
        "endpoint_host": httpx.URL(s.llm_base_url).host if s.llm_base_url else None,
        "api_key_set": bool(s.llm_api_key),
        "reachable": False,
        "error": None,
        "models": [{"role": r, "model": m, "available": None} for r, m in configured],
    }
    if not out["configured"]:
        out["error"] = "Set VERITAS_LLM_BASE_URL and VERITAS_LLM_MODEL or VERITAS_VLM_MODEL."
        return out
    listed, error = await _listed_models()
    if listed is None:
        out["error"] = error
        return out
    out["reachable"] = True
    for entry in out["models"]:
        entry["available"] = entry["model"] in listed
    return out


async def vision_status() -> dict[str, Any]:
    """Diagnostic: is the vision model configured, is the endpoint reachable, is the model
    listed there? Never sends document content."""
    s = get_settings()
    out: dict[str, Any] = {
        "configured": bool(s.llm_base_url and s.vlm_model),
        "model": s.vlm_model or None,
        "endpoint_host": httpx.URL(s.llm_base_url).host if s.llm_base_url else None,
        "reachable": False,
        "model_available": False,
        "error": None,
    }
    if not out["configured"]:
        out["error"] = "Set VERITAS_LLM_BASE_URL and VERITAS_VLM_MODEL (for example qwen2.5vl:7b)."
        return out
    headers = {"Authorization": f"Bearer {s.llm_api_key}"} if s.llm_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(s.llm_base_url.rstrip("/") + "/models", headers=headers)
            resp.raise_for_status()
            ids = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
    except (httpx.HTTPError, ValueError) as exc:
        out["error"] = f"endpoint not reachable ({type(exc).__name__})"
        return out
    out["reachable"] = True
    out["model_available"] = s.vlm_model in ids
    if not out["model_available"]:
        out["error"] = (
            f"{s.vlm_model} is not listed by the endpoint; pull it (ollama pull {s.vlm_model})."
        )
    return out
