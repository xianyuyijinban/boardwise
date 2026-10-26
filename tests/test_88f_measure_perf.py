"""#88F: the #88A pour-rings work must not cost a full edge-pair cross product.

#88A made a pour's *rings* (outline + clearance voids, arcs expanded) the
measured copper and made containment a solid test rather than an outline
tautology. That is the correct reading, but the first implementation rebuilt
each shape's ring / witness / edge lists on every pair **and** kept the
``min()`` over the complete ``edges_a x edges_b`` cross product — on ROBOT's
GND (two poured results with 553 and 6 251 outline points) that is ~11 M
exact segment evaluations for one board-wide call.

This file pins three things:

1. **Real-fixture identity + cost.** ``pour_connectivity(ROBOT, 'GND')`` and
   ``net_clearance(ROBOT, 'GND', 'VCC', same_layer_only=True)`` keep the exact
   #88A answer (1 island / 295 members / pinned area and layers; 3.538... mil
   and the same element pair), while the number of exact ``_segment_distance``
   calls stays under 100 k and the wall stays under a loose ceiling. The
   op-count is the primary gate — it is deterministic; the wall is a coarse
   backstop for a regression that only shows up as time.
2. **Deterministic small-shape differential.** The production answer is
   compared, value for value, against an independent brute-force reference
   (full edge cross product + independent even-odd containment) over
   hand-written shapes: two-point tracks, a degenerate zero-length edge,
   crossing, touching, separated, containment inside a pour, and a pour with a
   void (body in the void vs body in solid copper, pour against pour).
3. **The boundary contracts the optimisation must not change.** An outer ring
   with no points has no box and answers 「not inside」 rather than raising; an
   empty void ring is skipped; an empty edge set still raises the old
   ``min()`` ``ValueError`` (not a silent ``inf``); ``_edges`` keeps its
   two-point / degenerate / self-intersecting edge list.

Measured on the batch machine (2026-10-26, single process, ROBOT fixture):
current tree GND 15.5 s / same-layer 8.2 s / ~11.0 M segment calls; the
bbox-sweep implementation 2.2 s / 1.0 s / ~12.5 k calls for the same values.

Fixture: ``tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2`` — a real
board, not a synthetic one. This is a focused file, not a suite run.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest

from boardwise.core import measure
from boardwise.core.geometry import PourShape, Point
from boardwise.core.measure import (
    _Shape,
    _capsule_distance,
    _edges,
    _point_in_solid,
    _segment_distance,
    _shape_edges,
    _shape_rings,
    net_clearance,
    pour_connectivity,
)
from boardwise.parsers.epru import parse_epro2

FIXTURE = Path(__file__).parent / "fixtures" / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"

#: ROBOT's GND: two almost-full discs plus six small pieces, 295 members.
GND_MEMBERS = 295
GND_AREA = 2210304.22645474
GND_LAYERS = [1, 2, 15, 16]

#: The same-layer GND/VCC gap: a pad and a track, 3.538... mil apart.
VCC_GAP = 3.538172961471341
VCC_ELEMENT_A = "pad U1.31 on layer 1"
VCC_ELEMENT_B = "track 03d13fd9b5027b71 on layer 1"

#: Deterministic op-count ceiling. The full cross product is ~11 M; the
#: bbox-bounded sweep is ~12.5 k for both calls together. 100 k leaves room
#: for a new small pour on the fixture without ever admitting the old loop.
MAX_SEGMENT_CALLS = 100_000


@pytest.fixture(scope="module")
def robot():
    return parse_epro2(FIXTURE)


# ---------------------------------------------------------------------------
# 1. the real board: exact answer, bounded exact-test count, loose wall
# ---------------------------------------------------------------------------


def test_88f_robot_gnd_and_same_layer_gap_stay_exact_and_cheap(robot, monkeypatch):
    calls = {"n": 0}
    real_segment_distance = measure._segment_distance

    def counted_segment_distance(*args):
        calls["n"] += 1
        return real_segment_distance(*args)

    monkeypatch.setattr(measure, "_segment_distance", counted_segment_distance)

    started = time.perf_counter()
    connectivity = pour_connectivity(robot, "GND")
    gnd_wall = time.perf_counter() - started
    members = [element for island in connectivity.islands for element in island.element_ids]

    assert connectivity.island_count == 1
    assert len(members) == GND_MEMBERS
    assert [len(island.element_ids) for island in connectivity.islands] == [GND_MEMBERS]
    assert sum(island.area for island in connectivity.islands) == pytest.approx(
        GND_AREA, abs=1e-6
    )
    assert connectivity.islands[0].layer_ids == GND_LAYERS

    started = time.perf_counter()
    clearance = net_clearance(robot, "GND", "VCC", same_layer_only=True)
    clearance_wall = time.perf_counter() - started

    assert clearance is not None
    assert clearance.distance == pytest.approx(VCC_GAP, abs=1e-12)
    assert clearance.element_a == VCC_ELEMENT_A
    assert clearance.element_b == VCC_ELEMENT_B
    assert clearance.overlapping is False
    assert clearance.shared_layer_ids == [1]

    # Primary gate: deterministic count of *exact* segment evaluations.
    assert calls["n"] <= MAX_SEGMENT_CALLS, (
        f"{calls['n']} exact _segment_distance calls for two board-wide calls; "
        f"the full edge cross product is back (ceiling {MAX_SEGMENT_CALLS})"
    )
    # Coarse backstop, with ~2.7x/3x headroom over the measured implementation.
    assert gnd_wall <= 6.0, f"pour_connectivity(GND) took {gnd_wall:.2f}s"
    assert clearance_wall <= 3.0, f"net_clearance(GND,VCC,same_layer) took {clearance_wall:.2f}s"


# ---------------------------------------------------------------------------
# 2. deterministic small-shape differential (independent reference)
# ---------------------------------------------------------------------------


def _brute_point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Independent even-odd + on-edge test, written without measure helpers."""
    inside = False
    n = len(polygon)
    for index in range(n):
        a = polygon[index]
        b = polygon[(index + 1) % n]
        # on-edge: distance point→ab
        dx, dy = b.x - a.x, b.y - a.y
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-18:
            if math.hypot(point.x - a.x, point.y - a.y) <= 1e-9:
                return True
        else:
            t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / length_sq
            t = max(0.0, min(1.0, t))
            if math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy)) <= 1e-9:
                return True
        if (a.y > point.y) != (b.y > point.y):
            x_at = a.x + (point.y - a.y) / (b.y - a.y) * (b.x - a.x)
            if point.x < x_at:
                inside = not inside
    return inside


