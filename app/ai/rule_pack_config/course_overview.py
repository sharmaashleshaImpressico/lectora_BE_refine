"""Course overview/description resolution for content-generation output."""

from __future__ import annotations

from typing import Any


def resolve_course_overview_for_output(context: dict[str, Any]) -> str:
    """Return the user-authored course description to render, if any."""
    return str(context.get("course_description") or "").strip()


__all__ = ["resolve_course_overview_for_output"]
