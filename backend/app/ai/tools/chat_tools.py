"""Chat tools — extracted from chat_agent.py.

These tools handle BOQ search, binding viewing, and project stats
for the conversational assistant.
"""

from __future__ import annotations

import json

from app.ai.framework.context import AgentContext
from app.ai.framework.tool_def import tool
from app.ai.framework.tool_registry import registry
from app.models.boq_item import BoqItem
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.quota_item import QuotaItem


@tool(
    name="search_boq",
    description="在当前项目的清单中搜索条目，按名称或编码关键词匹配。",
    read_only=True,
)
def search_boq(ctx: AgentContext, *, keyword: str) -> str:
    items = ctx.db.query(BoqItem).filter(
        BoqItem.project_id == ctx.project_id,
    ).all()
    matched = [
        {
            "id": i.id,
            "code": i.code,
            "name": i.name,
            "unit": i.unit,
            "quantity": i.quantity,
            "division": i.division,
        }
        for i in items
        if keyword.lower() in (i.name or "").lower() or keyword.lower() in (i.code or "").lower()
    ][:20]
    return json.dumps({"results": matched, "total": len(matched)}, ensure_ascii=False)


@tool(
    name="view_bindings",
    description="查看指定清单项的定额绑定详情。",
    read_only=True,
)
def view_bindings(ctx: AgentContext, *, boq_item_id: int) -> str:
    bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id == boq_item_id)
        .all()
    )
    result = []
    for b in bindings:
        q = ctx.db.query(QuotaItem).filter(QuotaItem.id == b.quota_item_id).first()
        result.append({
            "binding_id": b.id,
            "quota_code": q.quota_code if q else "?",
            "quota_name": q.name if q else "?",
            "coefficient": b.coefficient,
        })
    return json.dumps({"bindings": result}, ensure_ascii=False)


@tool(
    name="get_project_stats",
    description="获取项目统计信息：清单总数、绑定覆盖率、计算汇总、分部概览、预算偏差等。",
    read_only=True,
)
def get_project_stats(ctx: AgentContext) -> str:
    from collections import defaultdict
    from app.models.calc_result import CalcResult
    from app.models.project import Project

    project = ctx.db.query(Project).filter(Project.id == ctx.project_id).first()
    items = ctx.db.query(BoqItem).filter(BoqItem.project_id == ctx.project_id).all()
    boq_ids = [i.id for i in items]
    bound_ids = set()
    if boq_ids:
        bound_ids = {
            r.boq_item_id
            for r in ctx.db.query(LineItemQuotaBinding)
            .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
            .all()
        }
    calc_results = (
        ctx.db.query(CalcResult).filter(CalcResult.boq_item_id.in_(boq_ids)).all()
        if boq_ids else []
    )
    calc_total = round(sum(c.total_cost or 0 for c in calc_results), 2)

    # Division summary (compact)
    div_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "bound": 0})
    for i in items:
        d = i.division or "未分类"
        div_stats[d]["count"] += 1
        if i.id in bound_ids:
            div_stats[d]["bound"] += 1
    divisions_compact = [
        {"div": k, "total": v["count"], "bound": v["bound"]}
        for k, v in sorted(div_stats.items())
    ]

    # Budget variance
    budget_info = {}
    if project and project.budget and project.budget > 0:
        variance = calc_total - project.budget
        budget_info = {
            "budget": project.budget,
            "variance": round(variance, 2),
            "status": "超支" if variance > 0 else "结余",
        }

    result = {
        "project_name": project.name if project else "",
        "standard_type": project.standard_type if project else "",
        "boq_count": len(items),
        "bound_count": len(bound_ids),
        "unbound_count": len(items) - len(bound_ids),
        "binding_rate": f"{len(bound_ids)/len(items)*100:.1f}%" if items else "0%",
        "calculated_count": len(calc_results),
        "calc_total": calc_total,
        "division_count": len(div_stats),
        "divisions": divisions_compact,
    }
    if budget_info:
        result["budget_analysis"] = budget_info
    return json.dumps(result, ensure_ascii=False)


# ────────────────────────────────────────────────
# Register all chat tools
# ────────────────────────────────────────────────

registry.register_many(
    search_boq,
    view_bindings,
    get_project_stats,
)
