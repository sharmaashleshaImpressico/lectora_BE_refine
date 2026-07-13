from __future__ import annotations

from pydantic import BaseModel


class IngestionMetadata(BaseModel):
    """Optional context attached to every chunk during ingestion and indexing."""

    course_id: str | None = None
    document_id: str | None = None
    jurisdiction: str | None = None
    source_file: str | None = None
    source_type: str | None = None
    source_priority: str | None = None
    source_intent: str | None = None

    @classmethod
    def empty(cls) -> IngestionMetadata:
        return cls()

    def with_document(self, document_id: str, source_file: str | None = None) -> IngestionMetadata:
        """Return a copy with document identity filled in when not already set."""
        updates: dict[str, str] = {}
        if not self.document_id:
            updates["document_id"] = document_id
        if source_file and not self.source_file:
            updates["source_file"] = source_file
        if not updates:
            return self
        return self.model_copy(update=updates)

    def apply_to_chunk_fields(self) -> dict[str, str | None]:
        """Return metadata fields to merge onto a CourseChunk."""
        return {
            "course_id": self.course_id,
            "jurisdiction": self.jurisdiction,
            "source_type": self.source_type,
            "source_priority": self.source_priority,
            "source_intent": self.source_intent,
        }


def build_ingestion_metadata(
    *,
    course_id: str | None = None,
    document_id: str | None = None,
    jurisdiction: str | None = None,
    source_file: str | None = None,
    source_type: str | None = None,
    source_priority: str | None = None,
    source_intent: str | None = None,
) -> IngestionMetadata | None:
    """Build metadata from optional upload fields; returns None when all are empty."""
    metadata = IngestionMetadata(
        course_id=_normalize_optional(course_id),
        document_id=_normalize_optional(document_id),
        jurisdiction=_normalize_optional(jurisdiction),
        source_file=_normalize_optional(source_file),
        source_type=_normalize_optional(source_type),
        source_priority=_normalize_optional(source_priority),
        source_intent=_normalize_optional(source_intent),
    )
    if metadata == IngestionMetadata.empty():
        return None
    return metadata


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
