"""Service-to-orchestrator contracts for learning objective generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LearningObjectiveGenerationInput:
    """Complete course context passed from the service into the LO orchestrator."""

    source_materials: list[str] = field(default_factory=list)
    course_title: str = ""
    course_description: str = ""
    course_type: str = ""
    course_duration: str = ""
    skill_level: str = ""
    target_audience: str = ""
    required_topics: list[str] = field(default_factory=list)


@dataclass
class LearningObjectiveRegenerationInput:
    """Context for revising existing objectives from user feedback."""

    current_objectives: list[str] = field(default_factory=list)
    regeneration_prompt: str = ""
    course_title: str = ""
    course_type: str = ""
    course_duration: str = ""
    skill_level: str = ""
    target_audience: str = ""


@dataclass
class LearningObjectiveGenerationResult:
    """Final output of the learning objective generation pipeline."""

    objectives: list[str]
    validation_passed: bool
    repair_attempts: int
    final_issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LearningObjectiveRegenerationResult:
    """Final output of the learning objective regeneration pipeline."""

    objectives: list[str]
