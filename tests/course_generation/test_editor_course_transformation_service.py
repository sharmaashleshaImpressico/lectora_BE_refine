"""Unit tests for EditorCourseTransformationService (Phase 2 merge layer)."""

from __future__ import annotations

import pytest

from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.editor_course_transformation_service import (
    EditorCourseTransformationError,
    EditorCourseTransformationService,
)
from app.services.onboarding.course_generation.editor_snapshot_mapper import (
    FRONTEND_OWNED_SECTION_FIELDS,
    PIPELINE_OWNED_SECTION_FIELDS,
)


def _section(**kwargs) -> CourseSectionInput:
    return CourseSectionInput(**kwargs)


def _svc() -> EditorCourseTransformationService:
    return EditorCourseTransformationService()


def _existing_a2(**overrides) -> dict:
    base = {
        "status": "completed",
        "run_id": "job-42",
        "course_title": "Existing Title",
        "course_description": "Old description",
        "course_conclusion": "Old conclusion",
        "sections": [
            {
                "section_id": "ch-1",
                "heading": "Chapter One",
                "outline_lesson": "Chapter One",
                "level": 1,
                "body_paragraphs": [],
                "word_count": 0,
                "is_parent_overview": True,
                "status": "generated",
                "images": [],
                "maps_to_objectives": [0],
                "subtopics": ["Primary purposes"],
            },
            {
                "section_id": "sec-1",
                "heading": "Primary purposes",
                "outline_lesson": "Chapter One",
                "level": 2,
                "body_paragraphs": [
                    {"type": "text", "content": "Pipeline body for sec-1"}
                ],
                "word_count": 4,
                "is_parent_overview": False,
                "status": "generated",
                "images": [
                    {
                        "media_filename": "chart.png",
                        "path": "blobs/chart.png",
                        "caption": "Chart",
                        "alt_text": "A chart",
                    }
                ],
                "maps_to_objectives": [0, 1],
                "subtopics": [],
                "source_refs": [{"chunk_id": "c1"}],
                "provenance": {"writer": "a2"},
            },
        ],
        "stats": {"generated": 2, "total_words": 4},
    }
    base.update(overrides)
    return base


# ─── Mapping ──────────────────────────────────────────────────────────────────


def test_maps_overview_los_conclusion_and_content():
    snapshot = RenderDocxRequest(
        courseTitle="Annuity Basics",
        sections=[
            _section(
                id="intro",
                title="Introduction",
                level=1,
                sectionType="overview",
                content="Welcome to the course.",
                order=0,
            ),
            _section(
                id="los",
                title="Learning Objectives",
                level=1,
                sectionType="learning-objectives",
                learningObjectives=["Explain annuities", "Compare products"],
                order=1,
            ),
            _section(
                id="ch-1",
                title="Why Annuities Matter",
                level=1,
                sectionType="overview",
                content="",
                order=2,
                children=[
                    _section(
                        id="sec-1",
                        title="Primary purposes",
                        level=2,
                        sectionType="content",
                        content="Manual edit about purposes.",
                        order=0,
                    ),
                ],
            ),
            _section(
                id="outro",
                title="Conclusion",
                level=1,
                sectionType="conclusion",
                content="Thanks for reading.",
                order=3,
            ),
        ],
    )

    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    a2 = result.canonical_a2

    assert a2["course_title"] == "Annuity Basics"
    assert a2["course_description"] == "Welcome to the course."
    assert a2["course_conclusion"] == "Thanks for reading."
    assert result.learning_objectives == ["Explain annuities", "Compare products"]
    assert [s["heading"] for s in a2["sections"]] == [
        "Why Annuities Matter",
        "Primary purposes",
    ]
    assert a2["sections"][0]["is_parent_overview"] is True
    assert a2["sections"][1]["status"] == "editor_saved"


def test_chapter_overview_is_not_course_description():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Chapter Head",
                level=1,
                sectionType="overview",
                content="",
                order=0,
                children=[
                    _section(
                        id="sec-1",
                        title="Child",
                        level=2,
                        content="Child body",
                        order=0,
                    )
                ],
            )
        ],
    )
    result = _svc().transform(
        snapshot,
        existing_a2=_existing_a2(course_description="Keep me"),
    )
    assert result.canonical_a2["course_description"] == "Keep me"
    assert result.canonical_a2["sections"][0]["heading"] == "Chapter Head"


def test_depth_first_flattening_and_order():
    snapshot = RenderDocxRequest(
        courseTitle="Ordered",
        sections=[
            _section(
                id="ch-b",
                title="Chapter B",
                level=1,
                content="B",
                order=2,
            ),
            _section(
                id="ch-a",
                title="Chapter A",
                level=1,
                content="A",
                order=1,
                children=[
                    _section(id="a2", title="A2", level=2, content="second", order=2),
                    _section(id="a1", title="A1", level=2, content="first", order=1),
                ],
            ),
        ],
    )
    result = _svc().transform(snapshot)
    assert [s["heading"] for s in result.canonical_a2["sections"]] == [
        "Chapter A",
        "A1",
        "A2",
        "Chapter B",
    ]


