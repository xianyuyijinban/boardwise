"""Tests for task 125 stick 1 (125a): geometric measurement primitives.

Two evidence sources, per the task book:

* **Synthetic boards** — hand-built :class:`BoardGeometry` objects (the
  ``__post_init__`` net index supports manual construction) with every
  expected value derived by hand in a comment next to the assertion.
* **Fixtures (read-only)** — `llc_board.epro2` (2-layer, C7 anchor) and
  `ProPrj_毕设FOC驱动板_2026-09-17.epro2` (岳亲裁 four-layer board).

The 毕设FOC fixture carries **three** PCB documents (040b measured the same
project as three boards): "PCB3" (33 components, 2-layer — the document
``parse_epro2``'s first-document rule reads, pinned by test_042), "PCB1"
(105 components, the 4-layer driver board), "PCB2" (11 components, 2-layer).
The four-layer anchor therefore reads the **main** PCB document — the one
with the most components — via the public ``extract_board`` path, which is
also the geometry 125b's inner-layer pour test will need.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    StackupEntry,
    TrackSegment,
)
from boardwise.core.measure import (
    _pad_corners,
    component_distance,
    loop_area,
    pad_edge_distance,
    read_stackup,
    track_width_stats,
    track_width_table,
)
from boardwise.parsers.epru import (
    extract_board,
    load_epro2_source,
    parse_epro2,
)

FIXTURES = Path(__file__).parent / "fixtures"
LLC = FIXTURES / "llc_board.epro2"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"


@pytest.fixture(scope="module")
def llc_board():
    return parse_epro2(LLC)


def _main_pcb_board(path: Path) -> BoardGeometry:
    """Geometry of the project's main PCB document (the most components)."""
    source = load_epro2_source(path)
    document = max(
        source.documents_of_type("PCB"),
        key=lambda d: sum(1 for r in d.records if r.type == "COMPONENT"),
    )
    return extract_board(document, source.footprints(), source.stats)


@pytest.fixture(scope="module")
def foc_main_board():
    return _main_pcb_board(FOC)


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
    shape: str = "RECT",
    angle: float = 0.0,
) -> PadGeometry:
    """One hand-built pad. ``angle`` is board-frame (post-125a contract)."""
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
        shape=shape,
        angle=angle,
    )


def _layer_table(board: BoardGeometry) -> str:
    return "\n".join(
        f"  layer_id={li.layer_id} name={li.name!r} layer_type={li.layer_type!r}"
        for _, li in sorted(board.layers.items())
    )


# ---------------------------------------------------------------------------
# stackup
# ---------------------------------------------------------------------------


def _stackup_board() -> BoardGeometry:
    """The 毕设FOC "PCB1" layer situation in miniature, plus one phantom.

    Layer definitions include a phantom Inner3 (SIGNAL) that the editor
    offers but the physical stackup does not seat — exactly what the real
    file does with its 32 inner-layer definitions on a 4-layer board.
    """
    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        3: LayerInfo(3, "Top Silkscreen Layer", "TOP_SILK"),
        15: LayerInfo(15, "Inner1", "PLANE"),
        16: LayerInfo(16, "Inner2", "SIGNAL"),
        17: LayerInfo(17, "Inner3", "SIGNAL"),  # phantom: defined, not seated
        361: LayerInfo(361, "Dielectric1", "SUBSTRATE"),
        362: LayerInfo(362, "Dielectric2", "SUBSTRATE"),
        363: LayerInfo(363, "Dielectric3", "SUBSTRATE"),
    }
    stackup = [
        StackupEntry(3, 1, "", 0.0),
        StackupEntry(1, 1000, "外层铜厚1oz", 1.378),
        StackupEntry(361, 1001, "7628 RC49% 8.6mil", 8.283),
        StackupEntry(15, 1002, "内层铜厚", 0.598),
        StackupEntry(362, 1003, "1.1mm H/HOZ Copper", 41.929),
        StackupEntry(16, 1004, "内层铜厚", 0.598),
        StackupEntry(363, 1005, "7628 RC49% 8.6mil", 8.283),
        StackupEntry(2, 9000, "外层铜厚1oz", 1.378),
    ]
    return BoardGeometry(layers=layers, stackup=stackup)


