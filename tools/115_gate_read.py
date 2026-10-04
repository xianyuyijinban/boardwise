#!/usr/bin/env python3
"""115 gate read-out: what the readability checker says about the flyback page.

Read-only, offline.  It builds the page the way 114 did (the first variant's
plan, with the relation gate switched off so a layout that has not cleared the
grammar gate yet still gets measured) and prints every hard violation the
readability checker finds on it — which is where 115-② and 115-③ are read.

    .venv/Scripts/python.exe tools/115_gate_read.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import readability  # noqa: E402


def book_from(path: Path) -> dict[str, SymbolProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                SymbolPin(
                    str(p["number"]), (float(p["tip"][0]), float(p["tip"][1])),
                    str(p.get("name", "")), str(p.get("direction", "")))
                for p in entry["pins"]
            ],
        )
    return book


def main() -> int:
    specs = ROOT / "blocklib" / "specs"
    circuit = CircuitSpec.load(specs / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(specs / "flyback_uc3845.presentation.json")
    book = book_from(specs / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book,
        dc.CompileBudget(max_candidates=64),
    ).context
    assert ctx is not None
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        built, failure, violations = dc._build_candidate(ctx, dc._variants(ctx)[0])
    finally:
        dc._relation_failures = saved
    if built is None:
        print("the first variant is refused by the readability gate:")
        print("  ", (failure.detail if failure else "")[:2000])
        for line in violations:
            print("  ", line)
        return 1
    print("hard violations: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())