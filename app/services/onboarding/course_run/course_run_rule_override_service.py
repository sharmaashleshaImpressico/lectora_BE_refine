"""Business logic for the Course Run Rule Override API."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run_rule_override import CourseRunRuleOverride
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.repositories.course_run.course_run_rule_override_repository import CourseRunRuleOverrideRepository
from app.schemas.onboarding.course_run.course_run_rule_override import CourseRunRuleOverrideCreate
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)


class CourseRunRuleOverrideService:
    """Encapsulates course-run-rule-override CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRunRuleOverrideRepository(db)
        self.course_run_repository = CourseRunRepository(db)

    def create_override(
        self, payload: CourseRunRuleOverrideCreate, created_by: str
    ) -> CourseRunRuleOverride:
        """Persist a new course-run-rule-override record.

        `created_by` is the authenticated user's name, used when the payload
        does not carry an explicit creator.
        """
        course_run = self.course_run_repository.get_by_id(payload.course_run_id)
        if course_run is None:
            raise CourseRunNotFoundError(f"Course run '{payload.course_run_id}' not found.")

        data = payload.model_dump()
        data["created_by"] = data.get("created_by") or created_by
        override = CourseRunRuleOverride(**data)
        created = self.repository.create(override)
        logger.info("Created course run rule override %s (run %s)", created.id, created.course_run_id)
        return created
