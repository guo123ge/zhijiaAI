"""Shared types for the Agent Framework.

Replaces the duplicated AgentStep / AgentResult dataclasses that were
copy-pasted across valuation_agent, validation_agent, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepType(str, Enum):
    """Kinds of steps in an agent reasoning chain."""
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ANSWER = "answer"
    ERROR = "error"


@dataclass
class AgentStep:
    """One step in the agent reasoning chain.

    Unified replacement for the identical AgentStep classes in
    valuation_agent.py and validation_agent.py.
    """
    type: StepType
    content: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: str = ""
    duration_ms: float = 0.0

    # Convenience for SSE serialization
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value, "content": self.content}
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.tool_args:
            d["tool_args"] = self.tool_args
        if self.tool_result:
            d["tool_result"] = self.tool_result
        if self.duration_ms:
            d["duration_ms"] = round(self.duration_ms, 1)
        return d


@dataclass
class AgentResult:
    """Complete result of an agent run.

    Generic enough for all agent types. Specific agents can subclass or
    add extra fields via the ``extra`` dict.
    """
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.steps if s.type == StepType.TOOL_RESULT)
