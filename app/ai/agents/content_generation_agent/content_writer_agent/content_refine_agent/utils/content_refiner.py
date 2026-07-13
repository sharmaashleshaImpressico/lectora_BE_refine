"""Content refinement logic — pure, kernel-based; no ``shared_state.json``."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import json_repair
from semantic_kernel import Kernel

from app.kernel.chat import LLMConfig, chat as kernel_chat
from app.kernel.model_registry import get_deployment
from app.ai.agents.content_generation_agent.models import A2Output, A2Stats
from app.ai.rule_pack_config.prompt_bundle import bundle_rule_pack_for_prompt

from ..constants.prompts import REFINEMENT_SYSTEM_PROMPT, build_refinement_user_message

logger = logging.getLogger(__name__)

_SECTION_BODY_MAX_CHARS = 6000
_MAX_SECTIONS_PER_CALL = 12


def _strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text.rstrip())
    return text.strip()


def _get_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _count_words_in_section(section_data: dict) -> int:
    total = 0
    for para in section_data.get("body_paragraphs", []) or []:
        ptype = para.get("type", "")
        if ptype in ("text", "important_callout", "heading_3", "heading_4", "paragraph"):
            total += len(re.findall(r"\w+", str(para.get("content", ""))))
        elif ptype in ("bullet_list", "sub_bullet_list", "numbered_list"):
            for item in para.get("items", []) or []:
                total += len(re.findall(r"\w+", str(item)))
        elif ptype == "table":
            for hdr in para.get("headers") or []:
                total += len(re.findall(r"\w+", str(hdr)))
            for row in para.get("rows") or []:
                for cell in row or []:
                    total += len(re.findall(r"\w+", str(cell)))
    return total


def _trim_section_for_prompt(section: dict) -> dict:
    body = section.get("body_paragraphs") or []
    serialized = json.dumps(body, ensure_ascii=False)
    if len(serialized) <= _SECTION_BODY_MAX_CHARS:
        return {
            "heading": section.get("heading"),
            "section_id": section.get("section_id"),
            "outline_lesson": section.get("outline_lesson"),
            "body_paragraphs": body,
        }
    trimmed_body: list[dict] = []
    size = 0
    for block in body:
        block_json = json.dumps(block, ensure_ascii=False)
        if size + len(block_json) > _SECTION_BODY_MAX_CHARS:
            break
        trimmed_body.append(block)
        size += len(block_json)
    return {
        "heading": section.get("heading"),
        "section_id": section.get("section_id"),
        "outline_lesson": section.get("outline_lesson"),
        "body_paragraphs": trimmed_body,
    }


def _parse_refined_sections(raw: str) -> list[dict]:
    text = _strip_fences(raw)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = json_repair.loads(text)
        except Exception:
            return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        sections = parsed.get("sections")
        if isinstance(sections, list):
            return [item for item in sections if isinstance(item, dict)]
    return []


def _section_keys(section: dict) -> set[str]:
    keys: set[str] = set()
    heading = str(section.get("heading") or "").strip().lower()
    section_id = str(section.get("section_id") or "").strip().lower()
    if heading:
        keys.add(heading)
    if section_id:
        keys.add(section_id)
    return keys


def _merge_refined_sections(
    original_sections: list[dict],
    refined_sections: list[dict],
) -> list[dict]:
    refined_lookup: dict[str, dict] = {}
    for section in refined_sections:
        for key in _section_keys(section):
            refined_lookup[key] = section

    merged: list[dict] = []
    for original in original_sections:
        updated = dict(original)
        match = None
        for key in _section_keys(original):
            if key in refined_lookup:
                match = refined_lookup[key]
                break
        if match and match.get("body_paragraphs"):
            updated["body_paragraphs"] = match["body_paragraphs"]
            updated["word_count"] = _count_words_in_section(updated)
            updated["status"] = "generated"
        merged.append(updated)
    return merged


def _resolve_generation_context(context: dict[str, Any], rule_pack: dict) -> dict[str, Any]:
    return {
        "course_title": context.get("course_title"),
        "audience": context.get("course_audience"),
        "course_difficulty": context.get("course_difficulty"),
        "special_instructions": context.get("special_instructions"),
        "rule_pack_family": rule_pack.get("family"),
        "rule_pack_version": rule_pack.get("version"),
        "voice": (rule_pack.get("style_constraints") or {}).get("voice"),
    }


def _build_a2_output_from_sections(
    *,
    run_id: str,
    course_title: str,
    course_description: str,
    course_conclusion: str,
    sections: list[dict],
) -> A2Output:
    successful = sum(1 for s in sections if s.get("status") == "generated")
    failed = sum(1 for s in sections if s.get("status") == "failed")
    skipped = sum(1 for s in sections if s.get("status") == "skipped_thin")
    total_words = sum(int(s.get("word_count") or 0) for s in sections)
    return A2Output(
        status="complete" if failed == 0 else "partial",
        run_id=run_id,
        course_title=course_title or "Untitled Course",
        sections=sections,
        stats=A2Stats(
            generated=successful,
            skipped=skipped,
            failed=failed,
            total_words=total_words,
        ),
        course_description=course_description or "",
        course_conclusion=course_conclusion or "",
        study_guide_docx=None,
        generated_content_json=None,
        timestamp=datetime.now(timezone.utc),
    )


def refine_sections(
    kernel: Kernel,
    *,
    a2_output: A2Output,
    s2_report: Any,
    rule_pack: dict[str, Any],
    context: dict[str, Any],
    lesson_title: str | None = None,
) -> A2Output:
    """Refine existing A2 sections in place using S2 validation feedback."""
    sections: list[dict] = list(a2_output.sections or [])
    if not sections:
        raise RuntimeError("Cannot refine content: A2 produced no sections.")

    lesson_title = str(lesson_title or _get_value(s2_report, "lesson_title", "") or "").strip()
    target_sections = sections
    if lesson_title:
        target_sections = [
            section
            for section in sections
            if str(section.get("outline_lesson") or "").strip() == lesson_title
        ]
        if not target_sections:
            raise RuntimeError(
                f"Cannot refine content: no sections found for lesson {lesson_title!r}."
            )

    sections_payload = [_trim_section_for_prompt(section) for section in target_sections]
    if len(sections_payload) > _MAX_SECTIONS_PER_CALL:
        sections_payload = sections_payload[:_MAX_SECTIONS_PER_CALL]

    generation_context = _resolve_generation_context(context, rule_pack)
    generation_context["full_rule_pack"] = bundle_rule_pack_for_prompt(rule_pack)

    user_msg = build_refinement_user_message(
        report=s2_report,
        sections_payload=sections_payload,
        generation_context=generation_context,
    )
    config = LLMConfig(
        deployment=get_deployment("A2"),
        temperature=0.35,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )
    raw = kernel_chat(kernel, REFINEMENT_SYSTEM_PROMPT, user_msg, config, "CONTENT_REFINE")
    refined_sections = _parse_refined_sections(raw)
    if not refined_sections:
        raise RuntimeError("Content refinement LLM returned no usable section updates.")

    if lesson_title:
        updated_lessons = _merge_refined_sections(target_sections, refined_sections)
        updated_lookup: dict[str, dict] = {}
        for section in updated_lessons:
            for key in _section_keys(section):
                updated_lookup[key] = section
        merged_all = []
        for section in sections:
            replacement = None
            for key in _section_keys(section):
                if key in updated_lookup:
                    replacement = updated_lookup[key]
                    break
            merged_all.append(replacement if replacement is not None else section)
    else:
        merged_all = _merge_refined_sections(sections, refined_sections)

    result = _build_a2_output_from_sections(
        run_id=a2_output.run_id,
        course_title=a2_output.course_title,
        course_description=a2_output.course_description,
        course_conclusion=a2_output.course_conclusion,
        sections=merged_all,
    )

    logger.info("[CONTENT_REFINE] Updated %s section(s).", len(refined_sections))
    return result
