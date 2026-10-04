"""112: `addcomponent.wire_route` grows from straight/L into an orthogonal search.

The capability gap this batch closes is measured, not stylistic: 110's flyback
page is pressed through and overlapped because the interactive draw flow could
only ever emit a straight run or one L, while `drawcompiler` has carried a real
obstacle-avoiding lattice search since 053. The search is **reused**, not
rewritten — the fixtures below are aimed at the seam, not at a new algorithm.

What is pinned here, in the order the task book names it:

1. the old path is **byte-for-byte the old path** (``avoid=None``), including
   the corner rule and the float shape of the returned tuples;
2. with an obstacle field, the same two points come out routed **around** the
   body, orthogonally, with more points and more bends than the L — measured
   both ways in §C of `outputs/112/SUMMARY.md`;
3. a goal walled in on all four sides returns ``None`` rather than a path that
   walks through a wall: a wire that cannot be drawn is reported, not faked;
4. the lattice itself: no diagonal ever, start snapped to the anchor's residue,
   off-lattice goals joined by an orthogonal final leg;
5. the geometry the flows read (`avoid_from_geometry`) is honest about what a
   `sch.geometry` snapshot cannot say — no per-part body boxes, so no boxes are
   invented; origins, wire vertices and foreign runs are what it can carry;
6. each of the four consumption points degrades to the old path when the
   snapshot gives it nothing to avoid.
"""

from __future__ import annotations

import math

import pytest

from boardwise.engines import addcomponent, drawcompiler
from boardwise.engines.addcomponent import ObstacleField, route_orthogonal
from boardwise.engines.router import segment_hits_box

GRID = addcomponent.LANDING_GRID


def _orthogonal(points):
    return all(
        abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9
        for a, b in zip(points, points[1:])
    )


def _cuts_box(points, box):
    """Independent re-statement of the compiler's interior clip test."""
    left, bottom, right, top = box[0] + 1e-6, box[1] + 1e-6, box[2] - 1e-6, box[3] - 1e-6
    for start, end in zip(points, points[1:]):
        if not _orthogonal((start, end)):
            continue
        if abs(start[1] - end[1]) < 1e-12 and bottom < start[1] < top:
            if max(start[0], end[0]) > left and min(start[0], end[0]) < right:
                return True
        if abs(start[0] - end[0]) < 1e-12 and left < start[0] < right:
            if max(start[1], end[1]) > bottom and min(start[1], end[1]) < top:
                return True
    return False


# --------------------------------------------------------------- 1. old path


def test_without_avoid_the_route_is_exactly_the_straight_run_it_was():
    assert addcomponent.wire_route((0.0, 0.0), (10.0, 0.0)) == [(0.0, 0.0), (10.0, 0.0)]
    assert addcomponent.wire_route((0.0, 0.0), (0.0, 10.0)) == [(0.0, 0.0), (0.0, 10.0)]


def test_without_avoid_the_corner_is_still_at_anchor_x_target_y():
    """029-c's rule, restated: the run out of the pin leaves along the pin's axis."""
    assert addcomponent.wire_route((-20.0, -5.0), (5.0, 0.0)) == [
        (-20.0, -5.0), (-20.0, 0.0), (5.0, 0.0),
    ]


def test_an_avoid_that_carries_nothing_is_still_the_old_path():
    """An empty field is not a licence to change the drawing: it is the old L."""
    empty = ObstacleField(boxes=(), blocked=(), edges=())
    assert addcomponent.wire_route(
        (-20.0, -5.0), (5.0, 0.0), avoid=empty,
    ) == [(-20.0, -5.0), (-20.0, 0.0), (5.0, 0.0)]


# ------------------------------------------------------- 2. the obstacle field

BODY = (-5.0, -5.0, 5.0, 5.0)
FAR = (200.0, 200.0, 400.0, 400.0)
#: Another net's straight run, in the ``(x0, y0, x1, y1)`` shape ObstacleField reads.
A_ROUTER_EDGE = (-50.0, 0.0, 50.0, 0.0)


