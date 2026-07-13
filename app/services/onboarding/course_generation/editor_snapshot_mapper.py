"""Pure editor-snapshot → A2Output helpers for render and editor-save transforms.

Ports reverse-mapping behaviour from the legacy ``sync_course_content`` flow
without disk writes, repository calls, Azure uploads, or job updates.

``map_editor_snapshot_to_a2`` treats the submitted snapshot as the sole source
of truth (render-docx). ``EditorCourseTransformationService`` builds on these
helpers and merges pipeline-owned metadata from an existing A2 payload.
"""

from __future__ import annotations

from typing import Any

from app.ai.agents.content_generation_agent.models import A2Output, A2Stats
from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)

# Frontend-owned A2 section fields (always taken from the editor snapshot).
FRONTEND_OWNED_SECTION_FIELDS: frozenset[str] = frozenset(
    {
        "section_id",
        "heading",
        "outline_lesson",
        "level",
        "body_paragraphs",
        "word_count",
        "has_knowledge_check",
        "is_parent_overview",
        "status",
    }
)

# Pipeline-owned fields preserved from a matching existing A2 section when the
# editor does not supply a replacement (images: FE wins only when non-empty).
PIPELINE_OWNED_SECTION_FIELDS: frozenset[str] = frozenset(
    {
        "images",
        "maps_to_objectives",
        "subtopics",
        "source_refs",
        "provenance",
        "provenance_log",
        "source_chunks",
        "generation_metadata",
        "attempt_count",
        "attempts",
        "maps_to_required_topics",
        "kc_plan",
        "interactive_elements",
        "outline_section_id",
        "content_hash",
        "writer_model",
        "repair_history",
    }
)


class EmptyCourseContentError(ValueError):
    """Raised when the snapshot has nothing the DOCX builder can render."""


def sorted_sections(
    sections: list[CourseSectionInput],
) -> list[tuple[int, CourseSectionInput]]:
    """Prefer explicit ``order`` when present; otherwise keep array order."""
    if not sections:
        return []
    # Stable sort: equal orders preserve relative array order.
    return sorted(enumerate(sections), key=lambda pair: (pair[1].order, pair[0]))


# Backward-compatible private alias used by older call sites / tests.
_sorted_sections = sorted_sections


def frontend_body_paragraphs(sec: CourseSectionInput) -> list[dict[str, Any]]:
    """Body from the editor only: paragraphs win over plain content."""
    if sec.paragraphs:
        return [dict(p) for p in sec.paragraphs]
    content = (sec.content or "").strip()
    if content:
        return [{"type": "text", "content": content}]
    return []


def body_paragraphs_with_existing_fallback(
    sec: CourseSectionInput,
    existing: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Legacy sync body priority: paragraphs → content → existing body → []."""
    fe_body = frontend_body_paragraphs(sec)
    if fe_body:
        return fe_body
    if existing:
        return list(existing.get("body_paragraphs") or [])
    return []


def _body_paragraphs_from_input(sec: CourseSectionInput) -> list[dict[str, Any]]:
    """Render-only body (no existing-A2 fallback)."""
    return frontend_body_paragraphs(sec)


def map_images(images: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
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


_map_images = map_images


def is_introduction_section(sec: CourseSectionInput) -> bool:
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


_is_introduction_section = is_introduction_section


def index_existing_a2_sections(
    existing_sections: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Build stable-id → existing A2 section lookup (``id`` / ``section_id``)."""
    by_id: dict[str, dict[str, Any]] = {}
    for i, sec in enumerate(existing_sections or []):
        if not isinstance(sec, dict):
            continue
        real_id = str(sec.get("section_id") or "").strip()
        if real_id:
            by_id[real_id] = sec
        # Legacy fallback key when section_id was empty.
        fallback = str(sec.get("id") or "").strip() or f"idx-{i}"
        by_id.setdefault(fallback, sec)
    return by_id


def merge_pipeline_section_metadata(
    a2_sec: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    frontend_images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach pipeline-owned fields from a matching existing section.

    Images: non-empty frontend list wins; otherwise preserve existing images.
    Other pipeline keys are copied when present on the existing section and not
    already set as frontend-owned fields on ``a2_sec``.
    """
    if frontend_images:
        a2_sec["images"] = frontend_images
    elif existing:
        a2_sec["images"] = list(existing.get("images") or [])
    else:
        a2_sec.setdefault("images", [])

    if not existing:
        return a2_sec

    for key in PIPELINE_OWNED_SECTION_FIELDS:
        if key == "images":
            continue
        if key in FRONTEND_OWNED_SECTION_FIELDS:
            continue
        if key in existing:
            a2_sec[key] = existing[key]

    # Preserve any additional non-frontend keys from the pipeline section so
    # unknown provenance fields survive editor saves.
    for key, value in existing.items():
        if key in FRONTEND_OWNED_SECTION_FIELDS or key in a2_sec:
            continue
        a2_sec[key] = value

    return a2_sec


def estimate_read_time_minutes(total_words: int) -> str:
    """Legacy sync read-time string (integer minutes via floor division)."""
    if total_words <= 0:
        return "—"
    read_minutes = max(1, total_words // 200)
    if read_minutes < 60:
        return f"{read_minutes} min read"
    return f"{read_minutes // 60}h {read_minutes % 60}m"


def word_count_for_section(
    sec: CourseSectionInput,
    body: list[dict[str, Any]],
) -> int:
    if sec.word_count:
        return int(sec.word_count)
    content = (sec.content or "").strip()
    if content:
        return len(content.split())
    total = 0
    for block in body:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "text")
        if btype in ("text", "heading_3", "heading_4", "important_callout", "callout"):
            total += len(str(block.get("content") or "").split())
        elif btype in ("bullet_list", "sub_bullet_list", "numbered_list"):
            for item in block.get("items") or []:
                total += len(str(item).split())
    return total


def plain_text_from_body_or_content(sec: CourseSectionInput) -> str:
    """Flatten FE body/content for course_description / conclusion fields."""
    body = frontend_body_paragraphs(sec)
    if body:
        text_parts = [
            str(p.get("content") or "").strip()
            for p in body
            if isinstance(p, dict)
            and p.get("type", "text") == "text"
            and p.get("content")
        ]
        if text_parts:
            return "\n\n".join(text_parts)
    return (sec.content or "").strip()


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
            course_conclusion = plain_text_from_body_or_content(sec)
            return

        if is_introduction_section(sec):
            course_description = plain_text_from_body_or_content(sec)
            return

        content = (sec.content or "").strip()
        body = frontend_body_paragraphs(sec)
        wc = word_count_for_section(sec, body)
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
            "images": map_images(sec.images),
        }
        a2_sections.append(a2_sec)

        child_lesson = sec.title.strip() if sec.level == 1 else parent_lesson
        for _, child in sorted_sections(list(sec.children)):
            process(child, parent_lesson=child_lesson)

    for _, section in sorted_sections(list(payload.sections)):
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
    "FRONTEND_OWNED_SECTION_FIELDS",
    "PIPELINE_OWNED_SECTION_FIELDS",
    "body_paragraphs_with_existing_fallback",
    "estimate_read_time_minutes",
    "frontend_body_paragraphs",
    "index_existing_a2_sections",
    "is_introduction_section",
    "map_editor_snapshot_to_a2",
    "map_images",
    "merge_pipeline_section_metadata",
    "plain_text_from_body_or_content",
    "sorted_sections",
    "word_count_for_section",
]
