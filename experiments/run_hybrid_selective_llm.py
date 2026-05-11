from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from run_docling_standard import write_json, write_text

PARSER_NAME = "hybrid_selective_llm"
DEFAULT_DOC_SOURCE_DIR = Path("experiments/out/docling_standard")
DEFAULT_OUTPUT_DIR = Path("experiments/out") / PARSER_NAME
DEFAULT_LLM_URL = os.environ.get("CIVIC_LLM_URL")
DEFAULT_LLM_MODEL = os.environ.get("CIVIC_LLM_MODEL", "local-civic-parser")

ITEM_RE = re.compile(r"^(?:[-*]\s*)?(?P<num>\d{1,3})(?P<suffix>[A-Z])?[\.)]\s+(?P<title>.+)")
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+)")
TABLE_RE = re.compile(r"^\|.+\|$")
VOTE_RE = re.compile(r"\b(result|motion/second|ayes?|nays?|noes?|abstain|approved|unanimous)\b", re.I)
ACTION_RE = re.compile(r"\b(accepted|approved|adopted|directed|ratified|continued|denied|filed)\b", re.I)
PUBLIC_COMMENT_RE = re.compile(r"\b(public comment|addressed the board|via zoom|in chambers)\b", re.I)
DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b",
    re.I,
)
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
OCR_JOIN_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+){2,}\b")


@dataclass
class Section:
    section_id: str
    filename: str
    doc_type: str
    kind: str
    title: str
    item_number: str | None
    text: str
    start_line: int
    end_line: int


@dataclass
class SectionScore:
    section_id: str
    filename: str
    doc_type: str
    kind: str
    item_number: str | None
    title: str
    char_count: int
    word_count: int
    table_lines: int
    ocr_joined_tokens: int
    reasons: list[str] = field(default_factory=list)
    handoff_type: str | None = None
    llm_status: str = "not_requested"
    llm_output_path: str | None = None
    prompt_path: str | None = None


def load_standard_rows(source_dir: Path) -> list[dict[str, Any]]:
    summary_path = source_dir / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))

    rows = []
    for metadata_path in sorted(source_dir.glob("*/metadata.json")):
        rows.append(json.loads(metadata_path.read_text(encoding="utf-8")))
    return rows


def infer_doc_type(filename: str, text: str) -> str:
    filename_lower = filename.lower()
    if "minutes" in filename_lower:
        return "minutes"
    if "agenda" in filename_lower:
        return "agenda"

    haystack = text[:2000].lower()
    if "action summary minutes" in haystack:
        return "minutes"
    if "agenda" in haystack:
        return "agenda"
    return "unknown"


