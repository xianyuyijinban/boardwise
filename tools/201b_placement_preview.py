#!/usr/bin/env python3
"""201B stage 1: the placement module's own preview, side by side with the compiler's.

    .venv/Scripts/python.exe tools/201b_placement_preview.py [output-dir] [scenario ...]

Stage 1 of 201B adds ``engines/placement.py`` and wires it to **nothing** — the
compiler's ``_place`` is untouched (201A is editing that file in parallel). So
this tool is what shows the new search's work: for each scenario it

1. runs the compiler exactly as the existing preview tools do, and records what
   it produced (**the before** — for the flyback that is "0 candidates, every
   variant refused by ``same-column(Q1, R5)``");
2. builds a :class:`~boardwise.engines.placement.PlacementInput` out of the same
   four things the task book names — the part list, the netlist, each part's
   accepted pose set (the compiler's own ``_accepted_poses``口径, read from the
   ``_Context`` its stage 2 builds) and the grammar's relations;
3. runs :func:`boardwise.engines.placement.place`;
4. writes both drawings as SVG, plus a JSON with the placement, the cost list and
   the gate's reading.

The SVG is a *placement* preview, not a compiled page: parts, their pins, the
netlist drawn as nearest-neighbour runs, and each part's designator. Flags,
labels and routing are the compiler's stage 3b onwards and are deliberately out
of scope here — what this picture answers is the question 岳 asks first, "does
the topology read".

Determinism: the search is seeded, so two runs write byte-identical files. The
tool re-runs the search a second time and reports the two placements' sha256 in
the JSON, so "same input, same output" is a reading and not a claim.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.layoutplan import (  # noqa: E402
    LayoutPart,
    LayoutPlan,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import (  # noqa: E402
    DEFAULT_POSES,
    SymbolPin,
    SymbolPose,
    SymbolProfile,
)
from boardwise.core.textmetrics import CANVAS_TEXT_UNITS, render_width  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import placement as pl  # noqa: E402
from boardwise.engines import readability as rb  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"
DRAWAPPLY = ROOT / "tests" / "fixtures" / "drawapply"
DEFAULT_OUT = ROOT / "outputs" / "201b" / "previews"

#: scenario -> (circuit, presentation, library)
SCENARIOS: dict[str, tuple[Path, Path, Path]] = {
    "flyback": (
        SPECS / "flyback_uc3845.circuit.json",
        SPECS / "flyback_uc3845.presentation.json",
        SPECS / "flyback_uc3845.library.json",
    ),
    "power_entry": (
        SPECS / "power_entry_xt30.circuit.json",
        SPECS / "power_entry_xt30.presentation.json",
        SPECS / "power_entry_xt30.library.json",
    ),
    "divider": (
        DRAWAPPLY / "divider.circuit.json",
        DRAWAPPLY / "divider.presentation.json",
        DRAWAPPLY / "library.json",
    ),
}


def _library_from(path: Path) -> dict[str, SymbolProfile]:
    """The library sidecar, read into the book the compiler is handed.

    The same reader the flyback test uses (``test_113_flyback_grammar.
    _library_from``); repeated here rather than imported so the tool runs from a
    clean checkout with no test module import.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        poses = entry.get("poses")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                SymbolPin(
                    number=str(pin["number"]),
                    tip=(float(pin["tip"][0]), float(pin["tip"][1])),
                    name=str(pin.get("name", "")),
                    direction=str(pin.get("direction", "")),
                )
                for pin in entry["pins"]
            ],
            poses=(
                [SymbolPose(int(p["rotation"]), bool(p["mirror"])) for p in poses]
                if poses else list(DEFAULT_POSES)
            ),
        )
    return book


