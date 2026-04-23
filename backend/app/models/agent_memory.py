"""AgentMemory — persistent cross-session memory for agents.

Each row is one memory entry keyed by (scope, scope_id, key).

See app/ai/framework/memory_store.py for the high-level API.
"""

from datetime import datetime, timezone

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Scoping ──
    # scope ∈ {"global", "user", "project"}
    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # scope_id: user_id / project_id; NULL for global scope
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── Payload ──
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # ── Provenance ──
    created_by_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Timestamps ──
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    last_accessed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Usage stats ──
    accessed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "key", name="uq_memory_scope_key"),
        Index("idx_memory_scope_importance", "scope", "scope_id", "importance"),
    )
