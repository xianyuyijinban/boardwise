"""Issue #83: ``_capsule_distance``'s containment test was a tautology.

``contained`` had both disjuncts measuring a polygon against **its own**
vertices::

    (a.is_pour and any(point_in_polygon(p, b.points) for p in b.points)) or (
        b.is_pour and any(point_in_polygon(p, a.points) for p in a.points)
    )

``point_in_polygon`` of a polygon's own vertex is true by construction (the
vertex is on two of the edges), so ``any`` was true and every pair with a pour
on either side was decided by that tautology instead of by geometry — on both
callers, in opposite directions:

* ``connectivity=False`` (the clearance engine) returned ``math.inf`` for
  **every** pour pair, so a real measurable gap silently dropped out of the
  minimum (:func:`~boardwise.core.measure.net_clearance` returned ``None`` for
  a net pair whose only copper is one pour plus one distant element);
* ``connectivity=True`` (:func:`~boardwise.core.measure.pour_connectivity`)
  returned ``0.0`` for every pour pair, so a pour was fused to everything else
  on its net no matter how far away, and the island count was a lie.

The docstring's intent is 「one side's **body** falls inside the other's
**pour** polygon」: when ``a`` is the pour the test belongs to ``b``'s points
against ``a``'s polygon, and vice versa. The two branches were swapped.

Every expectation below is **hand-computed geometry**, and the coordinate
literals are the ones in the issue. The issue quotes the probe's separation as
「约 990 mil」 — that is the horizontal offset from the pour's corner; the
edge-to-edge gap the primitive returns is ``990*sqrt(2) - 5`` (the corner
``(10, 10)`` to the nearer track endpoint ``(1000, 1000)``, minus the track's
5 mil half width), and asserting the distance measured from the far corner
would have baked in the issue's arithmetic rather than the geometry.

Groups:

1. the issue's two probes, plus the same answer under argument swap;
2. 「仅仅挨着」 — 10 mil off the pour edge, and copper that just touches;
3. a body genuinely inside the pour (containment must still read as one piece
   of copper — the reason the test exists at all, and the over-fixing guard);
4. both shapes pours: intersecting / disjoint / contained;
5. the two consumers of the flag, at board level: ``net_clearance`` on a pour
   net pair and ``pour_connectivity`` island counts.
"""

from __future__ import annotations

import math

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    TrackSegment,
)
from boardwise.core.measure import (
    _Shape,
    _capsule_distance,
    _overlapping,
    net_clearance,
    pour_connectivity,
)

#: The issue's pour: a 10 x 10 mil square with its corner at the origin.
_POUR_SQUARE = [Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)]

#: The issue's far track: centreline 1000 .. 1010 mil, 5 mil half width. Its
#: nearer endpoint (1000, 1000) is 990 mil from the pour on **both** axes.
_FAR_TRACK = [Point(1000, 1000), Point(1010, 1000)]
_FAR_GAP = math.hypot(990.0, 990.0) - 5.0  # 1395.0710678...

#: An L-shaped pour, ``(0,0)-(10,10)`` with the ``x > 4, y > 4`` quadrant
#: missing. Its **bounding box** still covers that quadrant, so a body sitting
#: in the notch is one the coarse rejects in ``_best_pair`` / ``pour_connectivity``
#: (which compare capsule boxes) cannot throw away — it is the geometry that
#: separates 「the bbox overlaps」 from 「the copper does」, and the only kind of
#: pair on which both halves of issue #83 are observable.
_L_POUR = [
    Point(0, 0),
    Point(10, 0),
    Point(10, 4),
    Point(4, 4),
    Point(4, 10),
    Point(0, 10),
]

#: A 2 x 2 pad in the notch: every corner 2 mil from the nearest pour edge,
#: no corner inside the polygon.
_NOTCH_PAD = [Point(6, 6), Point(8, 6), Point(8, 8), Point(6, 8)]
_NOTCH_GAP = 2.0


def _pour(points=None, *, radius: float = 0.0, layers=frozenset({1})) -> _Shape:
    return _Shape(
        list(_POUR_SQUARE if points is None else points),
        radius,
        set(layers),
        "pour q",
        is_pour=True,
    )


def _solid(points, radius: float = 0.0, *, layers=frozenset({1}), label: str = "t") -> _Shape:
    return _Shape(list(points), radius, set(layers), label, is_pour=False)


# ---------------------------------------------------------------------------
# 1. the issue's probes
# ---------------------------------------------------------------------------


