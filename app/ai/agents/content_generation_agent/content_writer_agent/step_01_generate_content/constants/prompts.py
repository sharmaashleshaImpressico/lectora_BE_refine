"""
Prompts for A2 — Content Generator.

Lesson-level generation: subtopics are sent in one or more LLM calls when a
lesson is large (batched); each response is a JSON array — one element per
subtopic, in order.

The active rule pack is injected as a filtered content-writing view via
``full_rule_pack`` (see ``rule_pack_config.prompt_bundle``).
"""

from __future__ import annotations

import json

from app.ai.rule_pack_config.prompt_bundle import bundle_rule_pack_for_prompt


def _build_teaching_style_section(rule_pack: dict, audience: str = "") -> str:
    """Build the mandatory instructor-style teaching block, enhanced with rule-pack specifics."""
    style = rule_pack.get("style_constraints") or {}
    content = rule_pack.get("content_rules") or {}
    labels = style.get("instructional_emphasis_labels") or []
    scenarios = style.get("require_scenario_based_examples")
    transitions = style.get("require_transition_sentences")
    ex_range = content.get("require_examples_per_section")
    callout_range = content.get("require_callouts_per_section")

    audience_line = f"- Audience: **{audience}** — calibrate every example, scenario, and explanation for this specific learner." if audience.strip() else ""

    lines = [
        "## Teaching style (human mentor — CRITICAL)",
        "",
        "Write like a **real instructor teaching a live class**, NOT like an encyclopedia or dictionary.",
        "",
        "### The core rule: TEACH, don't DEFINE",
        "",
        "WRONG (dictionary style, avoid this):",
        '> "Coinsurance is a provision in an insurance policy requiring the insured to maintain coverage equal to a specified percentage of the property\'s value."',
        "",
        "RIGHT (instructor style, use this):",
        '> "Imagine a business owner who insures a $1 million building for only $300,000. If a fire causes $500,000 in damage, the insurer won\'t pay the full claim — because the property was significantly underinsured. Coinsurance rules exist for exactly this reason: to encourage policyholders to carry coverage that actually reflects what they\'re protecting."',
        "",
        "Every section must answer ALL of these questions:",
        "  1. **What is this?** (brief, plain-English definition)",
        "  2. **Why does it matter?** (real consequences for the learner or their clients)",
        "  3. **How is it used in practice?** (scenario, client conversation, or example)",
        "  4. **What mistakes should be avoided?** (common pitfalls, misconceptions)",
        "  5. **What should the learner know in a real situation?** (actionable takeaway)",
        "",
        "### Voice and tone",
        "- Address the reader directly (second person: 'you', 'your', 'your client').",
        "- Conversational but professional — like an experienced colleague explaining something.",
        "- Vary sentence length. Short punchy sentences for key rules. Longer sentences for context.",
        '- NEVER start a section with "In this section we will discuss…" or "It is important to note that…"',
        '- NEVER use filler openers. Jump straight into the teaching.',
        "",
        "### Avoid reference-manual writing",
        "- The goal is to teach understanding, not to create a glossary or reference document.",
        "- Do not simply list facts, rules, definitions, or regulations.",
        "- Instead:",
        "  - Explain concepts.",
        "  - Connect ideas together.",
        "  - Show cause and effect.",
        "  - Use examples to make concepts memorable.",
        "  - Help the learner understand how knowledge is applied in real situations."

    ]

    if audience_line:
        lines.extend(["", audience_line])

    lines.extend([
        "",
        "### Real-world examples and scenarios",
        "- Every section of 200+ words MUST include at least one scenario or real-world example.",
        "- A good scenario is 2–5 sentences: a realistic client situation → what happens → what the learner should do or know.",
        "- Use business situations, client conversations, agent decisions, compliance situations.",
        "- Scenarios should feel like things that actually happen, not hypotheticals.",
    ])

    if scenarios or ex_range:
        lo, hi = (ex_range or [1, 2])[:2] if ex_range else (1, 2)
        lines.extend([
            f"- Rule-pack requires **{lo}–{hi}** example(s) per section.",
        ])

    if transitions:
        lines.extend([
            "",
            "### Transitions",
            "- Bridge between major ideas with a smooth transition sentence.",
            "- Do not jump abruptly between bullet points and prose.",
        ])

    lines.extend([
        "",
        "### Course and lesson continuity (CRITICAL)",
        "The course is a continuous learning journey — NOT a collection of isolated sections.",
        "",
        "**Between lessons** — when a `Previous Lesson Context` block is present:",
        "  - The FIRST section of this lesson MUST open with ONE bridging sentence that:",
        "    a) acknowledges what the learner just covered in the previous lesson, and",
        "    b) explains why the current topic is the natural next step.",
        "  - Example: 'Now that you understand how coinsurance works, let's look at "
        "how deductibles interact with those rules — because the two work together in every claim.'",
        "  - The bridge must feel like a real instructor pivoting, not a mechanical summary.",
        "  - Do NOT repeat content from the previous lesson — one sentence of acknowledgment only.",
        "",
        "**Between sections within this lesson** — when a section block shows `prev_section`:",
        "  - Open THAT section with ONE sentence connecting it to the named previous section.",
        "  - Show HOW the new topic follows from or builds on the previous one.",
        "  - Examples of good intra-lesson bridges:",
        "    'With that foundation in place, let's look at how [new topic] applies in practice.'",
        "    '[Prev topic] sets the stage — now we need to understand [new topic] to complete the picture.'",
        "    'Understanding [prev topic] is only half the equation; [new topic] is what determines...'",
        "  - NEVER start a non-first section cold, as if the previous section did not exist.",
        "  - Keep the bridge to ONE sentence — do not summarise the prior section at length.",
    ])

    if labels or callout_range:
        lo_c, hi_c = (callout_range or [1, 2])[:2] if callout_range else (1, 2)
        label_list = ", ".join(f'"{x}"' for x in labels) if labels else '"Important", "Pro Tip", "Common Mistake", "Warning"'
        lines.extend([
            "",
            "### Instructional emphasis callouts",
            f"- Use **{lo_c}–{hi_c}** `important_callout` block(s) per section.",
            f"- Label options: {label_list}",
            '- Example: {{"type": "important_callout", "label": "Common Mistake", "content": "Many agents assume coinsurance only applies to commercial policies — it applies to residential as well."}}',
            "- Use 'Common Mistake' for pitfalls, 'Warning' for compliance risk, 'Pro Tip' for best practices.",
        ])

    lines.append("")
    return "\n".join(lines)


