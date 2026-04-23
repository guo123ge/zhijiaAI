"""BaseAgent — abstract base class with unified agent reasoning loop.

Eliminates the duplicated loop in valuation_agent, validation_agent, etc.
Subclasses only need to define:
  - name, description, system_prompt
  - tool_names (which tools from the registry to use)

The loop logic (call LLM → parse tool_calls → execute → append → repeat)
lives here once.

Usage:
    class ValuationAgent(BaseAgent):
        name = "valuation_agent"
        description = "智能组价 Agent"
        system_prompt = "你是一位专业的工程计价AI助手..."
        tool_names = ["search_quotas", "bind_quota", ...]

    agent = ValuationAgent()
    result = agent.run(ctx, instruction="为该清单项组价")
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.ai.framework.budget import TokenBudget
from app.ai.framework.context import AgentContext
from app.ai.framework.tool_registry import ToolRegistry, registry as global_registry
from app.ai.framework.trace_collector import TraceCollector
from app.ai.framework.types import AgentResult, AgentStep, StepType
from app.ai.observability import log_ai_call
from app.ai.providers import AIProviderError, get_ai_provider

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all AI agents.

    Subclasses define WHAT the agent does (prompt, tools).
    This class handles HOW it runs (loop, budget, step tracking, streaming).
    """

    # ── Subclass must define ──

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier (e.g. 'valuation_agent')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description for Orchestrator routing."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt for this agent."""
        ...

    @property
    @abstractmethod
    def tool_names(self) -> list[str]:
        """List of tool names this agent can use (from ToolRegistry)."""
        ...

    # ── Optional overrides ──

    @property
    def max_turns(self) -> int:
        """Default max LLM round-trips. Override per agent if needed."""
        return 20

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        """Build the initial user message. Override for custom context injection.

        When use_memory_context is True (H3), this auto-prepends relevant
        cross-session memories from ctx.memory.
        """
        if self.use_memory_context:
            memory_block = self.build_memory_context(ctx)
            if memory_block:
                return f"{memory_block}\n\n## 任务\n{instruction}"
        return instruction

    def on_result(self, ctx: AgentContext, result: AgentResult) -> AgentResult:
        """Post-processing hook. Override to add agent-specific fields to result."""
        return result

    # ── Optional overrides (Phase F) ──

    @property
    def read_only(self) -> bool:
        """If True, framework auto-filters destructive tools. (F2)"""
        return False

    @property
    def max_tool_concurrency(self) -> int:
        """Max parallel tool executions for concurrency-safe tools. (F1)"""
        return 5

    @property
    def compact_threshold_tokens(self) -> int:
        """Input token threshold to trigger auto-compaction. (F5)
        Set to 0 to disable. Default 8000 keeps prompts bounded across
        multi-turn tool loops and prevents runaway LLM latency/timeouts.
        Reasoning models (kimi-k2.5 etc.) have hidden reasoning tokens that
        multiply real cost, so a lower threshold is safer.
        """
        return 8000

    # ── Optional overrides (Phase H3: Agent Memory) ──

    @property
    def use_memory_context(self) -> bool:
        """If True, build_user_message injects relevant memories. (H3)
        Requires ctx.memory to be set. Default: False for backward compatibility."""
        return False

    @property
    def memory_context_limit(self) -> int:
        """Max memories per scope to inject into context. (H3)"""
        return 5

    def build_memory_context(self, ctx: AgentContext) -> str:
        """Build a text block summarizing relevant memories for this run. (H3)

        Returns empty string if no memory store is attached or no memories exist.
        Called by build_user_message() when use_memory_context is True.
        """
        store = getattr(ctx, "memory", None)
        if store is None:
            return ""

        try:
            memories = store.collect_relevant(
                user_id=ctx.user_id,
                project_id=ctx.project_id,
                limit_per_scope=self.memory_context_limit,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("build_memory_context failed: %s", e)
            return ""

        if not memories:
            return ""

        lines = ["## 历史记忆（跨会话）"]
        for m in memories:
            scope_tag = f"[{m.scope}]"
            tags = f" #{','.join(m.tags)}" if m.tags else ""
            lines.append(f"- {scope_tag} **{m.key}** (重要度 {m.importance}){tags}: {m.content}")
        return "\n".join(lines)

    # ── Core loop ──

    def run(
        self,
        ctx: AgentContext,
        instruction: str,
        *,
        on_step: Callable[[AgentStep], None] | None = None,
        budget: TokenBudget | None = None,
        registry: ToolRegistry | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        """Run the agent reasoning loop.

        Args:
            ctx: Runtime context (db, project_id, etc.)
            instruction: User instruction / task description
            on_step: Optional callback for SSE streaming of each step
            budget: Optional token budget (defaults to self.max_turns)
            registry: Optional tool registry (defaults to global)
            conversation_history: Prior turns as [{"role": "user"|"assistant", "content": str}, ...].
                When provided, these are inserted between the system prompt and the new user
                message, so the agent sees the full dialogue. Memory/skill hints still apply
                only to the *new* instruction (via build_user_message).

        Returns:
            AgentResult with answer, steps, and optional error.
        """
        reg = registry or global_registry
        effective_budget = budget or TokenBudget(max_turns=self.max_turns)
        ctx.budget = effective_budget

        # Initialize trace collector
        trace = TraceCollector(agent_name=self.name, ctx=ctx)
        trace.start(instruction)

        # Check AI provider
        provider = get_ai_provider()
        if not provider.is_enabled() or not provider.is_configured():
            result = AgentResult(answer="AI 服务未配置，无法执行任务。", error="ai_not_configured")
            trace.finish(result)
            trace.persist()
            return result

        trace.set_model_info(provider=type(provider).__name__, model=getattr(provider, 'model', ''))

        # Resolve tools (F2: filter destructive tools for read-only agents)
        effective_tool_names = self.tool_names
        if self.read_only:
            effective_tool_names = [
                n for n in self.tool_names
                if (t := reg.get(n)) is not None and not t.destructive
            ]
        tool_schemas = reg.get_openai_schemas(effective_tool_names)
        if not tool_schemas:
            logger.warning("Agent '%s' has no tools resolved", self.name)

        # Build initial messages
        user_msg = self.build_user_message(ctx, instruction)
        ctx.metadata["current_instruction"] = instruction
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        if conversation_history:
            for m in conversation_history:
                role = m.get("role")
                content = m.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_msg})

        steps: list[AgentStep] = []
        repeated_validation_failures: dict[str, int] = {}
        consecutive_delegate_failures: dict[str, int] = {}
        # B5: Track no-progress turns — a turn with 0 tool calls OR only
        # read-only tool calls with identical args to a recent turn counts
        # as "no progress". After N consecutive no-progress turns, we inject
        # a reflection directive forcing the LLM to re-plan.
        recent_tool_signatures: list[str] = []
        no_progress_turns = 0
        reflection_injected_at_turn = -1

        # ── Main loop ──
        while not effective_budget.should_force_answer:
            # A1: Microcompact first — cheap, preserves tool_call_id pairings.
            # Elides old tool_result content; keeps last N fresh.
            threshold = self.compact_threshold_tokens
            over_token_budget = threshold > 0 and effective_budget.input_tokens_used > threshold
            over_msg_budget = len(messages) > 12
            if over_token_budget or over_msg_budget:
                messages, bytes_saved = self._microcompact_messages(messages)
                if bytes_saved > 0:
                    trace.record_microcompact(bytes_saved)
                    logger.info(
                        "Agent '%s': microcompacted messages (saved %d bytes, tokens=%d, msgs=%d)",
                        self.name, bytes_saved, effective_budget.input_tokens_used, len(messages),
                    )

            # F5: Full compact (LLM-aware summarization) only when micro wasn't enough.
            # We use a higher bar (1.5x threshold) to avoid replacing the structured
            # tool history whenever possible — full compact breaks tool_call_id
            # pairings and requires costly re-grounding.
            did_full_compact = False
            if over_token_budget and effective_budget.input_tokens_used > int(threshold * 1.5):
                messages = self._compact_messages(messages)
                did_full_compact = True
                logger.info(
                    "Agent '%s': full-compacted messages (tokens used: %d > %d)",
                    self.name, effective_budget.input_tokens_used, int(threshold * 1.5),
                )
            # F5b: Fallback full compact by message count when API gives no usage.
            elif over_msg_budget and len(messages) > 20:
                messages = self._compact_messages(messages)
                did_full_compact = True
                logger.info(
                    "Agent '%s': full-compacted messages (message count: %d > 20)",
                    self.name, len(messages),
                )

            # A3: Post-compact re-grounding. When a full-compact replaced the
            # tool-result history with a text summary, the model loses its
            # freshest knowledge of project state. We re-inject a compact
            # project snapshot as a user message so the next turn isn't blind.
            if did_full_compact:
                trace.record_full_compact()
                snapshot = self._build_post_compact_snapshot(ctx)
                if snapshot:
                    messages.append({"role": "user", "content": snapshot})

            messages = self._sanitize_messages_for_provider(messages)

            turn_start = time.time()
            try:
                response = provider.generate_with_tools(
                    task=self.name,
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                )
            except AIProviderError as exc:
                logger.error("Agent '%s' provider error at turn %d: %s", self.name, effective_budget.turns_used, exc)
                error_step = AgentStep(type=StepType.ERROR, content=str(exc))
                steps.append(error_step)
                if on_step:
                    on_step(error_step)

                # If we already completed some tool steps, return a partial
                # result instead of a bare error — the work done so far is
                # still valuable to the caller / orchestrator.
                answer_steps = [s for s in steps if s.type == StepType.ANSWER]
                tool_steps = [s for s in steps if s.type == StepType.TOOL_RESULT]
                if tool_steps and not answer_steps:
                    partial_summary = self._summarize_partial_steps(tool_steps, str(exc))
                    result = self.on_result(ctx, AgentResult(
                        answer=partial_summary,
                        steps=steps,
                        error="provider_error_partial",
                    ))
                else:
                    result = self.on_result(ctx, AgentResult(
                        answer=f"AI 调用失败: {exc}",
                        steps=steps,
                        error="provider_error",
                    ))
                trace.finish(result)
                trace.persist()
                return result

            # Record budget + trace usage
            turn_usage = response.get("usage", {}) or {}
            turn_input = turn_usage.get("input_tokens", 0)
            turn_output = turn_usage.get("output_tokens", 0)
            turn_cache = turn_usage.get("cache_hit_tokens", 0) or 0
            turn_reasoning = turn_usage.get("reasoning_content") or ""
            effective_budget.record_turn(input_tokens=turn_input, output_tokens=turn_output)
            trace.record_turn(
                input_tokens=turn_input,
                output_tokens=turn_output,
                cache_hit_tokens=turn_cache,
                reasoning_chars=len(turn_reasoning),
            )

            # A4: Log prompt-cache hits (auto-caching on DeepSeek/OpenAI/Moonshot).
            cache_hit = turn_usage.get("cache_hit_tokens", 0)
            if cache_hit and turn_input > 0:
                logger.info(
                    "Agent '%s': prompt cache hit %d/%d tokens (%.0f%%)",
                    self.name, cache_hit, turn_input,
                    100 * cache_hit / turn_input,
                )

            # B2: Emit reasoning_content as a THINKING step for UI observability.
            # Do NOT append reasoning to ``messages`` — DeepSeek-reasoner explicitly
            # requires stripping it on subsequent turns (the model re-derives).
            reasoning_text = turn_usage.get("reasoning_content")
            if reasoning_text:
                thinking_step = AgentStep(
                    type=StepType.THINKING,
                    content=reasoning_text,
                )
                steps.append(thinking_step)
                if on_step:
                    on_step(thinking_step)

            # ── No tool calls → final answer ──
            if not response.get("tool_calls"):
                answer = response.get("content") or "任务完成。"
                answer_step = AgentStep(type=StepType.ANSWER, content=answer)
                steps.append(answer_step)
                if on_step:
                    on_step(answer_step)

                log_ai_call(
                    task=self.name,
                    provider=str(type(provider).__name__),
                    model="",
                    success=True,
                    duration_ms=int(effective_budget.elapsed_seconds * 1000),
                )

                result = self.on_result(ctx, AgentResult(answer=answer, steps=steps))
                trace.finish(result)
                trace.persist()
                return result

            # ── Thinking content (model text before tool calls) ──
            if response.get("content"):
                thinking_step = AgentStep(type=StepType.THINKING, content=response["content"])
                steps.append(thinking_step)
                if on_step:
                    on_step(thinking_step)

            # ── Build assistant message for conversation history ──
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in response["tool_calls"]
                ],
            }
            messages.append(assistant_msg)

            # ── Execute tool calls (F1: concurrent when safe) ──
            tool_steps, tool_messages = self._execute_tools(
                response["tool_calls"], reg, ctx, trace, on_step,
            )
            steps.extend(tool_steps)
            messages.extend(tool_messages)

            # ── Detect delegate sub-agent failures (anti-loop) ──
            for tc, ts in zip(response["tool_calls"], tool_steps):
                tool_name = tc.get("name", "")
                if tool_name.startswith("delegate_") and ts.tool_result:
                    try:
                        result_data = json.loads(ts.tool_result)
                        calls_made = result_data.get("tool_calls_made", -1)
                        has_error = result_data.get("error")
                        if calls_made == 0 or has_error:
                            consecutive_delegate_failures[tool_name] = (
                                consecutive_delegate_failures.get(tool_name, 0) + 1
                            )
                            if consecutive_delegate_failures[tool_name] >= 2:
                                warning = (
                                    f"⚠️ {tool_name} 已连续 {consecutive_delegate_failures[tool_name]} 次"
                                    f"未能完成任务（tool_calls_made={calls_made}）。"
                                    f"请不要再调用同一个 Agent。换一种策略："
                                    f"使用其他 Agent，或你自己直接用工具完成任务。"
                                )
                                messages.append({"role": "user", "content": warning})
                        else:
                            consecutive_delegate_failures.pop(tool_name, None)
                    except (json.JSONDecodeError, TypeError):
                        pass

            validation_feedback = self._build_validation_feedback(
                tool_steps,
                repeated_validation_failures,
            )
            if validation_feedback:
                feedback_step = AgentStep(type=StepType.ERROR, content=validation_feedback)
                steps.append(feedback_step)
                if on_step:
                    on_step(feedback_step)
                messages.append({"role": "user", "content": validation_feedback})

            # ── B5: No-progress detection + Reflection injection ──
            turn_signature = self._tool_call_signature(response["tool_calls"])
            made_progress = self._turn_made_progress(turn_signature, recent_tool_signatures, reg)
            if made_progress:
                no_progress_turns = 0
            else:
                no_progress_turns += 1
            recent_tool_signatures.append(turn_signature)
            if len(recent_tool_signatures) > 5:
                recent_tool_signatures = recent_tool_signatures[-5:]

            if (
                no_progress_turns >= 3
                and reflection_injected_at_turn != effective_budget.turns_used
            ):
                reflection_msg = (
                    "⚠️ 反思时间（本轮不要调用任何工具，用纯文本回答）：\n"
                    "你已经连续 3 轮没有取得实质进展——要么没调工具，要么在重复调同样参数的只读工具。\n"
                    "请回答下面三个问题：\n"
                    "1. **当前任务我已经掌握了什么关键信息？**（列要点）\n"
                    "2. **还差什么才能交付结果？**（具体到要写入的数据或要调用的写操作）\n"
                    "3. **下一步我要调用哪个工具（或放弃并给用户最终回答）？** 若调工具，请说明参数和预期。\n"
                    "完成反思后，下一轮再按计划执行。"
                )
                messages.append({"role": "user", "content": reflection_msg})
                reflection_injected_at_turn = effective_budget.turns_used
                no_progress_turns = 0
                trace.record_reflection()
                reflection_step = AgentStep(type=StepType.THINKING, content="[系统注入反思节点]")
                steps.append(reflection_step)
                if on_step:
                    on_step(reflection_step)

            if self._should_abort_after_repeated_validation_failures(repeated_validation_failures):
                result = self.on_result(ctx, AgentResult(
                    answer="工具调用多次参数无效，请检查已返回的参数错误并调整后重试。",
                    steps=steps,
                    error="tool_validation_failed",
                ))
                trace.finish(result)
                trace.persist()
                return result

        # ── Budget exceeded ──
        logger.warning(
            "Agent '%s' exceeded budget: %s",
            self.name,
            effective_budget.summary(),
        )
        result = self.on_result(ctx, AgentResult(
            answer="任务执行超过限制，请查看已完成的步骤。",
            steps=steps,
            error="budget_exceeded",
        ))
        trace.finish(result)
        trace.persist()
        return result

    # ── F1: Tool execution with concurrency support ──

    @staticmethod
    def _execute_single_tool(
        tc: dict[str, Any],
        reg: ToolRegistry,
        ctx: AgentContext,
    ) -> tuple[str, float]:
        """Execute one tool call. Returns (result_str, duration_ms).

        OPT-2: In-run read-only result cache. If the same ``(tool, args)`` was
        already executed this run AND the tool is ``read_only``, serve the
        cached result annotated with a cache notice. Stops LLMs from spinning
        on the same query before B5 reflection kicks in.
        """
        name = tc["name"]
        args = tc.get("arguments") or {}
        tool_def = reg.get(name)
        cache: dict[str, str] | None = None
        cache_key: str | None = None
        if tool_def is not None and getattr(tool_def, "read_only", False):
            try:
                cache_key = name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                cache_key = None
            if cache_key is not None:
                cache = ctx.metadata.setdefault("_readonly_tool_cache", {})
                cached = cache.get(cache_key)
                if cached is not None:
                    # Serve from cache with a small prefix so the model knows.
                    return (
                        '{"_cached_from_this_run": true, "hint": "此工具此参数本轮已查询过，'
                        '下方是缓存结果。若需最新数据请调用会改变状态的写操作后再查。", '
                        '"cached_result": ' + cached + "}"
                    ), 0.0
        t0 = time.time()
        result_str = reg.execute(name, args, ctx)
        duration_ms = (time.time() - t0) * 1000
        if cache is not None and cache_key is not None:
            # Only cache non-error results to avoid pinning transient failures.
            if not result_str.lstrip().startswith('{"error"'):
                cache[cache_key] = result_str
        return result_str, duration_ms

    def _execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
        reg: ToolRegistry,
        ctx: AgentContext,
        trace: TraceCollector,
        on_step: Callable[[AgentStep], None] | None,
    ) -> tuple[list[AgentStep], list[dict[str, Any]]]:
        """Execute tool calls with concurrency partitioning (F1).

        Consecutive concurrency-safe tools run in parallel;
        non-safe tools run serially one at a time.

        Returns (steps, tool_result_messages) preserving original order.
        """
        all_steps: list[AgentStep] = []
        all_messages: list[dict[str, Any]] = []

        prepared_tool_calls = [self._prepare_tool_call(tc, reg, ctx) for tc in tool_calls]

        # Partition into batches: (is_concurrent, [tool_call_dicts])
        batches: list[tuple[bool, list[dict[str, Any]]]] = []
        for tc in prepared_tool_calls:
            tool_def = reg.get(tc["name"])
            safe = tool_def.is_concurrency_safe if tool_def else False
            if batches and batches[-1][0] and safe:
                batches[-1][1].append(tc)
            else:
                batches.append((safe, [tc]))

        for is_concurrent, batch in batches:
            # Emit tool_call steps upfront
            for tc in batch:
                call_step = AgentStep(
                    type=StepType.TOOL_CALL,
                    tool_name=tc["name"],
                    tool_args=tc["arguments"],
                )
                if on_step:
                    on_step(call_step)

            if is_concurrent and len(batch) > 1:
                # ── Parallel execution ──
                logger.info(
                    "Agent '%s': running %d concurrency-safe tools in parallel",
                    self.name, len(batch),
                )
                results: dict[str, tuple[str, float]] = {}
                max_workers = min(len(batch), self.max_tool_concurrency)
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    future_to_tc = {
                        pool.submit(self._execute_single_tool, tc, reg, ctx): tc
                        for tc in batch
                    }
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        try:
                            result_str, duration_ms = future.result()
                        except Exception as exc:
                            logger.error("Parallel tool %s failed: %s", tc["name"], exc)
                            result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)
                            duration_ms = 0.0
                        results[tc["id"]] = (result_str, duration_ms)

                # Emit results in original order
                for tc in batch:
                    trace.record_tool_call(tc["name"])
                    result_str, duration_ms = results[tc["id"]]
                    step = AgentStep(
                        type=StepType.TOOL_RESULT,
                        tool_name=tc["name"],
                        tool_args=tc["arguments"],
                        tool_result=result_str,
                        duration_ms=duration_ms,
                    )
                    all_steps.append(step)
                    if on_step:
                        on_step(step)
                    all_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": self._truncate_tool_result(result_str),
                    })
            else:
                # ── Serial execution ──
                for tc in batch:
                    trace.record_tool_call(tc["name"])
                    result_str, duration_ms = self._execute_single_tool(tc, reg, ctx)
                    # OPT-2: destructive tools invalidate the read-only cache
                    # because project state may have changed.
                    td = reg.get(tc["name"])
                    if td is not None and getattr(td, "destructive", False):
                        ctx.metadata.pop("_readonly_tool_cache", None)
                    step = AgentStep(
                        type=StepType.TOOL_RESULT,
                        tool_name=tc["name"],
                        tool_args=tc["arguments"],
                        tool_result=result_str,
                        duration_ms=duration_ms,
                    )
                    all_steps.append(step)
                    if on_step:
                        on_step(step)
                    all_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": self._truncate_tool_result(result_str),
                    })

        return all_steps, all_messages

    @staticmethod
    def _prepare_tool_call(
        tc: dict[str, Any],
        reg: ToolRegistry,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        prepared = dict(tc)
        arguments = dict(tc.get("arguments") or {})
        tool_name = prepared.get("name", "")
        instruction = str(ctx.metadata.get("current_instruction", "") or "").strip()
        if tool_name in {"match_skills_semantic", "search_memory_semantic"}:
            if not any(arguments.get(key) for key in ("query", "q", "task", "instruction")):
                if instruction:
                    arguments["query"] = instruction
        elif tool_name == "load_skill":
            if not arguments.get("name") and instruction:
                top = BaseAgent._resolve_top_skill_name(instruction)
                if top:
                    arguments["name"] = top
        elif tool_name.startswith("delegate_"):
            if not arguments.get("task") and instruction:
                arguments["task"] = instruction
        prepared["arguments"] = arguments
        return prepared

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

    # ── Tool result truncation for LLM context ──

    @property
    def max_tool_result_chars(self) -> int:
        """Max characters of a tool_result sent back to the LLM. 0 = no truncation.

        The full result is always kept for UI display and traces; this only
        affects what the LLM sees in subsequent turns. Large JSON payloads
        (e.g. 500-item unbound lists) can blow up context and slow down or
        time out the next LLM call.
        """
        return 1200

    def _truncate_tool_result(self, content: str) -> str:
        """Truncate a tool_result string for LLM context.

        For JSON arrays with > 10 items, keep the first 10 and summarize the rest.
        Otherwise slice to max_tool_result_chars with an explicit truncation notice.
        """
        limit = self.max_tool_result_chars
        if limit <= 0 or len(content) <= limit:
            return content

        # Try smart truncation for JSON arrays
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content[:limit] + " ... (truncated)"

        if isinstance(parsed, dict):
            for key, val in list(parsed.items()):
                if isinstance(val, list) and len(val) > 10:
                    parsed[key] = val[:10]
                    parsed[f"_{key}_truncated"] = f"... {len(val) - 10} more items"
            truncated = json.dumps(parsed, ensure_ascii=False)
            if len(truncated) > limit:
                return truncated[:limit] + " ... (truncated)"
            return truncated

        return content[:limit] + " ... (truncated)"

    @staticmethod
    def _parse_tool_result_payload(result: str) -> dict[str, Any] | None:
        try:
            data = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    def _build_validation_feedback(
        self,
        tool_steps: list[AgentStep],
        repeated_validation_failures: dict[str, int],
    ) -> str:
        feedback_lines: list[str] = []
        for step in tool_steps:
            payload = self._parse_tool_result_payload(step.tool_result)
            if not payload or payload.get("error_type") != "validation_error":
                continue

            fingerprint = json.dumps(
                {"tool_name": step.tool_name, "tool_args": step.tool_args},
                ensure_ascii=False,
                sort_keys=True,
            )
            repeated_validation_failures[fingerprint] = (
                repeated_validation_failures.get(fingerprint, 0) + 1
            )
            details = payload.get("details") or {}
            accepted_params = details.get("accepted_params") or []
            suggested_args = details.get("suggested_args") or {}
            param_descriptions = details.get("param_descriptions") or {}
            retry_hint = payload.get("retry_hint") or ""
            line = f"工具 `{step.tool_name}` 参数无效：{payload.get('error', '参数校验失败')}"
            if accepted_params:
                line += f"。可用参数：{', '.join(accepted_params)}"
            if param_descriptions:
                desc_parts = [
                    f"{name}={param_descriptions[name]}"
                    for name in accepted_params
                    if name in param_descriptions
                ]
                if desc_parts:
                    line += f"。参数说明：{'; '.join(desc_parts)}"
            if suggested_args:
                line += "。请改为使用参数：" + json.dumps(suggested_args, ensure_ascii=False)
            if retry_hint:
                line += f"。{retry_hint}"
            if repeated_validation_failures[fingerprint] > 1:
                line += "。相同参数已重复失败，请不要原样重试。"
            feedback_lines.append(f"- {line}")

        if not feedback_lines:
            return ""

        return "\n".join([
            "以下工具调用参数需要修正后再继续：",
            *feedback_lines,
        ])

    @staticmethod
    def _should_abort_after_repeated_validation_failures(
        repeated_validation_failures: dict[str, int],
    ) -> bool:
        return any(count >= 2 for count in repeated_validation_failures.values())

    # ── A3: Post-compact re-grounding ──

    def _build_post_compact_snapshot(self, ctx: "AgentContext") -> str:
        """Build a compact fresh snapshot of project state to re-inject after
        a full-compact. Override in subclasses for domain-specific snapshots.

        Default: project metadata + BOQ item count + division breakdown.
        Returns an empty string when no project context is available.
        """
        if not getattr(ctx, "project_id", None):
            return ""
        try:
            project = ctx.get_project()
        except Exception:
            project = None
        parts: list[str] = ["🔄 [上下文压缩后的项目快照 — 最新状态]"]
        if project:
            meta_bits = [f"项目：{project.name}", f"地区：{project.region}"]
            if getattr(project, "project_type", None):
                meta_bits.append(f"类型：{project.project_type}")
            if getattr(project, "budget", None):
                meta_bits.append(
                    f"预算：{project.currency} {float(project.budget):,.0f}"
                )
            parts.append(" | ".join(meta_bits))
        try:
            from app.models.boq_item import BoqItem
            from collections import Counter
            items = ctx.db.query(BoqItem).filter(
                BoqItem.project_id == ctx.project_id
            ).all()
            if items:
                div_counts = Counter((i.division or "未分类") for i in items)
                div_str = ", ".join(
                    f"{d}({c})" for d, c in div_counts.most_common(8)
                )
                parts.append(f"已有清单项：{len(items)} 条 — {div_str}")
            else:
                parts.append("清单项：0 条（项目为空）")
        except Exception:
            pass
        parts.append("请基于此快照继续任务，不要重复已完成的查询。")
        return "\n".join(parts)

    # ── B5: No-progress / reflection helpers ──

    @staticmethod
    def _tool_call_signature(tool_calls: list[dict[str, Any]]) -> str:
        """Canonical signature of a turn's tool calls for progress tracking.

        Returns a stable string like 'get_project_stats()|list_unbound_items({})'.
        Empty when the turn had no tool calls (final-answer turn).
        """
        if not tool_calls:
            return ""
        parts: list[str] = []
        for tc in tool_calls:
            name = tc.get("name", "?")
            args = tc.get("arguments") or {}
            try:
                args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                args_str = str(args)
            parts.append(f"{name}({args_str})")
        return "|".join(sorted(parts))

    @staticmethod
    def _turn_made_progress(
        current_signature: str,
        recent_signatures: list[str],
        registry: ToolRegistry,
    ) -> bool:
        """Decide whether the just-finished turn made progress.

        A turn counts as progress when:
        - It called at least one tool, AND
        - Either the signature is new, OR it called at least one destructive
          (write) tool — repeating a write is still forward motion.
        """
        if not current_signature:
            return False
        if current_signature not in recent_signatures:
            return True
        # Same signature as before — was it a write? Then still progress.
        for token in current_signature.split("|"):
            name = token.split("(", 1)[0]
            tool = registry.get(name)
            if tool is not None and getattr(tool, "destructive", False):
                return True
        return False

    @staticmethod
    def _summarize_partial_steps(
        tool_steps: list[AgentStep],
        error_msg: str,
    ) -> str:
        """Synthesize a user-visible answer from partial tool results when
        the provider fails mid-run (e.g. timeout after many turns).

        This preserves the work already done instead of showing only an error.
        """
        lines: list[str] = [
            "⚠️ AI 在处理过程中遇到错误，以下是已完成的部分结果：\n",
        ]
        for i, step in enumerate(tool_steps[:15], 1):
            content = (step.content or "").strip()
            if len(content) > 300:
                content = content[:300] + "…"
            if content:
                lines.append(f"**步骤 {i}**: {content}\n")
        if len(tool_steps) > 15:
            lines.append(f"_（还有 {len(tool_steps) - 15} 个步骤未显示）_\n")
        lines.append(f"\n**错误信息**: {error_msg}")
        lines.append("\n建议：可以重试此操作，或缩小任务范围后再试。")
        return "\n".join(lines)

    # ── H2: Streaming run ──

    @property
    def streaming_enabled(self) -> bool:
        """If True, stream_run() dispatches tools as they arrive. (H2)
        Override per agent to enable. Default: False for backward compatibility."""
        return False

    def stream_run(
        self,
        ctx: AgentContext,
        instruction: str,
        *,
        on_step: Callable[[AgentStep], None] | None = None,
        budget: TokenBudget | None = None,
        registry: ToolRegistry | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        """Run the agent using the streaming path. (H2)

        Same semantics as run(), but dispatches tool executions the moment
        each tool_call is assembled from the provider's stream, overlapping
        LLM network latency with tool execution.

        If the provider does not implement streaming, transparently falls back
        to the synchronous run() path.
        """
        provider = get_ai_provider()
        if not provider.is_enabled() or not provider.is_configured():
            return self.run(ctx, instruction, on_step=on_step,
                            budget=budget, registry=registry,
                            conversation_history=conversation_history)
        if not provider.supports_streaming():
            logger.info(
                "Agent '%s': provider does not support streaming, using sync run()",
                self.name,
            )
            return self.run(ctx, instruction, on_step=on_step,
                            budget=budget, registry=registry,
                            conversation_history=conversation_history)

        from app.ai.framework.streaming_executor import StreamingToolExecutor

        reg = registry or global_registry
        effective_budget = budget or TokenBudget(max_turns=self.max_turns)
        ctx.budget = effective_budget

        trace = TraceCollector(agent_name=self.name, ctx=ctx)
        trace.start(instruction)
        trace.set_model_info(
            provider=type(provider).__name__, model=getattr(provider, "model", "")
        )

        # Resolve tools (F2: filter destructive for read-only)
        effective_tool_names = self.tool_names
        if self.read_only:
            effective_tool_names = [
                n for n in self.tool_names
                if (t := reg.get(n)) is not None and not t.destructive
            ]
        tool_schemas = reg.get_openai_schemas(effective_tool_names)

        user_msg = self.build_user_message(ctx, instruction)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        if conversation_history:
            for m in conversation_history:
                role = m.get("role")
                content = m.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_msg})
        steps: list[AgentStep] = []
        ctx.metadata["current_instruction"] = instruction
        repeated_validation_failures: dict[str, int] = {}

        while not effective_budget.should_force_answer:
            # A1 + F5: Same tiered compaction as run() — microcompact first,
            # fall back to full-compact only when micro wasn't enough.
            threshold = self.compact_threshold_tokens
            over_token_budget = threshold > 0 and effective_budget.input_tokens_used > threshold
            over_msg_budget = len(messages) > 12
            if over_token_budget or over_msg_budget:
                messages, bytes_saved = self._microcompact_messages(messages)
                if bytes_saved > 0:
                    trace.record_microcompact(bytes_saved)
            did_full_compact = False
            if over_token_budget and effective_budget.input_tokens_used > int(threshold * 1.5):
                messages = self._compact_messages(messages)
                did_full_compact = True
            elif over_msg_budget and len(messages) > 20:
                messages = self._compact_messages(messages)
                did_full_compact = True
            if did_full_compact:
                trace.record_full_compact()
                snapshot = self._build_post_compact_snapshot(ctx)
                if snapshot:
                    messages.append({"role": "user", "content": snapshot})
            messages = self._sanitize_messages_for_provider(messages)

            # Drive the stream
            stream = provider.generate_with_tools_stream(
                task=self.name,
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
            )
            executor = StreamingToolExecutor(
                registry=reg, ctx=ctx, trace=trace,
                max_concurrency=self.max_tool_concurrency,
                on_step=on_step,
                truncator=self._truncate_tool_result,
            )
            stream_result = executor.run(stream)

            # Record usage / budget
            in_tok = stream_result.usage.get("input_tokens", 0)
            out_tok = stream_result.usage.get("output_tokens", 0)
            in_cache = stream_result.usage.get("cache_hit_tokens", 0) or 0
            in_reasoning = stream_result.usage.get("reasoning_content") or ""
            effective_budget.record_turn(
                input_tokens=in_tok, output_tokens=out_tok
            )
            trace.record_turn(
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_hit_tokens=in_cache,
                reasoning_chars=len(in_reasoning),
            )

            # A4 cache + B2 reasoning (same as run() path).
            stream_cache_hit = stream_result.usage.get("cache_hit_tokens", 0)
            if stream_cache_hit and in_tok > 0:
                logger.info(
                    "Agent '%s' (stream): prompt cache hit %d/%d tokens (%.0f%%)",
                    self.name, stream_cache_hit, in_tok,
                    100 * stream_cache_hit / in_tok,
                )
            stream_reasoning = stream_result.usage.get("reasoning_content")
            if stream_reasoning:
                thinking_step = AgentStep(
                    type=StepType.THINKING, content=stream_reasoning,
                )
                steps.append(thinking_step)
                if on_step:
                    on_step(thinking_step)

            if stream_result.error:
                error_step = AgentStep(type=StepType.ERROR, content=stream_result.error)
                steps.append(error_step)
                if on_step:
                    on_step(error_step)
                result = self.on_result(ctx, AgentResult(
                    answer=f"AI 流式调用失败: {stream_result.error}",
                    steps=steps,
                    error="stream_error",
                ))
                trace.finish(result)
                trace.persist()
                return result

            # No tool calls → final answer
            if not stream_result.tool_calls:
                answer = stream_result.content or "任务完成。"
                answer_step = AgentStep(type=StepType.ANSWER, content=answer)
                steps.append(answer_step)
                if on_step:
                    on_step(answer_step)
                result = self.on_result(ctx, AgentResult(answer=answer, steps=steps))
                trace.finish(result)
                trace.persist()
                return result

            # Thinking content before tool calls
            if stream_result.content:
                thinking_step = AgentStep(
                    type=StepType.THINKING, content=stream_result.content
                )
                steps.append(thinking_step)

            # Append tool call steps + results to conversation
            steps.extend(stream_result.tool_steps)

            # Build assistant message w/ tool_calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": stream_result.content or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in stream_result.tool_calls
                ],
            }
            messages.append(assistant_msg)
            messages.extend(stream_result.tool_messages)

            validation_feedback = self._build_validation_feedback(
                stream_result.tool_steps,
                repeated_validation_failures,
            )
            if validation_feedback:
                feedback_step = AgentStep(type=StepType.ERROR, content=validation_feedback)
                steps.append(feedback_step)
                if on_step:
                    on_step(feedback_step)
                messages.append({"role": "user", "content": validation_feedback})

            if self._should_abort_after_repeated_validation_failures(repeated_validation_failures):
                result = self.on_result(ctx, AgentResult(
                    answer="工具调用多次参数无效，请检查已返回的参数错误并调整后重试。",
                    steps=steps,
                    error="tool_validation_failed",
                ))
                trace.finish(result)
                trace.persist()
                return result

        # Budget exceeded
        result = self.on_result(ctx, AgentResult(
            answer="任务执行超过限制，请查看已完成的步骤。",
            steps=steps,
            error="budget_exceeded",
        ))
        trace.finish(result)
        trace.persist()
        return result

    # ── Tool result truncation for LLM context ──

    @property
    def max_tool_result_chars(self) -> int:
        """Max characters of a tool_result sent back to the LLM. 0 = no truncation.

        The full result is always kept for UI display and traces; this only
        affects what the LLM sees in subsequent turns. Large JSON payloads
        (e.g. 500-item unbound lists) can blow up context and slow down or
        time out the next LLM call.
        """
        return 2000

    def _truncate_tool_result(self, content: str) -> str:
        """Truncate a tool_result string for LLM context.

        For JSON arrays with > 20 items, keep the first 20 and summarize the rest.
        Otherwise slice to max_tool_result_chars with an explicit truncation notice.
        """
        limit = self.max_tool_result_chars
        if limit <= 0 or len(content) <= limit:
            return content

        # Try smart truncation for JSON arrays
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                for key, val in list(parsed.items()):
                    if isinstance(val, list) and len(val) > 20:
                        parsed[key] = val[:20]
                        parsed[f"_{key}_truncated"] = (
                            f"original list had {len(val)} items; "
                            f"showing first 20 only (agent: {self.name})"
                        )
                smart = json.dumps(parsed, ensure_ascii=False)
                if len(smart) <= limit * 2:  # accept if reasonably smaller
                    return smart
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: simple slice
        return (
            content[:limit]
            + f"\n...[truncated: original {len(content)} chars, showing first {limit}]"
        )

    # ── F5: Auto-compaction ──

    _KEEP_RECENT = 6  # system + user + last 4 messages minimum

    # A1: Microcompact — stub for elided tool results
    _MICROCOMPACT_STUB = "[elided — see full result in trace, later turns can re-query if needed]"
    _MICROCOMPACT_KEEP_FRESH = 4  # keep the last N tool messages intact

    def _microcompact_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Tier-1 compaction: elide old tool_result content, preserving structure.

        Unlike ``_compact_messages`` (Tier-2), this:
        - Does NOT call the LLM.
        - Does NOT remove any messages — keeps all assistant/tool_use + tool_result
          pairings intact so ``tool_call_id`` references stay valid (Kimi/OpenAI
          reject broken pairings with HTTP 400).
        - Only replaces the ``content`` of OLD ``role=="tool"`` messages with a short
          stub. Fresh tool results (last N) are kept verbatim so the model can still
          act on them.

        Returns: (possibly mutated messages, bytes_saved).
        """
        bytes_saved = 0
        tool_positions = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_positions) <= self._MICROCOMPACT_KEEP_FRESH:
            return messages, 0

        # Positions to elide = everything except the last N tool messages
        elide_positions = set(tool_positions[:-self._MICROCOMPACT_KEEP_FRESH])
        if not elide_positions:
            return messages, 0

        compacted: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            if i in elide_positions:
                original = m.get("content", "") or ""
                if len(original) > len(self._MICROCOMPACT_STUB):
                    bytes_saved += len(original) - len(self._MICROCOMPACT_STUB)
                    new_msg = dict(m)
                    new_msg["content"] = self._MICROCOMPACT_STUB
                    compacted.append(new_msg)
                    continue
            compacted.append(m)
        return compacted, bytes_saved

    def _compact_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Summarize old messages to reduce token usage. (F5)

        Keeps: system prompt, initial user message, compact summary, last N msgs.
        """
        if len(messages) <= self._KEEP_RECENT:
            return messages

        message_groups = self._group_messages_for_history(messages)
        if len(message_groups) <= self._KEEP_RECENT:
            return messages

        # Split: [system, user_init, ...middle..., ...recent...]
        system_msg = message_groups[0][0]
        user_init = message_groups[1][0]
        recent_groups = message_groups[-(self._KEEP_RECENT - 2):]
        middle_groups = message_groups[2:-(self._KEEP_RECENT - 2)]

        if not middle_groups:
            return messages

        # Build a concise summary of the middle messages
        summary_parts: list[str] = []
        for group in middle_groups:
            msg = group[0]
            role = msg.get("role", "?")
            if role == "assistant":
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                    summary_parts.append(f"[Assistant called tools: {', '.join(names)}]")
                    for tool_msg in group[1:]:
                        tool_content = tool_msg.get("content", "")
                        preview = tool_content[:80] + "..." if len(tool_content) > 80 else tool_content
                        summary_parts.append(f"[Tool result: {preview}]")
                elif content:
                    summary_parts.append(f"[Assistant: {content[:120]}...]")
            elif role == "user":
                content = msg.get("content", "")
                summary_parts.append(f"[User: {content[:100]}]")

        compact_text = (
            f"[以下是之前 {sum(len(g) for g in middle_groups)} 条对话的摘要]\n"
            + "\n".join(summary_parts)
        )

        logger.debug(
            "Compacted %d middle messages into summary (%d chars)",
            sum(len(g) for g in middle_groups), len(compact_text),
        )

        return [
            system_msg,
            user_init,
            {"role": "user", "content": compact_text},
            *[msg for group in recent_groups for msg in group],
        ]

    @staticmethod
    def _group_messages_for_history(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        groups: list[list[dict[str, Any]]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")
            if role == "assistant" and msg.get("tool_calls"):
                group = [msg]
                expected_ids = {tc.get("id") for tc in msg.get("tool_calls", []) if tc.get("id")}
                i += 1
                while i < len(messages):
                    next_msg = messages[i]
                    if next_msg.get("role") != "tool":
                        break
                    tool_call_id = next_msg.get("tool_call_id")
                    if expected_ids and tool_call_id not in expected_ids:
                        break
                    group.append(next_msg)
                    i += 1
                groups.append(group)
                continue

            if role == "tool":
                i += 1
                continue

            groups.append([msg])
            i += 1
        return groups

    @classmethod
    def _sanitize_messages_for_provider(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        pending_tool_ids: set[str] = set()
        for msg in messages:
            role = msg.get("role")
            if role == "assistant":
                sanitized.append(msg)
                pending_tool_ids = {
                    tc.get("id")
                    for tc in msg.get("tool_calls", [])
                    if tc.get("id")
                }
                continue
            if role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if pending_tool_ids and tool_call_id in pending_tool_ids:
                    sanitized.append(msg)
                    pending_tool_ids.discard(tool_call_id)
                continue
            sanitized.append(msg)
            pending_tool_ids = set()
        return sanitized
