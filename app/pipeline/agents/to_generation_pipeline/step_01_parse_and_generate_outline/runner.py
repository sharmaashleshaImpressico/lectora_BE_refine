"""A0 agent runner — registered with the central orchestrator."""

from lectora_backend.pipeline.agent.to_generation_pipeline.step_01_parse_and_generate_outline.phases.synthesizer import (
    A0RequestSynthesizer,
)

__all__ = ["A0RequestSynthesizer"]
