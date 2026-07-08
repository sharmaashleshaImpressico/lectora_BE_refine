from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from pydantic import ValidationError

from lectora_backend.pipeline.shared_llm_config.llm import LLMConfig, chat as llm_chat
from lectora_backend.pipeline.shared_llm_config.model_registry import get_deployment
from lectora_backend.pipeline.shared_llm_config.tracer import (
    defer_s1_langfuse_tracing,
)

from ...constants.prompts import (
    RESPONSE_SCHEMA,
    SEMANTIC_SYSTEM_PROMPT as _SEMANTIC_SYSTEM_PROMPT,
    SEVERITY_POLICY,
    VALIDATION_RULES,
)
from ...constants.validation import (
    A0_NON_BLOCKING_FIELD_TOKENS as _A0_NON_BLOCKING_FIELD_TOKENS,
    MAX_S1_SEMANTIC_WARNINGS,
    is_out_of_scope_to_validation_issue,
    normalize_s1_issue_field,
    s1_warning_priority_key,
)
from .deterministic import TopicCoverageChecker
from .models import (
    MAX_LLM_RETRIES,
    RETRY_BACKOFF_SECONDS,
    BaseValidator,
    DependencyIssue,
    MissingTopic,
    ObjectiveMapping,
    Recommendation,
    ValidationIssue,
    ValidationResult,
)

try:
    import json_repair  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    json_repair = None

logger = logging.getLogger(__name__)


