"""ToolRegistry — global tool registration and dispatch.

Inspired by Claude Code's tools.ts registry + buildTool() pattern.
All tools register here; agents select subsets by name.

Usage:
    registry = ToolRegistry()
    registry.register(search_quotas_tool)
    registry.register(bind_quota_tool)

    # Agent declares which tools it needs
    tools = registry.get_tools(["search_quotas", "bind_quota"])
    schemas = registry.get_openai_schemas(["search_quotas", "bind_quota"])

    # Execute a tool call from LLM
    result = registry.execute("search_quotas", {"keyword": "混凝土"}, ctx)
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from app.ai.framework.tool_def import ToolDef

if TYPE_CHECKING:
    from app.ai.framework.context import AgentContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central registry for all agent tools.

    Singleton-friendly: import the module-level ``registry`` instance.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    # ── Registration ──

    def register(self, tool: ToolDef) -> None:
        """Register a tool. Overwrites if name already exists."""
        if tool.name in self._tools:
            logger.debug("Overwriting tool '%s' in registry", tool.name)
        self._tools[tool.name] = tool

    def register_many(self, *tools: ToolDef) -> None:
        for t in tools:
            self.register(t)

    # ── Lookup ──

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def get_tools(self, names: list[str] | None = None) -> list[ToolDef]:
        """Get tools by name list. If names is None, return all."""
        if names is None:
            return list(self._tools.values())
        return [self._tools[n] for n in names if n in self._tools]

    def get_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """Generate OpenAI function calling schemas for given tool names."""
        return [t.to_openai_schema() for t in self.get_tools(names)]

    @property
    def all_names(self) -> list[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    # ── Execution ──

    def execute(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        ctx: "AgentContext",
    ) -> str:
        """Execute a tool by name with context injection.

        Returns JSON string (always — even on error).
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            logger.warning("Unknown tool requested: %s", tool_name)
            return json.dumps(
                {
                    "ok": False,
                    "error_type": "unknown_tool",
                    "error": f"未知工具: {tool_name}",
                    "recoverable": False,
                    "tool_name": tool_name,
                },
                ensure_ascii=False,
            )
        return tool.execute(ctx, tool_args)

    # ── Partitioning (borrowed from Claude Code's partitionToolCalls) ──

    def partition_by_concurrency(
        self,
        tool_names: list[str],
    ) -> list[tuple[bool, list[str]]]:
        """Partition a sequence of tool names into batches.

        Consecutive concurrency-safe tools are grouped together;
        non-safe tools are isolated into single-item batches.

        Returns list of (is_concurrent_batch, [tool_names]).
        """
        if not tool_names:
            return []

        batches: list[tuple[bool, list[str]]] = []
        for name in tool_names:
            tool = self._tools.get(name)
            safe = tool.is_concurrency_safe if tool else False
            if batches and batches[-1][0] == safe and safe:
                batches[-1][1].append(name)
            else:
                batches.append((safe, [name]))
        return batches


# ── Module-level singleton ──
registry = ToolRegistry()