# ─── Body selection ───────────────────────────────────────────────────────────


def test_paragraphs_win_over_content_and_existing():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="sec-1",
                title="Primary purposes",
                level=1,
                content="Plain should lose",
                paragraphs=[{"type": "text", "content": "Structured wins"}],
            )
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    body = result.canonical_a2["sections"][0]["body_paragraphs"]
    assert body == [{"type": "text", "content": "Structured wins"}]


def test_content_wins_when_paragraphs_empty():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="sec-1",
                title="Primary purposes",
                level=1,
                content="Plain content wins",
                paragraphs=[],
            )
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    assert result.canonical_a2["sections"][0]["body_paragraphs"] == [
        {"type": "text", "content": "Plain content wins"}
    ]


def test_existing_body_preserved_when_fe_empty():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="sec-1",
                title="Primary purposes",
                level=2,
                content="",
                paragraphs=[],
            )
        ],
    )
    # Need an L1 wrapper so hierarchy is valid for level 2... actually level 2
    # without parent_level is OK (parent_level is None). Allowed.
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    assert result.canonical_a2["sections"][0]["body_paragraphs"][0]["content"] == (
        "Pipeline body for sec-1"
    )


def test_empty_new_section_stays_empty():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(id="brand-new", title="New", level=1, content="", paragraphs=[])
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    assert result.canonical_a2["sections"][0]["body_paragraphs"] == []


def test_parent_l1_keeps_pipeline_metadata_when_empty():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Chapter One",
                level=1,
                sectionType="overview",
                content="",
                children=[
                    _section(
                        id="sec-1",
                        title="Primary purposes",
                        level=2,
                        content="Updated child",
                    )
                ],
            )
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    parent = result.canonical_a2["sections"][0]
    assert parent["is_parent_overview"] is True
    assert parent["maps_to_objectives"] == [0]
    assert parent["subtopics"] == ["Primary purposes"]


# ─── Metadata preservation ────────────────────────────────────────────────────


def test_preserves_images_maps_subtopics_and_provenance():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="sec-1",
                title="Primary purposes",
                level=1,
                content="",  # force existing body
            )
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    sec = result.canonical_a2["sections"][0]
    assert sec["images"][0]["media_filename"] == "chart.png"
    assert sec["maps_to_objectives"] == [0, 1]
    assert sec["source_refs"] == [{"chunk_id": "c1"}]
    assert sec["provenance"] == {"writer": "a2"}
    assert sec["heading"] == "Primary purposes"  # FE-owned update of title
    assert sec["status"] == "editor_saved"


def test_frontend_images_replace_pipeline_images_when_supplied():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="sec-1",
                title="Primary purposes",
                level=1,
                content="x",
                images=[
                    {
                        "fileName": "new.png",
                        "blobPath": "blobs/new.png",
                        "caption": "New",
                        "altText": "new alt",
                    }
                ],
            )
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    images = result.canonical_a2["sections"][0]["images"]
    assert images[0]["media_filename"] == "new.png"
    assert images[0]["path"] == "blobs/new.png"


def test_metadata_not_copied_across_unrelated_ids():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(id="other-sec", title="Other", level=1, content="Other body")
        ],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    sec = result.canonical_a2["sections"][0]
    assert sec["section_id"] == "other-sec"
    assert sec.get("maps_to_objectives") in (None, [])
    assert "source_refs" not in sec or sec.get("source_refs") in (None, [])
    assert sec["images"] == []


def test_field_ownership_sets_documented():
    assert "body_paragraphs" in FRONTEND_OWNED_SECTION_FIELDS
    assert "heading" in FRONTEND_OWNED_SECTION_FIELDS
    assert "maps_to_objectives" in PIPELINE_OWNED_SECTION_FIELDS
    assert "images" in PIPELINE_OWNED_SECTION_FIELDS
    assert FRONTEND_OWNED_SECTION_FIELDS.isdisjoint(PIPELINE_OWNED_SECTION_FIELDS)


# ─── Hierarchy ────────────────────────────────────────────────────────────────


