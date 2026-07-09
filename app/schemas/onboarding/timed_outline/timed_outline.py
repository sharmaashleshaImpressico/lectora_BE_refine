"""Pydantic request/response schemas for Timed Outline generation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerateTimedOutlineRequest(BaseModel):
    """Payload accepted from the frontend for TO generation."""

    blobPaths: list[str] = Field(..., min_length=1, description="Source document blob paths")
    courseTitle: str = Field(..., min_length=1)
    courseDescription: str = Field(..., min_length=1)
    durationHours: float = Field(..., gt=0)
    calculatedWordCount: int = Field(..., gt=0)
    audience: str = Field(..., min_length=1)
    learningObjectives: list[str] = Field(..., min_length=1)
    requiredTopics: list[str] = Field(..., min_length=1)
    courseTopic: str | None = None
    difficulty: str | None = None
    difficultyLevel: str | None = None
    courseTypeHint: str | None = None
    ruleFamily: str | None = None
    experienceLevel: str | None = None
    learnerOutcomes: str | None = None
    tone: str | None = None
    depth: str | None = None
    emphasis: str | None = None
    avoid: str | None = None
    includeCaseStudies: bool | None = None
    includeExamples: bool | None = None
    includeKnowledgeChecks: bool | None = None
    preferredChapters: int | None = None
    lessonStyle: str | None = None


class GenerateTimedOutlineResponse(BaseModel):
    """Timed outline generation result including validation and repair metadata."""

    timedOutline: dict[str, Any]
    validationPassed: bool
    repairAttempts: int
    finalIssues: list[dict[str, Any]]
