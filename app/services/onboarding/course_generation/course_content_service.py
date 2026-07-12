"""Resolves a completed job's generated course into the shape the frontend editor loads.

The pipeline persists two relevant artifacts per job (see `pipeline_runner`):

* ``course_content.json`` — the rich A2 writer output (headings + body_paragraphs
  + images). This is what the editor is designed around and is preferred here.
* ``enriched_sections.json`` — the thinner section-mapper output (titles +
  subtopics, no paragraph blocks). Used as a fallback for jobs generated before
  ``course_content.json`` was persisted, so they still render structure.

Both are read back from blob (or the local upload store when Azure is not
configured) and mapped into the camelCase ``CourseContent`` payload the frontend
binds to (``types/editor.ts``).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.config import azure_storage_settings
from app.core.storage.azure_blob_client import LocalUploadStore
from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_ENRICHED_SECTIONS,
)
from app.models.onboarding.course_basic.course_basic import CourseBasic
from app.models.onboarding.course_run.course_run import CourseRun
from app.repositories.course_generation.course_generation_job_artifact_repository import (
    CourseGenerationJobArtifactRepository,
)
from app.services.onboarding.course_generation.artifact_service import ArtifactsBlobClient

logger = logging.getLogger(__name__)


class CourseContentNotFoundError(Exception):
    """Raised when a job has no readable generated-course artifact."""


class CourseContentService:
    """Reads a job's generated-course artifact and maps it for the editor."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.artifacts = CourseGenerationJobArtifactRepository(db)
        self._blob_client = ArtifactsBlobClient(azure_storage_settings)
        self._local_store = LocalUploadStore(azure_storage_settings)

    def get_course_content(self, job_id: str) -> dict:
        """Return the `CourseContent` payload for a completed job.

        Raises `CourseContentNotFoundError` when no generated-course artifact
        exists yet (e.g. the job hasn't finished, or failed before writing one).
        """
        artifacts = self.artifacts.list_by_job(job_id)
        by_type = {a.artifact_type: a for a in artifacts}

        course_type = self._resolve_course_type(job_id, artifacts)

        content_artifact = by_type.get(ARTIFACT_TYPE_COURSE_CONTENT)
        if content_artifact is not None:
            payload = self._read_json(content_artifact.blob_path)
            return _map_a2_output(job_id, payload, course_type=course_type)

        enriched_artifact = by_type.get(ARTIFACT_TYPE_ENRICHED_SECTIONS)
        if enriched_artifact is not None:
            payload = self._read_json(enriched_artifact.blob_path)
            return _map_enriched_sections(job_id, payload, course_type=course_type)

        raise CourseContentNotFoundError(
            f"No generated course content found for job '{job_id}'."
        )

    def _resolve_course_type(self, job_id: str, artifacts: list) -> str:
        """Best-effort lookup of the course type for display (never fatal)."""
        if not artifacts:
            return ""
        course_run_id = artifacts[0].course_run_id
        row = (
            self.db.query(CourseBasic.course_type)
            .join(CourseRun, CourseRun.course_id == CourseBasic.id)
            .filter(CourseRun.id == course_run_id)
            .first()
        )
        return row[0] if row else ""

    def _read_json(self, blob_path: str) -> dict:
        if self._blob_client.is_ready():
            raw = self._blob_client.download_bytes(blob_path)
        else:
            local_path = self._local_store.resolve(blob_path)
            if not local_path.is_file():
                raise CourseContentNotFoundError(
                    f"Artifact '{blob_path}' not found on local store."
                )
            raw = local_path.read_bytes()
        return json.loads(raw.decode("utf-8"))


# ─── Mapping helpers ──────────────────────────────────────────────────────────
# Output keys are camelCase to match the frontend `CourseContent` contract in
# course_generation_frontend/src/modules/course-generation/types/editor.ts.


def _estimated_read_time(word_count: int) -> str:
    minutes = max(1, round(word_count / 200)) if word_count else 0
    return f"{minutes} min read" if minutes else "—"


def _paragraphs_to_text(paragraphs: list[dict]) -> str:
    """Flatten body_paragraph blocks into a plain-text preview for `content`."""
    parts: list[str] = []
    for block in paragraphs or []:
        btype = block.get("type")
        if btype in ("text", "heading_3", "heading_4"):
            if block.get("content"):
                parts.append(str(block["content"]))
        elif btype in ("bullet_list", "sub_bullet_list", "numbered_list"):
            parts.extend(str(item) for item in block.get("items") or [])
        elif btype in ("important_callout", "callout"):
            if block.get("content"):
                parts.append(str(block["content"]))
    return "\n\n".join(parts)


def _map_images(images: list) -> list[dict]:
    mapped: list[dict] = []
    for idx, img in enumerate(images or []):
        if not isinstance(img, dict):
            continue
        mapped.append(
            {
                "id": str(img.get("id") or img.get("image_id") or f"img-{idx}"),
                "fileName": img.get("file_name") or img.get("fileName") or "",
                "blobPath": img.get("blob_path") or img.get("blobPath") or "",
                "caption": img.get("caption"),
                "altText": img.get("alt_text") or img.get("altText"),
            }
        )
    return mapped


