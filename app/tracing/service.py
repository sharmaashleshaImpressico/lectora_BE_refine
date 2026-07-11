"""Generic tracing façade — application code depends only on this module's API."""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator

from app.tracing.context import (
    clear_generation_label,
    consume_generation_label,
    current_frame,
    get_doc_name,
    get_run_id,
    get_source_refs,
    get_stack,
    get_workflow,
    pop_frame,
    push_frame,
    reset_source_refs,
    set_generation_label,
    set_source_refs,
    should_defer_generation_export,
    submit_with_trace_context,
)
from app.tracing.models import GenerationTraceData, WorkflowFrame, WorkflowTraceContext
from app.tracing.providers.registry import get_providers, tracing_enabled
from app.tracing.sanitize import sanitize_secrets

logger = logging.getLogger(__name__)

# Re-export helpers used by callers
__all__ = [
    "traced_workflow",
    "atraced_workflow",
    "record_generation",
    "flush_tracing",
    "shutdown_tracing",
    "set_generation_label",
    "set_source_refs",
    "submit_with_trace_context",
    "get_run_id",
    "get_doc_name",
    "get_workflow",
    "get_source_refs",
]


def _safe_doc_name(name: str | None, fallback: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE).strip("._")
    return s or fallback


def _safe_sanitize(value: Any, *, fallback: Any = None) -> Any:
    """Sanitize without ever raising into business logic."""
    try:
        return sanitize_secrets(value)
    except Exception:
        logger.warning("[tracing] sanitize failed — using fallback", exc_info=True)
        return fallback


def _resolve_context(
    workflow: str,
    *,
    run_id: str | None,
    doc_name: str | None,
    session_id: str | None,
    job_id: str | None,
    course_run_id: str | None,
    course_id: str | None,
    metadata: dict[str, Any] | None,
) -> WorkflowTraceContext:
    parent = current_frame()
    parent_ctx = parent.context if parent else None

    resolved_run_id = (
        run_id
        or (parent_ctx.run_id if parent_ctx else None)
        or f"{workflow}-{uuid.uuid4().hex[:8]}"
    )
    resolved_doc = _safe_doc_name(
        doc_name or (parent_ctx.doc_name if parent_ctx else None),
        workflow,
    )
    raw_meta = dict(metadata or {})
    safe_meta = _safe_sanitize(raw_meta, fallback={})
    if not isinstance(safe_meta, dict):
        safe_meta = {"_sanitized_metadata": safe_meta}

    return WorkflowTraceContext(
        workflow=workflow,
        run_id=resolved_run_id,
        session_id=session_id
        or (parent_ctx.session_id if parent_ctx else None)
        or course_run_id
        or (parent_ctx.course_run_id if parent_ctx else None),
        job_id=job_id or (parent_ctx.job_id if parent_ctx else None),
        course_run_id=course_run_id
        or (parent_ctx.course_run_id if parent_ctx else None),
        course_id=course_id or (parent_ctx.course_id if parent_ctx else None),
        doc_name=resolved_doc,
        metadata=safe_meta,
    )


@contextmanager
def traced_workflow(
    workflow: str,
    *,
    run_id: str | None = None,
    doc_name: str | None = None,
    session_id: str | None = None,
    job_id: str | None = None,
    course_run_id: str | None = None,
    course_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    input_data: Any = None,
    source_refs: list[str] | tuple[str, ...] | None = None,
) -> Iterator[WorkflowTraceContext]:
    """Sync workflow CM. Root flushes on exit; nested restores parent handles."""
    is_root = current_frame() is None
    ctx = _resolve_context(
        workflow,
        run_id=run_id,
        doc_name=doc_name,
        session_id=session_id,
        job_id=job_id,
        course_run_id=course_run_id,
        course_id=course_id,
        metadata=metadata,
    )
    safe_input = (
        _safe_sanitize(input_data, fallback="[SANITIZE_FAILED]")
        if input_data is not None
        else None
    )
    parent_frame = current_frame()
    provider_handles: dict[str, Any] = {}

    frame = WorkflowFrame(
        context=ctx,
        provider_handles=provider_handles,
        is_root=is_root,
    )
    tokens = push_frame(frame)
    source_refs_token = None
    if source_refs is not None:
        source_refs_token = set_source_refs(source_refs)

    business_exc: BaseException | None = None
    entered: list[tuple[Any, Any]] = []
    try:
        if tracing_enabled():
            for provider in get_providers():
                parent_handle = None
                if parent_frame is not None:
                    parent_handle = parent_frame.provider_handles.get(provider.name)
                try:
                    cm = provider.start_workflow(
                        ctx,
                        parent=parent_handle,
                        input_data=safe_input,
                    )
                    handle = cm.__enter__()
                    entered.append((provider, cm))
                    provider_handles[provider.name] = handle
                except Exception:
                    logger.warning(
                        "[tracing] provider %s failed to start workflow %s",
                        provider.name,
                        workflow,
                        exc_info=True,
                    )
        try:
            yield ctx
        except BaseException as exc:
            business_exc = exc
            raise
    finally:
        exc_info: tuple[Any, Any, Any] | tuple[None, None, None]
        if business_exc is not None:
            exc_info = (type(business_exc), business_exc, business_exc.__traceback__)
        else:
            exc_info = (None, None, None)
        for provider, cm in reversed(entered):
            try:
                cm.__exit__(*exc_info)
            except Exception:
                logger.warning(
                    "[tracing] provider %s failed to close workflow %s",
                    provider.name,
                    workflow,
                    exc_info=True,
                )
                # Never replace the original business exception.
        if source_refs_token is not None:
            reset_source_refs(source_refs_token)
        pop_frame(tokens)
        if is_root:
            # Drop any label that survived without a generation export.
            clear_generation_label()
            flush_tracing()


