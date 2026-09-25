"""Dump a PDF's text, page by page, with **pypdf and nothing else** (039 批②).

This module exists because of one constraint: pypdf must not become a project
dependency. It is imported *only* when a caller asks for a PDF's text, and the
caller (`parts fetch`) runs it in whichever interpreter has pypdf — usually an
isolated venv (`python -m venv .tmp_pdfenv && .tmp_pdfenv/bin/python -m pip
install pypdf`), reached through ``BOARDWISE_PDF_PYTHON``. Nothing else in
boardwise imports it, so an install without pypdf loses exactly one feature and
fails loudly when it is asked for.

Output format: one line of marker per page, then that page's text::

    <<<page 1>>>
    …text…
    <<<page 2>>>
    …

The markers are what makes a *page number* available to the fact extractor, and a
page number is what a fact's provenance has to cite — a fact that cannot name its
page does not enter the library (011b §2.3).
"""

from __future__ import annotations

import sys

PAGE_MARKER = "<<<page {number}>>>"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m boardwise.pdf_text <file.pdf> [more.pdf …]", file=sys.stderr)
        return 2
    try:
        from pypdf import PdfReader  # noqa: PLC0415 - the whole point of the module
    except ImportError as exc:  # pragma: no cover - exercised on a machine without pypdf
        print(
            "pdf_text: pypdf is not importable in this interpreter "
            f"({exc}). Install it in an isolated venv and point "
            "BOARDWISE_PDF_PYTHON at that interpreter:\n"
            "  python -m venv .tmp_pdfenv\n"
            "  .tmp_pdfenv/Scripts/python.exe -m pip install pypdf\n"
            "  set BOARDWISE_PDF_PYTHON=.tmp_pdfenv/Scripts/python.exe",
            file=sys.stderr,
        )
        return 3
    for path in args:
        try:
            reader = PdfReader(path)
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            print(f"pdf_text: {path}: cannot read: {exc}", file=sys.stderr)
            return 4
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - one page, not the document
                text = f"(page {number} failed to extract: {exc})"
            print(PAGE_MARKER.format(number=number))
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
