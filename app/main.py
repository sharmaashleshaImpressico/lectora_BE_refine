"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.logging import configure_logging
from app.core.service_bus.worker import CourseGenerationWorker
from app.db.seed_lookups import seed_lookup_tables
from app.db.session import azure_db_client

configure_logging()
logger = logging.getLogger(__name__)

course_generation_worker = CourseGenerationWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is owned by Alembic (`alembic upgrade head`); do not create_all here.
    logger.info("Starting up: seeding lookup tables")
    with azure_db_client.session_scope() as db:
        seed_lookup_tables(db)
    course_generation_worker.start()
    yield
    course_generation_worker.stop()
    try:
        from app.tracing import shutdown_tracing

        shutdown_tracing()
    except Exception:
        logger.warning("Tracing shutdown failed", exc_info=True)
    logger.info("Shutting down")


app = FastAPI(title="Lectora Backend API", lifespan=lifespan)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
