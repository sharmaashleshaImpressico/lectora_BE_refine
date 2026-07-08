"""Backward-compatibility shim for SharedStateLoader."""

from ..shared_state_loader import SharedStateLoader, load_shared_state

__all__ = ["SharedStateLoader", "load_shared_state"]
