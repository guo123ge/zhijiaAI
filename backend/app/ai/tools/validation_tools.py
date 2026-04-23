"""Validation tools — extracted from validation_agent.py.

These tools handle code compliance checking, anomaly detection,
historical comparison, and full project validation.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher

from app.ai.framework.context import AgentContext
from app.ai.framework.tool_def import tool
from app.ai.framework.tool_registry import registry
from app.models.boq_item import BoqItem
from app.models.boq_standard_code import BoqStandardCode
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.quota_item import QuotaItem
from app.models.quota_resource_detail import QuotaResourceDetail
from app.services.validation_service import (
    Severity,
    normalize_unit,
    validate_project,
)


@tool(
    name="check_code_compliance",
    description="检查一个清单编码是否符合GB50500标准，返回标准编码信息、计量规则和项目特征模板。",
    read_only=True,
)
def check_code_compliance(ctx: AgentContext, *, boq_code: str, boq_unit: str = "") -> str:
    code_prefix = boq_code.split("-")[0].strip()
    match = (
        ctx.db.query(BoqStandardCode)
        .filter(BoqStandardCode.standard_code == code_prefix)
        .first()
    )
    if not match and len(code_prefix) >= 9:
        match = (
            ctx.db.query(BoqStandardCode)
            .filter(BoqStandardCode.standard_code == code_prefix[:9])
            .first()
        )

    if not match:
        return json.dumps({
            "compliant": None,
            "message": f"编码 {boq_code} 未在GB50500标准库中找到匹配项",
            "suggestion": "可能是非标编码或地方标准编码",
        }, ensure_ascii=False)

    issues = []
    if boq_unit and normalize_unit(boq_unit) != normalize_unit(match.standard_unit):
        issues.append(f"单位 '{boq_unit}' 与标准单位 '{match.standard_unit}' 不一致")

    return json.dumps({
        "compliant": len(issues) == 0,
        "standard_code": match.standard_code,
        "standard_name": match.name,
        "standard_unit": match.standard_unit,
        "division": match.division,
        "measurement_rule": match.measurement_rule,
        "common_characteristics": match.common_characteristics,
        "issues": issues,
    }, ensure_ascii=False)


@tool(
    name="detect_price_anomaly",
    description="检测一个清单项的定额消耗量是否存在异常（与同类项目对比）。",
    read_only=True,
)
def detect_price_anomaly(ctx: AgentContext, *, boq_item_id: int) -> str:
    boq = ctx.db.query(BoqItem).filter(BoqItem.id == boq_item_id).first()
    if not boq:
        return json.dumps({"error": f"清单项 {boq_item_id} 不存在"}, ensure_ascii=False)

    bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id == boq.id)
        .all()
    )
    if not bindings:
        return json.dumps({
            "boq_code": boq.code,
            "message": "无绑定定额，无法分析消耗量异常",
        }, ensure_ascii=False)

    quota_ids = [b.quota_item_id for b in bindings]
    quotas = {q.id: q for q in ctx.db.query(QuotaItem).filter(QuotaItem.id.in_(quota_ids)).all()}

    total_l = total_m = total_mc = 0.0
    for b in bindings:
        q = quotas.get(b.quota_item_id)
        if q:
            coeff = getattr(b, "coefficient", 1.0) or 1.0
            total_l += q.labor_qty * coeff
            total_m += q.material_qty * coeff
            total_mc += q.machine_qty * coeff

    peers = (
        ctx.db.query(BoqItem)
        .filter(
            BoqItem.project_id == boq.project_id,
            BoqItem.division == boq.division,
            BoqItem.id != boq.id,
        )
        .all()
    )
    peer_data = []
    for p in peers:
        if normalize_unit(p.unit) != normalize_unit(boq.unit):
            continue
        p_bindings = (
            ctx.db.query(LineItemQuotaBinding)
            .filter(LineItemQuotaBinding.boq_item_id == p.id)
            .all()
        )
        if not p_bindings:
            continue
        p_qids = [pb.quota_item_id for pb in p_bindings]
        p_quotas = {q.id: q for q in ctx.db.query(QuotaItem).filter(QuotaItem.id.in_(p_qids)).all()}
        pl = pm = pmc = 0.0
        for pb in p_bindings:
            pq = p_quotas.get(pb.quota_item_id)
            if pq:
                pc = getattr(pb, "coefficient", 1.0) or 1.0
                pl += pq.labor_qty * pc
                pm += pq.material_qty * pc
                pmc += pq.machine_qty * pc
        peer_data.append({"code": p.code, "name": p.name, "labor": pl, "material": pm, "machine": pmc})

    return json.dumps({
        "boq_code": boq.code,
        "boq_name": boq.name,
        "current": {"labor": round(total_l, 4), "material": round(total_m, 4), "machine": round(total_mc, 4)},
        "peer_count": len(peer_data),
        "peers": peer_data[:10],
    }, ensure_ascii=False)


@tool(
    name="find_similar_historical_items",
    description=(
        "在其他项目中查找与指定清单项相似的历史项（名称/编码/单位匹配），用于参考对比。"
        "默认排除当前项目。可选 include_current=True 包含当前项目。"
    ),
    read_only=True,
)
def find_similar_historical_items(
    ctx: AgentContext,
    *,
    name_keyword: str,
    unit: str = "",
    top_n: int = 5,
    include_current: bool = False,
) -> str:
    # DB-level pre-filter: keyword LIKE + exclude current project
    query = ctx.db.query(BoqItem)
    if not include_current and ctx.project_id:
        query = query.filter(BoqItem.project_id != ctx.project_id)
    if len(name_keyword) >= 2:
        query = query.filter(BoqItem.name.ilike(f"%{name_keyword}%"))
        candidates = query.all()
        # Fallback if too few matches
        if len(candidates) < 3:
            fallback_q = ctx.db.query(BoqItem)
            if not include_current and ctx.project_id:
                fallback_q = fallback_q.filter(BoqItem.project_id != ctx.project_id)
            candidates = fallback_q.all()
    else:
        candidates = query.all()

    scored = []
    for item in candidates:
        sim = SequenceMatcher(None, name_keyword, item.name).ratio()
        if unit and normalize_unit(unit) != normalize_unit(item.unit):
            sim *= 0.5
        if sim > 0.2:
            scored.append((sim, item))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Batch-load bindings for top results to avoid N+1
    top_items = [item for _, item in scored[:top_n]]
    top_ids = [item.id for item in top_items]
    binding_map: dict[int, list[str]] = {}
    if top_ids:
        bindings = ctx.db.query(LineItemQuotaBinding).filter(
            LineItemQuotaBinding.boq_item_id.in_(top_ids)
        ).all()
        quota_ids = {b.quota_item_id for b in bindings}
        quotas = {q.id: q for q in ctx.db.query(QuotaItem).filter(QuotaItem.id.in_(quota_ids)).all()} if quota_ids else {}
        for b in bindings:
            q = quotas.get(b.quota_item_id)
            if q:
                binding_map.setdefault(b.boq_item_id, []).append(f"{q.quota_code}({q.name})")

    results = []
    for sim, item in scored[:top_n]:
        results.append({
            "project_id": item.project_id,
            "boq_item_id": item.id,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "quantity": item.quantity,
            "division": item.division,
            "bound_quotas": binding_map.get(item.id, []),
            "similarity": round(sim, 3),
        })
    return json.dumps({
        "results": results,
        "candidates_scanned": len(candidates),
    }, ensure_ascii=False)


@tool(
    name="run_full_validation",
    description="对指定项目执行完整校验，返回按严重度和分部分组的问题清单，附自动修复建议。",
    read_only=True,
)
def run_full_validation(ctx: AgentContext, *, project_id: int) -> str:
    from collections import defaultdict

    issues = validate_project(project_id=project_id, db=ctx.db)

    # Group by division
    boq_cache: dict[int, BoqItem] = {}
    div_issues: dict[str, list] = defaultdict(list)
    for i in issues:
        if i.boq_item_id and i.boq_item_id not in boq_cache:
            boq = ctx.db.query(BoqItem).filter(BoqItem.id == i.boq_item_id).first()
            if boq:
                boq_cache[i.boq_item_id] = boq
        boq = boq_cache.get(i.boq_item_id)
        div = boq.division if boq else "未分类"
        div_issues[div].append(i)

    # Build auto-fix suggestions
    FIX_MAP = {
        "UNIT_MISMATCH": "调用 update_boq_item 修正单位，或 unbind_quota 解绑后重新匹配",
        "MISSING_BINDING": "调用 auto_match_and_bind 自动匹配定额",
        "ZERO_QUANTITY": "调用 update_boq_item 补充工程量",
        "CODE_INVALID": "调用 search_standard_codes 查找正确编码后 update_boq_item 修正",
        "DUPLICATE_CODE": "调用 delete_boq_items 删除重复项",
    }

    issue_list = []
    for i in issues[:40]:
        entry = {
            "code": i.code,
            "severity": i.severity.value,
            "boq_item_id": i.boq_item_id,
            "message": i.message,
            "suggestion": i.suggestion,
        }
        fix = FIX_MAP.get(i.code)
        if fix:
            entry["auto_fix_hint"] = fix
        issue_list.append(entry)

    # Division summary
    div_summary = [
        {"division": d, "count": len(items), "errors": sum(1 for x in items if x.severity == Severity.ERROR)}
        for d, items in sorted(div_issues.items(), key=lambda x: -len(x[1]))
    ]

    summary = {
        "total": len(issues),
        "errors": sum(1 for i in issues if i.severity == Severity.ERROR),
        "warnings": sum(1 for i in issues if i.severity == Severity.WARNING),
        "info": sum(1 for i in issues if i.severity == Severity.INFO),
        "by_division": div_summary,
        "issues": issue_list,
        "fixable_count": sum(1 for i in issues if i.code in FIX_MAP),
    }
    if len(issues) > 40:
        summary["truncated"] = True
        summary["showing"] = 40
    return json.dumps(summary, ensure_ascii=False)


@tool(
    name="get_resource_details",
    description="查看某条定额的人材机资源明细。",
    read_only=True,
)
def get_resource_details(ctx: AgentContext, *, quota_item_id: int) -> str:
    quota = ctx.db.query(QuotaItem).filter(QuotaItem.id == quota_item_id).first()
    if not quota:
        return json.dumps({"error": f"定额 {quota_item_id} 不存在"}, ensure_ascii=False)

    details = (
        ctx.db.query(QuotaResourceDetail)
        .filter(QuotaResourceDetail.quota_item_id == quota_item_id)
        .all()
    )
    return json.dumps({
        "quota_code": quota.quota_code,
        "quota_name": quota.name,
        "has_resource_details": getattr(quota, "has_resource_details", 0),
        "details": [
            {
                "category": d.category,
                "resource_code": d.resource_code,
                "resource_name": d.resource_name,
                "spec": d.spec,
                "unit": d.unit,
                "quantity": d.quantity,
                "unit_price": d.unit_price,
                "is_main_material": d.is_main_material,
            }
            for d in details
        ],
    }, ensure_ascii=False)


# ────────────────────────────────────────────────
# Register all validation tools
# ────────────────────────────────────────────────

registry.register_many(
    check_code_compliance,
    detect_price_anomaly,
    find_similar_historical_items,
    run_full_validation,
    get_resource_details,
)
