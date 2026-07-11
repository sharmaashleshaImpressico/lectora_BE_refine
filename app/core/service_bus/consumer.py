"""Consumes course-generation job messages from the Service Bus queue.

Uses peek-lock semantics: a message is only removed from the queue once the
handler returns successfully (`complete_message`). If the handler raises, the
message is abandoned so it becomes visible again and can be retried by this
or another worker instance — the job row in the DB (looked up by `job_id`)
is what makes that retry resumable rather than a duplicate side effect.
After too many delivery attempts Service Bus dead-letters the message
automatically (`max_delivery_count` on the queue).

Peek-lock renewal: content generation runs for minutes (per-lesson LLM calls),
which far exceeds a queue's peek-lock duration (Azure default 60 s, max 5 min).
Without renewal the lock expires mid-run, Service Bus redelivers the message,
and a second worker starts the *entire* pipeline again — Section Mapper, content
generation and all — for the same job_id while the first run is still going.
An `AutoLockRenewer` keeps the lock held for the lifetime of the handler (capped
at `_MAX_LOCK_RENEWAL_SECONDS`) so a job is processed exactly once.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from azure.servicebus import AutoLockRenewer, ServiceBusReceiver
from azure.servicebus.exceptions import ServiceBusError

from app.core.service_bus.client import get_service_bus_client
from app.core.service_bus.config import ServiceBusSettings, service_bus_settings
from app.core.service_bus.message_models import CourseGenerationJobMessage

logger = logging.getLogger(__name__)

JobHandler = Callable[[CourseGenerationJobMessage], None]

# Upper bound on how long a single message's lock is auto-renewed. Matches the
# SSE stream's 30-minute ceiling — the longest a job is expected to run.
_MAX_LOCK_RENEWAL_SECONDS = 30 * 60


class CourseGenerationJobConsumer:
    """Receives and dispatches queued course-generation job messages."""

    def __init__(self, settings: ServiceBusSettings | None = None) -> None:
        self.settings = settings or service_bus_settings

    def run_forever(self, handler: JobHandler, stop_event: threading.Event) -> None:
        """Block, processing messages one at a time, until `stop_event` is set."""
        while not stop_event.is_set():
            try:
                with get_service_bus_client(self.settings) as client:
                    renewer = AutoLockRenewer(max_lock_renewal_duration=_MAX_LOCK_RENEWAL_SECONDS)
                    try:
                        with client.get_queue_receiver(self.settings.queue_name) as receiver:
                            self._drain_until_stopped(receiver, renewer, handler, stop_event)
                    finally:
                        renewer.close()
            except ServiceBusError:
                logger.exception("[service_bus] Connection error — retrying shortly")
                stop_event.wait(timeout=5)
            except Exception:
                logger.exception("[service_bus] Unexpected consumer error — retrying shortly")
                stop_event.wait(timeout=5)

    def _drain_until_stopped(
        self,
        receiver: ServiceBusReceiver,
        renewer: AutoLockRenewer,
        handler: JobHandler,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.is_set():
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
            for raw_message in messages:
                self._process_one(receiver, renewer, raw_message, handler)

    def _process_one(
        self,
        receiver: ServiceBusReceiver,
        renewer: AutoLockRenewer,
        raw_message,
        handler: JobHandler,
    ) -> None:
        try:
            message = CourseGenerationJobMessage.from_body(b"".join(raw_message.body))
        except Exception:
            logger.exception("[service_bus] Malformed message — dead-lettering")
            receiver.dead_letter_message(raw_message, reason="malformed_body")
            return

        # Auto-renew this message's peek-lock for the (long) lifetime of the
        # handler so the lock never expires mid-run and triggers a duplicate,
        # concurrent redelivery of the same job.
        renewer.register(receiver, raw_message)

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
