"""Business logic for Dashboard Summary statistics."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.repositories.course_run_repository import CourseRunRepository
from app.schemas.dashboard.summary import DashboardSummaryData

logger = logging.getLogger(__name__)

# course_runs.status_code values that mean generation is still running.
# Ticket wording used QUEUED / RUNNING / GENERATING; this schema seeds GENERATING.
_IN_PROGRESS_STATUSES = ("GENERATING",)

# course_runs.status_code value for a successful generation.
# Ticket wording used COMPLETED; this schema seeds GENERATED.
_COMPLETED_STATUSES = ("GENERATED",)


class DashboardService:
    """Computes Dashboard summary counts from course-run records."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRunRepository(db)

    def get_summary(self) -> DashboardSummaryData:
        """Return total, in-progress, and completed course-run counts."""
        total_courses = self.repository.count_all()
        in_progress = self.repository.count_by_statuses(_IN_PROGRESS_STATUSES)
        completed = self.repository.count_by_statuses(_COMPLETED_STATUSES)

        logger.info(
            "Dashboard summary: total=%s in_progress=%s completed=%s",
            total_courses,
            in_progress,
            completed,
        )
        return DashboardSummaryData(
            total_courses=total_courses,
            in_progress=in_progress,
            completed=completed,
        )