def test_plane_layer_type_counts_as_copper():
    # Evidence: 毕设FOC "PCB1" ["LAYER",15] = {"layerType": "PLANE",
    # "layerName": "Inner1", "use": true}, seated between two dielectrics in
    # that document's LAYER_PHYS stackup. An inner plane is copper.
    assert LayerInfo(15, "Inner1", "PLANE").is_copper


def test_read_stackup_phys_records_exclude_phantom_layers():
    info = read_stackup(_stackup_board())
    # Hand count of the stackup above: copper at 1 / 15 / 16 / 2, sorted by
    # layer_id -> [1, 2, 15, 16]; the phantom Inner3 (17) is defined but not
    # seated, the silkscreen (3) and dielectrics (361-363) are not copper.
    assert info.copper_count == 4
    assert [li.layer_id for li in info.copper_layers] == [1, 2, 15, 16]


def test_read_stackup_falls_back_to_layer_definitions_without_phys():
    board = _stackup_board()
    board.stackup = []
    info = read_stackup(board)
    # Without LAYER_PHYS the best available truth is the LAYER table: every
    # copper-typed definition counts, phantom included -> 5.
    assert info.copper_count == 5
    assert [li.layer_id for li in info.copper_layers] == [1, 2, 15, 16, 17]


def test_read_stackup_skips_unclassifiable_stackup_entries():
    board = _stackup_board()
    board.stackup.append(StackupEntry(99, 8999))  # no LayerInfo for 99
    info = read_stackup(board)
    # 99 cannot be classified (no LAYER record) -> skipped, not guessed.
    assert info.copper_count == 4


def test_read_stackup_used_layers():
    board = BoardGeometry(
        layers={
            1: LayerInfo(1, "Top Layer", "TOP"),
            2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
            12: LayerInfo(12, "Multi-Layer", "MULTI"),
            15: LayerInfo(15, "Inner1", "SIGNAL"),
        },
        pads=[
            _pad("p1", net="A", layer_id=1),
            _pad("p2", net="A", layer_id=12),  # MULTI is not a copper layer
        ],
        tracks=[
            TrackSegment(id="t1", net="A", layer_id=15, start=Point(0, 0), end=Point(10, 0), width=5),
            TrackSegment(id="t2", net="A", layer_id=99, start=Point(0, 0), end=Point(10, 0), width=5),
        ],
    )
    info = read_stackup(board)
    # Layer 15 has a track, layer 1 has a pad; the MULTI pad and the track on
    # undefined layer 99 classify as nothing. Layer 2 exists but carries no
    # element, so it is absent here while staying in copper_layers.
    assert info.used_copper_layer_ids == [1, 15]
    assert [li.layer_id for li in info.copper_layers] == [1, 2, 15]


def test_llc_stackup_two_copper_layers(llc_board):
    info = read_stackup(llc_board)
    assert info.copper_count == 2, _layer_table(llc_board)
    assert [li.layer_id for li in info.copper_layers] == [1, 2]
    assert info.used_copper_layer_ids == [1, 2]


def test_foc_main_board_is_the_four_layer_driver(foc_main_board):
    # The selection itself is part of the anchor: three PCB documents, and
    # the main one (most components) is the 105-part driver board.
    assert len(foc_main_board.components) == 105


def test_foc_main_board_four_copper_layers(foc_main_board):
    info = read_stackup(foc_main_board)
    # 岳 2026-10-07 亲裁: this board is 4-layer. LAYER_PHYS seats copper
    # 1 / 15 / 16 / 2 with dielectrics 361 / 362 / 363 between (zIndex
    # 1000/1001/1002/1003/1004/1005/9000). The LAYER table alone would read
    # 34 — every doc defines all 32 inner layers, used or not.
    assert info.copper_count == 4, (
        f"毕设FOC 主板应读出 4 层铜，实际 {info.copper_count} 层；"
        f"实际读到的全部 LayerInfo:\n{_layer_table(foc_main_board)}"
    )
    assert [li.layer_id for li in info.copper_layers] == [1, 2, 15, 16]
    # Evidence pin for the PLANE extension: Inner1 really is typed PLANE.
    assert foc_main_board.layers[15].layer_type == "PLANE"
    # The physical stackup also seats three dielectrics.
    dielectrics = {e.layer_id for e in foc_main_board.stackup} - {1, 2, 15, 16}
    assert {361, 362, 363} <= dielectrics


