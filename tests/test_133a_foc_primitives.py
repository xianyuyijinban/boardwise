"""Task 133a: the three FOC geometry primitives — ``via`` queries, ``track_corner_angle``
and ``return_path_projection``.

The FOC package's foundation stick, and **primitives only** — no rule lands here.
What the three have in common is the discipline 125a wrote into this module:
they produce numbers, and every threshold among them is a **geometric constant of
the measurement** rather than a verdict somebody would want to enforce.

Four groups:

* **一、``via_geometry`` queries** — ``via_layers`` (which copper layers a via's
  barrel reaches, which is a question the FOC package asks about every via on a
  board whose inner layers are 15 and 16), ``vias_in_region`` and
  ``vias_on_pad``. The trap is that the answer must come from the **physical**
  stackup, never from layer-id arithmetic.
* **二、``track_corner_angle``** — folds between same-net, same-layer segments.
  The angle is the **interior** one, which makes a straight continuation read
  180 and a classic 45° mitre read 135 — so the constant's own boundary is the
  case that decides whether the implementation is honest about it.
* **三、``return_path_projection``** — 岳 2026-10-08 裁定③: a multi-layer board's
  return path is analysed by projecting each trace onto its adjacent reference
  layer and reporting what ground copper covers it. Three coverage states, and
  **no verdict**: whether the reference layer *ought* to be a plane is the rule
  layer's call, so this module only says what is there.
* **四、the real anchors** — 毕设FOC 1.0.0 (four copper layers, physical order
  1 / 15 / 16 / 2) and llc (two), measured rather than quoted. The 1.0.0
  projection reading — **all 726 traces read ``none``**, because that board's
  planes are pour *regions* on the outer faces and its inner layers carry no
  ground pour at all — is the single most useful thing this suite pins, since
  it is the finding 133c's R5 has to start from.
"""

from __future__ import annotations

import math
import time
from collections import Counter
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
    OBTUSE_CORNER_DEG,
    reference_layer_for,
    return_path_projection,
    track_corner_angle,
    via_layers,
    vias_in_region,
    vias_on_pad,
)
from boardwise.parsers.epru import parse_epro2

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
LLC = FIXTURES / "llc_board.epro2"


# ---------------------------------------------------------------------------
# synthetic board helpers
# ---------------------------------------------------------------------------


#: The four copper layers of a 毕设FOC-shaped board, with the layer ids and
#: physical order the real fixture has. ``SIGNAL`` is the layer *type* that
#: :data:`COPPER_LAYER_TYPES` classifies as copper — spelling them ``INNER``
#: (which reads more naturally) makes ``is_copper`` false and silently drops the
#: layer from the stackup, which is a trap this suite states rather than hides.
_FOC_LAYERS: dict[int, LayerInfo] = {
    1: LayerInfo(1, "Top Layer", "TOP"),
    15: LayerInfo(15, "Inner1", "SIGNAL"),
    16: LayerInfo(16, "Inner2", "SIGNAL"),
    2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
}

#: Physical order by ``z_index`` — Top, Inner1, Inner2, Bottom. The **ids** run
#: 1 / 15 / 16 / 2, which is the whole reason a neighbour lookup cannot sort by id.
_FOC_STACKUP = [
    StackupEntry(1, 1000),
    StackupEntry(15, 1002),
    StackupEntry(16, 1004),
    StackupEntry(2, 9000),
]

_TWO_LAYER: dict[int, LayerInfo] = {
    1: LayerInfo(1, "Top Layer", "TOP"),
    2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
}

_TWO_LAYER_STACKUP = [StackupEntry(1, 4), StackupEntry(2, 6)]


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    return [Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)]


def _foc_board(**kwargs) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic", layers=dict(_FOC_LAYERS), stackup=list(_FOC_STACKUP), **kwargs
    )


def _track(
    track_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    net: str | None = "SIG",
    layer_id: int | None = 1,
    width: float = 10.0,
) -> TrackSegment:
    return TrackSegment(
        track_id, net=net, layer_id=layer_id, start=Point(*start), end=Point(*end), width=width
    )