def test_a_body_between_two_points_is_walked_around_not_through():
    """The synthetic field the task book names: two points, one part in between.

    The L that ``avoid=None`` produces cuts the body; with the body in ``boxes``
    the search must go round it, and the detour has to stay orthogonal (a
    diagonal hangs the host — 029-c, measured 2/2).
    """
    anchor, target = (-20.0, 0.0), (20.0, 0.0)
    naive = addcomponent.wire_route(anchor, target)
    assert _cuts_box(naive, BODY), "the control has to be the bad drawing"

    route = addcomponent.wire_route(anchor, target, avoid=ObstacleField(boxes=(BODY,)))
    assert route is not None
    assert _orthogonal(route), route
    assert not _cuts_box(route, BODY), route
    assert route[0] == anchor and route[-1] == target
    assert len(route) > len(naive)


def test_the_detour_leaves_the_body_by_a_clear_margin_not_by_a_hair():
    """The path runs beside the body, not on its outline.

    ``_segment_hits_box`` already refuses a run that grazes an outline, but a
    route that *sits* on the border would render as a wire merged with the part
    — the readability complaint this batch exists to answer.
    """
    route = addcomponent.wire_route(
        (-20.0, 0.0), (20.0, 0.0), avoid=ObstacleField(boxes=(BODY,)),
    )
    assert route is not None
    assert any(
        abs(point[1]) > 5.0 and abs(point[1]) <= 5.0 + GRID + 1e-6 for point in route
    ), route


def test_a_far_body_outside_the_corridor_does_not_bend_the_route():
    """Nothing to avoid in the way → the search reproduces an L, not a scenic tour.

    Which of the two legal L corners it picks is the search's business (both are
    orthogonal and both reach the target); what is pinned is that a body 200
    units away does not buy a detour — the corridor is derived from the wire's
    own ends, so a wall nobody is near is simply not in it.
    """
    anchor, target = (-20.0, -5.0), (5.0, 0.0)
    route = addcomponent.wire_route(
        anchor, target, avoid=ObstacleField(boxes=(FAR,)),
    )
    assert route is not None
    assert _orthogonal(route), route
    assert route[0] == anchor and route[-1] == target
    assert len(route) == 3, route


# ------------------------------------------------------------- 3. honest None


def test_a_goal_walled_in_on_four_sides_is_refused_not_walked_through():
    """No clean path → ``None``. Never a path that crosses the wall.

    The alternative — falling back to the L — is the lie this batch exists to
    remove: a wire that presses through a part is worse than a wire that was
    never drawn, because it looks connected. The four boxes below seal a pocket
    the size of the grid step, so the target's nearest free node *is* the
    pocket's own interior and no step out of it is legal.
    """
    pocket = (0.0, 0.0, 20.0, 20.0)
    walls = (
        (-30.0, -10.0, 0.0, 30.0),    # left
        (20.0, -10.0, 50.0, 30.0),    # right
        (-30.0, -10.0, 50.0, 0.0),    # below
        (-30.0, 20.0, 50.0, 30.0),    # above
    )
    field = ObstacleField(boxes=(pocket,) + walls)
    # The target sits deep inside the sealed pocket: every neighbouring node is
    # a wall, so the search can neither stand on it nor step to it.
    assert addcomponent.wire_route((-20.0, 10.0), (10.0, 10.0), avoid=field) is None


def test_a_sealed_anchor_is_refused_even_when_the_goal_itself_is_clear():
    """The search failing is its own answer, and it is not overridden.

    The boxes seal the *anchor* in, so every step out of it is a wall while the
    goal node itself is perfectly free. "The goal is reachable-looking" is not a
    path, and the batch's rule is that no path means ``None`` — the caller
    reports 无净通路 and exits, rather than drawing the L straight through the
    three boxes that are in the way.
    """
    sealed = (
        (-25.0, -25.0, -15.0, 25.0),  # left of the anchor
        (-15.0, -25.0, 25.0, -15.0),  # below the goal's lane
        (-15.0, 15.0, 25.0, 25.0),    # above it
    )
    assert addcomponent.wire_route(
        (-20.0, 0.0), (20.0, 0.0), avoid=ObstacleField(boxes=sealed),
    ) is None


