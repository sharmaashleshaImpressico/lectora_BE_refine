"""
Vector retriever for Section Mapper.

Queries the Azure AI Search index (populated by the ingestion pipeline) to find
the most semantically relevant source chunks for each lesson and subtopic.

This module is the sole Retrieval Layer for the Section Mapper.  It owns:
  - Query construction          (build_query, _build_subtopic_query)
  - Lesson-level vector search  (VectorRetriever.retrieve_for_lesson)
  - Subtopic-level retrieval    (VectorRetriever.distribute_to_subtopics)
  - Result parsing + threshold  (_parse_search_results)
  - Similarity-score sorting    (_sort_by_similarity_score)
  - Text aggregation            (merge_to_raw_text)

Retrieval architecture
──────────────────────
1. Lesson-level retrieval (one call per lesson):
     build_query(title + subtopics + objectives)
       → Azure AI Search vector search on embedding_content
       → top-20 chunks, dynamic threshold filter
       → candidate pool used for logging

2. Subtopic-level retrieval (one call per content subtopic):
     _build_subtopic_query(subtopic_title, lesson_title)
       → Azure AI Search vector search on embedding_content
       → top seed chunks, then optional full-section expansion
       → sorted by document order, attached as matched_chunks

Dynamic threshold
──────────────────
  threshold = max(MIN_ABSOLUTE_THRESHOLD, top_score × DYNAMIC_THRESHOLD_RATIO)

  Tightens the cut-off when strong results are returned; relaxes it when the
  query is ambiguous. Score is derived from @search.score.

Public surface
───────────────
    get_retriever()                             → VectorRetriever | None
    build_query(title, ...)                     → str
    merge_to_raw_text(chunks)                   → str
    VectorChunk                                 dataclass
    VectorRetriever.retrieve_for_lesson(…)
    VectorRetriever.distribute_to_subtopics(…)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.ai.shared_llm_config.tracer import (
    RetrievalTrace,
    write_retrieval_trace,
)

logger = logging.getLogger(__name__)

# Name of the Azure AI Search vector field used for chunk-content embeddings.
# No ingestion service is wired up in this repo yet (see get_retriever()) — this
# constant is kept for trace/logging labels and for parity with the search index
# schema once ingestion is connected.
EMBEDDING_CONTENT_VECTOR_FIELD = "embedding_content"

# ── Constants ──────────────────────────────────────────────────────────────────

# Lesson-level retrieval — broad candidate pool for scoring + logging.
_LESSON_TOP_K = 20

# Per-subtopic retrieval — seed chunks before optional section expansion.
_SUBTOPIC_TOP_K = 5
_SUBTOPIC_SEARCH_TOP_K = 24
_MIN_CHUNK_CHARS = 150
_TEXT_FINGERPRINT_CHARS = 500

# Dynamic threshold for score filtering.
# threshold = max(MIN_ABSOLUTE, top_score × RATIO)
# For reranker scores (0–1 normalised): top=0.90 → threshold≈0.63
# For search scores (0–1):             top=0.60 → threshold=0.42 (floor at 0.20)
_MIN_ABSOLUTE_THRESHOLD = 0.20
_DYNAMIC_THRESHOLD_RATIO = 0.70

# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class VectorChunk:
    """A single source chunk retrieved from Azure AI Search."""
    raw_text: str
    similarity_score: float
    source_metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "raw_text":         self.raw_text,
            "similarity_score": self.similarity_score,
            "source_metadata":  self.source_metadata,
        }


# ── Query builders ──────────────────────────────────────────────────────────────

def build_query(
    title: str,
    subtopic_titles: list[str] | None = None,
    objectives: list[str] | None = None,
) -> str:
    """
    Build a natural-language search query for lesson-level retrieval.

    Combines the lesson title, subtopic headings, and learning objectives into
    a single text for Azure OpenAI query embedding generation.
    """
    parts: list[str] = []
    if title:
        parts.append(title.strip())
    if subtopic_titles:
        parts.extend(t.strip() for t in subtopic_titles[:4] if t and t.strip())
    if objectives:
        parts.extend(o.strip() for o in objectives[:3] if o and o.strip())
    return ". ".join(filter(None, parts))


def _build_subtopic_query(subtopic_title: str, lesson_title: str) -> str:
    """
    Build a targeted query for per-subtopic retrieval.

    The subtopic title is the primary signal; the lesson title is appended as
    context to disambiguate terms that mean different things in different modules
    (e.g. "liability" in a property course vs. a health insurance course).
    """
    parts = [subtopic_title.strip()]
    if lesson_title and lesson_title.strip() != subtopic_title.strip():
        parts.append(lesson_title.strip())
    return ". ".join(filter(None, parts))


# ── Result parsing ──────────────────────────────────────────────────────────────

def _parse_search_results(
    raw: list[dict],
    threshold_ratio: float = _DYNAMIC_THRESHOLD_RATIO,
) -> list[VectorChunk]:
    """
    Convert raw Azure AI Search result dicts to VectorChunk objects.

    Score selection
    ────────────────
    When a reranker score is present, it is normalised to [0, 1] and preferred.
    Otherwise ``@search.score`` from the vector search response is used.

    Dynamic threshold
    ──────────────────
    threshold = max(MIN_ABSOLUTE_THRESHOLD, top_score × threshold_ratio)

    Calibrates the cut-off to the actual quality of each result set rather than
    using a fixed value that may be too strict or too loose across queries.

    ``source_metadata["reranker_score"]`` preserves the raw reranker value for
    logging and diagnostics.
    """
    if not raw:
        return []

    chunks: list[VectorChunk] = []
    for r in raw:
        raw_text = (r.get("raw_text") or "").strip()
        if not raw_text:
            continue

        reranker_raw = r.get("@search.rerankerScore")
        search_score = float(r.get("@search.score") or 0.0)
        # Normalise reranker score (0–4) to [0, 1]; fall back to search score.
        score = (float(reranker_raw) / 4.0) if reranker_raw is not None else search_score

        chunks.append(VectorChunk(
            raw_text=raw_text,
            similarity_score=round(score, 4),
            source_metadata={
                "chunk_id":       r.get("chunk_id", ""),
                "source_file":    r.get("source_file", ""),
                "page_num":       r.get("page_num"),
                "title":          r.get("title", ""),
                "section_id":     r.get("section_id", ""),
                "reranker_score": reranker_raw,
                "vector_field":   EMBEDDING_CONTENT_VECTOR_FIELD,
            },
        ))

    if not chunks:
        return chunks

    top_score = max(c.similarity_score for c in chunks)
    threshold = max(_MIN_ABSOLUTE_THRESHOLD, top_score * threshold_ratio)
    filtered = [c for c in chunks if c.similarity_score >= threshold]

    logger.debug(
        "[vector_retriever] parse: %d/%d passed threshold=%.3f "
        "(top=%.3f, has_reranker=%s)",
        len(filtered), len(chunks), threshold, top_score,
        chunks[0].source_metadata.get("reranker_score") is not None if chunks else False,
    )
    return filtered


# ── Similarity-score sort ──────────────────────────────────────────────────────

def _sort_by_similarity_score(chunks: list[VectorChunk]) -> list[VectorChunk]:
    """Order chunks by embedding_content vector similarity (highest first)."""
    return sorted(chunks, key=lambda chunk: chunk.similarity_score, reverse=True)


def _sort_by_document_order(chunks: list[VectorChunk]) -> list[VectorChunk]:
    """
    Re-sort chunks by their natural document order (page_num → sequence in chunk_id).

    Preserves reading order when multiple chunks are merged into a content block,
    which produces more coherent source text for A2's generation prompt.
    """
    def _order_key(c: VectorChunk) -> tuple:
        meta = c.source_metadata
        source_order = meta.get("source_order")
        para_start = meta.get("para_start")
        page = meta.get("page_num") or 0
        chunk_id = meta.get("chunk_id", "")
        try:
            seq = int(chunk_id.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            seq = 0
        return (
            int(source_order) if source_order is not None else 0,
            int(page) if page is not None else 0,
            int(para_start) if para_start is not None else seq,
            seq,
        )

    return sorted(chunks, key=_order_key)


def _filter_chunks_by_source_files(
    chunks: list[VectorChunk],
    source_files: list[str] | None,
) -> list[VectorChunk]:
    """Keep chunks whose source_file is in the allowed list."""
    if not source_files:
        return chunks

    allowed = {name.strip().lower() for name in source_files if str(name).strip()}
    if not allowed:
        return chunks

    filtered = [
        chunk
        for chunk in chunks
        if str(chunk.source_metadata.get("source_file") or "").strip().lower() in allowed
    ]
    if not filtered:
        retrieved = sorted({
            str(chunk.source_metadata.get("source_file") or "").strip().lower()
            for chunk in chunks
            if str(chunk.source_metadata.get("source_file") or "").strip()
        })
        logger.warning(
            "[vector_retriever] source_files filter removed all chunks "
            "(allowed=%s retrieved=%s) — using unfiltered Azure results.",
            sorted(allowed),
            retrieved,
        )
        return chunks
    return filtered


def _chunk_text_fingerprint(text: str) -> str:
    """Normalize chunk body text for duplicate detection across ingest copies."""
    return " ".join(str(text or "").split()).lower()[:_TEXT_FINGERPRINT_CHARS]


def _section_mapper_retrieval_options() -> tuple[int, int, bool, int]:
    """Retrieval tuning knobs — hardcoded defaults (no external settings source)."""
    return (_SUBTOPIC_TOP_K, _SUBTOPIC_SEARCH_TOP_K, False, 12000)


def _count_words(text: str) -> int:
    return len(str(text or "").split())


def _raw_record_to_vector_chunk(
    record: dict,
    *,
    similarity_score: float = 0.0,
) -> VectorChunk | None:
    raw_text = (record.get("raw_text") or "").strip()
    if not raw_text or len(raw_text) < _MIN_CHUNK_CHARS:
        return None

    reranker_raw = record.get("@search.rerankerScore")
    if similarity_score <= 0 and reranker_raw is not None:
        similarity_score = float(reranker_raw) / 4.0
    elif similarity_score <= 0:
        similarity_score = float(record.get("@search.score") or 0.0)

    return VectorChunk(
        raw_text=raw_text,
        similarity_score=round(similarity_score, 4),
        source_metadata={
            "chunk_id":       record.get("chunk_id", ""),
            "source_file":    record.get("source_file", ""),
            "page_num":       record.get("page_num"),
            "title":          record.get("title", ""),
            "section_id":     record.get("section_id", ""),
            "reranker_score": reranker_raw,
            "vector_field":   EMBEDDING_CONTENT_VECTOR_FIELD,
        },
    )


def _dedupe_within_subtopic(chunks: list[VectorChunk]) -> list[VectorChunk]:
    """Remove duplicate chunk_id / body text within one subtopic."""
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    unique: list[VectorChunk] = []
    for chunk in chunks:
        text = (chunk.raw_text or "").strip()
        if len(text) < _MIN_CHUNK_CHARS:
            continue
        chunk_id = str(chunk.source_metadata.get("chunk_id") or "").strip()
        fingerprint = _chunk_text_fingerprint(text)
        if chunk_id and chunk_id in seen_ids:
            continue
        if fingerprint in seen_fingerprints:
            continue
        unique.append(chunk)
        if chunk_id:
            seen_ids.add(chunk_id)
        seen_fingerprints.add(fingerprint)
    return unique


def _cap_chunks_by_word_limit(
    chunks: list[VectorChunk],
    max_words: int,
) -> list[VectorChunk]:
    if max_words <= 0:
        return chunks
    kept: list[VectorChunk] = []
    total_words = 0
    for chunk in chunks:
        chunk_words = _count_words(chunk.raw_text)
        if total_words + chunk_words > max_words and kept:
            break
        kept.append(chunk)
        total_words += chunk_words
    return kept


def _expand_matched_sections(
    service,
    seed_chunks: list[VectorChunk],
    *,
    max_words: int,
) -> list[VectorChunk]:
    """
    After vector search picks seed chunks, pull every indexed chunk for those
    sections so matched_chunks carry full section text (not one small slice).
    """
    if not seed_chunks:
        return seed_chunks

    score_by_chunk_id = {
        str(chunk.source_metadata.get("chunk_id") or ""): chunk.similarity_score
        for chunk in seed_chunks
        if chunk.source_metadata.get("chunk_id")
    }
    section_ids = sorted({
        str(chunk.source_metadata.get("section_id") or "").strip()
        for chunk in seed_chunks
        if str(chunk.source_metadata.get("section_id") or "").strip()
    })

    combined = list(seed_chunks)
    seen_chunk_ids = {
        str(chunk.source_metadata.get("chunk_id") or "")
        for chunk in seed_chunks
        if chunk.source_metadata.get("chunk_id")
    }

    for section_id in section_ids:
        raw_rows = service.list_chunks_for_section(section_id)
        for row in raw_rows:
            chunk_id = str(row.get("chunk_id") or "").strip()
            if chunk_id and chunk_id in seen_chunk_ids:
                continue
            score = score_by_chunk_id.get(chunk_id, 0.05)
            parsed = _raw_record_to_vector_chunk(row, similarity_score=score)
            if not parsed:
                continue
            combined.append(parsed)
            if chunk_id:
                seen_chunk_ids.add(chunk_id)

    ordered = _sort_by_document_order(combined)
    unique = _dedupe_within_subtopic(ordered)
    capped = _cap_chunks_by_word_limit(unique, max_words)
    logger.info(
        "[vector_retriever] Section expand: seeds=%d sections=%d → %d chunks (%d words)",
        len(seed_chunks),
        len(section_ids),
        len(capped),
        sum(_count_words(c.raw_text) for c in capped),
    )
    return capped


def _dedupe_and_select_chunks(
    chunks: list[VectorChunk],
    *,
    max_chunks: int,
    used_chunk_ids: set[str],
    used_text_fingerprints: set[str],
) -> list[VectorChunk]:
    """Pick up to max_chunks unique chunks, skipping lesson-level duplicates."""
    selected: list[VectorChunk] = []
    for chunk in chunks:
        if len(selected) >= max_chunks:
            break

        text = (chunk.raw_text or "").strip()
        if len(text) < _MIN_CHUNK_CHARS:
            continue

        chunk_id = str(chunk.source_metadata.get("chunk_id") or "").strip()
        fingerprint = _chunk_text_fingerprint(text)
        if chunk_id and chunk_id in used_chunk_ids:
            continue
        if fingerprint in used_text_fingerprints:
            continue

        selected.append(chunk)
        if chunk_id:
            used_chunk_ids.add(chunk_id)
        used_text_fingerprints.add(fingerprint)

    return selected


# ── Retriever ──────────────────────────────────────────────────────────────────

class VectorRetriever:
    """
    Retrieves and distributes source chunks from Azure AI Search for the Section Mapper.

    Design
    ──────
    - One Azure AI Search vector call per lesson gives a broad candidate pool
      used for monitoring.
    - One targeted Azure AI Search vector call per content subtopic is the
      primary path for matched_chunks assignment.
    - Retrieval is embedding-only; failures are surfaced in logs instead of
      falling back to source-text heuristics.
    """

    def __init__(self, retrieval_service) -> None:
        self._service = retrieval_service

    # ── Primary API ──────────────────────────────────────────────────────────

    def retrieve_for_lesson(
        self,
        lesson_title: str,
        subtopic_titles: list[str] | None = None,
        objectives: list[str] | None = None,
        document_id: str | None = None,
        top: int = _LESSON_TOP_K,
        source_files: list[str] | None = None,
    ) -> list[VectorChunk]:
        """
        Fetch a broad candidate pool for an entire lesson.

        This is a lesson-level vector search over chunk embeddings.
        The result serves two purposes:
          1. Monitoring — total chunks available, score distribution per lesson.
          2. Diagnostics — confirms whether the vector index returns supporting
             chunks for the lesson query.

        For the primary subtopic content assignment, call distribute_to_subtopics()
        which issues individual vector queries per subtopic.

        Returns VectorChunks above the adaptive threshold, sorted by score desc.
        """
        query = build_query(lesson_title, subtopic_titles, objectives)
        logger.info(
            "[vector_retriever] Lesson=%r  query=%r  document_id=%s  top=%d",
            lesson_title[:50], query[:120], document_id, top,
        )

        error_msg: str | None = None
        raw: list[dict] = []
        t_start = time.perf_counter()
        try:
            raw = self._service.retrieve_topic(
                topic=query,
                document_id=document_id,
                top=top,
            )
        except Exception as exc:
            error_msg = str(exc)
            logger.warning(
                "[vector_retriever] Lesson search failed for %r: %s",
                lesson_title[:50], exc,
            )
        finally:
            latency_ms = (time.perf_counter() - t_start) * 1000
            try:
                write_retrieval_trace(RetrievalTrace(
                    agent="SECTION_MAPPER",
                    retrieval_type="lesson_vector",
                    query=query,
                    result_count=len(raw),
                    latency_ms=latency_ms,
                    document_id=document_id,
                    error=error_msg,
                    metadata={
                        "lesson_title": lesson_title[:120],
                        "top_k": top,
                    },
                ))
            except Exception:
                pass

        if error_msg:
            return []

        chunks = _parse_search_results(raw)
        chunks = _filter_chunks_by_source_files(chunks, source_files)
        chunks.sort(key=lambda c: c.similarity_score, reverse=True)

        top_score = chunks[0].similarity_score if chunks else None
        has_reranker = (
            chunks[0].source_metadata.get("reranker_score") is not None
            if chunks else False
        )
        # Threshold is derived inside _parse_search_results; re-compute for the trace.
        threshold = (
            max(_MIN_ABSOLUTE_THRESHOLD, top_score * _DYNAMIC_THRESHOLD_RATIO)
            if top_score is not None else None
        )

        logger.info(
            "[vector_retriever] Lesson=%r → %d/%d chunks above threshold",
            lesson_title[:50], len(chunks), len(raw),
        )
        if chunks:
            logger.debug(
                "[vector_retriever] Top 3 lesson scores: %s  top_title=%r",
                [f"{c.similarity_score:.3f}" for c in chunks[:3]],
                chunks[0].source_metadata.get("title", "")[:50],
            )

        # Update the retrieval trace with score/threshold info now that we have it.
        try:
            write_retrieval_trace(RetrievalTrace(
                agent="SECTION_MAPPER",
                retrieval_type="lesson_vector_scored",
                query=query,
                result_count=len(chunks),
                latency_ms=0,  # already captured above; this is the post-filter record
                top_score=top_score,
                threshold=threshold,
                has_semantic_ranker=has_reranker,
                document_id=document_id,
                metadata={
                    "lesson_title": lesson_title[:120],
                    "raw_result_count": len(raw),
                    "top_3_scores": [f"{c.similarity_score:.3f}" for c in chunks[:3]],
                },
            ))
        except Exception:
            pass

        return chunks

    def distribute_to_subtopics(
        self,
        lesson_chunks: list[VectorChunk],
        subtopics: list[dict],
        lesson_title: str = "",
        document_id: str | None = None,
        top_per_subtopic: int = _SUBTOPIC_TOP_K,
        source_files: list[str] | None = None,
    ) -> list[dict]:
        """
        Assign relevant chunks to each subtopic via targeted Azure AI Search retrieval.

        Primary path: per-subtopic vector search
        ───────────────────────────────────────────
        For each content subtopic, a targeted query is issued:
            query = "{subtopic_title}. {lesson_title}"

        The lesson title provides disambiguation context while the embedding
        model encodes semantic similarity directly into the query vector.

        Score handling
        ───────────────
        @search.score from the vector search response is used. The dynamic
        threshold filters results: threshold = max(0.20, top_score × 0.70).

        Modifies subtopics in-place by adding "matched_chunks" to each entry.
        Only teaching-content subtopics are expected at this stage.
        Returns the augmented subtopic list.

        Args:
            lesson_chunks:     Lesson-level candidate pool used for diagnostics only.
            subtopics:         Mutable list of subtopic dicts from mapper.py.
            lesson_title:      TO lesson heading — appended to subtopic query for context.
            document_id:       Optional — restrict search to a specific ingested document.
            top_per_subtopic:  Max chunks per subtopic (default 5).
        """
        if not subtopics:
            return subtopics

        seed_count, search_top_k, expand_sections, max_source_words = (
            _section_mapper_retrieval_options()
        )
        if top_per_subtopic != _SUBTOPIC_TOP_K:
            seed_count = top_per_subtopic

        for sub in subtopics:
            sub_title = sub.get("title", "")
            query = _build_subtopic_query(sub_title, lesson_title)

            logger.debug(
                "[vector_retriever] Subtopic=%r  query=%r  document_id=%s",
                sub_title[:50], query[:120], document_id,
            )

            raw_sub: list[dict] = []
            error_msg: str | None = None
            t_start = time.perf_counter()
            try:
                raw_sub = self._service.retrieve_for_subtopic(
                    subtopic_query=query,
                    document_id=document_id,
                    top=search_top_k,
                )
            except Exception as exc:
                error_msg = str(exc)
                logger.warning(
                    "[vector_retriever] Subtopic search failed for %r: %s",
                    sub_title[:50], exc,
                )
            finally:
                latency_ms = (time.perf_counter() - t_start) * 1000
                try:
                    write_retrieval_trace(RetrievalTrace(
                        agent="SECTION_MAPPER",
                        retrieval_type="subtopic_vector" if not error_msg else "subtopic_vector_failed",
                        query=query,
                        result_count=len(raw_sub),
                        latency_ms=latency_ms,
                        document_id=document_id,
                        error=error_msg,
                        metadata={
                            "subtopic_title": sub_title[:120],
                            "lesson_title": lesson_title[:120],
                            "top_per_subtopic": top_per_subtopic,
                            "vector_field": EMBEDDING_CONTENT_VECTOR_FIELD,
                        },
                    ))
                except Exception:
                    pass

            if raw_sub:
                chunks = _parse_search_results(raw_sub)
                chunks = _filter_chunks_by_source_files(chunks, source_files)
                ordered = _sort_by_similarity_score(chunks)
                seeds = _dedupe_and_select_chunks(
                    ordered,
                    max_chunks=seed_count,
                    used_chunk_ids=set(),
                    used_text_fingerprints=set(),
                )
                if expand_sections and seeds:
                    selected = _expand_matched_sections(
                        self._service,
                        seeds,
                        max_words=max_source_words,
                    )
                else:
                    selected = _dedupe_within_subtopic(seeds)

                if len(selected) < seed_count and not expand_sections:
                    logger.info(
                        "[vector_retriever] Subtopic=%r → %d unique chunks after dedupe "
                        "(requested=%d, azure_candidates=%d)",
                        sub_title[:50],
                        len(selected),
                        seed_count,
                        len(ordered),
                    )
                sub["matched_chunks"] = [c.as_dict() for c in selected]

                has_reranker = any(
                    c.source_metadata.get("reranker_score") is not None
                    for c in selected[:1]
                )
                top_score = selected[0].similarity_score if selected else None
                threshold = (
                    max(_MIN_ABSOLUTE_THRESHOLD, top_score * _DYNAMIC_THRESHOLD_RATIO)
                    if top_score is not None else None
                )
                logger.debug(
                    "[vector_retriever] Subtopic=%r → %d chunks  "
                    "scores=%s  semantic_ranked=%s",
                    sub_title[:50],
                    len(selected),
                    [f"{c.similarity_score:.3f}" for c in selected],
                    has_reranker,
                )
                # Emit scored trace for this subtopic
                try:
                    write_retrieval_trace(RetrievalTrace(
                        agent="SECTION_MAPPER",
                        retrieval_type="subtopic_vector_scored",
                        query=query,
                        result_count=len(selected),
                        latency_ms=0,
                        top_score=top_score,
                        threshold=threshold,
                        has_semantic_ranker=has_reranker,
                        document_id=document_id,
                        metadata={
                            "subtopic_title": sub_title[:120],
                            "lesson_title": lesson_title[:120],
                            "raw_result_count": len(raw_sub),
                        },
                    ))
                except Exception:
                    pass
            else:
                sub["matched_chunks"] = []
                logger.warning(
                    "[vector_retriever] Subtopic=%r returned 0 chunks from vector retrieval.",
                    sub_title[:50],
                )
                try:
                    write_retrieval_trace(RetrievalTrace(
                        agent="SECTION_MAPPER",
                        retrieval_type="subtopic_empty",
                        query=sub_title,
                        result_count=0,
                        latency_ms=0,
                        document_id=document_id,
                        metadata={
                            "subtopic_title": sub_title[:120],
                            "lesson_title": lesson_title[:120],
                            "lesson_pool_size": len(lesson_chunks),
                        },
                    ))
                except Exception:
                    pass

        return subtopics


# ── Text aggregation ────────────────────────────────────────────────────────────

def merge_to_raw_text(chunks: list[VectorChunk], separator: str = "\n\n") -> str:
    """
    Merge a list of VectorChunks into a single coherent text block.

    Chunks should already be sorted by document order (as returned by
    distribute_to_subtopics).  Deduplicates identical paragraphs that
    occasionally appear when chunk boundaries overlap.

    Args:
        chunks:    Ordered list of VectorChunk objects.
        separator: String placed between chunks (default: blank line).

    Returns:
        Single string ready to pass to A2 as source_text.
    """
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in chunks:
        text = chunk.raw_text.strip()
        if text and text not in seen:
            parts.append(text)
            seen.add(text)
    return separator.join(parts)


# ── Factory ─────────────────────────────────────────────────────────────────────

_retriever_cache: VectorRetriever | None = None
_retriever_attempted: bool = False


def get_retriever() -> VectorRetriever | None:
    """
    Return a VectorRetriever backed by Azure AI Search embedding_content similarity.

    Caches the result after the first call so subsequent lessons share a single
    retriever instance.
    Returns None when Azure Search or embeddings are unavailable — the caller
    (mapper.py) will leave matched_chunks empty.
    """
    global _retriever_cache, _retriever_attempted
    if _retriever_attempted:
        return _retriever_cache

    _retriever_attempted = True
    try:
        from lectora_backend.ingestion.service import IngestionOrchestrator
        service = IngestionOrchestrator.get_instance().build_retrieval_service()
        if service is None:
            logger.warning(
                "[vector_retriever] Azure AI Search / embeddings not configured — "
                "subtopics will have no matched_chunks."
            )
            return None
        _retriever_cache = VectorRetriever(service)
        logger.info(
            "[vector_retriever] Retriever initialised for %s similarity search.",
            EMBEDDING_CONTENT_VECTOR_FIELD,
        )
    except Exception as exc:
        logger.warning(
            "[vector_retriever] Could not initialise retriever: %s — "
            "section mapper will run without vector retrieval.", exc,
        )
        _retriever_cache = None

    return _retriever_cache
