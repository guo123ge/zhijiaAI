"""Skills browsing API (Phase H9).

Read-only REST endpoints for listing and inspecting domain Skills.
Skills are statically loaded from ``app/ai/skills/`` at app startup
(via skill_tools import side-effect); these routes are pure reads.

## Endpoints

- GET /api/skills                   list all registered skills (summary)
- GET /api/skills/{name}            fetch a single skill including body
- GET /api/skills/search            keyword search (trigger/tag AND-match)
- GET /api/skills/search/semantic   embedding-based semantic match
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["skills"])


# ── Schemas ──────────────────────────────────────────────────────


class SkillSummary(BaseModel):
    """Compact skill description — no body, safe for list views."""

    name: str
    title: str
    description: str
    triggers: list[str] = []
    tags: list[str] = []
    version: str = "1.0"


class SkillDetail(SkillSummary):
    """Full skill including body."""
    body: str


class SkillMatch(SkillSummary):
    """Semantic / keyword match result with similarity score."""
    score: float = 0.0


class ListSkillsResponse(BaseModel):
    skills: list[SkillSummary]
    total: int


class SearchSkillsResponse(BaseModel):
    matches: list[SkillSummary]
    total: int


class SemanticMatchResponse(BaseModel):
    matches: list[SkillMatch]
    total: int


# ── Helpers ──────────────────────────────────────────────────────


def _registry():
    """Lazy-load registry + bootstrap default skills idempotently."""
    from app.ai.framework.skill_registry import (
        bootstrap_default_skills,
        skill_registry,
    )
    bootstrap_default_skills()
    return skill_registry


def _to_summary(skill) -> SkillSummary:
    return SkillSummary(
        name=skill.name,
        title=skill.title,
        description=skill.description,
        triggers=list(skill.triggers),
        tags=list(skill.tags),
        version=skill.version,
    )


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/skills", response_model=ListSkillsResponse)
def list_skills() -> ListSkillsResponse:
    """List all registered skills (summary, no body)."""
    skills = _registry().all_skills()
    return ListSkillsResponse(
        skills=[_to_summary(s) for s in skills],
        total=len(skills),
    )


@router.get("/skills/search", response_model=SearchSkillsResponse)
def search_skills(
    query: str | None = Query(None, description="match against skill triggers (case-insensitive)"),
    tags: str = Query("", description="comma-separated; skill must have ALL tags"),
) -> SearchSkillsResponse:
    """Keyword + tag search. AND semantics across provided criteria."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    matches = _registry().match(
        query=query or None,
        tags=tag_list,
    )
    return SearchSkillsResponse(
        matches=[_to_summary(s) for s in matches],
        total=len(matches),
    )


@router.get("/skills/search/semantic", response_model=SemanticMatchResponse)
def search_skills_semantic(
    query: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    min_similarity: float = Query(0.0, ge=-1.0, le=1.0),
) -> SemanticMatchResponse:
    """Embedding-based semantic skill match."""
    try:
        scored = _registry().match_semantic(
            query=query,
            limit=limit,
            min_similarity=min_similarity,
        )
    except Exception as exc:
        logger.error("semantic skill match failed: %s", exc)
        raise HTTPException(status_code=500, detail="semantic match failed")

    return SemanticMatchResponse(
        matches=[
            SkillMatch(score=round(score, 4), **_to_summary(s).model_dump())
            for score, s in scored
        ],
        total=len(scored),
    )


@router.get("/skills/{name}", response_model=SkillDetail)
def get_skill(name: str) -> SkillDetail:
    """Fetch a single skill including the full body."""
    skill = _registry().get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"skill not found: {name}")
    return SkillDetail(
        **_to_summary(skill).model_dump(),
        body=skill.body,
    )
