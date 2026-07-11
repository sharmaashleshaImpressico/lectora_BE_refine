"""Shared status-code constants for the course generation job lifecycle."""

from __future__ import annotations

JOB_STATUS_PENDING = "PENDING"
JOB_STATUS_PROCESSING = "PROCESSING"
JOB_STATUS_COMPLETED = "COMPLETED"
JOB_STATUS_FAILED = "FAILED"
JOB_STATUS_CANCELLED = "CANCELLED"

JOB_STATUS_SEED_ROWS: tuple[tuple[str, str, str], ...] = (
    (JOB_STATUS_PENDING, "Pending", "Course generation job has been created but not started."),
    (JOB_STATUS_PROCESSING, "Processing", "Course generation job is currently running."),
    (JOB_STATUS_COMPLETED, "Completed", "Course generation job completed successfully."),
    (JOB_STATUS_FAILED, "Failed", "Course generation job failed due to a technical or pipeline error."),
    (JOB_STATUS_CANCELLED, "Cancelled", "Course generation job was cancelled by the user or system."),
)

VALIDATION_STATUS_PASSED = "PASSED"
VALIDATION_STATUS_BLOCKED = "BLOCKED"
VALIDATION_STATUS_FAILED = "FAILED"

ARTIFACT_STAGE_CONTENT_GENERATION = "content_generation"
ARTIFACT_STAGE_VALIDATION = "validation"
ARTIFACT_STAGE_TO_GENERATION = "to_generation"

ARTIFACT_TYPE_SHARED_STATE = "shared_state"
ARTIFACT_TYPE_STUDY_GUIDE = "study_guide"
ARTIFACT_TYPE_ENRICHED_SECTIONS = "enriched_sections"
# Rich A2 writer output (headings + body_paragraphs + images) — the structured
# course the frontend editor loads via GET /jobs/{job_id}/course.
ARTIFACT_TYPE_COURSE_CONTENT = "course_content"
ARTIFACT_TYPE_VALIDATION_REPORT = "validation_report"
ARTIFACT_TYPE_LOG = "log"
ARTIFACT_TYPE_TO_OUTLINE = "to_outline"
ARTIFACT_TYPE_COURSE_SPEC = "course_spec"

# ── Pipeline stage tracking (drives the frontend's stage tracker + SSE) ────
#
# Stage codes match the frontend's `backendId` values exactly
# (course_generation_frontend/src/modules/course-generation/config/pipelineConfig.ts).
# The Course Generation screen shows five stages, in order:
#   SECTION_MAPPER -> "Section Mapper"      (map the reviewed outline to source content)
#   A2             -> "Content Generation"  (per-lesson content writer)
#   S2             -> "Validation"          (S2 validation + repair loop, a gate)
#   A6             -> "Assembly"            (study-guide docx rendering)
#   EXPORT is a frontend-only virtual stage — never emitted by the backend.
#
# A1 (Step 04 outline enrichment) runs synchronously in job_service *before* the
# job is queued, so it is intentionally NOT shown on the Course Generation
# screen — the outline is already prepared by the time this pipeline starts.
STAGE_A1 = "A1"
STAGE_SECTION_MAPPER = "SECTION_MAPPER"
STAGE_A2 = "A2"
STAGE_S2 = "S2"
STAGE_A6 = "A6"

ALL_STAGE_CODES: tuple[str, ...] = (
    STAGE_A1,
    STAGE_SECTION_MAPPER,
    STAGE_A2,
    STAGE_S2,
    STAGE_A6,
)

STAGE_STATUS_PENDING = "PENDING"
STAGE_STATUS_PROCESSING = "PROCESSING"
STAGE_STATUS_COMPLETED = "COMPLETED"
STAGE_STATUS_FAILED = "FAILED"

# Outcome values the frontend understands (`PipelineStageState['outcome']`).
# A COMPLETED stage with an outcome containing "FAIL" is shown as "retrying".
STAGE_OUTCOME_PASS = "PASS"
STAGE_OUTCOME_WARNING = "WARNING"
STAGE_OUTCOME_RECOVERABLE_FAIL = "RECOVERABLE_FAIL"
STAGE_OUTCOME_CRITICAL_FAIL = "CRITICAL_FAIL"

LOG_LEVEL_INFO = "info"
LOG_LEVEL_WARN = "warn"
LOG_LEVEL_ERROR = "error"
LOG_LEVEL_SUCCESS = "success"
