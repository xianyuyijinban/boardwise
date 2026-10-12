"""Task 162a: the measurement library's correctness batch (161's G1-G5).

Five findings from the 161 audit, four of them silent-wrong-answer bugs in
``core/measure.py``. Each probe below is the one the audit reproduced, turned
into a regression: the value asserted is the **ground truth computed by hand**,
not the value the pre-162a code happened to return.

* **G1** — the clearance engine's coarse-reject box was the *centreline* box, so
  a pair whose copper touches was pruned away whenever some other pair set a
  better ``best`` first: ``net_clearance`` answered 12.0 for a pair at 0.0, and
  which answer came out depended on record order. Fixed by inflating the shape's
  box by its radius at construction (:class:`_Shape`), which restores the lower
  bound the prune needs. Pinned by the audit's own probe, by record-order
  invariance, and by a brute-force cross-check over randomised boards.
* **G2** — same root cause in ``pour_connectivity``: two touching 10-mil tracks
  of one net read as two islands. Pinned the same three ways.
* **G3** — ``vias_on_pad`` tested the via centre against the **axis-aligned box**
  of a rotated pad's corners, which is a superset of the pad, so a via in the
  empty corner around a 45° pad counted as 压焊盘. Fixed to true
  point-in-rotated-rectangle.
* **G4** — ``reference_layer_for``'s docstring advertised 向下优先 while the body
  picked the layer *above*; 162a kept the code (the 「downward」 reading names the
  far face of the board for an inner-layer trace) and corrected the prose.
  Pinned here as the physical property the primitive exists for.
* **G5** — ``_endpoint_key``'s tolerance was ``1e-6`` mil where its own docstring
  said a thousandth (``1e-3``), so a shared endpoint drifting 0.0004 mil landed
  in a different bucket and the fold vanished. Fixed to the documented grid.
"""

from __future__ import annotations

import random

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    Point,
    StackupEntry,
    TrackSegment,
    ViaGeometry,
)
from boardwise.core.measure import (
    _ENDPOINT_EPS_MIL,
    _capsule_distance,
    _endpoint_key,
    _net_shape_records,
    _net_shapes,
    _touching,
    _UnionFind,
    net_clearance,
    pour_connectivity,
    reference_layer_for,
    track_corner_angle,
    vias_on_pad,
)

# ---------------------------------------------------------------------------
# synthetic boards
# ---------------------------------------------------------------------------

_TWO_LAYER = {
    1: LayerInfo(1, "Top Layer", "TOP"),
    2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
}
_TWO_LAYER_STACKUP = [StackupEntry(1, 1000), StackupEntry(2, 9000)]

#: 毕设FOC 1.0.0's real stackup: ids 1 / 15 / 16 / 2 at z_index
#: 1000 / 1002 / 1004 / 9000, with Inner1 (15) the only **PLANE** copper layer.
#: The z_index magnitudes are read verbatim from the fixture; only the ordering
#: is meaningful (``StackupEntry``), which is why the direction test below is
#: about *order* and never about z arithmetic.
_FOUR_LAYER = {
    1: LayerInfo(1, "Top Layer", "TOP"),
    15: LayerInfo(15, "Inner1", "PLANE"),
    16: LayerInfo(16, "Inner2", "SIGNAL"),
    2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
}
_FOUR_LAYER_STACKUP = [
    StackupEntry(1, 1000),
    StackupEntry(15, 1002),
    StackupEntry(16, 1004),
    StackupEntry(2, 9000),
]


def _board(**kwargs) -> BoardGeometry:
    return BoardGeometry(
        layers=dict(_TWO_LAYER), stackup=list(_TWO_LAYER_STACKUP), **kwargs
    )


def _track(
    track_id: str, y: float, *, net: str, width: float, layer_id: int = 1, x1: float = 100.0
) -> TrackSegment:
    return TrackSegment(
        track_id, net=net, layer_id=layer_id, start=Point(0.0, y), end=Point(x1, y), width=width
    )


# ---------------------------------------------------------------------------
# G1: clearance must not prune a pair whose copper touches
# ---------------------------------------------------------------------------


