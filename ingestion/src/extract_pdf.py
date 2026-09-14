from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz


PAGE_SEPARATOR_TEMPLATE = "{equals} PAGE {page_number} {equals}"
DEFAULT_OUTPUT_DIR = Path("raw")


class ExtractionError(Exception):
    """Raised when a PDF cannot be extracted safely."""


@dataclass(frozen=True)
class ExtractionResult:
    source_path: Path
    output_path: Path
    page_count: int
    character_count: int
    empty_pages: tuple[int, ...]


@dataclass(frozen=True)
class ExtractionFailure:
    source_path: Path
    reason: str


def normalize_extracted_text(text: str) -> str:
    """Apply only conservative source-preserving normalization."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n"))


def page_separator(page_number: int) -> str:
    return PAGE_SEPARATOR_TEMPLATE.format(equals="=" * 20, page_number=page_number)


def collect_pdfs(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise ExtractionError(f"input path does not exist: {input_path}")

    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ExtractionError(f"input file is not a PDF: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise ExtractionError(f"input path is neither a file nor directory: {input_path}")

    pdfs = sorted(path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
    if not pdfs:
        raise ExtractionError(f"directory contains no PDF files: {input_path}")
    return pdfs


def extract_pdf(
    pdf_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    overwrite: bool = False,
) -> ExtractionResult:
    if pdf_path.suffix.lower() != ".pdf":
        raise ExtractionError("input file is not a PDF")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{pdf_path.stem}.txt"
    if output_path.exists() and not overwrite:
        raise ExtractionError(f"output already exists: {output_path} (use --overwrite to replace it)")

    doc = None
    try:
        doc = fitz.open(pdf_path)
        if doc.needs_pass:
            raise ExtractionError("encrypted or password-protected PDF")

        page_count = doc.page_count
        if page_count == 0:
            raise ExtractionError("PDF has zero pages")

        parts: list[str] = []
        empty_pages: list[int] = []
        extracted_character_count = 0

        for page_index in range(page_count):
            page_number = page_index + 1
            try:
                page = doc.load_page(page_index)
                text = normalize_extracted_text(page.get_text("text"))
            except Exception as exc:  # pragma: no cover - hard to trigger with real PyMuPDF pages
                raise ExtractionError(f"extraction failed on page {page_number}: {exc}") from exc

            if text.strip() == "":
                empty_pages.append(page_number)

            extracted_character_count += len(text)
            parts.append(f"{page_separator(page_number)}\n\n{text}\n")

        output_text = "\n".join(parts)
        output_path.write_text(output_text, encoding="utf-8", newline="\n")
        return ExtractionResult(
            source_path=pdf_path,
            output_path=output_path,
            page_count=page_count,
            character_count=extracted_character_count,
            empty_pages=tuple(empty_pages),
        )
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"PDF cannot be opened or read: {exc}") from exc
    finally:
        if doc is not None:
            doc.close()


def print_success(result: ExtractionResult) -> None:
    print(result.source_path.name)
    print(f"Pages: {result.page_count}")
    print(f"Characters: {result.character_count:,}")
    print(f"Empty pages: {len(result.empty_pages)}")
    if result.empty_pages:
        pages = ", ".join(str(page) for page in result.empty_pages)
        print(f"Empty page numbers: {pages}")
    print(f"Output: {result.output_path}")
    print()


def print_failure(failure: ExtractionFailure) -> None:
    print(f"{failure.source_path.name}")
    print(f"Failed: {failure.reason}")
    print()


def run(input_path: Path, output_dir: Path, overwrite: bool = False, verbose: bool = False) -> int:
    try:
        pdfs = collect_pdfs(input_path)
    except ExtractionError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    successes: list[ExtractionResult] = []
    failures: list[ExtractionFailure] = []

    for pdf_path in pdfs:
        if verbose:
            print(f"Processing: {pdf_path}")
        try:
            result = extract_pdf(pdf_path, output_dir=output_dir, overwrite=overwrite)
        except ExtractionError as exc:
            failure = ExtractionFailure(source_path=pdf_path, reason=str(exc))
            failures.append(failure)
            print_failure(failure)
            continue

        successes.append(result)
        print_success(result)

    print("Extraction complete.")
    print()

    if successes:
        print("Successful:")
        for result in successes:
            print(f"* {result.source_path.name} -> {result.output_path}")
        print()

    if failures:
        print("Failed:")
        for failure in failures:
            print(f"* {failure.source_path.name} -> {failure.reason}")
        print()

    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract existing PDF text layers into page-preserving UTF-8 text files."
    )
    parser.add_argument("input_path", type=Path, help="PDF file or directory containing PDF files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated .txt files. Default: raw",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing output .txt file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show additional processing details.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(
        input_path=args.input_path,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
