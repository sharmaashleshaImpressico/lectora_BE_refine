"""Aggregates every v1 endpoint router into one `APIRouter`.

No prefix is applied here so existing route paths (`/course-basic`,
`/health`) are unchanged — this only groups the routers for `app.main`.
Onboarding generation routes (e.g. `/generate-learning-objectives`) live
alongside other feature routers at the root path level.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import dashboard, health, storage
from app.api.v1.endpoints.onboarding import (
    course_basic,
    course_run,
    learning_objective,
    required_topic,
    timed_outline,
    documents,
)

api_router = APIRouter()
api_router.include_router(course_basic.router)
api_router.include_router(course_run.router)
api_router.include_router(dashboard.router)
api_router.include_router(health.router)
api_router.include_router(learning_objective.router)
api_router.include_router(required_topic.router)
api_router.include_router(documents.router)
api_router.include_router(storage.router)
api_router.include_router(timed_outline.router)
