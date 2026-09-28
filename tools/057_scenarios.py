"""057 offline evidence: the page scenes a machine without an editor can run.

Usage::

    .venv/Scripts/python.exe tools/057_scenarios.py [OUT_DIR]

Writes (default ``outputs/057_offline/``, gitignored) one artefact per offline
scene, then prints a manifest (name, sha256, size) so two runs can be compared
byte for byte:

* ``O1_*`` — the voltage divider driven by a declared signal port (057 sec.7.1):
  the preview, and the binding's evidence for the ``in`` role;
* ``O2_timing.txt`` — 056 scene 7's shape, per-variant time with the page
  router's memo and, for comparison, with the module router it memoises (same
  pages, byte for byte — the file says so);
* ``E2_*`` — a page compiled around a census (existing primitives as keep-outs,
  relocated as a rigid body), and the page a full census refuses, named;
* ``E3_*`` — a page lock (the part on its point in every candidate) and the
  three lock refusals;
* ``E6_*`` — the CH340G integration attempt (057 sec.6): the real symbols of the
  repo's golden fixture (`tests/fixtures/ch340_golden.epro2`, read only), a 9-part
  "core + crystal + decoupling + USB" module set, what the page compiler says
  about it, what each existing grammar says about each module, and the one
  module of the golden board a grammar exists for (its RT9013 LDO). **Nothing is
  tuned to make it pass** (057 sec.6 / 052: not a CH340-specific layouter) — the
  refusals are the finding.

The scenes are built here from hand-written JSON and the 056 test module's own
scenes (single source of truth, the 053B/056 rule), so this script and the tests
cannot drift apart.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import test_053b_drawcompiler as b053  # noqa: E402
import test_056_pagecompiler as m056  # noqa: E402

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import from_parsed_symbol  # noqa: E402
from boardwise.engines import drawapply, drawcompiler, pagecompiler, svgpreview  # noqa: E402
from boardwise.parsers.schematic import (  # noqa: E402
    build_schematic_model,
    collect_symbol_details,
)

DEFAULT_OUT = ROOT / "outputs" / "057_offline"
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"
PROV = "verified_recipe"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------- O1


def o1(out: Path) -> list[Path]:
    circuit = b053.circuit(
        [b053.part("R1", "R0402", "10k"), b053.part("R2", "R0402", "10k")],
        [
            b053.net("SENSE", "signal", ["R1.1"]),
            b053.net("ADC", "signal", ["R1.2", "R2.1"]),
            b053.net("GND", "gnd", ["R2.2"]),
        ],
    )
    written = []
    for tag, roles in (("declared", {"SENSE": "input", "ADC": "output"}),
                       ("undeclared", {"ADC": "output"})):
        presentation = b053.presentation(
            "voltage-divider",
            modules=[b053.module("d", ["R1", "R2"], "divider")],
            portRoles=roles,
        )
        result = drawcompiler.compile(circuit, presentation, b053.library())
        lines = [f"O1 signal-top divider, top {tag}: ok={result.ok} "
                 f"categories={result.categories()}"]
        if result.ok:
            for binding in result.grammar.bindings:
                lines.append(f"  {binding.role:<10} {binding.part_id:<6} {binding.evidence[:160]}")
            written.append(svgpreview.write_preview(
                out / f"O1_{tag}_cand1.svg", result.candidates[0], b053.library(),
                title="057 O1: divider driven by a declared signal input port",
            ))
        else:
            lines.append(result.render_failures())
        written.append(_write(out / f"O1_{tag}.txt", "\n".join(lines) + "\n"))
    return written


# ------------------------------------------------------------------- O2


def o2(out: Path) -> list[Path]:
    scene = m056.scenes()[7]
    lines = ["O2: 056 scene 7's shape (three modules, two main-path edges, a 6-member ground)"]
    documents = {}
    for label, router in (("page router (memo)", pagecompiler._PageRouter),
                          ("module router (no memo)", drawcompiler.lattice_router)):
        original_router = pagecompiler._PageRouter
        pagecompiler._PageRouter = router
        original = pagecompiler._assemble
        times: list[tuple[str, float, bool]] = []

        def timed(ctx, variant, _original=original, _times=times):
            started = time.perf_counter()
            answer = _original(ctx, variant)
            _times.append((variant.label, time.perf_counter() - started, answer[0] is not None))
            return answer

        pagecompiler._assemble = timed
        try:
            started = time.perf_counter()
            result = pagecompiler.compile_page(
                scene.circuit, scene.presentation, m056.library(), scene.budget,
            )
            total = time.perf_counter() - started
        finally:
            pagecompiler._assemble = original
            pagecompiler._PageRouter = original_router
        documents[label] = [json.dumps(page.to_jsonable(), sort_keys=True) for page in result.pages]
        lines.append(f"\n{label}: total {total:.2f} s, slowest variant "
                     f"{max(item[1] for item in times):.2f} s, {len(result.pages)} page(s)")
        for name, seconds, ok in times:
            lines.append(f"  {seconds:7.3f} s  {'page   ' if ok else 'refused'}  {name}")
        lines.append("  pages: " + ", ".join(page.page_geometry_sha256()[:12] for page in result.pages))
    same = len(set(json.dumps(value) for value in documents.values())) == 1
    lines.append(
        "\nthe two routers produce byte-identical page documents: "
        + ("YES — the memo changes the time, not the answer" if same else "NO")
    )
    return [_write(out / "O2_timing.txt", "\n".join(lines) + "\n")]


# ------------------------------------------------------------------- E2 / E3


def e2(out: Path) -> list[Path]:
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
    boxes, labels, notes = drawapply.census_keepouts(census)
    budget = dataclasses.replace(
        scene.budget, keepouts=tuple(boxes), relocate_around_keepouts=True,
    )
    result = pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), budget,
    )
    lines = ["E2 offline: the chain (056 scene 2) compiled around a census",
             *[f"  keepouts[{index}] {box} <- {label}"
               for index, (box, label) in enumerate(zip(boxes, labels))],
             *[f"  note: {note}" for note in notes],
             f"result: ok={result.ok} pages={len(result.pages)}"]
    written = []
    if result.ok:
        page = result.pages[0]
        lines.append("  frames: " + ", ".join(
            f"{module.id} {tuple(round(value) for value in module.frame)}"
            for module in page.modules))
        written.append(svgpreview.write_preview(
            out / "E2_census_cand1.svg", page.plan, m056.library(),
            page_box=budget.page_box, keepouts=budget.keepouts,
            frames=[(module.id, module.frame) for module in page.modules],
            title="057 E2 (offline): the page placed around the existing primitives",
        ))
    full = dataclasses.replace(budget, keepouts=((0.0, 0.0, 1169.0, 826.0),))
    refused = pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), full,
    )
    lines += ["", "a census that covers the whole sheet:",
              f"  ok={refused.ok} categories={refused.categories()}",
              *[f"  {line}" for line in refused.render_failures().splitlines()]]
    written.append(_write(out / "E2_census.txt", "\n".join(lines) + "\n"))
    return written


def e3(out: Path) -> list[Path]:
    scene = m056.scenes()[1]
    written = []
    lines = []
    cases = {
        "lock R1 at (600, 500)": [{"partId": "R1", "x": 600, "y": 500, "scope": "page"}],
        "two locks disagree": [{"partId": "R1", "x": 600, "y": 500, "scope": "page"},
                               {"partId": "R2", "x": 600, "y": 500, "scope": "page"}],
        "lock off the page": [{"partId": "R1", "x": 3000, "y": 500, "scope": "page"}],
        "frame off the page": [{"partId": "U1", "x": 25, "y": 25, "scope": "page"}],
    }
    for title, locks in cases.items():
        payload = scene.presentation.to_jsonable()
        payload["userLocks"] = locks
        presentation = PresentationSpec.from_dict(payload)
        result = pagecompiler.compile_page(
            scene.circuit, presentation, m056.library(), scene.budget,
        )
        lines.append(f"{title}: ok={result.ok} pages={len(result.pages)} "
                     f"categories={result.categories()}")
        if result.ok:
            for index, page in enumerate(result.pages):
                part = page.plan.part(locks[0]["partId"])
                origins = {module.id: module.origin for module in page.modules}
                lines.append(f"  candidate {index + 1}: {locks[0]['partId']} at "
                             f"({part.x:g}, {part.y:g}); origins {origins}")
            written.append(svgpreview.write_preview(
                out / "E3_lock_cand1.svg", result.pages[0].plan, m056.library(),
                page_box=scene.budget.page_box,
                frames=[(module.id, module.frame) for module in result.pages[0].modules],
                title="057 E3 (offline): R1 pinned to the page point (600, 500)",
            ))
        else:
            lines += [f"  {line}" for line in result.render_failures().splitlines()]
    written.append(_write(out / "E3_locks.txt", "\n".join(lines) + "\n"))
    return written


# ------------------------------------------------------------------- E6


def _golden_profiles() -> tuple[dict, dict]:
    """``(designator -> symbolRef, symbolRef -> SymbolProfile)`` from the golden board."""
    model = build_schematic_model(GOLDEN)
    details = collect_symbol_details(GOLDEN)
    refs: dict[str, str] = {}
    book = {}
    for designator, component in model.components.items():
        uuid = str(component.props.get("library_symbol_uuid") or "")
        if uuid in details and details[uuid].offsets:
            refs[designator] = uuid
            if uuid not in book:
                book[uuid] = from_parsed_symbol(details[uuid], source=f"golden:{component.mpn}")
    return refs, book


def e6(out: Path) -> list[Path]:
    model = build_schematic_model(GOLDEN)
    refs, book = _golden_profiles()
    for ref in ("PWR-GND", "PWR-VCC", "PWR-+5V"):
        book[ref] = b053.flag(ref)
    chosen = ["U1", "C1", "C6", "X1", "C3", "C25", "USB1", "R24", "R27"]
    values = {"C1": "100nF", "C6": "100nF", "C3": "30pF", "C25": "30pF",
              "R24": "5.1k", "R27": "5.1k", "U1": "CH340G", "X1": "12MHz",
              "USB1": "TYPE-C"}
    parts = [
        {"id": designator, "symbolRef": refs[designator], "value": values[designator],
         "lcsc": model.components[designator].lcsc_part, "provenance": PROV}
        for designator in chosen
    ]
    classes = {"GND": "gnd", "VCC": "power", "+5V": "power"}
    nets = []
    for name, found in sorted(model.nets.items()):
        members = sorted(
            f"{designator}.{pin}" for designator, pin in found.pins if designator in chosen
        )
        if not members:
            continue
        nets.append({"id": name, "class": classes.get(name, "signal"),
                     "members": members, "provenance": PROV})
    circuit = CircuitSpec.from_dict({"parts": parts, "nets": nets})
    modules = [
        {"id": "core", "parts": ["U1", "C1", "C6"], "role": "CH340G and its decoupling"},
        {"id": "xtal", "parts": ["X1", "C3", "C25"], "role": "crystal and load caps"},
        {"id": "usb", "parts": ["USB1", "R24", "R27"], "role": "USB-C and its CC pull-downs"},
    ]
    page_box = (0.0, 0.0, 1169.0, 826.0)
    lines = [
        "E6 offline: the CH340G complete module (057 sec.6), real golden-fixture symbols",
        f"parts ({len(parts)}): " + ", ".join(
            f"{item['id']}={item['value']}({book[item['symbolRef']].title})" for item in parts),
        "nets: " + "; ".join(f"{item['id']}[{item['class']}] {' '.join(item['members'])}"
                             for item in nets),
        "",
        "1) as a page with no grammar for these groups (the only grammars are "
        f"{', '.join(drawcompiler_grammars())}):",
    ]
    presentation = PresentationSpec.from_dict({"modules": modules, "flow": [["usb", "core"], ["xtal", "core"]]})
    result = pagecompiler.compile_page(
        circuit, presentation, book, pagecompiler.PageCompileBudget(page_box=page_box),
    )
    lines += [f"   ok={result.ok} categories={result.categories()}",
              *[f"   {line}" for line in result.render_failures().splitlines()], "",
              "2) each module under each grammar the build has (what the binder says):"]
    for module in modules:
        for grammar in drawcompiler_grammars():
            sub = PresentationSpec.from_dict({
                "grammarRef": grammar,
                "modules": [{"id": module["id"], "parts": module["parts"], "role": module["role"]}],
            })
            local_circuit, _local = pagecompiler._module_view(
                circuit, presentation, presentation.module(module["id"]),
            )
            compiled = drawcompiler.compile(local_circuit, sub, book)
            first = compiled.failures[0] if compiled.failures else None
            lines.append(
                f"   {module['id']:<5} x {grammar:<16} ok={compiled.ok} "
                f"{compiled.categories()} "
                + ((first.detail[:230] + "…") if first is not None else "")
            )
    lines += ["", "3) the golden board's one module a grammar exists for — its RT9013 LDO:"]
    ldo_parts = ["U5", "C4", "C9"]
    ldo_values = {"U5": "RT9013-33GB", "C4": "1uF", "C9": "2.2uF"}
    ldo_circuit = CircuitSpec.from_dict({
        "parts": [{"id": designator, "symbolRef": refs[designator],
                   "value": ldo_values[designator],
                   "lcsc": model.components[designator].lcsc_part, "provenance": PROV}
                  for designator in ldo_parts],
        "nets": [
            {"id": name, "class": classes.get(name, "signal"),
             "members": sorted(f"{d}.{p}" for d, p in found.pins if d in ldo_parts),
             "provenance": PROV}
            for name, found in sorted(model.nets.items())
            if any(d in ldo_parts for d, _p in found.pins)
        ],
        "nc": ["U5.4"],
    })
    for sides in ({}, {"input": "left", "output": "right"}, {"input": "left", "output": "bottom"}):
        ldo_presentation = PresentationSpec.from_dict({
            "grammarRef": "ldo",
            "modules": [{"id": "ldo", "parts": ldo_parts, "role": "regulator"}],
            "portRoles": {"+5V": "input", "VCC": "output"},
            **({"sidePreferences": sides} if sides else {}),
        })
        compiled = drawcompiler.compile(ldo_circuit, ldo_presentation, book)
        lines.append(f"   sidePreferences={sides or 'default'}: ok={compiled.ok} "
                     f"candidates={len(compiled.candidates)} {compiled.categories()}")
        if not compiled.ok:
            lines += [f"     {line[:300]}" for line in compiled.render_failures().splitlines()[:3]]
        elif not any(path.name == "E6_rt9013_cand1.svg" for path in out.glob("E6_*.svg")):
            svgpreview.write_preview(
                out / "E6_rt9013_cand1.svg", compiled.candidates[0], book,
                title=f"057 E6: the golden board's RT9013 LDO module (sides {sides or 'default'})",
            )
    # Pit 33's remedy is the input side (sidePreferences), never the compiler:
    # every combination is tried, so "no side works" is a measurement.
    import itertools

    sides = ("left", "right", "top", "bottom")
    tried = 0
    working = []
    for inp, outp, gnd in itertools.product(sides, repeat=3):
        if inp == outp:
            continue
        tried += 1
        compiled = drawcompiler.compile(ldo_circuit, PresentationSpec.from_dict({
            "grammarRef": "ldo",
            "modules": [{"id": "ldo", "parts": ldo_parts, "role": "regulator"}],
            "portRoles": {"+5V": "input", "VCC": "output"},
            "sidePreferences": {"input": inp, "output": outp, "gnd": gnd},
        }), book)
        if compiled.ok:
            working.append((inp, outp, gnd))
    symbol = book[refs["U5"]]
    lines += [
        f"   sweep: {tried} sidePreferences combinations (input x output x gnd), "
        f"{len(working)} compile: {working or 'none'}",
        "   the symbol: " + ", ".join(
            f"{pin.number}:{pin.name}@{pin.direction}" for pin in symbol.pins
        ) + " — VIN, GND and EN share the left side (the AMS1117 family of pit 33, "
        "but GND is on the input side here, which no side preference separates)",
    ]
    written = [_write(out / "E6_ch340g.txt", "\n".join(lines) + "\n")]
    written.extend(sorted(out.glob("E6_*.svg")))
    return written


def drawcompiler_grammars() -> tuple[str, ...]:
    from boardwise.core.presentationspec import GRAMMARS

    return GRAMMARS


def manifest(paths: list[Path]) -> str:
    return "\n".join(
        f"{path.name}  {hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"{path.stat().st_size} bytes"
        for path in paths
    )


def main(argv: list[str]) -> int:
    out = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*"):
        if stale.is_file():
            stale.unlink()
    written: list[Path] = []
    for step in (o1, o2, e2, e3, e6):
        paths = step(out)
        written.extend(paths)
        print(f"{step.__name__}: " + ", ".join(path.name for path in paths))
    print(f"\n{len(written)} file(s) in {out}")
    print(manifest([path for path in written if path.name != "O2_timing.txt"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
