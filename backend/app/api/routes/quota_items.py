from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.models.quota_item import QuotaItem

router = APIRouter(tags=["quota-items"])


@router.get("/quota-items")
def list_quota_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    chapter: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(QuotaItem)
    if chapter:
        q = q.filter(QuotaItem.chapter == chapter)
    if keyword:
        q = q.filter(QuotaItem.name.contains(keyword))
    total = q.count()
    items = q.offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": it.id,
                "quota_code": it.quota_code,
                "name": it.name,
                "unit": it.unit,
                "chapter": it.chapter,
                "labor_qty": it.labor_qty,
                "material_qty": it.material_qty,
                "machine_qty": it.machine_qty,
            }
            for it in items
        ],
    }


@router.get("/quota-items/stats")
def quota_stats(db: Session = Depends(get_db)):
    total = db.query(QuotaItem).count()
    chapters = (
        db.query(QuotaItem.chapter, func.count())
        .group_by(QuotaItem.chapter)
        .order_by(func.count().desc())
        .all()
    )
    return {
        "total": total,
        "chapters": [{"chapter": ch, "count": n} for ch, n in chapters],
    }
