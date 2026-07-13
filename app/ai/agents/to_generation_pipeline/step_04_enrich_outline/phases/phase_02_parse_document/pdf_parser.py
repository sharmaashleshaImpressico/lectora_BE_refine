"""PDF section parser: reconstructs sections from A0 shared-state data."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.parse_documents.utils.pdf_parser import (
    PDFSourceParser,
)
from app.ai.shared_utils.interactive_elements import collect_interactive_elements

from ...shared.helpers.section_helpers import SectionHelper
from ...shared.utils.text_utils import TextUtils

logger = logging.getLogger(__name__)


class PdfSectionParser:
    """Rebuilds raw sections from A0 heading_tree and the source PDF."""

    def build_paragraph_map(self, pdf_path: str) -> dict[int, str]:
        parser = PDFSourceParser([pdf_path])
        para_map: dict[int, str] = {}
        for doc in parser._docs:
            for block in doc.blocks:
                text = block.text.strip()
                if text:
                    para_map[block.para_idx] = text
        return para_map

    def parse_from_shared_state(
        self,
        a0_data: dict,
        pdf_path: str,
        *,
        build_paragraph_map: Callable[[str], dict[int, str]] | None = None,
    ) -> tuple[list[dict], int, int]:
        extracted: dict = a0_data.get("extracted_inputs", {})
        heading_tree: list[dict] = extracted.get("heading_tree", [])
        paragraph_map_builder = build_paragraph_map or self.build_paragraph_map
        para_map = paragraph_map_builder(pdf_path)
        max_para = max(para_map.keys(), default=0)

        if not heading_tree:
            return self._build_fallback_section(para_map, max_para)

        sections: list[dict] = []
        kc_count = 0

        for index, heading in enumerate(heading_tree):
            section, is_knowledge_check = self._build_section_from_heading(
                heading,
                index,
                heading_tree,
                para_map,
                max_para,
                len(sections),
            )
            if is_knowledge_check and sections:
                sections[-1]["has_knowledge_check"] = True
                kc_count += 1
            sections.append(section)

        total_words = sum(section["word_count"] for section in sections)
        return sections, total_words, kc_count

    def _build_fallback_section(
        self,
        para_map: dict[int, str],
        max_para: int,
    ) -> tuple[list[dict], int, int]:
        all_paras = [para_map[key] for key in sorted(para_map.keys())]
        all_text = " ".join(all_paras)
        word_count = TextUtils.count_words(all_text)
        interactive_elements = collect_interactive_elements(all_paras)
        return (
            [{
                "id": "s1_content",
                "heading": "Content",
                "level": 1,
                "is_knowledge_check": False,
                "has_knowledge_check": False,
                "para_start": 0,
                "para_end": max_para,
                "paragraphs": all_paras,
                "word_count": word_count,
                "interactive_elements": interactive_elements,
            }],
            word_count,
            0,
        )

    def _build_section_from_heading(
        self,
        heading: dict,
        index: int,
        heading_tree: list[dict],
        para_map: dict[int, str],
        max_para: int,
        section_count: int,
    ) -> tuple[dict, bool]:
        para_start: int = heading.get("para_idx", 0)
        para_end: int = (
            heading_tree[index + 1].get("para_idx", para_start) - 1
            if index + 1 < len(heading_tree)
            else max_para
        )
        level: int = SectionHelper.normalize_section_level(heading.get("level", 1))
        heading_text: str = heading.get("text", "")
        is_knowledge_check = "Knowledge Check" in heading_text and level == 3

        body_paras = [
            para_map[paragraph_index]
            for paragraph_index in range(para_start + 1, para_end + 1)
            if paragraph_index in para_map
        ]
        word_count = TextUtils.count_words(" ".join(body_paras))
        interactive_elements = collect_interactive_elements(body_paras)

        section: dict = {
            "id": f"s{section_count + 1}_{TextUtils.to_snake(heading_text)}",
            "heading": heading_text,
            "level": level,
            "is_knowledge_check": is_knowledge_check,
            "has_knowledge_check": False,
            "para_start": para_start,
            "para_end": para_end,
            "paragraphs": body_paras,
            "word_count": word_count,
            "interactive_elements": interactive_elements,
        }
        return section, is_knowledge_check

    @staticmethod
    def append_section_body(current: dict, text: str) -> None:
        """Add a non-heading paragraph to the open section."""
        current["paragraphs"].append(text)
        current["word_count"] += TextUtils.count_words(text)
        current["interactive_elements"] = collect_interactive_elements(
            [text],
            initial=current.get("interactive_elements", []),
        )


def _build_para_map_from_pdf(pdf_path: str) -> dict[int, str]:
    return PdfSectionParser().build_paragraph_map(pdf_path)


def _append_section_body(current: dict, text: str) -> None:
    PdfSectionParser.append_section_body(current, text)
