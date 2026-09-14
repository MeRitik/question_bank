from __future__ import annotations

import json
from pathlib import Path

from src.parse_questions import main, parse_raw_file, render_validation_report


def write_raw(path: Path) -> Path:
    path.write_text(
        """==================== PAGE 4 ====================

Q.1 What is inheritance?
Ans
A. One
B. Two
C. Three
D. Four
Question Type : MCQ
Question ID : 111
Option 1 ID : 11
Option 2 ID : 12
Option 3 ID : 13
Option 4 ID : 14
Status : Answered
Chosen Option : C

==================== PAGE 5 ====================

Q.10
0
What does I stand for in CIA?
Ans
A. Indian
B. Individual
C. Income
D. Integrity
Question Type : MCQ
Question ID : 222
Option 1 ID : 21
Option 2 ID : 22
Option 3 ID : 23
Option 4 ID : 24
Status : Answered
Chosen Option : D
""",
        encoding="utf-8",
    )
    return path


def test_parse_raw_file_preserves_page_and_metadata(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / "paper.txt")

    questions, warnings = parse_raw_file(raw_path, max_questions=100)

    assert warnings == []
    assert len(questions) == 2
    assert questions[0]["source"]["page"] == 4
    assert questions[0]["source"]["source_question_id"] == "111"
    assert questions[0]["options"]["C"] == "Three"
    assert len(questions[0]["options"]) == 4


def test_split_question_number_is_combined(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / "paper.txt")

    questions, _warnings = parse_raw_file(raw_path, max_questions=100)

    assert questions[1]["source"]["question_number"] == 100


def test_validation_report_counts_clean_parse(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / "paper.txt")
    questions, warnings = parse_raw_file(raw_path, max_questions=100)

    report = render_validation_report(2, questions, warnings)

    assert "Questions expected: 2" in report
    assert "Questions parsed:   2" in report
    assert "  4 options: 2" in report
    assert "  0" in report


def test_main_writes_questions_json_and_report(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / "paper.txt")
    output_path = tmp_path / "parsed" / "questions.json"
    report_path = tmp_path / "validated" / "parse_report.md"

    exit_code = main(
        [
            str(raw_path),
            "--output",
            str(output_path),
            "--report",
            str(report_path),
            "--expected",
            "2",
        ]
    )

    assert exit_code == 0
    questions = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(questions) == 2
    assert set(questions[0]) == {"source", "question", "options"}
    assert report_path.exists()
