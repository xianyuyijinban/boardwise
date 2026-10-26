"""Issue #88A: the clearance engine ignored ``PourShape.rings``.

``PourShape`` has carried two views of a pour since R2-1: :attr:`~boardwise.
core.geometry.PourShape.points` (the first ring's vertices, arcs left as
**chords**) and :attr:`~boardwise.core.geometry.PourShape.rings` (``[outline,
void, void, ...]`` with every ``ARC`` expanded, i.e. where the copper actually
is). ``measure.py`` built every pour ``_Shape`` from ``points`` alone, so:

* a pour whose outline bulges outward between arc endpoints was measured at
  its **chords** — the copper was reported further away than it is, and its
  coarse-reject box was too small, so a body that really sits in the bulge was
  pruned away and called a separate island;
* the clearance voids were invisible, so **every** foreign body inside the
  outer outline read as 「inside solid copper, unmeasurable」 (``math.inf`` →
  ``net_clearance`` answered ``None``) even when the body sits in a void whose
  edge is a measurable distance away;
* the same blindness on the connectivity side fused a same-net body sitting in
  a void to the pour it is 8 mil clear of.

The fix is consumption only — ``_Shape`` gains a ``rings`` view, the pour
constructor passes ``pour.rings or [pour.points]`` (the explicit fallback for
``POLY`` / ``POUR`` / KiCad shapes that carry no rings), ``bbox`` is the union
of every ring's box inflated by the radius, solid containment means 「inside
``rings[0]`` and inside no void」, and edge-to-edge distance walks every ring.
``points``, ``radius``, ``layers``, ``component``, the area and the element
labels are untouched — this file pins that too.

Every expectation is hand-computed and written next to the assertion. The
tests go through the real consumer path (``PourShape`` → board →
:func:`~boardwise.core.measure._net_shape_records` → :func:`~boardwise.core.
measure._capsule_distance`), so the unmodified code fails on **assertions**
(20 instead of 10, ``None`` instead of 8, a false island merge), never on a
``TypeError`` for an argument ``_Shape`` does not yet take.

Groups:

1. the outline bulges past the chords: distance, bbox, and the island the
   coarse reject used to prune;
2. a foreign body inside a void is measurable to the void edge;
3. a same-net body inside a void is not fused, while real solid containment
   keeps issue #83's ``True→0`` / ``False→inf``;
4. ``rings == []`` (``POLY`` / ``POUR`` / KiCad) falls back to ``points``,
   a real touch stays 0, and nothing crosses layers;
5. the other side is a pour too: its ``rings`` drive containment and edge
   distance, while area and label keep the ``points`` reading;
6. (added by #88D) a stitching **via fence** in the bulge: the rings fuse it,
   the chords split it, and a via that sits in the ring's *void* proves the
   merge is the exact containment test rather than box overlap.
"""

from __future__ import annotations

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
    _net_shapes,
    net_clearance,
    pour_connectivity,
)

#: The chord view of the pour outline: a 10 x 10 square. ``points`` is always
#: this, in every test below, so an assertion that moves is an assertion about
#: ``rings``.
_CHORD_SQUARE = [Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)]

#: ``rings[0]``: the same outline with its right side bulging out to
#: ``(20, 5)`` — an arc from ``(10, 0)`` to ``(10, 10)``, sagitta 10, i.e.
#: radius 6.25. Shoelace area 150 sq mil against the chord square's 100.
_BULGED_RING = [Point(0, 0), Point(10, 0), Point(20, 5), Point(10, 10), Point(0, 10)]

#: A 100 x 100 pour with one void, ``[outline, void]``. The void is the
#: 20 x 20 square ``(40, 40) .. (60, 60)``.
_BIG_OUTER = [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)]
_BIG_VOID = [Point(40, 40), Point(60, 40), Point(60, 60), Point(40, 60)]


def _two_layer() -> tuple[dict[int, LayerInfo], list[StackupEntry]]:
    return (
        {1: LayerInfo(1, "Top Layer", "TOP"), 2: LayerInfo(2, "Bottom Layer", "BOTTOM")},
        [
            StackupEntry(1, 1000, "外层铜厚", 1.378),
            StackupEntry(2, 9000, "外层铜厚", 1.378),
        ],
    )


def _board(*, pours=(), tracks=(), pads=(), vias=()) -> BoardGeometry:
    layers, stackup = _two_layer()
    return BoardGeometry(
        source="synthetic",
        layers=layers,
        stackup=stackup,
        pours=list(pours),
        tracks=list(tracks),
        pads=list(pads),
        vias=list(vias),
    )


