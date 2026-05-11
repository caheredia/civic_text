# Future Experiments: MiniMax M2.5 and AWS Bedrock Data Automation

## Summary

We should keep these as two separate experiments:

1. **MiniMax M2.5 agentic parser**
   - Question: Can a strong agentic LLM parse Docling Standard Markdown into civic structured JSON reliably enough to justify the added latency and cost?
   - Input: Existing `experiments/out/docling_standard/*/document.md` outputs.
   - Output: Structured agenda/minutes JSON with provenance back to source sections.

2. **Amazon Bedrock Data Automation custom extraction**
   - Question: Can AWS's managed intelligent document processing service extract our civic meeting schema directly from PDFs with less orchestration than our Docling + rules + fallback-LLM pipeline?
   - Input: Original PDFs in `data/`, uploaded through S3 as required by the BDA document API flow.
   - Output: BDA standard document output plus custom blueprint output.

## BDA Fit Assessment

BDA sounds like a legitimately good fit, not an obvious shoehorn, because the core problem is structured extraction from semi-structured civic documents:

- meeting agendas and minutes have repeatable document types;
- fields are domain-specific but stable enough to define in blueprints;
- agenda/minutes/attendance can be represented as separate blueprint families;
- BDA is built for managed document processing, including extraction, normalization, and validation-like workflows;
- projects can attach multiple document blueprints, which maps well to agenda/minutes variants.

The risk is that civic meeting documents are not classic business forms. They contain long narrative items, inconsistent historical formatting, legislative actions, vote language, and agenda/minutes semantics that may not be obvious from layout alone. BDA is worth testing, but we should judge it empirically against our current Docling baseline.

## When BDA Is a Good Fit

Use BDA if the experiment shows:

- it extracts agenda/minutes fields directly from PDFs with high schema completeness;
- it handles both modern IQM2 PDFs and older/noisier PDFs without many separate special cases;
- custom blueprints can express our nested output shape, especially repeated agenda items;
- output includes enough source grounding or confidence data to support review;
- throughput and cost are acceptable compared with Docling Standard GPU plus deterministic parsing;
- setup complexity is lower than maintaining our own OCR/layout/LLM orchestration.

## When BDA Is a Shoehorn

Do not pursue BDA as the primary path if:

- blueprints work for simple header fields but struggle with repeated agenda items;
- it loses item boundaries, vote/action grouping, or public comment counts;
- we need many brittle blueprints for each county/system/year;
- provenance is too weak to audit extracted fields;
- output still requires the same amount of downstream LLM repair;
- latency/cost is high while Docling Standard already gives us usable text in about 10 seconds for the current 5-PDF corpus.

## Experiment 1: MiniMax M2.5 Agentic Parser

### Goal

Benchmark a high-quality agentic model on the already-extracted Docling Markdown.

### Inputs

- `experiments/out/docling_standard/*/document.md`
- Optional: `experiments/out/hybrid_selective_llm/sections.json` to provide pre-sectioned text.

### Model

- Bedrock model ID: `minimax.minimax-m2.5`
- Prefer `bedrock-mantle` Chat Completions if available.

### Procedure

1. Send one document at a time, or one agenda/minutes section group at a time.
2. Ask for strict JSON matching our civic schema.
3. Require provenance fields that quote or reference source section IDs.
4. Record wall time, token usage, output JSON validity, schema completeness, and hallucination rate.
5. Compare against our deterministic sectioner and llama.cpp/Qwen local run.

### Expected Output Directory

`experiments/out/minimax_m25_agent/`

Suggested files:

- `summary.json`
- `requests/*.json`
- `responses/*.json`
- `parsed_results.json`
- `quality_notes.md`

## Experiment 2: Bedrock Data Automation

### Goal

Test AWS's managed IDP path against our current Docling pipeline.

### Service

Amazon Bedrock Data Automation (BDA).

Relevant concepts:

- **Standard output** for document text/structure extraction.
- **Custom output** using **blueprints**.
- **Projects** that group output configuration and can include multiple document blueprints.
- **InvokeDataAutomationAsync** for document processing.

### Candidate Blueprints

#### `county_agenda`

Fields:

- meeting_date
- board_or_body
- meeting_type
- item_number
- item_title
- item_category
- department
- consent_or_regular
- public_hearing
- money_amounts
- referenced_dates
- attachments
- source_page
- source_text
- needs_review

#### `county_minutes`

Fields:

- meeting_date
- item_number
- item_title
- action_summary
- result
- motion_by
- second_by
- ayes
- nays
- abstain
- absent
- public_comment_in_chambers
- public_comment_zoom
- source_page
- source_text
- needs_review

#### `attendance`

Fields:

- present_members
- absent_members
- roles
- source_page
- source_text
- needs_review

### Procedure

1. Create representative blueprint prompts using one agenda and one minutes PDF.
2. Create a BDA project and attach the blueprints.
3. Upload the current `data/*.pdf` corpus to S3.
4. Run BDA async for each PDF.
5. Save raw BDA output and normalized comparison output.
6. Compare against Docling Standard Markdown and our deterministic parser.

### Expected Output Directory

`experiments/out/bedrock_data_automation/`

Suggested files:

- `project_config.json`
- `blueprints/*.json`
- `requests/*.json`
- `raw_outputs/*.json`
- `normalized_results.json`
- `summary.json`
- `quality_notes.md`

## Evaluation Criteria

Use the same rubric for both experiments:

- JSON validity
- schema completeness
- repeated agenda item boundary accuracy
- action/vote extraction accuracy
- attendance extraction accuracy
- public comment count accuracy
- money/date extraction accuracy
- source grounding/provenance quality
- manual review rate
- wall time
- cloud cost
- operational complexity

## Baseline To Beat

Current local baseline on the 5-PDF corpus:

- Docling Standard GPU: about 10.53 seconds total.
- Docling Standard CPU: about 49.98 seconds total.
- Hybrid selector dry-run: about 0.03 seconds after Docling output.

Any managed or agentic path must produce meaningfully better structured extraction quality to justify added cost, latency, and operational complexity.
