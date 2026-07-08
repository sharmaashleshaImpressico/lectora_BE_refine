"""Health-check route."""

from __future__ import annotations

from fastapi import APIRouter

from app.db.session import azure_db_client

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok", "db_connected": azure_db_client.check_connection()}