def _request(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    book: dict[str, SymbolProfile],
    binding,
    ctx,
    budget: dc.CompileBudget,
) -> pl.PlacementInput:
    """The four inputs, read off the compiler's own stage-2 context.

    ``ctx`` is what ``drawcompiler._prepare`` built: the accepted pose set per
    part (``_accepted_poses`` — the caliber the task book names), the chain
    direction it derived from the presentation's side preferences, the locks.
    Reading them from there rather than re-deriving them is what keeps this run
    and the eventual wired-in compiler from being two different drawings.
    """
    parts: list[pl.PlacementPart] = []
    for part_id in sorted(ctx.slots):
        locked = dc._locked_pose(ctx, part_id, ctx.accepted[part_id])
        parts.append(pl.PlacementPart(
            part_id=part_id,
            profile=ctx.profile(part_id),
            poses=tuple(ctx.accepted[part_id]),
            locked=locked,
        ))
    nets = tuple(
        pl.PlacementNet(
            net_id=net.id,
            members=tuple(
                (member.partition(".")[0], member.partition(".")[2])
                for member in net.members
            ),
            cls=net.cls,
        )
        for net in circuit.nets
    )
    relations = tuple(
        pl.PlacementRelation(
            kind=item.kind, subject=item.subject, object=item.object,
            reason=item.reason,
        )
        for item in binding.constraints
    )
    side_preferences = {
        role: (presentation.side_for(role) or fallback)
        for role, fallback in pl.DEFAULT_SIDE_PREFERENCES.items()
    }
    return pl.PlacementInput(
        parts=tuple(parts), nets=nets, relations=relations,
        progress=ctx.progress, lateral=ctx.lateral(),
        side_preferences=side_preferences,
        page_box=budget.page_box, keepouts=tuple(budget.keepouts),
        grid=budget.grid, near_limit=budget.near_limit,
        channel=budget.channel, lane=budget.lane,
    )


def _state_from_plan(plan: LayoutPlan) -> pl._State:
    return pl._State(
        origins={item.part_id: (item.x, item.y) for item in plan.parts},
        poses={
            item.part_id: SymbolPose(int(item.rotation), item.mirror)
            for item in plan.parts
        },
    )


def _wires(request: pl.PlacementInput, state: pl._State) -> list[LayoutSegment]:
    """The netlist as a sketch: each net joined by nearest-neighbour runs.

    Not routing — a straight run from each pin to the nearest not-yet-joined pin
    on the same net. It is there so the picture answers "is this pin next to what
    it connects to", which is the whole of concept 2, without pretending to be
    the compiler's stage 3b.
    """
    pins = pl._pins_of(request, state)
    out: list[LayoutSegment] = []
    for net in request.nets:
        points = [
            (owner, pin, pins[owner][pin])
            for owner, pin in sorted(net.members)
            if owner in pins and pin in pins[owner]
        ]
        if len(points) < 2:
            continue
        remaining = [point for _, _, point in points]
        runs: list[tuple[float, float]] = [remaining.pop(0)]
        while remaining:
            last = runs[-1]
            nearest = min(
                remaining,
                key=lambda point: (
                    (point[0] - last[0]) ** 2 + (point[1] - last[1]) ** 2,
                    point[0], point[1],
                ),
            )
            remaining.remove(nearest)
            runs.append(nearest)
        out.append(LayoutSegment(net=net.net_id, points=runs))
    return out


def _plan(
    request: pl.PlacementInput,
    state: pl._State,
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    *,
    with_wires: bool = False,
) -> LayoutPlan:
    """A :class:`LayoutPlan` carrying the placement, so the one renderer draws it."""
    parts: list[LayoutPart] = []
    texts: list[LayoutText] = []
    for part in request.parts:
        pose = state.poses[part.part_id]
        origin = state.origins[part.part_id]
        parts.append(LayoutPart(
            part_id=part.part_id, symbol_ref=part.profile.symbol_ref,
            symbol_hash=part.profile.geometry_hash(),
            x=origin[0], y=origin[1],
            rotation=float(pose.rotation), mirror=pose.mirror,
        ))
        width = render_width(part.part_id)
        box = pl.part_box(part.profile, pose, origin)
        texts.append(LayoutText(
            kind="reference", text=part.part_id, part_id=part.part_id,
            bbox=(box[0], box[3] + 2.0, box[0] + width, box[3] + 2.0 + CANVAS_TEXT_UNITS),
            x=box[0] + width / 2.0, y=box[3] + 2.0 + CANVAS_TEXT_UNITS / 2.0,
        ))
    return LayoutPlan(
        source=LayoutSource(
            circuit_sha256=circuit.sha256(),
            presentation_sha256=presentation.sha256(),
        ),
        parts=parts,
        segments=_wires(request, state) if with_wires else [],
        texts=texts,
    )