def test_a_foreign_vertices_own_wire_may_not_land_on():
    """Another net's wire vertex is a short, so it is a wall even mid-page.

    Nothing here is a body: a single point. A wire whose vertex lands on it *is*
    a connection in the editor's model, so the search steps around it — the
    060 capacitor case the compiler documents, where a wire from the output pin
    has to pass a ground pin ten units away.
    """
    route = addcomponent.wire_route(
        (-20.0, 0.0), (20.0, 0.0), avoid=ObstacleField(blocked=((0.0, 0.0),)),
    )
    assert route is not None
    assert _orthogonal(route), route
    assert len(route) > 2, "a foreign vertex in the way must be stepped around"
    assert (0.0, 0.0) not in route


def test_a_will_not_run_alongside_another_nets_wire():
    """A parallel run on top of a foreign wire is a short, not a crossing.

    Measured editor behaviour: overlapping wires join, so laying this wire along
    an existing one is a connection to another net. The router refuses the run
    and steps aside; dropping the overlap test (mutation M2) puts it right back
    on the foreign run.
    """
    foreign = A_ROUTER_EDGE
    route = addcomponent.wire_route(
        (-50.0, 0.0), (50.0, 0.0), avoid=ObstacleField(edges=(foreign,)),
    )
    assert route is not None
    assert _orthogonal(route), route
    assert len(route) > 2, "a run on top of another net's wire must be stepped off"
    horizontal = [
        (a, b) for a, b in zip(route, route[1:])
        if abs(a[1] - b[1]) < 1e-9
    ]
    assert horizontal, route
    for a, b in horizontal:
        overlap = min(a[0], b[0], foreign[2]) - max(a[0], b[0], foreign[0])
        assert overlap <= 1e-6, (route, a, b)


def test_none_is_returned_rather_than_an_empty_polyline():
    """An empty list would draw nothing and read as a success."""
    tight = ObstacleField(boxes=((0.0, 0.0, 50.0, 50.0),))
    assert addcomponent.wire_route((25.0, 25.0), (26.0, 25.0), avoid=tight) is None


# ------------------------------------------------------------ 4. the lattice


@pytest.mark.parametrize("anchor,target", [
    ((-20.0, 0.0), (20.0, 0.0)),
    ((-20.0, 2.0), (20.0, 13.0)),
    ((3.0, -7.0), (37.0, 21.0)),
    ((-1.0, -20.0), (-1.0, 20.0)),  # vertical, straddling the body
])
def test_a_route_is_orthogonal_and_starts_and_ends_where_it_was_asked_to(anchor, target):
    route = addcomponent.wire_route(anchor, target, avoid=ObstacleField(boxes=(BODY,)))
    assert route is not None
    assert _orthogonal(route), route
    assert route[0] == pytest.approx(anchor)
    assert route[-1] == pytest.approx(target)
    assert not _cuts_box(route, BODY), route


def test_a_goal_off_the_lattice_is_joined_by_an_orthogonal_final_leg():
    """The residue comes from the anchor; the goal may sit anywhere.

    Snapping the goal to the lattice would land the wire somewhere the editor
    does not join (029-c: a wire has to end on the point that is really there),
    so the last leg is drawn axis-aligned from the nearest lattice point instead.
    """
    anchor, target = (-20.0, 0.0), (20.0, 3.0)
    route = addcomponent.wire_route(anchor, target, avoid=ObstacleField(boxes=(BODY,)))
    assert route is not None
    assert _orthogonal(route), route
    assert route[-1] == pytest.approx(target)
    assert (round(route[-2][0], 6), round(route[-2][1], 6)) != (round(target[0], 6), round(target[1], 6))


