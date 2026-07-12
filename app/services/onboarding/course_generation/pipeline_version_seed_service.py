"""Idempotent Version 1 seeding for pipeline output (and lazy backfill).

Version numbering (per job):

* Version 1 = original pipeline-generated course (PIPELINE)
* Version 2+ = editor Save-to-Azure (EDITOR_SAVE)

Retry / idempotency for pipeline seed:

* Missing Version 1 → create AVAILABLE PIPELINE from successful artifact paths.
* AVAILABLE PIPELINE Version 1 with matching course/run → no-op success.
* PIPELINE Version 1 in CREATING/FAILED → repair paths/status to AVAILABLE.
* EDITOR_SAVE Version 1 → conflict (never silently replace editor history).
* Concurrent inserts → UNIQUE(job_id, version_number=1); loser returns winner.

Lazy backfill (``ensure_pipeline_version_one``) references existing flat
pipeline artifact paths; it does not copy blobs into ``v1/``.

Transaction ownership: this service may ``commit`` when called from Save /
pipeline completion. The repository only flushes.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_STUDY_GUIDE,
    CONTENT_VERSION_CREATED_BY_PIPELINE,
    CONTENT_VERSION_STATUS_AVAILABLE,
)
from app.models.course_generation.course_generation_job.course_content_version import (
    CourseContentVersion,
)
from app.repositories.course_generation.course_content_version_repository import (
    CourseContentVersionRepository,
    PipelineVersionConflictError,
)
from app.repositories.course_generation.course_generation_job_artifact_repository import (
    CourseGenerationJobArtifactRepository,
)

logger = logging.getLogger(__name__)


class PipelineVersionArtifactsMissingError(Exception):
    """Raised when Version 1 cannot be seeded because required artifacts are absent."""


class PipelineVersionSeedService:
    """Registers / backfills pipeline Version 1 from persisted artifacts."""

    def __init__(
        self,
        db: Session,
        *,
        versions: CourseContentVersionRepository | None = None,
        artifacts: CourseGenerationJobArtifactRepository | None = None,
    ) -> None:
        self.db = db
        self.versions = versions or CourseContentVersionRepository(db)
        self.artifacts = artifacts or CourseGenerationJobArtifactRepository(db)

    def register_from_paths(
        self,
        *,
        job_id: int | str,
        course_id: int,
        course_run_id: int,
        canonical_json_blob_path: str,
        docx_blob_path: str,
        created_by: str | None = None,
    ) -> CourseContentVersion:
        """Seed Version 1 from known successful pipeline artifact paths (flush-only)."""
        return self.versions.register_pipeline_version_one(
            job_id=int(job_id),
            course_id=int(course_id),
            course_run_id=int(course_run_id),
            canonical_json_blob_path=canonical_json_blob_path,
            docx_blob_path=docx_blob_path,
            created_by=(created_by or CONTENT_VERSION_CREATED_BY_PIPELINE).strip()
            or CONTENT_VERSION_CREATED_BY_PIPELINE,
        )

    def ensure_pipeline_version_one(
        self,
        job_id: int | str,
        course_id: int,
        course_run_id: int,
        *,
        created_by: str | None = None,
    ) -> CourseContentVersion:
        """Lazy-backfill Version 1 from flat pipeline artifacts when missing.

        1. If Version 1 already exists as AVAILABLE, return it (any source).
        2. Otherwise locate ``course_content.json`` + ``study_guide.docx`` artifacts.
        3. Register Version 1 as AVAILABLE / PIPELINE pointing at those paths.
        4. Concurrent callers share UNIQUE(job_id, 1); return the winning row.

        Does not fabricate Version 1 when either required artifact is missing.
        """
        job_id_int = int(job_id)
        course_id_int = int(course_id)
        course_run_id_int = int(course_run_id)

        existing = self.versions.get_version_one(job_id_int)
        if (
            existing is not None
            and existing.status_code == CONTENT_VERSION_STATUS_AVAILABLE
        ):
            if int(existing.course_id) != course_id_int or int(
                existing.course_run_id
            ) != course_run_id_int:
                raise PipelineVersionConflictError(
                    f"Version 1 for job '{job_id_int}' is linked to "
                    f"course={existing.course_id}/run={existing.course_run_id}, "
                    f"expected course={course_id_int}/run={course_run_id_int}."
                )
            return existing

        json_path, docx_path = self._resolve_pipeline_artifact_paths(job_id_int)
        identity = (
            (created_by or CONTENT_VERSION_CREATED_BY_PIPELINE).strip()
            or CONTENT_VERSION_CREATED_BY_PIPELINE
        )
        record = self.versions.register_pipeline_version_one(
            job_id=job_id_int,
            course_id=course_id_int,
            course_run_id=course_run_id_int,
            canonical_json_blob_path=json_path,
            docx_blob_path=docx_path,
            created_by=identity,
        )
        logger.info(
            "[pipeline_version_seed] Ensured Version 1 for job=%s json=%s docx=%s",
            job_id_int,
            json_path,
            docx_path,
        )
        return record

    def _resolve_pipeline_artifact_paths(self, job_id: int) -> tuple[str, str]:
        artifacts = self.artifacts.list_by_job(job_id)
        by_type = {a.artifact_type: a for a in artifacts}

        content = by_type.get(ARTIFACT_TYPE_COURSE_CONTENT)
        study_guide = by_type.get(ARTIFACT_TYPE_STUDY_GUIDE)

        missing: list[str] = []
        if content is None or not (content.blob_path or "").strip():
            missing.append("course_content.json")
        if study_guide is None or not (study_guide.blob_path or "").strip():
            missing.append("study_guide.docx")

        if missing:
            raise PipelineVersionArtifactsMissingError(
                f"Cannot seed Version 1 for job '{job_id}': missing pipeline "
                f"artifact(s): {', '.join(missing)}."
            )

        assert content is not None and study_guide is not None
        return str(content.blob_path), str(study_guide.blob_path)


__all__ = [
    "PipelineVersionArtifactsMissingError",
    "PipelineVersionConflictError",
    "PipelineVersionSeedService",
]
