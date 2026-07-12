"""HTTP routes for kicking off and polling course generation jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from semantic_kernel import Kernel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_kernel
from app.core.auth.dependencies import get_current_user_name, require_valid_token
from app.db.session import azure_db_client
from app.models.course_generation.course_generation_job.constants import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
)
from app.repositories.course_generation.course_generation_job_repository import (
    CourseGenerationJobRepository,
)
from app.schemas.onboarding.course_generation_job.job import (
    CancelJobResponse,
    CourseGenerationJobData,
    CourseGenerationJobResponse,
    GenerateCourseRequest,
)
from app.schemas.onboarding.course_generation_job.job_detail import JobDetailResponse
from app.services.onboarding.course_generation.course_content_service import (
    CourseContentNotFoundError,
    CourseContentService,
)
from app.services.onboarding.course_generation.job_progress_service import JobProgressService
from app.services.onboarding.course_generation.job_service import (
    CourseGenerationJobService,
    JobNotCancellableError,
)
from app.services.onboarding.course_generation.training_outline_service import (
    TrainingOutlineEnrichmentError,
    TrainingOutlineValidationError,
)
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Course Generation Job"],
    dependencies=[Depends(require_valid_token)],
)

_TERMINAL_JOB_STATUSES = {JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED}
_SSE_POLL_INTERVAL_SECONDS = 1.5
_SSE_MAX_STREAM_SECONDS = 30 * 60


@router.post(
    "/course-runs/{course_run_id}/jobs",
    response_model=CourseGenerationJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    course_run_id: str,
    payload: GenerateCourseRequest,
    db: Session = Depends(get_db),
    kernel: Kernel = Depends(get_kernel),
    current_user: str = Depends(get_current_user_name),
) -> CourseGenerationJobResponse:
    """Queue a content-generation job for an already-persisted course run.

    Persists a `QUEUED` job row, then publishes `{job_id, course_run_id}` to
    Service Bus — the worker loads everything else itself from the DB.

    If `payload.training_outline` is supplied, it is validated, enriched via
    Step 04, and both artifacts are uploaded to blob storage before queueing.
    """
    try:
        job = CourseGenerationJobService(db, kernel=kernel).create_and_queue(
            course_run_id=course_run_id,
            requested_by=payload.requested_by or current_user,
            training_outline=payload.training_outline,
        )
    except CourseRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TrainingOutlineValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid training_outline: {exc}")
    except TrainingOutlineEnrichmentError as exc:
        raise HTTPException(status_code=502, detail=f"Training outline enrichment failed: {exc}")
    except Exception:
        logger.exception("Failed to queue course generation job for run %s", course_run_id)
        raise HTTPException(status_code=500, detail="Could not queue course generation. Please try again.")

    return CourseGenerationJobResponse(success=True, data=CourseGenerationJobData.model_validate(job))


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job_detail(job_id: str, db: Session = Depends(get_db)) -> JobDetailResponse:
    """REST snapshot of the job's current status and per-stage progress.

    Same underlying data as the `GET /jobs/{job_id}/events` SSE stream —
    used by the frontend to hydrate state on load/reconnect before the
    stream's first event arrives.
    """
    job = CourseGenerationJobRepository(db).get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    detail = JobProgressService(db).build_job_detail(job)
    return JobDetailResponse(
        job_id=detail["jobId"],
        status=detail["status"],
        created_at=detail["createdAt"],
        updated_at=detail["updatedAt"],
        stages=detail["stages"],
        error=detail["error"],
    )


@router.get("/jobs/{job_id}/course")
def get_job_course(job_id: str, db: Session = Depends(get_db)) -> dict:
    """The generated course for a completed job, in the editor's `CourseContent` shape.

    Reads the `course_content.json` artifact (rich A2 writer output) the pipeline
    persisted on completion — falling back to `enriched_sections.json` for jobs
    generated before that artifact existed — and maps it to the camelCase payload
    the frontend editor binds to. Returns 404 when no content exists yet (job not
    finished / failed before writing one), which the editor treats as an
    expired job.
    """
    job = CourseGenerationJobRepository(db).get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    try:
        return CourseContentService(db).get_course_content(job_id)
    except CourseContentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Failed to load generated course for job %s", job_id)
        raise HTTPException(
            status_code=500, detail="Could not load the generated course. Please try again."
        )


# Headers that keep the event stream flowing unbuffered end-to-end: disable
# HTTP caching and, critically, `X-Accel-Buffering: no` so an intermediary
# (nginx / Azure front door) never holds frames back waiting for the response
# to finish — an SSE response never finishes until the job does.
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _poll_job_frames(job_id: str, state: dict) -> tuple[list[str], bool]:
    """Read the job's latest status/logs and render any SSE frames to send.

    Runs in a worker thread (via `run_in_threadpool`) on its own short-lived DB
    session, opened and closed entirely within this call. This is deliberate:
    the previous implementation reused the request-scoped session across the
    streaming generator, which Starlette pulls on *different* threadpool threads
    per iteration — and a pyodbc/Azure SQL connection must not be used across
    threads, so the very first read hung and no frame was ever flushed. A fresh
    per-poll session also always sees the worker thread's newest commits.
    """
    frames: list[str] = []
    with azure_db_client.session_scope() as db:
        repository = CourseGenerationJobRepository(db)
        progress = JobProgressService(db)

        current_job = repository.get_by_id(job_id)
        if current_job is None:
            return frames, True  # job vanished — end the stream

        new_logs = progress.logs.list_since(job_id, state["cursor"])
        if new_logs:
            state["cursor"] = max(entry.id for entry in new_logs)

        event = progress.build_sse_event(current_job, logs_since=new_logs)

        # Emit a frame when anything the client renders has changed — new
        # activity logs, a job-status transition, or a stage snapshot change —
        # not only when new logs exist. `mark_completed`/`mark_failed` change the
        # job status without writing a log, so a logs-only trigger would never
        # deliver the terminal COMPLETED/FAILED frame the client needs to finish
        # (transition to the editor / show the error).
        stage_signature = json.dumps(
            [(s["stage"], s["status"], s["outcome"], s["retryAttempt"]) for s in event["stages"]]
        )
        changed = (
            state["first"]
            or bool(new_logs)
            or current_job.status_code != state["last_status"]
            or stage_signature != state["last_signature"]
        )
        if changed:
            frames.append(
                f"event: message\ndata: {json.dumps(event)}\nid: {state['cursor']}\n\n"
            )
            state["first"] = False
            state["last_status"] = current_job.status_code
            state["last_signature"] = stage_signature
        else:
            frames.append(": heartbeat\n\n")

        terminal = current_job.status_code in _TERMINAL_JOB_STATUSES
        if terminal:
            frames.append("event: done\ndata: \n\n")
        return frames, terminal


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job_id: str,
    request: Request,
    lastEventId: int = 0,
) -> StreamingResponse:
    """SSE stream of live stage/log updates for a job.

    Sends a `stage_update` frame (matching `SSEPipelineEvent`) whenever new
    activity-log entries exist since the client's cursor, a terminal `done`
    event once the job reaches a finished status, or `timeout` after 30
    minutes. `lastEventId` (query param, or the `Last-Event-ID` header on
    reconnect) lets the client resume without replaying already-seen logs.

    Implemented as an async generator that offloads each blocking DB poll to a
    worker thread and awaits between polls, so a single long-lived stream never
    pins a threadpool thread and never shares a DB connection across threads.
    """
    with azure_db_client.session_scope() as db:
        if CourseGenerationJobRepository(db).get_by_id(job_id) is None:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    header_cursor = request.headers.get("last-event-id")
    cursor = int(header_cursor) if header_cursor and header_cursor.isdigit() else lastEventId

    async def event_stream():
        state = {
            "cursor": cursor,
            "first": True,
            "last_status": None,
            "last_signature": None,
        }
        start = time.monotonic()

        while True:
            if await request.is_disconnected():
                break

            frames, terminal = await run_in_threadpool(_poll_job_frames, job_id, state)
            for frame in frames:
                yield frame

            if terminal:
                break

            if time.monotonic() - start > _SSE_MAX_STREAM_SECONDS:
                yield "event: timeout\ndata: \n\n"
                break

            await asyncio.sleep(_SSE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.delete("/jobs/{job_id}", response_model=CancelJobResponse)
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> CancelJobResponse:
    """Cancel a queued or in-progress course generation job."""
    try:
        job = CourseGenerationJobService(db).mark_cancelled(
            job_id, completed_at=datetime.now(timezone.utc)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except JobNotCancellableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return CancelJobResponse(job_id=str(job.id), status=job.status_code)
