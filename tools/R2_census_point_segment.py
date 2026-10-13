# R2-4 evidence script. It instruments the THREE private point-to-segment copies
# that existed before R2-4, so it runs against the parent tree (9cd9d29), not HEAD:
#   git worktree add ../bw-pre-r2 9cd9d29 && cd ../bw-pre-r2 && python tools/R2_census_point_segment.py out.json
# Output committed as outputs/R2/point_segment_census.json.
"""R2-4 data: do the two point-to-segment guards ever disagree on a real call?

Three copies exist:
  core.measure._point_segment_distance      guard: dx == 0 and dy == 0
  rules.pcb.focthermal._point_segment_distance  guard: length_sq <= 1e-18
  rules.pcb.distance._point_segment_mil     guard: length_sq <= 1e-18 (same body)

Every call each copy receives while the full PCB review runs over every
fixture is replayed through BOTH guards, and the outputs are compared bitwise.
A second half measures the synthetic degenerate-edge band, and a third the
underflow case that crashes the exact-zero guard.

Run from the repo root: python census_point_segment.py <out.json>
"""
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

from boardwise import cli
from boardwise.core import measure
from boardwise.core.geometry import Point
from boardwise.engines import pcbreview
from boardwise.rules.pcb import distance, focthermal


def exact_zero_guard(p, a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    if dx == 0 and dy == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))


def length_sq_guard(p, a, b):
    dx, dy = b.x - a.x, b.y - a.y
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length_sq))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))


stats = {
    name: Counter()
    for name in ("core._point_segment_distance", "focthermal._point_segment_distance", "distance._point_segment_mil")
}
band_edges = Counter()
examples = []


def wrap(name, original):
    def recorder(p, a, b):
        out = original(p, a, b)
        s = stats[name]
        s["calls"] += 1
        dx, dy = b.x - a.x, b.y - a.y
        lsq = dx * dx + dy * dy
        if lsq == 0.0:
            s["exactly_degenerate"] += 1
        elif lsq <= 1e-18:
            s["in_band_0_to_1e-18"] += 1
            band_edges[name] += 1
        try:
            ez = exact_zero_guard(p, a, b)
        except ZeroDivisionError:
            s["exact_zero_guard_crashed"] += 1
            return out
        ls = length_sq_guard(p, a, b)
        if ez != ls:
            s["bitwise_diff"] += 1
            if len(examples) < 20:
                examples.append({"fn": name, "p": [p.x, p.y], "a": [a.x, a.y], "b": [b.x, b.y], "exact_zero": ez, "length_sq": ls})
        if out != (ez if name.startswith("core") else ls):
            s["recorder_mismatch"] += 1
        return out

    return recorder


measure._point_segment_distance = wrap("core._point_segment_distance", measure._point_segment_distance)
focthermal._point_segment_distance = wrap("focthermal._point_segment_distance", focthermal._point_segment_distance)
distance._point_segment_mil = wrap("distance._point_segment_mil", distance._point_segment_mil)

per_fixture = {}
for path in sorted(Path("tests/fixtures").glob("*.epro2")):
    before = {k: v["calls"] for k, v in stats.items()}
    try:
        model = cli._load_model(path, view="schematic")[0]
    except Exception as exc:  # a fixture with no schematic view still has boards
        model = None
    findings, section = pcbreview.run_pcb_review(path, model=model)
    per_fixture[path.name] = {
        "findings": len(findings),
        "calls": {k: stats[k]["calls"] - before[k] for k in stats},
        "rules_errored": (section or {}).get("rules_errored", []),
    }

# synthetic: the degenerate band and around it
rng = random.Random(20261013)
synthetic = Counter()
diff_max = 0.0
for _ in range(5000):
    a = Point(rng.uniform(-5000, 5000), rng.uniform(-5000, 5000))
    length = 10 ** rng.uniform(-12, -6)  # 1e-12 .. 1e-6 mil
    ang = rng.uniform(0, 2 * math.pi)
    b = Point(a.x + length * math.cos(ang), a.y + length * math.sin(ang))
    p = Point(a.x + rng.uniform(-50, 50), a.y + rng.uniform(-50, 50))
    ez, ls = exact_zero_guard(p, a, b), length_sq_guard(p, a, b)
    synthetic["cases"] += 1
    if ez != ls:
        synthetic["bitwise_diff"] += 1
        diff_max = max(diff_max, abs(ez - ls))
        dx, dy = b.x - a.x, b.y - a.y
        if dx * dx + dy * dy > 1e-18:
            synthetic["diff_outside_band"] += 1
underflow = {}
a = Point(0.0, 0.0)
b = Point(1e-170, 0.0)  # dx*dx underflows to 0.0, dx != 0
p = Point(1.0, 1.0)
try:
    underflow["exact_zero_guard"] = exact_zero_guard(p, a, b)
except ZeroDivisionError as exc:
    underflow["exact_zero_guard"] = f"ZeroDivisionError: {exc}"
underflow["length_sq_guard"] = length_sq_guard(p, a, b)

out = {
    "per_function": {k: dict(v) for k, v in stats.items()},
    "per_fixture": per_fixture,
    "examples_of_real_diffs": examples,
    "synthetic_band_1e-12_to_1e-6_mil": dict(synthetic) | {"max_abs_diff_mil": diff_max},
    "underflow_case_dx_1e-170": underflow,
}
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("per_function", "synthetic_band_1e-12_to_1e-6_mil", "underflow_case_dx_1e-170")}, ensure_ascii=False, indent=1))
