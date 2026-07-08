"""Shared difficulty-level and NAIC pacing constants for the parse-and-generate pipeline."""

DEFAULT_TO_DURATION_HOURS: int = 3
DEFAULT_DIFFICULTY = "intermediate"

WORDS_PER_MINUTE = 180
MINUTES_PER_CREDIT = 50
WORDS_PER_CE_HOUR = WORDS_PER_MINUTE * MINUTES_PER_CREDIT

DIFFICULTY_MULTIPLIERS: dict[str, float] = {
    "basic": 1.00,
    "intermediate": 1.25,
    "advanced": 1.50,
}


def get_difficulty_multiplier(difficulty: str) -> float:
    return DIFFICULTY_MULTIPLIERS.get((difficulty or DEFAULT_DIFFICULTY).lower(), 1.25)


def compute_calculated_word_count(duration_hours: int | float, difficulty: str) -> int:
    """Return target word count from duration + difficulty.

    Formula: (duration_hours × 9,000) × multiplier
    Mirrors the difficulty-aware pacing used by the active Insurance CE overlays.
    """
    multiplier = get_difficulty_multiplier(difficulty)
    return max(1, round((duration_hours * WORDS_PER_CE_HOUR) * multiplier))
