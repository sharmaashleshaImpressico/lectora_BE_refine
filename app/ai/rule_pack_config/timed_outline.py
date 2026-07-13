"""Canonical Timed Outline (TO) JSON schema shared by prompts and normalizers.

Native replacement for ``lectora_backend.pipeline.rule_pack_config.timed_outline``.
``TO_outline_format`` is a plain dict used two ways by the TO generation
pipeline:

- dumped via ``json.dumps(TO_outline_format, indent=2)`` into the LLM prompt
  that extracts a Timed Outline document into structured JSON (see
  ``step_01_parse_and_generate_outline/generate_outline/constants/prompts.py``
  -- ``CLASSIFICATIONTO_OUTLINE_PROMPT``), and
- used as a defaults source (``TO_outline_format["totals"]``) when normalizing
  heterogeneous LLM outline JSON back into this canonical shape (see
  ``finalize_output/utils/normalize_llm_outline_schema.py``).
"""

from __future__ import annotations

from typing import Any

_TO_SECTION_FORMAT: dict[str, Any] = {
    "title": "",
    "content": "",
    "subtopics": [],
    "word_count": "",
    "minutes": "",
    "credit_hour": "",
    "interactive_elements": [],
}

TO_outline_format: dict[str, Any] = {
    "course_title": "",
    "course_id": "",
    "description": "",
    "learning_objectives": [],
    "sections": [_TO_SECTION_FORMAT],
    "totals": {"word_count": "", "minutes": "", "credit_hours": ""},
}

__all__ = ["TO_outline_format"]
