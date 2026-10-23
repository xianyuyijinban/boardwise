"""535 probe: what happens to each net of the 144 locked page, per stage.

Run: .venv/Scripts/python.exe tools/535_sec_gnd_probe.py
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(
    os.environ.get("BW535_ROOT", pathlib.Path(__file__).resolve().parents[1])
)
SRC = pathlib.Path(os.environ.get("BW535_SRC", ROOT / "src"))
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tests"))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc  # noqa: E402
from boardwise.engines import grammar  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
LOCKS_144 = ROOT / "outputs" / "144" / "presentation_144.json"

circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(LOCKS_144)
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

log: list[tuple[str, object]] = []
real_connect = dc._connect_net


def spy(ctx, router, expression, blocked, existing=()):
    out = real_connect(ctx, router, expression, blocked, existing)
    log.append((expression.net, out))
    return out


dc._connect_net = spy
real_res = dc._lead_lane_reservations


def spy_res(ctx, placed, expressions, order, router, occupied, solids, bodies):
    out = real_res(ctx, placed, expressions, order, router, occupied, solids, bodies)
    log.append(("##reserved", dict(router.reserved)))
    log.append(("##flag_walls", list(router.flag_walls)))
    return out


dc._lead_lane_reservations = spy_res

real_expressions = dc._expressions


def spy_expressions(ctx, placed):
    out = real_expressions(ctx, placed)
    log.append((
        "##styles",
        {net: (expr.style, len(expr.points), sorted(p for _, p in expr.points))
         for net, expr in out.items()},
    ))
    return out


dc._expressions = spy_expressions

if len(sys.argv) > 1 and sys.argv[1] == "--skip-flag-symbol":
    dc._missing_flag_symbol = lambda ctx, net_id: True

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("src =", SRC)
print("ok =", result.ok)
for item in result.failures:
    print("FAIL", item.category, "|", item.subject, "|", item.detail[:400])

first_styles = True
seen_styles = 0
for net, out in log:
    if net.startswith("##"):
        if net == "##styles":
            seen_styles += 1
            if first_styles:
                print("styles:")
                for name, value in out.items():
                    print(f"   {name}: {value[0]} n={value[1]} {value[2]}")
                first_styles = False
            elif seen_styles > 2:
                break
            continue
        if net == "##reserved":
            owners: dict[str, int] = {}
            for value in out.values():
                owners[value] = owners.get(value, 0) + 1
            print(f"reserved: {len(out)} cells by net {owners}")
        else:
            print(f"flag_walls: {len(out)}")
        continue
    unrouted = getattr(dc, "_Unrouted", ())
    if unrouted and isinstance(out, unrouted):
        print(f"UNROUTED {net} [{out.stage}] {out.reason[:200]}")
    elif out is None:
        print(f"NONE {net}")
    else:
        segs, why = out
        cells = sum(
            max(abs(b[0] - a[0]), abs(b[1] - a[1])) / 5.0
            for seg in segs for a, b in zip(seg.points, seg.points[1:])
        )
        print(f"ROUTED {net}: {len(segs)} segs, {cells:.0f} units | {why}")

if result.candidates:
    plan = result.candidates[0]
    counts: dict[str, int] = {}
    for symbol in plan.power_symbols:
        counts[symbol.net] = counts.get(symbol.net, 0) + 1
    print("flags:", counts)
    leads: dict[str, int] = {}
    for seg in plan.segments:
        leads[seg.net] = leads.get(seg.net, 0) + 1
    print("segments by net:", leads)
    print("labels:", [(item.net, item.point) for item in plan.labels])
