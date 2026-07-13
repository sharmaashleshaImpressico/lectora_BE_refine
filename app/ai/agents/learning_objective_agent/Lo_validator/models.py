"""Input/output models for the LO validator agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.ai.agents.learning_objective_agent.models import CourseMetadata

IssueType = Literal[
    "count",
    "weak_verb",
    "vague",
    "duplicate",
    "overlap",
    "misaligned",
    "missing_intent",
    "overloaded",
]


@dataclass
class LOValidationIssue:
    type: str  # one of IssueType values
    message: str
    affected_objectives: list[str] = field(default_factory=list)
    # Instruction for the refiner: replace | merge | remove | add
    expected_action: str = ""


@dataclass
class LOValidationInput:
    objectives: list[str]
    metadata: CourseMetadata


@dataclass
class LOValidationOutput:
    status: str  # "pass" | "fail"
    issues: list[LOValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"
