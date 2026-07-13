"""Input/output models for the RT generation agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.agents.required_topic.models import RTPipelineMetadata


@dataclass
class RTGenerationInput:
    metadata: RTPipelineMetadata


@dataclass
class RTGenerationOutput:
    topics: list[str] = field(default_factory=list)
