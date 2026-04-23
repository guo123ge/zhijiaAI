"""CostPlanAgent — read-only pricing plan designer (Phase G2).

Inspired by Claude Code's Plan Agent:
- read_only=True: never modifies data
- Analyzes BOQ items and recommends pricing strategies
- Outputs structured plan without executing it
"""

from __future__ import annotations

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext


class CostPlanAgent(BaseAgent):
    """Read-only planning agent — designs pricing strategies without executing."""

    @property
    def name(self) -> str:
        return "cost_plan"

    @property
    def description(self) -> str:
        return "组价方案设计 Agent：分析清单项特征，搜索候选定额，设计组价策略方案（不执行绑定）"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def tool_names(self) -> list[str]:
        return [
            # Search tools for analysis
            "search_quotas",
            "get_quota_detail",
            "get_material_prices",
            "search_standard_codes",
            # BOQ analysis
            "query_boq_items",
            "list_unbound_items",
            "get_cost_breakdown",
            "get_divisions_summary",
            # Reference
            "search_boq",
            "view_bindings",
            "get_project_stats",
            "find_similar_historical_items",
            "get_resource_details",
            "list_current_bindings",
        ]

    @property
    def max_turns(self) -> int:
        return 12

    @property
    def system_prompt(self) -> str:
        return """\
你是工程造价组价方案设计师。你的职责是**分析和规划**，不执行任何修改操作。

## 工作流程
1. **理解需求** — 分析清单项的名称、特征、单位、工程量
2. **搜索标准** — 用 search_standard_codes 确认GB50500计量规则
3. **搜索定额** — 用 search_quotas 搜索候选定额，查看详情
4. **参考历史** — 用 find_similar_historical_items 查找相似案例
5. **设计方案** — 制定组价策略

## 输出格式（严格遵守）

### 清单项分析
- 编码/名称/特征/单位/工程量

### 推荐组价方案
| 序号 | 定额编码 | 定额名称 | 推荐系数 | 理由 |
|------|---------|---------|---------|------|
| 1    | ...     | ...     | 1.0     | ...  |

### 预估综合单价
- 人工费: ¥XX
- 材料费: ¥XX
- 机械费: ¥XX
- 综合单价: ¥XX

### 风险提示
- 列出需要注意的问题（单位换算、系数调整等）

### 关键文件清单
- 列出方案涉及的关键数据来源

## 重要
- **你只设计方案，不执行绑定操作**
- 如果找不到合适定额，明确说明并建议替代方案
- 方案要考虑多条定额组合的情况
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        """Inject BOQ item context if available."""
        boq = ctx.get_boq_item()
        if boq:
            return (
                f"请为以下清单项设计组价方案（只设计，不执行）：\n"
                f"编码: {boq.code}, 名称: {boq.name}, 单位: {boq.unit}, "
                f"工程量: {boq.quantity}, 特征: {boq.characteristics or '无'}\n"
                f"项目ID: {ctx.project_id}, 地区: {ctx.resolve_region() or '未设置'}"
            )

        project_ctx = ctx.build_project_context()
        msg = f"项目ID: {ctx.project_id}"
        if project_ctx:
            msg += f"\n{project_ctx}"
        if instruction:
            msg += f"\n\n{instruction}"
        return msg
