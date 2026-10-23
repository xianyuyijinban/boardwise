"""535 probe 4: the full `_connect_net`/`_attach` transcript of one net.

    BW535_ROOT=<root> BW535_SRC=<root>/src python tools/535_trace_probe.py SEC_GND
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

TARGET = sys.argv[1] if len(sys.argv) > 1 else "SEC_GND"

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(ROOT / "outputs" / "144" / "presentation_144.json")
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

_Unrouted = getattr(dc, "_Unrouted", None)
lines: list[str] = []
call_no = {"value": 0}

real_connect = dc._connect_net
real_attach = dc._attach
real_elbow = dc._elbow_route
real_route = None  # set below


def spy_connect(ctx, router, expression, blocked, existing=()):
    if expression.net != TARGET:
        return real_connect(ctx, router, expression, blocked, existing)
    call_no["value"] += 1
    lines.append(f"### connect #{call_no['value']} {TARGET} points={[list(p) for _, p in expression.points]}")
    out = real_connect(ctx, router, expression, blocked, existing)
    if _Unrouted is not None and isinstance(out, _Unrouted):
        lines.append(f"  -> UNROUTED [{out.stage}]")
    elif out is None:
        lines.append("  -> None")
    else:
        segs, why = out
        for seg in segs:
            lines.append(f"  -> seg {[list(p) for p in seg.points]}")
        lines.append(f"  -> {why}")
    return out


def spy_attach(router, point, segments, blocked, net_id):
    if net_id != TARGET:
        return real_attach(router, point, segments, blocked, net_id)
    out = real_attach(router, point, segments, blocked, net_id)
    if out is None:
        verdict = "FAILED(None)"
    elif _Unrouted is not None and isinstance(out, _Unrouted):
        verdict = f"FAILED[{out.stage}]"
    else:
        verdict = f"ok {[list(p) for p in out.points]}"
    lines.append(f"  attach {list(point)} -> {verdict}")
    return out


dc._connect_net = spy_connect
dc._attach = spy_attach

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("ok =", result.ok)
for line in lines:
    print(line)
