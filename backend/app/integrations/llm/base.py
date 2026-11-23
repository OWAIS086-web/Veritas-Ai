"""Model provider interface (see .kiro/steering/ai-engineering.md)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """Every model in the chain failed (after retries), or the provider isn't configured."""


@dataclass(frozen=True)
class Completion:
    content: dict[str, Any]
    model: str
    provider: str
    attempts: int
    # Token counts reported by the provider ({"prompt_tokens", "completion_tokens"}), or None
    # when it reports none. Never estimated here.
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    """Chat completion with a JSON answer. A message's `content` is a string, or (for vision
    models) a list of OpenAI-style parts: {"type": "text", ...} and {"type": "image_url", ...}."""

    name: str

    async def complete_json(self, messages: list[dict[str, Any]]) -> Completion:
        """Return a JSON object answer. Raises ProviderError when every model fails."""