def _pour(
    pour_id: str,
    net: str,
    *,
    points=_CHORD_SQUARE,
    rings=None,
    kind: str = "fill",
    layer_id: int = 1,
) -> PourShape:
    """A pour whose ``points`` are the chord square and whose ``rings``, when
    given, are the copper-presence view. ``rings=[]`` is the parser's answer
    for ``POLY`` / ``POUR`` / a hand-built (KiCad-shaped) record."""
    return PourShape(
        id=pour_id,
        net=net,
        layer_id=layer_id,
        kind=kind,
        points=list(points),
        rings=[list(ring) for ring in (rings or [])],
    )


def _track(track_id: str, net: str, start, end, *, width: float = 0.0, layer_id: int = 1):
    return TrackSegment(
        track_id, net=net, layer_id=layer_id, start=Point(*start), end=Point(*end), width=width
    )


def _pad(pad_id: str, net: str, x: float, y: float, size: float = 4.0) -> PadGeometry:
    return PadGeometry(
        pad_id,
        component="U1",
        pin_number="1",
        net=net,
        footprint_layer_id=1,
        x=x,
        y=y,
        width=size,
        height=size,
        shape="RECT",
    )


def _via(
    via_id: str, net: str, x: float, y: float, *, hole: float = 2.0, diameter: float = 4.0
) -> ViaGeometry:
    """A via on both copper layers of the two-layer stackup, ``diameter`` mil wide."""
    return ViaGeometry(id=via_id, net=net, x=x, y=y, hole_diameter=hole, via_diameter=diameter)


def _pour_shape(board: BoardGeometry, net: str):
    """The single pour ``_Shape`` of one net, looked up the way the consumers do."""
    shapes = [shape for shape in _net_shapes(board, board.net(net)) if shape.is_pour]
    assert len(shapes) == 1, f"expected exactly one pour on {net}, got {len(shapes)}"
    return shapes[0]


# ---------------------------------------------------------------------------
# 1. the outline bulges past the chords
# ---------------------------------------------------------------------------


def test_88a_distance_is_measured_on_the_outer_ring_not_the_chords():
    """A zero-width track at ``y = 5``, ``x`` in ``[30, 40]``.

    ``rings[0]``'s apex is ``(20, 5)``, so the copper gap is
    ``30 - 20 = 10.0``. The chord view's nearest edge is the square's right
    side ``x = 10``, which would say ``30 - 10 = 20.0`` — the number the
    unmodified engine published. The control board below is the same geometry
    with ``rings=[]`` and must keep saying 20.0, so the delta is provably the
    rings and not a change in the chord path.
    """
    board = _board(
        pours=[_pour("p1", "GND", rings=[_BULGED_RING])],
        tracks=[_track("t1", "HV", (30, 5), (40, 5))],
    )
    result = net_clearance(board, "GND", "HV")
    assert result is not None
    assert result.distance == pytest.approx(10.0)
    assert result.shared_layer_ids == [1]
    assert result.overlapping is False

    chord_only = _board(
        pours=[_pour("p1", "GND", rings=[])],
        tracks=[_track("t1", "HV", (30, 5), (40, 5))],
    )
    control = net_clearance(chord_only, "GND", "HV")
    assert control is not None
    assert control.distance == pytest.approx(20.0)


def test_88a_pour_bbox_is_the_union_of_every_ring():
    """The coarse-reject box must cover the bulge, or a body in it is pruned.

    ``rings[0]`` reaches ``x = 20`` (``points`` stops at 10); the void ring of
    a different pour sits inside the outer and cannot shrink the union. This is
    the box :func:`_best_pair` and :func:`pour_connectivity` compare, and a box
    built from ``points`` is a *wrong* lower bound here — it rejects pairs whose
    copper overlaps.
    """
    board = _board(pours=[_pour("p1", "GND", rings=[_BULGED_RING])])
    box = _pour_shape(board, "GND").bbox
    assert box is not None
    assert (box.min_x, box.min_y, box.max_x, box.max_y) == (0.0, 0.0, 20.0, 10.0)

    voided = _board(pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])])
    voided_box = _pour_shape(voided, "GND").bbox
    assert voided_box is not None
    assert (voided_box.min_x, voided_box.min_y, voided_box.max_x, voided_box.max_y) == (
        0.0,
        0.0,
        100.0,
        100.0,
    )

    chord_only = _board(pours=[_pour("p1", "GND", rings=[])])
    chord_box = _pour_shape(chord_only, "GND").bbox
    assert chord_box is not None and chord_box.max_x == pytest.approx(10.0)


