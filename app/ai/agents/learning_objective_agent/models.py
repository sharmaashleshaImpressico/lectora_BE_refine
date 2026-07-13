"""Shared data models for the LO generation pipeline.

All three agents (Lo_generation, Lo_validator, Lo_refine_agent) receive a
CourseMetadata instance so each agent has the full course context without
passing kwargs individually.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CourseMetadata:
    """Complete course context passed to every agent in the LO pipeline."""

    course_title: str = ""
    course_description: str = ""
    course_type: str = ""
    course_duration: str = ""
    target_audience: str = ""
    skill_level: str = ""
    desired_outcomes: str = ""
    certification_focus: str = ""
    additional_instructions: str = ""
    required_topics: list[str] = field(default_factory=list)
    # Serialised as plain dicts so the pipeline layer has no dependency on API schemas.
    # Keys mirror SourceAnalysis fields: source_name, source_role, extract_hint,
    # main_topics, supports_learning_objectives, ignore_or_reduce.
    source_analyses: list[dict[str, Any]] = field(default_factory=list)
    # Present only for regeneration calls (user editing existing objectives).
    regeneration_prompt: str = ""
    current_objectives: list[str] = field(default_factory=list)


@dataclass
class LOPipelineResult:
    """Final output of run_lo_pipeline()."""

    objectives: list[str]
    validation_passed: bool
    repair_attempts: int
    # Populated only when validation never passed after all repair attempts.
    final_issues: list[dict[str, Any]] = field(default_factory=list)
