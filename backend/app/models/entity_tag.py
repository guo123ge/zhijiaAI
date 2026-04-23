"""EntityTag junction table — polymorphic many-to-many between tags and any entity.

Uses (entity_type, entity_id) pattern so tags can be attached to projects,
boq_items, quota_items, material_prices, etc. without altering their schemas.
"""

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntityTag(Base):
    __tablename__ = "entity_tags"
    __table_args__ = (
        UniqueConstraint("tag_id", "entity_type", "entity_id", name="uq_entity_tag"),
        Index("ix_entity_tag_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "project" | "boq_item" | "quota_item" | "material_price" ...
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
