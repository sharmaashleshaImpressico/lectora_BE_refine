"""Rule-pack resolution for content generation/validation.

``context`` is a plain dict assembled by the caller (e.g. the content
generation orchestrator) — it is not required to be a ``shared_state.json``
document. Recognized keys: ``course_difficulty``, ``rule_family``.

When ``rule_family`` resolves to one of the real course-type packs in
``rule_pack_config/packs/`` (insurance_ce / iarce / firm_element), that pack
is returned — layered over the per-difficulty base so difficulty-view keys
(``active_difficulty``, ``style_constraints``, …) stay available to existing
consumers. Unknown/absent families keep the previous placeholder behavior.
"""

from __future__ import annotations

from typing import Any

from .course_packs import resolve_course_rule_pack
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
            today (the rule packs don't vary by purpose).
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

    base_packs = RULE_PACKS.get(family) or RULE_PACKS.get(DEFAULT_FAMILY)
    base = (base_packs.get(difficulty) or base_packs.get("intermediate")) if base_packs else None

    # Real course-type pack from rule_pack_config/packs — the single source
    # of truth for content generation/validation rules.
    resolved = resolve_course_rule_pack(rule_family=family)
    if resolved is not None:
        family_key, course_pack = resolved
        merged: dict[str, Any] = {**(base or {}), **course_pack}
        merged["family_key"] = family_key
        merged["active_difficulty"] = difficulty
        return merged

    return base


__all__ = ["resolve_content_rule_pack_from_shared_state"]
