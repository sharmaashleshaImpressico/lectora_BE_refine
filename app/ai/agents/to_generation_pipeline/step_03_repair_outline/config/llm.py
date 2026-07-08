"""LLM configuration for S1 TO refinement."""

from __future__ import annotations

from app.ai.shared_llm_config.llm import LLMConfig
from app.ai.shared_llm_config.model_registry import get_deployment


class RefinementLLMConfigFactory:
    """Builds LLM settings for the S1 TO repair agent."""

    _DEPLOYMENT_KEY = "A0_TO"
    _MAX_TOKENS = 16_384

    @classmethod
    def create(cls) -> LLMConfig:
        return LLMConfig(
            deployment=get_deployment(cls._DEPLOYMENT_KEY),
            max_tokens=cls._MAX_TOKENS,
            response_format={"type": "json_object"},
        )


def make_config() -> LLMConfig:
    """Backward-compatible factory function."""
    return RefinementLLMConfigFactory.create()
