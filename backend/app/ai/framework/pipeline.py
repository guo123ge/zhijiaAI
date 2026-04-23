"""Pipeline — sequential multi-agent workflow execution.

A Pipeline chains multiple agents in order, passing context and results
between stages. Each stage can read the previous stage's output.

Usage:
    pipeline = Pipeline(
        name="full_pricing",
        stages=[
            Stage(agent=QuotaMatchAgentV2(), instruction="为清单项搜索最佳定额"),
            Stage(agent=ValuationAgentV2(), instruction="绑定推荐定额并计算综合单价"),
            Stage(agent=ValidationAgentV2(), instruction="校验绑定结果"),
        ],
    )
    result = pipeline.run(ctx, on_stage=callback)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.budget import TokenBudget
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult, AgentStep, StepType

logger = logging.getLogger(__name__)


@dataclass
class Stage:
    """One stage in a pipeline."""
    agent: BaseAgent
    instruction: str = ""
    max_turns: int | None = None  # Override agent default
    skip_if: Callable[[AgentContext, list["StageResult"]], bool] | None = None


@dataclass
class StageResult:
    """Result of a single pipeline stage."""
    stage_index: int
    agent_name: str
    result: AgentResult
    duration_s: float = 0.0

    @property
    def success(self) -> bool:
        return self.result.success

    @property
    def answer(self) -> str:
        return self.result.answer


@dataclass
class PipelineResult:
    """Complete result of a pipeline run."""
    pipeline_name: str
    stages: list[StageResult] = field(default_factory=list)
    final_answer: str = ""
    error: str | None = None
    total_duration_s: float = 0.0

    @property
    def success(self) -> bool:
        return self.error is None and all(s.success for s in self.stages)

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    def summary(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline_name,
            "stages_completed": self.stage_count,
            "success": self.success,
            "total_duration_s": round(self.total_duration_s, 1),
            "stages": [
                {
                    "index": s.stage_index,
                    "agent": s.agent_name,
                    "success": s.success,
                    "duration_s": round(s.duration_s, 1),
                    "tool_calls": s.result.tool_call_count,
                }
                for s in self.stages
            ],
            "error": self.error,
        }


class Pipeline:
    """Sequential multi-agent pipeline.

    Runs stages in order. Each stage's answer is injected into the next
    stage's instruction as context, so agents can build on previous results.
    """

    def __init__(
        self,
        name: str,
        stages: list[Stage],
        *,
        stop_on_error: bool = True,
    ) -> None:
        self.name = name
        self.stages = stages
        self.stop_on_error = stop_on_error

    def run(
        self,
        ctx: AgentContext,
        *,
        on_stage: Callable[[int, str, str], None] | None = None,
        on_step: Callable[[AgentStep], None] | None = None,
    ) -> PipelineResult:
        """Execute all pipeline stages sequentially.

        Args:
            ctx: Shared context for all stages.
            on_stage: Callback(stage_index, agent_name, status) for progress.
                      status is "start" | "done" | "error" | "skipped".
            on_step: Callback for individual agent steps (SSE streaming).

        Returns:
            PipelineResult with all stage results.
        """
        pipeline_start = time.time()
        stage_results: list[StageResult] = []
        previous_answers: list[str] = []

        for i, stage in enumerate(self.stages):
            agent_name = stage.agent.name

            # Check skip condition
            if stage.skip_if and stage.skip_if(ctx, stage_results):
                logger.info("Pipeline '%s' skipping stage %d (%s)", self.name, i, agent_name)
                if on_stage:
                    on_stage(i, agent_name, "skipped")
                continue

            if on_stage:
                on_stage(i, agent_name, "start")

            # Build instruction with previous context
            instruction = self._build_instruction(stage, previous_answers)

            # Run stage
            stage_start = time.time()
            budget = TokenBudget(max_turns=stage.max_turns or stage.agent.max_turns)

            try:
                result = stage.agent.run(
                    ctx,
                    instruction,
                    budget=budget,
                    on_step=on_step,
                )
            except Exception as exc:
                logger.error("Pipeline '%s' stage %d (%s) failed: %s", self.name, i, agent_name, exc)
                stage_result = StageResult(
                    stage_index=i,
                    agent_name=agent_name,
                    result=AgentResult(answer=f"Stage failed: {exc}", error="stage_exception"),
                    duration_s=time.time() - stage_start,
                )
                stage_results.append(stage_result)
                if on_stage:
                    on_stage(i, agent_name, "error")

                if self.stop_on_error:
                    return PipelineResult(
                        pipeline_name=self.name,
                        stages=stage_results,
                        final_answer=f"Pipeline stopped at stage {i} ({agent_name}): {exc}",
                        error="stage_exception",
                        total_duration_s=time.time() - pipeline_start,
                    )
                continue

            stage_result = StageResult(
                stage_index=i,
                agent_name=agent_name,
                result=result,
                duration_s=time.time() - stage_start,
            )
            stage_results.append(stage_result)
            previous_answers.append(result.answer)

            if on_stage:
                on_stage(i, agent_name, "done" if result.success else "error")

            # Stop on error if configured
            if not result.success and self.stop_on_error:
                return PipelineResult(
                    pipeline_name=self.name,
                    stages=stage_results,
                    final_answer=f"Pipeline stopped at stage {i} ({agent_name}): {result.error}",
                    error=result.error,
                    total_duration_s=time.time() - pipeline_start,
                )

        # All stages complete
        final_answer = stage_results[-1].answer if stage_results else "Pipeline has no stages."
        return PipelineResult(
            pipeline_name=self.name,
            stages=stage_results,
            final_answer=final_answer,
            total_duration_s=time.time() - pipeline_start,
        )

    def _build_instruction(self, stage: Stage, previous_answers: list[str]) -> str:
        """Build stage instruction with context from previous stages."""
        instruction = stage.instruction
        if previous_answers:
            context = "\n---\n".join(
                f"[Stage {i} result]\n{ans}"
                for i, ans in enumerate(previous_answers)
            )
            instruction = (
                f"## 前序阶段结果\n{context}\n\n"
                f"## 当前阶段任务\n{instruction}"
            )
        return instruction
