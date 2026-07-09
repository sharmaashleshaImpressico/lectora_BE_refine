"""Microsoft Entra access-token validation."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.core.auth.config import auth_settings

logger = logging.getLogger(__name__)

_JWKS_CACHE_TTL_SECONDS = 3600
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expires_at: float = 0.0

_SUPPORTED_ALGORITHMS = ("RS256",)


class TokenValidationError(Exception):
    """Raised when an access token fails validation."""


def _fetch_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_cache_expires_at

    now = time.time()
    if _jwks_cache is not None and now < _jwks_cache_expires_at:
        return _jwks_cache

    try:
        response = httpx.get(auth_settings.azure_jwks_url, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Failed to fetch Microsoft JWKS")
        raise TokenValidationError("Unable to validate token") from None

    _jwks_cache = response.json()
    _jwks_cache_expires_at = now + _JWKS_CACHE_TTL_SECONDS
    return _jwks_cache


def _find_signing_key(jwks: dict[str, Any], kid: str, *, refresh: bool) -> dict[str, Any]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key

    if refresh:
        global _jwks_cache, _jwks_cache_expires_at
        _jwks_cache = None
        _jwks_cache_expires_at = 0.0
        refreshed = _fetch_jwks()
        for key in refreshed.get("keys", []):
            if key.get("kid") == kid:
                return key

    raise TokenValidationError("Token signing key not found")


def _accepted_audiences() -> list[str]:
    """Audience values accepted for Microsoft access tokens."""
    audiences: list[str] = []
    for value in (
        auth_settings.azure_api_audience,
        auth_settings.azure_api_client_id,
        f"api://{auth_settings.azure_api_client_id}",
    ):
        if value and value not in audiences:
            audiences.append(value)
    return audiences


def _accepted_issuers() -> tuple[str, ...]:
    """Issuer values accepted for the configured tenant (v2 and legacy v1)."""
    issuers: list[str] = [auth_settings.azure_issuer]
    v1_issuer = f"https://sts.windows.net/{auth_settings.azure_tenant_id}/"
    if v1_issuer not in issuers:
        issuers.append(v1_issuer)
    return tuple(issuers)


def _required_scope_name() -> str:
    """Scope name required in the token `scp` claim (not the full scope URI)."""
    scope = auth_settings.azure_api_scope or "access_as_user"
    return scope.rsplit("/", 1)[-1]


def _claim_values(claims: dict[str, Any], key: str) -> list[str]:
    value = claims.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _resolve_audience_for_decode(unverified_claims: dict[str, Any]) -> str:
    """Pick the token aud value that matches our accepted audiences.

    python-jose requires `audience` to be a string (not a list), so we must
    pass exactly one accepted audience string to jwt.decode().
    """
    token_audiences = _claim_values(unverified_claims, "aud")
    accepted = _accepted_audiences()
    for token_aud in token_audiences:
        if token_aud in accepted:
            return token_aud
    raise TokenValidationError("Invalid audience")


def _validate_scope(claims: dict[str, Any]) -> None:
    required = _required_scope_name()
    scp = claims.get("scp", "")
    if isinstance(scp, str):
        granted = scp.split()
    elif isinstance(scp, list):
        granted = [str(item) for item in scp]
    else:
        granted = []

    if required not in granted:
        raise TokenValidationError("Missing required scope")


def _validate_tenant(claims: dict[str, Any]) -> None:
    token_tid = claims.get("tid")
    if token_tid and str(token_tid) != auth_settings.azure_tenant_id:
        raise TokenValidationError("Invalid tenant")


def _log_auth_debug(stage: str, **fields: Any) -> None:
    logger.info(
        "[auth-debug] %s | %s",
        stage,
        " | ".join(f"{key}={value!r}" for key, value in fields.items()),
    )


def validate_access_token(token: str) -> dict[str, Any]:
    """Validate a Microsoft access token and return its claims."""
    expected_audiences = _accepted_audiences()
    expected_issuers = _accepted_issuers()
    expected_scope = _required_scope_name()

    _log_auth_debug(
        "config",
        expected_issuer=expected_issuers,
        expected_audiences=expected_audiences,
        expected_scope=expected_scope,
        env_audience_var="AZURE_API_AUDIENCE",
        loaded_audience=auth_settings.azure_api_audience,
        loaded_client_id=auth_settings.azure_api_client_id,
    )

    if not token or not isinstance(token, str):
        raise TokenValidationError("Invalid token format")

    token = token.strip()
    if token.count(".") != 2:
        raise TokenValidationError("Invalid token format")

    try:
        header = jwt.get_unverified_header(token)
        unverified_claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise TokenValidationError("Invalid token format") from None

    _log_auth_debug(
        "token-claims",
        iss=unverified_claims.get("iss"),
        aud=unverified_claims.get("aud"),
        scp=unverified_claims.get("scp"),
        tid=unverified_claims.get("tid"),
        ver=unverified_claims.get("ver"),
        azp=unverified_claims.get("azp"),
        appid=unverified_claims.get("appid"),
    )

    kid = header.get("kid")
    if not kid:
        raise TokenValidationError("Invalid token format")

    algorithm = header.get("alg")
    if algorithm not in _SUPPORTED_ALGORITHMS:
        raise TokenValidationError("Unsupported token algorithm")

    try:
        audience_for_decode = _resolve_audience_for_decode(unverified_claims)
    except TokenValidationError as exc:
        _log_auth_debug("audience-resolution-failed", error=str(exc), token_aud=unverified_claims.get("aud"))
        raise

    jwks = _fetch_jwks()
    signing_key = _find_signing_key(jwks, kid, refresh=True)

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=list(_SUPPORTED_ALGORITHMS),
            audience=audience_for_decode,
            issuer=expected_issuers,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except JWTError as exc:
        _log_auth_debug(
            "jwt-decode-failed",
            audience_used=audience_for_decode,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        logger.info("Access token validation failed")
        raise TokenValidationError("Invalid or expired token") from None

    token_use = claims.get("token_use")
    if token_use and str(token_use).lower() == "id":
        raise TokenValidationError("Invalid token type")

    try:
        _validate_scope(claims)
        _validate_tenant(claims)
    except TokenValidationError as exc:
        _log_auth_debug("post-decode-validation-failed", error=str(exc), scp=claims.get("scp"))
        raise

    _log_auth_debug("validation-succeeded", aud=claims.get("aud"), iss=claims.get("iss"))
    return claims
