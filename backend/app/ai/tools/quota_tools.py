"""Quota & pricing tools — extracted from valuation_agent.py.

These tools handle quota search, binding, cost calculation, and related
operations. Each tool uses the @tool decorator for automatic schema
generation and metadata tagging.
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
from app.services.quota_match_service import _name_similarity, _units_compatible
from app.services.validation_service import normalize_unit


def _resolve_boq(ctx: AgentContext, boq_item_id: int | None = None) -> BoqItem | None:
    """Resolve a BOQ item from either an explicit ID or from ctx.

    In single-item mode, ctx.boq_item_id is pre-set.
    In batch mode, agents pass boq_item_id explicitly.
    """
    target_id = boq_item_id or ctx.boq_item_id
    if target_id is None:
        return None
    return (
        ctx.db.query(BoqItem)
        .filter(BoqItem.id == target_id, BoqItem.project_id == ctx.project_id)
        .first()
    )


# ────────────────────────────────────────────────
# Read-only tools
# ────────────────────────────────────────────────

@tool(
    name="search_quotas",
    description=(
        "搜索定额库，根据关键词、名称或编码查找候选定额。"
        "可选 chapter_filter 按章节/分部缩小范围（如 '土建-混凝土'），"
        "unit_filter 按单位过滤。返回最多 top_n 条（默认10）。"
    ),
    read_only=True,
)
def search_quotas(
    ctx: AgentContext,
    *,
    keyword: str,
    unit_filter: str = "",
    chapter_filter: str = "",
    top_n: int = 10,
) -> str:
    """Search quota database by keyword similarity with optional pre-filters."""
    query = ctx.db.query(QuotaItem)

    # Pre-filter at DB level to avoid full-table scan
    if chapter_filter:
        query = query.filter(QuotaItem.chapter.ilike(f"%{chapter_filter}%"))

    kw_lower = keyword.lower()
    # If keyword is long enough, use DB LIKE pre-filter to reduce in-memory work
    if len(kw_lower) >= 2:
        query = query.filter(
            (QuotaItem.name.ilike(f"%{keyword}%")) | (QuotaItem.quota_code.ilike(f"%{keyword}%"))
        )
        candidates = query.all()
        # If LIKE returns too few, fall back to full similarity search
        if len(candidates) < 3:
            candidates = ctx.db.query(QuotaItem).all()
            if chapter_filter:
                candidates = [q for q in candidates if chapter_filter.lower() in (q.chapter or "").lower()]
    else:
        candidates = query.all()

    if not candidates:
        return json.dumps({"results": [], "message": "未找到匹配定额"}, ensure_ascii=False)

    scored: list[tuple[float, QuotaItem]] = []
    for q in candidates:
        name_sim = _name_similarity(keyword, q.name)
        code_sim = SequenceMatcher(None, kw_lower, q.quota_code.lower()).ratio()
        score = name_sim * 0.7 + code_sim * 0.3
        if unit_filter and not _units_compatible(unit_filter, q.unit):
            score *= 0.3
        if score > 0.05:
            scored.append((score, q))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, q in scored[:top_n]:
        results.append({
            "quota_item_id": q.id,
            "quota_code": q.quota_code,
            "name": q.name,
            "unit": q.unit,
            "chapter": q.chapter,
            "base_price": q.base_price,
            "labor_qty": q.labor_qty,
            "material_qty": q.material_qty,
            "machine_qty": q.machine_qty,
            "relevance": round(score, 3),
        })
    return json.dumps({
        "results": results,
        "candidates_scanned": len(candidates),
    }, ensure_ascii=False)


@tool(
    name="get_quota_detail",
    description="查看一条定额的详细信息，包括人工/材料/机械消耗量。",
    read_only=True,
)
def get_quota_detail(ctx: AgentContext, *, quota_item_id: int) -> str:
    q = ctx.db.query(QuotaItem).filter(QuotaItem.id == quota_item_id).first()
    if not q:
        return json.dumps({"error": f"定额ID {quota_item_id} 不存在"}, ensure_ascii=False)
    return json.dumps({
        "quota_item_id": q.id,
        "quota_code": q.quota_code,
        "name": q.name,
        "unit": q.unit,
        "labor_qty": q.labor_qty,
        "material_qty": q.material_qty,
        "machine_qty": q.machine_qty,
    }, ensure_ascii=False)


@tool(
    name="list_current_bindings",
    description="查看指定清单项已绑定的所有定额。批量模式下请传 boq_item_id。",
    read_only=True,
)
def list_current_bindings(ctx: AgentContext, *, boq_item_id: int | None = None) -> str:
    boq = _resolve_boq(ctx, boq_item_id)
    if not boq:
        return json.dumps({"error": "未指定清单项，请传入 boq_item_id"}, ensure_ascii=False)

    bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id == boq.id)
        .all()
    )
    if not bindings:
        return json.dumps({"bindings": [], "message": "当前无绑定定额"}, ensure_ascii=False)

    results = []
    for b in bindings:
        q = ctx.db.query(QuotaItem).filter(QuotaItem.id == b.quota_item_id).first()
        results.append({
            "binding_id": b.id,
            "quota_item_id": b.quota_item_id,
            "quota_code": q.quota_code if q else "?",
            "quota_name": q.name if q else "未知",
            "unit": q.unit if q else "",
            "coefficient": b.coefficient,
            "labor_qty": round(q.labor_qty * b.coefficient, 4) if q else 0,
            "material_qty": round(q.material_qty * b.coefficient, 4) if q else 0,
            "machine_qty": round(q.machine_qty * b.coefficient, 4) if q else 0,
        })
    return json.dumps({"bindings": results, "count": len(results)}, ensure_ascii=False)


@tool(
    name="calculate_cost",
    description="基于绑定的所有定额，计算清单项的综合单价和合价。批量模式下请传 boq_item_id。",
    read_only=True,
)
def calculate_cost(ctx: AgentContext, *, boq_item_id: int | None = None) -> str:
    from app.services.project_calc_service import (
        _compose_quota_quantities,
        _lookup_price,
        _resolve_fee_config,
    )
    from app.services.pricing_engine import calculate_line_item

    boq = _resolve_boq(ctx, boq_item_id)
    if not boq:
        return json.dumps({"error": "未指定清单项，请传入 boq_item_id"}, ensure_ascii=False)

    bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id == boq.id)
        .all()
    )
    if not bindings:
        return json.dumps({"error": "当前无绑定定额，无法计算"}, ensure_ascii=False)

    quota_by_id = {
        q.id: q
        for q in ctx.db.query(QuotaItem)
        .filter(QuotaItem.id.in_([b.quota_item_id for b in bindings]))
        .all()
    }

    project_region = ctx.resolve_region()
    labor_qty, material_qty, machine_qty = _compose_quota_quantities(bindings, quota_by_id)
    labor_price = _lookup_price(ctx.db, category="人工费", region=project_region)
    material_price = _lookup_price(ctx.db, category="材料费", region=project_region)
    machine_price = _lookup_price(ctx.db, category="机械费", region=project_region)

    fee_config = _resolve_fee_config(boq.project_id, ctx.db)
    result = calculate_line_item(
        labor_qty=labor_qty,
        labor_price=labor_price,
        material_qty=material_qty,
        material_price=material_price,
        machine_qty=machine_qty,
        machine_price=machine_price,
        quantity=boq.quantity,
        fee_config=fee_config,
    )

    return json.dumps({
        "boq_quantity": boq.quantity,
        "composed_labor_qty": round(labor_qty, 4),
        "composed_material_qty": round(material_qty, 4),
        "composed_machine_qty": round(machine_qty, 4),
        "labor_price": labor_price,
        "material_price": material_price,
        "machine_price": machine_price,
        "labor_cost": result.labor_cost,
        "material_cost": result.material_cost,
        "machine_cost": result.machine_cost,
        "direct_cost": result.direct_cost,
        "management_fee": result.management_fee,
        "profit": result.profit,
        "regulatory_fee": result.regulatory_fee,
        "pre_tax_total": result.pre_tax_total,
        "tax": result.tax,
        "total": result.total,
        "unit_price": round(result.total / boq.quantity, 2) if boq.quantity else 0,
    }, ensure_ascii=False)


@tool(
    name="get_material_prices",
    description="查询当前项目区域的材料信息价（人工费、材料费、机械费单价）。",
    read_only=True,
)
def get_material_prices(ctx: AgentContext) -> str:
    from app.services.project_calc_service import _lookup_price

    project_region = ctx.resolve_region()
    labor = _lookup_price(ctx.db, category="人工费", region=project_region)
    material = _lookup_price(ctx.db, category="材料费", region=project_region)
    machine = _lookup_price(ctx.db, category="机械费", region=project_region)
    return json.dumps({
        "region": project_region,
        "labor_price": labor,
        "material_price": material,
        "machine_price": machine,
    }, ensure_ascii=False)


def _search_standard_codes_impl(
    ctx: AgentContext,
    *,
    keyword: str,
    division_filter: str = "",
    top_n: int = 8,
) -> str:
    """Core implementation — called by the tool and by batch_search_standard_codes."""
    query = ctx.db.query(BoqStandardCode)
    if division_filter:
        query = query.filter(BoqStandardCode.division.ilike(f"%{division_filter}%"))

    kw = keyword.strip()
    # DB-level pre-filter for performance
    if len(kw) >= 2:
        query = query.filter(
            (BoqStandardCode.name.ilike(f"%{kw}%")) | (BoqStandardCode.standard_code.ilike(f"%{kw}%"))
        )
        candidates = query.all()
        # Fallback to full scan if too few results
        if len(candidates) < 3:
            fallback_q = ctx.db.query(BoqStandardCode)
            if division_filter:
                fallback_q = fallback_q.filter(BoqStandardCode.division.ilike(f"%{division_filter}%"))
            candidates = fallback_q.all()
    else:
        candidates = query.all()

    if not candidates:
        return json.dumps({"results": [], "message": "未找到匹配的标准编码"}, ensure_ascii=False)

    scored = []
    for sc in candidates:
        name_sim = SequenceMatcher(None, kw, sc.name).ratio()
        code_sim = SequenceMatcher(None, kw, sc.standard_code).ratio()
        score = max(name_sim, code_sim)
        if kw in sc.name or kw in sc.standard_code:
            score = max(score, 0.8)
        if score > 0.15:
            scored.append((score, sc))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, sc in scored[:top_n]:
        results.append({
            "standard_code": sc.standard_code,
            "name": sc.name,
            "standard_unit": sc.standard_unit,
            "division": sc.division,
            "measurement_rule": sc.measurement_rule[:100] if sc.measurement_rule else "",
            "common_characteristics": sc.common_characteristics,
            "relevance": round(score, 3),
        })
    return json.dumps({
        "results": results,
        "candidates_scanned": len(candidates),
    }, ensure_ascii=False)


@tool(
    name="search_standard_codes",
    description=(
        "搜索GB50500标准清单编码库，获取标准名称、单位、计量规则和项目特征模板。"
        "可选 division_filter 缩小到指定分部（如 '混凝土及钢筋混凝土工程'），"
        "top_n 控制返回条数（默认8）。"
        "💡 若要一次查多个关键词，请用 batch_search_standard_codes 节省 LLM 轮次。"
    ),
    read_only=True,
)
def search_standard_codes(
    ctx: AgentContext,
    *,
    keyword: str,
    division_filter: str = "",
    top_n: int = 8,
) -> str:
    """Search GB50500 standard codes by keyword with optional division pre-filter."""
    return _search_standard_codes_impl(
        ctx, keyword=keyword, division_filter=division_filter, top_n=top_n,
    )


@tool(
    name="batch_search_standard_codes",
    description=(
        "批量并行搜索GB50500标准编码库——一次 tool call 返回多个关键词的搜索结果，"
        "用法与 search_standard_codes 相同但 keywords 是 JSON 数组字符串。"
        "⚡ 强烈推荐：需要查多个分部（土方/混凝土/钢筋…）时用此工具，"
        "比顺序调用 search_standard_codes 省 N-1 个 LLM 轮次。"
        "示例：keywords='[\"基坑开挖\", \"基础混凝土\", \"基础钢筋\"]'。"
        "可选 division_filter（对全部关键词生效），top_n_per_keyword 控制每个关键词返回条数（默认6）。"
    ),
    read_only=True,
)
def batch_search_standard_codes(
    ctx: AgentContext,
    *,
    keywords: str,
    division_filter: str = "",
    top_n_per_keyword: int = 6,
) -> str:
    """Run multiple search_standard_codes in one call and return merged results.

    OPT-1: Collapse N sequential LLM turns into 1. The server still does N DB
    queries but they're cheap (<5ms each for typical code tables) and the LLM
    only pays for one tool_call_id round-trip.
    """
    try:
        kw_list = json.loads(keywords)
        if not isinstance(kw_list, list) or not all(isinstance(k, str) for k in kw_list):
            raise ValueError("keywords must be a JSON array of strings")
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({
            "error": f"keywords 参数格式错误: {exc}",
            "expected": '["关键词1", "关键词2", ...]',
        }, ensure_ascii=False)

    if not kw_list:
        return json.dumps({"batches": [], "message": "keywords 为空"}, ensure_ascii=False)
    if len(kw_list) > 20:
        kw_list = kw_list[:20]  # hard cap; avoid runaway

    batches: list[dict] = []
    total_hits = 0
    for kw in kw_list:
        raw = _search_standard_codes_impl(
            ctx,
            keyword=kw,
            division_filter=division_filter,
            top_n=top_n_per_keyword,
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"results": [], "error": "parse_failed"}
        hits = len(payload.get("results", []))
        total_hits += hits
        batches.append({
            "keyword": kw,
            "hits": hits,
            "results": payload.get("results", []),
        })
    return json.dumps({
        "batches": batches,
        "keywords_count": len(kw_list),
        "total_hits": total_hits,
    }, ensure_ascii=False)


@tool(
    name="validate_binding",
    description="校验指定清单项的绑定状态，检查单位一致性、消耗量合理性等。批量模式下请传 boq_item_id。",
    read_only=True,
)
def validate_binding(ctx: AgentContext, *, boq_item_id: int | None = None) -> str:
    """Validate current bindings for issues."""
    boq = _resolve_boq(ctx, boq_item_id)
    if not boq:
        return json.dumps({"error": "未指定清单项，请传入 boq_item_id"}, ensure_ascii=False)

    bindings = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(LineItemQuotaBinding.boq_item_id == boq.id)
        .all()
    )
    if not bindings:
        return json.dumps({"valid": False, "issues": ["无绑定定额"]}, ensure_ascii=False)

    issues = []
    for b in bindings:
        q = ctx.db.query(QuotaItem).filter(QuotaItem.id == b.quota_item_id).first()
        if not q:
            issues.append(f"绑定ID {b.id} 的定额不存在")
            continue
        if normalize_unit(boq.unit) != normalize_unit(q.unit):
            issues.append(
                f"定额 [{q.quota_code}] 单位 '{q.unit}' 与清单单位 '{boq.unit}' 不一致，请确认是否需要换算系数"
            )
        if q.labor_qty == 0 and q.material_qty == 0 and q.machine_qty == 0:
            issues.append(f"定额 [{q.quota_code}] 人材机含量均为0")

    code_prefix = boq.code.split("-")[0].strip()
    std = ctx.db.query(BoqStandardCode).filter(BoqStandardCode.standard_code == code_prefix).first()
    if not std and len(code_prefix) >= 9:
        std = ctx.db.query(BoqStandardCode).filter(BoqStandardCode.standard_code == code_prefix[:9]).first()
    if std and normalize_unit(boq.unit) != normalize_unit(std.standard_unit):
        issues.append(f"清单单位 '{boq.unit}' 与GB50500标准单位 '{std.standard_unit}' 不一致")

    return json.dumps({
        "valid": len(issues) == 0,
        "binding_count": len(bindings),
        "issues": issues,
        "standard_code_match": std.name if std else None,
    }, ensure_ascii=False)


# ────────────────────────────────────────────────
# Write tools (destructive / requires confirmation)
# ────────────────────────────────────────────────

@tool(
    name="bind_quota",
    description="将一条定额绑定到指定清单项，支持设置系数。批量模式下必须传 boq_item_id 指定哪个清单项。",
    destructive=True,
    requires_confirmation=True,
)
def bind_quota(ctx: AgentContext, *, boq_item_id: int | None = None, quota_item_id: int, coefficient: float = 1.0) -> str:
    boq = _resolve_boq(ctx, boq_item_id)
    if not boq:
        return json.dumps({"error": "未指定清单项，请传入 boq_item_id"}, ensure_ascii=False)

    q = ctx.db.query(QuotaItem).filter(QuotaItem.id == quota_item_id).first()
    if not q:
        return json.dumps({"error": f"定额ID {quota_item_id} 不存在"}, ensure_ascii=False)

    existing = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(
            LineItemQuotaBinding.boq_item_id == boq.id,
            LineItemQuotaBinding.quota_item_id == quota_item_id,
        )
        .first()
    )
    if existing:
        existing.coefficient = coefficient
        ctx.db.commit()
        return json.dumps({
            "action": "updated",
            "binding_id": existing.id,
            "quota_code": q.quota_code,
            "quota_name": q.name,
            "coefficient": coefficient,
            "message": f"已更新绑定系数为 {coefficient}",
        }, ensure_ascii=False)

    binding = LineItemQuotaBinding(
        boq_item_id=boq.id,
        quota_item_id=quota_item_id,
        coefficient=coefficient,
    )
    ctx.db.add(binding)
    boq.is_dirty = 1
    ctx.db.commit()
    ctx.db.refresh(binding)
    return json.dumps({
        "action": "created",
        "binding_id": binding.id,
        "quota_code": q.quota_code,
        "quota_name": q.name,
        "coefficient": coefficient,
        "message": f"已绑定定额 [{q.quota_code}] {q.name}，系数={coefficient}",
    }, ensure_ascii=False)


@tool(
    name="unbind_quota",
    description="解除一条定额与指定清单项的绑定。批量模式下请传 boq_item_id。",
    destructive=True,
    requires_confirmation=True,
)
def unbind_quota(ctx: AgentContext, *, boq_item_id: int | None = None, binding_id: int) -> str:
    boq = _resolve_boq(ctx, boq_item_id)
    if not boq:
        return json.dumps({"error": "未指定清单项，请传入 boq_item_id"}, ensure_ascii=False)

    binding = (
        ctx.db.query(LineItemQuotaBinding)
        .filter(
            LineItemQuotaBinding.id == binding_id,
            LineItemQuotaBinding.boq_item_id == boq.id,
        )
        .first()
    )
    if not binding:
        return json.dumps({"error": f"绑定ID {binding_id} 不存在或不属于当前清单"}, ensure_ascii=False)

    ctx.db.delete(binding)
    boq.is_dirty = 1
    ctx.db.commit()
    return json.dumps({"action": "deleted", "binding_id": binding_id, "message": "已解除绑定"}, ensure_ascii=False)


@tool(
    name="batch_bind_quotas",
    description=(
        "批量绑定多组（清单项→定额）。"
        "参数 bindings 是一个 JSON 数组，每个元素含 boq_item_id、quota_item_id、coefficient（默认1.0）。"
        "一次调用最多处理50组。"
    ),
    destructive=True,
    requires_confirmation=True,
)
def batch_bind_quotas(
    ctx: AgentContext,
    *,
    bindings: list[dict],
) -> str:
    """Bind multiple BOQ items to quotas in one call."""
    MAX_BATCH = 50
    if len(bindings) > MAX_BATCH:
        return json.dumps({"error": f"单次最多绑定 {MAX_BATCH} 组，收到 {len(bindings)} 组"}, ensure_ascii=False)

    results = []
    errors = []
    for idx, b in enumerate(bindings):
        bid = b.get("boq_item_id")
        qid = b.get("quota_item_id")
        coeff = b.get("coefficient", 1.0)
        if not bid or not qid:
            errors.append({"index": idx, "error": "缺少 boq_item_id 或 quota_item_id"})
            continue

        boq = ctx.db.query(BoqItem).filter(
            BoqItem.id == bid, BoqItem.project_id == ctx.project_id
        ).first()
        if not boq:
            errors.append({"index": idx, "boq_item_id": bid, "error": "清单项不存在"})
            continue

        quota = ctx.db.query(QuotaItem).filter(QuotaItem.id == qid).first()
        if not quota:
            errors.append({"index": idx, "quota_item_id": qid, "error": "定额不存在"})
            continue

        existing = ctx.db.query(LineItemQuotaBinding).filter(
            LineItemQuotaBinding.boq_item_id == bid,
            LineItemQuotaBinding.quota_item_id == qid,
        ).first()
        if existing:
            existing.coefficient = coeff
            results.append({"boq_item_id": bid, "action": "updated", "quota_code": quota.quota_code})
        else:
            ctx.db.add(LineItemQuotaBinding(boq_item_id=bid, quota_item_id=qid, coefficient=coeff))
            boq.is_dirty = 1
            results.append({"boq_item_id": bid, "action": "created", "quota_code": quota.quota_code})

    ctx.db.commit()
    return json.dumps({
        "bound": len(results),
        "errors": len(errors),
        "results": results[:20],
        "error_details": errors[:10],
    }, ensure_ascii=False)


@tool(
    name="auto_match_and_bind",
    description=(
        "为指定清单项自动搜索最佳定额并绑定。"
        "按名称相似度 + 单位兼容性选择 top1 定额，自动绑定。"
        "适合批量处理未绑定项。"
    ),
    destructive=True,
    requires_confirmation=True,
)
def auto_match_and_bind(
    ctx: AgentContext,
    *,
    boq_item_id: int,
    min_similarity: float = 0.3,
) -> str:
    """Auto-find the best quota for a BOQ item and bind it."""
    boq = _resolve_boq(ctx, boq_item_id)
    if not boq:
        return json.dumps({"error": "清单项不存在"}, ensure_ascii=False)

    # Search candidates
    quotas = ctx.db.query(QuotaItem).all()
    if not quotas:
        return json.dumps({"error": "定额库为空"}, ensure_ascii=False)

    best_score = 0.0
    best_quota = None
    for q in quotas:
        name_sim = _name_similarity(boq.name, q.name)
        unit_compat = 1.0 if _units_compatible(boq.unit, q.unit) else 0.3
        score = name_sim * unit_compat
        if score > best_score:
            best_score = score
            best_quota = q

    if not best_quota or best_score < min_similarity:
        return json.dumps({
            "matched": False,
            "best_score": round(best_score, 3),
            "message": f"未找到相似度 ≥ {min_similarity} 的定额",
        }, ensure_ascii=False)

    # Bind
    existing = ctx.db.query(LineItemQuotaBinding).filter(
        LineItemQuotaBinding.boq_item_id == boq.id,
        LineItemQuotaBinding.quota_item_id == best_quota.id,
    ).first()
    if existing:
        return json.dumps({
            "matched": True, "already_bound": True,
            "quota_code": best_quota.quota_code,
            "quota_name": best_quota.name,
            "similarity": round(best_score, 3),
        }, ensure_ascii=False)

    binding = LineItemQuotaBinding(
        boq_item_id=boq.id,
        quota_item_id=best_quota.id,
        coefficient=1.0,
    )
    ctx.db.add(binding)
    boq.is_dirty = 1
    ctx.db.commit()
    ctx.db.refresh(binding)
    return json.dumps({
        "matched": True,
        "binding_id": binding.id,
        "quota_code": best_quota.quota_code,
        "quota_name": best_quota.name,
        "quota_unit": best_quota.unit,
        "similarity": round(best_score, 3),
        "message": f"已自动绑定定额 [{best_quota.quota_code}] {best_quota.name}（相似度 {best_score:.0%}）",
    }, ensure_ascii=False)


@tool(
    name="batch_auto_match_all",
    description=(
        "一键自动匹配并绑定项目所有未绑定清单项。"
        "逐项搜索最佳定额并绑定，返回成功/失败/跳过统计。"
        "适合全流程中快速完成阶段2。"
    ),
    destructive=True,
    requires_confirmation=True,
)
def batch_auto_match_all(
    ctx: AgentContext,
    *,
    min_similarity: float = 0.3,
    limit: int = 200,
) -> str:
    """Auto-match and bind ALL unbound items in one call."""
    all_items = ctx.db.query(BoqItem).filter(
        BoqItem.project_id == ctx.project_id,
    ).order_by(BoqItem.sort_order, BoqItem.id).all()
    boq_ids = [i.id for i in all_items]

    if not boq_ids:
        return json.dumps({"message": "项目无清单项"}, ensure_ascii=False)

    bound_ids = {
        r.boq_item_id
        for r in ctx.db.query(LineItemQuotaBinding.boq_item_id)
        .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
        .distinct()
        .all()
    }
    unbound = [i for i in all_items if i.id not in bound_ids]
    if not unbound:
        return json.dumps({
            "message": "所有清单项已绑定", "total": len(all_items), "bound": len(bound_ids),
        }, ensure_ascii=False)

    unbound = unbound[:limit]

    # Load all quotas once
    quotas = ctx.db.query(QuotaItem).all()
    if not quotas:
        return json.dumps({"error": "定额库为空"}, ensure_ascii=False)

    matched = 0
    skipped = 0
    details = []
    for boq in unbound:
        best_score = 0.0
        best_quota = None
        for q in quotas:
            name_sim = _name_similarity(boq.name, q.name)
            unit_compat = 1.0 if _units_compatible(boq.unit, q.unit) else 0.3
            score = name_sim * unit_compat
            if score > best_score:
                best_score = score
                best_quota = q

        if not best_quota or best_score < min_similarity:
            skipped += 1
            details.append({"boq_id": boq.id, "name": boq.name, "status": "skipped", "score": round(best_score, 3)})
            continue

        binding = LineItemQuotaBinding(
            boq_item_id=boq.id, quota_item_id=best_quota.id, coefficient=1.0,
        )
        ctx.db.add(binding)
        boq.is_dirty = 1
        matched += 1
        details.append({
            "boq_id": boq.id, "name": boq.name, "status": "bound",
            "quota_code": best_quota.quota_code, "quota_name": best_quota.name,
            "score": round(best_score, 3),
        })

    ctx.db.commit()
    return json.dumps({
        "action": "batch_auto_matched",
        "total_unbound": len(unbound),
        "matched": matched,
        "skipped": skipped,
        "already_bound": len(bound_ids),
        "details": details[:30],  # Truncate for token budget
        "message": f"自动匹配完成：{matched} 成功，{skipped} 跳过",
    }, ensure_ascii=False)


# ────────────────────────────────────────────────
# Register all tools into the global registry
# ────────────────────────────────────────────────

registry.register_many(
    search_quotas,
    get_quota_detail,
    list_current_bindings,
    calculate_cost,
    get_material_prices,
    search_standard_codes,
    batch_search_standard_codes,
    validate_binding,
    bind_quota,
    unbind_quota,
    batch_bind_quotas,
    auto_match_and_bind,
    batch_auto_match_all,
)
