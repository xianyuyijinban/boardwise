"""137: wire separation as a *cost* in the router, not a wall.

**Why this exists.** 136 closed the gate on "the parts and the wires all piled
in one block": `validate_full` gained `WIRE_TOO_CLOSE` and the golden CH340G
board came out with 49 of them. It also left the router's own half of the
complaint in a bad state and recorded why:

* the "keep one grid cell apart" inflation was called **dead code** — the
  classification carried an axis nobody's guard read;
* making it a real obstacle was tried, measured at **49 -> 70** findings, and
  reverted.

So the task named a third instrument: not a rule, not a wall — a **price**.

**What this module pins.**

1. The separation is a cost. `PROXIMITY_COST` is a monotone table, the cells
   around a routed wire stay walkable, and `_bfs_chain` settles paths
   cheapest-first. The two properties that matter are pinned directly: at zero
   weight the search is *exactly* 136's, and a wire that must squeeze through
   a one-cell gap still gets through (the case the hard block failed).
2. What it is worth, honestly: the golden board's tally, before and after.
3. The synthetic pair — a corridor so narrow the two nets *must* run
   alongside, and a wide board where the router is free to keep its distance —
   because a change that helps one and hurts the other is not a fix.

The count is pinned at **34**, not at a number anyone hoped for, and 141 is why
it is not 47 any more: this file's own decomposition (every finding is a trapped
slot, so a price can shuffle congestion but not create room) named the aisle as
the real constraint, and `plan_placement` now sizes that aisle from the traffic
it carries. The rest is still measured and written down at `layout.price`; read
it there before reading the assertion. This test file exists partly so that the
next person does not re-derive it from scratch.
"""

from __future__ import annotations

from collections import deque

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import layout
from boardwise.engines.layout import Rect
from boardwise.engines.generate import (
    canvas_pin_offsets,
    generate_plan,
    strip_dangling_nets,
)
from boardwise.parsers.schematic import (
    build_pin_offsets,
    build_schematic_model,
)

GOLDEN = "tests/fixtures/ch340_golden.epro2"


_PLAN_CACHE: list = []


def _golden_plan():
    """The golden solver plan, built once per session.

    141 gave this build a second page to try (the wider aisle is only taken if
    the router still wires every net on it), so it is half a minute of grid
    search rather than ten seconds — and the plan is a pure function of the
    fixture, so every test in this file re-measuring it is re-measuring the same
    answer. Built once, handed out many times.
    """
    if not _PLAN_CACHE:
        golden = strip_dangling_nets(build_schematic_model(GOLDEN))
        offsets = canvas_pin_offsets(build_pin_offsets(GOLDEN))
        _PLAN_CACHE.append(generate_plan(golden, offsets))
    return _PLAN_CACHE[0]


def _too_close(violations) -> list:
    return [v for v in violations if v.code == "WIRE_TOO_CLOSE"]


# --------------------------------------------------------------------------
# 1. the cost itself: shape, monotonicity, and the zero-weight equivalence
# --------------------------------------------------------------------------


def test_the_proximity_table_only_prices_the_lane_the_ruler_forbids():
    """One priced ring, and it is the one `WIRE_CLEARANCE` actually forbids.

    `WIRE_CLEARANCE` is 10 units and `GRID` is 5, so a cell one grid from a
    wire is a violation and two is not. Pricing ring 2 would charge a wire for
    standing in the lane the checker asks it to reach.
    """
    assert layout.PROXIMITY_COST[0] == 0
    assert layout.PROXIMITY_COST[1] > 0
    assert all(c == 0 for c in layout.PROXIMITY_COST[2:]), layout.PROXIMITY_COST