def test_foc_main_board_used_layers(foc_main_board):
    info = read_stackup(foc_main_board)
    # Measured on the fixture: element copper (pads/tracks) lives on 1 / 2 /
    # 16. Inner1 (15) is a PLANE layer — its copper is the plane itself, not
    # tracks — and the 55 POURED records carry no layer_id, so "used" is
    # honestly smaller than the stackup. That is why the two fields differ.
    assert info.used_copper_layer_ids == [1, 2, 16]


def test_foc_first_pcb_document_remains_two_layer():
    # parse_epro2 keeps its first-document rule (test_042 pins the resulting
    # 33 components): the first PCB document here is "PCB3", a 2-layer board.
    board = parse_epro2(FOC)
    assert read_stackup(board).copper_count == 2


def test_llc_phys_records_parse_into_the_stackup(llc_board):
    """The ``LAYER_PHYS`` records parse, not just the reader that consumes them.

    Every other stackup test either hand-builds `StackupEntry` objects or
    checks only the copper count. Nothing pinned that the *parser* reads the
    record id (`["LAYER_PHYS",<layer>]`), the z order, or the mil thickness —
    so deleting the `elif rtype == "LAYER_PHYS"` arm would silently drop
    `board.stackup` and every test would fall back to the LAYER definitions
    and still read 2 copper layers here. This one reads the table directly.

    Measured on the fixture: 9 records; the copper sits at zIndex 4 (Top) and
    6 (Bottom) with FR4 at 5 between them, and the board's own outline-layer
    placeholders at zIndex 1 / 2 / 3 and 7 / 8 / 9. The LLC file predates the
    毕设FOC's zIndex 1000-scale, which is why only the ordering counts.
    """
    assert len(llc_board.stackup) == 9
    by_z = {e.z_index: e for e in llc_board.stackup}
    # Ordered by z_index, so the list itself is the physical top-to-bottom order.
    assert [e.z_index for e in llc_board.stackup] == sorted(e.z_index for e in llc_board.stackup)
    assert (by_z[4].layer_id, by_z[4].thickness) == (1, 1.378)
    assert (by_z[5].layer_id, by_z[5].material, by_z[5].thickness) == (361, "FR4", 59.449)
    assert (by_z[6].layer_id, by_z[6].thickness) == (2, 1.378)
    # The two copper entries are the only ones read_stackup keeps.
    assert [e.layer_id for e in llc_board.stackup if e.layer_id in (1, 2)] == [1, 2]


def test_foc_phys_records_carry_the_four_layer_order(foc_main_board):
    """The 4-layer answer is read from the file's own physical ordering.

    This is the anti-hardcode pin for the copper_count == 4 anchor: it walks
    the parsed stackup top-to-bottom and names the copper / dielectric
    alternation the file actually carries, so a hardcoded 4 (or a fallback to
    the LAYER definitions) cannot satisfy it.

    Measured on "PCB1" (META title "PCB1", the 105-component board):
    copper at zIndex 1000 / 1002 / 1004 / 9000 = layers 1 / 15 / 16 / 2, with
    dielectrics 361 / 362 / 363 at 1001 / 1003 / 1005. 1 oz outer copper
    reads 1.378 mil (35 um), inner copper 0.598 mil (half an ounce, 15 um).
    """
    seated = [(e.z_index, e.layer_id, e.thickness) for e in foc_main_board.stackup]
    copper = [(z, lid) for z, lid, _ in seated if lid in (1, 2, 15, 16)]
    dielectric = [(z, lid) for z, lid, _ in seated if lid in (361, 362, 363)]
    assert copper == [(1000, 1), (1002, 15), (1004, 16), (9000, 2)]
    assert dielectric == [(1001, 361), (1003, 362), (1005, 363)]
    # 1 oz = 35 um = 1.378 mil outer, half-oz = 15 um = 0.598 mil inner.
    thickness = {lid: t for _, lid, t in seated}
    assert thickness[1] == pytest.approx(1.378, abs=0.001)
    assert thickness[2] == pytest.approx(1.378, abs=0.001)
    assert thickness[15] == pytest.approx(0.598, abs=0.001)
    assert thickness[16] == pytest.approx(0.598, abs=0.001)


