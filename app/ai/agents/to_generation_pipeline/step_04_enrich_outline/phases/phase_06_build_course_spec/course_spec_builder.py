"""Assemble final course_spec from parsed + enriched data."""

from __future__ import annotations

import logging
from typing import Any

from app.ai.rule_pack_config.course_packs import resolve_course_rule_pack
from app.ai.shared_utils.interactive_elements import (
    collect_interactive_elements,
    resolve_section_assets,
)

from ...nodes.base_node import BaseA1Node
from ...shared.helpers.section_helpers import SectionHelper
from ...shared.models.state import A1State
from ...shared.utils.text_utils import TextUtils

logger = logging.getLogger(__name__)


class CourseSpecBuilder(BaseA1Node):
    """Assembles course_spec from raw_sections and enrichment data."""

    def execute(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        logger.info("[A1] Assembling course_spec from parsed + enriched data...")
        enrichment = state.get("enrichment", {})
        sections_out: list[dict[str, Any]] = []
        prefer_a0_outline = bool(state.get("prefer_a0_outline"))

        rule_family = (
            state["a0_data"].get("request_spec", {})
            .get("rule_classification", {})
            .get("family_key")
            or state["a0_data"].get("request_spec", {})
            .get("rule_classification", {})
            .get("family")
        )
        resolved = resolve_course_rule_pack(rule_family=rule_family) if rule_family else None
        rule_pack = resolved[1] if resolved else None
        words_per_minute = TextUtils.wpm_from_rule_pack(rule_pack or {}, default=180)
        logger.info("[A1] Pacing: %s words/min (derived from rule pack)", words_per_minute)

        for section in state["raw_sections"]:
            sections_out.append(
                self._build_section_output(
                    section,
                    enrichment,
                    state,
                    prefer_a0_outline=prefer_a0_outline,
                    words_per_minute=words_per_minute,
                )
            )

        a0_inputs = state["a0_data"].get("extracted_inputs", {})
        course_spec = {
            "run_id": state["run_id"],
            "course_id": a0_inputs.get("course_id"),
            "course_title": a0_inputs.get("title"),
            "extracted_inputs": {
                "title": a0_inputs.get("title"),
                "course_id": a0_inputs.get("course_id"),
                "learning_objectives": a0_inputs.get("learning_objectives", []),
            },
            "sections": sections_out,
        }

        logger.info("[A1] course_spec built: %s sections.", len(sections_out))
        return {**state, "course_spec": course_spec}

    def _build_section_output(
        self,
        section: dict[str, Any],
        enrichment: dict[str, Any],
        state: A1State,
        *,
        prefer_a0_outline: bool,
        words_per_minute: int,
    ) -> dict[str, Any]:
        heading = section["heading"]
        enrich = enrichment.get(heading, {})
        para_start = section["para_start"]
        para_end = max(section["para_end"], para_start)
        level = SectionHelper.normalize_section_level(section["level"])

        mapped_images = [
            image
            for image in state.get("image_map", {}).get(section["id"], [])
            if para_start <= image.get("para_idx", -1) <= para_end
        ]

        if prefer_a0_outline:
            raw_interactive_elements = self._resolve_generate_to_interactive_elements(
                section,
                has_knowledge_check=bool(section.get("has_knowledge_check")),
            )
            section_images = list(mapped_images or [])
            has_knowledge_check_final = "knowledge_check" in raw_interactive_elements
        else:
            raw_interactive_elements, section_images = resolve_section_assets(
                section.get("interactive_elements", []),
                mapped_images,
                has_knowledge_check=bool(section.get("has_knowledge_check")),
            )
            has_knowledge_check_final = "knowledge_check" in raw_interactive_elements

        word_count = section.get("word_count", 0) or 0
        if prefer_a0_outline and section.get("outline_minutes") is not None:
            estimated_minutes = round(float(section["outline_minutes"]), 2)
        else:
            estimated_minutes = (
                round(TextUtils.words_to_minutes(word_count, wpm=words_per_minute), 2)
                if word_count
                else 0.0
            )

        section_out: dict[str, Any] = {
            "id": section["id"],
            "heading": heading,
            "level": level,
            "para_start": para_start,
            "para_end": para_end,
            "word_count": word_count,
            "estimated_duration_minutes": estimated_minutes,
            "interactive_elements": list(raw_interactive_elements),
            "maps_to_objectives": enrich.get("maps_to_objectives", []),
            "images": section_images,
            "image_count": len(section_images),
        }

        if prefer_a0_outline:
            section_out["content"] = section.get("outline_content") or ""
            section_out["subtopics"] = enrich.get("subtopics") or section.get("outline_subtopics") or []
            if section.get("outline_credit_hour") is not None:
                section_out["credit_hour"] = section.get("outline_credit_hour")
            if section.get("outline_minutes") is not None:
                section_out["minutes"] = section.get("outline_minutes")

        return section_out

    @staticmethod
    def _resolve_generate_to_interactive_elements(
        section: dict[str, Any],
        *,
        has_knowledge_check: bool,
    ) -> list[str]:
        resolved = collect_interactive_elements([], initial=section.get("interactive_elements") or [])
        if has_knowledge_check and "knowledge_check" not in resolved:
            resolved.append("knowledge_check")
        return resolved


def build_course_spec(state: A1State) -> A1State:
    return CourseSpecBuilder().execute(state)
