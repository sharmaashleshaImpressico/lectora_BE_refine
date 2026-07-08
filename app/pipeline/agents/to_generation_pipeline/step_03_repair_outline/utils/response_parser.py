"""Parse and validate LLM refinement responses."""

from __future__ import annotations

import json
import re
from typing import Any


class RefinementResponseParser:
    """Extracts a repaired outline JSON object from raw LLM output."""

    _FENCE_OPEN_PATTERN = re.compile(r"^```[a-zA-Z]*\n?")
    _FENCE_CLOSE_PATTERN = re.compile(r"\n?```$")

    def parse_outline(self, raw: str) -> dict[str, Any] | None:
        """Return the parsed outline dict when valid, otherwise None."""
        repaired = json.loads(self.strip_markdown_fences(raw))
        if not isinstance(repaired, dict) or not repaired.get("sections"):
            return None
        return repaired

    @classmethod
    def strip_markdown_fences(cls, raw: str) -> str:
        stripped = raw.strip()
        if not stripped.startswith("```"):
            return stripped
        stripped = cls._FENCE_OPEN_PATTERN.sub("", stripped)
        return cls._FENCE_CLOSE_PATTERN.sub("", stripped.rstrip())