def test_foc_main_board_is_not_selected_by_a_magic_count(foc_main_board):
    """The "most components" board selection is a fact about the file.

    All three PCB documents are enumerated with their real component counts
    so the 105-part choice is auditable rather than implicit: PCB3 33 (2-layer,
    first — what `parse_epro2` reads), PCB1 105 (the 4-layer driver board),
    PCB2 11 (2-layer). The counts are also each one of these boards' identity,
    so a change in the fixture surfaces here instead of silently retargeting
    the four-layer anchor.
    """
    source = load_epro2_source(FOC)
    counts = {
        document.uuid: sum(1 for r in document.records if r.type == "COMPONENT")
        for document in source.documents_of_type("PCB")
    }
    assert sorted(counts.values()) == [11, 33, 105]
    assert len(foc_main_board.components) == max(counts.values())


# ---------------------------------------------------------------------------
# track widths
# ---------------------------------------------------------------------------


def _widths_board() -> BoardGeometry:
    return BoardGeometry(
        tracks=[
            # 3-4-5 triangle scaled by 10 -> length exactly 50.
            TrackSegment(id="t1", net="N1", layer_id=1, start=Point(0, 0), end=Point(30, 40), width=10),
            TrackSegment(id="t2", net="N1", layer_id=1, start=Point(0, 0), end=Point(0, 15), width=20),
            TrackSegment(id="t3", net="N1", layer_id=2, start=Point(0, 0), end=Point(12, 0), width=30),
        ],
        pads=[_pad("p1", net="N2", layer_id=1)],  # N2 has copper but no tracks
    )


def test_track_width_stats_hand_computed():
    stats = track_width_stats(_widths_board(), "N1")
    # widths {10, 20, 30}, lengths {50, 15, 12}.
    assert stats.net == "N1"
    assert stats.track_count == 3
    assert stats.min_width == 10
    assert stats.max_width == 30
    assert stats.total_length == 50 + 15 + 12


def test_track_width_stats_per_layer():
    stats = track_width_stats(_widths_board(), "N1")
    layer1 = stats.per_layer[1]
    assert (layer1.track_count, layer1.min_width, layer1.total_length) == (2, 10, 65)
    layer2 = stats.per_layer[2]
    assert (layer2.track_count, layer2.min_width, layer2.total_length) == (1, 30, 12)


def test_track_width_stats_unknown_net_is_zero():
    stats = track_width_stats(_widths_board(), "NO_SUCH_NET")
    assert stats.track_count == 0
    assert stats.min_width == 0.0
    assert stats.max_width == 0.0
    assert stats.total_length == 0.0
    assert stats.per_layer == {}


def test_track_width_table_skips_trackless_nets():
    table = track_width_table(_widths_board())
    assert set(table) == {"N1"}


# ---------------------------------------------------------------------------
# pad / component distances
# ---------------------------------------------------------------------------


def test_pad_edge_distance_axis_aligned():
    a = _pad("a", x=0, y=0, width=100, height=60)
    b = _pad("b", x=300, y=0, width=100, height=60)
    # Facing edges at x=50 and x=250 -> 200; argument order must not matter.
    assert pad_edge_distance(a, b) == pytest.approx(200.0, abs=1e-9)
    assert pad_edge_distance(b, a) == pytest.approx(200.0, abs=1e-9)


def test_pad_edge_distance_touching_is_zero():
    a = _pad("a", x=0, y=0, width=100, height=60)
    b = _pad("b", x=100, y=0, width=100, height=60)
    # Edges coincide at x=50 -> touching -> 0.
    assert pad_edge_distance(a, b) == pytest.approx(0.0, abs=1e-9)


def test_pad_edge_distance_rotated_90():
    a = _pad("a", x=0, y=0, width=100, height=40, angle=90)
    b = _pad("b", x=200, y=0, width=100, height=40)
    # A rotated 90° becomes 40 wide (x in [-20, 20]) x 100 tall; B spans
    # x in [150, 250] -> 150 - 20 = 130.
    assert pad_edge_distance(a, b) == pytest.approx(130.0, abs=1e-9)


