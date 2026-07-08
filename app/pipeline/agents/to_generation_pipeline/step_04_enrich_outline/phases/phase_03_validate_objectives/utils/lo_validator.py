"""Backward-compatibility shim for LearningObjectiveValidator."""

from ..learning_objective_validator import LearningObjectiveValidator, validate_los

__all__ = ["LearningObjectiveValidator", "validate_los"]
