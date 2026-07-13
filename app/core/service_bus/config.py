"""Azure Service Bus settings, sourced entirely from `.env`."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceBusSettings(BaseSettings):
    """Connection details for the course-generation job queue."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_bus_namespace: str | None = None
    service_bus_connection_string: str | None = None
    queue_name: str = "course-jobs"

    @property
    def is_configured(self) -> bool:
        return bool(self.service_bus_connection_string)


service_bus_settings = ServiceBusSettings()
