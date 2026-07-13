"""
Content writer — generates study guide content one lesson at a time.

Subtopics of a lesson are sent in one or more LLM calls (batched when there are
many sections — e.g. a single synthetic TO lesson mapping the whole course).
The LLM returns a JSON array — one element per subtopic, in the same order.

Flow per lesson:
  1. Build source text for every subtopic from vector-retrieved matched_chunks.
  2. Cap source text at 3× the section word-count target (prevents LLM
     over-generation on rich source docs).
  3. Calculate each subtopic's word count proportionally from the lesson
     word_count in enriched_sections.json.
  4. Call generate_lesson() → one or more LLM calls → JSON arrays concatenated.
  5. Count words in each generated section and attach metadata.
"""

import json
import logging
import re
import time
from typing import Callable

import json_repair
from semantic_kernel import Kernel

from app.kernel.chat import chat as kernel_chat
from app.tracing import set_generation_label
from ...config.llm import AGENT_CONFIG
from ..constants.prompts import (
    build_lesson_system_prompt,
    build_lesson_user_message,
)
from ...shared.helpers.text_utils import _strip_fences
from .source_chunker import (
    build_prior_summary,
    extract_last_section_tail,
)

# Reserved section headings rendered by A2 from metadata (not from LLM generation).
# Any enriched_section whose title matches these is skipped in content generation.
_RESERVED_LESSON_RE = re.compile(
    r"^\s*(\d+(\.\d+)*\s+)?"
    r"(overview|learning\s+objectives?|learning\s+outcomes?|course\s+objectives?|"
    r"summary|assessment|introduction)\s*$",
    re.IGNORECASE,
)


def _is_reserved_lesson(title: str) -> bool:
    return bool(_RESERVED_LESSON_RE.match((title or "").strip()))


logger = logging.getLogger(__name__)

LessonCompletionHook = Callable[[int, int, dict, list[dict]], None]
LessonGateHook = Callable[[int, int, dict, list[dict], list[dict]], list[dict]]

# Single-call payloads with 100+ sections routinely exceed practical limits; the
# model may return [] or invalid JSON. Chunk when a TO lesson maps many sections.
MAX_SECTIONS_PER_LLM_CALL = 20

# When source >> TO target (rich-source mode), cap source text fed to the LLM at
# this multiple of the section's target_word_count.  Giving the LLM 10 × more
# source than it needs to write causes it to over-generate even when the target
# is marked STRICT.  3× provides enough context without inflating the output.
_SOURCE_TO_TARGET_RATIO = 3.0


def _trim_source_to_budget(text: str, target_wc: int) -> str:
    """Cap source text to _SOURCE_TO_TARGET_RATIO × target_wc words."""
    if not text or target_wc <= 0:
        return text
    cap = max(150, int(target_wc * _SOURCE_TO_TARGET_RATIO))
    words = text.split()
    if len(words) <= cap:
        return text
    return " ".join(words[:cap]) + "\n[... source excerpt capped to word budget ...]"


def _count_source_text_words(text: str) -> int:
    """Count source words from prepared retrieval context."""
    return len(re.findall(r"\w+", text or ""))


def _merge_matched_chunk_text(subtopic: dict) -> str:
    """Merge unique matched-chunk text for a subtopic in retrieval order."""
    matched_chunks = subtopic.get("matched_chunks") or []
    if not matched_chunks:
        return ""

    seen_texts: set[str] = set()
    merged_parts: list[str] = []
    for chunk in matched_chunks:
        raw_text = (chunk.get("raw_text") or "").strip()
        if raw_text and raw_text not in seen_texts:
            merged_parts.append(raw_text)
            seen_texts.add(raw_text)
    return "\n\n".join(merged_parts)


