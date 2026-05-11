from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import platform
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

PARSER_NAME = "docling_standard"
DEFAULT_INPUT_DIR = Path("data")
DEFAULT_OUTPUT_DIR = Path("experiments/out") / PARSER_NAME
DEFAULT_OCR_BATCH_SIZE = 32
DEFAULT_LAYOUT_BATCH_SIZE = 32
DEFAULT_TABLE_BATCH_SIZE = 4
NIXOS_CUDA_LIBRARY_PATH = "/run/opengl-driver/lib"


def slugify_pdf_name(pdf_path: Path) -> str:
    return pdf_path.stem.replace(" ", "_")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def export_document_dict(document: Any) -> dict[str, Any]:
    if hasattr(document, "export_to_dict"):
        return document.export_to_dict()
    if hasattr(document, "model_dump"):
        return document.model_dump(mode="json")
    if hasattr(document, "dict"):
        return document.dict()
    return {"repr": repr(document)}


def convert_pdf(converter: Any, pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    doc_name = slugify_pdf_name(pdf_path)
    doc_dir = output_dir / doc_name
    markdown_path = doc_dir / "document.md"
    json_path = doc_dir / "document.json"
    metadata_path = doc_dir / "metadata.json"

    started = time.perf_counter()
    metadata: dict[str, Any] = {
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

    try:
        result = converter.convert(pdf_path)
        document = result.document
        write_text(markdown_path, document.export_to_markdown())
        write_json(json_path, export_document_dict(document))
        metadata["status"] = "success"
    except Exception as exc:  # noqa: BLE001 - batch experiments should record failures.
        metadata["status"] = "error"
        metadata["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        metadata["runtime_seconds"] = round(time.perf_counter() - started, 3)
        write_json(metadata_path, metadata)

    return metadata


def collect_runtime_metadata(device: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "requested_device": device,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "ld_library_path": os.environ.get("LD_LIBRARY_PATH"),
        "libcuda_find_library": ctypes.util.find_library("cuda"),
        "nvidia_smi": collect_nvidia_smi(),
    }
    metadata["libcuda_loadable"] = is_library_loadable("libcuda.so.1")
    try:
        import torch

        cuda_available = torch.cuda.is_available()
        metadata.update(
            {
                "torch_version": torch.__version__,
                "torch_cuda_version": torch.version.cuda,
                "cuda_available": cuda_available,
                "cuda_device": torch.cuda.get_device_name(0) if cuda_available else None,
                "cuda_device_count": torch.cuda.device_count(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - runtime metadata should not block parsing.
        metadata["torch_error"] = f"{type(exc).__name__}: {exc}"
    return metadata


def collect_nvidia_smi() -> dict[str, Any]:
    if shutil.which("nvidia-smi") is None:
        return {"available": False, "error": "nvidia-smi not found on PATH"}

    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics should preserve failures.
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    return {"available": True, "output": completed.stdout.strip()}


def is_library_loadable(name: str) -> bool:
    try:
        ctypes.CDLL(name)
    except OSError:
        return False
    return True


def cuda_warning(metadata: dict[str, Any]) -> str | None:
    if metadata.get("cuda_available") is True:
        return None

    if Path(NIXOS_CUDA_LIBRARY_PATH).exists() and not metadata.get("libcuda_loadable"):
        return (
            "PyTorch cannot load CUDA, but /run/opengl-driver/lib exists. "
            "On NixOS, retry with LD_LIBRARY_PATH=/run/opengl-driver/lib:$LD_LIBRARY_PATH."
        )

    if metadata.get("nvidia_smi", {}).get("available") and not metadata.get("libcuda_loadable"):
        return (
            "nvidia-smi works, but libcuda.so.1 is not loadable by Python. "
            "Set LD_LIBRARY_PATH to the directory containing the NVIDIA driver libraries."
        )

    return "PyTorch reports CUDA unavailable. Verify the installed torch wheel and driver library path."


def print_cuda_diagnostics(metadata: dict[str, Any]) -> None:
    print(json.dumps(metadata, indent=2, sort_keys=True))
    warning = cuda_warning(metadata)
    if warning:
        print(f"\nCUDA diagnostic: {warning}")


def run(
    input_dir: Path,
    output_dir: Path,
    device: str,
    ocr_batch_size: int,
    layout_batch_size: int,
    table_batch_size: int,
) -> list[dict[str, Any]]:
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import RapidOcrOptions, ThreadedPdfPipelineOptions
    from docling.document_converter import DocumentConverter
    from docling.document_converter import PdfFormatOption

    pdfs = sorted(input_dir.glob("*.pdf"))
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline_options = ThreadedPdfPipelineOptions(
        ocr_batch_size=ocr_batch_size,
        layout_batch_size=layout_batch_size,
        table_batch_size=table_batch_size,
    )
    if device != "auto":
        pipeline_options.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice(device),
        )
    pipeline_options.ocr_options = RapidOcrOptions(lang=["en"])

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    runtime_metadata = collect_runtime_metadata(device)
    runtime_metadata.update(
        {
            "ocr_batch_size": ocr_batch_size,
            "layout_batch_size": layout_batch_size,
            "table_batch_size": table_batch_size,
        }
    )
    write_json(output_dir / "runtime.json", runtime_metadata)
    if device == "cuda":
        warning = cuda_warning(runtime_metadata)
        if warning:
            print(f"CUDA diagnostic: {warning}")

    results = []
    for pdf_path in pdfs:
        result = convert_pdf(converter, pdf_path, output_dir)
        result["runtime"] = runtime_metadata
        metadata_path = Path(result["metadata_path"])
        write_json(metadata_path, result)
        results.append(result)
    write_json(output_dir / "summary.json", results)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Docling Standard over sample PDFs.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda", "mps"], default="auto")
    parser.add_argument("--ocr-batch-size", type=int, default=DEFAULT_OCR_BATCH_SIZE)
    parser.add_argument("--layout-batch-size", type=int, default=DEFAULT_LAYOUT_BATCH_SIZE)
    parser.add_argument("--table-batch-size", type=int, default=DEFAULT_TABLE_BATCH_SIZE)
    parser.add_argument(
        "--diagnose-cuda",
        action="store_true",
        help="Print CUDA/PyTorch/NVIDIA driver diagnostics and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.diagnose_cuda:
        print_cuda_diagnostics(collect_runtime_metadata(args.device))
        return

    results = run(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        device=args.device,
        ocr_batch_size=args.ocr_batch_size,
        layout_batch_size=args.layout_batch_size,
        table_batch_size=args.table_batch_size,
    )
    successes = sum(1 for row in results if row["status"] == "success")
    print(f"{PARSER_NAME}: {successes}/{len(results)} PDFs converted")
    print(f"Outputs: {args.output_dir}")


if __name__ == "__main__":
    main()
