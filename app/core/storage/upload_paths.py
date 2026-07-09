"""Path helpers and validation for uploaded source documents."""

from __future__ import annotations

import re
from pathlib import Path

ALLOWED_UPLOAD_EXTENSIONS = frozenset({".docx", ".pdf", ".json"})
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB

CONTENT_TYPES: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".json": "application/json",
}


def parse_course_topic(course_topic: str) -> str:
    """Sanitize the mandatory course topic into a safe folder name."""
    cleaned = re.sub(r"[^\w\s-]", "", (course_topic or "").strip())
    slug = re.sub(r"[\s_]+", "-", cleaned).strip("-").lower()
    if not slug:
        raise ValueError(
            "courseTopic must contain at least one alphanumeric character.")
    return slug[:120]


def uploads_blob_path(folder: str, filename: str) -> str:
    """Build the blob path within the uploaded-documents container."""
    safe_name = Path(filename).name
    return f"{folder}/{safe_name}"


def validate_upload_filename(filename: str | None) -> str:
    """Validate extension and return a safe basename."""
    if not filename or not filename.strip():
        raise ValueError("Uploaded file must have a filename.")
    safe_name = Path(filename).name.strip()
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type '{ext or '(none)'}'. Allowed: {allowed}")
    return safe_name
