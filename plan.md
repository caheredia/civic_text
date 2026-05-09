# PDF Parsing POC Plan

## Goal

Evaluate three realistic approaches for extracting civic meeting data from PDFs:

- attendance
- agenda item counts
- motions / seconds
- yes / no / abstain vote counts

The immediate objective is not production readiness. The immediate objective is to de-risk the architecture by building small proof-of-concepts and measuring quality, speed, operational complexity, and cost.

## Context

The current problem is not just OCR accuracy. The harder issue is document structure:

- headers and footers pollute text
- page numbers and repeated boilerplate break continuity
- vote blocks and item blocks span pages
- municipalities use inconsistent formatting

Because of that, the main technical bet is that we should start from layout-aware PDF parsing, not plain OCR text alone.

## Recommendation Summary

We should evaluate these three paths in parallel order, from most pragmatic to most managed:

1. Local GPU parsing with `Docling`
2. Local GPU parsing with `MinerU`
3. AWS-native parsing and extraction with `Textract` plus `Bedrock`

`Unstructured` remains a possible benchmark, but not a primary track for the first round of POCs.

## Option 1: Local GPU with Docling

### Why this path

`Docling` looks like a strong fit for:

- local execution
- structured document output
- OCR plus layout understanding
- Python-friendly integration
- GPU support

This is a good candidate if we want to preserve control, avoid per-document vendor costs, and keep the system deployable on a single local workstation or dedicated GPU box.

### What this POC should prove

- Can `Docling` produce cleaner reading order than the current page-by-page Tesseract flow?
- Does it suppress or isolate headers and footers well enough to reduce custom cleanup?
- Can it preserve page and block structure so later extraction logic can reference exact source regions?
- Is throughput good enough for a realistic asynchronous pipeline?

### POC shape

Run a small corpus of representative PDFs through `Docling` and inspect:

- extracted markdown / JSON
- page-level text quality
- block ordering
- whether attendance sections and vote sections remain coherent

Then add a thin extraction layer for:

- document type classification
- attendance count
- yes / no / abstain count on clearly structured samples

### Primary risks

- local GPU setup complexity
- runtime still too slow on scanned minutes
- output is structurally better than Tesseract but still not good enough for vote extraction

### Success criteria

- materially better structure than Tesseract
- stable extraction output on at least a small mixed sample
- acceptable local runtime for batch processing

## Option 2: Local GPU with MinerU

### Why this path

`MinerU` is promising because it explicitly emphasizes:

- header and footer removal
- reading-order reconstruction
- JSON / markdown export
- scanned PDF handling
- local GPU acceleration

On paper, it maps closely to the actual failure modes described in the problem statement.

### What this POC should prove

- Does `MinerU` outperform `Docling` on messy civic PDFs?
- Is its output easier to post-process into item and vote records?
- Does it better preserve cross-page continuity for discussion and vote blocks?

### POC shape

Run the same evaluation corpus used for `Docling` and compare:

- parsing quality
- structural cleanliness
- runtime
- ease of downstream extraction

Then implement the same narrow extraction tasks so results are comparable across options.

### Primary risks

- more operational complexity than `Docling`
- parsing quality may be strong on academic/business PDFs but less strong on civic documents
- integration ergonomics may be worse even if raw output quality is better

### Success criteria

- equal or better structure than `Docling`
- better handling of repeated boilerplate and cross-page blocks
- comparable or acceptable runtime on local hardware

## Option 3: AWS with Textract + Bedrock

### Why this path

This path is the most operationally managed and the least dependent on local GPU availability.

The division of labor should be:

- `Textract` for OCR, layout, and block structure
- `Bedrock` for targeted extraction on candidate sections only

This is intentionally not a “send entire PDFs to an LLM” design. The point is to spend managed AI budget only after cheap parsing and narrowing.

### What this POC should prove

- Can `Textract` recover useful layout and reading structure from these PDFs?
- Can we identify candidate vote and attendance regions from Textract blocks?
- Can a bounded `Bedrock` extraction step return reliable structured fields from those candidate regions?
- Is the cost profile acceptable when used selectively instead of universally?

### POC shape

Build a narrow AWS flow:

1. send a sample PDF to `Textract`
2. inspect `LAYOUT` and text blocks
3. isolate likely attendance / motion / vote regions
4. send only those regions to a Bedrock model
5. return structured JSON fields with provenance

The first POC should optimize for observability, not throughput.

### Primary risks

- cost becomes unattractive at scale
- extraction quality depends too much on prompt behavior
- additional AWS orchestration overhead is not worth the gain

### Success criteria

- high-quality extraction on targeted regions
- clear evidence that selective invocation controls cost
- simpler operations story than maintaining local GPU parsing at scale

## Evaluation Dataset

Use a small but intentionally mixed sample from the repo:

- at least one agenda
- at least one minutes document
- at least one packet or harder long-form document
- at least one scanned or OCR-difficult sample if available

We should not optimize to a single municipality in the first round.

## Common Evaluation Criteria

Each POC should be scored on the same dimensions:

- text accuracy
- layout fidelity
- header / footer suppression
- cross-page continuity
- ease of extracting attendance
- ease of extracting vote counts
- latency per document
- operational complexity
- estimated cost at scale

## Proposed Execution Order

1. `Docling` POC
2. `MinerU` POC
3. `Textract` plus `Bedrock` POC

Reasoning:

- the first two tell us how far we can get with local parsing before paying cloud inference costs
- the AWS path gives us a managed baseline and may still win on engineering simplicity

## Deliverables Per POC

Each proof of concept should produce:

- a script or small module that runs on sample PDFs
- raw parsed outputs stored for inspection
- a short results note
- a structured comparison against the other options

## Exit Criteria

At the end of the three POCs, we should be able to answer:

- which parser gives us the best document normalization layer
- whether local GPU is good enough to avoid managed services
- whether AWS managed extraction is worth the cost and complexity
- what the thinnest possible custom civic-extraction layer looks like
