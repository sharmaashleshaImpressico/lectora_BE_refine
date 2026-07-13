"""Input/output models for the LO refine agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.agents.learning_objective_agent.Lo_validator.models import (
    LOValidationIssue,
)
from app.ai.agents.learning_objective_agent.models import CourseMetadata


@dataclass
class LORefinementInput:
    objectives: list[str]
    issues: list[LOValidationIssue]
    metadata: CourseMetadata


@dataclass
class LORefinementOutput:
    objectives: list[str] = field(default_factory=list)
