from __future__ import annotations
import logging
import time

from app.ai.ingestion.chunking.models import CourseChunk
from app.shared_llm_config.tracer import (
    EmbeddingTrace,
    write_embedding_trace,
)

logger = logging.getLogger(__name__)

_DIMENSIONS = 3072
_BATCH_SIZE = 16
_MAX_CONTENT_CHARS = 8000


def build_embeddings_client(resource_name: str, api_key: str):
    """
    Build a dedicated AsyncAzureOpenAI client for the embeddings resource.

    Returns None if either credential is missing.
    """
    import openai

    if not resource_name or not api_key:
        logger.warning(
            "[embedding_service] AZURE_OPENAI_EMBEDDINGS_RESOURCE_NAME or "
            "AZURE_OPENAI_EMBEDDINGS_KEY is not set — embedding will be skipped."
        )
        return None

    endpoint = f"https://{resource_name.strip()}.openai.azure.com/"
    logger.info("[embedding_service] Embeddings client → %s", endpoint)
    return openai.AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version="2024-02-01",
        max_retries=1,
    )


class ChunkEmbeddingService:
    """Embed CourseChunk.raw_text into a single content vector per chunk."""

    def __init__(self, client, deployment: str) -> None:
        self._client = client
        self._deployment = deployment
        self._endpoint_reachable: bool | None = None

    async def embed_chunks(self, chunks: list[CourseChunk]) -> list[CourseChunk]:
        """Generate one embedding_content vector per chunk."""
        if not chunks:
            return chunks

        document_id: str | None = chunks[0].document_id if chunks else None
        source_file: str | None = chunks[0].source_file if chunks else None
        source_refs = [source_file] if source_file else []

        content_texts = [c.raw_text[:_MAX_CONTENT_CHARS] for c in chunks]
        content_embs = await self._embed_all(
            content_texts, level="content", document_id=document_id, source_refs=source_refs
        )
        if self._endpoint_reachable is False:
            raise RuntimeError(
                "Embeddings endpoint unreachable — refusing to continue without chunk embeddings."
            )

        missing_count = sum(1 for embedding in content_embs if not embedding)
        wrong_dims = sorted({len(embedding) for embedding in content_embs if embedding and len(embedding) != _DIMENSIONS})
        if missing_count or wrong_dims or len(content_embs) != len(chunks):
            logger.error(
                "[embedding_service] Invalid embedding batch "
                "(document_id=%s chunks=%d embeddings=%d missing=%d wrong_dims=%s deployment=%s)",
                document_id,
                len(chunks),
                len(content_embs),
                missing_count,
                wrong_dims,
                self._deployment,
            )
            raise RuntimeError(
                "Embedding generation incomplete or dimension-mismatched; aborting indexing."
            )

        enriched: list[CourseChunk] = []
        for i, chunk in enumerate(chunks):
            enriched.append(chunk.model_copy(update={
                "embedding_content": content_embs[i] if i < len(content_embs) else None,
            }))

        logger.info(
            "[embedding_service] Embedded %d chunks "
            "(document_id=%s deployment=%s dims=%d)",
            len(enriched),
            document_id,
            self._deployment,
            _DIMENSIONS,
        )
        return enriched

    async def _embed_all(
        self,
        texts: list[str],
        level: str = "",
        document_id: str | None = None,
        source_refs: list[str] | None = None,
    ) -> list[list[float]]:
        """Call the embeddings API in batches."""
        all_embeddings: list[list[float]] = []
        batch_index = 0
        for i in range(0, len(texts), _BATCH_SIZE):
            if self._endpoint_reachable is False:
                all_embeddings.extend([] for _ in texts[i : i + _BATCH_SIZE])
                batch_index += 1
                continue
            batch = texts[i : i + _BATCH_SIZE]
            t_start = time.perf_counter()
            error_msg: str | None = None
            total_tokens = 0
            try:
                response = await self._client.embeddings.create(
                    model=self._deployment,
                    input=batch,
                    dimensions=_DIMENSIONS,
                )
                self._endpoint_reachable = True
                if getattr(response, "usage", None):
                    total_tokens = response.usage.total_tokens or 0
                sorted_data = sorted(response.data, key=lambda item: item.index)
                all_embeddings.extend(item.embedding for item in sorted_data)
                logger.debug(
                    "[embedding_service] Batch %d/%s ok (batch_size=%d tokens=%d deployment=%s)",
                    batch_index,
                    level,
                    len(batch),
                    total_tokens,
                    self._deployment,
                )
            except Exception as exc:
                error_msg = str(exc)
                exc_lower = error_msg.lower()
                is_connection_error = "connection" in exc_lower or "connect" in exc_lower
                if is_connection_error and self._endpoint_reachable is None:
                    self._endpoint_reachable = False
                logger.warning(
                    "[embedding_service] Batch %d/%s failed: %s", i, level, exc
                )
                all_embeddings.extend([] for _ in batch)
            finally:
                latency_ms = (time.perf_counter() - t_start) * 1000
                try:
                    write_embedding_trace(EmbeddingTrace(
                        agent="INGEST_EMBED",
                        deployment=self._deployment,
                        level=level,
                        batch_index=batch_index,
                        batch_size=len(batch),
                        dimensions=_DIMENSIONS,
                        latency_ms=latency_ms,
                        total_tokens=total_tokens,
                        error=error_msg,
                        document_id=document_id,
                        source_refs=source_refs or [],
                        run_id=f"ingest:{document_id}" if document_id else "",
                        doc_name=document_id or "ingestion",
                    ))
                except Exception:
                    pass

            if self._endpoint_reachable is False:
                remaining = texts[i + _BATCH_SIZE :]
                all_embeddings.extend([] for _ in remaining)
                break
            batch_index += 1
        return all_embeddings
