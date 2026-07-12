"""Render-only DOCX generation from an in-memory editor snapshot or A2 payload.

Uses a temporary directory for the existing filesystem-based DOCX builder, then
returns the document bytes. Performs no DB writes, artifact persistence, or
Azure uploads.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.ai.agents.content_generation_agent import render_study_guide
from app.ai.agents.content_generation_agent.models import A2Output
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.editor_snapshot_mapper import (
    EmptyCourseContentError,
    map_editor_snapshot_to_a2,
)

logger = logging.getLogger(__name__)

_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@dataclass(frozen=True)
class RenderedDocx:
    """In-memory DOCX result ready for an HTTP file response."""

    content: bytes
    filename: str
    media_type: str = _DOCX_MEDIA_TYPE


def sanitize_docx_filename(course_title: str) -> str:
    """Build a safe ``*.docx`` download filename from the course title."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (course_title or "").strip()).strip("-")
    slug = slug or "course"
    # Keep filenames reasonably short for Content-Disposition headers.
    slug = slug[:80].rstrip("-") or "course"
    return f"{slug}.docx"


class DocxRenderService:
    """Map an editor snapshot and render a study-guide DOCX in memory."""

    def render(self, payload: RenderDocxRequest) -> RenderedDocx:
        a2_output, learning_objectives = map_editor_snapshot_to_a2(payload)
        return self.render_from_a2(a2_output, learning_objectives)

    def render_from_a2(
        self,
        a2_output: A2Output | dict[str, Any],
        learning_objectives: list[str] | None = None,
    ) -> RenderedDocx:
        """Render DOCX from canonical A2 (+ learning objectives)."""
        if isinstance(a2_output, dict):
            # Drop non-A2 helper keys (e.g. learning_objectives embedded for storage).
            payload = {
                k: v for k, v in a2_output.items() if k != "learning_objectives"
            }
            a2 = A2Output.model_validate(payload)
        else:
            a2 = a2_output

        los = list(learning_objectives or [])
        filename = sanitize_docx_filename(a2.course_title)

        with TemporaryDirectory(prefix="lectora-render-docx-") as temp_dir:
            output_path = Path(temp_dir) / filename
            generated_path = render_study_guide(a2, los, str(output_path))
            docx_bytes = Path(generated_path).read_bytes()

        logger.info(
            "Rendered DOCX from A2 (title=%r, sections=%d, bytes=%d)",
            a2.course_title,
            len(a2.sections),
            len(docx_bytes),
        )
        return RenderedDocx(content=docx_bytes, filename=filename)


__all__ = [
    "DocxRenderService",
    "EmptyCourseContentError",
    "RenderedDocx",
    "sanitize_docx_filename",
]
