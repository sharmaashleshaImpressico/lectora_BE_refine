"""Backward-compatible shim — delegates to Semantic Kernel chat helpers."""

from app.kernel.chat import LLMConfig, chat, chat_async

__all__ = ["LLMConfig", "chat", "chat_async"]
