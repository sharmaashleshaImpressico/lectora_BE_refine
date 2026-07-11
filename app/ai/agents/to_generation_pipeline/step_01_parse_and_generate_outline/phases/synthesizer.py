"""
A0 — Request Synthesizer & Input Normalizer

Accepts one or more source .docx / .pdf files and an optional Timed Outline.

Scenario 1 — TO provided:
  Parses the uploaded TO (DOCX/PDF) via LLM into structured outline JSON.

Scenario 2 — NO TO provided:
  Extracts structured content from source files (headings + para indices for DOCX,
  TOC entries + section content for PDF) and sends only the structured data to the
  LLM using GENERATE_TO_PROMPT.  No raw file upload to the Files API.

In both scenarios A0 runs rule-family classification and writes shared_state plus
llm_to_outline.json for downstream agents.
"""

import logging
import threading
import uuid
from typing import Callable, Optional, TYPE_CHECKING

from semantic_kernel import Kernel

from app.core.storage.blob_file_resolver import resolve_source_path
from ..shared.constants.difficulty import (
    DEFAULT_TO_DURATION_HOURS,
    compute_calculated_word_count,
)
from ..shared.constants.pipeline_config import DEFAULT_DIFFICULTY
from ..shared.helpers.output_slug import OutputSlugResolver
from .classification_phase import ClassificationPhase
from .finalization_phase import FinalizationPhase
from .parse_phase import ParsePhase
from .to_generation_phase import TOGenerationPhase
from app.ai.agents.to_generation_pipeline.models import A0Result

if TYPE_CHECKING:
    from ..shared.models.to_wizard_prompt_context import ToWizardPromptContext

logger = logging.getLogger(__name__)


