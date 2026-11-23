"""Per-investigation budget. Checked before every agent step, model call and tool call.

Exceeding a limit raises `BudgetExhausted`. The workflow stops with status
`budget_exhausted` and keeps everything persisted so far.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings


class BudgetExhausted(Exception):
    def __init__(self, limit: str, used: int | float, maximum: int | float) -> None:
        super().__init__(f"{limit} budget exhausted ({used} of {maximum})")
        self.limit = limit
        self.used = used
        self.maximum = maximum


@dataclass
class Budget:
    max_iterations: int
    max_tool_calls: int
    max_tokens: int
    timeout_seconds: int
    iterations: int = 0
    tool_calls: int = 0
    tokens: int = 0
    # Model calls whose provider reported no token counts (they can't be counted).
    unmetered_calls: int = 0
    # Wall-clock seconds already spent in earlier worker sessions (a resumed run keeps them).
    elapsed_before: float = 0.0
    _started: float = field(default_factory=time.monotonic, repr=False)

    @classmethod
    def from_settings(cls) -> Budget:
        s = get_settings()
        return cls(
            max_iterations=s.investigation_max_iterations,
            max_tool_calls=s.investigation_max_tool_calls,
            max_tokens=s.investigation_max_tokens,
            timeout_seconds=s.investigation_timeout_seconds,
        )

    @classmethod
    def restore(cls, limits: dict[str, Any], usage: dict[str, Any]) -> Budget:
        """Rebuild from the persisted `budget` (limits) and `usage` columns."""
        return cls(
            max_iterations=int(limits["max_iterations"]),
            max_tool_calls=int(limits["max_tool_calls"]),
            max_tokens=int(limits["max_tokens"]),
            timeout_seconds=int(limits["timeout_seconds"]),
            iterations=int(usage.get("iterations", 0)),
            tool_calls=int(usage.get("tool_calls", 0)),
            tokens=int(usage.get("tokens", 0)),
            unmetered_calls=int(usage.get("unmetered_calls", 0)),
            elapsed_before=float(usage.get("elapsed_seconds", 0.0)),
        )

    def limits(self) -> dict[str, int]:
        return {
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def elapsed(self) -> float:
        return self.elapsed_before + (time.monotonic() - self._started)

    def usage(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "tokens": self.tokens,
            "unmetered_calls": self.unmetered_calls,
            "elapsed_seconds": round(self.elapsed, 2),
        }

    def check(self) -> None:
        if self.elapsed > self.timeout_seconds:
            raise BudgetExhausted("timeout_seconds", round(self.elapsed, 1), self.timeout_seconds)
        if self.tokens > self.max_tokens:
            raise BudgetExhausted("max_tokens", self.tokens, self.max_tokens)

    def start_iteration(self) -> None:
        self.check()
        if self.iterations >= self.max_iterations:
            raise BudgetExhausted("max_iterations", self.iterations, self.max_iterations)
        self.iterations += 1

    def start_tool_call(self) -> None:
        self.check()
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExhausted("max_tool_calls", self.tool_calls, self.max_tool_calls)
        self.tool_calls += 1

    def add_usage(self, usage: dict[str, int] | None) -> int | None:
        """Count a model call's tokens; returns the tokens counted, or None if unmetered."""
        if usage is None:
            self.unmetered_calls += 1
            return None
        spent = int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
        self.tokens += spent
        return spent
