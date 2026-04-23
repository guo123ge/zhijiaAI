"""BOQ management tools — for boq_agent, query_agent, and batch_review_agent.

New tools that enable prompt-only agents to become tool-calling agents.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher

from app.ai.framework.context import AgentContext
from app.ai.framework.tool_def import tool
from app.ai.framework.tool_registry import registry
from app.models.boq_item import BoqItem
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.quota_item import QuotaItem
from app.services.validation_service import normalize_unit


@tool(
    name="query_boq_items",
    description="按条件查询项目清单项。支持按编码/名称/分部/单位/绑定状态筛选，支持分页。",
    read_only=True,
)
def query_boq_items(
    ctx: AgentContext,
    *,
    keyword: str = "",
    division: str = "",
    unit: str = "",
    bound_only: bool = False,
    unbound_only: bool = False,
    dirty_only: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> str:
    q = ctx.db.query(BoqItem).filter(BoqItem.project_id == ctx.project_id)

    if division:
        q = q.filter(BoqItem.division == division)
    if dirty_only:
        q = q.filter(BoqItem.is_dirty == 1)

    # DB-level keyword pre-filter
    if keyword and len(keyword) >= 2:
        q = q.filter(
            BoqItem.name.ilike(f"%{keyword}%") | BoqItem.code.ilike(f"%{keyword}%")
        )
        items = q.order_by(BoqItem.sort_order, BoqItem.id).all()
    else:
        items = q.order_by(BoqItem.sort_order, BoqItem.id).all()
        if keyword:
            kw = keyword.lower()
            items = [i for i in items if kw in (i.name or "").lower() or kw in (i.code or "").lower()]

    # Filter by unit
    if unit:
        items = [i for i in items if normalize_unit(i.unit) == normalize_unit(unit)]

    # Filter by binding status
    if bound_only or unbound_only:
        boq_ids = [i.id for i in items]
        bound_ids = set()
        if boq_ids:
            bound_ids = {
                r.boq_item_id
                for r in ctx.db.query(LineItemQuotaBinding)
                .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
                .all()
            }
        if bound_only:
            items = [i for i in items if i.id in bound_ids]
        elif unbound_only:
            items = [i for i in items if i.id not in bound_ids]

    total_matched = len(items)
    page_items = items[offset:offset + limit]

    results = [
        {
            "id": i.id,
            "code": i.code,
            "name": i.name,
            "unit": i.unit,
            "quantity": i.quantity,
            "division": i.division,
            "characteristics": i.characteristics or "",
            "remark": i.remark or "",
            "is_dirty": bool(i.is_dirty),
        }
        for i in page_items
    ]
    return json.dumps({
        "results": results,
        "total_matched": total_matched,
        "showing": len(results),
        "offset": offset,
        "has_more": (offset + limit) < total_matched,
    }, ensure_ascii=False)


@tool(
    name="list_unbound_items",
    description="列出项目中所有未绑定定额的清单项，按分部分组，附优先级提示。",
    read_only=True,
)
def list_unbound_items(ctx: AgentContext, *, limit: int = 50, division: str = "") -> str:
    q = ctx.db.query(BoqItem).filter(BoqItem.project_id == ctx.project_id)
    if division:
        q = q.filter(BoqItem.division == division)
    items = q.order_by(BoqItem.sort_order, BoqItem.id).all()

    boq_ids = [i.id for i in items]
    bound_ids = set()
    if boq_ids:
        bound_ids = {
            r.boq_item_id
            for r in ctx.db.query(LineItemQuotaBinding)
            .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
            .all()
        }

    unbound = [i for i in items if i.id not in bound_ids]

    # Group by division with count
    from collections import Counter
    div_counts = Counter(i.division or "未分类" for i in unbound)
    by_division = [
        {"division": d, "count": c}
        for d, c in div_counts.most_common()
    ]

    results = [
        {
            "id": i.id, "code": i.code, "name": i.name,
            "unit": i.unit, "quantity": i.quantity,
            "division": i.division or "未分类",
        }
        for i in unbound[:limit]
    ]

    # Priority hint: largest division first
    hint = ""
    if by_division:
        top_div = by_division[0]
        hint = f"建议优先处理「{top_div['division']}」（{top_div['count']}项未绑定）"

    return json.dumps({
        "unbound_items": results,
        "unbound_count": len(unbound),
        "total_items": len(items),
        "by_division": by_division,
        "priority_hint": hint,
    }, ensure_ascii=False)


@tool(
    name="get_cost_breakdown",
    description="获取项目的费用分解汇总：人工费、材料费、机械费、管理费、利润、总价，附TOP5高成本项和单方指标。",
    read_only=True,
)
def get_cost_breakdown(ctx: AgentContext) -> str:
    from app.models.calc_result import CalcResult
    from app.models.project import Project

    items = ctx.db.query(BoqItem).filter(BoqItem.project_id == ctx.project_id).all()
    boq_ids = [i.id for i in items]

    if not boq_ids:
        return json.dumps({"message": "项目无清单项"}, ensure_ascii=False)

    calc_results = ctx.db.query(CalcResult).filter(CalcResult.boq_item_id.in_(boq_ids)).all()
    if not calc_results:
        return json.dumps({"message": "项目尚未计算", "boq_count": len(items)}, ensure_ascii=False)

    total_labor = sum(c.labor_cost or 0 for c in calc_results)
    total_material = sum(c.material_cost or 0 for c in calc_results)
    total_machine = sum(c.machine_cost or 0 for c in calc_results)
    total_direct = sum(c.direct_cost or 0 for c in calc_results)
    total_management = sum(c.management_fee or 0 for c in calc_results)
    total_profit = sum(c.profit or 0 for c in calc_results)
    total_cost = sum(c.total_cost or 0 for c in calc_results)

    # Breakdown by division
    div_totals: dict[str, float] = {}
    item_map = {i.id: i for i in items}
    for c in calc_results:
        boq = item_map.get(c.boq_item_id)
        div = boq.division if boq else "未分类"
        div_totals[div] = div_totals.get(div, 0) + (c.total_cost or 0)

    # TOP5 highest cost items
    sorted_calcs = sorted(calc_results, key=lambda c: c.total_cost or 0, reverse=True)
    top5 = []
    for c in sorted_calcs[:5]:
        boq = item_map.get(c.boq_item_id)
        if boq:
            unit_price = round((c.total_cost or 0) / boq.quantity, 2) if boq.quantity else 0
            top5.append({
                "boq_item_id": boq.id, "code": boq.code, "name": boq.name,
                "total": round(c.total_cost or 0, 2), "unit_price": unit_price,
                "pct": round((c.total_cost or 0) / total_cost * 100, 1) if total_cost else 0,
            })

    # Cost structure ratios
    structure = {}
    if total_cost > 0:
        structure = {
            "labor_pct": round(total_labor / total_cost * 100, 1),
            "material_pct": round(total_material / total_cost * 100, 1),
            "machine_pct": round(total_machine / total_cost * 100, 1),
        }

    result = {
        "calculated_items": len(calc_results),
        "total_items": len(items),
        "labor_cost": round(total_labor, 2),
        "material_cost": round(total_material, 2),
        "machine_cost": round(total_machine, 2),
        "direct_cost": round(total_direct, 2),
        "management_fee": round(total_management, 2),
        "profit": round(total_profit, 2),
        "total_cost": round(total_cost, 2),
        "cost_structure": structure,
        "by_division": {k: round(v, 2) for k, v in sorted(div_totals.items(), key=lambda x: -x[1])},
        "top5_items": top5,
    }

    # Per-sqm indicator if project description contains area info
    project = ctx.db.query(Project).filter(Project.id == ctx.project_id).first()
    if project and project.budget and project.budget > 0:
        result["budget_variance"] = round(total_cost - project.budget, 2)
        result["budget_usage_pct"] = round(total_cost / project.budget * 100, 1)

    return json.dumps(result, ensure_ascii=False)


@tool(
    name="batch_scan_bindings",
    description="批量扫描项目所有绑定，检查未绑定项、单位不一致、系数异常、零消耗量等问题。返回结构化问题清单。",
    read_only=True,
)
def batch_scan_bindings(ctx: AgentContext) -> str:
    """Deterministic batch binding scan (extracted from batch_review_agent)."""
    items = (
        ctx.db.query(BoqItem)
        .filter(BoqItem.project_id == ctx.project_id)
        .order_by(BoqItem.sort_order, BoqItem.id)
        .all()
    )
    if not items:
        return json.dumps({"total_items": 0, "issues": []}, ensure_ascii=False)

    boq_ids = [b.id for b in items]
    bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
        .all()
    )

    binding_map: dict[int, list] = {}
    for b in bindings:
        binding_map.setdefault(b.boq_item_id, []).append(b)

    quota_ids = {b.quota_item_id for b in bindings}
    quotas = {q.id: q for q in ctx.db.query(QuotaItem).filter(QuotaItem.id.in_(quota_ids)).all()} if quota_ids else {}

    issues = []
    bound_count = 0

    for boq in items:
        item_bindings = binding_map.get(boq.id, [])
        if not item_bindings:
            issues.append({
                "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                "severity": "warning", "type": "unbound",
                "message": f"清单项 [{boq.code}] {boq.name} 尚未绑定定额",
            })
            continue

        bound_count += 1
        seen_qids: set[int] = set()
        for b in item_bindings:
            q = quotas.get(b.quota_item_id)
            if not q:
                issues.append({
                    "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                    "severity": "error", "type": "missing_quota",
                    "message": f"绑定的定额ID {b.quota_item_id} 不存在",
                })
                continue
            if q.id in seen_qids:
                issues.append({
                    "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                    "severity": "warning", "type": "duplicate",
                    "message": f"定额 [{q.quota_code}] 被重复绑定",
                })
            seen_qids.add(q.id)
            if normalize_unit(boq.unit) != normalize_unit(q.unit):
                issues.append({
                    "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                    "severity": "warning", "type": "unit_mismatch",
                    "message": f"清单单位 '{boq.unit}' 与定额单位 '{q.unit}' 不一致",
                })
            if b.coefficient <= 0:
                issues.append({
                    "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                    "severity": "error", "type": "coeff_abnormal",
                    "message": f"定额 [{q.quota_code}] 系数为 {b.coefficient}",
                })
            elif b.coefficient > 5.0:
                issues.append({
                    "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                    "severity": "warning", "type": "coeff_abnormal",
                    "message": f"定额 [{q.quota_code}] 系数 {b.coefficient} 偏高",
                })
            if q.labor_qty == 0 and q.material_qty == 0 and q.machine_qty == 0:
                issues.append({
                    "boq_item_id": boq.id, "boq_code": boq.code, "boq_name": boq.name,
                    "severity": "warning", "type": "zero_consumption",
                    "message": f"定额 [{q.quota_code}] 人材机消耗量均为0",
                })

    return json.dumps({
        "total_items": len(items),
        "bound_count": bound_count,
        "unbound_count": len(items) - bound_count,
        "issue_count": len(issues),
        "errors": sum(1 for i in issues if i["severity"] == "error"),
        "warnings": sum(1 for i in issues if i["severity"] == "warning"),
        "issues": issues[:50],
    }, ensure_ascii=False)


@tool(
    name="get_divisions_summary",
    description="获取项目的分部工程汇总：各分部的清单数量和绑定覆盖率。",
    read_only=True,
)
def get_divisions_summary(ctx: AgentContext) -> str:
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

    divs: dict[str, dict] = {}
    for i in items:
        d = i.division or "未分类"
        if d not in divs:
            divs[d] = {"count": 0, "bound": 0}
        divs[d]["count"] += 1
        if i.id in bound_ids:
            divs[d]["bound"] += 1

    results = [
        {
            "division": k,
            "item_count": v["count"],
            "bound_count": v["bound"],
            "binding_rate": f"{v['bound']/v['count']*100:.0f}%" if v["count"] else "0%",
        }
        for k, v in sorted(divs.items())
    ]
    return json.dumps({"divisions": results, "total_divisions": len(results)}, ensure_ascii=False)


# ── Register ──

registry.register_many(
    query_boq_items,
    list_unbound_items,
    get_cost_breakdown,
    batch_scan_bindings,
    get_divisions_summary,
)
