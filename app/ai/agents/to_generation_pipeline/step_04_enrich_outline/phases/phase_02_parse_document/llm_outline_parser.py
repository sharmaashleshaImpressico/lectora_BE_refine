"""Build A1 raw_sections from A0 llm_to_outline_classification (Generate TO flow)."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.shared_utils.learning_objectives import normalize_learning_objectives
from app.ai.shared_utils.source_documents import (
    resolve_section_source_documents,
)

from ...shared.utils.text_utils import TextUtils

logger = logging.getLogger(__name__)


class LlmOutlineSectionParser:
    """Converts A0 llm_to_outline sections into A1 raw_sections."""

    _LEVEL_RE = re.compile(r"^(\d+(?:\.\d+)*)")

    def sync_extracted_inputs(self, a0_data: dict[str, Any]) -> dict[str, Any]:
        """Align extracted_inputs with A0-generated TO metadata for downstream A1 steps."""
        outline = a0_data.get("llm_to_outline_classification") or {}
        if not outline.get("sections"):
            return a0_data

        extracted = dict(a0_data.get("extracted_inputs", {}) or {})
        course_title = str(outline.get("course_title") or "").strip()
        if course_title:
            extracted["title"] = course_title
        if outline.get("course_id") is not None:
            extracted["course_id"] = str(outline.get("course_id") or "")
        learning_objectives = normalize_learning_objectives(outline.get("learning_objectives"))
        if learning_objectives:
            extracted["learning_objectives"] = learning_objectives

        return {**a0_data, "extracted_inputs": extracted}

    def parse_sections(self, a0_data: dict[str, Any]) -> tuple[list[dict], int, int]:
        """Convert A0 llm_to_outline sections into A1 raw_sections."""
        outline = a0_data.get("llm_to_outline_classification") or {}
        raw_sections = outline.get("sections") or []
        if not raw_sections:
            raise ValueError("llm_to_outline_classification has no sections")

        resolved = self._resolve_para_ranges(
            [item for item in raw_sections if isinstance(item, dict)],
            a0_data,
        )

        sections: list[dict] = []
        kc_count = 0

        for item in resolved:
            section, has_knowledge_check = self._build_section(item, len(sections))
            if section is None:
                continue
            if has_knowledge_check:
                kc_count += 1
            sections.append(section)

        if not sections:
            raise ValueError("No valid sections in llm_to_outline_classification")

        total_words = sum(section["word_count"] for section in sections)
        totals = outline.get("totals") or {}
        if total_words <= 0:
            total_words = self._coerce_int(totals.get("word_count"))

        logger.info(
            "[A1] Loaded %s section(s), %s words, %s KC(s) from A0 llm_to_outline.",
            len(sections),
            total_words,
            kc_count,
        )
        return sections, total_words, kc_count

    def _build_section(
        self,
        item: dict[str, Any],
        section_count: int,
    ) -> tuple[dict[str, Any] | None, bool]:
        title = str(item.get("title") or "").strip()
        if not title:
            return None, False

        paragraphs = self._section_paragraphs(item)
        word_count = self._coerce_int(item.get("word_count"))
        if word_count <= 0 and paragraphs:
            word_count = sum(len(paragraph.split()) for paragraph in paragraphs)

        has_knowledge_check = self._has_knowledge_check(item)
        para_start = item.get("para_idx_start")
        para_end = item.get("para_idx_end")
        if para_start is None:
            para_start = 0
        if para_end is None:
            para_end = int(para_start)

        section = {
            "id": f"s{section_count + 1}_{TextUtils.to_snake(title)}",
            "heading": title,
            "level": self._infer_section_level(title),
            "is_knowledge_check": "knowledge check" in title.lower(),
            "has_knowledge_check": has_knowledge_check,
            "para_start": int(para_start),
            "para_end": int(para_end),
            "paragraphs": paragraphs,
            "word_count": word_count,
            "interactive_elements": list(item.get("interactive_elements") or []),
            "outline_subtopics": self._outline_subtopic_titles(item),
            "outline_content": str(item.get("content") or "").strip(),
            "outline_minutes": item.get("minutes"),
            "outline_credit_hour": item.get("credit_hour"),
            "source_documents": resolve_section_source_documents(item),
        }
        return section, has_knowledge_check

    def _resolve_para_ranges(
        self,
        outline_sections: list[dict[str, Any]],
        a0_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        extracted = a0_data.get("extracted_inputs", {}) or {}
        total_paragraphs = self._coerce_int(extracted.get("total_paragraphs"))
        if total_paragraphs <= 0:
            images = a0_data.get("images") or []
            if images:
                total_paragraphs = max(self._coerce_int(img.get("para_idx")) for img in images) + 1

        working = [dict(section) for section in outline_sections]
        has_a0_para = any(section.get("para_idx_start") is not None for section in working)

        if has_a0_para:
            for section in working:
                start = section.get("para_idx_start")
                end = section.get("para_idx_end")
                if start is not None and end is None:
                    section["para_idx_end"] = start
            unmapped = [section for section in working if section.get("para_idx_start") is None]
            if unmapped and total_paragraphs > 0:
                logger.info(
                    "[A1] %d TO section(s) missing para ranges — proportional fallback only for those.",
                    len(unmapped),
                )
                self._assign_proportional_para_ranges(unmapped, total_paragraphs)
            return working

        mapped_count = sum(
            1
            for section in working
            if section.get("para_idx_start") is not None and section.get("para_idx_end") is not None
        )
        if mapped_count == 0 and total_paragraphs > 0:
            logger.info(
                "[A1] No A0 para ranges — assigning proportional spans across %d paragraph(s).",
                total_paragraphs,
            )
            self._assign_proportional_para_ranges(working, total_paragraphs)
        elif mapped_count == 0:
            for index, section in enumerate(working):
                section["para_idx_start"] = index
                section["para_idx_end"] = index

        return working

    def _assign_proportional_para_ranges(
        self,
        sections: list[dict[str, Any]],
        total_paragraphs: int,
    ) -> None:
        if total_paragraphs <= 0 or not sections:
            return

        weights = [max(self._coerce_int(section.get("word_count")), 1) for section in sections]
        total_weight = sum(weights) or len(sections)
        cursor = 0

        for section, weight in zip(sections, weights):
            span = max(1, round(total_paragraphs * weight / total_weight))
            section["para_idx_start"] = cursor
            section["para_idx_end"] = min(total_paragraphs - 1, cursor + span - 1)
            cursor = int(section["para_idx_end"]) + 1

        sections[-1]["para_idx_end"] = total_paragraphs - 1

    @classmethod
    def _infer_section_level(cls, title: str) -> int:
        match = cls._LEVEL_RE.match((title or "").strip())
        if not match:
            return 1
        return min(max(match.group(1).count("."), 1), 4)

    @staticmethod
    def _coerce_int(value: Any) -> int:
        try:
            if value is None:
                return 0
            if isinstance(value, (int, float)):
                return int(value)
            return int(str(value).strip().replace(",", ""))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _outline_subtopic_titles(section: dict[str, Any]) -> list[str]:
        titles: list[str] = []
        for subtopic in section.get("subtopics") or []:
            if isinstance(subtopic, dict):
                text = str(subtopic.get("title") or subtopic.get("name") or "").strip()
            else:
                text = str(subtopic).strip()
            if text:
                titles.append(text)
        return titles

    def _section_paragraphs(self, section: dict[str, Any]) -> list[str]:
        paragraphs: list[str] = []
        content = str(section.get("content") or "").strip()
        if content:
            paragraphs.append(content)
        paragraphs.extend(self._outline_subtopic_titles(section))
        return paragraphs

    @staticmethod
    def _has_knowledge_check(section: dict[str, Any]) -> bool:
        heading = str(section.get("title") or "")
        if "knowledge check" in heading.lower():
            return True
        for element in section.get("interactive_elements") or []:
            if "knowledge" in str(element).lower():
                return True
        return False


def sync_extracted_inputs_from_llm_outline(a0_data: dict[str, Any]) -> dict[str, Any]:
    return LlmOutlineSectionParser().sync_extracted_inputs(a0_data)


def parse_sections_from_llm_outline(a0_data: dict[str, Any]) -> tuple[list[dict], int, int]:
    return LlmOutlineSectionParser().parse_sections(a0_data)
