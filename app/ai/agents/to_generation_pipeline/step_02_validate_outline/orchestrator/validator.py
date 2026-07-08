"""S1 validation orchestrator — coordinates rule resolution, checks, and reporting."""

from __future__ import annotations

import logging
import time as _time
from typing import Literal

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.to_rule_pack import (
    TO_RULE_PACK_ID,
    TO_RULE_PACK_VERSION,
)
from app.ai.agents.to_generation_pipeline.models import S1ValidationReport
from app.ai.shared_llm_config.tracer import write_span

from .deterministic_check_runner import DeterministicCheckRunner
from .report_writer import ValidationReportWriter
from .rule_source_resolver import RuleSourceResolver

S1ValidationPhase = Literal["full", "to_only", "a1_only"]
logger = logging.getLogger(__name__)


class S1Validator:
    """Stage-1 validator for TO outlines and enriched course specifications.

    Operates entirely on an in-memory ``shared_state`` dict — no file is read
    or written. ``shared_state`` is mutated in place with the validation
    result (mirrors what the file-backed version used to persist to disk),
    so callers running a repair loop keep passing the same dict back in.
    """

    def __init__(self, kernel: Kernel, shared_state: dict) -> None:
        self.kernel = kernel
        self.shared_state = shared_state

    def run(self, *, phase: S1ValidationPhase = "full") -> S1ValidationReport:
        """Execute S1 validation checks and return a typed report."""
        started_at = _time.perf_counter()
        report: S1ValidationReport | None = None
        error: str | None = None
        try:
            report = self._run_checks(phase=phase)
            return report
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            write_span(
                name=f"S1 Validation | phase={phase}",
                agent="S1",
                latency_ms=(_time.perf_counter() - started_at) * 1000,
                output_data={
                    "status": getattr(report, "status", None),
                    "blockers": getattr(report, "blockers", None),
                    "warnings": getattr(report, "warnings", None),
                }
                if report is not None
                else {},
                error=error,
            )

    def _run_checks(self, *, phase: S1ValidationPhase) -> S1ValidationReport:
        logger.info("[S1] Running validation checks in-memory (phase=%s)...", phase)
        shared_state = self.shared_state

        run_id = shared_state.get("run_id", "unknown")
        a1_output = shared_state.get("agent_outputs", {}).get("A1", {})
        a1_ready = bool(a1_output) and a1_output.get("status") == "complete"
        course_spec = a1_output.get("course_spec", {}) if a1_ready else {}

        self._log_phase_banner(phase, a1_ready)

        rule_context = RuleSourceResolver.resolve(
            phase=phase,
            shared_state=shared_state,
            run_id=run_id,
        )
        if rule_context.early_exit_report is not None:
            return rule_context.early_exit_report

        self._log_rule_pack_source(rule_context)

        check_result = DeterministicCheckRunner.run(
            kernel=self.kernel,
            phase=phase,
            shared_state=shared_state,
            course_spec=course_spec,
            a1_output=a1_output,
            a1_ready=a1_ready,
            rule_context=rule_context,
        )

        report = ValidationReportWriter.build_report(
            raw_issues=check_result.raw_issues,
            run_id=run_id,
        )
        ValidationReportWriter.persist(
            report=report,
            shared_state=shared_state,
            rule_pack_label=rule_context.rule_pack_label,
            priority_rule=check_result.priority_rule,
            phase=phase,
        )
        return report

    @staticmethod
    def _log_phase_banner(phase: S1ValidationPhase, a1_ready: bool) -> None:
        if phase == "to_only":
            logger.info("[S1] Phase to_only: validating A0 TO outline before A1 runs.")
        elif phase == "a1_only":
            logger.info("[S1] Phase a1_only: re-validating TO outline with to_rule_pack after A1.")
        elif not a1_ready:
            logger.info(
                "[S1] A1 output missing/incomplete; running TO-only validation on A0 outline."
            )

    @staticmethod
    def _log_rule_pack_source(rule_context) -> None:
        if rule_context.use_to_rule_pack:
            logger.info(
                "[S1] Validating TO outline against rule pack: %s %s",
                TO_RULE_PACK_ID,
                TO_RULE_PACK_VERSION,
            )
