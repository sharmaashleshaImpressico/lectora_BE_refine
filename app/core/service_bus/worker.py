"""Background worker: bridges Service Bus messages to the generation pipeline.

Kept inside `core/service_bus/` because it is Service-Bus-specific glue (owns
the receive loop and its background thread). The actual business logic it
calls into — loading data, running the orchestrator, persisting results —
lives in `app.services.onboarding.course_generation` and has no Service Bus
dependency, so it stays testable and reusable outside of a queue trigger.
"""

from __future__ import annotations

import logging
import threading

from app.core.service_bus.config import ServiceBusSettings, service_bus_settings
from app.core.service_bus.consumer import CourseGenerationJobConsumer
from app.core.service_bus.message_models import CourseGenerationJobMessage
from app.db.session import azure_db_client

logger = logging.getLogger(__name__)


class CourseGenerationWorker:
    """Runs the Service Bus consumer loop on a background thread."""

    def __init__(self, settings: ServiceBusSettings | None = None) -> None:
        self.settings = settings or service_bus_settings
        self._consumer = CourseGenerationJobConsumer(self.settings)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.settings.is_configured:
            logger.warning(
                "[service_bus] SERVICE_BUS_CONNECTION_STRING not set — worker not started."
            )
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._consumer.run_forever,
            args=(self._handle_message, self._stop_event),
            name="course-generation-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("[service_bus] Worker started | queue=%s", self.settings.queue_name)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("[service_bus] Worker stopped")

    def _handle_message(self, message: CourseGenerationJobMessage) -> None:
        # Import here to avoid a service_bus -> services -> service_bus cycle at module load.
        from app.services.onboarding.course_generation.pipeline_runner import (
            CourseGenerationPipelineRunner,
        )

        with azure_db_client.session_scope() as db:
            CourseGenerationPipelineRunner(db).run(
                job_id=message.job_id, course_run_id=message.course_run_id
            )
