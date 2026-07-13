"""Vendor-neutral application tracing API.

Application code must import from ``app.tracing`` only — never from Langfuse.
"""

from __future__ import annotations

from app.tracing.context import (
    get_doc_name,
    get_run_id,
    get_source_refs,
    get_workflow,
    set_generation_label,
    set_source_refs,
    submit_with_trace_context,
)
from app.tracing.models import GenerationTraceData, WorkflowTraceContext
from app.tracing.service import (
    atraced_workflow,
    flush_tracing,
    record_generation,
    shutdown_tracing,
    stack_depth,
    traced_workflow,
)

__all__ = [
    "GenerationTraceData",
    "WorkflowTraceContext",
    "atraced_workflow",
    "flush_tracing",
    "get_doc_name",
    "get_run_id",
    "get_source_refs",
    "get_workflow",
    "record_generation",
    "set_generation_label",
    "set_source_refs",
    "shutdown_tracing",
    "stack_depth",
    "submit_with_trace_context",
    "traced_workflow",
]