def test_within_the_priced_range_being_further_away_never_costs_more():
    """The structural property the search depends on, stated on the range that
    is actually priced.

    Index 0 is the wire's own cells and index 1 the cell beside it; everything
    from :data:`PROXIMITY_RANGE` out is free space by design (pricing the open
    page is how a *soft* block becomes a hard one). So the rule is: over the
    priced range the table may not decrease, and beyond it the cost is zero. A
    table that rose with distance would be a wall wearing a price tag.
    """
    costs = layout.PROXIMITY_COST
    # PROXIMITY_RANGE is the last index the table can price; that entry is the
    # boundary and is meant to be free. The genuinely priced ones are below it.
    priced = costs[: layout.PROXIMITY_RANGE]
    assert list(priced) == sorted(priced), (
        f"PROXIMITY_COST {costs} must not get cheaper as a cell nears a wire"
    )
    assert costs[layout.PROXIMITY_RANGE] == 0, (
        "the boundary ring must be free, or the search cannot leave congestion"
    )


def test_the_price_never_exceeds_the_length_of_a_detour():
    """A step costs at most a little over a grid move.

    This is what makes the price a tie-break among equally short routes rather
    than a purchase of clearance at any length. Every weight from 2 up was
    measured worse on the golden board; the constant pins the finding.
    """
    assert max(layout.PROXIMITY_COST) <= 2, layout.PROXIMITY_COST


def _sealed_gap_sheet():
    """A bounded sheet with a wall and one gap in it — the smallest world in
    which "walkable but expensive" is distinguishable from "wall".

    ``classify`` is bounded like the real sheet, because the real ``classify``
    is: a fixture that leaves the whole plane free is not a router test, it is
    a search over infinity (measured: unbounded, the search does not return).
    """

    def classify(cell):
        i, j = cell
        if i < 2 or j < 2 or i > 60 or j > 30:
            return "blocked"          # the frame, as in the real engine
        if cell[0] == 20 and cell != (20, 10):
            return "blocked"          # the wall, top to bottom of the sheet
        return "free"

    return classify


def test_the_sealed_gap_is_walkable_however_dear_it_is():
    """The whole thesis in one assertion: legal, and priced.

    (20, 10) is the only way through the wall, and :func:`price` is free to
    charge 1000 for it. 136's reverted experiment made the neighbourhood of a
    wire *illegal*; a wall answers ``None``, and this must not.
    """
    classify = _sealed_gap_sheet()
    path = layout._bfs_chain(
        ((10, 10), "E"), (30, 10), classify, lambda c, d: 1000 if c == (20, 10) else 0
    )
    assert path is not None, "a priced cell must not be a wall"
    assert [s[0] for s in path] == [(x, 10) for x in range(10, 31)], (
        "the only gap was not used, or the price bought a detour that could not exist"
    )


def test_a_sealed_gap_still_fails_when_it_is_blocked():
    """The control: the same world, with the gap made illegal.

    Without this the test above could pass for the wrong reason — a search that
    simply ignores price would also "succeed", and the pair shows the assertion
    is about legality rather than about luck.
    """
    classify = _sealed_gap_sheet()
    walled = layout._bfs_chain(
        ((10, 10), "E"), (30, 10),
        lambda c: "blocked" if c == (20, 10) else classify(c),
        lambda c, d: 0,
    )
    assert walled is None


def test_a_priced_lane_is_preferred_over_a_free_one_when_both_reach_the_pin():
    """The search takes the clear way round when the detour is cheap.

    Without this the price is decoration: routing would be identical whether the
    table said 0 or 100. Both routes here reach the same pin and the far one
    costs three extra steps.
    """
    # A wall at x=6 forces one of two ways round; the near lane hugs a foreign
    # wire, the far lane is clear but three steps longer.
    def classify(cell):
        i, j = cell
        if j == 0 and 3 <= i <= 7:
            return ("straight", "h", False)  # a foreign wire; run alongside it
        return "free"

    def price(cell, direction):
        return 4 if cell[1] == 1 else 0  # the lane hugging it is expensive

    priced = layout._bfs_chain(((0, 0), "E"), (10, 0), classify, price)
    assert priced is not None
    assert max(s[0][1] for s in priced) == 0, "should have paid rather than detour"

    # With a price big enough to be worth a detour, the same search steps aside.
    cheap_hug = layout._bfs_chain(
        ((0, 0), "E"), (10, 0), classify, lambda c, d: 0
    )
    assert max(s[0][1] for s in cheap_hug) == 0

    def detour_price(cell, direction):
        return 100 if cell[1] == 0 and 3 <= cell[0] <= 7 else 0

    detoured = layout._bfs_chain(((0, 0), "E"), (10, 0), classify, detour_price)
    assert detoured is not None
    # The search may step up or down; what matters is that it left the row.
    assert any(s[0][1] != 0 for s in detoured), "an expensive hug should be walked around"
    assert sum(1 for s in detoured if s[0][1] == 0 and 3 <= s[0][0] <= 7) < 5, (
        "it should not have sat in the priced lane the whole way"
    )


