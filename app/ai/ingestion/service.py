from __future__ import annotations
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from app.ai.ingestion.chunking.models import IngestionResult
from app.ai.ingestion.metadata import IngestionMetadata

logger = logging.getLogger(__name__)

_instance: "IngestionOrchestrator | None" = None
_executor = ThreadPoolExecutor(max_workers=2)


class IngestionOrchestrator:
    """
    Orchestrate the document ingestion pipeline:

        Parse → Chunk → Embed → Index

    Uses a dedicated Azure OpenAI embeddings resource when configured.
    Each step is skipped individually when credentials are missing.
    """

    def __init__(self) -> None:
        from app.core.config import ingestion_settings, llm_pipeline_settings

        self._ingestion = ingestion_settings
        self._llm = llm_pipeline_settings
        self._embeddings_client = self._build_embeddings_client()
        self._search_client = self._build_search_client()
        self._embedder = self._build_embedder()

    def _build_embeddings_client(self):
        from app.ai.ingestion.embedding.embedding_service import build_embeddings_client

        client = build_embeddings_client(
            resource_name=self._ingestion.azure_openai_embeddings_resource_name,
            api_key=self._ingestion.azure_openai_embeddings_key,
        )
        if client is not None:
            return client

        if self._llm.azure_openai_endpoint and self._llm.azure_openai_api_key:
            import openai
            logger.warning(
                "[ingestion] Embeddings resource not configured — falling back to "
                "main Azure OpenAI resource for embedding generation."
            )
            return openai.AsyncAzureOpenAI(
                azure_endpoint=self._llm.azure_openai_endpoint,
                api_key=self._llm.azure_openai_api_key,
                api_version="2024-02-01",
                max_retries=1,
            )

        logger.warning(
            "[ingestion] No embeddings client configured — embedding will be skipped."
        )
        return None

    def _build_search_client(self):
        if not self._ingestion.azure_search_endpoint or not self._ingestion.azure_search_api_key:
            logger.warning(
                "[ingestion] AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_API_KEY not set "
                "— indexing will be skipped."
            )
            return None
        from app.ai.ingestion.storage.azure_search_client import AzureSearchIngestionClient
        return AzureSearchIngestionClient(
            endpoint=self._ingestion.azure_search_endpoint,
            api_key=self._ingestion.azure_search_api_key,
            index_name=self._ingestion.azure_search_index_name,
        )

    def _build_embedder(self):
        if self._embeddings_client is None:
            return None
        from app.ai.ingestion.embedding.embedding_service import ChunkEmbeddingService
        return ChunkEmbeddingService(
            client=self._embeddings_client,
            deployment=self._ingestion.ingestion_embedding_deployment,
        )

    def build_retrieval_service(self):
        """Return a CourseRetrievalService wired to the ingestion index."""
        if not self._ingestion.azure_search_endpoint or not self._ingestion.azure_search_api_key:
            return None
        if self._embeddings_client is None:
            return None
        from app.ai.ingestion.storage.retrieval_service import CourseRetrievalService
        return CourseRetrievalService(
            endpoint=self._ingestion.azure_search_endpoint,
            api_key=self._ingestion.azure_search_api_key,
            index_name=self._ingestion.azure_search_index_name,
            embeddings_client=self._embeddings_client,
            embedding_deployment=self._ingestion.ingestion_embedding_deployment,
        )

    async def ingest(
        self,
        file_path: str,
        document_id: str,
        filename: str,
        metadata: IngestionMetadata | None = None,
    ) -> IngestionResult:
        """
        Run ingestion for a single document.

        Steps (each skipped individually if not configured):
          1. Parse — extract DocumentTree
          2. Chunk — build CourseChunk list with raw_text
          3. Embed — 3072-dim content vector from raw_text
          4. Index — upload to Azure AI Search
        """
        logger.info(
            "[ingestion] Starting: document_id=%s  file=%s", document_id, filename
        )

        from app.ai.ingestion.parsers.structure_extractor import DocumentStructureExtractor
        extractor = DocumentStructureExtractor()
        tree = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: extractor.extract(file_path, document_id, source_filename=filename),
        )
        logger.info(
            "[ingestion] Parsed %d sections, %d nodes",
            len(tree.sections), len(tree.flat_nodes),
        )

        from app.ai.ingestion.chunking.chunk_builder import CourseChunkBuilder
        builder = CourseChunkBuilder()
        resolved_metadata = (metadata or IngestionMetadata.empty()).with_document(
            document_id,
            filename,
        )
        chunks = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: builder.build(tree, resolved_metadata),
        )
        logger.info("[ingestion] Built %d chunks", len(chunks))

        if self._embedder and chunks:
            try:
                chunks = await self._embedder.embed_chunks(chunks)
                logger.info("[ingestion] Embedding complete")
            except Exception as exc:
                logger.error("[ingestion] Embedding failed; aborting ingestion: %s", exc)
                raise
        else:
            logger.info("[ingestion] Skipping embedding (not configured or no chunks)")

        index_result: dict | None = None
        if self._search_client and chunks:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    _executor, self._search_client.ensure_index_exists
                )
                index_result = await asyncio.get_event_loop().run_in_executor(
                    _executor, self._search_client.upload_chunks, chunks
                )
                logger.info("[ingestion] Indexed: %s", index_result)
            except Exception as exc:
                logger.warning("[ingestion] Azure Search upload failed: %s", exc)
                raise
        else:
            logger.info("[ingestion] Skipping indexing (not configured or no chunks)")

        if index_result and index_result.get("succeeded", 0) > 0:
            outcome_status = "indexed"
        elif self._search_client and chunks:
            outcome_status = "failed"
        elif self._search_client:
            outcome_status = "parsed"
        else:
            outcome_status = "parsed"

        outcome = IngestionResult(
            document_id=document_id,
            total_sections=len(tree.sections),
            total_chunks=len(chunks),
            status=outcome_status,
        )
        logger.info(
            "[ingestion] Done: document_id=%s  sections=%d  chunks=%d  status=%s",
            outcome.document_id, outcome.total_sections,
            outcome.total_chunks, outcome.status,
        )
        return outcome

    @classmethod
    def get_instance(cls) -> "IngestionOrchestrator":
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance
