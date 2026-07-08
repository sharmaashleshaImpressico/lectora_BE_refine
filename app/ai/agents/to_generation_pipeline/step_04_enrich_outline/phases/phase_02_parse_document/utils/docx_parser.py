"""Backward-compatibility shim for DocxDocumentParser."""

from ..docx_parser import DocxDocumentParser, parse_docx_document

__all__ = ["DocxDocumentParser", "parse_docx_document"]
