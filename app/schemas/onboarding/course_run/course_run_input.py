"""Pydantic request/response schemas for the Course Run Input API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_UPLOADED_BY = "system"


class CourseRunInputCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_run_id: str = Field(..., min_length=1, max_length=64, description="Id of the course run this input belongs to")
    input_type: str = Field(..., min_length=1, max_length=100, description="Kind of input, e.g. study_guide, timed_outline")
    original_filename: str = Field(..., min_length=1, max_length=512)
    blob_path: str = Field(..., min_length=1, max_length=1024, description="Path of the already-uploaded blob")
    file_size: int | None = Field(default=None, ge=0)
    mime_type: str | None = Field(default=None, max_length=255)
    source_intent: str | None = None
    uploaded_by: str | None = Field(default=None, max_length=255)

    @field_validator("uploaded_by", mode="before")
    @classmethod
    def default_uploaded_by(cls, value: str | None) -> str:
        return value or DEFAULT_UPLOADED_BY


class CourseRunInputData(BaseModel):
    """Course-run-input record as returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_run_id: str
    input_type: str
    original_filename: str
    blob_path: str
    file_size: int | None
    mime_type: str | None
    source_intent: str | None
    uploaded_by: str
    uploaded_at: datetime


class CourseRunInputResponse(BaseModel):
    """Standard API response envelope for the Course Run Input endpoint."""

    success: bool
    data: CourseRunInputData
