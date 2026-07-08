"""Assemble course_spec from parsed and enriched sections."""

from .course_spec_builder import CourseSpecBuilder, build_course_spec

__all__ = ["CourseSpecBuilder", "build_course_spec"]
