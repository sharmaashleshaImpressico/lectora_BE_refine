"""Canonical content-writer agent surface — pure, kernel-based (no shared_state.json)."""

from __future__ import annotations

from .runner import generate_course_content, render_study_guide

__all__ = ["generate_course_content", "render_study_guide"]
