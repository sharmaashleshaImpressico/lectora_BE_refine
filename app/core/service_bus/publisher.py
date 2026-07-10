"""Publishes course-generation job messages to the Service Bus queue."""

from __future__ import annotations

import logging

from azure.servicebus import ServiceBusMessage

from app.core.service_bus.client import get_service_bus_client
from app.core.service_bus.config import ServiceBusSettings, service_bus_settings
from app.core.service_bus.message_models import CourseGenerationJobMessage

logger = logging.getLogger(__name__)


class CourseGenerationJobPublisher:
    """Publishes the minimal `{job_id, course_run_id}` message that kicks off a worker run."""

    def __init__(self, settings: ServiceBusSettings | None = None) -> None:
        self.settings = settings or service_bus_settings

    def publish(self, job_id: str, course_run_id: str) -> None:
        message = CourseGenerationJobMessage(job_id=job_id, course_run_id=course_run_id)
        with get_service_bus_client(self.settings) as client:
            with client.get_queue_sender(self.settings.queue_name) as sender:
                sender.send_messages(ServiceBusMessage(message.to_body()))
        logger.info(
            "[service_bus] Published job message | job_id=%s | course_run_id=%s | queue=%s",
            job_id,
            course_run_id,
            self.settings.queue_name,
        )
