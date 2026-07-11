from __future__ import annotations

import logging
import re
from typing import Any

from semantic_kernel import Kernel

from app.ai.rule_pack_config.prune import prune_empty_payload_values
from app.ai.shared_llm_config.tracer import write_s1_semantic_trace

from ...constants.validation import (
    S1_DIGEST_SECTION_CONTENT_MAX_CHARS,
    S1_DIGEST_SECTION_TITLE_MAX_CHARS,
    S1_DIGEST_SUBTOPIC_MAX_CHARS,
    is_out_of_scope_to_validation_issue,
    resolved_issues_from_refine_history,
)
from .deterministic import _check_required_topics_deterministic, _required_topics_to_issues
from .user_requirements import collect_s1_user_requirements, has_s1_user_requirements
from .models import MissingTopic, ValidationIssue, ValidationResult
from .semantic import SemanticValidator, _finalize_result

logger = logging.getLogger(__name__)


def _normalize_topic_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _precheck_topics_from_issues(issues: list[ValidationIssue]) -> set[str]:
    topics: set[str] = set()
    for issue in issues:
        field = str(issue.field or "")
        if field.startswith("required_topics_precheck."):
            topics.add(_normalize_topic_key(field.split(".", 1)[1]))
    return topics


def _coverage_topic_key(issue: ValidationIssue) -> str:
    message = str(issue.message or "")
    match = re.search(r"Required topic '([^']+)'", message)
    if match:
        return _normalize_topic_key(match.group(1))
    field = str(issue.field or "")
    if field.startswith("required_topics.coverage."):
        return _normalize_topic_key(field.split(".", 1)[1])
    return ""


