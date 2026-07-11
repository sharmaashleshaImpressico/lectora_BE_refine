from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.ai.shared_utils.image_validation import filter_stored_image_records
from ..parse_documents.utils.doc_parser import CourseDocParser
from ..parse_documents.utils.pdf_parser import PDFSourceParser
from ..shared.constants.pipeline_config import (
    DEFAULT_COURSE_TITLE,
    DEFAULT_SOURCE_LABEL,
    PARSE_CONTENT_SAMPLE_CHARS,
)
from .base_phase import BasePipelinePhase

if TYPE_CHECKING:
    from .synthesizer import A0RequestSynthesizer

logger = logging.getLogger(__name__)


@dataclass
class ParsePhaseResult:
    parser: Any
    pdf_parser: Any
    title: str
    course_id: str | None
    learning_objectives: list[str]
    content_sample: str
    classification_sample: str
    to_outline_content: str
    total_doc_word_count: int
    total_paragraphs: int
    heading_map: list[tuple[int, str, int, str]]
    heading_tree: list[dict]
    pdf_heading_tree: list[dict]
    images: list[dict]
    to_is_json: bool


def _build_heading_map_from_heading_tree(
    heading_tree: list[dict],
) -> list[tuple[int, str, int, str]]:
    return [
        (
            int(entry["para_idx"]),
            str(entry["text"]),
            int(entry["level"]),
            str(entry.get("source") or DEFAULT_SOURCE_LABEL),
        )
        for entry in heading_tree
        if entry.get("para_idx") is not None and entry.get("text")
    ]


