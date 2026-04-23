"""CRUD routes for KnowledgeNotes (Markdown notes attached to entities)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.knowledge_note import KnowledgeNote
from app.schemas.knowledge_graph import (
    KnowledgeNoteCreate,
    KnowledgeNoteOut,
    KnowledgeNoteUpdate,
)

router = APIRouter(tags=["knowledge-notes"])


@router.get("/knowledge-notes", response_model=list[KnowledgeNoteOut])
def list_notes(
    entity_type: str | None = None,
    entity_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeNote)
    if entity_type:
        q = q.filter(KnowledgeNote.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(KnowledgeNote.entity_id == entity_id)
    return q.order_by(KnowledgeNote.updated_at.desc()).all()


@router.post("/knowledge-notes", response_model=KnowledgeNoteOut, status_code=201)
def create_note(body: KnowledgeNoteCreate, db: Session = Depends(get_db)):
    note = KnowledgeNote(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        title=body.title,
        content=body.content,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.put("/knowledge-notes/{note_id}", response_model=KnowledgeNoteOut)
def update_note(note_id: int, body: KnowledgeNoteUpdate, db: Session = Depends(get_db)):
    note = db.query(KnowledgeNote).get(note_id)
    if not note:
        raise HTTPException(404, "KnowledgeNote not found")
    if body.title is not None:
        note.title = body.title
    if body.content is not None:
        note.content = body.content
    note.updated_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(note)
    return note


@router.delete("/knowledge-notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    note = db.query(KnowledgeNote).get(note_id)
    if not note:
        raise HTTPException(404, "KnowledgeNote not found")
    db.delete(note)
    db.commit()
