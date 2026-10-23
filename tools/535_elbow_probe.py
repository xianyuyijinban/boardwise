"""535 probe 6: exactly which wall refuses the elbow that joins one pin.

    BW535_ROOT=<root> BW535_SRC=<root>/src BW535_SPECS=<specs> \
        python tools/535_elbow_probe.py SEC_GND 440 660
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

TARGET = sys.argv[1]
PIN = (float(sys.argv[2]), float(sys.argv[3]))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, drawcompiler as dc  # noqa: E402

circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
presentation = PresentationSpec.load(ROOT / "outputs" / "144" / "presentation_144.json")
book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")

reported = {"done": False}
real_attach = dc._attach
_Unrouted = getattr(dc, "_Unrouted", None)


def hits_box(start, end, box):
    if dc._segment_hits_box(start, end, box):
        return "box"
    return None


def why_span(router, start, end, blocked):
    out = []
    for box in router.boxes:
        if dc._segment_hits_box(start, end, box):
            out.append(f"box {[round(v, 3) for v in box]}")
    for index, foreign in enumerate(router.edges):
        if dc._collinear_overlap(start, end, foreign[0], foreign[1]):
            net = router.edge_nets[index] if index < len(router.edge_nets) else ""
            out.append(f"runs along {net}'s wire {foreign}")
    for point in sorted(blocked):
        if dc._strictly_on_segment(point, start, end):
            out.append(f"foreign anchor {list(point)} inside the span")
    if dc._reserved_hits(router, start, end):
        out.append("crosses a reserved lane")
    return out


def spy(router, point, segments, blocked, net_id):
    out = real_attach(router, point, segments, blocked, net_id)
    failed = out is None or (_Unrouted is not None and isinstance(out, _Unrouted))
    if failed and net_id == TARGET and dc._key(point) == dc._key(PIN) and not reported["done"]:
        reported["done"] = True
        print(f"=== {net_id} cannot reach {list(point)}")
        targets = dc._nearest_first(point, dc._geometry_nodes(router, segments))
        print(f"{len(targets)} candidate targets; nearest 4:")
        for target in targets[:4]:
            print(f"   {list(target)}")
        extra = os.environ.get("BW535_TARGETS", "")
        if os.environ.get("BW535_ALL"):
            buckets: dict[str, int] = {}
            crossing_only = []
            for target in targets:
                if dc._key(target) == dc._key(point):
                    continue
                if dc._elbow_route(router, point, target, blocked) is not None:
                    buckets["free elbow"] = buckets.get("free elbow", 0) + 1
                    continue
                summary = []
                for corner in ((target[0], point[1]), (point[0], target[1])):
                    if dc._key(corner) in (dc._key(point), dc._key(target)):
                        hard = tuple(why_span(router, point, target, blocked))
                        crossing = dc._run_crosses_a_foreign_wire(router, point, target)
                        summary.append(("straight", hard, crossing))
                        continue
                    hard = []
                    for label, start, end in (("1", point, corner), ("2", corner, target)):
                        hard.extend(why_span(router, start, end, blocked))
                    if dc._key(dc._rounded(corner)) in blocked:
                        hard.append("corner is a foreign anchor")
                    if not dc._vertex_clear(router, corner):
                        hard.append("corner on a foreign span")
                    crossing = any(
                        dc._run_crosses_a_foreign_wire(router, start, end)
                        for start, end in ((point, corner), (corner, target))
                    )
                    summary.append(("elbow", tuple(hard), crossing))
                if any(not hard for _, hard, _ in summary):
                    if all(crossing for kind, hard, crossing in summary if not hard):
                        crossing_only.append(target)
                    buckets["otherwise free, but crosses"] = (
                        buckets.get("otherwise free, but crosses", 0) + 1)
                    continue
                buckets["a box/anchor/lane refuses both corners"] = (
                    buckets.get("a box/anchor/lane refuses both corners", 0) + 1)
            print("--- all targets, elbow verdict buckets:")
            for key, count in sorted(buckets.items()):
                print(f"      {count:4d}  {key}")
            print(f"--- crossing-only targets: {len(crossing_only)} e.g. "
                  f"{[list(t) for t in crossing_only[:8]]}")
            node = router.node(point)
            neighbours = [(node[0] + dx, node[1] + dy)
                          for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            enterable = [router.point(other) for other in neighbours
                         if router._in_bounds(other) and not router._wall(other)]
            print(f"--- the search can step out of the pin to: {enterable}")
        if extra:
            picked = [tuple(float(v) for v in item.split(",")) for item in extra.split(";")]
            print("--- named targets:")
            for target in picked:
                elbow = dc._elbow_route(router, point, target, blocked)
                print(f"   {list(target)}: elbow={elbow}")
                for corner in ((target[0], point[1]), (point[0], target[1])):
                    if dc._key(corner) in (dc._key(point), dc._key(target)):
                        straight = why_span(router, point, target, blocked)
                        print(f"      straight -> {list(target)}: "
                              f"{'refused: ' + '; '.join(straight) if straight else 'ok'}")
                        continue
                    print(f"      corner {list(corner)}:")
                    for label, start, end in (
                        ("leg 1", point, corner), ("leg 2", corner, target),
                    ):
                        bad = why_span(router, start, end, blocked)
                        print(f"         {label} {list(start)}->{list(end)}: "
                              f"{'refused: ' + '; '.join(bad) if bad else 'ok'}")
                    if dc._key(dc._rounded(corner)) in blocked:
                        print("         corner is a foreign anchor (blocked)")
                    if not dc._vertex_clear(router, corner):
                        print("         corner lies inside a foreign wire's span")
                    for label, start, end in (
                        ("leg 1", point, corner), ("leg 2", corner, target),
                    ):
                        if dc._run_crosses_a_foreign_wire(router, start, end):
                            print(f"         {label} crosses a foreign wire")
        for target in targets[:4]:
            for corner in ((target[0], point[1]), (point[0], target[1])):
                if dc._key(corner) in (dc._key(point), dc._key(target)):
                    straight = why_span(router, point, target, blocked)
                    print(f"   straight {list(point)}->{list(target)}: "
                          f"{'refused: ' + '; '.join(straight) if straight else 'ok'}")
                    continue
                print(f"   corner {list(corner)} towards {list(target)}:")
                for label, start, end in (
                    ("leg 1", point, corner), ("leg 2", corner, target),
                ):
                    bad = why_span(router, start, end, blocked)
                    print(f"      {label} {list(start)}->{list(end)}: "
                          f"{'refused: ' + '; '.join(bad) if bad else 'ok'}")
                if dc._key(dc._rounded(corner)) in blocked:
                    print("      corner is a foreign anchor (blocked)")
                if not dc._vertex_clear(router, corner):
                    print("      corner lies inside a foreign wire's span")
                for label, start, end in (
                    ("leg 1", point, corner), ("leg 2", corner, target),
                ):
                    if dc._run_crosses_a_foreign_wire(router, start, end):
                        print(f"      {label} crosses a foreign wire")
    return out


dc._attach = spy

result = dc.compile(circuit, presentation, book, dc.CompileBudget())
print("ok =", result.ok)
for item in result.failures:
    print("FAIL", item.category, "|", item.subject, "|", item.detail[:160])
