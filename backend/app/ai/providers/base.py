"""Base interfaces for pluggable AI providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator, Literal, Sequence, TypeVar, TypedDict

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class StructuredMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ToolCallRequest(TypedDict):
    """A tool call returned by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(TypedDict):
    """Result of executing a tool, fed back to the model."""
    tool_call_id: str
    content: str


class ToolsResponse(TypedDict, total=False):
    """Response from generate_with_tools: either text or tool_calls."""
    content: str | None
    tool_calls: list[ToolCallRequest]
    usage: dict[str, Any]


# ───────────────────────────────────────────────────────────────────
# Phase H2: Streaming event types
# ───────────────────────────────────────────────────────────────────


class StreamEvent(TypedDict, total=False):
    """An event yielded by generate_with_tools_stream().

    Event types:
        - "content_delta": incremental text (used for SSE progress).
            Fields: type, text
        - "tool_call": a fully-assembled tool call is ready to execute.
            Fields: type, tool_call (ToolCallRequest)
        - "done": stream finished; final usage metadata available.
            Fields: type, content (full text), usage (dict)
        - "error": provider error; stream ends.
            Fields: type, error (str)
    """
    type: Literal["content_delta", "tool_call", "done", "error"]
    text: str
    tool_call: ToolCallRequest
    content: str | None
    usage: dict[str, Any]
    error: str


class AIProviderError(RuntimeError):
    """Generic provider execution error."""


class AIProviderNotConfiguredError(AIProviderError):
    """Raised when provider is disabled or missing required config."""


class AIProviderNotAvailableError(AIProviderError):
    """Raised when runtime dependency for provider is unavailable."""


class BaseAIProvider(ABC):
    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether provider should be used for requests."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether provider has complete configuration."""

    @abstractmethod
    def generate_structured(
        self,
        *,
        task: str,
        messages: Sequence[StructuredMessage],
        schema_model: type[TModel],
    ) -> TModel:
        """Run model completion and validate response against schema."""

    @abstractmethod
    def generate_text(
        self,
        *,
        task: str,
        messages: Sequence[StructuredMessage],
    ) -> str:
        """Run model completion and return plain text (no schema)."""

    def generate_with_tools(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
    ) -> ToolsResponse:
        """Run model completion with tool definitions. Returns text or tool_calls.

        ``model`` (OPT-4) optionally overrides the provider's default model for
        this single call (e.g. to route to a faster or more powerful tier).
        """
        raise AIProviderNotConfiguredError("Tool calling not supported")

    def supports_streaming(self) -> bool:
        """Whether this provider implements generate_with_tools_stream(). (H2)"""
        return False

    def generate_with_tools_stream(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Run model completion streaming tool calls and content deltas. (H2)

        Yields StreamEvent dicts as chunks arrive. This allows the caller to
        dispatch tool executions the moment each tool_call is assembled,
        overlapping LLM network latency with tool execution time.

        Default implementation raises NotImplementedError — subclasses that
        support streaming must override this and return True from
        supports_streaming().
        """
        raise NotImplementedError("Provider does not implement streaming")


class DisabledAIProvider(BaseAIProvider):
    def is_enabled(self) -> bool:
        return False

    def is_configured(self) -> bool:
        return False

    def generate_structured(
        self,
        *,
        task: str,
        messages: Sequence[StructuredMessage],
        schema_model: type[TModel],
    ) -> TModel:
        raise AIProviderNotConfiguredError("AI provider is disabled")

    def generate_text(
        self,
        *,
        task: str,
        messages: Sequence[StructuredMessage],
    ) -> str:
        raise AIProviderNotConfiguredError("AI provider is disabled")

    def generate_with_tools(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
    ) -> ToolsResponse:
        raise AIProviderNotConfiguredError("AI provider is disabled")

