"""R3: KiCad as the second host — the offline minimum loop.

The fixture ``tests/fixtures/kicad_min/`` is self-built
(``tools/R3_make_kicad_fixture.py``) and carries KiCad's **own** readings of
itself next to the design: ``kicad_min.net`` is kicad-cli's netlist of the
schematic and ``kicad_min.pcbnew.json`` is pcbnew's geometry of the board. The
parser is held to those two, so every transform below is a measurement of
KiCad, not an assumption carried over from the EasyEDA reader.

The circuit carries defects on purpose, and the loop is closed when the
existing rules name them on a KiCad input:

* two parts named ``R3``                       → ``conn-duplicate-designators`` (ERROR)
* AMS1117 VO with only 100 nF (shelf: ≥ 22 µF) → ``decap-required-caps`` (WARN)
* a 10 mΩ shunt no IC reads                    → ``shunt-sense-link``
* C2 0.15 mm from R3 on the board               → ``pcb-component-spacing`` (WARN; KiCad's
  own DRC reports the same 0.15 mm)
* C2 far from U1                                → ``pcb-decap-distance`` (WARN)
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from boardwise.engines.pcbreview import run_pcb_review
from boardwise.engines.review import run_review
from boardwise.parsers.kicad import (
    MM_TO_MIL,
    Atom,
    KicadFormatError,
    _sheet_point,
    is_kicad_path,
    kicad_project_files,
    load_kicad,
    parse_sexpr,
    read_kicad_board,
    read_kicad_board_model,
    read_kicad_schematic_model,
    schematic_connectivity,
)

FIX = Path(__file__).parent / "fixtures" / "kicad_min"
PRO = FIX / "kicad_min.kicad_pro"
SCH = FIX / "kicad_min.kicad_sch"
PCB = FIX / "kicad_min.kicad_pcb"
REPO = Path(__file__).resolve().parents[1]


def _oracle_nets() -> Counter:
    """kicad-cli's netlist as a multiset of (net, ref, pin), root ``/`` stripped."""
    tree = parse_sexpr((FIX / "kicad_min.net").read_text(encoding="utf-8"))
    nets = next(c for c in tree if isinstance(c, list) and c[0] == "nets")
    out = Counter()
    for net in nets[1:]:
        name = next(c for c in net if isinstance(c, list) and c[0] == "name")[1]
        if name.startswith("unconnected-"):
            continue
        for node in (c for c in net if isinstance(c, list) and c[0] == "node"):
            fields = {c[0]: c[1] for c in node[1:]}
            out[(name.removeprefix("/"), fields["ref"], fields["pin"])] += 1
    return out


# ---------------------------------------------------------------------------
# S-expressions and project files
# ---------------------------------------------------------------------------


def test_the_reader_tells_atoms_from_strings_and_decodes_escapes():
    tree = parse_sexpr('(a 1.5 "two words" (b yes "q\\"uote\\\\") ())')
    assert tree[0] == "a" and isinstance(tree[0], Atom)
    assert tree[1] == "1.5" and isinstance(tree[1], Atom)
    assert tree[2] == "two words" and not isinstance(tree[2], Atom)
    assert tree[3] == ["b", "yes", 'q"uote\\']
    assert tree[4] == []
    for bad in ("(a (b)", "(a))", '(a "open', "a b"):
        with pytest.raises(KicadFormatError):
            parse_sexpr(bad)


def test_any_of_the_three_names_finds_the_same_siblings(tmp_path):
    for name in (PRO, SCH, PCB):
        assert is_kicad_path(name)
        assert kicad_project_files(name) == (SCH, PCB)
    assert not is_kicad_path(FIX.parent / "ch340_golden.epro2")
    lonely = tmp_path / "x.kicad_pro"
    lonely.write_text("{}", encoding="utf-8")
    assert kicad_project_files(lonely) == (None, None)
    with pytest.raises(KicadFormatError, match="no schematic next to"):
        load_kicad(lonely)
    with pytest.raises(KicadFormatError, match="no board next to"):
        load_kicad(lonely, view="pcb")
    broken = tmp_path / "y.kicad_pro"
    broken.write_text("not json", encoding="utf-8")
    with pytest.raises(KicadFormatError, match="not a KiCad project"):
        load_kicad(broken)