def _build_s1_langfuse_payload(issue_dicts: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = sum(1 for issue in issue_dicts if issue.get("severity") == "blocker")
    warnings = sum(1 for issue in issue_dicts if issue.get("severity") == "warning")
    infos = sum(1 for issue in issue_dicts if issue.get("severity") == "info")
    actionable = [
        {
            key: issue.get(key)
            for key in ("field", "severity", "message", "rule_source")
            if issue.get(key)
        }
        for issue in issue_dicts
        if issue.get("severity") in ("blocker", "warning")
    ]
    summary_issue = next(
        (issue for issue in issue_dicts if issue.get("field") == "s1_ai_validator.summary"),
        None,
    )
    metrics_issue = next(
        (issue for issue in issue_dicts if issue.get("field") == "s1_ai_validator.metrics"),
        None,
    )
    return {
        "status": "PASS" if blockers == 0 and warnings == 0 else "FAIL",
        "blockers": blockers,
        "warnings": warnings,
        "infos": infos,
        "summary": (summary_issue or {}).get("message") or (summary_issue or {}).get("found"),
        "metrics": (metrics_issue or {}).get("found"),
        "issues": actionable,
    }


class AIOutlineValidator:
    """Orchestrates deterministic and AI semantic validation of the A0 Topic Outline.

    All methods are stateless; instantiation is not required.
    """

    @staticmethod
    def _trim_text(value: str | None, *, max_chars: int | None = 280) -> str:
        text = (value or "").strip()
        if max_chars is None or len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}..."

    @staticmethod
    def _subtopic_title(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("title") or "").strip()
        return str(item).strip()

    @staticmethod
    def _section_digest_from_course_spec(course_spec: dict[str, Any]) -> list[dict[str, Any]]:
        digest: list[dict[str, Any]] = []
        for idx, section in enumerate(course_spec.get("sections", []) or []):
            digest.append(
                {
                    "index": idx + 1,
                    "id": section.get("id") or section.get("section_id") or f"sec_{idx+1}",
                    "level": section.get("level", 1),
                    "title": AIOutlineValidator._trim_text(
                        section.get("heading") or section.get("title") or "",
                        max_chars=S1_DIGEST_SECTION_TITLE_MAX_CHARS,
                    ),
                    "word_count": section.get("word_count"),
                    "maps_to_objectives": section.get("maps_to_objectives") or [],
                }
            )
        return digest

    @staticmethod
    def _filter_out_of_scope_issues(issue_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            issue
            for issue in issue_dicts
            if not is_out_of_scope_to_validation_issue(issue)
        ]

    @staticmethod
    def _section_digest_from_llm_outline(shared_state: dict[str, Any]) -> list[dict[str, Any]]:
        llm_outline = shared_state.get("llm_to_outline_classification") or {}
        sections = llm_outline.get("sections") or llm_outline.get("course_outline", {}).get("sections") or []
        digest: list[dict[str, Any]] = []
        for idx, section in enumerate(sections):
            subtopics = section.get("subtopics") or section.get("topics") or []
            digest.append(
                {
                    "index": idx + 1,
                    "id": section.get("id") or section.get("section_id") or f"sec_{idx+1}",
                    "level": section.get("level", 1),
                    "title": AIOutlineValidator._trim_text(
                        section.get("title") or section.get("heading") or "",
                        max_chars=S1_DIGEST_SECTION_TITLE_MAX_CHARS,
                    ),
                    "word_count": section.get("word_count"),
                    "maps_to_objectives": section.get("maps_to_objectives") or [],
                    "subtopics": [
                        AIOutlineValidator._trim_text(
                            AIOutlineValidator._subtopic_title(item),
                            max_chars=S1_DIGEST_SUBTOPIC_MAX_CHARS,
                        )
                        for item in subtopics
                    ],
                    "content": AIOutlineValidator._trim_text(
                        section.get("content") or "",
                        max_chars=S1_DIGEST_SECTION_CONTENT_MAX_CHARS,
                    ),
                }
            )
        return digest

    @staticmethod
    def _collect_user_requirements(shared_state: dict[str, Any]) -> dict[str, Any]:
        return collect_s1_user_requirements(shared_state)

    @staticmethod
    def _has_user_requirements(requirements: dict[str, Any]) -> bool:
        return has_s1_user_requirements(requirements)

    @staticmethod
    def _fallback_issues(error: Exception) -> list[dict[str, Any]]:
        return [
            ValidationIssue(
                field="s1_ai_validator",
                expected="AI semantic validation result",
                found=str(error),
                severity="warning",
                message=(
                    "AI semantic validation could not be completed. "
                    "Only deterministic S1 checks were applied for this run."
                ),
                rule_source="s1_ai_validator",
                failure_reason="LLM call or response parsing failed after retries.",
                remediation=(
                    "Retry semantic validation. If the issue persists, verify model deployment and "
                    "response-format compatibility."
                ),
            ).model_dump(exclude_none=True)
        ]

    @staticmethod
    def _result_to_issue_dicts(result: ValidationResult) -> list[dict[str, Any]]:
        issues = [issue.model_dump(exclude_none=True) for issue in result.issues]

        if result.summary:
            issues.append(
                ValidationIssue(
                    field="s1_ai_validator.summary",
                    expected="Semantic TO validation summary",
                    found=result.summary,
                    severity="info",
                    message=result.summary,
                    rule_source="s1_ai_validator",
                ).model_dump(exclude_none=True)
            )

        issues.append(
            ValidationIssue(
                field="s1_ai_validator.metrics",
                expected="Scores and confidence computed",
                found={
                    "coverage_score": round(result.coverage_score, 2),
                    "sequence_score": round(result.sequence_score, 2),
                    "relevance_score": round(result.relevance_score, 2),
                    "completeness_score": round(result.completeness_score, 2),
                    "confidence": round(result.confidence, 3),
                    "status": result.status,
                    "blockers": sum(1 for issue in result.issues if issue.severity == "blocker"),
                    "warnings": sum(1 for issue in result.issues if issue.severity == "warning"),
                },
                severity="info",
                message="AI semantic validation scores computed.",
                rule_source="s1_ai_validator.metrics",
            ).model_dump(exclude_none=True)
        )

        if result.retry_required:
            issues.append(
                ValidationIssue(
                    field="s1_ai_validator.retry",
                    expected="retry_required=false",
                    found=True,
                    severity="info",
                    message="AI validator requested TO regeneration.",
                    rule_source="s1_ai_validator.retry",
                    remediation=result.retry_prompt,
                ).model_dump(exclude_none=True)
            )
        return issues

    @staticmethod
    def _merge_required_topic_findings(
        result: ValidationResult,
        det_issues: list[ValidationIssue],
        det_missing: list[MissingTopic],
    ) -> None:
        if not det_issues and not det_missing:
            return

        existing_fields = {i.field for i in result.issues}
        precheck_topics = _precheck_topics_from_issues(result.issues)
        for issue in det_issues:
            if issue.field in existing_fields:
                continue
            topic_key = _coverage_topic_key(issue)
            if topic_key and topic_key in precheck_topics:
                continue
            result.issues.append(issue)
            existing_fields.add(issue.field)

        existing_topics = {mt.topic.lower() for mt in result.missing_topics}
        for mt in det_missing:
            if mt.topic.lower() not in existing_topics:
                result.missing_topics.append(mt)
                existing_topics.add(mt.topic.lower())

        _finalize_result(result)

    @staticmethod
    def run(
        *,
        kernel: Kernel,
        shared_state: dict[str, Any],
        course_spec: dict[str, Any],
        to_rule_pack: dict[str, Any] | None = None,
        rule_pack: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Run all AI outline checks and return (issues, priority_rule)."""
        active_to_rules = to_rule_pack or rule_pack or {}
        _ = course_spec
        requirements = AIOutlineValidator._collect_user_requirements(shared_state)
        has_user_reqs = AIOutlineValidator._has_user_requirements(requirements)
        priority_rule = (
            "User requirements override TO rule pack whenever both are present."
            if has_user_reqs
            else "Validate using TO timed-outline rule pack."
        )

        sections = AIOutlineValidator._section_digest_from_llm_outline(shared_state)
        if not sections:
            logger.warning(
                "[S1][AI] No A0 TO sections found in llm_to_outline_classification; "
                "semantic validation will run with empty outline context."
            )

        required_topics: list[str] = requirements.get("required_topics") or []
        coverage_results = _check_required_topics_deterministic(required_topics, sections)

        det_issues: list[ValidationIssue] = []
        det_missing: list[MissingTopic] = []
        if coverage_results:
            det_issues, det_missing = _required_topics_to_issues(coverage_results)

        required_topics_precheck = [
            {
                "topic": c.topic,
                "status": c.status,
                "match_pct": int(c.matched_fraction * 100),
                "found_in_sections": c.found_in_sections[:4],
            }
            for c in coverage_results
        ]
        missing_required = [c.topic for c in coverage_results if c.status == "missing"]
        partial_required = [c.topic for c in coverage_results if c.status == "partial"]

        n_missing = len(missing_required)
        n_partial = len(partial_required)
        if not required_topics:
            precheck_instruction = (
                "No required topics were supplied; skip required-topic coverage checks."
            )
        elif n_missing or n_partial:
            logger.warning(
                "[S1][AI] Required-topics pre-check: %d missing, %d partial out of %d requested.",
                n_missing,
                n_partial,
                len(required_topics),
            )
            precheck_instruction = (
                "The deterministic pre-check above already flagged the topics below. "
                "Do NOT contradict these findings. For each missing/partial topic, "
                "produce a corresponding issue and add it to missing_topics. "
                f"Missing: {missing_required}. Partial: {partial_required}."
            )
        else:
            logger.info(
                "[S1][AI] Required-topics pre-check: all %d required topics covered.",
                len(required_topics),
            )
            precheck_instruction = "All required topics detected by pre-check."

        payload = prune_empty_payload_values(
            {
                "validation_priority": priority_rule,
                "has_user_requirements": has_user_reqs,
                "user_requirements": requirements,
                "do_not_reflag": resolved_issues_from_refine_history(shared_state),
                "to_rule_pack": {
                    "id": active_to_rules.get("id"),
                    "name": active_to_rules.get("name"),
                    "version": active_to_rules.get("version"),
                    "required_fields": active_to_rules.get("required_fields", {}),
                    "structure_rules": active_to_rules.get("structure_rules", {}),
                    "quality_rules": active_to_rules.get("quality_rules", {}),
                },
                "to_validation_scope": (
                    "Validate TO outline quality only: user requirements, required topics, "
                    "sequencing, clarity, and to_rule_pack structure/quality rules. "
                    "Do NOT validate in-lesson knowledge checks, KC counts, quiz placement, "
                    "final exam readiness, exam question counts, or assessment_rules constraints."
                ),
                "course_outline": {
                    "title": requirements.get("course_title_override")
                    or shared_state.get("extracted_inputs", {}).get("title")
                    or "",
                    "total_sections": len(sections),
                    "sections": sections,
                },
                "required_topics_precheck": {
                    "total_requested": len(required_topics),
                    "missing_count": n_missing,
                    "partial_count": n_partial,
                    "coverage": required_topics_precheck,
                    "instruction": precheck_instruction,
                },
                "frontend_input_contract": {
                    "source": "POST /generate-to",
                    "a0_only_validation": True,
                    "notes": (
                        "Validate only against A0-generated TO and user inputs persisted from FE; "
                        "ignore A1 structure for this semantic pass."
                    ),
                },
            }
        )

        try:
            validator = SemanticValidator(kernel)
            result = validator.run(payload=payload, priority_rule=priority_rule)
            AIOutlineValidator._merge_required_topic_findings(result, det_issues, det_missing)
            issue_dicts = AIOutlineValidator._result_to_issue_dicts(result)
            issue_dicts = AIOutlineValidator._filter_out_of_scope_issues(issue_dicts)
            write_s1_semantic_trace(
                deployment=validator.last_deployment,
                system_prompt=validator.last_system_prompt,
                user_msg=validator.last_user_msg,
                validated_output=_build_s1_langfuse_payload(issue_dicts),
                latency_ms=validator.last_latency_ms,
            )
            return issue_dicts, priority_rule
        except Exception as exc:
            logger.exception("[S1][AI] Outline semantic validation failed: %s", exc)
            fallback = AIOutlineValidator._fallback_issues(exc)
            for issue in det_issues:
                fallback.append(issue.model_dump(exclude_none=True))
            return AIOutlineValidator._filter_out_of_scope_issues(fallback), priority_rule


# ---------------------------------------------------------------------------
# Backward-compatible module-level wrapper
# ---------------------------------------------------------------------------

def run_ai_outline_checks(
    *,
    kernel: Kernel,
    shared_state: dict[str, Any],
    course_spec: dict[str, Any],
    to_rule_pack: dict[str, Any] | None = None,
    rule_pack: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    return AIOutlineValidator.run(
        kernel=kernel,
        shared_state=shared_state,
        course_spec=course_spec,
        to_rule_pack=to_rule_pack,
        rule_pack=rule_pack,
    )


__all__ = ["AIOutlineValidator", "run_ai_outline_checks"]
