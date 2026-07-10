"""Business logic for creating and progressing course generation jobs."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.service_bus.publisher import CourseGenerationJobPublisher
from app.models.course_generation.course_generation_job.constants import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
)
from app.models.course_generation.course_generation_job.job import CourseGenerationJob
from app.repositories.course_generation.course_generation_job_repository import CourseGenerationJobRepository
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)


class CourseGenerationJobService:
    """Creates jobs, publishes their queue message, and updates their lifecycle."""

    def __init__(self, db: Session, publisher: CourseGenerationJobPublisher | None = None) -> None:
        self.db = db
        self.repository = CourseGenerationJobRepository(db)
        self.course_run_repository = CourseRunRepository(db)
        self.publisher = publisher or CourseGenerationJobPublisher()

    def create_and_queue(self, course_run_id: str, requested_by: str | None) -> CourseGenerationJob:
        """Persist a new QUEUED job for `course_run_id`, then publish its queue message.

        The job row is committed before publishing so the worker can always
        find it by `job_id`, even if it happens to pick up the message before
        this call returns.
        """
        course_run = self.course_run_repository.get_by_id(course_run_id)
        if course_run is None:
            raise CourseRunNotFoundError(f"Course run '{course_run_id}' not found.")

        job = CourseGenerationJob(
            id=uuid.uuid4().hex,
            course_run_id=course_run_id,
            status_code=JOB_STATUS_QUEUED,
            requested_by=requested_by or "system",
        )
        created = self.repository.create(job)
        self.db.commit()

        logger.info(
            "[course_generation] Job %s queued for course_run %s", created.id, course_run_id
        )
        self.publisher.publish(job_id=created.id, course_run_id=course_run_id)

        return created

    def mark_running(self, job_id: str, *, started_at) -> CourseGenerationJob:
        job = self._get_or_raise(job_id)
        job.status_code = JOB_STATUS_RUNNING
        job.started_at = started_at
        self.db.flush()
        return job

    def mark_completed(self, job_id: str, *, completed_at, shared_state_blob_path: str | None) -> CourseGenerationJob:
        job = self._get_or_raise(job_id)
        job.status_code = JOB_STATUS_COMPLETED
        job.completed_at = completed_at
        if shared_state_blob_path:
            job.shared_state_blob_path = shared_state_blob_path
        self.db.flush()
        return job

    def mark_failed(self, job_id: str, *, completed_at, error_message: str) -> CourseGenerationJob:
        job = self._get_or_raise(job_id)
        job.status_code = JOB_STATUS_FAILED
        job.completed_at = completed_at
        job.error_message = error_message[:4000]
        self.db.flush()
        return job

    def _get_or_raise(self, job_id: str) -> CourseGenerationJob:
        job = self.repository.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Course generation job '{job_id}' not found.")
        return job
