from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..shared.constants.course_titles import GENERIC_COURSE_TITLES
from ..shared.constants.pipeline_config import CLASSIFICATION_CONTENT_SAMPLE_CHARS
from ..shared.helpers.document_titles import DocumentTitleCollector, TitleCleaner
from .base_phase import BasePipelinePhase
from .parse_phase import ParsePhaseResult

if TYPE_CHECKING:
    from .synthesizer import A0RequestSynthesizer

logger = logging.getLogger(__name__)

GENERIC_TITLES = GENERIC_COURSE_TITLES


@dataclass
class ClassificationPhaseResult:
    title: str
    all_doc_titles: list[str]
    rich_classification_sample: str


class ClassificationPhase(BasePipelinePhase):
    """Title extraction and content sampling for downstream classification."""

    def __init__(self, synthesizer: A0RequestSynthesizer, parsed: ParsePhaseResult) -> None:
        super().__init__(synthesizer)
        self._parsed = parsed

    def prepare(self) -> ClassificationPhaseResult:
        parsed = self._parsed
        title_collector = DocumentTitleCollector(
            self._synth.docx_paths,
            self._synth.pdf_paths,
            has_docx_parser=bool(parsed.parser),
            has_pdf_parser=bool(parsed.pdf_parser),
            fallback_title=parsed.title,
        )
        raw_titles = title_collector.collect_raw_titles()
        classify_all_titles = title_collector.collect_clean_titles()
        if not classify_all_titles and parsed.title:
            classify_all_titles = [parsed.title]
        logger.info(
            "[A0] Classification titles (cleaned, %d of %d raw): %s",
            len(classify_all_titles),
            len(raw_titles),
            classify_all_titles,
        )

        title = parsed.title
        if TitleCleaner.is_generic(title) and classify_all_titles:
            title = classify_all_titles[0]
            logger.info("[A0] Primary title upgraded to: %r", title)

        rich_classification_sample = self._build_rich_sample(parsed)

        return ClassificationPhaseResult(
            title=title,
            all_doc_titles=classify_all_titles,
            rich_classification_sample=rich_classification_sample,
        )

    def _build_rich_sample(self, parsed: ParsePhaseResult) -> str:
        classify_parts: list[str] = []
        if parsed.parser:
            sample = parsed.parser.extract_content_sample(
                max_chars=CLASSIFICATION_CONTENT_SAMPLE_CHARS
            )
            if sample:
                classify_parts.append(sample)
        if parsed.pdf_parser:
            sample = parsed.pdf_parser.extract_content_sample(
                max_chars=CLASSIFICATION_CONTENT_SAMPLE_CHARS
            )
            if sample:
                classify_parts.append(sample)
        return "\n\n".join(classify_parts) or parsed.classification_sample
