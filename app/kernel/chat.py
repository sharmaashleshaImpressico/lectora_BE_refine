"""LLM chat helpers backed by Microsoft Semantic Kernel."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from inspect import currentframe
from pathlib import Path

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import (
    AzureChatCompletion,
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.contents import ChatHistory
from semantic_kernel.exceptions import KernelServiceNotFoundError

from app.kernel.config import load_kernel_settings
from app.shared_llm_config.tracer import LLMTrace, write_trace

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHAT_SERVICE_PREFIX = "azure_chat_"


@dataclass
class LLMConfig:
    """Per-agent model settings passed into kernel chat helpers."""

    deployment: str
    temperature: float | None = None
    max_tokens: int | None = None
    top_k: int | None = None
    response_format: dict | None = None


def _infer_prompt_callsite() -> dict[str, object]:
    frame = currentframe()
    if frame is None:
        return {}
    caller = frame.f_back
    fallback: dict[str, object] = {}
    while caller is not None:
        filename = Path(caller.f_code.co_filename).resolve()
        is_kernel_chat = filename == Path(__file__).resolve()
        is_tracer_file = filename.name == "tracer.py"
        is_agent_config_wrapper = tuple(filename.parts[-2:]) == ("config", "llm.py")
        if is_kernel_chat or is_tracer_file or is_agent_config_wrapper:
            caller = caller.f_back
            continue
        try:
            rel = filename.relative_to(_REPO_ROOT).as_posix()
            return {
                "prompt_file": rel,
                "prompt_function": caller.f_code.co_name,
                "prompt_line": int(caller.f_lineno),
            }
        except ValueError:
            if not fallback:
                fallback = {
                    "prompt_file": filename.as_posix(),
                    "prompt_function": caller.f_code.co_name,
                    "prompt_line": int(caller.f_lineno),
                }
        caller = caller.f_back
    return fallback


def _augment_system_prompt_for_json(
    system_prompt: str,
    user_msg: str,
    config: LLMConfig,
) -> str:
    if (
        config.response_format is not None
        and config.response_format.get("type") == "json_object"
        and "json" not in system_prompt.lower()
        and "json" not in user_msg.lower()
    ):
        return system_prompt + "\n\nRespond with a valid JSON object only."
    return system_prompt


def _ensure_chat_service(kernel: Kernel, deployment: str) -> str:
    service_id = f"{_CHAT_SERVICE_PREFIX}{deployment}"
    try:
        kernel.get_service(service_id=service_id)
        return service_id
    except KernelServiceNotFoundError:
        pass

    settings = load_kernel_settings()
    if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
        raise RuntimeError("azure_openai_api_key and azure_openai_endpoint must be configured.")

    kernel.add_service(
        AzureChatCompletion(
            service_id=service_id,
            deployment_name=deployment,
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    )
    return service_id


def _build_execution_settings(
    service_id: str,
    config: LLMConfig,
) -> AzureChatPromptExecutionSettings:
    kwargs: dict[str, object] = {"service_id": service_id}
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature
    if config.max_tokens is not None:
        kwargs["max_tokens"] = config.max_tokens
    if config.response_format is not None:
        kwargs["response_format"] = config.response_format
    return AzureChatPromptExecutionSettings(**kwargs)


async def chat_async(
    kernel: Kernel,
    system_prompt: str,
    user_msg: str,
    config: LLMConfig,
    agent: str = "",
) -> str:
    """Send a system + user turn through Semantic Kernel and return response text."""
    service_id = _ensure_chat_service(kernel, config.deployment)
    chat_service = kernel.get_service(service_id=service_id)
    effective_system_prompt = _augment_system_prompt_for_json(
        system_prompt,
        user_msg,
        config,
    )

    history = ChatHistory()
    history.add_system_message(effective_system_prompt)
    history.add_user_message(user_msg)
    settings = _build_execution_settings(service_id, config)

    t_start = time.perf_counter()
    error_msg: str | None = None
    response_text = ""
    prompt_tokens = completion_tokens = total_tokens = 0

    try:
        results = await chat_service.get_chat_message_contents(
            chat_history=history,
            settings=settings,
        )
        if not results:
            response_text = ""
        else:
            response_text = str(results[0]).strip()
            usage = getattr(results[0], "metadata", None) or {}
            if isinstance(usage, dict):
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or 0)
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        latency_ms = (time.perf_counter() - t_start) * 1000
        write_trace(
            LLMTrace(
                agent=agent,
                deployment=config.deployment,
                system_prompt=effective_system_prompt,
                user_msg=user_msg,
                response=response_text,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error=error_msg,
                model_parameters={
                    "temperature": config.temperature,
                    "max_completion_tokens": config.max_tokens,
                    "top_k": config.top_k,
                    "response_format": config.response_format,
                },
                prompt_metadata={
                    "original_system_prompt": system_prompt,
                    "effective_system_prompt": effective_system_prompt,
                    "prompt_was_augmented_for_json_contract": (
                        effective_system_prompt != system_prompt
                    ),
                    **_infer_prompt_callsite(),
                },
                observation_name=None,
            )
        )

    return response_text


def chat(
    kernel: Kernel,
    system_prompt: str,
    user_msg: str,
    config: LLMConfig,
    agent: str = "",
) -> str:
    """Synchronous wrapper around :func:`chat_async`."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise RuntimeError(
            "chat() cannot be called from a running event loop; use chat_async() instead."
        )

    return asyncio.run(
        chat_async(kernel, system_prompt, user_msg, config, agent=agent)
    )
