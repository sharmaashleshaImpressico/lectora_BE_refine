"""Pydantic request/response schemas for Required Topics APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerateRequiredTopicsRequest(BaseModel):
    """Payload accepted from the frontend for required topics generation."""

    courseTitle: str = Field(..., min_length=1)
    courseDescription: str = Field(..., min_length=1)
    courseType: str = Field(..., min_length=1)
    courseDuration: str = Field(..., min_length=1)
    skillLevel: str = Field(..., min_length=1)
    targetAudience: str = Field(..., min_length=1)
    learnerOutcomes: str = Field(..., min_length=1)


class GenerateRequiredTopicsResponse(BaseModel):
    """Required topics returned after generation, validation, and repair."""

    requiredTopics: list[str]
    validationPassed: bool
    repairAttempts: int
    finalIssues: list[dict[str, Any]]


class RegenerateRequiredTopicsRequest(BaseModel):
    """Payload for revising existing required topics from user feedback."""

    currentTopics: list[str] = Field(..., min_length=1)
    regenerationPrompt: str = Field(..., min_length=1)


class RegenerateRequiredTopicsResponse(BaseModel):
    """Revised required topics returned after regeneration."""

    requiredTopics: list[str]
