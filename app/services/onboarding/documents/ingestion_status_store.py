"""In-memory ingestion status tracking for uploaded documents."""

from __future__ import annotations

import threading
import time
from typing import Literal

IngestionStatusValue = Literal["pending", "processing", "indexed", "parsed", "failed"]

_lock = threading.Lock()
_statuses: dict[str, dict[str, object]] = {}


def set_status(
    document_id: str,
    status: IngestionStatusValue,
    *,
    total_chunks: int = 0,
    error: str | None = None,
) -> None:
    """Record or update ingestion status for a document."""
    with _lock:
        _statuses[document_id] = {
            "document_id": document_id,
            "status": status,
            "total_chunks": total_chunks,
            "error": error,
            "updated_at": time.time(),
        }


def get_status(document_id: str) -> dict[str, object] | None:
    """Return the latest status dict for a document, if known."""
    with _lock:
        record = _statuses.get(document_id)
        return dict(record) if record is not None else None
