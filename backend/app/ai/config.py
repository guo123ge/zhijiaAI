"""AI settings loaded from environment variables (with multi-provider support).

Resolution order:
1. Per-provider env vars: AI_{PROVIDER}_API_KEY / AI_{PROVIDER}_BASE_URL / AI_{PROVIDER}_MODEL
2. Generic fallback: AI_API_KEY / AI_BASE_URL / AI_MODEL
3. Built-in defaults (per provider)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Supported model providers that the user can configure.
AI_SUPPORTED_PROVIDERS = ["deepseek", "qwen", "kimi", "glm", "openai"]

# Valid values for AI_PROVIDER env var (includes "disabled").
AI_VALID_PROVIDERS = {"disabled"} | set(AI_SUPPORTED_PROVIDERS)

# Default base_url per provider (used when none is supplied).
_DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
}

# Default model name per provider.
_DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "kimi": "kimi-k2.5",
    "glm": "glm-4",
    "openai": "gpt-4o-mini",
}


def _to_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _to_float(raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AISettings:
    provider: str = "disabled"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    # OPT-4: optional per-tier overrides; fall back to ``model`` when None.
    model_fast: str | None = None
    model_powerful: str | None = None
    timeout_seconds: float = 180.0
    enable_audit_logs: bool = False

    def is_enabled(self) -> bool:
        return self.provider != "disabled" and self.is_configured()

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    def resolve_model_for_tier(self, tier_level: int) -> str:
        """OPT-4: Map tier level (1=fast / 2=balanced / 3=powerful) → model name.

        Falls back to ``self.model`` (the balanced default) when a tier override
        is not configured. Callers can safely pass level=2 to get the default.
        """
        if tier_level <= 1 and self.model_fast:
            return self.model_fast
        if tier_level >= 3 and self.model_powerful:
            return self.model_powerful
        return self.model or ""


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def get_ai_settings() -> AISettings:
    """Build runtime AISettings by resolving per-provider env vars → generic fallback."""
    provider = _env("AI_PROVIDER", "disabled").lower()
    if provider not in AI_VALID_PROVIDERS:
        provider = "disabled"

    upper = provider.upper()

    # Per-provider env takes precedence, then generic env, then built-in default.
    api_key = (
        _env(f"AI_{upper}_API_KEY")
        or _env("AI_API_KEY")
        or None
    )
    base_url = (
        _env(f"AI_{upper}_BASE_URL")
        or _env("AI_BASE_URL")
        or _DEFAULT_BASE_URLS.get(provider, "")
        or None
    )
    model = (
        _env(f"AI_{upper}_MODEL")
        or _env("AI_MODEL")
        or _DEFAULT_MODELS.get(provider, "")
        or None
    )
    # OPT-4: Optional per-tier overrides. Per-provider takes precedence.
    # e.g. AI_DEEPSEEK_MODEL_FAST, AI_MODEL_POWERFUL.
    model_fast = (
        _env(f"AI_{upper}_MODEL_FAST")
        or _env("AI_MODEL_FAST")
        or None
    )
    model_powerful = (
        _env(f"AI_{upper}_MODEL_POWERFUL")
        or _env("AI_MODEL_POWERFUL")
        or None
    )

    timeout_seconds = _to_float(os.getenv("AI_TIMEOUT_SECONDS"), 180.0)
    enable_audit_logs = _to_bool(os.getenv("AI_ENABLE_AUDIT_LOGS"), default=False)

    return AISettings(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        model_fast=model_fast,
        model_powerful=model_powerful,
        timeout_seconds=timeout_seconds,
        enable_audit_logs=enable_audit_logs,
    )


# ───────────────────────────────────────────────────────────────────
# Phase H8: Memory / Embedding production settings
# ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MemorySettings:
    """Runtime settings for the Memory + Embedding subsystem."""

    # "" = auto-detect (openai if key available, else hash fallback)
    # "hash" / "openai" = force
    embedding_backend: str
    # Default for orchestrate API when request doesn't override it.
    auto_save_memory_default: bool
    # Extractor budget (max memory items persisted per run).
    memory_extractor_max_items: int


def get_memory_settings() -> MemorySettings:
    """Build MemorySettings from environment variables."""
    backend = _env("EMBEDDING_BACKEND", "").strip().lower()
    if backend not in ("", "hash", "openai"):
        backend = ""

    max_items_raw = _env("AI_MEMORY_EXTRACTOR_MAX_ITEMS", "").strip()
    try:
        max_items = int(max_items_raw) if max_items_raw else 3
    except ValueError:
        max_items = 3
    if max_items < 1:
        max_items = 1

    return MemorySettings(
        embedding_backend=backend,
        auto_save_memory_default=_to_bool(
            os.getenv("AI_AUTO_SAVE_MEMORY"), default=False
        ),
        memory_extractor_max_items=max_items,
    )


def get_ai_settings_payload() -> dict[str, Any]:
    """Return the full multi-provider config dict used by the settings API."""
    provider = _env("AI_PROVIDER", "disabled").lower()
    if provider not in AI_VALID_PROVIDERS:
        provider = "disabled"

    providers: dict[str, dict[str, str]] = {}
    for p in AI_SUPPORTED_PROVIDERS:
        upper = p.upper()
        providers[p] = {
            "api_key": _env(f"AI_{upper}_API_KEY") or _env("AI_API_KEY") if p == provider else _env(f"AI_{upper}_API_KEY"),
            "base_url": _env(f"AI_{upper}_BASE_URL") or _DEFAULT_BASE_URLS.get(p, ""),
            "model": _env(f"AI_{upper}_MODEL") or _DEFAULT_MODELS.get(p, ""),
        }

    return {
        "provider": provider,
        "timeout_seconds": _to_float(os.getenv("AI_TIMEOUT_SECONDS"), 180.0),
        "enable_audit_logs": _to_bool(os.getenv("AI_ENABLE_AUDIT_LOGS"), default=False),
        "providers": providers,
    }

