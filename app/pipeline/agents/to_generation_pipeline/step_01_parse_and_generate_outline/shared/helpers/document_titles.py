"""Collect and clean document titles from DOCX and PDF sources."""

from __future__ import annotations

import logging

from ...parse_documents.utils.doc_parser import CourseDocParser
from ...parse_documents.utils.pdf_parser import PDFSourceParser
from ..constants.course_titles import GENERIC_COURSE_TITLES

logger = logging.getLogger(__name__)


class TitleCleaner:
    """Filters generic or duplicate course titles."""

    @staticmethod
    def remove_generic_duplicates(titles: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for raw in titles:
            title = raw.strip()
            if not title or title.lower() in GENERIC_COURSE_TITLES:
                continue
            seen[title] = None
        return list(seen)

    @staticmethod
    def is_generic(title: str) -> bool:
        return (title or "").strip().lower() in GENERIC_COURSE_TITLES


class DocumentTitleCollector:
    """Extracts titles from each uploaded source file."""

    def __init__(
        self,
        docx_paths: list[str],
        pdf_paths: list[str],
        *,
        has_docx_parser: bool,
        has_pdf_parser: bool,
        fallback_title: str = "",
    ) -> None:
        self._docx_paths = docx_paths
        self._pdf_paths = pdf_paths
        self._has_docx_parser = has_docx_parser
        self._has_pdf_parser = has_pdf_parser
        self._fallback_title = fallback_title

    def collect_raw_titles(self) -> list[str]:
        titles: list[str] = []
        if self._has_docx_parser:
            titles.extend(self._docx_titles())
        if self._has_pdf_parser:
            titles.extend(self._pdf_titles())
        if not titles and self._fallback_title:
            titles = [self._fallback_title]
        return titles

    def collect_clean_titles(self) -> list[str]:
        return TitleCleaner.remove_generic_duplicates(self.collect_raw_titles())

    def _docx_titles(self) -> list[str]:
        titles: list[str] = []
        for path in self._docx_paths:
            try:
                parser = CourseDocParser(docx_paths=[str(path)])
                title = parser.extract_title()
                if title and title.strip():
                    titles.append(title.strip())
            except Exception:
                logger.debug("DOCX title extraction failed for %s", path, exc_info=True)
        return titles

    def _pdf_titles(self) -> list[str]:
        titles: list[str] = []
        for path in self._pdf_paths:
            try:
                parser = PDFSourceParser([str(path)])
                title = parser.extract_title()
                if title and title.strip():
                    titles.append(title.strip())
            except Exception:
                logger.debug("PDF title extraction failed for %s", path, exc_info=True)
        return titles
