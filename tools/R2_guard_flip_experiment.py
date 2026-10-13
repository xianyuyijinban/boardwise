# R2-4 evidence script. It instruments the THREE private point-to-segment copies
# that existed before R2-4, so it runs against the parent tree (9cd9d29), not HEAD:
#   git worktree add ../bw-pre-r2 9cd9d29 && cd ../bw-pre-r2 && python tools/R2_guard_flip_experiment.py out.json
# Output committed as outputs/R2/guard_flip_experiment.json.
"""R2-4 hard constraint: does unifying the point-segment guard flip any verdict?

Three runs of the full PCB review over every fixture:
  baseline  — the code as it is (core: exact-zero guard; focthermal/distance: length_sq guard)
  A         — every copy uses the length_sq <= 1e-18 guard
  B         — every copy uses the exact-zero guard
Each finding is reduced to (board, rule, severity, message, evidence...) and the
three multisets are compared per fixture.

Run from the repo root: python guard_flip_experiment.py <out.json>
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

from boardwise import cli
from boardwise.core import measure
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


ORIGINAL = (measure._point_segment_distance, focthermal._point_segment_distance, distance._point_segment_mil)


def install(variant):
    if variant == "baseline":
        measure._point_segment_distance, focthermal._point_segment_distance, distance._point_segment_mil = ORIGINAL
    else:
        fn = length_sq_guard if variant == "A" else exact_zero_guard
        measure._point_segment_distance = fn
        focthermal._point_segment_distance = fn
        distance._point_segment_mil = fn


def signature(f):
    d = f.to_dict() if hasattr(f, "to_dict") else dict(vars(f))
    return json.dumps(d, ensure_ascii=False, sort_keys=True, default=str)


fixtures = sorted(Path("tests/fixtures").glob("*.epro2"))
models = {}
for path in fixtures:
    try:
        models[path] = cli._load_model(path, view="schematic")[0]
    except Exception:
        models[path] = None

runs = {}
for variant in ("baseline", "A", "B"):
    install(variant)
    per = {}
    for path in fixtures:
        findings, section = pcbreview.run_pcb_review(path, model=models[path])
        per[path.name] = {
            "sigs": Counter(signature(f) for f in findings),
            "severity": Counter((getattr(f, "rule_id", None) or getattr(f, "rule", None), str(getattr(f, "severity", ""))) for f in findings),
            "errored": (section or {}).get("rules_errored", []),
        }
    runs[variant] = per
install("baseline")

out = {}
for variant in ("A", "B"):
    diffs = {}
    for name, base in runs["baseline"].items():
        other = runs[variant][name]
        only_base = base["sigs"] - other["sigs"]
        only_other = other["sigs"] - base["sigs"]
        diffs[name] = {
            "findings": sum(base["sigs"].values()),
            "identical": not only_base and not only_other,
            "severity_table_identical": base["severity"] == other["severity"],
            "only_in_baseline": list(only_base.elements())[:5],
            "only_in_variant": list(only_other.elements())[:5],
            "errored_baseline": base["errored"],
            "errored_variant": other["errored"],
        }
    out[variant] = diffs
summary = {
    v: {
        "fixtures": len(d),
        "fixtures_with_any_finding_change": sum(1 for x in d.values() if not x["identical"]),
        "fixtures_with_severity_change": sum(1 for x in d.values() if not x["severity_table_identical"]),
        "total_findings": sum(x["findings"] for x in d.values()),
    }
    for v, d in out.items()
}
Path(sys.argv[1]).write_text(json.dumps({"summary": summary, "detail": out}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
