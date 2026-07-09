from __future__ import annotations
import logging
import subprocess
import uuid

from app.ai.ingestion.chunking.models import BlockType, DocumentNode
from app.ai.ingestion.parsers.base import BaseDocumentParser

logger = logging.getLogger(__name__)

_A0_PDF_PARSER = (
    "app.ai.agents.to_generation_pipeline.step_01_parse_and_generate_outline"
    ".parse_documents.utils.pdf_parser"
)

# Pages with fewer characters than this are treated as low-yield (extraction likely failed).
_MIN_CHARS_PER_PAGE = 20

# If this fraction of pages are low-yield, trigger the pdftotext whole-doc fallback.
_LOW_YIELD_FRACTION_THRESHOLD = 0.5


def _infer_heading_level(line: str, numbered_re, all_caps_re) -> int | None:
    """
    Return heading level 1–3 using the same heuristics as A0's PDFSourceParser,
    or None for plain body text.
    """
    stripped = line.strip()
    if not stripped:
        return None

    words = stripped.split()
    word_count = len(words)

    if all_caps_re.match(stripped) and word_count < 12:
        return 1

    m = numbered_re.match(stripped)
    if m:
        first_token = stripped.split()[0].rstrip(".")
        dots = first_token.count(".")
        return min(dots + 1, 3)

    if word_count < 8 and stripped[-1] not in ".!?,;:":
        return 2

    return None


def _extract_page_plain(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def _extract_page_layout(page) -> str:
    """pypdf layout mode — better for columnar/XObject-heavy pages."""
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception:
        return ""


def _extract_doc_pdftotext(path: str) -> list[str]:
    """
    Use pdftotext (poppler) to extract text from the whole document.

    Returns a list of page texts (split by form-feed \\f).
    Returns an empty list when pdftotext is unavailable or fails.

    Handles XObjects, WinAnsiEncoding, and non-standard content streams that
    pypdf cannot parse.
    """
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            logger.warning("[pdf_parser] pdftotext exited %d: %s",
                           result.returncode, stderr)
            return []
        full_text = result.stdout.decode("utf-8", errors="replace")
        return full_text.split("\f")
    except FileNotFoundError:
        logger.warning(
            "[pdf_parser] pdftotext not found — poppler is not installed.")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("[pdf_parser] pdftotext timed out for %s", path)
        return []
    except OSError as exc:
        logger.warning("[pdf_parser] pdftotext OS error for %s: %s", path, exc)
        return []


def _page_text_to_nodes(
    text: str,
    page_num: int,
    raw_index: int,
    numbered_re,
    all_caps_re,
) -> tuple[list[DocumentNode], int]:
    """
    Convert raw page text into DocumentNode objects.

    Returns (nodes, next_raw_index). raw_index is incremented for every line
    (empty or not) to maintain positional parity with the source document.
    """
    nodes: list[DocumentNode] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            raw_index += 1
            continue
        heading_level = _infer_heading_level(
            stripped, numbered_re, all_caps_re)
        nodes.append(DocumentNode(
            node_id=uuid.uuid4().hex[:12],
            block_type=BlockType.HEADING if heading_level else BlockType.PARAGRAPH,
            level=heading_level or 0,
            text=stripped,
            page_num=page_num,
            raw_index=raw_index,
        ))
        raw_index += 1
    return nodes, raw_index


class PDFParser(BaseDocumentParser):
    """
    Parse a PDF into DocumentNode objects using a three-tier extraction strategy:

    Tier 1 — pypdf plain mode (fast; works for well-formed PDFs)
    Tier 2 — pypdf layout mode (per-page fallback; better for columnar / XObject pages)
    Tier 3 — pdftotext / poppler (whole-doc fallback; handles WinAnsiEncoding,
              non-standard content streams, and form XObjects that pypdf cannot parse)

    If all tiers yield no text (e.g. scanned / image-only PDF), logs a clear warning
    rather than silently producing zero chunks.
    """

    def parse(self, path: str) -> list[DocumentNode]:
        from importlib import import_module
        from pypdf import PdfReader

        a0_pdf = import_module(_A0_PDF_PARSER)
        numbered_re = a0_pdf._NUMBERED_HEADING_RE
        all_caps_re = a0_pdf._ALL_CAPS_RE

        try:
            reader = PdfReader(path, strict=False)
        except Exception as exc:
            logger.warning("[pdf_parser] Cannot open PDF %s: %s", path, exc)
            return []

        total_pages = len(reader.pages)
        nodes: list[DocumentNode] = []
        raw_index = 0
        low_yield_page_count = 0

        for page_num, page in enumerate(reader.pages, start=1):
            # Tier 1: plain mode
            text = _extract_page_plain(page)

            # Tier 2: layout fallback if plain yielded little text
            if len(text.strip()) < _MIN_CHARS_PER_PAGE:
                layout_text = _extract_page_layout(page)
                if len(layout_text.strip()) > len(text.strip()):
                    text = layout_text
                    logger.debug(
                        "[pdf_parser] Page %d: layout mode recovered %d chars",
                        page_num, len(layout_text.strip()),
                    )

            if len(text.strip()) < _MIN_CHARS_PER_PAGE:
                low_yield_page_count += 1

            page_nodes, raw_index = _page_text_to_nodes(
                text, page_num, raw_index, numbered_re, all_caps_re
            )
            nodes.extend(page_nodes)

        # Tier 3: whole-doc pdftotext fallback when most pages have low yield
        low_yield_fraction = low_yield_page_count / total_pages if total_pages else 0
        if low_yield_fraction >= _LOW_YIELD_FRACTION_THRESHOLD:
            logger.warning(
                "[pdf_parser] pypdf extracted <20 chars on %d/%d pages (%.0f%%) for %s "
                "— likely XObjects / WinAnsiEncoding / non-standard content streams. "
                "Falling back to pdftotext.",
                low_yield_page_count, total_pages, low_yield_fraction * 100, path,
            )
            pdftotext_pages = _extract_doc_pdftotext(path)
            if pdftotext_pages:
                nodes = []
                raw_index = 0
                for page_num, page_text in enumerate(pdftotext_pages, start=1):
                    page_nodes, raw_index = _page_text_to_nodes(
                        page_text, page_num, raw_index, numbered_re, all_caps_re
                    )
                    nodes.extend(page_nodes)
                logger.info(
                    "[pdf_parser] pdftotext fallback produced %d nodes from %s",
                    len(nodes), path,
                )
            else:
                logger.warning(
                    "[pdf_parser] All extraction tiers failed for %s. "
                    "The PDF may be scanned / image-only — no text can be extracted without OCR.",
                    path,
                )

        logger.info(
            "[pdf_parser] Parsed %d nodes from %s (%d pages)",
            len(nodes), path, total_pages,
        )
        return nodes
