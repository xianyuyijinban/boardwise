#!/usr/bin/env python3
"""121b: the hand-plan locks for the flyback page (岳's option 2, step 2).

    .venv/Scripts/python.exe tools/121b_hand_plan_lock.py [out-dir]

121a established the ground with the fixture library reader: **1 of 6** ladder
rungs built a plan (``spacing=2.2 pose-variant=0``), gated by the real
readability checker, zero hard violations.  岳's ruling (2026-10-06) is the
hand-plan path: pin the placements the compiler cannot solve by hand (052
sec.4's ``userLocks``, which the compiler honours exactly and never snaps),
re-route, lint, apply.

**121b's own measurement moved two of those numbers**, and both are on the
record rather than argued:

* the rung is real — its 19 placements are byte-for-byte what 121a recorded —
  but it is **not** the only buildable rung once the library is read the way
  ``draw plan`` reads it (4 of 6 build, and every one of them is refused by the
  same relation, ``same-column(Q1, R5)``);
* the rung's own landing points break **two** relations, not one.  The ruler is
  ``_relation_violations`` — `check_grammar`'s own — and it weighs
  ``same-column`` and ``near`` between the two parts' **pins on the net they
  share**, which is why an origins-only reading says "one" and the compiler
  says "two": ``same-column(Q1, R5)`` is broken (R5's SRC pin lands 20 units
  off Q1's, both origins on x = 0), and ``near(C13, T1)`` is over its 300
  limit.  Both are hand-fixed below, and the report's
  ``hand_edit_measurements`` carries the two measured pairs on both plans.

This tool runs the offline half of the work:

1. **the skeleton** — the 2.2/pose-0 rung's own plan, obtained exactly as
   ``tools/121_hand_plan_dump.py`` obtains it (relation gate stood aside for
   the *skeleton* only, so the rung's own landing points can be read);
2. **the lock table** — every one of the 19 parts at that plan's landing
   point, plus the hand edits the rung's own landing points were **measured**
   to need.  Each edit carries its reason and its measurement, and the
   literal-landing set is compiled alongside so the difference is on the
   record rather than argued;
3. **``dc.compile``** on the locked presentation with **no gate stood aside** —
   the real compile, real relation gate, real readability gate;
4. **the artefacts** — the locked presentation, the green candidate's
   ``drawapply.module_plan`` ChangePlan (the exact document ``draw apply``
   consumes), its layout JSON, its SVG, and a report with the failure table
   when a run is not green.

Nothing here touches the editor.  ``draw apply`` is a separate, supervised
step (121b's real-machine leg).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import (  # noqa: E402
    PresentationSpec,
    UserLock,
)
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import drawapply  # noqa: E402
from boardwise.engines import readability as rb  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
DEFAULT_OUT = ROOT / "outputs" / "121" / "continuation"

#: The rung 121a measured as the only buildable one.
SKELETON_VARIANT = "spacing=2.2 pose-variant=0"

#: 岳 2026-10-04 ruling: the two 75k 0603 RCD resistors are C23242.
LCSC_OVERRIDES = {"R3": "C23242", "R15": "C23242"}

#: The hand edits — the landings the rung reached, moved by hand because the
#: **final plan** (measured with ``_relation_violations``, ``check_grammar``'s
#: own ruler) does not keep every relation there.  Each entry carries its
#: reason; every number the reason would want is **measured at run time** and
#: travels in the report, so prose and measurement cannot drift apart here.
R5_TARGET: tuple[float, float] = (20.0, -410.0)
C13_TARGET: tuple[float, float] = (110.0, -375.0)

LOCK_EDITS: dict[str, dict] = {
    "R5": {
        "why": (
            "same-column(Q1, R5) is measured between the two parts' pins on "
            "the net they share (SRC), not between their origins — so the "
            "landing points break it even though both origins sit on x = 0: "
            "Q1's SRC pin and R5's SRC pin land 20 units apart (a lattice "
            "multiple, far outside grid/2).  Neither part may be moved by the "
            "relax pass (both are chain parts, and a lock fixes them both), so "
            "the place that fixes it is the lock: +20 in x puts R5's SRC pin "
            "directly under Q1's — which is what 岳 110 c/d's own reason asks "
            "for ('the source→sense→primary-ground return is one straight "
            "run').  See the report's measured pin pair for both sets."
        ),
    },
    "C13": {
        "why": (
            "121b's own edit (岳 2026-10-06: 'T1 副边侧近旁, hypot ≤ 300, 与 C11 "
            "并排').  C13 is an output cap: its reason (岳 110 a/f) is that it "
            "hangs below the rectifier it filters and returns SEC_12V to "
            "SEC_GND, so it keeps C11's own column below D3.  near(C13, T1) is "
            "measured between C13.2 and T1.6 on SEC_GND, the net they share, "
            "and that pair is what the landing point overshoots — the report "
            "carries both the landing distance and this one."
        ),
    },
}

#: The plan's own coordinates are the skeleton; a lock for a part with no edit
#: is its landing point verbatim.
HAND_EDITED = tuple(sorted(LOCK_EDITS))


def _page():
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    #: **The pipeline's own reader** — `draw plan` reads the library through
    #: `drawapply.load_library`; see `tools/121_hand_plan_dump.py::_page` for
    #: the measurement that made the fixture loader untenable here (it drops
    #: `pin.length`, and the router routes differently without it).
    book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")
    return circuit, presentation, book


def _skeleton(circuit, presentation, book) -> tuple[object, object, object]:
    """``(ctx, binding, plan)`` for the 2.2/pose-0 rung, gate stood aside for the read.

    **The whole ladder is walked, in the compiler's own order** — not just the
    target rung.  `_place` caches "what the tightest rung breaks" on the
    context, so a rung's plan depends on the rungs tried before it: measured
    2026-10-09, reading C13's landing by placing the 2.2 rung *alone* gives
    (110, -375), while the compiler, which starts at spacing = 1, lands it at
    (110, -450).  A skeleton that skips the earlier rungs is not the plan
    `draw plan` would make, and a lock table built from it mis-states which
    coordinates are the rung's own.
    """
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        for variant in dc._variants(ctx):
            built, failure, _ = dc._build_candidate(ctx, variant)
            if variant.label != SKELETON_VARIANT:
                continue
            if built is None:
                raise SystemExit(
                    f"the skeleton rung {SKELETON_VARIANT} no longer builds: "
                    f"{failure.category} {failure.subject}: {failure.detail}")
            return ctx, binding, built.plan
    finally:
        dc._relation_failures = saved
    raise SystemExit(f"the ladder has no rung {SKELETON_VARIANT}")


def _targets(c13: tuple[float, float] | None = None) -> dict[str, tuple[float, float]]:
    """The hand-edit targets, with C13 overridable so a spot can be tried."""
    out = {"R5": R5_TARGET, "C13": c13 or C13_TARGET}
    return out


def _lock_table(plan, *, edits: bool,
                targets: dict[str, tuple[float, float]] | None = None
                ) -> dict[str, dict]:
    targets = targets or _targets()
    table: dict[str, dict] = {}
    for part in plan.parts:
        x, y = part.x, part.y
        if edits and part.part_id in targets:
            x, y = targets[part.part_id]
        table[part.part_id] = {
            "x": x,
            "y": y,
            "rotation": part.rotation,
            "landing_x": part.x,
            "landing_y": part.y,
            "edited": bool(edits and part.part_id in targets),
        }
    return table


def _locked(presentation: PresentationSpec, table: dict[str, dict]) -> PresentationSpec:
    return dataclasses.replace(
        presentation,
        user_locks=[
            UserLock(part_id=part_id, x=row["x"], y=row["y"],
                     rotation=row["rotation"])
            for part_id, row in sorted(table.items())
        ],
    )


def _plan_relation_rows(plan, circuit, binding, book, ctx) -> list[dict]:
    """The finished plan's relation verdicts — check_grammar's own ruler."""
    progress = ctx.progress
    rows = []
    for item, points in dc._relation_violations(
        circuit, binding,
        origin_of=lambda part_id: dc._plan_origin(plan, part_id),
        pin_of=lambda part_id, token: dc._plan_pin(plan, book, part_id, token),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        lateral=(-progress[1], progress[0]), progress=progress,
    ):
        rows.append({
            "kind": item.kind, "subject": item.subject, "object": item.object,
            "points": [list(point) for point in points],
        })
    return rows


def _pair_measure(plan, circuit, binding, book, kind, subject, other) -> dict:
    """The two points (and their distance) one named relation is measured between.

    The same ``_points_for_relation`` the checker uses, so a number written in
    the report is the number the compiler weighed — pins on the shared net for
    ``near`` and ``same-column``, origins otherwise.
    """
    for item in binding.constraints:
        if (item.kind, item.subject, item.object) != (kind, subject, other):
            continue
        points = dc._points_for_relation(
            circuit, item,
            origin_of=lambda part_id: dc._plan_origin(plan, part_id),
            pin_of=lambda part_id, token: dc._plan_pin(plan, book, part_id, token),
        )
        if points is None:
            return {"kind": kind, "subject": subject, "object": other,
                    "points": None}
        (ax, ay), (bx, by) = points
        return {
            "kind": kind, "subject": subject, "object": other,
            "points": [list(points[0]), list(points[1])],
            "hypot": math.hypot(ax - bx, ay - by),
        }
    return {"kind": kind, "subject": subject, "object": other,
            "points": None}


def _run(circuit, presentation, book, budget):
    """One real compile + the plan-level readings, as a report dict."""
    result = dc.compile(circuit, presentation, book, budget)
    report: dict = {
        "ok": result.ok,
        "notes": list(result.notes),
        "failure_categories": result.categories(),
        "failures": [
            {"category": item.category, "subject": item.subject,
             "detail": item.detail, "action": item.action}
            for item in result.failures
        ],
        "rejected": [
            {"variant": item.variant, "reason": item.reason}
            for item in result.rejected
        ],
    }
    if result.ok:
        plan = result.best()
        report["ranked"] = [
            {"variant": item.describe_key(), "metrics": dict(item.metrics),
             "geometry_sha256": item.plan.geometry_sha256()}
            for item in result.ranked
        ]
        report["best"] = {
            "counts": {
                "parts": len(plan.parts), "texts": len(plan.texts),
                "labels": len(plan.labels), "segments": len(plan.segments),
                "power_symbols": len(plan.power_symbols),
            },
            "hard_violations": list(plan.evidence.hard_violations),
            "grammar_findings": list(plan.evidence.grammar_findings),
            "labels": sorted(
                ({"net": label.net, "x": label.x, "y": label.y}
                 for label in plan.labels),
                key=lambda row: (row["net"], row["x"], row["y"])),
            "power_symbols": [
                {"net": symbol.net, "symbol_ref": symbol.symbol_ref,
                 "x": symbol.x, "y": symbol.y}
                for symbol in plan.power_symbols
            ],
        }
    return result, report


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    c13 = None
    if len(argv) > 2 and argv[2]:
        x, _, y = argv[2].partition(",")
        c13 = (float(x), float(y))
    out.mkdir(parents=True, exist_ok=True)
    targets = _targets(c13)

    circuit, presentation, book = _page()
    ctx, binding, plan = _skeleton(circuit, presentation, book)

    budget = dc.CompileBudget()
    report: dict = {
        "skel": {
            "variant": SKELETON_VARIANT,
            "budget": dataclasses.asdict(budget) if dataclasses.is_dataclass(budget)
            else repr(budget),
            "landing_points": {
                part.part_id: {"x": part.x, "y": part.y,
                               "rotation": part.rotation, "mirror": part.mirror}
                for part in sorted(plan.parts, key=lambda p: p.part_id)
            },
            "relation_violations": _plan_relation_rows(
                plan, circuit, binding, book, ctx),
        },
        "lock_edits": LOCK_EDITS,
        "hand_edited_parts": list(HAND_EDITED),
        "targets": {part_id: list(point) for part_id, point in targets.items()},
    }

    # --- 0. the baseline: the same compile with no locks at all -------------
    base_result, base_report = _run(circuit, presentation, book, budget)
    report["no_locks"] = base_report

    # --- 1. the literal lock set (19 landings, no hand edit) ----------------
    literal_table = _lock_table(plan, edits=False)
    literal_spec = _locked(presentation, literal_table)
    lit_result, lit_report = _run(circuit, literal_spec, book, budget)
    report["literal_locks"] = lit_report

    # --- 2. the delivered lock set (hand edits in place) -------------------
    table = _lock_table(plan, edits=True, targets=targets)
    locked_spec = _locked(presentation, table)
    spec_file = out / "121b_locked_presentation.json"
    locked_spec.dump(spec_file)
    report["lock_table"] = table
    report["locked_presentation"] = spec_file.name

    result, run_report = _run(circuit, locked_spec, book, budget)
    report["locked"] = run_report

    # The two pairs the hand edits were decided on, measured on both plans —
    # the numbers LOCK_EDITS' reasons point at, so they cannot drift apart.
    report["hand_edit_measurements"] = {
        "near(C13, T1)": {
            "limit": budget.near_limit,
            "at the landing point": _pair_measure(
                plan, circuit, binding, book, "near", "C13", "T1"),
            "at the delivered lock": (
                _pair_measure(result.best(), circuit, binding, book,
                              "near", "C13", "T1") if result.ok else None),
        },
        "same-column(Q1, R5)": {
            "at the landing point": _pair_measure(
                plan, circuit, binding, book, "same-column", "Q1", "R5"),
            "at the delivered lock": (
                _pair_measure(result.best(), circuit, binding, book,
                              "same-column", "Q1", "R5") if result.ok else None),
        },
    }

    written: list[str] = [spec_file.name]
    if result.ok:
        best = result.best()
        checked = rb.check(best, circuit, locked_spec, book,
                           page_box=budget.page_box,
                           keepouts=budget.keepouts, grid=budget.grid)
        report["locked"]["best"]["readability"] = {
            "checker": rb.CHECKER_NAME,
            "hard_violations": [v.render() for v in checked.hard_violations],
        }
        report["locked"]["best"]["relation_violations_from_plan"] = (
            _plan_relation_rows(best, circuit, binding, book, ctx))

        svg = svgpreview.render_svg(best, book)
        for name, text in (
            ("121b_locked_candidate.svg", svg),
            ("121b_locked_candidate.layout.json",
             json.dumps(best.to_jsonable(), indent=2, ensure_ascii=False)
             + "\n"),
        ):
            (out / name).write_text(text, encoding="utf-8")
            written.append(name)
        report["locked"]["best"]["svg_sha256"] = hashlib.sha256(
            svg.encode("utf-8")).hexdigest()

        lcsc = {part.id: part.lcsc for part in circuit.parts if part.lcsc}
        lcsc.update(LCSC_OVERRIDES)
        doc = None
        plan_error = ""
        try:
            change_plan = drawapply.module_plan(
                best, circuit, locked_spec, book,
                candidate_index=0,
                lcsc_by_part=lcsc,
                pool=[], baseline=None, baseline_findings=[],
                notes=[
                    "121b hand-plan path: every part is locked at the 2.2/pose-0 "
                    "rung's own landing point; " + ", ".join(HAND_EDITED)
                    + " carry a recorded hand edit (see 121b_report.json)"
                ],
            )
            doc = change_plan.to_jsonable()
        except Exception as exc:  # a plan error must not hide the compile result
            plan_error = f"{type(exc).__name__}: {exc}"
        report["locked"]["change_plan_error"] = plan_error
        if doc is not None:
            (out / "121b_locked_change_plan.json").write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            written.append("121b_locked_change_plan.json")

    (out / "121b_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    written.append("121b_report.json")

    # ------------------------------------------------------------ the summary
    def _say(name: str, item: dict) -> None:
        print(f"  {name}: ok={item['ok']}", end="")
        if item["ok"]:
            best = item["best"]
            print(f" parts={best['counts']['parts']} "
                  f"labels={best['counts']['labels']} "
                  f"segments={best['counts']['segments']} "
                  f"flags={best['counts']['power_symbols']} "
                  f"hard={len(best['hard_violations'])} "
                  f"findings={len(best['grammar_findings'])}")
        else:
            print(f" categories={item['failure_categories']}")
            for failure in item["failures"][:4]:
                print(f"      [{failure['category']}] {failure['subject']}: "
                      f"{failure['detail'][:150]}")

    print(f"121b hand-plan locks — skeleton {SKELETON_VARIANT}, "
          f"{len(table)} locks ({len(HAND_EDITED)} hand-edited)")
    _say("no locks       ", report["no_locks"])
    _say("literal landings", report["literal_locks"])
    _say("delivered locks ", report["locked"])
    for row in report["skel"]["relation_violations"]:
        print(f"    skeleton violation: {row['kind']}({row['subject']}, "
              f"{row['object']}) {tuple(row['points'][0])} / "
              f"{tuple(row['points'][1])}")
    if report["locked"]["ok"]:
        for row in report["locked"]["best"]["relation_violations_from_plan"]:
            print(f"    LOCKED plan still violates: {row['kind']}"
                  f"({row['subject']}, {row['object']}) {row['points']}")
    print("wrote: " + ", ".join(written))
    return 0 if report["locked"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
