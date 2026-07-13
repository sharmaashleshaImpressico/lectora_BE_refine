"""A1 pipeline phases — executed in numbered order by the LangGraph orchestrator.

1. phase_01_load_state          — read A0's in-memory shared state and prepare A1State
2. phase_02_parse_document      — parse source DOCX/PDF into section structure
3. phase_03_validate_objectives — validate learning-objective coverage
4. phase_04_map_images          — attach source images to sections
5. phase_05_enrich_sections     — LLM enrichment of subtopics and LO mappings
6. phase_06_build_course_spec   — assemble the final course_spec payload
7. phase_07_detect_issues       — flag structural inconsistencies
8. phase_08_save_outputs        — fold course_spec back into the in-memory shared state (no disk I/O)
"""

from .phase_01_load_state.shared_state_loader import SharedStateLoader
from .phase_02_parse_document.document_parser import DocumentParserNode
from .phase_03_validate_objectives.learning_objective_validator import LearningObjectiveValidator
from .phase_04_map_images.image_mapper import SectionImageMapper
from .phase_05_enrich_sections.section_enricher import SectionEnricher
from .phase_06_build_course_spec.course_spec_builder import CourseSpecBuilder
from .phase_07_detect_issues.inconsistency_detector import InconsistencyDetector
from .phase_08_save_outputs.output_writer import OutputWriter

__all__ = [
    "SharedStateLoader",
    "DocumentParserNode",
    "LearningObjectiveValidator",
    "SectionImageMapper",
    "SectionEnricher",
    "CourseSpecBuilder",
    "InconsistencyDetector",
    "OutputWriter",
]
