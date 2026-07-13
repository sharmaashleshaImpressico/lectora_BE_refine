"""TO A0→S1 user-input propagation: shared state, precheck, pruning, refine revalidation."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.phases.finalization_phase import (
    build_course_config_for_shared_state,
)
from app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline.shared.models.to_wizard_prompt_context import (
    SourceAnalysisPromptContext,
    ToWizardPromptContext,
)
from app.ai.agents.to_generation_pipeline.step_02_validate_outline.to_validation_check.ai_check.models import (
    ValidationResult,
)
from app.ai.agents.to_generation_pipeline.step_02_validate_outline.to_validation_check.ai_check.runner import (
    AIOutlineValidator,
)
from app.ai.agents.to_generation_pipeline.step_02_validate_outline.to_validation_check.ai_check.user_requirements import (
    collect_s1_user_requirements,
    has_s1_user_requirements,
)
from app.ai.rule_pack_config.prune import prune_empty_payload_values
from app.orchestrators.topic_outline.models import TimedOutlineGenerationInput
from app.orchestrators.topic_outline.orchestrator import _build_wizard_prompt_context


REQUIRED_TOPICS = [f"Topic {i}" for i in range(1, 15)]


def _full_generation_input() -> TimedOutlineGenerationInput:
    return TimedOutlineGenerationInput(
        blob_paths=["docs/sample.docx"],
        course_title="Annuity Suitability Essentials",
        course_description="A practical course on annuity suitability for agents.",
        audience="Licensed insurance agents",
        learning_objectives=[
            "Explain suitability standards",
            "Apply disclosure requirements",
        ],
        required_topics=list(REQUIRED_TOPICS),
        duration_hours=2.0,
        calculated_word_count=16000,
        difficulty="intermediate",
        course_topic="Annuities",
        course_type_hint="Insurance CE",
        rule_family="insurance_ce",
        experience_level="some",
        learner_outcomes="Confidently recommend suitable annuity products",
        tone="professional",
        depth="balanced",
        emphasis="suitability and disclosures",
        avoid="product pitching",
        include_case_studies=True,
        include_examples=False,
        include_knowledge_checks=True,
        preferred_chapters=6,
        lesson_style="short",
    )


def _wizard_with_sources() -> ToWizardPromptContext:
    base = _build_wizard_prompt_context(_full_generation_input())
    return ToWizardPromptContext(
        **{
            **base.__dict__,
            "source_analyses": (
                SourceAnalysisPromptContext(
                    source_name="annuity_sg.docx",
                    extract_hint="Focus on suitability rules",
                    main_topics=("suitability", "disclosures"),
                    recommended_course_use="primary curriculum",
                    recommended_depth="detailed",
                    supports_learning_objectives=("Explain suitability standards",),
                    ignore_or_reduce=("marketing fluff",),
                ),
            ),
        }
    )


class TestBuildCourseConfig:
    def test_full_metadata_propagates_required_topics_and_flags(self):
        meta = _full_generation_input()
        wizard = _build_wizard_prompt_context(meta)
        config = build_course_config_for_shared_state(
            difficulty_level=meta.difficulty,
            duration_hours=meta.duration_hours,
            calculated_word_count=meta.calculated_word_count,
            preferred_chapters=meta.preferred_chapters,
            course_type_hint=meta.course_type_hint,
            audience=meta.audience,
            course_description=meta.course_description,
            course_topic=meta.course_topic,
            learning_objectives=meta.learning_objectives,
            wizard=wizard,
        )

        assert config["required_topics"] == REQUIRED_TOPICS
        assert len(config["required_topics"]) == 14
        assert config["course_description"] == meta.course_description
        assert config["audience_notes"] == meta.audience
        assert config["course_type_hint"] == meta.course_type_hint
        assert config["difficulty_level"] == "intermediate"
        assert config["experience_level"] == "some"
        assert config["duration_hours"] == 2.0
        assert config["calculated_word_count"] == 16000
        assert config["preferred_chapters"] == 6
        assert config["lesson_style"] == "short"
        assert config["depth"] == "balanced"
        assert config["tone"] == "professional"
        assert config["emphasis"] == "suitability and disclosures"
        assert config["avoid"] == "product pitching"
        assert config["learner_outcomes"] == meta.learner_outcomes
        assert config["include_case_studies"] is True
        assert config["include_examples"] is False
        assert config["learning_objectives"] == meta.learning_objectives
        assert config["course_topic"] == "Annuities"

    def test_empty_optional_values_are_pruned_not_invented(self):
        config = build_course_config_for_shared_state(
            difficulty_level="basic",
            duration_hours=1.0,
            calculated_word_count=9000,
            learning_objectives=["LO1"],
            wizard=ToWizardPromptContext(required_topics=("Only Topic",)),
        )
        assert "tone" not in config
        assert "depth" not in config
        assert "include_case_studies" not in config
        assert config["required_topics"] == ["Only Topic"]


class TestS1UserRequirements:
    def test_collect_reads_persisted_course_config_and_source_hints(self):
        meta = _full_generation_input()
        wizard = _wizard_with_sources()
        course_config = build_course_config_for_shared_state(
            difficulty_level=meta.difficulty,
            duration_hours=meta.duration_hours,
            calculated_word_count=meta.calculated_word_count,
            preferred_chapters=meta.preferred_chapters,
            course_type_hint=meta.course_type_hint,
            audience=meta.audience,
            course_description=meta.course_description,
            course_topic=meta.course_topic,
            learning_objectives=meta.learning_objectives,
            wizard=wizard,
        )
        shared_state: dict[str, Any] = {
            "course_config": course_config,
            "course_title_override": meta.course_title,
            "course_difficulty": meta.difficulty,
            "course_audience": meta.audience,
            "special_instructions": meta.avoid,
            "source_file_specs": [
                {
                    "filename": "annuity_sg.docx",
                    "extract_hint": "Focus on suitability rules",
                    "main_topics": ["suitability", "disclosures"],
                    "recommended_course_use": "primary curriculum",
                    "recommended_depth": "detailed",
                    "supports_learning_objectives": ["Explain suitability standards"],
                    "ignore_or_reduce": ["marketing fluff"],
                }
            ],
            "extracted_inputs": {"title": meta.course_title, "learning_objectives": []},
            "request_spec": {
                "course_metadata": {
                    "title": meta.course_title,
                    "audience": meta.audience,
                    "course_type": meta.course_type_hint,
                    "topic": meta.course_topic,
                }
            },
        }

        requirements = collect_s1_user_requirements(shared_state)

        assert requirements["required_topics"] == REQUIRED_TOPICS
        assert requirements["course_title_override"] == meta.course_title
        assert requirements["course_description"] == meta.course_description
        assert requirements["audience"] == meta.audience
        assert requirements["difficulty_level"] == "intermediate"
        assert requirements["experience_level"] == "some"
        assert requirements["duration_hours"] == 2.0
        assert requirements["calculated_word_count"] == 16000
        assert requirements["preferred_chapters"] == 6
        assert requirements["lesson_style"] == "short"
        assert requirements["tone"] == "professional"
        assert requirements["depth"] == "balanced"
        assert requirements["emphasis"] == "suitability and disclosures"
        assert requirements["avoid"] == "product pitching"
        assert requirements["learner_outcomes"] == meta.learner_outcomes
        assert requirements["include_case_studies"] is True
        assert requirements["include_examples"] is False
        assert requirements["learning_objectives"] == meta.learning_objectives
        assert len(requirements["source_hints"]) == 1
        assert requirements["source_hints"][0]["extract_hint"] == "Focus on suitability rules"
        assert has_s1_user_requirements(requirements) is True

    def test_missing_course_config_yields_empty_required_topics(self):
        """Regression: without persisted course_config, S1 saw total_requested=0."""
        requirements = collect_s1_user_requirements(
            {
                "extracted_inputs": {"title": "X", "learning_objectives": ["LO"]},
                "request_spec": {"course_metadata": {"title": "X"}},
            }
        )
        assert requirements.get("required_topics") in (None, [])


class TestEmptyValuePruning:
    def test_preserves_false_zero_and_drops_empty_containers(self):
        pruned = prune_empty_payload_values(
            {
                "include_examples": False,
                "include_case_studies": True,
                "preferred_chapters": 0,
                "total_requested": 0,
                "empty_list": [],
                "empty_str": "",
                "none_val": None,
                "nested": {"keep": False, "drop": ""},
            }
        )
        assert pruned["include_examples"] is False
        assert pruned["include_case_studies"] is True
        assert pruned["preferred_chapters"] == 0
        assert pruned["total_requested"] == 0
        assert "empty_list" not in pruned
        assert "empty_str" not in pruned
        assert "none_val" not in pruned
        assert pruned["nested"] == {"keep": False}


class TestRequiredTopicsPrecheck:
    def _run_validator(
        self,
        *,
        required_topics: list[str],
        sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        shared_state = {
            "course_config": {"required_topics": required_topics} if required_topics else {},
            "course_title_override": "Course",
            "extracted_inputs": {"title": "Course"},
            "llm_to_outline_classification": {
                "sections": sections
                or [
                    {
                        "title": "Covered Topic",
                        "content": "covers everything",
                        "subtopics": ["Topic 1"],
                        "word_count": 100,
                    }
                ]
            },
        }
        captured: dict[str, Any] = {}

        def _fake_run(self, *, payload, priority_rule):  # noqa: ANN001
            captured["payload"] = payload
            return ValidationResult(
                status="PASS",
                confidence=1.0,
                coverage_score=10.0,
                sequence_score=10.0,
                relevance_score=10.0,
                completeness_score=10.0,
                issues=[],
                missing_topics=[],
                retry_required=False,
            )

        with (
            patch(
                "app.ai.agents.to_generation_pipeline.step_02_validate_outline."
                "to_validation_check.ai_check.runner.SemanticValidator.run",
                _fake_run,
            ),
            patch(
                "app.ai.agents.to_generation_pipeline.step_02_validate_outline."
                "to_validation_check.ai_check.runner.write_s1_semantic_trace",
            ),
            patch(
                "app.ai.agents.to_generation_pipeline.step_02_validate_outline."
                "to_validation_check.ai_check.runner._check_required_topics_deterministic",
                return_value=[],
            ),
        ):
            AIOutlineValidator.run(
                kernel=MagicMock(),
                shared_state=shared_state,
                course_spec={},
                to_rule_pack={"id": "to", "name": "TO", "version": "1"},
            )
        return captured["payload"]

    def test_total_requested_matches_required_topics(self):
        payload = self._run_validator(required_topics=REQUIRED_TOPICS)
        precheck = payload["required_topics_precheck"]
        assert precheck["total_requested"] == 14
        assert precheck["instruction"] == "All required topics detected by pre-check."

    def test_empty_required_topics_does_not_claim_all_detected(self):
        payload = self._run_validator(required_topics=[])
        precheck = payload["required_topics_precheck"]
        assert precheck["total_requested"] == 0
        assert "No required topics were supplied" in precheck["instruction"]
        assert "All required topics detected" not in precheck["instruction"]


class TestRefinementRevalidation:
    def test_course_config_survives_outline_replacement(self):
        """After refine, only the outline is overwritten — metadata must remain."""
        meta = _full_generation_input()
        course_config = build_course_config_for_shared_state(
            difficulty_level=meta.difficulty,
            duration_hours=meta.duration_hours,
            calculated_word_count=meta.calculated_word_count,
            preferred_chapters=meta.preferred_chapters,
            course_type_hint=meta.course_type_hint,
            audience=meta.audience,
            course_description=meta.course_description,
            course_topic=meta.course_topic,
            learning_objectives=meta.learning_objectives,
            wizard=_build_wizard_prompt_context(meta),
        )
        shared_state: dict[str, Any] = {
            "course_config": course_config,
            "course_title_override": meta.course_title,
            "llm_to_outline_classification": {"sections": [{"title": "Old"}]},
        }

        # Mimic TopicOutlineOrchestrator repair-loop mutation.
        shared_state["llm_to_outline_classification"] = {
            "sections": [{"title": "Refined Section", "subtopics": ["Topic 1"]}]
        }

        requirements = collect_s1_user_requirements(shared_state)
        assert requirements["required_topics"] == REQUIRED_TOPICS
        assert requirements["course_title_override"] == meta.course_title
        assert requirements["include_examples"] is False
        assert len(requirements["required_topics"]) == 14


@pytest.mark.parametrize(
    "field,expected",
    [
        ("course_title", "Annuity Suitability Essentials"),
        ("course_description", "A practical course on annuity suitability for agents."),
        ("audience", "Licensed insurance agents"),
        ("difficulty", "intermediate"),
        ("experience_level", "some"),
        ("preferred_chapters", 6),
        ("lesson_style", "short"),
        ("include_examples", False),
    ],
)
def test_timed_outline_input_fields_round_trip_via_wizard(field: str, expected: Any):
    meta = _full_generation_input()
    wizard = _build_wizard_prompt_context(meta)
    if field == "course_title":
        assert meta.course_title == expected
    elif field == "course_description":
        assert meta.course_description == expected
    elif field == "audience":
        assert wizard.audience_notes == expected
    elif field == "difficulty":
        assert meta.difficulty == expected
    elif field == "experience_level":
        assert wizard.experience_level == expected
    elif field == "preferred_chapters":
        assert meta.preferred_chapters == expected
    elif field == "lesson_style":
        assert wizard.lesson_style == expected
    elif field == "include_examples":
        assert wizard.include_examples is expected
