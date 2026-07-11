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


def _map_a2_output(job_id: str, payload: dict, *, course_type: str) -> dict:
    """Map persisted `A2Output` into the editor `CourseContent` payload.

    A2 `sections` is a flat list with `level` (1 = parent overview, 2 = subtopic)
    and `outline_lesson` grouping subtopics under their lesson. We rebuild the
    two-level tree the editor expects: level-1 sections carrying level-2 children.
    """
    raw_sections = payload.get("sections") or []

    top_level: list[dict] = []
    current_parent: dict | None = None
    order = 0
    total_words = 0

    def build_section(raw: dict, level: int, index: int, parent_id: str | None) -> dict:
        nonlocal total_words
        paragraphs = raw.get("body_paragraphs") or []
        word_count = int(raw.get("word_count") or 0)
        total_words += word_count
        is_overview = bool(raw.get("is_parent_overview")) or level == 1
        section_id = str(raw.get("section_id") or "").strip() or f"{job_id}-sec-{index}"
        return {
            "id": section_id,
            "title": raw.get("heading") or f"Section {index + 1}",
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
        top_level.append(
            {
                "id": f"{job_id}-introduction",
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

    for idx, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            continue
        level = int(raw.get("level") or 1)
        if level <= 1 or current_parent is None:
            section = build_section(raw, 1, order, None)
            top_level.append(section)
            current_parent = section
            order += 1
        else:
            child = build_section(raw, 2, len(current_parent["children"]), current_parent["id"])
            current_parent["children"].append(child)

    # Optional course conclusion from A2 course_conclusion.
    conclusion = (payload.get("course_conclusion") or "").strip()
    if conclusion:
        top_level.append(
            {
                "id": f"{job_id}-conclusion",
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