def test_88a_a_body_in_the_bulge_is_one_island_with_the_pour():
    """A same-net track wholly inside the bulge: contained, not pruned.

    ``(17, 5)`` is inside ``rings[0]`` (below the edge ``(10, 0)-(20, 5)``,
    above ``(20, 5)-(10, 10)``) and outside the chord square (``x > 10``).
    The rings box reaches it, so the exact test runs and reads containment
    (0.0, one island); with the chord box the pair is rejected at
    ``17 - 10 = 7`` mil and the track becomes a second island.
    """
    board = _board(
        pours=[_pour("p1", "GND", rings=[_BULGED_RING])],
        tracks=[_track("t1", "GND", (17, 5), (17.5, 5))],
    )
    connectivity = pour_connectivity(board, "GND")
    assert connectivity.island_count == 1
    assert connectivity.islands[0].element_ids == ["t1", "p1"]

    chord_only = _board(
        pours=[_pour("p1", "GND", rings=[])],
        tracks=[_track("t1", "GND", (17, 5), (17.5, 5))],
    )
    assert pour_connectivity(chord_only, "GND").island_count == 2


# ---------------------------------------------------------------------------
# 2. a foreign body inside a void is measurable
# ---------------------------------------------------------------------------


def test_88a_foreign_body_inside_a_void_measures_to_the_void_edge():
    """A 4 x 4 ``SIG`` pad centred in the 20 x 20 void: 8 mil on every side.

    The pad's corners are ``(48, 48) .. (52, 52)``; the void's edges are
    ``x = 40 / 60`` and ``y = 40 / 60``, so ``48 - 40 = 8.0`` is the gap. The
    pad is inside the outer outline (so the old engine called it 「inside solid
    copper」 and returned ``inf``, dropping the net pair entirely) but inside
    the void, which is not copper: it is an ordinary measurable pair, and the
    tox implementation must read 8.0 rather than ``None``.
    """
    board = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])],
        pads=[_pad("pad1", "SIG", 50, 50)],
    )
    result = net_clearance(board, "GND", "SIG")
    assert result is not None
    assert result.distance == pytest.approx(8.0)
    assert result.overlapping is False
    assert result.shared_layer_ids == [1]

    # With no rings the void is invisible and #83's documented blind spot
    # returns: the same pad is 「inside the outline」 and unmeasurable.
    chord_only = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[])],
        pads=[_pad("pad1", "SIG", 50, 50)],
    )
    assert net_clearance(chord_only, "GND", "SIG") is None


# ---------------------------------------------------------------------------
# 3. same-net body in a void; solid containment unchanged
# ---------------------------------------------------------------------------


def test_88a_same_net_body_inside_a_void_is_not_fused():
    """A ``GND`` pad in the ``GND`` pour's void is 8 mil clear of the copper.

    The pad sits where the pour engine cut copper away, so it is **not** one
    piece of copper with the pour: two islands, pad first by flat record order.
    Pre-fix its corner was 「in the outer polygon」, ``connectivity=True``
    answered 0.0 and the pad was silently welded to a pour it is 8 mil from.
    """
    board = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])],
        pads=[_pad("pad1", "GND", 50, 50)],
    )
    connectivity = pour_connectivity(board, "GND")
    assert connectivity.island_count == 2
    assert [island.element_ids for island in connectivity.islands] == [["U1.1"], ["p1"]]


def test_88a_solid_containment_keeps_issue_83_semantics():
    """The over-fixing guard: copper in the **solid** part is still one piece.

    ``U1.1`` (``GND``) is a 4 x 4 pad at ``(10, 10)``, inside the outer
    outline and outside the void, so the pour's solid copper contains it:
    ``connectivity=True`` → one island. A foreign ``SIG`` pad at ``(20, 20)``
    is equally inside the solid, so ``connectivity=False`` is ``inf`` and
    :func:`net_clearance` answers ``None`` — issue #83's blind spot, kept.
    """
    board = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])],
        pads=[_pad("pad1", "GND", 10, 10)],
    )
    connectivity = pour_connectivity(board, "GND")
    assert connectivity.island_count == 1
    assert connectivity.islands[0].element_ids == ["U1.1", "p1"]

    # A foreign pad in the same solid copper: no measurable pair, so the net
    # pair drops out (the blind spot #83 documented, unchanged by #88A).
    foreign = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])],
        pads=[_pad("pad2", "SIG", 20, 20)],
    )
    assert net_clearance(foreign, "GND", "SIG") is None


