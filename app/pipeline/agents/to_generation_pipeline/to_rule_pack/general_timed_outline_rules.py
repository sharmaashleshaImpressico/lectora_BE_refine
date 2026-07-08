"""General timed-outline validation rules for the TO generation pipeline."""

from __future__ import annotations

from typing import Any

GENERAL_TIMED_OUTLINE_RULES: dict[str, Any] = {
    "required_fields": {
        "fields": [
            "title",
            "content",
            "subtopics",
            "word_count",
            "minutes",
            "credit_hour",
        ],
        "severity": "blocking",
        "action": "regenerate_affected_section",
    },
    "structure_rules": {
        "overall_course_must_match_requested_duration": {
            "enabled": True,
            "tolerance_percent": 10,
            "severity": "warning",
            "action": "do_not_regenerate",
        },
        "overall_course_must_cover_all_learning_objectives": {
            "enabled": True,
            "severity": "blocking",
            "action": "regenerate_outline",
        },
        "overall_course_must_preserve_course_intent": {
            "enabled": True,
            "severity": "blocking",
            "action": "regenerate_outline",
        },
        "course_must_have_intro_or_opening_section": {
            "enabled": True,
            "severity": "warning",
            "action": "regenerate_affected_section",
        },
        "course_must_have_summary_or_conclusion_section": {
            "enabled": True,
            "severity": "warning",
            "action": "regenerate_affected_section",
        },
    },
    "quality_rules": {
        "sections_must_be_logically_ordered": {
            "enabled": True,
            "severity": "warning",
            "action": "regenerate_outline",
        },
        "sections_must_not_overlap": {
            "enabled": True,
            "severity": "blocking",
            "action": "regenerate_affected_section",
        },
        "sections_must_not_be_duplicates": {
            "enabled": True,
            "severity": "blocking",
            "action": "regenerate_affected_section",
        },
        "section_titles_must_be_clear": {
            "enabled": True,
            "severity": "warning",
            "action": "regenerate_affected_section",
        },
        "subtopics_must_be_specific": {
            "enabled": True,
            "severity": "warning",
            "action": "regenerate_affected_section",
        },
        "topics_must_be_source_supported": {
            "enabled": True,
            "severity": "blocking",
            "action": "regenerate_affected_section",
        },
    },
}
