"""
A1 — Timed Outline Interpreter

Backward-compatibility shim. Implementation lives in orchestrator/
and the numbered phases/ subdirectories (phase_01 … phase_08).
"""
from .orchestrator import A1GraphBuilder, A1PipelineRunner, build_graph, run
from .phases.phase_02_parse_document.utils.pdf_parser import (
    _parse_pdf_sections_from_shared_state,
)
from .shared.helpers.section_helpers import _normalize_section_level

__all__ = [
    "A1GraphBuilder",
    "A1PipelineRunner",
    "run",
    "build_graph",
    "_normalize_section_level",
    "_parse_pdf_sections_from_shared_state",
]
