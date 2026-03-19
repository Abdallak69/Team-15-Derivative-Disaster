"""Circuit breaker helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CircuitBreaker:
    """Simple drawdown threshold evaluator."""

    level_one: float = 0.03
    level_two: float = 0.05

    def evaluate(self, drawdown_pct: float) -> str:
        """Return the action level for the supplied drawdown."""
        if drawdown_pct >= self.level_two:
            return "halt"
        if drawdown_pct >= self.level_one:
            return "reduce"
        return "ok"

