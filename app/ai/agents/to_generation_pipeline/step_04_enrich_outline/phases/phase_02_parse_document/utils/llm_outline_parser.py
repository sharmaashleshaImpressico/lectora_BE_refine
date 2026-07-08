"""Backward-compatibility shim for LlmOutlineSectionParser."""

from ..llm_outline_parser import (
    LlmOutlineSectionParser,
    parse_sections_from_llm_outline,
    sync_extracted_inputs_from_llm_outline,
)

__all__ = [
    "LlmOutlineSectionParser",
    "parse_sections_from_llm_outline",
    "sync_extracted_inputs_from_llm_outline",
]
