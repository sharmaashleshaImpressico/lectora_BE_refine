"""Accepts a frontend-supplied Training Outline (TO) and enriches it via Step 04.

The frontend may already hold a generated TO in local storage (from an earlier
`/generate-to` call) and resubmit it when kicking off a course generation job,
instead of asking the backend to regenerate it. This module validates that TO
and feeds it into the Step 04 - Enrich Outline pipeline (`A1PipelineRunner`,
run with `prefer_a0_outline=True` so it does not re-parse any source document)
to produce the enriched `CourseSpec`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.models import (
    A0Result,
    A1Status,
    CourseMetadata,
    CourseSpec,
    RequestSpec,
    RuleClassification,
)
from app.ai.agents.to_generation_pipeline.step_04_enrich_outline.orchestrator.pipeline_runner import (
    A1PipelineRunner,
)
from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.finalize_output.utils.normalize_llm_outline_schema import (
    normalize_llm_to_outline_schema,
)
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)


class TrainingOutlineValidationError(ValueError):
    """Raised when a frontend-supplied Training Outline fails validation."""


class TrainingOutlineEnrichmentError(RuntimeError):
    """Raised when Step 04 fails to enrich a validated Training Outline."""


def _coerce_word_count(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def build_to_outline_document(
    *,
    job_id: str,
    course_id: str | None,
    normalized_outline: dict[str, Any],
) -> dict[str, Any]:
    """Wrap a validated, normalized TO into the canonical `to_outline.json` shape.

    `run_id` is the `job_id` (not the course_run_id) — this document is scoped
    to one generation job, matching the `<course_title>/<job_id>/` artifact
    folder it's uploaded into.
    """
    total_word_count = _coerce_word_count(normalized_outline.get("totals", {}).get("word_count"))
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": job_id,
        "course_id": course_id,
        "llm_to_outline": {
            "course_title": normalized_outline.get("course_title", ""),
            "description": normalized_outline.get("description", ""),
            "learning_objectives": normalized_outline.get("learning_objectives", []),
            "sections": normalized_outline.get("sections", []),
            "totals": normalized_outline.get("totals", {}),
            "_parsed_from_uploaded_to": True,
        },
        # No source document is parsed for a frontend-supplied TO, so the
        # only known word count is the outline's own total.
        "total_doc_word_count": total_word_count,
        "to_outline_total_word_count": total_word_count,
    }


def validate_training_outline(training_outline: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a frontend-supplied TO into the canonical schema.

    Returns the normalized outline dict. Raises `TrainingOutlineValidationError`
    if the payload has no recognizable outline structure.
    """
    if not isinstance(training_outline, dict) or not training_outline:
        raise TrainingOutlineValidationError("training_outline must be a non-empty object.")

    try:
        return normalize_llm_to_outline_schema(training_outline, require_sections=True)
    except ValueError as exc:
        raise TrainingOutlineValidationError(str(exc)) from exc


def enrich_training_outline_to_course_spec(
    kernel: Kernel,
    *,
    normalized_outline: dict[str, Any],
    run_id: str,
    course_id: str | None,
    course_title: str,
) -> CourseSpec:
    """Run Step 04 (A1) against an already-generated TO and return the enriched CourseSpec.

    `prefer_a0_outline=True` tells Step 04 to build sections directly from
    `normalized_outline` rather than re-parsing a source document, so no
    `docx_path` is needed.
    """
    a0_result = A0Result(
        request_spec=RequestSpec(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
            course_metadata=CourseMetadata(title=course_title, course_id=course_id),
            rule_classification=RuleClassification(),
        ),
        shared_state={
            "run_id": run_id,
            "llm_to_outline_classification": normalized_outline,
            "extracted_inputs": {
                "title": course_title,
                "course_id": course_id,
                "learning_objectives": normalized_outline.get("learning_objectives", []),
                "total_paragraphs": 0,
            },
            "images": [],
        },
        llm_to_outline=normalized_outline,
    )

    logger.info(
        "[training_outline] Enriching frontend-supplied TO via Step 04 | run_id=%s course_title=%r",
        run_id,
        course_title,
    )

    doc_name = re.sub(
        r"[^\w.\-]+", "_", (course_title or "").strip(), flags=re.UNICODE
    ).strip("._") or "outline_enrichment"

    with traced_workflow(
        "outline_enrichment",
        run_id=run_id,
        session_id=run_id,
        course_run_id=run_id,
        course_id=course_id,
        doc_name=doc_name,
        metadata={"course_title": course_title},
        input_data={"course_title": course_title},
    ):
        output = A1PipelineRunner(kernel).run(
            a0_result,
            docx_path="",
            feedback=None,
            prefer_a0_outline=True,
        )

    if output.status != A1Status.complete or output.course_spec is None:
        raise TrainingOutlineEnrichmentError(
            f"Step 04 enrichment failed for run_id={run_id!r}: {output.error or 'unknown error'}"
        )

    logger.info(
        "[training_outline] Step 04 enrichment complete | run_id=%s sections=%s",
        run_id,
        len(output.course_spec.sections),
    )
    return output.course_spec
