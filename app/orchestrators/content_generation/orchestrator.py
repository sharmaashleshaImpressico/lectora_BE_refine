"""Orchestrates content generation workflows."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from semantic_kernel import Kernel

from app.ai.agents.content_generation_agent.content_validation import (
    validate_content,
)
from app.ai.agents.content_generation_agent.content_writer_agent.content_refine_agent import (
    refine_sections,
)
from app.ai.agents.content_generation_agent.content_writer_agent.runner import (
    generate_course_content,
    render_study_guide,
)
from app.ai.agents.content_generation_agent.models import (
    A2Output,
    A2Stats,
    S2Status,
    S2ValidationReport,
)
from app.ai.agents.content_generation_agent.section_mapper.runner import (
    map_sections,
)
from app.ai.rule_pack_config import resolve_content_rule_pack_from_shared_state
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)


def _doc_name(title: str | None, fallback: str) -> str:
    s = re.sub(r"[^\w.\-]+", "_", (title or "").strip(), flags=re.UNICODE).strip("._")
    return s or fallback

_MAX_REPAIR_ATTEMPTS = 2


class StageReporter(Protocol):
    """Callback interface for surfacing pipeline stage progress to a caller.

    Deliberately kernel/DB-agnostic — this orchestrator stays pure. A caller
    (e.g. the Service Bus pipeline runner) supplies an adapter backed by
    whatever progress-tracking store it uses.
    """

    def start(self, stage_code: str, message: str) -> None: ...
    def complete(self, stage_code: str, message: str, *, outcome: str | None = None) -> None: ...
    def retry(self, stage_code: str, message: str) -> None: ...
    def fail(self, stage_code: str, message: str, *, blockers: list[dict[str, Any]] | None = None) -> None: ...


class _NullStageReporter:
    """No-op reporter used when a caller doesn't care about stage progress."""

    def start(self, stage_code: str, message: str) -> None:
        pass

    def complete(self, stage_code: str, message: str, *, outcome: str | None = None) -> None:
        pass

    def retry(self, stage_code: str, message: str) -> None:
        pass

    def fail(self, stage_code: str, message: str, *, blockers: list[dict[str, Any]] | None = None) -> None:
        pass


def _issues_to_blockers(validation: S2ValidationReport) -> list[dict[str, Any]]:
    return [
        {"severity": issue.severity, "field": issue.field, "message": issue.message}
        for issue in validation.issues
        if issue.severity == "blocker"
    ]


def _is_blocked(validation: S2ValidationReport) -> bool:
    return validation.blockers > 0


# Stamped onto every section of a lesson that stayed blocked after the repair
# limit but was accepted anyway so course generation could continue.
VALIDATION_ACCEPTED_AFTER_MAX_RETRIES = "accepted_after_max_retries"


def _interim_a2_output(
    *, run_id: str, course_title: str, sections: list[dict[str, Any]]
) -> A2Output:
    """Minimal `A2Output` over in-progress sections for the validator/refiner.

    Mid-generation there is no description/conclusion yet; S2 and
    CONTENT_REFINE only read `status`, `sections`, and course metadata.
    """
    failed = sum(1 for s in sections if s.get("status") == "failed")
    return A2Output(
        status="complete" if failed == 0 else "partial",
        run_id=run_id,
        course_title=course_title or "Untitled Course",
        sections=sections,
        stats=A2Stats(
            generated=sum(1 for s in sections if s.get("status") == "generated"),
            skipped=sum(1 for s in sections if s.get("status") == "skipped_thin"),
            failed=failed,
            total_words=sum(int(s.get("word_count") or 0) for s in sections),
        ),
    )


