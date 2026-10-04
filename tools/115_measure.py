#!/usr/bin/env python3
"""115 diagnostic: every order relation the flyback page violates, per variant.

Read-only.  Prints what the compiler measured for each variant instead of only
the first refusal, so a change can be judged on the whole set rather than on
whichever relation happened to sort first.
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

ORDER = (dc.ABOVE, dc.BELOW, dc.LEFT_OF, dc.RIGHT_OF, dc.ADJACENT)


def book_from(path: Path) -> dict[str, SymbolProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    book = {}
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


def report(title, circuit, presentation, book) -> None:
    binding = dc.bind_grammar(circuit, presentation, book)
    prepare = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64),
    )
    ctx = prepare.context
    assert ctx is not None, prepare.failures
    print(f"\n===== {title} =====")
    print(f"axis={ctx.axis} progress={ctx.progress} chain={ctx.chain}")
    for variant in dc._variants(ctx):
        placed, failure = dc._place(ctx, variant)
        if placed is None:
            detail = failure.detail if failure is not None else "?"
            print(f"  {variant.label}: REFUSED "
                  f"({failure.category if failure else '?'}) {detail[:200]}")
            continue
        violations = dc._relation_violations(
            circuit, binding,
            origin_of=lambda part_id: placed.origins.get(part_id),
            pin_of=lambda part_id, token: dc._pin_point(
                ctx, part_id, token, placed.poses, placed.origins),
            grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
            lateral=ctx.lateral(), progress=ctx.progress,
        )
        if not violations:
            print(f"  {variant.label}: every relation holds")
            continue
        print(f"  {variant.label}: {len(violations)} violated")
        for item, points in violations:
            print(f"      {item.kind}({item.subject},{item.object}) "
                  f"measured ({points[0][0]:g}, {points[0][1]:g}) and "
                  f"({points[1][0]:g}, {points[1][1]:g})")


def main() -> int:
    specs = ROOT / "blocklib" / "specs"
    report(
        "flyback",
        CircuitSpec.load(specs / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(specs / "flyback_uc3845.presentation.json"),
        book_from(specs / "flyback_uc3845.library.json"),
    )
    import test_098_ic_periphery as sc
    circuit, presentation = sc.sample()
    report("098 sample (wide)", circuit, presentation, sc.library())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())