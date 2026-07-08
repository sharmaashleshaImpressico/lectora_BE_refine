"""Image record validation helpers for A0 document parsing."""

from __future__ import annotations

from typing import Any


def filter_stored_image_records(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only image records that reference a stored file path."""
    valid: list[dict[str, Any]] = []
    for image in images or []:
        if not isinstance(image, dict):
            continue
        path = image.get("path") or image.get("file") or image.get("filename")
        if path:
            valid.append(image)
    return valid


def coerce_image_bytes_for_storage(
    img_bytes: bytes,
    ext: str,
    **kwargs: Any,
) -> tuple[bytes, str, dict[str, Any]]:
    """Validate image bytes before persisting to disk (stub for disabled extractors)."""
    _ = kwargs
    return img_bytes, ext, {"valid": bool(img_bytes)}


__all__ = ["coerce_image_bytes_for_storage", "filter_stored_image_records"]
