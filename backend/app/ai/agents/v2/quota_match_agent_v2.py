"""QuotaMatchAgentV2 — quota reranking with tool-calling capability.

Upgrades the original single-call quota_match_agent to a tool-calling agent
that can search quotas, check details, and compare candidates.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class QuotaMatchAgentV2(BaseAgent):
    """Quota matching/reranking agent — finds best quota for a BOQ item."""

    @property
    def name(self) -> str:
        return "quota_match_agent"

    @property
    def description(self) -> str:
        return "定额匹配 Agent：为清单项搜索和排序最佳候选定额，给出匹配理由和置信度"

    @property
    def tool_names(self) -> list[str]:
        return [
            "search_quotas",
            "get_quota_detail",
            "search_standard_codes",
            "get_resource_details",
            "find_similar_historical_items",
        ]

    @property
    def max_turns(self) -> int:
        return 12

    @property
    def system_prompt(self) -> str:
        return """\
你是定额匹配专家。根据清单项信息，搜索并推荐最合适的定额。

## 🚨 核心原则：主动搜索，不要反问

**你收到的任务描述中已经包含了清单项信息。立即使用 `search_quotas` 开始搜索，禁止反问用户要求提供清单项信息。**

任务类型识别：
1. **批量匹配** — 任务包含多个清单项 → 逐项调用 `search_quotas`，每项推荐 Top 1-3 候选
2. **单项匹配** — 任务只有一个清单项 → 深入搜索，推荐 Top 3-5 候选
3. **只要有清单名称和单位** → 就足够开始搜索，不需要其他信息

## 匹配策略
1. **名称匹配** — 用清单名称作为关键词调用 search_quotas
2. **单位兼容** — 优先选择单位一致的定额
3. **标准编码** — 根据清单编码查找标准要求
4. **历史参考** — 参考相似清单项的绑定方案

## 输出要求
- 每个清单项推荐候选定额
- 每个候选给出匹配理由和置信度(0-1)
- 说明是否需要组合多条定额

## 严禁
- ❌ 反问用户"请提供清单项信息" —— 任务描述里已经有了
- ❌ 返回 0 次工具调用 —— 至少要调用一次 search_quotas
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        # Priority 1: structured metadata (called from API with pre-filled context)
        boq_info = ctx.metadata.get("boq_info", {})
        candidates = ctx.metadata.get("candidates", [])

        if boq_info:
            msg = "请为以下清单项推荐最合适的定额：\n"
            msg += json.dumps(boq_info, ensure_ascii=False, indent=2) + "\n"
            if candidates:
                msg += f"\n已有 {len(candidates)} 个候选定额供参考，请评估排序。\n"
            if instruction:
                msg += f"\n补充说明：{instruction}"
            return msg

        # Priority 2: single BOQ item from context
        boq = ctx.get_boq_item()
        if boq:
            return (
                f"请为以下清单项推荐最合适的定额：\n"
                f"id={boq.id} | 编码: {boq.code} | 名称: {boq.name} | "
                f"单位: {boq.unit} | 工程量: {boq.quantity} | "
                f"特征: {boq.characteristics or '无'}\n"
                f"项目ID: {ctx.project_id}\n\n"
                + (f"补充说明：{instruction}" if instruction else "")
            )

        # Priority 3: text instruction from orchestrator (batch mode)
        # The instruction itself contains BOQ item data — pass it through directly.
        parts = [f"项目ID: {ctx.project_id}"]
        if instruction:
            parts.append(instruction)
        else:
            parts.append("请搜索项目中未绑定清单项的候选定额。")

        # Also try to enumerate unbound items like cost_execute does.
        unbound_preview = self._preview_unbound_items(ctx)
        if unbound_preview:
            parts.append(unbound_preview)
            parts.append(
                "⚠️ 这是一个**批量匹配任务**。"
                "按系统提示中的策略逐项搜索候选定额，**不要反问用户具体是哪一项**。"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _preview_unbound_items(ctx: AgentContext, limit: int = 25) -> str:
        """Return a compact preview of unbound BOQ items."""
        try:
            from app.models.boq_item import BoqItem
            from app.models.line_item_quota_binding import LineItemQuotaBinding
        except Exception:
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
            lines.append(f"- _... 还有 {len(unbound) - limit} 项_")
        return "\n".join(lines)
