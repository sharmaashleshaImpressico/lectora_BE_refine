"""HTTP routes for browsing uploaded-document storage (Azure Blob or local fallback)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.onboarding.documents.browse import BrowseResponse
from app.services.onboarding.documents.document_upload_service import DocumentUploadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Storage"])


@router.get(
    "/uploaded-documents/browse",
    response_model=BrowseResponse,
    status_code=status.HTTP_200_OK,
)
def browse_uploaded_documents(
    prefix: str = Query(default="", description="Folder prefix, relative to the uploads root."),
) -> BrowseResponse:
    """Non-recursive listing of the folders/files immediately under `prefix`."""
    try:
        return DocumentUploadService().browse_uploads(prefix)
    except Exception:
        logger.exception("Failed to browse uploaded-documents storage: prefix=%r", prefix)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not list files. Please try again.",
        )
