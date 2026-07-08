"""LangGraph StateGraph assembly for the A1 enrichment pipeline."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from ..phases.phase_01_load_state.shared_state_loader import SharedStateLoader
from ..phases.phase_02_parse_document.document_parser import DocumentParserNode
from ..phases.phase_03_validate_objectives.learning_objective_validator import (
    LearningObjectiveValidator,
)
# Image mapper disabled — skip mapping source images to sections.
# from ..phases.phase_04_map_images.image_mapper import SectionImageMapper
from ..phases.phase_05_enrich_sections.section_enricher import SectionEnricher
from ..phases.phase_06_build_course_spec.course_spec_builder import CourseSpecBuilder
from ..phases.phase_07_detect_issues.inconsistency_detector import InconsistencyDetector
from ..phases.phase_08_save_outputs.output_writer import OutputWriter
from semantic_kernel import Kernel

from ..shared.models.state import A1State
from .graph_router import A1GraphRouter


class A1GraphBuilder:
    """Wires A1 node handlers into a compiled LangGraph application."""

    def __init__(self, kernel: Kernel | None = None) -> None:
        self._router = A1GraphRouter()
        self._loader = SharedStateLoader()
        self._document_parser = DocumentParserNode()
        self._lo_validator = LearningObjectiveValidator()
        # self._image_mapper = SectionImageMapper()
        self._section_enricher = SectionEnricher(kernel=kernel)
        self._spec_builder = CourseSpecBuilder()
        self._issue_detector = InconsistencyDetector()
        self._output_writer = OutputWriter()

    def build(self):
        graph = StateGraph(A1State)

        for name, handler in [
            ("load_shared_state", self._loader),
            ("parse_document", self._document_parser),
            ("validate_los", self._lo_validator),
            # ("map_images", self._image_mapper),
            ("enrich_with_llm", self._section_enricher),
            ("build_course_spec", self._spec_builder),
            ("detect_inconsistencies", self._issue_detector),
            ("persist_output", self._output_writer.persist_output),
            ("failed_end", self._output_writer.failed_end),
            ("stopped_end", self._output_writer.stopped_end),
        ]:
            graph.add_node(name, handler)

        graph.set_entry_point("load_shared_state")

        graph.add_conditional_edges(
            "load_shared_state",
            self._router.after_load,
            {"parse_document": "parse_document", "failed_end": "failed_end"},
        )
        graph.add_conditional_edges(
            "parse_document",
            self._router.after_parse,
            {
                "parse_document": "parse_document",
                "validate_los": "validate_los",
                "failed_end": "failed_end",
            },
        )
        graph.add_conditional_edges(
            "validate_los",
            self._router.after_validate,
            {"enrich_with_llm": "enrich_with_llm", "stopped_end": "stopped_end"},
        )
        # graph.add_edge("map_images", "enrich_with_llm")
        graph.add_edge("enrich_with_llm", "build_course_spec")
        graph.add_conditional_edges(
            "build_course_spec",
            self._router.after_build,
            {"detect_inconsistencies": "detect_inconsistencies", "failed_end": "failed_end"},
        )
        graph.add_edge("detect_inconsistencies", "persist_output")
        graph.add_edge("persist_output", END)
        graph.add_edge("failed_end", END)
        graph.add_edge("stopped_end", END)

        return graph.compile()


def build_graph(kernel: Kernel | None = None):
    """Build and return the compiled A1 LangGraph application."""
    return A1GraphBuilder(kernel=kernel).build()
