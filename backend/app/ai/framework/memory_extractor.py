"""MemoryExtractor — auto-sediment conversational facts into Memory (Phase H7).

Closes the learning loop: after an agent run finishes, an extractor analyzes
(instruction, final answer) and proposes a small set of long-lived facts to
persist in the MemoryStore.

## Design

- **ExtractedMemory**: lightweight DTO for a proposed memory entry.
- **MemoryExtractor** ABC: `extract(instruction, answer, ctx) -> list[ExtractedMemory]`.
- **NoopMemoryExtractor**: default for agents that don't want extraction.
- **LLMMemoryExtractor**: uses the configured AI provider to produce a
  JSON list of memory candidates. Has strict safeguards:
    - Bounded max_items (default 3) to prevent memory spam.
    - Scope/key/importance validated before returning.
    - Any provider error → graceful empty result (never breaks caller).

## Typical wiring

```python
class MyOrchestrator(BaseAgent):
    auto_save_memory = True
    memory_extractor = LLMMemoryExtractor(max_items=3)

    def on_result(self, ctx, result):
        if self.auto_save_memory and ctx.memory is not None:
            for item in self.memory_extractor.extract(
                self._last_instruction, result.answer, ctx,
            ):
                ctx.memory.save(
                    scope=item.scope, scope_id=..., key=item.key,
                    content=item.content, importance=item.importance,
                    tags=item.tags, created_by_agent=self.name,
                )
        return result
```
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.ai.framework.context import AgentContext

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# DTO
# ───────────────────────────────────────────────────────────────────


_VALID_SCOPES = {"global", "user", "project"}
_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")


@dataclass
class ExtractedMemory:
    """A memory candidate proposed by an extractor.

    scope_id is resolved by the caller (orchestrator) from ctx.user_id /
    ctx.project_id; extractors should only decide the scope *type*.
    """

    scope: str            # "global" | "user" | "project"
    key: str              # snake_case or kebab-case, 1-100 chars
    content: str
    importance: int = 3   # 1-5
    tags: list[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Validate scope, key, importance, content."""
        if self.scope not in _VALID_SCOPES:
            return False
        if not self.key or not _KEY_RE.match(self.key):
            return False
        if not self.content or not self.content.strip():
            return False
        if not (1 <= self.importance <= 5):
            return False
        return True


# ───────────────────────────────────────────────────────────────────
# ABC
# ───────────────────────────────────────────────────────────────────


class MemoryExtractor(ABC):
    """Abstract memory extractor. Returns a bounded list of candidates."""

    @abstractmethod
    def extract(
        self,
        instruction: str,
        answer: str,
        ctx: "AgentContext",
    ) -> list[ExtractedMemory]:
        """Analyze the exchange and propose memories to save.

        Implementations must:
        - Return an empty list on any failure (never raise).
        - Respect a max_items budget.
        - Only produce valid ExtractedMemory instances.
        """


# ───────────────────────────────────────────────────────────────────
# Noop (default)
# ───────────────────────────────────────────────────────────────────


class NoopMemoryExtractor(MemoryExtractor):
    """Returns no memories. Default — extraction is opt-in."""

    def extract(
        self,
        instruction: str,
        answer: str,
        ctx: "AgentContext",
    ) -> list[ExtractedMemory]:
        return []


# ───────────────────────────────────────────────────────────────────
# LLM-based
# ───────────────────────────────────────────────────────────────────


_EXTRACTION_SYSTEM_PROMPT = """\
你是一个会话总结助手。从下面的「用户指令」和「助手回答」中，提取值得长期保存的事实。

规则：
1. 只提取明显、可验证、未来有用的事实。例子：
   - 用户偏好（"用户偏好所有报价按 m² 展开"）→ scope=user
   - 项目约定（"本项目按广东省 2018 定额计价"）→ scope=project
   - 通用标准（"HKSMM4 扣减大于 0.5m² 的开口"）→ scope=global
2. 不要提取临时信息（本次查询结果、中间计算、下次用不上的数据）。
3. 不确定时宁可少保存（返回空数组）。
4. 最多 {max_items} 条。
5. key 必须 snake_case（仅含小写字母/数字/下划线/连字符），1-100 字符。
6. importance 范围 1-5（一般事实 2-3，关键约定 4-5）。

严格按以下 JSON 格式返回（根对象必须为 memories 字段）：
{{
  "memories": [
    {{
      "scope": "user|project|global",
      "key": "snake_case_key",
      "content": "简短的事实描述",
      "importance": 2,
      "tags": ["tag1", "tag2"]
    }}
  ]
}}

没有任何值得保存的事实时返回 {{"memories": []}}。
"""


