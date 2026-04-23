"""Skill tools — let agents discover and load domain Skills at runtime (H4).

These tools query the global skill_registry. Useful when an agent needs
to dynamically pull in expertise mid-conversation rather than statically
declaring all skills in its YAML config.

Tools exposed:
- list_skills: enumerate all registered skills (name, title, description)
- load_skill: fetch the full body of a named skill
- match_skills: find skills whose triggers match a query / context
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.framework.context import AgentContext
from app.ai.framework.skill_registry import (
    bootstrap_default_skills,
    skill_registry,
)
from app.ai.framework.tool_def import ParamDef, tool
from app.ai.framework.tool_registry import registry

# Auto-populate the skill registry from app/ai/skills/ on first import.
bootstrap_default_skills()


def _ok(data: Any) -> str:
    if isinstance(data, dict):
        return json.dumps({"ok": True, **data}, ensure_ascii=False)
    return json.dumps({"ok": True, "result": data}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


@tool(
    name="list_skills",
    description=(
        "列出所有已注册的领域 Skill（知识模块）。"
        " 返回 name/title/description/tags。"
        " 用于发现可以按需加载的专业知识模块。"
    ),
    read_only=True,
    concurrency_safe=True,
)
def list_skills(ctx: AgentContext) -> str:
    """List all registered skills."""
    skills = skill_registry.all_skills()
    return _ok({
        "total": len(skills),
        "skills": [
            {
                "name": s.name,
                "title": s.title,
                "description": s.description,
                "tags": list(s.tags),
                "version": s.version,
            }
            for s in skills
        ],
    })


@tool(
    name="load_skill",
    description=(
        "根据 name 加载一个 Skill 的完整知识内容，以文本形式返回。"
        " 适合：Agent 发现需要某个专业领域的详细规则时调用。"
    ),
    read_only=True,
    concurrency_safe=True,
)
def load_skill(ctx: AgentContext, *, name: str) -> str:
    """Load the full body of a named skill."""
    s = skill_registry.get(name)
    if s is None:
        return _err(f"skill not found: {name}")
    return _ok({
        "name": s.name,
        "title": s.title,
        "description": s.description,
        "tags": list(s.tags),
        "version": s.version,
        "content": s.render(include_meta=False),
    })


@tool(
    name="match_skills",
    description=(
        "按查询关键词和/或标签，返回匹配的 Skill 名单。"
        " query 会匹配 Skill 的 triggers；tags 要求 Skill 包含全部指定 tag。"
    ),
    read_only=True,
    concurrency_safe=True,
)
def match_skills(
    ctx: AgentContext,
    *,
    query: str = "",
    tags: str = "",
) -> str:
    """Match skills by trigger query and/or tags."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    matches = skill_registry.match(
        query=query or None,
        tags=tag_list,
    )
    return _ok({
        "total": len(matches),
        "matches": [
            {
                "name": s.name,
                "title": s.title,
                "description": s.description,
                "triggers": list(s.triggers),
                "tags": list(s.tags),
            }
            for s in matches
        ],
    })


@tool(
    name="match_skills_semantic",
    description=(
        "按语义相似度匹配 Skill（embedding 检索）。"
        " 比 match_skills 更智能：即使触发词不完全匹配，也能找到相关的领域知识。"
        " 必须传入非空 query，内容应为当前任务、问题或检索语句原文。"
        " 返回 {matches: [{name, title, description, score}]}，按相似度降序。"
        " limit 默认 5；min_similarity 默认 0。"
    ),
    read_only=True,
    concurrency_safe=True,
    params=[
        ParamDef(
            name="query",
            json_type="string",
            description="必填。传入当前任务、问题或检索语句，不要留空。",
            required=True,
            aliases=("q", "task", "instruction"),
        ),
        ParamDef(name="limit", json_type="integer", required=False),
        ParamDef(name="min_similarity", json_type="number", required=False),
    ],
)
def match_skills_semantic(
    ctx: AgentContext,
    *,
    query: str,
    limit: int = 5,
    min_similarity: float = 0.0,
) -> str:
    """Semantic skill matching via embeddings."""
    if not query:
        return _err("missing required query")
    scored = skill_registry.match_semantic(
        query=query,
        limit=int(limit),
        min_similarity=float(min_similarity),
    )
    return _ok({
        "total": len(scored),
        "matches": [
            {
                "name": s.name,
                "title": s.title,
                "description": s.description,
                "triggers": list(s.triggers),
                "tags": list(s.tags),
                "score": round(score, 4),
            }
            for score, s in scored
        ],
    })


# ── Register ──

registry.register_many(
    list_skills,
    load_skill,
    match_skills,
    match_skills_semantic,
)
