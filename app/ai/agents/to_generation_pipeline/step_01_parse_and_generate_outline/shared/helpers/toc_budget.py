"""TOC word-budget helpers for LLM prompt assembly."""

from __future__ import annotations

from ..constants.pipeline_config import (
    TOC_WORD_BUDGET_MAX,
    TOC_WORD_BUDGET_MIN,
    TOC_WORD_BUDGET_PER_ENTRY,
)


class TocWordBudgetCalculator:
    """Computes how many words of TOC section body text to send to the LLM."""

    @staticmethod
    def for_entry_count(entry_count: int) -> int:
        return min(TOC_WORD_BUDGET_MAX, max(TOC_WORD_BUDGET_MIN, TOC_WORD_BUDGET_PER_ENTRY * entry_count))
