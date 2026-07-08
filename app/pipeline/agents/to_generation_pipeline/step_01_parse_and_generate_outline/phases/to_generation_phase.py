from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..generate_outline.utils.to_processor import (
    classify_to_outline_with_llm,
    generate_to_with_llm,
)
from ..finalize_output.utils.normalize_llm_outline_schema import normalize_llm_to_outline_schema
from ..shared.constants.pipeline_config import PDF_MIXED_OUTLINE_PROMPT_LIMIT
from ..shared.constants.rule_families import DEFAULT_RULE_FAMILY, RuleFamilyResolver
from ..shared.helpers.document_titles import DocumentTitleCollector
from ..shared.helpers.toc_budget import TocWordBudgetCalculator
from lectora_backend.pipeline.shared_llm_config.tracer import submit_with_trace_context
from lectora_backend.pipeline.shared_utils.learning_objectives import (
    normalize_learning_objectives,
)

from .base_phase import BasePipelinePhase
from .classification_phase import ClassificationPhaseResult
from .parse_phase import ParsePhaseResult

if TYPE_CHECKING:
    from .synthesizer import A0RequestSynthesizer

logger = logging.getLogger(__name__)


@dataclass
class ToGenerationPhaseResult:
    llm_result: dict[str, Any]
    llm_to_outline_result: dict[str, Any]
    learning_objectives: list[str]
    paragraphs_by_source: dict[str, int]


