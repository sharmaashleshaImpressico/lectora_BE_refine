"""Persistence for immutable per-job course-content versions."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.constants import (
    CONTENT_VERSION_ERROR_MESSAGE_MAX_LENGTH,
    CONTENT_VERSION_STATUS_AVAILABLE,
    CONTENT_VERSION_STATUS_CREATING,
    CONTENT_VERSION_STATUS_FAILED,
)
from app.models.course_generation.course_generation_job.course_content_version import (
    CourseContentVersion,
)
from app.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)

MAX_VERSION_ALLOCATION_RETRIES = 5


class VersionAllocationError(Exception):
    """Raised when a unique version_number could not be reserved after retries."""


class VersionNotFoundError(Exception):
    """Raised when a version id does not exist."""


class InvalidVersionStatusTransitionError(Exception):
    """Raised when a status transition is not allowed."""


class PipelineVersionConflictError(Exception):
    """Raised when Version 1 exists but cannot be treated as a pipeline seed."""


class CourseContentVersionRepository(BaseRepository[CourseContentVersion]):
    """CRUD + allocation helpers for ``course_content_versions``.

    Transaction ownership: this repository **flushes** (and may use SAVEPOINT
    nested transactions for allocation retries) but never ``commit()``s.
    Callers / services own the outer transaction, matching
    ``BaseRepository`` and ``CourseGenerationArtifactService``.
    """

    def __init__(self, db: Session) -> None:
        super().__init__(CourseContentVersion, db)

    def get_latest_available(self, job_id: int | str) -> CourseContentVersion | None:
        """Return the highest AVAILABLE version for the job, or ``None``."""
        return (
            self.db.query(self.model)
            .filter_by(job_id=job_id, status_code=CONTENT_VERSION_STATUS_AVAILABLE)
            .order_by(self.model.version_number.desc())
            .first()
        )

    def get_by_job_and_version(
        self, job_id: int | str, version_number: int
    ) -> CourseContentVersion | None:
        return (
            self.db.query(self.model)
            .filter_by(job_id=job_id, version_number=version_number)
            .first()
        )

    def get_version_one(self, job_id: int | str) -> CourseContentVersion | None:
        return self.get_by_job_and_version(job_id, 1)

    def get_any_version(self, job_id: int | str) -> CourseContentVersion | None:
        """Return any version row for the job (newest first), or ``None``."""
        return (
            self.db.query(self.model)
            .filter_by(job_id=job_id)
            .order_by(self.model.version_number.desc())
            .first()
        )

    def has_any_version(self, job_id: int | str) -> bool:
        return self.get_any_version(job_id) is not None

    def list_available_versions(self, job_id: int | str) -> list[CourseContentVersion]:
        """Return AVAILABLE versions for the job, newest first."""
        return (
            self.db.query(self.model)
            .filter_by(job_id=job_id, status_code=CONTENT_VERSION_STATUS_AVAILABLE)
            .order_by(self.model.version_number.desc())
            .all()
        )

    def max_version_number(self, job_id: int | str) -> int:
        """Highest version_number reserved for the job (any status), or 0."""
        value = (
            self.db.query(func.max(self.model.version_number))
            .filter_by(job_id=job_id)
            .scalar()
        )
        return int(value or 0)

    def register_pipeline_version_one(
        self,
        *,
        job_id: int,
        course_id: int,
        course_run_id: int,
        canonical_json_blob_path: str,
        docx_blob_path: str,
        created_by: str,
    ) -> CourseContentVersion:
        """Idempotently register Version 1 as AVAILABLE from pipeline artifacts.

        Does **not** use ``reserve_next_version`` (which would allocate v2+ on
        retries). Concurrent callers race on UNIQUE(job_id, version_number=1);
        the loser reads and returns the winner's row.
        """
        from app.models.course_generation.course_generation_job.constants import (
            CONTENT_VERSION_SOURCE_PIPELINE,
        )

        existing = self.get_version_one(job_id)
        if existing is not None:
            return self._resolve_existing_pipeline_v1(
                existing,
                course_id=course_id,
                course_run_id=course_run_id,
                canonical_json_blob_path=canonical_json_blob_path,
                docx_blob_path=docx_blob_path,
            )

        now = datetime.now(timezone.utc)
        record = CourseContentVersion(
            job_id=job_id,
            course_id=course_id,
            course_run_id=course_run_id,
            version_number=1,
            status_code=CONTENT_VERSION_STATUS_AVAILABLE,
            source_type=CONTENT_VERSION_SOURCE_PIPELINE,
            canonical_json_blob_path=canonical_json_blob_path,
            docx_blob_path=docx_blob_path,
            created_by=created_by,
            completed_at=now,
            error_message=None,
        )
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
        except IntegrityError as exc:
            if not self._is_version_number_collision(exc):
                raise
            winner = self.get_version_one(job_id)
            if winner is None:
                raise VersionAllocationError(
                    f"Version 1 collision for job '{job_id}' but row not found after retry."
                ) from exc
            return self._resolve_existing_pipeline_v1(
                winner,
                course_id=course_id,
                course_run_id=course_run_id,
                canonical_json_blob_path=canonical_json_blob_path,
                docx_blob_path=docx_blob_path,
            )

        self.db.refresh(record)
        return record

    def _resolve_existing_pipeline_v1(
        self,
        existing: CourseContentVersion,
        *,
        course_id: int,
        course_run_id: int,
        canonical_json_blob_path: str,
        docx_blob_path: str,
    ) -> CourseContentVersion:
        from app.models.course_generation.course_generation_job.constants import (
            CONTENT_VERSION_SOURCE_EDITOR_SAVE,
            CONTENT_VERSION_SOURCE_PIPELINE,
        )

        if int(existing.course_id) != int(course_id) or int(existing.course_run_id) != int(
            course_run_id
        ):
            raise PipelineVersionConflictError(
                f"Version 1 for job '{existing.job_id}' is linked to "
                f"course={existing.course_id}/run={existing.course_run_id}, "
                f"expected course={course_id}/run={course_run_id}."
            )

        if existing.source_type == CONTENT_VERSION_SOURCE_EDITOR_SAVE:
            raise PipelineVersionConflictError(
                f"Version 1 for job '{existing.job_id}' was created by an editor save "
                "and cannot be replaced by a pipeline seed."
            )

        if (
            existing.source_type == CONTENT_VERSION_SOURCE_PIPELINE
            and existing.status_code == CONTENT_VERSION_STATUS_AVAILABLE
        ):
            return existing

        # Repair incomplete pipeline seed (retry after CREATING/FAILED).
        if existing.source_type == CONTENT_VERSION_SOURCE_PIPELINE and existing.status_code in {
            CONTENT_VERSION_STATUS_CREATING,
            CONTENT_VERSION_STATUS_FAILED,
        }:
            previous_status = existing.status_code
            existing.status_code = CONTENT_VERSION_STATUS_AVAILABLE
            existing.canonical_json_blob_path = canonical_json_blob_path
            existing.docx_blob_path = docx_blob_path
            existing.completed_at = datetime.now(timezone.utc)
            existing.error_message = None
            self.db.flush()
            self.db.refresh(existing)
            logger.info(
                "[content_version] Repaired pipeline Version 1 | job_id=%s version_id=%s "
                "previous_status=%s repaired_status=%s json=%s docx=%s",
                existing.job_id,
                existing.id,
                previous_status,
                existing.status_code,
                canonical_json_blob_path,
                docx_blob_path,
            )
            return existing

        raise PipelineVersionConflictError(
            f"Version 1 for job '{existing.job_id}' has unexpected "
            f"source={existing.source_type!r} status={existing.status_code!r}."
        )

    def ensure_pipeline_version_one(
        self,
        *,
        job_id: int,
        course_id: int,
        course_run_id: int,
        canonical_json_blob_path: str,
        docx_blob_path: str,
        created_by: str,
    ) -> CourseContentVersion:
        """Ensure Version 1 exists for known pipeline artifact paths (flush-only).

        Prefer this (or ``register_pipeline_version_one``) over
        ``reserve_next_version`` when seeding the original generation.
        """
        return self.register_pipeline_version_one(
            job_id=job_id,
            course_id=course_id,
            course_run_id=course_run_id,
            canonical_json_blob_path=canonical_json_blob_path,
            docx_blob_path=docx_blob_path,
            created_by=created_by,
        )

    def reserve_next_version(
        self,
        *,
        job_id: int,
        course_id: int,
        course_run_id: int,
        source_type: str,
        created_by: str,
    ) -> CourseContentVersion:
        """Insert the next version as CREATING.

        Concurrency: ``UNIQUE(job_id, version_number)`` is the final safeguard.
        Each attempt computes ``max(version_number) + 1``, inserts inside a
        SAVEPOINT (so a collision does not abort the caller's outer transaction),
        and retries a bounded number of times on uniqueness conflicts only.
        """
        for attempt in range(1, MAX_VERSION_ALLOCATION_RETRIES + 1):
            next_version = self.max_version_number(job_id) + 1
            record = CourseContentVersion(
                job_id=job_id,
                course_id=course_id,
                course_run_id=course_run_id,
                version_number=next_version,
                status_code=CONTENT_VERSION_STATUS_CREATING,
                source_type=source_type,
                created_by=created_by,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(record)
                    self.db.flush()
            except IntegrityError as exc:
                if not self._is_version_number_collision(exc):
                    raise
                logger.warning(
                    "Course content version collision for job %s on attempt %s "
                    "(tried v%s); retrying.",
                    job_id,
                    attempt,
                    next_version,
                )
                continue

            self.db.refresh(record)
            return record

        raise VersionAllocationError(
            f"Could not reserve a unique content version for job '{job_id}' "
            f"after {MAX_VERSION_ALLOCATION_RETRIES} attempts."
        )

    def mark_available(
        self,
        version_id: int,
        *,
        canonical_json_blob_path: str,
        docx_blob_path: str,
    ) -> CourseContentVersion:
        version = self.get_by_id(version_id)
        if version is None:
            raise VersionNotFoundError(f"Course content version '{version_id}' not found.")

        self._require_transition(
            version,
            expected=CONTENT_VERSION_STATUS_CREATING,
            target=CONTENT_VERSION_STATUS_AVAILABLE,
        )

        version.status_code = CONTENT_VERSION_STATUS_AVAILABLE
        version.canonical_json_blob_path = canonical_json_blob_path
        version.docx_blob_path = docx_blob_path
        version.completed_at = datetime.now(timezone.utc)
        version.error_message = None
        self.db.flush()
        self.db.refresh(version)
        return version

    def mark_failed(self, version_id: int, *, error_message: str) -> CourseContentVersion:
        version = self.get_by_id(version_id)
        if version is None:
            raise VersionNotFoundError(f"Course content version '{version_id}' not found.")

        self._require_transition(
            version,
            expected=CONTENT_VERSION_STATUS_CREATING,
            target=CONTENT_VERSION_STATUS_FAILED,
        )

        version.status_code = CONTENT_VERSION_STATUS_FAILED
        version.completed_at = datetime.now(timezone.utc)
        version.error_message = self._truncate_error(error_message)
        self.db.flush()
        self.db.refresh(version)
        return version

    @staticmethod
    def _truncate_error(message: str) -> str:
        text = message or ""
        if len(text) <= CONTENT_VERSION_ERROR_MESSAGE_MAX_LENGTH:
            return text
        return text[: CONTENT_VERSION_ERROR_MESSAGE_MAX_LENGTH - 3] + "..."

    @staticmethod
    def _require_transition(
        version: CourseContentVersion, *, expected: str, target: str
    ) -> None:
        if version.status_code != expected:
            raise InvalidVersionStatusTransitionError(
                f"Cannot transition course content version {version.id} from "
                f"'{version.status_code}' to '{target}' "
                f"(expected current status '{expected}')."
            )

    @staticmethod
    def _is_version_number_collision(exc: IntegrityError) -> bool:
        """Return True only for UNIQUE(job_id, version_number) collisions."""
        raw = str(getattr(exc, "orig", None) or exc).lower()
        constraint = "uq_course_content_versions_job_id_version_number"
        if constraint in raw:
            return True
        # SQLite: UNIQUE constraint failed: course_content_versions.job_id,
        # course_content_versions.version_number
        if "unique" in raw and "version_number" in raw and "course_content_versions" in raw:
            return True
        # Azure SQL / pyodbc often cite the constraint name or columns.
        if "unique" in raw and "version_number" in raw and "job_id" in raw:
            return True
        # FK or other integrity errors must not be retried as collisions.
        if re.search(r"foreign\s*key|not null|check constraint", raw):
            return False
        return False
