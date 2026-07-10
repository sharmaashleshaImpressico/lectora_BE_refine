"""Loads everything `ContentGenerationOrchestrator` needs, given only a `course_run_id`.

This is the DB-facing half of the API<->pipeline wiring described in
CLAUDE.md's "Known Gaps": the worker receives nothing but `{job_id,
course_run_id}` over Service Bus, so this loader reconstructs the full
`ContentGenerationInput` from `courses`, `course_runs`, `course_run_specs`,
and `course_run_inputs`.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.storage.blob_file_resolver import resolve_source_path
from app.models.onboarding.course_run.course_run_input import CourseRunInput
from app.orchestrators.content_generation.orchestrator import ContentGenerationInput
from app.repositories.course_basic.course_repository import CourseRepository
from app.repositories.course_run.course_run_input_repository import CourseRunInputRepository
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.repositories.course_run.course_run_spec_repository import CourseRunSpecRepository

logger = logging.getLogger(__name__)

DOCX_INPUT_TYPES = {"source_document", "study_guide", "docx"}


class CourseRunNotFoundError(Exception):
    """Raised when the course run referenced by a job no longer exists."""


class CourseGenerationDataLoader:
    """Builds a `ContentGenerationInput` purely from persisted DB rows + blob storage."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.course_repository = CourseRepository(db)
        self.course_run_repository = CourseRunRepository(db)
        self.spec_repository = CourseRunSpecRepository(db)
        self.input_repository = CourseRunInputRepository(db)

    def load(self, course_run_id: str, *, output_path: str | None = None) -> ContentGenerationInput:
        course_run = self.course_run_repository.get_by_id(course_run_id)
        if course_run is None:
            raise CourseRunNotFoundError(f"Course run '{course_run_id}' not found.")

        course = self.course_repository.get_by(id=int(course_run.course_id))
        spec = self.spec_repository.get_by(course_run_id=course_run_id)
        inputs = self.input_repository.list_by_course_run(course_run_id)

        learning_objectives = _parse_json_list(spec.learning_objectives_json if spec else None)
        outline = self._load_outline(spec.uploaded_outline_blob_path if spec else None)
        docx_path = self._resolve_docx_path(inputs)

        return ContentGenerationInput(
            run_id=course_run_id,
            course_spec=_spec_to_dict(spec),
            outline=outline,
            course_title=course.title if course else "",
            course_description=(spec.course_scope if spec else None) or "",
            learning_objectives=learning_objectives,
            docx_path=docx_path,
            course_difficulty=(spec.difficulty_level if spec else None) or "intermediate",
            course_audience=(spec.target_audience if spec else None) or "",
            special_instructions=spec.avoid_instructions if spec else None,
            course_config=_spec_to_dict(spec),
            source_file_specs=[_input_to_spec(item) for item in inputs],
            output_path=output_path,
        )

    def _load_outline(self, blob_path: str | None) -> dict:
        if not blob_path:
            return {}
        try:
            local_path = resolve_source_path(blob_path)
            with open(local_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            logger.exception("[course_generation] Failed to load outline from %r", blob_path)
            return {}

    def _resolve_docx_path(self, inputs: list[CourseRunInput]) -> str:
        primary = next((item for item in inputs if item.input_type in DOCX_INPUT_TYPES), None)
        primary = primary or next(
            (item for item in inputs if item.original_filename.lower().endswith(".docx")), None
        )
        if primary is None:
            raise CourseRunNotFoundError(
                "No DOCX source input found for this course run — cannot start content generation."
            )
        return resolve_source_path(primary.blob_path)


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _spec_to_dict(spec) -> dict:
    if spec is None:
        return {}
    return {
        "course_scope": spec.course_scope,
        "duration_hours": spec.duration_hours,
        "difficulty_level": spec.difficulty_level,
        "target_audience": spec.target_audience,
        "learner_experience_level": spec.learner_experience_level,
        "learner_outcomes": spec.learner_outcomes,
        "required_topics_json": spec.required_topics_json,
        "learning_objectives_json": spec.learning_objectives_json,
        "tone": spec.tone,
        "depth": spec.depth,
        "emphasis": spec.emphasis,
        "avoid_instructions": spec.avoid_instructions,
        "include_case_studies": spec.include_case_studies,
        "include_examples": spec.include_examples,
        "course_structure_mode": spec.course_structure_mode,
        "rule_pack_id": spec.rule_pack_id,
        "rule_pack_version": spec.rule_pack_version,
        "outline_notes": spec.outline_notes,
    }


def _input_to_spec(item: CourseRunInput) -> dict:
    return {
        "blob_path": item.blob_path,
        "original_filename": item.original_filename,
        "mime_type": item.mime_type,
        "input_type": item.input_type,
        "source_intent": item.source_intent,
    }
