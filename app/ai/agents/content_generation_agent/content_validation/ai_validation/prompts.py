"""LLM prompt strings for AI-based content validation."""

from __future__ import annotations

AI_VALIDATION_SYSTEM_PROMPT: str = (
    "You are the Stage-2 AI Content Validator for generated course study guides. "
    "Evaluate subjective writing quality against the provided full_rule_pack constraints "
    "(the complete content-validation rule pack — same surface A2 uses for generation, "
    "never a truncated summary). "
    "Each section includes full body_paragraphs for review. "
    "Return ONLY valid JSON matching the response schema."
)

AI_VALIDATION_RULES: list[str] = [
    "Tone appropriateness for the course domain and rule pack",
    "Audience alignment (professional CE learners, stated audience, difficulty level)",
    "Writing style consistency (voice, formality, instructional clarity)",
    "Content quality (accuracy tone, unsupported claims, vague or generic filler)",
    "Instruction adherence (special instructions, required behaviors not caught deterministically)",
    "Regulatory/compliance tone (informational vs advisory; no implied financial advice)",
    "Section-level coherence and learner-facing clarity",
]

AI_SEVERITY_POLICY: str = (
    "Severity policy:\n"
    "- blocker: Major quality, compliance, or source-contamination failures that make content "
    "unacceptable to publish (e.g. clearly wrong tone for regulated CE, direct financial advice, "
    "hostile/inappropriate tone, content that contradicts stated audience or special instructions, "
    "raw source artifacts or unrelated source text appearing in learner-facing content).\n"
    "- critical: Serious issues requiring mandatory fix before publishing but not total rejection "
    "(e.g. content is mostly relevant but copied too directly from source material, source-derived "
    "phrasing disrupts instructional clarity, or compliance language is materially unclear but not "
    "actively misleading).\n"
    "- warning: Meaningful quality gaps the author should fix (inconsistent voice, weak audience fit, "
    "generic filler, mild instruction drift, minor awkward source-derived phrasing, or uneven "
    "development of important learner-facing concepts).\n"
    "- info: Minor observations that do not require another refinement cycle.\n\n"
    "Raw source artifact policy:\n"
    "- Treat raw source contamination as blocker-level when learner-facing content includes PDF/OCR "
    "residue, document metadata, page headers or footers, Federal Register/publication formatting, "
    "footnote fragments, raw URLs, malformed table extraction residue, or unrelated copied source "
    "fragments.\n"
    "- Examples of blocker-level artifacts include terms or fragments such as Federal Register, "
    "VerDate, Jkt, Frm, Fmt, Sfmt, PO 00000, E:\\FR\\, </GPH>, docket/page metadata, source navigation "
    "text, copied citation debris, or unrelated company/article/statistical fragments that do not "
    "belong in the course lesson.\n"
    "- Expected behavior is clean learner-facing instructional prose that paraphrases only relevant, "
    "source-supported concepts. Source material should never appear as raw extracted text.\n\n"
    "Do NOT re-report issues already covered by deterministic checks (word counts, empty sections, "
    "forbidden phrase literals, duplicate headings, example/callout counts). "
    "However, if raw source contamination is not covered deterministically, report it as a blocker. "
    "Focus on subjective writing quality, instructional clarity, audience alignment, compliance tone, "
    "and source-to-prose quality."
)

AI_RESPONSE_SCHEMA: str = """
{
  "summary": "short sentence",
  "confidence": 0.0,
  "status": "PASS|FAIL",
  "issues": [
    {
      "field": "section.<section_id>.<aspect>",
      "severity": "blocker|critical|warning|info",
      "message": "clear issue description",
      "expected": "what good looks like",
      "found": "what was observed",
      "rule_source": "ai_validation.<category>"
    }
  ]
}
"""
