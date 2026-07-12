"""Real course-type rule packs (single source of truth).

One module per rule family; each exposes a ``PACK`` dict. Resolution by
course type / rule family lives in ``rule_pack_config.course_packs``.
"""

from app.ai.rule_pack_config.packs.firm_element import PACK as FIRM_ELEMENT_PACK
from app.ai.rule_pack_config.packs.iarce import PACK as IARCE_PACK
from app.ai.rule_pack_config.packs.insurance_ce import PACK as INSURANCE_CE_PACK

__all__ = ["FIRM_ELEMENT_PACK", "IARCE_PACK", "INSURANCE_CE_PACK"]