def _chain(points, *, net: str | None = "SIG", layer_id: int | None = 1) -> BoardGeometry:
    """A board carrying one polyline's worth of collinear-endpoint segments."""
    return _foc_board(
        tracks=[
            _track(
                f"s{index}",
                points[index],
                points[index + 1],
                net=net,
                layer_id=layer_id,
            )
            for index in range(len(points) - 1)
        ]
    )


# ---------------------------------------------------------------------------
# 一、via_geometry queries
# ---------------------------------------------------------------------------


def test_via_layers_are_the_whole_stackup_minus_unused_inner_layers():
    """The barrel reading, on a board whose inner layers are ids 15 and 16.

    A through via reaches every copper layer. A via that states ``unused_inner_layers``
    does not, and the subtraction is the whole reading: 133d's thermal-via rule
    asks which layers a thermal via actually bridges, and answering 「all four」
    to a via that skips Inner1 would be the classic misreport.
    """
    through = ViaGeometry("v1", net="SIG", x=0, y=0, hole_diameter=20, via_diameter=50)
    assert via_layers(_foc_board(), through) == [1, 2, 15, 16]

    blind = ViaGeometry(
        "v2", net="SIG", x=0, y=0, hole_diameter=20, via_diameter=50, unused_inner_layers=[15, 16]
    )
    assert via_layers(_foc_board(), blind) == [1, 2]


def test_via_layers_on_a_two_layer_board_and_on_a_board_with_no_stackup():
    """Two layers is two layers, and an unclassifiable board says so.

    The empty answer for a board naming no copper layer is the module's
    「unclassifiable, never guessed」 discipline — not "the via reaches nothing".
    """
    via = ViaGeometry("v", net="SIG", x=0, y=0, hole_diameter=20, via_diameter=50)
    assert via_layers(BoardGeometry(source="syn", layers=dict(_TWO_LAYER)), via) == [1, 2]
    assert via_layers(BoardGeometry(source="syn"), via) == []


def test_vias_in_region_takes_the_whole_disc_and_is_net_blind():
    """The region test is the annulus, and it does not care which net.

    ``vias_in_region`` answers 「is there any via here」, which is what a rule
    asks *before* it knows the net. The half-width inflation is what makes a via
    whose centre is just outside the region but whose disc reaches into it count
    — the same test :func:`region_copper` uses, so the two cannot disagree.
    """
    board = _foc_board(
        vias=[
            ViaGeometry("inside", net="SIG", x=0, y=0, hole_diameter=20, via_diameter=50),
            # centre 30 mil out, disc radius 25: 5 mil of copper inside a box
            # ending at x=10
            ViaGeometry("straddle", net="PWR", x=30, y=0, hole_diameter=20, via_diameter=50),
            ViaGeometry("far", net="SIG", x=5000, y=5000, hole_diameter=20, via_diameter=50),
        ]
    )
    found = vias_in_region(board, BBox(-100, -100, 10, 100))
    assert [via.id for via in found] == ["inside", "straddle"]
    assert {via.id for via in vias_in_region(board, BBox(4990, 4990, 5010, 5010))} == {"far"}


def test_vias_on_pad_tests_the_centre_against_the_pad_corners():
    """Centred reading, on the pad's own bounding rectangle.

    The distinction from :func:`vias_in_region` is the point: this one asks
    「does this via land **on** the pad」, which is what 133d's R7 needs before it
    may call a thermal pad direct-connected. A pad rotated 90° is still tested
    through :func:`pad_corners`, so the rotation is honoured rather than
    approximated by the footprint's unrotated box.
    """
    pad = PadGeometry(
        "p1", component="U1", pin_number="1", net="GND", layer_id=1,
        x=0, y=0, width=100, height=60, shape="RECT", angle=0.0,
    )
    board = _foc_board(
        vias=[
            ViaGeometry("on", net="GND", x=10, y=5, hole_diameter=20, via_diameter=50),
            ViaGeometry("edge", net="GND", x=50, y=5, hole_diameter=20, via_diameter=50),
            ViaGeometry("outside", net="GND", x=80, y=0, hole_diameter=20, via_diameter=50),
        ]
    )
    assert [via.id for via in vias_on_pad(board, pad)] == ["on", "edge"]
    assert vias_on_pad(board, pad)[1].x == 50  # the pad's half-width, inclusive
    rotated = PadGeometry(
        "p2", component="U2", pin_number="1", net="GND", layer_id=1,
        x=0, y=0, width=100, height=60, shape="RECT", angle=90.0,
    )
    # A 90-degree rotation swaps the extents, so the same point now sits outside.
    assert [via.id for via in vias_on_pad(board, rotated)] == ["on"]