def test_g1_wide_track_pruned_into_a_false_12_mil_clearance():
    """The audit's probe, hand-computed.

    ``a0`` (net A, y=0, width 16) has copper y in [-8, +8]; ``b1`` (net B,
    y=15, width 16) has copper y in [7, 23]. The two bodies overlap by 1 mil, so
    the true answer is distance 0 with ``overlapping`` True — and ``b0``
    (net B, y=20, width 0) sits 12 mil away, which is the *wrong* answer the
    pre-162a prune published: ``b0`` came first in the record order, set
    ``best = 12``, and ``b1``'s centreline box (15 mil away) was rejected by the
    coarse test even though its copper touches ``a0``.
    """
    board = _board(
        tracks=[
            _track("a0", 0, net="A", width=16),
            _track("b0", 20, net="B", width=0),
            _track("b1", 15, net="B", width=16),
        ]
    )
    result = net_clearance(board, "A", "B")
    assert result is not None
    assert result.distance == 0.0
    assert result.overlapping is True


def test_g1_the_answer_does_not_depend_on_record_order():
    """The same three tracks, ``b1`` before ``b0``: the same answer.

    Pre-162a this read 0.0 (``b1`` got in first and set ``best = 0``), so the
    *record order* decided whether the board reported a short — the摆动 the
    audit called out. A measurement whose result depends on which element the
    file happened to list first is not a measurement.
    """
    forward = _board(
        tracks=[
            _track("a0", 0, net="A", width=16),
            _track("b0", 20, net="B", width=0),
            _track("b1", 15, net="B", width=16),
        ]
    )
    reversed_ = _board(
        tracks=[
            _track("a0", 0, net="A", width=16),
            _track("b1", 15, net="B", width=16),
            _track("b0", 20, net="B", width=0),
        ]
    )
    first, second = net_clearance(forward, "A", "B"), net_clearance(reversed_, "A", "B")
    assert first is not None and second is not None
    assert (first.distance, first.overlapping) == (second.distance, second.overlapping)
    assert (first.distance, first.overlapping) == (0.0, True)
    assert (first.element_a, first.element_b) == (second.element_a, second.element_b)


def _brute_force_clearance(board: BoardGeometry, net_a: str, net_b: str) -> float | None:
    """The minimum over **every** pair, with no coarse reject anywhere.

    The prune is an optimisation, so the property that has to hold is exactly
    this: the pruned answer equals the exhaustive one. ``None`` mirrors
    ``net_clearance``'s unmeasurable-pair case (every pair came back ``inf``).
    """
    shapes_a = _net_shapes(board, board.net(net_a))
    shapes_b = _net_shapes(board, board.net(net_b))
    best = None
    for sa in shapes_a:
        for sb in shapes_b:
            distance = _capsule_distance(sa, sb, connectivity=False)
            if best is None or distance < best:
                best = distance
    return None if best is None or best == float("inf") else best


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
def test_g1_pruned_clearance_matches_the_exhaustive_pairwise_answer(seed):
    """Randomised two-net boards: the fast path may never disagree with the slow one.

    Tracks are drawn on a coarse grid with widths up to 20 mil, so a random
    board routinely puts a wide track near another net's copper — the geometry
    the pre-162a centreline box got wrong. The exhaustive minimum is recomputed
    from :func:`_capsule_distance` over all 49-odd pairs, which is the number the
    prune is supposed to be a shortcut for.
    """
    rng = random.Random(seed)
    tracks = []
    for i in range(7):
        for net in ("A", "B"):
            starting = rng.randrange(0, 60, 5)
            tracks.append(
                _track(
                    f"{net}{i}",
                    float(starting),
                    net=net,
                    width=float(rng.choice([0, 6, 16, 20])),
                    x1=float(rng.choice([50, 100])),
                )
            )
    board = _board(tracks=tracks)
    result = net_clearance(board, "A", "B")
    expected = _brute_force_clearance(board, "A", "B")
    if expected is None:
        assert result is None
        return
    assert result is not None
    assert result.distance == pytest.approx(expected, abs=1e-9)
    assert result.overlapping is (expected == 0.0)


# ---------------------------------------------------------------------------
# G2: pour connectivity must not reject touching copper
# ---------------------------------------------------------------------------


def test_g2_two_touching_tracks_of_one_net_are_one_island():
    """Two 10-mil-wide tracks at y=0 and y=10: 10 apart centre-to-centre,
    5 + 5 of half width, copper edge-to-edge 0. One island, not two.

    Pre-162a the centreline boxes were 10 mil apart, which the coarse reject
    read as proven separation — the same root cause as G1, and it reported the
    plane as split (a false 切断 in the FOC ground rule's report).
    """
    board = _board(
        tracks=[
            _track("t0", 0, net="GND", width=10),
            _track("t1", 10, net="GND", width=10),
        ]
    )
    assert pour_connectivity(board, "GND").island_count == 1


