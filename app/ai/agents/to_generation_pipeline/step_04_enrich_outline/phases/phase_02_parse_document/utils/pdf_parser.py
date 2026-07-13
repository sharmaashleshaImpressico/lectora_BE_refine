"""Backward-compatibility shim for PdfSectionParser."""

from ..pdf_parser import PdfSectionParser, _append_section_body

_parser = PdfSectionParser()


def _build_para_map_from_pdf(pdf_path: str) -> dict[int, str]:
    return _parser.build_paragraph_map(pdf_path)


def _parse_pdf_sections_from_shared_state(
    a0_data: dict,
    pdf_path: str,
) -> tuple[list[dict], int, int]:
    return _parser.parse_from_shared_state(
        a0_data,
        pdf_path,
        build_paragraph_map=_build_para_map_from_pdf,
    )


__all__ = [
    "PdfSectionParser",
    "_append_section_body",
    "_build_para_map_from_pdf",
    "_parse_pdf_sections_from_shared_state",
]