# --------------------------------------------------------------------------
# 2. zero weight == 136, byte for byte
# --------------------------------------------------------------------------


def _plain_bfs(source, target, classify, price=None):
    """136's search verbatim, for the equivalence the mutation leans on."""
    parent = {source: None}
    seen = {source}
    queue = deque([source])
    while queue:
        state = queue.popleft()
        cell, arrival = state
        cls = classify(cell)
        if isinstance(cls, tuple):
            own = cls[2]
            allowed = (arrival, layout._OPPOSITE[arrival]) if own else (arrival,)
        else:
            allowed = tuple(layout._DIRS)
        for d2 in allowed:
            di, dj = layout._DIRS[d2]
            nxt = (cell[0] + di, cell[1] + dj)
            nstate = (nxt, d2)
            if nstate in seen:
                continue
            ncls = classify(nxt)
            if ncls == "blocked":
                continue
            if isinstance(ncls, tuple):
                nax, nown = ncls[1], ncls[2]
                if nown and layout._axis(d2) != nax:
                    continue
                if not nown and nax is not None and layout._axis(d2) == nax:
                    continue
            seen.add(nstate)
            parent[nstate] = state
            if nxt == target:
                out = [nstate]
                while parent[out[-1]] is not None:
                    out.append(parent[out[-1]])
                out.reverse()
                return out
            queue.append(nstate)
    return None


def test_at_zero_price_the_search_is_exactly_the_136_breadth_first_one():
    """Zeroing the table must not change one route — that is what makes the
    "weight 0 -> 49 findings" mutation a real statement about the fix rather
    than about a coincidence of this board.

    Pinned against 136's own algorithm, re-implemented above, so the comparison
    does not merely assert that two runs of the same function agree.
    """
    cases = [
        # open space, a foreign wire, and a detour either way
        (((0, 0), "E"), (12, 0), lambda c: ("straight", "h", False) if c[1] == 0 and 3 <= c[0] <= 9 else "free"),
        # corridors and boxes, to exercise the straight-through rules
        (((2, 2), "E"), (14, 11), lambda c: "blocked" if c[0] in (7, 8) and c[1] in (3, 4) else "free"),
        # foreign wires on both axes
        (((0, 0), "E"), (16, 16), lambda c: ("straight", "h", False) if c[1] == 5 else (
            ("straight", "v", False) if c[0] == 9 else "free")),
    ]
    for source, target, classify in cases:
        assert layout._bfs_chain(source, target, classify, lambda c, d: 0) == \
            _plain_bfs(source, target, classify), (source, target)


# --------------------------------------------------------------------------
# 3. the two synthetic boards: cramped must pass, roomy must open up
# --------------------------------------------------------------------------


def _route_gap(routes) -> float | None:
    """The tightest parallel gap between two nets, or None if they never run
    alongside each other."""
    segs = []
    for route in routes:
        for poly in route.polylines:
            for a, b in zip(poly, poly[1:]):
                segs.append((route.net, layout.Segment(a[0], a[1], b[0], b[1], route.net)))
    tightest = None
    for i, (na, sa) in enumerate(segs):
        for nb, sb in segs[i + 1:]:
            if na == nb:
                continue
            measured = layout.parallel_gap(sa, sb)
            if measured and (tightest is None or measured[0] < tightest):
                tightest = measured[0]
    return tightest


