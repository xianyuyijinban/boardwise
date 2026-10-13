"""R2-1: ``pcb-keepout-violation`` — the first reader of 162b's REGION keepouts.

What is pinned, and why each one:

1. **The vocabulary is the host's.** ``prohibitType`` words and numeric codes
   are read through the table lifted from 立创 EDA Pro 3.2.186's own code
   (``COPPER`` = code 7 = 禁止覆铜, ``1`` = TRACK+FILL, ``4`` = COPPER+PLANE …);
   a word outside it is never guessed at.
2. **Each word forbids one kind**, on the keepout's layer or everywhere when the
   keepout is on layer 12 — the host DRC's ``checkProhibitXXX``. A track inside a
   ``COPPER`` keepout is *not* a violation; a poured island is.
3. **Voids are read.** A poured island is its outline minus its voids
   (``PourShape.rings``). On 高速电机控制器 PCB2 the bottom PGND pour carries a
   void around each keepout, and the board is clean only because of them — the
   outline-only reading would report all five bottom keepouts.
4. **Every existing fixture stays at zero findings from this rule**, and an
   injected copy of the one board with keepouts is caught: a void deleted from
   the PGND pour (a keepout added after the pour and never re-poured) is one WARN
   for exactly that keepout, and a ``TRACK`` keepout drawn over a routed track is
   one WARN naming that track.
5. **The tolerance**: copper that only touches a keepout's edge does not count;
   copper 0.5 mil inside does.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    ProhibitRegion,
    TrackSegment,
    ViaGeometry,
)
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, _pcb_documents, run_pcb_review
from boardwise.parsers.epru import extract_board, load_epro2_source
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.keepout import (
    KEEPOUT_TOLERANCE_MIL,
    KeepoutViolation,
    _region_area,
    _rings_meet,
    prohibited_kinds,
)

FIXTURES = Path(__file__).parent / "fixtures"
MOTOR = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"
RULE = KeepoutViolation()


# ---------------------------------------------------------------------------
# 1. vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tokens", "words", "unknown"),
    [
        (["COPPER"], ["COPPER"], []),
        (["copper", "Track"], ["COPPER", "TRACK"], []),
        ([1], ["FILL", "TRACK"], []),
        (["4"], ["COPPER", "PLANE"], []),
        ([2, 3, 5, 6, 7, 8], ["COPPER", "FILL", "TRACK", "VIA", "COMPONENT", "PLANE"], []),
        (["WIRE", 9, "COPPER"], ["COPPER"], ["WIRE", "9"]),
        ([], [], []),
    ],
)
def test_prohibit_types_are_read_through_the_hosts_own_table(tokens, words, unknown):
    assert prohibited_kinds(tokens) == (words, unknown)


def test_the_rule_is_registered_last_and_says_where_its_reading_comes_from():
    assert BUILTIN_PCB_RULES[-1].id == "pcb-keepout-violation"
    assert isinstance(BUILTIN_PCB_RULES[-1], KeepoutViolation)
    assert RULE.level == "L1-pcb-geometry"
    assert "3.2.186" in RULE.source and "checkProhibitXXX" in RULE.source


# ---------------------------------------------------------------------------
# 2. synthetic boards: one kind per word, the layer rule, the tolerance
# ---------------------------------------------------------------------------


def _board(**elements) -> BoardGeometry:
    board = BoardGeometry(
        layers={1: LayerInfo(1, "Top Layer", "TOP"), 2: LayerInfo(2, "Bottom Layer", "BOTTOM")},
    )
    for key, value in elements.items():
        setattr(board, key, value)
    return board


def _circle(words, layer=1, centre=(0.0, 0.0), radius=50.0, region_type="PROHIBIT", rid="k1"):
    return ProhibitRegion(
        id=rid, name="PROHIBIT", layer_id=layer, region_type=region_type,
        prohibit_types=list(words), points=[Point(*centre)], radius=radius,
    )


def _square(x0, y0, x1, y1):
    return [Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)]


def _run(board):
    return RULE.check(PcbReviewContext(board=board, board_title="PCB1"))


def test_a_track_keepout_catches_a_track_on_its_layer_and_only_there():
    inside = TrackSegment(id="t-in", net="SIG", layer_id=1, start=Point(-100, 0), end=Point(100, 0), width=10)
    other_layer = TrackSegment(id="t-bot", net="SIG2", layer_id=2, start=Point(-100, 5), end=Point(100, 5), width=10)
    far = TrackSegment(id="t-far", net="SIG3", layer_id=1, start=Point(-100, 200), end=Point(100, 200), width=10)
    findings = _run(_board(tracks=[inside, other_layer, far], prohibit_regions=[_circle(["TRACK"])]))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN" and finding.rule_id == "pcb-keepout-violation"
    assert "t-in" in finding.message and "t-bot" not in finding.message and "t-far" not in finding.message
    assert finding.target.primitive_id == "k1" and finding.target.net_refs == ["SIG"]


def test_a_keepout_on_the_multi_layer_applies_to_every_layer():
    bottom = TrackSegment(id="t-bot", net="SIG2", layer_id=2, start=Point(-100, 5), end=Point(100, 5), width=10)
    findings = _run(_board(tracks=[bottom], prohibit_regions=[_circle(["TRACK"], layer=12)]))
    assert len(findings) == 1 and "t-bot" in findings[0].message


def test_a_copper_keepout_forbids_poured_copper_and_not_tracks():
    track = TrackSegment(id="t-in", net="SIG", layer_id=1, start=Point(-100, 0), end=Point(100, 0), width=10)
    poured = PourShape(id='["POURED","p1"]', net="GND", layer_id=1, kind="poured",
                       points=_square(-300, -300, 300, 300), rings=[_square(-300, -300, 300, 300)])
    clean = _run(_board(tracks=[track], prohibit_regions=[_circle(["COPPER"])]))
    assert clean == [], "a COPPER keepout is 禁止覆铜: tracks are another word's business"
    hit = _run(_board(tracks=[track], pours=[poured], prohibit_regions=[_circle(["COPPER"])]))
    assert len(hit) == 1 and "poured" in hit[0].message and "GND" in hit[0].message


def test_a_void_around_the_keepout_clears_the_pour_and_a_void_too_small_does_not():
    outline = _square(-300, -300, 300, 300)
    void = [Point(55 * c, 55 * s) for c, s in ((1, 0), (0.7071, 0.7071), (0, 1), (-0.7071, 0.7071),
                                                (-1, 0), (-0.7071, -0.7071), (0, -1), (0.7071, -0.7071))]
    # An octagon of circumradius 55 has inradius 55*cos(22.5°) = 50.8 > 50: clear.
    cleared = PourShape(id="p", net="GND", layer_id=1, kind="poured", points=outline, rings=[outline, void])
    assert _run(_board(pours=[cleared], prohibit_regions=[_circle(["COPPER"])])) == []
    small = [Point(p.x * 0.8, p.y * 0.8) for p in void]
    tight = PourShape(id="p", net="GND", layer_id=1, kind="poured", points=outline, rings=[outline, small])
    assert len(_run(_board(pours=[tight], prohibit_regions=[_circle(["COPPER"])]))) == 1
    # The outline-only view of the cleared pour is exactly the false positive
    # the voids exist to prevent.
    area = _region_area(_circle(["COPPER"]))
    assert _rings_meet([outline], area) and not _rings_meet([outline, void], area)


def test_a_fill_keepout_catches_a_fill_and_not_a_pour():
    square = _square(-20, -20, 20, 20)
    fill = PourShape(id="f1", net="VCC", layer_id=1, kind="fill", points=square, rings=[square])
    poured = PourShape(id="p1", net="GND", layer_id=1, kind="poured", points=square, rings=[square])
    findings = _run(_board(pours=[fill, poured], prohibit_regions=[_circle(["FILL"])]))
    assert len(findings) == 1 and "fill f1" in findings[0].message and "poured" not in findings[0].message


def test_a_via_keepout_catches_a_via_and_says_the_host_would_not():
    via = ViaGeometry(id="v1", net="GND", x=30, y=0, hole_diameter=12, via_diameter=24)
    far = ViaGeometry(id="v2", net="GND", x=200, y=0, hole_diameter=12, via_diameter=24)
    findings = _run(_board(vias=[via, far], prohibit_regions=[_circle(["VIA"], layer=2)]))
    assert len(findings) == 1 and "via v1" in findings[0].message and "v2" not in findings[0].message
    assert any("does not check VIA" in line for line in findings[0].evidence)


def test_a_component_keepout_judges_the_parts_pads_on_its_face():
    top = ComponentPlacement(id="c1", designator="U1", x=0, y=0, layer_id=1)
    bottom = ComponentPlacement(id="c2", designator="U2", x=0, y=0, layer_id=2)
    pads = [
        PadGeometry(id="e1", component="U1", component_id="c1", pin_number="1", net="N1",
                    layer_id=1, effective_layer_ids=[1], x=10, y=0, width=20, height=20, shape="RECT"),
        PadGeometry(id="e1", component="U2", component_id="c2", pin_number="1", net="N2",
                    layer_id=1, effective_layer_ids=[2], x=10, y=0, width=20, height=20, shape="RECT"),
    ]
    findings = _run(_board(components=[top, bottom], pads=pads, prohibit_regions=[_circle(["COMPONENT"])]))
    assert len(findings) == 1
    assert "component U1" in findings[0].message and "U2" not in findings[0].message
    assert findings[0].target.component_ref == "U1"


def test_touching_is_not_intruding_but_half_a_mil_in_is():
    # A 10-mil track whose copper edge ends exactly on the keepout circle.
    touching = TrackSegment(id="t", net="S", layer_id=1, start=Point(-100, 55), end=Point(100, 55), width=10)
    assert _run(_board(tracks=[touching], prohibit_regions=[_circle(["TRACK"])])) == []
    within_tolerance = TrackSegment(id="t", net="S", layer_id=1,
                                    start=Point(-100, 55 - KEEPOUT_TOLERANCE_MIL / 2), end=Point(100, 55 - KEEPOUT_TOLERANCE_MIL / 2), width=10)
    assert _run(_board(tracks=[within_tolerance], prohibit_regions=[_circle(["TRACK"])])) == []
    inside = TrackSegment(id="t", net="S", layer_id=1, start=Point(-100, 54.5), end=Point(100, 54.5), width=10)
    assert len(_run(_board(tracks=[inside], prohibit_regions=[_circle(["TRACK"])]))) == 1


def test_a_polygon_keepout_is_eroded_too():
    region = ProhibitRegion(id="k2", name="PROHIBIT", layer_id=1, region_type="PROHIBIT",
                            prohibit_types=["TRACK"], points=_square(0, 0, 100, -100))
    edge = TrackSegment(id="t-edge", net="S", layer_id=1, start=Point(-50, 5), end=Point(150, 5), width=10)
    assert _run(_board(tracks=[edge], prohibit_regions=[region])) == [], "copper edge on y=0: touching"
    crossing = TrackSegment(id="t-x", net="S", layer_id=1, start=Point(50, 50), end=Point(50, -150), width=10)
    assert len(_run(_board(tracks=[crossing], prohibit_regions=[region]))) == 1


def test_a_constraint_area_is_not_a_keepout_and_plane_is_said_to_be_unjudged():
    track = TrackSegment(id="t", net="S", layer_id=1, start=Point(-100, 0), end=Point(100, 0), width=10)
    assert _run(_board(tracks=[track], prohibit_regions=[_circle(["TRACK"], region_type="CONSTRAINT")])) == []
    findings = _run(_board(tracks=[track], prohibit_regions=[_circle(["TRACK", "PLANE"])]))
    assert any("PLANE" in line and "not judged" in line for line in findings[0].evidence)


def test_an_unknown_word_is_named_and_not_judged():
    track = TrackSegment(id="t", net="S", layer_id=1, start=Point(-100, 0), end=Point(100, 0), width=10)
    findings = _run(_board(tracks=[track], prohibit_regions=[_circle(["WIRE"])]))
    assert len(findings) == 1 and findings[0].severity == "INFO"
    assert "WIRE" in findings[0].message and "不确定" in findings[0].message and "不判" in findings[0].message
    assert _run(_board(prohibit_regions=[_circle(["WIRE"])])) == [], "nothing inside, nothing to say"


# ---------------------------------------------------------------------------
# 3. the fixture board with keepouts, as it is and injected
# ---------------------------------------------------------------------------


def _motor_findings(path: Path):
    model = cli._load_model(path, view="schematic")[0]
    findings, section = run_pcb_review(path, model=model, rules=[RULE])
    assert section is not None and section["rules_errored"] == []
    return findings


def _rewrite(source: Path, out: Path, transform) -> Path:
    with zipfile.ZipFile(source) as archive:
        members = [(info, archive.read(info.filename)) for info in archive.infolist()]
    index = next(i for i, (info, _) in enumerate(members) if info.filename.endswith(".epru"))
    lines = members[index][1].decode("utf-8").split("\n")
    lines = transform(lines)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, (info, data) in enumerate(members):
            archive.writestr(info, "\n".join(lines).encode("utf-8") if i == index else data)
    return out


def test_the_motor_board_is_clean_because_its_pour_has_voids():
    assert _motor_findings(MOTOR) == []
    source = load_epro2_source(MOTOR)
    boards = {title: extract_board(doc, source.footprints(), source.stats, source.footprint_artwork())
              for title, _u, doc in _pcb_documents(source)}
    board = boards["PCB2"]
    assert len(board.prohibit_regions) == 6
    bottom_pours = [p for p in board.pours if p.kind == "poured" and p.layer_id == 2]
    main = [p for p in bottom_pours if p.poured_from == "174fb55f65247b4a"]
    assert len(main) == 1 and main[0].net == "PGND" and len(main[0].rings) == 7
    bottom = [r for r in board.prohibit_regions if r.layer_id == 2]
    assert len(bottom) == 5
    for region in bottom:
        area = _region_area(region)
        assert not any(_rings_meet(p.rings, area) for p in bottom_pours), region.id
        assert _rings_meet(main[0].rings[:1], area), f"{region.id}: the outline alone would have been a finding"


def test_a_void_deleted_from_the_pour_is_one_warn_for_exactly_that_keepout(tmp_path):
    def drop_void(lines):
        hits = [i for i, line in enumerate(lines) if line.startswith('{"type":"POURED"') and "174fb55f65247b4a" in line]
        assert len(hits) == 1
        envelope, body = lines[hits[0]].split("||", 1)
        data = json.loads(body.rstrip("|"))
        removed = 0
        for entry in data["pourFill"]:
            if entry.get("fill") is not True:
                continue
            keep = []
            for ring in entry["path"]:
                is_target = (
                    abs(ring[0] * 10 - 1670.484) < 1e-3 and abs(ring[1] * 10 + 370.0) < 1e-3 and "ARC" in ring
                )
                removed += is_target
                if not is_target:
                    keep.append(ring)
            entry["path"] = keep
        assert removed == 1, "exactly the void around keepout 6335e88d3ac44536"
        lines[hits[0]] = envelope + "||" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "|"
        return lines

    findings = _motor_findings(_rewrite(MOTOR, tmp_path / "stale_pour.epro2", drop_void))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN" and finding.board == "PCB2"
    assert finding.target.primitive_id == "6335e88d3ac44536"
    assert finding.target.net_refs == ["PGND"]
    assert "[COPPER] poured" in finding.message


def test_a_track_keepout_drawn_over_a_routed_track_names_it(tmp_path):
    source = load_epro2_source(MOTOR)
    board = next(extract_board(doc, source.footprints(), source.stats, source.footprint_artwork())
                 for title, _u, doc in _pcb_documents(source) if title == "PCB2")
    track = next(t for t in board.tracks if t.layer_id == 1 and t.width > 0 and t.net)
    mid = ((track.start.x + track.end.x) / 2, (track.start.y + track.end.y) / 2)
    region = {
        "partitionId": "", "groupId": 0, "layerId": 1, "width": 0.2, "prohibitType": ["TRACK"],
        "path": [["CIRCLE", mid[0], mid[1], 5]], "locked": False, "name": "R2-1 injected", "regionType": "PROHIBIT",
    }

    def add_region(lines):
        anchor = [i for i, line in enumerate(lines) if line.startswith('{"type":"REGION"') and "528d5108078ee52a" in line]
        assert len(anchor) == 1
        envelope = json.dumps({"type": "REGION", "ticket": 1, "id": "r2injectedtrack"}, separators=(",", ":"))
        lines.insert(anchor[0] + 1, envelope + "||" + json.dumps(region, separators=(",", ":")) + "|")
        return lines

    findings = _motor_findings(_rewrite(MOTOR, tmp_path / "track_keepout.epro2", add_region))
    assert len(findings) == 1
    assert findings[0].target.primitive_id == "r2injectedtrack"
    assert f"track {track.id}" in findings[0].message and track.net in findings[0].target.net_refs


def test_no_fixture_gains_a_finding_from_this_rule():
    for path in sorted(FIXTURES.glob("*.epro2")):
        try:
            model = cli._load_model(path, view="schematic")[0]
        except Exception:  # a fixture with no schematic view still has boards
            model = None
        findings, section = run_pcb_review(path, model=model, rules=[RULE])
        assert findings == [], path.name
        if section is not None:
            assert section["rules_errored"] == [], path.name


def test_arcs_turn_the_way_the_editor_turns_them():
    """``["ARC", sweep, x, y]`` per 3.2.186's ``build5``: counter-clockwise for a
    positive sweep, the centre on the chord's rotated left normal. The fixture's
    deciding voids are 180° pairs (direction-blind), so the direction is pinned
    here directly — a flipped sweep bulges every rounded corner the wrong way."""
    import math

    from boardwise.parsers.epru import _arc_points

    ccw = _arc_points(Point(0, 0), Point(2, 0), 180)
    assert all(abs(math.hypot(p.x - 1, p.y) - 1) < 1e-9 for p in ccw)
    assert min(p.y for p in ccw) < -0.99, "180° → 270° → 360°: below the chord"
    cw = _arc_points(Point(0, 0), Point(2, 0), -180)
    assert max(p.y for p in cw) > 0.99
    quarter = _arc_points(Point(0, 0), Point(1, 1), 90)
    assert all(abs(math.hypot(p.x, p.y - 1) - 1) < 1e-9 for p in quarter), "centre (0, 1)"
    assert quarter[-1] == Point(1, 1)
    back = _arc_points(Point(0, 0), Point(1, 1), -90)
    assert all(abs(math.hypot(p.x - 1, p.y) - 1) < 1e-9 for p in back), "centre (1, 0)"
    assert len(quarter) == 30, "3° per chord"


def test_the_pgnd_void_around_a_keepout_is_the_circle_the_file_draws():
    import math

    source = load_epro2_source(MOTOR)
    board = next(extract_board(doc, source.footprints(), source.stats, source.footprint_artwork())
                 for title, _u, doc in _pcb_documents(source) if title == "PCB2")
    main = next(p for p in board.pours if p.poured_from == "174fb55f65247b4a")
    centre = Point(1768.425, -370.0)
    voids = [ring for ring in main.rings[1:] if all(abs(math.hypot(p.x - centre.x, p.y - centre.y) - 97.9415) < 1e-3 for p in ring)]
    assert len(voids) == 1 and len(voids[0]) == 120
