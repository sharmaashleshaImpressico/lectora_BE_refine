"""
Section Mapper — maps Timed Outline sections to enriched course_spec groupings.
Backward-compatibility shim. Implementation lives in step_01_map_sections/.
"""

from .step_01_map_sections.utils.mapper import map_sections  # noqa: F401

__all__ = ["map_sections"]
