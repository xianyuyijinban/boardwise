"""535 probe 2: the routing environment of one net's `_connect_net` call.

Run in two trees and diff the output:

    BW535_ROOT=<root> BW535_SRC=<root>/src python tools/535_net_env_probe.py SEC_GND
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(
    os.environ.get("BW535_ROOT", pathlib.Path(__file__).resolve().parents[1])
)
SRC = pathlib.Path(os.environ.get("BW535_SRC", ROOT / "src"))
sys.path.insert(0, str(SRC))

TARGET = sys.argv[1] if len(sys.argv) > 1 else "SEC_GND"
OUT = pathlib.Path(os.environ.get("BW535_OUT", f"/tmp/env_{TARGET}.json"))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc  # noqa: E402

SPECS = pathlib.Path(os.environ.get("BW535_SPECS", ROOT / "blocklib" / "specs"))
circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(ROOT / "outputs" / "144" / "presentation_144.json")
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

records: list[dict] = []
real_connect = dc._connect_net


def _box(box):
    return [round(float(value), 3) for value in box]


def spy(ctx, router, expression, blocked, existing=()):
    if expression.net == TARGET:
        records.append({
            "call": len(records),
            "points": [list(p) for _, p in expression.points],
            "style": expression.style,
            "segments": [
                {"net": s.net, "points": [list(p) for p in s.points]}
                for s in existing
            ],
            "boxes": sorted(_box(b) for b in router.boxes),
            "blocked": sorted(list(b) for b in router.blocked),
            "reserved": sorted([list(k), v] for k, v in router.reserved.items()),
            "flag_walls": sorted(_box(b) for b in router.flag_walls),
            "edges": sorted([
                [list(edge[0]), list(edge[1]), net]
                for edge, net in zip(router.edges, router.edge_nets or [""] * len(router.edges))
            ]),
            "bounds": _box(router.bounds),
            "own_edges": sorted([[list(a), list(b)] for a, b in router.own_edges]),
        })
    return real_connect(ctx, router, expression, blocked, existing)


dc._connect_net = spy

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("ok =", result.ok, file=sys.stderr)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(records, indent=1), encoding="utf-8")
print(f"{len(records)} call(s) -> {OUT}", file=sys.stderr)
