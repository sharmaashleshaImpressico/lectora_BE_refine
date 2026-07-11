"""Runs the Content Generation pipeline for one job and persists every result.

This is the DB-facing orchestration layer that sits between the Service Bus
worker and `ContentGenerationOrchestrator`. It is intentionally free of any
Service Bus import so it can be invoked directly (tests, scripts, a future
synchronous endpoint) without a queue in the loop — the worker in
`app.core.service_bus.worker` is just one caller of `run()`.

Resumability: every state transition (`RUNNING` -> `COMPLETED`/`FAILED`) and
every artifact is committed to the DB as it happens, keyed by `job_id`. If
the process dies mid-run, the job is left `RUNNING` with whatever artifacts
were persisted so far; a future retry path can inspect those rows instead of
starting from zero.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.agents.content_generation_agent.models import S2ValidationReport
from app.core.storage.blob_file_resolver import BlobResolutionError
from app.kernel import create_kernel
from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_STAGE_CONTENT_GENERATION,
    ARTIFACT_STAGE_VALIDATION,
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_ENRICHED_SECTIONS,
    ARTIFACT_TYPE_SHARED_STATE,
    ARTIFACT_TYPE_STUDY_GUIDE,
    ARTIFACT_TYPE_VALIDATION_REPORT,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    LOG_LEVEL_INFO,
    VALIDATION_STATUS_BLOCKED,
    VALIDATION_STATUS_PASSED,
)
from app.orchestrators.content_generation.orchestrator import (
    ContentGenerationOrchestrator,
    StageReporter,
)
from app.repositories.course_generation.course_generation_validation_run_repository import (
    CourseGenerationValidationRunRepository,
)
from app.services.onboarding.course_generation.artifact_service import (
    CourseGenerationArtifactService,
)
from app.services.onboarding.course_generation.data_loader import (
    CourseGenerationDataLoader,
    CourseRunNotFoundError,
    MissingTrainingOutlineError,
)
from app.services.onboarding.course_generation.job_progress_service import JobProgressService
from app.services.onboarding.course_generation.job_service import CourseGenerationJobService
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)

# A job in one of these states has already finished — a redelivered message must
# not re-run the pipeline (Section Mapper, content generation, …) for it.
_TERMINAL_JOB_STATUSES = frozenset(
    {JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED}
)


class _PipelineStageReporter(StageReporter):
    """Bridges `ContentGenerationOrchestrator`'s stage callbacks to the DB.

    Commits after every transition (not just flush) so a concurrent SSE
    poller in a different DB session sees progress as it happens, rather
    than only once the whole (long-running, single-transaction) orchestrator
    call finishes.
    """

    def __init__(self, db: Session, job_id: str) -> None:
        self._progress = JobProgressService(db)
        self._db = db
        self._job_id = job_id

    def start(self, stage_code: str, message: str) -> None:
        self._progress.start_stage(self._job_id, stage_code, log_message=message)
        self._db.commit()

    def complete(self, stage_code: str, message: str, *, outcome: str | None = None) -> None:
        self._progress.complete_stage(self._job_id, stage_code, outcome=outcome, log_message=message)
        self._db.commit()

    def retry(self, stage_code: str, message: str) -> None:
        self._progress.mark_retry(self._job_id, stage_code, log_message=message)
        self._db.commit()

    def fail(self, stage_code: str, message: str, *, blockers: list | None = None) -> None:
        self._progress.fail_stage(self._job_id, stage_code, message=message, blockers=blockers)
        self._db.commit()


class CourseGenerationPipelineRunner:
    """Loads a job's inputs, runs Content Generation + validation, persists everything."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = CourseGenerationJobService(db)
        self.loader = CourseGenerationDataLoader(db)
        self.artifacts = CourseGenerationArtifactService(db)
        self.validation_runs = CourseGenerationValidationRunRepository(db)
        self.progress = JobProgressService(db)

    def _activity(self, job_id: str, message: str, level: str = LOG_LEVEL_INFO) -> None:
        """Write one human-readable activity-feed entry and commit it.

        Committing (not just flushing) makes the entry visible to the SSE
        endpoint, which polls the job from a separate DB session — so each
        milestone reaches the frontend Activity Feed as it happens rather than
        only when the whole run finishes.
        """
        self.progress.log(job_id, level, message)
        self.db.commit()

    def run(self, *, job_id: str, course_run_id: str) -> None:
        logger.info(
            "[course_generation] Starting job %s | course_run_id=%s", job_id, course_run_id
        )

        # Idempotency guard: a redelivered message (e.g. a late duplicate whose
        # original run already finished) must not re-execute the pipeline and run
        # the Section Mapper a second time. A job that already reached a terminal
        # state is done — acknowledge the message without re-processing.
        existing = self.jobs.repository.get_by_id(job_id)
        if existing is not None and existing.status_code in _TERMINAL_JOB_STATUSES:
            logger.info(
                "[course_generation] Job %s already in terminal state %s — "
                "skipping duplicate delivery.",
                job_id,
                existing.status_code,
            )
            return

        self.jobs.mark_running(job_id, started_at=datetime.now(timezone.utc))
        self.db.commit()
        self._activity(job_id, "Course generation started.")

        try:
            self._execute(job_id=job_id, course_run_id=course_run_id)
        except (MissingTrainingOutlineError, CourseRunNotFoundError, BlobResolutionError) as exc:
            # Permanent, data-driven failures: retrying the same message can
            # never succeed (the course run won't spontaneously gain an
            # outline or reappear, and a source blob missing at its recorded
            # path won't materialise). Mark failed and let the message complete
            # so it doesn't loop forever — being re-delivered would just re-run
            # the whole (LLM-heavy) pipeline to the same failure until the queue
            # dead-letters it — and starve the jobs queued behind it.
            logger.error("[course_generation] Job %s failed permanently: %s", job_id, exc)
            self.jobs.mark_failed(
                job_id, completed_at=datetime.now(timezone.utc), error_message=str(exc)
            )
            self.db.commit()
        except Exception as exc:
            logger.exception("[course_generation] Job %s failed", job_id)
            self.jobs.mark_failed(
                job_id, completed_at=datetime.now(timezone.utc), error_message=str(exc)
            )
            self.db.commit()
            raise

    def _execute(self, *, job_id: str, course_run_id: str) -> None:
        with traced_workflow(
            "course_generation",
            run_id=job_id,
            session_id=course_run_id,
            job_id=job_id,
            course_run_id=course_run_id,
            doc_name=f"job_{job_id}",
            metadata={"job_id": job_id, "course_run_id": course_run_id},
            input_data={"job_id": job_id, "course_run_id": course_run_id},
        ):
            self._execute_traced(job_id=job_id, course_run_id=course_run_id)

    def _execute_traced(self, *, job_id: str, course_run_id: str) -> None:
        with tempfile.TemporaryDirectory(prefix=f"course_gen_{job_id}_") as tmp_dir:
            output_path = str(Path(tmp_dir) / "study_guide.docx")
            spec = self.loader.load(course_run_id, output_path=output_path)

            source_count = len(spec.source_file_specs or [])
            self._activity(
                job_id,
                f"Inputs validated — {source_count} source document(s) resolved.",
            )

            self.artifacts.persist_bytes(
                job_id=job_id,
                course_run_id=course_run_id,
                course_title=spec.course_title,
                artifact_type=ARTIFACT_TYPE_SHARED_STATE,
                stage_name=ARTIFACT_STAGE_CONTENT_GENERATION,
                file_name="pipeline_input.json",
                content=json.dumps(
                    {
                        "run_id": spec.run_id,
                        "course_title": spec.course_title,
                        "course_difficulty": spec.course_difficulty,
                        "course_audience": spec.course_audience,
                        "course_spec": spec.course_spec,
                        "learning_objectives": spec.learning_objectives,
                    },
                    default=str,
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.db.commit()

            with traced_workflow(
                "source_processing",
                run_id=job_id,
                doc_name=spec.course_title or f"job_{job_id}",
                metadata={"source_count": source_count},
            ):
                self._activity(
                    job_id, "Documents processed — indexing source content for retrieval."
                )

            kernel = create_kernel()
            reporter = _PipelineStageReporter(self.db, job_id)
            result = ContentGenerationOrchestrator(kernel).execute(spec, on_stage=reporter)

            self.artifacts.persist_bytes(
                job_id=job_id,
                course_run_id=course_run_id,
                course_title=spec.course_title,
                artifact_type=ARTIFACT_TYPE_ENRICHED_SECTIONS,
                stage_name=ARTIFACT_STAGE_CONTENT_GENERATION,
                file_name="enriched_sections.json",
                content=json.dumps(result.enriched_sections, default=str).encode("utf-8"),
                content_type="application/json",
            )

            # Rich A2 writer output — the structured course (headings +
            # body_paragraphs + images) the frontend editor loads via
            # GET /jobs/{job_id}/course. Persisted alongside enriched_sections
            # because the docx/enriched_sections artifacts don't carry the
            # paragraph-block structure the editor binds to.
            self.artifacts.persist_bytes(
                job_id=job_id,
                course_run_id=course_run_id,
                course_title=spec.course_title,
                artifact_type=ARTIFACT_TYPE_COURSE_CONTENT,
                stage_name=ARTIFACT_STAGE_CONTENT_GENERATION,
                file_name="course_content.json",
                content=result.a2.model_dump_json().encode("utf-8"),
                content_type="application/json",
            )

            if result.study_guide_path:
                self.artifacts.persist_file(
                    job_id=job_id,
                    course_run_id=course_run_id,
                    course_title=spec.course_title,
                    artifact_type=ARTIFACT_TYPE_STUDY_GUIDE,
                    stage_name=ARTIFACT_STAGE_CONTENT_GENERATION,
                    local_path=result.study_guide_path,
                    content_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                )

            report_artifact = self.artifacts.persist_bytes(
                job_id=job_id,
                course_run_id=course_run_id,
                course_title=spec.course_title,
                artifact_type=ARTIFACT_TYPE_VALIDATION_REPORT,
                stage_name=ARTIFACT_STAGE_VALIDATION,
                file_name="validation_report.json",
                content=result.validation.model_dump_json().encode("utf-8"),
                content_type="application/json",
            )
            self.db.commit()

            self._persist_validation_run(
                job_id=job_id,
                course_run_id=course_run_id,
                validation=result.validation,
                attempt_number=result.repair_attempts + 1,
                report_artifact_id=report_artifact.id,
            )
            self.db.commit()

            if not result.validation_passed:
                self.jobs.mark_failed(
                    job_id,
                    completed_at=datetime.now(timezone.utc),
                    error_message=(
                        f"Content validation blocked after {result.repair_attempts} "
                        f"repair attempt(s): {result.validation.message or 'see validation report'}"
                    ),
                )
                self.db.commit()
                return

            self.jobs.mark_completed(
                job_id,
                completed_at=datetime.now(timezone.utc),
                shared_state_blob_path=None,
            )
            self.db.commit()
            logger.info("[course_generation] Job %s completed", job_id)

    def _persist_validation_run(
        self,
        *,
        job_id: str,
        course_run_id: str,
        validation: S2ValidationReport,
        attempt_number: int,
        report_artifact_id: int,
    ) -> None:
        from app.models.course_generation.course_generation_job.validation_run import (
            CourseGenerationValidationRun,
        )

        status = VALIDATION_STATUS_BLOCKED if validation.blockers > 0 else VALIDATION_STATUS_PASSED
        self.validation_runs.create(
            CourseGenerationValidationRun(
                job_id=job_id,
                course_run_id=course_run_id,
                validation_type=validation.phase or "full",
                attempt_number=attempt_number,
                status=status,
                blocker_count=validation.blockers,
                warning_count=validation.warnings,
                info_count=validation.infos,
                report_artifact_id=report_artifact_id,
            )
        )
