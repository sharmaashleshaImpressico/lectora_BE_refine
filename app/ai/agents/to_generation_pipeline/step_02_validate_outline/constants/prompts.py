"""LLM prompt strings and response schemas for S1 validation and refinement."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Semantic validator (SemanticValidator)
# ---------------------------------------------------------------------------

SEMANTIC_SYSTEM_PROMPT: str = (
    "You are S1 Validator for Topic Outline quality gates. "
    "Return ONLY valid JSON and follow the response schema exactly."
)

VALIDATION_RULES: list[str] = [
    "User requirement alignment",
    "Rule pack compliance",
    "Topic completeness",
    "Topic sequencing",
    "Duplicate detection",
    "Missing critical topics",
    "Dependency ordering",
    "Topic granularity",
    "Difficulty progression",
    "Industry best practices",
    "Hallucinated topics",
    "Source hint coverage",
    "Learning objective coverage",
    "Section balance",
    "Practical vs theoretical balance",
    "Naming consistency",
    "Course duration alignment",
]

SEVERITY_POLICY: str = (
    "Severity policy:\n"
    "- blocker: Use only for major structural, completeness, or compliance failures that make the outline unacceptable, "
    "such as missing required fields, missing learning-objective coverage, missing mandatory topics, material duplication/overlap, "
    "lost course intent, or invalid/incomplete content like truncated text.\n"
    "- warning: Use only for issues that must be fixed before the TO can pass. "
    "Because warnings trigger retry_required=true and status=FAIL, do not use warning for optional improvements, subjective preferences, "
    "minor wording concerns, or polish suggestions.\n"
    "- info: Use for minor observations that do not require another refinement cycle, such as acceptable but improvable wording, "
    "high-level preview of later topics, or small specificity/style improvements where required coverage is already clear.\n\n"
    "Warning discipline rule:\n"
    "Since any warning causes FAIL, classify an issue as warning only when it clearly affects required topic coverage, "
    "learning objective coverage, course intent, learner comprehension, or rule-pack compliance. "
    "When unsure between warning and info, choose info."
    "WARNING EVIDENCE RULE:\n"
    "Warn only when a required topic is missing or materially unclear across the full outline.\n"
    "Use info for wording, placement, standalone-treatment, or specificity improvements.\n"
    "Opening section sequencing rule:\n"
    "The opening section may briefly preview later course themes, regulatory areas, or compliance topics at a high level. "
    "Do not flag this as a warning unless the opening section teaches detailed advanced regulatory content before foundational concepts are introduced. "
    "A high-level preview of later topics should be classified as info or ignored."
    "Opening section sequencing rule:\n"
    "The opening section may briefly preview later course themes, regulatory areas, or compliance topics at a high level. "
    "Do not flag this as a warning unless the opening section teaches detailed advanced regulatory content before foundational concepts are introduced. "
    "A high-level preview of later topics should be classified as info or ignored."
    "GLOBAL COVERAGE RULE:\n"
    "Check required-topic coverage across the full outline.\n"
    "If a topic is clear in any title, content, or subtopic, treat it as covered.\n"
    "When precheck shows no missing/partial topics, warn only if a topic is absent from the full outline.\n"

)

RESPONSE_SCHEMA: str = """
{
  "summary": "short sentence",
  "coverage_score": 0,
  "sequence_score": 0,
  "relevance_score": 0,
  "completeness_score": 0,
  "confidence": 0,
  "status": "PASS|FAIL",
  "blockers": 0,
  "issues": [
    {
      "field": "path",
      "severity": "blocker|warning|info",
      "message": "issue",
      "expected": "expected condition",
      "found": "actual finding",
      "rule_source": "user_requirements|rule_pack|sequence|coverage|relevance|clarity",
      "failure_reason": "why it matters",
      "remediation": "what to change"
    }
  ],
  "recommendations": [
    {"title": "what to improve", "detail": "how to improve", "priority": "high|medium|low"}
  ],
  "missing_topics": [
    {"topic": "topic", "reason": "why missing", "severity": "high|medium|low"}
  ],
  "duplicates": ["topic A", "topic B"],
  "dependency_issues": [
    {"topic": "dependent topic", "missing_prerequisite": "prerequisite", "reason": "why order is wrong"}
  ],
  "learning_objective_mapping": [
    {"objective": "objective text", "status": "covered|partial|missing", "evidence": "short proof"}
  ],
  "retry_required": false,
  "retry_prompt": ""
}
""".strip()

# ---------------------------------------------------------------------------
# S1 refinement agent (S1ValidatorRefineAgent) — canonical prompt lives in step_03
# ---------------------------------------------------------------------------

from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.prompts import (
    REPAIR_SYSTEM_PROMPT as REFINE_SYSTEM_PROMPT,
)
