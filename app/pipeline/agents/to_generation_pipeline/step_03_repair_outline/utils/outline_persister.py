"""Persist a refined TO outline back to shared state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lectora_backend.pipeline.agent.to_generation_pipeline.step_01_parse_and_generate_outline.finalize_output.utils.outline_metrics import (
    enrich_outline_metrics,
)
from lectora_backend.pipeline.agent.to_generation_pipeline.step_03_repair_outline.constants.config import (
    DEFAULT_DIFFICULTY,
)
from lectora_backend.pipeline.agent.to_generation_pipeline.step_03_repair_outline.utils.section1 import (
    Section1LearningObjectiveNormalizer,
)
from lectora_backend.pipeline.shared_utils.interactive_elements import (
    strip_knowledge_checks_from_outline,
)
from lectora_backend.pipeline.shared_utils.outline_cleanup import (
    strip_para_indices_from_outline,
)
from lectora_backend.pipeline.shared_utils.source_documents import (
    assign_source_documents_to_outline,
)


class OutlinePersister:
    """Writes a repaired outline to shared_state and the llm_to_outline sidecar."""

    def __init__(
        self,
        *,
        section1_normalizer: Section1LearningObjectiveNormalizer | None = None,
    ) -> None:
        self._section1_normalizer = section1_normalizer or Section1LearningObjectiveNormalizer()

    def persist(
        self,
        shared_state_path: str,
        refined_outline: dict[str, Any],
        *,
        refinement_issues: list[Any] | None = None,
    ) -> None:
        state_path = Path(shared_state_path).expanduser().resolve()
        state = self._load_json(state_path)

        difficulty = self._resolve_difficulty(state)
        normalized_outline = self._section1_normalizer.normalize(
            refined_outline,
            issues=refinement_issues,
        )
        enriched_outline = self._enrich_outline(normalized_outline, difficulty)
        heading_tree = (state.get("extracted_inputs") or {}).get("heading_tree") or []
        enriched_outline, _ = assign_source_documents_to_outline(
            enriched_outline,
            heading_tree,
        )
        word_count = self._extract_word_count(enriched_outline)

        state["llm_to_outline_classification"] = enriched_outline
        extracted = state.get("extracted_inputs") or {}
        extracted["to_outline_total_word_count"] = word_count
        state["extracted_inputs"] = extracted

        self._write_json(state_path, state)
        self._update_sidecar(state_path, enriched_outline, word_count)

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def _resolve_difficulty(state: dict[str, Any]) -> str:
        return (
            (state.get("course_config") or {}).get("difficulty_level")
            or state.get("course_difficulty")
            or DEFAULT_DIFFICULTY
        )

    @staticmethod
    def _enrich_outline(refined_outline: dict[str, Any], difficulty: str) -> dict[str, Any]:
        payload = {"llm_to_outline": refined_outline}
        enriched_payload, _ = enrich_outline_metrics(payload, difficulty=str(difficulty))
        return enriched_payload.get("llm_to_outline") or refined_outline

    @staticmethod
    def _extract_word_count(outline: dict[str, Any]) -> int:
        totals = outline.get("totals") or {}
        try:
            return int(totals.get("word_count") or 0)
        except (TypeError, ValueError):
            return 0

    def _update_sidecar(
        self,
        state_path: Path,
        outline: dict[str, Any],
        word_count: int,
    ) -> None:
        llm_outline_path = state_path.parent / "llm_to_outline.json"
        if not llm_outline_path.is_file():
            return

        sidecar = self._load_json(llm_outline_path)
        outline_payload = sidecar.get("llm_to_outline") or outline
        state = self._load_json(state_path)
        stripped_outline, _ = strip_knowledge_checks_from_outline(dict(outline_payload))
        stripped_outline, _ = strip_para_indices_from_outline(stripped_outline)
        heading_tree = ((state.get("extracted_inputs") or {}).get("heading_tree") or [])
        stripped_outline, _ = assign_source_documents_to_outline(
            stripped_outline,
            heading_tree,
        )
        sidecar["llm_to_outline"] = stripped_outline
        sidecar["to_outline_total_word_count"] = word_count
        self._write_json(llm_outline_path, sidecar)
