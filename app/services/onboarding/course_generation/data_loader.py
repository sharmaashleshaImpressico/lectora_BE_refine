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

from app.ai.rule_pack_config import normalize_rule_family_key
from app.core.storage.blob_file_resolver import BlobResolutionError, resolve_source_path
from app.models.onboarding.course_run.course_run_input import CourseRunInput
from app.orchestrators.content_generation.orchestrator import ContentGenerationInput
from app.repositories.course_basic.course_repository import CourseRepository
from app.repositories.course_run.course_run_input_repository import CourseRunInputRepository
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.repositories.course_run.course_run_spec_repository import CourseRunSpecRepository
from app.services.onboarding.course_generation.artifact_service import ArtifactsBlobClient

logger = logging.getLogger(__name__)

DOCX_INPUT_TYPES = {"source_document", "study_guide", "docx"}


class CourseRunNotFoundError(Exception):
    """Raised when the course run referenced by a job no longer exists."""


class MissingTrainingOutlineError(Exception):
    """Raised when a course run has no usable Training Outline to generate from."""


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
        outline_blob_path = spec.uploaded_outline_blob_path if spec else None
        outline = self._load_outline(outline_blob_path)
        if not outline.get("sections"):
            raise MissingTrainingOutlineError(
                f"Course run '{course_run_id}' has no usable Training Outline — "
                f"uploaded_outline_blob_path={outline_blob_path!r} could not be resolved to an "
                "outline with sections. Either supply `training_outline` when creating the "
                "generation job, or ensure a valid outline blob exists at that path."
            )
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
            # Rule family for content generation/validation — recovered from the
            # rule pack the run was created with (spec.rule_pack_id, persisted by
            # the frontend from the /generate-to response). None (legacy runs /
            # unknown ids) keeps the previous default rule-pack behavior.
            rule_family=_resolve_rule_family(spec, course),
            output_path=output_path,
            # Section Mapper retrieval filters indexed chunks by `course_id`, but the
            # ingestion pipeline stores `course_id` as the *upload folder slug*
            # (document_upload_service sets `course_id = course_id or folder`, and the
            # FE upload path sends no course_id). The numeric course PK therefore never
            # matches any stored chunk and would filter every vector query to zero
            # results. Recover the folder slug the ingestion actually wrote — it is the
            # first path segment of each input's blob_path — so retrieval scopes to the
            # same value both modules agree on.
            course_id=_resolve_ingest_scope_course_id(inputs),
            # Not yet a persisted column on CourseRunSpec — resolves to None until
            # jurisdiction/state is added there; retrieval degrades gracefully.
            jurisdiction=getattr(spec, "jurisdiction", None) if spec else None,
        )

    def _load_outline(self, blob_path: str | None) -> dict:
        if not blob_path:
            return {}
        try:
            local_path = self._resolve_outline_path(blob_path)
            with open(local_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            logger.exception("[course_generation] Failed to load outline from %r", blob_path)
            return {}

        # `generated_to.json` wraps the actual timed outline (with its
        # `sections` key) under a `to` field, alongside sibling metadata
        # (rules, rule_family_key, preview_artifacts, ...). `to_outline.json`
        # (uploaded by the frontend-supplied-TO flow) wraps it under
        # `llm_to_outline` instead. Unwrap either so callers (Section Mapper)
        # see the outline shape they expect.
        if isinstance(data, dict) and "sections" not in data:
            if isinstance(data.get("to"), dict):
                return data["to"]
            if isinstance(data.get("llm_to_outline"), dict):
                return data["llm_to_outline"]
        return data

    @staticmethod
    def _resolve_outline_path(blob_path: str) -> str:
        """Resolve an outline blob, trying the default container then the artifacts one.

        `uploaded_outline_blob_path` historically pointed at the documents
        container; the frontend-supplied-TO flow instead writes `to_outline.json`
        into the `course-generation-artifacts` container. Try the default
        resolution first (local file / documents container) and fall back to
        the artifacts container so both sources work.
        """
        try:
            return resolve_source_path(blob_path)
        except BlobResolutionError:
            return resolve_source_path(blob_path, blob_client=ArtifactsBlobClient())

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


def _resolve_ingest_scope_course_id(inputs: list[CourseRunInput]) -> str | None:
    """Recover the `course_id` value the ingestion pipeline stored on this run's chunks.

    Ingestion writes ``course_id = course_id or folder`` (see
    ``document_upload_service.upload_document``) and the wired FE upload path sends
    no explicit course_id, so the stored value is the sanitized upload folder slug.
    Uploaded blobs live at ``"{folder}/{filename}"``, so the folder is the first
    path segment of each input's ``blob_path``.

    Returns the shared folder slug when all inputs agree on one (the normal case:
    a run's documents share a single course topic). Returns ``None`` when the folder
    can't be determined unambiguously (no blob paths, or inputs spanning multiple
    folders) — retrieval then searches the shared index unfiltered rather than being
    scoped to a wrong value that would match zero chunks.
    """
    folders = {
        (item.blob_path or "").split("/", 1)[0].strip()
        for item in inputs
        if item.blob_path and "/" in item.blob_path
    }
    folders.discard("")
    if len(folders) == 1:
        return next(iter(folders))
    return None


def _resolve_rule_family(spec, course) -> str | None:
    """Recover the run's rule family for content generation/validation.

    Prefers the rule pack persisted on the spec (``rule_pack_id`` accepts a
    pack id or family key); falls back to the course's ``course_type`` label
    so runs created before the frontend sent ``rule_pack_id`` still resolve.
    Returns ``None`` when neither is recognized.
    """
    family = normalize_rule_family_key(spec.rule_pack_id if spec else None)
    if family:
        return family
    return normalize_rule_family_key(course.course_type if course else None)


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
