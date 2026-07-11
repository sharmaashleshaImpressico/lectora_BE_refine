from __future__ import annotations
import logging

import httpx
import openai

logger = logging.getLogger(__name__)

_API_VERSION = "2024-07-01"
_EMBEDDING_DIMS = 3072
_DEFAULT_TOP = 5
EMBEDDING_CONTENT_VECTOR_FIELD = "embedding_content"

# Fields returned with every search result — raw_text is always included so
# callers receive the verbatim chunk text alongside the matched score.
_DEFAULT_SELECT = (
    "chunk_id,document_id,section_id,source_file,page_num,"
    "title,raw_text,"
    "token_count,estimated_read_min,"
    "course_id,run_id,jurisdiction"
)


def _escape_odata_literal(value: str) -> str:
    """Escape single quotes for safe interpolation into an OData filter string."""
    return str(value).replace("'", "''")


def build_scope_filter(
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    course_id: str | None = None,
    run_id: str | None = None,
    jurisdiction: str | None = None,
) -> str | None:
    """
    Build a combined OData ``$filter`` expression restricting search to the
    given course/run/document/jurisdiction scope.

    Each provided field contributes an ``eq`` clause (or ``search.in`` for
    ``document_ids``); clauses are joined with ``and``. Fields left as
    ``None`` are omitted so retrieval degrades gracefully when scope
    metadata isn't available (legacy/unindexed chunks).

    ``course_id`` and ``document_id``/``document_ids`` are combined: when both
    are supplied, results must match the course AND the document scope, so
    only chunks belonging to the specified course and document(s) are ever
    returned.
    """
    clauses: list[str] = []

    if document_id:
        clauses.append(f"document_id eq '{_escape_odata_literal(document_id)}'")
    if document_ids:
        safe_ids = ",".join(_escape_odata_literal(str(v)) for v in document_ids if str(v).strip())
        if safe_ids:
            clauses.append(f"search.in(document_id, '{safe_ids}', ',')")
    if course_id:
        clauses.append(f"course_id eq '{_escape_odata_literal(course_id)}'")
    if run_id:
        clauses.append(f"run_id eq '{_escape_odata_literal(run_id)}'")
    if jurisdiction:
        clauses.append(f"jurisdiction eq '{_escape_odata_literal(jurisdiction)}'")

    return " and ".join(clauses) if clauses else None


