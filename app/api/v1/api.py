"""Aggregates every v1 endpoint router into one `APIRouter`.

No prefix is applied here so existing route paths (`/course-basic`,
`/health`) are unchanged — this only groups the routers for `app.main`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health
from app.api.v1.endpoints.onboarding import course_basic

api_router = APIRouter()
api_router.include_router(course_basic.router)
api_router.include_router(health.router)
