"""LLM configuration for the outline structure suggestion agent."""
from app.ai.shared_llm_config.llm import LLMConfig
from app.ai.shared_llm_config.model_registry import get_deployment


def make_config() -> LLMConfig:
    return LLMConfig(
        deployment=get_deployment("A0_TO"),
        max_tokens=1_024,
        response_format={"type": "json_object"},
    )
