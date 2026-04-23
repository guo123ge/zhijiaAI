"""TokenBudget — cost control per agent run.

Tracks token usage and enforces limits to prevent runaway costs.
Each agent run gets a budget; when exceeded, the agent is forced
to produce a final answer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TokenBudget:
    """Token and turn budget for a single agent run.

    Attributes:
        max_turns: Maximum number of LLM round-trips.
        max_input_tokens: Soft limit on cumulative input tokens.
        max_output_tokens: Soft limit on cumulative output tokens.
    """
    max_turns: int = 20
    max_input_tokens: int = 100_000
    max_output_tokens: int = 16_000

    # ── Tracking (mutated during run) ──
    turns_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    start_time: float = field(default_factory=time.time)

    # ── Checks ──

    @property
    def turns_remaining(self) -> int:
        return max(0, self.max_turns - self.turns_used)

    @property
    def is_turn_exceeded(self) -> bool:
        return self.turns_used >= self.max_turns

    @property
    def is_token_exceeded(self) -> bool:
        return (
            self.input_tokens_used >= self.max_input_tokens
            or self.output_tokens_used >= self.max_output_tokens
        )

    @property
    def should_force_answer(self) -> bool:
        """True when the agent should stop calling tools and give a final answer."""
        return self.is_turn_exceeded or self.is_token_exceeded

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    # ── Mutation ──

    def record_turn(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record one LLM round-trip."""
        self.turns_used += 1
        self.input_tokens_used += input_tokens
        self.output_tokens_used += output_tokens

    # ── Reporting ──

    def summary(self) -> dict:
        return {
            "turns": f"{self.turns_used}/{self.max_turns}",
            "input_tokens": f"{self.input_tokens_used}/{self.max_input_tokens}",
            "output_tokens": f"{self.output_tokens_used}/{self.max_output_tokens}",
            "elapsed_s": round(self.elapsed_seconds, 1),
        }
