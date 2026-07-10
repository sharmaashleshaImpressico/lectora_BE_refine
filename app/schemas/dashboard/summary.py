"""Pydantic schemas for the Dashboard Summary API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardSummaryData(BaseModel):
    """Aggregated course-generation counts for the Dashboard screen."""

    total_courses: int = Field(..., ge=0, description="Total number of course generation runs")
    in_progress: int = Field(..., ge=0, description="Runs currently generating")
    completed: int = Field(..., ge=0, description="Runs that finished successfully")


class DashboardSummaryResponse(BaseModel):
    """Standard API response envelope for the Dashboard Summary endpoint."""

    success: bool
    data: DashboardSummaryData
