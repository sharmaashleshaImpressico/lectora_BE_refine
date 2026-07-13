"""Backward-compatibility shim for InconsistencyDetector."""

from ..inconsistency_detector import InconsistencyDetector, detect_inconsistencies

__all__ = ["InconsistencyDetector", "detect_inconsistencies"]