def _brute_point_in_solid(shape: _Shape, point: Point) -> bool:
    rings = _shape_rings(shape)
    if not _brute_point_in_polygon(point, rings[0]):
        return False
    return not any(_brute_point_in_polygon(point, void) for void in rings[1:])


def _brute_capsule_distance(a: _Shape, b: _Shape, *, connectivity: bool) -> float:
    """The old full cross product, with independently rebuilt containment."""
    contained = (
        a.is_pour
        and any(_brute_point_in_solid(a, p) for ring in _shape_rings(b) for p in ring)
    ) or (
        b.is_pour
        and any(_brute_point_in_solid(b, p) for ring in _shape_rings(a) for p in ring)
    )
    if contained:
        return 0.0 if connectivity else math.inf
    edges_a = _shape_edges(a)
    edges_b = _shape_edges(b)
    center = min(
        _segment_distance(p1, p2, p3, p4)
        for p1, p2 in edges_a
        for p3, p4 in edges_b
    )
    return max(0.0, center - a.radius - b.radius)


def _track(points, radius=0.0, label="track t", layers=None) -> _Shape:
    return _Shape(list(points), radius, layers or {1}, label)


def _pour(points, rings, radius=0.0, label="pour p", layers=None) -> _Shape:
    return _Shape(
        list(points), radius, layers or {1}, label, is_pour=True, rings=[list(r) for r in rings]
    )