def test_outline_lesson_inheritance_l1_l2_l3():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Lesson Alpha",
                level=1,
                content="Head",
                children=[
                    _section(
                        id="sec-2",
                        title="Subtopic",
                        level=2,
                        content="L2",
                        children=[
                            _section(
                                id="sec-3",
                                title="Detail",
                                level=3,
                                content="L3",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    result = _svc().transform(snapshot)
    sections = result.canonical_a2["sections"]
    assert sections[0]["outline_lesson"] == "Lesson Alpha"
    assert sections[1]["outline_lesson"] == "Lesson Alpha"
    assert sections[2]["outline_lesson"] == "Lesson Alpha"
    assert [s["section_id"] for s in sections] == ["ch-1", "sec-2", "sec-3"]


def test_empty_l1_with_children_is_parent_overview():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Parent",
                level=1,
                content="",
                children=[
                    _section(id="sec-1", title="Child", level=2, content="Body")
                ],
            )
        ],
    )
    result = _svc().transform(snapshot)
    assert result.canonical_a2["sections"][0]["is_parent_overview"] is True
    assert result.canonical_a2["sections"][1]["is_parent_overview"] is False


# ─── Special fields ───────────────────────────────────────────────────────────


def test_empty_title_preserves_existing_title():
    snapshot = RenderDocxRequest(
        courseTitle="   ",
        sections=[_section(id="s1", title="Sec", level=1, content="Body")],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    assert result.course_title == "Existing Title"
    assert result.canonical_a2["course_title"] == "Existing Title"


def test_omitted_learning_objectives_section_preserves_existing():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[_section(id="s1", title="Sec", level=1, content="Body")],
    )
    result = _svc().transform(
        snapshot,
        existing_a2=_existing_a2(),
        existing_learning_objectives=["Keep LO"],
    )
    assert result.learning_objectives == ["Keep LO"]


def test_present_empty_learning_objectives_section_clears():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="los",
                title="LOs",
                level=1,
                sectionType="learning-objectives",
                learningObjectives=[],
                content="",
            ),
            _section(id="s1", title="Sec", level=1, content="Body"),
        ],
    )
    result = _svc().transform(
        snapshot,
        existing_learning_objectives=["Old LO"],
    )
    assert result.learning_objectives == []


def test_omitted_conclusion_preserves_existing():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[_section(id="s1", title="Sec", level=1, content="Body")],
    )
    result = _svc().transform(snapshot, existing_a2=_existing_a2())
    assert result.canonical_a2["course_conclusion"] == "Old conclusion"


# ─── Meta calculations ────────────────────────────────────────────────────────


def test_meta_excludes_parent_overview_from_counts():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Parent",
                level=1,
                content="",
                wordCount=0,
                children=[
                    _section(
                        id="sec-1",
                        title="Child",
                        level=2,
                        content="one two three four five",
                        wordCount=5,
                    )
                ],
            ),
            _section(
                id="ch-2",
                title="Solo Chapter",
                level=1,
                content="six seven",
                wordCount=2,
            ),
        ],
    )
    result = _svc().transform(snapshot)
    # Parent overview excluded; content secs = child + solo chapter.
    assert result.meta["sectionCount"] == 2
    assert result.meta["chapterCount"] == 1  # only level-1 non-parent (solo)
    assert result.meta["totalWordCount"] == 7
    assert "min read" in result.meta["estimatedReadTime"]


def test_read_time_zero_words():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Parent",
                level=1,
                content="",
                children=[_section(id="sec-1", title="Child", level=2, content="")],
            )
        ],
    )
    result = _svc().transform(snapshot)
    assert result.meta["estimatedReadTime"] == "—"


# ─── Invalid input ────────────────────────────────────────────────────────────


def test_duplicate_ids_raise():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(id="dup", title="A", level=1, content="a"),
            _section(id="dup", title="B", level=1, content="b"),
        ],
    )
    with pytest.raises(EditorCourseTransformationError, match="Duplicate section id"):
        _svc().transform(snapshot)


def test_missing_content_id_raises():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[_section(id="", title="No Id", level=1, content="Body")],
    )
    with pytest.raises(EditorCourseTransformationError, match="missing a stable id"):
        _svc().transform(snapshot)


def test_unsupported_level_raises():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[_section(id="s1", title="Bad", level=4, content="Body")],
    )
    with pytest.raises(EditorCourseTransformationError, match="unsupported level"):
        _svc().transform(snapshot)


def test_unsupported_hierarchy_raises():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="ch-1",
                title="Parent",
                level=2,
                content="P",
                children=[
                    _section(id="sec-1", title="Child", level=1, content="C"),
                ],
            )
        ],
    )
    with pytest.raises(EditorCourseTransformationError, match="Unsupported hierarchy"):
        _svc().transform(snapshot)


def test_malformed_paragraphs_raise():
    sec = CourseSectionInput.model_construct(
        id="s1",
        title="Bad paras",
        level=1,
        section_type="content",
        content="",
        paragraphs=["not-a-dict"],  # bypass pydantic list[dict] check
        learning_objectives=[],
        word_count=0,
        has_knowledge_check=False,
        order=0,
        children=[],
        images=[],
    )
    snapshot = RenderDocxRequest(courseTitle="T", sections=[sec])
    with pytest.raises(EditorCourseTransformationError, match="malformed paragraphs"):
        _svc().transform(snapshot)


def test_no_content_sections_raises():
    snapshot = RenderDocxRequest(
        courseTitle="T",
        sections=[
            _section(
                id="intro",
                title="Introduction",
                level=1,
                sectionType="overview",
                content="Only intro",
            )
        ],
    )
    with pytest.raises(EditorCourseTransformationError, match="No content sections"):
        _svc().transform(snapshot)
