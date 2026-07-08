from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..shared.helpers.text_utils import resolve_value
from ..finalize_output.utils.normalize_to_hierarchy import normalize_to_hierarchy
from ..finalize_output.utils.normalize_llm_outline_schema import normalize_llm_to_outline_schema
from ..finalize_output.utils.outline_metrics import enrich_outline_metrics
from ..finalize_output.utils.title_cleaner import clean_outline_titles
from lectora_backend.pipeline.shared_utils.interactive_elements import (
    strip_knowledge_checks_from_outline,
)
from lectora_backend.pipeline.shared_utils.outline_cleanup import (
    strip_para_indices_from_outline,
)
from lectora_backend.pipeline.shared_utils.source_documents import (
    assign_source_documents_to_outline,
)
from lectora_backend.pipeline.models import (
    A0OutputFiles,
    A0Result,
    AgentOutputSlots,
    CourseMetadata,
    ExtractedInputs,
    LLMClassification,
    ProvenanceEntry,
    RequestSpec,
    RuleClassification,
    SharedState,
)
from lectora_backend.pipeline.rule_pack_config.rule_packs import RULE_PACKS, resolve_rule_pack
from lectora_backend.pipeline.shared_utils.course_id_resolver import (
    derive_course_id_from_title,
    normalize_course_id,
    resolve_course_id,
)
from .classification_phase import ClassificationPhaseResult
from .parse_phase import ParsePhaseResult
from .to_generation_phase import ToGenerationPhaseResult
from lectora_backend.pipeline.shared_utils.learning_objectives import normalize_learning_objectives

if TYPE_CHECKING:
    from .synthesizer import A0RequestSynthesizer

logger = logging.getLogger(__name__)


def _normalize_provenance_source(source: str) -> str:
    """Map internal source labels onto the public ProvenanceSource enum values."""
    if source == "explicitly_provided":
        return "explicitly_provided"
    if source in {"from_generated_to", "inferred_from_document"}:
        return "inferred"
    if source == "derived_from_rule_pack":
        return "derived_from_rule_pack"
    return "unresolved"


