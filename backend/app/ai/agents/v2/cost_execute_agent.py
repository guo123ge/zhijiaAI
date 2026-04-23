"""CostExecuteAgent — full-permission execution agent (Phase G4).

Inspired by Claude Code's General-purpose Agent:
- Full tool access including destructive operations (bind/unbind)
- Designed for actual execution after planning
- Includes post-execution validation
"""

from __future__ import annotations

import json

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class CostExecuteAgent(BaseAgent):
    """Full-permission execution agent — binds quotas, modifies prices, validates results."""

    @property
    def name(self) -> str:
        return "cost_execute"

    @property
    def description(self) -> str:
        return "组价执行 Agent：执行定额绑定、单价修改、费用计算等写操作，并验证结果"

    @property
    def tool_names(self) -> list[str]:
        return [
            # Write operations
            "bind_quota",
            "unbind_quota",
            "batch_bind_quotas",
            "auto_match_and_bind",
            "batch_auto_match_all",
            "update_boq_item",
            # Calculation
            "calculate_cost",
            "batch_calculate_project",
            "recalculate_dirty",
            # Validation after execution
            "validate_binding",
            "check_code_compliance",
            # Reference tools for context
            "search_quotas",
            "get_quota_detail",
            "list_current_bindings",
            "list_unbound_items",
            "get_material_prices",
            "search_standard_codes",
            "get_cost_breakdown",
            "view_bindings",
            "get_resource_details",
        ]

    @property
    def max_turns(self) -> int:
        return 60

    @property
    def system_prompt(self) -> str:
        return """\
你是工程造价执行助手。你负责**实际执行**组价操作：绑定定额、计算费用、验证结果。

## 🚨 核心原则：执行优先，不要反问

**你是执行 Agent，不是咨询 Agent。用户把任务委派给你，意味着已经决定要执行。你的工作是"干活"，不是"问话"。**

任务范围识别（按优先级）：
1. **项目级批量任务** — 指令中出现"所有"、"全部"、"未绑定"、"批量"、"逐项" 等词，或用户消息包含 "为项目内所有..." → **立即调用 `view_bindings` 或 `list_current_bindings` 枚举清单项，然后逐项绑定**。禁止反问"具体哪一项？"。
2. **单项任务** — 上下文已注入单个清单项 → 按标准流程处理该项。
3. **指令完全空白**（连项目ID都没有）— 才可以请求澄清。

## 批量工作流（高效模式）
用户消息中已包含未绑定清单项列表。**不需要再调用 view_bindings 获取列表**。

**最快方式：**调用 `batch_auto_match_all()` 一键匹配并绑定所有未绑定项。

**逐项方式：**对每个未绑定项调用 `auto_match_and_bind(boq_item_id=X)` — 一步完成搜索+绑定。

**可控方式：**
1. `search_quotas(keyword=清单名称)` — 搜索候选定额
2. 收集好多组后用 `batch_bind_quotas(bindings=[...])` 一次提交（最多50组）

全部绑定完后优先调用 `recalculate_dirty`（只重算脏项，速度快），或 `batch_calculate_project`（全量重算）。
**不要**在批量模式下逐项调 validate_binding / calculate_cost / list_current_bindings，那会浪费轮数。

## 单项工作流（深入模式）
1. `search_quotas` + `get_quota_detail` 搜索候选
2. `bind_quota(boq_item_id=X)` 执行绑定
3. `calculate_cost(boq_item_id=X)` 验证并计算

## 执行原则
- **找不到精确定额**也要选最接近的候选绑定，不要跳过该项
- bind_quota 和 list_current_bindings 等工具在批量模式下**必须传 boq_item_id**

## 输出要求
- 结构化报告：✅ 成功绑定项 / ⚠️ 需人工复核项 / ❌ 无法绑定项
- 综合单价汇总表
- 无论中途出什么错，都要给出**部分结果**而不是空答案

## 严禁
- ❌ 反问用户"具体哪个清单项" —— 批量任务中这句话等于罢工
- ❌ 以"需要更多信息"为由返回 0 次工具调用
- ❌ 只做 `search_quotas` 不做 `bind_quota`（那是 `cost_plan` 的工作，不是你的）
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        """Inject BOQ item context for execution.

        For batch tasks (no single BOQ item), proactively enumerate unbound
        items so the agent has immediate data to act on, avoiding the
        "先询问用户具体哪一项" failure mode.
        """
        boq = ctx.get_boq_item()
        if boq:
            base = (
                f"请为以下清单项执行组价操作：\n"
                f"编码: {boq.code}, 名称: {boq.name}, 单位: {boq.unit}, "
                f"工程量: {boq.quantity}, 特征: {boq.characteristics or '无'}\n"
                f"项目ID: {ctx.project_id}, 地区: {ctx.resolve_region() or '未设置'}"
            )
            return f"{base}\n\n{instruction}" if instruction else base

        # Batch / project-level task — enumerate unbound items up-front.
        parts = [f"项目ID: {ctx.project_id}, 地区: {ctx.resolve_region() or '未设置'}"]
        if instruction:
            parts.append(f"执行任务: {instruction}")

        unbound_preview = self._preview_unbound_items(ctx)
        if unbound_preview:
            parts.append(unbound_preview)
            parts.append(
                "⚠️ 这是一个**项目级批量任务**。"
                "按系统提示中的「批量任务工作流程」逐项绑定，**不要反问用户具体是哪一项**。"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _preview_unbound_items(ctx: AgentContext, limit: int = 30) -> str:
        """Return a compact markdown preview of unbound BOQ items, or empty on failure."""
        try:
            from app.models.boq_item import BoqItem
            from app.models.line_item_quota_binding import LineItemQuotaBinding
        except Exception:  # pragma: no cover — model paths may differ
            return ""
        try:
            bound_ids = {
                b.boq_item_id
                for b in ctx.db.query(LineItemQuotaBinding).join(
                    BoqItem, BoqItem.id == LineItemQuotaBinding.boq_item_id
                ).filter(BoqItem.project_id == ctx.project_id).all()
            }
            items = (
                ctx.db.query(BoqItem)
                .filter(BoqItem.project_id == ctx.project_id)
                .order_by(BoqItem.id)
                .all()
            )
        except Exception:
            return ""

        unbound = [i for i in items if i.id not in bound_ids]
        if not unbound:
            return ""

        lines = [f"## 项目当前未绑定的清单项（共 {len(unbound)} 项）"]
        for it in unbound[:limit]:
            lines.append(
                f"- id={it.id} | {it.code} | {it.name} | 单位={it.unit} | 量={it.quantity}"
            )
        if len(unbound) > limit:
            lines.append(f"- _... 还有 {len(unbound) - limit} 项未列出（调用 `view_bindings` 获取完整清单）_")
        return "\n".join(lines)

    def on_result(self, ctx: AgentContext, result: AgentResult) -> AgentResult:
        """Track execution operations."""
        operations = []
        for s in result.steps:
            if s.tool_name in ("bind_quota", "unbind_quota", "batch_bind_quotas", "auto_match_and_bind"):
                operations.append({
                    "action": s.tool_name,
                    "args": s.tool_args,
                    "success": "error" not in (s.tool_result or ""),
                })
        result.extra["operations"] = operations
        result.extra["operations_count"] = len(operations)
        result.extra["bindings_changed"] = len(operations) > 0
        return result
