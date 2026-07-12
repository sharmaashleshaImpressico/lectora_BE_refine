"""Request schemas for the editor CourseContent snapshot (render-docx / sync-shaped).

Mirrors the frontend ``CourseContent`` / legacy ``SyncCoursePayload`` contracts so the
editor can POST ``getCourseSnapshot()`` without reshaping. Fields that are
frontend-only metadata (``jobId``, ``courseType``, ``generatedAt``) are accepted
and ignored by the render pipeline.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CourseSectionInput(BaseModel):
    """One nested editor section (chapter, subtopic, intro, conclusion, …)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    title: str = ""
    level: int = 1
    section_type: str = Field(default="content", alias="sectionType")
    content: str = ""
    paragraphs: list[dict[str, Any]] = Field(default_factory=list)
    learning_objectives: list[str] = Field(
        default_factory=list, alias="learningObjectives"
    )
    word_count: int = Field(default=0, alias="wordCount")
    has_knowledge_check: bool = Field(default=False, alias="hasKnowledgeCheck")
    order: int = 0
    children: list[CourseSectionInput] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)


class CourseContentMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    total_word_count: int = Field(default=0, alias="totalWordCount")
    section_count: int = Field(default=0, alias="sectionCount")
    chapter_count: int = Field(default=0, alias="chapterCount")
    estimated_read_time: str = Field(default="", alias="estimatedReadTime")


class RenderDocxRequest(BaseModel):
    """Full frontend editor snapshot used as the sole source of truth for DOCX render.

    Compatible with FE ``CourseContent`` and legacy ``SyncCoursePayload``. Extra
    metadata fields are optional and ignored by the mapper.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    course_title: str = Field(default="Untitled Course", alias="courseTitle")
    sections: list[CourseSectionInput] = Field(default_factory=list)
    meta: CourseContentMeta | dict[str, Any] = Field(default_factory=dict)

    # Frontend metadata — accepted, not used for rendering.
    job_id: str | None = Field(default=None, alias="jobId")
    course_type: str | None = Field(default=None, alias="courseType")
    generated_at: str | None = Field(default=None, alias="generatedAt")


CourseSectionInput.model_rebuild()

__all__ = [
    "CourseSectionInput",
    "CourseContentMeta",
    "RenderDocxRequest",
]
