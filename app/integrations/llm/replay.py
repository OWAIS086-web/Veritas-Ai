"""Replays recorded provider answers (integration tests only; never wired into the app)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.integrations.llm.base import Completion, ProviderError


class ReplayProvider:
    """Returns recorded answers in order. A recorded entry of {"error": ...} simulates a
    provider failure; running out of recordings is also a failure."""

    def __init__(self, recordings: list[dict[str, Any]], model: str = "recorded-model") -> None:
        self.name = "replay"
        self._recordings = list(recordings)
        self._model = model
        self.requests: list[list[dict[str, str]]] = []

    @classmethod
    def from_file(cls, path: Path) -> ReplayProvider:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["responses"], model=data.get("model", "recorded-model"))

    async def complete_json(self, messages: list[dict[str, str]]) -> Completion:
        self.requests.append(messages)
        if not self._recordings:
            raise ProviderError("no recorded response left")
        entry = self._recordings.pop(0)
        if "error" in entry:
            raise ProviderError(str(entry["error"]))
        return Completion(entry["content"], self._model, self.name, 1)
