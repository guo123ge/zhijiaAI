"""CRUD routes for Tags and EntityTags."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.tag import Tag
from app.models.entity_tag import EntityTag
from app.schemas.knowledge_graph import (
    EntityTagCreate,
    EntityTagOut,
    TagCreate,
    TagOut,
)

router = APIRouter(tags=["tags"])


# ── Tag CRUD ─────────────────────────────────────────────────────────────────

@router.get("/tags", response_model=list[TagOut])
def list_tags(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Tag)
    if category:
        q = q.filter(Tag.category == category)
    return q.order_by(Tag.name).all()


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(body: TagCreate, db: Session = Depends(get_db)):
    existing = db.query(Tag).filter(Tag.name == body.name).first()
    if existing:
        raise HTTPException(400, f"Tag '{body.name}' already exists")
    tag = Tag(name=body.name, color=body.color, category=body.category)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.query(Tag).get(tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.query(EntityTag).filter(EntityTag.tag_id == tag_id).delete()
    db.delete(tag)
    db.commit()


# ── EntityTag (attach / detach tags to entities) ─────────────────────────────

@router.get("/entity-tags", response_model=list[EntityTagOut])
def list_entity_tags(
    entity_type: str | None = None,
    entity_id: int | None = None,
    tag_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(EntityTag, Tag.name, Tag.color).join(Tag, EntityTag.tag_id == Tag.id)
    if entity_type:
        q = q.filter(EntityTag.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(EntityTag.entity_id == entity_id)
    if tag_id is not None:
        q = q.filter(EntityTag.tag_id == tag_id)
    rows = q.all()
    return [
        EntityTagOut(
            id=et.id,
            tag_id=et.tag_id,
            tag_name=name,
            tag_color=color,
            entity_type=et.entity_type,
            entity_id=et.entity_id,
        )
        for et, name, color in rows
    ]


@router.post("/entity-tags", response_model=EntityTagOut, status_code=201)
def attach_tag(body: EntityTagCreate, db: Session = Depends(get_db)):
    tag = db.query(Tag).get(body.tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    existing = (
        db.query(EntityTag)
        .filter(
            EntityTag.tag_id == body.tag_id,
            EntityTag.entity_type == body.entity_type,
            EntityTag.entity_id == body.entity_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(400, "Tag already attached to this entity")
    et = EntityTag(tag_id=body.tag_id, entity_type=body.entity_type, entity_id=body.entity_id)
    db.add(et)
    db.commit()
    db.refresh(et)
    return EntityTagOut(
        id=et.id,
        tag_id=et.tag_id,
        tag_name=tag.name,
        tag_color=tag.color,
        entity_type=et.entity_type,
        entity_id=et.entity_id,
    )


@router.delete("/entity-tags/{entity_tag_id}", status_code=204)
def detach_tag(entity_tag_id: int, db: Session = Depends(get_db)):
    et = db.query(EntityTag).get(entity_tag_id)
    if not et:
        raise HTTPException(404, "EntityTag not found")
    db.delete(et)
    db.commit()
