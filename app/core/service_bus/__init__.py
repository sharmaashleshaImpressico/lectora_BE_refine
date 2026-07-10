"""Azure Service Bus integration: publisher, consumer, worker, and message models.

All Service Bus-related code lives in this package — do not construct
`ServiceBusClient`/`ServiceBusMessage` or read Service Bus env vars anywhere
else in the project.
"""

from __future__ import annotations

from app.core.service_bus.config import ServiceBusSettings, service_bus_settings
from app.core.service_bus.consumer import CourseGenerationJobConsumer
from app.core.service_bus.message_models import CourseGenerationJobMessage
from app.core.service_bus.publisher import CourseGenerationJobPublisher
from app.core.service_bus.worker import CourseGenerationWorker

__all__ = [
    "CourseGenerationJobConsumer",
    "CourseGenerationJobMessage",
    "CourseGenerationJobPublisher",
    "CourseGenerationWorker",
    "ServiceBusSettings",
    "service_bus_settings",
]
