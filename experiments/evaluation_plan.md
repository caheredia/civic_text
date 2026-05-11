# Parser Evaluation Plan

## Purpose

After generating parsed text and structured candidates from each approach, run one consistent evaluation pass across all outputs.

The goal is to avoid judging parsers by runtime alone. We need to know whether the text is coherent enough to support downstream civic data extraction, and whether structured outputs can be audited back to source text.

## Evaluation Inputs

Candidate inputs:

- `experiments/out/docling_standard/`
- `experiments/out/docling_standard_cpu/`
- `experiments/out/hybrid_selective_llm/`
- future `experiments/out/minimax_m25_agent/`
- future `experiments/out/bedrock_data_automation/`

Each parser should provide, when possible:

- Markdown or plain text output
- structured JSON output
- runtime metadata
- source document filename
- source page or section provenance
- error metadata

## Core Questions

1. Is the extracted text coherent enough to read?
2. Are agenda/minutes item boundaries preserved?
3. Are civic fields extractable with deterministic rules?
4. Where deterministic extraction fails, are the failures localized enough for targeted LLM repair?
5. Can structured fields be traced back to source text or page spans?
6. Is the quality improvement worth the runtime, cost, and operational complexity?

## Quality Rubric

Score each document/parser pair on a 0-3 scale.

| Score | Meaning |
|---|---|
| 0 | unusable |
| 1 | partially usable, major manual cleanup required |
| 2 | usable with targeted repair or review |
| 3 | production-quality for this field |

### Document-Level Checks

| Check | Description |
|---|---|
| reading_order | Text follows the source document in a human-readable order. |
| header_footer_handling | Repeated headers/footers are not overly disruptive. |
| duplicate_text | Output does not contain large duplicated blocks. |
| page_continuity | Items split across pages remain understandable. |
| markdown_usability | Markdown is readable and preserves useful structure. |
| json_usability | Structured output is valid and useful for downstream code. |

### Civic Extraction Checks

| Check | Description |
|---|---|
| item_boundaries | Agenda/minutes item numbers and titles are preserved. |
| item_count_accuracy | Extracted item count matches expected item count. |
| consent_regular_classification | Consent vs regular agenda sections are distinguishable. |
| attendance | Present/absent members are extractable. |
| actions | Action summaries are extractable from minutes. |
| motion_second | Motion and second fields are extractable when present. |
| vote_result | Result and vote counts are extractable. |
| ayes_nays_abstain | Member-level vote lists are extractable when present. |
| public_comment | Public comment counts and modality are extractable. |
| dates_money | Dates and money amounts remain intact. |
| tables | Tables are preserved well enough to parse. |

### OCR/Layout Damage Checks

| Check | Description |
|---|---|
| joined_words | Words are not excessively joined together. |
| broken_words | Words are not split or corrupted frequently. |
| lost_punctuation | Punctuation loss does not change meaning. |
| column_mixing | Multi-column or sidebar text is not mixed into body text. |
| attachment_noise | Attachment/footer text does not obscure agenda items. |

### Provenance Checks

| Check | Description |
|---|---|
| source_page | Fields can be tied to page numbers. |
| source_section | Fields can be tied to section or item IDs. |
| source_quote | Extracted fields can include supporting source text. |
| auditability | A reviewer can quickly verify extracted fields. |

## Suggested Output Files

Add an evaluation output directory:

`experiments/out/evaluation/`

Suggested files:

- `document_scores.csv`
- `document_scores.json`
- `field_scores.csv`
- `field_scores.json`
- `issues.json`
- `summary.md`

## Semi-Automated Checks

Implement these first:

- Count agenda/minutes item markers.
- Detect skipped or duplicate item numbers.
- Count headings and tables.
- Count keyword presence for:
  - `present`
  - `absent`
  - `motion`
  - `second`
  - `approved`
  - `ayes`
  - `nays`
  - `abstain`
  - `public comment`
- Detect OCR spacing damage with joined-word heuristics.
- Detect repeated page headers/footers.
- Validate JSON parseability.
- Validate required schema fields for structured outputs.

## Manual Review

Manual review should be limited to ambiguous cases surfaced by automated checks.

For each parser/document pair, inspect:

1. First page/header area.
2. One consent agenda section.
3. One regular agenda item.
4. One minutes item with action and vote.
5. One attendance or roll-call section.
6. One table, if present.
7. One item split across pages, if present.

Record notes in the score files rather than ad hoc chat messages.

## Decision Criteria

### Parser Is Good Enough

A parser is good enough for the next pipeline stage if:

- item boundaries score at least 2;
- actions/votes score at least 2 for minutes;
- dates/money score at least 2;
- reading order score at least 2;
- provenance score at least 2;
- manual review rate is acceptable.

### Parser Needs Targeted Repair

Use targeted repair if:

- most output is coherent;
- failures are localized to specific sections or fields;
- deterministic checks can identify likely failures;
- LLM repair volume stays low.

### Parser Is Not Worth Pursuing

Drop or deprioritize a parser if:

- item boundaries are unreliable;
- output requires whole-document LLM repair;
- provenance is weak;
- runtime/cost is high without clear quality gains;
- manual review would dominate the workflow.

## Current Baseline Context

Current local extraction timing on the 5-PDF corpus:

- Docling Standard GPU: about 10.53 seconds total.
- Docling Standard CPU: about 49.98 seconds total.
- Hybrid selector dry-run: about 0.03 seconds after Docling output.

These timing numbers should be paired with the quality rubric before making final architecture decisions.
