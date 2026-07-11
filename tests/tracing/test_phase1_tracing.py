"""Phase 1 tracing tests."""

from __future__ import annotations

import ast
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from app.tracing.models import GenerationTraceData, WorkflowTraceContext
from app.tracing.providers.jsonl import JsonlTracingProvider
from app.tracing.providers.registry import build_providers, reset_providers_cache
from app.tracing.sanitize import sanitize_secrets
from app.tracing.service import (
    atraced_workflow,
    flush_tracing,
    record_generation,
    stack_depth,
    traced_workflow,
)
from app.tracing import context as tracing_context

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"
APPROVED_LANGFUSE_IMPORT = (
    APP_ROOT / "tracing" / "providers" / "langfuse.py"
).relative_to(REPO_ROOT).as_posix()


class FakeProvider:
    name = "fake"

    def __init__(self, *, fail_enter: bool = False, fail_record: bool = False, fail_exit: bool = False) -> None:
        self.fail_enter = fail_enter
        self.fail_record = fail_record
        self.fail_exit = fail_exit
        self.workflows: list[tuple[str, Any]] = []
        self.generations: list[GenerationTraceData] = []
        self.flush_count = 0
        self.handles_seen: list[Any] = []

    @contextmanager
    def start_workflow(
        self,
        ctx: WorkflowTraceContext,
        *,
        parent: Any | None,
        input_data: Any = None,
    ) -> Iterator[Any]:
        self.handles_seen.append(parent)
        if self.fail_enter:
            raise RuntimeError("enter failed")
        handle = {"name": ctx.workflow, "parent": parent, "id": id(ctx)}
        self.workflows.append((ctx.workflow, parent))
        try:
            yield handle
        finally:
            if self.fail_exit:
                raise RuntimeError("exit failed")

    def record_generation(self, data: GenerationTraceData, *, parent: Any | None) -> None:
        if self.fail_record:
            raise RuntimeError("record failed")
        # Ensure secrets never arrive
        blob = json.dumps(
            {"s": data.system_prompt, "u": data.user_input, "r": data.response},
            default=str,
        )
        assert "sk-secret" not in blob
        assert "Bearer REALTOKEN" not in blob
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
    # Ensure no leaked workflow frames
    while tracing_context.get_stack():
        frame = tracing_context.current_frame()
        if frame is None:
            break
        tracing_context.pop_frame(frame.tokens)


def test_sanitize_redacts_secrets():
    payload = {
        "auth": "Bearer REALTOKEN",
        "key": "api_key=sk-secret-value",
        "conn": "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=ABC123==",
        "nested": ["password=hunter2", {"sig": "sig=SASTOKEN123"}],
    }
    cleaned = sanitize_secrets(payload)
    assert "REALTOKEN" not in json.dumps(cleaned)
    assert "sk-secret-value" not in json.dumps(cleaned)
    assert "ABC123" not in json.dumps(cleaned)
    assert "hunter2" not in json.dumps(cleaned)
    assert "SASTOKEN123" not in json.dumps(cleaned)
    assert isinstance(cleaned, dict)
    assert isinstance(cleaned["nested"], list)


def test_nested_workflows_provider_specific_parents():
    fake = FakeProvider()
    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("root", run_id="run-1", doc_name="Course_A"):
            assert stack_depth() == 1
            with traced_workflow("child", run_id="run-1", doc_name="Course_A"):
                assert stack_depth() == 2
                record_generation(
                    GenerationTraceData(
                        agent="RT_GEN",
                        system_prompt="sys",
                        user_input="user",
                        response="ok",
                    )
                )
        assert stack_depth() == 0

    assert fake.workflows[0][0] == "root"
    assert fake.workflows[0][1] is None
    assert fake.workflows[1][0] == "child"
    assert fake.workflows[1][1] is not None
    assert fake.workflows[1][1]["name"] == "root"
    assert fake.flush_count == 1  # root only
    assert fake.generations[0].metadata["doc_name"] == "Course_A"
    assert fake.generations[0].metadata["run_id"] == "run-1"


def test_two_providers_different_parent_handles():
    a = FakeProvider()
    a.name = "a"
    b = FakeProvider()
    b.name = "b"
    with patch("app.tracing.service.get_providers", return_value=(a, b)):
        with traced_workflow("root", run_id="r1", doc_name="doc"):
            with traced_workflow("nested", run_id="r1", doc_name="doc"):
                pass
    assert a.workflows[1][1]["name"] == "root"
    assert b.workflows[1][1]["name"] == "root"
    # Handles are provider-specific objects (not shared identity across providers)
    assert a.workflows[0][1] is None
    assert b.workflows[0][1] is None
    assert a.workflows[1][1] is not b.workflows[1][1]


