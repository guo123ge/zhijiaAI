"""AgentDefinition — declarative agent configuration (Phase H1).

Parses Markdown files with YAML frontmatter into typed AgentDefinition objects.
Inspired by Claude Code's `loadAgentsDir.ts`, this allows creating new agents
by writing a .md file — no Python code required.

## File format

Agents are .md files with YAML frontmatter:

```markdown
---
name: cost_explorer_lite
description: 轻量级造价探索
model: fast              # fast | balanced | powerful
read_only: true
max_turns: 5
max_tool_concurrency: 5
compact_threshold_tokens: 0
tools:
  - search_quotas
  - get_quota_detail
---

你是一个轻量级造价探索助手...
(system prompt body — everything after the frontmatter)
```

## Usage

    from app.ai.framework.agent_definition import parse_agent_file
    definition = parse_agent_file(Path("agents/configs/cost_explorer_lite.md"))
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ───────────────────────────────────────────────────────────────────
# AgentDefinition
# ───────────────────────────────────────────────────────────────────


@dataclass
class AgentDefinition:
    """Declarative agent spec parsed from a Markdown file with YAML frontmatter."""

    name: str
    description: str
    system_prompt: str
    tool_names: list[str] = field(default_factory=list)
    model: str = "balanced"           # fast | balanced | powerful
    max_turns: int = 12
    read_only: bool = False
    max_tool_concurrency: int = 5
    compact_threshold_tokens: int = 0
    # Phase H3: cross-session memory
    use_memory_context: bool = False
    memory_context_limit: int = 5
    # Phase H4: domain skills (declarative)
    skills: list[str] = field(default_factory=list)
    source_file: str | None = None     # provenance — where this was loaded from
    extra: dict[str, Any] = field(default_factory=dict)

    # ── Validation ──

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty if valid)."""
        errors: list[str] = []
        if not self.name:
            errors.append("'name' is required")
        elif not re.match(r"^[a-z][a-z0-9_]*$", self.name):
            errors.append(
                f"'name' must be lowercase snake_case, got: {self.name!r}"
            )
        if not self.description:
            errors.append("'description' is required")
        if not self.system_prompt.strip():
            errors.append("system_prompt body is required")
        if self.model not in ("fast", "balanced", "powerful"):
            errors.append(
                f"'model' must be fast|balanced|powerful, got: {self.model!r}"
            )
        if self.max_turns <= 0:
            errors.append(f"'max_turns' must be > 0, got {self.max_turns}")
        if self.max_tool_concurrency <= 0:
            errors.append(
                f"'max_tool_concurrency' must be > 0, got {self.max_tool_concurrency}"
            )
        if self.compact_threshold_tokens < 0:
            errors.append(
                f"'compact_threshold_tokens' must be >= 0, got {self.compact_threshold_tokens}"
            )
        return errors


# ───────────────────────────────────────────────────────────────────
# Parsers
# ───────────────────────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


class AgentDefinitionError(ValueError):
    """Raised when an agent definition file is malformed."""


def parse_agent_text(text: str, *, source: str | None = None) -> AgentDefinition:
    """Parse a Markdown string with YAML frontmatter into an AgentDefinition.

    Args:
        text: The full file contents.
        source: Optional source identifier (e.g. file path) used in error messages.

    Raises:
        AgentDefinitionError: If frontmatter is missing, YAML is invalid,
            or required fields are missing.
    """
    src = source or "<string>"
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise AgentDefinitionError(
            f"{src}: missing YAML frontmatter — file must start with '---\\n...\\n---\\n'"
        )

    fm_text = match.group("frontmatter")
    body = match.group("body").strip()

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise AgentDefinitionError(f"{src}: invalid YAML frontmatter: {e}") from e

    if not isinstance(fm, dict):
        raise AgentDefinitionError(
            f"{src}: frontmatter must be a YAML mapping, got {type(fm).__name__}"
        )

    # Known fields → AgentDefinition
    known_fields = {
        "name", "description", "tools", "model",
        "max_turns", "read_only", "max_tool_concurrency",
        "compact_threshold_tokens",
        "use_memory_context", "memory_context_limit",
        "skills",
    }
    extra = {k: v for k, v in fm.items() if k not in known_fields}

    tool_names = fm.get("tools", []) or []
    if not isinstance(tool_names, list):
        raise AgentDefinitionError(
            f"{src}: 'tools' must be a list, got {type(tool_names).__name__}"
        )
    tool_names = [str(t) for t in tool_names]

    skills_raw = fm.get("skills", []) or []
    if not isinstance(skills_raw, list):
        raise AgentDefinitionError(
            f"{src}: 'skills' must be a list, got {type(skills_raw).__name__}"
        )
    skill_names = [str(s) for s in skills_raw]

    definition = AgentDefinition(
        name=str(fm.get("name", "")).strip(),
        description=str(fm.get("description", "")).strip(),
        system_prompt=body,
        tool_names=tool_names,
        model=str(fm.get("model", "balanced")).strip(),
        max_turns=int(fm.get("max_turns", 12)),
        read_only=bool(fm.get("read_only", False)),
        max_tool_concurrency=int(fm.get("max_tool_concurrency", 5)),
        compact_threshold_tokens=int(fm.get("compact_threshold_tokens", 0)),
        use_memory_context=bool(fm.get("use_memory_context", False)),
        memory_context_limit=int(fm.get("memory_context_limit", 5)),
        skills=skill_names,
        source_file=source,
        extra=extra,
    )

    errors = definition.validate()
    if errors:
        raise AgentDefinitionError(f"{src}: " + "; ".join(errors))
    return definition


def parse_agent_file(path: Path | str) -> AgentDefinition:
    """Parse a single .md agent definition file."""
    p = Path(path)
    if not p.is_file():
        raise AgentDefinitionError(f"not a file: {p}")
    text = p.read_text(encoding="utf-8")
    return parse_agent_text(text, source=str(p))
