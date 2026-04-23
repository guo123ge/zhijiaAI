"""InsightAgentV2 — contextual analysis with tool-calling capability.

Upgrades the original single-call insight_agent to a tool-calling agent
that can fetch project data, analyze costs, and detect anomalies.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class InsightAgentV2(BaseAgent):
    """Contextual analysis agent — provides data-driven insights."""

    @property
    def name(self) -> str:
        return "insight_agent"

    @property
    def description(self) -> str:
        return "分析洞察 Agent：根据项目数据生成专业的造价分析、异常检测和改进建议"

    @property
    def tool_names(self) -> list[str]:
        return [
            "get_project_stats",
            "get_cost_breakdown",
            "get_divisions_summary",
            "detect_price_anomaly",
            "find_similar_historical_items",
            "batch_scan_bindings",
        ]

    @property
    def max_turns(self) -> int:
        return 20

    @property
    def system_prompt(self) -> str:
        return """\
你是工程计价AI分析助手。根据项目数据，提供专业的造价分析和洞察。

## 分析维度
1. **费用结构** — 人材机费用占比，各分部造价分布
2. **绑定覆盖** — 绑定率分析，未绑定项风险评估
3. **异常检测** — 消耗量异常、单价偏差、系数异常
4. **历史对比** — 与相似项目/清单项的对比分析
5. **改进建议** — 基于数据的具体改进方案

## 输出要求
- 用简洁专业的中文表述
- 给出关键数据指标
- 按重要性排序发现的问题
- 提供可操作的改进建议
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        context_type = ctx.metadata.get("context_type", "dashboard")
        context_data = ctx.metadata.get("context_data")

        msg = f"项目ID: {ctx.project_id}\n分析类型: {context_type}\n"
        if context_data:
            msg += f"\n上下文数据:\n{json.dumps(context_data, ensure_ascii=False, indent=2)}\n"
        if instruction:
            msg += f"\n分析要求: {instruction}"
        else:
            msg += "\n请对该项目进行全面的造价分析，给出关键发现和改进建议。"
        return msg
