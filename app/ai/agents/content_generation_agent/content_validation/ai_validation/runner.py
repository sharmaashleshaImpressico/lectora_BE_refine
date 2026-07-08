"""AI-based content validation using LLM semantic review."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from semantic_kernel import Kernel

from app.kernel.chat import LLMConfig, chat as kernel_chat
from app.kernel.model_registry import get_deployment
from app.ai.rule_pack_config.prompt_bundle import (
    bundle_rule_pack_for_validation_prompt,
)
from app.ai.shared_llm_config.tracer import set_langfuse_step_label

from .prompts import (
    AI_RESPONSE_SCHEMA,
    AI_SEVERITY_POLICY,
    AI_VALIDATION_RULES,
    AI_VALIDATION_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

_MAX_LLM_RETRIES = 2

try:
    import json_repair  # type: ignore
except Exception:  # pragma: no cover
    json_repair = None


def _build_section_payload(sections: list[dict]) -> list[dict[str, Any]]:
    """Return complete generated sections for LLM review — no previews or caps."""
    payload: list[dict[str, Any]] = []
    for sec in sections:
        if sec.get("status") in ("skipped", "skipped_thin"):
            continue
        payload.append(
            {
                "section_id": sec.get("section_id") or sec.get("heading"),
                "heading": sec.get("heading"),
                "outline_lesson": sec.get("outline_lesson"),
                "level": sec.get("level"),
                "status": sec.get("status"),
                "word_count": sec.get("word_count"),
                "body_paragraphs": sec.get("body_paragraphs") or [],
            }
        )
    return payload


def _build_system_prompt() -> str:
    rules = "\n".join(f"- {rule}" for rule in AI_VALIDATION_RULES)
    return (
        f"{AI_VALIDATION_SYSTEM_PROMPT}\n\n"
        f"Validation focus areas:\n{rules}\n\n"
        f"{AI_SEVERITY_POLICY}\n\n"
        f"Response schema:\n{AI_RESPONSE_SCHEMA.strip()}"
    )


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    if json_repair is not None:
        try:
            repaired = json_repair.loads(text)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _normalize_ai_issues(raw_issues: list[Any]) -> list[dict]:
    normalized: list[dict] = []
    allowed = {"blocker", "critical", "warning", "info"}
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "warning").strip().lower()
        if severity not in allowed:
            severity = "warning"
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        normalized.append(
            {
                "field": str(item.get("field") or "ai_validation.summary"),
                "expected": item.get("expected"),
                "found": item.get("found"),
                "severity": severity,
                "message": message,
                "rule_source": str(item.get("rule_source") or "ai_validation.semantic"),
            }
        )
    return normalized


def run_ai_validation(
    kernel: Kernel,
    *,
    sections: list[dict],
    rule_pack: dict[str, Any],
    context: dict[str, Any],
    phase: str,
    lesson_title: str | None,
) -> list[dict]:
    """Run LLM-backed subjective content quality validation."""
    section_payload = _build_section_payload(sections)
    if not section_payload:
        logger.info("[S2][ai] Skipping AI validation — no section content to review.")
        return []

    payload = {
        "phase": phase,
        "lesson_title": lesson_title,
        "course_title": context.get("course_title"),
        "audience": context.get("course_audience"),
        "course_difficulty": context.get("course_difficulty"),
        "special_instructions": context.get("special_instructions"),
        "full_rule_pack": bundle_rule_pack_for_validation_prompt(rule_pack),
        "sections": section_payload,
    }

    system_prompt = _build_system_prompt()
    user_msg = json.dumps(payload, ensure_ascii=False)
    config = LLMConfig(
        deployment=get_deployment("A2"),
        temperature=0,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    if phase == "lesson" and lesson_title:
        set_langfuse_step_label(f"content validate · {lesson_title}")
    elif phase == "lesson":
        set_langfuse_step_label("content validate · lesson")
    else:
        set_langfuse_step_label("content validate · full")

    issues: list[dict] = []
    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            raw_response = kernel_chat(kernel, system_prompt, user_msg, config, "S2")
            parsed = _parse_llm_json(raw_response)
            issues = _normalize_ai_issues(parsed.get("issues") or [])
            logger.info(
                "[S2][ai] Validation complete (attempt=%s) — %s issue(s), status=%s",
                attempt,
                len(issues),
                parsed.get("status"),
            )
            break
        except Exception as exc:
            logger.warning("[S2][ai] LLM validation failed (attempt=%s): %s", attempt, exc)
            if attempt >= _MAX_LLM_RETRIES:
                issues = [
                    {
                        "field": "ai_validation.llm",
                        "expected": "AI validation response",
                        "found": "error",
                        "severity": "info",
                        "message": (
                            "AI content validation could not complete. "
                            "Deterministic validation results still apply."
                        ),
                        "rule_source": "ai_validation.pipeline",
                    }
                ]

    return issues