# ---------------------------------------------------------------------------
# the schematic, against kicad-cli's own netlist
# ---------------------------------------------------------------------------


def test_the_geometric_solve_reproduces_kicads_netlist_pin_for_pin():
    """Every placed pin (both R3s included) lands on the net kicad-cli put it on."""
    solved = schematic_connectivity(SCH)
    ours = Counter((name, solved.placed[i].ref, number) for (i, number), name in solved.net_of.items())
    assert ours == _oracle_nets()
    assert solved.dangling_tees == []


@pytest.mark.parametrize(
    ("rot", "mirror", "expected"),
    [
        # library pin at (0, 3.81) — Device:R pin 1 — placed at (100, 100)
        (0, "", (100.0, 96.19)),
        (90, "", (96.19, 100.0)),
        (180, "", (100.0, 103.81)),
        (270, "", (103.81, 100.0)),
        (0, "x", (100.0, 103.81)),
        (90, "y", (103.81, 100.0)),  # rotate first, then mirror: measured on R3 (4.7k)
    ],
)
def test_the_pin_transform_is_rotate_then_mirror(rot, mirror, expected):
    assert _sheet_point((100.0, 100.0), rot, mirror, 0.0, 3.81) == expected


def test_the_schematic_model_follows_the_duplicate_designator_contract():
    model = read_kicad_schematic_model(SCH)
    assert sorted(model.components) == ["C1", "C2", "R1", "R3", "R4", "U1"], "no #PWR symbols"
    assert model.duplicate_designators == ["R3"]
    kept = model.components["R3"]
    assert kept.value == "4.7k", "the first placement in the file is the one kept"
    assert {p.number: p.net for p in kept.pins} == {"1": "+3V3", "2": "SENSE"}
    # The dropped 1k R3 touches GND and LED_A: those nets are short of a member.
    assert set(model.unproven_nets) == {"GND", "LED_A"}
    assert all(reason[0] == "truncated-by-duplicate-designator" for reason in model.unproven_reasons.values())
    assert model.nets["LED_A"].pins == [("R1", "2")]


def test_fields_pins_and_net_names_read_as_the_designer_wrote_them():
    model = read_kicad_schematic_model(SCH)
    u1 = model.components["U1"]
    assert (u1.value, u1.lcsc_part, u1.mpn, u1.manufacturer) == ("AMS1117-3.3", "C6186", "AMS1117-3.3", "AMS")
    assert u1.footprint == "SOT-223-3_TabPin2", "library nickname stripped"
    assert u1.props["Footprint"] == "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
    assert {p.number: (p.name, p.net) for p in u1.pins} == {"1": ("GND", "GND"), "2": ("VO", "+3V3"), "3": ("VI", "+5V")}
    assert model.raw["netNamedBy"] == {
        "+3V3": "power", "+5V": "power", "GND": "power", "LED_A": "local", "SENSE": "local", "VLOAD": "global",
    }
    assert "/LED_A" not in model.nets, "a root-sheet local label is the name typed, not its sheet path"


# ---------------------------------------------------------------------------
# synthetic sheets: T junctions, hierarchy, buses
# ---------------------------------------------------------------------------


def _lib_symbols_text() -> str:
    text = SCH.read_text(encoding="utf-8")
    start = text.index("\t(lib_symbols")
    depth, i = 0, start
    while True:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


def _sheet(tmp_path, body: str) -> Path:
    path = tmp_path / "t.kicad_sch"
    path.write_text(f'(kicad_sch (version 20260306) (generator "eeschema")\n{_lib_symbols_text()}\n{body}\n)', encoding="utf-8")
    return path


def _resistor(ref, x, y, rot=0):
    return (f'(symbol (lib_id "Device:R") (at {x} {y} {rot}) (unit 1) (uuid "{ref}-u")'
            f' (property "Reference" "{ref}" (at 0 0 0)) (property "Value" "1k" (at 0 0 0)))')


def _wire(a, b):
    return f"(wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]})))"


