"""
A0 — Request Synthesizer & Input Normalizer

This module re-exports A0RequestSynthesizer for backward compatibility.
The implementation lives in phases/synthesizer.py.
"""

from .phases.synthesizer import A0RequestSynthesizer  # noqa: F401

__all__ = ["A0RequestSynthesizer"]
