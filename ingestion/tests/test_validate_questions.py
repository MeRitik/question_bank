from __future__ import annotations

import json
from pathlib import Path

from src.validate_questions import load_questions, load_raw_pages, main, validate_questions


def write_raw(path: Path, question_id: str = "111") -> Path:
    path.write_text(
        """==================== PAGE 4 ====================

Q.1 What is inheritance?
Ans
A. One
B. Two
C. Three
D. Four
Question Type : MCQ
Question ID : {question_id}
Option 1 ID : 11
Option 2 ID : 12
Option 3 ID : 13
Option 4 ID : 14
Status : Answered
Chosen Option : C
""".replace("{question_id}", question_id),
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


def write_question_file(path: Path, *, paper_file: str, question_number: int, question_id: str, page: int, question_text: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "paper": {
                    "file": paper_file,
                    "year": 2025,
                    "exam_date": "2025-11-03",
                    "shift": 1,
                    "paper": "Paper II",
                    "subject": "Computer Science",
                    "language": "English",
                },
                "questions": [
                    {
                        "question_number": question_number,
                        "source": {
                            "page": page,
                            "source_question_id": question_id,
                        },
                        "question": question_text,
                        "options": {
                            "A": "One",
                            "B": "Two",
                            "C": "Three",
                            "D": "Four",
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


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


def test_load_questions_reads_directory_of_files(tmp_path: Path) -> None:
    questions_dir = tmp_path / "parsed"
    questions_dir.mkdir()

    write_question_file(
        questions_dir / "paper-a.json",
        paper_file="paper-a.txt",
        question_number=1,
        question_id="111",
        page=4,
        question_text="What is inheritance?",
    )
    write_question_file(
        questions_dir / "paper-b.json",
        paper_file="paper-b.txt",
        question_number=2,
        question_id="222",
        page=5,
        question_text="What does CPU stand for?",
    )

    questions = load_questions(questions_dir)

    assert len(questions) == 2
    assert questions[0]["paper"]["file"] == "paper-a.txt"
    assert questions[1]["source"]["source_question_id"] == "222"


def test_main_validates_questions_directory(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    write_raw(raw_dir / "paper-a.txt")
    write_raw(raw_dir / "paper-b.txt", question_id="222")

    questions_dir = tmp_path / "parsed"
    questions_dir.mkdir()
    write_question_file(
        questions_dir / "paper-a.json",
        paper_file="paper-a.txt",
        question_number=1,
        question_id="111",
        page=4,
        question_text="What is inheritance?",
    )
    write_question_file(
        questions_dir / "paper-b.json",
        paper_file="paper-b.txt",
        question_number=2,
        question_id="222",
        page=4,
        question_text="What is inheritance?",
    )

    markdown_report = tmp_path / "validated" / "question_validation_report.md"
    json_report = tmp_path / "validated" / "question_validation_report.json"

    exit_code = main(
        [
            "--questions-dir",
            str(questions_dir),
            "--raw-dir",
            str(raw_dir),
            "--markdown-report",
            str(markdown_report),
            "--json-report",
            str(json_report),
        ]
    )

    assert exit_code == 0
    assert markdown_report.exists()
    assert json_report.exists()
