"""Deprecated paragraph-index mapping for A0 Timed Outlines.

Section Mapper now uses Azure AI Search embeddings (matched_chunks).
OutlineSectionMapper is retained only for backward-compatible imports.
"""

from __future__ import annotations

import logging
from typing import Any

from lectora_backend.pipeline.shared_utils.outline_cleanup import strip_para_indices_from_sections

logger = logging.getLogger(__name__)


class OutlineSectionMapper:
    """Strips deprecated para_idx fields from outline sections."""

    @staticmethod
    def map_sections(
        sections: list[dict[str, Any]],
        heading_map: list[tuple[int, str, int, str]],
        total_paragraphs: int,
        paragraphs_by_source: dict[str, int],
        *,
        log_prefix: str,
    ) -> list[dict[str, Any]]:
        del heading_map, total_paragraphs, paragraphs_by_source
        cleaned, removed = strip_para_indices_from_sections(sections)
        if removed:
            logger.info(
                "%s Removed deprecated para_idx fields from %d section(s).",
                log_prefix,
                removed,
            )
        return cleaned