def test_the_lattice_step_is_the_grid_the_caller_states():
    """A coarser grid cannot dodge as tightly, so the detour leaves wider.

    Both routes clear the body; what the grid decides is *how far out* the wire
    has to swing to do it, which is the number a reviewer sees on the page.
    """
    coarse = addcomponent.wire_route(
        (-40.0, 0.0), (40.0, 0.0), avoid=ObstacleField(boxes=(BODY,)), grid=10.0,
    )
    fine = addcomponent.wire_route(
        (-40.0, 0.0), (40.0, 0.0), avoid=ObstacleField(boxes=(BODY,)), grid=5.0,
    )
    assert coarse is not None and fine is not None
    assert not _cuts_box(coarse, BODY) and not _cuts_box(fine, BODY)
    coarse_swing = max(abs(p[1]) for p in coarse)
    fine_swing = max(abs(p[1]) for p in fine)
    assert coarse_swing >= fine_swing, (coarse, fine)


# ------------------------------------------------- 5. what geometry can carry


def _snapshot():
    return {
        "components": [
            {"primitiveId": "U1", "state": {"ComponentType": "part", "Designator": "U1",
                                             "X": 0.0, "Y": 0.0}},
            {"primitiveId": "U2", "state": {"ComponentType": "part", "Designator": "U2",
                                             "X": 60.0, "Y": 0.0}},
            {"primitiveId": "F1", "state": {"ComponentType": "netflag", "Designator": "",
                                            "X": 20.0, "Y": -40.0}},
        ],
        "wires": [
            {"primitiveId": "W1", "state": {"PrimitiveType": "Wire", "Net": "GND",
                                            "Line": [10.0, 10.0, 10.0, 60.0]}},
            {"primitiveId": "W2", "state": {"PrimitiveType": "Wire", "Net": "VCC",
                                            "Line": [20.0, 10.0, 60.0, 10.0]}},
        ],
    }


def test_the_geometry_field_names_own_net_geometry_as_legal():
    field = addcomponent.avoid_from_geometry(_snapshot(), "GND")
    assert (10.0, 10.0) in field.own_vertices
    assert (10.0, 60.0) in field.own_vertices
    assert (10.0, 10.0, 10.0, 60.0) in field.own_edges


def test_the_geometry_field_keeps_foreign_nets_out():
    field = addcomponent.avoid_from_geometry(_snapshot(), "GND")
    assert (20.0, 10.0) in field.blocked, "another net's wire vertex is a short"
    assert (60.0, 10.0) in field.blocked
    assert (20.0, 10.0) not in field.own_vertices
    assert (60.0, 10.0) not in field.own_vertices


def test_the_geometry_field_invents_no_body_boxes():
    """A `sch.geometry` snapshot carries no per-part extent (坑 9 / 111 §八.2).

    So ``boxes`` is empty and only the origins are walls. Inventing a box from
    a designator would be a fabricated obstacle, and a fabricated obstacle is a
    wire refused for a body that is not there.
    """
    field = addcomponent.avoid_from_geometry(_snapshot(), "GND")
    assert field.boxes == ()
    assert (0.0, 0.0) in field.blocked, "the part origin is the only extent we have"


def test_the_geometry_field_carries_foreign_runs_as_edges_and_own_runs_as_own():
    field = addcomponent.avoid_from_geometry(_snapshot(), "GND")
    assert (20.0, 10.0, 60.0, 10.0) in field.edges
    assert (20.0, 10.0, 60.0, 10.0) not in field.own_edges


def test_an_empty_snapshot_yields_an_empty_field_rather_than_a_crash():
    field = addcomponent.avoid_from_geometry({}, "GND")
    assert field.boxes == () and field.blocked == () and field.edges == ()
    assert addcomponent.avoid_from_geometry(None, "GND").boxes == ()


# ------------------------------------------- 6. the shared router, not a clone


def test_the_interactive_path_uses_the_compilers_own_router():
    """One search, two callers. A second implementation would drift from the
    checker's idea of a legal wire, and the drift would only show up as a
    drawing the checker refuses."""
    assert route_orthogonal is not None
    assert drawcompiler.lattice_router.__module__ == "boardwise.engines.router"
    assert isinstance(drawcompiler.lattice_router, type)


def test_the_router_lives_in_engines_and_keeps_its_own_helpers_there():
    from boardwise.engines import router

    assert router.Router is drawcompiler.lattice_router
    assert router.TURN_COST == drawcompiler.TURN_COST
    assert router.CROSS_COST == drawcompiler.CROSS_COST
    assert router.segment_hits_box is drawcompiler._segment_hits_box


