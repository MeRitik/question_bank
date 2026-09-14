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
PAPER_PREFIX_RE = re.compile(
    r"^(?P<base>.+?)-Class-\d+-\d+-(?P<subject>.+?)-Official-(?P<paper>.+)$"
)
PAPER_DATE_RE = re.compile(
    r"^(?P<day>\d{2})-(?P<month>[A-Za-z]{3})-(?P<year>\d{4})-Shift-(?P<shift>\d+)-(?P<language>[A-Za-z]+)$"
)
QUESTION_RE = re.compile(r'^"?\s*Q\.(?P<number>\d+)(?:\s+(?P<text>.*))?\s*$')
OPTION_RE = re.compile(r"^(?P<label>[A-D])\.\s*(?P<text>.*)$")
METADATA_RE = re.compile(
    r"^(?P<key>Question Type|Question ID|Option [1-4] ID|Status|Chosen Option)"
    r"\s*:\s*(?P<value>.*)$"
)

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

LANGUAGE_ALIASES = {
    "Eng": "English",
    "Hin": "Hindi",
}


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


def parse_paper_metadata(raw_path: Path) -> dict[str, Any]:
    try:
        prefix, date_suffix = raw_path.stem.split("-Held-On_-", 1)
    except ValueError:
        raise ParseError(f"raw file name does not match expected pattern: {raw_path.name}")

    prefix_match = PAPER_PREFIX_RE.match(prefix)
    date_match = PAPER_DATE_RE.match(date_suffix)

    if not prefix_match or not date_match:
        raise ParseError(f"raw file name does not match expected pattern: {raw_path.name}")

    month = date_match.group("month")
    if month not in MONTHS:
        raise ParseError(f"unsupported month in raw file name: {raw_path.name}")

    language = date_match.group("language")

    return {
        "file": raw_path.name,
        "year": int(date_match.group("year")),
        "exam_date": f"{date_match.group('year')}-{MONTHS[month]:02d}-{date_match.group('day')}",
        "shift": int(date_match.group("shift")),
        "paper": prefix_match.group("paper").replace("-", " "),
        "subject": prefix_match.group("subject").replace("-", " "),
        "language": LANGUAGE_ALIASES.get(language, language),
    }


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
            parsed_lines.append(
                ParsedRawLine(page=current_page, text=line)
            )

    return parsed_lines


def detect_question_start(
    lines: list[ParsedRawLine],
    index: int
) -> QuestionStart | None:

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


def find_question_starts(
    lines: list[ParsedRawLine]
) -> list[QuestionStart]:

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
    start: QuestionStart,
    block_lines: list[str],
) -> tuple[dict[str, Any], list[str]]:

    warnings: list[str] = []

    content = [start.inline_text] if start.inline_text else []
    content.extend(block_lines[start.consumed_lines:])

    try:
        ans_index = next(
            index
            for index, line in enumerate(content)
            if line.strip() == "Ans"
        )
    except StopIteration:
        ans_index = -1
        warnings.append(
            f"{start.question_label}: missing Ans marker"
        )

    question_lines = (
        content[:ans_index]
        if ans_index >= 0
        else content
    )

    after_ans = (
        content[ans_index + 1:]
        if ans_index >= 0
        else []
    )

    options: dict[str, str] = {}
    metadata: dict[str, str] = {}
    current_option: str | None = None

    for line in after_ans:
        option_match = OPTION_RE.match(line.strip())
        metadata_match = METADATA_RE.match(line.strip())

        if option_match:
            current_option = option_match.group("label")

            options[current_option] = option_match.group(
                "text"
            ).rstrip()

            continue

        if metadata_match:
            current_option = None

            metadata[
                metadata_match.group("key")
            ] = metadata_match.group("value").strip()

            continue

        if current_option is not None:
            existing = options[current_option]

            options[current_option] = join_preserved(
                [existing, line]
            )

    for option_label in ("A", "B", "C", "D"):
        if option_label not in options:
            warnings.append(
                f"{start.question_label}: missing option {option_label}"
            )

    if "Question ID" not in metadata:
        warnings.append(
            f"{start.question_label}: missing Question ID"
        )

    if "Chosen Option" not in metadata:
        warnings.append(
            f"{start.question_label}: missing Chosen Option"
        )

    question = {
        "question_number": start.question_number,
        "question": join_preserved(question_lines),
        "source": {
            "page": start.page,
            "source_question_id": metadata.get("Question ID"),
        },
        "options": {
            label: options[label]
            for label in ("A", "B", "C", "D")
            if label in options
        },
    }

    return question, warnings


