"""HTTP routes for document upload and ingestion status."""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.schemas.onboarding.documents.upload import (
    IngestionStatusResponse,
    UploadDocumentResponse,
)
from app.services.onboarding.documents.document_upload_service import DocumentUploadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post(
    "/upload",
    response_model=UploadDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="A .docx or .pdf source document, or a .json Timed Outline file.",
    ),
    course_topic: str = Form(
        ...,
        alias="courseTopic",
        description="Course topic / folder name (required). Creates {topic}/ in uploaded-documents.",
    ),
    course_id: str | None = Form(
        default=None,
        alias="courseId",
        description="Optional stable course identifier for RAG chunk metadata.",
    ),
    jurisdiction: str | None = Form(
        default=None,
        description="Optional jurisdiction label for RAG chunk metadata.",
    ),
    source_type: str | None = Form(
        default=None,
        alias="sourceType",
        description="Optional source role/type for RAG chunk metadata.",
    ),
    source_priority: str | None = Form(
        default=None,
        alias="sourcePriority",
        description="Optional source priority for RAG chunk metadata.",
    ),
    source_intent: str | None = Form(
        default=None,
        alias="sourceIntent",
        description="Optional extract hint or source intent for RAG chunk metadata.",
    ),
) -> UploadDocumentResponse:
    """
    Save an uploaded DOCX, PDF, or JSON file under ``{course_topic}/{filename}``
    in the uploaded-documents Azure container (or local dev storage).

    DOCX and PDF files are stored as-is — no conversion is performed.
    A0 handles PDFs natively via ``PDFSourceParser``.

    JSON files must be valid Timed Outline objects. A0 detects the ``.json``
    extension and uses the fast-path loader, skipping outline re-generation.

    The folder name is derived from the mandatory ``courseTopic`` field (sanitized).
  """
    service = DocumentUploadService()
    try:
        return await service.upload_document(
            background_tasks=background_tasks,
            file=file,
            course_topic=course_topic,
            course_id=course_id,
            jurisdiction=jurisdiction,
            source_type=source_type,
            source_priority=source_priority,
            source_intent=source_intent,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        logger.exception("Failed to upload document")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not upload the document. Please try again.",
        )


@router.get(
    "/{document_id}/ingestion-status",
    response_model=IngestionStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_ingestion_status(document_id: str) -> IngestionStatusResponse:
    """Poll background ingestion status for a previously uploaded document."""
    return DocumentUploadService().get_ingestion_status(document_id)
