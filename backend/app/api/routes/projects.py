import json
import math
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.boq_item import BoqItem
from app.models.comment import Comment
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.project import Project
from app.schemas.project import (
    DashboardSummaryOut,
    HealthScoreDimension,
    HealthScoreOut,
    ProjectCreate,
    ProjectListOut,
    ProjectOut,
    ProjectStatusUpdate,
    ProjectUpdate,
)
from app.services.validation_service import Severity, validate_project

router = APIRouter(prefix="/projects", tags=["projects"])

# ── Valid status transitions ──
STATUS_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["ongoing"],
    "ongoing": ["completed", "draft"],
    "completed": ["archived", "ongoing"],
    "archived": ["draft"],
}
VALID_STATUSES = set(STATUS_TRANSITIONS.keys())
VALID_PROJECT_TYPES = {"住宅", "商业", "工业", "公共建筑", "市政"}
SORT_FIELDS = {"name", "created_at", "updated_at", "budget", "status", "project_type", "region"}


def _project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id, name=p.name, description=p.description, region=p.region,
        project_type=p.project_type, status=p.status, budget=p.budget,
        start_date=p.start_date, end_date=p.end_date, owner=p.owner,
        standard_type=p.standard_type, language=p.language, currency=p.currency,
        created_at=p.created_at, updated_at=p.updated_at,
    )


def _log_audit(db: Session, project_id: int, action: str, before: dict | None = None, after: dict | None = None) -> None:
    if action == "project.created" and os.getenv("PROJECT_CREATE_AUDIT_LOG", "false").lower() not in {"1", "true", "yes", "on"}:
        return
    db.add(AuditLog(
        project_id=project_id,
        actor="system",
        action=action,
        resource_type="project",
        resource_id=project_id,
        before_json=json.dumps(before, ensure_ascii=False, default=str) if before else None,
        after_json=json.dumps(after, ensure_ascii=False, default=str) if after else None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))


def _get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Create ──
@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectOut:
    project = Project(
        name=payload.name,
        description=payload.description,
        region=payload.region,
        project_type=payload.project_type,
        budget=payload.budget,
        start_date=payload.start_date,
        end_date=payload.end_date,
        owner=payload.owner,
        standard_type=payload.standard_type,
        language=payload.language,
        currency=payload.currency,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    _log_audit(db, project.id, "project.created", after={"name": project.name})
    db.commit()
    return _project_out(project)


# ── List (paginated + filtered + sorted) ──
@router.get("", response_model=ProjectListOut)
def list_projects(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Search keyword"),
    status: Optional[str] = Query(None, description="Filter by status"),
    project_type: Optional[str] = Query(None, description="Filter by project type"),
    region: Optional[str] = Query(None, description="Filter by region"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="asc or desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ProjectListOut:
    query = db.query(Project)

    # Filters
    if status and status in VALID_STATUSES:
        query = query.filter(Project.status == status)
    if project_type and project_type in VALID_PROJECT_TYPES:
        query = query.filter(Project.project_type == project_type)
    if region:
        query = query.filter(Project.region.ilike(f"%{region}%"))
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(
            Project.name.ilike(pattern),
            Project.description.ilike(pattern),
            Project.region.ilike(pattern),
            Project.owner.ilike(pattern),
        ))

    # Count before pagination
    total = query.count()

    # Sort
    sort_col = getattr(Project, sort_by, None) if sort_by in SORT_FIELDS else Project.created_at
    if sort_col is None:
        sort_col = Project.created_at
    query = query.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc())

    # Paginate
    total_pages = max(1, math.ceil(total / page_size))
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return ProjectListOut(
        items=[_project_out(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ── Get single ──
@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectOut:
    return _project_out(_get_project_or_404(project_id, db))


# ── Update ──
@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)) -> ProjectOut:
    project = _get_project_or_404(project_id, db)
    before = {"name": project.name, "region": project.region}
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    _log_audit(db, project.id, "project.updated", before=before, after=update_data)
    db.commit()
    return _project_out(project)


# ── Delete ──
@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)) -> dict:
    project = _get_project_or_404(project_id, db)
    _log_audit(db, project.id, "project.deleted", before={"name": project.name})
    db.delete(project)
    db.commit()
    return {"ok": True, "deleted_id": project_id}


# ── Status change ──
@router.patch("/{project_id}/status", response_model=ProjectOut)
def change_project_status(
    project_id: int, payload: ProjectStatusUpdate, db: Session = Depends(get_db),
) -> ProjectOut:
    project = _get_project_or_404(project_id, db)
    new_status = payload.status
    if new_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")
    allowed = STATUS_TRANSITIONS.get(project.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{project.status}' to '{new_status}'. Allowed: {allowed}",
        )
    before_status = project.status
    project.status = new_status
    db.commit()
    db.refresh(project)
    _log_audit(db, project.id, "project.status_changed", before={"status": before_status}, after={"status": new_status})
    db.commit()
    return _project_out(project)


