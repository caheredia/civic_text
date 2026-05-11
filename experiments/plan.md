# Docling Experiment Plan

## Summary

Build a lightweight experiment harness in `civic_text` to install Docling with `uv`, run the repo's sample PDFs through Docling Standard, save inspectable outputs, and summarize findings in a Jupyter notebook table.

The first goal is empirical: determine whether layout-aware parsing gives us a better normalization layer for attendance, agenda items, motions/seconds, and vote counts than raw page OCR or plain PDF text extraction.

## Implementation Changes

- Configure Python for whichever version makes Docling easiest to install:
  - Prefer Python `3.12` or `3.13` if PyTorch/Docling wheels require it.
  - Use Python `3.14` if `uv` resolves the Docling stack cleanly.
  - Keep the chosen version consistent across `.python-version`, `pyproject.toml`, and `uv.lock`.
- Use a workspace-local uv cache during setup: `UV_CACHE_DIR=.uv-cache`.
- Add dependencies with `uv add docling jupyter pandas`.
- For RTX runs, prefer the explicit CUDA command from a host shell that can see the NVIDIA driver:
  - `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python HF_HOME=.hf-cache uv run python experiments/run_docling_standard.py --device cuda --ocr-batch-size 32 --layout-batch-size 32 --table-batch-size 4`
  - On NixOS, if `nvidia-smi` works but PyTorch says CUDA is unavailable, prepend the driver library path:
    `LD_LIBRARY_PATH=/run/opengl-driver/lib:$LD_LIBRARY_PATH UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python HF_HOME=.hf-cache uv run python experiments/run_docling_standard.py --device cuda --ocr-batch-size 32 --layout-batch-size 32 --table-batch-size 4`
  - To inspect GPU visibility without running the PDFs:
    `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python experiments/run_docling_standard.py --device cuda --diagnose-cuda`
  - Increase OCR/layout batch sizes cautiously on the RTX 3090 if GPU memory remains low.
- Add `experiments/run_docling_standard.py`:
  - Input: `data/*.pdf`.
  - Output: `experiments/out/docling_standard/`.
  - For each PDF, write parsed Markdown, structured Docling export where available, timing metadata, file metadata, and success/error status.
  - Continue processing remaining PDFs if one file fails.
- Add `experiments/findings.ipynb`:
  - Load experiment metadata.
  - Present a table with parser, filename, runtime, status, output paths, and manual quality notes.
  - Include manual scoring columns for reading order, header/footer handling, attendance usefulness, agenda/item usefulness, motion/vote usefulness, and extraction readiness.

## Experiment Sequence

1. **Docling Standard baseline**
   - Install Docling.
   - Run all `data/*.pdf`.
   - Inspect Markdown/JSON output.
   - Score each document in the notebook.

2. **Cheap text baseline**
   - Add a simple embedded-text parser later, likely PyMuPDF or pypdf.
   - Run the same files.
   - Compare against Docling so we know when layout parsing is actually adding value.

3. **Docling VLM / Granite follow-up**
   - Start a local OpenAI-compatible vLLM server with `experiments/docker-compose.vllm.yml`.
   - Run `experiments/run_docling_vlm_vllm.py` against `http://localhost:8000/v1/chat/completions`.
   - Use Docling batch conversion by default so page-level VLM calls can be in flight concurrently.
   - Reuse the same output structure and notebook scoring table.
   - Compare quality gain against runtime and setup complexity.

4. **Hybrid selective LLM parser**
   - Use Docling Standard GPU output as the fast canonical extraction layer.
   - Run `experiments/run_hybrid_selective_llm.py` to split Markdown into civic sections and agenda/minutes items.
   - Score each section with deterministic heuristics for action/vote parsing, public comment counts, attendance tables, money/date entities, OCR spacing damage, and long ambiguous sections.
   - Default to dry-run mode that writes selected prompts under `experiments/out/hybrid_selective_llm/prompts/`.
   - If a local or API OpenAI-compatible model is available, set `CIVIC_LLM_URL` and `CIVIC_LLM_MODEL`, or pass `--llm-url` and `--llm-model`, to parse selected sections into JSON.
   - Compare the handoff count and prompt mix against all-in VLM runtime and failure modes.

5. **Optional managed benchmark**
   - Treat AWS Textract/Bedrock as a later benchmark.
   - Use it only if local parsing quality is poor or inconclusive.

## Test Plan

- Verify `uv sync` succeeds after dependency and Python-version changes.
- Run the Docling Standard experiment over all sample PDFs.
- Confirm runtime metadata records PyTorch/CUDA visibility and requested device.
- Confirm successful PDFs produce Markdown, structured output, and metadata.
- Confirm failures are captured as metadata rows instead of crashing the batch.
- Run the hybrid selective LLM dry-run and confirm it writes `summary.json`, `sections.json`, `section_scores.json`, and prompt files.
- Open or execute the notebook and verify the findings table renders from generated outputs.

## Assumptions

- First priority is fast empirical learning, not production ETL.
- Manual scoring is acceptable for round one because the key unknown is document-structure quality.
- The experiment harness should be reusable for multiple parser PoCs.
- We will defer full civic-data extraction until parser quality is understood.
