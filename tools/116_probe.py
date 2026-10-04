#!/usr/bin/env python3
"""116 diagnostic: every relation each variant violates, ignoring the first refusal.

115's harness stops at :func:`_place`'s first refusal, so it prints one relation
per variant — whichever sorted first. 116 has to judge four relations that live
in four different variants, so this harness patches the refusal out and measures
every relation of every variant, exactly the way the relation checker does.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.engines import drawcompiler as dc  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from importlib import import_module  # noqa: E402

_measure = import_module("115_measure")

_real_relation_failures = dc._relation_failures
dc._relation_failures = lambda ctx, placed: []


def report(title, circuit, presentation, book) -> None:
    binding = dc.bind_grammar(circuit, presentation, book)
    prepare = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64),
    )
    ctx = prepare.context
    assert ctx is not None, prepare.failures
    print(f"\n===== {title} =====")
    print(f"axis={ctx.axis} progress={ctx.progress} chain={ctx.chain}")
    total = 0
    for variant in dc._variants(ctx):
        placed, failure = dc._place(ctx, variant)
        if placed is None:
            print(f"  {variant.label}: PLACEMENT REFUSED "
                  f"({failure.category if failure else '?'})")
            continue
        violations = dc._relation_violations(
            circuit, binding,
            origin_of=lambda part_id: placed.origins.get(part_id),
            pin_of=lambda part_id, token: dc._pin_point(
                ctx, part_id, token, placed.poses, placed.origins),
            grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
            lateral=ctx.lateral(), progress=ctx.progress,
        )
        total += len(violations)
        if not violations:
            print(f"  {variant.label}: every relation holds")
            continue
        print(f"  {variant.label}: {len(violations)} violated")
        for item, points in violations:
            print(f"      {item.kind}({item.subject},{item.object}) "
                  f"measured ({points[0][0]:g}, {points[0][1]:g}) and "
                  f"({points[1][0]:g}, {points[1][1]:g})")
    print(f"  -- total violated relation instances: {total}")


def main() -> int:
    specs = ROOT / "blocklib" / "specs"
    report(
        "flyback",
        _measure.CircuitSpec.load(specs / "flyback_uc3845.circuit.json"),
        _measure.PresentationSpec.load(specs / "flyback_uc3845.presentation.json"),
        _measure.book_from(specs / "flyback_uc3845.library.json"),
    )
    import test_098_ic_periphery as sc
    circuit, presentation = sc.sample()
    report("098 sample (wide)", circuit, presentation, sc.library())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
