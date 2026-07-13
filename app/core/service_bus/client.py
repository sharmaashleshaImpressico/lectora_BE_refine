"""Shared Azure Service Bus client factory.

Other modules in `core/service_bus/` should go through `get_service_bus_client`
rather than constructing `ServiceBusClient` themselves, so connection setup
stays in one place and is easy to swap or mock in tests.
"""

from __future__ import annotations

import logging

from azure.servicebus import ServiceBusClient

from app.core.service_bus.config import ServiceBusSettings, service_bus_settings

logger = logging.getLogger(__name__)


def get_service_bus_client(settings: ServiceBusSettings | None = None) -> ServiceBusClient:
    """Build a `ServiceBusClient` from the configured connection string.

    Raises `RuntimeError` if Service Bus is not configured — callers should
    check `settings.is_configured` first if they want to degrade gracefully.
    """
    settings = settings or service_bus_settings
    if not settings.is_configured:
        raise RuntimeError(
            "Azure Service Bus is not configured. Set SERVICE_BUS_CONNECTION_STRING in .env."
        )
    return ServiceBusClient.from_connection_string(settings.service_bus_connection_string)