def test_a_tee_without_a_junction_is_not_joined_and_is_reported(tmp_path):
    # R1 pin 2 at (100, 103.81), R2 pin 1 at (120, 96.19). A horizontal wire
    # from R2's pin crosses x = 100 into the middle of a vertical wire hanging
    # from R1's pin — no junction there.
    body = "\n".join([
        _resistor("R1", 100, 100), _resistor("R2", 120, 100),
        _wire((100, 103.81), (100, 120)),
        _wire((120, 96.19), (110, 96.19)), _wire((110, 96.19), (110, 110)), _wire((110, 110), (100, 110)),
    ])
    solved = schematic_connectivity(_sheet(tmp_path, body))
    nets = {(solved.placed[i].ref, n): name for (i, n), name in solved.net_of.items()}
    assert ("R1", "2") not in nets and ("R2", "1") not in nets, "two unconnected pins, no net"
    assert solved.dangling_tees == [(100.0, 110.0)]
    with_junction = _sheet(tmp_path, body + "\n(junction (at 100 110))")
    solved = schematic_connectivity(with_junction)
    nets = {(solved.placed[i].ref, n): name for (i, n), name in solved.net_of.items()}
    assert nets[("R1", "2")] == nets[("R2", "1")] == "Net-(R1-Pad2)"
    assert solved.dangling_tees == []


@pytest.mark.parametrize("item", ['(sheet (at 0 0) (size 10 10) (uuid "s"))', "(bus (pts (xy 0 0) (xy 10 0)))"])
def test_a_hierarchical_sheet_or_a_bus_is_refused_by_name(tmp_path, item):
    with pytest.raises(KicadFormatError, match="refusing"):
        read_kicad_schematic_model(_sheet(tmp_path, item))


# ---------------------------------------------------------------------------
# the board, against pcbnew's own reading
# ---------------------------------------------------------------------------


def _pcbnew() -> dict:
    return json.loads((FIX / "kicad_min.pcbnew.json").read_text(encoding="utf-8"))


def _mil(point):
    return (point[0] * MM_TO_MIL, -point[1] * MM_TO_MIL)


def test_every_pad_lands_where_pcbnew_puts_it():
    board = read_kicad_board(PCB)
    oracle = _pcbnew()
    assert len(board.components) == len(oracle["footprints"]) == 7
    matched = 0
    for fo in oracle["footprints"]:
        x, y = _mil(fo["pos"])
        component = next(c for c in board.components if c.designator == fo["ref"] and abs(c.x - x) < 1e-6 and abs(c.y - y) < 1e-6)
        assert component.layer_id == (2 if fo["layer"] == "B.Cu" else 1)
        assert component.angle == fo["rot"]
        pads = [p for p in board.pads if p.component_id == component.id]
        for po in fo["pads"]:
            px, py = _mil(po["pos"])
            pad = next(p for p in pads if p.pin_number == po["number"] and math.hypot(p.x - px, p.y - py) < 1e-6)
            assert pad.net == (po["net"] or None)
            assert pad.angle % 360 == po["angle"] % 360
            assert (pad.width, pad.height) == pytest.approx((po["size"][0] * MM_TO_MIL, po["size"][1] * MM_TO_MIL))
            assert pad.effective_layer_ids == sorted({"F.Cu": 1, "B.Cu": 2}[name] for name in po["copper"])
            matched += 1
    assert matched == len(board.pads) == 16


def test_tracks_vias_zones_and_outline_match_pcbnew():
    board = read_kicad_board(PCB)
    oracle = _pcbnew()
    layer = {"F.Cu": 1, "B.Cu": 2}
    ours = sorted((round(t.start.x, 3), round(t.start.y, 3), round(t.end.x, 3), round(t.end.y, 3), round(t.width, 3), t.layer_id, t.net) for t in board.tracks)
    theirs = sorted(
        (round(_mil(t["start"])[0], 3), round(_mil(t["start"])[1], 3), round(_mil(t["end"])[0], 3), round(_mil(t["end"])[1], 3),
         round(t["width"] * MM_TO_MIL, 3), layer[t["layer"]], t["net"])
        for t in oracle["tracks"]
    )
    assert ours == theirs
    assert sorted((round(v.x, 3), round(v.y, 3), round(v.via_diameter, 3), round(v.hole_diameter, 3), v.net) for v in board.vias) == sorted(
        (round(_mil(v["pos"])[0], 3), round(_mil(v["pos"])[1], 3), round(v["width"] * MM_TO_MIL, 3), round(v["drill"] * MM_TO_MIL, 3), v["net"])
        for v in oracle["vias"]
    )
    poured = [p for p in board.pours if p.kind == "poured"]
    assert [(p.net, p.layer_id) for p in poured] == [(z["net"], layer[z["layer"]]) for z in oracle["zones"]]
    assert len(poured) == sum(z["filled_outlines"] for z in oracle["zones"])
    # The outline's centreline vs pcbnew's edge bbox (which includes the 0.1 mm line).
    (x0, y0), (x1, y1) = oracle["outline"]
    xs = [p.x for p in board.outline.points]
    ys = [p.y for p in board.outline.points]
    assert min(xs) == pytest.approx((x0 + 0.05) * MM_TO_MIL) and max(xs) == pytest.approx((x1 - 0.05) * MM_TO_MIL)
    assert max(ys) == pytest.approx(-(y0 + 0.05) * MM_TO_MIL) and min(ys) == pytest.approx(-(y1 - 0.05) * MM_TO_MIL)
    assert sorted(board.layers) == [1, 2]


