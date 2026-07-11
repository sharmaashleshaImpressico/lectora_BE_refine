"""
Section Mapper — core mapping logic.

Architecture
────────────
  Retrieval Layer  → vector_retriever.py   (Azure AI Search: embed → search → rank)
  Mapping Layer    → this file             (TO structure + metadata propagation)
  Generation Layer → A2 content generator  (consumes matched_chunks per subtopic)

Flow (per TO lesson)
────────────────────
  1. Build subtopic list from the TO outline (Format 1: timed objects; Format 2: strings).
  2. Propagate KC flags and objective indices from A1 course_spec via proportional
     index distribution — no fuzzy text matching required.
  3. Retrieve semantically relevant source chunks via Azure AI Search hybrid search.
  4. Distribute chunks to subtopics via per-subtopic Azure AI Search retrieval
     with semantic ranking — no keyword-overlap or cosine-similarity heuristics.

Output contract (enriched_sections)
────────────────────────────────────
  One dict per TO lesson:
    title, content, word_count, minutes, credit_hour,
    interactive_elements,
    subtopics: [
      title, word_count, minutes, credit_hour,
      interactive_elements,
      maps_to_objectives, images, image_count,
      matched_chunks: [{raw_text, similarity_score, source_metadata}]
    ]

  Knowledge-check and exam metadata are intentionally excluded from this stage.
  Source content for A2 comes from matched_chunks (Azure AI Search embeddings),
  not paragraph-index ranges on the Timed Outline.
"""
from __future__ import annotations

import logging

from app.ai.agents.content_generation_agent.shared.kc_patterns import (
    is_kc_title as _is_kc_title,
)
from app.ai.agents.content_generation_agent.shared.source_documents import (
    resolve_section_source_documents,
)

from .section_helpers import _clean_ie, _is_breakdown_format
from .vector_retriever import EMBEDDING_CONTENT_VECTOR_FIELD, get_retriever

logger = logging.getLogger(__name__)

# Diagnostic threshold: log a warning when average vector chunks per subtopic
# falls below this value (search returned thin results).
_LOW_COVERAGE_THRESHOLD = 1


# ── Utilities ──────────────────────────────────────────────────────────────────

def _subtopic_title(sub) -> str:
    """Return the title string from a subtopic (string or dict)."""
    if isinstance(sub, dict):
        return str(sub.get("title") or "")
    return str(sub or "")


def _strip_disabled_interactive_elements(values: list[str]) -> list[str]:
    """Remove disabled assessment-style interactive elements from output."""
    return [value for value in _clean_ie(values) if value != "knowledge_check"]


# ── Metadata propagation from course_spec ─────────────────────────────────────

def _build_spec_meta(spec_sections: list[dict], n_lessons: int) -> dict[int, dict]:
    """
    Distribute A1 course_spec metadata to TO lesson slots by proportional index.

    Preserves objective-index lists and image references from A1 without any
    text-similarity matching. Each lesson slot gets the metadata from its
    proportional slice of spec sections.

    Returns:
        {lesson_idx: {"objectives": list[int], "images": list}}
    """
    if not spec_sections or n_lessons == 0:
        return {}

    n_specs = len(spec_sections)
    result: dict[int, dict] = {}

    for lesson_idx in range(n_lessons):
        start = round(lesson_idx * n_specs / n_lessons)
        end = round((lesson_idx + 1) * n_specs / n_lessons)
        slice_ = spec_sections[start:end]

        objectives: list[int] = []
        for s in slice_:
            objectives.extend(s.get("maps_to_objectives") or [])
        objectives = list(dict.fromkeys(objectives))  # unique, order-preserving

        images: list = []
        for s in slice_:
            images.extend(s.get("images") or [])

        result[lesson_idx] = {
            "objectives": objectives,
            "images":     images,
        }

    return result


# ── Subtopic builders ──────────────────────────────────────────────────────────

def _build_breakdown_subtopics(
    to_sec: dict,
    lesson_objectives: list[int],
    lesson_images: list,
) -> list[dict]:
    """
    Build subtopic entries for Format 1 (TO subtopics are objects with timing data).

    Knowledge-check-titled entries are excluded from the list because this stage
    now maps teaching content only.
    """
    subtopics: list[dict] = []
    to_subs = [s for s in (to_sec.get("subtopics") or []) if isinstance(s, dict)]

    for i, sub in enumerate(to_subs):
        title = sub.get("title", "")
        if _is_kc_title(title):
            continue

        # Assign images to the first content subtopic of the lesson only, so
        # they appear near the start of the generated content rather than being
        # duplicated across every subtopic in A2's docx renderer.
        images = lesson_images if (i == 0 and lesson_images) else []

        subtopics.append({
            "title":                title,
            "content":              sub.get("content", ""),
            "word_count":           sub.get("word_count", ""),
            "minutes":              sub.get("minutes", ""),
            "credit_hour":          sub.get("credit_hour", ""),
            "interactive_elements": _strip_disabled_interactive_elements(
                sub.get("interactive_elements") or []
            ),
            "maps_to_objectives":   lesson_objectives,
            "images":               images,
            "image_count":          len(images),
        })

    return subtopics