# ---------------------------------------------------------------------------
# 二、track_corner_angle
# ---------------------------------------------------------------------------


def test_a_right_angle_fold_is_reported_and_its_geometry_is_exact():
    """90 degrees out, at the joint, with both segments named.

    Hand-computable: the fold is ``(0,0) -> (100,0) -> (100,100)``, so the
    interior angle is exactly 90 and the reported position is the shared
    endpoint ``(100, 0)``. The two ids are sorted, so a pair read in either
    order is the same pair.
    """
    board = _chain([(0, 0), (100, 0), (100, 100)])
    corners = track_corner_angle(board)
    assert len(corners) == 1
    corner = corners[0]
    assert corner.angle_deg == pytest.approx(90.0)
    assert (corner.position.x, corner.position.y) == (100.0, 0.0)
    assert corner.net == "SIG" and corner.layer_id == 1
    assert (corner.track_a, corner.track_b) == ("s0", "s1")


def test_a_straight_continuation_is_not_a_corner():
    """180 degrees is outside the window by construction, not by a special case.

    The two segments are collinear, so the interior angle is 180 and nothing is
    reported. This is the case a separate 「is it collinear」 test would get
    wrong: it is the same comparison as every other fold.
    """
    assert track_corner_angle(_chain([(0, 0), (50, 0), (100, 0)])) == []
    # and the near-miss: 1e-12 out of line is still straight for any purpose a
    # reader could act on
    assert track_corner_angle(_chain([(0, 0), (100, 0), (200, 1e-12)])) == []


def test_the_classic_45_degree_mitre_is_the_135_boundary_and_stays_out():
    """The convention, stated as the case that decides it.

    A 45-degree mitre — the bend TI SLVA959B section 4 asks about — turns the
    *direction* of travel by 45, which is an **interior** angle of 135. The
    constant is 135 and the mitre therefore sits exactly on the boundary and is
    not reported, while a fold whose interior angle is genuinely below 135 is.
    Both halves are pinned: getting the angle convention backwards would report
    every 45 mitre on the board and miss every right-angle bend, which is the
    exact inversion of what the rule wants.
    """
    assert OBTUSE_CORNER_DEG == 135.0
    # interior 135: direction change of 45 -> not reported
    mitre = _chain([(0, 0), (100, 0), (100 + 100 * math.cos(math.radians(45)),
                                     100 * math.sin(math.radians(45)))])
    assert track_corner_angle(mitre) == []

    # interior 45: a sharp reverse, well inside the window -> reported
    sharp = _chain([(0, 0), (100, 0), (100 - 100 * math.cos(math.radians(45)),
                                      100 * math.sin(math.radians(45)))])
    assert [round(c.angle_deg, 6) for c in track_corner_angle(sharp)] == [45.0]

    # a gentle 139 interior (direction change of 41) is above the window
    gentle = _chain([(0, 0), (100, 0), (200, 100)])
    assert track_corner_angle(gentle) == []


def test_a_fold_is_only_a_fold_when_net_and_layer_both_agree():
    """Two crossings that are not bends, and the reason each is refused.

    Same-layer different-net is a DRC matter, not a bend; different-layer
    same-net is two independent routes crossing in plan view. Both are excluded
    because a corner is a property of **one continuous piece of copper**, and
    both exclusions are preconditions rather than filters applied afterwards.
    """
    crossing = BoardGeometry(
        source="syn",
        layers=dict(_FOC_LAYERS),
        stackup=list(_FOC_STACKUP),
        tracks=[
            _track("a", (0, 0), (100, 0), net="A"),
            _track("b", (100, 0), (100, 100), net="B"),
        ],
    )
    assert track_corner_angle(crossing) == []

    layered = BoardGeometry(
        source="syn",
        layers=dict(_FOC_LAYERS),
        stackup=list(_FOC_STACKUP),
        tracks=[
            _track("a", (0, 0), (100, 0), net="A", layer_id=1),
            _track("b", (100, 0), (100, 100), net="A", layer_id=15),
        ],
    )
    assert track_corner_angle(layered) == []