def test_83_the_far_track_is_measurable_under_both_readings():
    """Both callers get the geometric gap, not ``inf`` / ``0.0``.

    Pre-fix: ``connectivity=False`` answered ``inf`` (pair dropped from the
    clearance minimum) and ``connectivity=True`` answered ``0.0`` (the pour and
    a track 1.4 mm away declared one piece of copper). The value asserted is
    the hand-computed edge-to-edge gap, ``990*sqrt(2) - 5``.
    """
    pour = _pour()
    track = _solid(_FAR_TRACK, 5.0)
    assert _capsule_distance(track, pour, connectivity=False) == pytest.approx(_FAR_GAP)
    assert _capsule_distance(track, pour, connectivity=True) == pytest.approx(_FAR_GAP)


def test_83_the_answer_does_not_depend_on_which_side_is_the_pour():
    """``(a, b)`` and ``(b, a)`` are the same measurement.

    The bug was exactly an order dependence — the pour had to be on the left
    for the tautology to fire — so the symmetry is the property the fix
    restores. This is the same probe with the arguments swapped.
    """
    pour = _pour()
    track = _solid(_FAR_TRACK, 5.0)
    for connectivity in (False, True):
        assert _capsule_distance(pour, track, connectivity=connectivity) == pytest.approx(_FAR_GAP)
        assert _capsule_distance(track, pour, connectivity=connectivity) == pytest.approx(_FAR_GAP)


# ---------------------------------------------------------------------------
# 2. close to the pour, but outside it
# ---------------------------------------------------------------------------


def test_83_a_pair_10_mil_off_the_pour_edge_reads_10_mil():
    """``(20, 0) -> (30, 0)``, zero width: 10 mil from the pour's ``(10, 0)``
    corner, on the ``y = 0`` edge line. 「仅仅挨着」 — near, and not inside."""
    pour = _pour()
    near = _solid([Point(20, 0), Point(30, 0)])
    assert _capsule_distance(near, pour, connectivity=False) == pytest.approx(10.0)
    assert _capsule_distance(near, pour, connectivity=True) == pytest.approx(10.0)
    assert _capsule_distance(pour, near, connectivity=False) == pytest.approx(10.0)


def test_83_copper_that_just_touches_stays_at_zero():
    """A 5 mil half width track whose left endpoint is 5 mil off the corner.

    The copper's edge meets the pour's corner exactly, with no vertex inside
    the polygon, so the containment branch must not swallow it: both readings
    are 0.0 and the pair is a same-layer overlap. A fix that made *every*
    non-contained pair honest but turned a real touch into 「unmeasurable」
    would be an over-correction, and this is the case that catches it.
    """
    pour = _pour()
    touching = _solid([Point(15, 0), Point(25, 0)], 5.0)
    assert _capsule_distance(touching, pour, connectivity=True) == 0.0
    assert _capsule_distance(touching, pour, connectivity=False) == 0.0
    assert _overlapping(pour, touching) is True


# ---------------------------------------------------------------------------
# 3. genuinely inside — containment must survive (the over-fixing guard)
# ---------------------------------------------------------------------------


def test_83_a_body_inside_the_pour_is_still_one_piece_of_copper():
    """A 2 x 2 pad and a track wholly inside the 10 x 10 pour.

    This is what the containment test exists for: a real pour is solid copper
    around its own net's pads, so the pad's body is inside the polygon and
    never reaches its outline. ``connectivity=True`` must read 0.0 (one piece
    of copper) and ``connectivity=False`` must keep reading ``inf`` — the
    documented blind spot for a foreign body inside a pour outline, unchanged
    by this fix.
    """
    pour = _pour()
    pad = _solid([Point(4, 4), Point(6, 4), Point(6, 6), Point(4, 6)], label="pad U1.1")
    inner_track = _solid([Point(2, 2), Point(8, 8)], 0.5, label="t inner")
    for body in (pad, inner_track):
        assert _capsule_distance(body, pour, connectivity=True) == 0.0
        assert _capsule_distance(pour, body, connectivity=True) == 0.0
        assert math.isinf(_capsule_distance(body, pour, connectivity=False))
        assert math.isinf(_capsule_distance(pour, body, connectivity=False))


# ---------------------------------------------------------------------------
# 4. pour against pour
# ---------------------------------------------------------------------------


