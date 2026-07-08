"""Backward-compatibility shim for SectionEnricher."""

from ..section_enricher import SectionEnricher, enrich_with_llm

__all__ = ["SectionEnricher", "enrich_with_llm"]
