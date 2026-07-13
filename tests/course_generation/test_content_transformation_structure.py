"""Unit tests for structure-preserving paragraph validation."""

from __future__ import annotations

import pytest

from app.ai.agents.content_transformation_agent.errors import ContentTransformationError
from app.ai.agents.content_transformation_agent.structure_validator import (
    paragraphs_to_flat_content,
    validate_preserved_paragraphs,
)


def _source() -> list[dict]:
    return [
        {"id": "t1", "type": "text", "content": "Hello **world**"},
        {
            "id": "c1",
            "type": "important_callout",
            "label": "Important",
            "content": "Key point",
        },
        {
            "id": "c2",
            "type": "callout",
            "label": "Warning",
            "content": "Caution",
        },
        {
            "id": "c3",
            "type": "callout",
            "label": "Best Practice",
            "content": "Do this",
        },
        {"id": "l1", "type": "bullet_list", "items": ["A", "B"]},
        {"id": "l2", "type": "numbered_list", "items": ["One", "Two"]},
        {
            "id": "tb1",
            "type": "table",
            "caption": "Compare",
            "headers": ["Col1", "Col2"],
            "rows": [["r1c1", "r1c2"], ["r2c1", "r2c2"]],
        },
    ]


def test_validate_accepts_text_only_changes():
    source = _source()
    result = []
    for block in source:
        cloned = dict(block)
        if "content" in cloned:
            cloned["content"] = f"New {cloned['content']}"
        if "items" in cloned:
            cloned["items"] = [f"New {i}" for i in cloned["items"]]
        if "headers" in cloned:
            cloned["headers"] = [f"New {h}" for h in cloned["headers"]]
        if "rows" in cloned:
            cloned["rows"] = [[f"New {c}" for c in row] for row in cloned["rows"]]
        result.append(cloned)

    validated = validate_preserved_paragraphs(source, result)
    assert [b["id"] for b in validated] == [b["id"] for b in source]
    assert validated[0]["content"].startswith("New ")
    assert validated[1]["label"] == "Important"
    assert validated[2]["label"] == "Warning"
    assert validated[3]["label"] == "Best Practice"


def test_validate_repairs_missing_ids_and_types_from_source():
    """Models often omit id/type; restore them positionally from the request."""
    source = _source()
    result = []
    for block in source:
        cloned = {k: v for k, v in block.items() if k not in {"id", "type"}}
        if "content" in cloned:
            cloned["content"] = f"Expanded {cloned['content']}"
        if "items" in cloned:
            cloned["items"] = [f"Expanded {i}" for i in cloned["items"]]
        if "headers" in cloned:
            cloned["headers"] = list(cloned["headers"])
        if "rows" in cloned:
            cloned["rows"] = [list(row) for row in cloned["rows"]]
        # Keep label so protected metadata still matches for callouts.
        result.append(cloned)

    validated = validate_preserved_paragraphs(source, result)
    assert [b["id"] for b in validated] == [b["id"] for b in source]
    assert [b["type"] for b in validated] == [b["type"] for b in source]
    assert validated[0]["content"].startswith("Expanded ")
    assert validated[1]["label"] == "Important"
    assert validated[4]["items"][0].startswith("Expanded ")


def test_validate_repairs_missing_callout_label_from_source():
    source = _source()
    result = []
    for block in source:
        cloned = dict(block)
        if "content" in cloned:
            cloned["content"] = f"New {cloned['content']}"
        if "label" in cloned:
            del cloned["label"]
        result.append(cloned)

    validated = validate_preserved_paragraphs(source, result)
    assert validated[1]["label"] == "Important"
    assert validated[2]["label"] == "Warning"
    assert validated[3]["label"] == "Best Practice"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda blocks: blocks[:-1], "Block count changed"),
        (lambda blocks: list(reversed(blocks)), "Block id mismatch"),
        (
            lambda blocks: [{**blocks[0], "type": "heading_3"}, *blocks[1:]],
            "Block type mismatch",
        ),
        (
            lambda blocks: [
                blocks[0],
                {**blocks[1], "label": "Note"},
                *blocks[2:],
            ],
            "Protected metadata 'label'",
        ),
        (
            lambda blocks: [
                *blocks[:4],
                {**blocks[4], "items": ["only-one"]},
                *blocks[5:],
            ],
            "Protected metadata 'items_count'",
        ),
        (
            lambda blocks: [
                *blocks[:6],
                {
                    **blocks[6],
                    "headers": ["Col1"],
                    "rows": [["r1c1"], ["r2c1"]],
                },
            ],
            "Protected metadata 'headers_count'",
        ),
        (
            lambda blocks: [blocks[0], dict(blocks[0]), *blocks[2:]],
            "Duplicate block id",
        ),
    ],
)
def test_validate_rejects_structure_mutations(mutate, match):
    source = _source()
    result = mutate([dict(b) for b in source])
    with pytest.raises(ContentTransformationError, match=match):
        validate_preserved_paragraphs(source, result)


def test_paragraphs_to_flat_content_includes_callouts_lists_tables():
    flat = paragraphs_to_flat_content(_source())
    assert "Hello **world**" in flat
    assert "Key point" in flat
    assert "Caution" in flat
    assert "A" in flat
    assert "Col1 | Col2" in flat
