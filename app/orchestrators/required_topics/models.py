"""Service-to-orchestrator contracts for required topics generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequiredTopicsGenerationInput:
    """Complete course context passed from the service into the RT orchestrator."""

    course_title: str = ""
    course_scope: str = ""
    course_type: str = ""
    course_duration: str = ""
    difficulty_level: str = ""
    target_audience: str = ""
    learner_experience_level: str = ""
    learner_outcomes: list[str] = field(default_factory=list)


@dataclass
class RequiredTopicsGenerationResult:
    """Final output of the required topics generation pipeline."""

    topics: list[str]
    validation_passed: bool
    repair_attempts: int
    final_issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RequiredTopicsRegenerationInput:
    """Context for revising existing required topics from user feedback."""

    current_topics: list[str] = field(default_factory=list)
    regeneration_prompt: str = ""


@dataclass
class RequiredTopicsRegenerationResult:
    """Final output of the required topics regeneration pipeline."""

    topics: list[str]
