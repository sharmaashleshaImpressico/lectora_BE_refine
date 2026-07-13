"""Input/output models for the RT validator agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.agents.required_topic.models import RTPipelineMetadata


@dataclass
class RTValidationIssue:
    type: str
    message: str
    affected_topics: list[str] = field(default_factory=list)
    # Instruction for the refiner: replace | merge | remove | add
    expected_action: str = ""


@dataclass
class RTValidationInput:
    topics: list[str]
    metadata: RTPipelineMetadata


@dataclass
class RTValidationOutput:
    status: str  # "pass" | "fail"
    issues: list[RTValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"
