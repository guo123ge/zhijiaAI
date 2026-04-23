"""StreamingToolExecutor — dispatch tool executions as they stream from the LLM.

Phase H2: inspired by Claude Code's StreamingToolExecutor.

Key idea: in the synchronous pathway (`BaseAgent.run()`), we wait for the
LLM to emit ALL tool_calls before starting any tool execution. With streaming,
each tool_call can be executed the moment it is fully assembled from the stream,
overlapping LLM network latency with tool execution.

## Pipeline

                 ┌─────────────┐  events   ┌─────────────────┐  futures  ┌──────────┐
    LLM stream ──▶ provider    ├──────────▶ StreamingToolExec├──────────▶ executor │
                 │ (iter)       │           │ (orchestrator)  │           │ threads  │
                 └─────────────┘           └─────────────────┘           └──────────┘
                                                  │
                                                  ▼
                                           AgentStep events
                                          (on_step callback)

## Ordering guarantees

- Tool results are returned in the **same order** as tool_calls were received
  from the stream, so the conversation history remains deterministic.
- A concurrency-unsafe tool waits for all prior tool futures to complete before
  it starts, matching F1 semantics.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from app.ai.framework.context import AgentContext
from app.ai.framework.tool_registry import ToolRegistry
from app.ai.framework.trace_collector import TraceCollector
from app.ai.framework.types import AgentStep, StepType
from app.ai.providers.base import StreamEvent

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# Result container
# ───────────────────────────────────────────────────────────────────


@dataclass
class StreamRunResult:
    """Aggregate result of one streaming turn."""
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_steps: list[AgentStep] = field(default_factory=list)
    tool_messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ───────────────────────────────────────────────────────────────────
# StreamingToolExecutor
# ───────────────────────────────────────────────────────────────────


class StreamingToolExecutor:
    """Consumes provider StreamEvents and dispatches tool executions immediately.

    Usage:
        executor = StreamingToolExecutor(
            registry=reg, ctx=ctx, trace=trace,
            max_concurrency=5, on_step=cb,
        )
        result = executor.run(provider_stream)
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        ctx: AgentContext,
        trace: TraceCollector | None = None,
        max_concurrency: int = 5,
        on_step: Callable[[AgentStep], None] | None = None,
        truncator: Callable[[str], str] | None = None,
    ) -> None:
        self._reg = registry
        self._ctx = ctx
        self._trace = trace
        self._max_concurrency = max(1, max_concurrency)
        self._on_step = on_step
        self._truncator = truncator

    # ── Public API ──

    def run(self, stream: Iterator[StreamEvent]) -> StreamRunResult:
        """Drive the stream-to-execution pipeline and return aggregated results."""
        result = StreamRunResult()

        # One executor per turn to avoid leaks.
        with ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            # Ordered lists so we can append tool_results in the order
            # the tool_calls were received.
            futures: list[tuple[dict[str, Any], Future[tuple[str, float]]]] = []
            # Concurrency fences: if a non-safe tool is dispatched, all earlier
            # futures must complete before it starts. We enforce this by
            # blocking on prior futures before submitting the non-safe one.

            for event in stream:
                etype = event.get("type")

                if etype == "content_delta":
                    text = event.get("text", "")
                    if text:
                        result.content += text
                        # Emit a lightweight THINKING step for SSE progress.
                        if self._on_step:
                            step = AgentStep(
                                type=StepType.THINKING, content=text
                            )
                            self._on_step(step)

                elif etype == "tool_call":
                    tc = event.get("tool_call")
                    if not tc:
                        continue
                    tc_dict = dict(tc)  # coerce TypedDict to plain dict
                    tc_dict["arguments"] = self._autofill_arguments(
                        tc_dict.get("name", ""),
                        dict(tc_dict.get("arguments") or {}),
                    )
                    result.tool_calls.append(tc_dict)

                    # Emit TOOL_CALL step immediately
                    step = AgentStep(
                        type=StepType.TOOL_CALL,
                        tool_name=tc_dict["name"],
                        tool_args=tc_dict["arguments"],
                    )
                    result.tool_steps.append(step)
                    if self._on_step:
                        self._on_step(step)

                    if self._trace is not None:
                        self._trace.record_tool_call(tc_dict["name"])

                    td = self._reg.get(tc_dict["name"])
                    is_safe = bool(td and td.is_concurrency_safe)

                    if not is_safe:
                        # Flush all prior futures before dispatching a non-safe tool.
                        self._flush_pending(futures, result)

                    fut = pool.submit(
                        self._execute_one, tc_dict,
                    )
                    futures.append((tc_dict, fut))

                elif etype == "done":
                    result.usage = event.get("usage", {}) or {}
                    # fall through — finish draining futures below

                elif etype == "error":
                    result.error = event.get("error") or "stream_error"
                    break

            # Drain any remaining futures in order
            self._flush_pending(futures, result)

        return result

    # ── Internals ──

    _SEMANTIC_TOOLS_REQUIRING_QUERY: tuple[str, ...] = (
        "match_skills_semantic",
        "search_memory_semantic",
    )
    _QUERY_ALIAS_KEYS: tuple[str, ...] = ("query", "q", "task", "instruction")

    def _autofill_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        instruction = str(self._ctx.metadata.get("current_instruction", "") or "").strip()
        if tool_name in self._SEMANTIC_TOOLS_REQUIRING_QUERY:
            if not any(arguments.get(key) for key in self._QUERY_ALIAS_KEYS):
                if instruction:
                    arguments["query"] = instruction
            return arguments
        if tool_name == "load_skill":
            if not arguments.get("name") and instruction:
                top = self._resolve_top_skill_name(instruction)
                if top:
                    arguments["name"] = top
            return arguments
        # Generic fallback: any delegate_* sub-agent tool has a single required
        # `task` parameter. If the model omits it, inherit the current user
        # instruction so the sub-agent still receives actionable context
        # instead of looping on "缺少必填参数 task".
        if tool_name.startswith("delegate_"):
            if not arguments.get("task") and instruction:
                arguments["task"] = instruction
            return arguments
        return arguments

    @staticmethod
    def _resolve_top_skill_name(instruction: str) -> str | None:
        try:
            from app.ai.framework.skill_registry import skill_registry
        except Exception:  # pragma: no cover — defensive
            return None
        try:
            scored = skill_registry.match_semantic(query=instruction, limit=1)
        except Exception:  # pragma: no cover — defensive
            return None
        if not scored:
            return None
        _score, skill = scored[0]
        return getattr(skill, "name", None)

    def _execute_one(self, tc: dict[str, Any]) -> tuple[str, float]:
        # OPT-2: route through BaseAgent._execute_single_tool so the streaming
        # path shares the same per-run read-only cache as the non-stream path.
        from app.ai.framework.base_agent import BaseAgent
        try:
            result_str, duration_ms = BaseAgent._execute_single_tool(
                tc, self._reg, self._ctx
            )
        except Exception as exc:
            logger.exception("Streaming tool %s failed: %s", tc["name"], exc)
            return (
                json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
                0.0,
            )
        # Invalidate read-only cache after destructive writes so subsequent
        # reads observe fresh state.
        td = self._reg.get(tc["name"])
        if td is not None and getattr(td, "destructive", False):
            self._ctx.metadata.pop("_readonly_tool_cache", None)
        return result_str, duration_ms

    def _flush_pending(
        self,
        futures: list[tuple[dict[str, Any], Future[tuple[str, float]]]],
        result: StreamRunResult,
    ) -> None:
        """Wait for all pending futures (in order) and record their results."""
        while futures:
            tc, fut = futures.pop(0)
            try:
                result_str, duration_ms = fut.result()
            except Exception as exc:  # pragma: no cover — executor error
                result_str = json.dumps(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    ensure_ascii=False,
                )
                duration_ms = 0.0

            step = AgentStep(
                type=StepType.TOOL_RESULT,
                tool_name=tc["name"],
                tool_args=tc["arguments"],
                tool_result=result_str,
                duration_ms=duration_ms,
            )
            result.tool_steps.append(step)
            if self._on_step:
                self._on_step(step)

            result.tool_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": self._truncator(result_str) if self._truncator else result_str,
            })