def _build_course_config_system_block(course_config: dict) -> str:
    """Build an authoring guidance block from onboarding wizard fields."""
    if not course_config:
        return ""

    lines: list[str] = []

    tone = (course_config.get("tone") or "").strip()
    if tone:
        lines.append(f"- **Tone**: Write in a {tone} voice throughout. Every section must reflect this tone.")

    depth = (course_config.get("depth") or "").strip()
    if depth:
        depth_labels = {
            "overview": "Overview — high-level introduction, minimal technical detail. Prioritise accessibility over completeness.",
            "balanced": "Balanced — mix conceptual explanation with practical application.",
            "detailed": "Detailed — thorough, in-depth coverage. Unpack nuance, include edge cases, go beyond definitions.",
        }
        depth_desc = depth_labels.get(depth.lower(), depth)
        lines.append(f"- **Course depth**: {depth_desc}")

    experience = (course_config.get("experience_level") or "").strip()
    if experience:
        exp_labels = {
            "new": "New to the topic — assume little or no prior knowledge. Define all terms, avoid jargon without explanation.",
            "some": "Some experience — familiar with core concepts. Skip basic definitions; focus on application and nuance.",
            "experienced": "Experienced — strong existing knowledge. Use precise terminology, assume domain fluency, focus on advanced application.",
        }
        exp_desc = exp_labels.get(experience.lower(), experience)
        lines.append(f"- **Learner experience**: {exp_desc}")

    emphasis = (course_config.get("emphasis") or "").strip()
    if emphasis:
        lines.append(f"- **Emphasise**: {emphasis}. Weight your examples and explanations toward these topics.")

    avoid = (course_config.get("avoid") or "").strip()
    if avoid:
        lines.append(f"- **Avoid**: {avoid}. Do not introduce this material in any section.")

    include_case_studies = course_config.get("include_case_studies")
    if include_case_studies is None:
        include_case_studies = course_config.get("include_scenarios")
    if include_case_studies is False:
        lines.append("- **Case studies**: Omit case studies — deliver content as direct instruction.")

    include_examples = course_config.get("include_examples")
    if include_examples is False:
        lines.append("- **Examples**: Minimize illustrative examples — keep explanations conceptual.")

    if not lines:
        return ""

    return "## Authoring guidance (from course configuration)\n\n" + "\n".join(lines) + "\n"


