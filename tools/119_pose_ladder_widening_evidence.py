#!/usr/bin/env python3
"""119: what the pose-ladder widening actually did, measured and written down.

    .venv/Scripts/python.exe tools/119_pose_ladder_widening_evidence.py [out-dir]

This is 118's ``118_preview.py`` with a different question. 118 stood the
relation gate aside to get a picture of a page the compiler refused; 119's page
is still refused, and what 119 wants on the record is **the search itself**:

* which relation the six base rungs were refused by, and that it was **one**
  relation (that is the widening's ignition condition, stated as a fact about
  this page);
* which rungs the widening added, and that **none of them** is refused by that
  relation any more — the rescue, rung by rung;
* what each widened rung *is* refused by instead, so the reader can see the page
  moved forward one relation and is still red, for a written-down reason;
* the **next** blocker behind those, measured rather than inferred: with the
  relation gate stood aside, every rung still fails on ``net 'HVDC'``.

Nothing here is softened.  The real ``readability.check`` verdict is recorded
wherever a plan exists; where no plan exists, the tool says so and writes the
refusal instead of a picture.  A picture of nothing is not evidence, which is
why the file names carry ``NOT_A_PLAN``.
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

import test_113_flyback_grammar as t113  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
DEFAULT_OUT = ROOT / "outputs" / "119" / "previews"

#: Written into every artefact, so a preview is never read as a passing compile.
DISCLAIMER = (
    "NOT a passing compile. The flyback page is still refused on the measured "
    "seven-pin library. 119's widening rescued the relation the base ladder was "
    "refused by; the page is red for the next, different relation, and behind "
    "that for the HVDC direct wire. The compiler's own verdicts are recorded "
    "below verbatim; no gate is softened to produce a picture."
)


def _page():
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    return circuit, presentation, book


def _blocked_rejections(result) -> list[dict]:
    out = []
    for item in result.rejected:
        out.append({
            "variant": item.variant,
            "rung": "widened" if "(widened)" in item.variant else "base",
            "relation": list(dc._refusing_relation(item.failure) or ()),
            "reason": item.reason,
        })
    return out


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    circuit, presentation, book = _page()
    result = dc.compile(circuit, presentation, book,
                        dc.CompileBudget(max_candidates=64))

    rejections = _blocked_rejections(result)
    base = [item for item in rejections if item["rung"] == "base"]
    wide = [item for item in rejections if item["rung"] == "widened"]
    base_relations = {tuple(item["relation"]) for item in base}
    wide_relations = {tuple(item["relation"]) for item in wide}

    notes = " ".join(result.notes)
    print(f"as compiled: ok={result.ok} candidates={len(result.candidates)} "
          f"failures={len(result.failures)} rejected={len(result.rejected)}")
    print(f"  base rungs: {len(base)}, all naming {sorted(base_relations)}")
    print(f"  widened rungs: {len(wide)}, naming {sorted(wide_relations)}")
    print(f"  the widening fired: {'pose ladder was widened' in notes}")

    # The next blocker behind the relations, measured with the relation gate
    # stood aside — 118's own method, on 119's page.
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context
    routing = []
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        for scale in ctx.budget.spacing_ladder:
            for index in (0, 2):
                built, failure, _ = dc._build_candidate(
                    ctx, dc._Variant(label=f"{scale:g}-{index}", scale=scale,
                                     pose_index=index))
                routing.append({
                    "variant": f"spacing={scale:g} pose-variant={index}",
                    "built": built is not None,
                    "category": failure.category if failure else "",
                    "subject": failure.subject if failure else "",
                    "detail": failure.detail if failure else "",
                })
    finally:
        dc._relation_failures = saved
    blockers = sorted({
        (item["category"], item["subject"]) for item in routing
        if not item["built"]
    })
    print(f"  with the relation gate stood aside: "
          f"{sum(1 for i in routing if not i['built'])}/{len(routing)} rungs "
          f"still fail, on {blockers}")

    payload = {
        "disclaimer": DISCLAIMER,
        "compile": {
            "ok": result.ok,
            "candidates": len(result.candidates),
            "failures": [item.render() if hasattr(item, "render")
                         else item.detail for item in result.failures],
            "notes": list(result.notes),
        },
        "widening": {
            "base_rungs": len(base),
            "base_relations": sorted(list(rel) for rel in base_relations),
            "one_relation_in_common": len(base_relations) == 1,
            "widened_rungs": len(wide),
            "widened_relations": sorted(list(rel) for rel in wide_relations),
            "rescued": not any(
                rel == ("same-column", "Q1", "R5") for rel in wide_relations
            ),
        },
        "rejections": rejections,
        "next_blocker_with_relations_stood_aside": routing,
        "transformer": {
            "symbolRef": "XFMR-XREE16-050624",
            "lcsc": "C49118510",
            "body": list(book["XFMR-XREE16-050624"].body),
            "body_extent": [
                book["XFMR-XREE16-050624"].body[2] - book["XFMR-XREE16-050624"].body[0],
                book["XFMR-XREE16-050624"].body[3] - book["XFMR-XREE16-050624"].body[1],
            ],
            "note": (
                "the 118b probe's measured bbox. The five-pin part it replaced "
                "was 40x40, so the body grew about 8.5x in area, which is what "
                "pushes the chain's D3 onto the HVDC row."
            ),
        },
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    file = out / "119_widening_evidence.json"
    file.write_text(body, encoding="utf-8")
    print(f"  {file.relative_to(ROOT).as_posix()} "
          f"sha256={hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}")
    if result.candidates:
        print("UNEXPECTED: this tool is written for a page the compiler refuses; "
              "if the page now compiles, its disclaimer is stale")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
