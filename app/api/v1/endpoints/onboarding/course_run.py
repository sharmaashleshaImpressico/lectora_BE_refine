"""HTTP routes for the Course Run, Spec, Input and Rule Override APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.auth.dependencies import require_valid_token
from app.schemas.onboarding.course_run.course_run import (
    CourseRunCreate,
    CourseRunData,
    CourseRunDetailData,
    CourseRunDetailResponse,
    CourseRunResponse,
)
from app.schemas.onboarding.course_run.course_run_input import (
    CourseRunInputCreate,
    CourseRunInputData,
    CourseRunInputResponse,
)
from app.schemas.onboarding.course_run.course_run_rule_override import (
    CourseRunRuleOverrideCreate,
    CourseRunRuleOverrideData,
    CourseRunRuleOverrideResponse,
)
from app.schemas.onboarding.course_run.course_run_spec import (
    CourseRunSpecCreate,
    CourseRunSpecData,
    CourseRunSpecResponse,
)
from app.services.onboarding.course_run.course_run_input_service import CourseRunInputService
from app.services.onboarding.course_run.course_run_rule_override_service import (
    CourseRunRuleOverrideService,
)
from app.services.onboarding.course_run.course_run_service import (
    CourseNotFoundError,
    CourseRunNotFoundError,
    CourseRunService,
)
from app.services.onboarding.course_run.course_run_spec_service import CourseRunSpecService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Course Run"],
    dependencies=[Depends(require_valid_token)],
)


@router.post(
    "/course-runs",
    response_model=CourseRunDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_course_run(
    payload: CourseRunCreate,
    db: Session = Depends(get_db),
) -> CourseRunDetailResponse:
    """Create a new run (generation attempt) for a course.

    Also creates the run's spec, inputs, and rule overrides in the same
    request. All writes share one `db` session, which `get_db` commits once
    at the end of the request (and rolls back entirely on any error), so the
    whole operation is atomic — the frontend only needs to call this one
    endpoint.
    """
    try:
        course_run = CourseRunService(db).create_course_run(payload)
        course_run_id = str(course_run.id)

        spec = None
        if payload.spec is not None:
            spec = CourseRunSpecService(db).create_spec(payload.spec.to_create(course_run_id))

        inputs = [
            CourseRunInputService(db).create_input(item.to_create(course_run_id))
            for item in payload.inputs
        ]

        rule_overrides = [
            CourseRunRuleOverrideService(db).create_override(item.to_create(course_run_id))
            for item in payload.rule_overrides
        ]
    except (CourseNotFoundError, CourseRunNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Failed to create course run")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the course run. Please try again.",
        )

    return CourseRunDetailResponse(
        success=True,
        data=CourseRunDetailData(
            run=CourseRunData.model_validate(course_run),
            spec=CourseRunSpecData.model_validate(spec) if spec is not None else None,
            inputs=[CourseRunInputData.model_validate(item) for item in inputs],
            rule_overrides=[CourseRunRuleOverrideData.model_validate(item) for item in rule_overrides],
        ),
    )


@router.post(
    "/course-run-specs",
    response_model=CourseRunSpecResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_course_run_spec(
    payload: CourseRunSpecCreate,
    db: Session = Depends(get_db),
) -> CourseRunSpecResponse:
    """Create the generation-parameter spec for a course run."""
    try:
        service = CourseRunSpecService(db)
        spec = service.create_spec(payload)
    except CourseRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Failed to create course run spec")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the course run spec. Please try again.",
        )

    return CourseRunSpecResponse(success=True, data=CourseRunSpecData.model_validate(spec))


@router.post(
    "/course-run-inputs",
    response_model=CourseRunInputResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_course_run_input(
    payload: CourseRunInputCreate,
    db: Session = Depends(get_db),
) -> CourseRunInputResponse:
    """Record a previously-uploaded source input against a course run."""
    try:
        service = CourseRunInputService(db)
        course_run_input = service.create_input(payload)
    except CourseRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Failed to create course run input")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the course run input. Please try again.",
        )

    return CourseRunInputResponse(success=True, data=CourseRunInputData.model_validate(course_run_input))


@router.post(
    "/course-run-rule-overrides",
    response_model=CourseRunRuleOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_course_run_rule_override(
    payload: CourseRunRuleOverrideCreate,
    db: Session = Depends(get_db),
) -> CourseRunRuleOverrideResponse:
    """Record a rule-pack override applied to a course run."""
    try:
        service = CourseRunRuleOverrideService(db)
        override = service.create_override(payload)
    except CourseRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Failed to create course run rule override")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the course run rule override. Please try again.",
        )

    return CourseRunRuleOverrideResponse(success=True, data=CourseRunRuleOverrideData.model_validate(override))
