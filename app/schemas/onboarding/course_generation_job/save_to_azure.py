"""Request/response schemas for POST /jobs/{job_id}/artifacts/save-to-azure."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    RenderDocxRequest,
)


class SaveToAzureRequest(BaseModel):
    """Frontend editor Save-to-Azure payload.

    Reuses ``RenderDocxRequest`` for the full course snapshot. Path ``job_id`` is
    authoritative — clients must not send version numbers, blob paths, or IDs.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    course: RenderDocxRequest
    course_slug: str | None = Field(default=None, alias="courseSlug")


class SaveToAzureMetaResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_word_count: int = Field(alias="totalWordCount")
    section_count: int = Field(alias="sectionCount")
    chapter_count: int = Field(alias="chapterCount")
    estimated_read_time: str = Field(alias="estimatedReadTime")


class SaveToAzureResponse(BaseModel):
    """Response contract compatible with FE ``SaveToAzureResponse``.

    Includes version identifiers and optional forward-looking fields
    (``courseId``, ``courseRunId``, ``meta``, ``canonicalJsonBlobPath``).
    """

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["uploaded"] = "uploaded"
    job_id: str = Field(serialization_alias="jobId")
    file_name: str = Field(serialization_alias="fileName")
    blob_path: str = Field(serialization_alias="blobPath")
    pdf_blob_path: str | None = Field(default=None, serialization_alias="pdfBlobPath")
    container_name: str = Field(serialization_alias="containerName")
    saved_at: str | None = Field(default=None, serialization_alias="savedAt")
    warning: str | None = None
    version_number: int = Field(serialization_alias="versionNumber")
    version_id: str = Field(serialization_alias="versionId")
    state_blob_path: str | None = Field(default=None, serialization_alias="stateBlobPath")
    course_id: int = Field(serialization_alias="courseId")
    course_run_id: int = Field(serialization_alias="courseRunId")
    canonical_json_blob_path: str = Field(serialization_alias="canonicalJsonBlobPath")
    docx_blob_path: str = Field(serialization_alias="docxBlobPath")
    meta: SaveToAzureMetaResponse | dict[str, Any]


__all__ = [
    "SaveToAzureMetaResponse",
    "SaveToAzureRequest",
    "SaveToAzureResponse",
]
