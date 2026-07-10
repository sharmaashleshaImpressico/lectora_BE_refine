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
from app.kernel import create_kernel
from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_STAGE_CONTENT_GENERATION,
    ARTIFACT_STAGE_VALIDATION,
    ARTIFACT_TYPE_ENRICHED_SECTIONS,
    ARTIFACT_TYPE_SHARED_STATE,
    ARTIFACT_TYPE_STUDY_GUIDE,
    ARTIFACT_TYPE_VALIDATION_REPORT,
    VALIDATION_STATUS_BLOCKED,
    VALIDATION_STATUS_PASSED,
)
from app.orchestrators.content_generation.orchestrator import ContentGenerationOrchestrator
from app.repositories.course_generation.course_generation_validation_run_repository import (
    CourseGenerationValidationRunRepository,
)
from app.services.course_generation.artifact_service import (
    CourseGenerationArtifactService,
)
from app.services.course_generation.data_loader import CourseGenerationDataLoader
from app.services.course_generation.job_service import CourseGenerationJobService

logger = logging.getLogger(__name__)


class CourseGenerationPipelineRunner:
    """Loads a job's inputs, runs Content Generation + validation, persists everything."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = CourseGenerationJobService(db)
        self.loader = CourseGenerationDataLoader(db)
        self.artifacts = CourseGenerationArtifactService(db)
        self.validation_runs = CourseGenerationValidationRunRepository(db)

    def run(self, *, job_id: str, course_run_id: str) -> None:
        logger.info(
            "[course_generation] Starting job %s | course_run_id=%s", job_id, course_run_id
        )
        self.jobs.mark_running(job_id, started_at=datetime.now(timezone.utc))
        self.db.commit()

        try:
            self._execute(job_id=job_id, course_run_id=course_run_id)
        except Exception as exc:
            logger.exception("[course_generation] Job %s failed", job_id)
            self.jobs.mark_failed(
                job_id, completed_at=datetime.now(timezone.utc), error_message=str(exc)
            )
            self.db.commit()
            raise

    def _execute(self, *, job_id: str, course_run_id: str) -> None:
        with tempfile.TemporaryDirectory(prefix=f"course_gen_{job_id}_") as tmp_dir:
            output_path = str(Path(tmp_dir) / "study_guide.docx")
            spec = self.loader.load(course_run_id, output_path=output_path)

            self.artifacts.persist_bytes(
                job_id=job_id,
                course_run_id=course_run_id,
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

            kernel = create_kernel()
            result = ContentGenerationOrchestrator(kernel).execute(spec)

            self.artifacts.persist_bytes(
                job_id=job_id,
                course_run_id=course_run_id,
                artifact_type=ARTIFACT_TYPE_ENRICHED_SECTIONS,
                stage_name=ARTIFACT_STAGE_CONTENT_GENERATION,
                file_name="enriched_sections.json",
                content=json.dumps(result.enriched_sections, default=str).encode("utf-8"),
                content_type="application/json",
            )

            if result.study_guide_path:
                self.artifacts.persist_file(
                    job_id=job_id,
                    course_run_id=course_run_id,
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
