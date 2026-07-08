"""Section 1 learning-objective detection and normalization."""

from __future__ import annotations

import copy
import re
from typing import Any

from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.config import (
    COMPRESSED_LO_PREFIX,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementIssue,
)


class Section1IssueDetector:
    """Identifies when S1 feedback relates to Section 1 learning objectives."""

    @staticmethod
    def _field_and_message(issue: Any) -> tuple[str, str]:
        field = str(getattr(issue, "field", None) or issue.get("field", "")).lower()
        message = str(getattr(issue, "message", None) or issue.get("message", "")).lower()
        return field, message

    @classmethod
    def _matches_section_index(cls, field: str, message: str) -> bool:
        if "sections[1]" not in field and "sections[0]" not in field:
            return False
        return "subtopic" in field or "learning objective" in message

    @classmethod
    def needs_lo_repair_directive(cls, issues: list[S1RefinementIssue]) -> bool:
        """Return True when the LLM user message should include a Section 1 LO directive."""
        for issue in issues:
            field, message = cls._field_and_message(issue)
            if cls._matches_section_index(field, message):
                return True
            if "section 1" in message and (
                "learning objective" in message or "compressed" in message
            ):
                return True
            if "first section" in message and "learning objective" in message:
                return True
        return False

    @classmethod
    def targets_normalization(cls, issues: list[Any]) -> bool:
        """Return True when post-LLM normalization should rewrite Section 1 subtopics."""
        for issue in issues:
            field, message = cls._field_and_message(issue)
            if cls._matches_section_index(field, message):
                return True
            if "section 1" in message and (
                "learning objective" in message
                or "compressed" in message
                or "repeat" in message
            ):
                return True
            if "learning objective" in message and "first section" in message:
                return True
        return False


class Section1LearningObjectiveNormalizer:
    """Ensures each learning objective appears once in Section 1 subtopics."""

    def normalize(
        self,
        outline: dict[str, Any],
        *,
        issues: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Ensure each learning objective appears once in Section 1 subtopics."""
        if issues is not None and not Section1IssueDetector.targets_normalization(issues):
            return outline

        objectives = self._extract_objectives(outline)
        if not objectives:
            return outline

        sections = outline.get("sections") or []
        if not sections:
            return outline

        objective_keys = {self._normalize_key(objective) for objective in objectives}
        raw_subtopics = list((sections[0].get("subtopics") or []))

        removed_compressed = False
        non_lo: list[Any] = []
        seen_lo_keys: set[str] = set()

        for entry in raw_subtopics:
            title = self._subtopic_title(entry)
            key = self._normalize_key(title)
            if self._is_compressed_lo_subtopic(title):
                removed_compressed = True
                continue
            if key in objective_keys:
                if key in seen_lo_keys:
                    continue
                seen_lo_keys.add(key)
                continue
            non_lo.append(entry)

        if issues is None and not removed_compressed:
            return outline

        repaired = copy.deepcopy(outline)
        first_section = dict(sections[0])
        first_section["subtopics"] = list(objectives) + non_lo
        repaired["sections"] = [first_section, *sections[1:]]
        return repaired

    @staticmethod
    def _normalize_key(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    @staticmethod
    def _subtopic_title(entry: Any) -> str:
        if isinstance(entry, dict):
            return str(entry.get("title") or "").strip()
        return str(entry or "").strip()

    @classmethod
    def _is_compressed_lo_subtopic(cls, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if COMPRESSED_LO_PREFIX.search(stripped):
            return True
        lowered = stripped.lower()
        if "learning objective" not in lowered:
            return False
        if ":" not in stripped:
            return False
        return stripped.count(",") >= 2 or len(stripped) > 100

    @staticmethod
    def _extract_objectives(outline: dict[str, Any]) -> list[str]:
        return [
            str(item).strip()
            for item in (outline.get("learning_objectives") or [])
            if str(item).strip()
        ]


_default_normalizer = Section1LearningObjectiveNormalizer()


def normalize_section1_learning_objectives(
    outline: dict[str, Any],
    *,
    issues: list[Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper for Section1LearningObjectiveNormalizer."""
    return _default_normalizer.normalize(outline, issues=issues)
