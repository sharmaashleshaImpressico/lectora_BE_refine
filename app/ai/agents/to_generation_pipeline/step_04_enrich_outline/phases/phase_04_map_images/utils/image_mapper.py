"""Backward-compatibility shim for SectionImageMapper."""

from ..image_mapper import SectionImageMapper, map_images, map_images_to_sections

__all__ = ["SectionImageMapper", "map_images", "map_images_to_sections"]
