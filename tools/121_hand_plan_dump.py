#!/usr/bin/env python3
"""121: dump every buildable flyback candidate for the hand-plan path (岳's option 2).

    .venv/Scripts/python.exe tools/121_hand_plan_dump.py [out-dir]

120 closed with the page still refused: ladder rungs died in routing, and the
relation gate hid the rest.  岳 ruled (2026-10-06): take the hand-plan path —
pick a buildable rung, pin the few placements the compiler could not solve by
hand, re-route, lint, apply.

This tool is the first step: it writes, for **every** ladder rung,

* whether it builds (relation gate stood aside, readability gate **real**);
* which relations the rung violates, measured on the **finished plan** with
  ``_relation_violations`` — `check_grammar`'s own ruler over ``plan.parts``
  (origins and posed pin tips).  A rung that builds is measured there, so the
  table is exactly what the gate and the checker would read and every row
  carries the two points it was measured between.  A rung that does **not**
  build is measured on the placement the compiler reached before the plan was
  assembled, and the row says so (``relation_violations_ruler``);
* the real readability verdict on the built plan, verbatim;
* the full plan JSON (``drawapply.module_plan`` output — the exact document
  ``draw apply`` would consume) and an SVG preview.

Nothing here is a passing compile.  Every artefact's name carries
``RELATION_GATE_STOOD_ASIDE``; the disclaimer is inside every JSON.

**The library is read the way `draw plan` reads it** (:func:`_page`): a
fixture loader that drops a pin's drawn length changes what the router draws
from one and the same placement, and a dump that is not the pipeline's drawing
is no use for choosing a rung to pin.

A no-arg run writes into :data:`DEFAULT_OUT`
(``outputs/121/buildable``) — the directory 121a's artefacts came from.  The
two are not the same landscape (121a used the fixture loader, and the router
then labelled CLAMP instead of wiring it), so re-running with no argument
replaces that landmark; name an out-dir when the comparison matters.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import drawapply  # noqa: E402
from boardwise.engines import readability as rb  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
DEFAULT_OUT = ROOT / "outputs" / "121" / "buildable"

DISCLAIMER = (
    "NOT a passing compile. This plan exists only because the relation gate "
    "was stood aside so the page could be looked at (岳's option-2 hand-plan "
    "path, 2026-10-06). The relation violations listed are the real ones, "
    "measured with check_grammar's own ruler over the finished plan where a "
    "plan came out (see relation_violations_ruler); the readability verdict is "
    "the real checker's, unsoftened."
)

#: 岳 2026-10-04 ruling: the two 75k 0603 RCD resistors are C23242.
LCSC_OVERRIDES = {"R3": "C23242", "R15": "C23242"}


def _page():
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    #: **The pipeline's own reader.**  `draw plan` reads the library through
    #: `drawapply.load_library`, and this tool must hand the compiler the same
    #: book or it dumps a drawing the pipeline would not make.  Measured
    #: 2026-10-09: `test_113`'s fixture loader drops `pin.length` (and the
    #: profiles' notes), and the router, which reads a pin's drawn length, then
    #: routes the **same placement** differently — 17 wires against the real
    #: reader's 19 on the hand-plan candidate.
    book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")
    return circuit, presentation, book


def _plan_violations(plan, circuit, binding, book, ctx) -> list[dict]:
    """The relations the **finished plan** does not keep — the checker's own ruler.

    ``_relation_violations`` is called exactly as ``check_grammar`` calls it
    (same ``origin_of`` / ``pin_of`` over ``plan.parts``, same lateral axis),
    so a row here is a row the gate would report on this plan.  The two
    measured points travel with the row: a table of prose cannot be re-checked
    by hand, coordinates can.
    """
    progress = ctx.progress
    out: list[dict] = []
    for item, points in dc._relation_violations(
        circuit, binding,
        origin_of=lambda part_id: dc._plan_origin(plan, part_id),
        pin_of=lambda part_id, token: dc._plan_pin(plan, book, part_id, token),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        lateral=(-progress[1], progress[0]), progress=progress,
    ):
        out.append({
            "kind": item.kind,
            "subject": item.subject,
            "object": item.object,
            "points": [list(point) for point in points],
            "reason": item.reason,
        })
    return out


def _placement_violations(ctx, placed) -> list[dict]:
    """The same table for a rung that never reached a plan (pre-build placement)."""
    out: list[dict] = []
    for item, points in dc._relation_violations(
        ctx.circuit, ctx.binding,
        origin_of=lambda part_id: placed.origins.get(part_id),
        pin_of=lambda part_id, token: dc._pin_point(
            ctx, part_id, token, placed.poses, placed.origins),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        lateral=ctx.lateral(), progress=ctx.progress,
    ):
        out.append({
            "kind": item.kind,
            "subject": item.subject,
            "object": item.object,
            "points": [list(point) for point in points],
            "reason": item.reason,
        })
    return out


def _render_rows(rows: list[dict]) -> list[str]:
    return [
        f"the relation {row['kind']}({row['subject']}, {row['object']}) is not "
        f"kept by the plan: the two points measured are "
        f"{tuple(row['points'][0])} and {tuple(row['points'][1])}"
        for row in rows
    ]


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    circuit, presentation, book = _page()
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context

    index: list[dict] = []
    saved_rel = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        for variant in dc._variants(ctx):
            placed, place_failure = dc._place(ctx, variant)
            built, failure, _ = dc._build_candidate(ctx, variant)
            if built is not None:
                rows = _plan_violations(built.plan, circuit, binding, book, ctx)
                ruler = "plan.parts (check_grammar's own ruler)"
                relations = _render_rows(rows)
            elif placed is not None:
                rows = _placement_violations(ctx, placed)
                ruler = ("the placement this rung reached before the plan was "
                         "assembled (no plan came out of it)")
                relations = _render_rows(rows)
            else:
                rows, relations = [], []
                ruler = "none (no placement was reached)"
            entry = {
                "variant": variant.label,
                "scale": variant.scale,
                "pose_index": variant.pose_index,
                "placed": placed is not None,
                "relation_violations_ruler": ruler,
                "relation_violations": relations,
                "relation_violation_points": rows,
                "built": built is not None,
                "build_failure": (
                    {"category": failure.category, "subject": failure.subject,
                     "detail": failure.detail}
                    if failure else None
                ),
            }
            if built is None:
                index.append(entry)
                continue
            plan = built.plan
            checked = rb.check(plan, circuit, presentation, book,
                               page_box=ctx.budget.page_box,
                               keepouts=ctx.budget.keepouts, grid=ctx.budget.grid)
            entry["readability"] = {
                "checker": rb.CHECKER_NAME,
                "hard_violations": [v.render() for v in checked.hard_violations],
            }
            slug = variant.label.replace(" ", "_").replace("=", "")
            svg = svgpreview.render_svg(plan, book)
            svg_file = out / f"121_{slug}_RELATION_GATE_STOOD_ASIDE.svg"
            svg_file.write_text(svg, encoding="utf-8")

            lcsc = {p.id: p.lcsc for p in circuit.parts if p.lcsc}
            lcsc.update(LCSC_OVERRIDES)
            doc = None
            plan_error = ""
            try:
                change_plan = drawapply.module_plan(
                    plan, circuit, presentation,
                    {ref: book[ref] for ref in book} if False else
                    {p.symbol_ref: book[p.symbol_ref] for p in circuit.parts},
                    candidate_index=0,
                    lcsc_by_part=lcsc,
                    pool=[], baseline=None, baseline_findings=[],
                    notes=["121 hand-plan dump; " + DISCLAIMER],
                )
                doc = change_plan.to_jsonable()
            except Exception as exc:  # the dump must survive a plan error
                plan_error = f"{type(exc).__name__}: {exc}"
            payload = {
                "disclaimer": DISCLAIMER,
                "variant": variant.label,
                "relation_violations_ruler": ruler,
                "relation_violations": relations,
                "relation_violation_points": rows,
                "readability": entry["readability"],
                "counts": {
                    "parts": len(plan.parts), "texts": len(plan.texts),
                    "labels": len(plan.labels), "segments": len(plan.segments),
                    "power_symbols": len(plan.power_symbols),
                },
                "layout": plan.to_jsonable(),
                "change_plan": doc,
                "change_plan_error": plan_error,
                "svg_sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
            }
            json_file = out / f"121_{slug}_RELATION_GATE_STOOD_ASIDE.json"
            json_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            index.append(entry)
            print(f"  {variant.label}: built, {len(relations)} relation "
                  f"violation(s), {len(checked.hard_violations)} hard readability"
                  f" violation(s)"
                  + (f", change_plan ERROR {plan_error}" if plan_error else ""))
            for row in rows:
                print(f"    relation: {row['kind']}({row['subject']}, "
                      f"{row['object']}) measured on the finished plan between "
                      f"{tuple(row['points'][0])} and {tuple(row['points'][1])}")
    finally:
        dc._relation_failures = saved_rel

    summary = out / "121_index.json"
    summary.write_text(json.dumps(index, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    built_n = sum(1 for e in index if e["built"])
    print(f"built {built_n}/{len(index)} rungs; index -> "
          f"{summary.resolve().relative_to(ROOT).as_posix()}")
    return 0 if built_n else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
