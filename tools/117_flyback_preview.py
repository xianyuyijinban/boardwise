#!/usr/bin/env python3
"""117: the flyback page's candidate, rendered to SVG — the first one there is.

    .venv/Scripts/python.exe tools/117_flyback_preview.py [output-dir]

The compiler has never produced this page before (113/114/115/116 each left it
refused, and 116's §一 records "no candidate preview could be written, because a
plan that did not pass the gate has no preview"). 117 turned the page green, so
this writes it.

Two files per candidate, so the evidence is checkable without opening an SVG:
the render plus a JSON fingerprint of the plan (parts, texts, labels, wires and
the gate's own reading). The gate is re-run here on the finished plan — the
number in the JSON is the one to believe, not this script's say-so.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
DEFAULT_OUT = ROOT / "outputs" / "117" / "previews"


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    result = dc.compile(circuit, presentation, book,
                        dc.CompileBudget(max_candidates=64))
    print(f"ok={result.ok} candidates={len(result.candidates)} "
          f"failures={len(result.failures)} rejected={len(result.rejected)}")
    if not result.ok or not result.candidates:
        for item in result.failures:
            print(f"  [{item.category}] {item.detail[:200]}")
        for item in result.rejected:
            print(f"  rejected {item.variant}: {item.reason[:160]}")
        return 1

    written: list[Path] = []
    for index, candidate in enumerate(result.candidates, 1):
        plan = candidate
        checked = rb.check(plan, circuit, presentation, book)
        svg = svgpreview.render_svg(plan, book)
        svg_file = out / f"117_flyback_cand{index}.svg"
        svg_file.write_text(svg, encoding="utf-8")
        written.append(svg_file)

        payload = {
            "candidate": index,
            "circuit_sha256": plan.source.circuit_sha256,
            "svg_sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
            "gate": {
                "checker": rb.CHECKER_NAME,
                "hard_violations": [item.render() for item in checked.hard_violations],
                "hard_violation_count": len(checked.hard_violations),
            },
            "counts": {
                "parts": len(plan.parts),
                "texts": len(plan.texts),
                "labels": len(plan.labels),
                "power_symbols": len(plan.power_symbols),
                "segments": len(plan.segments),
            },
            "parts": [
                {"id": item.part_id, "symbol": item.symbol_ref,
                 "x": item.x, "y": item.y,
                 "rotation": item.rotation, "mirror": item.mirror}
                for item in sorted(plan.parts, key=lambda i: i.part_id)
            ],
            "texts": [
                {"kind": item.kind, "part": item.part_id, "text": item.text,
                 "bbox": list(item.bbox)}
                for item in plan.texts
            ],
            "labels": [
                {"net": item.net, "part": item.part_id, "text": item.text,
                 "anchor": [item.x, item.y], "bbox": list(item.bbox)}
                for item in plan.labels
            ],
            "notes": list(plan.notes),
        }
        json_file = out / f"117_flyback_cand{index}.json"
        json_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        written.append(json_file)
        print(f"  cand{index}: {len(checked.hard_violations)} hard violation(s), "
              f"svg sha256 {payload['svg_sha256'][:16]}, "
              f"{payload['counts']['parts']} parts / "
              f"{payload['counts']['segments']} wires")
        print(f"           {svg_file.relative_to(ROOT).as_posix()}")
        print(f"           {json_file.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
