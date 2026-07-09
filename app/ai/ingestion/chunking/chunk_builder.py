from __future__ import annotations
import logging

from app.ai.ingestion.chunking.models import (
    BlockType,
    CourseChunk,
    DocumentSection,
    DocumentTree,
)
from app.ai.ingestion.metadata import IngestionMetadata

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 2500
_DEFAULT_MIN_TOKENS = 80
MAX_TOKENS = _DEFAULT_MAX_TOKENS
MIN_TOKENS = _DEFAULT_MIN_TOKENS
_WORDS_PER_MINUTE = 200


def _chunk_token_limits() -> tuple[int, int]:
    from app.core.config import ingestion_settings

    max_tokens = int(ingestion_settings.ingestion_max_chunk_tokens or _DEFAULT_MAX_TOKENS)
    min_tokens = int(ingestion_settings.ingestion_min_chunk_tokens or _DEFAULT_MIN_TOKENS)
    return max(80, max_tokens), max(1, min_tokens)


def _get_encoder():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        logger.warning(
            "[chunk_builder] tiktoken not available — falling back to word-count approximation "
            "(1 token ≈ 0.75 words). Install tiktoken for accurate counts."
        )
        return None


def _count_tokens(text: str, encoder) -> int:
    if encoder is None:
        # Approx: GPT tokeniser averages ~0.75 words per token → 1.33 tokens per word
        return max(1, round(len(text.split()) * 1.33))
    return len(encoder.encode(text))


def _estimated_read_min(token_count: int) -> float:
    words = token_count * 0.75
    return round(words / _WORDS_PER_MINUTE, 2)


def _first_page(section: DocumentSection) -> int | None:
    """Return the page number of the first node in the section, if available."""
    for node in section.nodes:
        if node.page_num is not None:
            return node.page_num
    return None


def _chunk_title(section_title: str, seq: int) -> str:
    if seq == 0:
        return section_title
    return f"{section_title} (part {seq + 1})"


class CourseChunkBuilder:
    """Build CourseChunk objects from a DocumentTree."""

    def __init__(self) -> None:
        self._encoder = _get_encoder()

    def build(
        self,
        tree: DocumentTree,
        metadata: IngestionMetadata | None = None,
    ) -> list[CourseChunk]:
        resolved_metadata = (metadata or IngestionMetadata.empty()).with_document(
            tree.document_id,
            tree.filename,
        )
        chunks: list[CourseChunk] = []
        for section in tree.sections:
            section_chunks = self._chunk_section(
                section,
                tree.document_id,
                tree.filename,
                resolved_metadata,
            )
            chunks.extend(section_chunks)
        logger.info(
            "[chunk_builder] Built %d chunks from document %s",
            len(chunks),
            tree.document_id,
        )
        return chunks

    def _chunk_section(
        self,
        section: DocumentSection,
        document_id: str,
        source_file: str,
        metadata: IngestionMetadata,
    ) -> list[CourseChunk]:
        max_tokens, min_tokens = _chunk_token_limits()
        body_nodes = [
            n for n in section.nodes
            if not (n.block_type == BlockType.HEADING and n.level > 0)
        ]

        if not body_nodes:
            return []

        full_content = "\n\n".join(n.text for n in body_nodes)
        total_tokens = _count_tokens(full_content, self._encoder)

        if total_tokens < min_tokens:
            return []

        if total_tokens <= max_tokens:
            return [
                self._make_chunk(
                    document_id,
                    section,
                    full_content,
                    0,
                    source_file,
                    metadata,
                )
            ]

        chunks: list[CourseChunk] = []
        current_texts: list[str] = []
        current_tokens = 0
        seq = 0

        for node in body_nodes:
            node_tokens = _count_tokens(node.text, self._encoder)

            if current_tokens + node_tokens > max_tokens and current_texts:
                raw_text = "\n\n".join(current_texts)
                if _count_tokens(raw_text, self._encoder) >= min_tokens:
                    chunks.append(
                        self._make_chunk(
                            document_id,
                            section,
                            raw_text,
                            seq,
                            source_file,
                            metadata,
                        )
                    )
                    seq += 1
                current_texts = [node.text]
                current_tokens = node_tokens
            else:
                current_texts.append(node.text)
                current_tokens += node_tokens

        if current_texts:
            raw_text = "\n\n".join(current_texts)
            if _count_tokens(raw_text, self._encoder) >= min_tokens:
                chunks.append(
                    self._make_chunk(
                        document_id,
                        section,
                        raw_text,
                        seq,
                        source_file,
                        metadata,
                    )
                )

        return chunks

    def _make_chunk(
        self,
        document_id: str,
        section: DocumentSection,
        raw_text: str,
        seq: int,
        source_file: str,
        metadata: IngestionMetadata,
    ) -> CourseChunk:
        token_count = _count_tokens(raw_text, self._encoder)
        chunk_id = f"chunk_{document_id}_{section.section_id}_{seq:03d}"
        section_title = section.title
        chunk_title = _chunk_title(section_title, seq)
        resolved_source_file = metadata.source_file or source_file
        searchable_text = f"{section_title} {resolved_source_file} {raw_text[:500]}"

        return CourseChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            section_id=section.section_id,
            title=section_title,
            level=section.level,
            raw_text=raw_text,
            token_count=token_count,
            estimated_read_min=_estimated_read_min(token_count),
            source_file=resolved_source_file,
            page_num=_first_page(section),
            searchable_text=searchable_text,
            section_title=section_title,
            chunk_title=chunk_title,
            chunk_index=seq,
            **metadata.apply_to_chunk_fields(),
        )
