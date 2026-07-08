"""Pydantic request/response schemas for the Course Run Rule Override API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CREATED_BY = "system"


class CourseRunRuleOverrideCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_run_id: str = Field(..., min_length=1, max_length=64, description="Id of the course run this override belongs to")
    rule_name: str = Field(..., min_length=1, max_length=255)
    original_value_json: str | None = Field(default=None, description="Original rule value, serialized as JSON")
    override_value_json: str | None = Field(default=None, description="Overridden rule value, serialized as JSON")
    created_by: str | None = Field(default=None, max_length=255)

    @field_validator("created_by", mode="before")
    @classmethod
    def default_created_by(cls, value: str | None) -> str:
        return value or DEFAULT_CREATED_BY


class CourseRunRuleOverrideData(BaseModel):
    """Course-run-rule-override record as returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_run_id: str
    rule_name: str
    original_value_json: str | None
    override_value_json: str | None
    created_by: str
    created_at: datetime


class CourseRunRuleOverrideResponse(BaseModel):
    """Standard API response envelope for the Course Run Rule Override endpoint."""

    success: bool
    data: CourseRunRuleOverrideData
