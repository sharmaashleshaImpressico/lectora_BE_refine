"""Heuristic for detecting knowledge-check / assessment-style titles."""

from __future__ import annotations

import re

_KC_TITLE_RE = re.compile(
    r"\b(knowledge\s*check|quiz|exam(ination)?|assessment|test\s*your\s*knowledge)\b",
    re.IGNORECASE,
)


def is_kc_title(title: str) -> bool:
    """Return True when a title looks like a knowledge-check/assessment entry."""
    return bool(_KC_TITLE_RE.search(title or ""))


__all__ = ["is_kc_title"]
