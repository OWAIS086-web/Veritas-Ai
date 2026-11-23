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


class LLMProvider(Protocol):
    name: str

    async def complete_json(self, messages: list[dict[str, str]]) -> Completion:
        """Return a JSON object answer. Raises ProviderError when every model fails."""
