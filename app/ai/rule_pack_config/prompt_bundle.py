"""Filtered rule-pack views injected into LLM prompts as ``full_rule_pack``.

Placeholder: returns the rule pack itself (already a small, prompt-safe
dict). Swap for a real filtered/pruned view once the real rule packs (with
larger internal-only sections) exist.
"""

from __future__ import annotations

from typing import Any


def bundle_rule_pack_for_prompt(rule_pack: dict[str, Any]) -> dict[str, Any]:
    """Return the content-writing view of a rule pack for prompt injection."""
    return dict(rule_pack or {})


def bundle_rule_pack_for_validation_prompt(rule_pack: dict[str, Any]) -> dict[str, Any]:
    """Return the validation view of a rule pack for prompt injection."""
    return dict(rule_pack or {})


__all__ = ["bundle_rule_pack_for_prompt", "bundle_rule_pack_for_validation_prompt"]
