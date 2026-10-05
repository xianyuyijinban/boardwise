#!/usr/bin/env python3
"""118: render what the flyback page actually is under the **measured** library.

    .venv/Scripts/python.exe tools/118_preview.py [output-dir]

117 wrote `tools/117_flyback_preview.py` for the page 113's **hand-written**
profiles produced, and that page drew.  118 replaced those profiles with the
ones the host actually has, and this page **does not compile** — so the same
tool now honestly reports that and writes nothing.

That is the finding, but it is not the whole picture, and a picture of nothing
is not evidence.  Measured on the measured library (see `outputs/118/SUMMARY.md`):

* the page is refused at `same-column(Q1, R5)` in **all six** variants;
* with that one relation stood aside, **four** of six variants still cannot wire
  their direct-wire nets (the parts are bigger than 113 drew them, the corridor is
  tighter);
* **two** variants do produce a plan — and on those, 117(2)'s text/flag fix
  holds exactly (**0** `text-overlap`, 0 text-on-body, 0 flag-on-body).

So this tool writes those two plans, **with both gates named in the file name and
in the JSON**, so nobody can mistake them for a passing compile.  The gate is
**not** softened for the numbers: the real `readability.check` runs on the plan
that comes out and its verdict is recorded verbatim.
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
from boardwise.engines import readability as rb  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

import test_113_flyback_grammar as t113  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
DEFAULT_OUT = ROOT / "outputs" / "118" / "previews"

#: Recorded in every artefact this tool writes, so a preview is never read as a
#: passing compile when it is not one.
DISCLAIMER = (
    "NOT a passing compile. The flyback page is refused under the measured "
    "library at `same-column(Q1, R5)` in all six variants; this plan exists "
    "only because that one relation was stood aside so the page could be looked "
    "at. The readability gate's own verdict on it is recorded below verbatim."
)


def _soft(real, plan, *args, **kwargs):
    result = real(plan, *args, **kwargs)
    result.hard_violations = []
    return result


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")

    result = dc.compile(circuit, presentation, book,
                        dc.CompileBudget(max_candidates=64))
    print(f"as compiled: ok={result.ok} candidates={len(result.candidates)} "
          f"failures={len(result.failures)} rejected={len(result.rejected)}")
    for item in result.failures:
        print(f"  [{item.category}] {item.detail[:180]}")

    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context

    real = rb.check
    real_rel = dc._relation_failures
    dc.readability.check = lambda plan, *a, **k: _soft(real, plan, *a, **k)
    dc._relation_failures = lambda ctx_, placed_: []
    written = []
    try:
        for variant in dc._variants(ctx):
            built, _failure, _ = dc._build_candidate(ctx, variant)
            if built is None:
                continue
            plan = built.plan
            checked = real(plan, circuit, presentation, book,
                           page_box=ctx.budget.page_box,
                           keepouts=ctx.budget.keepouts, grid=ctx.budget.grid)
            slug = variant.label.replace(" ", "_").replace("=", "")
            svg = svgpreview.render_svg(plan, book)
            svg_file = out / f"118_flyback_{slug}_RELATION_GATE_STOOD_ASIDE.svg"
            svg_file.write_text(svg, encoding="utf-8")
            payload = {
                "disclaimer": DISCLAIMER,
                "variant": variant.label,
                "gate_verdict": {
                    "checker": rb.CHECKER_NAME,
                    "hard_violation_count": len(checked.hard_violations),
                    "hard_violations": [v.render() for v in checked.hard_violations],
                },
                "svg_sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
                "counts": {
                    "parts": len(plan.parts), "texts": len(plan.texts),
                    "labels": len(plan.labels), "segments": len(plan.segments),
                },
                "parts": [
                    {"id": p.part_id, "symbol": p.symbol_ref,
                     "x": p.x, "y": p.y, "rotation": p.rotation,
                     "mirror": p.mirror}
                    for p in sorted(plan.parts, key=lambda i: i.part_id)
                ],
                "notes": list(plan.notes),
            }
            json_file = out / f"118_flyback_{slug}_RELATION_GATE_STOOD_ASIDE.json"
            json_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            written += [svg_file, json_file]
            print(f"  {variant.label}: {len(checked.hard_violations)} hard "
                  f"violation(s), {payload['counts']['parts']} parts, "
                  f"svg {payload['svg_sha256'][:16]}")
            print(f"    {svg_file.relative_to(ROOT).as_posix()}")
    finally:
        dc.readability.check = real
        dc._relation_failures = real_rel
    if not written:
        print("no variant yields a plan even with the relation gate stood aside")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
