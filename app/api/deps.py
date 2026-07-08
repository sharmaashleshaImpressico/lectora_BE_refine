"""Shared FastAPI dependencies for the API layer."""

from __future__ import annotations

from semantic_kernel import Kernel

from app.db.session import get_db
from app.kernel.factory import create_kernel

__all__ = ["get_db", "get_kernel"]


def get_kernel() -> Kernel:
    """FastAPI dependency that returns a configured Semantic Kernel instance."""
    return create_kernel()
