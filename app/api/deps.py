"""Shared FastAPI dependencies for the API layer."""

from __future__ import annotations

from fastapi import Depends
from semantic_kernel import Kernel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.kernel.factory import create_kernel
from app.services.onboarding.course_generation.save_to_azure_service import (
    SaveToAzureService,
)

__all__ = ["get_db", "get_kernel", "get_save_to_azure_service"]


def get_kernel() -> Kernel:
    """FastAPI dependency that returns a configured Semantic Kernel instance."""
    return create_kernel()


def get_save_to_azure_service(db: Session = Depends(get_db)) -> SaveToAzureService:
    """Request-scoped Save-to-Azure application service (shares the request DB session)."""
    return SaveToAzureService(db)