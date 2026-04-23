"""Audit Pipeline — end-to-end project quality audit.

Stage 1: BatchReviewAgent — scan all bindings for issues
Stage 2: InsightAgent — analyze cost structure and anomalies
Stage 3: ValidationAgent — deep-dive on critical issues
"""

from __future__ import annotations

from app.ai.agents.v2.batch_review_agent_v2 import BatchReviewAgentV2
from app.ai.agents.v2.insight_agent_v2 import InsightAgentV2
from app.ai.agents.v2.validation_agent_v2 import ValidationAgentV2
from app.ai.framework.pipeline import Pipeline, Stage


def build_audit_pipeline() -> Pipeline:
    """Build the project audit pipeline.

    Prerequisites: ctx.project_id must be set.

    Flow:
        1. BatchReview → scan all bindings, find issues
        2. Insight → analyze cost structure, detect anomalies
        3. Validation → deep-dive on worst issues
    """
    return Pipeline(
        name="project_audit",
        stages=[
            Stage(
                agent=BatchReviewAgentV2(),
                instruction=(
                    "对项目执行全面的绑定扫描审查：\n"
                    "1. 扫描所有绑定问题\n"
                    "2. 统计绑定覆盖率\n"
                    "3. 列出最严重的问题"
                ),
                max_turns=6,
            ),
            Stage(
                agent=InsightAgentV2(),
                instruction=(
                    "基于前序审查结果，进一步分析项目造价：\n"
                    "1. 分析费用结构是否合理\n"
                    "2. 检查各分部造价占比\n"
                    "3. 识别成本风险点"
                ),
                max_turns=5,
            ),
            Stage(
                agent=ValidationAgentV2(),
                instruction=(
                    "基于前序审查和分析结果，对最严重的问题进行深入校验：\n"
                    "1. 对标准编码合规性问题逐一核查\n"
                    "2. 对消耗量异常项做详细分析\n"
                    "3. 给出最终审计结论和风险评级"
                ),
                max_turns=6,
            ),
        ],
        stop_on_error=False,
    )