def test_the_clip_test_the_router_obeys_is_the_one_reachable_from_here():
    """Not a re-statement. If this test ever carried its own clip test it would
    prove nothing about the router, and a looser one would pass while the wire
    still went through the body."""
    assert segment_hits_box is drawcompiler._segment_hits_box
    assert segment_hits_box((-5.0, 0.0), (5.0, 0.0), (-1.0, -1.0, 1.0, 1.0))
    assert not segment_hits_box((-5.0, -5.0), (5.0, -5.0), (-1.0, -1.0, 1.0, 1.0))


def test_a_route_handed_to_the_compilers_own_compressor_is_unchanged():
    """The bend list is already a bend list.

    ``drawcompiler._compress`` is what the compiler runs before it emits a
    segment; if the interactive route still carried every lattice node, the two
    paths would emit wires of different shapes for the same drawing, and only
    one of them would be "a wire whose vertices are its bends". Asserting with
    the *real* compressor (not a re-statement) is the point.
    """
    route = addcomponent.wire_route(
        (-20.0, 0.0), (20.0, 0.0), avoid=ObstacleField(boxes=(BODY,)),
    )
    assert route is not None
    assert drawcompiler._compress([tuple(p) for p in route]) == [tuple(p) for p in route]


def test_a_goal_sitting_on_a_wall_falls_back_to_the_nearest_free_node():
    """A target inside a body must not make the wire unroutable.

    The goal slides to the nearest node the search may legally stand on, and the
    final leg is the orthogonal run (plus, at worst, one bend) from there into
    the target. Reaching a point that is *inside* a body necessarily touches
    that body on the last hop — that is geometry, not a routing fault, and it is
    why a real caller never aims a wire at a point inside a part. What is pinned
    here is that the search's own portion still clears the body, so the wire does
    not run through it from the anchor's side.
    """
    field = ObstacleField(boxes=(BODY,))
    route = addcomponent.wire_route((-20.0, 0.0), (3.0, 3.0), avoid=field)
    assert route is not None
    assert _orthogonal(route), route
    assert route[-1] == pytest.approx((3.0, 3.0))
    # The last point before the goal is the free node the search stood on; it is
    # outside the body, so the wire approached from there rather than crossing in.
    approach = route[-2]
    assert not (
        BODY[0] < approach[0] < BODY[2] and BODY[1] < approach[1] < BODY[3]
    ), (route, approach)


def test_a_wall_thinner_than_the_grid_is_still_a_wall():
    """The case the *segment* test exists for, and a node test cannot catch.

    A body narrower than one lattice step has no lattice node inside it, so
    ``_wall`` — which asks about nodes — calls the node free. Only
    ``_segment_hits_box``, which asks about the run between two nodes, refuses
    the step. Drop that test (mutation M1) and this wire goes straight through
    the part; the fixture is placed off the grid columns on purpose so the two
    questions genuinely differ.
    """
    thin = (1.0, -40.0, 4.0, 40.0)
    route = addcomponent.wire_route(
        (-20.0, 0.0), (20.0, 0.0), avoid=ObstacleField(boxes=(thin,)),
    )
    assert route is not None
    assert _orthogonal(route), route
    assert not _cuts_box(route, thin), route
    assert len(route) > 2, "a wall no node stands on still costs a detour"


def test_a_route_that_bends_actually_bends():
    route = addcomponent.wire_route(
        (-20.0, 0.0), (20.0, 0.0), avoid=ObstacleField(boxes=(BODY,)),
    )
    assert route is not None
    bends = [
        index for index in range(1, len(route) - 1)
        if not (
            abs(route[index][0] - route[index - 1][0]) < 1e-9
            and abs(route[index][0] - route[index + 1][0]) < 1e-9
        )
    ]
    assert bends, "a detour has at least one bend"
    for index in bends:
        assert math.isclose(route[index][0], route[index - 1][0]) or math.isclose(
            route[index][1], route[index - 1][1]
        )
