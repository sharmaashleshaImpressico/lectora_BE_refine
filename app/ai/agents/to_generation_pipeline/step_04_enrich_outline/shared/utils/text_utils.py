"""Shared text and pacing utilities for A1."""

from __future__ import annotations

import re


class TextUtils:
    """Word counting, pacing, and text normalization helpers."""

    @staticmethod
    def count_words(text: str) -> int:
        return len(re.findall(r"\w+", text))

    @staticmethod
    def words_to_minutes(word_count: int, wpm: int = 180) -> float:
        """Convert words to reading minutes. 180 wpm = 1 min per NAIC CE standard."""
        return round(word_count / wpm, 1)

    @staticmethod
    def wpm_from_rule_pack(rule_pack: dict, default: int = 180) -> int:
        """Derive reading speed (wpm) from rule pack: wpm = words_per_credit_hour / 50."""
        try:
            words_per_hour = (rule_pack.get("content_rules") or {}).get("words_per_credit_hour")
            if words_per_hour:
                return max(1, int(round(float(words_per_hour) / 50.0)))
        except (TypeError, ValueError):
            pass
        return default

    @staticmethod
    def to_snake(text: str) -> str:
        normalized = re.sub(r"[^\w\s]", "", text.lower())
        return re.sub(r"\s+", "_", normalized.strip())[:60]


def count_words(text: str) -> int:
    return TextUtils.count_words(text)


def words_to_minutes(word_count: int, wpm: int = 180) -> float:
    return TextUtils.words_to_minutes(word_count, wpm=wpm)


def wpm_from_rule_pack(rule_pack: dict, default: int = 180) -> int:
    return TextUtils.wpm_from_rule_pack(rule_pack, default=default)


def to_snake(text: str) -> str:
    return TextUtils.to_snake(text)
