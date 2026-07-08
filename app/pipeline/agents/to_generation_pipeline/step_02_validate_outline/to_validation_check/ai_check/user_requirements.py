"""Build a normalized user-requirements payload for S1 semantic validation."""

from __future__ import annotations

from typing import Any

from lectora_backend.pipeline.rule_pack_config.prune import prune_empty_payload_values
from lectora_backend.pipeline.shared_utils.learning_objectives import (
    normalize_learning_objectives,
)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _resolve_topic(shared_state: dict[str, Any], course_meta: dict[str, Any], course_config: dict[str, Any]) -> str:
    llm = shared_state.get("llm_classification") or {}
    rule_class = (shared_state.get("request_spec") or {}
                  ).get("rule_classification") or {}
    return _first_non_empty(
        course_meta.get("topic"),
        llm.get("topic"),
        course_config.get("course_topic"),
        course_config.get("topic"),
        shared_state.get("course_title_override"),
        course_meta.get("title"),
        shared_state.get("extracted_inputs", {}).get("title"),
        course_config.get("course_type_hint"),
        rule_class.get("family"),
    )


def _resolve_category(
    shared_state: dict[str, Any], course_meta: dict[str, Any], course_config: dict[str, Any]
) -> str:
    llm = shared_state.get("llm_classification") or {}
    rule_class = (shared_state.get("request_spec") or {}
                  ).get("rule_classification") or {}
    return _first_non_empty(
        course_meta.get("category"),
        llm.get("category"),
        course_config.get("category"),
        course_meta.get("course_type"),
        course_config.get("course_type_hint"),
        rule_class.get("family"),
    )


def _resolve_difficulty_level(shared_state: dict[str, Any], course_config: dict[str, Any]) -> str:
    return _first_non_empty(
        course_config.get("difficulty_level"),
        shared_state.get("course_difficulty"),
        (shared_state.get("request_spec") or {})
        .get("course_metadata", {})
        .get("difficulty_level"),
    )


def _resolve_learning_objectives(shared_state: dict[str, Any], course_config: dict[str, Any]) -> list[str]:
    """Prefer wizard/FE objectives, then document-extracted objectives — deduped once."""
    wizard_los = normalize_learning_objectives(
        course_config.get("learning_objectives"))
    if wizard_los:
        return wizard_los
    return normalize_learning_objectives(
        (shared_state.get("extracted_inputs") or {}).get("learning_objectives")
    )


def collect_s1_user_requirements(shared_state: dict[str, Any]) -> dict[str, Any]:
    """Normalize FE/A0 context for the S1 AI validator prompt."""
    request_spec = shared_state.get("request_spec") or {}
    course_meta = request_spec.get("course_metadata") or {}
    course_config = shared_state.get("course_config") or {}

    required_topics = (
        course_config.get("required_topics")
        or request_spec.get("required_topics")
        or shared_state.get("required_topics")
        or []
    )

    source_hints = []
    for spec in shared_state.get("source_file_specs") or []:
        hint = (spec.get("extract_hint") or "").strip()
        if hint:
            source_hints.append(
                {
                    "source_name": spec.get("filename") or spec.get("blob_path") or "source",
                    "extract_hint": hint,
                    "main_topics": spec.get("main_topics") or [],
                    "recommended_course_use": spec.get("recommended_course_use") or "",
                    "recommended_depth": spec.get("recommended_depth") or "",
                    "supports_learning_objectives": spec.get("supports_learning_objectives") or [],
                    "ignore_or_reduce": spec.get("ignore_or_reduce") or [],
                }
            )

    return prune_empty_payload_values(
        {
            "audience": _first_non_empty(
                course_meta.get("audience"),
                shared_state.get("course_audience"),
                course_config.get("audience_notes"),
            ),
            "course_type": _first_non_empty(
                course_meta.get("course_type"),
                course_config.get("course_type_hint"),
                (shared_state.get("llm_classification") or {}).get("course_type"),
            ),
            "topic": _resolve_topic(shared_state, course_meta, course_config),
            "category": _resolve_category(shared_state, course_meta, course_config),
            "difficulty_level": _resolve_difficulty_level(shared_state, course_config),
            "course_title_override": shared_state.get("course_title_override") or "",
            "learning_objectives": _resolve_learning_objectives(shared_state, course_config),
            "required_topics": required_topics,
            "special_instructions": shared_state.get("special_instructions") or "",
            "emphasis": course_config.get("emphasis") or "",
            "avoid": course_config.get("avoid") or "",
            "tone": course_config.get("tone") or "",
            "depth": course_config.get("depth") or "",
            "preferred_chapters": course_config.get("preferred_chapters"),
            "lesson_style": course_config.get("lesson_style") or "",
            "experience_level": course_config.get("experience_level") or "",
            "learner_outcomes": course_config.get("learner_outcomes") or "",
            "audience_notes": course_config.get("audience_notes") or "",
            "course_type_hint": course_config.get("course_type_hint") or "",
            "duration_hours": course_config.get("duration_hours"),
            "calculated_word_count": course_config.get("calculated_word_count"),
            "include_case_studies": course_config.get("include_case_studies")
            if course_config.get("include_case_studies") is not None
            else course_config.get("include_scenarios"),
            "include_examples": course_config.get("include_examples"),
            "source_hints": source_hints,
        }
    )


def has_s1_user_requirements(requirements: dict[str, Any]) -> bool:
    return any(
        [
            bool(requirements.get("required_topics")),
            bool(requirements.get("special_instructions")),
            bool(requirements.get("emphasis")),
            bool(requirements.get("avoid")),
            bool(requirements.get("source_hints")),
            bool(requirements.get("learning_objectives")),
            bool(requirements.get("tone")),
            bool(requirements.get("depth")),
            bool(requirements.get("preferred_chapters")),
            bool(requirements.get("lesson_style")),
            bool(requirements.get("experience_level")),
            bool(requirements.get("learner_outcomes")),
            bool(requirements.get("audience_notes")),
            bool(requirements.get("course_type_hint")),
            bool(requirements.get("duration_hours")),
            bool(requirements.get("calculated_word_count")),
            requirements.get("include_case_studies") is not None,
            requirements.get("include_examples") is not None,
        ]
    )
