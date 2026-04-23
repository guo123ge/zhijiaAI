"""AgentLoader — discovers and loads ConfigurableAgent instances from a directory.

Phase H1: Enables hot-loading agents from .md files without Python code changes.

Usage:
    from app.ai.framework.agent_loader import load_agents_from_dir

    agents = load_agents_from_dir("app/ai/agents/configs")
    for agent in agents:
        print(agent.name, agent.description)

The loader:
1. Scans a directory for .md files (non-recursive by default)
2. Parses each file into an AgentDefinition
3. Validates tool references against the global ToolRegistry
4. Returns a list of ConfigurableAgent instances

Invalid files are skipped with a warning (by default) or raise (if strict=True).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.ai.framework.agent_definition import (
    AgentDefinition,
    AgentDefinitionError,
    parse_agent_file,
)
from app.ai.framework.configurable_agent import ConfigurableAgent
from app.ai.framework.tool_registry import ToolRegistry, registry as global_registry

logger = logging.getLogger(__name__)

# Agent files must have snake_case filenames (e.g. `quick_explorer.md`).
# Non-matching files (README.md, NOTES.md, _draft.md) are skipped silently,
# treating them as documentation rather than malformed agent definitions.
_AGENT_FILENAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.md$")


def _is_agent_file(path: Path) -> bool:
    """Return True if filename matches the agent-file convention."""
    return bool(_AGENT_FILENAME_RE.match(path.name))


# ───────────────────────────────────────────────────────────────────
# Loader
# ───────────────────────────────────────────────────────────────────


def load_definitions_from_dir(
    directory: str | Path,
    *,
    recursive: bool = False,
    strict: bool = False,
) -> list[AgentDefinition]:
    """Scan a directory for .md agent definition files.

    Args:
        directory: Path to the directory containing .md files.
        recursive: If True, recurse into subdirectories.
        strict: If True, raise on any parse error; otherwise log and skip.

    Returns:
        List of successfully parsed AgentDefinition objects.
    """
    d = Path(directory)
    if not d.is_dir():
        if strict:
            raise AgentDefinitionError(f"not a directory: {d}")
        logger.warning("agent_loader: directory does not exist: %s", d)
        return []

    pattern = "**/*.md" if recursive else "*.md"
    # Filter to snake_case agent files; skip README.md, NOTES.md, etc.
    files = sorted(f for f in d.glob(pattern) if _is_agent_file(f))
    definitions: list[AgentDefinition] = []

    for f in files:
        try:
            definitions.append(parse_agent_file(f))
        except AgentDefinitionError as e:
            if strict:
                raise
            logger.warning("agent_loader: skipping %s: %s", f.name, e)
        except Exception as e:  # pragma: no cover — defensive
            if strict:
                raise
            logger.exception("agent_loader: unexpected error on %s: %s", f.name, e)

    # Detect duplicate names — these are errors regardless of strict mode
    names_seen: dict[str, AgentDefinition] = {}
    deduped: list[AgentDefinition] = []
    for defn in definitions:
        if defn.name in names_seen:
            msg = (
                f"duplicate agent name {defn.name!r}: "
                f"{names_seen[defn.name].source_file} vs {defn.source_file}"
            )
            if strict:
                raise AgentDefinitionError(msg)
            logger.warning("agent_loader: %s (second definition ignored)", msg)
            continue
        names_seen[defn.name] = defn
        deduped.append(defn)

    return deduped


def validate_tool_references(
    definition: AgentDefinition,
    *,
    tool_registry: ToolRegistry | None = None,
) -> list[str]:
    """Return missing tool names that are referenced but not registered."""
    reg = tool_registry or global_registry
    all_tools = set(reg.all_names)
    return [t for t in definition.tool_names if t not in all_tools]


def load_agents_from_dir(
    directory: str | Path,
    *,
    recursive: bool = False,
    strict: bool = False,
    tool_registry: ToolRegistry | None = None,
) -> list[ConfigurableAgent]:
    """High-level helper: parse + validate + instantiate ConfigurableAgents.

    Args:
        directory: Directory containing .md files.
        recursive: Recurse into subdirectories.
        strict: Raise on parse errors or missing tool references.
        tool_registry: Optional custom registry (defaults to global).

    Returns:
        List of ConfigurableAgent instances whose tool references are all valid.
    """
    definitions = load_definitions_from_dir(
        directory, recursive=recursive, strict=strict
    )
    agents: list[ConfigurableAgent] = []
    for defn in definitions:
        missing = validate_tool_references(defn, tool_registry=tool_registry)
        if missing:
            msg = (
                f"{defn.source_file}: agent {defn.name!r} references unknown tools: "
                f"{missing}"
            )
            if strict:
                raise AgentDefinitionError(msg)
            logger.warning("agent_loader: %s — skipping", msg)
            continue
        agents.append(ConfigurableAgent(defn))
    logger.info("agent_loader: loaded %d agent(s) from %s", len(agents), directory)
    return agents