def _build_subtopic_source_text(
    *,
    lesson_title: str,
    subtopic: dict,
    source_chunks: list[dict] | None,
    build_context,
) -> str:
    """Build prompt-ready source text from retrieval results only."""
    _ = (lesson_title, source_chunks, build_context)
    source_parts: list[str] = []

    vector_text = _merge_matched_chunk_text(subtopic)
    if vector_text:
        source_parts.append(vector_text)
        logger.debug(
            "[A2] Subtopic=%r — %d vector chunk chars from matched_chunks.",
            subtopic.get("title", "")[:40],
            len(vector_text),
        )

    if not source_parts:
        return ""

    deduped_parts: list[str] = []
    seen_parts: set[str] = set()
    for part in source_parts:
        normalized = part.strip()
        if normalized and normalized not in seen_parts:
            deduped_parts.append(normalized)
            seen_parts.add(normalized)
    return "\n\n--- Additional source material ---\n".join(deduped_parts)


def _build_parent_overview_source(
    lesson: dict,
    subtopic_sources: list[str],
) -> str:
    """Build grounding text for a parent overview from lesson context + child sources."""
    parts: list[str] = []

    lesson_content = (lesson.get("content") or "").strip()
    if lesson_content:
        parts.append(f"Lesson focus:\n{lesson_content}")

    supporting_sources = [text.strip() for text in subtopic_sources if text.strip()]
    if supporting_sources:
        parts.append(
            "Supporting source material:\n"
            + "\n\n---\n\n".join(supporting_sources[:2])
        )

    return "\n\n".join(parts)


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _parse_llm_json_array(raw: str) -> list[dict]:
    """
    Parse a JSON array from LLM response.

    The LLM is expected to return a bare JSON array. If it wraps the array
    in a dict key (e.g. {"sections": [...]}), the most likely key is unwrapped.
    Falls back to json_repair when the response contains malformed JSON.
    """
    text = _strip_fences(raw)

    def _extract_list(parsed: object) -> list[dict] | None:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            for key in ("sections", "results", "data", "content"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]
        return None

    try:
        parsed = json.loads(text)
        result = _extract_list(parsed)
        if result is not None:
            return result
        raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")
    except json.JSONDecodeError as original_exc:
        logger.warning(
            "[A2] Invalid JSON from LLM — attempting json_repair. "
            "Raw response (first 500 chars): %r",
            raw[:500],
        )
        try:
            repaired = json_repair.repair_json(text, return_objects=True)
            result = _extract_list(repaired)
            if result is not None:
                logger.info("[A2] json_repair successfully recovered malformed content JSON array.")
                return result
            raise ValueError(
                f"json_repair returned {type(repaired).__name__}, expected list or dict with list"
            )
        except Exception as repair_exc:
            raise ValueError(
                f"LLM returned invalid JSON array and repair failed. "
                f"Original error: {original_exc}. "
                f"Repair error: {repair_exc}. "
                f"Raw output (first 500 chars): {raw[:500]!r}"
            ) from original_exc


# ── Word-count helper ─────────────────────────────────────────────────────────

def _count_words_in_section(section_data: dict) -> int:
    """Count total words in a generated section's body_paragraphs."""
    total = 0
    for para in section_data.get("body_paragraphs", []):
        ptype = para.get("type", "")
        if ptype in ("text", "important_callout", "heading_3", "heading_4"):
            total += len(re.findall(r"\w+", para.get("content", "")))
        elif ptype in ("bullet_list", "sub_bullet_list", "numbered_list"):
            for item in para.get("items", []):
                total += len(re.findall(r"\w+", item))
        elif ptype == "table":
            for hdr in (para.get("headers") or []):
                total += len(re.findall(r"\w+", str(hdr)))
            for row in (para.get("rows") or []):
                for cell in (row or []):
                    total += len(re.findall(r"\w+", str(cell)))
    return total


def _strip_disallowed_blocks(section_data: dict) -> dict:
    """Drop disabled assessment-style blocks from generated section output."""
    filtered = []
    removed = 0
    for para in section_data.get("body_paragraphs", []):
        if para.get("type") == "knowledge_check":
            removed += 1
            continue
        filtered.append(para)
    if removed:
        logger.info(
            "[A2] Removed %s disabled knowledge-check block(s) from %r.",
            removed,
            section_data.get("heading", "?"),
        )
    section_data["body_paragraphs"] = filtered
    return section_data