def parse_raw_file(
    raw_path: Path,
    max_questions: int = DEFAULT_EXPECTED_QUESTIONS,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:

    lines = read_raw_lines(raw_path)
    starts = find_question_starts(lines)
    paper = parse_paper_metadata(raw_path)

    questions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, start in enumerate(starts):

        if start.question_number > max_questions:
            continue

        next_index = len(lines)

        for later_start in starts[index + 1:]:
            if later_start.question_number > start.question_number:
                next_index = later_start.index
                break

        block_lines = [
            line.text
            for line in lines[start.index:next_index]
        ]

        question, block_warnings = parse_question_block(
            start,
            block_lines,
        )

        questions.append(question)
        warnings.extend(block_warnings)

    questions.sort(
        key=lambda item: item["question_number"]
    )

    return paper, questions, warnings


def validation_counts(
    questions: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, int]:

    question_ids = [
        question.get("source", {}).get("source_question_id")
        for question in questions
        if question.get("source", {}).get("source_question_id")
    ]

    duplicate_ids = (
        len(question_ids) - len(set(question_ids))
    )

    return {
        "questions_parsed": len(questions),
        "four_options": sum(
            1
            for question in questions
            if len(question.get("options", {})) == 4
        ),
        "missing_options": sum(
            1
            for question in questions
            if len(question.get("options", {})) != 4
        ),
        "question_ids_present": len(question_ids),
        "duplicate_question_ids": duplicate_ids,
        "pages_recorded": sum(
            1
            for question in questions
            if question.get("source", {}).get("page") is not None
        ),
        "parse_warnings": len(warnings),
    }


def render_validation_report(
    file_results: list[dict[str, Any]],
    all_questions: list[dict[str, Any]],
    all_warnings: list[str],
) -> str:

    report_lines = []

    report_lines.append("# Parse Report")
    report_lines.append("")

    report_lines.append("## Overall")
    report_lines.append("")

    total_questions = len(all_questions)

    question_ids = [
        q.get("source", {}).get("source_question_id")
        for q in all_questions
        if q.get("source", {}).get("source_question_id")
    ]

    duplicate_ids = (
        len(question_ids) - len(set(question_ids))
    )

    total_four_options = sum(
        1
        for q in all_questions
        if len(q.get("options", {})) == 4
    )

    report_lines.append(
        f"- Files parsed: {len(file_results)}"
    )
    report_lines.append(
        f"- Questions parsed: {total_questions}"
    )
    report_lines.append(
        f"- Four-option questions: {total_four_options}"
    )
    report_lines.append(
        f"- Questions with missing options: "
        f"{total_questions - total_four_options}"
    )
    report_lines.append(
        f"- Source question IDs: {len(question_ids)}"
    )
    report_lines.append(
        f"- Duplicate source question IDs: {duplicate_ids}"
    )
    report_lines.append(
        f"- Warnings: {len(all_warnings)}"
    )

    report_lines.append("")
    report_lines.append("## Per File")
    report_lines.append("")

    for result in file_results:
        report_lines.append(
            f"### {result['file']}"
        )
        report_lines.append("")

        report_lines.append(
            f"- Expected questions: {result['expected']}"
        )
        report_lines.append(
            f"- Parsed questions: {result['parsed']}"
        )
        report_lines.append(
            f"- Four options: {result['four_options']}"
        )
        report_lines.append(
            f"- Missing options: {result['missing_options']}"
        )
        report_lines.append(
            f"- Source IDs: {result['question_ids']}"
        )
        report_lines.append(
            f"- Duplicate IDs: {result['duplicate_ids']}"
        )
        report_lines.append(
            f"- Warnings: {result['warnings']}"
        )

        status = (
            "PASS"
            if result["parsed"] == result["expected"]
            and result["missing_options"] == 0
            and result["duplicate_ids"] == 0
            and result["warnings"] == 0
            else "REVIEW"
        )

        report_lines.append(
            f"- Status: **{status}**"
        )

        report_lines.append("")

    if all_warnings:
        report_lines.append("## Warnings")
        report_lines.append("")

        for warning in all_warnings:
            report_lines.append(f"- {warning}")

        report_lines.append("")

    return "\n".join(report_lines)


def write_outputs(
    payload: dict[str, Any] | list[dict[str, Any]],
    report: str,
    output_path: Path,
    report_path: Path,
) -> None:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    report_path.write_text(
        report,
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Parse one or all page-preserving raw TXT files "
            "into questions.json."
        )
    )

    parser.add_argument(
        "raw_path",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Optional raw .txt file. "
            "If omitted, all .txt files in --raw-dir are parsed."
        ),
    )

    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Directory containing raw .txt files.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output questions JSON path.",
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Validation report path.",
    )

    parser.add_argument(
        "--expected",
        type=int,
        default=DEFAULT_EXPECTED_QUESTIONS,
        help="Expected question count per paper.",
    )

    return parser


