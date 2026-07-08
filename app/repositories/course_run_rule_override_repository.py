"""Course-run-rule-override repository, built on the generic `BaseRepository`."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run_rule_override import CourseRunRuleOverride
from app.repositories.base_repository import BaseRepository


class CourseRunRuleOverrideRepository(BaseRepository[CourseRunRuleOverride]):
    """CRUD helper scoped to the `CourseRunRuleOverride` model."""

    def __init__(self, db: Session) -> None:
        super().__init__(CourseRunRuleOverride, db)