def test_a_pair_with_a_netless_segment_is_never_a_fold():
    """「The same net as what」 has no answer, so the pair is not reported.

    Reporting it would mean pairing copper with something whose net the file
    does not state, which is precisely the guess this module does not make
    elsewhere.
    """
    board = BoardGeometry(
        source="syn",
        layers=dict(_FOC_LAYERS),
        stackup=list(_FOC_STACKUP),
        tracks=[
            _track("a", (0, 0), (100, 0), net=None),
            _track("b", (100, 0), (100, 100), net="SIG"),
        ],
    )
    assert track_corner_angle(board) == []


def test_a_pair_sharing_both_endpoints_is_one_fold_not_two():
    """Two tracks meeting at both ends form a single fold.

    Deduplicated by the sorted id pair, so a hairpin loop contributes one entry
    and the count does not depend on which endpoint the bucketing happened to
    reach first.
    """
    board = _foc_board(
        tracks=[
            _track("a", (0, 0), (100, 0)),
            _track("b", (0, 0), (0, 100)),
        ]
    )
    corners = track_corner_angle(board)
    assert len(corners) == 1
    assert (corners[0].angle_deg, corners[0].track_a, corners[0].track_b) == (90.0, "a", "b")


def test_a_zero_length_segment_has_no_direction_and_no_angle():
    """A degenerate segment is skipped rather than given an invented heading.

    The angle is computed between two directions; a segment with no length has
    none, and reporting 0° for it would manufacture the sharpest corner on the
    board out of copper that is not there.
    """
    board = _foc_board(
        tracks=[
            _track("a", (0, 0), (100, 0)),
            _track("b", (100, 0), (100, 0)),  # zero length
            _track("c", (100, 0), (100, 100)),
        ]
    )
    corners = track_corner_angle(board)
    assert [(c.track_a, c.track_b) for c in corners] == [("a", "c")]


def test_net_filter_narrows_a_whole_board_sweep_and_absent_copper_is_empty():
    """``net=None`` is the whole board; an unknown name is an empty list."""
    board = BoardGeometry(
        source="syn",
        layers=dict(_FOC_LAYERS),
        stackup=list(_FOC_STACKUP),
        tracks=[
            _track("a", (0, 0), (100, 0), net="A"),
            _track("b", (100, 0), (100, 100), net="A"),
            _track("c", (500, 500), (600, 500), net="B"),
            _track("d", (600, 500), (600, 600), net="B"),
        ],
    )
    assert len(track_corner_angle(board)) == 2
    narrowed = track_corner_angle(board, "B")
    assert len(narrowed) == 1 and narrowed[0].net == "B"
    assert track_corner_angle(board, "NOPE") == []


# ---------------------------------------------------------------------------
# 三、return_path_projection
# ---------------------------------------------------------------------------


def test_reference_layer_is_the_physical_neighbour_not_the_nearest_id():
    """The anchor that makes the whole primitive correct.

    毕设FOC 1.0.0's copper layers carry ids 1 / 15 / 16 / 2 at ``z_index``
    1000 / 1002 / 1004 / 9000. A top-layer signal therefore has **Inner1 (15)**
    physically beneath it — which is why a return plane belongs there — while
    sorting by layer id would name layer 2 (the *bottom* face) and report a
    return plane on the far side of the board. The 向下优先 rule is visible in
    ``L16 -> 15``: Inner2's reference is the layer below it, not above it.
    """
    board = _foc_board()
    assert reference_layer_for(board, 1) == 15
    assert reference_layer_for(board, 15) == 1
    assert reference_layer_for(board, 16) == 15
    assert reference_layer_for(board, 2) == 16
    # A layer the stackup does not name, and a board with no copper at all, are
    # both 「no reference」 rather than a guess.
    assert reference_layer_for(board, 99) is None
    assert reference_layer_for(board, None) is None


def test_reference_layer_on_a_two_layer_board_falls_through_to_above():
    """llc's control: a top-layer signal has nothing below, so it references the bottom.

    向下优先 with no 下 to prefer is 向上 — the bottom layer is the only
    reference a two-layer board offers a top-layer trace, which is exactly the
    degenerate case the four-layer board never exercises.
    """
    board = BoardGeometry(source="syn", layers=dict(_TWO_LAYER), stackup=list(_TWO_LAYER_STACKUP))
    assert reference_layer_for(board, 1) == 2
    assert reference_layer_for(board, 2) == 1


