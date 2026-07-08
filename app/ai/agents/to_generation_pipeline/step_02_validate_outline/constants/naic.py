"""NAIC CE credit-hour formula constants."""
from __future__ import annotations

# Average reading pace used by the NAIC CE credit-hour formula.
DEFAULT_WPM: int = 180

# Difficulty multipliers from NAIC CE Standardized Terms-Definitions.
DIFFICULTY_MULTIPLIERS: dict[str, float] = {
    "basic": 1.00,
    "intermediate": 1.25,
    "advanced": 1.50,
}
