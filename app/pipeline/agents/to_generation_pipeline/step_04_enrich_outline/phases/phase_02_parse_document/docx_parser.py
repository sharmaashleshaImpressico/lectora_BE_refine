"""DOCX section parser using python-docx."""

from __future__ import annotations

import logging

from docx import Document

from ...shared.utils.text_utils import TextUtils
from .pdf_parser import PdfSectionParser

logger = logging.getLogger(__name__)


class DocxDocumentParser:
    """Parses a DOCX file into structured section dictionaries."""

    def parse(self, docx_path: str) -> tuple[list[dict], int, int]:
        doc = Document(docx_path)
        all_paras = doc.paragraphs
        sections: list[dict] = []
        current: dict | None = None
        kc_count = 0

        for para_idx, paragraph in enumerate(all_paras):
            style = paragraph.style.name
            text = paragraph.text.strip()
            if not text:
                continue

            if style in ("Heading 1", "Heading 2", "Heading 3"):
                current, kc_count = self._handle_heading(
                    text,
                    style,
                    para_idx,
                    sections,
                    current,
                    kc_count,
                )
            elif current is not None:
                PdfSectionParser.append_section_body(current, text)

        if current is not None:
            current["para_end"] = len(all_paras) - 1
            sections.append(current)

        total_words = sum(section["word_count"] for section in sections)
        return sections, total_words, kc_count

    def _handle_heading(
        self,
        text: str,
        style: str,
        para_idx: int,
        sections: list[dict],
        current: dict | None,
        kc_count: int,
    ) -> tuple[dict | None, int]:
        level = int(style[-1])
        is_knowledge_check = "Knowledge Check" in text and level == 3

        if is_knowledge_check and current is not None:
            current["has_knowledge_check"] = True
            kc_count += 1
            PdfSectionParser.append_section_body(current, text)
            return current, kc_count

        if current is not None:
            current["para_end"] = para_idx - 1
            sections.append(current)

        return {
            "id": f"s{len(sections) + 1}_{TextUtils.to_snake(text)}",
            "heading": text,
            "level": level,
            "is_knowledge_check": False,
            "has_knowledge_check": False,
            "para_start": para_idx,
            "para_end": para_idx,
            "paragraphs": [],
            "word_count": 0,
            "interactive_elements": [],
        }, kc_count


def parse_docx_document(docx_path: str) -> tuple[list[dict], int, int]:
    return DocxDocumentParser().parse(docx_path)
