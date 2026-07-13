"""Input/output models for the LO generation agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.agents.learning_objective_agent.models import CourseMetadata


@dataclass
class LOGenerationInput:
    metadata: CourseMetadata


@dataclass
class LOGenerationOutput:
    objectives: list[str] = field(default_factory=list)
