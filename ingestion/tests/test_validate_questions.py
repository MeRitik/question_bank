from __future__ import annotations

from pathlib import Path

from src.validate_questions import load_raw_pages, validate_questions


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
""",
        encoding="utf-8",
    )
    return path


def valid_question() -> dict:
    return {
        "source": {
            "file": "paper.txt",
            "page": 4,
            "question_number": 1,
            "source_question_id": "111",
        },
        "question": "What is inheritance?",
        "options": {
            "A": "One",
            "B": "Two",
            "C": "Three",
            "D": "Four",
        },
    }


def test_validation_accepts_valid_question_against_raw_page(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    write_raw(raw_dir / "paper.txt")

    report = validate_questions([valid_question()], load_raw_pages(raw_dir))

    assert report["summary"]["errors"] == 0
    assert report["summary"]["warnings"] == 0


def test_validation_detects_missing_source_text(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    write_raw(raw_dir / "paper.txt")
    question = valid_question()
    question["question"] = "Different text"

    report = validate_questions([question], load_raw_pages(raw_dir))

    assert report["summary"]["errors"] == 1
    assert report["findings"][0]["code"] == "question_not_on_source_page"


def test_validation_detects_duplicate_source_question_ids(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    write_raw(raw_dir / "paper.txt")
    first = valid_question()
    second = valid_question()
    second["source"] = dict(second["source"], question_number=2)

    report = validate_questions([first, second], load_raw_pages(raw_dir))

    codes = {finding["code"] for finding in report["findings"]}
    assert "duplicate_source_question_id" in codes


def test_validation_detects_suspicious_markers(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    write_raw(raw_dir / "paper.txt")
    question = valid_question()
    question["options"]["A"] = "One<br"

    report = validate_questions([question], load_raw_pages(raw_dir))

    codes = {finding["code"] for finding in report["findings"]}
    assert "suspicious_text_marker" in codes
