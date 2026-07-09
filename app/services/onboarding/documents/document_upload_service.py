"""Business logic for document upload and ingestion status."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException, UploadFile, status

from app.ai.ingestion.metadata import IngestionMetadata, build_ingestion_metadata
from app.core.storage.azure_blob_client import AzureBlobClient, LocalUploadStore
from app.core.storage.upload_paths import (
    CONTENT_TYPES,
    MAX_UPLOAD_BYTES,
    parse_course_topic,
    uploads_blob_path,
    validate_upload_filename,
)
from app.schemas.onboarding.documents.browse import BrowseResponse, StorageEntry
from app.schemas.onboarding.documents.upload import (
    IngestionStatusResponse,
    UploadDocumentResponse,
)
from app.services.onboarding.documents.ingestion_status_store import (
    get_status,
    set_status,
)

logger = logging.getLogger(__name__)

_INGESTABLE_EXTENSIONS = frozenset({".docx", ".pdf"})


class DocumentUploadService:
    """Upload source documents to Azure Blob Storage (or local fallback)."""

    def __init__(
        self,
        *,
        blob_client: AzureBlobClient | None = None,
        local_store: LocalUploadStore | None = None,
    ) -> None:
        self._blob_client = blob_client or AzureBlobClient()
        self._local_store = local_store or LocalUploadStore()

    async def upload_document(
        self,
        *,
        background_tasks: BackgroundTasks,
        file: UploadFile,
        course_topic: str,
        course_id: str | None = None,
        jurisdiction: str | None = None,
        source_type: str | None = None,
        source_priority: str | None = None,
        source_intent: str | None = None,
    ) -> UploadDocumentResponse:
        filename = validate_upload_filename(file.filename)
        folder = parse_course_topic(course_topic)
        content = await self._read_upload_bytes(file)
        ext = Path(filename).suffix.lower()
        blob_path = uploads_blob_path(folder, filename)
        document_id = uuid.uuid4().hex[:12]

        ingestion_metadata = build_ingestion_metadata(
            course_id=course_id or folder,
            document_id=document_id,
            jurisdiction=jurisdiction,
            source_file=filename,
            source_type=source_type,
            source_priority=source_priority,
            source_intent=source_intent,
        )

        if self._blob_client.is_ready():
            self._upload_to_azure(blob_path, content, ext)
        else:
            dest = self._local_store.save_bytes(blob_path, content)
            logger.info("[upload] Saved %s → %s (%d bytes)",
                        filename, dest, len(content))

        if ext in _INGESTABLE_EXTENSIONS:
            set_status(document_id, "pending")
            background_tasks.add_task(
                _run_ingestion_background,
                content,
                filename,
                document_id,
                ingestion_metadata,
            )

        return UploadDocumentResponse(
            blob_path=blob_path,
            upload_folder=folder,
            document_id=document_id,
        )

    def get_ingestion_status(self, document_id: str) -> IngestionStatusResponse:
        record = get_status(document_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No ingestion status found for document '{document_id}'.",
            )
        return IngestionStatusResponse(
            document_id=str(record["document_id"]),
            status=str(record["status"]),
            total_chunks=int(record.get("total_chunks") or 0),
            error=record.get("error"),  # type: ignore[arg-type]
            updated_at=float(record["updated_at"]),
        )

    def browse_uploads(self, prefix: str) -> BrowseResponse:
        """Non-recursive listing of folders/files under `prefix` (relative to the uploads root)."""
        normalized = prefix.strip("/")
        full_prefix = f"{normalized}/" if normalized else ""

        if self._blob_client.is_ready():
            raw_entries = self._blob_client.list_entries(full_prefix)
            source = "azure"
            container_name = self._blob_client.container_name
        else:
            raw_entries = self._local_store.list_entries(full_prefix)
            source = "local"
            container_name = None

        entries = [
            StorageEntry(
                name=e.name,
                path=e.path,
                entry_type=e.entry_type,
                size=e.size,
                last_modified=e.last_modified,
                content_type=e.content_type,
            )
            for e in raw_entries
        ]
        files = [e for e in entries if e.entry_type == "file"]
        folders = [e for e in entries if e.entry_type == "folder"]

        return BrowseResponse(
            prefix=prefix,
            entries=entries,
            total_files=len(files),
            total_folders=len(folders),
            total_size=sum(f.size or 0 for f in files),
            source=source,
            container_name=container_name,
        )

    def _upload_to_azure(self, blob_path: str, content: bytes, ext: str) -> None:
        try:
            self._blob_client.upload_bytes(
                blob_path,
                content,
                content_type=CONTENT_TYPES.get(
                    ext, "application/octet-stream"),
            )
        except Exception as exc:
            logger.exception(
                "[upload] Failed to upload to Azure Blob: blob_path=%s", blob_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload file to storage — see server logs.",
            ) from exc

    @staticmethod
    async def _read_upload_bytes(file: UploadFile) -> bytes:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )
        return content


def _run_ingestion_background(
    content: bytes,
    filename: str,
    document_id: str,
    metadata: IngestionMetadata | None,
) -> None:
    """Sync wrapper for FastAPI BackgroundTasks — runs async ingestion."""
    asyncio.run(_ingest_document(content, filename, document_id, metadata))


async def _ingest_document(
    content: bytes,
    filename: str,
    document_id: str,
    metadata: IngestionMetadata | None,
) -> None:
    set_status(document_id, "processing")
    suffix = Path(filename).suffix
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(content)
            tmp_path = handle.name

        from app.ai.ingestion.service import IngestionOrchestrator

        orchestrator = IngestionOrchestrator.get_instance()
        result = await orchestrator.ingest(
            tmp_path,
            document_id,
            filename,
            metadata,
        )
        set_status(
            document_id,
            result.status,  # type: ignore[arg-type]
            total_chunks=result.total_chunks,
        )
    except Exception as exc:
        logger.exception(
            "[upload] Ingestion failed for document_id=%s", document_id)
        set_status(document_id, "failed", error=str(exc))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