class SemanticValidator(BaseValidator):
    """Primary LLM-backed semantic validator for Topic Outline quality gates."""

    name = "semantic"

    def __init__(self) -> None:
        self.last_system_prompt = ""
        self.last_user_msg = ""
        self.last_latency_ms = 0.0
        self.last_deployment = ""

    def run(
        self,
        *,
        payload: dict[str, Any],
        priority_rule: str,
    ) -> ValidationResult:
        _ = priority_rule
        prompt = self._build_system_prompt()
        started = time.perf_counter()
        payload_json = json.dumps(payload, ensure_ascii=False)
        logger.info(
            "[S1][AI] Starting semantic validation | payload_bytes=%d | sections=%d",
            len(payload_json.encode("utf-8")),
            payload.get("course_outline", {}).get("total_sections", 0),
        )

        config = LLMConfig(
            deployment=get_deployment("A0_TO"),
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        with defer_s1_langfuse_tracing():
            raw_data = self._call_llm_with_retries(prompt, payload_json, config)
        result = self._to_validation_result(raw_data)
        self._finalize_result(result)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self.last_system_prompt = prompt
        self.last_user_msg = payload_json
        self.last_latency_ms = elapsed_ms
        self.last_deployment = config.deployment
        logger.info(
            "[S1][AI] Validation complete | duration_ms=%d | status=%s | confidence=%.2f | retry=%s",
            elapsed_ms,
            result.status,
            result.confidence,
            result.retry_required,
        )
        logger.info(
            "[S1][AI] Scores | coverage=%.1f | sequence=%.1f | relevance=%.1f | completeness=%.1f",
            result.coverage_score,
            result.sequence_score,
            result.relevance_score,
            result.completeness_score,
        )
        logger.info(
            "[S1][AI] Issues summary | blockers=%d | warnings=%d | infos=%d",
            self._count_by_severity(result.issues, "blocker"),
            self._count_by_severity(result.issues, "warning"),
            self._count_by_severity(result.issues, "info"),
        )
        return result

    def _call_llm_with_retries(self, system_prompt: str, payload_json: str, config: LLMConfig) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_LLM_RETRIES + 2):
            try:
                raw = llm_chat(system_prompt, payload_json, config, agent="S1")
                data = self._safe_json_loads(raw)
                if not isinstance(data, dict):
                    raise ValueError(f"Expected JSON object, got {type(data).__name__}")
                return data
            except Exception as exc:
                last_error = exc
                if attempt > MAX_LLM_RETRIES:
                    break
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "[S1][AI] LLM attempt %d failed (%s). Retrying in %.2fs...",
                    attempt,
                    exc,
                    delay,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    # ── Private static helpers ────────────────────────────────────────────────

    @staticmethod
    def _build_system_prompt() -> str:
        rules = "\n".join(f"{idx + 1}) {rule}" for idx, rule in enumerate(VALIDATION_RULES))
        return "\n\n".join(
            [
                _SEMANTIC_SYSTEM_PROMPT,
                "Validate all checks:\n" + rules,
                "Return JSON with this exact schema:\n" + RESPONSE_SCHEMA,
                SEVERITY_POLICY,
                (
                    "Pass criteria (must enforce):\n"
                    "- status=PASS and retry_required=false only when there are zero blocker and zero warning issues\n"
                    "- status=FAIL when at least one issue has severity blocker or warning\n"
                    "- retry_required=true when at least one issue has severity blocker or warning\n"
                    "- info issues alone must NEVER produce FAIL or retry_required"
                ),
                (
                    "A0 TO validation constraints:\n"
                    "- Do NOT require final exam blueprint, question counts, or assessment_rules checks.\n"
                    "- Do NOT require explicit maps_to_objectives arrays in A0 sections.\n"
                    "- Do NOT validate in-lesson knowledge checks, KC counts, or quiz placement.\n"
                    "- \n"
                    "- Use field paths: course_outline.sections[N].subtopics (1-based N matching section title).\n"
                    "- Emit at most 4 warning issues per run; prioritize required-topic coverage gaps first.\n"
                    "- Do NOT re-flag issues listed under do_not_reflag in the payload unless clearly unfixed.\n"
                    "- Do NOT warn about course duration/section count unless deviation exceeds 15%.\n"
                    "- DURATION CHECK RULE:\n"
                    "  - If calculated_word_count is provided, validate duration against total word_count, not raw minutes or credit_hours.\n"
                    "  - Pass duration when total word_count matches calculated_word_count within tolerance.\n"
                    "  - Warn only if word_count exceeds tolerance or section totals are inconsistent.\n"
                    "- Sequencing concerns that are acceptable with a brief prerequisite note should be info, not warning.\n"
                    "- If maps_to_objectives are missing, emit warning/info (not blocker)."
                ),
            ]
        )

    @staticmethod
    def _safe_json_loads(raw: str) -> Any:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if json_repair is not None:
                repaired = json_repair.repair_json(raw, return_objects=True)
                if repaired is not None:
                    return repaired
            raise

    @staticmethod
    def _coerce_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        return []

    @staticmethod
    def _clamp_score(value: Any, *, max_value: float = 100.0) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(max_value, numeric))

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        score = SemanticValidator._clamp_score(value, max_value=100.0)
        if score > 1.0:
            score = score / 100.0
        return SemanticValidator._clamp_score(score, max_value=1.0)

    @staticmethod
    def _count_by_severity(issues: list[ValidationIssue], severity: str) -> int:
        return sum(1 for issue in issues if issue.severity == severity)

    _FIELD_TOPIC_PREFIXES: tuple[str, ...] = ("learning_objective_mapping.",)
    _EXPECTED_TOPIC_PREFIXES: tuple[str, ...] = (
        "a practical ",
        "a dedicated ",
        "a clearly developed ",
        "course outline should explicitly teach ",
    )
    _REQUIRED_TOPIC_IN_BODY = re.compile(r"Required topic '([^']+)'")

    @staticmethod
    def _derive_topic_label_from_expected(expected: str) -> str:
        text = expected.strip().rstrip(".")
        lowered = text.lower()
        for prefix in SemanticValidator._EXPECTED_TOPIC_PREFIXES:
            if lowered.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        return text[:120].strip()

    @staticmethod
    def _realign_issue_field_topic(issue: ValidationIssue) -> ValidationIssue:
        """Fix S1 AI issues where ``field`` names one topic but body text describes another."""
        field = issue.field
        for prefix in SemanticValidator._FIELD_TOPIC_PREFIXES:
            if not field.startswith(prefix):
                continue

            label = field[len(prefix):]
            label_tokens = TopicCoverageChecker._topic_keywords(label)
            if not label_tokens:
                break

            body = " ".join(
                str(part)
                for part in (issue.expected, issue.message, issue.remediation or "")
                if part
            )
            body_tokens = set(TopicCoverageChecker._topic_keywords(body))
            overlap = sum(1 for token in label_tokens if token in body_tokens) / len(label_tokens)
            if overlap >= 0.34:
                break

            quoted = SemanticValidator._REQUIRED_TOPIC_IN_BODY.search(body)
            new_label = quoted.group(1).strip() if quoted else ""
            if not new_label:
                new_label = SemanticValidator._derive_topic_label_from_expected(str(issue.expected))
            if new_label:
                issue.field = f"{prefix}{new_label}"
            break
        return issue

    @staticmethod
    def _normalize_issue(raw: dict[str, Any], idx: int) -> ValidationIssue:
        raw_sev = str(raw.get("severity", "warning")).lower()
        severity_map = {
            "blocker": "blocker",
            "blocked": "blocker",
            "critical": "blocker",
            "major": "blocker",
            "warning": "warning",
            "warn": "warning",
            "info": "info",
        }
        severity = severity_map.get(raw_sev, "warning")
        field = normalize_s1_issue_field(str(raw.get("field") or f"ai_outline_validation.{idx}"))
        message = str(raw.get("message") or "AI validator found an outline issue.")

        if severity == "blocker":
            lower_field = field.lower()
            lower_msg = message.lower()
            if any(token in lower_field or token in lower_msg for token in _A0_NON_BLOCKING_FIELD_TOKENS):
                severity = "warning"

        return ValidationIssue(
            field=field,
            expected=str(raw.get("expected") or "Requirement satisfied"),
            found=raw.get("found", "Not satisfied"),
            severity=severity,  # type: ignore[arg-type]
            message=message,
            rule_source=str(raw.get("rule_source") or "s1_ai_validator"),
            failure_reason=raw.get("failure_reason"),
            remediation=raw.get("remediation"),
        )

    @staticmethod
    def _coerce_recommendation(raw: Any) -> Recommendation:
        if isinstance(raw, str):
            return Recommendation(title=raw, detail="", priority="medium")
        if isinstance(raw, dict):
            return Recommendation.model_validate(raw)
        return Recommendation(title=str(raw), detail="", priority="low")

    @staticmethod
    def _coerce_missing_topic(raw: Any) -> MissingTopic:
        if isinstance(raw, str):
            return MissingTopic(topic=raw, reason="", severity="medium")
        if isinstance(raw, dict):
            return MissingTopic.model_validate(raw)
        return MissingTopic(topic=str(raw), reason="", severity="low")

    @staticmethod
    def _coerce_dependency_issue(raw: Any) -> DependencyIssue:
        if isinstance(raw, str):
            return DependencyIssue(topic=raw, missing_prerequisite="", reason="")
        if isinstance(raw, dict):
            return DependencyIssue.model_validate(raw)
        return DependencyIssue(topic=str(raw), missing_prerequisite="", reason="")

    @staticmethod
    def _coerce_objective_mapping(raw: Any) -> ObjectiveMapping:
        if isinstance(raw, str):
            return ObjectiveMapping(objective=raw, status="partial", evidence="")
        if isinstance(raw, dict):
            return ObjectiveMapping.model_validate(raw)
        return ObjectiveMapping(objective=str(raw), status="partial", evidence="")

    @staticmethod
    def _to_validation_result(raw_data: dict[str, Any]) -> ValidationResult:
        raw_issues = SemanticValidator._coerce_list(raw_data.get("issues"))
        issues = [
            SemanticValidator._realign_issue_field_topic(
                SemanticValidator._normalize_issue(issue, idx)
            )
            for idx, issue in enumerate(raw_issues)
            if isinstance(issue, dict)
            and not is_out_of_scope_to_validation_issue(issue)
        ]

        recommendations = [
            SemanticValidator._coerce_recommendation(item)
            for item in SemanticValidator._coerce_list(raw_data.get("recommendations"))
        ]
        missing_topics = [
            SemanticValidator._coerce_missing_topic(item)
            for item in SemanticValidator._coerce_list(raw_data.get("missing_topics"))
        ]
        dependency_issues = [
            SemanticValidator._coerce_dependency_issue(item)
            for item in SemanticValidator._coerce_list(raw_data.get("dependency_issues"))
        ]
        objective_mapping = [
            SemanticValidator._coerce_objective_mapping(item)
            for item in SemanticValidator._coerce_list(raw_data.get("learning_objective_mapping"))
        ]

        duplicates = [
            str(item).strip()
            for item in SemanticValidator._coerce_list(raw_data.get("duplicates"))
            if str(item).strip()
        ]

        try:
            return ValidationResult(
                summary=str(raw_data.get("summary") or "").strip(),
                coverage_score=SemanticValidator._clamp_score(raw_data.get("coverage_score")),
                sequence_score=SemanticValidator._clamp_score(raw_data.get("sequence_score")),
                relevance_score=SemanticValidator._clamp_score(raw_data.get("relevance_score")),
                completeness_score=SemanticValidator._clamp_score(raw_data.get("completeness_score")),
                confidence=SemanticValidator._normalize_confidence(raw_data.get("confidence")),
                status="PASS" if str(raw_data.get("status", "FAIL")).strip().upper() == "PASS" else "FAIL",
                issues=issues,
                recommendations=recommendations,
                missing_topics=missing_topics,
                duplicates=duplicates,
                dependency_issues=dependency_issues,
                learning_objective_mapping=objective_mapping,
                retry_required=bool(raw_data.get("retry_required", False)),
                retry_prompt=str(raw_data.get("retry_prompt") or "").strip(),
            )
        except ValidationError:
            logger.exception("[S1][AI] ValidationResult parsing failed; using minimal fallback.")
            return ValidationResult(
                summary="Semantic validation result could not be fully parsed.",
                issues=issues,
                recommendations=recommendations,
                missing_topics=missing_topics,
                duplicates=duplicates,
                dependency_issues=dependency_issues,
                learning_objective_mapping=objective_mapping,
            )

    @staticmethod
    def _score_from_issues(result: ValidationResult) -> None:
        blockers = SemanticValidator._count_by_severity(result.issues, "blocker")
        warnings = SemanticValidator._count_by_severity(result.issues, "warning")
        infos = SemanticValidator._count_by_severity(result.issues, "info")

        if result.coverage_score <= 0:
            result.coverage_score = max(0.0, 100.0 - (18.0 * len(result.missing_topics)) - (6.0 * warnings))
        if result.sequence_score <= 0:
            sequence_penalty = 20.0 * len(result.dependency_issues)
            result.sequence_score = max(0.0, 100.0 - sequence_penalty - (5.0 * warnings))
        if result.relevance_score <= 0:
            relevance_penalty = 12.0 * len(result.duplicates) + (8.0 * blockers)
            result.relevance_score = max(0.0, 100.0 - relevance_penalty - (3.0 * warnings))
        if result.completeness_score <= 0:
            result.completeness_score = max(0.0, 100.0 - (12.0 * blockers) - (4.0 * warnings) - (1.0 * infos))
        if result.confidence <= 0:
            confidence = 0.95 - (0.18 * blockers) - (0.04 * warnings)
            result.confidence = max(0.05, min(1.0, confidence))

    @staticmethod
    def _cap_actionable_warnings(result: ValidationResult) -> None:
        """Keep refine cycles convergent by limiting warning count from the AI validator."""
        blockers = [issue for issue in result.issues if issue.severity == "blocker"]
        warnings = [issue for issue in result.issues if issue.severity == "warning"]
        infos = [issue for issue in result.issues if issue.severity == "info"]
        if len(warnings) <= MAX_S1_SEMANTIC_WARNINGS:
            return

        warnings.sort(key=lambda issue: s1_warning_priority_key(issue.field))
        kept = warnings[:MAX_S1_SEMANTIC_WARNINGS]
        demoted = warnings[MAX_S1_SEMANTIC_WARNINGS:]
        for issue in demoted:
            issue.severity = "info"
            infos.append(issue)
        result.issues = blockers + kept + infos

    @staticmethod
    def _finalize_result(result: ValidationResult) -> None:
        """Recompute auxiliary scores, determine pass/fail from blockers/warnings, and build retry prompt."""
        SemanticValidator._cap_actionable_warnings(result)
        SemanticValidator._score_from_issues(result)

        blockers = SemanticValidator._count_by_severity(result.issues, "blocker")
        warnings = SemanticValidator._count_by_severity(result.issues, "warning")
        result.status = "PASS" if blockers == 0 and warnings == 0 else "FAIL"
        result.retry_required = blockers > 0 or warnings > 0

        if result.retry_required and not result.retry_prompt:
            strongest_issue = next(
                (issue for issue in result.issues if issue.severity == "blocker"),
                next(
                    (issue for issue in result.issues if issue.severity == "warning"),
                    result.issues[0] if result.issues else None,
                ),
            )
            issue_text = strongest_issue.message if strongest_issue else "Improve semantic alignment."
            missing = ", ".join(t.topic for t in result.missing_topics[:5] if t.topic)
            duplicate_text = ", ".join(result.duplicates[:5])
            result.retry_prompt = (
                "Regenerate the Topic Outline with strict adherence to user requirements and rule-pack constraints. "
                f"Primary issue: {issue_text}. "
                + (f"Missing topics to include: {missing}. " if missing else "")
                + (f"Remove or merge duplicates: {duplicate_text}. " if duplicate_text else "")
                + "Ensure prerequisite topics appear before advanced topics, and map each learning objective explicitly."
            ).strip()


# ---------------------------------------------------------------------------
# Backward-compatible module-level wrapper
# ---------------------------------------------------------------------------

def _finalize_result(result: ValidationResult) -> None:
    SemanticValidator._finalize_result(result)


__all__ = ["SemanticValidator", "_finalize_result"]