def _project_one(pours, *, track=None):
    """Project a single top-layer trace over ``pours`` and return its row."""
    board = _foc_board(
        tracks=[track if track is not None else _track("t1", (0, 0), (1000, 0))],
        pours=pours,
    )
    return return_path_projection(board, "SIG").rows[0]


def test_a_ground_plane_under_the_footprint_reads_covered():
    """The full-coverage case, with the corner mask as its evidence.

    The pour on Inner1 spans the whole trace, so all four corners of the
    width-inflated footprint are inside it. The mask is published rather than
    only the word, so a reader can check the measurement instead of trusting it.
    """
    row = _project_one([PourShape(id="p1", net="GND", layer_id=15, kind="pour",
                                   points=_rect(-100, -100, 2000, 2000))])
    assert row.cover_status == "covered"
    assert row.corner_cover_mask == [True] * 4
    assert row.ground_items == ["p1"]
    assert row.ground_pour_count == 1
    assert row.reference_layer_id == 15 and row.layer_id == 1


def test_a_plane_that_stops_short_reads_partial_and_names_the_missing_corners():
    """The fragmenting case 裁定③ exists to surface.

    The pour reaches x=500 while the trace runs to x=1000, so the two right-hand
    corners are over air. ``partial`` is the measurement; whether a partial
    return path is acceptable is 133c's R5 to decide, and nothing here says it is
    a defect.
    """
    row = _project_one([PourShape(id="p1", net="GND", layer_id=15, kind="pour",
                                   points=_rect(-100, -100, 500, 2000))])
    assert row.cover_status == "partial"
    assert row.corner_cover_mask == [True, False, False, True]
    assert row.ground_items == ["p1"]


def test_no_ground_copper_under_the_footprint_reads_none():
    """The empty case, and the three ways a board can produce it.

    A non-ground net (a +24V plane is not a return path), copper on the wrong
    layer, and a pour with no net are all 「no ground here」 — and the last two
    are named because they are the mistakes a reader would otherwise suspect the
    primitive of making.
    """
    assert _project_one([PourShape(id="p1", net="+24V", layer_id=15, kind="pour",
                                    points=_rect(-100, -100, 2000, 2000))]).cover_status == "none"
    assert _project_one([PourShape(id="p1", net="GND", layer_id=16, kind="pour",
                                    points=_rect(-100, -100, 2000, 2000))]).cover_status == "none"
    assert _project_one([PourShape(id="p1", net=None, layer_id=15, kind="pour",
                                    points=_rect(-100, -100, 2000, 2000))]).cover_status == "none"
    assert _project_one([]).cover_status == "none"


def test_a_poured_result_is_not_counted_as_a_plane():
    """125b's decision holds here too: ``poured`` carries no polygon.

    The parser leaves a ``POURED`` record's points empty on purpose, so it can
    never be the copper this primitive reads. A plane exists only as its region.
    """
    row = _project_one([PourShape(id="p1", net="GND", layer_id=15, kind="poured", points=[])])
    assert row.cover_status == "none" and row.ground_pour_count == 0


def test_the_projected_footprint_is_the_trace_inflated_by_half_its_width():
    """A projection keeps its coordinates and the footprint respects the width.

    The return current runs under the **copper**, not under the centreline, so
    the region asked about is the segment grown by half its width — and
    ``projected`` itself is the unchanged geometry, which is what makes the row
    checkable against the board by hand.
    """
    row = _project_one(
        [], track=_track("t1", (0, 0), (1000, 0), width=40.0)
    )
    assert row.projected == [Point(0, 0), Point(1000, 0)]
    # A plane that covers the centreline but not the copper's edge reads partial.
    row = _project_one(
        [PourShape(id="p1", net="GND", layer_id=15, kind="pour",
                   points=_rect(-100, -100, 500, 2000))],
        track=_track("t1", (0, 0), (1000, 0), width=40.0),
    )
    assert row.cover_status == "partial"


