"""
TO-processing utilities for A0 — timed-outline generation and mapping step.

Contains: TOProcessor class (generate_from_source, classify_uploaded,
map_sections_to_source) plus backward-compatible module-level wrappers.

Classification for rule family is provided by the frontend; TO LLM utilities
live in this module.

Azure OpenAI client/model settings live in config/llm.py.
This module only contains business logic.
"""

import difflib
import json
import logging
import re

import json_repair

from ...config.llm import chat_for_to
from ...shared.constants.difficulty import (
    DEFAULT_TO_DURATION_HOURS,
    compute_calculated_word_count,
)
from ...shared.helpers.text_utils import _strip_fences
from lectora_backend.pipeline.shared_llm_config.model_registry import get_deployment
from ..constants.prompts import (
    CLASSIFICATIONTO_OUTLINE_PROMPT,
    GENERATE_TO_PROMPT,
    build_dynamic_to_prompt,
)

logger = logging.getLogger(__name__)

_TO_DEBUG_PREVIEW_CHARS = 12_000
_STRUCTURE_LINE_RE = re.compile(r"^\s*\[L\d+\]")

# Moved out of map_to_to_source_indices — compiled once at module level.
_NUMBER_PREFIX_RE = re.compile(r"^\d+(\.\d+)*[\s.\-:]*")


# ---------------------------------------------------------------------------
# Module-level diagnostic helpers — no class affiliation
# ---------------------------------------------------------------------------

def _debug_print_to_section(title: str, body: str, *, preview_chars: int | None = _TO_DEBUG_PREVIEW_CHARS) -> None:
    """stdout debug dump for TO LLM payloads."""
    print("\n" + "=" * 80, flush=True)
    print(f"[TO-DEBUG] {title}", flush=True)
    print("=" * 80, flush=True)
    total = len(body)
    if preview_chars is not None and total > preview_chars:
        print(body[:preview_chars], flush=True)
        print(
            f"\n[TO-DEBUG] ... truncated preview ({preview_chars:,} / {total:,} chars) ...",
            flush=True,
        )
    else:
        print(body, flush=True)
    print("=" * 80 + "\n", flush=True)


def _count_prompt_structure_lines(user_msg: str) -> dict[str, int]:
    """Count [L<n>] structure lines per section block in the TO user message."""
    counts = {"toc_lines": 0, "heading_lines": 0, "pdf_outline_lines": 0}
    section: str | None = None
    for line in user_msg.splitlines():
        if line.startswith("## TOC Hierarchy"):
            section = "toc"
            continue
        if line.startswith("## DOCUMENT HEADING STRUCTURE"):
            section = "heading"
            continue
        if line.startswith("## PDF SOURCE OUTLINE"):
            section = "pdf"
            continue
        if line.startswith("## "):
            section = None
            continue
        if section and _STRUCTURE_LINE_RE.match(line):
            if section == "toc":
                counts["toc_lines"] += 1
            elif section == "heading":
                counts["heading_lines"] += 1
            elif section == "pdf":
                counts["pdf_outline_lines"] += 1
    return counts


def _log_structure_prompt_verification(
    *,
    user_msg: str,
    toc_source_count: int,
    heading_source_count: int,
    pdf_outline_source_count: int | None,
    uses_toc_format: bool,
) -> dict[str, int]:
    """Log source vs prompt structure counts; warn when upstream caps dropped entries."""
    counts = _count_prompt_structure_lines(user_msg)
    if uses_toc_format:
        logger.info(
            "[TO-LLM]  Structure verified  : toc %d/%d in user_msg "
            "(headings omitted — FORMAT A)",
            counts["toc_lines"],
            toc_source_count,
        )
        if counts["toc_lines"] != toc_source_count:
            logger.warning(
                "[TO-LLM]  TOC structure mismatch: source=%d prompt=%d",
                toc_source_count,
                counts["toc_lines"],
            )
    else:
        logger.info(
            "[TO-LLM]  Structure verified  : headings %d/%d in user_msg",
            counts["heading_lines"],
            heading_source_count,
        )
        if counts["heading_lines"] != heading_source_count:
            logger.warning(
                "[TO-LLM]  Heading structure mismatch: source=%d prompt=%d",
                heading_source_count,
                counts["heading_lines"],
            )
    if pdf_outline_source_count is not None:
        logger.info(
            "[TO-LLM]  PDF outline in prompt : %d/%d entries",
            counts["pdf_outline_lines"],
            pdf_outline_source_count,
        )
        if counts["pdf_outline_lines"] < pdf_outline_source_count:
            logger.warning(
                "[TO-LLM]  PDF outline truncated upstream: source=%d prompt=%d",
                pdf_outline_source_count,
                counts["pdf_outline_lines"],
            )
    return counts


