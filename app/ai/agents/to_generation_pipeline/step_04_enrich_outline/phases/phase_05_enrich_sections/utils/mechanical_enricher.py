"""Backward-compatibility shim for MechanicalSectionEnricher."""

from ..mechanical_enricher import (
    MechanicalSectionEnricher,
    build_mechanical_enrichment,
    derive_maps_to_objectives,
)

__all__ = [
    "MechanicalSectionEnricher",
    "build_mechanical_enrichment",
    "derive_maps_to_objectives",
]