# ── Lesson-level generation ───────────────────────────────────────────────────


def _generate_lesson_single_call(
    kernel: Kernel,
    lesson: dict,
    subtopic_specs: list[dict],
    prior_summary: str,
    rule_pack: dict,
    lesson_wc: int,
    feedback: str | None,
    retries: int,
    *,
    batch_info: str = "",
    audience: str = "",
    special_instructions: str | None = None,
    prev_lesson_context: str = "",
    course_config: dict | None = None,
) -> list[dict]:
    """One LLM round-trip for a slice of subtopic_specs (internal)."""
    if not subtopic_specs:
        return []

    system_prompt = build_lesson_system_prompt(rule_pack, audience=audience, course_config=course_config)

    user_msg = build_lesson_user_message(
        lesson=lesson,
        subtopic_specs=subtopic_specs,
        prior_summary=prior_summary,
        rule_constraints=rule_pack,
        lesson_wc=lesson_wc,
        feedback=feedback,
        audience=audience,
        special_instructions=special_instructions,
        prev_lesson_context=prev_lesson_context,
        course_config=course_config,
    )

    last_error: str | None = None
    prefix = f"{batch_info} " if batch_info else ""

    for attempt in range(1, retries + 1):
        try:
            lesson_title = (lesson.get("title") or lesson.get("heading") or "lesson").strip()
            set_generation_label(f"content generate · {lesson_title}")
            raw = kernel_chat(kernel, system_prompt, user_msg, AGENT_CONFIG, "A2")
            sections_data = _parse_llm_json_array(raw)

            if len(sections_data) != len(subtopic_specs):
                raise ValueError(
                    f"Expected {len(subtopic_specs)} sections in array, "
                    f"got {len(sections_data)}"
                )

            results: list[dict] = []
            for i, sec in enumerate(sections_data):
                if "body_paragraphs" not in sec:
                    raise ValueError(
                        f"Section {i + 1} missing 'body_paragraphs'")
                sec = _strip_disallowed_blocks(sec)
                wc = _count_words_in_section(sec)
                sec["word_count"] = wc
                sec["status"] = "generated"
                sec["attempts"] = attempt
                logger.info(
                    "    %s[%s/%s] %s — %sw (target %sw)",
                    prefix,
                    i + 1,
                    len(subtopic_specs),
                    sec.get("heading", "?"),
                    wc,
                    subtopic_specs[i].get("target_word_count", 0),
                )
                results.append(sec)

            return results

        except Exception as e:
            last_error = str(e)
            logger.warning(
                "  [A2] %sAttempt %s/%s error: %s",
                prefix,
                attempt,
                retries,
                last_error,
            )
            if attempt < retries:
                # Azure OpenAI server errors (500) need recovery time before retry.
                # Short sleep suffices for parse/validation failures (our fault).
                _err_lower = last_error.lower()
                is_server_err = (
                    "500" in last_error
                    or "server_error" in _err_lower
                    or "internal server" in _err_lower
                )
                wait_s = 30 if is_server_err else (2 * attempt)
                if is_server_err:
                    logger.info(
                        "  [A2] %sServer error — waiting %ss for Azure to recover "
                        "before attempt %s/%s…",
                        prefix, wait_s, attempt + 1, retries,
                    )
                time.sleep(wait_s)

    return [
        {
            "heading":         spec.get("heading", f"Section {i + 1}"),
            "body_paragraphs": [],
            "word_count":      0,
            "status":          "failed",
            "error":           last_error,
            "attempts":        retries,
        }
        for i, spec in enumerate(subtopic_specs)
    ]