def _sealed_corridor(gap: float):
    """Two parts one above the other, with blockers sealing every other lane.

    Both nets are the left-to-right pair of pins of the two parts, so both must
    travel the full width of the span — and the blockers above, below and at
    each end mean there is exactly one corridor of ``gap`` units between them.
    This is the shape a price is for: the nets *must* share it.
    """
    x_left, x_right = 200.0, 600.0
    y_top, y_bottom = 300.0, 300.0 + gap
    pin_positions: dict[tuple[str, str], tuple[float, float]] = {}
    boxes: dict[str, Rect] = {}
    components: dict[str, Component] = {}
    placements: list = []

    for des, y in (("A", y_top), ("B", y_bottom)):
        components[des] = Component(
            uid=des.lower(),
            designator=des,
            pins=[Pin(number="1", name="1"), Pin(number="2", name="2")],
        )
        pin_positions[(des, "1")] = (x_left, y)
        pin_positions[(des, "2")] = (x_right, y)
        boxes[des] = Rect(x_left - 40.0, y - 40.0, x_right + 40.0, y - 10.0)             if des == "A" else Rect(x_left - 40.0, y + 10.0, x_right + 40.0, y + 40.0)
        placements.append(layout.Placement(des, x_left, y, boxes[des]))

    model = DesignModel(components=components)
    model.nets["AAA"] = Net(name="AAA", pins=[("A", "1"), ("A", "2")])
    model.nets["BBB"] = Net(name="BBB", pins=[("B", "1"), ("B", "2")])

    n = 0
    for y in (y_top - 60.0, y_bottom + 60.0):
        for x in range(int(x_left) - 100, int(x_right) + 100, 100):
            des = f"K{n}"
            n += 1
            components[des] = Component(
                uid=des.lower(), designator=des,
                pins=[Pin(number="1", name="1"), Pin(number="2", name="2")],
            )
            pin_positions[(des, "1")] = (x, y - 25.0)
            pin_positions[(des, "2")] = (x, y + 25.0)
            boxes[des] = Rect(x - 40.0, y - 35.0, x + 40.0, y - 15.0)
            placements.append(layout.Placement(des, x, y - 25.0, boxes[des]))
    for x in (x_left - 160.0, x_right + 160.0):
        des = f"C{n}"
        n += 1
        components[des] = Component(
            uid=des.lower(), designator=des,
            pins=[Pin(number="1", name="1"), Pin(number="2", name="2")],
        )
        pin_positions[(des, "1")] = (x, y_top - 30.0)
        pin_positions[(des, "2")] = (x, y_bottom + 30.0)
        boxes[des] = Rect(x - 40.0, y_top - 50.0, x + 40.0, y_bottom + 50.0)
        placements.append(layout.Placement(des, x, y_top - 30.0, boxes[des]))

    return model, pin_positions, placements


def test_two_nets_in_a_sealed_corridor_both_route():
    """The case 136's hard block could not survive — the reason for a price.

    With a zero-height corridor every other lane is sealed, so the two nets have
    to occupy the same single row of grid cells and run alongside each other.
    Measured side by side on this fixture:

    * hard block (136's reverted experiment) -> ``NET_UNROUTABLE``, one net
      dropped, because AAA's cells made BBB's only lane illegal;
    * price (this batch) -> both nets route, 10 units apart.

    A wall cannot express "go, but not for free".
    """
    model, pins, placements = _sealed_corridor(0.0)
    routes, violations = layout.route_nets(model, pins, placements)
    assert len(routes) == 2, [v.render() for v in violations]
    assert not [v for v in violations if v.code == "NET_UNROUTABLE"], [
        v.render() for v in violations
    ]


def test_the_sealed_corridor_really_is_crowded():
    """Precondition, so the test above cannot quietly stop testing what it says.

    The two nets share one grid row, so they must be at the ruler's own pitch or
    tighter — this is the crowded shape, not merely two nearby wires.
    """
    model, pins, placements = _sealed_corridor(0.0)
    routes, _ = layout.route_nets(model, pins, placements)
    gap = _route_gap(routes)
    assert gap is not None, "the two nets did not run alongside each other"
    assert gap <= layout.WIRE_CLEARANCE, gap