def test_83_two_intersecting_pours_are_one_piece_of_copper():
    """Overlapping squares, ``(0,0)-(10,10)`` and ``(5,5)-(15,15)``.

    ``connectivity=True``: 0.0 — the copper overlaps, which is the same answer
    the pre-fix tautology gave for the wrong reason. ``connectivity=False``:
    ``inf``, the containment blind spot reaching pour-vs-pour pairs as well
    (two nets' pours cannot both be solid copper where they cross; the editor
    cut one of them back, and the model does not hold the cut).
    """
    a = _pour()
    b = _pour([Point(5, 5), Point(15, 5), Point(15, 15), Point(5, 15)])
    assert _capsule_distance(a, b, connectivity=True) == 0.0
    assert _capsule_distance(b, a, connectivity=True) == 0.0
    assert math.isinf(_capsule_distance(a, b, connectivity=False))


def test_83_two_distant_pours_read_their_corner_gap():
    """``(0,0)-(10,10)`` against ``(100,100)-(110,110)``: the corner ``(10,10)``
    to the corner ``(100,100)`` is ``90*sqrt(2)`` mil. Pre-fix both readings
    were the tautology's answers (``inf`` / ``0.0``), so a pour pair's real
    separation was unmeasurable at any distance."""
    a = _pour()
    b = _pour([Point(100, 100), Point(110, 100), Point(110, 110), Point(100, 110)])
    expected = math.hypot(90.0, 90.0)
    assert _capsule_distance(a, b, connectivity=False) == pytest.approx(expected)
    assert _capsule_distance(a, b, connectivity=True) == pytest.approx(expected)
    assert _capsule_distance(b, a, connectivity=False) == pytest.approx(expected)


def test_83_a_pour_inside_another_pour_is_contained():
    """``(2,2)-(4,4)`` inside ``(0,0)-(10,10)``: one piece of copper either
    way round, and unmeasurable for the clearance engine."""
    outer = _pour()
    inner = _pour([Point(2, 2), Point(4, 2), Point(4, 4), Point(2, 4)])
    assert _capsule_distance(outer, inner, connectivity=True) == 0.0
    assert _capsule_distance(inner, outer, connectivity=True) == 0.0
    assert math.isinf(_capsule_distance(outer, inner, connectivity=False))
    assert math.isinf(_capsule_distance(inner, outer, connectivity=False))


# ---------------------------------------------------------------------------
# 5. the two consumers, at board level
# ---------------------------------------------------------------------------


def _two_layer() -> tuple[dict[int, LayerInfo], list[StackupEntry]]:
    return (
        {1: LayerInfo(1, "Top Layer", "TOP"), 2: LayerInfo(2, "Bottom Layer", "BOTTOM")},
        [
            StackupEntry(1, 1000, "外层铜厚", 1.378),
            StackupEntry(2, 9000, "外层铜厚", 1.378),
        ],
    )


def _square_pour(pour_id: str, net: str, layer_id: int = 1) -> PourShape:
    return PourShape(
        id=pour_id, net=net, layer_id=layer_id, kind="pour", points=list(_POUR_SQUARE)
    )


def _board(**kwargs) -> BoardGeometry:
    layers, stackup = _two_layer()
    return BoardGeometry(source="synthetic", layers=layers, stackup=stackup, **kwargs)


def test_83_net_clearance_between_a_pour_net_and_a_distant_net_is_measurable():
    """The clearance engine's silent drop, at the level a rule sees it.

    ``GND`` is one pour and ``HV`` one track 1395.07 mil away on the same
    layer. Pre-fix every shape pair came back ``inf``, ``_best_pair`` found no
    pair at all, and ``net_clearance`` answered ``None`` — a rule reading that
    as 「no copper」 / 「not measurable」 loses the pair entirely. Post-fix it is
    an ordinary measurement: this is the class of pair the issue's board
    evidence counts as 645 recovered pairs.
    """
    board = _board(
        pours=[_square_pour("p1", "GND")],
        tracks=[
            TrackSegment(
                "t1", net="HV", layer_id=1,
                start=Point(1000, 1000), end=Point(1010, 1000), width=10,
            )
        ],
    )
    result = net_clearance(board, "GND", "HV")
    assert result is not None
    assert result.distance == pytest.approx(_FAR_GAP)
    assert result.overlapping is False
    assert result.shared_layer_ids == [1]
    # ... and the same measurement in the other argument order.
    mirrored = net_clearance(board, "HV", "GND")
    assert mirrored is not None and mirrored.distance == pytest.approx(_FAR_GAP)


