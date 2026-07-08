"""Input/output models for the RT refine agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.agents.required_topic.models import RTPipelineMetadata
from app.ai.agents.required_topic.rt_validator.models import RTValidationIssue


@dataclass
class RTRefinementInput:
    topics: list[str]
    issues: list[RTValidationIssue]
    metadata: RTPipelineMetadata


@dataclass
class RTRefinementOutput:
    topics: list[str] = field(default_factory=list)
