"""Shared data models for the required-topics (RT) pipeline.

All three agents (rt_generation, rt_validator, rt_refine_agent) receive an
RTPipelineMetadata instance so each agent has the full course context without
passing kwargs individually.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RTPipelineMetadata:
    """Course context passed to every agent in the RT pipeline."""

    course_title: str = ""
    course_description: str = ""
    course_type: str = ""
    course_duration: str = ""
    target_audience: str = ""
    skill_level: str = ""
    learner_outcomes: str = ""


@dataclass
class RTPipelineResult:
    """Final output of RequiredTopicsOrchestrator.execute()."""

    topics: list[str]
    validation_passed: bool
    repair_attempts: int
    # Populated only when validation never passed after all repair attempts.
    final_issues: list[dict[str, Any]] = field(default_factory=list)