@asynccontextmanager
async def atraced_workflow(
    workflow: str,
    *,
    run_id: str | None = None,
    doc_name: str | None = None,
    session_id: str | None = None,
    job_id: str | None = None,
    course_run_id: str | None = None,
    course_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    input_data: Any = None,
    source_refs: list[str] | tuple[str, ...] | None = None,
) -> AsyncIterator[WorkflowTraceContext]:
    """Async wrapper around :func:`traced_workflow`."""
    with traced_workflow(
        workflow,
        run_id=run_id,
        doc_name=doc_name,
        session_id=session_id,
        job_id=job_id,
        course_run_id=course_run_id,
        course_id=course_id,
        metadata=metadata,
        input_data=input_data,
        source_refs=source_refs,
    ) as ctx:
        yield ctx


def record_generation(data: GenerationTraceData) -> None:
    """Record one LLM generation to all active providers (after sanitize).

    Always clears a pending generation label — including when tracing is
    disabled — so labels cannot leak across calls.
    """
    label = consume_generation_label()

    if not tracing_enabled():
        return
    if not (data.agent or "").strip():
        return
    if should_defer_generation_export():
        return

    frame = current_frame()
    try:
        meta = dict(data.metadata or {})
    except Exception:
        meta = {}
    if frame is not None:
        meta.setdefault("run_id", frame.context.run_id)
        meta.setdefault("doc_name", frame.context.doc_name)
        meta.setdefault("workflow", frame.context.workflow)
        meta.setdefault("job_id", frame.context.job_id)
        meta.setdefault("course_run_id", frame.context.course_run_id)
        meta.setdefault("course_id", frame.context.course_id)
        meta.setdefault("session_id", frame.context.session_id)
    else:
        meta.setdefault("run_id", get_run_id() or None)
        meta.setdefault("doc_name", get_doc_name() or None)
        meta.setdefault("workflow", get_workflow() or None)
    if label:
        meta["generation_label"] = label
    refs = get_source_refs()
    if refs:
        meta.setdefault("source_refs", refs)

    try:
        model_parameters = dict(data.model_parameters or {})
    except Exception:
        model_parameters = {}
    try:
        token_usage = dict(data.token_usage) if data.token_usage else None
    except Exception:
        token_usage = None

    enriched = GenerationTraceData(
        agent=data.agent,
        system_prompt=data.system_prompt,
        user_input=data.user_input,
        response=data.response,
        model=data.model,
        model_parameters=model_parameters,
        token_usage=token_usage,
        latency_ms=data.latency_ms,
        error=data.error,
        metadata=meta,
        observation_name=data.observation_name or label or None,
    )

    # Fail-safe sanitize — never raise into the chat/business finally block.
    safe = GenerationTraceData(
        agent=enriched.agent,
        system_prompt=_safe_sanitize(enriched.system_prompt, fallback=""),
        user_input=_safe_sanitize(enriched.user_input, fallback=""),
        response=_safe_sanitize(enriched.response, fallback=""),
        model=enriched.model,
        model_parameters=_safe_sanitize(enriched.model_parameters, fallback={}) or {},
        token_usage=enriched.token_usage,
        latency_ms=enriched.latency_ms,
        error=(
            _safe_sanitize(enriched.error, fallback="[SANITIZE_FAILED]")
            if enriched.error
            else None
        ),
        metadata=_safe_sanitize(enriched.metadata, fallback={}) or {},
        observation_name=enriched.observation_name,
    )
    if not isinstance(safe.metadata, dict):
        safe = GenerationTraceData(
            agent=safe.agent,
            system_prompt=safe.system_prompt,
            user_input=safe.user_input,
            response=safe.response,
            model=safe.model,
            model_parameters=safe.model_parameters
            if isinstance(safe.model_parameters, dict)
            else {},
            token_usage=safe.token_usage,
            latency_ms=safe.latency_ms,
            error=safe.error,
            metadata={"_sanitized_metadata": safe.metadata},
            observation_name=safe.observation_name,
        )
    if not isinstance(safe.model_parameters, dict):
        safe = GenerationTraceData(
            agent=safe.agent,
            system_prompt=safe.system_prompt,
            user_input=safe.user_input,
            response=safe.response,
            model=safe.model,
            model_parameters={},
            token_usage=safe.token_usage,
            latency_ms=safe.latency_ms,
            error=safe.error,
            metadata=safe.metadata,
            observation_name=safe.observation_name,
        )

    for provider in get_providers():
        parent = None
        if frame is not None:
            parent = frame.provider_handles.get(provider.name)
        try:
            provider.record_generation(safe, parent=parent)
        except Exception:
            logger.warning(
                "[tracing] provider %s failed to record generation for agent=%s",
                provider.name,
                data.agent,
                exc_info=True,
            )


def flush_tracing() -> None:
    """Flush all active providers. Prefer root workflow lifecycle over manual calls."""
    if not tracing_enabled():
        return
    for provider in get_providers():
        try:
            provider.flush()
        except Exception:
            logger.warning(
                "[tracing] provider %s flush failed",
                provider.name,
                exc_info=True,
            )


def shutdown_tracing() -> None:
    """Best-effort flush + shutdown for process exit."""
    flush_tracing()
    for provider in get_providers():
        try:
            provider.shutdown()
        except Exception:
            logger.warning(
                "[tracing] provider %s shutdown failed",
                provider.name,
                exc_info=True,
            )


def stack_depth() -> int:
    return len(get_stack())
