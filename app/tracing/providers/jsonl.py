"""Local JSONL tracing sink."""

from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.tracing.models import GenerationTraceData, WorkflowTraceContext
from app.tracing.sanitize import truncate_text

logger = logging.getLogger(__name__)

_LOGS_ROOT = Path(__file__).resolve().parents[2] / "logs"
_write_lock = threading.Lock()


def _safe_dir_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE).strip("._")
    return s or "unknown"


class JsonlTracingProvider:
    """Appends generation records under ``app/logs/{doc_name}/{agent}/``."""

    name = "jsonl"

    def __init__(self, *, max_chars: int | None = None) -> None:
        self._max_chars = max_chars

    @contextmanager
    def start_workflow(
        self,
        ctx: WorkflowTraceContext,
        *,
        parent: Any | None,
        input_data: Any = None,
    ) -> Iterator[dict[str, Any]]:
        handle = {
            "workflow": ctx.workflow,
            "run_id": ctx.run_id,
            "doc_name": ctx.doc_name or ctx.workflow,
            "parent": parent,
        }
        try:
            yield handle
        finally:
            pass

    def record_generation(
        self,
        data: GenerationTraceData,
        *,
        parent: Any | None,
    ) -> None:
        parent_doc = None
        if isinstance(parent, dict):
            parent_doc = parent.get("doc_name")
        doc_name = _safe_dir_name(
            str(data.metadata.get("doc_name") or parent_doc or "unknown")
        )
        agent = _safe_dir_name(data.agent or "unknown_agent")
        log_path = _LOGS_ROOT / doc_name / agent / "llm_traces.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "run_id": data.metadata.get("run_id"),
            "doc_name": data.metadata.get("doc_name"),
            "workflow": data.metadata.get("workflow"),
            "agent": data.agent,
            "deployment": data.model,
            "latency_ms": data.latency_ms,
            "prompt_tokens": (data.token_usage or {}).get("input"),
            "completion_tokens": (data.token_usage or {}).get("output"),
            "total_tokens": (data.token_usage or {}).get("total"),
            "error": data.error,
            "model_parameters": data.model_parameters,
            "prompt_metadata": data.metadata,
            "observation_name": data.observation_name,
            "system_prompt": data.system_prompt,
            "user_msg": data.user_input,
            "response": data.response,
        }
        if self._max_chars:
            record = truncate_text(record, max_chars=self._max_chars)

        with _write_lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def flush(self) -> None:
        return

    def shutdown(self) -> None:
        return