def _build_flat_subtopics(
    to_sec: dict,
    lesson_objectives: list[int],
    lesson_images: list,
) -> list[dict]:
    """
    Build subtopic entries for Format 2 (TO subtopics are strings, or absent).

    Knowledge-check-titled strings are excluded because this stage now maps
    teaching content only.
    """
    subtopics: list[dict] = []
    to_subs = to_sec.get("subtopics") or []

    for i, sub in enumerate(to_subs):
        title = _subtopic_title(sub)
        if not title or _is_kc_title(title):
            continue

        images = lesson_images if (i == 0 and lesson_images) else []

        subtopics.append({
            "title":                title,
            "interactive_elements": [],
            "maps_to_objectives":   lesson_objectives,
            "images":               images,
            "image_count":          len(images),
        })

    return subtopics


# ── Vector enrichment ──────────────────────────────────────────────────────────

def _enrich_with_vector_chunks(
    retriever,
    to_idx: int,
    lesson_title: str,
    subtopics: list[dict],
    lesson_objectives: list[int],
    spec_learning_objectives: list[str] | None,
    source_files: list[str] | None = None,
    course_id: str | None = None,
    document_ids: list[str] | None = None,
    jurisdiction: str | None = None,
) -> None:
    """
    Fetch source chunks from Azure AI Search and distribute them to subtopics.

    Mutates subtopics in-place by adding 'matched_chunks' to each entry.
    Logs query, retrieved chunks, similarity scores, and mapping decisions.
    Silently skips on network errors so the pipeline never blocks on retrieval.

    Args:
        retriever:                  VectorRetriever instance.
        to_idx:                     Lesson index (for logging).
        lesson_title:               TO lesson heading (used in query).
        subtopics:                  Mutable list of subtopic dicts.
        lesson_objectives:          Objective indices for this lesson.
        spec_learning_objectives:   Natural-language objective strings (from A0
                                    extracted_inputs); used to build a richer query.
                                    May be None when not available.
    """
    sub_titles = [s["title"] for s in subtopics if s.get("title")]

    # Build natural-language objectives from objective indices when available.
    nl_objectives: list[str] | None = None
    if lesson_objectives and spec_learning_objectives:
        nl_objectives = [
            spec_learning_objectives[i]
            for i in lesson_objectives
            if 0 <= i < len(spec_learning_objectives)
        ][:4]

    try:
        lesson_chunks = retriever.retrieve_for_lesson(
            lesson_title=lesson_title,
            subtopic_titles=sub_titles,
            objectives=nl_objectives,
            source_files=source_files,
            course_id=course_id,
            document_ids=document_ids,
            jurisdiction=jurisdiction,
        )
    except Exception as exc:
        logger.warning(
            "[SectionMapper] Vector retrieval failed for lesson %d %r: %s",
            to_idx + 1, lesson_title[:50], exc,
        )
        return

    if not lesson_chunks:
        logger.info(
            "[SectionMapper] Lesson %d %r — 0 lesson-level chunks; "
            "running per-subtopic %s similarity search.",
            to_idx + 1,
            lesson_title[:50],
            EMBEDDING_CONTENT_VECTOR_FIELD,
        )

    retriever.distribute_to_subtopics(
        lesson_chunks,
        subtopics,
        lesson_title=lesson_title,
        source_files=source_files,
        course_id=course_id,
        document_ids=document_ids,
        jurisdiction=jurisdiction,
    )

    chunk_counts = [len(s.get("matched_chunks", [])) for s in subtopics]
    total = sum(chunk_counts)
    logger.info(
        "[SectionMapper] Lesson %d %r — %d chunks distributed → %s per subtopic",
        to_idx + 1, lesson_title[:50], total, chunk_counts,
    )

    avg = total / len(subtopics) if subtopics else 0
    if avg < _LOW_COVERAGE_THRESHOLD:
        logger.warning(
            "[SectionMapper] Lesson %d — low vector coverage (avg %.1f chunks/subtopic). "
            "Ensure the source document is indexed before running the pipeline.",
            to_idx + 1, avg,
        )


# ── Public entry point ─────────────────────────────────────────────────────────