def resolve_raw_files(
    raw_path: Path | None,
    raw_dir: Path,
) -> list[Path]:

    if raw_path is not None:

        if not raw_path.exists():
            raise ParseError(
                f"raw input does not exist: {raw_path}"
            )

        if raw_path.suffix.lower() != ".txt":
            raise ParseError(
                f"raw input is not a .txt file: {raw_path}"
            )

        return [raw_path]

    raw_files = sorted(
        raw_dir.glob("*.txt")
    )

    if not raw_files:
        raise ParseError(
            f"no raw .txt files found in {raw_dir}"
        )

    return raw_files


def main(argv: list[str] | None = None) -> int:

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw_files = resolve_raw_files(
            args.raw_path,
            args.raw_dir,
        )

        paper_payloads: list[dict[str, Any]] = []
        all_questions: list[dict[str, Any]] = []
        all_warnings: list[str] = []
        file_results: list[dict[str, Any]] = []

        for raw_file in raw_files:

            print(f"Parsing: {raw_file.name}")

            paper, questions, warnings = parse_raw_file(
                raw_file,
                max_questions=args.expected,
            )

            paper_payloads.append(
                {
                    "paper": paper,
                    "questions": questions,
                }
            )

            counts = validation_counts(
                questions,
                warnings,
            )

            file_results.append({
                "file": raw_file.name,
                "expected": args.expected,
                "parsed": counts["questions_parsed"],
                "four_options": counts["four_options"],
                "missing_options": counts["missing_options"],
                "question_ids": counts["question_ids_present"],
                "duplicate_ids": counts["duplicate_question_ids"],
                "warnings": counts["parse_warnings"],
            })

            all_questions.extend(questions)

            all_warnings.extend(
                f"{raw_file.name}: {warning}"
                for warning in warnings
            )

            print(
                f"  Questions: {counts['questions_parsed']}"
            )
            print(
                f"  Warnings:  {counts['parse_warnings']}"
            )

        report = render_validation_report(
            file_results,
            all_questions,
            all_warnings,
        )

        write_outputs(
            paper_payloads[0] if len(paper_payloads) == 1 else paper_payloads,
            report,
            args.output,
            args.report,
        )

    except ParseError as exc:
        print(
            f"Failed: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print(report)
    print(f"Output: {args.output}")
    print(f"Report: {args.report}")

    has_errors = any(
        result["parsed"] != result["expected"]
        or result["missing_options"] > 0
        or result["duplicate_ids"] > 0
        for result in file_results
    )

    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())