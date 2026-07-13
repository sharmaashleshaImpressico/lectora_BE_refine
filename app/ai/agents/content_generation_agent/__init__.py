"""Content-generation stage agents.

The pure, kernel-based building blocks used by
``app.orchestrators.content_generation.orchestrator.ContentGenerationOrchestrator``:
Section Mapper, A2 content generation, S2 validation, and content refinement.

``pipeline.py``/``lesson_gate.py`` in this package are legacy, file-based, and
tied to a "central orchestrator" framework that no longer exists in this repo
(they still import the removed ``lectora_backend`` package) — they are not
exposed here and are superseded by ``ContentGenerationOrchestrator``.
"""

from __future__ import annotations

from app.ai.agents.content_generation_agent.content_validation import (
    validate_content,
)
from app.ai.agents.content_generation_agent.content_writer_agent.content_refine_agent import (
    refine_sections,
)
from app.ai.agents.content_generation_agent.content_writer_agent.runner import (
    generate_course_content,
    render_study_guide,
)
from app.ai.agents.content_generation_agent.section_mapper.runner import (
    map_sections,
)

__all__ = [
    "generate_course_content",
    "render_study_guide",
    "validate_content",
    "refine_sections",
    "map_sections",
]
