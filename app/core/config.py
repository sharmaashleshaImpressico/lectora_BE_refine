"""Centralized configuration for the app, currently just Azure DB settings.

All Azure database settings are loaded from environment variables (`.env`).
No credential, connection string, database name, or endpoint should ever be
hardcoded here or anywhere else in the codebase.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSQLSettings(BaseSettings):
    """Azure SQL connection settings, sourced entirely from `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Preferred: individual Azure SQL parts (used to build DATABASE_URL below).
    azure_sql_server: str | None = None
    azure_sql_database: str | None = None
    azure_sql_username: str | None = None
    azure_sql_password: str | None = None
    azure_sql_driver: str = "ODBC Driver 18 for SQL Server"

    # Fallback: a fully-formed SQLAlchemy URL (e.g. for local SQLite dev use).
    database_url: str | None = None

    # Set True to log SQL statements emitted by SQLAlchemy.
    sql_echo: bool = False

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return the SQLAlchemy connection URL, building it from Azure SQL
        parts when `DATABASE_URL` is not explicitly set."""
        if self.database_url:
            return self.database_url

        if not all(
            [
                self.azure_sql_server,
                self.azure_sql_database,
                self.azure_sql_username,
                self.azure_sql_password,
            ]
        ):
            raise ValueError(
                "Azure DB is not configured. Set either DATABASE_URL or all of "
                "AZURE_SQL_SERVER, AZURE_SQL_DATABASE, AZURE_SQL_USERNAME and "
                "AZURE_SQL_PASSWORD in your .env file."
            )

        odbc_params = (
            f"DRIVER={{{self.azure_sql_driver}}};"
            f"SERVER=tcp:{self.azure_sql_server},1433;"
            f"DATABASE={self.azure_sql_database};"
            f"UID={self.azure_sql_username};"
            f"PWD={self.azure_sql_password};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_params)}"


azure_settings = AzureSQLSettings()


class LLMPipelineSettings(BaseSettings):
    """Azure OpenAI + Langfuse settings for the content pipeline's shared LLM client."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-12-01-preview"

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_base_url: str | None = None
    langfuse_project: str | None = None
    langfuse_env: str | None = None
    langfuse_api_key: str | None = None


llm_pipeline_settings = LLMPipelineSettings()
