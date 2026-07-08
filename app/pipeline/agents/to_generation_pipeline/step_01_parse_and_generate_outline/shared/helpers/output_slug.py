"""Resolve a filesystem-safe output folder name for a pipeline run."""

from __future__ import annotations

from pathlib import Path

from ..constants.pipeline_config import MULTI_SOURCE_SLUG_PREFIX


class OutputSlugResolver:
    """Derives the per-run output directory slug from source paths."""

    @staticmethod
    def resolve(
        *,
        course_output_slug: str | None,
        docx_paths: list[str],
        pdf_paths: list[str],
        run_id: str,
    ) -> str:
        if course_output_slug:
            return course_output_slug
        if len(docx_paths) == 1:
            return Path(docx_paths[0]).stem
        if len(pdf_paths) == 1 and not docx_paths:
            return Path(pdf_paths[0]).stem
        return f"{MULTI_SOURCE_SLUG_PREFIX}{run_id}"
