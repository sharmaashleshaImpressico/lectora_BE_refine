"""Seeds small reference/lookup tables that the app depends on at startup."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.constants import JOB_STATUS_SEED_ROWS
from app.models.course_generation.course_generation_job.job_status import CourseGenerationJobStatus

logger = logging.getLogger(__name__)


def seed_lookup_tables(db: Session) -> None:
    """Insert any missing job-status rows. Safe to call on every startup."""
    existing = {row.code for row in db.query(CourseGenerationJobStatus.code).all()}
    for code, name, description in JOB_STATUS_SEED_ROWS:
        if code in existing:
            continue
        db.add(CourseGenerationJobStatus(code=code, name=name, description=description))
    db.commit()
