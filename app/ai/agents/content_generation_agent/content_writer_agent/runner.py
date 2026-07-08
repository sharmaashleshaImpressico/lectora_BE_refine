"""Runner shim for the canonical `content_writer_agent` path."""

from .orchestrator.generator import generate_course_content, render_study_guide

__all__ = ["generate_course_content", "render_study_guide"]
