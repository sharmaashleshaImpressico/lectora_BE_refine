"""Rule-pack resolution for content generation/validation.

``context`` is a plain dict assembled by the caller (e.g. the content
generation orchestrator) — it is not required to be a ``shared_state.json``
document. Recognized keys: ``course_difficulty``, ``rule_family``.
"""

from __future__ import annotations

from typing import Any

from .rule_packs import DEFAULT_FAMILY, RULE_PACKS

_VALID_DIFFICULTIES = ("basic", "intermediate", "advanced")


def resolve_content_rule_pack_from_shared_state(
    context: dict[str, Any],
    *,
    purpose: str = "validate",
    difficulty_override: str | None = None,
) -> dict[str, Any] | None:
    """Resolve the active rule pack for a course context.

    Args:
        context: Plain dict carrying at least ``course_difficulty`` and,
            optionally, ``rule_family``.
        purpose: ``"write"`` or ``"validate"`` — recorded for logging only
            today (the placeholder rule packs don't vary by purpose).
        difficulty_override: Explicit difficulty, takes precedence over
            ``context["course_difficulty"]``.
    """
    _ = purpose
    family = str(context.get("rule_family") or DEFAULT_FAMILY).strip() or DEFAULT_FAMILY
    difficulty = str(
        difficulty_override or context.get("course_difficulty") or "intermediate"
    ).strip().lower()
    if difficulty not in _VALID_DIFFICULTIES:
        difficulty = "intermediate"

    family_packs = RULE_PACKS.get(family) or RULE_PACKS.get(DEFAULT_FAMILY)
    if not family_packs:
        return None
    return family_packs.get(difficulty) or family_packs.get("intermediate")


__all__ = ["resolve_content_rule_pack_from_shared_state"]
