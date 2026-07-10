"""HTTP routes for the Dashboard screen."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.auth.dependencies import require_valid_token
from app.schemas.dashboard.summary import DashboardSummaryResponse
from app.services.dashboard.dashboard_service import DashboardService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(require_valid_token)],
)


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_dashboard_summary(
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    """Return total, in-progress, and completed course-generation counts."""
    try:
        summary = DashboardService(db).get_summary()
    except Exception:
        logger.exception("Failed to load dashboard summary")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load dashboard summary. Please try again.",
        )

    return DashboardSummaryResponse(success=True, data=summary)
