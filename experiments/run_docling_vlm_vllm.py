from __future__ import annotations

import argparse
import copy
import json
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from run_docling_standard import collect_runtime_metadata, slugify_pdf_name, write_json, write_text

PARSER_NAME = "docling_vlm_vllm"
DEFAULT_INPUT_DIR = Path("data")
DEFAULT_OUTPUT_DIR = Path("experiments/out") / PARSER_NAME
DEFAULT_VLLM_URL = "http://localhost:8000/v1/chat/completions"
DEFAULT_MODELS_URL = "http://localhost:8000/v1/models"
DEFAULT_MODEL = "ibm-granite/granite-docling-258M"
DEFAULT_CONCURRENCY = 64
DEFAULT_MAX_TOKENS = 4096


def check_vllm_server(models_url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(models_url, timeout=10) as response:
            body = response.read().decode("utf-8")
        return {
            "available": True,
            "models_url": models_url,
            "status_code": response.status,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "body": json.loads(body),
        }
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "models_url": models_url,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def export_document_dict(document: Any) -> dict[str, Any]:
    if hasattr(document, "export_to_dict"):
        return document.export_to_dict()
    if hasattr(document, "model_dump"):
        return document.model_dump(mode="json")
    if hasattr(document, "dict"):
        return document.dict()
    return {"repr": repr(document)}


def metadata_for_pdf(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    doc_name = slugify_pdf_name(pdf_path)
    doc_dir = output_dir / doc_name
    markdown_path = doc_dir / "document.md"
    json_path = doc_dir / "document.json"
    metadata_path = doc_dir / "metadata.json"

    return {
        "parser": PARSER_NAME,
        "filename": pdf_path.name,
        "input_path": str(pdf_path),
        "output_dir": str(doc_dir),
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "metadata_path": str(metadata_path),
        "bytes": pdf_path.stat().st_size,
        "status": "started",
        "runtime_seconds": None,
        "error": None,
    }


def write_conversion_outputs(metadata: dict[str, Any], document: Any) -> str:
    markdown = document.export_to_markdown()
    write_text(Path(metadata["markdown_path"]), markdown)
    write_json(Path(metadata["json_path"]), export_document_dict(document))
    metadata["markdown_chars"] = len(markdown)
    return markdown


def convert_pdf(converter: Any, pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    metadata = metadata_for_pdf(pdf_path, output_dir)
    started = time.perf_counter()

    try:
        result = converter.convert(pdf_path)
        markdown = write_conversion_outputs(metadata, result.document)
        metadata["status"] = "success" if markdown.strip() else "error"
        if metadata["status"] == "error":
            metadata["error"] = {"message": "Empty Markdown output"}
    except Exception as exc:  # noqa: BLE001 - batch experiments should record failures.
        metadata["status"] = "error"
        metadata["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        metadata["runtime_seconds"] = round(time.perf_counter() - started, 3)
        write_json(Path(metadata["metadata_path"]), metadata)

    return metadata


def convert_pdfs_batched(converter: Any, pdfs: list[Path], output_dir: Path) -> list[dict[str, Any]]:
    started_by_name = {pdf_path.name: time.perf_counter() for pdf_path in pdfs}
    results = []

    for pdf_path, conversion_result in zip(
        pdfs,
        converter.convert_all(pdfs, raises_on_error=False),
        strict=True,
    ):
        metadata = metadata_for_pdf(pdf_path, output_dir)
        metadata["runtime_seconds"] = round(
            time.perf_counter() - started_by_name[pdf_path.name],
            3,
        )

        markdown = ""
        if conversion_result.document is not None:
            markdown = write_conversion_outputs(metadata, conversion_result.document)

        errors = [str(error) for error in getattr(conversion_result, "errors", [])]
        status = str(getattr(conversion_result, "status", "unknown"))
        metadata["status"] = (
            "success"
            if not errors and conversion_result.document and markdown.strip()
            else "error"
        )
        metadata["conversion_status"] = status
        if metadata["status"] == "success":
            metadata["error"] = None
        else:
            metadata["error"] = {
                "messages": errors,
                "empty_markdown": not bool(markdown.strip()),
            }
        write_json(Path(metadata["metadata_path"]), metadata)
        results.append(metadata)

    return results


def debug_one_page(
    input_dir: Path,
    output_dir: Path,
    vllm_url: str,
    model: str,
    max_tokens: int,
    page_index: int,
) -> dict[str, Any]:
    import pypdfium2 as pdfium
    from docling.datamodel import vlm_model_specs
    from docling.utils.api_image_request import api_image_request

    pdf_path = sorted(input_dir.glob("*.pdf"))[0]
    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[page_index]
    image = page.render(scale=2.0).to_pil()

    vlm_options = copy.deepcopy(vlm_model_specs.GRANITEDOCLING_VLLM_API)
    vlm_options.url = vllm_url
    vlm_options.params["model"] = model
    vlm_options.params["max_tokens"] = max_tokens
    vlm_options.params["skip_special_tokens"] = False

    started = time.perf_counter()
    text, tokens, stop_reason = api_image_request(
        image=image,
        prompt=vlm_options.prompt,
        url=vlm_options.url,
        timeout=vlm_options.timeout,
        **{**vlm_options.params, "temperature": vlm_options.temperature},
    )

    debug = {
        "filename": pdf_path.name,
        "page_index": page_index,
        "image_size": image.size,
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "tokens": tokens,
        "stop_reason": getattr(stop_reason, "value", str(stop_reason)),
        "chars": len(text),
        "starts_with": text[:200],
        "ends_with": text[-200:],
        "raw_output_path": str(output_dir / "debug_raw_page.txt"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text(Path(debug["raw_output_path"]), text)
    write_json(output_dir / "debug_one_page.json", debug)
    return debug


def run(
    input_dir: Path,
    output_dir: Path,
    vllm_url: str,
    models_url: str,
    model: str,
    concurrency: int,
    max_tokens: int,
    sequential: bool,
) -> list[dict[str, Any]]:
    from docling.datamodel import vlm_model_specs
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline

    pdfs = sorted(input_dir.glob("*.pdf"))
    output_dir.mkdir(parents=True, exist_ok=True)

    server_metadata = check_vllm_server(models_url)
    runtime_metadata = collect_runtime_metadata("cuda")
    runtime_metadata.update(
        {
            "vllm_url": vllm_url,
            "models_url": models_url,
            "model": model,
            "concurrency": concurrency,
            "max_tokens": max_tokens,
            "document_mode": "sequential" if sequential else "batched",
            "server": server_metadata,
        }
    )
    write_json(output_dir / "runtime.json", runtime_metadata)

    if not server_metadata["available"]:
        raise RuntimeError(
            f"vLLM server is not reachable at {models_url}. "
            "Start it with `docker compose -f experiments/docker-compose.vllm.yml up`."
        )

    vlm_options = copy.deepcopy(vlm_model_specs.GRANITEDOCLING_VLLM_API)
    vlm_options.url = vllm_url
    vlm_options.concurrency = concurrency
    vlm_options.params["model"] = model
    vlm_options.params["max_tokens"] = max_tokens
    vlm_options.params["skip_special_tokens"] = False

    pipeline_options = VlmPipelineOptions(
        enable_remote_services=True,
        vlm_options=vlm_options,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline,
                pipeline_options=pipeline_options,
            ),
        }
    )

    if sequential:
        results = []
        for pdf_path in pdfs:
            result = convert_pdf(converter, pdf_path, output_dir)
            result["runtime"] = runtime_metadata
            write_json(Path(result["metadata_path"]), result)
            results.append(result)
    else:
        results = convert_pdfs_batched(converter, pdfs, output_dir)
        for result in results:
            result["runtime"] = runtime_metadata
            write_json(Path(result["metadata_path"]), result)

    write_json(output_dir / "summary.json", results)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Docling Granite VLM through vLLM.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--vllm-url", default=DEFAULT_VLLM_URL)
    parser.add_argument("--models-url", default=DEFAULT_MODELS_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--sequential", action="store_true")
    parser.add_argument("--check-server", action="store_true")
    parser.add_argument("--debug-one-page", action="store_true")
    parser.add_argument("--page-index", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.check_server:
        print(json.dumps(check_vllm_server(args.models_url), indent=2, sort_keys=True))
        return
    if args.debug_one_page:
        print(
            json.dumps(
                debug_one_page(
                    input_dir=args.input_dir,
                    output_dir=args.output_dir,
                    vllm_url=args.vllm_url,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    page_index=args.page_index,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return

    results = run(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        vllm_url=args.vllm_url,
        models_url=args.models_url,
        model=args.model,
        concurrency=args.concurrency,
        max_tokens=args.max_tokens,
        sequential=args.sequential,
    )
    successes = sum(1 for row in results if row["status"] == "success")
    print(f"{PARSER_NAME}: {successes}/{len(results)} PDFs converted")
    print(f"Outputs: {args.output_dir}")


if __name__ == "__main__":
    main()