def test_83_net_clearance_across_a_pour_notch_is_measurable():
    """The same failure from the clearance side, in the geometry the coarse
    reject cannot skip: a foreign net's pad 2 mil from an L pour's edge.

    Pre-fix every pair with a pour came back ``inf``, so a net pair whose only
    copper is one pour plus one nearby element had no measurable pair at all
    and ``net_clearance`` answered ``None``. This is the shape the issue's
    board evidence counts (7434 same-layer pairs of which 645 were dropped) —
    elements near or across a pour outline rather than inside it.
    """
    board = _board(
        pours=[PourShape(id="p1", net="GND", layer_id=1, kind="pour", points=list(_L_POUR))],
        pads=[
            PadGeometry(
                "pad1", component="U1", pin_number="1", net="HV",
                footprint_layer_id=1, x=7, y=7, width=2, height=2, shape="RECT",
            )
        ],
    )
    result = net_clearance(board, "GND", "HV")
    assert result is not None
    assert result.distance == pytest.approx(_NOTCH_GAP)
    assert result.overlapping is False
    assert result.shared_layer_ids == [1]


def test_83_a_foreign_pad_inside_the_pour_is_still_unmeasurable():
    """The blind spot the containment branch protects, kept intact.

    A ``SIG`` pad wholly inside the ``GND`` pour's outline: the pour's real
    copper has a clearance void around it and the model does not hold the
    void, so the honest answer is still ``None`` rather than a manufactured
    0.0 short. This is 131f's anchor, re-pinned here so a fix that made the
    branch honest by *deleting* containment would fail in this file too.
    """
    board = _board(
        pours=[_square_pour("p1", "GND")],
        pads=[
            PadGeometry(
                "pad1", component="U1", pin_number="1", net="SIG",
                footprint_layer_id=1, x=5, y=5, width=2, height=2, shape="RECT",
            )
        ],
    )
    assert net_clearance(board, "GND", "SIG") is None


def test_83_pour_connectivity_no_longer_fuses_a_body_that_is_only_near_the_pour():
    """A pad in the notch of an L pour is ``2.0`` mil away, not one island.

    The pour's **capsule box** covers the notch, so the coarse reject in
    ``pour_connectivity`` does not skip this pair — pre-fix it reached the
    tautology, read ``0.0``, and the union-find declared the pad one piece of
    copper with the pour it is 2 mil clear of. This is the 「一切皆相连」 half
    of issue #83 in the only geometry that can show it, and the reading behind
    the thermal rules' island counts.

    The far track from the issue's probe is kept alongside it: there the coarse
    reject already separated the two (correctly, before and after), so the two
    together state which pairs the bug could and could not reach.
    """
    board = _board(
        pours=[PourShape(id="p1", net="GND", layer_id=1, kind="pour", points=list(_L_POUR))],
        pads=[
            PadGeometry(
                "pad1", component="U1", pin_number="1", net="GND",
                footprint_layer_id=1, x=7, y=7, width=2, height=2, shape="RECT",
            )
        ],
        tracks=[
            TrackSegment(
                "t1", net="GND", layer_id=1,
                start=Point(1000, 1000), end=Point(1010, 1000), width=10,
            )
        ],
    )
    connectivity = pour_connectivity(board, "GND")
    # The notch pad is its own island; so is the far track. Flat record order
    # is tracks, then vias, then pads, then pours.
    assert connectivity.island_count == 3
    assert [island.element_ids for island in connectivity.islands] == [["t1"], ["U1.1"], ["p1"]]


def test_83_pour_connectivity_still_fuses_copper_inside_and_on_the_pour():
    """The other side of the same consumer: a pad inside the pour and a track
    meeting its corner are both one island with it.

    Without this, the fix above could be satisfied by never unioning a pour
    with anything.
    """
    board = _board(
        pours=[_square_pour("p1", "GND")],
        pads=[
            PadGeometry(
                "pad1", component="U1", pin_number="1", net="GND",
                footprint_layer_id=1, x=5, y=5, width=2, height=2, shape="RECT",
            )
        ],
        tracks=[
            TrackSegment(
                "t1", net="GND", layer_id=1,
                start=Point(15, 0), end=Point(25, 0), width=10,
            )
        ],
    )
    connectivity = pour_connectivity(board, "GND")
    assert connectivity.island_count == 1
    assert connectivity.islands[0].element_ids == ["t1", "U1.1", "p1"]
