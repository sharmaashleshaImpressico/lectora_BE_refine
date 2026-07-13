"""LLM enrichment: subtopics + LO mapping."""

from __future__ import annotations

import json
import logging
import re

from semantic_kernel import Kernel

from ...config.llm import chat
from ...constants.prompts import ENRICH_SYSTEM
from ...nodes.base_node import BaseA1Node
from ...shared.helpers.section_helpers import SectionHelper
from ...shared.models.state import A1State
from .mechanical_enricher import MechanicalSectionEnricher

logger = logging.getLogger(__name__)


class SectionEnricher(BaseA1Node):
    """Enriches sections with subtopics and learning-objective mappings."""

    def __init__(
        self,
        kernel: Kernel | None = None,
        mechanical_enricher: MechanicalSectionEnricher | None = None,
    ) -> None:
        self._kernel = kernel
        self._mechanical_enricher = mechanical_enricher or MechanicalSectionEnricher()

    def execute(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        learning_objectives = state["a0_data"].get("extracted_inputs", {}).get("learning_objectives", [])

        if state.get("prefer_a0_outline"):
            enrichment = self._mechanical_enricher.build(state["raw_sections"], learning_objectives)
            logger.info(
                "[A1] Generate-TO mode — built mechanical enrichment for %s section(s) "
                "(no LLM; subtopics from A0 outline).",
                len(enrichment),
            )
            return {**state, "enrichment": enrichment, "error": None}

        logger.info("[A1] Enriching sections with AzureOpenAI (subtopics + LO mapping)...")

        try:
            enrichment = self._enrich_with_llm(state, learning_objectives)
            logger.info("[A1] LLM enriched %s sections.", len(enrichment))
            return {**state, "enrichment": enrichment, "error": None}
        except Exception as exc:
            logger.warning("[A1] LLM enrichment failed: %s — continuing without enrichment.", exc)
            return {**state, "enrichment": {}, "error": f"enrich_with_llm failed: {exc}"}

    def _enrich_with_llm(
        self,
        state: A1State,
        learning_objectives: list[str],
    ) -> dict[str, dict]:
        section_input = {}
        for section in state["raw_sections"]:
            if SectionHelper.is_reserved_section(section["heading"]):
                continue
            preview = " ".join(section["paragraphs"][:2])[:250] if section["paragraphs"] else ""
            section_input[section["heading"]] = {"preview": preview}

        payload: dict = {
            "learning_objectives": {str(index): lo for index, lo in enumerate(learning_objectives)},
            "sections": section_input,
        }
        feedback = state.get("feedback")
        if feedback:
            validator_feedback = feedback.get("validator_feedback")
            if validator_feedback:
                payload["validator_feedback"] = validator_feedback
            attempt = feedback.get("attempt")
            if attempt is not None:
                payload["retry_attempt"] = attempt

        if self._kernel is None:
            raise RuntimeError("SectionEnricher requires a Kernel for LLM enrichment.")

        raw = chat(self._kernel, ENRICH_SYSTEM, json.dumps(payload, ensure_ascii=False))
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)


def enrich_with_llm(state: A1State) -> A1State:
    return SectionEnricher().execute(state)