def build_lesson_system_prompt(rule_pack: dict, audience: str = "", course_config: dict | None = None) -> str:
    """System prompt: output contract + authority rules; voice/KC details come from rule pack JSON."""
    fam = rule_pack.get("family") or ""
    if not fam:
        raise ValueError(
            "rule_pack must contain a non-empty 'family' key — "
            "ensure resolve_rule_pack() was called before building the system prompt."
        )
    ver = rule_pack.get("version", "")
    meta = f"{fam} v{ver}" if ver else fam
    teaching_block = _build_teaching_style_section(rule_pack, audience=audience)
    active_difficulty = (
        rule_pack.get("active_difficulty")
        or (rule_pack.get("style_constraints") or {}).get("difficulty_level")
        or "intermediate"
    )
    difficulty_block = f"""## Course difficulty: **{active_difficulty}**

Honor `full_rule_pack.active_difficulty` and any difficulty-specific fields in
`style_constraints`, `content_rules`, `compliance_elements.required_behaviors`, and
other instructional constraints. Do not write below or above the expected depth
for this level.

"""
    course_config_block = _build_course_config_system_block(course_config or {})

    return f"""\
You are a professional continuing education course author for RegEd Inc.

**Active rule pack:** {meta}

 The USER MESSAGE includes a JSON object with a key `full_rule_pack` containing the filtered content-writing rule configuration for this course and few inputs from the user.
Course-specific user inputs are authoritative for course title, target audience, tone, difficulty, chapter title, chapter description, timed outline, subtopics, desired learner outcomes, and special author instructions.

The rule pack is authoritative for compliance, regulatory safety, source fidelity, citation controls, forbidden content, output constraints, KC/exam rules, and default course-family behavior.

If user/course input conflicts with generic rule-pack defaults, obey the user/course input.

If user/course input conflicts with compliance, regulatory safety, source fidelity, hallucinated citation controls, forbidden content, or output format rules, obey the rule pack and system prompt.
Return ONLY a valid JSON ARRAY where each element is one section, in the same
order as the sections listed in the prompt. No markdown fences, no commentary:

[
  {{
    "heading": "<section heading exactly as given>",
    "body_paragraphs": [
      {{ "type": "text",             "content": "paragraph text here" }},
      {{ "type": "bullet_list",      "items": ["item 1", "item 2"] }},
      {{ "type": "important_callout", "label": "Important", "content": "key takeaway text" }}
    ]
  }},
  {{ "heading": "...", "body_paragraphs": [ ... ] }}
]

## Paragraph Types You May Use

- "text"               — standard body paragraph
- "bullet_list"        — bulleted list of items
- "sub_bullet_list"    — indented sub-bullets under a parent bullet
- "numbered_list"      — numbered list
- "important_callout"  — highlighted box (lavender); optional `label` (Important, Pro Tip, …)
- "heading_3"          — sub-heading within the section
- "heading_4"          — minor sub-heading
- "table"              — comparison matrix, process table, or structured reference data

Table format:
```json
{{
  "type": "table",
  "caption": "optional bold title above the table",
  "headers": ["Column A", "Column B", "Column C"],
  "rows": [
    ["row 1 cell A", "row 1 cell B", "row 1 cell C"],
    ["row 2 cell A", "row 2 cell B", "row 2 cell C"]
  ]
}}
```

## Voice, tone, and structure

Derive reading level, voice (e.g. second vs third person), tone, organization reference ("we" vs "this course"), and client references **only** from `full_rule_pack.content_rules.chapter_rules` and `full_rule_pack.compliance_elements`.

Derive section structure expectations (intro placement, summaries, examples/callouts per section,  etc.) from `full_rule_pack.content_rules` and user input.

### Voice enforcement (CRITICAL)

When `full_rule_pack.content_rules.chapter_rules.voice` mentions **second_person**:
- Address the learner directly as "you" / "your" in EVERY section.
- Each section of 80+ words MUST contain at least 2 second-person references (you, your, yourself, yours).
- Do NOT write only third-person regulatory prose like "Buildings must resist…". Reframe as "You will find that buildings must resist…" or "When you advise a client, the building must resist…".
-Use "we" / "this organization" / "this course" only as allowed by `full_rule_pack.content_rules.chapter_rules.voice` and `full_rule_pack.content_rules.chapter_rules.required_behaviors`.
When `full_rule_pack.content_rules.chapter_rules.voice` mentions **third_person**:
- Avoid "you" / "your".
- Use role titles based on the course type and audience, such as "the registered representative", "the IAR", "the producer", "the licensee", or the course-specific learner role.
- Do not switch into direct learner address unless the course-specific user input explicitly allows it.
If the voice rule conflicts with the source text, **rewrite** the source text to match the rule — do not preserve the source voice.


## Visual learning aids (Priority 2)

Use `table` blocks to make structured information scannable. A table is BETTER than a bullet list when:
- Comparing 2+ policy types, coverage options, regulatory tiers, or plan features
- Showing a process with steps and their descriptions or conditions
- Presenting attributes of 2+ entities side-by-side
- Mapping requirements to actions (e.g. "If the client has X, then Y applies")

**Good triggers for tables:**
- "Types of X and their differences" → comparison matrix
- "Steps in the [process]" → numbered process table
- "Regulatory requirements" → requirement / action / example columns
- "Coverage tiers" → tier / benefit / limit columns

**Do NOT use tables for:**
- Lists with only one attribute per item (use bullet_list instead)
- Fewer than 2 rows (use a callout or bullet instead)
- Content that is flowing narrative (use text instead)

Introduce each table with a `heading_3` or `text` block before it. The table should feel like a teaching aid, not raw data.

## Content optimization

- **No repetition**: Do not re-explain a concept already covered in the `Prior Sections Summary`. If a concept from a prior section is relevant, reference it briefly ("As you saw in the previous section, …") and build on it — do not re-teach it.
- **Consolidate overlapping content**: When two closely related concepts appear in the same or adjacent sections, explain their relationship and how they interact, rather than presenting them as completely independent topics.
- **Avoid summary openers**: Do not start a section by listing what you are about to cover ("In this section, we will discuss X, Y, and Z"). Jump directly into the teaching.
- **Compress at the concept level**: If the source material has more detail than the word budget allows, select the most instructionally valuable points — do not produce a thin summary of everything.

## Regulatory content

When regulatory references are applicable (insurance rules, SEC/NASAA regulations, FINRA rules), integrate them naturally into the narrative:
- Name specific regulations or regulatory bodies when citing them: "Under FINRA Rule 1240…", "State departments of insurance require…", "SEC Release IA-5248 clarifies…"
- Connect regulations to real consequences: what happens if the learner or their client violates this requirement?
- Use regulatory context to ground scenarios: "If a state insurance examiner reviewed this policy, they would expect to see…"
- Frame compliance not as a checkbox but as professional responsibility: why these rules protect clients and practitioners.
- Do NOT hallucinate regulation numbers or names — cite only what the source material supports.

## Source material fidelity (CRITICAL)

When `full_rule_pack.content_rules.require_source_fidelity` is true (or source text is provided):
- Teach **only** what the **Source Content** excerpt supports — paraphrase in your own words; do NOT copy long passages verbatim.
- Do NOT invent statistics, laws, dates, or product features absent from the source.
- If the source is thin, expand with definitions and **lightweight** examples that stay consistent with the excerpt — never contradict it.
- Regulatory references must align with `compliance_elements` and the source.


## Source cleanup and artifact filtering (CRITICAL)

Use source material only as instructional reference. Do not copy raw source extraction artifacts, PDF headers/footers, page numbers, footnotes, URLs, file metadata, OCR residue, table extraction residue, legal publication formatting, or unrelated source fragments into the generated course.

When source text contains noisy fragments, convert only the relevant meaning into clean instructional prose. If a source fragment is unrelated to the course topic, skip it completely.

Do NOT include content such as:
- Federal Register page headers or publication metadata
- page numbers, volume numbers, dates, document control text, or filing codes
- OCR artifacts such as “VerDate,” “Jkt,” “Frm,” “Fmt,” “Sfmt,” “PO 00000,” “E:\FR\...,” “</GPH>”
- raw URLs, citation fragments, footnote fragments, or source navigation text
- unrelated company names, article references, investment statistics, or examples not directly relevant to the lesson
- copied source tables or malformed table fragments unless converted into a clean teaching table

If the source contains noisy or irrelevant text, ignore the noise and continue teaching the lesson using only relevant, source-supported concepts.

Before finalizing the output, self-check that every paragraph reads like clean learner-facing course content and not like copied source material.

## Safety

Do not invent statistics, citations, or regulator quotes when `disclosure_handling` forbids hallucinated citations. Frame content as informational, not personal investment advice, unless the rule pack explicitly allows otherwise.

## Word counts (STRICT — non-negotiable)

Use the chapter target word count as the controlling requirement.

Subtopic word counts, if provided, are guidance only unless explicitly marked as hard limits. Do not force equal subtopic lengths.

Keep the final chapter within the configured tolerance from `chapter_rules.word_count_tolerance_percent` or `error_tolerance.word_count_tolerance_percent`.

Give more depth to subtopics with higher regulatory, suitability, client-risk, source, or instructional importance.

If source material is thin, expand only with supported definitions, examples, scenarios, and compliance context. Do not invent unsupported facts, laws, citations, penalties, or product features.

The total chapter content must land within the configured chapter-level tolerance.
"""


