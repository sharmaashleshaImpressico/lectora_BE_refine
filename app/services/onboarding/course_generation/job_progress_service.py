"""Tracks per-stage progress and activity logs for a course generation job.

Backs two frontend-facing surfaces that both need the same underlying data:
  - `GET /jobs/{job_id}`        — a REST snapshot (`JobDetail` shape)
  - `GET /jobs/{job_id}/events` — an SSE stream of `stage_update` events

Stage codes (`A1`, `A2`, `S2`, `A6`) match the frontend's `backendId` values
exactly (see `course_generation_frontend/.../config/pipelineConfig.ts`).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.constants import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_SUCCESS,
    STAGE_OUTCOME_CRITICAL_FAIL,
    STAGE_OUTCOME_RECOVERABLE_FAIL,
    STAGE_STATUS_COMPLETED,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_PROCESSING,
)
from app.models.course_generation.course_generation_job.job import CourseGenerationJob
from app.models.course_generation.course_generation_job.job_log import CourseGenerationJobLog
from app.models.course_generation.course_generation_job.job_stage import CourseGenerationJobStage
from app.repositories.course_generation.course_generation_job_log_repository import (
    CourseGenerationJobLogRepository,
)
from app.repositories.course_generation.course_generation_job_repository import (
    CourseGenerationJobRepository,
)
from app.repositories.course_generation.course_generation_job_stage_repository import (
    CourseGenerationJobStageRepository,
)

logger = logging.getLogger(__name__)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class JobProgressService:
    """Records stage transitions/logs and builds the FE-facing snapshot payload."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = CourseGenerationJobRepository(db)
        self.stages = CourseGenerationJobStageRepository(db)
        self.logs = CourseGenerationJobLogRepository(db)

    # ── Stage transitions ───────────────────────────────────────────────────

    def _get_or_create_stage(self, job_id: str, stage_code: str) -> CourseGenerationJobStage:
        stage = self.stages.get_by_job_and_stage(job_id, stage_code)
        if stage is None:
            stage = self.stages.create(
                CourseGenerationJobStage(
                    job_id=job_id, stage_code=stage_code, status=STAGE_STATUS_PENDING
                )
            )
        return stage

    def start_stage(self, job_id: str, stage_code: str, *, log_message: str) -> None:
        stage = self._get_or_create_stage(job_id, stage_code)
        now = datetime.now(timezone.utc)
        stage.status = STAGE_STATUS_PROCESSING
        if stage.started_at is None:
            stage.started_at = now
        stage.completed_at = None
        self.db.flush()
        self.log(job_id, LOG_LEVEL_INFO, log_message, stage_code=stage_code)

    def complete_stage(
        self,
        job_id: str,
        stage_code: str,
        *,
        outcome: str | None,
        log_message: str,
    ) -> None:
        stage = self._get_or_create_stage(job_id, stage_code)
        stage.status = STAGE_STATUS_COMPLETED
        stage.outcome = outcome
        stage.completed_at = datetime.now(timezone.utc)
        self.db.flush()
        self.log(job_id, LOG_LEVEL_SUCCESS, log_message, stage_code=stage_code)

    def mark_retry(self, job_id: str, stage_code: str, *, log_message: str) -> None:
        """One repair cycle finished but needs another round — shown as 'retrying' by the FE."""
        stage = self._get_or_create_stage(job_id, stage_code)
        stage.status = STAGE_STATUS_COMPLETED
        stage.outcome = STAGE_OUTCOME_RECOVERABLE_FAIL
        stage.retry_attempt += 1
        stage.completed_at = datetime.now(timezone.utc)
        self.db.flush()
        self.log(job_id, LOG_LEVEL_INFO, log_message, stage_code=stage_code)

    def fail_stage(
        self,
        job_id: str,
        stage_code: str,
        *,
        message: str,
        blockers: list[dict[str, Any]] | None = None,
    ) -> None:
        stage = self._get_or_create_stage(job_id, stage_code)
        stage.status = STAGE_STATUS_FAILED
        stage.outcome = STAGE_OUTCOME_CRITICAL_FAIL
        stage.completed_at = datetime.now(timezone.utc)
        stage.blockers_json = json.dumps(blockers) if blockers else None
        self.db.flush()
        self.log(job_id, LOG_LEVEL_ERROR, message, stage_code=stage_code)

    def record_instant_stage(
        self,
        job_id: str,
        stage_code: str,
        *,
        started_at: datetime,
        completed_at: datetime,
        log_message: str,
    ) -> None:
        """For stages that already fully ran before tracking started (e.g. A1

        enrichment, which completes synchronously inside job creation before
        the job is even queued) — records it as already COMPLETED.
        """
        stage = self._get_or_create_stage(job_id, stage_code)
        stage.status = STAGE_STATUS_COMPLETED
        stage.outcome = None
        stage.started_at = started_at
        stage.completed_at = completed_at
        self.db.flush()
        self.log(job_id, LOG_LEVEL_SUCCESS, log_message, stage_code=stage_code)

    # ── Logging ──────────────────────────────────────────────────────────────

    def log(self, job_id: str, level: str, message: str, *, stage_code: str | None = None) -> None:
        entry = CourseGenerationJobLog(
            job_id=job_id, level=level, message=message, stage_code=stage_code
        )
        self.logs.create(entry)
        self.db.flush()

    # ── Snapshot building (shared by REST + SSE) ────────────────────────────

    def build_job_detail(self, job: CourseGenerationJob) -> dict[str, Any]:
        """`JobDetail`-shaped payload for `GET /jobs/{job_id}`."""
        stages = self.stages.list_by_job(job.id)
        return {
            "jobId": str(job.id),
            "status": job.status_code,
            "createdAt": _iso(job.created_at),
            "updatedAt": _iso(job.completed_at or job.started_at or job.created_at),
            "stages": [self._stage_progress(s) for s in stages],
            "error": self._build_error(job, stages),
        }

    def build_sse_event(
        self, job: CourseGenerationJob, *, logs_since: list[CourseGenerationJobLog]
    ) -> dict[str, Any]:
        """`SSEPipelineEvent`-shaped payload for one `stage_update` SSE frame."""
        stages = self.stages.list_by_job(job.id)
        return {
            "type": "stage_update",
            "jobId": str(job.id),
            "status": job.status_code,
            "updatedAt": _iso(job.completed_at or job.started_at or job.created_at),
            "stages": [self._stage_sse(s) for s in stages],
            "error": self._build_error(job, stages),
            "logs": [self._log_sse(entry) for entry in logs_since],
        }

    @staticmethod
    def _stage_progress(stage: CourseGenerationJobStage) -> dict[str, Any]:
        return {
            "stage": stage.stage_code,
            "status": stage.status,
            "startedAt": _iso(stage.started_at),
            "completedAt": _iso(stage.completed_at),
            "outcome": stage.outcome,
        }

    @staticmethod
    def _stage_sse(stage: CourseGenerationJobStage) -> dict[str, Any]:
        blockers = json.loads(stage.blockers_json) if stage.blockers_json else []
        return {
            "stage": stage.stage_code,
            "status": stage.status,
            "startedAt": _iso(stage.started_at),
            "completedAt": _iso(stage.completed_at),
            "outcome": stage.outcome,
            "blockers": blockers,
            "retryAttempt": stage.retry_attempt,
        }

    @staticmethod
    def _log_sse(entry: CourseGenerationJobLog) -> dict[str, Any]:
        return {
            "id": entry.id,
            "level": entry.level,
            "message": entry.message,
            "stageId": entry.stage_code,
            "createdAt": _iso(entry.created_at),
        }

    @staticmethod
    def _build_error(
        job: CourseGenerationJob, stages: list[CourseGenerationJobStage]
    ) -> dict[str, Any] | None:
        if not job.error_message:
            return None
        failed_stage = next((s for s in stages if s.status == STAGE_STATUS_FAILED), None)
        return {
            "code": "GENERATION_FAILED",
            "message": job.error_message,
            "stage": failed_stage.stage_code if failed_stage else None,
            "retryable": False,
        }
