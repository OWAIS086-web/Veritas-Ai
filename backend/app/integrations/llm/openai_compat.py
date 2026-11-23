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
        self, client: httpx.AsyncClient, model: str, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
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
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("model answer is not a JSON object")
        return parsed

    async def complete_json(self, messages: list[dict[str, str]]) -> Completion:
        attempts = 0
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for model in self._models:
                for retry in range(MAX_RETRIES + 1):
                    attempts += 1
                    try:
                        content = await self._call(client, model, messages)
                        return Completion(content, model, self.name, attempts)
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


def configured_provider() -> OpenAICompatProvider | None:
    s = get_settings()
    if not s.llm_configured:
        return None
    return OpenAICompatProvider(s.llm_base_url, s.llm_api_key, s.llm_models, s.llm_timeout_seconds)
