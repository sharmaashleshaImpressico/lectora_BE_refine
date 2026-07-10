"""Shared status-code constants for the course generation job lifecycle."""

from __future__ import annotations

JOB_STATUS_QUEUED = "QUEUED"
JOB_STATUS_RUNNING = "RUNNING"
JOB_STATUS_COMPLETED = "COMPLETED"
JOB_STATUS_FAILED = "FAILED"

JOB_STATUS_SEED_ROWS: tuple[tuple[str, str, str], ...] = (
    (JOB_STATUS_QUEUED, "Queued", "Job has been created and its message published to Service Bus."),
    (JOB_STATUS_RUNNING, "Running", "Worker picked up the message and is executing the pipeline."),
    (JOB_STATUS_COMPLETED, "Completed", "Content generation and validation finished successfully."),
    (JOB_STATUS_FAILED, "Failed", "Job failed during content generation or validation."),
)

VALIDATION_STATUS_PASSED = "PASSED"
VALIDATION_STATUS_BLOCKED = "BLOCKED"
VALIDATION_STATUS_FAILED = "FAILED"

ARTIFACT_STAGE_CONTENT_GENERATION = "content_generation"
ARTIFACT_STAGE_VALIDATION = "validation"

ARTIFACT_TYPE_SHARED_STATE = "shared_state"
ARTIFACT_TYPE_STUDY_GUIDE = "study_guide"
ARTIFACT_TYPE_ENRICHED_SECTIONS = "enriched_sections"
ARTIFACT_TYPE_VALIDATION_REPORT = "validation_report"
ARTIFACT_TYPE_LOG = "log"
