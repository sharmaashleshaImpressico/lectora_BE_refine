"""Provider protocol for vendor-neutral tracing sinks."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol

from app.tracing.models import GenerationTraceData, WorkflowTraceContext


class TracingProvider(Protocol):
    """Minimal provider interface. Handles are opaque and provider-specific."""

    name: str

    def start_workflow(
        self,
        ctx: WorkflowTraceContext,
        *,
        parent: Any | None,
        input_data: Any = None,
    ) -> AbstractContextManager[Any]:
        """Return a CM that yields an opaque handle for this provider."""
        ...

    def record_generation(
        self,
        data: GenerationTraceData,
        *,
        parent: Any | None,
    ) -> None: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...