# ── Archive (shortcut) ──
@router.post("/{project_id}:archive", response_model=ProjectOut)
def archive_project(project_id: int, db: Session = Depends(get_db)) -> ProjectOut:
    project = _get_project_or_404(project_id, db)
    if project.status == "archived":
        raise HTTPException(status_code=400, detail="Project is already archived")
    before_status = project.status
    project.status = "archived"
    db.commit()
    db.refresh(project)
    _log_audit(db, project.id, "project.archived", before={"status": before_status}, after={"status": "archived"})
    db.commit()
    return _project_out(project)


# ── Duplicate ──
@router.post("/{project_id}:duplicate", response_model=ProjectOut)
def duplicate_project(
    project_id: int,
    deep: bool = Query(True, description="深拷贝：复制清单项和绑定关系"),
    db: Session = Depends(get_db),
) -> ProjectOut:
    source = _get_project_or_404(project_id, db)
    new_project = Project(
        name=f"{source.name} (副本)",
        description=source.description,
        region=source.region,
        project_type=source.project_type,
        status="draft",
        budget=source.budget,
        start_date=source.start_date,
        end_date=source.end_date,
        owner=source.owner,
        rule_package_id=source.rule_package_id,
        standard_type=source.standard_type,
        language=source.language,
        currency=source.currency,
    )
    db.add(new_project)
    db.flush()  # Get new_project.id before copying children

    boq_copied = 0
    binding_copied = 0
    if deep:
        # Deep copy: BOQ items + their bindings
        source_items = db.query(BoqItem).filter(BoqItem.project_id == project_id).order_by(BoqItem.sort_order).all()
        old_to_new: dict[int, int] = {}
        for item in source_items:
            new_item = BoqItem(
                project_id=new_project.id,
                code=item.code,
                name=item.name,
                unit=item.unit,
                quantity=item.quantity,
                characteristics=item.characteristics,
                division=item.division,
                sort_order=item.sort_order,
                remark=item.remark,
            )
            db.add(new_item)
            db.flush()
            old_to_new[item.id] = new_item.id
            boq_copied += 1

        if old_to_new:
            source_bindings = (
                db.query(LineItemQuotaBinding)
                .filter(LineItemQuotaBinding.boq_item_id.in_(old_to_new.keys()))
                .all()
            )
            for b in source_bindings:
                new_bid = old_to_new.get(b.boq_item_id)
                if new_bid:
                    db.add(LineItemQuotaBinding(
                        boq_item_id=new_bid,
                        quota_item_id=b.quota_item_id,
                        coefficient=b.coefficient,
                    ))
                    binding_copied += 1

    db.commit()
    db.refresh(new_project)
    _log_audit(db, new_project.id, "project.duplicated", after={
        "source_id": project_id, "name": new_project.name,
        "boq_copied": boq_copied, "binding_copied": binding_copied,
    })
    db.commit()
    return _project_out(new_project)


# ── Batch delete ──
@router.post(":batch-delete")
def batch_delete_projects(ids: list[int], db: Session = Depends(get_db)) -> dict:
    deleted = db.query(Project).filter(Project.id.in_(ids)).delete(synchronize_session="fetch")
    db.commit()
    return {"ok": True, "deleted": deleted}


# ── Batch archive ──
@router.post(":batch-archive")
def batch_archive_projects(ids: list[int], db: Session = Depends(get_db)) -> dict:
    updated = (
        db.query(Project)
        .filter(Project.id.in_(ids), Project.status != "archived")
        .update({Project.status: "archived"}, synchronize_session="fetch")
    )
    db.commit()
    return {"ok": True, "archived": updated}


