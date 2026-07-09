"""Service-to-orchestrator contracts for timed outline generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TimedOutlineGenerationInput:
    """Complete course context passed from the service into the TO orchestrator."""

    blob_paths: list[str] = field(default_factory=list)
    course_title: str = ""
    course_description: str = ""
    audience: str = ""
    learning_objectives: list[str] = field(default_factory=list)
    required_topics: list[str] = field(default_factory=list)
    duration_hours: float | None = None
    calculated_word_count: int | None = None
    difficulty: str = "intermediate"
    course_topic: str | None = None
    course_type_hint: str | None = None
    rule_family: str | None = None
    experience_level: str | None = None
    learner_outcomes: str | None = None
    tone: str | None = None
    depth: str | None = None
    emphasis: str | None = None
    avoid: str | None = None
    include_case_studies: bool | None = None
    include_examples: bool | None = None
    include_knowledge_checks: bool | None = None
    preferred_chapters: int | None = None
    lesson_style: str | None = None


@dataclass
class TimedOutlineGenerationResult:
    """Final output of the timed outline generation pipeline."""

    outline: dict[str, Any]
    validation_passed: bool
    repair_attempts: int
    blocked: bool
    final_issues: list[dict[str, Any]] = field(default_factory=list)
