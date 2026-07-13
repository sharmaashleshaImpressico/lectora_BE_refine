"""Orchestrates versioned editor Save-to-Azure (no HTTP route).

Transaction boundaries (service owns commits; repositories only flush):

1. Read job/course context + load canonical A2 (read-only).
2. Transform snapshot + render DOCX in memory (no DB writes).
3. Lazy-ensure pipeline Version 1 from flat artifacts when missing → ``commit``.
4. ``reserve_next_version`` → ``commit`` so CREATING is durable before uploads.
5. Upload JSON + DOCX (overwrite=False) via artifact storage abstraction.
6. ``mark_available`` → ``commit``.

On failure after reservation: ``rollback`` (if session is dirty/failed), then
``mark_failed`` → ``commit``. Orphan blobs from a partial upload are left in
place for traceability (no delete API in the current storage layer).

Duplicate / concurrent saves: each accepted save allocates a new version number
via UNIQUE(job_id, version_number); no content-hash deduplication.

Lazy Version 1 backfill runs here (not on GET /course) so read paths stay
write-free. First editor save on a legacy completed job becomes Version 2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.constants import (
    CONTENT_VERSION_CREATED_BY_PIPELINE,
    CONTENT_VERSION_SOURCE_EDITOR_SAVE,
    JOB_STATUS_COMPLETED,
)
from app.models.course_generation.course_generation_job.course_content_version import (
    CourseContentVersion,
)
from app.repositories.course_basic.course_repository import CourseRepository
from app.repositories.course_generation.course_content_version_repository import (
    CourseContentVersionRepository,
    PipelineVersionConflictError,
    VersionAllocationError,
)
from app.repositories.course_generation.course_generation_job_repository import (
    CourseGenerationJobRepository,
)
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.artifact_service import (
    ArtifactAlreadyExistsError,
    CourseGenerationArtifactService,
    build_versioned_artifact_paths,
    resolve_course_slug,
)
from app.services.onboarding.course_generation.course_content_service import (
    CourseContentNotFoundError,
    CourseContentService,
)
from app.services.onboarding.course_generation.docx_render_service import (
    DocxRenderService,
    EmptyCourseContentError,
)
from app.services.onboarding.course_generation.editor_course_transformation_service import (
    EditorCourseTransformationError,
    EditorCourseTransformationService,
)
from app.services.onboarding.course_generation.pipeline_version_seed_service import (
    PipelineVersionArtifactsMissingError,
    PipelineVersionSeedService,
)

logger = logging.getLogger(__name__)

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class SaveToAzureError(Exception):
    """Base application error for Save-to-Azure failures."""


class JobNotFoundError(SaveToAzureError):
    """Raised when the course-generation job does not exist."""


class JobNotSavableError(SaveToAzureError):
    """Raised when the job is not in a state that permits editor save."""


class CourseContextNotFoundError(SaveToAzureError):
    """Raised when the related course or course run cannot be resolved."""


class SaveToAzureFailedError(SaveToAzureError):
    """Raised after a reserved version is marked FAILED (or reservation fails)."""

    def __init__(
        self,
        message: str,
        *,
        version_id: int | None = None,
        version_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.version_id = version_id
        self.version_number = version_number


@dataclass(frozen=True)
class SaveToAzureResult:
    """Successful editor-save outcome for Phase 4 API mapping."""

    job_id: int
    course_id: int
    course_run_id: int
    version_id: int
    version_number: int
    canonical_json_blob_path: str
    docx_blob_path: str
    created_at: datetime
    meta: dict[str, Any]
    course_title: str
    container_hint: str = "course-generation-artifacts"


class SaveToAzureService:
    """Application service for versioned editor Save-to-Azure."""

    def __init__(
        self,
        db: Session,
        *,
        content_service: CourseContentService | None = None,
        transformation_service: EditorCourseTransformationService | None = None,
        docx_service: DocxRenderService | None = None,
        artifact_service: CourseGenerationArtifactService | None = None,
        versions: CourseContentVersionRepository | None = None,
        version_seed: PipelineVersionSeedService | None = None,
    ) -> None:
        self.db = db
        self.jobs = CourseGenerationJobRepository(db)
        self.course_runs = CourseRunRepository(db)
        self.courses = CourseRepository(db)
        self.versions = versions or CourseContentVersionRepository(db)
        self.version_seed = version_seed or PipelineVersionSeedService(
            db, versions=self.versions
        )
        self.content = content_service or CourseContentService(db)
        self.transformer = transformation_service or EditorCourseTransformationService()
        self.docx = docx_service or DocxRenderService()
        self.artifacts = artifact_service or CourseGenerationArtifactService(db)

    def save(
        self,
        *,
        job_id: int | str,
        course_snapshot: RenderDocxRequest,
        course_slug: str | None = None,
        created_by: str,
    ) -> SaveToAzureResult:
        context = self._resolve_job_context(job_id)
        logger.info(
            "[save_to_azure] start | job_id=%s course_id=%s course_run_id=%s created_by=%s",
            context["job_id"],
            context["course_id"],
            context["course_run_id"],
            created_by,
        )
        canonical = self.content.load_canonical_state(context["job_id"])

        try:
            transformed = self.transformer.transform(
                course_snapshot,
                existing_a2=canonical.canonical_a2,
                existing_learning_objectives=canonical.learning_objectives,
            )
        except EditorCourseTransformationError:
            raise

        try:
            rendered = self.docx.render_from_a2(
                transformed.canonical_a2,
                transformed.learning_objectives,
            )
        except EmptyCourseContentError as exc:
            raise SaveToAzureError(f"DOCX generation failed: {exc}") from exc
        except Exception as exc:
            raise SaveToAzureError(f"DOCX generation failed: {exc}") from exc

        # Ensure pipeline Version 1 exists before allocating the editor version so
        # the first Save-to-Azure becomes Version 2 (never silently Version 1).
        try:
            seeded = self.version_seed.ensure_pipeline_version_one(
                context["job_id"],
                context["course_id"],
                context["course_run_id"],
                created_by=CONTENT_VERSION_CREATED_BY_PIPELINE,
            )
            self.db.commit()
            logger.info(
                "[save_to_azure] stage=ensure_v1 | job_id=%s version_id=%s "
                "version_number=%s status=ok",
                context["job_id"],
                seeded.id,
                seeded.version_number,
            )
        except PipelineVersionArtifactsMissingError as exc:
            self.db.rollback()
            # Do not fabricate Version 1 from the editor payload.
            if not self.versions.has_any_version(context["job_id"]):
                raise SaveToAzureError(
                    f"Cannot save: original pipeline Version 1 artifacts are "
                    f"incomplete ({exc})."
                ) from exc
            # Versions already exist (e.g. prior editor saves) — continue.
            logger.warning(
                "[save_to_azure] stage=ensure_v1 | job_id=%s status=skipped | %s",
                context["job_id"],
                exc,
            )
        except PipelineVersionConflictError as exc:
            self.db.rollback()
            raise SaveToAzureError(str(exc)) from exc
        except Exception as exc:
            self.db.rollback()
            raise SaveToAzureFailedError(
                f"Failed to ensure pipeline Version 1: {exc}"
            ) from exc

        version: CourseContentVersion | None = None
        try:
            version = self.versions.reserve_next_version(
                job_id=context["job_id"],
                course_id=context["course_id"],
                course_run_id=context["course_run_id"],
                source_type=CONTENT_VERSION_SOURCE_EDITOR_SAVE,
                created_by=created_by,
            )
            self.db.commit()
            logger.info(
                "[save_to_azure] stage=reserve | job_id=%s course_id=%s "
                "course_run_id=%s version_id=%s version_number=%s status=CREATING",
                context["job_id"],
                context["course_id"],
                context["course_run_id"],
                version.id,
                version.version_number,
            )
        except VersionAllocationError:
            self.db.rollback()
            raise
        except Exception as exc:
            self.db.rollback()
            raise SaveToAzureFailedError(
                f"Failed to reserve content version: {exc}"
            ) from exc

        assert version is not None
        version_id = version.id
        version_number = version.version_number

        slug = resolve_course_slug(
            database_title=context["course_title"],
            course_slug_hint=course_slug,
        )
        paths = build_versioned_artifact_paths(
            course_slug=slug,
            job_id=context["job_id"],
            version_number=version_number,
        )

        storage_payload = dict(transformed.canonical_a2)
        storage_payload["learning_objectives"] = list(transformed.learning_objectives)
        storage_payload["course_title"] = transformed.course_title

        try:
            json_bytes = json.dumps(storage_payload, indent=2, default=str).encode("utf-8")
            self.artifacts.upload_bytes_no_overwrite(
                paths.canonical_json_blob_path,
                json_bytes,
                content_type="application/json",
            )
            logger.info(
                "[save_to_azure] stage=upload_json | job_id=%s version_id=%s "
                "version_number=%s path=%s status=ok",
                context["job_id"],
                version_id,
                version_number,
                paths.canonical_json_blob_path,
            )
            self.artifacts.upload_bytes_no_overwrite(
                paths.docx_blob_path,
                rendered.content,
                content_type=_DOCX_CONTENT_TYPE,
            )
            logger.info(
                "[save_to_azure] stage=upload_docx | job_id=%s version_id=%s "
                "version_number=%s path=%s status=ok",
                context["job_id"],
                version_id,
                version_number,
                paths.docx_blob_path,
            )
        except ArtifactAlreadyExistsError as exc:
            logger.error(
                "[save_to_azure] stage=upload | job_id=%s version_id=%s "
                "version_number=%s status=FAILED | %s",
                context["job_id"],
                version_id,
                version_number,
                exc,
            )
            self._fail_version(version_id, str(exc))
            raise SaveToAzureFailedError(
                str(exc),
                version_id=version_id,
                version_number=version_number,
            ) from exc
        except Exception as exc:
            logger.error(
                "[save_to_azure] stage=upload | job_id=%s version_id=%s "
                "version_number=%s status=FAILED | %s",
                context["job_id"],
                version_id,
                version_number,
                exc,
            )
            self._fail_version(version_id, f"Artifact upload failed: {exc}")
            raise SaveToAzureFailedError(
                f"Artifact upload failed: {exc}",
                version_id=version_id,
                version_number=version_number,
            ) from exc

        try:
            available = self.versions.mark_available(
                version_id,
                canonical_json_blob_path=paths.canonical_json_blob_path,
                docx_blob_path=paths.docx_blob_path,
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.error(
                "[save_to_azure] stage=mark_available | job_id=%s version_id=%s "
                "version_number=%s status=FAILED | %s",
                context["job_id"],
                version_id,
                version_number,
                exc,
            )
            self._fail_version(version_id, f"Failed to mark version available: {exc}")
            raise SaveToAzureFailedError(
                f"Failed to mark version available: {exc}",
                version_id=version_id,
                version_number=version_number,
            ) from exc

        logger.info(
            "[save_to_azure] stage=complete | job_id=%s course_id=%s course_run_id=%s "
            "version_id=%s version_number=%s status=AVAILABLE paths=%s / %s",
            context["job_id"],
            context["course_id"],
            context["course_run_id"],
            available.id,
            available.version_number,
            available.canonical_json_blob_path or paths.canonical_json_blob_path,
            available.docx_blob_path or paths.docx_blob_path,
        )
        return SaveToAzureResult(
            job_id=context["job_id"],
            course_id=context["course_id"],
            course_run_id=context["course_run_id"],
            version_id=available.id,
            version_number=available.version_number,
            canonical_json_blob_path=available.canonical_json_blob_path or paths.canonical_json_blob_path,
            docx_blob_path=available.docx_blob_path or paths.docx_blob_path,
            created_at=available.created_at,
            meta=dict(transformed.meta),
            course_title=transformed.course_title,
        )

    def _resolve_job_context(self, job_id: int | str) -> dict[str, Any]:
        job = self.jobs.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(f"Job '{job_id}' not found.")

        if job.status_code != JOB_STATUS_COMPLETED:
            raise JobNotSavableError(
                f"Job '{job_id}' is not savable (status={job.status_code}); "
                f"expected {JOB_STATUS_COMPLETED}."
            )

        course_run = self.course_runs.get_by_id(job.course_run_id)
        if course_run is None:
            raise CourseContextNotFoundError(
                f"Course run '{job.course_run_id}' not found for job '{job_id}'."
            )

        course = self.courses.get_by_id(course_run.course_id)
        if course is None:
            raise CourseContextNotFoundError(
                f"Course '{course_run.course_id}' not found for job '{job_id}'."
            )

        return {
            "job_id": int(job.id),
            "course_run_id": int(course_run.id),
            "course_id": int(course.id),
            "course_title": course.title or "",
            "job_status": job.status_code,
        }

    def _fail_version(self, version_id: int, error_message: str) -> None:
        try:
            self.db.rollback()
        except Exception:
            logger.exception("Rollback before mark_failed failed for version %s", version_id)
        try:
            self.versions.mark_failed(version_id, error_message=error_message)
            self.db.commit()
        except Exception:
            logger.exception(
                "Failed to mark content version %s as FAILED after save error",
                version_id,
            )
            try:
                self.db.rollback()
            except Exception:
                pass


__all__ = [
    "CourseContextNotFoundError",
    "JobNotFoundError",
    "JobNotSavableError",
    "SaveToAzureError",
    "SaveToAzureFailedError",
    "SaveToAzureResult",
    "SaveToAzureService",
]