class A0RequestSynthesizer:
    """
    A0 — Request Synthesizer & Input Normalizer

    All source docs (`docx_paths` / `pdf_paths`): metadata, headings, indexed
    paragraphs, images, and rule-family classification are extracted in code.

    Timed-outline doc (`to_outline_doc_path`, optional):
      - If provided: parsed via LLM into structured outline JSON (Scenario 1).
      - If omitted: TO is generated from uploaded source files via LLM (Scenario 2).

    Outputs: request_spec, provenance_log, shared_state, and llm_to_outline —
    held in memory / persisted to Azure Blob Storage by callers, never to
    local disk.
    """

    def __init__(
        self,
        kernel: Kernel,
        docx_paths: Optional[list[str]] = None,
        pdf_paths: Optional[list[str]] = None,
        to_outline_doc_path: Optional[str] = None,
        course_difficulty: str = DEFAULT_DIFFICULTY,
        extra_text_contents: Optional[list[str]] = None,
        custom_to_prompt: Optional[str] = None,
        course_type_hint: Optional[str] = None,
        audience: Optional[str] = None,
        step_logger: Optional[Callable[[str, str, str | None], None]] = None,
        *,
        docx_path: Optional[str] = None,
        extra_docx_paths: Optional[list[str]] = None,
        course_output_slug: Optional[str] = None,
        duration_hours: Optional[float] = None,
        difficulty_level: Optional[str] = None,
        calculated_word_count: Optional[int] = None,
        course_description: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        use_static_prompt: bool = False,
        rule_family: Optional[str] = None,
        validation_hints: Optional[str] = None,
        wizard_course_title: Optional[str] = None,
        wizard_learning_objectives: Optional[list[str]] = None,
        preferred_chapters: Optional[int] = None,
        wizard_prompt_context: Optional["ToWizardPromptContext"] = None,
    ):
        self.kernel = kernel
        raw_docx_paths: list[str] = [str(path) for path in (docx_paths or []) if path]
        raw_pdf_paths: list[str] = [str(path) for path in (pdf_paths or []) if path]
        if not raw_docx_paths and docx_path:
            raw_docx_paths = [str(docx_path)]
            raw_docx_paths.extend(str(path) for path in (extra_docx_paths or []) if path)
        if not raw_docx_paths and not raw_pdf_paths:
            raise ValueError("At least one docx or pdf path is required")

        # `raw_docx_paths`/`raw_pdf_paths` are Azure blob paths (or, for local dev
        # without Azure configured, references into the local upload fallback
        # root) — not local filesystem paths. Resolve each to a real local file
        # (downloading from Azure Blob Storage as needed) here, once, so every
        # downstream consumer of `self.docx_paths`/`self.pdf_paths`/
        # `self.to_outline_doc_path` (ParsePhase, CourseDocParser, PDFSourceParser,
        # DocumentTitleCollector, TOGenerationPhase's `open(...)` for JSON TOs)
        # always sees an absolute local path.
        paths = [resolve_source_path(path) for path in raw_docx_paths]
        pdfs = [resolve_source_path(path) for path in raw_pdf_paths]

        self.docx_paths = paths
        self.pdf_paths = pdfs
        self.docx_path = paths[0] if paths else pdfs[0]

        raw_to_outline = (to_outline_doc_path or "").strip() or None
        if not raw_to_outline and use_static_prompt:
            if len(raw_docx_paths) == 1 and not raw_pdf_paths:
                raw_to_outline = raw_docx_paths[0]
            elif len(raw_pdf_paths) == 1 and not raw_docx_paths:
                raw_to_outline = raw_pdf_paths[0]

        resolved_to_outline: str | None = None
        if raw_to_outline:
            if raw_to_outline in raw_docx_paths:
                # Already resolved above — reuse it instead of downloading twice.
                resolved_to_outline = paths[raw_docx_paths.index(raw_to_outline)]
            elif raw_to_outline in raw_pdf_paths:
                resolved_to_outline = pdfs[raw_pdf_paths.index(raw_to_outline)]
            else:
                resolved_to_outline = resolve_source_path(raw_to_outline)

        self.to_outline_doc_path = resolved_to_outline
        self.course_difficulty = (course_difficulty or DEFAULT_DIFFICULTY).strip().lower()
        self.run_id = str(uuid.uuid4())[:8]
        self.extra_text_contents: list[str] = extra_text_contents or []
        self.custom_to_prompt: Optional[str] = custom_to_prompt
        self.course_type_hint: Optional[str] = course_type_hint
        self.audience: Optional[str] = (audience or "").strip() or None
        self.course_description: Optional[str] = (course_description or "").strip() or None
        self.course_output_slug = (course_output_slug or "").strip() or None
        self.step_logger = step_logger

        self.difficulty_level: str = (
            (difficulty_level or course_difficulty or DEFAULT_DIFFICULTY).strip().lower()
        )
        self._generate_to_from_source: bool = not bool(resolved_to_outline)
        if self._generate_to_from_source:
            self.duration_hours: float = (
                float(duration_hours)
                if duration_hours is not None
                else float(DEFAULT_TO_DURATION_HOURS)
            )
            self.calculated_word_count: int = (
                int(calculated_word_count)
                if calculated_word_count is not None
                else compute_calculated_word_count(
                    self.duration_hours, self.difficulty_level
                )
            )
        else:
            self.duration_hours = float(duration_hours) if duration_hours is not None else None
            self.calculated_word_count = (
                int(calculated_word_count) if calculated_word_count is not None else None
            )

        self.use_static_prompt: bool = use_static_prompt
        self.rule_family: Optional[str] = (rule_family or "").strip() or None
        self.validation_hints: Optional[str] = (validation_hints or "").strip() or None
        self.cancel_event: Optional[threading.Event] = cancel_event
        self.wizard_course_title: Optional[str] = (wizard_course_title or "").strip() or None
        self.wizard_learning_objectives: Optional[list[str]] = (
            list(wizard_learning_objectives) if wizard_learning_objectives else None
        )
        self.preferred_chapters: Optional[int] = (
            int(preferred_chapters) if preferred_chapters is not None else None
        )
        self.wizard_prompt_context = wizard_prompt_context

    def _emit_step(self, message: str, *, level: str = "info", stage: str = "A0") -> None:
        if self.step_logger:
            self.step_logger(level, message, stage)

    def _check_cancelled(self) -> None:
        if self.cancel_event and self.cancel_event.is_set():
            raise RuntimeError("Cancelled")

    def _resolve_trace_doc_name(self) -> str:
        return OutputSlugResolver.resolve(
            course_output_slug=self.course_output_slug,
            docx_paths=self.docx_paths,
            pdf_paths=self.pdf_paths,
            run_id=self.run_id,
        )

    def _ensure_trace_context(self) -> None:
        from app.ai.shared_llm_config.tracer import (
            set_run_context,
            set_source_refs,
        )

        doc_name = self._resolve_trace_doc_name()
        source_refs = [*self.docx_paths, *self.pdf_paths]
        if self.to_outline_doc_path:
            source_refs.append(self.to_outline_doc_path)
        # Always overwrite run_id so retry cycles (cycle 2, 3) don't inherit the
        # previous cycle's trace ID and contaminate the earlier trace.
        set_run_context(self.run_id, doc_name, source_refs=source_refs)

    def run(self) -> A0Result:
        self._ensure_trace_context()

        parsed = ParsePhase(self).execute()
        paragraphs_by_source = ParsePhase.build_paragraphs_by_source(parsed)
        classification = ClassificationPhase(self, parsed).prepare()
        generation = TOGenerationPhase(self, parsed, classification, paragraphs_by_source).execute()
        return FinalizationPhase(self, parsed, classification, generation).execute()