def test_pad_corners_contract_for_stick_two():
    """`_pad_corners` is 125b's interface: 4 CCW corners, board coordinates.

    125b's clearance engine consumes the same corner sets for pads, tracks and
    pours, so its contract is pinned here rather than left to a later task:
    exactly four points, in counter-clockwise order (positive shoelace), and
    rotated about the pad's own centre in the y-up board frame.

    A 60 x 30 pad at 90° is 30 wide by 60 tall, so its corners sit
    (+-15, +-30) around the centre: CCW from the top-left corner (-15, +30)
    goes (-15, -30) -> (15, -30) -> (15, 30) -> (-15, 30), i.e. down, right,
    up, left, which is counter-clockwise in a y-up frame. (The local
    top-right corner (hw, hh) = (30, 15) rotates to (-15, 30) — CCW in the
    y-up frame carries +x toward +y.)
    """
    pad = _pad("p", x=1030, y=575, width=60, height=30, angle=90)
    corners = _pad_corners(pad)
    assert len(corners) == 4
    assert corners == [
        Point(1015.0, 605.0),
        Point(1015.0, 545.0),
        Point(1045.0, 545.0),
        Point(1045.0, 605.0),
    ]
    # CCW: the shoelace sum is positive for this ordering.
    total = sum(
        p.x * q.y - q.x * p.y
        for p, q in zip(corners, [*corners[1:], corners[0]])
    )
    assert total > 0
    # The rotation is about the pad's centre, which is preserved.
    assert math.hypot(
        sum(c.x for c in corners) / 4 - 1030, sum(c.y for c in corners) / 4 - 575
    ) == pytest.approx(0.0, abs=1e-9)


def test_pad_edge_distance_rotated_45():
    a = _pad("a", x=0, y=0, width=40, height=40, angle=45)
    b = _pad("b", x=100, y=0, width=40, height=40)
    # A 40x40 square at 45° is a diamond; its rightmost vertex is the local
    # corner (20, -20) rotated to ((20+20)/sqrt(2), 0) = (20*sqrt(2), 0).
    # B's left edge is x = 80, spanning y in [-20, 20], which contains y=0,
    # so the distance is horizontal: 80 - 20*sqrt(2) = 51.71572875...
    assert pad_edge_distance(a, b) == pytest.approx(80 - 20 * math.sqrt(2), abs=1e-9)


def test_pad_edge_distance_intersecting_is_zero():
    a = _pad("a", x=0, y=0, width=100, height=100)
    b = _pad("b", x=50, y=0, width=100, height=100)
    # Rectangles overlap over x in [50, 50+] -> edges cross -> 0.
    assert pad_edge_distance(a, b) == 0.0


def test_pad_edge_distance_oval_uses_bounding_rect():
    rect = _pad("r", x=0, y=0, width=100, height=40, shape="RECT")
    oval = _pad("o", x=0, y=0, width=100, height=40, shape="OVAL")
    far = _pad("f", x=200, y=0, width=100, height=40, shape="ELLIPSE")
    # Same bounding box -> same measurement (200 - 50 - 50 = 100): the
    # conservative under-estimate contract for non-rectangular shapes.
    assert pad_edge_distance(oval, far) == pytest.approx(100.0, abs=1e-9)
    assert pad_edge_distance(oval, far) == pytest.approx(
        pad_edge_distance(rect, far), abs=1e-9
    )


def _component_board() -> BoardGeometry:
    """R1 at (1000, 0) angle 0, C1 at (1030, 500) angle 90, plus padless TP1.

    Both parts are top-side (``layer_id = 1``), and the hand-built pads carry no
    ``effective_layer_ids`` — so they read through
    :func:`~boardwise.core.measure._element_layers`'s pre-127b fallback, which is
    exactly what "no physical reading established" has always meant here.
    """
    return BoardGeometry(
        components=[
            ComponentPlacement(id="cr1", designator="R1", x=1000, y=0, angle=0),
            ComponentPlacement(id="cc1", designator="C1", x=1030, y=500, angle=90),
            ComponentPlacement(id="ct1", designator="TP1", x=0, y=0, angle=0),
        ],
        pads=[
            _pad("p1", component="R1", pin="1", net="GND", layer_id=1, x=975, y=0, width=50, height=40),
            _pad("p2", component="R1", pin="2", net="SIG", layer_id=1, x=1025, y=0, width=50, height=40),
            # 60x30 at board-frame 90° -> 30 wide (x ±15) by 60 tall (y ±30).
            _pad("p3", component="C1", pin="1", net="GND", layer_id=1, x=1030, y=575, width=60, height=30, angle=90),
            _pad("p4", component="C1", pin="2", net="SIG", layer_id=1, x=1030, y=425, width=60, height=30, angle=90),
        ],
    )


