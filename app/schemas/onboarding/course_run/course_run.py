"""Pydantic request/response schemas for the Course Run API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.onboarding.course_run.course_run_input import (
    CourseRunInputData,
    CourseRunInputNestedCreate,
)
from app.schemas.onboarding.course_run.course_run_rule_override import (
    CourseRunRuleOverrideData,
    CourseRunRuleOverrideNestedCreate,
)
from app.schemas.onboarding.course_run.course_run_spec import (
    CourseRunSpecData,
    CourseRunSpecNestedCreate,
)

DEFAULT_CREATED_BY = "system"

CourseRunStatus = Literal["DRAFT", "GENERATING", "GENERATED", "FAILED", "CANCELLED"]


class CourseRunCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here.

    The nested `spec`/`inputs`/`rule_overrides` are created together with the
    run in a single transaction so the frontend only ever calls this one
    endpoint instead of orchestrating four separate requests itself.
    """

    course_id: int = Field(..., description="Id of the course this run belongs to")
    created_from_run_id: str | None = Field(
        default=None,
        max_length=64,
        description="Id of the run this one was branched from, if any",
    )
    created_by: str | None = Field(
        default=None,
        max_length=255,
        description="Who created this run; defaults to 'system' if omitted",
    )
    spec: CourseRunSpecNestedCreate | None = Field(
        default=None,
        description="Generation-parameter spec to create alongside the run",
    )
    inputs: list[CourseRunInputNestedCreate] = Field(
        default_factory=list,
        description="Source inputs to create alongside the run",
    )
    rule_overrides: list[CourseRunRuleOverrideNestedCreate] = Field(
        default_factory=list,
        description="Rule-pack overrides to create alongside the run",
    )


class CourseRunInternal(BaseModel):
    """Server-side record ready to persist."""

    course_id: int
    version_number: int
    created_from_run_id: int | None = None
    status_code: CourseRunStatus = Field(default="DRAFT")
    created_by: str = Field(default=DEFAULT_CREATED_BY)

    @field_validator("created_by", mode="before")
    @classmethod
    def default_created_by(cls, value: str | None) -> str:
        return value or DEFAULT_CREATED_BY


class CourseRunData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int 
    course_id: int
    version_number: int
    created_from_run_id: int | None
    status_code: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class CourseRunResponse(BaseModel):
    """Standard API response envelope for the Course Run endpoint."""

    success: bool
    data: CourseRunData


class CourseRunDetailData(BaseModel):
    """Course run together with everything created alongside it."""

    run: CourseRunData
    spec: CourseRunSpecData | None
    inputs: list[CourseRunInputData]
    rule_overrides: list[CourseRunRuleOverrideData]


class CourseRunDetailResponse(BaseModel):
    """Response envelope for the orchestrated `POST /course-runs` endpoint."""

    success: bool
    data: CourseRunDetailData