def _merge_lesson_reports(
    reports: list[S2ValidationReport],
    *,
    run_id: str,
    accepted_after_max_retries: list[str] | None = None,
) -> S2ValidationReport:
    """Fold per-lesson S2 reports into one course-level report.

    Preserves the shape of the single report the pipeline runner persists as
    `validation_report.json` — same model, aggregated counts, all issues.
    Lessons accepted despite exhausting the repair limit keep their blocker
    issues in the report (for review visibility), and are named in `message`.
    """
    accepted = accepted_after_max_retries or []
    issues = [issue for report in reports for issue in report.issues]
    blockers = sum(r.blockers for r in reports)
    warnings = sum(r.warnings for r in reports)
    if blockers > 0:
        # Blockers here can only come from accepted-after-max-retries lessons
        # (every other lesson passed its gate) — surfaced as warnings-level
        # status so the course still completes, with the issues kept above.
        status = S2Status.pass_with_warnings
    elif warnings > 0:
        status = S2Status.pass_with_warnings
    else:
        status = S2Status.pass_
    message = f"Sequential per-lesson validation across {len(reports)} lesson(s)."
    if accepted:
        message += (
            f" {len(accepted)} lesson(s) accepted after max repair attempts "
            f"with unresolved issues: {', '.join(repr(t) for t in accepted)}."
        )
    return S2ValidationReport(
        status=status,
        run_id=run_id,
        issues=issues,
        blockers=blockers,
        criticals=sum(r.criticals for r in reports),
        warnings=warnings,
        infos=sum(r.infos for r in reports),
        message=message,
        phase="full",
    )


@dataclass
class ContentGenerationInput:
    """Everything the content-generation pipeline needs — no shared_state.json."""

    run_id: str
    course_spec: dict[str, Any]
    outline: dict[str, Any]
    course_title: str
    course_description: str
    learning_objectives: list[str]
    docx_path: str
    content_sample: str = ""
    course_difficulty: str = "intermediate"
    course_audience: str = ""
    special_instructions: str | None = None
    course_config: dict[str, Any] = field(default_factory=dict)
    source_file_specs: list[dict[str, Any]] | None = None
    rule_family: str | None = None
    output_path: str | None = None
    course_id: str | None = None
    # Ingestion-time document identifiers for this course's uploaded source
    # files. Always written onto every indexed chunk (unlike course_id, which
    # is optional at upload time and can silently fall back to a slugified
    # course-topic folder name — see document_upload_service.upload_document).
    # Preferred over course_id for scoping section-mapper retrieval; None
    # until the upload flow persists document_id back onto CourseRunInput
    # (see Known Gaps in CLAUDE.md re: API <-> pipeline wiring).
    document_ids: list[str] | None = None
    jurisdiction: str | None = None


@dataclass
class ContentGenerationResult:
    """Final output of the content generation (A2/S2) pipeline."""

    enriched_sections: list[dict[str, Any]]
    a2: A2Output
    validation: S2ValidationReport
    validation_passed: bool
    repair_attempts: int
    blocked: bool
    study_guide_path: str | None


