"""Build, log, and persist the S1 validation report.

Persistence is entirely in-memory: `persist()` writes the report into the
`shared_state` dict it's given (same shape as before) but never touches disk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.ai.agents.to_generation_pipeline.models import S1Status, S1ValidationReport, ValidationIssue

from ..constants.pipeline_config import (
    SHARED_STATE_STATUS_BLOCKED,
    SHARED_STATE_STATUS_VALIDATED,
)

logger = logging.getLogger(__name__)


class ValidationReportWriter:
    """Tallies issues, logs the report, and stores it in the in-memory shared state."""

    @classmethod
    def build_report(
        cls,
        *,
        raw_issues: list[dict],
        run_id: str,
    ) -> S1ValidationReport:
        all_issues = [ValidationIssue.model_validate(issue) for issue in raw_issues]
        blockers = [issue for issue in all_issues if issue.severity == "blocker"]
        warnings = [issue for issue in all_issues if issue.severity == "warning"]
        infos = [issue for issue in all_issues if issue.severity == "info"]

        if blockers:
            status = S1Status.blocked
        elif warnings:
            status = S1Status.pass_with_warnings
        else:
            status = S1Status.pass_

        cls._log_summary(status, blockers, warnings, infos)

        return S1ValidationReport(
            status=status,
            run_id=run_id,
            issues=all_issues,
            blockers=len(blockers),
            warnings=len(warnings),
            infos=len(infos),
        )

    @classmethod
    def persist(
        cls,
        *,
        report: S1ValidationReport,
        shared_state: dict,
        rule_pack_label: str,
        priority_rule: str,
        phase: str,
    ) -> None:
        """Record the report onto `shared_state` in place — no disk I/O."""
        validation_dict = report.model_dump(mode="json")
        validation_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
        validation_dict["rule_pack_used"] = rule_pack_label
        validation_dict["validation_priority"] = priority_rule
        validation_dict["phase"] = phase

        shared_state["s1_validation"] = validation_dict
        shared_state["status"] = (
            SHARED_STATE_STATUS_BLOCKED
            if report.status == S1Status.blocked
            else SHARED_STATE_STATUS_VALIDATED
        )

        logger.info("[S1] Report recorded in-memory (run_id=%s)", report.run_id)

    @staticmethod
    def _log_summary(
        status: S1Status,
        blockers: list[ValidationIssue],
        warnings: list[ValidationIssue],
        infos: list[ValidationIssue],
    ) -> None:
        logger.info("[S1] Validation complete: %s", status.upper())
        logger.info(
            "     Blockers: %s  |  Warnings: %s  |  Info: %s",
            len(blockers),
            len(warnings),
            len(infos),
        )

        if blockers:
            logger.warning("  BLOCKERS (pipeline cannot proceed):")
            for blocker in blockers:
                logger.warning("    [BLOCKER] %s: %s", blocker.field, blocker.message)
                logger.warning("              Rule: %s", blocker.rule_source)

        if warnings:
            logger.info("  WARNINGS (review recommended):")
            for warning in warnings:
                logger.info("    [WARNING] %s: %s", warning.field, warning.message)
                logger.info("              Rule: %s", warning.rule_source)

        if infos:
            logger.info("  INFO:")
            for info in infos:
                logger.info("    [INFO] %s: %s", info.field, info.message)
