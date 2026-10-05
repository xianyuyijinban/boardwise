#!/usr/bin/env python3
"""117(1) root-cause probe: is the AUX/PGND merge a flag, a route, or a profile?

The gate says the plan makes these pins one node but the spec does not:

    pins[C10.2] pins[C6.2] pins[C7.2] pins[D2.1] pins[R10.2] pins[R5.2]
    pins[T1.A1] pins[T1.A2] pins[U5.3]

with ``D2.1`` and ``T1.A1`` on net ``AUX`` and the rest on ``PGND``.

Three candidates the task book names, and what each one would look like in the
geometry:

a. **flag** — a netlabel/flag (or the stub that carries it) was placed on a pin
   that belongs to another net. Measure: is there a flag whose *anchored pin* is
   D2.1 or T1.A1 while its *named net* is PGND, or vice versa?
b. **route** — a wire segment physically connects an AUX pin to a PGND pin.
   Measure: for every wire vertex pair in the merged component, which pin tips
   does the segment touch, and do those pins sit on different nets?
c. **profile** — T1's pin token ``A1`` is read as a different pin than the spec
   means. Measure: dump T1's profile pins with their net assignments, and check
   ``A1``/``A2`` against the CircuitSpec.

The probe prints all three measurements, so the SUMMARY can name one.
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
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import readability as rb  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"

MERGED = [
    "C10.2", "C6.2", "C7.2", "D2.1", "R10.2", "R5.2", "T1.A1", "T1.A2", "U5.3",
]

# The checker is the thing that names the violation, so it runs.
_real_gate = dc._readability_gate if hasattr(dc, "_readability_gate") else None


def _library(path: Path):
    sys.path.insert(0, str(ROOT / "tests"))
    from importlib import import_module
    return import_module("test_113_flyback_grammar")._library_from(path)


def main() -> int:
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = _library(SPECS / "flyback_uc3845.library.json")

    print("=" * 78)
    print("(c) PROFILE: what net does the compiler think each T1 / D2 pin is on?")
    print("=" * 78)
    binding = dc.bind_grammar(circuit, presentation, book)
    prepare = dc._prepare(circuit, presentation, binding, book,
                          dc.CompileBudget(max_candidates=64))
    ctx = prepare.context
    if ctx is None:
        print("no context:", [f.detail for f in prepare.failures])
        return 2

    for part_id in ("T1", "D2", "C7", "C10", "U5", "R5", "R10", "C6"):
        nets = dc._part_nets(circuit, part_id)
        print(f"  {part_id}: {nets}")
    print()
    print("  T1 profile pins (token -> tip -> direction):")
    for pin in ctx.profile("T1").pins:
        print(f"    number={pin.number!r} name={pin.name!r} "
              f"tip={pin.tip} dir={pin.direction} "
              f"-> net={dc._part_nets(circuit, 'T1').get(pin.number) or dc._part_nets(circuit, 'T1').get(pin.name)!r}")
    print("  D2 profile pins:")
    for pin in ctx.profile("D2").pins:
        print(f"    number={pin.number!r} name={pin.name!r} "
              f"tip={pin.tip} dir={pin.direction} "
              f"-> net={dc._part_nets(circuit, 'D2').get(pin.number) or dc._part_nets(circuit, 'D2').get(pin.name)!r}")
    print()
    print("  CircuitSpec members mentioning T1 / D2:")
    for net in circuit.nets:
        members = list(net.members)
        if any(m.startswith(("T1.", "D2.")) for m in members):
            print(f"    net {net.id!r} cls={net.cls!r}: {members}")

    print()
    print("=" * 78)
    print("(a)+(b) GEOMETRY: the merged component, wire by wire")
    print("=" * 78)

    # Find a placed variant: the readability gate refuses, so measure the plan
    # the compiler produced *before* the gate speaks.
    plan = None
    label = None
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        for variant in dc._variants(ctx):
            placed, _ = dc._place(ctx, variant)
            if placed is None:
                continue
            plan, label = placed, variant.label
            break
    finally:
        dc._relation_failures = saved
    if plan is None:
        print("no variant placed at all")
        return 2
    print(f"  measuring variant: {label}")

    # Which pin tips does the plan actually put where?
    print()
    print("  pin tips of the merged members (page coordinates):")
    for token in MERGED:
        part_id, _, pad = token.partition(".")
        point = dc._pin_point(ctx, part_id, pad, plan.poses, plan.origins)
        nets = dc._part_nets(circuit, part_id)
        net = nets.get(pad) or nets.get(pad) or ""
        print(f"    {token:<8} net={net!r:<8} tip={point}")

    print()
    print("  wires whose endpoints sit on a merged member's pin tip:")
    for wire in plan.wires:
        pts = list(wire.points)
        touching = []
        for token in MERGED:
            part_id, _, pad = token.partition(".")
            point = dc._pin_point(ctx, part_id, pad, plan.poses, plan.origins)
            if point is None:
                continue
            for index, p in enumerate(pts):
                if abs(p[0] - point[0]) < rb.TOL * 10 and \
                        abs(p[1] - point[1]) < rb.TOL * 10:
                    touching.append((index, token))
        if touching:
            print(f"    wire {pts}: touches {touching}")

    print()
    print("  netlabels/flags in the plan:")
    for label_obj in getattr(plan, "labels", ()) or ():
        print(f"    {label_obj}")
    for name in ("netlabels", "flags", "texts"):
        items = getattr(plan, name, None)
        if items:
            print(f"    plan.{name} ({len(items)}):")
            for item in items:
                print(f"      {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
