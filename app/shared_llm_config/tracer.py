"""Legacy tracer helpers — LLM tracing is delegated to ``app.tracing``.

This module must NOT import the external ``langfuse`` package.
Embedding/retrieval JSONL writers remain here for Phase 1 callers.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, List, Optional

from app.tracing.context import (
    defer_generation_export,
    get_doc_name,
    get_run_id,
    get_source_refs,
    set_source_refs,
    should_defer_generation_export,
    submit_with_trace_context,
)
from app.tracing.models import GenerationTraceData
from app.tracing.service import (
    record_generation,
)

logger = logging.getLogger(__name__)

_LOGS_ROOT = Path(__file__).resolve().parent.parent / "logs"
_write_lock = threading.Lock()


@contextmanager
def defer_s1_generation_export() -> Generator[None, None, None]:
    """Defer S1 generation export until post-processed validation is recorded."""
    with defer_generation_export():
        yield


# Backward-compatible name used by older S1 call sites.
defer_s1_langfuse_tracing = defer_s1_generation_export
should_defer_s1_langfuse = should_defer_generation_export

@dataclass
class LLMTrace:
    """Legacy dataclass retained for embedding/call-site compatibility."""

    agent: str
    deployment: str
    system_prompt: str
    user_msg: str
    response: str
    latency_ms: float
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    error: Optional[str] = None
    source_refs: list[str] = field(default_factory=get_source_refs)
    model_parameters: dict[str, Any] = field(default_factory=dict)
    prompt_metadata: dict[str, Any] = field(default_factory=dict)
    observation_name: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str = field(default_factory=get_run_id)
    doc_name: str = field(default_factory=get_doc_name)


@dataclass
class EmbeddingTrace:
    agent: str
    deployment: str
    level: str
    batch_index: int
    batch_size: int
    dimensions: int
    latency_ms: float
    total_tokens: int = 0
    error: Optional[str] = None
    document_id: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str = field(default_factory=get_run_id)
    doc_name: str = field(default_factory=get_doc_name)


@dataclass
class RetrievalTrace:
    agent: str
    retrieval_type: str
    query: str
    result_count: int
    latency_ms: float
    top_score: Optional[float] = None
    threshold: Optional[float] = None
    has_semantic_ranker: bool = False
    document_id: Optional[str] = None
    error: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    filters_applied: Optional[dict] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str = field(default_factory=get_run_id)
    doc_name: str = field(default_factory=get_doc_name)


def _ensure_log_dir() -> None:
    _LOGS_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_dir_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE).strip("._")
    return s or "unknown"


def write_embedding_trace(trace: EmbeddingTrace) -> None:
    """Append one embedding trace record to JSONL (local only)."""
    _ensure_log_dir()
    safe_doc = _safe_dir_name(trace.doc_name or "ingestion")
    log_path = _LOGS_ROOT / safe_doc / (trace.agent or "EMBED") / "embedding_traces.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": trace.timestamp,
        "run_id": trace.run_id,
        "doc_name": trace.doc_name,
        "agent": trace.agent,
        "deployment": trace.deployment,
        "level": trace.level,
        "batch_index": trace.batch_index,
        "batch_size": trace.batch_size,
        "dimensions": trace.dimensions,
        "latency_ms": round(trace.latency_ms, 2),
        "total_tokens": trace.total_tokens,
        "document_id": trace.document_id,
        "source_refs": trace.source_refs,
        "error": trace.error,
    }
    with _write_lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_retrieval_trace(trace: RetrievalTrace) -> None:
    """Append one retrieval trace record to JSONL (local only)."""
    _ensure_log_dir()
    safe_doc = _safe_dir_name(trace.doc_name or "pipeline")
    log_path = (
        _LOGS_ROOT / safe_doc / (trace.agent or "RETRIEVAL") / "retrieval_traces.jsonl"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": trace.timestamp,
        "run_id": trace.run_id,
        "doc_name": trace.doc_name,
        "agent": trace.agent,
        "retrieval_type": trace.retrieval_type,
        "query": trace.query,
        "result_count": trace.result_count,
        "latency_ms": round(trace.latency_ms, 2),
        "top_score": trace.top_score,
        "threshold": trace.threshold,
        "has_semantic_ranker": trace.has_semantic_ranker,
        "document_id": trace.document_id,
        "source_refs": trace.source_refs,
        "metadata": trace.metadata,
        "filters_applied": trace.filters_applied,
        "error": trace.error,
    }
    with _write_lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_trace(trace: LLMTrace) -> None:
    """Delegate LLM traces to the vendor-neutral façade."""
    if trace.agent == "S1" and should_defer_generation_export():
        return
    record_generation(
        GenerationTraceData(
            agent=trace.agent,
            system_prompt=trace.system_prompt,
            user_input=trace.user_msg,
            response=trace.response,
            model=trace.deployment,
            model_parameters=dict(trace.model_parameters or {}),
            token_usage={
                "input": trace.prompt_tokens,
                "output": trace.completion_tokens,
                "total": trace.total_tokens,
            },
            latency_ms=trace.latency_ms,
            error=trace.error,
            metadata=dict(trace.prompt_metadata or {}),
            observation_name=trace.observation_name,
        )
    )


def write_s1_semantic_trace(
    *,
    deployment: str,
    system_prompt: str,
    user_msg: str,
    validated_output: dict[str, Any],
    latency_ms: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    """Record finalized S1 validation output via the generic tracing API."""
    record_generation(
        GenerationTraceData(
            agent="S1",
            system_prompt=system_prompt,
            user_input=user_msg,
            response=json.dumps(validated_output, ensure_ascii=False),
            model=deployment,
            token_usage={
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": total_tokens,
            },
            latency_ms=latency_ms,
            metadata={"purpose": "semantic validation"},
            observation_name="S1",
        )
    )


# Backward-compatible alias
write_s1_semantic_langfuse_trace = write_s1_semantic_trace


__all__ = [
    "EmbeddingTrace",
    "LLMTrace",
    "RetrievalTrace",
    "defer_s1_generation_export",
    "defer_s1_langfuse_tracing",
    "get_doc_name",
    "get_run_id",
    "get_source_refs",
    "set_source_refs",
    "should_defer_generation_export",
    "should_defer_s1_langfuse",
    "submit_with_trace_context",
    "write_embedding_trace",
    "write_retrieval_trace",
    "write_s1_semantic_langfuse_trace",
    "write_s1_semantic_trace",
    "write_trace",
]
