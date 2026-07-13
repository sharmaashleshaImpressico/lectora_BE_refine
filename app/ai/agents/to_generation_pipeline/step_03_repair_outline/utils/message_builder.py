"""Build the LLM user message for S1 TO refinement."""

from __future__ import annotations

import json
from typing import Any

from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.config import (
    COURSE_CONFIG_KEYS,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.models import (
    S1RefinementInput,
    S1RefinementIssue,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.issues import (
    RefinementIssueGrouper,
)
from app.ai.agents.to_generation_pipeline.step_02_validate_outline.constants.validation import (
    section_index_from_field,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.section1 import (
    Section1IssueDetector,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.utils.topic_keys import (
    extract_required_topic_label,
    topic_keywords,
)


class RefinementMessageBuilder:
    """Formats the current outline and S1 feedback for the refine LLM."""

    def build(self, input_data: S1RefinementInput) -> str:
        blockers, warnings = RefinementIssueGrouper.partition_by_severity(input_data.issues)
        parts = [
            "CURRENT TIMED OUTLINE (llm_to_outline JSON):",
            json.dumps(input_data.current_outline, indent=2),
            "",
            (
                "S1 VALIDATION FEEDBACK — fix ONLY the BLOCKER and WARNING items listed "
                f"below (blockers={len(blockers)}, warnings={len(warnings)}). "
                "Do NOT change any section, field, or metric that is not directly "
                "related to one of these issues."
            ),
            (
                "S1 field paths use 1-based section numbers: course_outline.sections[1] "
                "is the FIRST section (JSON sections[0]); sections[2] → JSON sections[1]."
            ),
        ]

        section1_block = self._format_section1_lo_directive(input_data)
        if section1_block:
            parts.append(section1_block)

        if blockers:
            parts.extend(["", "BLOCKERS (must fix):"])
            parts.extend(self._format_issue_block(issue) for issue in blockers)

        if warnings:
            parts.extend(["", "WARNINGS (must also fix):"])
            parts.extend(self._format_issue_block(issue) for issue in warnings)

        locked_sections = self._format_locked_sections(input_data)
        if locked_sections:
            parts.append(locked_sections)

        config_section = self._format_course_config(input_data.course_config)
        if config_section:
            parts.append(config_section)

        return "\n".join(parts)

    @classmethod
    def _format_locked_sections(cls, input_data: S1RefinementInput) -> str:
        """List sections that must be copied verbatim (not named in any issue)."""
        targeted_indices = {
            index
            for issue in input_data.issues
            for index in [section_index_from_field(issue.field)]
            if index is not None
        }
        sections = input_data.current_outline.get("sections") or []
        if not sections:
            return ""

        locked_lines = ["", "LOCKED SECTIONS (copy EXACTLY — no edits unless listed above):"]
        for idx, section in enumerate(sections, start=1):
            if idx in targeted_indices:
                continue
            title = str(section.get("title") or section.get("heading") or f"Section {idx}")
            locked_lines.append(f"  - sections[{idx}] / JSON index {idx - 1}: {title}")
        return "\n".join(locked_lines) if len(locked_lines) > 2 else ""

    @staticmethod
    def _format_issue_block(issue: S1RefinementIssue) -> str:
        block = f"  • [{issue.severity.upper()}] [{issue.field}] {issue.message}"
        if issue.expected:
            block += f"\n    Expected: {issue.expected}"
        if issue.found:
            block += f"\n    Found: {issue.found}"
        if issue.rule_source:
            block += f"\n    Rule: {issue.rule_source}"
        if issue.remediation:
            block += f"\n    Remediation: {issue.remediation}"
        keyword_hint = RefinementMessageBuilder._format_coverage_keyword_hint(issue)
        if keyword_hint:
            block += f"\n    {keyword_hint}"
        return block

    @classmethod
    def _format_coverage_keyword_hint(cls, issue: S1RefinementIssue) -> str:
        if not issue.field.startswith("required_topics.coverage."):
            return ""
        topic = extract_required_topic_label(issue.field, issue.message)
        keywords = topic_keywords(topic)
        if not keywords:
            return ""
        return (
            "Keyword hint: include these terms verbatim in a subtopic title "
            f"or section content: {', '.join(keywords)}."
        )

    @classmethod
    def _format_section1_lo_directive(cls, input_data: S1RefinementInput) -> str:
        if not Section1IssueDetector.needs_lo_repair_directive(input_data.issues):
            return ""

        outline_los = cls._extract_non_empty_strings(
            input_data.current_outline.get("learning_objectives")
        )
        config_los = cls._extract_non_empty_strings(
            input_data.course_config.get("learning_objectives")
        )
        objectives = outline_los or config_los
        if not objectives:
            return ""

        lines = [
            "",
            "SECTION 1 LEARNING OBJECTIVE REPAIR (mandatory):",
            "Replace any compressed objective line in the first section with these "
            "topic-only subtopics (one per line, verbatim):",
        ]
        lines.extend(f"  - {objective}" for objective in objectives)
        lines.append(
            "Remove subtopics like \"Course purpose and learning objectives: ...\" "
            "that comma-separate multiple objectives in one string."
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_non_empty_strings(values: Any) -> list[str]:
        return [str(item).strip() for item in (values or []) if str(item).strip()]

    @classmethod
    def _format_course_config(cls, course_config: dict[str, Any]) -> str:
        if not course_config:
            return ""

        lines = [
            "\nAUTHOR COURSE CONFIG (preserve unless a blocker or warning requires change):"
        ]
        for key in COURSE_CONFIG_KEYS:
            value = course_config.get(key)
            if value not in (None, "", [], {}):
                lines.append(f"  {key}: {value}")

        return "\n".join(lines) if len(lines) > 1 else ""
