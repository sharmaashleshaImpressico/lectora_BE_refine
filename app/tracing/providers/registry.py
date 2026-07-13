"""Lazy provider registry — Langfuse is imported only when selected."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from app.tracing.providers.base import TracingProvider
from app.tracing.providers.jsonl import JsonlTracingProvider

logger = logging.getLogger(__name__)


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_providers(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return ["jsonl"]
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _langfuse_credentials() -> dict[str, str | None]:
    """Resolve Langfuse creds from process env, then pydantic settings (.env)."""
    try:
        from app.core.config import llm_pipeline_settings as _settings
    except Exception:  # pragma: no cover
        _settings = None

    public = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip() or None
    secret = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip() or None
    api_key = (os.getenv("LANGFUSE_API_KEY") or "").strip()
    host = (
        (os.getenv("LANGFUSE_HOST") or "").strip()
        or (os.getenv("LANGFUSE_BASE_URL") or "").strip()
        or None
    )
    environment = (os.getenv("LANGFUSE_ENV") or "").strip() or None

    if _settings is not None:
        public = public or (_settings.langfuse_public_key or "").strip() or None
        secret = secret or (_settings.langfuse_secret_key or "").strip() or None
        api_key = api_key or (_settings.langfuse_api_key or "").strip()
        host = (
            host
            or (_settings.langfuse_host or "").strip()
            or (_settings.langfuse_base_url or "").strip()
            or None
        )
        environment = environment or (_settings.langfuse_env or "").strip() or None

    if (not public or not secret) and api_key:
        for sep in (":", "|", ","):
            if sep in api_key:
                left, right = api_key.split(sep, 1)
                public = public or left.strip() or None
                secret = secret or right.strip() or None
                break

    return {
        "public_key": public,
        "secret_key": secret,
        "host": host,
        "environment": environment,
    }


def _int_env(name: str, default: int | None) -> int | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def build_providers() -> list[TracingProvider]:
    """Construct active providers from ``TRACING_ENABLED`` / ``TRACING_PROVIDERS``."""
    # Prefer process env (tests); fall back to pydantic settings for app runtime.
    try:
        from app.core.config import llm_pipeline_settings as _settings
    except Exception:  # pragma: no cover
        _settings = None

    enabled_env = os.getenv("TRACING_ENABLED")
    if enabled_env is None and _settings is not None:
        enabled = bool(_settings.tracing_enabled)
    else:
        enabled = _truthy(enabled_env, default=True)
    if not enabled:
        return []

    providers_env = os.getenv("TRACING_PROVIDERS")
    if providers_env is None and _settings is not None:
        providers_env = _settings.tracing_providers
    selected = _parse_providers(providers_env)
    providers: list[TracingProvider] = []

    for name in selected:
        if name == "jsonl":
            max_chars = _int_env("JSONL_MAX_CHARS", None)
            if max_chars is None and _settings is not None:
                max_chars = _settings.jsonl_max_chars
            providers.append(JsonlTracingProvider(max_chars=max_chars))
        elif name == "langfuse":
            provider = _try_load_langfuse()
            if provider is not None:
                providers.append(provider)
        else:
            logger.warning("[tracing] unknown provider %r — skipping", name)

    return providers


def _try_load_langfuse() -> TracingProvider | None:
    """Lazily import the Langfuse adapter only when selected."""
    try:
        # Import adapter module only — never import the external package here.
        from app.tracing.providers.langfuse import (  # noqa: PLC0415
            LangfuseTracingProvider,
        )
    except Exception as exc:
        logger.warning("[tracing] Langfuse adapter unavailable: %s", exc)
        return None

    creds = _langfuse_credentials()
    if not creds["public_key"] or not creds["secret_key"]:
        logger.warning(
            "[tracing] Langfuse selected but LANGFUSE_PUBLIC_KEY/SECRET_KEY "
            "are missing — skipping Langfuse provider"
        )
        return None

    try:
        from app.core.config import llm_pipeline_settings as _settings

        max_chars = _int_env("LANGFUSE_MAX_CHARS", _settings.langfuse_max_chars)
    except Exception:
        max_chars = _int_env("LANGFUSE_MAX_CHARS", 50_000)

    try:
        return LangfuseTracingProvider(
            public_key=creds["public_key"],
            secret_key=creds["secret_key"],
            host=creds["host"],
            environment=creds["environment"],
            max_chars=max_chars,
        )
    except Exception as exc:
        logger.warning("[tracing] Langfuse provider init failed: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_providers() -> tuple[TracingProvider, ...]:
    return tuple(build_providers())


def reset_providers_cache() -> None:
    """Test helper — clear cached provider list."""
    get_providers.cache_clear()


def tracing_enabled() -> bool:
    try:
        from app.core.config import llm_pipeline_settings as _settings

        if os.getenv("TRACING_ENABLED") is None:
            return bool(_settings.tracing_enabled)
    except Exception:
        pass
    return _truthy(os.getenv("TRACING_ENABLED"), default=True)
