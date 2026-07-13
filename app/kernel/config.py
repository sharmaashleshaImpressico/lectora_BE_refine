"""Environment-backed settings for Semantic Kernel services."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import llm_pipeline_settings


@dataclass(frozen=True)
class KernelSettings:
    """Resolved Azure OpenAI and Azure AI Search settings for kernel bootstrap."""

    azure_openai_endpoint: str | None
    azure_openai_api_key: str | None
    azure_openai_api_version: str
    azure_search_endpoint: str | None
    azure_search_api_key: str | None
    azure_search_index_name: str


def load_kernel_settings() -> KernelSettings:
    return KernelSettings(
        azure_openai_endpoint=llm_pipeline_settings.azure_openai_endpoint,
        azure_openai_api_key=llm_pipeline_settings.azure_openai_api_key,
        azure_openai_api_version=llm_pipeline_settings.azure_openai_api_version,
        azure_search_endpoint=(os.getenv("AZURE_SEARCH_ENDPOINT") or "").strip() or None,
        azure_search_api_key=(os.getenv("AZURE_SEARCH_API_KEY") or "").strip() or None,
        azure_search_index_name=(
            (os.getenv("AZURE_SEARCH_INDEX_NAME") or "").strip() or "course-chunks"
        ),
    )
