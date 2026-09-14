from __future__ import annotations

from pathlib import Path

import fitz

from src.extract_pdf import collect_pdfs, extract_pdf, main, page_separator, run


def make_pdf(path: Path, page_texts: list[str]) -> Path:
    doc = fitz.open()
    try:
        for text in page_texts:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        doc.save(path)
    finally:
        doc.close()
    return path


def test_successful_extraction_from_text_pdf(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "paper.pdf", ["Question 1", "Question 2"])

    result = extract_pdf(pdf_path, output_dir=tmp_path / "raw")

    assert result.page_count == 2
    assert result.character_count > 0
    assert result.output_path.exists()
    output = result.output_path.read_text(encoding="utf-8")
    assert "Question 1" in output
    assert "Question 2" in output


def test_page_separators_and_numbering_are_present(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "paper.pdf", ["First", "Second"])

    result = extract_pdf(pdf_path, output_dir=tmp_path / "raw")
    output = result.output_path.read_text(encoding="utf-8")

    assert page_separator(1) in output
    assert page_separator(2) in output
    assert "PAGE 0" not in output


def test_output_is_utf8(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "unicode.pdf", ["Unicode: caf\u00e9"])

    result = extract_pdf(pdf_path, output_dir=tmp_path / "raw")

    assert "caf\u00e9" in result.output_path.read_text(encoding="utf-8")


def test_empty_page_detection(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "empty.pdf", ["Text page", ""])

    result = extract_pdf(pdf_path, output_dir=tmp_path / "raw")

    assert result.empty_pages == (2,)
    output = result.output_path.read_text(encoding="utf-8")
    assert page_separator(2) in output


def test_missing_input_handling(tmp_path: Path) -> None:
    exit_code = main([str(tmp_path / "missing.pdf")])

    assert exit_code == 1


def test_multiple_pdfs_in_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_pdf(input_dir / "b.pdf", ["B"])
    make_pdf(input_dir / "a.pdf", ["A"])
    output_dir = tmp_path / "raw"

    exit_code = run(input_dir, output_dir=output_dir)

    assert exit_code == 0
    assert (output_dir / "a.txt").exists()
    assert (output_dir / "b.txt").exists()


def test_output_filename_generation_uses_pdf_stem(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "sample-paper.pdf", ["Text"])

    result = extract_pdf(pdf_path, output_dir=tmp_path / "raw")

    assert result.output_path.name == "sample-paper.txt"


def test_existing_output_is_not_overwritten_without_flag(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "paper.pdf", ["New text"])
    output_dir = tmp_path / "raw"
    output_dir.mkdir()
    output_path = output_dir / "paper.txt"
    output_path.write_text("existing", encoding="utf-8")

    exit_code = run(pdf_path, output_dir=output_dir)

    assert exit_code == 1
    assert output_path.read_text(encoding="utf-8") == "existing"


def test_overwrite_replaces_existing_output_when_flag_is_set(tmp_path: Path) -> None:
    pdf_path = make_pdf(tmp_path / "paper.pdf", ["New text"])
    output_dir = tmp_path / "raw"
    output_dir.mkdir()
    output_path = output_dir / "paper.txt"
    output_path.write_text("existing", encoding="utf-8")

    exit_code = run(pdf_path, output_dir=output_dir, overwrite=True)

    assert exit_code == 0
    assert "New text" in output_path.read_text(encoding="utf-8")


def test_batch_continues_after_failed_pdf_and_returns_nonzero(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_pdf(input_dir / "good.pdf", ["Good"])
    (input_dir / "bad.pdf").write_text("not a real pdf", encoding="utf-8")
    output_dir = tmp_path / "raw"

    exit_code = run(input_dir, output_dir=output_dir)

    assert exit_code == 1
    assert (output_dir / "good.txt").exists()
    assert not (output_dir / "bad.txt").exists()


def test_collect_pdfs_rejects_non_pdf_file(tmp_path: Path) -> None:
    text_path = tmp_path / "notes.txt"
    text_path.write_text("hello", encoding="utf-8")

    try:
        collect_pdfs(text_path)
    except Exception as exc:
        assert "not a PDF" in str(exc)
    else:
        raise AssertionError("collect_pdfs should reject non-PDF files")
