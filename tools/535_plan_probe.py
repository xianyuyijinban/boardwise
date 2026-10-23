"""535: the 144 lock table's real reading after the fix — the numbers a test pins.

    python tools/535_plan_probe.py
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(
    os.environ.get("BW535_ROOT", pathlib.Path(__file__).resolve().parents[1])
)
SRC = pathlib.Path(os.environ.get("BW535_SRC", ROOT / "src"))
SPECS = pathlib.Path(os.environ.get("BW535_SPECS", ROOT / "blocklib" / "specs"))
sys.path.insert(0, str(SRC))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc, readability  # noqa: E402

circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(ROOT / "outputs" / "144" / "presentation_144.json")
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

seen: dict[str, object] = {}
real = dc._lead_lane_reservations


def spy(ctx, placed, expressions, order, router, occupied, solids, bodies):
    real(ctx, placed, expressions, order, router, occupied, solids, bodies)
    seen["reserved"] = dict(router.reserved)


dc._lead_lane_reservations = spy

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("ok =", result.ok, "| candidates:", len(result.candidates))
for item in result.failures:
    print("FAIL", item.category, "|", item.subject, "|", item.detail[:200])
print("notes:")
for note in result.notes:
    print("   ", note[:180])
if not result.candidates:
    raise SystemExit(1)
plan = result.candidates[0]
counts: dict[str, int] = {}
for symbol in plan.power_symbols:
    counts[symbol.net] = counts.get(symbol.net, 0) + 1
print("flags:", counts, "->", sorted((s.net, s.x, s.y) for s in plan.power_symbols))
label_nets: dict[str, int] = {}
for label in plan.labels:
    label_nets[label.net] = label_nets.get(label.net, 0) + 1
print("labels:", label_nets)
by_net: dict[str, int] = {}
points_by_net: dict[str, list] = {}
for segment in plan.segments:
    by_net[segment.net] = by_net.get(segment.net, 0) + 1
    points_by_net.setdefault(segment.net, []).append(
        [list(point) for point in segment.points])
print("segments by net:", by_net)
for net, value in points_by_net.items():
    if net in ("PGND", "SEC_GND", "HVDC", "SEC_12V"):
        print(f"   {net}: {value}")
checked = readability.check(
    plan, circuit, presentation, book, page_box=None, grid=dc.CompileBudget().grid,
)
print("hard violations:", [item.render()[:140] for item in checked.hard_violations])
print("soft metrics:", checked.soft_metrics)
reserved = seen.get("reserved") or {}
owners: dict[str, int] = {}
for value in reserved.values():
    owners[value] = owners.get(value, 0) + 1
print("reserved cells by net:", owners)
flag_anchors = [(item.x, item.y) for item in plan.power_symbols]


def reaches_flag(segment):
    return any(
        any(abs(x - ax) <= 1e-6 and abs(y - ay) <= 1e-6 for x, y in segment.points)
        for ax, ay in flag_anchors
    )


leads = [segment for segment in plan.segments if reaches_flag(segment)]
print("segments reaching a flag anchor:", [(s.net, s.points) for s in leads])
for segment in leads:
    for start, end in zip(segment.points, segment.points[1:]):
        for other in plan.segments:
            if other.net == segment.net:
                continue
            for a, b in zip(other.points, other.points[1:]):
                spot = dc._proper_crossing(start, end, a, b)
                if spot is not None:
                    print(f"   CUT {segment.net} by {other.net} at "
                          f"({spot[0]:g}, {spot[1]:g})")
ground = [s for s in plan.segments if s.net in ("PGND", "SEC_GND")]
print("ground segments:", len(ground), [(s.net, len(s.points)) for s in ground])
caps = dict(dc.ISLAND_GATE_TOLERATED_LIMITS)
print("tolerated caps:", caps)
