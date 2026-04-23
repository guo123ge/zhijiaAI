"""Skill — declarative domain-knowledge module (Phase H4).

Inspired by Claude Code's Skills pattern. A Skill is a reusable
domain-knowledge fragment (Markdown body + YAML frontmatter metadata)
that Agents can reference to gain specialized expertise.

## Difference from Agent

- **Agent**: a complete actor (name + prompt + tools + reasoning loop)
- **Skill**: a knowledge module that gets injected into an agent's
  system prompt — no tools, no loop, just domain content

Multiple agents can share the same Skill, e.g. `hksmm4_basics` could be
used by both the BOQ agent and the validation agent.

## File format

```markdown
---
name: hksmm4_basics
title: HKSMM4 第四版基础规则
description: 香港标准工程量计算方法第四版的关键规则摘要
triggers:
  - HKSMM4
  - 香港工程量
  - BOQ 计量
applies_to:
  region: HK
tags:
  - standard
  - hong_kong
  - measurement
version: "4.0"
---

## 总则

HKSMM4 适用于香港地区的建筑与土木工程工程量清单编制...

## 第 2 部分 一般规则
...
```

## Usage

```python
from app.ai.framework.skill import parse_skill_file

skill = parse_skill_file("skills/hksmm4_basics.md")
# Inject into a system prompt
system_prompt = f"{base_prompt}\n\n{skill.render()}"
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ───────────────────────────────────────────────────────────────────
# Skill
# ───────────────────────────────────────────────────────────────────


@dataclass
class Skill:
    """Declarative domain-knowledge module.

    Skills are Markdown files with YAML frontmatter. Their body is
    the domain content that gets injected into an agent's system prompt.
    """

    name: str
    title: str
    description: str
    body: str                          # the Markdown knowledge content
    triggers: list[str] = field(default_factory=list)   # keywords that activate this skill
    applies_to: dict[str, Any] = field(default_factory=dict)  # e.g. {"region": "HK"}
    tags: list[str] = field(default_factory=list)
    version: str = "1.0"
    source_file: str | None = None
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
        if not self.title:
            errors.append("'title' is required")
        if not self.description:
            errors.append("'description' is required")
        if not self.body.strip():
            errors.append("skill body is required")
        return errors

    # ── Rendering ──

    def render(self, *, include_meta: bool = True) -> str:
        """Render skill for injection into a system prompt.

        Args:
            include_meta: If True, prepend a short header identifying the skill.
        """
        if not include_meta:
            return self.body.strip()

        header = f"## 领域知识：{self.title}\n_{self.description}_\n"
        return f"{header}\n{self.body.strip()}"

    # ── Matching ──

    def matches_query(self, query: str) -> bool:
        """Check if any trigger keyword appears in the given query."""
        if not query:
            return False
        q = query.lower()
        return any(t.lower() in q for t in self.triggers)

    def matches_context(self, ctx_attrs: dict[str, Any]) -> bool:
        """Check if all applies_to conditions match the given context attrs.

        Example: skill.applies_to = {"region": "HK"}; if ctx_attrs["region"] == "HK",
        matches.
        """
        if not self.applies_to:
            return True
        for key, expected in self.applies_to.items():
            actual = ctx_attrs.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            else:
                if actual != expected:
                    return False
        return True


# ───────────────────────────────────────────────────────────────────
# Parsers
# ───────────────────────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


class SkillParseError(ValueError):
    """Raised when a skill file is malformed."""


def parse_skill_text(text: str, *, source: str | None = None) -> Skill:
    """Parse a Markdown string with YAML frontmatter into a Skill.

    Args:
        text: File contents.
        source: Source identifier (e.g. file path) for error messages.
    """
    src = source or "<string>"
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillParseError(
            f"{src}: missing YAML frontmatter — file must start with '---\\n...\\n---\\n'"
        )

    fm_text = match.group("frontmatter")
    body = match.group("body").strip()

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"{src}: invalid YAML frontmatter: {e}") from e

    if not isinstance(fm, dict):
        raise SkillParseError(
            f"{src}: frontmatter must be a YAML mapping, got {type(fm).__name__}"
        )

    known_fields = {
        "name", "title", "description",
        "triggers", "applies_to", "tags", "version",
    }
    extra = {k: v for k, v in fm.items() if k not in known_fields}

    triggers_raw = fm.get("triggers", []) or []
    if not isinstance(triggers_raw, list):
        raise SkillParseError(
            f"{src}: 'triggers' must be a list, got {type(triggers_raw).__name__}"
        )
    triggers = [str(t) for t in triggers_raw]

    tags_raw = fm.get("tags", []) or []
    if not isinstance(tags_raw, list):
        raise SkillParseError(
            f"{src}: 'tags' must be a list, got {type(tags_raw).__name__}"
        )
    tags = [str(t) for t in tags_raw]

    applies_to_raw = fm.get("applies_to", {}) or {}
    if not isinstance(applies_to_raw, dict):
        raise SkillParseError(
            f"{src}: 'applies_to' must be a mapping, got {type(applies_to_raw).__name__}"
        )

    skill = Skill(
        name=str(fm.get("name", "")).strip(),
        title=str(fm.get("title", "")).strip(),
        description=str(fm.get("description", "")).strip(),
        body=body,
        triggers=triggers,
        applies_to=applies_to_raw,
        tags=tags,
        version=str(fm.get("version", "1.0")).strip(),
        source_file=source,
        extra=extra,
    )

    errors = skill.validate()
    if errors:
        raise SkillParseError(f"{src}: " + "; ".join(errors))
    return skill


def parse_skill_file(path: Path | str) -> Skill:
    """Parse a single .md skill file."""
    p = Path(path)
    if not p.is_file():
        raise SkillParseError(f"not a file: {p}")
    text = p.read_text(encoding="utf-8")
    return parse_skill_text(text, source=str(p))
