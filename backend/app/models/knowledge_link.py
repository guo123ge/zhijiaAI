"""KnowledgeLink — soft/custom associations between any two entities.

Unlike foreign-key relationships which are structural, knowledge links capture
semantic associations such as "similar item", "alternative material",
"derived from", "compare", etc.  These power the knowledge graph edges.
"""

from datetime import datetime, timezone

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeLink(Base):
    __tablename__ = "knowledge_links"
    __table_args__ = (
        Index("ix_kl_source", "source_type", "source_id"),
        Index("ix_kl_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # entity type
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    link_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="related",
    )  # "similar" | "alternative" | "derived_from" | "compare" | "related" | "custom"
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
