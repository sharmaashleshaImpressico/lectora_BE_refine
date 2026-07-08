"""DB layer: declarative base, engine/session wiring, and the Azure DB client.

Application code should depend on this package instead of importing
SQLAlchemy or Azure SDKs directly.
"""

from app.db.base import Base
from app.db.session import AzureDatabaseClient, azure_db_client, get_db

__all__ = [
    "AzureDatabaseClient",
    "azure_db_client",
    "Base",
    "get_db",
]