# ---------------------------------------------------------------------------
# TOProcessor — LLM-based TO generation, classification, and section mapping
# ---------------------------------------------------------------------------

class TOProcessor:
    """Generates, parses, and maps timed-outlines via AzureOpenAI.

    All methods are static — no mutable state, safe to call from any thread.

    Three main operations:
      - ``generate_from_source``: build a TO from extracted source structure.
      - ``classify_uploaded``: parse raw TO content into the standard outline format.
      - ``map_sections_to_source``: add para_idx_start/end to a parsed TO.
    """

    @staticmethod
    def generate_from_source(
        title: str,
        objectives: list[str],
        *,
        heading_tree: list[dict] | None = None,
        toc_section_contents: list[dict] | None = None,
        pdf_toc_outline: str | None = None,
        course_difficulty: str = "intermediate",
        course_type_hint: str | None = None,
        duration_hours: int | float | None = None,
        calculated_word_count: int | None = None,
        audience: str | None = None,
        course_description: str | None = None,
        custom_system_prompt: str | None = None,
        validation_hints: str | None = None,
        all_doc_titles: list[str] | None = None,
        use_static_prompt: bool = False,
        locked_course_title: str | None = None,
        locked_learning_objectives: list[str] | None = None,
        preferred_section_count: int | None = None,
        wizard: "ToWizardPromptContext | None" = None,
        pdf_outline_source_count: int | None = None,
    ) -> dict:
        """Generate a structured Timed Outline from extracted source document content.

        Used when no TO document is provided (Scenario 2). Sends structural data
        only to the LLM — no paragraph body text is included in either format.

        For DOCX with Word TOC (TOC 1/2/3 styles): passes toc_section_contents (FORMAT A —
          TOC hierarchy only; per-section body text not sent).
        For DOCX without TOC: passes heading_tree only (FORMAT B — no indexed body text).
        For PDF sources with an embedded TOC/bookmarks: passes toc_section_contents (FORMAT A).
        For PDF sources without a TOC: falls back to FORMAT B (heading structure only).

        System prompt selection (``use_static_prompt`` only):
          - ``False`` (default FE generate-from-source) → ``build_dynamic_to_prompt``
          - ``True`` (outline DOCX/PDF upload) → ``GENERATE_TO_PROMPT``

        ``custom_system_prompt`` is appended after the base prompt as freeform author notes.
        """
        # Always build the base prompt first (dynamic or static) so the JSON format
        # instructions and schema are always present.  custom_system_prompt is appended
        # as supplemental guidance — it must never replace the format contract because
        # the LLM would lose the required JSON schema and return a free-form response.
        if not use_static_prompt:
            effective_duration = (
                float(duration_hours)
                if duration_hours is not None
                else float(DEFAULT_TO_DURATION_HOURS)
            )
            effective_word_count = (
                int(calculated_word_count)
                if calculated_word_count is not None
                else compute_calculated_word_count(effective_duration, course_difficulty)
            )
            system_prompt = build_dynamic_to_prompt(
                duration_hours=effective_duration,
                difficulty_level=course_difficulty,
                calculated_word_count=effective_word_count,
                audience=audience,
                course_description=course_description,
                locked_course_title=locked_course_title,
                locked_learning_objectives=locked_learning_objectives,
                preferred_section_count=preferred_section_count,
                wizard=wizard,
            )
            prompt_source = (
                f"dynamic (duration={effective_duration}h, words={effective_word_count:,}, "
                f"difficulty={course_difficulty}, audience={'set' if audience else 'none'}, "
                f"description={'set' if course_description else 'none'})"
            )
        else:
            system_prompt = GENERATE_TO_PROMPT
            prompt_source = "static (GENERATE_TO_PROMPT)"

        if custom_system_prompt and custom_system_prompt.strip():
            # Append user-supplied hints after the base prompt so the JSON schema
            # constraints are preserved and the hints act as additional guidance only.
            system_prompt = (
                system_prompt
                + "\n\n"
                + "═══════════════════════════════════════════════════════════\n"
                + "ADDITIONAL AUTHOR NOTES (freeform)\n"
                + "═══════════════════════════════════════════════════════════\n"
                + custom_system_prompt.strip()
            )
            prompt_source += " + custom hints"

        fmt = "A (TOC hierarchy only)" if toc_section_contents else "B (heading structure only)"

        logger.info("[TO-LLM] ── INPUT SUMMARY ──────────────────────────────────────────")
        logger.info("[TO-LLM]  Course title      : %s", locked_course_title or title)
        logger.info("[TO-LLM]  Difficulty         : %s", course_difficulty)
        logger.info("[TO-LLM]  Duration           : %s h", duration_hours)
        logger.info("[TO-LLM]  Target word count  : %s", f"{calculated_word_count:,}" if calculated_word_count else "—")
        logger.info("[TO-LLM]  System prompt      : %s", prompt_source)
        logger.info("[TO-LLM]  Content format     : %s", fmt)
        logger.info("[TO-LLM]  Heading entries    : %d", len(heading_tree or []))
        logger.info("[TO-LLM]  TOC sections       : %d (structure only — no body text)", len(toc_section_contents or []))
        logger.info("[TO-LLM] ─────────────────────────────────────────────────────────────")

        user_objectives = objectives
        if not use_static_prompt and locked_learning_objectives:
            user_objectives = []

        user_msg = TOProcessor._build_user_message(
            title=locked_course_title or title,
            objectives=user_objectives,
            toc_section_contents=toc_section_contents,
            heading_tree=heading_tree,
            pdf_toc_outline=pdf_toc_outline,
            course_difficulty=course_difficulty,
            course_type_hint=course_type_hint if use_static_prompt else None,
            calculated_word_count=calculated_word_count,
            audience=audience if use_static_prompt else None,
            validation_hints=validation_hints,
            all_doc_titles=all_doc_titles,
            metadata_in_system=not use_static_prompt,
        )

        user_msg_words = len(user_msg.split())
        est_tokens = int(user_msg_words * 1.35)
        structure_counts = _log_structure_prompt_verification(
            user_msg=user_msg,
            toc_source_count=len(toc_section_contents or []),
            heading_source_count=len(heading_tree or []),
            pdf_outline_source_count=pdf_outline_source_count,
            uses_toc_format=bool(toc_section_contents),
        )
        logger.info(
            "[TO-LLM]  user_msg size      : %d words (~%d tokens estimated)",
            user_msg_words,
            est_tokens,
        )
        logger.info("[TO-LLM]  Sending request to LLM (model=A0_TO → %s)…", get_deployment("A0_TO"))

        print("\n" + "=" * 80, flush=True)
        print("[TO-DEBUG] generate_to_with_llm — LLM request summary", flush=True)
        print("=" * 80, flush=True)
        print(f"  title              : {title}", flush=True)
        print(f"  difficulty         : {course_difficulty}", flush=True)
        print(f"  duration_hours     : {duration_hours}", flush=True)
        print(f"  target_word_count  : {calculated_word_count}", flush=True)
        print(f"  audience           : {audience or '(none)'}", flush=True)
        print(f"  course_description : {(course_description or '(none)')[:200]}", flush=True)
        print(f"  prompt_source      : {prompt_source}", flush=True)
        print(f"  content_format     : {fmt}", flush=True)
        print(f"  heading_entries    : {len(heading_tree or [])}", flush=True)
        print(f"  toc_sections       : {len(toc_section_contents or [])} (structure only)", flush=True)
        print(f"  all_doc_titles     : {all_doc_titles or [title]}", flush=True)
        print(f"  learning_objectives: {len(objectives)}", flush=True)
        for idx, obj in enumerate(objectives[:10], start=1):
            print(f"    {idx}. {obj}", flush=True)
        if len(objectives) > 10:
            print(f"    ... +{len(objectives) - 10} more", flush=True)
        print(f"  system_prompt_chars: {len(system_prompt):,}", flush=True)
        print(f"  user_msg_chars     : {len(user_msg):,}", flush=True)
        if toc_section_contents:
            print(
                f"  structure_in_prompt: toc {structure_counts['toc_lines']}/"
                f"{len(toc_section_contents)} lines (FORMAT A, no body text)",
                flush=True,
            )
        else:
            print(
                f"  structure_in_prompt: headings {structure_counts['heading_lines']}/"
                f"{len(heading_tree or [])} lines (FORMAT B, no body text)",
                flush=True,
            )
        if pdf_outline_source_count is not None:
            print(
                f"  pdf_outline        : {structure_counts['pdf_outline_lines']}/"
                f"{pdf_outline_source_count} entries in user_msg",
                flush=True,
            )
        print("=" * 80 + "\n", flush=True)
        _debug_print_to_section("generate_to_with_llm — system_prompt (preview)", system_prompt, preview_chars=4_000)
        _debug_print_to_section("generate_to_with_llm — user_msg (LLM payload)", user_msg)

        raw = chat_for_to(system_prompt, user_msg)
        resp_words = len(raw.split()) if raw else 0
        logger.info(
            "[TO-LLM]  LLM response received — %d words. Parsing TO JSON…",
            resp_words,
        )
        return TOProcessor._parse_json(
            raw,
            log_prefix="TO-LLM",
            success_label="TO JSON",
            error_desc="TO generation",
            check_truncation=True,
        )

    @staticmethod
    def classify_uploaded(
        content_sample: str,
        *,
        validation_hints: str | None = None,
    ) -> dict:
        """Parse raw TO content into the structured outline format via AzureOpenAI."""
        user_msg = f"## Content\n{content_sample}"
        if validation_hints:
            user_msg += (
                "\n\n## Prior S1 validation feedback (align outline structure accordingly)\n"
                + validation_hints.strip()
            )

        print("\n" + "=" * 80, flush=True)
        print("[TO-DEBUG] classify_to_outline_with_llm — uploaded TO parse", flush=True)
        print("=" * 80, flush=True)
        print(f"  content_sample_words : {len(content_sample.split()):,}", flush=True)
        print(f"  user_msg_chars       : {len(user_msg):,}", flush=True)
        print(f"  has_validation_hints : {bool(validation_hints)}", flush=True)
        print("=" * 80 + "\n", flush=True)
        _debug_print_to_section("classify_to_outline_with_llm — user_msg", user_msg)

        raw = chat_for_to(CLASSIFICATIONTO_OUTLINE_PROMPT, user_msg)
        logger.info(
            "[TO-CLASSIFY] LLM raw response (first 300 chars): %s",
            raw[:300].replace("\n", " "),
        )
        return TOProcessor._parse_json(
            raw,
            log_prefix="TO-CLASSIFY",
            success_label="timed-outline JSON",
            error_desc="timed-outline classification",
            check_truncation=False,
        )

    @staticmethod
    def map_sections_to_source(
        sections: list[dict],
        heading_map: list[tuple],
        total_paragraphs: int,
        *,
        paragraphs_by_source: dict[str, int] | None = None,
    ) -> list[dict]:
        """Add para_idx_start / para_idx_end to TO sections parsed from a TO document.

        Deprecated: retained for legacy TO-parse paths. Generate-TO flow no longer
        persists paragraph indices; Section Mapper uses embeddings instead.

        Args:
            sections:         List of section dicts from the parsed TO.
            heading_map:      Output of CourseDocParser.get_section_heading_map() —
                              (para_idx, heading_text, heading_level) or with a 4th
                              element: source filename when multiple DOCX files are loaded.
            total_paragraphs: Fallback paragraph count for end-of-doc sections.
            paragraphs_by_source: Optional map of filename -> paragraph count per file.

        Returns:
            Same list with para_idx_start and para_idx_end set on each section dict.
        """
        if not heading_map:
            for section in sections:
                section.setdefault("para_idx_start", None)
                section.setdefault("para_idx_end", None)
            return sections

        heading_para_indices: list[int] = []
        heading_texts: list[str] = []
        heading_sources: list[str | None] = []
        for h in heading_map:
            heading_para_indices.append(h[0])
            heading_texts.append(h[1])
            heading_sources.append(h[3] if len(h) > 3 else None)

        def _clean(title: str) -> str:
            return _NUMBER_PREFIX_RE.sub("", title).lower().strip()

        def _best_match_heading_pos(section_title: str) -> int | None:
            clean = _clean(section_title)
            if not clean:
                return None
            cleaned_headings = [_clean(h) for h in heading_texts]
            matches = difflib.get_close_matches(clean, cleaned_headings, n=1, cutoff=0.4)
            if matches:
                return cleaned_headings.index(matches[0])
            return None

        result: list[dict] = []
        for i, section in enumerate(sections):
            sec = dict(section)
            pos = _best_match_heading_pos(sec.get("title", ""))
            if pos is not None:
                start = heading_para_indices[pos]
                source_file = heading_sources[pos]
                sec["para_idx_start"] = start
                if source_file:
                    sec["source_documents"] = [source_file]
                    sec.pop("source_document", None)
                if i + 1 < len(sections):
                    next_pos = _best_match_heading_pos(sections[i + 1].get("title", ""))
                    next_start = heading_para_indices[next_pos] if next_pos is not None else None
                    sec["para_idx_end"] = (next_start - 1) if (next_start and next_start > start) else None
                else:
                    end_total = total_paragraphs - 1
                    if source_file and paragraphs_by_source:
                        end_total = paragraphs_by_source.get(source_file, total_paragraphs) - 1
                    sec["para_idx_end"] = end_total
            else:
                sec["para_idx_start"] = None
                sec["para_idx_end"] = None
            result.append(sec)

        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(
        raw: str,
        *,
        log_prefix: str = "TO-LLM",
        success_label: str = "TO JSON",
        error_desc: str = "TO generation",
        check_truncation: bool = True,
    ) -> dict:
        """Parse and repair the LLM JSON response for any TO operation.

        Parameterized to serve both ``generate_from_source`` and
        ``classify_uploaded`` with distinct log prefixes and messages.
        """
        cleaned = _strip_fences(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as original_exc:
            hint = ""
            if check_truncation:
                truncated = len(raw) < 200 or not raw.rstrip().endswith("}")
                hint = (
                    " Response appears TRUNCATED — increase max_output_tokens."
                    if truncated else ""
                )
            logger.warning(
                "[%s] Invalid JSON from LLM — attempting json_repair.%s "
                "Raw response (first 500 chars): %r",
                log_prefix,
                hint,
                raw[:500],
            )
            try:
                repaired = json_repair.repair_json(cleaned, return_objects=True)
                if isinstance(repaired, list) and repaired and all(isinstance(i, dict) for i in repaired):
                    logger.info("[%s] json_repair returned list — wrapping as {sections: [...]}", log_prefix)
                    repaired = {"sections": repaired}
                if not isinstance(repaired, dict):
                    raise ValueError(
                        f"json_repair returned {type(repaired).__name__}, expected dict"
                    )
                logger.info("[%s] json_repair successfully recovered malformed %s.", log_prefix, success_label)
                return repaired
            except Exception as repair_exc:
                raise ValueError(
                    f"LLM returned invalid JSON for {error_desc} and repair failed.{hint} "
                    f"Original error: {original_exc}. "
                    f"Repair error: {repair_exc}. "
                    f"Raw output (first 500 chars): {raw[:500]!r}"
                ) from original_exc

    @staticmethod
    def _build_user_message(
        title: str,
        objectives: list[str],
        *,
        toc_section_contents: list[dict] | None = None,
        heading_tree: list[dict] | None = None,
        pdf_toc_outline: str | None = None,
        course_difficulty: str = "intermediate",
        course_type_hint: str | None = None,
        calculated_word_count: int | None = None,
        audience: str | None = None,
        validation_hints: str | None = None,
        all_doc_titles: list[str] | None = None,
        metadata_in_system: bool = False,
    ) -> str:
        """Build the user message for TO generation.

        When ``metadata_in_system`` is True (dynamic FE flow), course configuration,
        audience, locked title/LOs, and wizard preferences live only in the system
        prompt. The user message carries source structure (headings/TOC/outline) only.
        Do not emit para_idx_start, para_idx_end, or paragraph-index fields in JSON.

        When False (static ``GENERATE_TO_PROMPT``), metadata is included here as before.
        """
        parts: list[str] = []

        if metadata_in_system:
            parts.append(
                "## Source Document Structure\n"
                "Course configuration, audience, locked title/learning objectives, and "
                "author preferences are defined in the system message. Use the "
                "structure blocks below to plan sections and subtopics. "
                "Do not derive course_title or learning_objectives from source filenames."
            )
            if all_doc_titles and len(all_doc_titles) > 1:
                parts.append(
                    "## Source Document Files (reference only — do not use as course_title)\n"
                    + "\n".join(f"- {name}" for name in all_doc_titles)
                )
        else:
            parts.append(f"## Course Difficulty\n{course_difficulty}")
            if calculated_word_count:
                parts.append(f"## Target Word Count\n{calculated_word_count}")
            if audience and audience.strip():
                parts.append(f"## Target Audience\n{audience.strip()}")
            parts.append(f"## Course Title\n{title}")
            if all_doc_titles and len(all_doc_titles) > 1:
                parts.append(
                    "## Source Document Titles (ALL uploaded files)\n"
                    "The course is assembled from "
                    + str(len(all_doc_titles))
                    + " source document(s). "
                    "Generate a course title that comprehensively covers ALL the topics across these files:\n"
                    + "\n".join(f"- {doc_title}" for doc_title in all_doc_titles)
                )
            if objectives:
                parts.append(
                    "## Learning Objectives\n" + "\n".join(f"- {obj}" for obj in objectives)
                )
            if course_type_hint:
                parts.append(f"## COURSE TYPE CONTEXT\n{course_type_hint}")

        if toc_section_contents:
            toc_lines = ["## TOC Hierarchy"]
            for sec in toc_section_contents:
                level = sec.get("level", 1)
                sec_title = sec.get("title", "")
                indent = "  " * max(0, level - 1)
                source = str(sec.get("source") or "").strip()
                if source:
                    toc_lines.append(f"{indent}[L{level}] {sec_title}  (source: {source})")
                else:
                    toc_lines.append(f"{indent}[L{level}] {sec_title}")
            parts.append("\n".join(toc_lines))
        else:
            if heading_tree:
                heading_lines = ["## DOCUMENT HEADING STRUCTURE"]
                for h in heading_tree:
                    level = h.get("level", 1)
                    text = h.get("text", "")
                    indent = "  " * max(0, level - 1)
                    source = str(h.get("source") or "").strip()
                    if source:
                        heading_lines.append(f"{indent}[L{level}] {text}  (source: {source})")
                    else:
                        heading_lines.append(f"{indent}[L{level}] {text}")
                parts.append("\n".join(heading_lines))

            if pdf_toc_outline:
                parts.append(pdf_toc_outline.strip())

        if validation_hints:
            parts.append(
                "## Prior validation feedback (resolve these issues in the generated outline)\n"
                + validation_hints.strip()
            )

        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Backward-compatible module-level wrappers
# ---------------------------------------------------------------------------

def generate_to_with_llm(
    title: str,
    objectives: list[str],
    *,
    heading_tree: list[dict] | None = None,
    toc_section_contents: list[dict] | None = None,
    pdf_toc_outline: str | None = None,
    course_difficulty: str = "intermediate",
    course_type_hint: str | None = None,
    duration_hours: int | float | None = None,
    calculated_word_count: int | None = None,
    audience: str | None = None,
    course_description: str | None = None,
    custom_system_prompt: str | None = None,
    validation_hints: str | None = None,
    all_doc_titles: list[str] | None = None,
    use_static_prompt: bool = False,
    locked_course_title: str | None = None,
    locked_learning_objectives: list[str] | None = None,
    preferred_section_count: int | None = None,
    wizard: "ToWizardPromptContext | None" = None,
    pdf_outline_source_count: int | None = None,
) -> dict:
    return TOProcessor.generate_from_source(
        title,
        objectives,
        heading_tree=heading_tree,
        toc_section_contents=toc_section_contents,
        pdf_toc_outline=pdf_toc_outline,
        course_difficulty=course_difficulty,
        course_type_hint=course_type_hint,
        duration_hours=duration_hours,
        calculated_word_count=calculated_word_count,
        audience=audience,
        course_description=course_description,
        custom_system_prompt=custom_system_prompt,
        validation_hints=validation_hints,
        all_doc_titles=all_doc_titles,
        use_static_prompt=use_static_prompt,
        locked_course_title=locked_course_title,
        locked_learning_objectives=locked_learning_objectives,
        preferred_section_count=preferred_section_count,
        wizard=wizard,
        pdf_outline_source_count=pdf_outline_source_count,
    )


def classify_to_outline_with_llm(
    content_sample: str,
    *,
    validation_hints: str | None = None,
) -> dict:
    return TOProcessor.classify_uploaded(content_sample, validation_hints=validation_hints)


def map_to_to_source_indices(
    sections: list[dict],
    heading_map: list[tuple],
    total_paragraphs: int,
    *,
    paragraphs_by_source: dict[str, int] | None = None,
) -> list[dict]:
    return TOProcessor.map_sections_to_source(
        sections,
        heading_map,
        total_paragraphs,
        paragraphs_by_source=paragraphs_by_source,
    )
