# BSEB STET Computer Science PDF Extraction

This is Step 1 of the question bank pipeline: deterministic extraction of existing PDF text layers into page-preserving UTF-8 text files.

It intentionally does not perform OCR, question parsing, answer extraction, topic classification, database writes, frontend work, embeddings, or AI enrichment.

## Python Version

Use Python 3.10 or newer.

## Installation

From this directory:

```bash
pip install -r requirements.txt
```

## Project Structure

```text
ingestion/
  input/          # source PDFs, not required for tests
  raw/            # generated text output
  src/
    extract_pdf.py
  tests/
  requirements.txt
  README.md
```

## Extract One PDF

```bash
python -m src.extract_pdf input/file.pdf
```

This creates:

```text
raw/file.txt
```

## Process a Directory

```bash
python -m src.extract_pdf input/
```

Directory processing is non-recursive and processes only `.pdf` files directly inside the supplied directory.

## Options

Use a different output directory:

```bash
python -m src.extract_pdf input/ --output-dir raw
```

Replace existing output files:

```bash
python -m src.extract_pdf input/file.pdf --overwrite
```

Show extra processing details:

```bash
python -m src.extract_pdf input/ --verbose
```

## Output Format

Each page is kept separate with a delimiter:

```text
==================== PAGE 1 ====================

<text from page 1>

==================== PAGE 2 ====================

<text from page 2>
```

Page numbers start at 1 and match the PDF page order.

## Raw Extraction Rules

The extractor uses PyMuPDF's text-layer extraction with `page.get_text("text")`.

It only:

- normalizes line endings to `\n`
- removes trailing whitespace at line ends
- writes UTF-8 text
- adds page separators

It does not correct spelling, infer missing text, remove headers or footers, join lines, split questions, detect options, or change question numbering.

## Error Handling

Existing `.txt` files are not overwritten unless `--overwrite` is used.

In directory mode, one failed PDF does not stop the rest of the batch. The command exits with a non-zero status if any file fails.

## Tests

```bash
pytest
```

The tests create small PDFs programmatically and do not require real BSEB papers.

## Parse Questions

After raw extraction, parse all 150 questions into JSON:

```bash
python -m src.parse_questions
```

This reads the single `.txt` file in `raw/` and writes:

```text
parsed/questions.json
validated/parse_report.md
```

You can also pass paths explicitly:

```bash
python -m src.parse_questions raw/file.txt --output parsed/questions.json --report validated/parse_report.md
```

The parser writes a compact JSON shape with source filename, original page number, question number, source question ID, question text, and A-D option text.

## Validate Questions

Validate the finalized JSON against the source raw text without modifying the JSON:

```bash
python -m src.validate_questions
```

This writes:

```text
validated/question_validation_report.md
validated/question_validation_report.json
```

The validation checks JSON structure, source file/page references, whether question and option text appear on the recorded source page, duplicate question numbers and source IDs, duplicate question text, duplicate options, and suspicious extraction markers such as mojibake or HTML fragments.
