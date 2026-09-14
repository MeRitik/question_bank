from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RAW_DIR = Path("raw")
DEFAULT_OUTPUT_PATH = Path("parsed") / "questions.json"
DEFAULT_REPORT_PATH = Path("validated") / "parse_report.md"
DEFAULT_EXPECTED_QUESTIONS = 150

PAGE_RE = re.compile(r"^={20} PAGE (?P<page>\d+) ={20}\s*$")
QUESTION_RE = re.compile(r'^"?\s*Q\.(?P<number>\d+)(?:\s+(?P<text>.*))?\s*$')
OPTION_RE = re.compile(r"^(?P<label>[A-D])\.\s*(?P<text>.*)$")
METADATA_RE = re.compile(r"^(?P<key>Question Type|Question ID|Option [1-4] ID|Status|Chosen Option)\s*:\s*(?P<value>.*)$")


class ParseError(Exception):
    """Raised when raw question text cannot be parsed."""


@dataclass(frozen=True)
class ParsedRawLine:
    page: int
    text: str


@dataclass(frozen=True)
class QuestionStart:
    index: int
    page: int
    question_number: int
    question_label: str
    inline_text: str
    consumed_lines: int


def read_raw_lines(raw_path: Path) -> list[ParsedRawLine]:
    if not raw_path.exists():
        raise ParseError(f"raw input does not exist: {raw_path}")
    if raw_path.suffix.lower() != ".txt":
        raise ParseError(f"raw input is not a .txt file: {raw_path}")

    current_page: int | None = None
    parsed_lines: list[ParsedRawLine] = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        page_match = PAGE_RE.match(line)
        if page_match:
            current_page = int(page_match.group("page"))
            continue
        if current_page is not None:
            parsed_lines.append(ParsedRawLine(page=current_page, text=line))
    return parsed_lines


def detect_question_start(lines: list[ParsedRawLine], index: int) -> QuestionStart | None:
    match = QUESTION_RE.match(lines[index].text.strip())
    if not match:
        return None

    number_text = match.group("number")
    inline_text = (match.group("text") or "").strip()
    consumed_lines = 1

    if not inline_text and index + 1 < len(lines):
        next_text = lines[index + 1].text.strip()
        if re.fullmatch(r"\d", next_text):
            number_text = f"{number_text}{next_text}"
            consumed_lines = 2

    return QuestionStart(
        index=index,
        page=lines[index].page,
        question_number=int(number_text),
        question_label=f"Q.{number_text}",
        inline_text=inline_text,
        consumed_lines=consumed_lines,
    )


def find_question_starts(lines: list[ParsedRawLine]) -> list[QuestionStart]:
    starts: list[QuestionStart] = []
    index = 0
    while index < len(lines):
        start = detect_question_start(lines, index)
        if start is None:
            index += 1
            continue
        starts.append(start)
        index += start.consumed_lines
    return starts


