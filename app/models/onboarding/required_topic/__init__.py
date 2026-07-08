"""Shared models for the required topics pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RTPipelineMetadata:
    """Complete course context passed to every agent in the RT pipeline."""

    course_title: str = ""
    course_description: str = ""
    course_type: str = ""
    course_duration: str = ""
    target_audience: str = ""
    skill_level: str = ""
    learner_outcomes: str = ""


@dataclass
class RTPipelineResult:
    """Final output of the required topics pipeline."""

    topics: list[str]
    validation_passed: bool
    repair_attempts: int
    final_issues: list[dict[str, Any]] = field(default_factory=list)
