"""Pydantic schemas for storage/directory browsing APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StorageEntry(BaseModel):
    """A single folder or file entry within a storage listing."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    path: str
    entry_type: str = Field(serialization_alias="entryType")
    size: int | None = None
    last_modified: str | None = Field(default=None, serialization_alias="lastModified")
    content_type: str | None = Field(default=None, serialization_alias="contentType")


class BrowseResponse(BaseModel):
    """Non-recursive listing of the folders/files immediately under `prefix`."""

    model_config = ConfigDict(populate_by_name=True)

    prefix: str
    entries: list[StorageEntry]
    total_files: int = Field(serialization_alias="totalFiles")
    total_folders: int = Field(serialization_alias="totalFolders")
    total_size: int = Field(serialization_alias="totalSize")
    source: str
    container_name: str | None = Field(default=None, serialization_alias="containerName")
