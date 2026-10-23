"""535 probe 5: every net's drawn wiring, first variant — base vs head diff input.

    BW535_ROOT=<root> BW535_SRC=<root>/src python tools/535_routes_probe.py
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

LIMIT = int(os.environ.get("BW535_LIMIT", "1"))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc  # noqa: E402

SPECS = pathlib.Path(os.environ.get("BW535_SPECS", ROOT / "blocklib" / "specs"))
circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(ROOT / "outputs" / "144" / "presentation_144.json")
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

_Unrouted = getattr(dc, "_Unrouted", None)
lines: list[str] = []
rounds = {"value": 0}
real_connect = dc._connect_net
real_reservations = dc._lead_lane_reservations


def spy_res(ctx, placed, expressions, order, router, occupied, solids, bodies):
    rounds["value"] += 1
    if rounds["value"] > LIMIT:
        return real_reservations(
            ctx, placed, expressions, order, router, occupied, solids, bodies
        )
    lines.append(f"=== variant {rounds['value']} net order {list(order)}")
    return real_reservations(
        ctx, placed, expressions, order, router, occupied, solids, bodies
    )


def spy(ctx, router, expression, blocked, existing=()):
    if rounds["value"] > LIMIT:
        return real_connect(ctx, router, expression, blocked, existing)
    out = real_connect(ctx, router, expression, blocked, existing)
    head = f"{expression.net}: points={[list(p) for _, p in expression.points]}"
    if _Unrouted is not None and isinstance(out, _Unrouted):
        lines.append(f"{head} -> UNROUTED[{out.stage}]")
    elif out is None:
        lines.append(f"{head} -> None")
    else:
        segs, _why = out
        lines.append(f"{head} ->")
        for seg in segs:
            lines.append(f"    {[list(p) for p in seg.points]}")
    return out


dc._connect_net = spy
dc._lead_lane_reservations = spy_res

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("ok =", result.ok)
for line in lines:
    print(line)
