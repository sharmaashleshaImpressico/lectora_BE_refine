"""Microsoft Entra / MSAL authentication settings loaded from `.env`."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Azure AD token validation settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_tenant_id: str
    azure_api_client_id: str
    azure_api_audience: str
    azure_api_scope: str | None = None
    azure_authority: str
    azure_jwks_url: str
    azure_issuer: str


auth_settings = AuthSettings()