@router.get("/{project_id}/dashboard-summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(project_id: int, db: Session = Depends(get_db)) -> DashboardSummaryOut:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    boq_rows = db.query(BoqItem.id, BoqItem.is_dirty).filter(BoqItem.project_id == project_id).all()
    boq_ids = [r.id for r in boq_rows]
    boq_count = len(boq_rows)
    dirty_count = sum(1 for r in boq_rows if r.is_dirty)

    bound_count = 0
    if boq_ids:
        bound_count = (
            db.query(func.count(func.distinct(LineItemQuotaBinding.boq_item_id)))
            .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
            .scalar()
            or 0
        )
    unbound_count = max(boq_count - bound_count, 0)

    issues = validate_project(project_id=project_id, db=db)
    validation_total = len(issues)
    validation_errors = sum(1 for i in issues if i.severity == Severity.ERROR)
    validation_warnings = sum(1 for i in issues if i.severity == Severity.WARNING)

    recent_audit_count = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.project_id == project_id)
        .scalar()
        or 0
    )
    recent_comment_count = (
        db.query(func.count(Comment.id))
        .filter(Comment.project_id == project_id)
        .scalar()
        or 0
    )

    # Calc total + division breakdown
    from collections import defaultdict
    from app.models.calc_result import CalcResult
    calc_total = 0.0
    div_costs: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost": 0.0})
    if boq_ids:
        boq_items = db.query(BoqItem).filter(BoqItem.project_id == project_id).all()
        calc_results = db.query(CalcResult).filter(CalcResult.boq_item_id.in_(boq_ids)).all()
        calc_map = {c.boq_item_id: c for c in calc_results}
        calc_total = sum(c.total_cost or 0 for c in calc_results)
        for item in boq_items:
            d = item.division or "未分类"
            div_costs[d]["count"] += 1
            c = calc_map.get(item.id)
            if c:
                div_costs[d]["cost"] += c.total_cost or 0

    from app.schemas.project import DivisionStat
    top_divisions = [
        DivisionStat(division=k, count=v["count"], cost=round(v["cost"], 2))
        for k, v in sorted(div_costs.items(), key=lambda x: -x[1]["cost"])
    ][:5]

    binding_rate = f"{bound_count / boq_count * 100:.1f}%" if boq_count else "0%"

    return DashboardSummaryOut(
        project_id=project_id,
        boq_count=boq_count,
        unbound_count=unbound_count,
        dirty_count=dirty_count,
        validation_total=validation_total,
        validation_errors=validation_errors,
        validation_warnings=validation_warnings,
        recent_audit_count=recent_audit_count,
        recent_comment_count=recent_comment_count,
        calc_total=round(calc_total, 2),
        binding_rate=binding_rate,
        budget=project.budget,
        top_divisions=top_divisions,
    )


@router.get("/{project_id}/health-score", response_model=HealthScoreOut)
def get_health_score(project_id: int, db: Session = Depends(get_db)) -> HealthScoreOut:
    """Multi-dimensional project health score (0-100)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    boq_rows = db.query(BoqItem).filter(BoqItem.project_id == project_id).all()
    boq_count = len(boq_rows)
    boq_ids = [r.id for r in boq_rows]

    # 1. Binding completeness (30% weight)
    bound_count = 0
    if boq_ids:
        bound_count = (
            db.query(func.count(func.distinct(LineItemQuotaBinding.boq_item_id)))
            .filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids))
            .scalar() or 0
        )
    binding_pct = (bound_count / boq_count * 100) if boq_count else 0
    binding_score = min(int(binding_pct), 100)

    # 2. Calculation freshness (25% weight) — % of items not dirty
    dirty_count = sum(1 for r in boq_rows if r.is_dirty)
    clean_pct = ((boq_count - dirty_count) / boq_count * 100) if boq_count else 0
    calc_score = min(int(clean_pct), 100)

    # 3. Validation (25% weight)
    issues = validate_project(project_id=project_id, db=db)
    error_count = sum(1 for i in issues if i.severity == Severity.ERROR)
    warning_count = sum(1 for i in issues if i.severity == Severity.WARNING)
    # Deduct 15 per error, 5 per warning
    val_score = max(0, 100 - error_count * 15 - warning_count * 5)

    # 4. Data quality (20% weight) — BOQ count + description presence
    has_desc = bool(project.description and len(project.description) >= 10)
    has_budget = bool(project.budget and project.budget > 0)
    has_enough_items = boq_count >= 5
    dq_score = int(
        (30 if has_desc else 0) +
        (30 if has_budget else 0) +
        (40 if has_enough_items else min(boq_count * 8, 40))
    )

    dimensions = [
        HealthScoreDimension(name="绑定完整性", score=binding_score, weight=0.30,
                             detail=f"{bound_count}/{boq_count} 已绑定"),
        HealthScoreDimension(name="计算时效性", score=calc_score, weight=0.25,
                             detail=f"{dirty_count} 项待重算"),
        HealthScoreDimension(name="验证通过率", score=val_score, weight=0.25,
                             detail=f"{error_count} 错误, {warning_count} 警告"),
        HealthScoreDimension(name="数据完整度", score=dq_score, weight=0.20,
                             detail=f"{'有' if has_desc else '无'}描述, {'有' if has_budget else '无'}预算, {boq_count}项"),
    ]

    overall = int(sum(d.score * d.weight for d in dimensions))
    grade = "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60 else "D" if overall >= 40 else "F"

    suggestions = []
    if binding_score < 80:
        suggestions.append(f"还有 {boq_count - bound_count} 项未绑定定额，建议使用「一键自动匹配」")
    if dirty_count > 0:
        suggestions.append(f"{dirty_count} 项清单需要重新计算，点击「增量重算」更新造价")
    if error_count > 0:
        suggestions.append(f"存在 {error_count} 个验证错误，请先修复再出报告")
    if not has_budget:
        suggestions.append("建议设置项目预算，方便进行造价偏差分析")
    if not has_desc:
        suggestions.append("添加项目描述有助于 AI 智能开项时理解需求")

    return HealthScoreOut(
        project_id=project_id,
        overall_score=overall,
        grade=grade,
        dimensions=dimensions,
        suggestions=suggestions,
    )