def test_a_layer_with_no_neighbour_says_no_reference_layer_rather_than_guessing():
    """The stackup fact, reported as a stackup fact.

    A one-copper-layer board has nothing to project onto. That is not a
    coverage failure and must not be reported as one, which is why it has its
    own status instead of falling through to ``none``.
    """
    board = BoardGeometry(
        source="syn",
        layers={1: LayerInfo(1, "Top Layer", "TOP")},
        stackup=[StackupEntry(1, 1000)],
        tracks=[_track("t1", (0, 0), (1000, 0))],
    )
    row = return_path_projection(board, "SIG").rows[0]
    assert row.cover_status == "no_reference_layer"
    assert row.reference_layer_id is None and row.corner_cover_mask == []


def test_the_report_summarises_counts_and_says_no_single_reference_for_a_board_sweep():
    """A whole-board sweep spans layers, so it has no one reference layer.

    Naming one would be picking a layer arbitrarily for traces that never run on
    it. The counts, by contrast, are the summary a rule prints.
    """
    board = BoardGeometry(
        source="syn",
        layers=dict(_FOC_LAYERS),
        stackup=list(_FOC_STACKUP),
        tracks=[
            _track("a", (0, 0), (1000, 0), layer_id=1),
            _track("b", (0, 0), (1000, 0), layer_id=2),
        ],
        pours=[PourShape(id="p1", net="GND", layer_id=15, kind="pour",
                         points=_rect(-100, -100, 2000, 2000))],
    )
    report = return_path_projection(board)
    assert report.reference_layer_id is None
    assert report.row_count == 2
    assert sum(report.cover_counts.values()) == 2
    assert {row.reference_layer_id for row in report.rows} == {15, 16}
    # and naming a layer explicitly does resolve one
    assert return_path_projection(board, layer=1).reference_layer_id == 15


def test_absent_copper_yields_an_empty_report():
    """An unknown net is an empty report, not an exception."""
    board = _foc_board(tracks=[_track("t1", (0, 0), (1000, 0))])
    report = return_path_projection(board, "NOPE")
    assert report.rows == [] and report.row_count == 0 and report.cover_counts == {}


# ---------------------------------------------------------------------------
# 四、real-fixture anchors
# ---------------------------------------------------------------------------


def test_foc_100_four_layer_stackup_and_the_three_adjacencies():
    """The physical order, read off the fixture rather than assumed.

    This is the anchor the whole primitive rests on: a reader who sees ids
    1 / 2 / 15 / 16 sorted would conclude the reference layers were nonsense.
    """
    board = parse_epro2(FOC_100)
    assert [info.layer_id for info in read_stackup_copper(board)] == [1, 2, 15, 16]
    assert reference_layer_for(board, 1) == 15
    assert reference_layer_for(board, 16) == 15
    assert reference_layer_for(board, 2) == 16


def read_stackup_copper(board):
    from boardwise.core.measure import read_stackup

    return read_stackup(board).copper_layers


def test_foc_100_every_trace_projects_onto_an_inner_layer_and_none_is_covered():
    """The measured 1.0.0 projection: **726 rows, every one ``none``**.

    毕设FOC 1.0.0 routes its signals on the outer faces (all 726 tracks are on
    layer 1 or 2) and stores its planes as pour **regions on those same outer
    faces** — 27 ``POUR`` records, all of them layer 1 or 2. So a top-layer trace
    projects onto Inner1 (15) and a bottom-layer one onto Inner2 (16), and
    neither inner layer carries any pour at all. All 726 rows read ``none``.

    That is the finding, and it is exactly what 133c's R5 needs as its starting
    point: on this board there is **no** plane under any signal route, by the
    project's own storage of it. The number is pinned because a later batch that
    teaches the parser to read poured results would move it, and that move
    would be a correction worth seeing rather than discovering.
    """
    board = parse_epro2(FOC_100)
    assert len(board.tracks) == 726
    assert {track.layer_id for track in board.tracks} == {1, 2}
    # the planes are on the outer faces, which is why the inner ones are empty
    assert {pour.layer_id for pour in board.pours if pour.kind == "pour"} == {1, 2}

    report = return_path_projection(board)
    assert report.row_count == 726
    assert report.cover_counts == {"none": 726}
    assert report.reference_layer_id is None
    assert {row.reference_layer_id for row in report.rows} == {15, 16}


