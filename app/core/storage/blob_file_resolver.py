"""Resolves source-document references from the frontend into real local files.

The frontend sends `blobPaths` — Azure Blob Storage paths such as
`"Employer-Provided_Health_Plans/05_COBRA_Continuation_Coverage.docx"` — not
local filesystem paths. Every parser downstream (python-docx, pypdf) needs an
actual file on disk, so each reference must be resolved to a local path
*before* it reaches a parser: downloaded from Azure Blob Storage, or read from
the local upload fallback root when Azure isn't configured.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from app.core.storage.azure_blob_client import AzureBlobClient, LocalUploadStore

logger = logging.getLogger(__name__)


class BlobResolutionError(RuntimeError):
    """Raised when a source-document reference cannot be resolved to a real local file."""


def resolve_source_path(
    path_str: str,
    *,
    blob_client: AzureBlobClient | None = None,
    local_store: LocalUploadStore | None = None,
) -> str:
    """Resolve a blob path (or an already-local path) to an absolute local file path.

    Resolution order:
      1. Already a real local file — used as-is (covers tests/direct-path callers).
      2. Azure Blob Storage — download the blob to a local temp file.
      3. Local upload fallback root — used when Azure isn't configured.
    """
    candidate = Path(path_str)
    if candidate.is_file():
        size = candidate.stat().st_size
        logger.info(
            "[blob-resolve] %r is already a local file | path=%s | exists=True | size=%d bytes",
            path_str,
            candidate.resolve(),
            size,
        )
        return str(candidate.resolve())

    client = blob_client or AzureBlobClient()
    if client.is_ready():
        return str(_download_from_azure(path_str, client))

    store = local_store or LocalUploadStore()
    local_candidate = store.resolve(path_str)
    exists = local_candidate.is_file()
    size = local_candidate.stat().st_size if exists else 0
    logger.info(
        "[blob-resolve] Azure not configured — resolved via local upload fallback | "
        "blob_path=%r | local_path=%s | exists=%s | size=%d bytes",
        path_str,
        local_candidate,
        exists,
        size,
    )
    if not exists:
        raise BlobResolutionError(
            f"Could not resolve source file '{path_str}': not found on disk, Azure Blob "
            f"Storage is not configured, and no matching file exists under the local "
            f"upload fallback root ({store.root})."
        )
    return str(local_candidate.resolve())


def _download_from_azure(blob_path: str, client: AzureBlobClient) -> Path:
    logger.info(
        "[blob-resolve] Downloading blob | blob_path=%r | container=%r",
        blob_path,
        client.container_name,
    )
    try:
        content = client.download_bytes(blob_path)
    except FileNotFoundError:
        logger.error(
            "[blob-resolve] Blob not found | blob_path=%r | container=%r",
            blob_path,
            client.container_name,
        )
        raise BlobResolutionError(
            f"Could not resolve source file '{blob_path}': not found in Azure Blob "
            f"Storage container '{client.container_name}'."
        ) from None
    except Exception as exc:
        logger.exception(
            "[blob-resolve] Azure download failed | blob_path=%r | container=%r",
            blob_path,
            client.container_name,
        )
        raise BlobResolutionError(
            f"Could not download source file '{blob_path}' from Azure Blob Storage: {exc}"
        ) from exc

    # Use a per-blob temp directory (rather than NamedTemporaryFile's random
    # suffix on the filename itself) so the local file keeps the exact source
    # filename — downstream naming (OutputSlugResolver, _persist_input_files)
    # derives course/output names from the filename.
    tmp_dir = Path(tempfile.mkdtemp(prefix="blob_dl_"))
    local_path = tmp_dir / Path(blob_path).name
    local_path.write_bytes(content)

    exists = local_path.is_file()
    size = local_path.stat().st_size if exists else 0
    logger.info(
        "[blob-resolve] Downloaded blob -> local file | blob_path=%r | local_path=%s | "
        "exists=%s | size=%d bytes",
        blob_path,
        local_path,
        exists,
        size,
    )
    if not exists or size == 0:
        raise BlobResolutionError(
            f"Downloaded blob '{blob_path}' but the local file is missing or empty at {local_path}."
        )
    return local_path
