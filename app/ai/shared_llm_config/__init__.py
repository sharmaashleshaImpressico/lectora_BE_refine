"""Pipeline import shim for ``app.kernel``."""

from app.kernel.chat import LLMConfig, chat, chat_async
from app.kernel.factory import SEMANTIC_SEARCH_STORE_ATTR, create_kernel
from app.kernel.model_registry import (
    AVAILABLE_MODELS,
    DEFAULTS,
    get_all_configs,
    get_deployment,
    get_to_file_deployment,
    reset_all_deployments,
    reset_deployment,
    set_deployment,
)

__all__ = [
    "AVAILABLE_MODELS",
    "DEFAULTS",
    "LLMConfig",
    "SEMANTIC_SEARCH_STORE_ATTR",
    "chat",
    "chat_async",
    "create_kernel",
    "get_all_configs",
    "get_deployment",
    "get_to_file_deployment",
    "reset_all_deployments",
    "reset_deployment",
    "set_deployment",
]