class TOGenerationPhase(BasePipelinePhase):
    """TO generation — loads a pre-built JSON, parses an uploaded TO, or generates from source."""

    def __init__(
        self,
        synthesizer: A0RequestSynthesizer,
        parsed: ParsePhaseResult,
        classification: ClassificationPhaseResult,
        paragraphs_by_source: dict[str, int],
    ) -> None:
        super().__init__(synthesizer)
        self._parsed = parsed
        self._classification = classification
        self._paragraphs_by_source = paragraphs_by_source

    def execute(self) -> ToGenerationPhaseResult:
        synth = self._synth
        parsed = self._parsed
        self._check_cancelled()
        started_at = time.perf_counter()
        self._emit_step("Running TO generation…")
        logger.info("[A0] Starting TO generation (rule family from FE, no LLM classification)...")

        to_is_pregenerated_json = self._is_pregenerated_json()

        with ThreadPoolExecutor(max_workers=1) as pool:
            if to_is_pregenerated_json:
                logger.info(
                    "[TO MODE] Existing TO detected — loading pre-generated JSON from disk."
                )
                to_future = submit_with_trace_context(pool, self._load_pregenerated_to)
            elif synth.to_outline_doc_path:
                logger.info(
                    "[TO MODE] Existing TO detected — sending TO document to LLM for parsing."
                )
                print(
                    "[TO-DEBUG] TO mode: PARSE uploaded TO via classify_to_outline_with_llm",
                    flush=True,
                )
                to_future = submit_with_trace_context(
                    pool,
                    classify_to_outline_with_llm,
                    parsed.to_outline_content,
                    validation_hints=synth.validation_hints,
                )
            else:
                to_future = submit_with_trace_context(pool, self._generate_to_from_structured)

            llm_to_outline_result = to_future.result()

        llm_to_outline_result = normalize_llm_to_outline_schema(llm_to_outline_result)

        llm_result = self._build_rule_family_result()
        self._check_cancelled()
        logger.info(
            "[A0] TO generation finished in %.1fs",
            time.perf_counter() - started_at,
        )

        llm_to_outline_result = self._tag_and_map_result(
            llm_to_outline_result, to_is_pregenerated_json
        )
        learning_objectives = self._resolve_learning_objectives(llm_to_outline_result)

        return ToGenerationPhaseResult(
            llm_result=llm_result,
            llm_to_outline_result=llm_to_outline_result,
            learning_objectives=learning_objectives,
            paragraphs_by_source=self._paragraphs_by_source,
        )

    def _is_pregenerated_json(self) -> bool:
        path = self._synth.to_outline_doc_path
        return path is not None and path.lower().endswith(".json")

    def _load_pregenerated_to(self) -> dict[str, Any]:
        with open(self._synth.to_outline_doc_path, encoding="utf-8") as file_handle:  # type: ignore[arg-type]
            payload = json.load(file_handle)
        raw = payload.get("llm_to_outline") or payload
        return normalize_llm_to_outline_schema(raw, require_sections=True)

    def _generate_to_from_structured(self) -> dict[str, Any]:
        synth = self._synth
        parsed = self._parsed
        classification = self._classification

        title = (synth.wizard_course_title or "").strip() or classification.title
        objectives = list(synth.wizard_learning_objectives or []) or list(
            parsed.learning_objectives or []
        )
        pdf_toc_outline, pdf_outline_source_count = self._build_pdf_mixed_outline()
        toc_section_contents = self._extract_toc_section_contents()

        self._check_cancelled()
        fmt = "FORMAT A (TOC hierarchy)" if toc_section_contents else "FORMAT B (headings)"
        print(
            f"\n[TO-DEBUG] TO mode: GENERATE from source | {fmt} | "
            f"toc_sections={len(toc_section_contents or [])} | "
            f"headings={len(parsed.heading_tree)} | "
            f"pdf_outline_source={pdf_outline_source_count or 0}",
            flush=True,
        )
        return generate_to_with_llm(
            title,
            objectives,
            heading_tree=parsed.heading_tree,
            pdf_toc_outline=pdf_toc_outline,
            toc_section_contents=toc_section_contents,
            course_difficulty=synth.difficulty_level,
            course_type_hint=synth.course_type_hint,
            duration_hours=synth.duration_hours,
            calculated_word_count=synth.calculated_word_count,
            audience=synth.audience,
            course_description=synth.course_description,
            custom_system_prompt=synth.custom_to_prompt,
            validation_hints=synth.validation_hints,
            all_doc_titles=self._collect_doc_titles(),
            use_static_prompt=synth.use_static_prompt,
            locked_course_title=synth.wizard_course_title,
            locked_learning_objectives=synth.wizard_learning_objectives,
            preferred_section_count=synth.preferred_chapters,
            wizard=synth.wizard_prompt_context,
            pdf_outline_source_count=pdf_outline_source_count,
        )

    def _build_pdf_mixed_outline(self) -> tuple[str | None, int | None]:
        parsed = self._parsed
        if not (parsed.pdf_parser and parsed.parser):
            return None, None

        pdf_entries = parsed.pdf_parser.extract_toc_entries(include_heading_fallback=True)
        if not pdf_entries:
            return None, None

        pdf_outline_source_count = len(pdf_entries)
        outline_lines = ["## PDF SOURCE OUTLINE (bookmarks — structure from PDF)"]
        for entry in pdf_entries[:PDF_MIXED_OUTLINE_PROMPT_LIMIT]:
            page = f" p{entry.page}" if entry.page else ""
            indent = "  " * max(0, entry.level - 1)
            outline_lines.append(f"{indent}[L{entry.level}] {entry.text}{page}")

        if pdf_outline_source_count > PDF_MIXED_OUTLINE_PROMPT_LIMIT:
            logger.warning(
                "[A0] Mixed sources: PDF outline capped %d → %d entries "
                "in user_msg (see [TO-LLM] Structure verified)",
                pdf_outline_source_count,
                PDF_MIXED_OUTLINE_PROMPT_LIMIT,
            )
        logger.info(
            "[A0] Mixed sources: attached PDF bookmark outline "
            "(%d source entries, %d lines in prompt)",
            pdf_outline_source_count,
            len(outline_lines) - 1,
        )
        return "\n".join(outline_lines), pdf_outline_source_count

    def _extract_toc_section_contents(self) -> list[dict[str, Any]] | None:
        parsed = self._parsed
        if parsed.parser:
            docx_toc = parsed.parser.extract_toc_entries()
            if docx_toc:
                toc_budget = TocWordBudgetCalculator.for_entry_count(len(docx_toc))
                toc_section_contents = parsed.parser.extract_toc_section_contents(
                    docx_toc, total_word_budget=toc_budget
                )
                logger.info(
                    "[A0] DOCX TOC: %d entries → FORMAT A "
                    "(TOC hierarchy only; section body not sent to LLM)",
                    len(docx_toc),
                )
                return toc_section_contents
            logger.info(
                "[A0] DOCX: no Word TOC paragraphs (TOC 1/2/3 styles) found "
                "→ FORMAT B (heading_tree + full body)"
            )
            return None

        if parsed.pdf_parser:
            pdf_toc = parsed.pdf_parser.extract_toc_entries(include_heading_fallback=True)
            if pdf_toc:
                toc_budget = TocWordBudgetCalculator.for_entry_count(len(pdf_toc))
                return parsed.pdf_parser.extract_toc_section_contents(
                    pdf_toc, total_word_budget=toc_budget
                )
        return None

    def _collect_doc_titles(self) -> list[str]:
        parsed = self._parsed
        return DocumentTitleCollector(
            self._synth.docx_paths,
            self._synth.pdf_paths,
            has_docx_parser=bool(parsed.parser),
            has_pdf_parser=bool(parsed.pdf_parser),
        ).collect_raw_titles()

    def _build_rule_family_result(self) -> dict:
        family = RuleFamilyResolver.resolve(self._synth.rule_family) or DEFAULT_RULE_FAMILY
        return RuleFamilyResolver.build_classification_result(family, self._synth.audience)

    def _resolve_learning_objectives(self, llm_to_outline_result: dict[str, Any]) -> list[str]:
        parsed = self._parsed
        synth = self._synth
        learning_objectives = list(parsed.learning_objectives)
        if learning_objectives:
            return learning_objectives

        llm_learning_objectives = normalize_learning_objectives(
            (llm_to_outline_result or {}).get("learning_objectives", [])
        )
        if not llm_learning_objectives:
            return learning_objectives

        source_label = "TO document" if synth.to_outline_doc_path else "generated TO"
        logger.info(
            "[A0] Backfilled %s learning objective(s) from %s (none found in study guide).",
            len(llm_learning_objectives),
            source_label,
        )
        return llm_learning_objectives

    def _tag_and_map_result(
        self, llm_to_outline_result: dict[str, Any], to_is_pregenerated_json: bool
    ) -> dict[str, Any]:
        synth = self._synth
        parsed = self._parsed

        if to_is_pregenerated_json:
            logger.info(
                "[TO MODE] Pre-generated TO loaded from disk — no LLM TO generation was performed."
            )
            llm_to_outline_result["_reused_from_preview"] = True
            return llm_to_outline_result

        if synth.to_outline_doc_path:
            return self._map_uploaded_to_sections(llm_to_outline_result)

        return self._map_generated_to_sections(llm_to_outline_result)

    def _map_uploaded_to_sections(self, llm_to_outline_result: dict[str, Any]) -> dict[str, Any]:
        raw_sections = (llm_to_outline_result or {}).get("sections") or []
        logger.info(
            "[TO MODE] Parsed uploaded TO — %d section(s); "
            "paragraph-index mapping skipped (embeddings used downstream).",
            len(raw_sections),
        )
        llm_to_outline_result["_parsed_from_uploaded_to"] = True
        return llm_to_outline_result

    def _map_generated_to_sections(self, llm_to_outline_result: dict[str, Any]) -> dict[str, Any]:
        synth = self._synth
        parsed = self._parsed
        section_count = len((llm_to_outline_result or {}).get("sections") or [])
        logger.info(
            "[STRUCTURED CONTENT MODE] LLM generated %d section(s) from extracted content "
            "(duration=%sh, difficulty=%s, target_words=%d).",
            section_count,
            synth.duration_hours,
            synth.difficulty_level,
            synth.calculated_word_count,
        )
        llm_to_outline_result["_generated_from_source"] = True
        llm_to_outline_result["_dynamic_flow"] = True
        llm_to_outline_result["_duration_hours"] = synth.duration_hours
        llm_to_outline_result["_difficulty_level"] = synth.difficulty_level
        llm_to_outline_result["_calculated_word_count"] = synth.calculated_word_count
        return llm_to_outline_result
