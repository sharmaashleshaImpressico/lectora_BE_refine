"""Resolve which rule pack drives validation for a given S1 phase."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lectora_backend.pipeline.agent.to_generation_pipeline.to_rule_pack import (
    TO_RULE_PACK_ID,
    TO_RULE_PACK_VERSION,
    get_to_rule_pack,
)

from lectora_backend.pipeline.models import S1ValidationReport

S1ValidationPhase = Literal["full", "to_only", "a1_only"]


@dataclass
class RuleSourceContext:
    use_to_rule_pack: bool
    to_rule_pack: dict | None
    course_rule_pack: dict | None
    rule_pack_label: str
    early_exit_report: S1ValidationReport | None = None


class RuleSourceResolver:
    """S1 validation always uses the TO timed-outline rule pack."""

    @classmethod
    def resolve(
        cls,
        *,
        phase: S1ValidationPhase,
        shared_state: dict,
        run_id: str,
    ) -> RuleSourceContext:
        _ = (phase, shared_state, run_id)
        to_rule_pack = get_to_rule_pack()
        return RuleSourceContext(
            use_to_rule_pack=True,
            to_rule_pack=to_rule_pack,
            course_rule_pack=None,
            rule_pack_label=f"{TO_RULE_PACK_ID} {TO_RULE_PACK_VERSION}",
            early_exit_report=None,
        )
