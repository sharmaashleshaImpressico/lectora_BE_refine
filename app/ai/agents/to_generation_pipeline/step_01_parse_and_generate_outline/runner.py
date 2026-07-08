"""A0 agent runner — registered with the central orchestrator."""

from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.phases.synthesizer import (
    A0RequestSynthesizer,
)

__all__ = ["A0RequestSynthesizer"]