def generate_lesson(
    kernel: Kernel,
    lesson: dict,
    subtopic_specs: list[dict],
    prior_summary: str,
    rule_pack: dict,
    lesson_wc: int,
    max_retries: int | None = None,
    feedback: str | None = None,
    audience: str = "",
    special_instructions: str | None = None,
    prev_lesson_context: str = "",
    course_config: dict | None = None,
) -> list[dict]:
    """
    Generate content for ALL subtopics of one TO lesson (one or more LLM calls).

    Large lessons (e.g. entire course under one synthetic TO bucket) are split
    into batches of ``MAX_SECTIONS_PER_LLM_CALL`` so the model returns a valid
    JSON array at practical sizes.

    Args:
        lesson         : The TO lesson entry from enriched_sections.
        subtopic_specs : List of per-subtopic dicts (heading, target_word_count,
                         source_text, interactive_elements, …).
        prior_summary  : Brief summary of already-generated lessons.
        rule_pack      : Active rule pack constraints.
        lesson_wc      : Total word budget for this lesson (from enriched_sections.json).
        max_retries    : Retry count on JSON parse failure (default: rule_pack.error_tolerance.max_retries_per_step).

    Returns:
        List of section dicts in the same order as subtopic_specs.
        Each dict has: heading, body_paragraphs, word_count, status, attempts.
        On complete failure, returns stub dicts with status="failed".
    """
    if not subtopic_specs:
        return []

    retries = max_retries
    if retries is None:
        retries = int(rule_pack.get("error_tolerance", {}).get("max_retries_per_step", 3))

    n_specs = len(subtopic_specs)
    if n_specs <= MAX_SECTIONS_PER_LLM_CALL:
        return _generate_lesson_single_call(
            kernel,
            lesson=lesson,
            subtopic_specs=subtopic_specs,
            prior_summary=prior_summary,
            rule_pack=rule_pack,
            lesson_wc=lesson_wc,
            feedback=feedback,
            retries=retries,
            audience=audience,
            special_instructions=special_instructions,
            prev_lesson_context=prev_lesson_context,
            course_config=course_config,
        )

    n_batches = (n_specs + MAX_SECTIONS_PER_LLM_CALL - 1) // MAX_SECTIONS_PER_LLM_CALL
    logger.info(
        "  [A2] Lesson %r: %s section(s) in %s batch(es) (max %s per LLM call)",
        lesson.get("title", ""),
        n_specs,
        n_batches,
        MAX_SECTIONS_PER_LLM_CALL,
    )

    all_results: list[dict] = []
    for b in range(n_batches):
        start = b * MAX_SECTIONS_PER_LLM_CALL
        chunk = subtopic_specs[start : start + MAX_SECTIONS_PER_LLM_CALL]
        chunk_wc = sum(int(s.get("target_word_count") or 0) for s in chunk)
        if chunk_wc <= 0:
            chunk_wc = max(
                200,
                lesson_wc * len(chunk) // max(n_specs, 1),
            )
        batch_label = f"batch {b + 1}/{n_batches}"
        # Only pass prev_lesson_context to the first batch — subsequent batches
        # already have continuity from the sections generated before them.
        batch_prev_ctx = prev_lesson_context if b == 0 else ""
        all_results.extend(
            _generate_lesson_single_call(
                kernel,
                lesson=lesson,
                subtopic_specs=chunk,
                prior_summary=prior_summary,
                rule_pack=rule_pack,
                lesson_wc=chunk_wc,
                feedback=feedback,
                retries=retries,
                batch_info=batch_label,
                audience=audience,
                special_instructions=special_instructions,
                prev_lesson_context=batch_prev_ctx,
                course_config=course_config,
            )
        )

    return all_results


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_one_lesson(
    *,
    kernel: Kernel,
    lesson_idx: int,
    total_lessons: int,
    lesson: dict,
    generated_so_far: list[dict],
    rule_pack: dict,
    feedback: str | None = None,
    source_chunks: list[dict] | None = None,
    audience: str = "",
    special_instructions: str | None = None,
    course_config: dict | None = None,
) -> list[dict]:
    """Generate all sections for a single TO lesson."""
    to_title = lesson.get("title", "")
    subtopics = lesson.get("subtopics", [])

    try:
        lesson_wc = int(float(lesson.get("word_count") or 500))
    except (ValueError, TypeError):
        lesson_wc = 500

    try:
        lesson_mins = float(lesson.get("minutes") or 3.0)
    except (ValueError, TypeError):
        lesson_mins = 3.0

    logger.info(
        "[Lesson %s/%s] %s  (%sw, %s subtopic(s))",
        lesson_idx,
        total_lessons,
        to_title,
        lesson_wc,
        len(subtopics),
    )

    if not subtopics:
        logger.info("  -> No subtopics, skipping lesson")
        return []

    if _is_reserved_lesson(to_title):
        logger.info(
            "  -> Reserved section %r — skipping content generation "
            "(rendered from metadata by doc_formatter).",
            to_title,
        )
        return []

    source_texts: list[str] = []
    for sub in subtopics:
        source_texts.append(
            _build_subtopic_source_text(
                lesson_title=to_title,
                subtopic=sub,
                source_chunks=source_chunks,
                build_context=None,
            )
        )

    def _parse_to_wc(val) -> int:
        try:
            f = float(val)
            return int(f) if f > 0 else 0
        except (TypeError, ValueError):
            return 0

    to_wc_values = [_parse_to_wc(sub.get("word_count")) for sub in subtopics]
    use_to_wc = any(v > 0 for v in to_wc_values)

    if use_to_wc:
        fallback = max(50, lesson_wc // len(subtopics))
        wc_per_sub = [v if v > 0 else fallback for v in to_wc_values]
        logger.debug("  [A2] Using TO subtopic word_counts: %s", wc_per_sub)
    else:
        src_wc = [_count_source_text_words(text) for text in source_texts]
        total_src = sum(src_wc)
        if total_src > 0:
            wc_per_sub = [
                max(50, int(lesson_wc * w / total_src)) if w > 0 else 50
                for w in src_wc
            ]
        else:
            even = max(50, lesson_wc // len(subtopics))
            wc_per_sub = [even] * len(subtopics)

    subtopic_specs: list[dict] = []
    parent_overview_added = False
    if use_to_wc and lesson_wc > 0:
        parent_source = _build_parent_overview_source(lesson, source_texts)
        parent_wc = lesson_wc
        parent_source = _trim_source_to_budget(parent_source, parent_wc)
        subtopic_specs.append({
            "heading":              to_title,
            "target_word_count":    parent_wc,
            "source_text":          parent_source,
            "subtopics":            [sub.get("title", "") for sub in subtopics],
            "interactive_elements": [],
            "image_count":          0,
            "target_minutes":       lesson_mins,
            "_is_parent_overview":  True,
            "prev_section_heading": "",
        })
        parent_overview_added = True

    _prev_spec_heading: str = to_title if parent_overview_added else ""

    for sub_i, sub in enumerate(subtopics):
        source_text = source_texts[sub_i]
        source_text = _trim_source_to_budget(source_text, wc_per_sub[sub_i])
        sub_heading = sub.get("title", f"Section {sub_i + 1}")
        subtopic_specs.append({
            "heading":             sub_heading,
            "target_word_count":   wc_per_sub[sub_i],
            "source_text":         source_text,
            "maps_to_objectives":  sub.get("maps_to_objectives", []),
            "subtopics":           sub.get("subtopics", []),
            "interactive_elements": sub.get("interactive_elements", []),
            "image_count":         sub.get("image_count", 0),
            "target_minutes":      lesson_mins,
            "prev_section_heading": _prev_spec_heading,
        })
        _prev_spec_heading = sub_heading

    prior_summary = build_prior_summary(generated_so_far)
    prev_lesson_context = extract_last_section_tail(generated_so_far)
    results = generate_lesson(
        kernel,
        lesson=lesson,
        subtopic_specs=subtopic_specs,
        prior_summary=prior_summary,
        rule_pack=rule_pack,
        lesson_wc=lesson_wc,
        feedback=feedback,
        audience=audience,
        special_instructions=special_instructions,
        prev_lesson_context=prev_lesson_context,
        course_config=course_config,
    )

    lesson_generated: list[dict] = []
    offset = 1 if parent_overview_added else 0
    for i, result in enumerate(results):
        if i == 0 and parent_overview_added:
            result["subtopics"] = [sub.get("title", "") for sub in subtopics]
            result["maps_to_objectives"] = []
            result["section_id"] = ""
            result["images"] = []
            result["outline_lesson"] = to_title
            result["is_parent_overview"] = True
            result["level"] = 1
            lesson_generated.append(result)
        else:
            sub_idx = i - offset
            if sub_idx < 0 or sub_idx >= len(subtopics):
                continue
            sub = subtopics[sub_idx]
            result["subtopics"] = sub.get("subtopics", [])
            result["maps_to_objectives"] = sub.get("maps_to_objectives", [])
            result["section_id"] = sub.get("id", "")
            result["images"] = sub.get("images", [])
            result["outline_lesson"] = to_title
            result["level"] = 2
            lesson_generated.append(result)

        status = result.get("status", "unknown")
        wc_out = result.get("word_count", 0)
        if status == "failed":
            logger.error(
                "    -> FAILED [%s]: %s",
                result.get("heading", ""),
                result.get("error", "?"),
            )
        else:
            logger.info("    -> %s — %sw", result.get("heading", ""), wc_out)

    return lesson_generated


def generate_all_sections(
    kernel: Kernel,
    enriched_sections: list[dict],
    docx_path: str,
    rule_pack: dict,
    feedback: str | None = None,
    source_chunks: list[dict] | None = None,
    shared_state_path: str | None = None,
    audience: str = "",
    special_instructions: str | None = None,
    course_config: dict | None = None,
    lesson_completion_hook: LessonCompletionHook | None = None,
    lesson_gate_hook: LessonGateHook | None = None,
) -> list[dict]:
    """
    Generate content for every lesson in enriched_sections.

    For each TO lesson, all subtopics are sent in a SINGLE LLM call.
    Word count per subtopic is distributed proportionally based on the length
    of each subtopic's retrieved source text, within the lesson's total
    word_count budget from enriched_sections.json.

    Args:
        enriched_sections : List of TO-lesson dicts from Section Mapper.
        docx_path         : Retained for backward-compatible call sites; A2 now
                            grounds generation from retrieval context instead of
                            paragraph-index ranges.
        rule_pack         : Active rule pack constraints.
        feedback          : Optional S2 feedback to inject into generation.
        source_chunks     : Deprecated compatibility argument. A2 now grounds
                            generation from matched_chunks only.
        shared_state_path : Deprecated; retained in the signature for call-site compatibility.

    Returns:
        Flat list of generated section dicts in document order.
    """
    generated: list[dict] = []
    total_lessons = len(enriched_sections)

    for lesson_idx, lesson in enumerate(enriched_sections, start=1):
        lesson_generated = generate_one_lesson(
            kernel=kernel,
            lesson_idx=lesson_idx,
            total_lessons=total_lessons,
            lesson=lesson,
            generated_so_far=generated,
            rule_pack=rule_pack,
            feedback=feedback,
            source_chunks=source_chunks,
            audience=audience,
            special_instructions=special_instructions,
            course_config=course_config,
        )

        if lesson_gate_hook is not None and lesson_generated:
            all_generated = generated + lesson_generated
            lesson_generated = lesson_gate_hook(
                lesson_idx,
                total_lessons,
                lesson,
                lesson_generated,
                all_generated,
            )
        elif lesson_completion_hook is not None and lesson_generated:
            lesson_completion_hook(
                lesson_idx,
                total_lessons,
                lesson,
                generated + lesson_generated,
            )

        generated.extend(lesson_generated)

    return generated
