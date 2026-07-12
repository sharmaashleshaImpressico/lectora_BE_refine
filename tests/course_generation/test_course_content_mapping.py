"""Tests for GET /jobs/{id}/course A2 → editor payload mapping."""

from __future__ import annotations

from app.services.onboarding.course_generation.course_content_service import (
    _group_a2_sections_by_lesson,
    _map_a2_output,
)


def _subtopic(lesson: str, heading: str, *, level: int = 2, words: int = 10) -> dict:
    return {
        "heading": heading,
        "level": level,
        "outline_lesson": lesson,
        "body_paragraphs": [{"type": "text", "content": f"{heading} body"}],
        "word_count": words,
        "section_id": "",
        "images": [],
    }


def test_map_a2_output_creates_one_chapter_per_outline_lesson_without_parents():
    """When A2 emits only level-2 subtopics, still produce one chapter per lesson."""
    lessons = [
        "1.0 Why Annuities Matter",
        "2.0 Distinguishing Annuity Structures",
        "3.0 Evaluating Contract Features",
    ]
    raw_sections = [
        _subtopic(lessons[0], "Primary purposes"),
        _subtopic(lessons[0], "Tax deferral"),
        _subtopic(lessons[1], "Immediate versus deferred"),
        _subtopic(lessons[1], "Fixed annuities"),
        _subtopic(lessons[2], "Surrender charges"),
    ]

    result = _map_a2_output(
        "1",
        {
            "course_title": "Test Course",
            "course_description": "Intro text.",
            "sections": raw_sections,
            "timestamp": "2026-07-12T09:21:22Z",
        },
        course_type="Insurance CE",
    )

    # Intro + 3 lesson chapters
    assert result["meta"]["sectionCount"] == 4
    assert result["meta"]["chapterCount"] == 4
    titles = [s["title"] for s in result["sections"]]
    assert titles[0] == "Introduction"
    assert titles[1:] == lessons
    assert [len(s["children"]) for s in result["sections"][1:]] == [2, 2, 1]


def test_map_a2_output_uses_existing_parent_overview_when_present():
    parent = {
        "heading": "1.0 Why Annuities Matter",
        "level": 1,
        "is_parent_overview": True,
        "outline_lesson": "1.0 Why Annuities Matter",
        "body_paragraphs": [{"type": "text", "content": "Overview"}],
        "word_count": 5,
        "section_id": "",
        "images": [],
    }
    child = _subtopic("1.0 Why Annuities Matter", "Primary purposes")
    result = _map_a2_output(
        "9",
        {"course_title": "T", "sections": [parent, child]},
        course_type="",
    )
    assert result["meta"]["chapterCount"] == 1
    chapter = result["sections"][0]
    assert chapter["title"] == "1.0 Why Annuities Matter"
    assert chapter["content"] == "Overview"
    assert len(chapter["children"]) == 1
    assert chapter["children"][0]["title"] == "Primary purposes"


def test_map_a2_output_dedupes_colliding_section_ids():
    sections = [
        _subtopic("Lesson A", "First"),
        _subtopic("Lesson A", "Second"),
    ]
    # Both empty section_id used to collide as "{job}-sec-1" under the old mapper.
    result = _map_a2_output("1", {"course_title": "T", "sections": sections}, course_type="")
    ids = [result["sections"][0]["id"]] + [c["id"] for c in result["sections"][0]["children"]]
    assert len(ids) == len(set(ids))


def test_group_a2_sections_by_lesson_preserves_order():
    raw = [
        _subtopic("L1", "a"),
        _subtopic("L1", "b"),
        _subtopic("L2", "c"),
    ]
    groups = _group_a2_sections_by_lesson(raw)
    assert [key for key, _ in groups] == ["L1", "L2"]
    assert [len(secs) for _, secs in groups] == [2, 1]
