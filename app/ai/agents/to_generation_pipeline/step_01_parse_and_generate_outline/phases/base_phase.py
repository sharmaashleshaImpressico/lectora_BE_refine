"""Base class for sequential pipeline phases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .synthesizer import A0RequestSynthesizer


class BasePipelinePhase:
    """Provides common access to the synthesizer coordinator."""

    def __init__(self, synthesizer: A0RequestSynthesizer) -> None:
        self._synth = synthesizer

    def _check_cancelled(self) -> None:
        self._synth._check_cancelled()

    def _emit_step(self, message: str, *, level: str = "info", stage: str = "A0") -> None:
        self._synth._emit_step(message, level=level, stage=stage)
