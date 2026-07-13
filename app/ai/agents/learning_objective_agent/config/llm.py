"""Shared LLM configuration for every learning-objective (LO) sub-agent.

Each ``make_*_config()`` resolves the deployment from the model registry at
call time (not import time) so settings-API overrides apply without a server
restart.
"""
from app.kernel.chat import LLMConfig
from app.kernel.model_registry import get_deployment

_RESPONSE_FORMAT = {"type": "json_object"}


def _make_config(max_tokens: int) -> LLMConfig:
    return LLMConfig(
        deployment=get_deployment("A0_TO"),
        max_tokens=max_tokens,
        response_format=_RESPONSE_FORMAT,
    )


def make_generation_config() -> LLMConfig:
    return _make_config(max_tokens=2048)


def make_refine_config() -> LLMConfig:
    return _make_config(max_tokens=2048)


def make_regenerate_config() -> LLMConfig:
    return _make_config(max_tokens=2048)


def make_validator_config() -> LLMConfig:
    return _make_config(max_tokens=1024)
