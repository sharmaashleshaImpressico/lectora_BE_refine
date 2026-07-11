"""
A2 — Content Generator (pure, kernel-based; no ``shared_state.json``).

Expects the caller (the content-generation orchestrator) to already have
Section Mapper's ``enriched_sections`` and the resolved course metadata in
hand — nothing here reads or writes any state file.

enriched_sections shape (one entry per TO lesson):
  {
    "title":               str,   # TO lesson title
    "content":             str,   # TO Content Objective
    "word_count":          str,   # raw string, e.g. "4115"
    "minutes":              str,
    "credit_hour":          str,
    "interactive_elements": list,
    "subtopics": [
      {
        "title":              str,   # course_spec heading
        "id":                 str,
        "level":              int,
        "subtopics":          list,
        "maps_to_objectives": list,
        "images":             list,
        "image_count":        int,
        "interactive_elements": list,
        "matched_chunks":     list,
      }, ...
    ]
  }

Flow:
  1. Resolve the rule pack for the requested difficulty.
  2. Generate study guide content lesson-by-lesson, subtopic-by-subtopic.
  3. Build the course conclusion.
  4. Return a typed ``A2Output`` (caller decides whether/when to render docx).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from semantic_kernel import Kernel

from app.kernel.chat import chat as kernel_chat
from app.tracing import set_generation_label
from app.ai.agents.content_generation_agent.models import A2Output, A2Stats
from app.ai.rule_pack_config.content_generation_filter import (
    resolve_content_rule_pack_from_shared_state,
)

from ..config.llm import CONCLUSION_CONFIG
from ..step_01_generate_content.utils.content_writer import generate_all_sections
from ..step_03_conclusion.constants.prompts import (
    CONCLUSION_SYSTEM_PROMPT,
    build_conclusion_user_message,
)
from ..step_04_render_docx.utils.doc_formatter import build_study_guide_docx
from ..shared.helpers.text_utils import _strip_fences

logger = logging.getLogger(__name__)


def _build_source_guidance(
    special_instructions: str | None,
    source_file_specs: list[dict] | None,
) -> str | None:
    if not source_file_specs:
        return special_instructions

    sorted_specs = sorted(
        source_file_specs,
        key=lambda s: (0 if (s.get("extract_hint") or "").strip() else 1),
    )
    guidance_lines = ["## Source Material Guidance"]
    guidance_lines.append(
        "The following source files were provided by the course author. "
        "Respect what they asked to get from each source when drawing on source material:"
    )
    for spec in sorted_specs:
        name = spec.get("blob_path", "").split("/")[-1]
        hint = (spec.get("extract_hint") or "").strip()
        if hint:
            guidance_lines.append(f"- {name}: What to get from this source — {hint}")
        else:
            guidance_lines.append(f"- {name}")
    source_guidance = "\n".join(guidance_lines)
    return f"{source_guidance}\n\n{special_instructions}" if special_instructions else source_guidance


def _build_course_conclusion(
    kernel: Kernel,
    course_title: str,
    *,
    content_sample: str | None = None,
    learning_objectives: list[str] | None = None,
    generated_sections: list[dict] | None = None,
) -> str:
    """Generate the final Conclusion section via LLM (grounded in source + outline)."""
    if not (content_sample or "").strip():
        logger.warning("[A2] No content_sample — conclusion left empty.")
        return ""

    title_for_prompt = (course_title or "").strip() or "Untitled Course"
    user_msg = build_conclusion_user_message(
        title_for_prompt,
        content_sample or "",
        learning_objectives=learning_objectives or [],
        generated_sections=generated_sections or [],
    )

    try:
        set_generation_label(f"content generate · Conclusion · {title_for_prompt}")
        raw = kernel_chat(kernel, CONCLUSION_SYSTEM_PROMPT, user_msg, CONCLUSION_CONFIG, "A2")
        text = _strip_fences(raw)
        if not text:
            logger.warning("[A2] LLM returned empty conclusion after strip.")
            return ""
        logger.info("[A2] Conclusion via LLM (%s words).", len(text.split()))
        return text
    except Exception as exc:
        logger.warning("[A2] Conclusion LLM failed (%s) — leaving empty.", exc)
        return ""


def _build_a2_output(
    *,
    run_id: str,
    course_title: str,
    generated_sections: list[dict],
    course_description: str,
    course_conclusion: str,
) -> A2Output:
    total_generated_words = sum(s.get("word_count", 0) for s in generated_sections)
    successful = sum(1 for s in generated_sections if s.get("status") == "generated")
    failed = sum(1 for s in generated_sections if s.get("status") == "failed")
    skipped = sum(1 for s in generated_sections if s.get("status") == "skipped_thin")
    stats = A2Stats(
        generated=successful,
        skipped=skipped,
        failed=failed,
        total_words=total_generated_words,
    )
    return A2Output(
        status="complete" if failed == 0 else "partial",
        run_id=run_id,
        course_title=course_title,
        sections=generated_sections,
        stats=stats,
        course_description=course_description,
        course_conclusion=course_conclusion,
        study_guide_docx=None,
        generated_content_json=None,
        timestamp=datetime.now(timezone.utc),
    )


def generate_course_content(
    kernel: Kernel,
    *,
    run_id: str,
    enriched_sections: list[dict],
    docx_path: str,
    course_title: str,
    course_description: str,
    learning_objectives: list[str],
    content_sample: str = "",
    course_difficulty: str = "intermediate",
    course_audience: str = "",
    special_instructions: str | None = None,
    course_config: dict | None = None,
    source_file_specs: list[dict] | None = None,
    feedback: str | None = None,
) -> A2Output:
    """Generate study-guide content for every lesson in ``enriched_sections``."""
    if not enriched_sections:
        raise RuntimeError("Section Mapper produced no enriched_sections — nothing to generate")

    effective_special_instructions = _build_source_guidance(special_instructions, source_file_specs)

    rule_pack = resolve_content_rule_pack_from_shared_state(
        {"course_difficulty": course_difficulty},
        purpose="write",
        difficulty_override=course_difficulty,
    )
    if not rule_pack:
        raise RuntimeError(f"Could not resolve rule pack for difficulty {course_difficulty!r}")

    total_subtopics = sum(len(lesson.get("subtopics", [])) for lesson in enriched_sections)
    logger.info("[A2] Course: %s", course_title)
    logger.info("[A2] Rule pack: %s %s", rule_pack["family"], rule_pack["version"])
    logger.info("[A2] Difficulty: %s", rule_pack.get("active_difficulty", course_difficulty))
    logger.info(
        "[A2] TO lessons: %s  |  subtopics to generate: %s",
        len(enriched_sections),
        total_subtopics,
    )
    logger.info("[A2] Learning objectives: %s", len(learning_objectives))

    if feedback:
        logger.info(
            "[A2] Generating content with prior S2 feedback applied (%s chars).",
            len(feedback),
        )
    else:
        logger.info("[A2] Generating content section-by-section...")

    generated_sections = generate_all_sections(
        kernel,
        enriched_sections=enriched_sections,
        docx_path=docx_path,
        rule_pack=rule_pack,
        feedback=feedback,
        source_chunks=None,
        audience=course_audience,
        special_instructions=effective_special_instructions,
        course_config=course_config,
    )

    total_generated_words = sum(s.get("word_count", 0) for s in generated_sections)
    successful = sum(1 for s in generated_sections if s.get("status") == "generated")
    failed = sum(1 for s in generated_sections if s.get("status") == "failed")
    skipped = sum(1 for s in generated_sections if s.get("status") == "skipped_thin")
    logger.info(
        "[A2] Generation complete: %s generated, %s skipped, %s failed",
        successful,
        skipped,
        failed,
    )
    logger.info("     Total words: %s", total_generated_words)

    course_conclusion = _build_course_conclusion(
        kernel,
        course_title,
        content_sample=content_sample,
        learning_objectives=learning_objectives,
        generated_sections=generated_sections,
    )

    logger.info("[A2] Done.")
    return _build_a2_output(
        run_id=run_id,
        course_title=course_title,
        generated_sections=generated_sections,
        course_description=course_description,
        course_conclusion=course_conclusion,
    )


def render_study_guide(
    a2_output: A2Output,
    learning_objectives: list[str],
    output_path: str,
) -> str:
    """Render a study-guide .docx from an ``A2Output``. Returns the final docx path."""
    sections = a2_output.sections
    if not sections:
        raise RuntimeError("Cannot render study guide: A2 produced no sections.")

    final_path = build_study_guide_docx(
        course_title=a2_output.course_title,
        course_description=a2_output.course_description,
        learning_objectives=learning_objectives,
        generated_sections=sections,
        output_path=output_path,
        conclusion_text=a2_output.course_conclusion or "",
        include_overview=bool((a2_output.course_description or "").strip()),
    )
    a2_output.study_guide_docx = str(final_path)
    return final_path


__all__ = ["generate_course_content", "render_study_guide"]
