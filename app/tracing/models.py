"""Vendor-neutral tracing data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowTraceContext:
    """Domain context for a workflow span (root or nested)."""

    workflow: str
    run_id: str
    session_id: str | None = None
    job_id: str | None = None
    course_run_id: str | None = None
    course_id: str | None = None
    doc_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationTraceData:
    """One LLM generation recorded by the central chat wrapper."""

    agent: str
    system_prompt: str | None
    user_input: Any
    response: Any
    model: str | None = None
    model_parameters: dict[str, Any] = field(default_factory=dict)
    token_usage: dict[str, Any] | None = None
    latency_ms: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_name: str | None = None


@dataclass
class WorkflowFrame:
    """One level on the workflow ContextVar stack."""

    context: WorkflowTraceContext
    provider_handles: dict[str, Any]
    is_root: bool
    tokens: list[Any] = field(default_factory=list)
