"""LLM configuration for the RT generation agent."""
from app.pipeline.shared_llm_config.llm import LLMConfig
from app.pipeline.shared_llm_config.model_registry import get_deployment


def make_config() -> LLMConfig:
    """Return an LLMConfig resolved against the current model registry.

    Called at run-time (not import-time) so settings-API overrides apply
    without a server restart.
    """
    return LLMConfig(
        deployment=get_deployment("A0_TO"),
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