def test_component_distance_hand_computed():
    dist = component_distance(_component_board(), "R1", "C1")
    assert dist is not None
    # Anchors (1000, 0) and (1030, 500) -> hypot(30, 500). The anchor distance
    # is unchanged by 127b: it is the distance between the two placements and
    # no pad exemption can move it.
    assert dist.center_distance == pytest.approx(math.hypot(30, 500), abs=1e-9)
    # **127b changed which pair is nearest**, and this is the pin that records
    # why. Under 125's layer-blind sweep the winner was R1.2/SIG against
    # C1.2/SIG at 375.0 — but those are **the same net**, and two pads of one
    # net meeting is the design's own connection, not a placement defect, so
    # that pair is now exempt. The winner is the nearest *surviving* pair:
    # R1.1/GND against C1.2/SIG.
    #
    #   R1.1 spans x [950, 1000], y [-20, 20]
    #   C1.2 spans x [1015, 1045], y [395, 455]   (60x30 rotated 90° -> 30 x 60)
    # Neither range overlaps the other on either axis, so the gap is the corner
    # to corner distance: dx = 1015 - 1000 = **15**, dy = 395 - 20 = **375**,
    # hypot(15, 375) = **375.2999**. (R1.2/C1.1, the 540.0 corner-to-corner
    # alternative, is further.) Stated so a reader can redo the subtraction.
    assert dist.edge_distance == pytest.approx(math.hypot(15, 375), abs=1e-9)
    assert (dist.pad_a, dist.pad_b) == ("1", "2")


def test_component_distance_unknown_designator_is_none():
    assert component_distance(_component_board(), "R1", "X9") is None
    assert component_distance(_component_board(), "X9", "R1") is None


def test_component_distance_component_without_pads_is_none():
    assert component_distance(_component_board(), "R1", "TP1") is None


def test_llc_c7_pad_center_distance(llc_board):
    pads = llc_board.pads_for_component("C7")
    assert len(pads) == 2
    center = math.hypot(pads[0].x - pads[1].x, pads[0].y - pads[1].y)
    # 001 反推板人工抽测: P7.50 封装 -> 7.50 mm = 295.28 mil.
    assert center == pytest.approx(295.28, abs=0.05)


def test_llc_c7_pad_edge_distance(llc_board):
    pads = llc_board.pads_for_component("C7")
    # Both pads are 70.866 x 70.866 squares (1.8 mm) with the centres 295.28
    # apart on a horizontal line (dy = 0, measured above). Each pad's facing
    # half-width is 70.866 / 2 = 35.433, so the edge gap is
    # 295.28 - 35.433 - 35.433 = 224.414 mil.
    assert pad_edge_distance(pads[0], pads[1]) == pytest.approx(295.28 - 70.866, abs=0.05)


def test_llc_board_outline_bbox(llc_board):
    bbox = llc_board.bbox()
    assert bbox is not None
    # 155 x 80 mm outline -> 6102.36 x 3149.61 mil.
    assert bbox.width == pytest.approx(6102.36, abs=0.1)
    assert bbox.height == pytest.approx(3149.61, abs=0.1)


def test_pad_angle_is_board_frame_composition_of_component_and_template(llc_board):
    """A placed pad's angle is ``component.angle + template.angle`` (125a).

    Without this pin nothing in the suite notices the parser handing the
    footprint-local angle through unchanged: mutating ``build_pads`` back to
    ``angle=template.angle`` leaves every test green, because 79 of llc's 117
    pads carry a composed angle and only ``test_pad_edge_distance``-style
    measurements — none of which the fixture pins — can tell them apart.

    Hand check on R1 (footprint ``e7``'s 1206 land pattern, pads at local
    x = +/-120.715): the component sits at (2450, -2300) rotated 90 deg CCW,
    so the local +x axis points along the board's -y. Pad 2's template angle
    is 180 deg, so the board-frame pad angle is 90 + 180 = 270. Under the
    footprint-local reading it would read 180 instead.
    """
    comp = llc_board.component("R1")
    assert comp is not None and comp.angle == 90
    pads = {p.pin_number: p for p in llc_board.pads_for_component("R1")}
    assert set(pads) == {"1", "2"}
    for pad in pads.values():
        assert pad.angle == 270
    # The pins really did swap sides under the 90 deg rotation: local
    # x = +120.714 (pin 2) lands at y = -2300 + 120.714 = -2179.286.
    assert pads["2"].y == pytest.approx(-2179.286, abs=0.01)
    assert pads["1"].y == pytest.approx(-2420.716, abs=0.01)


