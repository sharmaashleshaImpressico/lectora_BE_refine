"""Pydantic request/response schemas for the Course Run Rule Override API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseRunRuleOverrideCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_run_id: int = Field(..., description="Id of the course run this override belongs to")
    rule_name: str = Field(..., min_length=1, max_length=255)
    original_value_json: str | None = Field(default=None, description="Original rule value, serialized as JSON")
    override_value_json: str | None = Field(default=None, description="Overridden rule value, serialized as JSON")
    created_by: str | None = Field(default=None, max_length=255)


class CourseRunRuleOverrideNestedCreate(BaseModel):
    """Override fields accepted when nested inside `CourseRunCreate`.

    Same as `CourseRunRuleOverrideCreate` minus `course_run_id`, which the
    backend fills in itself once the parent run has been created.
    """

    rule_name: str = Field(..., min_length=1, max_length=255)
    original_value_json: str | None = Field(default=None, description="Original rule value, serialized as JSON")
    override_value_json: str | None = Field(default=None, description="Overridden rule value, serialized as JSON")
    created_by: str | None = Field(default=None, max_length=255)

    def to_create(self, course_run_id: str) -> "CourseRunRuleOverrideCreate":
        return CourseRunRuleOverrideCreate(course_run_id=course_run_id, **self.model_dump())


class CourseRunRuleOverrideData(BaseModel):
    """Course-run-rule-override record as returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_run_id: int
    rule_name: str
    original_value_json: str | None
    override_value_json: str | None
    created_by: str
    created_at: datetime


class CourseRunRuleOverrideResponse(BaseModel):
    """Standard API response envelope for the Course Run Rule Override endpoint."""

    success: bool
    data: CourseRunRuleOverrideData