class CourseRetrievalService:
    """
    Retrieve course content from Azure AI Search using chunk embeddings only.

    Every search request must successfully generate a query embedding and then run
    a vector similarity search on ``embedding_content``. No BM25, source-file, or
    keyword fallback is used; failures are surfaced via logs and empty results.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        index_name: str,
        embeddings_client: openai.AsyncAzureOpenAI,
        embedding_deployment: str,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._index_name = index_name
        self._embeddings_client = embeddings_client
        self._embedding_deployment = embedding_deployment
        self._search_headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }
    # ── Query embedding ───────────────────────────────────────────────────────

    def embed_query(self, text: str) -> list[float]:
        """
        Synchronously embed a single query string.

        Delegates to embed_batch() for a unified code path.
        Returns an empty list on failure so the caller can stop retrieval early.
        """
        result = self.embed_batch([text])
        return result[0] if result else []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Synchronously embed multiple texts in a single API call.

        One HTTP round-trip regardless of batch size.  The Azure OpenAI billing
        unit (tokens) is identical to calling embed_query() N times.

        Returns a list of embedding vectors in the same order as ``texts``.
        On failure returns a list of empty lists (one per input).
        """
        if not texts:
            return []
        import asyncio
        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is not None:
                # Called from inside a running event loop (e.g. an async route).
                # Dispatch to a fresh thread so asyncio.run() can own its own loop.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(
                        asyncio.run, self._async_embed_batch(texts)
                    ).result(timeout=60)
            else:
                # Called from a sync context or a worker thread with no event loop
                # (e.g. ThreadPoolExecutor-*).  asyncio.run() creates its own loop.
                return asyncio.run(self._async_embed_batch(texts))
        except Exception as exc:
            logger.warning(
                "[retrieval] embed_batch failed (%d texts, deployment=%s): %s",
                len(texts),
                self._embedding_deployment,
                exc,
            )
            return [[] for _ in texts]

    async def _async_embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._embeddings_client.embeddings.create(
            model=self._embedding_deployment,
            input=texts,
            dimensions=_EMBEDDING_DIMS,
        )
        # Sort by index to guarantee input order is preserved (API contract).
        sorted_data = sorted(response.data, key=lambda e: e.index)
        logger.debug(
            "[retrieval] Query embeddings generated "
            "(count=%d deployment=%s dims=%d)",
            len(sorted_data),
            self._embedding_deployment,
            _EMBEDDING_DIMS,
        )
        return [item.embedding for item in sorted_data]

    # ── Core search ───────────────────────────────────────────────────────────

    def _search(
        self,
        query: str,
        vector_fields: list[str] | None = None,
        filters: str | None = None,
        top: int = _DEFAULT_TOP,
        select: str = _DEFAULT_SELECT,
        use_semantic: bool = False,
    ) -> list[dict]:
        """
        Execute a vector-only search request and return raw result dicts.

        The request is considered invalid when query embedding generation fails.
        In that case this method logs the failure context and returns no results
        instead of silently degrading to a non-vector retrieval mode.
        """
        url = (
            f"{self._endpoint}/indexes/{self._index_name}/docs/search"
            f"?api-version={_API_VERSION}"
        )
        embedding = self.embed_query(query)
        target_fields = vector_fields or [EMBEDDING_CONTENT_VECTOR_FIELD]
        if not embedding:
            logger.error(
                "[retrieval] Query embedding missing; aborting vector search "
                "(query=%r, fields=%s, filter=%r, deployment=%s)",
                query[:80],
                target_fields,
                filters,
                self._embedding_deployment,
            )
            return []

        vector_queries = [
            {"kind": "vector", "vector": embedding, "fields": field, "k": top}
            for field in target_fields
            if embedding
        ]
        payload: dict = {
            "vectorQueries": vector_queries,
            "top": top,
            "select": select,
        }
        if filters:
            payload["filter"] = filters
        if use_semantic:
            logger.debug(
                "[retrieval] Ignoring semantic reranker request for query=%r "
                "because retrieval is embedding-only.",
                query[:80],
            )

        try:
            resp = httpx.post(
                url, json=payload, headers=self._search_headers, timeout=30
            )
            resp.raise_for_status()

            results = resp.json().get("value", [])
            logger.info(
                "[retrieval] Query='%s' → %d results "
                "(vector_only=%s, dims=%d, fields=%s, filter=%r)",
                query[:60], len(results),
                True,
                len(embedding),
                target_fields,
                filters,
            )
            return results

        except Exception as exc:
            logger.warning(
                "[retrieval] Vector search failed for query=%r fields=%s filter=%r: %s",
                query[:80],
                target_fields,
                filters,
                exc,
            )
            return []

    # ── Retrieval strategies ──────────────────────────────────────────────────

    def retrieve_topic(
        self,
        topic: str,
        document_id: str | None = None,
        top: int = _DEFAULT_TOP,
        *,
        document_ids: list[str] | None = None,
        course_id: str | None = None,
        run_id: str | None = None,
        jurisdiction: str | None = None,
    ) -> list[dict]:
        """
        Retrieve chunks most relevant to a topic (lesson-level) using vectors only.

        Pre-filters the search space to the given course/run/document/jurisdiction
        scope before running vector similarity — see ``build_scope_filter``.
        """
        filters = build_scope_filter(
            document_id=document_id,
            document_ids=document_ids,
            course_id=course_id,
            run_id=run_id,
            jurisdiction=jurisdiction,
        )
        if not filters:
            logger.warning(
                "[retrieval] retrieve_topic called with no scope filters "
                "(course_id/run_id/document_id/jurisdiction) — searching the "
                "full shared index for query=%r.",
                topic[:80],
            )
        return self._search(
            topic,
            vector_fields=[EMBEDDING_CONTENT_VECTOR_FIELD],
            filters=filters,
            top=top,
        )

    def retrieve_for_subtopic(
        self,
        subtopic_query: str,
        document_id: str | None = None,
        top: int = _DEFAULT_TOP,
        *,
        document_ids: list[str] | None = None,
        course_id: str | None = None,
        run_id: str | None = None,
        jurisdiction: str | None = None,
    ) -> list[dict]:
        """
        Retrieve chunks for a single subtopic using vectors only.

        Pre-filters the search space to the given course/run/document/jurisdiction
        scope before running vector similarity — see ``build_scope_filter``.
        """
        filters = build_scope_filter(
            document_id=document_id,
            document_ids=document_ids,
            course_id=course_id,
            run_id=run_id,
            jurisdiction=jurisdiction,
        )
        if not filters:
            logger.warning(
                "[retrieval] retrieve_for_subtopic called with no scope filters "
                "(course_id/run_id/document_id/jurisdiction) — searching the "
                "full shared index for query=%r.",
                subtopic_query[:80],
            )
        return self._search(
            subtopic_query,
            vector_fields=[EMBEDDING_CONTENT_VECTOR_FIELD],
            filters=filters,
            top=top,
        )

    def list_chunks_for_section(self, section_id: str, top: int = 50) -> list[dict]:
        """Return all indexed chunks for one section (full section text, ordered)."""
        safe_section_id = str(section_id or "").replace("'", "''")
        if not safe_section_id:
            return []

        url = (
            f"{self._endpoint}/indexes/{self._index_name}/docs/search"
            f"?api-version={_API_VERSION}"
        )
        payload: dict = {
            "search": "*",
            "filter": f"section_id eq '{safe_section_id}'",
            "top": top,
            "select": _DEFAULT_SELECT,
            "orderby": "chunk_id asc",
        }
        try:
            resp = httpx.post(
                url, json=payload, headers=self._search_headers, timeout=30
            )
            resp.raise_for_status()
            results = resp.json().get("value", [])
            logger.info(
                "[retrieval] section_id=%r → %d chunks (filter-only, ordered)",
                section_id[:80],
                len(results),
            )
            return results
        except Exception as exc:
            logger.warning(
                "[retrieval] Section chunk listing failed for section_id=%r: %s",
                section_id[:80],
                exc,
            )
            return []