def is_noise_heading(title: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", title.lower())
    return normalized in {
        "santacruzcounty",
        "boardofsupervisorsagenda",
        "santacruzcountyboardofsupervisorsagenda",
    }


def split_sections(filename: str, markdown: str) -> list[Section]:
    doc_type = infer_doc_type(filename, markdown)
    lines = markdown.splitlines()
    sections: list[Section] = []
    current: dict[str, Any] | None = None

    def flush(end_line: int) -> None:
        nonlocal current
        if current is None:
            return
        text = "\n".join(current["lines"]).strip()
        if text:
            sections.append(
                Section(
                    section_id=f"{Path(filename).stem}:{len(sections) + 1:04d}",
                    filename=filename,
                    doc_type=doc_type,
                    kind=current["kind"],
                    title=current["title"],
                    item_number=current.get("item_number"),
                    text=text,
                    start_line=current["start_line"],
                    end_line=end_line,
                )
            )
        current = None

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        item_match = ITEM_RE.match(stripped)
        heading_match = HEADING_RE.match(stripped)

        starts_section = False
        section_kind = "body"
        section_title = "Preamble"
        item_number: str | None = None

        if item_match:
            starts_section = True
            section_kind = "item"
            item_number = f"{item_match.group('num')}{item_match.group('suffix') or ''}"
            section_title = item_match.group("title").strip()
        elif heading_match:
            title = heading_match.group("title").strip()
            if not is_noise_heading(title):
                starts_section = True
                section_kind = "heading"
                section_title = title

        if starts_section:
            flush(line_no - 1)
            current = {
                "kind": section_kind,
                "title": section_title,
                "item_number": item_number,
                "start_line": line_no,
                "lines": [line],
            }
        elif current is None:
            current = {
                "kind": "preamble",
                "title": "Preamble",
                "item_number": None,
                "start_line": line_no,
                "lines": [line],
            }
        else:
            current["lines"].append(line)

    flush(len(lines))
    return sections


def score_section(section: Section) -> SectionScore:
    words = re.findall(r"\b\w+\b", section.text)
    table_lines = sum(1 for line in section.text.splitlines() if TABLE_RE.match(line.strip()))
    ocr_joined_tokens = len(OCR_JOIN_RE.findall(section.text))
    lower_title = section.title.lower()
    reasons: list[str] = []
    handoff_type: str | None = None

    has_votes = bool(VOTE_RE.search(section.text))
    has_actions = bool(ACTION_RE.search(section.text))
    has_public_comment = bool(PUBLIC_COMMENT_RE.search(section.text))

    if section.doc_type == "minutes" and section.kind == "item" and (has_votes or has_actions):
        reasons.append("minutes_item_action_or_vote")
        handoff_type = "minutes_action_vote_parse"
    if "attendance" in section.text.lower() or "present" in lower_title or "absent" in section.text.lower():
        reasons.append("attendance_or_presence")
        handoff_type = handoff_type or "attendance_parse"
    if table_lines >= 2:
        reasons.append("markdown_table")
        handoff_type = handoff_type or "table_parse"
    if has_public_comment:
        reasons.append("public_comment_counts")
        handoff_type = handoff_type or "public_comment_parse"
    if MONEY_RE.search(section.text) or DATE_RE.search(section.text):
        reasons.append("money_or_date_entities")
        handoff_type = handoff_type or "agenda_entity_parse"
    if section.doc_type == "agenda" and section.kind == "item":
        reasons.append("agenda_item_classification")
        handoff_type = handoff_type or "agenda_item_classify"
    if ocr_joined_tokens >= 4:
        reasons.append("possible_ocr_spacing_damage")
        handoff_type = "ocr_repair_then_parse"
    if len(words) > 450:
        reasons.append("long_section")
        handoff_type = handoff_type or "long_section_summarize_parse"

    return SectionScore(
        section_id=section.section_id,
        filename=section.filename,
        doc_type=section.doc_type,
        kind=section.kind,
        item_number=section.item_number,
        title=section.title[:240],
        char_count=len(section.text),
        word_count=len(words),
        table_lines=table_lines,
        ocr_joined_tokens=ocr_joined_tokens,
        reasons=reasons,
        handoff_type=handoff_type,
    )


def build_prompt(section: Section, score: SectionScore) -> str:
    schema_hint = {
        "section_id": section.section_id,
        "doc_type": section.doc_type,
        "handoff_type": score.handoff_type,
        "item_number": section.item_number,
        "title": section.title,
        "normalized_title": None,
        "agenda_item_type": None,
        "actions": [],
        "motion": None,
        "second": None,
        "result": None,
        "ayes": None,
        "nays": None,
        "abstain": None,
        "public_comment": None,
        "dates": [],
        "money_amounts": [],
        "needs_human_review": True,
    }
    return (
        "/no_think\n"
        "Return one compact JSON object only. Do not include analysis, markdown, prose, or code fences. "
        "Use null for unknown scalar values and [] for unknown lists. "
        "Set needs_human_review=true when evidence is ambiguous.\n\n"
        f"JSON shape:\n{json.dumps(schema_hint, separators=(',', ':'))}\n\n"
        f"Source section:\n{section.text}"
    )


def call_openai_compatible(
    llm_url: str,
    model: str,
    prompt: str,
    timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You extract structured civic meeting data. Return only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        llm_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def run(
    source_dir: Path,
    output_dir: Path,
    max_handoffs_per_doc: int,
    llm_url: str | None,
    llm_model: str,
    llm_timeout: int,
    llm_max_tokens: int,
    llm_concurrency: int,
    limit_handoffs: int | None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    if llm_url:
        llm_output_dir = output_dir / "llm_outputs"
        if llm_output_dir.exists():
            for old_output in llm_output_dir.glob("*.json"):
                old_output.unlink()

    rows = load_standard_rows(source_dir)
    all_scores: list[SectionScore] = []
    all_sections: list[dict[str, Any]] = []
    pending_calls: list[tuple[Section, SectionScore, str]] = []

    for row in rows:
        markdown_path = Path(row["markdown_path"])
        markdown = markdown_path.read_text(encoding="utf-8")
        sections = split_sections(row["filename"], markdown)
        scored = [score_section(section) for section in sections]
        selected_ids = {
            score.section_id
            for score in sorted(
                (score for score in scored if score.reasons),
                key=lambda item: (
                    "possible_ocr_spacing_damage" not in item.reasons,
                    item.word_count * -1,
                    item.section_id,
                ),
            )[:max_handoffs_per_doc]
        }

        for section, score in zip(sections, scored, strict=True):
            all_sections.append(asdict(section))
            if score.section_id in selected_ids:
                prompt = build_prompt(section, score)
                prompt_path = output_dir / "prompts" / f"{score.section_id.replace(':', '_')}.txt"
                write_text(prompt_path, prompt)
                score.prompt_path = str(prompt_path)
                score.llm_status = "dry_run"

                if llm_url:
                    pending_calls.append((section, score, prompt))
            all_scores.append(score)

    if limit_handoffs is not None:
        pending_calls = pending_calls[:limit_handoffs]

    llm_calls = execute_llm_calls(
        pending_calls=pending_calls,
        output_dir=output_dir,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_timeout=llm_timeout,
        llm_max_tokens=llm_max_tokens,
        llm_concurrency=llm_concurrency,
    )

    score_rows = [asdict(score) for score in all_scores]
    handoff_rows = [row for row in score_rows if row["prompt_path"]]
    write_json(output_dir / "sections.json", all_sections)
    write_json(output_dir / "section_scores.json", score_rows)
    write_json(
        output_dir / "summary.json",
        {
            "parser": PARSER_NAME,
            "source_dir": str(source_dir),
            "section_count": len(all_sections),
            "handoff_count": len(handoff_rows),
            "llm_calls": llm_calls,
            "llm_mode": "enabled" if llm_url else "dry_run",
            "llm_concurrency": llm_concurrency if llm_url else 0,
            "llm_max_tokens": llm_max_tokens if llm_url else 0,
            "limit_handoffs": limit_handoffs,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "handoffs_by_type": count_by(handoff_rows, "handoff_type"),
            "handoffs_by_doc": count_by(handoff_rows, "filename"),
        },
    )
    return score_rows


def execute_llm_calls(
    pending_calls: list[tuple[Section, SectionScore, str]],
    output_dir: Path,
    llm_url: str | None,
    llm_model: str,
    llm_timeout: int,
    llm_max_tokens: int,
    llm_concurrency: int,
) -> int:
    if not llm_url or not pending_calls:
        return 0

    def execute_one(call: tuple[Section, SectionScore, str]) -> tuple[SectionScore, str]:
        _section, score, prompt = call
        llm_output_path = output_dir / "llm_outputs" / f"{score.section_id.replace(':', '_')}.json"
        started = time.perf_counter()
        try:
            llm_response = call_openai_compatible(
                llm_url=llm_url,
                model=llm_model,
                prompt=prompt,
                timeout=llm_timeout,
                max_tokens=llm_max_tokens,
            )
            payload = {
                "status": "success",
                "runtime_seconds": round(time.perf_counter() - started, 3),
                "response": llm_response,
            }
            write_json(llm_output_path, payload)
            return score, "success"
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            write_json(
                llm_output_path,
                {
                    "status": "error",
                    "runtime_seconds": round(time.perf_counter() - started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return score, "error"

    call_count = 0
    max_workers = max(1, min(llm_concurrency, len(pending_calls)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(execute_one, call) for call in pending_calls]
        for future in as_completed(futures):
            score, status = future.result()
            score.llm_status = status
            score.llm_output_path = str(
                output_dir / "llm_outputs" / f"{score.section_id.replace(':', '_')}.json"
            )
            call_count += 1

    return call_count


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect civic document sections that merit selective LLM parsing."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_DOC_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-handoffs-per-doc", type=int, default=12)
    parser.add_argument("--llm-url", default=DEFAULT_LLM_URL)
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-timeout", type=int, default=60)
    parser.add_argument("--llm-max-tokens", type=int, default=768)
    parser.add_argument("--llm-concurrency", type=int, default=8)
    parser.add_argument("--limit-handoffs", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = run(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        max_handoffs_per_doc=args.max_handoffs_per_doc,
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        llm_timeout=args.llm_timeout,
        llm_max_tokens=args.llm_max_tokens,
        llm_concurrency=args.llm_concurrency,
        limit_handoffs=args.limit_handoffs,
    )
    handoff_count = sum(1 for row in rows if row["prompt_path"])
    print(f"{PARSER_NAME}: {handoff_count}/{len(rows)} sections selected for LLM handoff")
    print(f"Outputs: {args.output_dir}")


if __name__ == "__main__":
    main()
