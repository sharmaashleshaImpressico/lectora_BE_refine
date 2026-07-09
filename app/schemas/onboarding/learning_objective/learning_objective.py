"""Pydantic request/response schemas for Learning Objective APIs."""

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
    # Optional; ignored by the generate endpoint.
    regenerationPrompt: str | None = None
    currentObjectives: list[str] | None = None


class GenerateLearningObjectivesResponse(BaseModel):
    """Generation result including validation and repair metadata."""

    learningObjectives: list[str]
    validationPassed: bool
    repairAttempts: int
    finalIssues: list[dict[str, Any]]


class RegenerateLearningObjectivesRequest(BaseModel):
    """Payload for revising existing learning objectives from user feedback."""

    currentObjectives: list[str] = Field(..., min_length=1)
    regenerationPrompt: str = Field(..., min_length=1)
    courseTitle: str | None = None
    courseType: str | None = None
    courseDuration: str | None = None
    skillLevel: str | None = None
    targetAudience: str | None = None


class RegenerateLearningObjectivesResponse(BaseModel):
    """Revised learning objectives returned after regeneration."""

    learningObjectives: list[str]
