"""Multi-strategy image-to-section resolver."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.ai.agents.content_generation_agent.section_mapper.step_01_map_sections.utils.vector_retriever import (
    VectorChunk,
    VectorRetriever,
    get_retriever,
)

from ..constants.config import (
    HEADING_ANCHOR_MIN_SCORE,
    MIN_WEIGHTED_SCORE,
    PARA_RANGE_MATCH_SCORE,
    PARA_RANGE_MIN_SCORE,
    STRATEGY_WEIGHTS_ESTIMATED_PARA,
    STRATEGY_WEIGHTS_RELIABLE_PARA,
    TEXT_FUZZY_MIN_SCORE,
    VECTOR_MIN_SCORE,
)
from .text_similarity import best_fuzzy_match, fuzzy_ratio, join_non_empty, normalize_title

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SectionMatch:
    section_id: str
    strategy: str
    score: float
    weighted_score: float


class ImageSectionResolver:
    """Resolve the best TO section for a source image using layered signals."""

    def __init__(
        self,
        sections: list[dict[str, Any]],
        *,
        heading_tree: list[dict[str, Any]] | None = None,
        source_document: str | None = None,
        para_ranges_estimated: bool = False,
        vector_retriever: VectorRetriever | None = None,
        document_id: str | None = None,
    ) -> None:
        self._sections = sections
        self._heading_tree = heading_tree or []
        self._source_document = (source_document or "").strip().lower()
        self._weights = (
            STRATEGY_WEIGHTS_ESTIMATED_PARA
            if para_ranges_estimated
            else STRATEGY_WEIGHTS_RELIABLE_PARA
        )
        self._vector_retriever = vector_retriever
        self._document_id = document_id
        self._section_titles = [str(section.get("heading") or "") for section in sections]
        self._section_contexts = [self._section_context_text(section) for section in sections]

    def resolve(self, image: dict[str, Any]) -> SectionMatch | None:
        if self._is_source_mismatch(image):
            return None

        candidates: list[SectionMatch] = []
        candidates.extend(self._match_by_heading_anchor(image))
        candidates.extend(self._match_by_text_fuzzy(image))
        candidates.extend(self._match_by_vector_search(image))
        candidates.extend(self._match_by_para_range(image))

        if not candidates:
            return None

        best = max(candidates, key=lambda match: match.weighted_score)
        if self._is_acceptable(best):
            return best
        return None

    def _is_acceptable(self, match: SectionMatch) -> bool:
        if match.weighted_score >= MIN_WEIGHTED_SCORE:
            return True
        min_raw_scores = {
            "heading_anchor": HEADING_ANCHOR_MIN_SCORE,
            "text_fuzzy": TEXT_FUZZY_MIN_SCORE,
            "vector_search": VECTOR_MIN_SCORE,
            "para_range": PARA_RANGE_MIN_SCORE,
        }
        return match.score >= min_raw_scores.get(match.strategy, 1.0)

    def _is_source_mismatch(self, image: dict[str, Any]) -> bool:
        if not self._source_document:
            return False
        image_source = str(image.get("source_document") or "").strip().lower()
        return bool(image_source and image_source != self._source_document)

    def _match_by_heading_anchor(self, image: dict[str, Any]) -> list[SectionMatch]:
        heading_text = self._resolve_heading_text(image)
        if not heading_text:
            return []

        idx, score = best_fuzzy_match(heading_text, self._section_titles)
        if idx < 0 or score < HEADING_ANCHOR_MIN_SCORE:
            return []

        section = self._sections[idx]
        return [self._build_match(section["id"], "heading_anchor", score)]

    def _match_by_text_fuzzy(self, image: dict[str, Any]) -> list[SectionMatch]:
        query = self._image_context_text(image)
        if not query:
            return []

        best_idx = -1
        best_score = 0.0
        for idx, context in enumerate(self._section_contexts):
            score = fuzzy_ratio(query, context)
            subtopics = self._section_subtopics(self._sections[idx])
            for subtopic in subtopics:
                score = max(score, fuzzy_ratio(query, subtopic))
            if score > best_score:
                best_idx = idx
                best_score = score

        if best_idx < 0 or best_score < TEXT_FUZZY_MIN_SCORE:
            return []

        return [self._build_match(self._sections[best_idx]["id"], "text_fuzzy", best_score)]

    def _match_by_vector_search(self, image: dict[str, Any]) -> list[SectionMatch]:
        retriever = self._vector_retriever if self._vector_retriever is not None else get_retriever()
        if retriever is None:
            return []

        query = self._image_context_text(image)
        if not query:
            return []

        try:
            chunks = retriever.retrieve_for_lesson(
                lesson_title=query,
                document_id=self._document_id,
                top=5,
            )
        except Exception as exc:
            logger.debug("[A1] Vector image match skipped: %s", exc)
            return []

        if not chunks:
            return []

        best_idx = -1
        best_score = 0.0
        for idx, title in enumerate(self._section_titles):
            section_score = self._score_section_against_chunks(title, self._sections[idx], chunks)
            if section_score > best_score:
                best_idx = idx
                best_score = section_score

        if best_idx < 0 or best_score < VECTOR_MIN_SCORE:
            return []

        return [self._build_match(self._sections[best_idx]["id"], "vector_search", best_score)]

    def _match_by_para_range(self, image: dict[str, Any]) -> list[SectionMatch]:
        try:
            image_para = int(image["para_idx"])
        except (KeyError, TypeError, ValueError):
            return []

        for section in self._sections:
            para_start = int(section.get("para_start", 0))
            para_end = int(section.get("para_end", para_start))
            if para_start <= image_para <= para_end:
                return [self._build_match(section["id"], "para_range", PARA_RANGE_MATCH_SCORE)]

        return []

    def _build_match(self, section_id: str, strategy: str, score: float) -> SectionMatch:
        weight = self._weights.get(strategy, 0.5)
        return SectionMatch(
            section_id=section_id,
            strategy=strategy,
            score=score,
            weighted_score=score * weight,
        )

    def _resolve_heading_text(self, image: dict[str, Any]) -> str:
        heading_context = str(image.get("heading_context") or "").strip()
        if heading_context:
            return heading_context

        try:
            image_para = int(image["para_idx"])
        except (KeyError, TypeError, ValueError):
            return ""

        image_source = str(image.get("source_document") or "").strip().lower()
        active_heading = self._active_heading_at_para(image_para, image_source)
        return str(active_heading.get("text") or "").strip() if active_heading else ""

    def _active_heading_at_para(
        self,
        para_idx: int,
        source_document: str,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for heading in self._heading_tree:
            heading_para = heading.get("para_idx")
            if heading_para is None:
                continue
            try:
                heading_idx = int(heading_para)
            except (TypeError, ValueError):
                continue
            if heading_idx < 0 or heading_idx > para_idx:
                continue

            heading_source = str(heading.get("source") or "").strip().lower()
            if source_document and heading_source and heading_source != source_document:
                continue
            candidates.append(heading)

        if not candidates:
            return None
        return max(candidates, key=lambda item: int(item.get("para_idx", -1)))

    @staticmethod
    def _image_context_text(image: dict[str, Any]) -> str:
        return join_non_empty([
            str(image.get("caption") or ""),
            str(image.get("heading_context") or ""),
            str(image.get("alt_text") or ""),
        ])

    @staticmethod
    def _section_subtopics(section: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for subtopic in section.get("outline_subtopics") or section.get("paragraphs") or []:
            if isinstance(subtopic, dict):
                text = str(subtopic.get("title") or subtopic.get("name") or "").strip()
            else:
                text = str(subtopic).strip()
            if text:
                values.append(text)
        return values

    def _section_context_text(self, section: dict[str, Any]) -> str:
        return join_non_empty([
            str(section.get("heading") or ""),
            str(section.get("outline_content") or ""),
            *self._section_subtopics(section),
        ])

    @staticmethod
    def _score_section_against_chunks(
        section_title: str,
        section: dict[str, Any],
        chunks: list[VectorChunk],
    ) -> float:
        best = 0.0
        for chunk in chunks:
            chunk_title = str(chunk.source_metadata.get("title") or "")
            chunk_summary = str(chunk.source_metadata.get("summary") or "")
            chunk_text = chunk.raw_text[:400]
            title_score = fuzzy_ratio(section_title, chunk_title)
            summary_score = fuzzy_ratio(section_title, chunk_summary)
            text_score = fuzzy_ratio(normalize_title(section_title), normalize_title(chunk_text))
            subtopic_score = 0.0
            for subtopic in ImageSectionResolver._section_subtopics(section):
                subtopic_score = max(
                    subtopic_score,
                    fuzzy_ratio(subtopic, chunk_title),
                    fuzzy_ratio(subtopic, chunk_summary),
                )
            chunk_score = max(title_score, summary_score, text_score, subtopic_score)
            best = max(best, chunk_score * chunk.similarity_score)
        return best


def resolve_image_to_section(
    image: dict[str, Any],
    sections: list[dict[str, Any]],
    *,
    heading_tree: list[dict[str, Any]] | None = None,
    source_document: str | None = None,
    para_ranges_estimated: bool = False,
    vector_retriever: VectorRetriever | None = None,
    document_id: str | None = None,
) -> SectionMatch | None:
    return ImageSectionResolver(
        sections,
        heading_tree=heading_tree,
        source_document=source_document,
        para_ranges_estimated=para_ranges_estimated,
        vector_retriever=vector_retriever,
        document_id=document_id,
    ).resolve(image)