def join_preserved(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def parse_question_block(
    raw_path: Path,
    start: QuestionStart,
    block_lines: list[str],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    content = [start.inline_text] if start.inline_text else []
    content.extend(block_lines[start.consumed_lines:])

    try:
        ans_index = next(index for index, line in enumerate(content) if line.strip() == "Ans")
    except StopIteration:
        ans_index = -1
        warnings.append(f"{start.question_label}: missing Ans marker")

    question_lines = content[:ans_index] if ans_index >= 0 else content
    after_ans = content[ans_index + 1 :] if ans_index >= 0 else []

    options: dict[str, dict[str, str | None]] = {}
    metadata: dict[str, str] = {}
    current_option: str | None = None

    for line in after_ans:
        option_match = OPTION_RE.match(line.strip())
        metadata_match = METADATA_RE.match(line.strip())

        if option_match:
            current_option = option_match.group("label")
            options[current_option] = {
                "label": current_option,
                "text": option_match.group("text").rstrip(),
                "option_id": None,
            }
            continue

        if metadata_match:
            current_option = None
            metadata[metadata_match.group("key")] = metadata_match.group("value").strip()
            continue

        if current_option is not None:
            existing = options[current_option]["text"] or ""
            options[current_option]["text"] = join_preserved([existing, line])

    for option_number, option_label in enumerate(("A", "B", "C", "D"), start=1):
        option_id = metadata.get(f"Option {option_number} ID")
        if option_label in options:
            options[option_label]["option_id"] = option_id
        else:
            warnings.append(f"{start.question_label}: missing option {option_label}")

    if "Question ID" not in metadata:
        warnings.append(f"{start.question_label}: missing Question ID")
    if "Chosen Option" not in metadata:
        warnings.append(f"{start.question_label}: missing Chosen Option")

    question = {
        "source": {
            "file": raw_path.name,
            "page": start.page,
            "question_number": start.question_number,
            "source_question_id": metadata.get("Question ID"),
        },
        "question": join_preserved(question_lines),
        "options": {
            label: options[label]["text"]
            for label in ("A", "B", "C", "D")
            if label in options
        },
    }
    return question, warnings


def parse_raw_file(raw_path: Path, max_questions: int = DEFAULT_EXPECTED_QUESTIONS) -> tuple[list[dict[str, Any]], list[str]]:
    lines = read_raw_lines(raw_path)
    starts = find_question_starts(lines)
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, start in enumerate(starts):
        if start.question_number > max_questions:
            continue

        next_index = len(lines)
        for later_start in starts[index + 1 :]:
            if later_start.question_number > start.question_number:
                next_index = later_start.index
                break

        block_lines = [line.text for line in lines[start.index:next_index]]
        question, block_warnings = parse_question_block(raw_path, start, block_lines)
        questions.append(question)
        warnings.extend(block_warnings)

    questions.sort(key=lambda item: item["source"]["question_number"])
    return questions, warnings


def validation_counts(questions: list[dict[str, Any]], warnings: list[str]) -> dict[str, int]:
    question_ids = [
        question.get("source", {}).get("source_question_id")
        for question in questions
        if question.get("source", {}).get("source_question_id")
    ]
    duplicate_ids = len(question_ids) - len(set(question_ids))
    return {
        "questions_parsed": len(questions),
        "four_options": sum(1 for question in questions if len(question.get("options", {})) == 4),
        "missing_options": sum(1 for question in questions if len(question.get("options", {})) != 4),
        "question_ids_present": len(question_ids),
        "duplicate_question_ids": duplicate_ids,
        "pages_recorded": sum(1 for question in questions if question.get("source", {}).get("page") is not None),
        "chosen_options_present": len(questions) - sum(1 for warning in warnings if "missing Chosen Option" in warning),
        "parse_warnings": len(warnings),
    }


def render_validation_report(expected: int, questions: list[dict[str, Any]], warnings: list[str]) -> str:
    counts = validation_counts(questions, warnings)
    report = f"""Questions expected: {expected}
Questions parsed:   {counts["questions_parsed"]}

Options:
  4 options: {counts["four_options"]}
  Missing: {counts["missing_options"]}

Question IDs:
  Present: {counts["question_ids_present"]}
  Duplicate: {counts["duplicate_question_ids"]}

Pages:
  Recorded: {counts["pages_recorded"]}

Chosen options:
  Present: {counts["chosen_options_present"]}

Parse warnings:
  {counts["parse_warnings"]}
"""
    if warnings:
        report += "\nWarnings:\n"
        report += "\n".join(f"- {warning}" for warning in warnings)
        report += "\n"
    return report


def write_outputs(
    questions: list[dict[str, Any]],
    report: str,
    output_path: Path,
    report_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(report, encoding="utf-8", newline="\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse page-preserving raw text into questions.json.")
    parser.add_argument("raw_path", type=Path, nargs="?", default=None, help="Raw .txt file to parse.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="Directory used when raw_path is omitted.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output questions JSON path.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="Validation report path.")
    parser.add_argument("--expected", type=int, default=DEFAULT_EXPECTED_QUESTIONS, help="Expected question count.")
    return parser


def resolve_raw_path(raw_path: Path | None, raw_dir: Path) -> Path:
    if raw_path is not None:
        return raw_path

    raw_files = sorted(raw_dir.glob("*.txt"))
    if not raw_files:
        raise ParseError(f"no raw .txt files found in {raw_dir}")
    if len(raw_files) > 1:
        raise ParseError(f"multiple raw .txt files found in {raw_dir}; pass one explicitly")
    return raw_files[0]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw_path = resolve_raw_path(args.raw_path, args.raw_dir)
        questions, warnings = parse_raw_file(raw_path, max_questions=args.expected)
        report = render_validation_report(args.expected, questions, warnings)
        write_outputs(questions, report, args.output, args.report)
    except ParseError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    print(report)
    print(f"Output: {args.output}")
    print(f"Report: {args.report}")
    return 0 if not warnings and len(questions) == args.expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
