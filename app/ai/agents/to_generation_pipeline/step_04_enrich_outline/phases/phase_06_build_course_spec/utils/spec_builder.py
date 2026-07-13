"""Backward-compatibility shim for CourseSpecBuilder."""

from ..course_spec_builder import CourseSpecBuilder, build_course_spec

__all__ = ["CourseSpecBuilder", "build_course_spec"]
