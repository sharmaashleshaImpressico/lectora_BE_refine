"""Filter and group S1 validation issues for TO refinement."""

from __future__ import annotations

from app.ai.agents.to_generation_pipeline.step_02_validate_outline.constants.validation import (
    has_concrete_repair_target,
    normalize_s1_issue_field,
    s1_warning_priority_key,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.config import (
    MAX_REFINE_WARNING_ISSUES_PER_CYCLE,
    REFINE_SKIP_FIELDS,
    REFINE_SKIP_WARNING_FIELD_PREFIXES,
    REFINE_SKIP_WARNING_FIELDS,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.models import S1RefinementIssue
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.topic_keys import (
    refinement_issue_topic_key,
)
from app.ai.agents.to_generation_pipeline.models import IssueSeverity, S1ValidationReport, ValidationIssue


class RefinementIssueFilter:
    """Selects blocker and TO-repairable warning issues from an S1 report."""

    def __init__(
        self,
        *,
        skip_fields: frozenset[str] = REFINE_SKIP_FIELDS,
        skip_warning_fields: frozenset[str] = REFINE_SKIP_WARNING_FIELDS,
        skip_warning_prefixes: tuple[str, ...] = REFINE_SKIP_WARNING_FIELD_PREFIXES,
        max_warning_issues: int = MAX_REFINE_WARNING_ISSUES_PER_CYCLE,
    ) -> None:
        self._skip_fields = skip_fields
        self._skip_warning_fields = skip_warning_fields
        self._skip_warning_prefixes = skip_warning_prefixes
        self._max_warning_issues = max_warning_issues

    def is_refinable(self, issue: ValidationIssue) -> bool:
        """Return True for S1 blockers and TO-repairable warnings."""
        if issue.field == "s1_ai_validator.retry":
            return bool(issue.remediation and str(issue.remediation).strip())
        if issue.field in self._skip_fields:
            return False
        if self._matches_skip_warning_prefix(issue.field):
            return False
        if issue.severity == IssueSeverity.blocker:
            return True
        if issue.severity == IssueSeverity.warning:
            if issue.field in self._skip_warning_fields:
                return False
            return has_concrete_repair_target(issue.field)
        return False

    def from_report(self, report: S1ValidationReport) -> list[S1RefinementIssue]:
        """Convert an S1 report into deduplicated, capped refinement issues."""
        refined: list[S1RefinementIssue] = []
        seen_fields: set[str] = set()

        for issue in report.issues:
            if not self.is_refinable(issue):
                continue
            if issue.field in seen_fields:
                continue
            seen_fields.add(issue.field)
            refined.append(self._to_refinement_issue(issue))

        refined = self._dedupe_topic_issues(refined)
        refined = self._drop_retry_when_specific_issues_exist(refined)
        blockers, warnings = RefinementIssueGrouper.partition_by_severity(refined)
        if len(warnings) <= self._max_warning_issues:
            return blockers + warnings
        prioritized = sorted(warnings, key=lambda issue: s1_warning_priority_key(issue.field))
        return blockers + prioritized[: self._max_warning_issues]

    @classmethod
    def _drop_retry_when_specific_issues_exist(
        cls, issues: list[S1RefinementIssue]
    ) -> list[S1RefinementIssue]:
        """Drop broad retry guidance when field-specific warnings/blockers are present."""
        has_specific = any(issue.field != "s1_ai_validator.retry" for issue in issues)
        if not has_specific:
            return issues
        return [issue for issue in issues if issue.field != "s1_ai_validator.retry"]

    @classmethod
    def _dedupe_topic_issues(cls, issues: list[S1RefinementIssue]) -> list[S1RefinementIssue]:
        """Drop semantic duplicates when a deterministic coverage issue exists for the same topic."""
        coverage_keys = {
            key
            for issue in issues
            if issue.field.startswith("required_topics.coverage.")
            for key in [refinement_issue_topic_key(issue.field, issue.message)]
            if key
        }
        deduped: list[S1RefinementIssue] = []
        seen_topic_keys: set[str] = set()
        for issue in issues:
            topic_key = refinement_issue_topic_key(issue.field, issue.message)
            if topic_key:
                if (
                    issue.field.startswith("learning_objective_mapping.")
                    and topic_key in coverage_keys
                ):
                    continue
                if issue.field == "learning_objectives" and topic_key in coverage_keys:
                    continue
                if topic_key in seen_topic_keys:
                    continue
                seen_topic_keys.add(topic_key)
            deduped.append(issue)
        return deduped

    @classmethod
    def _matches_skip_warning_prefix(cls, field: str) -> bool:
        return any(field.startswith(prefix) for prefix in REFINE_SKIP_WARNING_FIELD_PREFIXES)

    @staticmethod
    def _to_refinement_issue(issue: ValidationIssue) -> S1RefinementIssue:
        severity = issue.severity.value
        field = normalize_s1_issue_field(issue.field)
        message = issue.message
        remediation = issue.remediation
        if issue.field == "s1_ai_validator.retry" and remediation:
            severity = "warning"
            message = str(remediation)
            remediation = None
        return S1RefinementIssue(
            field=field,
            message=message,
            severity=severity,
            expected=str(issue.expected),
            found=str(issue.found),
            rule_source=issue.rule_source,
            remediation=remediation,
        )


class RefinementIssueGrouper:
    """Partitions refinement issues into blocker and warning buckets."""

    @staticmethod
    def partition_by_severity(
        issues: list[S1RefinementIssue],
    ) -> tuple[list[S1RefinementIssue], list[S1RefinementIssue]]:
        blockers = [issue for issue in issues if issue.severity == "blocker"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        return blockers, warnings

    @staticmethod
    def count_severities(issues: list[S1RefinementIssue]) -> tuple[int, int]:
        blockers, warnings = RefinementIssueGrouper.partition_by_severity(issues)
        return len(blockers), len(warnings)