def test_g2_island_count_does_not_depend_on_record_order():
    forward = _board(
        tracks=[
            _track("t0", 0, net="GND", width=10),
            _track("t1", 10, net="GND", width=10),
            _track("t2", 40, net="GND", width=10),
        ]
    )
    reversed_ = _board(
        tracks=[
            _track("t2", 40, net="GND", width=10),
            _track("t0", 0, net="GND", width=10),
            _track("t1", 10, net="GND", width=10),
        ]
    )
    # y=0 and y=10 touch; y=40 (copper 35..45) is 25 mil clear of t1's copper
    # (5..15) — two islands either way.
    assert pour_connectivity(forward, "GND").island_count == 2
    assert pour_connectivity(reversed_, "GND").island_count == 2


def _brute_force_islands(board: BoardGeometry, net: str) -> int:
    """Island count with no coarse reject: every pair gets the exact touch test."""
    shapes = _net_shape_records(board, board.net(net), with_area=True)
    n = len(shapes)
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _touching(shapes[i][1], shapes[j][1]):
                uf.union(i, j)
    return len({uf.find(i) for i in range(n)})


@pytest.mark.parametrize("seed", [11, 12, 13, 14, 15, 16])
def test_g2_island_count_matches_the_exhaustive_touch_test(seed):
    rng = random.Random(seed)
    tracks = []
    for i in range(8):
        tracks.append(
            _track(
                f"t{i}",
                float(rng.randrange(0, 60, 5)),
                net="GND",
                width=float(rng.choice([4, 10, 16])),
                x1=float(rng.choice([50, 100])),
            )
        )
    board = _board(tracks=tracks)
    assert pour_connectivity(board, "GND").island_count == _brute_force_islands(board, "GND")


# ---------------------------------------------------------------------------
# G3: vias_on_pad on a rotated pad
# ---------------------------------------------------------------------------


def _via(via_id: str, x: float, y: float, *, net: str = "GND") -> ViaGeometry:
    return ViaGeometry(via_id, net=net, x=x, y=y, hole_diameter=4, via_diameter=10)


def test_g3_a_via_in_the_empty_corner_of_a_45_degree_pad_is_not_on_it():
    """The audit's probe, hand-computed.

    A 10 x 10 pad rotated 45° has its corners 7.071 mil from the centre
    (``5 * sqrt(2)``) along the axes and its edges 5 mil away along the
    diagonals. A via at (7, 7) is 9.899 mil from the centre — 2.8 mil of clear
    board outside the copper — but the pad's *axis-aligned box* reaches 7.071 on
    each axis, so the pre-162a test counted it. Reported as 「on the pad」, a
    thermal-pad rule would call the pad via-stitched by copper that is not on it.
    """
    pad = PadGeometry(
        "p1", component="U1", pin_number="1", net="GND", layer_id=1,
        x=0, y=0, width=10, height=10, shape="RECT", angle=45.0,
    )
    board = _board(vias=[_via("v1", 7, 7)])
    assert vias_on_pad(board, pad) == []


def test_g3_the_rotated_rectangle_is_the_boundary_that_counts():
    """Inside / on-edge / outside on the same 45° pad.

    The pad's own frame is what a via is tested against. Rotated 45°, the
    half-extents are 5 mil along each of the pad's edges: a via 3.535 mil out
    along both board axes is 5 mil out along the pad's edge and sits exactly on
    it (on-edge counts as on the pad — the 133a suite pins the inclusive
    boundary and this keeps it), a via at (4, 4) is 5.657 mil out along the pad
    edge and is outside, and one at the centre is inside.
    """
    pad = PadGeometry(
        "p1", component="U1", pin_number="1", net="GND", layer_id=1,
        x=0, y=0, width=10, height=10, shape="RECT", angle=45.0,
    )
    board = _board(
        vias=[
            _via("centre", 0.0, 0.0),
            _via("on-edge", 5.0 / (2**0.5), 5.0 / (2**0.5)),
            _via("outside", 4.0, 4.0),
        ]
    )
    assert [via.id for via in vias_on_pad(board, pad)] == ["centre", "on-edge"]


def test_g3_an_unrotated_pad_still_reads_its_own_half_widths_inclusively():
    """The 133a anchor, unchanged by the rotated-rectangle rewrite.

    A 100 x 60 pad at angle 0: a via at x=50 is exactly on the right edge and is
    found; one at x=80 is outside. This is the case the fix must not disturb,
    and it is asserted here as well as in ``test_133a_foc_primitives.py`` so a
    future rewrite of the containment test fails in this batch's file too.
    """
    pad = PadGeometry(
        "p1", component="U1", pin_number="1", net="GND", layer_id=1,
        x=0, y=0, width=100, height=60, shape="RECT", angle=0.0,
    )
    board = _board(vias=[_via("on", 10, 5), _via("edge", 50, 5), _via("outside", 80, 0)])
    assert [via.id for via in vias_on_pad(board, pad)] == ["on", "edge"]


