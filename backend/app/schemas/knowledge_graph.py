"""Pydantic schemas for knowledge graph features: tags, links, notes, and graph data."""

from pydantic import BaseModel


# ── Tags ──────────────────────────────────────────────────────────────────────

class TagCreate(BaseModel):
    name: str
    color: str = "#3b82f6"
    category: str = ""


class TagOut(BaseModel):
    id: int
    name: str
    color: str
    category: str
    created_at: str


class EntityTagCreate(BaseModel):
    tag_id: int
    entity_type: str
    entity_id: int


class EntityTagOut(BaseModel):
    id: int
    tag_id: int
    tag_name: str = ""
    tag_color: str = ""
    entity_type: str
    entity_id: int


# ── Knowledge Links ──────────────────────────────────────────────────────────

class KnowledgeLinkCreate(BaseModel):
    source_type: str
    source_id: int
    target_type: str
    target_id: int
    link_type: str = "related"
    label: str = ""
    note: str = ""


class KnowledgeLinkUpdate(BaseModel):
    link_type: str | None = None
    label: str | None = None
    note: str | None = None


class KnowledgeLinkOut(BaseModel):
    id: int
    source_type: str
    source_id: int
    target_type: str
    target_id: int
    link_type: str
    label: str
    note: str
    created_at: str


# ── Knowledge Notes ──────────────────────────────────────────────────────────

class KnowledgeNoteCreate(BaseModel):
    entity_type: str
    entity_id: int
    title: str = ""
    content: str = ""


class KnowledgeNoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class KnowledgeNoteOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    title: str
    content: str
    created_at: str
    updated_at: str


# ── Graph Data ───────────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str  # "{type}:{entity_id}" e.g. "project:1"
    type: str  # "project" | "boq_item" | "quota_item" | "material_price" | "tag" | "rule_package"
    label: str
    properties: dict = {}
    tags: list[str] = []


class GraphEdge(BaseModel):
    source: str  # node id
    target: str  # node id
    type: str  # "fk" | "binding" | "resource" | "tag" | "knowledge_link"
    label: str = ""


class GraphDataOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
