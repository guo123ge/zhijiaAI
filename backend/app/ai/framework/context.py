"""AgentContext — runtime context injection for tools and agents.

Inspired by Claude Code's ToolUseContext. All runtime dependencies
(db session, project_id, etc.) are bundled here so that:
1. Tools never need the LLM to provide system IDs
2. Parameter lists stay clean
3. Context is easily mockable for tests

Usage:
    ctx = AgentContext(db=db, project_id=1)
    result = some_tool.execute(ctx, {"keyword": "混凝土"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.ai.framework.budget import TokenBudget
    from app.ai.framework.memory_store import MemoryStore


@dataclass
class AgentContext:
    """Runtime context injected into every tool and agent.

    Replaces the scattered parameter lists like:
        _execute_tool(tool_name, tool_args, db, boq, project_region)

    With a single context object:
        tool.execute(ctx, tool_args)
    """

    # ── Required ──
    db: "Session"
    project_id: int

    # ── Optional context ──
    boq_item_id: int | None = None
    project_region: str = ""
    user_id: int | None = None
    session_id: str | None = None

    # ── Budget (set by BaseAgent.run) ──
    budget: "TokenBudget | None" = None

    # ── Domain context (F4) ──
    project_summary: str | None = None
    pricing_context: str | None = None
    recent_operations: list[str] = field(default_factory=list)

    # ── Memory store (H3) ──
    memory: "MemoryStore | None" = None

    # ── Extensible metadata ──
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── F4: Domain context builder ──

    def build_project_context(self) -> str:
        """Build a text summary of the current project for system prompt injection.

        Auto-loads from DB if project_summary is not already set.
        Returns empty string if project not found.
        """
        if self.project_summary:
            return self.project_summary

        project = self.get_project()
        if not project:
            return ""

        parts = [
            f"项目: {project.name}",
            f"地区: {getattr(project, 'region', '') or '未设置'}",
        ]
        if hasattr(project, 'project_type') and project.project_type:
            parts.append(f"类型: {project.project_type}")
        if hasattr(project, 'description') and project.description:
            parts.append(f"描述: {project.description[:200]}")

        # BOQ stats if available
        try:
            from app.models.boq_item import BoqItem
            total = self.db.query(BoqItem).filter(BoqItem.project_id == self.project_id).count()
            if total > 0:
                parts.append(f"清单项总数: {total}")
        except Exception:
            pass

        self.project_summary = "\n".join(parts)
        return self.project_summary

    # ── Convenience accessors ──

    def get_boq_item(self) -> Any:
        """Load the BOQ item from DB. Returns None if boq_item_id is not set."""
        if self.boq_item_id is None:
            return None
        from app.models.boq_item import BoqItem
        return (
            self.db.query(BoqItem)
            .filter(BoqItem.id == self.boq_item_id, BoqItem.project_id == self.project_id)
            .first()
        )

    def get_project(self) -> Any:
        """Load the Project from DB."""
        from app.models.project import Project
        return self.db.query(Project).filter(Project.id == self.project_id).first()

    def resolve_region(self) -> str:
        """Get project region, loading from DB if not set."""
        if self.project_region:
            return self.project_region
        project = self.get_project()
        if project:
            self.project_region = project.region or ""
        return self.project_region
