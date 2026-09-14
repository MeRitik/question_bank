from __future__ import annotations

import json
from pathlib import Path

from src.parse_questions import main, parse_raw_file, render_validation_report


def write_raw(path: Path, *, split_second_question: bool = False) -> Path:
    second_question = (
        """Q.10
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
"""
        if split_second_question
        else """Q.2 What does I stand for in CIA?
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
"""
    )

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
Chosen Option : C

==================== PAGE 5 ====================

"""
        + second_question,
        encoding="utf-8",
    )
    return path


RAW_FILENAME = (
    "Bihar-STET-Class-11-12-Computer-Science-"
    "Official-Paper-II-Held-On_-03-Nov-2025-Shift-1-Eng.txt"
)


def test_parse_raw_file_preserves_page_and_metadata(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / RAW_FILENAME, split_second_question=True)

    paper, questions, warnings = parse_raw_file(raw_path, max_questions=100)

    assert warnings == []
    assert paper["file"] == RAW_FILENAME
    assert paper["year"] == 2025
    assert paper["exam_date"] == "2025-11-03"
    assert paper["shift"] == 1
    assert paper["paper"] == "Paper II"
    assert paper["subject"] == "Computer Science"
    assert paper["language"] == "English"
    assert len(questions) == 2
    assert questions[0]["question_number"] == 1
    assert questions[0]["source"]["page"] == 4
    assert questions[0]["source"]["source_question_id"] == "111"
    assert questions[0]["options"]["C"] == "Three"
    assert len(questions[0]["options"]) == 4


def test_split_question_number_is_combined(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / RAW_FILENAME, split_second_question=True)

    _paper, questions, _warnings = parse_raw_file(raw_path, max_questions=100)

    assert questions[1]["question_number"] == 100


def test_validation_report_counts_clean_parse(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / RAW_FILENAME, split_second_question=True)
    _paper, questions, warnings = parse_raw_file(raw_path, max_questions=100)

    report = render_validation_report(
        [
            {
                "file": raw_path.name,
                "expected": 2,
                "parsed": 2,
                "four_options": 2,
                "missing_options": 0,
                "question_ids": 2,
                "duplicate_ids": 0,
                "warnings": 0,
            }
        ],
        questions,
        warnings,
    )

    assert "Files parsed: 1" in report
    assert "Questions parsed: 2" in report
    assert "Four-option questions: 2" in report
    assert "Warnings: 0" in report


def test_main_writes_questions_json_and_report(tmp_path: Path) -> None:
    raw_path = write_raw(tmp_path / RAW_FILENAME)
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
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["paper"]["file"] == raw_path.name
    assert len(output["questions"]) == 2
    assert set(output["questions"][0]) == {"question_number", "source", "question", "options"}
    assert report_path.exists()
