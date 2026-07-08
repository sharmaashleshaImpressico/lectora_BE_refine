"""Input/output models for the LO refine agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.agents.__lo1_learning_objective.Lo_validator.models import (
    LOValidationIssue,
)
from app.pipeline.agents.__lo1_learning_objective.models import CourseMetadata


@dataclass
class LORefinementInput:
    objectives: list[str]
    issues: list[LOValidationIssue]
    metadata: CourseMetadata


@dataclass
class LORefinementOutput:
    objectives: list[str] = field(default_factory=list)