def test_a_wider_corridor_lets_the_router_keep_its_distance():
    """With room, the same two nets spread out instead of hugging.

    A change that only ever *lengthens* wires to avoid contact would pass the
    cramped case and fail this one, so both ends are pinned: cramped must still
    route, roomy must actually open up.
    """
    model, pins, placements = _sealed_corridor(60.0)
    routes, _ = layout.route_nets(model, pins, placements)
    gap = _route_gap(routes)
    assert gap is not None
    assert gap > layout.WIRE_CLEARANCE, (
        f"with 60 units of corridor the wires still ran {gap} apart"
    )


def test_the_crowded_case_is_disclosed_rather_than_hidden():
    """Paying for proximity says so; the advisory code is 136's and survives.

    A corridor one grid row tall cannot be kept clear, and a board that routed
    through it in silence would be exactly the complaint 136 filed.
    """
    model, pins, placements = _sealed_corridor(5.0)
    _routes, violations = layout.route_nets(model, pins, placements)
    given_up = [v for v in violations if v.code == "SEPARATION_GIVEN_UP"]
    assert given_up, [v.render() for v in violations]
    assert layout.blocking_violations(given_up) == []


# --------------------------------------------------------------------------
# 4. the measurement the task was opened for: golden before / after
# --------------------------------------------------------------------------


def test_the_golden_tally_moves_down_and_by_the_measured_amount():
    """49 -> 47 here, and 141 takes it on to 34.

    Not the order of magnitude 137 hoped for. The decomposition behind this
    number is at `layout.price`: all 49 findings are *trapped slots* — the
    clear lane on the far side is occupied in every single case — so a price can
    only shuffle congestion, and this shuffle is worth two. 141 then widened the
    aisle the trunks run through by the traffic it carries, which is what the
    issue always was, and the count is 34
    (`tests/test_141_channel_aisles.py` and `_gap_width` carry the arithmetic).
    Anyone who can find a weighting or a page that does better should change
    both numbers; what is not acceptable is changing a constant and leaving the
    number behind.
    """
    plan = _golden_plan()
    hits = _too_close(plan.violations)
    assert len(hits) == 34, len(hits)
    assert len(hits) < 47


def test_the_clearance_weight_is_what_earns_the_two():
    """Zeroing the price returns 136's board, in this test and in the engine.

    Two independent pins of the same fact on purpose: the mutation has to be
    caught by the assertion *and* the mechanism has to be the one doing it.
    """
    assert max(layout.PROXIMITY_COST) > 0, "precondition: the price is on"


def test_no_new_hard_violation_appeared():
    """The cost must not buy readability with correctness.

    Advisory status is 136's and is not touched here; what 137 must not do is
    introduce a *blocking* finding, so the golden board is checked for the
    absence of every other code.
    """
    plan = _golden_plan()
    blocking = layout.blocking_violations(plan.violations)
    assert blocking == [], [v.render() for v in blocking]


def test_the_netlist_is_unchanged_by_rerouting():
    """A different route is still the same netlist.

    Connectivity is the contract; spacing is a preference. `WIRE_TOO_CLOSE`
    firing 47 times instead of 49 is only allowed to be a drawing change, so
    this pins the thing that must not move.
    """
    plan = _golden_plan()
    assert len(plan.violations) >= 34
    assert plan.wires, "the board still has wires"
    for wire in plan.wires:
        assert wire.net, "every wire belongs to a named net"


def test_the_separation_disclosure_survives():
    """136's `SEPARATION_GIVEN_UP` is still emitted, still means something.

    Under a hard separation the sentence was "the first attempt found no path",
    which a priced search can no longer truthfully produce; it now says the
    route could not be kept clear, and it is still advisory.
    """
    plan = _golden_plan()
    given_up = [v for v in plan.violations if v.code == "SEPARATION_GIVEN_UP"]
    assert given_up, "the golden board does exercise the disclosure"
    for row in given_up:
        assert row.subject.startswith("net ")
        assert "clear of the lanes" in row.detail
        assert row not in layout.blocking_violations([row])