def map_sections(
    course_spec: dict,
    outline: dict,
    *,
    course_id: str | None = None,
    document_ids: list[str] | None = None,
    jurisdiction: str | None = None,
) -> list[dict]:
    """
    Map TO lesson structure to source content via Azure AI Search vector retrieval.

    Supports both TO outline formats:
      Format 1 (breakdown) — subtopics are objects carrying timing data.
      Format 2 (flat)      — subtopics are plain strings (or absent).

    Returns one enriched entry per TO lesson.  Each subtopic carries:
      - Structural metadata from the TO outline (title, timing).
      - KC flags and objective indices propagated from A1 course_spec.
      - matched_chunks: vector-retrieved source content ready for A2.

    Retrieval scope
    ────────────────
    ``document_ids``/``course_id``/``jurisdiction`` restrict every retrieval
    call to this document set/course/jurisdiction rather than the full shared
    index. When not passed explicitly, they fall back to the matching keys on
    ``course_spec`` (if present) so legacy callers keep working unfiltered.

    ``course_id`` and ``document_ids`` are applied *together*: every retrieval
    call (lesson-level search, per-subtopic search, and section expansion)
    AND-s both clauses, so only chunks indexed for this course AND this
    document set are ever processed. For that to return results, the
    ``course_id`` written at ingestion time must match the one supplied here
    (see document_upload_service.upload_document).
    """
    course_id = course_id or course_spec.get("course_id") or None
    document_ids = document_ids or course_spec.get("document_ids") or None
    jurisdiction = jurisdiction or course_spec.get("jurisdiction") or None

    spec_sections = course_spec.get("sections", [])
    to_sections = outline.get("sections", [])

    if not to_sections:
        logger.warning("[SectionMapper] No TO sections found — returning empty mapping")
        return []

    is_breakdown = _is_breakdown_format(to_sections)
    logger.info(
        "[SectionMapper] TO format: %s | %d lessons | %d spec sections",
        "breakdown (Format 1)" if is_breakdown else "flat (Format 2)",
        len(to_sections),
        len(spec_sections),
    )
    logger.info(
        "[SectionMapper] Retrieval scope: document_ids=%s course_id=%s jurisdiction=%s",
        document_ids, course_id, jurisdiction,
    )

    # Propagate objective indices and images from A1 course_spec.
    # Uses proportional index distribution — no text matching.
    spec_meta = _build_spec_meta(spec_sections, len(to_sections))

    # Natural-language learning objectives (from A0 extracted_inputs, if present
    # in shared_state).  Passed through outline as a side channel when available.
    spec_lo_strings: list[str] | None = (
        outline.get("_learning_objectives_text") or None
    )

    retriever = get_retriever()
    if retriever:
        logger.info(
            "[SectionMapper] Azure %s similarity retriever active",
            EMBEDDING_CONTENT_VECTOR_FIELD,
        )
    else:
        logger.warning(
            "[SectionMapper] No retrieval backend available — "
            "subtopics will have no matched_chunks."
        )

    enriched: list[dict] = []

    for to_idx, to_sec in enumerate(to_sections):
        meta = spec_meta.get(to_idx, {})
        lesson_objectives: list[int] = meta.get("objectives", [])
        lesson_images: list = meta.get("images", [])

        # Build subtopics from TO structure
        if is_breakdown:
            subtopics = _build_breakdown_subtopics(to_sec, lesson_objectives, lesson_images)
        else:
            subtopics = _build_flat_subtopics(to_sec, lesson_objectives, lesson_images)

        lesson_title = to_sec.get("title", f"Section {to_idx + 1}")
        lesson_source_files = resolve_section_source_documents(to_sec)

        logger.info(
            "[SectionMapper] Lesson %d: %r  subtopics=%d  sources=%d",
            to_idx + 1, lesson_title[:60], len(subtopics), len(lesson_source_files),
        )

        # Vector retrieval — augments each subtopic with matched_chunks
        if retriever and subtopics:
            _enrich_with_vector_chunks(
                retriever=retriever,
                to_idx=to_idx,
                lesson_title=lesson_title,
                subtopics=subtopics,
                lesson_objectives=lesson_objectives,
                spec_learning_objectives=spec_lo_strings,
                source_files=lesson_source_files or None,
                course_id=course_id,
                document_ids=document_ids,
                jurisdiction=jurisdiction,
            )

        lesson_ie = _strip_disabled_interactive_elements(
            to_sec.get("interactive_elements") or []
        )

        enriched.append({
            "title":                lesson_title,
            "content":              to_sec.get("content", ""),
            "word_count":           to_sec.get("word_count", ""),
            "minutes":              to_sec.get("minutes", ""),
            "credit_hour":          to_sec.get("credit_hour", ""),
            "interactive_elements": lesson_ie,
            "subtopics":            subtopics,
        })

    return enriched