def _scenario(
    name: str,
    circuit_path: Path,
    presentation_path: Path,
    library_path: Path,
    out: Path,
) -> dict:
    circuit = CircuitSpec.load(circuit_path)
    presentation = PresentationSpec.load(presentation_path)
    book = _library_from(library_path)
    budget = dc.CompileBudget(max_candidates=64)
    compiled = dc.compile(circuit, presentation, book, budget)

    report: dict = {
        "scenario": name,
        "circuit": _display(circuit_path),
        "compiler": {
            "ok": compiled.ok,
            "candidates": len(compiled.candidates),
            "rejected": len(compiled.rejected),
            "failures": [
                {"category": item.category, "subject": item.subject,
                 "detail": item.detail[:400]}
                for item in compiled.failures
            ],
        },
    }
    if not compiled.grammar.ok:
        report["placement"] = {"skipped": "the grammar refused this circuit"}
        return report

    ctx = dc._prepare(circuit, presentation, compiled.grammar, book, budget).context
    assert ctx is not None
    request = _request(circuit, presentation, book, compiled.grammar, ctx, budget)

    started = time.perf_counter()
    result = pl.place(request)
    elapsed = time.perf_counter() - started
    again = pl.place(request)
    digest = hashlib.sha256(
        json.dumps(result.placement(), sort_keys=True).encode("utf-8")
    ).hexdigest()
    digest_again = hashlib.sha256(
        json.dumps(again.placement(), sort_keys=True).encode("utf-8")
    ).hexdigest()

    state = pl._State(dict(result.origins), dict(result.poses))
    plan = _plan(request, state, circuit, presentation)
    svg = svgpreview.render_svg(plan, book)
    svg_file = out / f"201b_{name}_placement.svg"
    svg_file.write_text(svg, encoding="utf-8")
    # The same placement with the netlist sketched in (nearest-neighbour runs,
    # not routing). The composition is the readable one; the sketch answers "is
    # this pin next to what it connects to".
    wired_plan = _plan(request, state, circuit, presentation, with_wires=True)
    wired = svgpreview.render_svg(wired_plan, book)
    wired_file = out / f"201b_{name}_placement_wired.svg"
    wired_file.write_text(wired, encoding="utf-8")
    checked = rb.check(wired_plan, circuit, presentation, book)
    report["placement"] = {
        "elapsed_s": round(elapsed, 3),
        "iterations": result.iterations,
        "accepted": result.accepted,
        "seed": result.seed,
        "placement_sha256": digest,
        "placement_sha256_second_run": digest_again,
        "deterministic": digest == digest_again,
        "svg": _display(svg_file),
        "svg_sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        "svg_wired": _display(wired_file),
        "svg_wired_sha256": hashlib.sha256(wired.encode("utf-8")).hexdigest(),
        "costs": [item.to_jsonable() for item in result.costs],
        "hard": [item.render() for item in result.hard],
        "soft": [item.render() for item in result.soft],
        "notes": list(result.notes),
        "placement": [
            {"partId": part_id, "x": x, "y": y, "rotation": rotation,
             "mirror": mirror}
            for part_id, (x, y, rotation, mirror)
            in sorted(result.placement().items())
        ],
        # The placement preview is not a compiled page (no flags, no routed
        # wires), so the readability contract is reported as a reading, not as a
        # verdict — its wire and text half has nothing to measure yet.
        "readability_hard_violations": [
            item.render() for item in checked.hard_violations
        ],
    }

    if compiled.candidates:
        before = compiled.candidates[0]
        before_state = _state_from_plan(before)
        report["compiler"]["best_candidate"] = {
            "costs": [
                item.to_jsonable()
                for item in pl.evaluate(request, before_state)
                if item.violated
            ],
        }
        before_svg = svgpreview.render_svg(
            _plan(request, before_state, circuit, presentation), book
        )
        before_file = out / f"201b_{name}_compiler_before.svg"
        before_file.write_text(before_svg, encoding="utf-8")
        report["compiler"]["best_candidate"]["svg"] = _display(before_file)
    return report


def _display(path: Path) -> str:
    """The path as a report writes it: repo-relative when it is in the repo."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main(argv: list[str]) -> int:
    out = (Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT).resolve()
    names = argv[2:] or list(SCENARIOS)
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    for name in names:
        if name not in SCENARIOS:
            print(f"unknown scenario {name!r}; known: {sorted(SCENARIOS)}")
            return 2
        circuit_path, presentation_path, library_path = SCENARIOS[name]
        print(f"== {name}")
        report = _scenario(name, circuit_path, presentation_path, library_path, out)
        reports.append(report)
        print(f"   compiler: ok={report['compiler']['ok']} "
              f"candidates={report['compiler']['candidates']} "
              f"rejected={report['compiler']['rejected']}")
        placement = report.get("placement", {})
        if "elapsed_s" in placement:
            print(f"   placement: {placement['elapsed_s']}s, "
                  f"{placement['iterations']} iters, "
                  f"deterministic={placement['deterministic']}")
            for line in placement["hard"]:
                print(f"     HARD {line}")
            for line in placement["soft"][:6]:
                print(f"     soft {line}")
            print(f"     {placement['svg']}")
    (out / "201b_preview_report.json").write_text(
        json.dumps(reports, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
