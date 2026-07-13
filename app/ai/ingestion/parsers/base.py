from __future__ import annotations
from abc import ABC, abstractmethod
from app.ai.ingestion.chunking.models import DocumentNode


class BaseDocumentParser(ABC):
    @abstractmethod
    def parse(self, path: str) -> list[DocumentNode]:
        ...
