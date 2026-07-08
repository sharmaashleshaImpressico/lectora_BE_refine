"""S1 — Stage 1 Validator: structural validation before content generation.

Layout:
  orchestrator/           — validation workflow (S1Validator)
  to_validation_check/    — TO outline checks (deterministic + AI)
  repair_outline_check/   — enriched A1 course_spec checks
  constants/              — prompts, thresholds, NAIC values
"""

from .main import S1Validator

__all__ = ["S1Validator"]
