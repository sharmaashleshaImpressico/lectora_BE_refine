"""Langfuse tracing provider adapter.

This is the ONLY application module allowed to import the external ``langfuse`` package.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.tracing.models import GenerationTraceData, WorkflowTraceContext
from app.tracing.sanitize import sanitize_secrets, truncate_text

logger = logging.getLogger(__name__)

_DISPLAY_AGENTS: dict[str, str] = {
    "A0": "A0",
    "A0_TO": "A0",
    "TO_REGEN": "A0",
    "A1": "A1",
    "A2": "A2",
    "CONTENT_REFINE": "S2_REFINE",
    "S1": "S1",
    "S1_TO_REFINE": "S1_REFINE",
    "S2": "S2",
    "S2_REFINE": "S2_REFINE",
    "RT_GEN": "RT_GENERATION",
    "RT_REGEN": "RT_GENERATION",
    "RT_VALIDATOR": "RT_VALIDATOR",
    "RT_REFINE": "RT_REFINEMENT",
    "LO_GEN": "LO_GENERATION",
    "LO_VALIDATOR": "LO_VALIDATOR",
    "LO_REFINE": "LO_REFINEMENT",
    "LO_REGEN": "LO_REFINEMENT",
}


def _display_agent(agent: str) -> str:
    label = (agent or "").strip()
    if not label:
        return "LLM"
    return _DISPLAY_AGENTS.get(label, label)


class LangfuseTracingProvider:
    """Langfuse adapter. Parent handles are Langfuse observation objects."""

    name = "langfuse"

    def __init__(
        self,
        *,
        public_key: str | None,
        secret_key: str | None,
        host: str | None = None,
        environment: str | None = None,
        max_chars: int | None = 50_000,
    ) -> None:
        self._public_key = (public_key or "").strip()
        self._secret_key = (secret_key or "").strip()
        self._host = (host or "").strip() or "https://cloud.langfuse.com"
        self._environment = (environment or "").strip() or None
        self._max_chars = max_chars
        self._client: Any | None | bool = None

    def _get_client(self) -> Any | None:
        if self._client is False:
            return None
        if self._client is not None:
            return self._client
        if not self._public_key or not self._secret_key:
            logger.warning("[tracing.langfuse] missing credentials — provider disabled")
            self._client = False
            return None
        try:
            from langfuse import Langfuse  # noqa: PLC0415 — lazy, adapter-only
        except Exception as exc:  # pragma: no cover
            logger.warning("[tracing.langfuse] package unavailable: %s", exc)
            self._client = False
            return None
        try:
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host,
                environment=self._environment,
            )
            return self._client
        except Exception as exc:
            logger.warning("[tracing.langfuse] init failed: %s", exc)
            self._client = False
            return None

    @contextmanager
    def start_workflow(
        self,
        ctx: WorkflowTraceContext,
        *,
        parent: Any | None,
        input_data: Any = None,
    ) -> Iterator[Any]:
        client = self._get_client()
        if client is None:
            yield None
            return

        # Defense in depth — service already sanitizes; never export raw payloads.
        payload_in = truncate_text(
            sanitize_secrets(input_data), max_chars=self._max_chars
        )
        safe_ctx_meta = sanitize_secrets(ctx.metadata) or {}
        if not isinstance(safe_ctx_meta, dict):
            safe_ctx_meta = {"_sanitized_metadata": safe_ctx_meta}
        metadata = {
            "run_id": ctx.run_id,
            "doc_name": ctx.doc_name,
            "job_id": ctx.job_id,
            "course_run_id": ctx.course_run_id,
            "course_id": ctx.course_id,
            "session_id": ctx.session_id,
            **safe_ctx_meta,
        }
        metadata = {k: v for k, v in metadata.items() if v not in (None, "")}

        trace_context = None
        if parent is None:
            try:
                trace_id = client.create_trace_id(seed=f"app:{ctx.run_id}")
                trace_context = {"trace_id": trace_id}
            except Exception as exc:
                logger.warning("[tracing.langfuse] create_trace_id failed: %s", exc)

        attr_cm = None
        if parent is None:
            try:
                from langfuse import propagate_attributes  # noqa: PLC0415

                attr_cm = propagate_attributes(
                    session_id=ctx.session_id or ctx.course_run_id,
                    metadata={
                        k: str(v)
                        for k, v in {
                            "run_id": ctx.run_id,
                            "workflow": ctx.workflow,
                            "job_id": ctx.job_id,
                            "course_run_id": ctx.course_run_id,
                        }.items()
                        if v
                    },
                    tags=[ctx.workflow],
                    trace_name=ctx.workflow,
                )
            except Exception as exc:
                logger.warning("[tracing.langfuse] propagate_attributes unavailable: %s", exc)

        obs_cm = None
        span = None
        attr_entered = False
        try:
            if attr_cm is not None:
                attr_cm.__enter__()
                attr_entered = True
            obs_cm = client.start_as_current_observation(
                as_type="span",
                name=ctx.workflow,
                trace_context=trace_context,
                input=payload_in,
                metadata=metadata or None,
            )
            span = obs_cm.__enter__()
        except Exception as exc:
            logger.warning("[tracing.langfuse] workflow span enter failed: %s", exc)
            if attr_entered and attr_cm is not None:
                try:
                    attr_cm.__exit__(None, None, None)
                except Exception:
                    pass
            yield None
            return

        exc_info: tuple[Any, Any, Any] | None = None
        try:
            try:
                yield span
            except Exception as exc:
                try:
                    span.update(level="ERROR", status_message=str(exc))
                except Exception:
                    pass
                raise
        except Exception:
            import sys

            exc_info = sys.exc_info()
            raise
        finally:
            if obs_cm is not None:
                try:
                    if exc_info:
                        obs_cm.__exit__(*exc_info)
                    else:
                        obs_cm.__exit__(None, None, None)
                except Exception as exit_exc:
                    logger.warning(
                        "[tracing.langfuse] workflow span exit failed: %s", exit_exc
                    )
            if attr_entered and attr_cm is not None:
                try:
                    if exc_info:
                        attr_cm.__exit__(*exc_info)
                    else:
                        attr_cm.__exit__(None, None, None)
                except Exception:
                    pass

    def record_generation(
        self,
        data: GenerationTraceData,
        *,
        parent: Any | None,
    ) -> None:
        client = self._get_client()
        if client is None:
            return

        label = (data.observation_name or data.metadata.get("generation_label") or "").strip()
        base = _display_agent(data.agent)
        name = f"{base} · {label}" if label else base

        user_content = (
            data.user_input
            if isinstance(data.user_input, str)
            else str(data.user_input)
        )
        messages = [
            {"role": "system", "content": data.system_prompt or ""},
            {"role": "user", "content": user_content},
        ]
        messages = truncate_text(messages, max_chars=self._max_chars)
        output = {"error": data.error} if data.error else data.response
        output = truncate_text(output, max_chars=self._max_chars)

        usage = data.token_usage or {}
        usage_details = {
            k: int(v)
            for k, v in {
                "input": usage.get("input"),
                "output": usage.get("output"),
                "total": usage.get("total"),
            }.items()
            if v is not None
        } or None

        model_parameters = {
            k: v for k, v in (data.model_parameters or {}).items() if v is not None
        } or None

        metadata = {
            "agent": base,
            "trace_agent": data.agent,
            "run_id": data.metadata.get("run_id"),
            "doc_name": data.metadata.get("doc_name"),
            "workflow": data.metadata.get("workflow"),
            "job_id": data.metadata.get("job_id"),
            "course_run_id": data.metadata.get("course_run_id"),
            "latency_ms": data.latency_ms,
        }
        for key in (
            "purpose",
            "step",
            "chunk_id",
            "document_id",
            "section_id",
            "chunk_title",
            "generation_label",
        ):
            value = (data.metadata or {}).get(key)
            if value not in (None, ""):
                metadata[key] = value
        metadata = {k: v for k, v in metadata.items() if v not in (None, "")}

        _ = parent  # attachment uses active OTel span; handle kept for API symmetry
        try:
            with client.start_as_current_observation(
                as_type="generation",
                name=name,
                input=messages,
                output=output,
                metadata=metadata or None,
                level="ERROR" if data.error else "DEFAULT",
                status_message=data.error,
                model=data.model,
                model_parameters=model_parameters,
                usage_details=usage_details,
                completion_start_time=datetime.now(timezone.utc),
            ):
                pass
        except Exception as exc:
            logger.warning("[tracing.langfuse] generation failed: %s", exc)

    def flush(self) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.flush()
        except Exception as exc:
            logger.warning("[tracing.langfuse] flush failed: %s", exc)

    def shutdown(self) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.shutdown()
        except Exception as exc:
            logger.warning("[tracing.langfuse] shutdown failed: %s", exc)