# ---------------------------------------------------------------------------
# 4. no rings, a real touch, and layers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fill", "poly", "pour", "poured"])
def test_88a_a_pour_without_rings_falls_back_to_points(kind):
    """``rings == []`` is every ``POLY`` / ``POUR`` record and any hand-built
    (KiCad-shaped) pour: the ``points`` outline is the only view there is, so
    the old reading must be exactly preserved — 20 mil here, box at ``x = 10``.
    """
    board = _board(
        pours=[_pour("p1", "GND", rings=[], kind=kind)],
        tracks=[_track("t1", "HV", (30, 5), (40, 5))],
    )
    result = net_clearance(board, "GND", "HV")
    assert result is not None
    assert result.distance == pytest.approx(20.0)
    box = _pour_shape(board, "GND").bbox
    assert box is not None and box.max_x == pytest.approx(10.0)


def test_88a_a_real_touch_is_still_zero_with_and_without_rings():
    """Both views must still call copper that meets copper 0.0.

    * with the bulged ring: a 10-mil-wide track whose left copper edge is at
      ``x = 20`` meets the ring's apex ``(20, 5)`` exactly;
    * without rings: the chord square's corner ``(10, 0)`` meets the 10-mil
      track's left copper edge at ``x = 10`` (issue #83's own probe).

    A fix that made containment honest by never reading a touch as 0 would
    fail here.
    """
    ringed = _board(
        pours=[_pour("p1", "GND", rings=[_BULGED_RING])],
        tracks=[_track("t1", "GND", (25, 5), (35, 5), width=10)],
    )
    ringed_conn = pour_connectivity(ringed, "GND")
    assert ringed_conn.island_count == 1
    assert ringed_conn.islands[0].element_ids == ["t1", "p1"]

    chorded = _board(
        pours=[_pour("p1", "GND", rings=[])],
        tracks=[_track("t1", "GND", (15, 0), (25, 0), width=10)],
    )
    assert pour_connectivity(chorded, "GND").island_count == 1


def test_88a_rings_do_not_reach_across_layers():
    """A body in the bulge on **another** layer shares no copper.

    The track's plan-view position is inside ``rings[0]``, which is exactly the
    geometry that must not become a connection: the pour is layer 1, the track
    layer 2, so two islands. For a foreign net the projection is still
    measurable (10.0) but ``overlapping`` is False and no layer is shared —
    and ``same_layer_only=True`` has no pair at all, so it must stay ``None``
    rather than inherit a cross-layer zero.
    """
    same_net = _board(
        pours=[_pour("p1", "GND", rings=[_BULGED_RING])],
        tracks=[_track("t1", "GND", (17, 5), (17.5, 5), layer_id=2)],
    )
    assert pour_connectivity(same_net, "GND").island_count == 2

    foreign = _board(
        pours=[_pour("p1", "GND", rings=[_BULGED_RING])],
        tracks=[_track("t1", "HV", (30, 5), (40, 5), layer_id=2)],
    )
    result = net_clearance(foreign, "GND", "HV")
    assert result is not None
    assert result.distance == pytest.approx(10.0)
    assert result.overlapping is False
    assert result.shared_layer_ids == []
    assert net_clearance(foreign, "GND", "HV", same_layer_only=True) is None


# ---------------------------------------------------------------------------
# 5. the other side is a pour too; area and label unchanged
# ---------------------------------------------------------------------------


def test_88a_the_other_side_pour_is_measured_on_its_rings_too():
    """Two bulged pours: ``(20, 5)`` against ``(25, 5)`` is 5 mil of air.

    The left pour is the usual one. The right pour's ``points`` are the chord
    square ``x in [30, 40]`` but its ``rings[0]`` bulges left to ``(25, 5)``
    — an arc collapsed to its chord. With both chord views the answer is
    ``30 - 10 = 20.0``; reading only one side's rings gives 10 or 15; the
    correct reading of two rings is ``25 - 20 = 5.0``, in either argument
    order and under both caller intents (the pours do not contain each other).
    """
    right_ring = [Point(30, 0), Point(40, 0), Point(40, 10), Point(30, 10), Point(25, 5)]
    board = _board(
        pours=[
            _pour("p1", "GND", rings=[_BULGED_RING]),
            _pour(
                "p2",
                "HV",
                points=[Point(30, 0), Point(40, 0), Point(40, 10), Point(30, 10)],
                rings=[right_ring],
            ),
        ]
    )
    forward = net_clearance(board, "GND", "HV")
    assert forward is not None
    assert forward.distance == pytest.approx(5.0)
    backward = net_clearance(board, "HV", "GND")
    assert backward is not None
    assert backward.distance == pytest.approx(5.0)


