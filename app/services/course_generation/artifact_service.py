"""Persists course generation artifacts (shared state, docs, logs, reports) to blob + DB."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import azure_storage_settings
from app.core.storage.azure_blob_client import AzureBlobClient, LocalUploadStore
from app.models.course_generation.course_generation_job.job_artifact import CourseGenerationJobArtifact
from app.repositories.course_generation.course_generation_job_artifact_repository import (
    CourseGenerationJobArtifactRepository,
)

logger = logging.getLogger(__name__)


class _ArtifactsBlobClient(AzureBlobClient):
    """Same Azure Blob Storage account, but targeting the artifacts container."""

    @property
    def container_name(self) -> str:
        return self._settings.course_generation_artifacts_container_name


class CourseGenerationArtifactService:
    """Uploads artifact bytes and records them in `course_generation_job_artifacts`."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseGenerationJobArtifactRepository(db)
        self._blob_client = _ArtifactsBlobClient(azure_storage_settings)
        self._local_store = LocalUploadStore(azure_storage_settings)

    def persist_bytes(
        self,
        *,
        job_id: str,
        course_run_id: str,
        artifact_type: str,
        stage_name: str,
        file_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> CourseGenerationJobArtifact:
        blob_path = f"{course_run_id}/{job_id}/{stage_name}/{file_name}"

        if self._blob_client.is_ready():
            self._blob_client.upload_bytes(blob_path, content, content_type=content_type)
        else:
            self._local_store.save_bytes(blob_path, content)
            logger.warning(
                "[course_generation] Azure Blob Storage not configured — artifact saved locally | %s",
                blob_path,
            )

        artifact = CourseGenerationJobArtifact(
            job_id=job_id,
            course_run_id=course_run_id,
            artifact_type=artifact_type,
            stage_name=stage_name,
            file_name=file_name,
            blob_path=blob_path,
            content_type=content_type,
        )
        created = self.repository.create(artifact)
        self.db.flush()
        return created

    def persist_file(
        self,
        *,
        job_id: str,
        course_run_id: str,
        artifact_type: str,
        stage_name: str,
        local_path: str,
        content_type: str = "application/octet-stream",
    ) -> CourseGenerationJobArtifact:
        with open(local_path, "rb") as handle:
            content = handle.read()
        file_name = local_path.rsplit("/", 1)[-1]
        return self.persist_bytes(
            job_id=job_id,
            course_run_id=course_run_id,
            artifact_type=artifact_type,
            stage_name=stage_name,
            file_name=file_name,
            content=content,
            content_type=content_type,
        )
