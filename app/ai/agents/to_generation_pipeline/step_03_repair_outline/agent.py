"""S1 Validator Refine agent — orchestrates TO repair from S1 feedback."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.step_03_repair_outline.config.llm import (
    make_config,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.config import (
    LLM_CALL_PURPOSE,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.prompts import (
    REPAIR_SYSTEM_PROMPT,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementInput,
    S1RefinementIssue,
    S1RefinementOutput,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.issues import (
    RefinementIssueFilter,
    RefinementIssueGrouper,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.message_builder import (
    RefinementMessageBuilder,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.outline_persister import (
    OutlinePersister,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.response_parser import (
    RefinementResponseParser,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.section1 import (
    Section1LearningObjectiveNormalizer,
)
from app.ai.agents.to_generation_pipeline.models import S1ValidationReport, ValidationIssue
from app.kernel.chat import LLMConfig, chat as llm_chat

logger = logging.getLogger(__name__)


class S1ValidatorRefineAgent:
    """Refines an A0 Timed Outline using S1 blocker and warning feedback."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        issue_filter: RefinementIssueFilter | None = None,
        message_builder: RefinementMessageBuilder | None = None,
        response_parser: RefinementResponseParser | None = None,
        outline_persister: OutlinePersister | None = None,
        section1_normalizer: Section1LearningObjectiveNormalizer | None = None,
        llm_chat_fn: Callable[[Kernel, str, str, LLMConfig, str], str] | None = None,
        config_factory: Callable[[], LLMConfig] | None = None,
    ) -> None:
        self._kernel = kernel
        self._issue_filter = issue_filter or RefinementIssueFilter()
        self._message_builder = message_builder or RefinementMessageBuilder()
        self._response_parser = response_parser or RefinementResponseParser()
        self._outline_persister = outline_persister or OutlinePersister()
        self._section1_normalizer = section1_normalizer or Section1LearningObjectiveNormalizer()
        self._llm_chat = llm_chat_fn or llm_chat
        self._config_factory = config_factory or make_config

    def run(self, input_data: S1RefinementInput) -> S1RefinementOutput:
        if not input_data.current_outline:
            logger.warning("[s1_validator_refine] Empty outline — skipping refinement")
            return S1RefinementOutput(outline={}, applied=False)

        if not input_data.issues:
            logger.warning("[s1_validator_refine] No refinable issues — skipping refinement")
            return S1RefinementOutput(
                outline=dict(input_data.current_outline),
                applied=False,
            )

        blocker_count, warning_count = RefinementIssueGrouper.count_severities(input_data.issues)
        logger.info(
            "[s1_validator_refine] Repairing TO with %d issue(s) "
            "(blockers=%d, warnings=%d)",
            len(input_data.issues),
            blocker_count,
            warning_count,
        )

        repaired = self._repair_outline(input_data)
        if repaired is None:
            return S1RefinementOutput(
                outline=dict(input_data.current_outline),
                applied=False,
            )

        repaired = self._section1_normalizer.normalize(
            repaired,
            issues=input_data.issues,
        )

        logger.info(
            "[s1_validator_refine] Repaired outline with %d section(s)",
            len(repaired.get("sections") or []),
        )
        return S1RefinementOutput(outline=repaired, applied=True)

    def run_from_shared_state(
        self,
        shared_state_path: str,
        s1_report: S1ValidationReport,
    ) -> S1RefinementOutput:
        state_path = Path(shared_state_path).expanduser().resolve()
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)

        refinement_issues = self._issue_filter.from_report(s1_report)
        output = self.run(
            S1RefinementInput(
                current_outline=state.get("llm_to_outline_classification") or {},
                issues=refinement_issues,
                course_config=state.get("course_config") or {},
            )
        )
        if output.applied:
            self._outline_persister.persist(
                shared_state_path,
                output.outline,
                refinement_issues=refinement_issues,
            )
        return output

    def _repair_outline(self, input_data: S1RefinementInput) -> dict[str, Any] | None:
        user_msg = self._message_builder.build(input_data)
        try:
            raw = self._llm_chat(
                self._kernel,
                REPAIR_SYSTEM_PROMPT,
                user_msg,
                self._config_factory(),
                LLM_CALL_PURPOSE,
            )
            repaired = self._response_parser.parse_outline(raw)
            if repaired is None:
                logger.warning(
                    "[s1_validator_refine] Invalid repaired outline — keeping original"
                )
            return repaired
        except json.JSONDecodeError as exc:
            logger.warning(
                "[s1_validator_refine] JSON parse error — keeping original outline: %s",
                exc,
            )
            return None
        except Exception:
            logger.exception("[s1_validator_refine] LLM call failed — keeping original outline")
            return None

    def is_refinable(self, issue: ValidationIssue) -> bool:
        """Expose issue filtering for backward-compatible module helpers."""
        return self._issue_filter.is_refinable(issue)

    def issues_from_report(self, report: S1ValidationReport) -> list[S1RefinementIssue]:
        """Expose report conversion for backward-compatible module helpers."""
        return self._issue_filter.from_report(report)

    def build_user_message(self, input_data: S1RefinementInput) -> str:
        """Expose message formatting for backward-compatible module helpers."""
        return self._message_builder.build(input_data)
