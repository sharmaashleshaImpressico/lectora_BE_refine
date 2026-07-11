from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CAPTION = "caption"


class DocumentNode(BaseModel):
    node_id: str
    block_type: BlockType
    level: int          # heading level 1-6; 0 = body
    text: str
    page_num: int | None = None
    raw_index: int


class DocumentSection(BaseModel):
    section_id: str
    title: str
    level: int
    parent_id: str | None = None
    children: list[str] = []
    nodes: list[DocumentNode] = []
    para_start: int
    para_end: int


class DocumentTree(BaseModel):
    document_id: str
    filename: str
    file_type: str   # "pdf" or "docx"
    total_pages: int
    sections: list[DocumentSection] = []
    flat_nodes: list[DocumentNode] = []


class CourseChunk(BaseModel):
    chunk_id: str
    document_id: str
    section_id: str
    title: str
    level: int
    raw_text: str                       # full verbatim chunk text, stored and retrievable
    token_count: int
    estimated_read_min: float
    source_file: str = ""               # original filename (e.g. "guide.docx")
    page_num: int | None = None         # first page this chunk appears on (PDF only)
    searchable_text: str = ""
    embedding_content: list[float] | None = None
    course_id: str | None = None
    jurisdiction: str | None = None
    source_type: str | None = None
    source_priority: str | None = None
    source_intent: str | None = None
    section_title: str | None = None
    chunk_title: str | None = None
    chunk_index: int | None = None


class IngestionResult(BaseModel):
    document_id: str
    total_sections: int
    total_chunks: int
    status: str = "indexed"