def test_provider_record_failure_isolated():
    good = FakeProvider()
    good.name = "good"
    bad = FakeProvider(fail_record=True)
    bad.name = "bad"
    with patch("app.tracing.service.get_providers", return_value=(bad, good)):
        with traced_workflow("wf", run_id="r", doc_name="doc"):
            record_generation(
                GenerationTraceData(
                    agent="LO_GEN",
                    system_prompt="s",
                    user_input="u",
                    response="r",
                )
            )
    assert len(good.generations) == 1
    assert bad.flush_count == 1
    assert good.flush_count == 1


def test_provider_enter_failure_isolated():
    good = FakeProvider()
    good.name = "good"
    bad = FakeProvider(fail_enter=True)
    bad.name = "bad"
    with patch("app.tracing.service.get_providers", return_value=(bad, good)):
        with traced_workflow("wf", run_id="r", doc_name="doc"):
            record_generation(
                GenerationTraceData(
                    agent="LO_GEN",
                    system_prompt="s",
                    user_input="u",
                    response="r",
                )
            )
    assert good.workflows
    assert len(good.generations) == 1


def test_provider_exit_failure_still_flushes_others():
    good = FakeProvider()
    good.name = "good"
    bad = FakeProvider(fail_exit=True)
    bad.name = "bad"
    with patch("app.tracing.service.get_providers", return_value=(bad, good)):
        # Provider exit failures are isolated and must not raise into business code.
        with traced_workflow("wf", run_id="r", doc_name="doc"):
            pass
    assert good.flush_count == 1
    assert bad.flush_count == 1


def test_unsanitized_never_reaches_provider():
    fake = FakeProvider()
    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("wf", run_id="r", doc_name="doc"):
            record_generation(
                GenerationTraceData(
                    agent="RT_GEN",
                    system_prompt="Authorization: Bearer REALTOKEN",
                    user_input="api_key=sk-secret",
                    response="password=hunter2",
                )
            )
    assert "REALTOKEN" not in (fake.generations[0].system_prompt or "")
    assert "sk-secret" not in str(fake.generations[0].user_input)


def test_jsonl_persistence_with_secrets(tmp_path, monkeypatch):
    provider = JsonlTracingProvider()
    monkeypatch.setattr(
        "app.tracing.providers.jsonl._LOGS_ROOT",
        tmp_path,
    )
    with patch("app.tracing.service.get_providers", return_value=(provider,)):
        with traced_workflow("required_topics", run_id="rt-1", doc_name="My_Course"):
            record_generation(
                GenerationTraceData(
                    agent="RT_GEN",
                    system_prompt="Bearer REALTOKEN",
                    user_input="hello",
                    response="world",
                    model="gpt-test",
                )
            )
    path = tmp_path / "My_Course" / "RT_GEN" / "llm_traces.jsonl"
    assert path.exists()
    line = path.read_text(encoding="utf-8").strip()
    assert "REALTOKEN" not in line
    assert "unknown" not in str(path)
    record = json.loads(line)
    assert record["run_id"] == "rt-1"
    assert record["doc_name"] == "My_Course"


def test_async_workflow():
    fake = FakeProvider()

    async def _run():
        async with atraced_workflow("async_wf", run_id="a1", doc_name="doc"):
            record_generation(
                GenerationTraceData(
                    agent="RT_GEN",
                    system_prompt="s",
                    user_input="u",
                    response="r",
                )
            )

    import asyncio

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        asyncio.run(_run())
    assert fake.flush_count == 1
    assert fake.generations


def test_thread_context_propagation():
    fake = FakeProvider()
    results: list[str] = []

    def worker():
        results.append(tracing_context.get_run_id())
        record_generation(
            GenerationTraceData(
                agent="RT_GEN",
                system_prompt="s",
                user_input="u",
                response="r",
            )
        )

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("wf", run_id="thread-run", doc_name="doc"):
            with ThreadPoolExecutor(max_workers=1) as pool:
                tracing_context.submit_with_trace_context(pool, worker).result()
    assert results == ["thread-run"]
    assert len(fake.generations) == 1


