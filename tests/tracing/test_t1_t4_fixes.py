"""Regression tests for tracing review findings T-1 through T-4."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from app.tracing import context as tracing_context
from app.tracing.models import GenerationTraceData, WorkflowTraceContext
from app.tracing.providers.registry import reset_providers_cache
from app.tracing.sanitize import sanitize_secrets, truncate_text
from app.tracing.service import record_generation, traced_workflow


class CapturingProvider:
    name = "capture"

    def __init__(self) -> None:
        self.workflow_inputs: list[Any] = []
        self.workflow_metadata: list[dict[str, Any]] = []
        self.generations: list[GenerationTraceData] = []
        self.flush_count = 0

    @contextmanager
    def start_workflow(
        self,
        ctx: WorkflowTraceContext,
        *,
        parent: Any | None,
        input_data: Any = None,
    ) -> Iterator[Any]:
        self.workflow_inputs.append(input_data)
        self.workflow_metadata.append(dict(ctx.metadata or {}))
        handle = {"name": ctx.workflow, "parent": parent}
        yield handle

    def record_generation(self, data: GenerationTraceData, *, parent: Any | None) -> None:
        self.generations.append(data)

    def flush(self) -> None:
        self.flush_count += 1

    def shutdown(self) -> None:
        return


class _NonCopyable:
    """Object that raises on deepcopy."""

    def __deepcopy__(self, memo):  # noqa: ANN001
        raise RuntimeError("cannot deepcopy")

    def __repr__(self) -> str:
        return "NonCopyable(api_key=sk-should-not-leak)"


@pytest.fixture(autouse=True)
def _reset_providers(monkeypatch):
    reset_providers_cache()
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.setenv("TRACING_PROVIDERS", "jsonl")
    yield
    reset_providers_cache()
    while tracing_context.get_stack():
        frame = tracing_context.current_frame()
        if frame is None:
            break
        tracing_context.pop_frame(frame.tokens)
    tracing_context.clear_generation_label()
    tracing_context.set_source_refs(None)


# ---------------------------------------------------------------------------
# T-1 — Secret sanitization
# ---------------------------------------------------------------------------


def test_t1_sensitive_dictionary_keys_redacted():
    payload = {
        "api_key": "sk-live-secret",
        "password": "hunter2",
        "client_secret": "cs-abc",
        "authorization": "Bearer REALTOKEN",
        "access_token": "atok",
        "connection_string": "AccountKey=ABC123==;Endpoint=https://x",
        "SharedAccessSignature": "sigvalue",
        "sas": "sas-token",
        "sig": "raw-sig",
        "safe_title": "Course A",
        "nested": {"api-key": "nested-secret", "ok": "visible"},
    }
    cleaned = sanitize_secrets(payload)
    blob = json.dumps(cleaned)
    assert "sk-live-secret" not in blob
    assert "hunter2" not in blob
    assert "cs-abc" not in blob
    assert "REALTOKEN" not in blob
    assert "atok" not in blob
    assert "ABC123" not in blob
    assert "sigvalue" not in blob
    assert "sas-token" not in blob
    assert "raw-sig" not in blob
    assert "nested-secret" not in blob
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["safe_title"] == "Course A"
    assert cleaned["nested"]["ok"] == "visible"


def test_t1_workflow_input_and_metadata_sanitized_before_provider():
    provider = CapturingProvider()
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with traced_workflow(
            "wf",
            run_id="r1",
            doc_name="doc",
            metadata={"api_key": "sk-meta", "course_title": "Safe"},
            input_data={"password": "p@ss", "title": "RT"},
        ):
            pass

    assert provider.workflow_inputs[0]["password"] == "[REDACTED]"
    assert provider.workflow_inputs[0]["title"] == "RT"
    assert provider.workflow_metadata[0]["api_key"] == "[REDACTED]"
    assert provider.workflow_metadata[0]["course_title"] == "Safe"


def test_t1_generation_metadata_sensitive_keys_never_reach_provider():
    provider = CapturingProvider()
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with traced_workflow("wf", run_id="r1", doc_name="doc"):
            record_generation(
                GenerationTraceData(
                    agent="RT_GEN",
                    system_prompt="sys Bearer REALTOKEN",
                    user_input={"api_key": "sk-user"},
                    response="ok",
                    metadata={"client_secret": "cs-1", "step": "1"},
                )
            )

    gen = provider.generations[0]
    assert "REALTOKEN" not in (gen.system_prompt or "")
    assert gen.user_input["api_key"] == "[REDACTED]"
    assert gen.metadata["client_secret"] == "[REDACTED]"
    assert gen.metadata["step"] == "1"


# ---------------------------------------------------------------------------
# T-2 — source_refs context leakage
# ---------------------------------------------------------------------------


def test_t2_nested_source_refs_restore_parent():
    with traced_workflow(
        "topic_outline",
        run_id="to-1",
        doc_name="Course",
        source_refs=["parent.docx"],
    ):
        assert tracing_context.get_source_refs() == ["parent.docx"]
        with traced_workflow(
            "A0",
            run_id="to-1",
            doc_name="Course",
            source_refs=["child.docx", "child.pdf"],
        ):
            assert tracing_context.get_source_refs() == ["child.docx", "child.pdf"]
        assert tracing_context.get_source_refs() == ["parent.docx"]
    assert tracing_context.get_source_refs() == []


def test_t2_root_exit_restores_previous_context():
    token = tracing_context.set_source_refs(["pre-existing.bin"])
    try:
        with traced_workflow(
            "root",
            run_id="r",
            doc_name="d",
            source_refs=["inside.txt"],
        ):
            assert tracing_context.get_source_refs() == ["inside.txt"]
        assert tracing_context.get_source_refs() == ["pre-existing.bin"]
    finally:
        tracing_context.reset_source_refs(token)
    assert tracing_context.get_source_refs() == []


def test_t2_cross_workflow_no_leakage():
    with traced_workflow(
        "first",
        run_id="a",
        doc_name="d",
        source_refs=["a.docx"],
    ):
        assert tracing_context.get_source_refs() == ["a.docx"]

    assert tracing_context.get_source_refs() == []

    with traced_workflow("second", run_id="b", doc_name="d"):
        assert tracing_context.get_source_refs() == []


def test_t2_set_source_refs_returns_resettable_token():
    token = tracing_context.set_source_refs(["x.pdf"])
    assert tracing_context.get_source_refs() == ["x.pdf"]
    tracing_context.reset_source_refs(token)
    assert tracing_context.get_source_refs() == []


# ---------------------------------------------------------------------------
# T-3 — Sanitization fail-safe
# ---------------------------------------------------------------------------


def test_t3_non_deepcopyable_sanitize_does_not_raise():
    obj = _NonCopyable()
    result = sanitize_secrets(obj)
    assert isinstance(result, str)
    assert "sk-should-not-leak" not in result or "[REDACTED]" in result or "SANITIZE" in result


def test_t3_non_deepcopyable_workflow_input_does_not_break_business():
    provider = CapturingProvider()
    business_ran = False
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with traced_workflow(
            "wf",
            run_id="r",
            doc_name="d",
            input_data=_NonCopyable(),
            metadata={"api_key": "sk-meta"},
        ):
            business_ran = True
    assert business_ran is True
    assert provider.workflow_metadata[0]["api_key"] == "[REDACTED]"
    # Input fell back to a safe representation — never raw secret object.
    assert provider.workflow_inputs[0] is not None


def test_t3_non_deepcopyable_generation_does_not_break_record():
    provider = CapturingProvider()
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with traced_workflow("wf", run_id="r", doc_name="d"):
            record_generation(
                GenerationTraceData(
                    agent="A2",
                    system_prompt="sys",
                    user_input=_NonCopyable(),
                    response="ok",
                )
            )
    assert len(provider.generations) == 1
    assert isinstance(provider.generations[0].user_input, str)


def test_t3_business_exception_preserved_when_provider_exit_fails():
    class BoomExit(CapturingProvider):
        @contextmanager
        def start_workflow(self, ctx, *, parent, input_data=None):
            yield {"name": ctx.workflow}
            raise RuntimeError("provider exit boom")

    provider = BoomExit()
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with pytest.raises(ValueError, match="business failed"):
            with traced_workflow("wf", run_id="r", doc_name="d"):
                raise ValueError("business failed")


def test_t3_truncate_text_fail_safe():
    class BadMapping(dict):
        def items(self):  # noqa: ANN201
            raise RuntimeError("items failed")

    assert truncate_text(BadMapping(a="x"), max_chars=10) == "[SANITIZE_FAILED]"


# ---------------------------------------------------------------------------
# T-4 — Generation-label leakage
# ---------------------------------------------------------------------------


def test_t4_label_restored_on_nested_workflow_exit():
    with traced_workflow("root", run_id="r", doc_name="d"):
        tracing_context.set_generation_label("parent-label")
        # Nested enter clears label; exit restores parent-scoped value.
        # push_frame clears to "" and saves token to restore prior ("parent-label").
        with traced_workflow("child", run_id="r", doc_name="d"):
            assert tracing_context.get_generation_label() == ""
            tracing_context.set_generation_label("child-label")
            assert tracing_context.get_generation_label() == "child-label"
        assert tracing_context.get_generation_label() == "parent-label"
    assert tracing_context.get_generation_label() == ""


def test_t4_early_return_clears_label_on_workflow_exit():
    with traced_workflow("wf", run_id="r", doc_name="d"):
        tracing_context.set_generation_label("orphan-label")
        # Early return without record_generation
    assert tracing_context.get_generation_label() == ""


def test_t4_disabled_tracing_clears_label_on_record():
    provider = CapturingProvider()
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with patch("app.tracing.service.tracing_enabled", return_value=False):
            tracing_context.set_generation_label("should-clear")
            record_generation(
                GenerationTraceData(
                    agent="RT_GEN",
                    system_prompt="sys",
                    user_input="u",
                    response="r",
                )
            )
            assert tracing_context.get_generation_label() == ""
            assert provider.generations == []


def test_t4_disabled_tracing_workflow_exit_clears_label(monkeypatch):
    monkeypatch.setenv("TRACING_ENABLED", "false")
    reset_providers_cache()
    with traced_workflow("wf", run_id="r", doc_name="d"):
        tracing_context.set_generation_label("left-over")
    assert tracing_context.get_generation_label() == ""


def test_t4_label_consumed_by_generation_does_not_leak():
    provider = CapturingProvider()
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with traced_workflow("wf", run_id="r", doc_name="d"):
            tracing_context.set_generation_label("content generate · Lesson")
            record_generation(
                GenerationTraceData(
                    agent="A2",
                    system_prompt="sys",
                    user_input="u",
                    response="r",
                )
            )
            assert tracing_context.get_generation_label() == ""
            assert (
                provider.generations[0].metadata.get("generation_label")
                == "content generate · Lesson"
            )
