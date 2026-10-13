"""R2-4: two pieces of 177's geometry debt, retired.

1. ``rules/pcb/distance.py::_point_in_outline`` was the fourth copy of the
   「on-edge counts as inside」 even-odd test. Line for line it was
   :func:`boardwise.core.measure.point_in_polygon`; the one difference was which
   private point-to-segment helper it called. It is gone, and the board-outline
   escape check calls core's.
2. Three point-to-segment distance functions existed: core's private one (guard
   ``dx == 0 and dy == 0``) and two byte-identical private copies in
   ``focthermal.py`` / ``distance.py`` (guard ``length_sq <= 1e-18``). They are
   one public function now, :func:`boardwise.core.measure.point_segment_distance`,
   with the ``length_sq`` guard.

The guard was chosen on data, not taste (``outputs/R2/point_segment_census.json``
and ``outputs/R2/guard_flip_experiment.json``): over the full PCB review of all
14 board fixtures the two guards disagree bitwise on 24 of 6.5 M real calls (all
on edges shorter than 1e-9 mil), and swapping **every** copy to either guard
leaves all 881 PCB findings identical — zero verdict flips. What separates them
is the crash: the exact-zero guard divides by an edge length that underflows to
0.0. Behaviour pins: the zero-flip claim is what the frozen per-fixture tables
(``test_126b`` / ``test_133d`` / ``test_164c`` …) keep holding.
"""

from __future__ import annotations

import math

from boardwise.core import measure
from boardwise.core.geometry import Point
from boardwise.rules.pcb import distance, focthermal


def test_there_is_one_point_to_segment_distance_and_one_point_in_polygon():
    for module in (distance, focthermal):
        for private in ("_point_segment_mil", "_point_segment_distance", "_point_in_outline"):
            assert not hasattr(module, private), f"{module.__name__}.{private} came back"
    assert not hasattr(measure, "_point_segment_distance"), "the private name is retired, not aliased"
    assert distance.point_in_polygon is measure.point_in_polygon
    assert distance.point_segment_distance is measure.point_segment_distance
    assert focthermal.point_segment_distance is measure.point_segment_distance


def test_an_edge_whose_length_underflows_does_not_divide_by_zero():
    # dx = 1e-170 is not zero, but dx*dx underflows to 0.0 — the exact-zero
    # guard's division by (dx*dx + dy*dy) raised ZeroDivisionError here.
    a, b, p = Point(0.0, 0.0), Point(1e-170, 0.0), Point(1.0, 1.0)
    assert (b.x - a.x) != 0.0 and (b.x - a.x) ** 2 == 0.0
    assert measure.point_segment_distance(p, a, b) == math.hypot(1.0, 1.0)


def test_an_edge_shorter_than_a_nanomil_is_a_point():
    a = Point(1000.0, -250.0)
    b = Point(1000.0 + 1e-12, -250.0)
    p = Point(1003.0, -246.0)
    assert measure.point_segment_distance(p, a, b) == math.hypot(3.0, 4.0)
    # ...and an exactly degenerate edge is the same point.
    assert measure.point_segment_distance(p, a, a) == 5.0


def test_an_ordinary_edge_still_measures_to_the_segment():
    a, b = Point(0.0, 0.0), Point(10.0, 0.0)
    assert measure.point_segment_distance(Point(5.0, 3.0), a, b) == 3.0      # perpendicular foot
    assert measure.point_segment_distance(Point(-4.0, 3.0), a, b) == 5.0     # clamped to a
    assert measure.point_segment_distance(Point(13.0, 4.0), a, b) == 5.0     # clamped to b


def test_the_board_outline_check_keeps_its_on_the_edge_is_on_the_board_reading():
    """「贴边不算越界」: the retired copy counted the boundary, and so does core's."""
    outline = [Point(0, 0), Point(100, 0), Point(100, -50), Point(0, -50)]
    on_edge = [Point(50, 0), Point(100, -25), Point(0, -50)]
    inside = [Point(50, -25)]
    assert all(measure.point_in_polygon(p, outline) for p in on_edge + inside)
    assert not measure.point_in_polygon(Point(100.01, -25), outline)
    # The escape distance the outline rule reports: a corner 3 mil past the right edge.
    corners = [Point(90, -20), Point(103, -20), Point(103, -30), Point(90, -30)]
    assert distance._outside_by(corners, outline) == 3.0
    assert distance._outside_by([Point(10, -10), Point(100, -10)], outline) == 0.0
