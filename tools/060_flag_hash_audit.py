#!/usr/bin/env python3
"""060 evidence: which scenario geometries a flag-rotation change moves, and how.

    .venv/Scripts/python.exe tools/060_flag_hash_audit.py [OUT.txt]

Compiles every offline scenario whose geometry summary contains a flag rotation —
053B's twelve, 056's eight, and 057's three page scenes — and prints one line per
scenario:

    <name> | ok=<bool> | drawing=<sha256> | page=<sha256> | flags=[…]

with each flag as ``(<net> @(<x>,<y>) rot <rotation> <symbolRef>)``. Run it once
before and once after a change and diff the two files: 060 sec.3 only allows the
flag rotation to move, so any *other* difference between the two runs is a finding
rather than a hash update.

**The scenarios are not restated here.** 053B's twelve and 056's eight come from
their own test modules — the same single source of truth `tools/053b_previews.py`
and `tools/056_previews.py` use. The three 057 page shapes are the compiler calls
`tools/057_scenarios.py`'s ``o1``/``e2``/``e3`` make, repeated so their plans can
be read: their printed digests are checked against that tool's own SVG captions
during the 060 audit, so a shape that drifted apart from the tool shows up as a
digest that does not match.

Nothing here writes a plan, runs a rule engine or touches the editor.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_053b_drawcompiler as b053  # noqa: E402
import test_056_pagecompiler as m056  # noqa: E402

from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawapply, pagecompiler  # noqa: E402


class _NoPlan:
    """A refusal has no flags — said explicitly rather than left blank."""

    power_symbols: tuple = ()


def _flags(plan) -> str:
    """``[(net @(x, y) rot R sym), …]`` — the field this audit is about."""
    return "[" + ", ".join(
        f"({symbol.net} @({symbol.x:g},{symbol.y:g}) rot {symbol.rotation:g} "
        f"{symbol.symbol_ref})"
        for symbol in plan.power_symbols
    ) + "]"


def _line(name: str, ok: bool, drawing: str, page: str, plan) -> str:
    return f"{name} | ok={ok} | drawing={drawing} | page={page} | flags={_flags(plan)}"


def drawings() -> list[str]:
    """053B's twelve scenarios — `test_053b_drawcompiler.compile_scene` each."""
    out: list[str] = []
    for index, scene in sorted(b053.scenes().items()):
        result = b053.compile_scene(scene)
        if not result.candidates:
            out.append(_line(f"053b.scene{index:02d}", False, "refused", "-", _NoPlan()))
            continue
        plan = result.candidates[0]
        out.append(_line(
            f"053b.scene{index:02d}", result.ok, plan.geometry_sha256()[:16], "-", plan,
        ))
    return out


def pages() -> list[str]:
    """056's eight page scenarios — `test_056_pagecompiler.compile_scene` each."""
    out: list[str] = []
    for index, scene in sorted(m056.scenes().items()):
        result = m056.compile_scene(scene)
        if not result.pages:
            out.append(_line(
                f"056.scene{index:02d}", False, "refused", "refused", _NoPlan(),
            ))
            continue
        page = result.pages[0]
        out.append(_line(
            f"056.scene{index:02d}", result.ok,
            page.plan.geometry_sha256()[:16], page.page_geometry_sha256()[:16],
            page.plan,
        ))
    return out


def _page_line(name: str, result, ok: bool = True) -> str:
    if not result.pages:
        return _line(name, False, "refused", "-", _NoPlan())
    page = result.pages[0]
    return _line(
        name, ok and result.ok, page.plan.geometry_sha256()[:16],
        page.page_geometry_sha256()[:16], page.plan,
    )


def page_scenes() -> list[str]:
    """057's three offline page scenes, as `tools/057_scenarios.py` builds them."""
    out: list[str] = []

    # o1 — the divider driven by a declared signal input port (the tool's shape).
    circuit = b053.circuit(
        [b053.part("R1", "R0402", "10k"), b053.part("R2", "R0402", "10k")],
        [
            b053.net("SENSE", "signal", ["R1.1"]),
            b053.net("ADC", "signal", ["R1.2", "R2.1"]),
            b053.net("GND", "gnd", ["R2.2"]),
        ],
    )
    for tag, roles in (("declared", {"SENSE": "input", "ADC": "output"}),
                       ("undeclared", {"ADC": "output"})):
        presentation = b053.presentation(
            "voltage-divider",
            modules=[b053.module("d", ["R1", "R2"], "divider")],
            portRoles=roles,
        )
        result = b053.dc.compile(circuit, presentation, b053.library())
        if not result.candidates:
            out.append(_line(f"057.O1.{tag}", False, "refused", "-", _NoPlan()))
            continue
        plan = result.candidates[0]
        out.append(_line(
            f"057.O1.{tag}", result.ok, plan.geometry_sha256()[:16], "-", plan,
        ))

    # e2 — 056's chain compiled around a census (the tool's own census literal).
    scene = m056.scenes()[2]
    census = {
        "components": [
            {"primitiveId": "c-R9", "state": {"ComponentType": "part", "Designator": "R9",
                                              "X": 100, "Y": 700, "SupplierId": "C25744",
                                              "OtherProperty": {"Value": "1k"}}},
            {"primitiveId": "f-1", "state": {"ComponentType": "netflag", "Net": "GND",
                                             "X": 100, "Y": 600}},
        ],
        "wires": [{"primitiveId": "w-1", "state": {"Line": [100, 750, 380, 750],
                                                   "Net": "OLD"}}],
        "bboxes": {"c-R9": {"minX": 80, "minY": 640, "maxX": 120, "maxY": 760}},
    }
    boxes, _labels, _notes = drawapply.census_keepouts(census)
    budget = dataclasses.replace(
        scene.budget, keepouts=tuple(boxes), relocate_around_keepouts=True,
    )
    out.append(_page_line("057.E2", pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), budget,
    )))

    # e3 — 056's second scene with R1 pinned to a page point.
    scene = m056.scenes()[1]
    payload = scene.presentation.to_jsonable()
    payload["userLocks"] = [{"partId": "R1", "x": 600, "y": 500, "scope": "page"}]
    out.append(_page_line("057.E3", pagecompiler.compile_page(
        scene.circuit, PresentationSpec.from_dict(payload), m056.library(),
        scene.budget,
    )))
    return out


def main(argv: list[str]) -> int:
    lines = [*drawings(), *pages(), *page_scenes()]
    text = "\n".join(lines) + "\n"
    if len(argv) > 1:
        Path(argv[1]).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    sys.stdout.write(
        f"\n{len(lines)} scenario lines; two runs over one revision are "
        "byte-identical (the compiler is deterministic)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
