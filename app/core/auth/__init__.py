"""Microsoft Entra bearer-token authentication."""

from app.core.auth.dependencies import require_valid_token
from app.core.auth.token_validator import TokenValidationError, validate_access_token

__all__ = [
    "TokenValidationError",
    "require_valid_token",
    "validate_access_token",
]
