"""TraceCollector — automatic trace capture for agent runs.

Collects token usage, tool calls, timing, and results during an agent run,
then persists them to the agent_traces table.

Usage (integrated into BaseAgent.run automatically):
    collector = TraceCollector(agent_name="valuation_agent", ctx=ctx)
    collector.start()
    # ... agent loop ...
    collector.record_turn(input_tokens=100, output_tokens=50)
    collector.record_tool_call("search_quotas")
    # ... more turns ...
    collector.finish(result)
    collector.persist()  # writes to DB
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult, AgentStep, StepType

logger = logging.getLogger(__name__)

# ── Cost rates (USD per 1M tokens) ──
# Updated for common models. Extend as needed.
MODEL_COST_RATES: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "qwen-plus": {"input": 0.80, "output": 2.00},
    # Default fallback
    "_default": {"input": 1.00, "output": 3.00},
}


def estimate_cost_cents(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD cents for a given model and token counts."""
    rates = MODEL_COST_RATES.get(model, MODEL_COST_RATES["_default"])
    cost_usd = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    return round(cost_usd * 100, 4)  # Convert to cents


@dataclass
class TraceCollector:
    """Collects observability data during an agent run."""

    agent_name: str
    ctx: AgentContext
    parent_trace_id: int | None = None

    # Accumulated data
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    turns_used: int = 0
    tool_calls_made: int = 0
    tool_names_used: list[str] = field(default_factory=list)
    # C3: Observability
    cache_hit_tokens: int = 0
    reasoning_chars: int = 0
    microcompact_bytes_saved: int = 0
    full_compact_count: int = 0
    reflection_injections: int = 0

    # Timing
    _start_time: float = 0.0
    _end_time: float = 0.0

    # Result
    _result: AgentResult | None = None
    _instruction: str = ""

    def start(self, instruction: str = "") -> None:
        """Mark the start of an agent run."""
        self._start_time = time.time()
        self._instruction = instruction[:500]

    def record_turn(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        *,
        cache_hit_tokens: int = 0,
        reasoning_chars: int = 0,
    ) -> None:
        """Record token usage + optional observability signals for one LLM turn. (C3)"""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.turns_used += 1
        self.cache_hit_tokens += cache_hit_tokens
        self.reasoning_chars += reasoning_chars

    def record_tool_call(self, tool_name: str) -> None:
        """Record a tool call."""
        self.tool_calls_made += 1
        self.tool_names_used.append(tool_name)

    # C3: Observability hooks
    def record_microcompact(self, bytes_saved: int) -> None:
        self.microcompact_bytes_saved += bytes_saved

    def record_full_compact(self) -> None:
        self.full_compact_count += 1

    def record_reflection(self) -> None:
        self.reflection_injections += 1

    def set_model_info(self, provider: str, model: str) -> None:
        """Set the AI provider and model name."""
        self.provider = provider
        self.model = model

    def finish(self, result: AgentResult) -> None:
        """Mark the end of an agent run."""
        self._end_time = time.time()
        self._result = result

    @property
    def duration_ms(self) -> int:
        end = self._end_time or time.time()
        return int((end - self._start_time) * 1000)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_cents(self) -> float:
        return estimate_cost_cents(self.model, self.input_tokens, self.output_tokens)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict (useful for logging without DB)."""
        cache_ratio = (
            self.cache_hit_tokens / self.input_tokens
            if self.input_tokens > 0 else 0.0
        )
        return {
            "agent": self.agent_name,
            "model": self.model,
            "turns": self.turns_used,
            "tool_calls": self.tool_calls_made,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_cents": self.estimated_cost_cents,
            "duration_ms": self.duration_ms,
            "success": self._result.success if self._result else False,
            # C3 observability
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_hit_ratio": round(cache_ratio, 3),
            "reasoning_chars": self.reasoning_chars,
            "microcompact_bytes_saved": self.microcompact_bytes_saved,
            "full_compacts": self.full_compact_count,
            "reflections": self.reflection_injections,
        }

    def persist(self) -> int | None:
        """Write trace to the agent_traces DB table. Returns trace ID or None."""
        db = self.ctx.db
        if db is None:
            logger.debug("No DB session, skipping trace persist for '%s'", self.agent_name)
            return None

        try:
            from app.models.agent_trace import AgentTrace

            now = datetime.now(timezone.utc).isoformat()

            # Compact steps summary
            steps_summary = None
            if self._result and self._result.steps:
                steps_summary = json.dumps(
                    [
                        {
                            "type": s.type.value if hasattr(s.type, "value") else s.type,
                            "tool": s.tool_name or "",
                            "ms": int(s.duration_ms) if s.duration_ms else 0,
                        }
                        for s in self._result.steps
                    ],
                    ensure_ascii=False,
                )

            trace = AgentTrace(
                project_id=self.ctx.project_id,
                user_id=self.ctx.user_id,
                agent_name=self.agent_name,
                parent_trace_id=self.parent_trace_id,
                instruction=self._instruction,
                model=self.model,
                provider=self.provider,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                total_tokens=self.total_tokens,
                estimated_cost_cents=self.estimated_cost_cents,
                turns_used=self.turns_used,
                tool_calls_made=self.tool_calls_made,
                duration_ms=self.duration_ms,
                success=1 if (self._result and self._result.success) else 0,
                error=(self._result.error if self._result else None),
                answer_preview=(self._result.answer[:500] if self._result else None),
                steps_json=steps_summary,
                started_at=datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat() if self._start_time else now,
                finished_at=now,
            )

            db.add(trace)
            db.commit()
            db.refresh(trace)
            logger.info(
                "Trace saved: agent=%s id=%d tokens=%d cost=%.2f¢ duration=%dms",
                self.agent_name, trace.id, self.total_tokens,
                self.estimated_cost_cents, self.duration_ms,
            )
            return trace.id

        except Exception as exc:
            logger.warning("Failed to persist trace for '%s': %s", self.agent_name, exc)
            try:
                db.rollback()
            except Exception:
                pass
            return None
