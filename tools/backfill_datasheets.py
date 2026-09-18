"""Fill ``datasheetPdfUrl`` on the curated library (task 008b, tail).

    python tools/backfill_datasheets.py --library blocklib/parts.json

A board's device attributes carry a **web page** (`Datasheet`) and not a file, so
every harvested entry starts with an empty ``datasheetPdfUrl``. The product page
knows it::

    GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=<C-number>
      -> {"code":200,"result":{ ..., "pdfUrl":"https://datasheet.lcsc.com/..." }}

Measured on this machine 2026-09-17 with `C2977777`.

The rules this file exists to keep:

* **Failure leaves a blank, never a guess.** Three outcomes are kept apart —
  answered with a URL, answered without one, and could not be asked. Only the
  first writes a value.
* **The network lives behind a seam.** ``backfill(..., fetcher=...)`` takes the
  fetcher; no test builds the real one, and the real one is constructed only by
  the CLI when nobody injected one.
* **Idempotent.** A part that already carries a URL is skipped unless
  ``--refresh`` asks for it, so a second run on a complete library writes
  nothing.
* **Reproducible.** Each link is also written to the corrections sidecar, which
  every harvest applies — so the library stays a deterministic function of its
  sources plus that file, and `harvest_parts.py --check` keeps meaning what it
  says.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from boardwise.core.parts import (  # noqa: E402
    DatasheetOverride,
    LibraryCorrections,
    PartError,
    PartLibrary,
    load_corrections,
    load_parts,
    save_corrections,
    save_parts,
)
from boardwise.engines.catalog import (  # noqa: E402
    ProductFetcher,
    fetch_product_detail,
    urllib_product_fetcher,
)


#: The note stored on every entry the service answered for. Deliberately free of
#: timestamps and run details: it is part of a committed artifact that has to be
#: reproducible byte for byte, so it says *where the fact comes from*, and
#: nothing about the run that fetched it.
DATASHEET_NOTE = (
    "datasheet PDF link read from the LCSC product page; recorded in the "
    "corrections sidecar because a board declares a datasheet web page and not "
    "a file, so an offline harvest cannot derive it."
)

CORRECTIONS_FILE = "blocklib/parts.corrections.json"


class BackfillReport:
    """What happened to every entry — the four buckets are all reported.

    A plain class, not a dataclass: this file is loaded by path from the tests
    and Python 3.14's `dataclasses` requires the defining module to be in
    `sys.modules`, which a path-loaded module is not.
    """

    def __init__(self) -> None:
        #: ``(lcsc, url)`` for entries that gained a URL.
        self.filled: list[tuple[str, str]] = []
        #: Entries that already carried a URL and were left alone.
        self.kept: list[str] = []
        #: ``(lcsc, reason)``: the service answered, and there is no PDF.
        self.answered_without_pdf: list[tuple[str, str]] = []
        #: ``(lcsc, reason)``: the service could not be asked.
        self.failed: list[tuple[str, str]] = []
        #: Entries with nothing to look up.
        self.skipped: list[tuple[str, str]] = []
        #: What belongs in the corrections sidecar, keyed by C-number. Only ever
        #: the bucket that answered with a URL.
        self.records: dict[str, DatasheetOverride] = {}

    @property
    def ok(self) -> bool:
        """True when every entry either got a URL or already had one."""
        return not self.failed

    def render(self) -> list[str]:
        lines = [
            f"filled {len(self.filled)}, kept {len(self.kept)}, "
            f"no PDF at source {len(self.answered_without_pdf)}, "
            f"could not ask {len(self.failed)}, no C-number {len(self.skipped)}"
        ]
        for lcsc, reason in self.failed:
            lines.append(f"  could not ask {lcsc}: {reason}")
        for lcsc, reason in self.answered_without_pdf:
            lines.append(f"  no PDF on the product page for {lcsc}: {reason}")
        for lcsc, reason in self.skipped:
            lines.append(f"  skipped {lcsc or '(none)'}: {reason}")
        return lines


def backfill(
    library: PartLibrary,
    *,
    fetcher: ProductFetcher,
    refresh: bool = False,
    limit: int | None = None,
) -> BackfillReport:
    """Look up each entry's datasheet link and write the ones that answer.

    ``fetcher`` is required rather than defaulted here: an optional argument
    that silently reaches a network is exactly what the tests must not be able
    to trigger, so the *caller* decides, and the CLI is the only caller that
    passes the real one.
    """
    report = BackfillReport()
    looked_up = 0
    for entry in library.parts:
        if limit is not None and looked_up >= limit:
            break
        if not entry.lcsc:
            report.skipped.append((entry.key, "the entry carries no C-number"))
            continue
        if entry.datasheetPdfUrl and not refresh:
            report.kept.append(entry.lcsc)
            continue
        looked_up += 1
        detail = fetch_product_detail(fetcher, entry.lcsc)
        if detail.pdf_url:
            entry.datasheetPdfUrl = detail.pdf_url
            report.records[entry.lcsc] = DatasheetOverride(
                lcsc=entry.lcsc, pdfUrl=detail.pdf_url, note=DATASHEET_NOTE
            )
            report.filled.append((entry.lcsc, detail.pdf_url))
        elif detail.answered:
            # The part exists and the page simply has no PDF: a fact about the
            # part, and the field stays empty for it.
            report.answered_without_pdf.append(
                (entry.lcsc, "; ".join(detail.notes) or "no pdfUrl")
            )
        else:
            report.failed.append(
                (entry.lcsc, "; ".join(detail.notes) or "no answer")
            )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_datasheets",
        description="Fill datasheetPdfUrl from the LCSC product page (task 008b tail).",
    )
    parser.add_argument(
        "--library",
        default="blocklib/parts.json",
        help="The part library to fill (default: blocklib/parts.json).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch entries that already carry a URL instead of skipping them.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Look up at most N entries (a partial run; the rest are untouched).",
    )
    parser.add_argument(
        "--corrections-file",
        default=CORRECTIONS_FILE,
        help=(
            "The sidecar the links are recorded in, so an offline harvest can "
            f"reproduce them (default: {CORRECTIONS_FILE}). `-` records none, "
            "leaving the library a thing only a re-fetch could reproduce."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing anything.",
    )
    parser.add_argument("--json", action="store_true", help="Print the whole library.")
    return parser


def _cli(argv: list[str] | None = None, *, fetcher: ProductFetcher | None = None) -> int:
    """The command. ``fetcher`` is injectable so a test drives it without a network."""
    args = build_parser().parse_args(argv)
    try:
        library = load_parts(args.library)
    except PartError as exc:
        print(f"backfill_datasheets: {exc}", file=sys.stderr)
        return 2
    if not library.parts:
        print(f"backfill_datasheets: {args.library} holds no entries", file=sys.stderr)
        return 2

    try:
        corrections = (
            LibraryCorrections()
            if args.corrections_file == "-"
            else load_corrections(args.corrections_file)
        )
    except PartError as exc:
        print(f"backfill_datasheets: {exc}", file=sys.stderr)
        return 2

    report = backfill(
        library,
        fetcher=fetcher or urllib_product_fetcher,
        refresh=args.refresh,
        limit=args.limit,
    )
    for line in report.render():
        print(line)

    if args.dry_run:
        print("dry run: nothing was written")
        return 0 if report.ok else 1

    if report.filled:
        corrections.datasheets.update(report.records)
        sidecar = save_corrections(corrections, args.corrections_file)
        written = save_parts(library, args.library)
        print(
            f"written: {written} ({len(library.parts)} entries); "
            f"{sidecar} now holds {len(corrections.datasheets)} datasheet link(s)"
        )
        if args.json:
            from boardwise.core.parts import library_to_json

            print(json.dumps(library_to_json(library), indent=2, ensure_ascii=False))
    else:
        print(
            f"nothing to write: {args.library} already carries every URL the "
            "service answered"
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(_cli())
