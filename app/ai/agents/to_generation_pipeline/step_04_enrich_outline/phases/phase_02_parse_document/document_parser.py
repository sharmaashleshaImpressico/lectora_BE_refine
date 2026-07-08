"""LangGraph node that parses the source document into raw sections."""

from __future__ import annotations

import logging
import os

from ...nodes.base_node import BaseA1Node
from ...shared.models.state import A1State
from .docx_parser import DocxDocumentParser
from .llm_outline_parser import LlmOutlineSectionParser
from .pdf_parser import PdfSectionParser

logger = logging.getLogger(__name__)


class DocumentParserNode(BaseA1Node):
    """Parses DOCX, PDF, or A0 llm_to_outline into raw_sections."""

    def __init__(
        self,
        docx_parser: DocxDocumentParser | None = None,
        pdf_parser: PdfSectionParser | None = None,
        outline_parser: LlmOutlineSectionParser | None = None,
    ) -> None:
        self._docx_parser = docx_parser or DocxDocumentParser()
        self._pdf_parser = pdf_parser or PdfSectionParser()
        self._outline_parser = outline_parser or LlmOutlineSectionParser()

    def execute(self, state: A1State) -> A1State:
        if state["status"] == "failed":
            return state

        attempt = state.get("retry_count", 0) + 1
        logger.info("[A1] Parsing document (attempt %s)...", attempt)

        try:
            sections, total_words, kc_count = self._parse_sections(state)
            return {
                **state,
                "raw_sections": sections,
                "total_word_count": total_words,
                "kc_count": kc_count,
                "error": None,
            }
        except Exception as exc:
            retry_count = state.get("retry_count", 0)
            return {
                **state,
                "retry_count": retry_count + 1,
                "error": f"parse_document: {exc}",
                "status": "running" if retry_count < 1 else "failed",
            }

    def _parse_sections(self, state: A1State) -> tuple[list[dict], int, int]:
        a0_data = state.get("a0_data", {})

        if state.get("prefer_a0_outline"):
            logger.info(
                "[A1] Generate-TO mode — using A0 llm_to_outline sections "
                "(not re-parsing source document)."
            )
            return self._outline_parser.parse_sections(a0_data)

        docx_path = state["docx_path"]

        if docx_path.lower().endswith(".pdf"):
            logger.info(
                "[A1] PDF source detected — rebuilding sections from "
                "shared-state heading_tree and source PDF."
            )
            sections, total_words, kc_count = self._pdf_parser.parse_from_shared_state(
                a0_data,
                docx_path,
            )
            logger.info(
                "[A1] Reconstructed %s sections, %s words, %s KC(s) from PDF shared state.",
                len(sections),
                total_words,
                kc_count,
            )
            return sections, total_words, kc_count

        if not os.path.exists(docx_path):
            raise FileNotFoundError(f"Source document not found: {docx_path!r}")

        sections, total_words, kc_count = self._docx_parser.parse(docx_path)
        logger.info(
            "[A1] Parsed %s sections, %s words, %s knowledge checks.",
            len(sections),
            total_words,
            kc_count,
        )
        return sections, total_words, kc_count


def parse_document(state: A1State) -> A1State:
    return DocumentParserNode().execute(state)
