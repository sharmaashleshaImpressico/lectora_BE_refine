"""Pydantic request/response schemas for the Course Run Spec API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseRunSpecCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_run_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Id of the course run this spec belongs to",
    )
    course_scope: str | None = None
    duration_hours: float | None = None
    difficulty_level: str | None = Field(default=None, max_length=100)
    target_audience: str | None = None
    learner_experience_level: str | None = Field(default=None, max_length=100)
    learner_outcomes: str | None = None
    required_topics_json: str | None = None
    learning_objectives_json: str | None = None
    tone: str | None = Field(default=None, max_length=255)
    depth: str | None = Field(default=None, max_length=100)
    emphasis: str | None = None
    avoid_instructions: str | None = None
    include_case_studies: bool | None = None
    include_examples: bool | None = None
    course_structure_mode: str | None = Field(default=None, max_length=100)
    uploaded_outline_blob_path: str | None = Field(default=None, max_length=512)
    rule_pack_id: str | None = Field(default=None, max_length=255)
    rule_pack_version: str | None = Field(default=None, max_length=100)
    effective_rule_pack_blob_path: str | None = Field(default=None, max_length=512)
    outline_notes: str | None = None


class CourseRunSpecNestedCreate(BaseModel):
    """Spec fields accepted when nested inside `CourseRunCreate`.

    Same as `CourseRunSpecCreate` minus `course_run_id`, which the backend
    fills in itself once the parent run has been created.
    """

    course_scope: str | None = None
    duration_hours: float | None = None
    difficulty_level: str | None = Field(default=None, max_length=100)
    target_audience: str | None = None
    learner_experience_level: str | None = Field(default=None, max_length=100)
    learner_outcomes: str | None = None
    required_topics_json: str | None = None
    learning_objectives_json: str | None = None
    tone: str | None = Field(default=None, max_length=255)
    depth: str | None = Field(default=None, max_length=100)
    emphasis: str | None = None
    avoid_instructions: str | None = None
    include_case_studies: bool | None = None
    include_examples: bool | None = None
    course_structure_mode: str | None = Field(default=None, max_length=100)
    uploaded_outline_blob_path: str | None = Field(default=None, max_length=512)
    rule_pack_id: str | None = Field(default=None, max_length=255)
    rule_pack_version: str | None = Field(default=None, max_length=100)
    effective_rule_pack_blob_path: str | None = Field(default=None, max_length=512)
    outline_notes: str | None = None

    def to_create(self, course_run_id: str) -> "CourseRunSpecCreate":
        return CourseRunSpecCreate(course_run_id=course_run_id, **self.model_dump())


class CourseRunSpecData(BaseModel):
    """Course-run-spec record as returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_run_id: int
    course_scope: str | None
    duration_hours: float | None
    difficulty_level: str | None
    target_audience: str | None
    learner_experience_level: str | None
    learner_outcomes: str | None
    required_topics_json: str | None
    learning_objectives_json: str | None
    tone: str | None
    depth: str | None
    emphasis: str | None
    avoid_instructions: str | None
    include_case_studies: bool | None
    include_examples: bool | None
    course_structure_mode: str | None
    uploaded_outline_blob_path: str | None
    rule_pack_id: str | None
    rule_pack_version: str | None
    effective_rule_pack_blob_path: str | None
    outline_notes: str | None
    created_at: datetime
    updated_at: datetime


class CourseRunSpecResponse(BaseModel):
    """Standard API response envelope for the Course Run Spec endpoint."""

    success: bool
    data: CourseRunSpecData
