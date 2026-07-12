"""Unit tests for ContentTransformationAgent and prompt builder."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ai.agents.content_transformation_agent.main import (
    AGENT_LABEL,
    ContentTransformationAgent,
    ContentTransformationError,
)
from app.ai.agents.content_transformation_agent.models import (
    ContentTransformationAgentInput,
)
from app.ai.agents.content_transformation_agent.prompt_builder import (
    ContentTransformationPromptBuilder,
)
from app.ai.agents.content_transformation_agent.prompts import (
    COMMON_INSTRUCTIONS,
    OPERATION_INSTRUCTIONS,
    STRUCTURE_PRESERVATION_INSTRUCTIONS,
)
from app.schemas.ai.content_ai import ContentAiOperation


def _mixed_paragraphs() -> list[dict]:
    return [
        {
            "id": "b1",
            "type": "text",
            "content": "Annuities provide **guaranteed** income over time.",
        },
        {
            "id": "b2",
            "type": "important_callout",
            "label": "Important",
            "content": "Surrender charges may apply.",
        },
        {
            "id": "b3",
            "type": "callout",
            "label": "Warning",
            "content": "Do not misrepresent liquidity.",
        },
        {
            "id": "b4",
            "type": "callout",
            "label": "Best Practice",
            "content": "Document suitability carefully.",
        },
        {
            "id": "b5",
            "type": "bullet_list",
            "items": ["Fixed annuity", "Variable annuity"],
        },
        {
            "id": "b6",
            "type": "numbered_list",
            "items": ["Assess needs", "Compare products"],
        },
        {
            "id": "b7",
            "type": "table",
            "caption": "Product comparison",
            "headers": ["Feature", "Fixed", "Variable"],
            "rows": [
                ["Principal", "Guaranteed", "Market-based"],
                ["Risk", "Low", "Higher"],
            ],
        },
    ]


def _transformed_paragraphs() -> list[dict]:
    source = _mixed_paragraphs()
    out = []
    for block in source:
        cloned = dict(block)
        if "content" in cloned and isinstance(cloned["content"], str):
            cloned["content"] = f"TX: {cloned['content']}"
        if "items" in cloned:
            cloned["items"] = [f"TX: {item}" for item in cloned["items"]]
        if "headers" in cloned:
            cloned["headers"] = [f"TX: {h}" for h in cloned["headers"]]
        if "rows" in cloned:
            cloned["rows"] = [[f"TX: {c}" for c in row] for row in cloned["rows"]]
        if "caption" in cloned:
            cloned["caption"] = f"TX: {cloned['caption']}"
        out.append(cloned)
    return out


@pytest.fixture
def builder() -> ContentTransformationPromptBuilder:
    return ContentTransformationPromptBuilder()


@pytest.mark.parametrize("operation", list(ContentAiOperation))
def test_prompt_builder_layers_and_delimiters(builder, operation):
    input_data = ContentTransformationAgentInput(
        operation=operation,
        content="<p>Source body</p>",
        user_prompt="Make it clearer" if operation.value in {"rewrite", "improve_tone"} else None,
    )

    system = builder.build_system_prompt(input_data)
    user = builder.build_user_message(input_data)

    assert "COMMON INSTRUCTIONS" in system
    assert COMMON_INSTRUCTIONS.strip().splitlines()[0] in system
    assert "OPERATION INSTRUCTIONS" in system
    assert OPERATION_INSTRUCTIONS[operation] in system

    assert "<source_content>" in user
    assert "</source_content>" in user
    assert "<p>Source body</p>" in user
    assert "<source_paragraphs>" not in user

    if input_data.user_prompt:
        assert "<user_instruction>" in user
        assert "Make it clearer" in user
    else:
        assert "<user_instruction>" not in user


def test_prompt_builder_structure_mode_sends_paragraphs(builder):
    paragraphs = _mixed_paragraphs()
    input_data = ContentTransformationAgentInput(
        operation=ContentAiOperation.summarize,
        content="flat preview",
        paragraphs=paragraphs,
        preserve_structure=True,
    )

    system = builder.build_system_prompt(input_data)
    user = builder.build_user_message(input_data)

    assert STRUCTURE_PRESERVATION_INSTRUCTIONS.strip().splitlines()[0] in system
    assert "<source_paragraphs>" in user
    assert '"label": "Important"' in user
    assert '"label": "Warning"' in user
    assert '"label": "Best Practice"' in user
    assert '"type": "table"' in user
    assert "<source_content_preview>" in user
    assert "flat preview" in user


def test_agent_parses_structured_output_success():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"content": "  Transformed HTML  "}),
    ) as chat_mock:
        result = agent.run(
            ContentTransformationAgentInput(
                operation=ContentAiOperation.summarize,
                content="Long source",
            )
        )

    assert result.content == "Transformed HTML"
    assert result.paragraphs is None
    assert chat_mock.call_args.args[4] == AGENT_LABEL


def test_agent_structure_mode_returns_validated_paragraphs():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)
    source = _mixed_paragraphs()
    transformed = _transformed_paragraphs()

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"paragraphs": transformed}),
    ):
        result = agent.run(
            ContentTransformationAgentInput(
                operation=ContentAiOperation.simplify,
                content="preview",
                paragraphs=source,
                preserve_structure=True,
            )
        )

    assert result.paragraphs is not None
    assert len(result.paragraphs) == len(source)
    assert [p["id"] for p in result.paragraphs] == [p["id"] for p in source]
    assert [p["type"] for p in result.paragraphs] == [p["type"] for p in source]
    assert result.paragraphs[1]["label"] == "Important"
    assert result.paragraphs[2]["label"] == "Warning"
    assert result.paragraphs[3]["label"] == "Best Practice"
    assert result.paragraphs[0]["content"].startswith("TX:")
    assert "**guaranteed**" in result.paragraphs[0]["content"]
    assert len(result.paragraphs[4]["items"]) == 2
    assert len(result.paragraphs[6]["headers"]) == 3
    assert len(result.paragraphs[6]["rows"]) == 2
    assert result.content  # compatibility flat field derived


@pytest.mark.parametrize(
    "raw,match",
    [
        ("not-json", "invalid JSON"),
        (json.dumps({"content": ""}), "empty transformed"),
        (json.dumps({"content": 123}), "string 'content'"),
        (json.dumps(["x"]), "non-object"),
        ("", "empty response"),
    ],
)
def test_agent_raises_on_structured_output_failure(raw, match):
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=raw,
    ):
        with pytest.raises(ContentTransformationError, match=match):
            agent.run(
                ContentTransformationAgentInput(
                    operation=ContentAiOperation.expand,
                    content="Source",
                )
            )


def test_agent_structure_mode_repairs_missing_ids_from_model():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)
    source = _mixed_paragraphs()
    # Simulate real model behavior: transformed text, omitted ids.
    transformed = []
    for block in source:
        cloned = {k: v for k, v in block.items() if k != "id"}
        if "content" in cloned:
            cloned["content"] = f"TX: {cloned['content']}"
        if "items" in cloned:
            cloned["items"] = [f"TX: {item}" for item in cloned["items"]]
        if "headers" in cloned:
            cloned["headers"] = [f"TX: {h}" for h in cloned["headers"]]
        if "rows" in cloned:
            cloned["rows"] = [[f"TX: {c}" for c in row] for row in cloned["rows"]]
        transformed.append(cloned)

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"paragraphs": transformed}),
    ):
        result = agent.run(
            ContentTransformationAgentInput(
                operation=ContentAiOperation.expand,
                content="preview",
                paragraphs=source,
                preserve_structure=True,
            )
        )

    assert result.paragraphs is not None
    assert [p["id"] for p in result.paragraphs] == [p["id"] for p in source]
    assert result.paragraphs[1]["label"] == "Important"
    assert result.paragraphs[0]["content"].startswith("TX:")


def test_agent_structure_mode_rejects_reordered_or_missing_blocks():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)
    source = _mixed_paragraphs()
    bad = list(reversed(_transformed_paragraphs()))

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"paragraphs": bad}),
    ):
        with pytest.raises(ContentTransformationError, match="Block id mismatch"):
            agent.run(
                ContentTransformationAgentInput(
                    operation=ContentAiOperation.summarize,
                    content="preview",
                    paragraphs=source,
                    preserve_structure=True,
                )
            )


def test_agent_structure_mode_rejects_changed_callout_label():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)
    source = _mixed_paragraphs()
    bad = _transformed_paragraphs()
    bad[1]["label"] = "Note"

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"paragraphs": bad}),
    ):
        with pytest.raises(ContentTransformationError, match="Protected metadata 'label'"):
            agent.run(
                ContentTransformationAgentInput(
                    operation=ContentAiOperation.improve_tone,
                    content="preview",
                    user_prompt="More formal",
                    paragraphs=source,
                    preserve_structure=True,
                )
            )


def test_agent_structure_mode_rejects_changed_table_dimensions():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)
    source = _mixed_paragraphs()
    bad = _transformed_paragraphs()
    bad[6]["rows"] = [["only one cell"]]

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"paragraphs": bad}),
    ):
        with pytest.raises(ContentTransformationError, match="Protected metadata"):
            agent.run(
                ContentTransformationAgentInput(
                    operation=ContentAiOperation.expand,
                    content="preview",
                    paragraphs=source,
                    preserve_structure=True,
                )
            )


def test_agent_raises_on_provider_failure():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        side_effect=RuntimeError("azure down"),
    ):
        with pytest.raises(ContentTransformationError, match="provider call failed"):
            agent.run(
                ContentTransformationAgentInput(
                    operation=ContentAiOperation.simplify,
                    content="Source",
                )
            )


def test_agent_does_not_return_original_on_failure():
    kernel = MagicMock()
    agent = ContentTransformationAgent(kernel)
    original = "Original unsaved content"

    with patch(
        "app.ai.agents.content_transformation_agent.main.chat",
        return_value=json.dumps({"content": ""}),
    ):
        with pytest.raises(ContentTransformationError):
            agent.run(
                ContentTransformationAgentInput(
                    operation=ContentAiOperation.summarize,
                    content=original,
                )
            )