def test_the_boards_netlist_is_the_schematics_netlist():
    sch = read_kicad_schematic_model(SCH)
    pcb = read_kicad_board_model(PCB)
    assert {n: sorted(v.pins) for n, v in pcb.nets.items()} == {n: sorted(v.pins) for n, v in sch.nets.items()}
    assert pcb.duplicate_designators == ["R3"]
    assert {p.number: p.name for p in pcb.components["U1"].pins} == {"1": "GND_1", "2": "VO_2", "3": "VI_3"}, "pad pinfunction, verbatim"


# ---------------------------------------------------------------------------
# the loop: the existing rules judge a KiCad project
# ---------------------------------------------------------------------------


def _by_rule(findings):
    out = {}
    for f in findings:
        out.setdefault(f.rule_id, []).append(f)
    return out


def test_the_l1_and_l2_rules_name_the_defects_drawn_into_the_schematic():
    findings = _by_rule(run_review(read_kicad_schematic_model(SCH)))
    (dup,) = findings["conn-duplicate-designators"]
    assert dup.severity == "ERROR" and "R3" in dup.message
    (decap,) = findings["decap-required-caps"]
    assert decap.severity == "WARN" and "U1 pin2" in decap.message and "22uF" in decap.message
    (shunt,) = findings["shunt-sense-link"]
    assert "R4" in shunt.message


def test_the_pcb_rules_measure_the_kicad_board():
    findings, section = run_pcb_review(PRO, model=read_kicad_schematic_model(SCH))
    assert section["rules_errored"] == []
    (board,) = section["boards"]
    assert (board["title"], board["components"], board["copperLayers"], board["boardUuid"]) == ("kicad_min", 7, 2, "")
    rows = _by_rule(findings)
    (spacing,) = rows["pcb-component-spacing"]
    assert spacing.severity == "WARN" and "C2 and R3 are 5.9 mil apart" in spacing.message
    assert any(f.severity == "WARN" and "C2" in f.message for f in rows["pcb-decap-distance"])
    assert not any(f.severity == "ERROR" for f in rows.get("pcb-footprint-consistency", [])), (
        "the KiCad library nickname no longer reads as a package family"
    )


def test_checkup_dispatches_a_kicad_project_end_to_end(tmp_path):
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "checkup", "--file", str(PRO), "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "BOARDWISE_NO_AUTO_DAEMON": "1"},
    )
    assert proc.returncode == 1, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    rules = {f["rule_id"] for f in report["findings"]}
    assert {"conn-duplicate-designators", "decap-required-caps", "pcb-component-spacing"} <= rules
    assert [b["title"] for b in report["pcb_review"]["boards"]] == ["kicad_min"]


def test_review_reads_both_views_and_refuses_what_it_cannot_read(tmp_path):
    for target, view in ((SCH, "schematic"), (PCB, "pcb")):
        proc = subprocess.run(
            [sys.executable, "-m", "boardwise.cli", "review", str(target), "--view", view],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert proc.returncode == 1, proc.stderr
        assert "conn-duplicate-designators" in proc.stdout
    sheet = _sheet(tmp_path, '(sheet (at 0 0) (size 10 10) (uuid "s"))')
    proc = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "review", str(sheet)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 2 and "refusing" in proc.stderr and "Traceback" not in proc.stderr
