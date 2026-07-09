"""Pydantic schemas for document upload and ingestion status APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UploadDocumentResponse(BaseModel):
    """Response returned after a successful document upload."""

    model_config = ConfigDict(populate_by_name=True)

    blob_path: str = Field(serialization_alias="blobPath")
    upload_folder: str = Field(serialization_alias="uploadFolder")
    document_id: str = Field(serialization_alias="documentId")


class IngestionStatusResponse(BaseModel):
    """Polling payload for background ingestion progress."""

    document_id: str
    status: str
    total_chunks: int = 0
    error: str | None = None
    updated_at: float
