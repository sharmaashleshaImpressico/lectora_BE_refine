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
    audiences = [auth_settings.azure_api_audience]
    if auth_settings.azure_api_client_id not in audiences:
        audiences.append(auth_settings.azure_api_client_id)
    return audiences


def validate_access_token(token: str) -> dict[str, Any]:
    """Validate a Microsoft access token and return its claims."""
    if not token or not isinstance(token, str):
        raise TokenValidationError("Invalid token format")

    token = token.strip()
    if token.count(".") != 2:
        raise TokenValidationError("Invalid token format")

    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise TokenValidationError("Invalid token format") from None

    kid = header.get("kid")
    if not kid:
        raise TokenValidationError("Invalid token format")

    algorithm = header.get("alg")
    if algorithm not in _SUPPORTED_ALGORITHMS:
        raise TokenValidationError("Unsupported token algorithm")

    jwks = _fetch_jwks()
    signing_key = _find_signing_key(jwks, kid, refresh=True)

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=list(_SUPPORTED_ALGORITHMS),
            audience=_accepted_audiences(),
            issuer=auth_settings.azure_issuer,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except JWTError:
        logger.info("Access token validation failed")
        raise TokenValidationError("Invalid or expired token") from None

    token_use = claims.get("token_use")
    if token_use and str(token_use).lower() == "id":
        raise TokenValidationError("Invalid token type")

    return claims
