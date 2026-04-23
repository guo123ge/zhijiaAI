"""Report tools — generate structured valuation reports and project summaries.

These tools produce rich JSON payloads for both UI display and export.
"""

from __future__ import annotations

import json
from collections import defaultdict

from app.ai.framework.context import AgentContext
from app.ai.framework.tool_def import tool
from app.ai.framework.tool_registry import registry
from app.models.boq_item import BoqItem
from app.models.calc_result import CalcResult
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.project import Project
from app.models.quota_item import QuotaItem


# ────────────────────────────────────────────────
# Project summary report
# ────────────────────────────────────────────────


@tool(
    name="get_project_summary_report",
    description=(
        "生成项目概况报告：项目信息 + BOQ 统计 + 绑定率 + "
        "费用分解 + 问题列表。返回完整结构化 JSON。"
    ),
    read_only=True,
)
def get_project_summary_report(ctx: AgentContext) -> str:
    project = ctx.db.query(Project).filter(Project.id == ctx.project_id).first()
    if not project:
        return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

    # BOQ items
    items = ctx.db.query(BoqItem).filter(BoqItem.project_id == ctx.project_id).order_by(BoqItem.sort_order).all()
    boq_ids = [i.id for i in items]

    # Bindings
    bound_ids = set()
    if boq_ids:
        bound_ids = {
            r.boq_item_id
            for r in ctx.db.query(LineItemQuotaBinding)
            .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
            .all()
        }

    # Calc results
    calc_results = (
        ctx.db.query(CalcResult).filter(CalcResult.boq_item_id.in_(boq_ids)).all()
        if boq_ids else []
    )
    calc_map = {c.boq_item_id: c for c in calc_results}

    # Division breakdown
    divisions: dict[str, dict] = defaultdict(lambda: {"count": 0, "bound": 0, "total_cost": 0.0})
    for item in items:
        div = item.division or "未分类"
        divisions[div]["count"] += 1
        if item.id in bound_ids:
            divisions[div]["bound"] += 1
        c = calc_map.get(item.id)
        if c:
            divisions[div]["total_cost"] += c.total_cost or 0

    total_cost = sum(c.total_cost or 0 for c in calc_results)

    # ── Warnings ──
    warnings = []
    unbound_names = [i.name for i in items if i.id not in bound_ids]
    if unbound_names:
        warnings.append(f"{len(unbound_names)} 项未绑定定额: {', '.join(unbound_names[:5])}{'...' if len(unbound_names) > 5 else ''}")
    zero_qty = [i.name for i in items if i.quantity == 0]
    if zero_qty:
        warnings.append(f"{len(zero_qty)} 项工程量为0: {', '.join(zero_qty[:5])}{'...' if len(zero_qty) > 5 else ''}")

    # Budget variance
    budget_info = {}
    if project.budget and project.budget > 0:
        variance = total_cost - project.budget
        budget_info = {
            "budget": project.budget,
            "variance": round(variance, 2),
            "variance_pct": f"{variance / project.budget * 100:+.1f}%",
            "status": "超支" if variance > 0 else "结余",
        }

    return json.dumps({
        "project": {
            "id": project.id,
            "name": project.name,
            "region": project.region,
            "project_type": project.project_type,
            "standard_type": project.standard_type,
            "status": project.status,
            "budget": project.budget,
        },
        "statistics": {
            "total_items": len(items),
            "bound_count": len(bound_ids),
            "unbound_count": len(items) - len(bound_ids),
            "binding_rate": f"{len(bound_ids)/len(items)*100:.1f}%" if items else "0%",
            "calculated_items": len(calc_results),
            "total_cost": round(total_cost, 2),
        },
        "budget_analysis": budget_info,
        "warnings": warnings,
        "division_breakdown": [
            {
                "division": k,
                "item_count": v["count"],
                "bound_count": v["bound"],
                "binding_rate": f"{v['bound']/v['count']*100:.0f}%" if v["count"] else "0%",
                "total_cost": round(v["total_cost"], 2),
            }
            for k, v in sorted(divisions.items(), key=lambda x: -x[1]["total_cost"])
        ],
    }, ensure_ascii=False)


# ────────────────────────────────────────────────
# Full valuation report
# ────────────────────────────────────────────────


