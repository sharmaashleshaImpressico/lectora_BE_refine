"""Persists course generation artifacts (shared state, docs, logs, reports) to blob + DB."""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app.core.config import azure_storage_settings
from app.core.storage.azure_blob_client import AzureBlobClient, LocalUploadStore
from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_STAGE_TO_GENERATION,
    ARTIFACT_TYPE_COURSE_SPEC,
    ARTIFACT_TYPE_TO_OUTLINE,
)
from app.models.course_generation.course_generation_job.job_artifact import CourseGenerationJobArtifact
from app.repositories.course_generation.course_generation_job_artifact_repository import (
    CourseGenerationJobArtifactRepository,
)

logger = logging.getLogger(__name__)

_TO_OUTLINE_FILE_NAME = "to_outline.json"
_COURSE_SPEC_FILE_NAME = "course_spec.json"


class ArtifactAlreadyExistsError(Exception):
    """Raised when an upload would overwrite a previously stored artifact."""


def _slugify_course_title(course_title: str) -> str:
    """Turn a course title into a safe, stable blob-path segment."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", course_title or "").strip("-").lower()
    return slug or "untitled-course"


class ArtifactsBlobClient(AzureBlobClient):
    """Same Azure Blob Storage account, but targeting the artifacts container.

    Public (not underscore-prefixed) so other modules — e.g. the data loader
    resolving `CourseRunSpec.uploaded_outline_blob_path` — can read blobs
    written here without going through `CourseGenerationArtifactService`.
    """

    @property
    def container_name(self) -> str:
        return self._settings.course_generation_artifacts_container_name


# Backward-compatible alias for the old private name.
_ArtifactsBlobClient = ArtifactsBlobClient


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
        course_title: str,
        artifact_type: str,
        stage_name: str,
        file_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> CourseGenerationJobArtifact:
        """Upload artifact bytes under `<course_title>/<job_id>/<file_name>` and record it."""
        title_slug = _slugify_course_title(course_title)
        blob_path = f"{title_slug}/{job_id}/{file_name}"

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
        course_title: str,
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
            course_title=course_title,
            artifact_type=artifact_type,
            stage_name=stage_name,
            file_name=file_name,
            content=content,
            content_type=content_type,
        )

    def persist_to_outline_and_course_spec(
        self,
        *,
        job_id: str,
        course_run_id: str,
        course_title: str,
        to_outline_document: dict,
        course_spec: dict,
    ) -> tuple[CourseGenerationJobArtifact, CourseGenerationJobArtifact]:
        """Upload the canonical to_outline.json and step-04 course_spec.json.

        Folder structure: `course-generation-artifacts/<course_title>/<job_id>/`.
        Never overwrites a previous course run's artifacts — each `job_id` gets
        its own folder, and an existing blob at the target path aborts the upload.
        """
        title_slug = _slugify_course_title(course_title)

        to_outline_blob_path = f"{title_slug}/{job_id}/{_TO_OUTLINE_FILE_NAME}"
        course_spec_blob_path = f"{title_slug}/{job_id}/{_COURSE_SPEC_FILE_NAME}"

        to_outline_artifact = self._persist_json_no_overwrite(
            job_id=job_id,
            course_run_id=course_run_id,
            artifact_type=ARTIFACT_TYPE_TO_OUTLINE,
            stage_name=ARTIFACT_STAGE_TO_GENERATION,
            file_name=_TO_OUTLINE_FILE_NAME,
            blob_path=to_outline_blob_path,
            payload=to_outline_document,
        )
        course_spec_artifact = self._persist_json_no_overwrite(
            job_id=job_id,
            course_run_id=course_run_id,
            artifact_type=ARTIFACT_TYPE_COURSE_SPEC,
            stage_name=ARTIFACT_STAGE_TO_GENERATION,
            file_name=_COURSE_SPEC_FILE_NAME,
            blob_path=course_spec_blob_path,
            payload=course_spec,
        )
        return to_outline_artifact, course_spec_artifact

    def _persist_json_no_overwrite(
        self,
        *,
        job_id: str,
        course_run_id: str,
        artifact_type: str,
        stage_name: str,
        file_name: str,
        blob_path: str,
        payload: dict,
    ) -> CourseGenerationJobArtifact:
        store = self._blob_client if self._blob_client.is_ready() else self._local_store

        try:
            already_exists = store.exists(blob_path)
        except Exception:
            logger.exception(
                "[course_generation] Failed to check for existing artifact | %s", blob_path
            )
            raise

        if already_exists:
            raise ArtifactAlreadyExistsError(
                f"Artifact already exists at '{blob_path}' — refusing to overwrite a "
                "previous course run's artifacts."
            )

        content = json.dumps(payload, indent=2, default=str).encode("utf-8")

        try:
            if self._blob_client.is_ready():
                self._blob_client.upload_bytes(blob_path, content, content_type="application/json")
            else:
                self._local_store.save_bytes(blob_path, content)
                logger.warning(
                    "[course_generation] Azure Blob Storage not configured — "
                    "artifact saved locally | %s",
                    blob_path,
                )
        except Exception:
            logger.exception(
                "[course_generation] Failed to upload artifact | job_id=%s course_run_id=%s path=%s",
                job_id,
                course_run_id,
                blob_path,
            )
            raise

        logger.info(
            "[course_generation] Artifact uploaded | job_id=%s course_run_id=%s type=%s path=%s",
            job_id,
            course_run_id,
            artifact_type,
            blob_path,
        )

        artifact = CourseGenerationJobArtifact(
            job_id=job_id,
            course_run_id=course_run_id,
            artifact_type=artifact_type,
            stage_name=stage_name,
            file_name=file_name,
            blob_path=blob_path,
            content_type="application/json",
        )
        created = self.repository.create(artifact)
        self.db.flush()
        return created
