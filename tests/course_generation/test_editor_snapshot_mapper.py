"""Tests for pure editor-snapshot → A2 mapping (no persistence)."""

from __future__ import annotations

import pytest

from app.schemas.onboarding.course_generation_job.course_content_snapshot import (
    CourseSectionInput,
    RenderDocxRequest,
)
from app.services.onboarding.course_generation.editor_snapshot_mapper import (
    EmptyCourseContentError,
    map_editor_snapshot_to_a2,
)


def _section(**kwargs) -> CourseSectionInput:
    return CourseSectionInput(**kwargs)


def test_maps_introduction_conclusion_chapters_and_los():
    payload = RenderDocxRequest(
        courseTitle="Annuity Basics",
        sections=[
            _section(
                id="job-introduction",
                title="Introduction",
                level=1,
                sectionType="overview",
                content="Welcome to the course.",
                order=0,
            ),
            _section(
                id="job-los",
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
                    _section(
                        id="sec-2",
                        title="Tax deferral",
                        level=2,
                        sectionType="content",
                        paragraphs=[
                            {"type": "text", "content": "AI-edited deferral text."}
                        ],
                        order=1,
                    ),
                ],
            ),
            _section(
                id="job-conclusion",
                title="Conclusion",
                level=1,
                sectionType="conclusion",
                content="Thanks for completing the course.",
                order=3,
            ),
        ],
    )

    a2, los = map_editor_snapshot_to_a2(payload)

    assert a2.course_title == "Annuity Basics"
    assert a2.course_description == "Welcome to the course."
    assert a2.course_conclusion == "Thanks for completing the course."
    assert los == ["Explain annuities", "Compare products"]

    headings = [s["heading"] for s in a2.sections]
    assert headings == [
        "Why Annuities Matter",
        "Primary purposes",
        "Tax deferral",
    ]
    assert a2.sections[1]["body_paragraphs"][0]["content"] == "Manual edit about purposes."
    assert a2.sections[2]["body_paragraphs"][0]["content"] == "AI-edited deferral text."


def test_preserves_submitted_order_over_array_order():
    payload = RenderDocxRequest(
        courseTitle="Ordered",
        sections=[
            _section(
                id="ch-b",
                title="Chapter B",
                level=1,
                sectionType="content",
                content="B body",
                order=2,
            ),
            _section(
                id="ch-a",
                title="Chapter A",
                level=1,
                sectionType="content",
                content="A body",
                order=1,
                children=[
                    _section(
                        id="a2",
                        title="A2 later",
                        level=2,
                        content="second",
                        order=2,
                    ),
                    _section(
                        id="a1",
                        title="A1 first",
                        level=2,
                        content="first",
                        order=1,
                    ),
                ],
            ),
        ],
    )

    a2, _ = map_editor_snapshot_to_a2(payload)
    assert [s["heading"] for s in a2.sections] == [
        "Chapter A",
        "A1 first",
        "A2 later",
        "Chapter B",
    ]


def test_omitted_sections_are_absent():
    payload = RenderDocxRequest(
        courseTitle="Trimmed",
        sections=[
            _section(
                id="keep",
                title="Kept Chapter",
                level=1,
                sectionType="content",
                content="Keep me",
                order=0,
            ),
        ],
    )
    a2, _ = map_editor_snapshot_to_a2(payload)
    headings = [s["heading"] for s in a2.sections]
    assert headings == ["Kept Chapter"]
    assert "Deleted Chapter" not in headings


def test_paragraphs_take_precedence_over_plain_content():
    payload = RenderDocxRequest(
        courseTitle="Dup",
        sections=[
            _section(
                id="s1",
                title="Section",
                level=1,
                sectionType="content",
                content="Plain content that should be ignored",
                paragraphs=[{"type": "text", "content": "Structured paragraph wins"}],
                order=0,
            ),
        ],
    )
    a2, _ = map_editor_snapshot_to_a2(payload)
    bodies = a2.sections[0]["body_paragraphs"]
    assert len(bodies) == 1
    assert bodies[0]["content"] == "Structured paragraph wins"


def test_empty_snapshot_raises():
    with pytest.raises(EmptyCourseContentError):
        map_editor_snapshot_to_a2(RenderDocxRequest(courseTitle="Empty", sections=[]))


def test_intro_only_raises_without_content_sections():
    payload = RenderDocxRequest(
        courseTitle="Intro Only",
        sections=[
            _section(
                id="intro",
                title="Introduction",
                level=1,
                sectionType="overview",
                content="Just an intro",
                order=0,
            ),
        ],
    )
    with pytest.raises(EmptyCourseContentError):
        map_editor_snapshot_to_a2(payload)


def test_added_frontend_section_appears():
    payload = RenderDocxRequest(
        courseTitle="Manual Add",
        sections=[
            _section(
                id="new-ch",
                title="Brand New Chapter",
                level=1,
                sectionType="content",
                content="Author added this in the editor.",
                order=0,
            ),
        ],
    )
    a2, _ = map_editor_snapshot_to_a2(payload)
    assert a2.sections[0]["heading"] == "Brand New Chapter"
    assert "Author added this in the editor." in a2.sections[0]["body_paragraphs"][0]["content"]
