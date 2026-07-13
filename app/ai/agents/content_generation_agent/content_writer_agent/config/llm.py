"""
LLM config for A2 — Content Generator.

Uses DynamicLLMConfig so the deployment is resolved from model_registry at
every call. Changes made via the settings API take effect immediately without
restarting the server.

COURSE_DESCRIPTION_CONFIG and CONCLUSION_CONFIG are also dynamic — they share
the same agent_id ("A2") so a single model change updates all three configs.

Actual LLM calls go through ``app.kernel.chat.chat``/``chat_async``, which
require an explicit ``Kernel`` — callers thread the kernel through rather than
calling a module-level wrapper here.
"""

from app.kernel.chat import LLMConfig
from app.kernel.model_registry import get_deployment


class _DynamicConfig:
    """Proxy that reads `deployment` from the registry on every attribute access."""

    def __init__(
        self,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_k: int | None = None,
        response_format: dict | None = None,
    ) -> None:
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_k = top_k
        self.response_format = response_format

    @property
    def deployment(self) -> str:  # type: ignore[override]
        return get_deployment("A2")


# ── Agent configs — all share the same dynamic deployment ───────────────────

# Module-level singleton — stays compatible with any code that imports AGENT_CONFIG
AGENT_CONFIG: LLMConfig = _DynamicConfig(temperature=0.7)  # type: ignore[assignment]

# Separate call configs used for course description and conclusion text.
# Both are imported by local_jobs.py — dynamic proxy means they always
# use the currently configured deployment.
COURSE_DESCRIPTION_CONFIG: LLMConfig = _DynamicConfig(  # type: ignore[assignment]
    temperature=0.35,
    max_tokens=1200,
)

CONCLUSION_CONFIG: LLMConfig = _DynamicConfig(  # type: ignore[assignment]
    temperature=0.35,
    max_tokens=1500,
)
