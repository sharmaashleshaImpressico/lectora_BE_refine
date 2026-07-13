"""Shared LLM configuration for every required-topics (RT) sub-agent.

``make_config()`` resolves the deployment from the model registry at call
time (not import time) so settings-API overrides apply without a server
restart.
"""
from app.kernel.chat import LLMConfig
from app.kernel.model_registry import get_deployment


def make_config() -> LLMConfig:
    return LLMConfig(
        deployment=get_deployment("A0_TO"),
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
