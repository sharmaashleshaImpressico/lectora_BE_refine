from __future__ import annotations
import logging
from datetime import datetime, timezone

import httpx

from app.ai.ingestion.chunking.models import CourseChunk
from app.ai.ingestion.storage.index_schema import get_index_definition

logger = logging.getLogger(__name__)

# Vector-heavy documents exceed Azure's 16 MB batch limit well before 100 docs.
_BATCH_SIZE = 15
_API_VERSION = "2024-07-01"
_REQUEST_TIMEOUT = 300


class AzureSearchIngestionClient:
    """
    Upload CourseChunk documents to Azure AI Search via the REST API.

    Each document stored in the index contains:
        - chunk_id / document_id / section_id — identity
        - title — section heading
        - raw_text — retrievable content
        - source_file / page_num — source provenance
        - token_count / estimated_read_min / upload_date — stats
        - searchable_text — BM25 catch-all
        - embedding_content — 3072-dim vector
    """

    def __init__(self, endpoint: str, api_key: str, index_name: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._index_name = index_name
        self._headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }
        # Populated by ensure_index_exists() from the *live* index definition —
        # used by upload_chunks() so dimension checks reflect what Azure
        # actually has, not just what our local schema module expects.
        self._verified_vector_dims: int | None = None

    # ── Index management ──────────────────────────────────────────────────────

    def ensure_index_exists(self) -> None:
        """Create the Azure AI Search index if it does not already exist."""
        index_url = f"{self._endpoint}/indexes/{self._index_name}?api-version={_API_VERSION}"
        try:
            resp = httpx.get(index_url, headers=self._headers, timeout=30)
            logger.debug(
                "[azure_search] GET %s -> %d", index_url, resp.status_code,
            )
            if resp.status_code == 200:
                doc_count = self._get_document_count()
                logger.info(
                    "[azure_search] Index '%s' ready (%s documents).",
                    self._index_name,
                    doc_count if doc_count is not None else "unknown",
                )
                self._verify_live_schema(resp.json())
                return
            if resp.status_code != 404:
                raise RuntimeError(
                    f"Unexpected status {resp.status_code} checking index "
                    f"'{self._index_name}': {resp.text[:400]}"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Could not reach Azure AI Search: {exc}") from exc

        create_url = f"{self._endpoint}/indexes?api-version={_API_VERSION}"
        definition = get_index_definition(self._index_name)
        try:
            resp = httpx.post(
                create_url, json=definition, headers=self._headers, timeout=_REQUEST_TIMEOUT
            )
            logger.debug(
                "[azure_search] POST %s -> %d: %s",
                create_url, resp.status_code, resp.text[:400],
            )
            if resp.status_code in (200, 201):
                logger.info("[azure_search] Index '%s' created.", self._index_name)
                self._verify_live_schema(resp.json())
                return
            raise RuntimeError(
                f"Failed to create index '{self._index_name}': "
                f"{resp.status_code} {resp.text[:400]}"
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Exception creating index '{self._index_name}': {exc}") from exc

    def delete_index(self) -> bool:
        """Delete the index if it exists. Returns True if a delete was issued."""
        index_url = f"{self._endpoint}/indexes/{self._index_name}?api-version={_API_VERSION}"
        resp = httpx.delete(index_url, headers=self._headers, timeout=60)
        if resp.status_code in (204, 404):
            logger.info(
                "[azure_search] Delete '%s' -> %d (204=deleted, 404=already absent)",
                self._index_name, resp.status_code,
            )
            self._verified_vector_dims = None
            return resp.status_code == 204
        raise RuntimeError(
            f"Failed to delete index '{self._index_name}': "
            f"{resp.status_code} {resp.text[:400]}"
        )

    def _verify_live_schema(self, live_definition: dict) -> None:
        """
        Compare the index Azure actually has against what this pipeline expects.

        The index may have been created earlier (by an older code version, or
        manually) with a different embedding dimension or a missing vector
        field. If so, every subsequent document upload is rejected by Azure
        with an opaque per-doc error — this check catches that up front with
        an actionable message instead of letting every chunk fail silently.
        """
        expected = get_index_definition(self._index_name)
        expected_field = next(
            (f for f in expected["fields"] if f.get("name") == "embedding_content"), None
        )
        live_field = next(
            (f for f in live_definition.get("fields", []) if f.get("name") == "embedding_content"),
            None,
        )
        expected_dims = expected_field.get("dimensions") if expected_field else None
        live_dims = live_field.get("dimensions") if live_field else None
        self._verified_vector_dims = live_dims

        if live_field is None:
            logger.error(
                "[azure_search] Live index '%s' has no 'embedding_content' vector "
                "field — every vector upload will be rejected.",
                self._index_name,
            )
            raise RuntimeError(
                f"Index '{self._index_name}' exists but is missing the "
                "'embedding_content' vector field. Delete the index in Azure AI "
                "Search (or set AZURE_SEARCH_INDEX_NAME to a new name) so it can "
                "be recreated with the correct schema."
            )

        if expected_dims is not None and live_dims != expected_dims:
            logger.error(
                "[azure_search] Vector dimension mismatch for index '%s': "
                "live=%s expected=%s. Every chunk upload will fail until this "
                "is resolved.",
                self._index_name, live_dims, expected_dims,
            )
            raise RuntimeError(
                f"Index '{self._index_name}' has embedding_content "
                f"dimensions={live_dims}, but the ingestion pipeline produces "
                f"{expected_dims}-dim vectors. Delete the index (or point "
                "AZURE_SEARCH_INDEX_NAME at a new index) so it is recreated "
                "with matching dimensions."
            )

        logger.info(
            "[azure_search] Live schema verified for '%s' (embedding_content dims=%s).",
            self._index_name, live_dims,
        )

    def _get_document_count(self) -> int | None:
        """Return total documents in the index, or None when the count API fails."""
        count_url = (
            f"{self._endpoint}/indexes/{self._index_name}/docs/$count"
            f"?api-version={_API_VERSION}"
        )
        try:
            resp = httpx.get(count_url, headers=self._headers, timeout=30)
            if resp.status_code == 200:
                return int(resp.text.strip())
        except Exception as exc:
            logger.warning("[azure_search] Could not read document count: %s", exc)
        return None

    def describe_index(self) -> dict:
        """Return index presence, document count, and queryability for diagnostics."""
        index_url = f"{self._endpoint}/indexes/{self._index_name}?api-version={_API_VERSION}"
        search_url = (
            f"{self._endpoint}/indexes/{self._index_name}/docs/search"
            f"?api-version={_API_VERSION}"
        )
        result: dict = {
            "configured": True,
            "endpoint": self._endpoint,
            "index_name": self._index_name,
            "api_version": _API_VERSION,
            "index_exists": False,
            "document_count": None,
            "searchable": False,
            "indexes": [],
        }
        try:
            list_resp = httpx.get(
                f"{self._endpoint}/indexes?api-version={_API_VERSION}",
                headers=self._headers,
                timeout=30,
            )
            if list_resp.status_code == 200:
                result["indexes"] = [
                    item.get("name")
                    for item in list_resp.json().get("value", [])
                    if item.get("name")
                ]
        except Exception as exc:
            result["error"] = f"Could not list indexes: {exc}"
            return result

        try:
            index_resp = httpx.get(index_url, headers=self._headers, timeout=30)
            result["index_exists"] = index_resp.status_code == 200
            if index_resp.status_code != 200:
                result["index_error"] = index_resp.text[:300]
        except Exception as exc:
            result["index_error"] = str(exc)
            return result

        result["document_count"] = self._get_document_count()

        try:
            search_resp = httpx.post(
                search_url,
                headers=self._headers,
                json={"search": "*", "top": 1, "select": "chunk_id"},
                timeout=30,
            )
            result["searchable"] = search_resp.status_code == 200
            if search_resp.status_code != 200:
                result["search_error"] = search_resp.text[:300]
        except Exception as exc:
            result["search_error"] = str(exc)

        return result

    # ── Document upload ───────────────────────────────────────────────────────

    def upload_chunks(self, chunks: list[CourseChunk]) -> dict:
        """
        Serialise and upload chunks to Azure AI Search in batches of 100.

        Each document includes raw_text alongside all vector embeddings so
        the full text is always retrievable from the index without a separate
        blob lookup.

        Returns a summary dict: {"succeeded": int, "failed": int}.
        """
        upload_url = (
            f"{self._endpoint}/indexes/{self._index_name}/docs/index"
            f"?api-version={_API_VERSION}"
        )
        upload_date = datetime.now(timezone.utc).isoformat()
        total_succeeded = 0
        total_failed = 0
        sample_errors: list[str] = []
        batch_count = (len(chunks) + _BATCH_SIZE - 1) // _BATCH_SIZE
        # Prefer the dimension confirmed against the *live* index (set by
        # ensure_index_exists); fall back to the local schema definition if
        # upload_chunks() is ever called without it (e.g. in isolated tests).
        if self._verified_vector_dims is not None:
            expected_dims = self._verified_vector_dims
        else:
            index_fields = get_index_definition(self._index_name)["fields"]
            expected_dims = next(
                int(field["dimensions"])
                for field in index_fields
                if field.get("name") == "embedding_content"
            )
        missing_embeddings = [chunk.chunk_id for chunk in chunks if not chunk.embedding_content]
        wrong_dims = sorted({
            len(chunk.embedding_content or [])
            for chunk in chunks
            if chunk.embedding_content and len(chunk.embedding_content) != expected_dims
        })
        if missing_embeddings or wrong_dims:
            logger.error(
                "[azure_search] Refusing to upload chunks with invalid embeddings "
                "(missing=%d wrong_dims=%s sample_missing=%s)",
                len(missing_embeddings),
                wrong_dims,
                missing_embeddings[:5],
            )
            raise RuntimeError(
                "Attempted to upload chunks without valid embedding_content vectors."
            )

        logger.info(
            "[azure_search] Uploading %d chunks to index '%s' in %d batch(es) "
            "(all vectors present, dims=%d)...",
            len(chunks), self._index_name, batch_count, expected_dims,
        )

        for batch_start in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[batch_start : batch_start + _BATCH_SIZE]
            docs = [_chunk_to_doc(c, upload_date) for c in batch]
            payload = {"value": docs}
            logger.debug(
                "[azure_search] Batch %d: uploading %d docs (keys=%s, "
                "vector_lens=%s)",
                batch_start,
                len(docs),
                [d["chunk_id"] for d in docs],
                sorted({len(d["embedding_content"]) for d in docs if "embedding_content" in d}),
            )

            try:
                resp = httpx.post(
                    upload_url, json=payload, headers=self._headers, timeout=_REQUEST_TIMEOUT
                )
                logger.debug(
                    "[azure_search] Batch %d: response status=%d body=%s",
                    batch_start, resp.status_code, resp.text[:1000],
                )
                if resp.status_code in (200, 207):
                    for item in resp.json().get("value", []):
                        if item.get("status"):
                            total_succeeded += 1
                        else:
                            total_failed += 1
                            err_msg = (
                                f"key={item.get('key')} "
                                f"statusCode={item.get('statusCode')} "
                                f"error={item.get('errorMessage')}"
                            )
                            logger.warning("[azure_search] Doc failed: %s", err_msg)
                            if len(sample_errors) < 5:
                                sample_errors.append(err_msg)
                else:
                    logger.error(
                        "[azure_search] Batch upload %d returned %d: %s",
                        batch_start, resp.status_code, resp.text[:1000],
                    )
                    total_failed += len(batch)
                    if len(sample_errors) < 5:
                        sample_errors.append(
                            f"HTTP {resp.status_code}: {resp.text[:300]}"
                        )
            except Exception as exc:
                logger.error("[azure_search] Exception uploading batch %d: %s", batch_start, exc)
                total_failed += len(batch)
                if len(sample_errors) < 5:
                    sample_errors.append(str(exc))

        doc_count = self._get_document_count()
        logger.info(
            "[azure_search] Upload complete — succeeded: %d  failed: %d  "
            "index_total_docs: %s",
            total_succeeded,
            total_failed,
            doc_count if doc_count is not None else "unknown",
        )
        if total_succeeded == 0 and chunks:
            detail = "; ".join(sample_errors[:3]) if sample_errors else "no error detail captured"
            raise RuntimeError(
                f"Azure Search upload failed for all {len(chunks)} chunks "
                f"(index '{self._index_name}'): {detail}"
            )
        return {"succeeded": total_succeeded, "failed": total_failed}


# ── Serialisation ─────────────────────────────────────────────────────────────

_METADATA_STRING_FIELDS = (
    "course_id",
    "jurisdiction",
    "source_type",
    "source_priority",
    "source_intent",
    "section_title",
    "chunk_title",
)


def _chunk_to_doc(chunk: CourseChunk, upload_date: str) -> dict:
    """Convert a CourseChunk to an Azure AI Search document."""
    doc: dict = {
        "@search.action": "mergeOrUpload",
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "section_id": chunk.section_id,
        "source_file": chunk.source_file or "",
        "title": chunk.title or "",
        "raw_text": chunk.raw_text or "",
        "token_count": chunk.token_count,
        "estimated_read_min": chunk.estimated_read_min,
        "upload_date": upload_date,
        "searchable_text": chunk.searchable_text or "",
    }
    if chunk.page_num is not None:
        doc["page_num"] = chunk.page_num
    if chunk.chunk_index is not None:
        doc["chunk_index"] = chunk.chunk_index
    for field_name in _METADATA_STRING_FIELDS:
        value = getattr(chunk, field_name, None)
        if value:
            doc[field_name] = value
    for field_name, vector in (("embedding_content", chunk.embedding_content),):
        if vector:
            doc[field_name] = vector
    return doc
