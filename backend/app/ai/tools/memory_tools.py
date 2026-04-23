"""Memory tools — expose AgentMemory operations to LLM agents (Phase H3).

These tools let agents persist and retrieve cross-session memories.
They resolve the MemoryStore from AgentContext.memory; if no store is
attached, they return a structured error payload.

Scoping convention:
- `scope="global"` → scope_id is ignored; visible to all users + projects.
- `scope="user"` → scope_id = ctx.user_id (inferred if omitted).
- `scope="project"` → scope_id = ctx.project_id (inferred if omitted).
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.framework.context import AgentContext
from app.ai.framework.memory_store import (
    MemoryStore,
    MemoryValidationError,
)
from app.ai.framework.tool_def import ParamDef, tool
from app.ai.framework.tool_registry import registry


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────


def _get_store(ctx: AgentContext) -> MemoryStore | None:
    return getattr(ctx, "memory", None)


def _resolve_scope_id(ctx: AgentContext, scope: str, scope_id: int | None) -> int | None:
    if scope == "global":
        return None
    if scope_id is not None:
        return scope_id
    if scope == "user":
        return ctx.user_id
    if scope == "project":
        return ctx.project_id
    return None


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, **(data if isinstance(data, dict) else {"result": data})},
                      ensure_ascii=False)


# ───────────────────────────────────────────────────────────────────
# Tools
# ───────────────────────────────────────────────────────────────────


@tool(
    name="save_memory",
    description=(
        "持久化一条跨会话记忆。仅当用户明确提出要记住某个事实/偏好时，或在一次任务完成后"
        "发现确有值得长期保留的结论时才调用。"
        " 🚫 禁止在执行类请求（如智能组价 / 批量绑定 / 处理未绑定项）的执行过程中调用，"
        " 这类请求应优先调用 delegate_valuation / delegate_execute 等写入型子 Agent。"
        " 必须同时提供 scope、key、content：scope=global|user|project；key 为短小英文标识（如 'pricing_standard'）；"
        " content 为记忆的完整事实内容。重复 key 会覆盖。importance 1-5。"
    ),
    read_only=False,
    destructive=False,
    concurrency_safe=False,
)
def save_memory(
    ctx: AgentContext,
    *,
    scope: str,
    key: str,
    content: str,
    tags: str = "",
    importance: int = 3,
    scope_id: int | None = None,
) -> str:
    """Save a memory entry. Returns {ok, id, key}."""
    store = _get_store(ctx)
    if store is None:
        return _err("memory store is not configured for this context")
    try:
        sid = _resolve_scope_id(ctx, scope, scope_id)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        mem = store.save(
            scope=scope,  # type: ignore[arg-type]
            scope_id=sid,
            key=key,
            content=content,
            tags=tag_list,
            importance=int(importance),
            created_by_agent="",  # filled by caller via hook if desired
        )
    except MemoryValidationError as e:
        return _err(str(e))
    except Exception as e:  # pragma: no cover — DB errors
        return _err(f"save failed: {e}")

    return _ok({"id": mem.id, "key": mem.key, "scope": mem.scope})


@tool(
    name="search_memory",
    description=(
        "搜索记忆。按 query 文本子串 + tags 过滤，按 importance 降序返回。"
        " scope=global|user|project。limit 默认 10。"
    ),
    read_only=True,
    concurrency_safe=True,
)
def search_memory(
    ctx: AgentContext,
    *,
    scope: str,
    query: str = "",
    tags: str = "",
    min_importance: int = 1,
    limit: int = 10,
    scope_id: int | None = None,
) -> str:
    """Search memories. Returns {ok, matches: [...]}."""
    store = _get_store(ctx)
    if store is None:
        return _err("memory store is not configured for this context")
    try:
        sid = _resolve_scope_id(ctx, scope, scope_id)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        matches = store.search(
            scope=scope,  # type: ignore[arg-type]
            scope_id=sid,
            query=query or None,
            tags=tag_list or None,
            min_importance=int(min_importance),
            limit=int(limit),
        )
    except MemoryValidationError as e:
        return _err(str(e))
    except Exception as e:  # pragma: no cover
        return _err(f"search failed: {e}")

    return _ok({"matches": [m.to_dict() for m in matches], "total": len(matches)})


@tool(
    name="search_memory_semantic",
    description=(
        "语义（embedding）检索记忆。比子串匹配更智能，能找到语义相近的条目。"
        " scope=global|user|project。返回 {matches, scores}，按相似度降序。"
        " 必须传入非空 query，内容应为当前任务、问题或检索语句原文。"
        " min_similarity 默认 0，取值 [-1, 1]；limit 默认 10。"
    ),
    read_only=True,
    concurrency_safe=True,
    params=[
        ParamDef(name="scope", json_type="string", required=True),
        ParamDef(
            name="query",
            json_type="string",
            description="必填。传入当前任务、问题或检索语句，不要留空。",
            required=True,
            aliases=("q", "task", "instruction"),
        ),
        ParamDef(name="limit", json_type="integer", required=False),
        ParamDef(name="min_similarity", json_type="number", required=False),
        ParamDef(name="scope_id", json_type="integer", required=False),
    ],
)
def search_memory_semantic(
    ctx: AgentContext,
    *,
    scope: str,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.0,
    scope_id: int | None = None,
) -> str:
    """Semantic memory search via embeddings."""
    store = _get_store(ctx)
    if store is None:
        return _err("memory store is not configured for this context")
    try:
        sid = _resolve_scope_id(ctx, scope, scope_id)
        scored = store.search_semantic(
            scope=scope,  # type: ignore[arg-type]
            scope_id=sid,
            query=query,
            limit=int(limit),
            min_similarity=float(min_similarity),
        )
    except MemoryValidationError as e:
        return _err(str(e))
    except Exception as e:  # pragma: no cover
        return _err(f"semantic search failed: {e}")

    return _ok({
        "matches": [
            {"score": round(score, 4), **mem.to_dict()}
            for score, mem in scored
        ],
        "total": len(scored),
    })


@tool(
    name="list_memories",
    description="列出 scope 下的所有记忆，按 importance + updated_at 降序。",
    read_only=True,
    concurrency_safe=True,
)
def list_memories(
    ctx: AgentContext,
    *,
    scope: str,
    limit: int = 20,
    scope_id: int | None = None,
) -> str:
    """List memories in a scope."""
    store = _get_store(ctx)
    if store is None:
        return _err("memory store is not configured for this context")
    try:
        sid = _resolve_scope_id(ctx, scope, scope_id)
        items = store.list(
            scope=scope,  # type: ignore[arg-type]
            scope_id=sid,
            limit=int(limit),
        )
    except MemoryValidationError as e:
        return _err(str(e))
    except Exception as e:  # pragma: no cover
        return _err(f"list failed: {e}")

    return _ok({"memories": [m.to_dict() for m in items], "total": len(items)})


@tool(
    name="forget_memory",
    description="按 (scope, key) 删除一条记忆。返回 {ok, deleted:bool}。",
    read_only=False,
    destructive=True,
    concurrency_safe=False,
)
def forget_memory(
    ctx: AgentContext,
    *,
    scope: str,
    key: str,
    scope_id: int | None = None,
) -> str:
    """Delete a memory by (scope, key)."""
    store = _get_store(ctx)
    if store is None:
        return _err("memory store is not configured for this context")
    try:
        sid = _resolve_scope_id(ctx, scope, scope_id)
        deleted = store.delete(
            scope=scope,  # type: ignore[arg-type]
            scope_id=sid,
            key=key,
        )
    except MemoryValidationError as e:
        return _err(str(e))
    except Exception as e:  # pragma: no cover
        return _err(f"delete failed: {e}")

    return _ok({"deleted": deleted, "key": key})


# ───────────────────────────────────────────────────────────────────
# Registration
# ───────────────────────────────────────────────────────────────────

registry.register_many(
    save_memory,
    search_memory,
    search_memory_semantic,
    list_memories,
    forget_memory,
)