def _is_lesson_parent_section(raw: dict) -> bool:
    """True when an A2 flat section is the lesson/chapter heading (not a subtopic)."""
    level = int(raw.get("level") or 2)
    outline_lesson = str(raw.get("outline_lesson") or "").strip()
    heading = str(raw.get("heading") or "").strip()
    return bool(
        level == 1
        or raw.get("is_parent_overview")
        or (outline_lesson and heading == outline_lesson)
    )


def _group_a2_sections_by_lesson(raw_sections: list) -> list[tuple[str, list[dict]]]:
    """Group flat A2 sections into ordered ``(lesson_title, sections)`` chapters.

    A2 writers tag every generated block with ``outline_lesson`` (the TO lesson
    title). Level-1 / ``is_parent_overview`` rows are the chapter heads; level-2
    rows are subtopics. When a lesson has only level-2 rows (no parent overview
    was generated), they still form their own chapter keyed by ``outline_lesson``.

    Falling back to a single ``level``-only walk incorrectly nests every later
    lesson's subtopics under the first level-2 section when no level-1 parents
    exist — which is why the editor saw 2 top-level sections instead of 9.
    """
    groups: list[tuple[str, list[dict]]] = []
    current_key: str | None = None
    current_sections: list[dict] = []
    orphan_idx = 0

    def flush() -> None:
        nonlocal current_key, current_sections
        if current_key is not None and current_sections:
            groups.append((current_key, current_sections))
        current_key = None
        current_sections = []

    for raw in raw_sections:
        if not isinstance(raw, dict):
            continue
        outline_lesson = str(raw.get("outline_lesson") or "").strip()
        heading = str(raw.get("heading") or "").strip()
        key = outline_lesson or heading or f"Section {orphan_idx + 1}"
        if not outline_lesson:
            orphan_idx += 1

        if current_key is None:
            current_key = key
            current_sections = [raw]
            continue

        if key != current_key:
            flush()
            current_key = key
            current_sections = [raw]
        else:
            current_sections.append(raw)

    flush()
    return groups


def _map_a2_output(job_id: str, payload: dict, *, course_type: str) -> dict:
    """Map persisted `A2Output` into the editor `CourseContent` payload.

    A2 ``sections`` is a flat list tagged with ``outline_lesson`` (lesson/chapter)
    plus ``level`` / ``is_parent_overview`` (1 = chapter head, 2 = subtopic).
    Rebuild one top-level chapter per lesson, with subtopics as children.
    """
    raw_sections = payload.get("sections") or []

    top_level: list[dict] = []
    order = 0
    total_words = 0
    used_ids: set[str] = set()

    def unique_id(preferred: str, fallback: str) -> str:
        candidate = (preferred or "").strip() or fallback
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        suffix = 2
        while f"{candidate}-{suffix}" in used_ids:
            suffix += 1
        resolved = f"{candidate}-{suffix}"
        used_ids.add(resolved)
        return resolved

    def build_section(
        raw: dict,
        *,
        level: int,
        index: int,
        parent_id: str | None,
        id_fallback: str,
        title_override: str | None = None,
    ) -> dict:
        nonlocal total_words
        paragraphs = list(raw.get("body_paragraphs") or [])
        word_count = int(raw.get("word_count") or 0)
        total_words += word_count
        is_overview = level == 1
        section_id = unique_id(str(raw.get("section_id") or ""), id_fallback)
        title = title_override or raw.get("heading") or f"Section {index + 1}"
        return {
            "id": section_id,
            "title": title,
            "level": level,
            "sectionType": "overview" if is_overview else "content",
            "content": _paragraphs_to_text(paragraphs),
            "paragraphs": paragraphs,
            "learningObjectives": [],
            "wordCount": word_count,
            "hasKnowledgeCheck": any(
                (b.get("type") == "knowledge_check") for b in paragraphs
            ),
            "order": index,
            "parentId": parent_id,
            "children": [],
            "images": _map_images(raw.get("images") or []),
        }

    # Optional course intro from A2 course_description.
    description = (payload.get("course_description") or "").strip()
    if description:
        intro_id = unique_id(f"{job_id}-introduction", f"{job_id}-introduction")
        top_level.append(
            {
                "id": intro_id,
                "title": "Introduction",
                "level": 1,
                "sectionType": "overview",
                "content": description,
                "paragraphs": [{"type": "text", "content": description}],
                "learningObjectives": [],
                "wordCount": len(description.split()),
                "hasKnowledgeCheck": False,
                "order": order,
                "parentId": None,
                "children": [],
                "images": [],
            }
        )
        order += 1

    for chapter_idx, (lesson_title, lesson_sections) in enumerate(
        _group_a2_sections_by_lesson(raw_sections)
    ):
        parent_raw = next(
            (sec for sec in lesson_sections if _is_lesson_parent_section(sec)),
            None,
        )
        child_raws = [
            sec for sec in lesson_sections if not _is_lesson_parent_section(sec)
        ]

        if parent_raw is not None:
            parent = build_section(
                parent_raw,
                level=1,
                index=order,
                parent_id=None,
                id_fallback=f"{job_id}-ch-{chapter_idx}",
            )
        else:
            # No generated parent overview — synthesize a chapter head so each
            # TO lesson still appears as its own top-level section in the editor.
            subtopic_titles = [
                str(sec.get("heading") or "").strip()
                for sec in child_raws
                if str(sec.get("heading") or "").strip()
            ]
            synthetic = {
                "heading": lesson_title,
                "body_paragraphs": (
                    [{"type": "bullet_list", "items": subtopic_titles}]
                    if subtopic_titles
                    else []
                ),
                "word_count": 0,
                "section_id": "",
                "images": [],
                "is_parent_overview": True,
                "level": 1,
            }
            parent = build_section(
                synthetic,
                level=1,
                index=order,
                parent_id=None,
                id_fallback=f"{job_id}-ch-{chapter_idx}",
                title_override=lesson_title,
            )

        for child_idx, child_raw in enumerate(child_raws):
            child = build_section(
                child_raw,
                level=2,
                index=child_idx,
                parent_id=parent["id"],
                id_fallback=f"{job_id}-ch-{chapter_idx}-sec-{child_idx}",
            )
            parent["children"].append(child)

        top_level.append(parent)
        order += 1

    # Optional course conclusion from A2 course_conclusion.
    conclusion = (payload.get("course_conclusion") or "").strip()
    if conclusion:
        conclusion_id = unique_id(f"{job_id}-conclusion", f"{job_id}-conclusion")
        top_level.append(
            {
                "id": conclusion_id,
                "title": "Conclusion",
                "level": 1,
                "sectionType": "conclusion",
                "content": conclusion,
                "paragraphs": [{"type": "text", "content": conclusion}],
                "learningObjectives": [],
                "wordCount": len(conclusion.split()),
                "hasKnowledgeCheck": False,
                "order": order,
                "parentId": None,
                "children": [],
                "images": [],
            }
        )
        order += 1

    return {
        "jobId": str(job_id),
        "courseTitle": payload.get("course_title") or "Untitled Course",
        "courseType": course_type or "",
        "generatedAt": _as_iso(payload.get("timestamp")),
        "meta": {
            "totalWordCount": total_words,
            "sectionCount": len(top_level),
            "chapterCount": sum(1 for s in top_level if s["sectionType"] != "conclusion"),
            "estimatedReadTime": _estimated_read_time(total_words),
        },
        "sections": top_level,
    }