def test_88a_the_other_side_pour_containment_reads_its_rings():
    """Containment is judged from the other pour's **rings**, not its chords.

    ``p1`` is the solid 100 x 100 square. ``p2``'s chord square is
    ``x in [120, 140]`` (20 mil clear of ``p1``), but its ``rings[0]`` carries
    the left-side arc that pokes into ``p1`` at ``(50, 90)``. That ring vertex
    is inside ``p1``'s solid copper, so the pair is issue #83's documented
    「one pour's body inside another's outline」: ``connectivity=True`` → 0.0
    (one piece of copper), ``connectivity=False`` → ``inf`` (unmeasurable, not
    a manufactured short). The ring-less control keeps the old 20.0, which is
    what reading only ``points`` would have published for the ringed shape.
    """
    p2_chords = [Point(120, 50), Point(140, 50), Point(140, 140), Point(120, 140)]
    p2_ring = [Point(120, 50), Point(50, 90), Point(120, 140), Point(140, 140), Point(140, 50)]

    board = _board(
        pours=[
            _pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER]),
            _pour("p2", "HV", points=p2_chords, rings=[p2_ring]),
        ]
    )
    result = net_clearance(board, "GND", "HV")
    assert result is None  # inf: the ring witness is inside p1's solid

    control_board = _board(
        pours=[
            _pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER]),
            _pour("p2", "HV", points=p2_chords, rings=[]),
        ]
    )
    control = net_clearance(control_board, "GND", "HV")
    assert control is not None
    assert control.distance == pytest.approx(20.0)


def test_88a_rings_change_no_area_and_no_label():
    """Area stays the ``points`` shoelace and the label keeps its record id.

    The bulged ring's shoelace area is 150 sq mil; the chord square's is 100.
    A consumer that reported the ring area would silently change every pour
    total in the review report, so the island area must still be 100. The
    element label is likewise built from the record (``kind`` + ``id`` +
    ``layer_id``), not from the geometry view.
    """
    board = _board(
        pours=[_pour("p1", "GND", rings=[_BULGED_RING])],
        tracks=[_track("t1", "HV", (30, 5), (40, 5))],
    )
    connectivity = pour_connectivity(board, "GND")
    assert connectivity.island_count == 1
    assert connectivity.islands[0].area == pytest.approx(100.0)
    assert connectivity.islands[0].element_ids == ["p1"]
    assert connectivity.islands[0].layer_ids == [1]

    result = net_clearance(board, "GND", "HV")
    assert result is not None
    assert result.element_a == "pour fill p1 on layer 1"
    assert result.element_b == "track t1 on layer 1"


# ---------------------------------------------------------------------------
# 6. #88D: a stitching via fence in the bulge
# ---------------------------------------------------------------------------


