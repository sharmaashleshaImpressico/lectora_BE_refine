"""LLM configuration for the content transformation agent."""

from app.kernel.chat import LLMConfig
from app.kernel.model_registry import get_deployment

_RESPONSE_FORMAT = {"type": "json_object"}


def make_transform_config() -> LLMConfig:
    """Resolve CONTENT_TRANSFORM deployment at call time."""
    return LLMConfig(
        deployment=get_deployment("CONTENT_TRANSFORM"),
        max_tokens=8192,
        response_format=_RESPONSE_FORMAT,
    )


__all__ = ["make_transform_config"]
