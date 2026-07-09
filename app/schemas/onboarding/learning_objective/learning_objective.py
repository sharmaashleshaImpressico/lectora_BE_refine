"""Pydantic request/response schemas for Learning Objective generation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerateLearningObjectivesRequest(BaseModel):
    """Payload accepted from the frontend for LO generation."""

    sourceMaterials: list[str] = Field(..., min_length=1, description="Source document paths")
    courseTitle: str = Field(..., min_length=1)
    courseDescription: str = Field(..., min_length=1)
    courseType: str = Field(..., min_length=1)
    courseDuration: str = Field(..., min_length=1)
    skillLevel: str = Field(..., min_length=1)
    targetAudience: str = Field(..., min_length=1)
    requiredTopics: list[str] = Field(..., min_length=1)
    # Optional; reserved for a future regenerate API — ignored here.
    regenerationPrompt: str | None = None
    currentObjectives: list[str] | None = None


class GenerateLearningObjectivesResponse(BaseModel):
    """Generation result including validation and repair metadata."""

    learningObjectives: list[str]
    validationPassed: bool
    repairAttempts: int
    finalIssues: list[dict[str, Any]]
