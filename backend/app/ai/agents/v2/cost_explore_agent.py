"""CostExploreAgent — read-only fast search agent (Phase G1).

Inspired by Claude Code's Explore Agent:
- read_only=True: framework auto-filters destructive tools
- Uses only search/query tools, never modifies data
- Designed for fast model tier (haiku equivalent)
- Skips heavy project context to save tokens
"""

from __future__ import annotations

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext


class CostExploreAgent(BaseAgent):
    """Read-only exploration agent — fast search across quotas, BOQ, and prices."""

    @property
    def name(self) -> str:
        return "cost_explore"

    @property
    def description(self) -> str:
        return "造价探索 Agent：只读快速搜索定额库、清单项、材料价格、历史数据（不修改任何数据）"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def tool_names(self) -> list[str]:
        return [
            # Quota search (read-only subset)
            "search_quotas",
            "get_quota_detail",
            "get_material_prices",
            "search_standard_codes",
            # BOQ query
            "query_boq_items",
            "list_unbound_items",
            "get_cost_breakdown",
            "get_divisions_summary",
            # General query
            "search_boq",
            "view_bindings",
            "get_project_stats",
            # Validation (read-only)
            "find_similar_historical_items",
            "get_resource_details",
        ]

    @property
    def max_turns(self) -> int:
        return 8

    @property
    def max_tool_concurrency(self) -> int:
        return 5  # All tools are read-only, maximize parallelism

    @property
    def system_prompt(self) -> str:
        return """\
你是工程造价数据探索助手。你只负责搜索和查询，**绝不修改任何数据**。

## 你的能力
- 搜索定额库：按关键词、编码搜索定额，查看定额详情和资源明细
- 查询清单项：搜索、筛选BOQ项，查看绑定状态和费用分解
- 材料价格：查询材料信息价
- 历史对比：查找相似历史清单项
- 项目统计：获取项目概况、分部汇总

## 工作方式
1. 理解用户想查什么
2. 并行调用多个搜索工具获取数据
3. 综合结果，用简洁格式呈现

## 输出要求
- 数据量大时用表格展示
- 给出关键统计数字
- 如果搜索结果为空，建议调整搜索条件
- 不要建议"绑定"或"修改"操作，你无权执行
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        return f"项目ID: {ctx.project_id}\n\n搜索请求: {instruction}"