def test_88d_a_via_fence_in_the_bulge_is_one_island_and_bbox_is_not_the_merge():
    """Three ``GND`` stitching vias along the bulge: the rings fuse them.

    Hand computation, all lengths in mil. ``rings[0]`` is :data:`_BULGED_RING`
    — the pentagon ``(0, 0) (10, 0) (20, 5) (10, 10) (0, 10)`` — whose lower
    edge ``(10, 0)-(20, 5)`` is ``y = (x - 10) / 2`` and whose upper edge
    ``(20, 5)-(10, 10)`` is ``y = 5 + (20 - x) / 2``:

    * at ``x = 13`` the ring spans ``y ∈ [1.5, 8.5]``, at ``x = 17`` it spans
      ``y ∈ [3.5, 6.5]``, so ``v1 = (13, 2.5)``, ``v2 = (17, 5)`` and
      ``v3 = (13, 7.5)`` are all **inside** the ring's solid copper, and all
      three have ``x > 10``: **outside** the chord square;
    * the vias are 4.72 / 4.72 / 5.0 mil apart and 4 mil wide (2 mil radius),
      so they never touch each other — the fence is fused by the pour, not by
      a via-to-via contact;
    * the nearest chord edge is ``13 - 2 = 11`` against ``x = 10``: a 1.0 mil
      copper gap, so with the chords alone every via is its own island.

    What this pins, and why each assertion matters:

    * ``rings`` → **1 island**, ``["v1", "v2", "v3", "p1"]``; ``rings=[]`` →
      **4 islands**. Same board otherwise, so the delta is provably the rings.
    * the bbox follows the same split — ``(0, 0, 20, 10)`` with rings,
      ``(0, 0, 10, 10)`` without — while the vias' **centres** sit outside the
      chord box: the ring box is what lets the pair reach the exact test.
    * the layer span of the fused island is ``[1, 2]`` (the pour's layer 1
      plus the through-via's 1/2) while the chord control's pour island is
      ``[1]``: fusing did not move any copper to another layer.

    **The bbox is not what merges them** — the exact containment test is. The
    last pair of boards carries a pour with a void: a ``GND`` via at
    ``(50, 50)`` sits deep inside the ring's ``(0, 0)-(100, 100)`` box, but it
    is inside the 20 × 20 void, i.e. **not** solid copper, and its copper
    starts ``46 - 40 = 6.0`` mil from the void edge — so the net keeps two
    islands even though the boxes overlap completely. A via at ``(20, 20)`` is
    equally inside the box *and* in the solid part, and is one island with
    the pour. Box overlap alone would have said 「one island」 for both.
    """
    fence = [_via("v1", "GND", 13, 2.5), _via("v2", "GND", 17, 5), _via("v3", "GND", 13, 7.5)]
    board = _board(pours=[_pour("p1", "GND", rings=[_BULGED_RING])], vias=fence)
    connectivity = pour_connectivity(board, "GND")
    assert connectivity.island_count == 1
    fused = connectivity.islands[0]
    assert fused.element_ids == ["v1", "v2", "v3", "p1"]
    assert fused.layer_ids == [1, 2]
    # The area is still the chord square's 100 — not the ring's 150 (group 5).
    assert fused.area == pytest.approx(100.0)

    chord_board = _board(pours=[_pour("p1", "GND", rings=[])], vias=fence)
    chord = pour_connectivity(chord_board, "GND")
    assert chord.island_count == 4
    assert [island.element_ids for island in chord.islands] == [
        ["v1"],
        ["v2"],
        ["v3"],
        ["p1"],
    ]
    assert [island.layer_ids for island in chord.islands] == [[1, 2], [1, 2], [1, 2], [1]]

    ring_box = _pour_shape(board, "GND").bbox
    chord_box = _pour_shape(chord_board, "GND").bbox
    assert ring_box is not None and chord_box is not None
    assert (ring_box.min_x, ring_box.min_y, ring_box.max_x, ring_box.max_y) == (0.0, 0.0, 20.0, 10.0)
    assert (chord_box.min_x, chord_box.min_y, chord_box.max_x, chord_box.max_y) == (
        0.0,
        0.0,
        10.0,
        10.0,
    )
    for centre_x in (13.0, 17.0):
        assert centre_x > chord_box.max_x  # outside the chord box, inside the ring box
        assert ring_box.min_x <= centre_x <= ring_box.max_x

    # Box overlap is necessary, never sufficient: a via in the ring's *void* is
    # inside the ring's bbox and still a separate island, because the exact
    # test reads 「inside the outer ring, inside a void」 as not-copper.
    voided = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])],
        vias=[_via("v9", "GND", 50, 50, diameter=8.0, hole=4.0)],
    )
    voided_box = _pour_shape(voided, "GND").bbox
    assert voided_box is not None
    assert (voided_box.min_x, voided_box.min_y, voided_box.max_x, voided_box.max_y) == (
        0.0,
        0.0,
        100.0,
        100.0,
    )
    assert pour_connectivity(voided, "GND").island_count == 2

    solid = _board(
        pours=[_pour("p1", "GND", points=_BIG_OUTER, rings=[_BIG_OUTER, _BIG_VOID])],
        vias=[_via("v9", "GND", 20, 20, diameter=8.0, hole=4.0)],
    )
    solid_conn = pour_connectivity(solid, "GND")
    assert solid_conn.island_count == 1
    assert solid_conn.islands[0].element_ids == ["v9", "p1"]