#: (a, b, connectivity) cases: crossing, touching, separated, degenerate,
#: two-point vs polygon, containment (both intents), void containment and
#: pour-against-pour. Expected values are the brute reference's, not literals.
_DIFFERENTIAL_CASES = [
    # two 2-point tracks, crossing and parallel
    (_track([Point(0, 0), Point(10, 10)]), _track([Point(0, 10), Point(10, 0)]), True),
    (_track([Point(0, 0), Point(10, 0)]), _track([Point(0, 5), Point(10, 5)]), False),
    # shared endpoint (touching) and a degenerate zero-length edge
    (_track([Point(0, 0), Point(10, 0)]), _track([Point(10, 0), Point(20, 0)]), True),
    (_track([Point(5, 5), Point(5, 5)]), _track([Point(0, 0), Point(10, 0)]), False),
    # widened capsules: 5 mil centre gap - 1 - 1 = 3
    (
        _track([Point(0, 0), Point(10, 0)], radius=1.0),
        _track([Point(0, 5), Point(10, 5)], radius=1.0),
        False,
    ),
    # a pour (no rings) containing a via: one piece for connectivity, but the
    # clearance intent is 「unmeasurable」 rather than an invented short
    (
        _pour([Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)], []),
        _track([Point(50, 50), Point(50, 50)]),
        True,
    ),
    (
        _pour([Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)], []),
        _track([Point(50, 50), Point(50, 50)]),
        False,
    ),
    # pour with a 20x20 void at (40,40)..(60,60):
    #   body at the void's centre -> measurable, 10 mil to the void edge
    #   body at (10,10) -> inside solid, same semantics as containment
    (
        _pour(
            [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
            [
                [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
                [Point(40, 40), Point(60, 40), Point(60, 60), Point(40, 60)],
            ],
        ),
        _track([Point(50, 50), Point(50, 50)]),
        True,
    ),
    (
        _pour(
            [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
            [
                [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
                [Point(40, 40), Point(60, 40), Point(60, 60), Point(40, 60)],
            ],
        ),
        _track([Point(50, 50), Point(50, 50)]),
        False,
    ),
    (
        _pour(
            [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
            [
                [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
                [Point(40, 40), Point(60, 40), Point(60, 60), Point(40, 60)],
            ],
        ),
        _track([Point(10, 10), Point(10, 10)]),
        True,
    ),
    # a body straddling a void edge: nearest void edge is 3 mil away
    (
        _pour(
            [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
            [
                [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
                [Point(40, 40), Point(60, 40), Point(60, 60), Point(40, 60)],
            ],
        ),
        _track([Point(63, 50), Point(63, 50)]),
        False,
    ),
    # two pours: the small one sits in the big one's void (measurable), and
    # one sits in solid copper (contained / fused)
    (
        _pour(
            [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
            [
                [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
                [Point(40, 40), Point(60, 40), Point(60, 60), Point(40, 60)],
            ],
            label="pour outer",
        ),
        _pour(
            [Point(45, 45), Point(55, 45), Point(55, 55), Point(45, 55)],
            [[Point(45, 45), Point(55, 45), Point(55, 55), Point(45, 55)]],
            label="pour in void",
        ),
        False,
    ),
    (
        _pour(
            [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)],
            [[Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)]],
            label="pour outer",
        ),
        _pour(
            [Point(10, 10), Point(20, 10), Point(20, 20), Point(10, 20)],
            [[Point(10, 10), Point(20, 10), Point(20, 20), Point(10, 20)]],
            label="pour inside",
        ),
        True,
    ),
]


@pytest.mark.parametrize("a,b,connectivity", _DIFFERENTIAL_CASES)
def test_88f_sweep_matches_brute_force_value_for_value(a, b, connectivity):
    expected = _brute_capsule_distance(a, b, connectivity=connectivity)
    if connectivity:
        # The connectivity intent: contained -> 0.0, otherwise the copper gap.
        assert _capsule_distance(a, b, connectivity=True) == expected
    else:
        # The clearance intent: contained -> inf (unmeasurable), else the gap.
        actual = _capsule_distance(a, b, connectivity=False)
        if math.isinf(expected):
            assert actual == math.inf
        else:
            assert actual == expected
    # symmetry: the sweep must not depend on argument order
    assert _capsule_distance(b, a, connectivity=connectivity) == _capsule_distance(
        a, b, connectivity=connectivity
    )


def test_88f_sweep_matches_brute_force_on_every_pair_of_a_deterministic_set():
    shapes = [
        _track([Point(0, 0), Point(12, 0)], radius=0.5, label="track h"),
        _track([Point(0, 6), Point(12, 6)], radius=0.5, label="track h2"),
        _track([Point(3, -5), Point(3, 9)], radius=0.25, label="track v"),
        _track([Point(5, 5), Point(5, 5)], radius=0.1, label="via point"),
        _pour(
            [Point(-20, -20), Point(40, -20), Point(40, 40), Point(-20, 40)],
            [
                [Point(-20, -20), Point(40, -20), Point(40, 40), Point(-20, 40)],
                [Point(0, 0), Point(6, 0), Point(6, 6), Point(0, 6)],
            ],
            label="pour small",
        ),
        _pour(
            [Point(-20, -20), Point(40, -20), Point(40, 40), Point(-20, 40)],
            [[Point(-20, -20), Point(40, -20), Point(40, 40), Point(-20, 40)]],
            radius=1.0,
            label="pour solid",
        ),
    ]
    for index, a in enumerate(shapes):
        for b in shapes[index + 1 :]:
            for connectivity in (True, False):
                expected = _brute_capsule_distance(a, b, connectivity=connectivity)
                actual = _capsule_distance(a, b, connectivity=connectivity)
                if math.isinf(expected):
                    assert actual == math.inf
                else:
                    assert actual == expected, (a.label, b.label, connectivity)


# ---------------------------------------------------------------------------
# 3. boundary contracts (no new public API is required to reach them)
# ---------------------------------------------------------------------------


def test_88f_outer_ring_without_points_is_not_inside_and_does_not_raise():
    empty = _pour([], [[]], label="pour empty")
    assert _point_in_solid(empty, Point(0, 0)) is False


def test_88f_empty_void_ring_is_skipped():
    outer = [Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)]
    with_empty_void = _pour(outer, [outer, []], label="pour empty void")
    assert _point_in_solid(with_empty_void, Point(5, 5)) is True
    assert _point_in_solid(with_empty_void, Point(50, 50)) is False


def test_88f_empty_edge_set_keeps_the_min_valueerror():
    empty = _track([], label="track empty")
    other = _track([Point(0, 0), Point(10, 0)])
    with pytest.raises(ValueError, match="empty"):
        _capsule_distance(empty, other, connectivity=False)
    with pytest.raises(ValueError, match="empty"):
        _capsule_distance(other, empty, connectivity=False)


def test_88f_edges_keep_two_point_degenerate_and_self_intersecting_behaviour():
    assert _edges([Point(0, 0), Point(10, 0)]) == [
        (Point(0, 0), Point(10, 0)),
        (Point(10, 0), Point(0, 0)),
    ]
    degenerate = [Point(5, 5), Point(5, 5)]
    assert _edges(degenerate) == [
        (degenerate[0], degenerate[1]),
        (degenerate[1], degenerate[0]),
    ]
    bowtie = [Point(0, 0), Point(10, 10), Point(10, 0), Point(0, 10)]
    assert len(_edges(bowtie)) == 4
    assert (_edges(bowtie)[1]) == (Point(10, 10), Point(10, 0))
