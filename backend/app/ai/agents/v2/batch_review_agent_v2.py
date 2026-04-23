"""BatchReviewAgentV2 — batch audit with tool-calling capability.

Upgrades the original batch_review_agent (deterministic scan + AI summary)
to a tool-calling agent that can scan bindings, analyze issues, and
provide actionable recommendations.
"""

from __future__ import annotations

import json

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class BatchReviewAgentV2(BaseAgent):
    """Batch project audit agent — scans all bindings and produces report."""

    @property
    def name(self) -> str:
        return "batch_review_agent"

    @property
    def description(self) -> str:
        return "批量审查 Agent：扫描项目所有绑定，检测问题并生成审查报告"

    @property
    def tool_names(self) -> list[str]:
        return [
            "batch_scan_bindings",
            "get_project_stats",
            "get_cost_breakdown",
            "get_divisions_summary",
            "list_unbound_items",
            "check_code_compliance",
            "detect_price_anomaly",
        ]

    @property
    def max_turns(self) -> int:
        return 25

    @property
    def system_prompt(self) -> str:
        return """\
你是工程计价项目审查专家。你的任务是对整个项目进行全面审查。

## 审查流程
1. **绑定扫描** — 使用 batch_scan_bindings 扫描全项目绑定问题
2. **项目概况** — 使用 get_project_stats 和 get_divisions_summary 了解整体情况
3. **费用分析** — 使用 get_cost_breakdown 检查费用结构合理性
4. **重点检查** — 对发现的重点问题使用 check_code_compliance 或 detect_price_anomaly 深入分析
5. **生成报告** — 汇总所有发现，给出审查结论

## 报告格式
1. **项目概况** — 清单数量、绑定率、计算状态
2. **问题汇总** — 按严重程度分类（错误/警告/提示）
3. **重点问题** — 最需要关注的3-5个问题及详细分析
4. **改进建议** — 具体可操作的改进方案
5. **风险评估** — 当前项目的整体风险等级（高/中/低）

## 原则
- 问题要具体到清单项编码
- 建议要可操作
- 优先关注金额影响大的问题
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        project = ctx.get_project()
        project_name = project.name if project else f"ID={ctx.project_id}"
        msg = f"请对项目「{project_name}」(ID={ctx.project_id}) 进行全面审查。"
        if instruction:
            msg += f"\n\n特别关注：{instruction}"
        return msg

    def on_result(self, ctx: AgentContext, result: AgentResult) -> AgentResult:
        """Extract issue counts from batch_scan_bindings results."""
        for s in result.steps:
            if s.tool_name == "batch_scan_bindings" and s.tool_result:
                try:
                    data = json.loads(s.tool_result)
                    result.extra["total_items"] = data.get("total_items", 0)
                    result.extra["bound_count"] = data.get("bound_count", 0)
                    result.extra["unbound_count"] = data.get("unbound_count", 0)
                    result.extra["issue_count"] = data.get("issue_count", 0)
                except (json.JSONDecodeError, KeyError):
                    pass
        return result
