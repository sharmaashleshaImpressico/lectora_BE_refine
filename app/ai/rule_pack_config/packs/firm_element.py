"""
Firm Element (FINRA Rule 1240 — Firm Element Continuing Education) rule pack.
"""

from __future__ import annotations

PACK: dict = {
    "id": "rp-firm-element-v2.4",
    "family": "Firm Element",
    "version": "2.4",
    "full_name": "Firm Element Continuing Education",
    "governed_by": "FINRA Rule 1240",
    "audience": (
        "Broker-Dealer reps (RRs)/IARs, investment professionals, Supervisors/Principals, "
        "Branch Managers, Desk Supervisors, Compliance/Risk, Operations & back office, C-level, "
        "Sales support & client-facing non-registered staff"
    ),
    "exam_file_format_samples": "DOCX",
    "sample_courses_available": [
        "932 Senior Safe Act",
        "959 Due Diligence New Complex and Private Offerings",
    ],
    "new_course_requested": None,
    "unique_artifacts": [],
    "assessment_rules": {
        "final_exam_min_questions": 15,
        "answer_options_count": 4,
        "allow_true_false": False,
        "allow_all_of_the_above": False,
        "forbidden_question_types": [
            "true_false",
            "all_of_the_above",
            "none_of_the_above",
            "except_questions",
            "roman_numeral_questions",
        ],
        # Exam feedback (RESPONSE) required: for every answer choice correct and incorrect
        "require_rationale": True,
        "require_distractor_rationales": True,
        "objective_coverage_required": True,
        # Cross-reference required: No
        "require_exam_cross_reference": False,
    },
    "compliance_elements": {
        "regulatory_mode": "strict_real_regulators",
        "require_non_advisory_language": False,
        "forbidden_phrases": [],
        "disclosure_handling": {
            "allow_generic_regulatory_reference": False,
            "no_hallucinated_citations": True,
        },
    },
    "course_assembly_rules": {
        "require_intro_section": True,
        "require_learning_objectives_section": True,
        "learning_objectives_position": "before_first_chapter",
        "require_expanded_summary_section": False,
        "require_course_conclusion_section": True,
    },
    "content_rules": {
        "require_source_fidelity": True,
        "must_map_to_learning_objectives": True,
        "require_learning_objectives_in_first_section": None,
        "require_expanded_summary_section": None,
        "require_intro_section": True,
        "require_learning_objectives": True,
        "learning_objectives_range": [5, 10],
        "require_examples_per_section": [1, 2],
        "require_callouts_per_section": [1, 2],
        "allow_case_studies": True,
        "case_study_policy": {
            "optional": True,
            "allow_fictionalized_narrative_or_dialogue": True,
            "knowledge_checks_advance_narrative": True,
        },
        "allow_regulatory_updates_section": True,
        "require_timed_outline": False,
        "require_ethics_category_application": None,
        "words_per_credit_hour": 6000,
        "course_word_count_bands": {"short": 3000, "typical": 6000, "long": 28000},
        "no_duplicate_concepts_across_sections": True,
        "no_unverified_statistics": True,
        "no_opinion_based_statements": True,
        "self_contained_subtopics": True,
        "maintain_section_boundary_integrity": True,
        "chapter_rules": {
            "allow_subtopic_word_count_flexibility": True,
            "do_not_force_equal_subtopic_lengths": True,
            "word_count_tolerance_percent": 10,
            "reading_level": "Grade 9 maximum; plain language; translate complex ideas into clear explanations",
            "voice": "third_person_role_title",
            "tone": "formal_direct_clean",
            "paragraph_length": "short",
            "max_sentences_per_paragraph": 5,
            "avoid_complex_jargon": True,
            "explain_terms_on_first_use": True,
            "bold_first_key_term": True,
            "audience_focus": "investment_professionals",
            "regulatory_mode": "strict_real_regulators",
            "required_behaviors": [
                "refer to learners in third person using role titles (e.g. registered representative)",
                "use 'this course' for organizational reference; do not use 'we'",
                "bold the first mention of a regulatory body (full name + acronym)",
                "bold the first mention of a rule or regulation",
                "cite only primary regulatory sources (SEC, FINRA, MSRB, NASAA, CFTC, NFA, FinCEN, FATF, CFPB, FRB, OCC, IRS)",
                "do not cite law blogs or consulting/marketing websites",
                "use neutral explanations",
                "avoid financial advice tone",
                "frame statements as informational",
                "avoid unsupported claims",
                "ground teaching points in the provided source excerpt — paraphrase faithfully; do not invent unsupported facts",
            ],
        },
    },
    "kc_placement_rules": {
        # KC placement rule: content-driven, not positionally predictable
        "placement": "content_driven_not_positionally_predictable",
        "min_kc_per_lesson": 2,
        "max_kc_per_lesson": 5,
        # KC answer options: 4 only
        "min_answer_options": 4,
        "max_answer_options": 4,
        "cadence": {
            "screens_min": 3,
            "screens_max": 6,
            "approximate_word_pages_min": 1,
            "approximate_word_pages_max": 3,
        },
        "kc_triggers": [
            "important_new_concepts",
            "complex_or_difficult_explanations",
            "section_or_subsection_completion",
            "scenario_or_case_study_interactions",
        ],
        "embedded_kc_format": {
            "typical_answer_option_count": 4,
            "components": [
                "stem",
                "answer_options",
                "correct_answer",
                "explanation",
            ],
            "allow_scenario_or_case_study": True,
            "prefer_scenario_or_case_study": True,
        },
        "forbidden_placements": [
            "mid_paragraph",
            "inside_regulatory_block",
        ],
        # KC structure: stem + options + correct answer with explanation for all options
        "require_explanation": True,
        "require_explanation_for_all_options": True,
        "distractor_quality": "plausible",
        "prefer_scenario_based_stems": True,
    },
    "deduplication_rules": {
        "similarity_threshold": 0.82,
        "apply_between": [
            "KC_to_KC",
            "KC_to_Exam",
            "Exam_to_Exam",
        ],
    },
    "error_tolerance": {
        "word_count_tolerance_percent": 10,
        "retry_on_failure": True,
        "max_retries_per_step": 3,
    },
}
