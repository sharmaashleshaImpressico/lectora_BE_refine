"""Image-to-section mapper using heading, text, vector, and paragraph signals."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

from ...nodes.base_node import BaseA1Node
from ...shared.models.state import A1State
from .utils.image_record import to_mapped_image_record
from .utils.resolver import ImageSectionResolver

logger = logging.getLogger(__name__)


class SectionImageMapper(BaseA1Node):
    """Maps source images to A1 sections using multi-strategy matching."""

    def execute(self, state: A1State) -> A1State:
        if state["status"] in ("failed", "stopped"):
            return state

        images: list[dict] = state["a0_data"].get("images", [])
        if not images:
            logger.info("[A1] No images in shared state — skipping image mapping.")
            return {**state, "image_map": {}}

        prefer_a0_outline = bool(state.get("prefer_a0_outline"))
        if prefer_a0_outline:
            source_document = None
            logger.info(
                "[A1] Generate-TO mode — mapping %s images with heading/text/vector signals.",
                len(images),
            )
        else:
            source_document = Path(state["docx_path"]).name
            logger.info(
                "[A1] Mapping %s images with multi-strategy resolver (source=%s)...",
                len(images),
                source_document,
            )

        image_map, strategy_counts = self.map_images_to_sections(
            images,
            state["raw_sections"],
            a0_data=state["a0_data"],
            source_document=source_document,
            para_ranges_estimated=prefer_a0_outline,
        )
        placed = sum(len(value) for key, value in image_map.items() if key != "unassigned")
        logger.info(
            "[A1] Mapped %s/%s images. Unassigned: %s. Strategies: %s",
            placed,
            len(images),
            len(image_map["unassigned"]),
            dict(strategy_counts),
        )
        return {**state, "image_map": image_map}

    @classmethod
    def map_images_to_sections(
        cls,
        images: list[dict],
        sections: list[dict],
        *,
        a0_data: dict[str, Any] | None = None,
        source_document: str | None = None,
        para_ranges_estimated: bool = False,
    ) -> tuple[dict[str, list], Counter[str]]:
        """Map images to sections and return the image map plus strategy counts."""
        a0_data = a0_data or {}
        extracted = a0_data.get("extracted_inputs") or {}
        heading_tree = extracted.get("heading_tree") or []

        resolver = ImageSectionResolver(
            sections,
            heading_tree=heading_tree,
            source_document=source_document,
            para_ranges_estimated=para_ranges_estimated,
        )

        image_map: dict[str, list] = {section["id"]: [] for section in sections}
        image_map["unassigned"] = []
        strategy_counts: Counter[str] = Counter()

        for image in images:
            match = resolver.resolve(image)
            if match is None:
                image_map["unassigned"].append(to_mapped_image_record(image))
                strategy_counts["unassigned"] += 1
                continue

            image_map[match.section_id].append(to_mapped_image_record(image))
            strategy_counts[match.strategy] += 1
            logger.debug(
                "[A1] Image %s -> %s via %s (score=%.2f weighted=%.2f)",
                image.get("id"),
                match.section_id,
                match.strategy,
                match.score,
                match.weighted_score,
            )

        return image_map, strategy_counts


def map_images_to_sections(
    images: list[dict],
    sections: list[dict],
    *,
    source_document: str | None = None,
    a0_data: dict[str, Any] | None = None,
    para_ranges_estimated: bool = False,
) -> dict[str, list]:
    image_map, _ = SectionImageMapper.map_images_to_sections(
        images,
        sections,
        a0_data=a0_data,
        source_document=source_document,
        para_ranges_estimated=para_ranges_estimated,
    )
    return image_map


def map_images(state: A1State) -> A1State:
    return SectionImageMapper().execute(state)
