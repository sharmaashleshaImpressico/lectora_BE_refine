"""Phase 2 tracing tests — Topic Outline, Content Generation, course job nesting."""

from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.tracing import context as tracing_context
from app.tracing.models import GenerationTraceData, WorkflowTraceContext
from app.tracing.providers.registry import reset_providers_cache
from app.tracing.service import record_generation, traced_workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"
APPROVED_LANGFUSE_IMPORT = (
    APP_ROOT / "tracing" / "providers" / "langfuse.py"
).relative_to(REPO_ROOT).as_posix()


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.workflows: list[tuple[str, Any]] = []
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
        handle = {"name": ctx.workflow, "parent": parent}
        self.workflows.append((ctx.workflow, parent))
        yield handle

    def record_generation(self, data: GenerationTraceData, *, parent: Any | None) -> None:
        self.generations.append(data)

    def flush(self) -> None:
        self.flush_count += 1

    def shutdown(self) -> None:
        return


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


def test_topic_outline_nests_a0_s1_refine_single_flush():
    fake = FakeProvider()

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("topic_outline", run_id="to-1", doc_name="Course"):
            with traced_workflow("A0"):
                record_generation(
                    GenerationTraceData(
                        agent="A0_TO",
                        system_prompt="s",
                        user_input="u",
                        response="r",
                    )
                )
            with traced_workflow("S1"):
                pass
            with traced_workflow("S1_TO_REFINE"):
                record_generation(
                    GenerationTraceData(
                        agent="S1_TO_REFINE",
                        system_prompt="s",
                        user_input="u",
                        response="r",
                    )
                )

    names = [n for n, _ in fake.workflows]
    assert names == ["topic_outline", "A0", "S1", "S1_TO_REFINE"]
    assert fake.workflows[0][1] is None
    assert fake.workflows[1][1] is not None
    assert fake.flush_count == 1


def test_content_generation_stage_hierarchy():
    fake = FakeProvider()

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("content_generation", run_id="cg-1", doc_name="Course"):
            with traced_workflow("A2"):
                record_generation(
                    GenerationTraceData(
                        agent="A2",
                        system_prompt="s",
                        user_input="u",
                        response="r",
                        observation_name="content generate · Intro",
                    )
                )
            with traced_workflow("S2"):
                record_generation(
                    GenerationTraceData(
                        agent="S2",
                        system_prompt="s",
                        user_input="u",
                        response="r",
                    )
                )
            with traced_workflow("CONTENT_REFINE"):
                record_generation(
                    GenerationTraceData(
                        agent="CONTENT_REFINE",
                        system_prompt="s",
                        user_input="u",
                        response="r",
                    )
                )

    assert [n for n, _ in fake.workflows] == [
        "content_generation",
        "A2",
        "S2",
        "CONTENT_REFINE",
    ]
    assert fake.flush_count == 1


def test_course_job_nests_content_no_duplicate_root():
    fake = FakeProvider()

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow(
            "course_generation",
            run_id="job-1",
            session_id="run-1",
            job_id="job-1",
            course_run_id="run-1",
            doc_name="job_job-1",
        ):
            with traced_workflow("source_processing"):
                pass
            with traced_workflow(
                "content_generation",
                run_id="run-1",
                doc_name="Course",
                course_run_id="run-1",
            ):
                with traced_workflow("A2"):
                    record_generation(
                        GenerationTraceData(
                            agent="A2",
                            system_prompt="s",
                            user_input="u",
                            response="r",
                        )
                    )

    names = [n for n, _ in fake.workflows]
    assert names[0] == "course_generation"
    assert names[1] == "source_processing"
    assert names[2] == "content_generation"
    assert names[3] == "A2"
    # Only the outermost root has parent None
    assert sum(1 for _, parent in fake.workflows if parent is None) == 1
    assert fake.flush_count == 1


def test_content_orchestrator_nests_under_course_root():
    """ContentGenerationOrchestrator must nest when a parent workflow exists."""
    from app.orchestrators.content_generation.orchestrator import (
        ContentGenerationOrchestrator,
        ContentGenerationInput,
    )

    fake = FakeProvider()
    orch = ContentGenerationOrchestrator(MagicMock())

    def fake_pipeline(spec, reporter):
        record_generation(
            GenerationTraceData(
                agent="A2",
                system_prompt="s",
                user_input="u",
                response="r",
            )
        )
        return MagicMock(
            enriched_sections=[],
            a2=MagicMock(),
            validation=MagicMock(blockers=0, warnings=0, infos=0, phase="full", message=""),
            validation_passed=True,
            repair_attempts=0,
            blocked=False,
            study_guide_path=None,
        )

    orch._execute_pipeline = fake_pipeline  # type: ignore[method-assign]

    spec = ContentGenerationInput(
        run_id="run-x",
        course_spec={"sections": []},
        outline={"sections": []},
        course_title="Nest Course",
        course_description="",
        learning_objectives=[],
        docx_path="",
        course_id="1",
    )

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("course_generation", run_id="job-x", doc_name="job"):
            orch.execute(spec)

    names = [n for n, _ in fake.workflows]
    assert names[0] == "course_generation"
    assert "content_generation" in names
    assert names.index("content_generation") > 0
    assert fake.flush_count == 1


def test_no_obsolete_langfuse_public_api_callers():
    banned = (
        "flush_langfuse(",
        "shutdown_langfuse(",
        "set_langfuse_step_label(",
        "write_span(",
        "span_context(",
    )
    hits: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("app/shared_llm_config/tracer.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in banned:
                if token in line:
                    hits.append(f"{rel}:{i}:{token}")
    assert hits == [], hits


def test_import_boundary_only_langfuse_adapter():
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "langfuse" or alias.name.startswith("langfuse."):
                        offenders.append(rel)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "langfuse" or mod.startswith("langfuse."):
                    offenders.append(rel)
    assert sorted(set(offenders)) == [APPROVED_LANGFUSE_IMPORT]


def test_orchestrators_use_traced_workflow():
    files = {
        "app/orchestrators/topic_outline/orchestrator.py": "topic_outline",
        "app/orchestrators/content_generation/orchestrator.py": "content_generation",
        "app/services/onboarding/course_generation/pipeline_runner.py": "course_generation",
        "app/services/onboarding/course_generation/training_outline_service.py": "outline_enrichment",
        "app/ai/agents/to_generation_pipeline/step_01_parse_and_generate_outline/phases/synthesizer.py": '"A0"',
    }
    for rel, needle in files.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "traced_workflow" in text, rel
        assert needle in text, f"{rel} missing {needle}"