# ---------------------------------------------------------------------------
# G4: the reference layer is the neighbour above, not the far face
# ---------------------------------------------------------------------------


def test_g4_an_inner_layer_references_the_plane_above_it_not_the_far_face():
    """The direction, stated as the property that motivated the primitive.

    毕设FOC's copper order (top first) is 1 / 15 / 16 / 2 with Inner1 (15) the
    PLANE layer. A trace on Inner2 (16) — 67 of the fixture's 726 — must
    reference **15**, the plane physically beside it, and never layer 2, the
    bottom face 8000 z-units away: that far-side answer is precisely the
    mis-projection ``_copper_layer_order`` exists to prevent. The 「向下优先」
    reading this docstring used to advertise gives exactly ``16 → 2``.
    """
    board = BoardGeometry(
        layers=dict(_FOUR_LAYER), stackup=list(_FOUR_LAYER_STACKUP)
    )
    assert reference_layer_for(board, 16) == 15
    assert reference_layer_for(board, 2) == 16  # the nearest copper, above it
    assert reference_layer_for(board, 1) == 15  # nothing above the top layer
    assert reference_layer_for(board, 15) == 1
    # No layer ever names the bottom face as the reference of an inner layer.
    assert reference_layer_for(board, 16) != 2


def test_g4_a_two_layer_board_is_direction_blind():
    """A top trace's only neighbour is the bottom layer, and vice versa.

    llc's control: with two copper layers the two readings of 「above」 and
    「below」 coincide, which is why 162a's decision could be made on the
    four-layer anchor alone without moving any two-layer expectation.
    """
    board = _board()
    assert reference_layer_for(board, 1) == 2
    assert reference_layer_for(board, 2) == 1


# ---------------------------------------------------------------------------
# G5: the endpoint tolerance is the thousandth of a mil the docstring claims
# ---------------------------------------------------------------------------


def test_g5_the_endpoint_grid_is_the_documented_thousandth_of_a_mil():
    """``1e-3`` mil, not the ``1e-6`` the signature carried.

    The constant is asserted by name so the next edit to the grid has to face
    this test, and the two keys it produces are the observable consequence:
    endpoints 0.0004 mil apart quantise to the same bucket, which is the whole
    point of the key.
    """
    assert _ENDPOINT_EPS_MIL == 1e-3
    assert _endpoint_key(Point(100.0, 0.0)) == _endpoint_key(Point(100.0004, 0.0))
    assert _endpoint_key(Point(100.0, 0.0)) == (100000, 0)


def test_g5_a_fold_whose_joint_drifted_by_a_thousandth_of_a_mil_is_reported():
    """The 漏报 the 1000× gap caused.

    Two segments meant to meet at (100, 0), one of them carrying a 0.0004 mil
    drift — 10 nm, a distance no drawing or editor acts on. Pre-162a the two
    joints landed in different buckets, the pair was never even considered, and
    a 90° bend vanished from the report. With the documented grid it is found,
    and the angle is 90 to within the drift itself: the key only *matches* the
    two endpoints, while the angle is computed from the real vertices, so a
    0.0004 mil offset shows up as 90.0002° rather than being rounded away.
    """
    board = _board(
        tracks=[
            _track("a", 0, net="SIG", width=6, x1=100.0),
            TrackSegment(
                "b", net="SIG", layer_id=1,
                start=Point(100.0004, 0.0), end=Point(100.0004, 100.0), width=6,
            ),
        ]
    )
    corners = track_corner_angle(board)
    assert [(c.track_a, c.track_b) for c in corners] == [("a", "b")]
    assert corners[0].angle_deg == pytest.approx(90.0, abs=1e-3)


def test_g5_genuinely_separate_endpoints_stay_separate():
    """The grid's other side: 2 mil apart is two endpoints, not one.

    Widening the tolerance to a thousandth of a mil must not start merging
    endpoints that are distinct copper — 2 mil is twenty times the board's own
    routing grid, and the two segments below are two tracks meeting nothing.
    """
    board = _board(
        tracks=[
            _track("a", 0, net="SIG", width=6, x1=100.0),
            TrackSegment(
                "b", net="SIG", layer_id=1,
                start=Point(102.0, 0.0), end=Point(102.0, 100.0), width=6,
            ),
        ]
    )
    assert track_corner_angle(board) == []