class FinalizationPhase:
    """Assembles the A0Result: resolves rule pack, builds specs, persists artifacts."""

    def __init__(
        self,
        synth: A0RequestSynthesizer,
        parsed: ParsePhaseResult,
        classification: ClassificationPhaseResult,
        generation: ToGenerationPhaseResult,
    ) -> None:
        self._synth = synth
        self._parsed = parsed
        self._classification = classification
        self._generation = generation

    def execute(self) -> A0Result:
        rule_family_key, rule_pack = self._resolve_rule_pack()
        request_spec, provenance_log, course_title, learning_objectives = self._build_request_spec(
            rule_pack,
            rule_family_key,
        )
        to_outline_total_word_count = self._extract_to_word_count()
        shared_state = self._build_shared_state(
            request_spec, provenance_log, course_title, learning_objectives, to_outline_total_word_count
        )
        return self._persist_artifacts(
            request_spec, provenance_log, shared_state, to_outline_total_word_count
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    def _resolve_rule_pack(self) -> tuple[str, dict]:
        rule_family_key = self._generation.llm_result["rule_family"]
        if rule_family_key not in RULE_PACKS:
            matched = next(
                (key for key in RULE_PACKS if key in rule_family_key or rule_family_key in key),
                None,
            )
            if matched:
                logger.warning(
                    "[A0] Unknown rule_family %r — falling back to matched key %r",
                    rule_family_key,
                    matched,
                )
                rule_family_key = matched
            else:
                logger.error(
                    "[A0] Unknown rule_family %r (valid: %s) — defaulting to 'insurance_ce'",
                    rule_family_key,
                    list(RULE_PACKS.keys()),
                )
                rule_family_key = "insurance_ce"
        difficulty = (
            getattr(self._synth, "difficulty_level", None)
            or getattr(self._synth, "course_difficulty", None)
        )
        rule_pack = resolve_rule_pack(rule_family_key, difficulty) or RULE_PACKS[rule_family_key]
        return rule_family_key, rule_pack

    def _build_request_spec(
        self, rule_pack: dict, rule_family_key: str
    ) -> tuple[RequestSpec, dict[str, ProvenanceEntry], str, list[str]]:
        synth = self._synth
        parsed = self._parsed
        generation = self._generation
        llm_result = generation.llm_result
        llm_to_outline_result = generation.llm_to_outline_result

        family_name = rule_pack["family"]
        course_title, title_source = self._resolve_course_title(llm_to_outline_result)
        learning_objectives = self._resolve_learning_objectives(llm_to_outline_result)
        course_id = self._resolve_course_id(llm_to_outline_result)
        explicit_metadata = self._build_explicit_metadata()

        if title_source == "explicitly_provided":
            logger.info("[A0] Using FE wizard course title for request_spec: %r", course_title)
        elif title_source == "from_generated_to":
            logger.info("[A0] Using generated TO course title for request_spec: %r", course_title)
        if explicit_metadata.get("audience"):
            logger.info("[A0] Using FE audience for request_spec metadata.")

        inferred = {
            "topic": llm_result.get("topic"),
            "audience": llm_result.get("audience"),
            "course_type": llm_result.get("course_type"),
            "category": llm_result.get("category"),
        }

        resolve_keys = ["words_per_credit_hour", "topic", "audience", "course_type", "category"]
        resolved: dict[str, Any] = {}
        provenance_log: dict[str, ProvenanceEntry] = {}
        for key in resolve_keys:
            rule_defaults = rule_pack.get("content_rules", {}) if key == "words_per_credit_hour" else {}
            value, source = resolve_value(key, explicit_metadata, rule_defaults, inferred)
            resolved[key] = value
            provenance_log[key] = ProvenanceEntry(value=value, source=source)

        provenance_log["title"] = ProvenanceEntry(
            value=course_title,
            source=_normalize_provenance_source(title_source),
        )

        request_spec = RequestSpec(
            run_id=synth.run_id,
            timestamp=datetime.now(timezone.utc),
            course_metadata=CourseMetadata(
                title=course_title,
                course_id=course_id,
                audience=resolved["audience"],
                course_type=resolved["course_type"],
                category=resolved["category"],
                topic=resolved["topic"],
            ),
            rule_classification=RuleClassification(
                family=family_name,
                family_key=rule_family_key,
                rule_pack_id=rule_pack["id"],
                rule_pack_version=rule_pack["version"],
                llm_confidence=llm_result.get("confidence"),
                llm_reasoning=llm_result.get("reasoning"),
            ),
        )
        return request_spec, provenance_log, course_title, learning_objectives

    def _extract_to_word_count(self) -> int:
        raw_totals = (self._generation.llm_to_outline_result or {}).get("totals") or {}
        try:
            count = int(raw_totals.get("word_count") or 0)
        except (TypeError, ValueError):
            count = 0
        logger.info("[A0] TO outline total word count (from LLM): %s", count)
        return count

    def _build_shared_state(
        self,
        request_spec: RequestSpec,
        provenance_log: dict[str, ProvenanceEntry],
        course_title: str,
        learning_objectives: list[str],
        to_outline_total_word_count: int,
    ) -> SharedState:
        synth = self._synth
        parsed = self._parsed
        generation = self._generation
        llm_to_outline_result = dict(generation.llm_to_outline_result or {})
        course_id = self._resolve_course_id(llm_to_outline_result)
        if course_id and not normalize_course_id(llm_to_outline_result.get("course_id")):
            llm_to_outline_result["course_id"] = course_id
            generation.llm_to_outline_result = llm_to_outline_result

        llm_classification = LLMClassification.model_validate(generation.llm_result)
        heading_map_serialized: list[list] = [list(entry) for entry in parsed.heading_map]

        return SharedState(
            run_id=synth.run_id,
            status="a0_completed",
            request_spec=request_spec,
            provenance_log=provenance_log,
            source_document=", ".join(
                os.path.basename(path) for path in [*synth.docx_paths, *synth.pdf_paths]
            ),
            extracted_inputs=ExtractedInputs(
                title=course_title,
                course_id=self._resolve_course_id(generation.llm_to_outline_result),
                learning_objectives=learning_objectives,
                content_sample=parsed.content_sample,
                total_doc_word_count=parsed.total_doc_word_count,
                to_outline_total_word_count=to_outline_total_word_count,
                heading_tree=parsed.heading_tree,
                heading_map=heading_map_serialized,
                toc_entries=[],
                toc_section_contents=[],
                total_paragraphs=parsed.total_paragraphs,
                paragraphs_by_source=generation.paragraphs_by_source,
            ),
            images=parsed.images,
            llm_classification=llm_classification,
            llm_to_outline_classification=generation.llm_to_outline_result,
            agent_outputs=AgentOutputSlots(),
        )

    def _persist_artifacts(
        self,
        request_spec: RequestSpec,
        provenance_log: dict[str, ProvenanceEntry],
        shared_state: SharedState,
        to_outline_total_word_count: int,
    ) -> A0Result:
        synth = self._synth
        parsed = self._parsed
        generation = self._generation
        llm_to_outline_result = generation.llm_to_outline_result

        synth._emit_step("Persisting A0 outputs and generated TO artifacts…")
        spec_path = parsed.doc_dir / "request_spec.json"
        prov_path = parsed.doc_dir / "provenance_log.json"
        state_path = parsed.doc_dir / "shared_state.json"
        llm_outline_path = parsed.doc_dir / "llm_to_outline.json"

        prov_serializable = {key: value.model_dump(mode="json") for key, value in provenance_log.items()}
        llm_to_outline_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": synth.run_id,
            "course_id": self._resolve_course_id(llm_to_outline_result),
            "llm_to_outline": llm_to_outline_result,
        }

        outline_inner = llm_to_outline_payload.get("llm_to_outline") or {}
        outline_inner = normalize_llm_to_outline_schema(outline_inner, require_sections=True)
        llm_to_outline_payload["llm_to_outline"] = outline_inner
        _, cleaned_titles_count = clean_outline_titles(outline_inner)
        if cleaned_titles_count:
            logger.info(
                "[A0] title_cleaner removed page references from %s title(s).",
                cleaned_titles_count,
            )

        outline_inner = llm_to_outline_payload.get("llm_to_outline") or {}
        normalized_inner, hierarchy_modified = normalize_to_hierarchy(outline_inner)
        if hierarchy_modified:
            logger.warning(
                "[A0] normalize_to_hierarchy: course topics were nested under a "
                "reserved section (Overview/LO) — promoted to top-level sections "
                "and renumbered."
            )
            llm_to_outline_payload["llm_to_outline"] = normalized_inner

        enriched_payload, was_modified = enrich_outline_metrics(
            llm_to_outline_payload,
            difficulty=synth.difficulty_level if synth._generate_to_from_source else synth.course_difficulty,
        )
        if was_modified:
            logger.info("[A0] outline_metrics enricher filled in missing pacing fields.")
            llm_to_outline_payload = enriched_payload

        llm_to_outline_payload["total_doc_word_count"] = parsed.total_doc_word_count
        llm_to_outline_payload["to_outline_total_word_count"] = to_outline_total_word_count

        outline_inner = llm_to_outline_payload.get("llm_to_outline") or {}
        stripped_outline, kc_sections_stripped = strip_knowledge_checks_from_outline(outline_inner)
        if kc_sections_stripped:
            logger.info(
                "[A0] Removed knowledge_check from interactive_elements on %s section(s) — "
                "KC Planner owns placement.",
                kc_sections_stripped,
            )
            outline_inner = stripped_outline

        outline_inner, para_sections_stripped = strip_para_indices_from_outline(outline_inner)
        if para_sections_stripped:
            logger.info(
                "[A0] Removed deprecated para_idx fields from %s section(s) — "
                "Section Mapper uses embeddings for source mapping.",
                para_sections_stripped,
            )

        outline_inner, source_docs_assigned = assign_source_documents_to_outline(
            outline_inner,
            self._parsed.heading_tree,
        )
        if source_docs_assigned:
            logger.info(
                "[A0] Assigned source_documents on %s section(s) via heading_tree fuzzy match.",
                source_docs_assigned,
            )

        llm_to_outline_payload["llm_to_outline"] = outline_inner
        shared_state.llm_to_outline_classification = outline_inner

        with open(llm_outline_path, "w", encoding="utf-8") as outline_handle:
            json.dump(llm_to_outline_payload, outline_handle, indent=2, ensure_ascii=False, default=str)

        for path, data in [
            (spec_path, request_spec.model_dump(mode="json")),
            (prov_path, prov_serializable),
            (state_path, shared_state.model_dump(mode="json")),
        ]:
            with open(path, "w", encoding="utf-8") as file_handle:
                json.dump(data, file_handle, indent=2, ensure_ascii=False, default=str)

        logger.info("[A0] llm_to_outline written -> %s", llm_outline_path)
        final_llm_to_outline = llm_to_outline_payload.get("llm_to_outline") or llm_to_outline_result

        return A0Result(
            request_spec=request_spec,
            provenance_log=provenance_log,
            shared_state_path=str(state_path),
            output_files=A0OutputFiles(
                request_spec=str(spec_path),
                provenance_log=str(prov_path),
                shared_state=str(state_path),
                llm_to_outline=str(llm_outline_path),
            ),
            llm_to_outline=final_llm_to_outline,
        )

    def _resolve_course_title(self, llm_to_outline_result: dict[str, Any] | None) -> tuple[str, str]:
        """Prefer FE wizard title, then generated TO title, then document title."""
        synth = self._synth
        wizard_title = (getattr(synth, "wizard_course_title", None) or "").strip() or None
        if wizard_title:
            return wizard_title, "explicitly_provided"

        outline_title = ((llm_to_outline_result or {}).get("course_title") or "").strip() or None
        if outline_title:
            return outline_title, "from_generated_to"

        return self._classification.title, "inferred_from_document"

    def _resolve_learning_objectives(self, llm_to_outline_result: dict[str, Any] | None) -> list[str]:
        """Prefer FE wizard LOs, then TO output, then parsed document LOs."""
        synth = self._synth
        parsed = self._parsed
        generation = self._generation

        wizard_los = normalize_learning_objectives(
            getattr(synth, "wizard_learning_objectives", None) or []
        )
        if wizard_los:
            return wizard_los

        outline_los = normalize_learning_objectives(
            (llm_to_outline_result or {}).get("learning_objectives") or []
        )
        if outline_los:
            return outline_los

        if generation.learning_objectives:
            return list(generation.learning_objectives)

        return normalize_learning_objectives(parsed.learning_objectives or [])

    def _resolve_course_id(self, llm_to_outline_result: dict[str, Any] | None) -> str | None:
        """Prefer document-extracted ID, then TO outline course_id, then title slug."""
        parsed = self._parsed
        outline_id = (llm_to_outline_result or {}).get("course_id")
        explicit = resolve_course_id(parsed.course_id, outline_id)
        if explicit:
            return explicit
        title, _ = self._resolve_course_title(llm_to_outline_result)
        return derive_course_id_from_title(title)

    def _build_explicit_metadata(self) -> dict[str, Any]:
        """FE-provided metadata that should override inferred/document values."""
        synth = self._synth
        explicit: dict[str, Any] = {}
        audience = (getattr(synth, "audience", None) or "").strip() or None
        if audience:
            explicit["audience"] = audience
        course_type = (getattr(synth, "course_type_hint", None) or "").strip() or None
        if course_type:
            explicit["course_type"] = course_type
        return explicit
