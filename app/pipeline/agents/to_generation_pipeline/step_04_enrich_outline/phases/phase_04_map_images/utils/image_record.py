"""Normalize image records for course_spec image_map output."""

from __future__ import annotations

from typing import Any


def to_mapped_image_record(image: dict[str, Any]) -> dict[str, Any]:
    """Return the image payload stored on course_spec sections."""
    return {
        "id": image["id"],
        "saved_path": image["saved_path"],
        "media_filename": image["media_filename"],
        "size_cm": image["size_cm"],
        "size_bytes": image["size_bytes"],
        "para_idx": image["para_idx"],
        "caption": image.get("caption", ""),
        "has_caption": image.get("has_caption", False),
        "alt_text": image.get("alt_text", ""),
    }
