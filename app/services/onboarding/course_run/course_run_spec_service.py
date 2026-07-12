"""Business logic for the Course Run Spec API."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.ai.rule_pack_config import resolve_course_rule_pack
from app.models.onboarding.course_run.course_run_spec import CourseRunSpec
from app.repositories.course_basic.course_repository import CourseRepository
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.repositories.course_run.course_run_spec_repository import CourseRunSpecRepository
from app.schemas.onboarding.course_run.course_run_spec import CourseRunSpecCreate
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)


class CourseRunSpecService:
    """Encapsulates course-run-spec CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRunSpecRepository(db)
        self.course_run_repository = CourseRunRepository(db)

    def create_spec(self, payload: CourseRunSpecCreate) -> CourseRunSpec:
        """Persist a new course-run-spec record."""
        course_run = self.course_run_repository.get_by_id(payload.course_run_id)
        if course_run is None:
            raise CourseRunNotFoundError(
                f"Course run '{payload.course_run_id}' not found."
            )

        values = payload.model_dump()

        # Backend is the source of truth for pack identity: when the frontend
        # doesn't send rule_pack_id/version, resolve the pack from the course
        # type chosen on the Course Basic screen. Frontend-provided values
        # (older clients) still win — same precedence data_loader applies.
        if not values.get("rule_pack_id"):
            course = CourseRepository(self.db).get_by(id=int(course_run.course_id))
            resolved = resolve_course_rule_pack(
                course_type=course.course_type if course else None
            )
            if resolved is not None:
                _, pack = resolved
                values["rule_pack_id"] = pack.get("id")
                values["rule_pack_version"] = values.get("rule_pack_version") or pack.get(
                    "version"
                )

        spec = CourseRunSpec(**values)

        created = self.repository.create(spec)

        logger.info(
            "Created course run spec %s (run %s)",
            created.id,
            created.course_run_id,
        )

        return created