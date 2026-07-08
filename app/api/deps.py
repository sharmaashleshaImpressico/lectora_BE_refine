"""Shared FastAPI dependencies for the API layer."""

from __future__ import annotations

from app.db.session import get_db

__all__ = ["get_db"]
