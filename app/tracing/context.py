"""ContextVar stack and thread-pool context propagation for tracing."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token, copy_context
from typing import Any, Iterator

from app.tracing.models import WorkflowFrame, WorkflowTraceContext

_ctx_stack: ContextVar[tuple[WorkflowFrame, ...]] = ContextVar(
    "tracing_workflow_stack", default=()
)
_ctx_run_id: ContextVar[str] = ContextVar("tracing_run_id", default="")
_ctx_doc_name: ContextVar[str] = ContextVar("tracing_doc_name", default="")
_ctx_workflow: ContextVar[str] = ContextVar("tracing_workflow", default="")
_ctx_generation_label: ContextVar[str] = ContextVar(
    "tracing_generation_label", default=""
)
_ctx_source_refs: ContextVar[tuple[str, ...]] = ContextVar(
    "tracing_source_refs", default=()
)
_ctx_defer_generation: ContextVar[bool] = ContextVar(
    "tracing_defer_generation", default=False
)


def get_stack() -> tuple[WorkflowFrame, ...]:
    return _ctx_stack.get()


def current_frame() -> WorkflowFrame | None:
    stack = _ctx_stack.get()
    return stack[-1] if stack else None


def get_run_id() -> str:
    return _ctx_run_id.get()


def get_doc_name() -> str:
    return _ctx_doc_name.get()


def get_workflow() -> str:
    return _ctx_workflow.get()


def get_source_refs() -> list[str]:
    return list(_ctx_source_refs.get())


def get_generation_label() -> str:
    return _ctx_generation_label.get().strip()


def _normalize_source_refs(
    source_refs: list[str] | tuple[str, ...] | str | None,
) -> tuple[str, ...]:
    if source_refs is None:
        return ()
    if isinstance(source_refs, str):
        refs = (source_refs,) if source_refs.strip() else ()
    else:
        refs = tuple(str(ref).strip() for ref in source_refs if str(ref).strip())
    return refs


def set_generation_label(label: str) -> Token:
    """Set the pending generation label. Returns a reset token for scoped use."""
    return _ctx_generation_label.set((label or "").strip())


def reset_generation_label(token: Token) -> None:
    try:
        token.var.reset(token)
    except Exception:
        pass


def consume_generation_label() -> str:
    """Read and clear the pending generation label."""
    label = _ctx_generation_label.get().strip()
    _ctx_generation_label.set("")
    return label


def clear_generation_label() -> None:
    """Drop any pending generation label without restoring a prior value."""
    _ctx_generation_label.set("")


def set_source_refs(
    source_refs: list[str] | tuple[str, ...] | str | None,
) -> Token:
    """Set source refs. Returns a ContextVar token — reset in ``finally``."""
    return _ctx_source_refs.set(_normalize_source_refs(source_refs))


def reset_source_refs(token: Token) -> None:
    try:
        token.var.reset(token)
    except Exception:
        pass


@contextmanager
def defer_generation_export() -> Iterator[None]:
    """Skip ``record_generation`` fan-out while active (e.g. S1 raw call)."""
    token = _ctx_defer_generation.set(True)
    try:
        yield
    finally:
        _ctx_defer_generation.reset(token)


def should_defer_generation_export() -> bool:
    return _ctx_defer_generation.get()


def push_frame(frame: WorkflowFrame) -> list[Token]:
    """Push a workflow frame and set convenience ContextVars. Returns reset tokens.

    Generation labels are cleared for the new frame and restored on ``pop_frame``,
    so labels set inside a workflow cannot leak to the parent or a later root.
    """
    tokens: list[Token] = []
    ctx = frame.context
    tokens.append(_ctx_stack.set(_ctx_stack.get() + (frame,)))
    tokens.append(_ctx_run_id.set(ctx.run_id))
    tokens.append(_ctx_doc_name.set(ctx.doc_name or ctx.workflow))
    tokens.append(_ctx_workflow.set(ctx.workflow))
    # Scope labels to this workflow frame (restore parent label on pop).
    tokens.append(_ctx_generation_label.set(""))
    frame.tokens = tokens
    return tokens


def pop_frame(tokens: list[Token]) -> None:
    for token in reversed(tokens):
        try:
            token.var.reset(token)
        except Exception:
            pass


def submit_with_trace_context(executor, fn, /, *args, **kwargs):
    """Run work in a thread-pool worker while preserving the current trace context."""
    ctx = copy_context()
    return executor.submit(ctx.run, fn, *args, **kwargs)


def current_context_snapshot() -> WorkflowTraceContext | None:
    frame = current_frame()
    return frame.context if frame else None


def provider_parent_handle(provider_name: str) -> Any | None:
    frame = current_frame()
    if frame is None:
        return None
    return frame.provider_handles.get(provider_name)
