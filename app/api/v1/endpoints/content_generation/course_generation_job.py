"""HTTP routes for kicking off and polling course generation jobs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.auth.dependencies import require_valid_token
from app.repositories.course_generation.course_generation_job_artifact_repository import (
    CourseGenerationJobArtifactRepository,
)
from app.repositories.course_generation.course_generation_validation_run_repository import (
    CourseGenerationValidationRunRepository,
)
from app.schemas.course_generation_job.job import (
    CourseGenerationJobData,
    CourseGenerationJobResponse,
    GenerateCourseRequest,
)
from app.schemas.course_generation_job.job_artifact import (
    CourseGenerationJobArtifactData,
)
from app.schemas.course_generation_job.job_detail import (
    CourseGenerationJobDetailData,
    CourseGenerationJobDetailResponse,
)
from app.schemas.course_generation_job.validation_run import (
    CourseGenerationValidationRunData,
)
from app.services.course_generation.job_service import CourseGenerationJobService
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Course Generation Job"],
    dependencies=[Depends(require_valid_token)],
)


@router.post(
    "/course-runs/{course_run_id}/jobs",
    response_model=CourseGenerationJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    course_run_id: str,
    payload: GenerateCourseRequest,
    db: Session = Depends(get_db),
) -> CourseGenerationJobResponse:
    """Queue a content-generation job for an already-persisted course run.

    Persists a `QUEUED` job row, then publishes `{job_id, course_run_id}` to
    Service Bus — the worker loads everything else itself from the DB.
    """
    try:
        job = CourseGenerationJobService(db).create_and_queue(
            course_run_id=course_run_id, requested_by=payload.requested_by
        )
    except CourseRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Failed to queue course generation job for run %s", course_run_id)
        raise HTTPException(status_code=500, detail="Could not queue course generation. Please try again.")

    return CourseGenerationJobResponse(success=True, data=CourseGenerationJobData.model_validate(job))


@router.get("/jobs/{job_id}", response_model=CourseGenerationJobDetailResponse)
def get_job_detail(job_id: str, db: Session = Depends(get_db)) -> CourseGenerationJobDetailResponse:
    """Return the job's current lifecycle state plus every artifact/validation run so far."""
    from app.repositories.course_generation.course_generation_job_repository import CourseGenerationJobRepository

    job = CourseGenerationJobRepository(db).get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    artifacts = CourseGenerationJobArtifactRepository(db).list_by_job(job_id)
    validation_runs = CourseGenerationValidationRunRepository(db).list_by_job(job_id)

    return CourseGenerationJobDetailResponse(
        success=True,
        data=CourseGenerationJobDetailData(
            job=CourseGenerationJobData.model_validate(job),
            artifacts=[CourseGenerationJobArtifactData.model_validate(a) for a in artifacts],
            validation_runs=[
                CourseGenerationValidationRunData.model_validate(v) for v in validation_runs
            ],
        ),
    )
