#!/usr/bin/env python3
"""121: dump every buildable flyback candidate for the hand-plan path (岳's option 2).

    .venv/Scripts/python.exe tools/121_hand_plan_dump.py [out-dir]

120 closed with the page still refused: 12 of 24 ladder rungs build a plan when
the relation gate is stood aside, the other 12 die in routing.  岳 ruled
(2026-10-06): take the hand-plan path — pick a buildable rung, pin the few
placements the compiler could not solve by hand, re-route, lint, apply.

This tool is the first step: it writes, for **every** ladder rung,

* whether it builds (relation gate stood aside, readability gate **real**);
* which relations the rung violates, measured with the real
  ``_relation_failures`` on that rung's own placement (never softened);
* the real readability verdict on the built plan, verbatim;
* the full plan JSON (``drawapply.module_plan`` output — the exact document
  ``draw apply`` would consume) and an SVG preview.

Nothing here is a passing compile.  Every artefact's name carries
``RELATION_GATE_STOOD_ASIDE``; the disclaimer is inside every JSON.
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

import test_113_flyback_grammar as t113  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
DEFAULT_OUT = ROOT / "outputs" / "121" / "buildable"

DISCLAIMER = (
    "NOT a passing compile. This plan exists only because the relation gate "
    "was stood aside so the page could be looked at (岳's option-2 hand-plan "
    "path, 2026-10-06). The relation violations listed are the real ones, "
    "measured on this rung's own placement; the readability verdict is the "
    "real checker's, unsoftened."
)

#: 岳 2026-10-04 ruling: the two 75k 0603 RCD resistors are C23242.
LCSC_OVERRIDES = {"R3": "C23242", "R15": "C23242"}


def _page():
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    return circuit, presentation, book


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
            relations = (
                [f.render() if hasattr(f, "render") else str(f)
                 for f in saved_rel(ctx, placed)]
                if placed is not None else []
            )
            built, failure, _ = dc._build_candidate(ctx, variant)
            entry = {
                "variant": variant.label,
                "scale": variant.scale,
                "pose_index": variant.pose_index,
                "placed": placed is not None,
                "relation_violations": relations,
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
                "relation_violations": relations,
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
            for rel in relations:
                print(f"    relation: {rel}")
    finally:
        dc._relation_failures = saved_rel

    summary = out / "121_index.json"
    summary.write_text(json.dumps(index, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    built_n = sum(1 for e in index if e["built"])
    print(f"built {built_n}/{len(index)} rungs; index -> "
          f"{summary.relative_to(ROOT).as_posix()}")
    return 0 if built_n else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
