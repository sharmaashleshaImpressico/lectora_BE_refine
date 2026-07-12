"""Editor snapshot → canonical A2 transform with pipeline metadata merge.

Pure in-memory service for Phase 2 / Save-to-Azure. No DB, Azure, or filesystem
I/O. Builds on ``editor_snapshot_mapper`` helpers and ports legacy
``sync_course_content`` merge semantics without ``shared_state.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai.agents.content_generation_agent.models import A2Output, A2Stats
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.editor_snapshot_mapper import (
    body_paragraphs_with_existing_fallback,
    estimate_read_time_minutes,
    frontend_body_paragraphs,
    index_existing_a2_sections,
    is_introduction_section,
    map_images,
    merge_pipeline_section_metadata,
    plain_text_from_body_or_content,
    sorted_sections,
    word_count_for_section,
)

_ALLOWED_LEVELS = frozenset({1, 2, 3})


class EditorCourseTransformationError(ValueError):
    """Raised when the editor snapshot fails structural validation."""


@dataclass(frozen=True)
class EditorTransformationResult:
    """Canonical editor-save output for persistence / DOCX in later phases."""

    canonical_a2: dict[str, Any]
    learning_objectives: list[str]
    course_title: str
    meta: dict[str, Any]


class EditorCourseTransformationService:
    """Transform a full editor snapshot into merged canonical A2 content."""

    def transform(
        self,
        snapshot: RenderDocxRequest,
        existing_a2: dict[str, Any] | None = None,
        existing_learning_objectives: list[str] | None = None,
    ) -> EditorTransformationResult:
        existing = dict(existing_a2 or {})
        existing_sections = existing.get("sections") or []
        if not isinstance(existing_sections, list):
            existing_sections = []
        existing_by_id = index_existing_a2_sections(existing_sections)

        self._validate_tree(list(snapshot.sections))

        course_description = str(existing.get("course_description") or "")
        course_conclusion = str(existing.get("course_conclusion") or "")
        learning_objectives = list(existing_learning_objectives or [])
        saw_learning_objectives_section = False
        a2_sections: list[dict[str, Any]] = []

        def process(
            sec: CourseSectionInput,
            *,
            parent_lesson: str = "",
            parent_level: int | None = None,
        ) -> None:
            nonlocal course_description, course_conclusion
            nonlocal saw_learning_objectives_section, learning_objectives

            stype = (sec.section_type or "content").strip().lower()

            if stype == "learning-objectives":
                saw_learning_objectives_section = True
                learning_objectives = self._extract_learning_objectives(sec)
                return

            if stype == "conclusion":
                course_conclusion = plain_text_from_body_or_content(sec)
                return

            if is_introduction_section(sec):
                course_description = plain_text_from_body_or_content(sec)
                return

            # Content / chapter nodes require stable IDs and valid levels.
            section_id = (sec.id or "").strip()
            if not section_id:
                raise EditorCourseTransformationError(
                    f"Content section '{sec.title or '(untitled)'}' is missing a stable id."
                )
            if sec.level not in _ALLOWED_LEVELS:
                raise EditorCourseTransformationError(
                    f"Section '{section_id}' has unsupported level {sec.level}; "
                    "allowed levels are 1, 2, or 3."
                )
            if parent_level is not None and sec.level <= parent_level:
                raise EditorCourseTransformationError(
                    f"Unsupported hierarchy: section '{section_id}' has level "
                    f"{sec.level} under parent level {parent_level}."
                )

            self._validate_paragraphs(sec)

            fe_body = frontend_body_paragraphs(sec)
            content = (sec.content or "").strip()
            # Parent-overview detection uses FE emptiness only (before merge).
            is_parent = (
                sec.level == 1 and bool(sec.children) and not content and not fe_body
            )

            existing_sec = existing_by_id.get(section_id)
            body = body_paragraphs_with_existing_fallback(sec, existing_sec)
            lesson = sec.title.strip() if sec.level == 1 else parent_lesson

            a2_sec: dict[str, Any] = {
                "section_id": section_id,
                "heading": (sec.title or "").strip() or "Untitled Section",
                "outline_lesson": lesson or (sec.title or "").strip(),
                "level": sec.level,
                "body_paragraphs": body,
                "word_count": word_count_for_section(sec, body),
                "has_knowledge_check": bool(sec.has_knowledge_check),
                "is_parent_overview": is_parent,
                "status": "editor_saved",
            }
            merge_pipeline_section_metadata(
                a2_sec,
                existing_sec,
                frontend_images=map_images(sec.images),
            )
            a2_sections.append(a2_sec)

            child_lesson = sec.title.strip() if sec.level == 1 else parent_lesson
            for _, child in sorted_sections(list(sec.children)):
                process(
                    child,
                    parent_lesson=child_lesson,
                    parent_level=sec.level,
                )

        for _, section in sorted_sections(list(snapshot.sections)):
            process(section)

        if not a2_sections:
            raise EditorCourseTransformationError(
                "No content sections in the submitted snapshot. "
                "Include at least one chapter or content section."
            )

        snapshot_title = (snapshot.course_title or "").strip()
        existing_title = str(existing.get("course_title") or "").strip()
        if snapshot_title:
            course_title = snapshot_title
        elif existing_title:
            course_title = existing_title
        else:
            course_title = "Untitled Course"

        if not saw_learning_objectives_section:
            learning_objectives = list(existing_learning_objectives or [])

        meta = self._build_meta(a2_sections)
        run_id = str(existing.get("run_id") or "").strip() or "editor-save"

        a2_output = A2Output(
            status="editor_saved",
            run_id=run_id,
            course_title=course_title,
            sections=a2_sections,
            stats=A2Stats(
                generated=len(a2_sections),
                total_words=int(meta["totalWordCount"]),
            ),
            course_description=course_description,
            course_conclusion=course_conclusion,
        )
        canonical = a2_output.model_dump(mode="json")
        # Drop derived filesystem pointers from prior pipeline runs.
        canonical["study_guide_docx"] = None
        canonical["generated_content_json"] = None

        return EditorTransformationResult(
            canonical_a2=canonical,
            learning_objectives=list(learning_objectives),
            course_title=course_title,
            meta=meta,
        )

    def _build_meta(self, a2_sections: list[dict[str, Any]]) -> dict[str, Any]:
        content_secs = [s for s in a2_sections if not s.get("is_parent_overview")]
        total_words = sum(int(s.get("word_count") or 0) for s in content_secs)
        section_count = len(content_secs)
        chapter_count = sum(1 for s in content_secs if int(s.get("level") or 0) == 1)
        return {
            "totalWordCount": total_words,
            "sectionCount": section_count,
            "chapterCount": chapter_count,
            "estimatedReadTime": estimate_read_time_minutes(total_words),
        }

    def _validate_tree(self, sections: list[CourseSectionInput]) -> None:
        seen: set[str] = set()

        def walk(sec: CourseSectionInput) -> None:
            sid = (sec.id or "").strip()
            if sid:
                if sid in seen:
                    raise EditorCourseTransformationError(
                        f"Duplicate section id '{sid}' in editor snapshot."
                    )
                seen.add(sid)
            self._validate_paragraphs(sec)
            for child in sec.children:
                walk(child)

        for sec in sections:
            walk(sec)

    @staticmethod
    def _validate_paragraphs(sec: CourseSectionInput) -> None:
        for idx, block in enumerate(sec.paragraphs or []):
            if not isinstance(block, dict):
                raise EditorCourseTransformationError(
                    f"Section '{sec.id or sec.title}' has malformed paragraphs[{idx}] "
                    f"(expected object, got {type(block).__name__})."
                )

    @staticmethod
    def _extract_learning_objectives(sec: CourseSectionInput) -> list[str]:
        objectives = [str(lo).strip() for lo in sec.learning_objectives if str(lo).strip()]
        if objectives:
            return objectives
        if (sec.content or "").strip():
            return [
                line.strip(" -\t")
                for line in sec.content.splitlines()
                if line.strip()
            ]
        # Explicit empty LO section clears objectives.
        return []


__all__ = [
    "EditorCourseTransformationError",
    "EditorCourseTransformationService",
    "EditorTransformationResult",
]
