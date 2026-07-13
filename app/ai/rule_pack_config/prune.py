"""Strip empty/None values from LLM prompt payloads before they're sent out.

Native replacement for ``lectora_backend.pipeline.rule_pack_config.prune``.
"""

from __future__ import annotations

from typing import Any

# Values that are considered "empty" and get dropped. Note ``False`` and ``0``
# are intentionally NOT included here — several call sites (e.g. TO S1 AI
# validation payload building) rely on booleans like `include_case_studies`
# surviving pruning so downstream `is not None` checks still see them.
_EMPTY_SENTINELS: tuple[Any, ...] = (None, "", [], {}, ())


def prune_empty_payload_values(payload: Any) -> Any:
    """Recursively remove ``None``/empty-string/empty-list/empty-dict values.

    Dicts have empty-valued keys dropped (after recursing into surviving
    nested values); lists/tuples have their items pruned recursively (empty
    resulting items are dropped). Any other value is returned unchanged.
    """
    if isinstance(payload, dict):
        pruned: dict[Any, Any] = {}
        for key, value in payload.items():
            value = prune_empty_payload_values(value)
            if isinstance(value, bool):
                pruned[key] = value
            elif not any(value is s or value == s for s in _EMPTY_SENTINELS):
                pruned[key] = value
        return pruned

    if isinstance(payload, list):
        return [
            item
            for item in (prune_empty_payload_values(item) for item in payload)
            if isinstance(item, bool) or not any(item is s or item == s for s in _EMPTY_SENTINELS)
        ]

    return payload


__all__ = ["prune_empty_payload_values"]
