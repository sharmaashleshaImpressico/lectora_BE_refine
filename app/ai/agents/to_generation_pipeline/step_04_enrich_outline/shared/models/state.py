"""A1State — shared LangGraph state definition."""
from typing import Any, Optional
from typing_extensions import TypedDict


class A1State(TypedDict):
    a0_shared_state: dict[str, Any]
    docx_path: str
    run_id: str
    a0_data: dict[str, Any]
    raw_sections: list[dict[str, Any]]
    total_word_count: int
    kc_count: int
    image_map: dict[str, Any]
    enrichment: dict[str, Any]
    course_spec: dict[str, Any]
    inconsistencies: list[dict[str, Any]]
    retry_count: int
    status: str
    error: Optional[str]
    feedback: Optional[dict[str, Any]]
    prefer_a0_outline: bool
