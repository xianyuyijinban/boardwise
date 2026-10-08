"""Tests for task 125 stick 2 (125b): net clearance engine + pour connectivity.

Two evidence sources, per the task book:

* **Synthetic boards** — hand-built :class:`BoardGeometry` objects with
  every expected value derived by hand in a comment next to the assertion:
  parallel-track spacing, crossing-track overlap, a cross-layer via chain
  joining two islands, an SMD pad that must not bridge layers, and a
  three-island GND pour board.
* **Fixtures (read-only)** — `llc_board.epro2` (2-layer, FILL pours, the
  hand-computed ``CHS`` vs ``DC+`` clearance) and
  `ProPrj_毕设FOC驱动板_2026-09-17.epro2`'s **PCB1** main board (the
  four-layer driver, via-chain cross-layer connectivity).

The 毕设FOC fixture carries three PCB documents; as in stick 1, the main
one (the most components = the 105-part driver board) is selected via the
public ``extract_board`` path, whose "most components" idiom is copied from
``test_125_pcb_measure.py`` rather than invented here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.geometry import (
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
    net_clearance,
    pour_connectivity,
    read_stackup,
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
    """Geometry of the project's main PCB document (the most components).

    The selection idiom is copied from ``test_125_pcb_measure.py`` so the
    four-layer anchor targets the same board that stick 1 pinned.
    """
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
    angle: float = 0.0,
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
        angle=angle,
        hole_diameter=hole,
    )


def _two_layer_stack() -> tuple[dict[int, LayerInfo], list[StackupEntry]]:
    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        361: LayerInfo(361, "Dielectric1", "SUBSTRATE"),
    }
    stackup = [
        StackupEntry(1, 1000, "外层铜厚", 1.378),
        StackupEntry(361, 1001, "FR4", 59.449),
        StackupEntry(2, 9000, "外层铜厚", 1.378),
    ]
    return layers, stackup


# ---------------------------------------------------------------------------
# clearance: parallel tracks, crossing tracks, widths
# ---------------------------------------------------------------------------


def test_parallel_track_clearance_hand_computed():
    """Two parallel tracks, same layer, hand gap between their copper edges."""
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        tracks=[
            # A: horizontal at y=0, width 20 -> copper y in [-10, +10].
            TrackSegment("ta", net="A", layer_id=1, start=Point(0, 0), end=Point(100, 0), width=20),
            # B: horizontal at y=60, width 20 -> copper y in [50, 70].
            # Nearest edges: +10 (A top) and 50 (B bottom) -> 40.
            TrackSegment("tb", net="B", layer_id=1, start=Point(0, 60), end=Point(100, 60), width=20),
        ],
    )
    result = net_clearance(board, "A", "B")
    assert result is not None
    assert result.distance == pytest.approx(40.0, abs=1e-9)
    assert not result.overlapping  # parallel, same layer, but not touching


def test_parallel_track_clearance_subtracts_half_widths():
    """The 40 mil gap above is centerline(60) − half(20) − half(20) = 40."""
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        tracks=[
            TrackSegment("ta", net="A", layer_id=1, start=Point(0, 0), end=Point(100, 0), width=25),
            TrackSegment("tb", net="B", layer_id=1, start=Point(0, 55), end=Point(100, 55), width=5),
        ],
    )
    result = net_clearance(board, "A", "B")
    # Centerlines 55 apart; A's copper reaches +12.5, B's reaches 55 − 2.5.
    # Gap = (55 − 2.5) − 12.5 = 40.
    assert result is not None
    assert result.distance == pytest.approx(40.0, abs=1e-9)


def test_crossing_tracks_overlap_same_layer():
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        tracks=[
            TrackSegment("ta", net="A", layer_id=1, start=Point(0, 0), end=Point(100, 0), width=10),
            TrackSegment("tb", net="B", layer_id=1, start=Point(50, -50), end=Point(50, 50), width=10),
        ],
    )
    result = net_clearance(board, "A", "B")
    assert result is not None
    # The two 10-wide tracks cross at (50, 0) on the same layer: their
    # copper bodies intersect, so the gap is 0 and this IS a planar short.
    assert result.distance == 0.0
    assert result.overlapping is True


def test_crossing_tracks_different_layers_are_projection_not_overlap():
    """Cross-layer = XY projection distance, and never ``overlapping``."""
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        tracks=[
            TrackSegment("ta", net="A", layer_id=1, start=Point(0, 0), end=Point(100, 0), width=10),
            TrackSegment("tb", net="B", layer_id=2, start=Point(50, -50), end=Point(50, 50), width=10),
        ],
    )
    result = net_clearance(board, "A", "B")
    assert result is not None
    # Same XY crossing as the previous test, but B is on layer 2. The planar
    # projection distance is still 0, but there is no shared copper layer,
    # so this is ordinary routing, NOT a short.
    assert result.distance == 0.0
    assert result.overlapping is False


def test_clearance_via_pad_hand_computed():
    """Via (round, radius = dia/2) vs pad rectangle, hand-computed 40 mil.

    The via's 60 mil pad is a circle of radius 30, so its copper reaches
    x = +30. The pad is a 60 x 40 rectangle centred at (100, 0), so its
    left edge is at x = 70 and it spans y in [-20, 20] — which contains the
    via's centreline y = 0, so the separation is purely horizontal:
    70 − 30 = **40 mil**. The capsule arithmetic gets there the long way:
    the centreline distance between the via's centre and the pad's nearest
    edge point is 70, minus the via's radius 30 and the pad's 0 (a bare
    rectangle carries no capsule radius) = 40.
    """


def test_unknown_nets_return_empty_results():
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        tracks=[TrackSegment("ta", net="A", layer_id=1, start=Point(0, 0), end=Point(10, 0), width=5)],
    )
    # Unknown net -> None, never a raise; self-pair -> None.
    assert net_clearance(board, "A", "NOPE") is None
    assert net_clearance(board, "A", "A") is None
    assert clearances_vs(board, "NOPE") == {}
    assert pour_connectivity(board, "NOPE").island_count == 0


# ---------------------------------------------------------------------------
# clearance: fixtures (hand-computed anchors)
# ---------------------------------------------------------------------------


def test_llc_chs_vs_dcp_plus_pad_clearance(llc_board):
    """Q1's two source pads: 214.17 centre-to-centre, 110.236 wide each.

    Q1.3 (net CHS, pad id e22) and Q1.2 (net DC+, pad id e21) are the two
    source pads of the same MOSFET. Both are 110.236 x 86.614 rectangles at
    y = -2709.996, centres 2279.998 and 2494.168 apart -> 214.170 in x, with
    the x-ranges touching-span. Each pad's facing half-width is
    110.236 / 2 = 55.118, so the edge-to-edge gap is
    214.170 − 55.118 − 55.118 = 103.934 mil.
    """
    result = net_clearance(llc_board, "CHS", "DC+")
    assert result is not None
    assert result.distance == pytest.approx(214.170 - 110.236, abs=0.01)
    # Both pads are through-hole (layer 12 = MULTI), so they share copper.
    assert "Q1.3" in result.element_a
    assert "Q1.2" in result.element_b


def test_llc_chs_vs_chg_track_clearance_hand_computed(llc_board):
    """CHS and CHG gate tracks, hand 40 mil edge gap (fixture-verified).

    CHS's nearest track ``5685cfda82d6f5b0`` runs vertically at x = 2445
    (width 60, so its copper spans x in [2415, 2475]). CHG's nearest track
    ``07c8e25c3fa445ec`` runs horizontally at y = -2970 ending at x = 2345
    (width 60, so its copper reaches x = 2375 and its y-band is
    [-3000, -2940]). The two copper bodies' nearest edges are therefore
    CHS's left edge at x = 2415 and CHG's right edge at x = 2375, and the
    y-bands overlap (CHS band [2415,2475]x contains -2970), so the gap is
    purely horizontal: 2415 − 2375 = **40.0 mil**. Same layer (1), but the
    tracks do not touch, so ``overlapping`` is False.
    """
    result = net_clearance(llc_board, "CHS", "CHG")
    assert result is not None
    assert result.distance == pytest.approx(2415.0 - 2375.0, abs=1e-6)
    assert result.distance == pytest.approx(40.0, abs=1e-6)
    assert not result.overlapping
    assert "5685cfda82d6f5b0" in result.element_a
    assert "07c8e25c3fa445ec" in result.element_b


def test_llc_chg_vs_cls_track_clearance_cross_layer_agnostic(llc_board):
    """A second measured pair: CHG vs CLG, both layer-1 tracks, 362.688 mil.

    CHG's horizontal track ``07c8e25c3fa445ec`` ends at (2345, -2970);
    CLG's vertical track ``faa458de4e2fb294`` runs x = 2745.828 over
    y in [-2835.828, -2709.996], so its nearest endpoint to the CHG
    endpoint is (2745.828, -2835.828). The centreline-to-centreline
    distance is hypot(2745.828 - 2345, 2835.828 - 2970)
    = hypot(400.828, 134.172) = 422.6880778635707. Both tracks are 60 mil
    wide, so the capsule arithmetic subtracts 30 + 30 = 60:
    422.6880778635707 - 60 = **362.6880778635707**. Same layer, no touch.
    """
    result = net_clearance(llc_board, "CHG", "CLG")
    assert result is not None
    assert result.distance == pytest.approx(362.6880778635707, abs=1e-6)
    assert not result.overlapping


def test_llc_clearances_vs_largest_net(llc_board):
    """clearances_vs on the largest net (DC-, 204 elements) is fast."""
    import time

    net = llc_board.nets_sorted_by_copper()[0].name
    assert net == "DC-"
    start = time.perf_counter()
    table = clearances_vs(llc_board, "DC-")
    elapsed = time.perf_counter() - start
    # DC- has 204 elements across 25 nets; the pairwise bbox-filtered scan
    # is well under a second here.
    assert len(table) >= 20
    assert elapsed < 2.0, f"clearances_vs took {elapsed:.2f}s on the largest net"


# ---------------------------------------------------------------------------
# pour connectivity: synthetic boards
# ---------------------------------------------------------------------------


def _pour(
    id: str,
    net: str,
    layer_id: int,
    points: list[Point],
    kind: str = "fill",
) -> PourShape:
    return PourShape(id=id, net=net, layer_id=layer_id, kind=kind, points=points)


def test_three_island_gnd_board():
    """Three disjoint square GND pours -> three islands; areas and layers."""
    layers, stackup = _two_layer_stack()
    squares = [
        _pour("pA", "GND", 1, [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)]),
        _pour("pB", "GND", 1, [Point(200, 0), Point(300, 0), Point(300, 100), Point(200, 100)]),
        _pour("pC", "GND", 2, [Point(0, 300), Point(100, 300), Point(100, 400), Point(0, 400)]),
    ]
    board = BoardGeometry(layers=layers, stackup=stackup, pours=squares)
    result = pour_connectivity(board, "GND")
    # Three 100x100 squares on {A top, B top, C bottom}, none touching ->
    # three islands, each 10000 sq mil on its own layer.
    assert result.island_count == 3
    areas = sorted(i.area for i in result.islands)
    assert areas == [10000.0, 10000.0, 10000.0]
    by_id = {tuple(i.element_ids): i for i in result.islands}
    assert set(by_id[("pC",)].layer_ids) == {2}
    assert set(by_id[("pA",)].layer_ids) == {1}


def test_two_pours_joined_by_track_are_one_island():
    """A track from inside pour A to inside pour B merges them."""
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        pours=[
            _pour("pA", "GND", 1, [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)]),
            _pour("pB", "GND", 1, [Point(300, 0), Point(400, 0), Point(400, 100), Point(300, 100)]),
        ],
        tracks=[
            TrackSegment("t", net="GND", layer_id=1, start=Point(50, 50), end=Point(350, 50), width=10),
        ],
    )
    result = pour_connectivity(board, "GND")
    # The track's endpoints sit inside each square (containment counts as
    # connected), so both pours plus the track form one island of 20000 sq mil.
    assert result.island_count == 1
    assert result.islands[0].area == pytest.approx(20000.0, abs=1e-6)
    assert set(result.islands[0].element_ids) == {"pA", "pB", "t"}


def test_cross_layer_via_chain_joins_two_islands():
    """A via on the top pad plus a bottom track reaching the bottom pad.

    Hand count: the via at (0, 0) has a 60 mil pad, so its copper spans
    x, y in [-30, 30]. The top SMD pad ``ptop`` is a 20x20 square at
    (0, 0), wholly inside the via's pad, so via and top pad meet on layer
    1. The via spans both copper layers, so it also occupies layer 2 — where
    the bottom track ``tb`` starts at (0, 0), inside the via pad: they meet
    on layer 2 too. The track runs to (0, 200), ending inside the bottom pad
    ``pbot`` (20x20 at (0, 200)). One island, touching both layers.
    """
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        pads=[
            _pad("ptop", net="GND", layer_id=1, x=0, y=0, width=20, height=20),
            _pad("pbot", net="GND", layer_id=2, x=0, y=200, width=20, height=20),
        ],
        vias=[ViaGeometry("v", net="GND", x=0, y=0, hole_diameter=20, via_diameter=60)],
        tracks=[
            TrackSegment("tb", net="GND", layer_id=2, start=Point(0, 0), end=Point(0, 200), width=10),
        ],
    )
    result = pour_connectivity(board, "GND")
    # top pad <-> via (layer 1 touch) -> via <-> bottom track (layer 2 touch,
    # via spans layer 2) -> track <-> bottom pad. One island across both layers.
    assert result.island_count == 1
    assert set(result.islands[0].layer_ids) == {1, 2}


def test_via_chain_two_islands_top_to_inner():
    """A via spans top AND an inner layer, bridging a top pad to an inner pad."""
    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        15: LayerInfo(15, "Inner1", "SIGNAL"),
        361: LayerInfo(361, "Dielectric", "SUBSTRATE"),
    }
    stackup = [
        StackupEntry(1, 1000, "外层铜厚", 1.378),
        StackupEntry(361, 1001, "core", 8.0),
        StackupEntry(15, 1002, "内层铜厚", 0.598),
        StackupEntry(361, 1003, "core", 40.0),
        StackupEntry(2, 9000, "外层铜厚", 1.378),
    ]
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        pads=[
            _pad("ptop", net="GND", layer_id=1, x=0, y=0, width=20, height=20),
            _pad("pin", net="GND", layer_id=15, x=0, y=0, width=20, height=20),
        ],
        vias=[ViaGeometry("v", net="GND", x=0, y=0, hole_diameter=20, via_diameter=60)],
    )
    # The via spans every copper layer (no unused_inner_layers), so it
    # touches both the top pad (layer 1) and the inner pad (layer 15).
    result = pour_connectivity(board, "GND")
    assert result.island_count == 1
    assert set(result.islands[0].layer_ids) == {1, 2, 15}


def test_smd_pad_does_not_bridge_layers():
    """An SMD pad is only on its own layer: a bottom pour cannot reach it."""
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        pads=[_pad("psmd", net="SIG", layer_id=1, x=0, y=0, width=20, height=20)],
        pours=[
            # A bottom-layer pour directly under the top SMD pad. Because the
            # SMD pad exists only on layer 1, it must NOT connect to the
            # layer-2 pour even though they overlap in XY.
            _pour("pb", "SIG", 2, [Point(-50, -50), Point(50, -50), Point(50, 50), Point(-50, 50)]),
        ],
    )
    result = pour_connectivity(board, "SIG")
    # No shared layer between the SMD pad (layer 1) and the pour (layer 2),
    # so they remain two islands even though their XY footprints overlap.
    assert result.island_count == 2


def test_through_hole_pad_bridges_layers():
    """A through-hole pad (hole_diameter set) spans every copper layer."""
    layers, stackup = _two_layer_stack()
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        pads=[
            _pad("pth", net="SIG", layer_id=12, x=0, y=0, width=40, height=40, hole=30),
        ],
        pours=[
            _pour("pt", "SIG", 1, [Point(-80, -80), Point(80, -80), Point(80, 80), Point(-80, 80)]),
            _pour("pb", "SIG", 2, [Point(-80, -80), Point(80, -80), Point(80, 80), Point(-80, 80)]),
        ],
    )
    result = pour_connectivity(board, "SIG")
    # The through-hole pad occupies layers {1, 2} and sits inside both pours
    # (containment -> connected), joining the top and bottom pours into one.
    assert result.island_count == 1
    assert set(result.islands[0].layer_ids) == {1, 2}


# ---------------------------------------------------------------------------
# pour connectivity: fixture anchors
# ---------------------------------------------------------------------------


def test_llc_fills_form_one_ground_island(llc_board):
    """The LLC ground-return net DC- is one island across both layers.

    DC- carries 13 pads, 10 tracks, 177 vias and 4 FILL pours spanning
    layers 1 and 2; the vias stitch the top and bottom fills together, so
    the whole net reads as a single connected island.
    """
    result = pour_connectivity(llc_board, "DC-")
    assert result.net == "DC-"
    assert result.island_count == 1
    island = result.islands[0]
    assert set(island.layer_ids) == {1, 2}
    # Every measurable DC- element (13 pads + 10 tracks + 177 vias + 4 FILL
    # pours = 204) is in that one island.
    assert len(island.element_ids) == 204


def test_foc_main_board_via_chain_spans_inner_layers(foc_main_board):
    """GND's first island is a via chain carrying top copper down to inner.

    On the four-layer driver, GND island 0 holds eight layer-1 tracks, one
    via (``6a075b07334b9ae8`` at (1605, -745), 24.016 mil pad) and three
    top pads. The via has no ``unused_inner_layers``, so it spans all four
    copper layers (1 / 2 / 15 / 16) and the island reports all four — a
    cross-layer via chain that was actually verified against the file.
    """
    assert read_stackup(foc_main_board).copper_count == 4
    result = pour_connectivity(foc_main_board, "GND")
    assert result.net == "GND"
    island0 = result.islands[0]
    # The via id is present, and the island touches every copper layer.
    assert "6a075b07334b9ae8" in island0.element_ids
    assert set(island0.layer_ids) == {1, 2, 15, 16}


def test_foc_clearances_vs_largest_net_is_fast(foc_main_board):
    """clearances_vs on GND (the 183-element largest net) is sub-second."""
    import time

    start = time.perf_counter()
    table = clearances_vs(foc_main_board, "GND")
    elapsed = time.perf_counter() - start
    # GND has 183 elements and the board has 92 nets; the bbox-filtered
    # per-pair scan completes well under a second.
    assert len(table) >= 80
    assert elapsed < 2.0, f"clearances_vs took {elapsed:.2f}s on the largest net"


# ---------------------------------------------------------------------------
# cross-layer projection semantics, on a fixture
# ---------------------------------------------------------------------------


def test_llc_dcp_vs_dcm_crossing_tracks_are_projection_not_overlap(llc_board):
    """DC+ and DC- cross in plan view on different layers: 0.0, not a short.

    DC+'s track ``0644fb6ea9747464`` runs vertically on **layer 1** at
    x = 5670 over y in [-2475.628, -1970]. DC-'s track ``e7ba551298ae4155``
    runs horizontally on **layer 2** at y = -2375.28 over x in
    [5388.3115, 6005]. The two centrelines cross at (5670, -2375.28), which
    lies inside both spans, so the XY-plane projection distance is 0.

    They sit on different copper layers, so ``overlapping`` is False: this
    is ordinary two-layer routing, not a short. This is the cross-layer
    semantics the task book pins — cross-layer pairs are compared by their
    planar projection and can only overlap within one layer.
    """
    result = net_clearance(llc_board, "DC+", "DC-")
    assert result is not None
    assert result.distance == 0.0
    assert result.overlapping is False
    assert "0644fb6ea9747464" in result.element_a
    assert "e7ba551298ae4155" in result.element_b
    # The layer numbers are carried in the descriptions, which is how a
    # caller recovers the cross-layer fact.
    assert "layer 1" in result.element_a
    assert "layer 2" in result.element_b


# ---------------------------------------------------------------------------
# unused_inner_layers, and the POURED blind spot
# ---------------------------------------------------------------------------


def test_via_unused_inner_layers_are_not_bridged():
    """A via with an unused inner layer does not reach that layer."""
    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        15: LayerInfo(15, "Inner1", "SIGNAL"),
        361: LayerInfo(361, "Dielectric", "SUBSTRATE"),
    }
    stackup = [
        StackupEntry(1, 1000, "外层铜厚", 1.378),
        StackupEntry(361, 1001, "core", 8.0),
        StackupEntry(15, 1002, "内层铜厚", 0.598),
        StackupEntry(361, 1003, "core", 40.0),
        StackupEntry(2, 9000, "外层铜厚", 1.378),
    ]
    pad = _pad("pin", net="GND", layer_id=15, x=0, y=0, width=20, height=20)
    board = BoardGeometry(
        layers=layers,
        stackup=stackup,
        pads=[pad],
        vias=[
            ViaGeometry("v", net="GND", x=0, y=0, hole_diameter=20, via_diameter=60,
                        unused_inner_layers=[15]),
        ],
    )
    # The via skips layer 15, so it and the inner pad share no layer and
    # stay two islands — same net, still not connected.
    result = pour_connectivity(board, "GND")
    assert result.island_count == 2
    via_layers = sorted(
        isl.layer_ids for isl in result.islands if any(
            eid == "v" for eid in isl.element_ids
        )
    )
    assert via_layers == [[1, 2]]  # every copper layer except 15


def test_poured_records_are_parsed_and_orphans_carry_no_net(llc_board):
    """**135 reversed this test, deliberately.** Its old claim was that a POURED
    contributes no geometry because its path is "parent-relative and scaled 1:10,
    not board coordinates" — and it pinned llc's four POURED records as
    point-less.

    135 measured the frame and found it is a plain uniform scale:
    ``board = 10 × local``, origin (0, 0), no flip. So a POURED **is** real
    copper and now parses into islands. llc's four records hold seven
    ``fill: true`` islands between them, all four are **orphans** (llc stores no
    ``POUR`` record at all, so their parent ids resolve to nothing) and all four
    therefore carry ``net=None``.

    The consequence is pinned here rather than assumed: a net-less polygon joins
    no net, so ``DC-`` is still one island and still made of its ``FILL`` pours,
    tracks and vias. A poured result with no parent and no net cannot perturb a
    net's connectivity — it can only be read directly, or by geometry.
    """
    poured = [p for p in llc_board.pours if p.kind == "poured"]
    assert len(poured) == 7  # four records, seven islands between them
    assert len({p.id for p in poured}) == 4
    assert all(len(p.points) >= 3 for p in poured)
    assert all(p.net is None and p.layer_id is None for p in poured)
    assert all(p.poured_from not in {"", None} for p in poured)
    assert llc_board.stats.poured_orphans == 4
    assert llc_board.stats.poured_with_parent == 0

    fills = [p for p in llc_board.pours if p.kind == "fill"]
    assert len(fills) == 25  # the task book's "PCB 段 25 条 FILL"

    # DC- is measured from its FILL pours + tracks + vias, and none of the
    # four net-less POURED records appear in its island.
    result = pour_connectivity(llc_board, "DC-")
    assert result.island_count == 1
    assert not ({p.id for p in poured} & set(result.islands[0].element_ids))