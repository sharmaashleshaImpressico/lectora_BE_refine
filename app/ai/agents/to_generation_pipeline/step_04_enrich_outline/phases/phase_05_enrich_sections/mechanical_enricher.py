"""Mechanical enrichment for Generate TO — no LLM; uses A0 outline subtopics."""

from __future__ import annotations

import re
from typing import Any

from ...shared.helpers.section_helpers import SectionHelper

_STOP_WORDS = frozenset({
    "and", "the", "for", "with", "that", "this", "are", "from", "have", "has",
    "its", "not", "but", "was", "will", "can", "may", "all", "any", "how",
    "their", "who", "which", "when", "what", "into", "than", "then", "they",
})

_LO_MATCH_THRESHOLD = 0.15


class MechanicalSectionEnricher:
    """Builds subtopics and LO mapping from A0 TO without an LLM call."""

    def build(
        self,
        raw_sections: list[dict[str, Any]],
        learning_objectives: list[str],
    ) -> dict[str, dict[str, Any]]:
        lo_maps = self.derive_maps_to_objectives(raw_sections, learning_objectives)
        enrichment: dict[str, dict[str, Any]] = {}

        for section in raw_sections:
            heading = str(section.get("heading") or "")
            if SectionHelper.is_reserved_section(heading):
                enrichment[heading] = {"subtopics": [], "maps_to_objectives": []}
                continue

            subtopics = self._outline_subtopic_titles(section)
            if not subtopics:
                subtopics = [
                    paragraph
                    for paragraph in (section.get("paragraphs") or [])
                    if paragraph
                ][:4]

            enrichment[heading] = {
                "subtopics": subtopics,
                "maps_to_objectives": lo_maps.get(heading, []),
            }

        return enrichment

    def derive_maps_to_objectives(
        self,
        raw_sections: list[dict[str, Any]],
        learning_objectives: list[str],
    ) -> dict[str, list[int]]:
        if not learning_objectives:
            return {
                str(section.get("heading") or ""): []
                for section in raw_sections
            }

        content_sections = [
            section
            for section in raw_sections
            if not SectionHelper.is_reserved_section(str(section.get("heading") or ""))
        ]
        assignments: dict[str, list[int]] = {}
        best_for_lo: dict[int, tuple[float, str]] = {}

        for section in raw_sections:
            heading = str(section.get("heading") or "")
            matched_indices: list[int] = []
            for index, learning_objective in enumerate(learning_objectives):
                score = self._score_lo_against_section(section, learning_objective)
                if score >= _LO_MATCH_THRESHOLD:
                    matched_indices.append(index)
                previous_score, _ = best_for_lo.get(index, (0.0, ""))
                if score > previous_score:
                    best_for_lo[index] = (score, heading)
            assignments[heading] = matched_indices

        for index in range(len(learning_objectives)):
            already_mapped = any(
                index in assignments.get(str(section.get("heading") or ""), [])
                for section in raw_sections
            )
            if already_mapped:
                continue
            _, best_heading = best_for_lo.get(index, (0.0, ""))
            if best_heading:
                assignments.setdefault(best_heading, []).append(index)
            elif content_sections:
                fallback_heading = str(
                    content_sections[index % len(content_sections)].get("heading") or ""
                )
                assignments.setdefault(fallback_heading, []).append(index)

        return {
            heading: sorted(dict.fromkeys(indices))
            for heading, indices in assignments.items()
        }

    @staticmethod
    def _outline_subtopic_titles(section: dict[str, Any]) -> list[str]:
        titles: list[str] = []
        for subtopic in section.get("outline_subtopics") or []:
            if isinstance(subtopic, dict):
                text = str(subtopic.get("title") or subtopic.get("name") or "").strip()
            else:
                text = str(subtopic).strip()
            if text:
                titles.append(text)
        return titles[:4]

    @staticmethod
    def _keywords(text: str) -> set[str]:
        return {
            word
            for word in re.findall(r"[a-z]{3,}", text.lower())
            if word not in _STOP_WORDS
        }

    def _section_text_blob(self, section: dict[str, Any]) -> str:
        parts = [str(section.get("heading") or "")]
        parts.append(str(section.get("outline_content") or ""))
        parts.extend(str(subtopic) for subtopic in self._outline_subtopic_titles(section))
        parts.extend(str(paragraph) for paragraph in (section.get("paragraphs") or []) if paragraph)
        return " ".join(parts)

    def _score_lo_against_section(self, section: dict[str, Any], learning_objective: str) -> float:
        section_keywords = self._keywords(self._section_text_blob(section))
        lo_keywords = self._keywords(learning_objective)
        if not lo_keywords:
            return 0.0
        return len(section_keywords & lo_keywords) / len(lo_keywords)


def build_mechanical_enrichment(
    raw_sections: list[dict[str, Any]],
    learning_objectives: list[str],
) -> dict[str, dict[str, Any]]:
    return MechanicalSectionEnricher().build(raw_sections, learning_objectives)


def derive_maps_to_objectives(
    raw_sections: list[dict[str, Any]],
    learning_objectives: list[str],
) -> dict[str, list[int]]:
    return MechanicalSectionEnricher().derive_maps_to_objectives(raw_sections, learning_objectives)
