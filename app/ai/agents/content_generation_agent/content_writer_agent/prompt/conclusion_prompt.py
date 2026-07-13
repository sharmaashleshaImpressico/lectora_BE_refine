"""Backward-compatibility re-export shim."""

from ..step_03_conclusion.constants import prompts as _impl

__all__ = [name for name in dir(_impl) if not name.startswith("__")]
globals().update({name: getattr(_impl, name) for name in __all__})