def build_lesson_user_message(
    lesson: dict,
    subtopic_specs: list[dict],
    prior_summary: str,
    rule_constraints: dict,
    lesson_wc: int,
    feedback: str | None = None,
    audience: str = "",
    special_instructions: str | None = None,
    prev_lesson_context: str = "",
    course_config: dict | None = None,
) -> str:
    """
    Build a single user message that asks the LLM to generate content for ALL
    subtopics of one TO lesson at once.

    subtopic_specs: list of dicts, each with:
      - heading         : section heading string
      - target_word_count : int
      - source_text     : full extracted paragraph text (no truncation)
      - subtopics       : list[str]  (sub-headings from course_spec)
      - interactive_elements : list[str]
      - image_count     : int

    The LLM must return a JSON array with exactly len(subtopic_specs) elements
    in the same order.
    """

    full_pack = bundle_rule_pack_for_prompt(rule_constraints)

    constraints = {
        "full_rule_pack": full_pack,
        "legacy_subset": {
            "style": rule_constraints.get("style_constraints", {}),
            "compliance": {
                "forbidden_phrases": rule_constraints.get("compliance_elements", {}).get(
                    "forbidden_phrases", []
                ),
                "required_behaviors": rule_constraints.get("compliance_elements", {}).get(
                    "required_behaviors", []
                ),
            },
        },
    }

    lesson_title = lesson.get("title", "")
    lesson_content = (lesson.get("content") or "").strip()
    lesson_ie = lesson.get("interactive_elements", [])

    # Build one block per subtopic
    section_blocks: list[str] = []
    for i, spec in enumerate(subtopic_specs):
        source = (spec.get("source_text") or "").strip()
        sub_headings = spec.get("subtopics", [])

        target_wc = int(spec.get("target_word_count", 0) or 0)
        wc_min = max(1, int(round(target_wc * 0.95)))
        wc_max = max(wc_min, int(round(target_wc * 1.05)))
        is_overview = bool(spec.get("_is_parent_overview"))
        section_kind = (
            "PARENT OVERVIEW (intro for the lesson — frame the topic, list what the "
            "learner will cover; do NOT duplicate subtopic detail)"
            if is_overview
            else "SUBTOPIC"
        )

        # Warn LLM when source is significantly richer than the target budget so
        # it does not try to cover everything and overshoot.
        source_words = len(source.split()) if source else 0
        if source_words > target_wc * 2 and target_wc > 0:
            compression_note = (
                f"\n⚠ COMPRESS: source has ~{source_words} words but target is {target_wc}. "
                f"Select the {target_wc} most important words of content. "
                f"Do NOT cover every point — prioritise key concepts only."
            )
        else:
            compression_note = ""

        prev_heading = (spec.get("prev_section_heading") or "").strip()
        if prev_heading:
            prev_section_line = (
                f"\nprev_section      : \"{prev_heading}\""
                f"\n→ Open this section with ONE sentence that bridges FROM \"{prev_heading}\" "
                f"INTO \"{spec['heading']}\" — show how the two topics connect or build on each other."
            )
        else:
            prev_section_line = ""

        block = f"""### Section {i + 1} of {len(subtopic_specs)}: "{spec['heading']}"
section_kind      : {section_kind}
soft_word_count        : {target_wc} words 
Note: This is planning guidance only. Do not validate this section against a hard subtopic band.
sub_headings      : {json.dumps(sub_headings)}
image_count       : {spec.get('image_count', 0)}
interactive_elements: {json.dumps(spec.get('interactive_elements', []))}{prev_section_line}

Source Content (reference material — paraphrase faithfully; do NOT copy verbatim):
{source if source else "(No source available — generate from sub_headings and lesson context only; keep claims general)"}"""

        section_blocks.append(block)

    sections_block = "\n\n---\n\n".join(section_blocks)
    n = len(subtopic_specs)

    feedback_block = ""
    if feedback and feedback.strip():
        feedback_block = (
            "\n\n## Prior S2 validation feedback (resolve these issues in this regeneration)\n"
            f"{feedback.strip()}\n"
        )

    audience_block = ""
    if audience.strip():
        audience_block = f"\n\n## Target Audience (CRITICAL — calibrate ALL content for this learner)\n{audience.strip()}\nEvery example, scenario, callout, and explanation must be relevant and practical for this audience. Do not write generic content."

    special_instructions_block = ""
    if special_instructions and special_instructions.strip():
        special_instructions_block = f"\n\n## Special Instructions from the Course Author (follow these EXACTLY)\n{special_instructions.strip()}\nThese instructions override default style choices. Apply them throughout every section of this lesson."

    prev_lesson_block = ""
    if prev_lesson_context and prev_lesson_context.strip():
        prev_lesson_block = (
            "\n\n## Previous Lesson Context (bridge from here into this lesson)\n"
            f"{prev_lesson_context.strip()}\n\n"
            "→ Your FIRST section must open with exactly ONE bridging sentence that naturally "
            "connects what the learner just finished to this new lesson topic. "
            "Do not repeat the previous content — one sentence of acknowledgment, then move forward."
        )

    course_config_block = ""
    cfg = course_config or {}
    cfg_lines: list[str] = []
    learner_outcomes = (cfg.get("learner_outcomes") or "").strip()
    if learner_outcomes:
        cfg_lines.append(f"Desired Learner Outcomes: {learner_outcomes}")
    audience_notes = (cfg.get("audience_notes") or "").strip()
    if audience_notes:
        cfg_lines.append(f"Additional Learner Context: {audience_notes}")
    if cfg_lines:
        course_config_block = "\n\n## Course Configuration Context\n" + "\n\n".join(cfg_lines)

    return f"""## Lesson
Title      : {lesson_title}
Description: {lesson_content[:400] if lesson_content else "(none)"}
Total word budget : {lesson_wc} words  
Interactive elements: {json.dumps(lesson_ie)}

Subtopic word counts, if provided, are planning guidance only. They are not hard limits. The final chapter should meet the chapter-level word count, and the model may redistribute words across subtopics based on instructional importance, compliance weight, suitability risk, and content complexity.
## Applicable Constraints (full_rule_pack is authoritative)

{json.dumps(constraints, indent=2)}

## Prior Sections Summary (do NOT repeat these concepts)

{prior_summary if prior_summary else "(No prior sections — this is the first lesson)"}
{prev_lesson_block}{feedback_block}{audience_block}{special_instructions_block}{course_config_block}
## Sections to Generate  [{n} total — return as JSON array in this exact order]

{sections_block}

## Instructions

Generate content for ALL {n} section(s) above in a SINGLE response.
Return a JSON ARRAY with exactly {n} element(s), one per section, in order:
[
  {{ "heading": "<heading 1 exactly>", "body_paragraphs": [ ... ] }},
  {{ "heading": "<heading 2 exactly>", "body_paragraphs": [ ... ] }}
]

-Subtopic-level word counts are approximate guidance only. Do not force every subtopic into an exact range. The total chapter word count is the controlling requirement.- Total across all sections must land within ±10% of {lesson_wc} words.
- Address the learner directly per `full_rule_pack.content_rules.chapter_rules.voice` — every long section needs the required voice tokens (see Voice enforcement above).
- Do NOT generate quiz, exam, assessment, or `knowledge_check` blocks anywhere in the response.
- Use "important_callout" with a `label` per content_rules / style_constraints (see Teaching style).
- Include **lightweight** scenario-based examples and transition sentences when the rule pack requires them.
- Stay faithful to each section's Source Content when `require_source_fidelity` is set.
- Prefer bullet_list for lists of 3+ items when that makes the content easier to scan.
- Use "table" for any structured comparison or multi-attribute data (2+ rows, 2+ columns). Tables count toward word count.
- Do NOT repeat concepts already described in the Prior Sections Summary — reference them briefly if needed.
- Return ONLY the JSON array — no explanation, no markdown fences.
"""


    