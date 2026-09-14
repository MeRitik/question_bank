from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS_PATH = Path("parsed") / "questions.json"
DEFAULT_RAW_DIR = Path("raw")
DEFAULT_MARKDOWN_REPORT_PATH = Path("validated") / "question_validation_report.md"
DEFAULT_JSON_REPORT_PATH = Path("validated") / "question_validation_report.json"

PAGE_RE = re.compile(r"^={20} PAGE (?P<page>\d+) ={20}\s*$")
EXPECTED_TOP_LEVEL_KEYS = {"source", "question", "options"}
EXPECTED_SOURCE_KEYS = {"file", "page", "question_number", "source_question_id"}
EXPECTED_OPTION_KEYS = {"A", "B", "C", "D"}
SUSPICIOUS_MARKERS = ("�", "Â", "â€", "â€¦", "<br", "</", "&nbsp;")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    question_number: int | None = None
    source_question_id: str | None = None
    page: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "question_number": self.question_number,
            "source_question_id": self.source_question_id,
            "page": self.page,
        }


class ValidationError(Exception):
    """Raised when validation inputs cannot be read."""


def load_questions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValidationError(f"questions JSON does not exist: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValidationError("questions JSON must contain a top-level list")
    return data


def load_raw_pages(raw_dir: Path) -> dict[str, dict[int, str]]:
    if not raw_dir.exists():
        raise ValidationError(f"raw directory does not exist: {raw_dir}")

    pages_by_file: dict[str, dict[int, str]] = {}
    for raw_path in sorted(raw_dir.glob("*.txt")):
        current_page: int | None = None
        current_lines: list[str] = []
        pages: dict[int, str] = {}

        for line in raw_path.read_text(encoding="utf-8").splitlines():
            page_match = PAGE_RE.match(line)
            if page_match:
                if current_page is not None:
                    pages[current_page] = "\n".join(current_lines)
                current_page = int(page_match.group("page"))
                current_lines = []
                continue
            if current_page is not None:
                current_lines.append(line)

        if current_page is not None:
            pages[current_page] = "\n".join(current_lines)

        pages_by_file[raw_path.name] = pages

    if not pages_by_file:
        raise ValidationError(f"no raw .txt files found in {raw_dir}")
    return pages_by_file


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def source_context(question: dict[str, Any]) -> tuple[int | None, str | None, int | None]:
    source = question.get("source") if isinstance(question.get("source"), dict) else {}
    number = source.get("question_number") if isinstance(source.get("question_number"), int) else None
    source_id = source.get("source_question_id") if isinstance(source.get("source_question_id"), str) else None
    page = source.get("page") if isinstance(source.get("page"), int) else None
    return number, source_id, page


def validate_structure(index: int, question: Any) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(question, dict):
        return [
            Finding(
                severity="error",
                code="invalid_question_object",
                message=f"Item {index} is not a JSON object.",
            )
        ]

    number, source_id, page = source_context(question)

    actual_keys = set(question)
    if actual_keys != EXPECTED_TOP_LEVEL_KEYS:
        findings.append(
            Finding(
                severity="error",
                code="unexpected_top_level_keys",
                message=f"Expected keys {sorted(EXPECTED_TOP_LEVEL_KEYS)}, found {sorted(actual_keys)}.",
                question_number=number,
                source_question_id=source_id,
                page=page,
            )
        )

    source = question.get("source")
    if not isinstance(source, dict):
        findings.append(Finding("error", "missing_source", "Missing or invalid source object.", number, source_id, page))
    else:
        missing_source = EXPECTED_SOURCE_KEYS - set(source)
        extra_source = set(source) - EXPECTED_SOURCE_KEYS
        if missing_source or extra_source:
            findings.append(
                Finding(
                    "error",
                    "invalid_source_keys",
                    f"Missing source keys {sorted(missing_source)}, extra source keys {sorted(extra_source)}.",
                    number,
                    source_id,
                    page,
                )
            )
        if not isinstance(source.get("file"), str) or not source.get("file"):
            findings.append(Finding("error", "invalid_source_file", "source.file must be a non-empty string.", number, source_id, page))
        if not isinstance(source.get("page"), int) or source.get("page", 0) <= 0:
            findings.append(Finding("error", "invalid_page", "source.page must be a positive integer.", number, source_id, page))
        if not isinstance(source.get("question_number"), int) or source.get("question_number", 0) <= 0:
            findings.append(
                Finding("error", "invalid_question_number", "source.question_number must be a positive integer.", number, source_id, page)
            )
        if not isinstance(source.get("source_question_id"), str) or not source.get("source_question_id"):
            findings.append(
                Finding("error", "invalid_source_question_id", "source.source_question_id must be a non-empty string.", number, source_id, page)
            )

    if not isinstance(question.get("question"), str) or not question.get("question", "").strip():
        findings.append(Finding("error", "invalid_question_text", "question must be a non-empty string.", number, source_id, page))

    options = question.get("options")
    if not isinstance(options, dict):
        findings.append(Finding("error", "invalid_options", "options must be an object.", number, source_id, page))
    else:
        option_keys = set(options)
        if option_keys != EXPECTED_OPTION_KEYS:
            findings.append(
                Finding(
                    "error",
                    "invalid_option_keys",
                    f"Expected option keys A-D, found {sorted(option_keys)}.",
                    number,
                    source_id,
                    page,
                )
            )
        for label in sorted(EXPECTED_OPTION_KEYS & option_keys):
            if not isinstance(options.get(label), str) or not options.get(label, "").strip():
                findings.append(Finding("error", "invalid_option_text", f"Option {label} must be non-empty text.", number, source_id, page))

    return findings


def validate_against_raw(question: dict[str, Any], raw_pages: dict[str, dict[int, str]]) -> list[Finding]:
    findings: list[Finding] = []
    number, source_id, page = source_context(question)
    source = question.get("source", {})
    source_file = source.get("file")

    if not isinstance(source_file, str) or not isinstance(page, int):
        return findings

    pages = raw_pages.get(source_file)
    if pages is None:
        return [Finding("error", "missing_raw_file", f"Raw source file not found: {source_file}.", number, source_id, page)]

    page_text = pages.get(page)
    if page_text is None:
        return [Finding("error", "missing_raw_page", f"Page {page} not found in {source_file}.", number, source_id, page)]

    compact_page = compact_text(page_text)
    question_text = question.get("question")
    if isinstance(question_text, str) and compact_text(question_text) not in compact_page:
        findings.append(Finding("error", "question_not_on_source_page", "Question text was not found on its source page.", number, source_id, page))

    if isinstance(source_id, str) and source_id not in page_text:
        findings.append(Finding("error", "source_question_id_not_on_page", "Source question ID was not found on its source page.", number, source_id, page))

    options = question.get("options")
    if isinstance(options, dict):
        for label, option_text in options.items():
            if isinstance(option_text, str) and compact_text(option_text) not in compact_page:
                findings.append(
                    Finding("error", "option_not_on_source_page", f"Option {label} text was not found on its source page.", number, source_id, page)
                )

    return findings


def detect_duplicates(questions: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    number_counts: Counter[int] = Counter()
    id_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    by_number: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    by_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    by_text: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for question in questions:
        if not isinstance(question, dict):
            continue
        number, source_id, _page = source_context(question)
        if number is not None:
            number_counts[number] += 1
            by_number[number].append(question)
        if source_id:
            id_counts[source_id] += 1
            by_id[source_id].append(question)
        text = question.get("question")
        if isinstance(text, str):
            normalized = compact_text(text).lower()
            if normalized:
                text_counts[normalized] += 1
                by_text[normalized].append(question)

    for number, count in sorted(number_counts.items()):
        if count > 1:
            findings.append(Finding("error", "duplicate_question_number", f"Question number {number} appears {count} times.", number))

    for source_id, count in sorted(id_counts.items()):
        if count > 1:
            sample = by_id[source_id][0]
            number, _source_id, page = source_context(sample)
            findings.append(Finding("error", "duplicate_source_question_id", f"Source question ID {source_id} appears {count} times.", number, source_id, page))

    for normalized_text, count in sorted(text_counts.items()):
        if count > 1:
            sample = by_text[normalized_text][0]
            number, source_id, page = source_context(sample)
            findings.append(Finding("warning", "duplicate_question_text", f"Question text appears {count} times.", number, source_id, page))

    return findings


def detect_suspicious_extraction(question: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    number, source_id, page = source_context(question)
    text_fields: list[tuple[str, str]] = []

    question_text = question.get("question")
    if isinstance(question_text, str):
        text_fields.append(("question", question_text))

    options = question.get("options")
    if isinstance(options, dict):
        for label, option_text in sorted(options.items()):
            if isinstance(option_text, str):
                text_fields.append((f"option {label}", option_text))

        compact_options = [compact_text(value).lower() for value in options.values() if isinstance(value, str)]
        duplicate_option_texts = len(compact_options) - len(set(compact_options))
        if duplicate_option_texts:
            findings.append(Finding("warning", "duplicate_options", "Question has duplicate option text.", number, source_id, page))

    if isinstance(question_text, str) and len(compact_text(question_text)) < 8:
        findings.append(Finding("warning", "short_question_text", "Question text is unusually short.", number, source_id, page))

    for field_name, value in text_fields:
        for marker in SUSPICIOUS_MARKERS:
            if marker in value:
                findings.append(
                    Finding("warning", "suspicious_text_marker", f"{field_name} contains suspicious extraction marker {marker!r}.", number, source_id, page)
                )
                break

    return findings


def validate_questions(questions: list[dict[str, Any]], raw_pages: dict[str, dict[int, str]]) -> dict[str, Any]:
    findings: list[Finding] = []
    for index, question in enumerate(questions):
        findings.extend(validate_structure(index, question))
        if isinstance(question, dict):
            findings.extend(validate_against_raw(question, raw_pages))
            findings.extend(detect_suspicious_extraction(question))

    findings.extend(detect_duplicates(questions))

    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    option_counts = Counter(len(question.get("options", {})) for question in questions if isinstance(question, dict))
    pages_recorded = sum(
        1
        for question in questions
        if isinstance(question, dict) and isinstance(question.get("source", {}).get("page"), int)
    )
    ids = [
        question.get("source", {}).get("source_question_id")
        for question in questions
        if isinstance(question, dict) and question.get("source", {}).get("source_question_id")
    ]

    return {
        "summary": {
            "questions_validated": len(questions),
            "errors": len(errors),
            "warnings": len(warnings),
            "pages_recorded": pages_recorded,
            "source_question_ids_present": len(ids),
            "duplicate_source_question_ids": len(ids) - len(set(ids)),
            "option_count_distribution": {str(key): option_counts[key] for key in sorted(option_counts)},
        },
        "findings": [finding.to_dict() for finding in findings],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    findings = report["findings"]
    lines = [
        "# Question JSON Validation Report",
        "",
        "## Summary",
        "",
        f"- Questions validated: {summary['questions_validated']}",
        f"- Errors: {summary['errors']}",
        f"- Warnings: {summary['warnings']}",
        f"- Pages recorded: {summary['pages_recorded']}",
        f"- Source question IDs present: {summary['source_question_ids_present']}",
        f"- Duplicate source question IDs: {summary['duplicate_source_question_ids']}",
        f"- Option counts: {summary['option_count_distribution']}",
        "",
        "## Findings",
        "",
    ]

    if not findings:
        lines.append("No validation findings.")
    else:
        for finding in findings:
            context = []
            if finding.get("question_number") is not None:
                context.append(f"Q.{finding['question_number']}")
            if finding.get("page") is not None:
                context.append(f"page {finding['page']}")
            if finding.get("source_question_id"):
                context.append(f"id {finding['source_question_id']}")
            context_text = f" ({', '.join(context)})" if context else ""
            lines.append(f"- **{finding['severity'].upper()}** `{finding['code']}`{context_text}: {finding['message']}")

    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate finalized questions.json against source raw text.")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH, help="Path to parsed questions JSON.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="Directory containing source raw .txt files.")
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_MARKDOWN_REPORT_PATH, help="Human-readable report path.")
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT_PATH, help="Machine-readable report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        questions = load_questions(args.questions)
        raw_pages = load_raw_pages(args.raw_dir)
        report = validate_questions(questions, raw_pages)
        write_reports(report, args.markdown_report, args.json_report)
    except (ValidationError, json.JSONDecodeError) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    summary = report["summary"]
    print(render_markdown_report(report))
    print(f"Markdown report: {args.markdown_report}")
    print(f"JSON report: {args.json_report}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
