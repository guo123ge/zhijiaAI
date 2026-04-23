"""Memory management API (Phase H9).

REST endpoints for direct CRUD + search over AgentMemory entries. Lets the
frontend and scripts manage persisted memories without going through the
Orchestrator.

## Endpoints

- GET    /api/memories                      list memories (by scope + optional filters)
- GET    /api/memories/search               substring search
- GET    /api/memories/search/semantic      embedding-based semantic search
- GET    /api/memories/one                  fetch single memory by (scope, scope_id, key)
- POST   /api/memories                      upsert a memory
- DELETE /api/memories/{memory_id}          delete by internal id

## Scope rules

- `scope=global` → `scope_id` must be omitted (or null)
- `scope=user`   → `scope_id` = user_id (required)
- `scope=project` → `scope_id` = project_id (required)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memories"])


# ── Schemas ──────────────────────────────────────────────────────


MemoryScopeLit = Literal["global", "user", "project"]


class MemoryOut(BaseModel):
    """Response model matching AgentMemory.to_dict() output."""

    id: int | None
    scope: str
    scope_id: int | None
    key: str
    content: str
    tags: list[str] = []
    importance: int = 3
    created_by_agent: str = ""
    created_at: str = ""
    updated_at: str = ""
    accessed_count: int = 0


class MemoryWithScore(MemoryOut):
    """Semantic search result with similarity score."""
    score: float = 0.0


class ListMemoriesResponse(BaseModel):
    memories: list[MemoryOut]
    total: int


class SearchMemoriesResponse(BaseModel):
    matches: list[MemoryOut]
    total: int


class SemanticSearchResponse(BaseModel):
    matches: list[MemoryWithScore]
    total: int


class UpsertMemoryRequest(BaseModel):
    scope: MemoryScopeLit
    scope_id: int | None = None
    key: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    importance: int = Field(3, ge=1, le=5)
    tags: list[str] = []
    created_by_agent: str = ""


class DeleteResponse(BaseModel):
    deleted: bool
    memory_id: int | None = None


# ── Helpers ──────────────────────────────────────────────────────


def _validate_scope(scope: str, scope_id: int | None) -> None:
    """Enforce scope → scope_id invariants used throughout the memory layer."""
    if scope == "global" and scope_id is not None:
        raise HTTPException(
            status_code=400,
            detail="global scope must not include scope_id",
        )
    if scope in ("user", "project") and scope_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"{scope} scope requires scope_id",
        )


def _store(db: Session):
    from app.ai.framework.memory_store import SQLAlchemyMemoryStore
    return SQLAlchemyMemoryStore(db)


def _to_out(memory: Any) -> MemoryOut:
    return MemoryOut(**memory.to_dict())


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/memories", response_model=ListMemoriesResponse)
def list_memories(
    scope: MemoryScopeLit = Query(...),
    scope_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ListMemoriesResponse:
    """List memories within a scope, ordered by importance desc / updated_at desc."""
    _validate_scope(scope, scope_id)
    mems = _store(db).list(scope=scope, scope_id=scope_id, limit=limit)
    return ListMemoriesResponse(
        memories=[_to_out(m) for m in mems],
        total=len(mems),
    )


@router.get("/memories/search", response_model=SearchMemoriesResponse)
def search_memories(
    scope: MemoryScopeLit = Query(...),
    scope_id: int | None = Query(None),
    query: str | None = Query(None, description="substring match against key/content"),
    tags: str = Query("", description="comma-separated; memory must have ALL tags"),
    min_importance: int = Query(1, ge=1, le=5),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
) -> SearchMemoriesResponse:
    """Substring + tag + importance search."""
    _validate_scope(scope, scope_id)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    mems = _store(db).search(
        scope=scope,
        scope_id=scope_id,
        query=query or None,
        tags=tag_list,
        min_importance=min_importance,
        limit=limit,
    )
    return SearchMemoriesResponse(
        matches=[_to_out(m) for m in mems],
        total=len(mems),
    )


@router.get("/memories/search/semantic", response_model=SemanticSearchResponse)
def search_memories_semantic(
    scope: MemoryScopeLit = Query(...),
    query: str = Query(..., min_length=1),
    scope_id: int | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    min_similarity: float = Query(0.0, ge=-1.0, le=1.0),
    db: Session = Depends(get_db),
) -> SemanticSearchResponse:
    """Embedding-based semantic search."""
    _validate_scope(scope, scope_id)
    try:
        scored = _store(db).search_semantic(
            scope=scope,
            scope_id=scope_id,
            query=query,
            limit=limit,
            min_similarity=min_similarity,
        )
    except Exception as exc:
        logger.error("semantic search failed: %s", exc)
        raise HTTPException(status_code=500, detail="semantic search failed")

    return SemanticSearchResponse(
        matches=[
            MemoryWithScore(score=round(score, 4), **m.to_dict())
            for score, m in scored
        ],
        total=len(scored),
    )


@router.get("/memories/one", response_model=MemoryOut)
def get_memory(
    scope: MemoryScopeLit = Query(...),
    key: str = Query(..., min_length=1, max_length=100),
    scope_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> MemoryOut:
    """Fetch a single memory by (scope, scope_id, key). 404 if absent."""
    _validate_scope(scope, scope_id)
    mem = _store(db).get(scope=scope, scope_id=scope_id, key=key)
    if mem is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _to_out(mem)


@router.post("/memories", response_model=MemoryOut)
def upsert_memory(
    payload: UpsertMemoryRequest,
    db: Session = Depends(get_db),
) -> MemoryOut:
    """Create or update a memory (keyed by scope + scope_id + key)."""
    _validate_scope(payload.scope, payload.scope_id)
    try:
        mem = _store(db).save(
            scope=payload.scope,
            scope_id=payload.scope_id,
            key=payload.key,
            content=payload.content,
            tags=list(payload.tags),
            importance=payload.importance,
            created_by_agent=payload.created_by_agent or "api",
        )
    except Exception as exc:
        logger.error("upsert memory failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_out(mem)


@router.delete("/memories/{memory_id}", response_model=DeleteResponse)
def delete_memory_by_id(
    memory_id: int,
    db: Session = Depends(get_db),
) -> DeleteResponse:
    """Delete a single memory by its internal id."""
    ok = _store(db).forget(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")
    return DeleteResponse(deleted=True, memory_id=memory_id)
