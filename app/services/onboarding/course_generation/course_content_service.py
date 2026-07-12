"""Resolves a completed job's generated course into the shape the frontend editor loads.

The pipeline persists two relevant artifacts per job (see `pipeline_runner`):

* ``course_content.json`` — the rich A2 writer output (headings + body_paragraphs
  + images). This is what the editor is designed around and is preferred here.
* ``enriched_sections.json`` — the thinner section-mapper output (titles +
  subtopics, no paragraph blocks). Used as a fallback for jobs generated before
  ``course_content.json`` was persisted, so they still render structure.

Resolution order for GET /jobs/{job_id}/course:

1. Latest ``AVAILABLE`` ``CourseContentVersion.canonical_json_blob_path``
2. Flat pipeline ``course_content.json`` artifact
3. ``enriched_sections.json`` fallback

``CREATING`` / ``FAILED`` versions are ignored. A missing or corrupt blob for the
latest AVAILABLE version raises a consistency error (no silent fall-back to an
older version or flat artifact).

Lazy Version 1 backfill is intentionally **not** performed on GET — that write
belongs to Save-to-Azure (and pipeline completion). GET remains read-only aside
from the DB session used for lookups.

Both are read back from blob (or the local upload store when Azure is not
configured) and mapped into the camelCase ``CourseContent`` payload the frontend
binds to (``types/editor.ts``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import azure_storage_settings
from app.core.storage.azure_blob_client import LocalUploadStore
from app.models.course_generation.course_generation_job.constants import (
    ARTIFACT_TYPE_COURSE_CONTENT,
    ARTIFACT_TYPE_ENRICHED_SECTIONS,
    ARTIFACT_TYPE_SHARED_STATE,
)
from app.models.onboarding.course_basic.course_basic import CourseBasic
from app.models.onboarding.course_run.course_run import CourseRun
from app.repositories.course_generation.course_content_version_repository import (
    CourseContentVersionRepository,
)
from app.repositories.course_generation.course_generation_job_artifact_repository import (
    CourseGenerationJobArtifactRepository,
)
from app.repositories.course_run.course_run_spec_repository import CourseRunSpecRepository
from app.services.onboarding.course_generation.artifact_service import ArtifactsBlobClient

logger = logging.getLogger(__name__)


class CourseContentNotFoundError(Exception):
    """Raised when a job has no readable generated-course artifact."""


class CourseContentConsistencyError(Exception):
    """Raised when the latest AVAILABLE version metadata points to bad storage."""


@dataclass(frozen=True)
class CanonicalCourseState:
    """Raw canonical A2 (+ learning objectives) for editor-save transforms."""

    canonical_a2: dict[str, Any]
    learning_objectives: list[str]
    course_title: str
    source: str  # "version" | "course_content_artifact" | "pipeline_input"


class CourseContentService:
    """Reads a job's generated-course artifact and maps it for the editor."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.artifacts = CourseGenerationJobArtifactRepository(db)
        self.versions = CourseContentVersionRepository(db)
        self.course_run_specs = CourseRunSpecRepository(db)
        self._blob_client = ArtifactsBlobClient(azure_storage_settings)
        self._local_store = LocalUploadStore(azure_storage_settings)

    def get_course_content(self, job_id: str) -> dict:
        """Return the `CourseContent` payload for a completed job.

        Raises `CourseContentNotFoundError` when no generated-course artifact
        exists yet (e.g. the job hasn't finished, or failed before writing one).
        Raises `CourseContentConsistencyError` when the latest AVAILABLE version
        blob is missing or corrupt.
        """
        artifacts = self.artifacts.list_by_job(job_id)
        by_type = {a.artifact_type: a for a in artifacts}
        course_type = self._resolve_course_type(job_id, artifacts)

        latest = self.versions.get_latest_available(job_id)
        if latest is not None and (latest.canonical_json_blob_path or "").strip():
            logger.info(
                "[course_content] load | job_id=%s source=version version_number=%s path=%s",
                job_id,
                latest.version_number,
                latest.canonical_json_blob_path,
            )
            payload = self._read_version_json(
                latest.canonical_json_blob_path,
                job_id=job_id,
                version_number=latest.version_number,
            )
            return _map_a2_output(job_id, payload, course_type=course_type)

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

    def load_canonical_state(self, job_id: int | str) -> CanonicalCourseState:
        """Load raw A2 canonical state for editor-save (never from DOCX).

        Preference order:
        1. Latest AVAILABLE ``CourseContentVersion`` JSON
        2. Flat pipeline ``course_content.json`` artifact
        3. ``pipeline_input.json`` / course-run-spec learning objectives as LO fallback
           only — enriched_sections alone is not sufficient for save transforms
        """
        latest = self.versions.get_latest_available(job_id)
        if latest is not None and (latest.canonical_json_blob_path or "").strip():
            payload = self._read_version_json(
                latest.canonical_json_blob_path,
                job_id=job_id,
                version_number=latest.version_number,
            )
            return self._canonical_from_payload(payload, source="version", job_id=job_id)

        artifacts = self.artifacts.list_by_job(job_id)
        by_type = {a.artifact_type: a for a in artifacts}

        content_artifact = by_type.get(ARTIFACT_TYPE_COURSE_CONTENT)
        if content_artifact is not None:
            payload = self._read_json(content_artifact.blob_path)
            return self._canonical_from_payload(
                payload, source="course_content_artifact", job_id=job_id, artifacts=by_type
            )

        raise CourseContentNotFoundError(
            f"No canonical course_content.json found for job '{job_id}'. "
            "Editor save requires rich A2 course content (not DOCX, not enriched_sections alone)."
        )

    def _read_version_json(
        self,
        blob_path: str,
        *,
        job_id: int | str,
        version_number: int,
    ) -> dict:
        """Load version JSON; surface storage/corruption errors without silent fallback."""
        try:
            return self._read_json(blob_path)
        except CourseContentNotFoundError as exc:
            logger.error(
                "[course_content] consistency | job_id=%s version_number=%s "
                "path=%s status=missing_blob",
                job_id,
                version_number,
                blob_path,
            )
            raise CourseContentConsistencyError(
                f"Latest AVAILABLE version {version_number} for job '{job_id}' "
                f"points to missing blob '{blob_path}'."
            ) from exc
        except json.JSONDecodeError as exc:
            logger.error(
                "[course_content] consistency | job_id=%s version_number=%s "
                "path=%s status=invalid_json",
                job_id,
                version_number,
                blob_path,
            )
            raise CourseContentConsistencyError(
                f"Latest AVAILABLE version {version_number} for job '{job_id}' "
                f"has invalid JSON at '{blob_path}'."
            ) from exc
        except CourseContentConsistencyError:
            raise
        except Exception as exc:
            raise CourseContentConsistencyError(
                f"Failed to load latest AVAILABLE version {version_number} for "
                f"job '{job_id}' from '{blob_path}': {exc}"
            ) from exc

    def _canonical_from_payload(
        self,
        payload: dict[str, Any],
        *,
        source: str,
        job_id: int | str,
        artifacts: dict | None = None,
    ) -> CanonicalCourseState:
        if not isinstance(payload, dict) or not (payload.get("sections") or []):
            raise CourseContentNotFoundError(
                f"Canonical payload for job '{job_id}' is missing A2 sections."
            )

        learning_objectives = self._extract_learning_objectives(payload)
        if not learning_objectives:
            learning_objectives = self._load_learning_objectives_fallback(
                job_id, artifacts=artifacts
            )

        course_title = str(payload.get("course_title") or "").strip() or "Untitled Course"
        return CanonicalCourseState(
            canonical_a2=dict(payload),
            learning_objectives=learning_objectives,
            course_title=course_title,
            source=source,
        )

    @staticmethod
    def _extract_learning_objectives(payload: dict[str, Any]) -> list[str]:
        raw = payload.get("learning_objectives")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    def _load_learning_objectives_fallback(
        self,
        job_id: int | str,
        *,
        artifacts: dict | None = None,
    ) -> list[str]:
        by_type = artifacts
        if by_type is None:
            by_type = {a.artifact_type: a for a in self.artifacts.list_by_job(job_id)}

        shared = by_type.get(ARTIFACT_TYPE_SHARED_STATE)
        if shared is not None:
            try:
                payload = self._read_json(shared.blob_path)
                raw = payload.get("learning_objectives")
                if isinstance(raw, list):
                    return [str(item).strip() for item in raw if str(item).strip()]
            except Exception:
                logger.exception(
                    "Failed reading learning objectives from pipeline_input for job %s",
                    job_id,
                )

        # Course-run spec JSON list (onboarding).
        if by_type:
            sample = next(iter(by_type.values()), None)
            course_run_id = getattr(sample, "course_run_id", None)
            if course_run_id is not None:
                spec = self.course_run_specs.get_by(course_run_id=course_run_id)
                if spec and spec.learning_objectives_json:
                    try:
                        parsed = json.loads(spec.learning_objectives_json)
                        if isinstance(parsed, list):
                            return [
                                str(item).strip() for item in parsed if str(item).strip()
                            ]
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid learning_objectives_json on course_run %s",
                            course_run_id,
                        )
        return []

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
            try:
                raw = self._blob_client.download_bytes(blob_path)
            except Exception as exc:
                raise CourseContentNotFoundError(
                    f"Artifact '{blob_path}' could not be downloaded: {exc}"
                ) from exc
        else:
            local_path = self._local_store.resolve(blob_path)
            if not local_path.is_file():
                raise CourseContentNotFoundError(
                    f"Artifact '{blob_path}' not found on local store."
                )
            raw = local_path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # Re-raise JSONDecodeError so version loaders can map to consistency errors.
            if isinstance(exc, json.JSONDecodeError):
                raise
            raise json.JSONDecodeError(str(exc), "", 0) from exc
        if not isinstance(payload, dict) and not isinstance(payload, list):
            raise CourseContentNotFoundError(
                f"Artifact '{blob_path}' did not contain a JSON object or array."
            )
        return payload  # type: ignore[return-value]


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

    Extra storage keys (``learning_objectives``, wrappers) are tolerated: older
    flat pipeline JSON without them continues to work; when present, learning
    objectives are surfaced as a ``learning-objectives`` section for the editor.
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

    # Versioned / editor-saved JSON may embed learning_objectives at the root.
    raw_los = payload.get("learning_objectives")
    learning_objectives: list[str] = []
    if isinstance(raw_los, list):
        learning_objectives = [
            str(item).strip() for item in raw_los if str(item).strip()
        ]
    if learning_objectives:
        lo_id = unique_id(
            f"{job_id}-learning-objectives", f"{job_id}-learning-objectives"
        )
        top_level.append(
            {
                "id": lo_id,
                "title": "Learning Objectives",
                "level": 1,
                "sectionType": "learning-objectives",
                "content": "\n".join(f"- {lo}" for lo in learning_objectives),
                "paragraphs": [
                    {"type": "bullet_list", "items": list(learning_objectives)}
                ],
                "learningObjectives": list(learning_objectives),
                "wordCount": sum(len(lo.split()) for lo in learning_objectives),
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
