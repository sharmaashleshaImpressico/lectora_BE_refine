"""Detect structural inconsistencies in the assembled course_spec."""

from .inconsistency_detector import InconsistencyDetector, detect_inconsistencies

__all__ = ["InconsistencyDetector", "detect_inconsistencies"]
