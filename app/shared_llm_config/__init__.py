"""Tracing and legacy shims — prefer ``app.tracing`` for new code."""

from app.shared_llm_config.tracer import (
    set_source_refs,
    submit_with_trace_context,
)
from app.tracing import (
    atraced_workflow,
    flush_tracing,
    record_generation,
    set_generation_label,
    shutdown_tracing,
    traced_workflow,
)

__all__ = [
    "atraced_workflow",
    "flush_tracing",
    "record_generation",
    "set_generation_label",
    "set_source_refs",
    "shutdown_tracing",
    "submit_with_trace_context",
    "traced_workflow",
]
