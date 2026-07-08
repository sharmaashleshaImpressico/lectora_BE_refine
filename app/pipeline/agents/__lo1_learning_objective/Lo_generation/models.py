"""Input/output models for the LO generation agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.agents.__lo1_learning_objective.models import CourseMetadata


@dataclass
class LOGenerationInput:
    metadata: CourseMetadata


@dataclass
class LOGenerationOutput:
    objectives: list[str] = field(default_factory=list)
