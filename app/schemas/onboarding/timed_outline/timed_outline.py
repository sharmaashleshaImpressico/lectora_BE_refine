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
    calculatedWordCount: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Optional target word count. Derived server-side from durationHours "
            "+ difficulty when omitted; send only to override the calculation."
        ),
    )
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
    ruleFamily: str | None = Field(
        default=None,
        description="Normalized rule-family key resolved from the course type (e.g. insurance_ce)",
    )
    rulePack: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The complete content-generation rule pack selected from rule_pack_config "
            "for this course type. Distinct from the Timed-Outline validation rule pack, "
            "which is internal to TO validation."
        ),
    )


class RegenerateTimedOutlineRequest(BaseModel):
    """Payload accepted from the frontend for revising an existing TO in place."""

    currentTo: dict[str, Any] = Field(..., description="Existing Training Outline JSON to revise")
    regenerationPrompt: str | None = Field(
        default=None,
        description="Free-text revision instructions; omit to leave the outline unchanged",
    )
    preferredChapters: int | None = None
    lessonStyle: str | None = None


class RegenerateTimedOutlineResponse(BaseModel):
    """Revised timed outline result."""

    to: dict[str, Any]


class SuggestOutlineStructureRequest(BaseModel):
    """Payload accepted from the frontend for outline structure suggestions."""

    courseTitle: str | None = None
    courseDescription: str | None = None
    courseType: str | None = None
    targetAudience: str | None = None
    skillLevel: str | None = None
    learningObjectives: list[str] | None = None


class SuggestOutlineStructureResponse(BaseModel):
    """Suggested chapter count and lesson style with rationale."""

    preferredChapters: int
    lessonStyle: str
    reasoning: str
