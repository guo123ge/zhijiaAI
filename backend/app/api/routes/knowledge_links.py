"""CRUD routes for KnowledgeLinks (soft associations between entities)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.knowledge_link import KnowledgeLink
from app.schemas.knowledge_graph import (
    KnowledgeLinkCreate,
    KnowledgeLinkOut,
    KnowledgeLinkUpdate,
)

router = APIRouter(tags=["knowledge-links"])


@router.get("/knowledge-links", response_model=list[KnowledgeLinkOut])
def list_links(
    entity_type: str | None = None,
    entity_id: int | None = None,
    link_type: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeLink)
    if entity_type and entity_id is not None:
        q = q.filter(
            ((KnowledgeLink.source_type == entity_type) & (KnowledgeLink.source_id == entity_id))
            | ((KnowledgeLink.target_type == entity_type) & (KnowledgeLink.target_id == entity_id))
        )
    if link_type:
        q = q.filter(KnowledgeLink.link_type == link_type)
    return q.order_by(KnowledgeLink.created_at.desc()).all()


@router.post("/knowledge-links", response_model=KnowledgeLinkOut, status_code=201)
def create_link(body: KnowledgeLinkCreate, db: Session = Depends(get_db)):
    link = KnowledgeLink(
        source_type=body.source_type,
        source_id=body.source_id,
        target_type=body.target_type,
        target_id=body.target_id,
        link_type=body.link_type,
        label=body.label,
        note=body.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.put("/knowledge-links/{link_id}", response_model=KnowledgeLinkOut)
def update_link(link_id: int, body: KnowledgeLinkUpdate, db: Session = Depends(get_db)):
    link = db.query(KnowledgeLink).get(link_id)
    if not link:
        raise HTTPException(404, "KnowledgeLink not found")
    if body.link_type is not None:
        link.link_type = body.link_type
    if body.label is not None:
        link.label = body.label
    if body.note is not None:
        link.note = body.note
    db.commit()
    db.refresh(link)
    return link


@router.delete("/knowledge-links/{link_id}", status_code=204)
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.query(KnowledgeLink).get(link_id)
    if not link:
        raise HTTPException(404, "KnowledgeLink not found")
    db.delete(link)
    db.commit()
