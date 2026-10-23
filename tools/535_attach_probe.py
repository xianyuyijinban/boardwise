"""535 probe 3: why the attachment to one pin fails — the local wall anatomy.

    BW535_ROOT=<root> BW535_SRC=<root>/src python tools/535_attach_probe.py SEC_GND

For the first failing `_attach` of the named net, dumps every lattice node in a
box around the pin and classifies why `_Router._wall` calls it a wall.
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
RADIUS = float(os.environ.get("BW535_RADIUS", "30"))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(ROOT / "outputs" / "144" / "presentation_144.json")
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

reported = {"done": False}
real_attach = dc._attach
_Unrouted = getattr(dc, "_Unrouted", None)


def classify(router, point):
    key = dc._key(point)
    why = []
    if key in router.blocked:
        why.append("blocked")
    owner = router.reserved.get(key)
    if owner is not None and owner != router.reserved_exempt:
        why.append(f"reserved:{owner}")
    for index, box in enumerate(router.boxes):
        if (box[0] - 1e-6 < point[0] < box[2] + 1e-6
                and box[1] - 1e-6 < point[1] < box[3] + 1e-6):
            why.append(f"box[{index}]{[round(v, 3) for v in box]}")
    return why


def spy(router, point, segments, blocked, net_id):
    out = real_attach(router, point, segments, blocked, net_id)
    failed = out is None or (_Unrouted is not None and isinstance(out, _Unrouted))
    if failed and net_id == TARGET and not reported["done"]:
        reported["done"] = True
        print(f"=== first failing attachment of {net_id} at {point}")
        print("existing geometry:")
        for segment in segments:
            print(f"   {segment.net} {[list(p) for p in segment.points]}")
        print("targets =", [t[0] for t in point] if False else "see below")
        grid = router.grid
        residue = router.residue
        print(f"grid={grid} residue={residue} bounds={router.bounds}")
        print(f"boxes={len(router.boxes)} blocked={len(router.blocked)} "
              f"reserved={len(router.reserved)}")
        ix = round((point[0] - residue[0]) / grid)
        iy = round((point[1] - residue[1]) / grid)
        span = int(RADIUS // grid)
        for dy in range(span, -span - 1, -1):
            row = []
            for dx in range(-span, span + 1):
                node = (
                    residue[0] + (ix + dx) * grid,
                    residue[1] + (iy + dy) * grid,
                )
                why = classify(router, node)
                if dx == 0 and dy == 0:
                    row.append("[PIN]")
                elif not why:
                    row.append("  .  ")
                elif any(w.startswith("box") for w in why):
                    row.append("  #  ")
                elif any(w == "blocked" for w in why):
                    row.append("  b  ")
                else:
                    row.append("  r  ")
            print("   " + " ".join(row))
    return out


dc._attach = spy

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("ok =", result.ok)
for item in result.failures:
    print("FAIL", item.category, "|", item.subject, "|", item.detail[:200])