def test_parallel_generations_no_crash():
    fake = FakeProvider()

    def gen(i: int):
        record_generation(
            GenerationTraceData(
                agent="A2",
                system_prompt="s",
                user_input=f"u{i}",
                response=f"r{i}",
            )
        )

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        with traced_workflow("content", run_id="c1", doc_name="doc"):
            threads = [threading.Thread(target=gen, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
    assert len(fake.generations) == 8


def test_langfuse_not_selected_no_adapter_import(monkeypatch):
    reset_providers_cache()
    monkeypatch.setenv("TRACING_PROVIDERS", "jsonl")
    providers = build_providers()
    assert [p.name for p in providers] == ["jsonl"]


def test_langfuse_selected_but_unavailable(monkeypatch):
    reset_providers_cache()
    monkeypatch.setenv("TRACING_PROVIDERS", "jsonl,langfuse")

    def boom():
        raise ImportError("no langfuse")

    with patch(
        "app.tracing.providers.registry._try_load_langfuse",
        side_effect=lambda: None,
    ):
        providers = build_providers()
    assert [p.name for p in providers] == ["jsonl"]


def test_tracing_disabled(monkeypatch):
    reset_providers_cache()
    monkeypatch.setenv("TRACING_ENABLED", "false")
    assert build_providers() == []


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
    offenders = sorted(set(offenders))
    assert offenders == [APPROVED_LANGFUSE_IMPORT]


def test_no_set_run_context_callers():
    hits: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "set_run_context(" in text and "def set_run_context" not in text:
            # Allow comments mentioning the removed API
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if "set_run_context(" in line:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{i}")
    assert hits == [], hits


@pytest.mark.asyncio
async def test_required_topics_hierarchy_mock_agents(monkeypatch):
    from app.orchestrators.required_topics.models import RequiredTopicsGenerationInput
    from app.orchestrators.required_topics.orchestrator import RequiredTopicsOrchestrator
    from app.ai.agents.required_topic.rt_generation.models import RTGenerationOutput
    from app.ai.agents.required_topic.rt_validator.models import RTValidationOutput
    from app.ai.agents.required_topic.rt_refine_agent.models import RTRefinementOutput

    fake = FakeProvider()

    class DummyKernel:
        pass

    orch = RequiredTopicsOrchestrator(DummyKernel())  # type: ignore[arg-type]

    async def gen_run(inp):
        record_generation(
            GenerationTraceData(
                agent="RT_GEN",
                system_prompt="sys",
                user_input="gen",
                response='{"required_topics":["A"]}',
            )
        )
        return RTGenerationOutput(topics=["A"])

    async def val_run(inp):
        record_generation(
            GenerationTraceData(
                agent="RT_VALIDATOR",
                system_prompt="sys",
                user_input="val",
                response='{"status":"fail","issues":[{"type":"x","message":"m","affected_topics":["A"],"expected_action":"fix"}]}',
            )
        )
        from app.ai.agents.required_topic.rt_validator.models import RTValidationIssue

        return RTValidationOutput(
            status="fail",
            issues=[
                RTValidationIssue(
                    type="x",
                    message="m",
                    affected_topics=["A"],
                    expected_action="fix",
                )
            ],
        )

    async def val_pass(inp):
        record_generation(
            GenerationTraceData(
                agent="RT_VALIDATOR",
                system_prompt="sys",
                user_input="val2",
                response='{"status":"pass","issues":[]}',
            )
        )
        return RTValidationOutput(status="pass", issues=[])

    async def refine_run(inp):
        record_generation(
            GenerationTraceData(
                agent="RT_REFINE",
                system_prompt="sys",
                user_input="refine",
                response='{"required_topics":["A fixed"]}',
            )
        )
        return RTRefinementOutput(topics=["A fixed"])

    calls = {"val": 0}

    async def val_dispatch(inp):
        calls["val"] += 1
        if calls["val"] == 1:
            return await val_run(inp)
        return await val_pass(inp)

    monkeypatch.setattr(orch.generation_agent, "run", gen_run)
    monkeypatch.setattr(orch.validator_agent, "run", val_dispatch)
    monkeypatch.setattr(orch.refinement_agent, "run", refine_run)

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        result = await orch.execute(
            RequiredTopicsGenerationInput(
                course_title="Safety Training",
                course_scope="scope",
                course_type="compliance",
                course_duration="1h",
                difficulty_level="beginner",
                target_audience="staff",
                learner_experience_level="beginner",
                learner_outcomes=["know rules"],
            )
        )

    assert result.validation_passed is True
    assert result.repair_attempts == 1
    agents = [g.agent for g in fake.generations]
    assert agents == ["RT_GEN", "RT_VALIDATOR", "RT_REFINE", "RT_VALIDATOR"]
    assert all(g.metadata.get("workflow") == "required_topics" for g in fake.generations)
    assert all(g.metadata.get("doc_name") == "Safety_Training" for g in fake.generations)
    assert fake.flush_count == 1
    assert fake.workflows[0][0] == "required_topics"


def test_learning_objectives_hierarchy_mock_agents(monkeypatch):
    from app.orchestrators.learning_objective.models import (
        LearningObjectiveGenerationInput,
    )
    from app.orchestrators.learning_objective.orchestrator import (
        LearningObjectiveOrchestrator,
    )
    from app.ai.agents.learning_objective_agent.Lo_generation.models import (
        LOGenerationOutput,
    )
    from app.ai.agents.learning_objective_agent.Lo_validator.models import (
        LOValidationOutput,
        LOValidationIssue,
    )
    from app.ai.agents.learning_objective_agent.Lo_refine_agent.models import (
        LORefinementOutput,
    )

    fake = FakeProvider()
    orch = LearningObjectiveOrchestrator(object())  # type: ignore[arg-type]

    def gen_run(inp):
        record_generation(
            GenerationTraceData(
                agent="LO_GEN",
                system_prompt="s",
                user_input="g",
                response="{}",
            )
        )
        return LOGenerationOutput(objectives=["Obj 1"])

    calls = {"val": 0}

    def val_run(inp):
        calls["val"] += 1
        record_generation(
            GenerationTraceData(
                agent="LO_VALIDATOR",
                system_prompt="s",
                user_input="v",
                response="{}",
            )
        )
        if calls["val"] == 1:
            return LOValidationOutput(
                status="fail",
                issues=[
                    LOValidationIssue(
                        type="x",
                        message="m",
                        affected_objectives=["Obj 1"],
                        expected_action="fix",
                    )
                ],
            )
        return LOValidationOutput(status="pass", issues=[])

    def refine_run(inp):
        record_generation(
            GenerationTraceData(
                agent="LO_REFINE",
                system_prompt="s",
                user_input="r",
                response="{}",
            )
        )
        return LORefinementOutput(objectives=["Obj 1 fixed"])

    monkeypatch.setattr(orch.generation_agent, "run", gen_run)
    monkeypatch.setattr(orch.validator_agent, "run", val_run)
    monkeypatch.setattr(orch.refinement_agent, "run", refine_run)

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        result = orch.generate_learning_objectives(
            LearningObjectiveGenerationInput(
                course_title="Annuities 101",
                course_description="desc",
                course_type="compliance",
                course_duration="2h",
                skill_level="beginner",
                target_audience="agents",
                required_topics=["Basics"],
                source_materials=[],
            )
        )

    assert result.validation_passed is True
    assert [g.agent for g in fake.generations] == [
        "LO_GEN",
        "LO_VALIDATOR",
        "LO_REFINE",
        "LO_VALIDATOR",
    ]
    assert all(g.metadata.get("workflow") == "learning_objectives" for g in fake.generations)
    assert all(g.metadata.get("doc_name") == "Annuities_101" for g in fake.generations)
    assert fake.flush_count == 1


@pytest.mark.asyncio
async def test_required_topics_regenerate(monkeypatch):
    from app.orchestrators.required_topics.models import RequiredTopicsRegenerationInput
    from app.orchestrators.required_topics.orchestrator import RequiredTopicsOrchestrator
    from app.ai.agents.required_topic.regenerate_required_topic_agent.models import (
        RTRegenerationOutput,
    )

    fake = FakeProvider()
    orch = RequiredTopicsOrchestrator(object())  # type: ignore[arg-type]

    async def regen_run(self, inp):
        record_generation(
            GenerationTraceData(
                agent="RT_REGEN",
                system_prompt="s",
                user_input="u",
                response="{}",
            )
        )
        return RTRegenerationOutput(topics=["T1"])

    monkeypatch.setattr(
        "app.orchestrators.required_topics.orchestrator.RTRegenerationAgent.run",
        regen_run,
    )

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        result = await orch.regenerate_required_topics(
            RequiredTopicsRegenerationInput(
                current_topics=["T0"],
                regeneration_prompt="make better",
            )
        )
    assert result.topics == ["T1"]
    assert fake.workflows[0][0] == "required_topics_regenerate"
    assert fake.generations[0].agent == "RT_REGEN"
    assert fake.flush_count == 1


def test_learning_objectives_regenerate(monkeypatch):
    from app.orchestrators.learning_objective.models import (
        LearningObjectiveRegenerationInput,
    )
    from app.orchestrators.learning_objective.orchestrator import (
        LearningObjectiveOrchestrator,
    )
    from app.ai.agents.learning_objective_agent.Lo_regenerate_agent.models import (
        LORegenerationOutput,
    )

    fake = FakeProvider()
    orch = LearningObjectiveOrchestrator(object())  # type: ignore[arg-type]

    def regen_run(self, inp):
        record_generation(
            GenerationTraceData(
                agent="LO_REGEN",
                system_prompt="s",
                user_input="u",
                response="{}",
            )
        )
        return LORegenerationOutput(objectives=["O1"])

    monkeypatch.setattr(
        "app.orchestrators.learning_objective.orchestrator.LORegenerationAgent.run",
        regen_run,
    )

    with patch("app.tracing.service.get_providers", return_value=(fake,)):
        result = orch.regenerate_learning_objectives(
            LearningObjectiveRegenerationInput(
                current_objectives=["O0"],
                regeneration_prompt="improve",
                course_title="Course X",
            )
        )
    assert result.objectives == ["O1"]
    assert fake.workflows[0][0] == "learning_objectives_regenerate"
    assert fake.flush_count == 1
