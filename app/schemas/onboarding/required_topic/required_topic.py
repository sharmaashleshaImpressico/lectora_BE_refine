"""Pydantic request/response schemas for Required Topics APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerateRequiredTopicsRequest(BaseModel):
    """Payload accepted from the frontend for required topics generation."""

    courseTitle: str = Field(..., min_length=1)
    courseScope: str = Field(..., min_length=1)
    difficultyLevel: str = Field(..., min_length=1)
    targetAudience: str = Field(..., min_length=1)
    learnerExperienceLevel: str = Field(..., min_length=1)
    learnerOutcomes: list[str] = Field(..., min_length=1)
    courseType: str | None = None
    courseDuration: str | None = None


class GenerateRequiredTopicsResponse(BaseModel):
    """Required topics returned after generation, validation, and repair."""

    requiredTopics: list[str]
    validationPassed: bool
    repairAttempts: int
    finalIssues: list[dict[str, Any]]
