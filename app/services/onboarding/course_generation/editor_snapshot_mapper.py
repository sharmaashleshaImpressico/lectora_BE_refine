"""Pure editor-snapshot → A2Output mapper for render-only DOCX generation.

Ports the reverse-mapping behaviour from the legacy ``sync_course_content`` flow
without any disk writes, repository calls, Azure uploads, or job updates.

The submitted frontend ``CourseContent`` tree is the sole source of truth.
"""

from __future__ import annotations

from typing import Any

from app.ai.agents.content_generation_agent.models import A2Output, A2Stats
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)


class EmptyCourseContentError(ValueError):
    """Raised when the snapshot has nothing the DOCX builder can render."""


def _sorted_sections(
    sections: list[CourseSectionInput],
) -> list[tuple[int, CourseSectionInput]]:
    """Prefer explicit ``order`` when present; otherwise keep array order."""
    if not sections:
        return []
    # Stable sort: equal orders preserve relative array order.
    return sorted(enumerate(sections), key=lambda pair: (pair[1].order, pair[0]))


def _body_paragraphs_from_input(sec: CourseSectionInput) -> list[dict[str, Any]]:
    """Legacy precedence: structured paragraphs win over plain content.

    Avoids duplicating text when the editor sends both ``content`` and
    ``paragraphs`` for the same section.
    """
    if sec.paragraphs:
        return [dict(p) for p in sec.paragraphs]
    content = (sec.content or "").strip()
    if content:
        return [{"type": "text", "content": content}]
    return []


def _map_images(images: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for img in images or []:
        if not isinstance(img, dict):
            continue
        mapped.append(
            {
                "media_filename": img.get("fileName")
                or img.get("media_filename")
                or img.get("file_name")
                or "",
                "path": img.get("path") or img.get("blobPath") or img.get("blob_path") or "",
                "caption": img.get("caption") or "",
                "alt_text": img.get("altText") or img.get("alt_text") or "",
            }
        )
    return mapped


def _is_introduction_section(sec: CourseSectionInput) -> bool:
    """Course intro / overview front-matter (not a chapter head).

    Refine's ``_map_a2_output`` emits Introduction as ``sectionType: overview``
    with no children, while chapter heads are also ``overview`` but *with*
    children. Legacy sync treated every overview as course_description — that
    would drop chapters — so we only map childless overview/intro nodes.
    """
    stype = (sec.section_type or "").strip().lower()
    if stype not in {"overview", "introduction"}:
        return False
    if sec.children:
        return False
    title = (sec.title or "").strip().lower()
    sid = (sec.id or "").strip().lower()
    if "introduction" in title or "introduction" in sid:
        return True
    if title in {"overview", "course overview"} or "overview" in sid:
        return True
    # Childless overview from refine / FE — treat as course description.
    return stype == "overview"


def map_editor_snapshot_to_a2(
    payload: RenderDocxRequest,
) -> tuple[A2Output, list[str]]:
    """Convert a nested editor snapshot into ``A2Output`` + learning objectives.

    Mapping rules (ported from legacy sync, adapted for refine's overview chapters):

    - ``learning-objectives`` → learning_objectives list (not a body section)
    - ``conclusion`` → ``course_conclusion``
    - childless ``overview`` / introduction → ``course_description``
    - all other nodes → flat A2 ``sections`` (depth-first), preserving order
    """
    course_title = (payload.course_title or "").strip() or "Untitled Course"
    course_description = ""
    course_conclusion = ""
    learning_objectives: list[str] = []
    a2_sections: list[dict[str, Any]] = []

    def process(sec: CourseSectionInput, parent_lesson: str = "") -> None:
        nonlocal course_description, course_conclusion

        stype = (sec.section_type or "content").strip().lower()

        if stype == "learning-objectives":
            learning_objectives.extend(
                lo for lo in sec.learning_objectives if str(lo).strip()
            )
            # Also accept LO text embedded as content / bullet paragraphs.
            if not sec.learning_objectives and (sec.content or "").strip():
                learning_objectives.extend(
                    line.strip(" -\t")
                    for line in sec.content.splitlines()
                    if line.strip()
                )
            return

        if stype == "conclusion":
            paragraphs = _body_paragraphs_from_input(sec)
            if paragraphs:
                text_parts = [
                    str(p.get("content") or "").strip()
                    for p in paragraphs
                    if p.get("type", "text") == "text" and p.get("content")
                ]
                course_conclusion = "\n\n".join(text_parts) or (sec.content or "").strip()
            else:
                course_conclusion = (sec.content or "").strip()
            return

        if _is_introduction_section(sec):
            paragraphs = _body_paragraphs_from_input(sec)
            if paragraphs:
                text_parts = [
                    str(p.get("content") or "").strip()
                    for p in paragraphs
                    if p.get("type", "text") == "text" and p.get("content")
                ]
                course_description = "\n\n".join(text_parts) or (sec.content or "").strip()
            else:
                course_description = (sec.content or "").strip()
            return

        content = (sec.content or "").strip()
        body = _body_paragraphs_from_input(sec)
        wc = sec.word_count or (
            len(content.split()) if content else sum(
                len(str(p.get("content") or "").split()) for p in body
            )
        )
        is_parent = sec.level == 1 and bool(sec.children) and not content and not body
        lesson = sec.title.strip() if sec.level == 1 else parent_lesson

        a2_sec: dict[str, Any] = {
            "section_id": sec.id,
            "heading": (sec.title or "").strip() or "Untitled Section",
            "outline_lesson": lesson or (sec.title or "").strip(),
            "level": sec.level if sec.level in (1, 2, 3) else 2,
            "body_paragraphs": body,
            "word_count": wc,
            "has_knowledge_check": bool(sec.has_knowledge_check),
            "is_parent_overview": is_parent,
            "status": "editor_render",
            "images": _map_images(sec.images),
        }
        a2_sections.append(a2_sec)

        child_lesson = sec.title.strip() if sec.level == 1 else parent_lesson
        for _, child in _sorted_sections(list(sec.children)):
            process(child, parent_lesson=child_lesson)

    for _, section in _sorted_sections(list(payload.sections)):
        process(section)

    if not a2_sections and not course_description.strip() and not course_conclusion.strip():
        raise EmptyCourseContentError(
            "No renderable course content in the submitted snapshot."
        )

    # DOCX builder requires at least one generated section. If the snapshot only
    # has intro/conclusion front-matter, synthesise a minimal body section so
    # rendering can still succeed with overview/conclusion metadata.
    if not a2_sections:
        raise EmptyCourseContentError(
            "No renderable course sections in the submitted snapshot. "
            "Include at least one chapter or content section."
        )

    total_words = sum(int(s.get("word_count") or 0) for s in a2_sections)
    a2_output = A2Output(
        status="editor_render",
        run_id="render-docx",
        course_title=course_title,
        sections=a2_sections,
        stats=A2Stats(generated=len(a2_sections), total_words=total_words),
        course_description=course_description,
        course_conclusion=course_conclusion,
    )
    return a2_output, learning_objectives


__all__ = [
    "EmptyCourseContentError",
    "map_editor_snapshot_to_a2",
]