class ParsePhase(BasePipelinePhase):
    """Document loading, structure extraction, and image harvest for A0."""

    def execute(self) -> ParsePhaseResult:
        synth = self._synth
        has_pdf_text = bool(synth.extra_text_contents)
        synth._emit_step("Loading source documents and extracting structure…")
        logger.info(
            "[A0] Parsing %s DOCX source(s), %s PDF source(s)%s...",
            len(synth.docx_paths),
            len(synth.pdf_paths),
            f" + {len(synth.extra_text_contents)} PDF text block(s)" if has_pdf_text else "",
        )

        to_is_json = (
            synth.to_outline_doc_path is not None
            and synth.to_outline_doc_path.lower().endswith(".json")
        )
        to_is_pdf = (
            synth.to_outline_doc_path is not None
            and synth.to_outline_doc_path.lower().endswith(".pdf")
        )
        parser = (
            CourseDocParser(
                docx_paths=synth.docx_paths,
                to_outline_doc_path=None if (to_is_json or to_is_pdf) else synth.to_outline_doc_path,
            )
            if synth.docx_paths
            else None
        )
        pdf_parser = PDFSourceParser(synth.pdf_paths) if synth.pdf_paths else None
        to_outline_pdf_parser = (
            PDFSourceParser([synth.to_outline_doc_path]) if to_is_pdf and synth.to_outline_doc_path else None
        )

        title = (
            (parser.extract_title() if parser else "")
            or (pdf_parser.extract_title() if pdf_parser else "")
            or DEFAULT_COURSE_TITLE
        )
        course_id = (
            (parser.extract_course_id() if parser else None)
            or (pdf_parser.extract_course_id() if pdf_parser else None)
        )

        learning_objectives: list[str] = []
        seen_objectives: set[str] = set()
        for items in (
            parser.extract_merged_learning_objectives() if parser else [],
            pdf_parser.extract_merged_learning_objectives() if pdf_parser else [],
        ):
            for obj in items:
                key = obj.lower()
                if key not in seen_objectives:
                    learning_objectives.append(obj)
                    seen_objectives.add(key)

        classification_parts: list[str] = []
        if parser:
            sample = parser.extract_content_sample(max_chars=PARSE_CONTENT_SAMPLE_CHARS)
            if sample:
                classification_parts.append(sample)
        if pdf_parser:
            sample = pdf_parser.extract_content_sample(max_chars=PARSE_CONTENT_SAMPLE_CHARS)
            if sample:
                classification_parts.append(sample)
        classification_sample = "\n\n".join(classification_parts)
        content_sample = classification_sample[:PARSE_CONTENT_SAMPLE_CHARS]

        to_outline_content = self._extract_to_outline_content(
            parser, to_outline_pdf_parser, to_is_json
        )

        total_doc_word_count = (
            (parser.count_total_doc_words() if parser else 0)
            + (pdf_parser.count_total_doc_words() if pdf_parser else 0)
        )
        logger.info("[A0] Source doc word count: %s", total_doc_word_count)

        total_paragraphs = 0
        if parser:
            total_paragraphs += parser.count_paragraphs()
        if pdf_parser:
            total_paragraphs += pdf_parser.count_paragraphs()

        self._log_to_mode(to_is_json)

        heading_map: list[tuple[int, str, int, str]] = []
        if parser:
            heading_map.extend(parser.get_section_heading_map())
        pdf_heading_tree = pdf_parser.extract_merged_heading_tree() if pdf_parser else []
        if pdf_parser:
            heading_map.extend(_build_heading_map_from_heading_tree(pdf_heading_tree))
        logger.info("[A0] Heading anchors across sources: %s", len(heading_map))

        heading_tree: list[dict] = []
        seen_headings: set[tuple[str, str]] = set()
        for tree in [
            *(parser.extract_merged_heading_tree() if parser else []),
            *pdf_heading_tree,
        ]:
            source = str(tree.get("source") or "")
            key = (source, str(tree["text"]).lower())
            if key in seen_headings:
                continue
            heading_tree.append(tree)
            seen_headings.add(key)
        logger.info("[A0] Heading tree entries: %s", len(heading_tree))

        self._log_extraction_summary(parser, pdf_parser, heading_tree, pdf_heading_tree)
        self._debug_print_parse_summary(
            title, total_doc_word_count, total_paragraphs, heading_tree, to_outline_content,
        )

        synth._check_cancelled()
        images = self._extract_images(parser, pdf_parser, pdf_heading_tree)

        return ParsePhaseResult(
            parser=parser,
            pdf_parser=pdf_parser,
            title=title,
            course_id=course_id,
            learning_objectives=learning_objectives,
            content_sample=content_sample,
            classification_sample=classification_sample,
            to_outline_content=to_outline_content,
            total_doc_word_count=total_doc_word_count,
            total_paragraphs=total_paragraphs,
            heading_map=heading_map,
            heading_tree=heading_tree,
            pdf_heading_tree=pdf_heading_tree,
            images=images,
            to_is_json=to_is_json,
        )

    @staticmethod
    def build_paragraphs_by_source(parsed: ParsePhaseResult) -> dict[str, int]:
        """Return paragraph counts keyed by source filename."""
        paragraphs_by_source: dict[str, int] = {}
        if parsed.parser:
            paragraphs_by_source.update(
                {path.name: len(doc.paragraphs) for path, doc in parsed.parser._sources}
            )
        if parsed.pdf_parser:
            paragraphs_by_source.update(parsed.pdf_parser.paragraphs_by_source())
        return paragraphs_by_source

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_to_outline_content(
        self,
        parser: Any,
        to_outline_pdf_parser: Any,
        to_is_json: bool,
    ) -> str:
        synth = self._synth
        if not synth.to_outline_doc_path or to_is_json:
            return ""
        to_outline_content = (
            to_outline_pdf_parser.extract_to_outline_text()
            if to_outline_pdf_parser
            else (parser.extract_to_outline_text() if parser else "")
        )
        to_word_count = len(to_outline_content.split())
        logger.info(
            "[A0] TO document extracted: %d words from %s",
            to_word_count,
            Path(synth.to_outline_doc_path).name,
        )
        if not to_outline_content.strip():
            logger.warning(
                "[A0] WARNING — TO document %r extracted to empty string. "
                "The file may use text boxes, SmartArt, or non-paragraph content "
                "that python-docx cannot read. LLM will receive no TO content.",
                Path(synth.to_outline_doc_path).name,
            )
        return to_outline_content

    def _log_to_mode(self, to_is_json: bool) -> None:
        synth = self._synth
        if to_is_json:
            logger.info(
                "[TO MODE] Existing TO detected (pre-generated JSON: %s) — "
                "will load directly from disk, no LLM TO call needed.",
                synth.to_outline_doc_path,
            )
        elif synth.to_outline_doc_path:
            logger.info(
                "[TO MODE] Existing TO detected (%s) — continuing with detected TO.",
                Path(synth.to_outline_doc_path).name,
            )
        else:
            logger.info(
                "[STRUCTURED CONTENT MODE] TO not found — extracted headings and indexed "
                "content will be sent to LLM (DOCX: heading_tree + indexed paragraphs; "
                "PDF: TOC entries + section content) "
                "(duration=%sh, difficulty=%s, target_words=%d).",
                synth.duration_hours,
                synth.difficulty_level,
                synth.calculated_word_count,
            )

    def _log_extraction_summary(
        self,
        parser: Any,
        pdf_parser: Any,
        heading_tree: list[dict],
        pdf_heading_tree: list[dict],
    ) -> None:
        logger.info("[EXTRACT] ══════════════ SOURCE EXTRACTION SUMMARY ══════════════")
        if parser:
            docx_headings = [h for h in heading_tree if not str(h.get("source", "")).lower().endswith(".pdf")]
            logger.info(
                "[EXTRACT]  DOCX  → %d headings extracted",
                len(docx_headings),
            )
            if docx_headings:
                logger.info("[EXTRACT]  ── DOCX titles ──────────────────────────────────")
                for h in docx_headings:
                    indent = "  " * max(0, int(h.get("level", 1)) - 1)
                    logger.info(
                        "[EXTRACT]     [L%s] %s%s",
                        h.get("level", "?"),
                        indent,
                        h.get("text", ""),
                    )
        else:
            logger.info("[EXTRACT]  DOCX  → (not provided)")

        if pdf_parser:
            pdf_headings = [h for h in heading_tree if str(h.get("source", "")).lower().endswith(".pdf")]
            if not pdf_headings:
                pdf_headings = pdf_heading_tree
            logger.info(
                "[EXTRACT]  PDF   → %d headings/TOC entries",
                len(pdf_headings),
            )
            if pdf_headings:
                logger.info("[EXTRACT]  ── PDF TOC / headings ─────────────────────────────")
                for h in pdf_headings:
                    indent = "  " * max(0, int(h.get("level", 1)) - 1)
                    logger.info(
                        "[EXTRACT]     [L%s] %s%s",
                        h.get("level", "?"),
                        indent,
                        h.get("text", ""),
                    )
        else:
            logger.info("[EXTRACT]  PDF   → (not provided)")

        logger.info(
            "[EXTRACT]  COMBINED → %d source(s)",
            (1 if parser else 0) + (1 if pdf_parser else 0),
        )
        logger.info("[EXTRACT] ══════════════════════════════════════════════════════════")

    def _debug_print_parse_summary(
        self,
        title: str,
        total_doc_word_count: int,
        total_paragraphs: int,
        heading_tree: list[dict],
        to_outline_content: str,
    ) -> None:
        synth = self._synth
        print("\n" + "=" * 80, flush=True)
        print("[TO-DEBUG] parse_phase — extracted file data for TO", flush=True)
        print("=" * 80, flush=True)
        print(f"  docx_paths ({len(synth.docx_paths)}):", flush=True)
        for p in synth.docx_paths:
            print(f"    - {p}", flush=True)
        print(f"  pdf_paths ({len(synth.pdf_paths)}):", flush=True)
        for p in synth.pdf_paths:
            print(f"    - {p}", flush=True)
        print(f"  to_outline_doc : {synth.to_outline_doc_path or '(none — will GENERATE TO)'}", flush=True)
        print(f"  title          : {title}", flush=True)
        print(f"  total_words    : {total_doc_word_count:,}", flush=True)
        print(f"  paragraphs     : {total_paragraphs:,}", flush=True)
        print(f"  headings       : {len(heading_tree)}", flush=True)
        if to_outline_content:
            print(f"  to_outline_words: {len(to_outline_content.split()):,}", flush=True)
        print("=" * 80, flush=True)
        if to_outline_content:
            preview = to_outline_content[:8_000]
            print("\n[TO-DEBUG] to_outline_content preview (first 8000 chars):", flush=True)
            print(preview, flush=True)
            if len(to_outline_content) > 8_000:
                print(
                    f"\n[TO-DEBUG] ... to_outline_content truncated ({8_000:,} / {len(to_outline_content):,} chars) ...",
                    flush=True,
                )
        print("=" * 80 + "\n", flush=True)

    def _extract_images(
        self,
        parser: Any,
        pdf_parser: Any,
        pdf_heading_tree: list[dict],
    ) -> list[dict]:
        synth = self._synth
        images: list[dict] = []
        synth._emit_step("Extracting source images and preparing prompts…")
        logger.info("[A0] Image extraction is disabled — skipping.")
        # Image extraction is intentionally disabled for this pipeline.
        # The extractors themselves are commented out in:
        #   - doc_parser.DocParser.extract_all_images() (DOCX, reads word/media/* via zipfile)
        #   - pdf_parser.PDFParser.extract_all_images() (PDF, reads embedded images via pypdf)
        # if parser:
        #     images.extend(parser.extract_all_images(images_dir))
        # if pdf_parser:
        #     images.extend(
        #         pdf_parser.extract_all_images(
        #             images_dir,
        #             start_seq=len(images),
        #             heading_anchors=pdf_heading_tree if pdf_heading_tree else None,
        #         )
        #     )
        images = filter_stored_image_records(images)
        logger.info("[A0] Retained %s valid image record(s) after validation.", len(images))
        return images
