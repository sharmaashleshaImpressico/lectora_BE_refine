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
            # Encrypt is mandatory for Azure SQL. Connection Timeout is generous
            # because the gateway login handshake can take several seconds over a
            # slow/remote network — a shorter value surfaces as an HYT00 "Login
            # timeout expired" even though the credentials are valid.
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;"
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


class AzureStorageSettings(BaseSettings):
    """Azure Blob Storage settings for document uploads and pipeline artifacts."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_storage_connection_string: str | None = None
    blob_container_name: str = "uploaded-documents"
    # Dedicated container for FE-uploaded source documents (Documents library).
    # Kept separate from `blob_container_name`, which `.env` may point at a
    # different container used for shared-state / pipeline artifacts.
    uploaded_documents_container_name: str = "uploaded-documents"
    course_generation_artifacts_container_name: str = "course-generation-artifacts"
    local_upload_root: str = "data/uploads"

    @property
    def is_configured(self) -> bool:
        return bool(
            self.azure_storage_connection_string
            and self.uploaded_documents_container_name.strip()
        )


class IngestionSettings(BaseSettings):
    """Azure AI Search + embeddings settings for the document ingestion pipeline."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_search_endpoint: str | None = None
    azure_search_api_key: str | None = None
    azure_search_index_name: str = "course-chunks"
    azure_openai_embeddings_resource_name: str | None = None
    azure_openai_embeddings_key: str | None = None
    ingestion_embedding_deployment: str = "text-embedding-3-large"
    ingestion_max_chunk_tokens: int = 1500
    ingestion_min_chunk_tokens: int = 80


azure_storage_settings = AzureStorageSettings()
ingestion_settings = IngestionSettings()