def _map_enriched_sections(job_id: str, payload, *, course_type: str) -> dict:
    """Fallback map from the thin section-mapper output (legacy jobs).

    `enriched_sections.json` is a list of lessons, each with `title`, `content`
    and a `subtopics` list. No paragraph blocks — we render the plain `content`
    strings so pre-fix jobs still show structure rather than a blank editor.
    """
    lessons = payload if isinstance(payload, list) else payload.get("sections") or []

    top_level: list[dict] = []
    total_words = 0

    for l_idx, lesson in enumerate(lessons):
        if not isinstance(lesson, dict):
            continue
        content = str(lesson.get("content") or "")
        word_count = len(content.split())
        total_words += word_count
        children: list[dict] = []
        for s_idx, sub in enumerate(lesson.get("subtopics") or []):
            if not isinstance(sub, dict):
                continue
            sub_content = str(sub.get("content") or "")
            total_words += len(sub_content.split())
            children.append(
                {
                    "id": f"{job_id}-sec-{l_idx}-{s_idx}",
                    "title": sub.get("title") or f"Subtopic {s_idx + 1}",
                    "level": 2,
                    "sectionType": "content",
                    "content": sub_content,
                    "paragraphs": (
                        [{"type": "text", "content": sub_content}] if sub_content else []
                    ),
                    "learningObjectives": [],
                    "wordCount": len(sub_content.split()),
                    "hasKnowledgeCheck": bool(sub.get("interactive_elements")),
                    "order": s_idx,
                    "parentId": f"{job_id}-sec-{l_idx}",
                    "children": [],
                    "images": _map_images(sub.get("images") or []),
                }
            )
        top_level.append(
            {
                "id": f"{job_id}-sec-{l_idx}",
                "title": lesson.get("title") or f"Section {l_idx + 1}",
                "level": 1,
                "sectionType": "overview" if l_idx == 0 else "content",
                "content": content,
                "paragraphs": [{"type": "text", "content": content}] if content else [],
                "learningObjectives": [],
                "wordCount": word_count,
                "hasKnowledgeCheck": bool(lesson.get("interactive_elements")),
                "order": l_idx,
                "parentId": None,
                "children": children,
                "images": [],
            }
        )

    return {
        "jobId": str(job_id),
        "courseTitle": "Untitled Course",
        "courseType": course_type or "",
        "generatedAt": "",
        "meta": {
            "totalWordCount": total_words,
            "sectionCount": len(top_level),
            "chapterCount": len(top_level),
            "estimatedReadTime": _estimated_read_time(total_words),
        },
        "sections": top_level,
    }


def _as_iso(value) -> str:
    if not value:
        return ""
    return str(value)
