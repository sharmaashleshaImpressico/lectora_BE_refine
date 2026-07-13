"""Resolve which source documents a TO section should be grounded against."""

from __future__ import annotations

from typing import Any


def resolve_section_source_documents(to_sec: dict[str, Any]) -> list[str]:
    """Return the source file references (paths/blob names) for a TO section, if any."""
    for key in ("source_documents", "source_files"):
        values = to_sec.get(key)
        if isinstance(values, list) and values:
            return [str(v).strip() for v in values if str(v).strip()]
    return []


__all__ = ["resolve_section_source_documents"]