def test_foc_100_corner_inventory_is_64_folds_of_which_34_are_right_angles():
    """The measured 1.0.0 corner list.

    64 folds survive the 135-degree window, and the dominant class is the
    interior-90 right-angle bend TI section 4 asks about — 34 of them, plus 19
    sharp 45-degree interior folds. The count is pinned with its composition
    because both halves can move for reasons that matter: a parser change that
    shifts endpoint coordinates would change how many pairs even meet, and the
    135 boundary guard is what keeps the 148 folds the editor drew at *exactly*
    135 out of the list (they come back as ``134.99999999999955``).
    """
    board = parse_epro2(FOC_100)
    corners = track_corner_angle(board)
    assert len(corners) == 64
    rounded = Counter(round(corner.angle_deg, 3) for corner in corners)
    assert rounded[90.0] == 34
    assert rounded[45.0] == 19
    assert all(corner.angle_deg < OBTUSE_CORNER_DEG - 1e-9 for corner in corners)
    assert all(corner.net for corner in corners)
    assert {corner.layer_id for corner in corners} == {1, 2}


def test_llc_is_the_two_layer_control_for_both_primitives():
    """llc: two copper layers, and its own measured numbers.

    A top-layer trace references the bottom layer — 向下优先 with nothing below
    to prefer — and the board carries no ``POUR`` record, so its ground copper is
    carried by ``fill`` polygons. All 49 traces read ``none`` here for the same
    structural reason as on 1.0.0, which is the control: a board that stores its
    copper a different way (131f's ``fill`` instead of ``POUR``) produces the
    same reading through the same path, so the primitive is not keyed to one
    board's storage convention.
    """
    board = parse_epro2(LLC)
    assert reference_layer_for(board, 1) == 2
    assert not [pour for pour in board.pours if pour.kind == "pour"]

    report = return_path_projection(board)
    assert report.row_count == 49
    assert report.cover_counts == {"none": 49}
    assert {row.reference_layer_id for row in report.rows} == {2, 1}

    corners = track_corner_angle(board)
    assert corners, "llc routes bends, so the primitive reports some"
    assert all(corner.angle_deg < OBTUSE_CORNER_DEG - 1e-9 for corner in corners)


def test_foc_100_vias_all_span_the_whole_stackup():
    """244 vias, every one reaching all four copper layers.

    No via on this board states ``unused_inner_layers``, so the subtraction in
    :func:`via_layers` is a no-op here — pinned because that is a property of
    *this* board, not of the function, and a later fixture with a blind via would
    be the first case where it does something.
    """
    board = parse_epro2(FOC_100)
    assert len(board.vias) == 244
    assert all(not via.unused_inner_layers for via in board.vias)
    assert {tuple(via_layers(board, via)) for via in board.vias} == {(1, 2, 15, 16)}


# ---------------------------------------------------------------------------
# performance pins
# ---------------------------------------------------------------------------


def test_a_whole_board_projection_of_the_four_layer_fixture_stays_under_two_seconds():
    """The performance pin the task book sets: full-board projection < 2 s.

    The cost that matters is 726 rows each asking what copper is in a small
    footprint, which naively is 726 full-board walks. The ground inventory is
    built once per layer and each row is answered against it, so the sweep is
    linear in the board rather than quadratic in it. Measured at ~4 ms, which
    leaves the 2 s bound three orders of magnitude of headroom for the boards
    that do carry inner-layer planes.
    """
    board = parse_epro2(FOC_100)
    start = time.perf_counter()
    report = return_path_projection(board)
    elapsed = time.perf_counter() - start
    assert report.row_count == 726
    assert elapsed < 2.0, f"whole-board projection took {elapsed:.3f}s"


def test_a_whole_board_corner_sweep_is_millisecond_scale():
    """The other performance claim: 726 tracks indexed, not pairwise-compared.

    Quadratic pairing over 726 tracks would be ~260k pair tests; the endpoint
    index makes it linear, and the whole-board sweep runs in a couple of
    milliseconds. The bound is loose on purpose — it is there to catch a
    regression to pairwise pairing, not to measure the machine.
    """
    board = parse_epro2(FOC_100)
    start = time.perf_counter()
    corners = track_corner_angle(board)
    elapsed = time.perf_counter() - start
    assert len(corners) == 64
    assert elapsed < 1.0, f"corner sweep took {elapsed:.3f}s"