"""Aggregates every v1 endpoint router into one `APIRouter`.

No prefix is applied here so existing route paths (`/course-basic`,
`/health`) are unchanged — this only groups the routers for `app.main`.
Onboarding document routes (e.g. `/documents/generate-learning-objectives`) carry
their own prefix on the feature router. The frontend calls `/api/documents/...`
via Vite, which proxies to these backend paths.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health
from app.api.v1.endpoints.onboarding import course_basic, course_run, learning_objective

api_router = APIRouter()
api_router.include_router(course_basic.router)
api_router.include_router(course_run.router)
api_router.include_router(health.router)
api_router.include_router(learning_objective.router)
