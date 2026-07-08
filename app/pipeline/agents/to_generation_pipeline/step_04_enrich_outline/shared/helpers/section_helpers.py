"""Shared section-classification helpers for A1."""

from __future__ import annotations

import re
from typing import Any


class SectionHelper:
    """Classifies section headings and normalizes section levels."""

    _RESERVED_SECTION_RE = re.compile(
        r"^\s*(\d+(\.\d+)*\s+)?"
        r"(overview|learning\s+objectives?|learning\s+outcomes?|course\s+objectives?|"
        r"summary|assessment|introduction)\s*$",
        re.IGNORECASE,
    )

    @classmethod
    def is_reserved_section(cls, heading: str) -> bool:
        """Return True if heading names a structural section that must not hold subtopics."""
        return bool(cls._RESERVED_SECTION_RE.match(heading.strip()))

    @classmethod
    def normalize_section_level(cls, level: Any) -> int:
        """Clamp section levels into the schema-supported range (1..4)."""
        try:
            value = int(level)
        except (TypeError, ValueError):
            value = 1
        return max(1, min(value, 4))


def _is_reserved_section(heading: str) -> bool:
    return SectionHelper.is_reserved_section(heading)


def _normalize_section_level(level: Any) -> int:
    return SectionHelper.normalize_section_level(level)