class ContentGenerationOrchestrator:
    """
    Workflow:

    Section Mapper
        ↓
    Generate (A2)
        ↓
    Validate (S2)
        ↓
    Refine (CONTENT_REFINE)
        ↓
    Validate (S2)
        ↓
    Pass / Fail → render study guide on pass
    """

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel

    def execute(
        self, spec: ContentGenerationInput, *, on_stage: StageReporter | None = None
    ) -> ContentGenerationResult:
        reporter = on_stage or _NullStageReporter()
        logger.info(
            "[content_generation] Starting | title=%r | difficulty=%r",
            spec.course_title,
            spec.course_difficulty,
        )

        doc_name = _doc_name(spec.course_title, "content_generation")

        with traced_workflow(
            "content_generation",
            run_id=spec.run_id,
            doc_name=doc_name,
            course_id=spec.course_id,
            course_run_id=spec.run_id,
            metadata={"course_title": spec.course_title},
            input_data={
                "course_title": spec.course_title,
                "difficulty": spec.course_difficulty,
            },
        ):
            return self._execute_pipeline(spec, reporter)

    def _execute_pipeline(
        self,
        spec: ContentGenerationInput,
        reporter: StageReporter,
    ) -> ContentGenerationResult:
        # Step 1: Section Mapper — maps the TO outline onto course_spec content.
        reporter.start(
            "SECTION_MAPPER", "Section Mapper running — retrieving source content for each section…"
        )
        enriched_sections = map_sections(
            spec.course_spec,
            spec.outline,
            course_id=spec.course_id,
            document_ids=spec.document_ids,
            jurisdiction=spec.jurisdiction,
        )
        reporter.complete(
            "SECTION_MAPPER",
            f"Sections mapped to source content ({len(enriched_sections)} lesson(s)).",
        )

        # Rule pack + validation context are resolved up front (rather than
        # after A2, as in the previous whole-course flow) because the
        # per-lesson gate below validates while generation is still running.
        rule_pack = resolve_content_rule_pack_from_shared_state(
            {"course_difficulty": spec.course_difficulty, "rule_family": spec.rule_family},
            purpose="validate",
            difficulty_override=spec.course_difficulty,
        )
        if not rule_pack:
            raise RuntimeError(f"Could not resolve rule pack for difficulty {spec.course_difficulty!r}")

        validation_context = {
            "course_title": spec.course_title,
            "course_audience": spec.course_audience,
            "course_difficulty": spec.course_difficulty,
            "special_instructions": spec.special_instructions,
            "extracted_inputs": {"learning_objectives": spec.learning_objectives},
        }

        lesson_reports: list[S2ValidationReport] = []
        lessons_accepted_after_max_retries: list[str] = []
        repair_attempts_total = 0

        def _validate_lesson(
            sections: list[dict[str, Any]], lesson_title: str
        ) -> S2ValidationReport:
            with traced_workflow("S2"):
                return validate_content(
                    self.kernel,
                    sections=sections,
                    a2_output=_interim_a2_output(
                        run_id=spec.run_id,
                        course_title=spec.course_title,
                        sections=sections,
                    ),
                    rule_pack=rule_pack,
                    context=validation_context,
                    run_id=spec.run_id,
                    phase="lesson",
                    lesson_title=lesson_title,
                )

        def _lesson_gate(
            lesson_idx: int,
            total_lessons: int,
            lesson: dict[str, Any],
            lesson_sections: list[dict[str, Any]],
            all_sections: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            """Validate one generated lesson; refine until it passes or the
            retry limit is hit. A lesson still blocked after the limit is
            accepted as-is (latest refined version, stamped in metadata) so
            the remaining lessons still generate. Returning replaces the
            lesson's sections — the writer only starts the next lesson after
            this returns."""
            nonlocal repair_attempts_total
            lesson_title = str(lesson.get("title") or "").strip()
            prev_sections = all_sections[: len(all_sections) - len(lesson_sections)]
            current = lesson_sections

            validation = _validate_lesson(prev_sections + current, lesson_title)

            attempt = 0
            while _is_blocked(validation) and attempt < _MAX_REPAIR_ATTEMPTS:
                attempt += 1
                repair_attempts_total += 1
                logger.info(
                    "[content_generation] Lesson %s/%s refinement attempt %s/%s | blockers=%s",
                    lesson_idx,
                    total_lessons,
                    attempt,
                    _MAX_REPAIR_ATTEMPTS,
                    validation.blockers,
                )
                reporter.retry(
                    "A2",
                    f"Lesson {lesson_idx}/{total_lessons} has {validation.blockers} "
                    f"blocker(s) — refining (attempt {attempt}/{_MAX_REPAIR_ATTEMPTS})…",
                )
                with traced_workflow("CONTENT_REFINE"):
                    refined = refine_sections(
                        self.kernel,
                        a2_output=_interim_a2_output(
                            run_id=spec.run_id,
                            course_title=spec.course_title,
                            sections=prev_sections + current,
                        ),
                        s2_report=validation,
                        rule_pack=rule_pack,
                        context=validation_context,
                        lesson_title=lesson_title,
                    )
                # The refiner merges positionally, so this lesson's sections
                # are exactly the tail beyond the already-accepted ones.
                current = refined.sections[len(prev_sections):]
                validation = _validate_lesson(prev_sections + current, lesson_title)

            if _is_blocked(validation):
                # Retry limit exhausted — accept the latest refined version so
                # the remaining lessons still generate. The lesson's blocker
                # issues stay in its report (merged into the course report),
                # and its sections are stamped for downstream visibility.
                lessons_accepted_after_max_retries.append(lesson_title)
                current = [
                    {**section, "validation_status": VALIDATION_ACCEPTED_AFTER_MAX_RETRIES}
                    for section in current
                ]
                logger.warning(
                    "[content_generation] Lesson %s/%s (%r) still has %s blocker(s) "
                    "after %s repair attempt(s) — accepting latest version and "
                    "continuing with the next lesson.",
                    lesson_idx,
                    total_lessons,
                    lesson_title,
                    validation.blockers,
                    _MAX_REPAIR_ATTEMPTS,
                )
                reporter.retry(
                    "A2",
                    f"Lesson {lesson_idx}/{total_lessons} still has "
                    f"{validation.blockers} blocker(s) after {_MAX_REPAIR_ATTEMPTS} "
                    "repair attempt(s) — accepted as-is; continuing with the next lesson.",
                )
            else:
                logger.info(
                    "[content_generation] Lesson %s/%s validated (%s attempt(s) used).",
                    lesson_idx,
                    total_lessons,
                    attempt,
                )

            lesson_reports.append(validation)
            return current

        # Step 2: Sequential generation (A2) — each lesson is validated (S2)
        # and, if blocked, refined (CONTENT_REFINE) before the next lesson is
        # generated. A lesson still blocked after the repair limit is accepted
        # as-is (stamped in metadata) and generation continues, so one bad
        # lesson never aborts the course. Prompts and generation logic are
        # untouched; the loop lives in `generate_all_sections`, which calls
        # the gate per lesson.
        reporter.start(
            "A2", "Generating course content lesson-by-lesson with per-lesson validation…"
        )
        with traced_workflow("A2"):
            current_a2 = generate_course_content(
                self.kernel,
                run_id=spec.run_id,
                enriched_sections=enriched_sections,
                docx_path=spec.docx_path,
                course_title=spec.course_title,
                course_description=spec.course_description,
                learning_objectives=spec.learning_objectives,
                content_sample=spec.content_sample,
                course_difficulty=spec.course_difficulty,
                course_audience=spec.course_audience,
                special_instructions=spec.special_instructions,
                course_config=spec.course_config,
                source_file_specs=spec.source_file_specs,
                lesson_gate_hook=_lesson_gate,
                rule_pack=rule_pack,
            )
        reporter.complete(
            "A2",
            f"Course content generated and validated for {len(current_a2.sections)} "
            f"section(s) across {len(enriched_sections)} lesson(s).",
        )

        # Step 3: Consolidate (S2) — fold the per-lesson reports into the
        # single course-level report the pipeline runner persists as
        # validation_report.json. Lessons accepted after the repair limit keep
        # their blocker issues in the report but do not fail the course.
        reporter.start("S2", "Consolidating validation results…")
        if lesson_reports:
            validation = _merge_lesson_reports(
                lesson_reports,
                run_id=spec.run_id,
                accepted_after_max_retries=lessons_accepted_after_max_retries,
            )
        else:
            # No lesson produced sections through the gate (edge case) — fall
            # back to the previous whole-course validation pass.
            with traced_workflow("S2"):
                validation = validate_content(
                    self.kernel,
                    sections=current_a2.sections,
                    a2_output=current_a2,
                    rule_pack=rule_pack,
                    context=validation_context,
                    run_id=spec.run_id,
                    phase="full",
                )
            if _is_blocked(validation):
                reporter.fail(
                    "S2",
                    "Content validation blocked.",
                    blockers=_issues_to_blockers(validation),
                )
                return ContentGenerationResult(
                    enriched_sections=enriched_sections,
                    a2=current_a2,
                    validation=validation,
                    validation_passed=False,
                    repair_attempts=repair_attempts_total,
                    blocked=True,
                    study_guide_path=None,
                )

        if lessons_accepted_after_max_retries:
            accepted_names = ", ".join(repr(t) for t in lessons_accepted_after_max_retries)
            reporter.complete(
                "S2",
                f"Content validated — {len(lessons_accepted_after_max_retries)} lesson(s) "
                f"accepted after max repair attempts with unresolved issues: {accepted_names}. "
                "Review recommended.",
                outcome="WARNING",
            )
        else:
            success_note = (
                f" ({repair_attempts_total} refinement attempt(s) across lessons)"
                if repair_attempts_total
                else ""
            )
            reporter.complete(
                "S2", f"Content validated successfully{success_note}.", outcome="PASS"
            )
        return ContentGenerationResult(
            enriched_sections=enriched_sections,
            a2=current_a2,
            validation=validation,
            validation_passed=True,
            repair_attempts=repair_attempts_total,
            blocked=False,
            study_guide_path=self._maybe_render(current_a2, spec, reporter),
        )

    def _maybe_render(
        self,
        a2_output: A2Output,
        spec: ContentGenerationInput,
        reporter: StageReporter,
    ) -> str | None:
        if not spec.output_path:
            return None
        reporter.start("A6", "Packaging your course — assembling the final study guide…")
        path = render_study_guide(a2_output, spec.learning_objectives, spec.output_path)
        reporter.complete("A6", "Course packaged and ready.")
        return path
