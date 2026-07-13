from __future__ import annotations

from ...constants.naic import DEFAULT_WPM as _DEFAULT_WPM, DIFFICULTY_MULTIPLIERS as _DIFFICULTY_MULTIPLIERS


class CreditHourCalculator:
    """Pure utility class for NAIC CE credit-hour computation.

    All methods are stateless; instantiation is not required.
    """

    @staticmethod
    def total_words_from_sections(sections: list) -> int:
        return sum(s.get("word_count", 0) for s in sections)

    @staticmethod
    def kc_count_from_sections(sections: list) -> int:
        return sum(
            1
            for section in sections
            if section.get("has_knowledge_check")
            or "knowledge_check" in (section.get("interactive_elements") or [])
        )

    @staticmethod
    def round_credit_hours(hours: float) -> float:
        """Round credit hours: fractional part >= 0.50 rounds up, <= 0.49 rounds down."""
        whole = int(hours)
        frac = hours - whole
        return float(whole + 1) if frac >= 0.50 else float(whole)

    @staticmethod
    def difficulty_multiplier(shared_state: dict) -> float:
        """Return the difficulty multiplier from course_metadata; defaults to basic (1.00)."""
        level = (
            shared_state.get("request_spec", {})
            .get("course_metadata", {})
            .get("difficulty_level", "basic")
            or "basic"
        )
        return _DIFFICULTY_MULTIPLIERS.get(level.lower(), 1.00)

    @staticmethod
    def credit_hours_derived(total_words: int, difficulty_multiplier_value: float = 1.00) -> float:
        """NAIC formula: words ÷ 180 = minutes; minutes ÷ 50 = base hours; × difficulty."""
        base_hours = total_words / _DEFAULT_WPM / 50
        return CreditHourCalculator.round_credit_hours(base_hours * difficulty_multiplier_value)

    @staticmethod
    def credit_hours_from_rule_pack(
        total_words: int,
        rule_pack: dict,
        difficulty_multiplier_value: float = 1.00,
    ) -> float | None:
        """Preferred credit-hour derivation using rule-pack pacing (words_per_credit_hour),
        falling back to the NAIC WPM formula when not configured.
        """
        pacing = (
            rule_pack.get("content_rules", {}).get("words_per_credit_hour")
            if isinstance(rule_pack, dict)
            else None
        )
        if pacing:
            try:
                base_hours = float(total_words) / float(pacing)
                return CreditHourCalculator.round_credit_hours(base_hours * difficulty_multiplier_value)
            except (TypeError, ValueError, ZeroDivisionError):
                return None
        return (
            CreditHourCalculator.credit_hours_derived(total_words, difficulty_multiplier_value)
            if total_words > 0
            else None
        )


# ---------------------------------------------------------------------------
# Backward-compatible module-level wrappers
# ---------------------------------------------------------------------------

def total_words_from_sections(sections: list) -> int:
    return CreditHourCalculator.total_words_from_sections(sections)


def kc_count_from_sections(sections: list) -> int:
    return CreditHourCalculator.kc_count_from_sections(sections)


def round_credit_hours(hours: float) -> float:
    return CreditHourCalculator.round_credit_hours(hours)


def difficulty_multiplier(shared_state: dict) -> float:
    return CreditHourCalculator.difficulty_multiplier(shared_state)


def credit_hours_derived(total_words: int, difficulty_multiplier_value: float = 1.00) -> float:
    return CreditHourCalculator.credit_hours_derived(total_words, difficulty_multiplier_value)


def credit_hours_from_rule_pack(
    total_words: int,
    rule_pack: dict,
    difficulty_multiplier_value: float = 1.00,
) -> float | None:
    return CreditHourCalculator.credit_hours_from_rule_pack(
        total_words, rule_pack, difficulty_multiplier_value
    )
