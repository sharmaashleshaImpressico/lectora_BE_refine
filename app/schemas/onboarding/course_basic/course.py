"""Pydantic request/response schemas for the Course Basic API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ID_PREFIX = "CRS-"
DEFAULT_COURSE_TYPE = "General"

CourseStatus = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]


def generate_id() -> str:
    """Generate a unique, readable course id, e.g. CRS-9F3A1C2B."""
    return f"{ID_PREFIX}{uuid.uuid4().hex[:8].upper()}"


class CourseBasicCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_title: str = Field(..., min_length=1, description="Title of the course")
    course_type: str = Field(..., min_length=1, max_length=100, description="Course type selected in the wizard")
    created_by: str | None = Field(
        default=None,
        max_length=255,
        description="Who created this course; defaults to the authenticated user if omitted",
    )


class CourseBasicUpdate(BaseModel):
    """Payload for replacing a course's basic details."""

    course_title: str = Field(..., min_length=1, description="Title of the course")
    course_type: str = Field(..., min_length=1, max_length=100, description="Course type selected in the wizard")
    status_code: CourseStatus = Field(..., description="Course lifecycle status")
    created_by: str = Field(..., min_length=1, max_length=255, description="Who created or owns this course")


class CourseBasicInternal(BaseModel):
    """Server-side record with auto-generated fields, ready to persist."""

    course_title: str
    course_code: str = Field(default_factory=generate_id)
    course_type: str = Field(default=DEFAULT_COURSE_TYPE)
    status_code: CourseStatus = Field(default="DRAFT")
    created_by: str = Field(..., min_length=1, max_length=255)


class CourseBasicData(BaseModel):
    """Course record as returned to the frontend."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    course_code: str
    course_title: str = Field(validation_alias="title")
    course_type: str
    status_code: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class CourseBasicResponse(BaseModel):
    """Standard API response envelope for the Course Basic endpoint."""

    success: bool
    data: CourseBasicData
