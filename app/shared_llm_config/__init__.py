"""Tracing and legacy shims — prefer ``app.kernel`` for LLM calls."""

from app.shared_llm_config.tracer import (
    flush_langfuse,
    set_doc_name,
    set_langfuse_step_label,
    set_run_id,
    set_run_context,
    set_source_refs,
    shutdown_langfuse,
    span_context,
)

__all__ = [
    "flush_langfuse",
    "set_doc_name",
    "set_langfuse_step_label",
    "set_run_id",
    "set_run_context",
    "set_source_refs",
    "shutdown_langfuse",
    "span_context",
]
