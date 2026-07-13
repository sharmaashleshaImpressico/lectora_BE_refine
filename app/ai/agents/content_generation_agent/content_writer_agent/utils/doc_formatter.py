"""Backward-compatibility re-export shim."""

from ..step_04_render_docx.utils import doc_formatter as _impl

__all__ = [name for name in dir(_impl) if not name.startswith("__")]
globals().update({name: getattr(_impl, name) for name in __all__})
