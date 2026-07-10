"""Consumes course-generation job messages from the Service Bus queue.

Uses peek-lock semantics: a message is only removed from the queue once the
handler returns successfully (`complete_message`). If the handler raises, the
message is abandoned so it becomes visible again and can be retried by this
or another worker instance — the job row in the DB (looked up by `job_id`)
is what makes that retry resumable rather than a duplicate side effect.
After too many delivery attempts Service Bus dead-letters the message
automatically (`max_delivery_count` on the queue).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from azure.servicebus import ServiceBusReceiver
from azure.servicebus.exceptions import ServiceBusError

from app.core.service_bus.client import get_service_bus_client
from app.core.service_bus.config import ServiceBusSettings, service_bus_settings
from app.core.service_bus.message_models import CourseGenerationJobMessage

logger = logging.getLogger(__name__)

JobHandler = Callable[[CourseGenerationJobMessage], None]


class CourseGenerationJobConsumer:
    """Receives and dispatches queued course-generation job messages."""

    def __init__(self, settings: ServiceBusSettings | None = None) -> None:
        self.settings = settings or service_bus_settings

    def run_forever(self, handler: JobHandler, stop_event: threading.Event) -> None:
        """Block, processing messages one at a time, until `stop_event` is set."""
        while not stop_event.is_set():
            try:
                with get_service_bus_client(self.settings) as client:
                    with client.get_queue_receiver(self.settings.queue_name) as receiver:
                        self._drain_until_stopped(receiver, handler, stop_event)
            except ServiceBusError:
                logger.exception("[service_bus] Connection error — retrying shortly")
                stop_event.wait(timeout=5)
            except Exception:
                logger.exception("[service_bus] Unexpected consumer error — retrying shortly")
                stop_event.wait(timeout=5)

    def _drain_until_stopped(
        self,
        receiver: ServiceBusReceiver,
        handler: JobHandler,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.is_set():
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
            for raw_message in messages:
                self._process_one(receiver, raw_message, handler)

    def _process_one(self, receiver: ServiceBusReceiver, raw_message, handler: JobHandler) -> None:
        try:
            message = CourseGenerationJobMessage.from_body(b"".join(raw_message.body))
        except Exception:
            logger.exception("[service_bus] Malformed message — dead-lettering")
            receiver.dead_letter_message(raw_message, reason="malformed_body")
            return

        try:
            handler(message)
        except Exception:
            logger.exception(
                "[service_bus] Handler failed | job_id=%s | course_run_id=%s — abandoning for retry",
                message.job_id,
                message.course_run_id,
            )
            receiver.abandon_message(raw_message)
            return

        receiver.complete_message(raw_message)
