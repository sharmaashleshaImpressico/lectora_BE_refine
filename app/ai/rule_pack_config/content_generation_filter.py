"""Rule-pack resolution for content generation/validation.

``context`` is a plain dict assembled by the caller (e.g. the content
generation orchestrator) — it is not required to be a ``shared_state.json``
document. Recognized keys: ``course_difficulty``, ``rule_family``.

``rule_family`` is resolved against the real course-type packs in
``rule_pack_config/packs/`` (insurance_ce / iarce / firm_element); an
unknown or absent family falls back to ``DEFAULT_COURSE_RULE_FAMILY``.
"""

from __future__ import annotations

from typing import Any

from .course_packs import DEFAULT_COURSE_RULE_FAMILY, resolve_course_rule_pack

_VALID_DIFFICULTIES = ("basic", "intermediate", "advanced")

# The subset of rule-pack keys the S2 content validator actually consumes:
# report metadata (family/version + resolution annotations) and the rule
# groups read by the deterministic checks and the AI-validation prompt.
# Everything else (assessment_rules, kc_placement_rules, deduplication_rules,
# course_assembly_rules, ...) is never read during lesson validation.
_VALIDATION_RULE_PACK_KEYS = (
    "family",
    "version",
    "family_key",
    "active_difficulty",
    "style_constraints",
    "compliance_elements",
    "content_rules",
    "error_tolerance",
)


def filter_rule_pack_for_validation(rule_pack: dict[str, Any]) -> dict[str, Any]:
    """Return the validation view of a resolved rule pack.

    Keeps only the keys the content validator (deterministic checks + AI
    validation prompt) consumes — see ``_VALIDATION_RULE_PACK_KEYS``. The
    input pack is not mutated.
    """
    return {key: rule_pack[key] for key in _VALIDATION_RULE_PACK_KEYS if key in rule_pack}


def apply_rule_pack_overrides(
    pack: dict[str, Any], overrides: dict[str, Any] | None
) -> dict[str, Any]:
    """Deep-apply user rule edits onto ``pack`` (mutates and returns it).

    ``overrides`` maps a dot-joined path (the frontend rules editor's
    ``rule_name``, e.g. ``"content_rules.chapter_rules.tone"``) to the
    user-edited value. User edits are the source of truth: they always
    replace the pack default at that path. Unknown intermediate keys are
    created; a path that conflicts with a non-dict value is skipped.
    """
    for path, value in (overrides or {}).items():
        keys = [key for key in path.split(".") if key]
        if not keys:
            continue
        node: Any = pack
        for key in keys[:-1]:
            if isinstance(node, list) and key.isdigit() and int(key) < len(node):
                node = node[int(key)]
                continue
            if not isinstance(node, dict):
                node = None
                break
            node = node.setdefault(key, {})
        leaf = keys[-1]
        if isinstance(node, dict):
            node[leaf] = value
        elif isinstance(node, list) and leaf.isdigit() and int(leaf) < len(node):
            node[int(leaf)] = value
    return pack


def resolve_content_rule_pack_from_shared_state(
    context: dict[str, Any],
    *,
    purpose: str = "validate",
    difficulty_override: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve the active rule pack for a course context.

    Args:
        context: Plain dict carrying at least ``course_difficulty`` and,
            optionally, ``rule_family``.
        purpose: ``"write"`` or ``"validate"`` — recorded for logging only
            today (the rule packs don't vary by purpose).
        difficulty_override: Explicit difficulty, takes precedence over
            ``context["course_difficulty"]``.
        overrides: User rule edits (dot-path → value) persisted from the
            frontend rules editor. Applied on top of the pack defaults —
            user-edited values are the source of truth.
    """
    _ = purpose
    family = str(context.get("rule_family") or "").strip()
    difficulty = str(
        difficulty_override or context.get("course_difficulty") or "intermediate"
    ).strip().lower()
    if difficulty not in _VALID_DIFFICULTIES:
        difficulty = "intermediate"

    resolved = resolve_course_rule_pack(rule_family=family) or resolve_course_rule_pack(
        rule_family=DEFAULT_COURSE_RULE_FAMILY
    )
    if resolved is None:  # defensive: default family always resolves
        return None
    family_key, pack = resolved
    pack["family_key"] = family_key
    pack["active_difficulty"] = difficulty

    # User rule edits win over pack defaults. Applied before the
    # style_constraints bridge below so an edited chapter voice/tone also
    # drives the deterministic voice check.
    apply_rule_pack_overrides(pack, overrides)

    # Deterministic validation (check_voice_pronouns) reads
    # ``style_constraints.voice`` — surface the pack's chapter-level
    # voice/tone there so the check keeps working against the real packs.
    if "style_constraints" not in pack:
        chapter_rules = (pack.get("content_rules") or {}).get("chapter_rules") or {}
        style = {
            key: chapter_rules[key]
            for key in ("voice", "tone")
            if chapter_rules.get(key)
        }
        if style:
            pack["style_constraints"] = style

    return pack


__all__ = [
    "apply_rule_pack_overrides",
    "filter_rule_pack_for_validation",
    "resolve_content_rule_pack_from_shared_state",
]