@tool(
    name="generate_valuation_report",
    description=(
        "生成完整工程计价报告数据：费用汇总表、分部分项工程计价表、"
        "综合单价分析表。返回可直接用于 UI 展示或导出的结构化 JSON。"
    ),
    read_only=True,
)
def generate_valuation_report(ctx: AgentContext) -> str:
    project = ctx.db.query(Project).filter(Project.id == ctx.project_id).first()
    if not project:
        return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

    # All items
    items = (
        ctx.db.query(BoqItem)
        .filter(BoqItem.project_id == ctx.project_id)
        .order_by(BoqItem.sort_order)
        .all()
    )
    boq_ids = [i.id for i in items]

    # Bindings
    all_bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
        .all()
    ) if boq_ids else []
    binding_map: dict[int, list] = defaultdict(list)
    for b in all_bindings:
        binding_map[b.boq_item_id].append(b)

    # Quotas
    quota_ids = {b.quota_item_id for b in all_bindings}
    quotas = (
        {q.id: q for q in ctx.db.query(QuotaItem).filter(QuotaItem.id.in_(quota_ids)).all()}
        if quota_ids else {}
    )

    # Calc results
    calc_results = (
        ctx.db.query(CalcResult).filter(CalcResult.boq_item_id.in_(boq_ids)).all()
        if boq_ids else []
    )
    calc_map = {c.boq_item_id: c for c in calc_results}

    # ── Build line-item detail table ──
    line_items = []
    for item in items:
        c = calc_map.get(item.id)
        item_bindings = binding_map.get(item.id, [])
        bound_quotas = []
        for b in item_bindings:
            q = quotas.get(b.quota_item_id)
            if q:
                bound_quotas.append({
                    "quota_code": q.quota_code,
                    "quota_name": q.name,
                    "unit": q.unit,
                    "coefficient": b.coefficient,
                    "labor_qty": q.labor_qty,
                    "material_qty": q.material_qty,
                    "machine_qty": q.machine_qty,
                })

        line_items.append({
            "boq_item_id": item.id,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "quantity": item.quantity,
            "division": item.division,
            "characteristics": item.characteristics,
            "total_cost": round(c.total_cost, 2) if c else None,
            "unit_price": round(c.total_cost / item.quantity, 2) if c and item.quantity else None,
            "is_bound": len(item_bindings) > 0,
            "quotas": bound_quotas,
        })

    # ── Division summary ──
    div_summary: dict[str, dict] = defaultdict(lambda: {"count": 0, "total": 0.0})
    for li in line_items:
        div = li["division"] or "未分类"
        div_summary[div]["count"] += 1
        div_summary[div]["total"] += li["total_cost"] or 0

    grand_total = sum(li["total_cost"] or 0 for li in line_items)

    # ── Cost summary (try using project_calc_service for detailed breakdown) ──
    cost_summary = {"grand_total": round(grand_total, 2)}
    try:
        from app.services.project_calc_service import run_project_calculation
        summary, _ = run_project_calculation(project_id=ctx.project_id, db=ctx.db)
        cost_summary = {
            "total_direct": summary.total_direct,
            "total_management": summary.total_management,
            "total_profit": summary.total_profit,
            "total_regulatory": summary.total_regulatory,
            "total_pre_tax": summary.total_pre_tax,
            "total_tax": summary.total_tax,
            "total_measures": summary.total_measures,
            "grand_total": summary.grand_total,
        }
    except Exception:
        pass

    # ── Warnings ──
    warnings = []
    unbound = [li for li in line_items if not li["is_bound"]]
    if unbound:
        warnings.append(f"{len(unbound)} 项未绑定定额")
    zero_cost = [li for li in line_items if li["is_bound"] and (li["total_cost"] or 0) == 0]
    if zero_cost:
        warnings.append(f"{len(zero_cost)} 项已绑定但计算结果为0")
    # Price anomaly: top 3 most expensive items
    sorted_by_cost = sorted(
        [li for li in line_items if li["total_cost"]],
        key=lambda x: x["total_cost"], reverse=True,
    )
    top3 = sorted_by_cost[:3]

    # Budget variance
    budget_analysis = {}
    if project.budget and project.budget > 0:
        variance = grand_total - project.budget
        budget_analysis = {
            "budget": project.budget,
            "actual": round(grand_total, 2),
            "variance": round(variance, 2),
            "variance_pct": f"{variance / project.budget * 100:+.1f}%",
        }

    # Token-efficient: truncate line_items for AI context (keep full for first 30, summary for rest)
    MAX_DETAIL = 30
    line_items_output = line_items[:MAX_DETAIL]
    if len(line_items) > MAX_DETAIL:
        remaining = line_items[MAX_DETAIL:]
        line_items_output.append({
            "_truncated": True,
            "remaining_count": len(remaining),
            "remaining_total": round(sum(li["total_cost"] or 0 for li in remaining), 2),
        })

    return json.dumps({
        "report_type": "valuation_report",
        "project": {
            "id": project.id,
            "name": project.name,
            "region": project.region,
            "standard_type": project.standard_type,
            "project_type": project.project_type,
            "currency": project.currency,
        },
        "cost_summary": cost_summary,
        "budget_analysis": budget_analysis,
        "division_summary": [
            {"division": k, "item_count": v["count"], "subtotal": round(v["total"], 2)}
            for k, v in sorted(div_summary.items(), key=lambda x: -x[1]["total"])
        ],
        "top_cost_items": [
            {"name": li["name"], "code": li["code"], "total": li["total_cost"]}
            for li in top3
        ],
        "warnings": warnings,
        "line_items": line_items_output,
        "statistics": {
            "total_items": len(items),
            "bound_items": sum(1 for li in line_items if li["is_bound"]),
            "calculated_items": sum(1 for li in line_items if li["total_cost"] is not None),
        },
    }, ensure_ascii=False)


# ────────────────────────────────────────────────
# Register
# ────────────────────────────────────────────────

registry.register_many(
    get_project_summary_report,
    generate_valuation_report,
)