class LLMMemoryExtractor(MemoryExtractor):
    """Extract memories by asking the configured AI provider.

    Uses `generate_text` + strict JSON parsing. All failures degrade to
    empty list — extraction never breaks the main agent run.
    """

    def __init__(
        self,
        *,
        max_items: int = 3,
        task_name: str = "memory_extraction",
        provider: Any = None,
    ) -> None:
        if max_items < 1:
            raise ValueError(f"max_items must be >= 1, got {max_items}")
        self._max_items = max_items
        self._task_name = task_name
        self._provider_override = provider

    # ── Public API ──

    def extract(
        self,
        instruction: str,
        answer: str,
        ctx: "AgentContext",
    ) -> list[ExtractedMemory]:
        if not instruction or not answer:
            return []

        provider = self._provider_override or self._load_provider()
        if provider is None or not self._provider_usable(provider):
            return []

        try:
            text = provider.generate_text(
                task=self._task_name,
                messages=[
                    {"role": "system",
                     "content": _EXTRACTION_SYSTEM_PROMPT.format(
                         max_items=self._max_items)},
                    {"role": "user",
                     "content": f"【用户指令】\n{instruction}\n\n【助手回答】\n{answer}"},
                ],
            )
        except Exception as e:  # pragma: no cover — provider failures degrade
            logger.warning("memory extraction failed: %s", e)
            return []

        parsed = self._parse_response(text)
        return parsed[:self._max_items]

    # ── Internals ──

    @staticmethod
    def _load_provider() -> Any:
        try:
            from app.ai.providers import get_ai_provider
        except Exception:  # pragma: no cover — import-time failure
            return None
        try:
            return get_ai_provider()
        except Exception:  # pragma: no cover
            return None

    @staticmethod
    def _provider_usable(provider: Any) -> bool:
        try:
            return bool(provider.is_enabled()) and bool(provider.is_configured())
        except Exception:  # pragma: no cover
            return False

    @staticmethod
    def _parse_response(text: str) -> list[ExtractedMemory]:
        """Parse the LLM's JSON output into validated ExtractedMemory instances.

        Forgiving: handles markdown code fences, trailing prose, slight schema
        drift. Returns [] on any parse failure.
        """
        if not text:
            return []

        payload = _extract_json_object(text)
        if payload is None:
            return []

        items_raw = payload.get("memories") if isinstance(payload, dict) else None
        if not isinstance(items_raw, list):
            return []

        out: list[ExtractedMemory] = []
        for raw in items_raw:
            if not isinstance(raw, dict):
                continue
            try:
                mem = ExtractedMemory(
                    scope=str(raw.get("scope", "")).strip().lower(),
                    key=str(raw.get("key", "")).strip(),
                    content=str(raw.get("content", "")).strip(),
                    importance=int(raw.get("importance", 3)),
                    tags=[str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()],
                )
            except (TypeError, ValueError):
                continue
            if mem.is_valid():
                out.append(mem)
            else:
                logger.debug("rejecting invalid extracted memory: %r", raw)
        return out


# ───────────────────────────────────────────────────────────────────
# JSON extraction helper
# ───────────────────────────────────────────────────────────────────


def _extract_json_object(text: str) -> Any:
    """Best-effort JSON extraction.

    Tries in order:
    1. Whole text as JSON.
    2. Content between ```json ... ``` fences.
    3. Substring starting at the first `{` through the last `}`.

    Returns parsed object or None.
    """
    text = text.strip()
    if not text:
        return None

    # 1. Direct parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Fenced.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. First { to last }.
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return None
