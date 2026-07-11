"""Thin wrapper around Azure Blob Storage for document uploads."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobPrefix, BlobServiceClient, ContentSettings

from app.core.config import AzureStorageSettings, azure_storage_settings

logger = logging.getLogger(__name__)


@dataclass
class StorageEntryData:
    """One folder or file entry returned by a storage listing."""

    name: str
    path: str
    entry_type: str  # "folder" | "file"
    size: int | None = None
    last_modified: str | None = None
    content_type: str | None = None


class AzureBlobClient:
    """Upload and read blobs from the configured Azure container."""

    def __init__(self, settings: AzureStorageSettings | None = None) -> None:
        self._settings = settings or azure_storage_settings
        self._client: BlobServiceClient | None = None

    @property
    def container_name(self) -> str:
        return self._settings.uploaded_documents_container_name

    def is_ready(self) -> bool:
        return self._settings.is_configured

    def _service_client(self) -> BlobServiceClient:
        if not self.is_ready():
            raise RuntimeError("Azure Blob Storage is not configured.")
        if self._client is None:
            self._client = BlobServiceClient.from_connection_string(
                self._settings.azure_storage_connection_string  # type: ignore[arg-type]
            )
        return self._client

    def upload_bytes(self, blob_path: str, content: bytes, *, content_type: str) -> None:
        """Upload bytes to the configured container."""
        blob_client = (
            self._service_client()
            .get_container_client(self.container_name)
            .get_blob_client(blob_path)
        )
        blob_client.upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        logger.info(
            "[blob] Uploaded %s (%d bytes) to container %s",
            blob_path,
            len(content),
            self.container_name,
        )

    def exists(self, blob_path: str) -> bool:
        """Return True if a blob already exists at `blob_path` in the configured container."""
        blob_client = (
            self._service_client()
            .get_container_client(self.container_name)
            .get_blob_client(blob_path)
        )
        return blob_client.exists()

    def download_bytes(self, blob_path: str) -> bytes:
        """Download a blob's raw bytes from the configured container."""
        blob_client = (
            self._service_client()
            .get_container_client(self.container_name)
            .get_blob_client(blob_path)
        )
        try:
            content = blob_client.download_blob().readall()
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(
                f"Blob '{blob_path}' not found in container '{self.container_name}'."
            ) from exc
        logger.info(
            "[blob] Downloaded %s (%d bytes) from container %s",
            blob_path,
            len(content),
            self.container_name,
        )
        return content

    def list_entries(self, prefix: str) -> list[StorageEntryData]:
        """List immediate folders/files under `prefix` (non-recursive)."""
        container_client = self._service_client().get_container_client(self.container_name)
        entries: list[StorageEntryData] = []
        for item in container_client.walk_blobs(name_starts_with=prefix, delimiter="/"):
            if isinstance(item, BlobPrefix):
                name = item.name.rstrip("/").rsplit("/", 1)[-1]
                entries.append(StorageEntryData(name=name, path=item.name, entry_type="folder"))
            else:
                name = item.name.rsplit("/", 1)[-1]
                content_type = item.content_settings.content_type if item.content_settings else None
                entries.append(
                    StorageEntryData(
                        name=name,
                        path=item.name,
                        entry_type="file",
                        size=item.size,
                        last_modified=item.last_modified.isoformat() if item.last_modified else None,
                        content_type=content_type,
                    )
                )
        return entries


class LocalUploadStore:
    """Filesystem fallback when Azure Blob Storage is not configured."""

    def __init__(self, settings: AzureStorageSettings | None = None) -> None:
        self._root = Path((settings or azure_storage_settings).local_upload_root)

    @property
    def root(self) -> Path:
        return self._root

    def save_bytes(self, blob_path: str, content: bytes) -> Path:
        """Persist content under the local upload root, mirroring blob paths."""
        dest = self._root / blob_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest

    def resolve(self, blob_path: str) -> Path:
        """Return the local filesystem path that mirrors `blob_path` under the upload root."""
        return self._root / blob_path

    def exists(self, blob_path: str) -> bool:
        """Return True if a file already exists at `blob_path` under the local upload root."""
        return self.resolve(blob_path).is_file()

    def list_entries(self, prefix: str) -> list[StorageEntryData]:
        """List immediate folders/files under `prefix` (non-recursive), mirroring blob paths."""
        directory = self._root / prefix
        if not directory.is_dir():
            return []
        entries: list[StorageEntryData] = []
        for child in sorted(directory.iterdir()):
            path = f"{prefix}{child.name}"
            if child.is_dir():
                entries.append(StorageEntryData(name=child.name, path=f"{path}/", entry_type="folder"))
            else:
                stat = child.stat()
                entries.append(
                    StorageEntryData(
                        name=child.name,
                        path=path,
                        entry_type="file",
                        size=stat.st_size,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    )
                )
        return entries
