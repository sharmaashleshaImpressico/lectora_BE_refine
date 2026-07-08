"""LLM configuration for the TO regeneration agent."""
from lectora_backend.pipeline.shared_llm_config.llm import LLMConfig
from lectora_backend.pipeline.shared_llm_config.model_registry import get_deployment


def make_config() -> LLMConfig:
    return LLMConfig(
        deployment=get_deployment("A0_TO"),
        max_tokens=16_384,
        response_format={"type": "json_object"},
    )
