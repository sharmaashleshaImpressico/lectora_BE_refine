"""Validate structure-preserving AI paragraph output against the source blocks."""

from __future__ import annotations

import logging
from typing import Any

from app.ai.agents.content_transformation_agent.errors import ContentTransformationError

logger = logging.getLogger(__name__)


def _fail(message: str) -> None:
    raise ContentTransformationError(message)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _table_dimensions(block: dict[str, Any]) -> tuple[int, int, tuple[int, ...]]:
    headers = _as_list(block.get("headers"))
    rows = _as_list(block.get("rows"))
    row_widths = tuple(len(row) if isinstance(row, list) else -1 for row in rows)
    return len(headers), len(rows), row_widths


def _protected_snapshot(block: dict[str, Any]) -> dict[str, Any]:
    """Metadata that must remain structurally identical."""
    snapshot: dict[str, Any] = {
        "id": str(block.get("id") or ""),
        "type": str(block.get("type") or ""),
    }
    if "label" in block:
        snapshot["label"] = block.get("label")

    btype = snapshot["type"]
    if btype in {"bullet_list", "numbered_list", "sub_bullet_list"}:
        snapshot["items_count"] = len(_as_list(block.get("items")))
    elif btype == "table":
        header_count, row_count, row_widths = _table_dimensions(block)
        snapshot["headers_count"] = header_count
        snapshot["rows_count"] = row_count
        snapshot["row_widths"] = row_widths
    elif btype == "knowledge_check":
        snapshot["options_count"] = len(_as_list(block.get("options")))
        if "correct_answer" in block:
            snapshot["correct_answer"] = block.get("correct_answer")
    return snapshot


def validate_preserved_paragraphs(
    source: list[dict[str, Any]],
    result: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure result blocks preserve ids, order, types, and protected metadata.

    Models often omit ``id`` (and occasionally ``type``/``label``). When the
    response is positionally aligned with the source, restore those protected
    fields from the source instead of failing the whole transform.
    """
    if not isinstance(result, list):
        _fail("Model paragraphs payload must be a list.")

    if len(result) != len(source):
        _fail(
            f"Block count changed: expected {len(source)}, got {len(result)}."
        )

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    repaired_ids = 0
    repaired_types = 0

    for index, (src, out) in enumerate(zip(source, result)):
        if not isinstance(out, dict):
            _fail(f"paragraphs[{index}] must be an object.")

        src_id = str(src.get("id") or "").strip()
        src_type = str(src.get("type") or "").strip()
        out_id = str(out.get("id") or "").strip()
        out_type = str(out.get("type") or "").strip()

        if not src_id or not src_type:
            _fail(f"Source paragraphs[{index}] is missing id or type.")

        # Positional repair: source ids/types are authoritative when the model
        # returns transformed text blocks without copying metadata.
        if not out_id:
            out_id = src_id
            repaired_ids += 1
        if not out_type:
            out_type = src_type
            repaired_types += 1

        if out_id in seen_ids:
            _fail(f"Duplicate block id '{out_id}' in transformed paragraphs.")
        seen_ids.add(out_id)

        if out_id != src_id:
            _fail(
                f"Block id mismatch at index {index}: expected '{src_id}', got '{out_id}'."
            )
        if out_type != src_type:
            _fail(
                f"Block type mismatch for id '{src_id}': expected '{src_type}', "
                f"got '{out_type}'."
            )

        out_for_meta = dict(out)
        out_for_meta["id"] = out_id
        out_for_meta["type"] = out_type
        if "label" in src and not str(out.get("label") or "").strip():
            out_for_meta["label"] = src.get("label")

        src_meta = _protected_snapshot(src)
        out_meta = _protected_snapshot(out_for_meta)
        for key, expected in src_meta.items():
            if out_meta.get(key) != expected:
                _fail(
                    f"Protected metadata '{key}' changed for block '{src_id}' "
                    f"(type={src_type})."
                )

        merged = dict(src)
        for key, value in out.items():
            if key in {"id", "type", "label"}:
                continue
            merged[key] = value
        merged["id"] = src_id
        merged["type"] = src_type
        if "label" in src:
            merged["label"] = src.get("label")
        normalized.append(merged)

    if repaired_ids or repaired_types:
        logger.info(
            "[content_transformation] Restored missing block metadata from source | "
            "repaired_ids=%d repaired_types=%d blocks=%d",
            repaired_ids,
            repaired_types,
            len(source),
        )

    return normalized


def paragraphs_to_flat_content(paragraphs: list[dict[str, Any]]) -> str:
    """Compatibility flat preview derived from structured blocks."""
    parts: list[str] = []
    for block in paragraphs:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        if btype in {"text", "heading_3", "heading_4", "important_callout", "callout"}:
            text = str(block.get("content") or "").strip()
            if text:
                parts.append(text)
        elif btype in {"bullet_list", "sub_bullet_list", "numbered_list"}:
            parts.extend(
                str(item).strip()
                for item in _as_list(block.get("items"))
                if str(item).strip()
            )
        elif btype == "table":
            headers = [
                str(h).strip() for h in _as_list(block.get("headers")) if str(h).strip()
            ]
            if headers:
                parts.append(" | ".join(headers))
            for row in _as_list(block.get("rows")):
                if isinstance(row, list):
                    cells = [str(c).strip() for c in row if str(c).strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            caption = str(block.get("caption") or "").strip()
            if caption:
                parts.append(caption)
        elif btype == "knowledge_check":
            question = str(block.get("question") or "").strip()
            if question:
                parts.append(question)
    return "\n\n".join(parts)


__all__ = [
    "paragraphs_to_flat_content",
    "validate_preserved_paragraphs",
]
