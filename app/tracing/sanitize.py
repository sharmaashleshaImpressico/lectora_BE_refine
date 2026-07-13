"""Recursive secret redaction for telemetry payloads."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(authorization\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s\"']+)"),
    re.compile(r"(?i)(password\s*[:=]\s*)([^\s\"']+)"),
    re.compile(r"(?i)(client[_-]?secret\s*[:=]\s*)([^\s\"']+)"),
    re.compile(r"(?i)(AccountKey=)([A-Za-z0-9+/=]+)"),
    re.compile(r"(?i)(SharedAccessSignature=|sig=)([A-Za-z0-9%+\/=_-]+)"),
    re.compile(
        r"(?i)(DefaultEndpointsProtocol=[^;]+;AccountName=[^;]+;AccountKey=)([^;]+)"
    ),
)

# Dict keys whose *values* are always redacted (case/separator insensitive).
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)^("
    r"api[_-]?key|password|passwd|pwd|"
    r"client[_-]?secret|secret|"
    r"authorization|auth|"
    r"(access|refresh|id|bearer|session)?[_-]?token|"
    r"connection[_-]?string|conn[_-]?str|"
    r"account[_-]?key|"
    r"sharedaccesssignature|sas|sig"
    r")$"
)

_REDACTED = "[REDACTED]"
_SANITIZE_FAILED = "[SANITIZE_FAILED]"


def _normalize_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


def _is_sensitive_key(key: Any) -> bool:
    return bool(_SENSITIVE_KEY_RE.match(_normalize_key(key)))


def _redact_string(value: str) -> str:
    out = value
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(
            lambda m: (m.group(1) if m.lastindex and m.lastindex >= 1 else "")
            + _REDACTED,
            out,
        )
    return out


def _sanitize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if _is_sensitive_key(k):
                out[key] = _REDACTED
            else:
                out[key] = _sanitize(v)
        return out
    if isinstance(value, (list, tuple)):
        items = [_sanitize(v) for v in value]
        return type(value)(items) if isinstance(value, tuple) else items
    # Unknown object types — string-redact a safe representation.
    try:
        return _redact_string(repr(value))
    except Exception:
        return _SANITIZE_FAILED


def _fallback_representation(value: Any) -> str:
    try:
        return _redact_string(repr(value))
    except Exception:
        try:
            return _redact_string(str(type(value)))
        except Exception:
            return _SANITIZE_FAILED


def sanitize_secrets(value: Any) -> Any:
    """Deep-copy and recursively redact secrets. Never raises.

    Preserves list/dict structure when possible. On deepcopy / sanitize failure,
    falls back to a redacted string representation so telemetry never blocks
    business execution.
    """
    try:
        return _sanitize(copy.deepcopy(value))
    except Exception:
        logger.warning(
            "[tracing] sanitize deepcopy failed — using safe fallback",
            exc_info=True,
        )
        try:
            return _fallback_representation(value)
        except Exception:
            return _SANITIZE_FAILED


def truncate_text(value: Any, *, max_chars: int | None) -> Any:
    """Truncate string leaves; preserve structure. Never raises.

    ``None`` or non-positive ``max_chars`` means no truncation.
    """
    try:
        if max_chars is None or max_chars <= 0:
            return value
        if isinstance(value, str):
            if len(value) <= max_chars:
                return value
            return value[:max_chars] + "…"
        if isinstance(value, dict):
            return {
                k: truncate_text(v, max_chars=max_chars) for k, v in value.items()
            }
        if isinstance(value, list):
            return [truncate_text(v, max_chars=max_chars) for v in value]
        if isinstance(value, tuple):
            return tuple(truncate_text(v, max_chars=max_chars) for v in value)
        return value
    except Exception:
        logger.warning(
            "[tracing] truncate_text failed — returning safe fallback",
            exc_info=True,
        )
        return _SANITIZE_FAILED
