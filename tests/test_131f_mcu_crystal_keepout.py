"""Task 131f: ``POUR`` records, the ``region_copper`` primitive, and ``pcb-mcu-crystal-keepout``.

The MCU package's sixth rule, and the first **data-model** change the package
has made: ``POUR`` records used to be counted in ``stats.unconsumed_types`` and
dropped, so a board's *plane* copper was invisible to every reader that works
from geometry. Four groups, plus the structure gate:

* **一、the parser** — a ``POUR`` record's path **is** in board coordinates
  (unlike ``POURED``, which is parent-relative and 1:10-scaled — 125b), in two
  shapes: ``["R", x, y, w, h, ..]`` rectangles and ``[x0, y0, "L", x1, y1,
  ..]`` polylines. Both are consumed, ``kind`` is the new ``"pour"``, and
  ``POUR`` disappears from ``stats.unconsumed_types`` on every fixture that
  carries it (27 on 毕设FOC 1.0.0, 3 on ROBOT, 4 on 药箱).
* **二、the consumption decision, and the numbers it moved** — ``kind="pour"``
  is a **real copper polygon** in board coordinates with its own net and layer,
  so ``_net_shape_records`` accepts it and 125b's island count, the clearance
  engine and the new primitive all read it. Every island-count change is
  pinned here with the reason it is a correction rather than a regression
  (毕设FOC 1.0.0's ``AGND`` went 67 → 1, ROBOT's ``GND`` 194 → 1, 药箱's ``GND``
  225 → 1, and **llc's ``DC-`` is unchanged to six decimals** because that
  fixture has no ``POUR`` record at all).
* **三、the primitive** — ``region_copper`` answers 「what copper is in this
  rectangle」, per layer, and **not** 「how far is it from that pad」. The two
  are not interchangeable and the file proves it: a pad sitting inside a pour's
  outline has a capsule distance of ``math.inf`` (125b's documented blind spot),
  so a region query built on distance semantics would report the exact copper it
  exists to find as unmeasurable.
* **四、the rule and the acceptance anchors** — 1.0.0's ``X1`` has an ``AGND``
  pour region **on both copper faces** (top and bottom), ROBOT's ``X2`` has a
  ``GND`` one on both, and 药箱's ``X1`` has a ``GND`` one on both. All four are
  measured, not quoted from the task book. ``llc`` is silent: it places no
  ``ic.mcu`` and therefore no crystal.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from boardwise.core.geometry import (
    BBox,
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    TrackSegment,
    ViaGeometry,
)
from boardwise.core.measure import (
    clearances_vs,
    pad_corners,
    pour_connectivity,
    read_stackup,
    region_copper,
)
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES
from boardwise.parsers.epru import _path_points, load_epro2_source, parse_epro2
from boardwise.rules.pcb.crystalkeepout import (
    CRYSTAL_REGION_MARGIN_MIL,
    McuCrystalKeepout,
    crystal_designators,
    crystal_region,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

RULE_ID = "pcb-mcu-crystal-keepout"


def _findings(path: Path, rule_id: str = RULE_ID) -> list:
    from boardwise.engines.pcbreview import run_pcb_review

    findings, _section = run_pcb_review(path)
    return [f for f in findings if f.rule_id == rule_id]


def _layer_row(rows, layer_name: str):
    """The one row that is 「about」 ``layer_name``."""
    matches = [row for row in rows if f"on {layer_name}" in row.message]
    assert len(matches) == 1, [row.message for row in rows]
    return matches[0]


def _evidence_blob(row) -> str:
    return "\n".join(row.evidence)


def _pad(
    id: str,
    *,
    component: str | None = None,
    pin: str | None = None,
    net: str | None = None,
    layer_id: int | None = 1,
    x: float = 0.0,
    y: float = 0.0,
    width: float = 0.0,
    height: float = 0.0,
    hole: float | None = None,
) -> PadGeometry:
    return PadGeometry(
        id=id,
        component=component,
        pin_number=pin,
        net=net,
        layer_id=layer_id,
        x=x,
        y=y,
        width=width,
        height=height,
        shape="RECT",
        hole_diameter=hole,
    )


def _two_layer_stack() -> tuple[dict[int, LayerInfo], list[StackupEntry]]:
    return (
        {
            1: LayerInfo(1, "Top Layer", "TOP"),
            2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        },
        [
            StackupEntry(1, 1000, "外层铜厚", 1.378),
            StackupEntry(2, 9000, "外层铜厚", 1.378),
        ],
    )


# ---------------------------------------------------------------------------
# 一、the parser: POUR is consumed
# ---------------------------------------------------------------------------


def test_pour_disappears_from_unconsumed_types_on_every_fixture_that_carries_it():
    """27 / 3 / 4 — the counts the task book states, and they are gone.

    ``stats.unconsumed_types`` is the board view's own account of what the
    format still carries that nothing reads. ``POUR`` used to sit in it on
    exactly the three acceptance boards; after 131f it does not, because the
    record is now parsed. The **count** is pinned as well as the absence: a
    parser that dropped the records instead of reading them would also make
    ``POUR`` disappear, and would leave ``unconsumed_types`` empty by accident.
    """
    expected = {FOC_100: 27, ROBOT: 3, PILLBOX: 4}
    for path, count in expected.items():
        source = load_epro2_source(path)
        source.pcb_context()  # the walk is what fills unconsumed_types
        assert source.stats.unconsumed_types.get("POUR", 0) == 0, (
            f"{path.name}: POUR is still unread"
        )
        assert sum(1 for p in source.pcb_context().pours if p.kind == "pour") == count
    # llc carries no POUR record at all, so nothing changed there — pinned so a
    # later batch that starts *writing* POUR on llc notices it moved.
    llc_source = load_epro2_source(LLC)
    llc_source.pcb_context()
    assert llc_source.stats.unconsumed_types.get("POUR", 0) == 0
    assert not [p for p in llc_source.pcb_context().pours if p.kind == "pour"]


def test_pour_records_parse_into_board_coordinates_as_kind_pour():
    """Both path shapes land in the same frame as pads and tracks.

    ``POURED`` is the trap 125b documented — its path is parent-relative and
    1:10-scaled, so feeding it to a bbox corrupts every geometry query.
    ``POUR`` is **not** that record: it is the pour region the editor holds, and
    its coordinates are board coordinates. The rectangle read here
    (``["R", 6695.10, -1625.24, 144.90, 149.76, 0, 0]``) expands to a box whose
    size is the two trailing dimensions the record states, which is the check a
    scaled record could not pass.
    """
    board = parse_epro2(FOC_100)
    pours = [p for p in board.pours if p.kind == "pour"]
    rectangles = [
        p
        for p in pours
        if p.points and p.bbox is not None
        and math.isclose(p.bbox.width, 144.8998, rel_tol=1e-4)
    ]
    assert rectangles, "the IA+ rectangle POUR is on this board"
    box = rectangles[0].bbox
    assert math.isclose(box.width, 144.8998, rel_tol=1e-4)
    assert math.isclose(box.height, 149.7638, rel_tol=1e-4)
    assert rectangles[0].net == "IA+" and rectangles[0].layer_id == 1
    # and the board-coordinate claim itself: the AGND pour under X1 sits in the
    # same x range as X1's own pads, which is only true in one frame.
    agnd = [
        p
        for p in pours
        if p.net == "AGND" and p.layer_id == 2
    ]
    assert agnd and agnd[0].bbox is not None
    assert 4000 < agnd[0].bbox.min_x < 6000, (
        "board coordinates, not a local or scaled frame"
    )


def test_poured_is_now_parsed_and_reads_as_board_coordinates():
    """**135 reversed 125b's decision here, on evidence.**

    131f pinned it as: 「every ``POURED`` on the fixtures has an empty point
    list, so no consumer can accidentally feed the scaled parent-relative frame
    to a bbox」. The premise was wrong — the frame is not parent-relative, it is
    a plain uniform ``board = 10 × local`` with no offset and no flip — so 135
    parses it, and the safety property is now carried by the *transform* instead
    of by an empty list.

    What still holds, and is what this pin now checks: every poured polygon is
    in **board** coordinates, so it sits on the same board as the tracks and
    pours around it, and a ``POURED`` whose parent is gone from the file says so
    on the record (``poured_from`` set, ``net`` ``None``).
    """
    for path in (FOC_100, ROBOT, PILLBOX, LLC):
        board = parse_epro2(path)
        poured = [p for p in board.pours if p.kind == "poured"]
        assert poured, f"{path.name} carries POURED records"
        assert all(len(p.points) >= 3 for p in poured)
        assert all(p.poured_from for p in poured)
        # Board coordinates, not local: the transform is x10, so re-deriving a
        # poured point from the raw record must reproduce the parsed one
        # exactly. ROBOT's board really is small (a few hundred mil across), so
        # this is checked as a ratio and not as an absolute size.
        raw_by_id = {}
        for record in load_epro2_source(path).first_document("PCB").records:
            if record.type == "POURED" and record.body:
                raw_by_id[record.id] = record.body
        checked = 0
        for shape in poured:
            body = raw_by_id[shape.id]
            wanted = [(q.x, q.y) for q in shape.points]
            matched = False
            for entry in body["pourFill"]:
                if not entry.get("fill"):
                    continue
                raw_points = [(q.x * 10.0, q.y * 10.0)
                              for q in _path_points(entry.get("path"))]
                if raw_points != wanted:
                    continue
                matched = True
                break
            assert matched, f"{path.name}: {shape.id} is not any entry x10"
            checked += 1
        assert checked == len(poured), f"{path.name}: {checked} of {len(poured)} re-derived"
        # An orphan is honest about being one.
        for shape in poured:
            if shape.net is None:
                assert shape.layer_id is None


# ---------------------------------------------------------------------------
# 二、the consumption decision, and the numbers it moved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, net, before, after",
    [
        # Before 131f a net's copper was read from tracks, vias, pads and
        # FILL/POLY polygons only, so every pour *region* on these boards was
        # missing from the union-find and each isolated pad or stub looked like
        # its own island. After 131f the region is in the union and the board
        # reads as the single piece of copper it is.
        #
        # AGND 67 -> 1: 毕设FOC 1.0.0's analog-ground plane is one POUR region
        #   per face, and the two layers are bridged by the vias that were
        #   already in the graph; 67 fragments became one plane.
        # GND 194 -> 1: ROBOT's ground is two almost-full-board rectangles.
        # GND 225 -> 1: 药箱's is the same shape.
        # +24V 36 -> 3, PGND 81 -> 33, MOTA/MOTB/MOTC 5 -> 1, +5V 3 -> 1,
        #   IA+/IB+/IC+ 4 -> 1: the same correction, smaller nets.
        # GND 45 -> 46 (毕设FOC): the one count that **grew**. That is not a
        #   regression -- a region now sits between two pads that used to be
        #   reported as touching copper through the empty space where the pour
        #   outline should have been, and the union-find correctly finds them
        #   separate. The number is pinned so a reader can see it rather than
        #   discover it later.
        #
        # --- 135 moved three of these again, and the *after* column below is
        # the 135 number. The direction is the same rule both times (read more
        # of the real copper), but 135 swaps each poured region for its POURED
        # *result* rather than adding to it -- see
        # `boardwise.core.measure._poured_supersedes`. The three that moved:
        #
        #   PGND 33 -> 31: the result polygons are smaller than the regions
        #     (the pour engine cut clearance voids out of them), so two pairs of
        #     fragments that touched through a region's full extent no longer
        #     touch. Pour area 224 746.8 -> 205 038.9 sq mil.
        #   GND 46 -> 39: the same effect on 毕设FOC's ground, 12 350.0 ->
        #     10 614.0 sq mil.
        #   ROBOT GND 1 -> 15: the opposite effect, and the most consequential
        #     number in this task. ROBOT's GND *region* is one near-full-board
        #     plane; its poured *result* is **fifteen** pieces. The region was
        #     the designer's intent, the result is what the pour engine left,
        #     and 131f's "one island" was reading the intent. 133d's R31/33c
        #     text that calls ROBOT's ground a single 7 494 300 sq mil island
        #     is superseded by this number.
        #
        # AGND and 药箱 GND stay at 1: their results are still one piece each,
        #     just less copper (AGND 2 059 037.0 -> 1 433 311.2 sq mil).
        (FOC_100, "AGND", 67, 1),
        (FOC_100, "+24V", 36, 3),
        (FOC_100, "PGND", 81, 31),
        (FOC_100, "MOTA", 5, 1),
        (FOC_100, "IA+", 4, 1),
        (FOC_100, "GND", 45, 39),
        (ROBOT, "GND", 194, 15),
        (ROBOT, "VCC", 3, 2),
        (PILLBOX, "GND", 225, 1),
    ],
)
def test_island_counts_moved_because_pour_regions_are_copper(path, net, before, after):
    """The before-number is the task's, the after-number is measured here.

    The point of pinning both ends is that a reviewer can tell a correction from
    a regression: a net whose copper is one plane should read as one island, and
    a net that genuinely has several disconnected pieces should keep reading as
    several. ``llc`` carries no POUR record, so its counts are the control and
    are pinned separately below.
    """
    board = parse_epro2(path)
    assert pour_connectivity(board, net).island_count == after


def test_llc_is_the_control_and_its_numbers_did_not_move():
    """llc has no POUR record, so 125b's published figures stand verbatim.

    ``clearances_vs(llc, "DC-")`` is the number 125b pinned (the largest net,
    204 elements, ≥ 20 neighbours) and it is unchanged to six decimals. That is
    the evidence that 131f changed what it meant to change and nothing else: a
    board whose format carries no POUR cannot have been touched by a decision
    about POUR.
    """
    board = parse_epro2(LLC)
    assert not [p for p in board.pours if p.kind == "pour"], (
        "if this ever becomes non-empty the control is void — re-measure"
    )
    assert pour_connectivity(board, "DC-").island_count > 0
    table = clearances_vs(board, "DC-")
    assert len(table) >= 20
    assert table["DHS"] == pytest.approx(101.932690, abs=1e-5)
    assert table["DLG"] == pytest.approx(40.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 三、the primitive: region_copper
# ---------------------------------------------------------------------------


def test_region_copper_files_copper_under_the_requested_layer_only():
    """A restriction, never an expansion, and an empty layer is still present.

    The layers the caller did not ask about are not reported under any other
    layer, and a requested layer with nothing in it keeps an **empty list** — an
    absent key would be indistinguishable from a layer never asked, which is
    exactly the wrong silence for a keepout question.
    """
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        source="synthetic",
        layers=layers,
        stackup=stackup,
        tracks=[
            TrackSegment("t1", net="SIG", layer_id=1, start=Point(0, 0), end=Point(10, 0), width=10),
            TrackSegment("t2", net="SIG", layer_id=2, start=Point(0, 0), end=Point(10, 0), width=10),
        ],
    )
    report = region_copper(board, BBox(-5, -5, 5, 5), [1])
    assert list(report.layers_by_id) == [1]
    assert [item.element_id for item in report.layers_by_id[1]] == ["t1"]
    empty = region_copper(board, BBox(900, 900, 950, 950))
    assert set(empty.layers_by_id) == {1, 2}
    assert empty.layers_by_id[1] == [] and empty.layers_by_id[2] == []
    assert empty.is_empty()


def test_region_copper_uses_containment_not_distance_semantics():
    """The 125b blind spot, stated as the reason this primitive exists.

    A foreign pad sitting **inside** a pour's outline has a capsule distance of
    ``math.inf`` from it — 125b's deliberate choice, so a pour's clearance voids
    around a foreign pad cannot be reported as a 0-mil short. For an **inventory**
    that same pad is precisely the answer, so the test here is geometric
    (point-in-box / polygon overlap) and the pad is found.

    The negative half matters as much: a pad nowhere near the pour must not be
    reported, or the primitive would be answering a different question.
    """
    layers, stackup = _two_layer_stack()
    big = PourShape(
        id="plane",
        net="GND",
        layer_id=2,
        kind="pour",
        points=[Point(0, 0), Point(1000, 0), Point(1000, 1000), Point(0, 1000)],
    )
    board = BoardGeometry(
        source="synthetic",
        layers=layers,
        stackup=stackup,
        pads=[
            _pad("inside", component="U1", pin="1", net="SIG", layer_id=1, x=500, y=500, width=40, height=40),
            _pad("outside", component="U2", pin="1", net="SIG", layer_id=1, x=2000, y=2000, width=40, height=40),
        ],
        pours=[big],
    )
    report = region_copper(board, BBox(480, 480, 520, 520), [1])
    ids = [item.element_id for item in report.layers_by_id[1]]
    assert ids == ["U1.1"], ids
    # The clearance engine's own answer on the same pair is unmeasurable, and
    # that is why the two cannot be one function.
    from boardwise.core.measure import _Shape, _capsule_distance

    pad_shape = _Shape(pad_corners(board.pads[0]), 0.0, {1}, "pad")
    pour_shape = _Shape(big.points, 0.0, {2}, "pour", is_pour=True)
    assert math.isinf(_capsule_distance(pad_shape, pour_shape, connectivity=False))
    assert _capsule_distance(pad_shape, pour_shape, connectivity=True) == 0.0


def test_region_copper_includes_pour_regions_and_excludes_poured():
    """``kind="pour"`` is inventoried; ``kind="poured"`` is not.

    The synthetic board carries one of each on the same layer and the same
    geometry, so the only thing separating them is the ``kind`` the parser
    assigned. That is the whole of 131f's parser change seen from the consumer
    side: the region is copper, the poured result is a second copy of it.
    """
    layers, stackup = _two_layer_stack()
    points = [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)]
    board = BoardGeometry(
        source="synthetic",
        layers=layers,
        stackup=stackup,
        pours=[
            PourShape(id="region", net="GND", layer_id=1, kind="pour", points=points),
            PourShape(id="result", net="GND", layer_id=1, kind="poured", points=[]),
        ],
    )
    report = region_copper(board, BBox(10, 10, 90, 90), [1])
    assert [item.element_id for item in report.layers_by_id[1]] == ["region"]
    assert report.layers_by_id[1][0].pour_kind == "pour"


def test_region_copper_reports_a_via_on_every_copper_layer_it_spans():
    """A via has no single layer, so it is filed under each one it occupies.

    Asking layer by layer is the contract the rule relies on, and a via is the
    element that makes it non-trivial: the same via answers 「yes, there is
    copper here」 on all four of 毕设FOC 1.0.0's copper layers, which is a true
    reading (its barrel is continuous) rather than a spread of one answer.
    """
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        source="synthetic",
        layers=layers,
        stackup=stackup,
        vias=[ViaGeometry("v", net="GND", x=0, y=0, hole_diameter=20, via_diameter=50)],
    )
    report = region_copper(board, BBox(-10, -10, 10, 10))
    assert {item.element_id for item in report.layers_by_id[1]} == {"v"}
    assert {item.element_id for item in report.layers_by_id[2]} == {"v"}
    assert report.layers_by_id[1][0].layer_ids == [1, 2]


# ---------------------------------------------------------------------------
# 四、the rule
# ---------------------------------------------------------------------------


def test_rule_is_declared_house_rule_with_no_threshold_and_is_in_the_list():
    """Structure gate: the id, its place in the list, and its source string.

    ``source`` is not decoration (钉 7) and this one says 待裁 because there is no
    ruled keepout radius. There is no distance constant in the module either —
    the only number it owns is :data:`CRYSTAL_REGION_MARGIN_MIL`, which is a
    region margin and is documented as a default rather than a measurement, and
    it is **not** used to grade a row.
    """
    assert [rule.id for rule in BUILTIN_PCB_RULES] == [
        "pcb-decap-distance",
        "pcb-regulator-cap-distance",
        "pcb-regulator-fb-placement",
        "pcb-mcu-crystal-placement",
        "pcb-mcu-crystal-keepout",
        "pcb-mcu-supply-groups",
        "pcb-mcu-reset-boot",
        "pcb-foc-decap-proximity",
        "pcb-foc-ground-plane",
        "pcb-foc-gate-trace-width",
        "pcb-foc-track-corners",
        "pcb-foc-power-loop-area",
        "pcb-foc-ground-domains",
        "pcb-foc-ground-tie",
        "pcb-foc-return-path",
        "pcb-foc-thermal-via-style",
        "pcb-foc-thermal-via-array",
        "pcb-foc-thermal-exit-path",
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
    ]
    rule = McuCrystalKeepout()
    assert rule.id == RULE_ID
    assert "待裁" in rule.source
    assert CRYSTAL_REGION_MARGIN_MIL > 0


def test_crystal_region_is_the_pad_bbox_plus_the_named_margin():
    """The region is built from every pad corner, grown by the margin.

    Built from ``pad_corners`` rather than the placement point so a rotated
    crystal reports its real footprint box, and grown by an **exported, named**
    constant rather than a literal — it is the module's one chosen number and it
    is 待裁, so a reader has to be able to see it and change it in one place.
    """
    board = parse_epro2(FOC_100)
    region = crystal_region(board, "X1")
    assert region is not None
    corners = [
        corner
        for pad in board.pads_for_component("X1")
        for corner in pad_corners(pad)
    ]
    raw = BBox.from_points(corners)
    assert math.isclose(
        region.min_x, raw.min_x - CRYSTAL_REGION_MARGIN_MIL, abs_tol=1e-6
    )
    assert math.isclose(
        region.max_y, raw.max_y + CRYSTAL_REGION_MARGIN_MIL, abs_tol=1e-6
    )
    assert crystal_region(board, "NOPE") is None


def test_crystal_designators_agree_with_131d_on_all_three_boards():
    """One crystal per board, found through 131d's own sieve.

    The rule must not carry a second, subtly different way of recognising a
    crystal: it imports 131d's ``_mcu_oscillators`` and
    ``is_crystal_member`` rather than re-deriving either, so the two rules
    cannot disagree about which part is the crystal.
    """
    from boardwise.rules.pcb.crystal import _mcu_oscillators
    from boardwise.core.parts import load_parts
    from boardwise.rules.facts import default_library_path

    library = load_parts(default_library_path())
    for path, expected in ((FOC_100, ["X1"]), (ROBOT, ["X2"]), (PILLBOX, ["X1"])):
        board = parse_epro2(path)
        model = _model_of(path)
        assert crystal_designators(model, board, library) == expected
        assert _mcu_oscillators(model, library), "the sieve found MCUs at all"


def _model_of(path: Path):
    """The PCB-document netlist view of one fixture.

    ``build_design_model`` reads the backup's first PCB document by default,
    which for all three acceptance fixtures is already the document the MCU and
    its crystal sit on (``PCB1``), so the historic default is what the runner
    reads too. Spelling it as the default rather than passing a document keeps
    this helper the same shape as 131e's.
    """
    from boardwise.parsers.epro2_model import build_design_model

    return build_design_model(load_epro2_source(path))


def test_foc100_crystal_has_an_agnd_pour_result_on_the_bottom_copper_face():
    """Acceptance anchor 1, **restated by 135**: 毕设FOC 1.0.0's ``X1``.

    131f pinned this as 「``AGND`` on top **and** bottom」, reading the pour
    **regions**. 135 reads each region *and* its ``POURED`` result, preferring
    the result where both exist (``measure._poured_supersedes``), and the two
    outer faces now answer differently:

    * **Bottom Layer** — the ``AGND`` region is still there and its result
      (``["POURED","e3b26ff04e3d6300"]``) still reaches the crystal footprint,
      so the row names it. Unchanged, apart from the label.
    * **Top Layer** — the region reaches the footprint but its **result does
      not**: the pour engine cleared a void around something on the top face,
      and the result polygon's edge falls outside the footprint rectangle. So
      the top row now says 「no pour region on this layer inside the region」.

    That is the point of the whole task in one line: the region is what the
    designer drew, the result is what copper there is, and the two disagree
    exactly where the design is wrong. The inner layers are unaffected (the
    inner planes are ``LAYER_FILL`` records, which this model does not read).
    """
    rows = _findings(FOC_100)
    assert len(rows) == 4, [row.message for row in rows]
    layer_names = ["Top Layer", "Bottom Layer", "Inner1", "Inner2"]
    for name in layer_names:
        row = _layer_row(rows, name)
        assert row.severity == "INFO"
        assert "no keepout threshold is in force" in row.message

    bottom = _layer_row(rows, "Bottom Layer")
    assert 'pour ["POURED","e3b26ff04e3d6300"] (kind=poured) @ AGND' in bottom.message
    assert "including 1 pour region(s) (AGND)" in bottom.message

    top = _layer_row(rows, "Top Layer")
    assert "no pour region on this layer inside the region" in top.message
    assert "AGND" not in top.message


def test_robot_crystal_has_a_gnd_pour_result_on_the_top_face_only():
    """Acceptance anchor 2, **restated by 135**: ROBOT's ``X2``.

    131f pinned 「``GND`` on top **and** bottom」 from the pour **regions**.
    135 reads the results instead, and the bottom face's ``GND`` result does not
    reach the crystal footprint — the same void story as 毕设FOC's top face. The
    top face's result (``["POURED","0a00b1e1974c2817"]``) does, so it is still
    named, and the count of pour regions reported under the footprint is still 1.

    ROBOT's ground is also the board whose ``GND`` island count moved most
    (1 -> 15); see the island-count pin above.
    """
    rows = _findings(ROBOT)
    assert len(rows) == 4, [row.message for row in rows]
    top = _layer_row(rows, "Top Layer")
    assert 'pour ["POURED","0a00b1e1974c2817"] (kind=poured) @ GND' in top.message
    assert "including 1 pour region(s) (GND)" in top.message
    for name in ("Bottom Layer", "Inner1", "Inner2"):
        row = _layer_row(rows, name)
        assert "no pour region on this layer inside the region" in row.message
    # The pour is almost the whole board, so the overlap bbox of the region with
    # it is the region itself: the whole pad box is inside the plane, with no
    # clearance modelled at all. 131f asserted this on the *Bottom Layer* row,
    # back when the bottom face still reported a region; with 135 the bottom
    # face reports none, so the assertion follows the pour to the top row.
    blob = _evidence_blob(top)
    assert "overlap bbox" in blob


def test_pillbox_crystal_region_is_reported_as_measured():
    """Acceptance anchor 3: 药箱 — measured here, not quoted from the task book.

    Its crystal sits on a two-layer board, so it gets two rows rather than
    four, and both name one ``GND`` pour. The rows also carry the inner layers'
    absence nowhere — a two-layer board asks two layers, and the rows say so.

    135 changes the label only: the pours named here are the ``POURED``
    **results** (``["POURED","e734"]`` top, ``["POURED","e875"]`` bottom) rather
    than the regions they came from, because 药箱's ground results still reach
    the crystal footprint on both faces. Both readings agree that the copper is
    there; which record proves it is the change.
    """
    rows = _findings(PILLBOX)
    assert len(rows) == 2, [row.message for row in rows]
    for name in ("Top Layer", "Bottom Layer"):
        row = _layer_row(rows, name)
        assert "(kind=poured)" in row.message
        assert "@ GND" in row.message
    assert '"POURED"' in rows[0].message and '"POURED"' in rows[1].message
    assert all("Inner" not in row.message for row in rows)


def test_every_row_names_the_pending_margin_and_withholds_a_verdict():
    """The evidence must show the reader what the one chosen number was.

    ``CRYSTAL_REGION_MARGIN_MIL`` is a default nobody ruled on, so a row that
    used it without saying so would be reporting a measurement it did not make.
    The row also has to say that the region query is an **inventory** rather
    than a clearance, because the two read the same board differently.
    """
    for path in (FOC_100, ROBOT, PILLBOX):
        for row in _findings(path):
            blob = _evidence_blob(row)
            assert str(CRYSTAL_REGION_MARGIN_MIL) in blob
            assert "default, not a measurement" in blob
            assert "region_copper" in blob
            assert "待裁" in blob or "no keepout" in blob
            assert "region asked:" in blob


def test_llc_places_no_mcu_and_is_silent():
    """The control: llc has no ``ic.mcu`` part, so it has no crystal region.

    Silence here is a **result**, not a skip — the same claim 131d and 131e
    make for the same board, and the reason the ``findings == []`` assertion in
    ``test_126b`` still holds after a tenth rule joined the list.
    """
    assert _findings(LLC) == []


def test_no_board_or_model_is_silent_rather_than_raising():
    """A context with no board or no ``pcb_model`` produces nothing at all."""
    from boardwise.rules.pcb.base import PcbReviewContext

    rule = McuCrystalKeepout()
    assert rule.check(PcbReviewContext(board=None)) == []
    assert rule.check(PcbReviewContext(board=parse_epro2(FOC_100), pcb_model=None)) == []


def test_the_region_asks_every_copper_layer_the_stackup_names():
    """Per-layer is the contract, and the layer list comes from the stackup.

    毕设FOC 1.0.0 is a four-layer board whose ``LAYER`` table declares all 32
    possible inner layers; asking what the physical stackup says (125a's
    reading) is what keeps the row count at four instead of 34.
    """
    board = parse_epro2(FOC_100)
    layers = [info.layer_id for info in read_stackup(board).copper_layers]
    assert layers == [1, 2, 15, 16]
    assert len(_findings(FOC_100)) == len(layers)
