"""Safe access to python-docx paragraph style names."""

from __future__ import annotations

from typing import Any


def paragraph_style_name(paragraph: Any) -> str:
    """Return the paragraph style name, or an empty string when style metadata is missing."""
    style = getattr(paragraph, "style", None)
    if style is None:
        return ""
    return str(getattr(style, "name", None) or "")
