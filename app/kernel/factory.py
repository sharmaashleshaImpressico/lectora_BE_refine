"""Semantic Kernel factory — Azure OpenAI chat + Azure AI Search semantic retrieval."""

from __future__ import annotations

import logging

from semantic_kernel import Kernel
from semantic_kernel.connectors.azure_ai_search import AzureAISearchStore

from app.kernel.config import load_kernel_settings
from app.kernel.model_registry import get_deployment

logger = logging.getLogger(__name__)

SEMANTIC_SEARCH_STORE_ATTR = "semantic_search_store"


def create_kernel() -> Kernel:
    """Build a Kernel wired for Azure OpenAI chat and optional Azure AI Search."""
    settings = load_kernel_settings()
    kernel = Kernel()

    if settings.azure_openai_endpoint and settings.azure_openai_api_key:
        from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

        default_deployment = get_deployment("A0_TO")
        kernel.add_service(
            AzureChatCompletion(
                service_id=f"azure_chat_{default_deployment}",
                deployment_name=default_deployment,
                endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
            )
        )
    else:
        logger.warning(
            "[kernel] Azure OpenAI is not configured — chat services will be "
            "registered lazily on first LLM call."
        )

    if settings.azure_search_endpoint and settings.azure_search_api_key:
        try:
            search_store = AzureAISearchStore(
                search_endpoint=settings.azure_search_endpoint,
                api_key=settings.azure_search_api_key,
            )
            setattr(kernel, SEMANTIC_SEARCH_STORE_ATTR, search_store)
            logger.info(
                "[kernel] Azure AI Search semantic store attached | index=%s",
                settings.azure_search_index_name,
            )
        except Exception:
            logger.exception("[kernel] Failed to attach Azure AI Search semantic store")

    return kernel