def test_rotated_pad_measurement_uses_the_board_frame_angle(llc_board):
    """R1's two pads measure as *short edge across* once the placement rotates.

    R1 is a 1206 resistor placed at 90 deg CCW. Each land is 50.493 x 136.063
    mil (width x height) with a template angle of 180, so in the footprint
    frame the short axis (width) already lies along the pitch axis and the
    long axis (height) crosses it. Rotating the placement by 90 sends that
    local x axis onto the board's -y, so the board-frame pad angle is 270 and
    the lands stand **tall along x, short along y**.

    Hand count: pad 2 lands at y = -2179.286, pad 1 at y = -2420.716, so the
    centres are 241.43 mil apart along y. Along y each pad only spans its
    width, half of it = 50.493 / 2 = 25.2465. The facing y-edges therefore sit
    at -2204.5325 and -2395.4695 and the edge-to-edge gap is
    241.43 - 2 * 25.2465 = 190.937 mil.

    Under the footprint-local reading (angle 180 left un-composed) the same two
    rectangles measure 105.367 mil apart, because their long axis would then
    lie along y. This assertion is what makes the composition observable.
    """
    pads = {p.pin_number: p for p in llc_board.pads_for_component("R1")}
    assert pad_edge_distance(pads["2"], pads["1"]) == pytest.approx(190.937, abs=0.01)


# ---------------------------------------------------------------------------
# loop area
# ---------------------------------------------------------------------------


def _loop_board() -> BoardGeometry:
    return BoardGeometry(
        components=[
            ComponentPlacement(id="cc1", designator="C1", x=50, y=0, angle=0),
            ComponentPlacement(id="cr1", designator="R1", x=50, y=100, angle=0),
        ],
        pads=[
            _pad("p1", component="C1", pin="1", x=0, y=0, width=10, height=10),
            _pad("p2", component="C1", pin="2", x=100, y=0, width=10, height=10),
            _pad("p3", component="R1", pin="1", x=0, y=100, width=10, height=10),
            _pad("p4", component="R1", pin="2", x=100, y=100, width=10, height=10),
        ],
    )


def test_loop_area_triangle_hand_computed():
    loop = loop_area(_loop_board(), ["C1", "R1", Point(150, 50)])
    # Component anchors are pad centroids: C1 -> (50, 0), R1 -> (50, 100).
    # Shoelace over (50, 0), (50, 100), (150, 50):
    #   (50*100 - 50*0) + (50*50 - 150*100) + (150*0 - 50*50) = -10000
    # area = |total| / 2 = 5000; bbox (50, 0)-(150, 100) -> 100 * 100 = 10000.
    assert loop.anchor_points == [Point(50, 0), Point(50, 100), Point(150, 50)]
    assert loop.polygon_area == pytest.approx(5000.0, abs=1e-9)
    assert loop.bbox_area == pytest.approx(10000.0, abs=1e-9)
    assert loop.bbox_area >= loop.polygon_area


def test_loop_area_pin_anchor_resolves_pad_center():
    loop = loop_area(_loop_board(), ["C1.2", "R1.1"])
    assert loop.anchor_points == [Point(100, 0), Point(0, 100)]
    # Two points enclose nothing, but the bbox upper bound still reports.
    assert loop.polygon_area == 0.0
    assert loop.bbox_area == pytest.approx(10000.0, abs=1e-9)


def test_loop_area_unknown_anchor_raises():
    with pytest.raises(ValueError):
        loop_area(_loop_board(), ["X9"])
    with pytest.raises(ValueError):
        loop_area(_loop_board(), ["C1.99"])


def test_llc_c7_pin_anchors_track_pad_centres(llc_board):
    pads = llc_board.pads_for_component("C7")
    loop = loop_area(llc_board, ["C7.1", "C7.2"])
    # Anchors resolve to the same centres the 295.28 mil anchor uses.
    assert loop.anchor_points == [p.center for p in pads]
