"""FastAPI dependencies for request authentication."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth.token_validator import TokenValidationError, validate_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def require_valid_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Validate the Bearer access token and return its claims."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return validate_access_token(credentials.credentials)
    except TokenValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


# Claims checked in order for a human-readable identity. `name` is the Entra
# display name; the rest are progressively weaker fallbacks that still
# uniquely identify the signed-in account.
_USER_NAME_CLAIMS = ("name", "preferred_username", "upn", "email")


def get_current_user_name(
    claims: dict[str, Any] = Depends(require_valid_token),
) -> str:
    """Resolve the logged-in user's name from the validated access token."""
    for claim in _USER_NAME_CLAIMS:
        value = claims.get(claim)
        if value and str(value).strip():
            return str(value).strip()

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )
