"""141: the aisle between two columns is sized by the nets that have to cross it.

**Why this exists.** Two batches ended on the same sentence. 136 reported the
golden CH340G page's 49 pairs of nets running 5 units apart; 137 made the
router *pay* for proximity and earned two of them back (49 -> 47), and both
entries left the real finding written down instead: the drawing is what it is
because the gaps it has to run wires through are too narrow for the traffic, and
no price can create width.

141 measured the width, and the first thing the measurement did was delete the
culprit the earlier note named:

* ``ROW_CHANNEL`` is not it. 60 -> 120 reports **47 findings at every value**
  (``evidence/141/probe_sweep.txt``) and only makes the page taller. The
  channel between the two shelves carries four to five nets, which is what 60
  units holds; the page's "six nets on one line" rows are the *pin-tip* rows of
  the two shelves, not a channel at all;
* the aisles are. The golden page is two shelves deep, and the aisle between
  ``U5`` and ``USB1`` is 40 units — seven grid lanes — with six nets to run
  through it and four of them on a 5-unit pitch. ``WIRE_CLEARANCE`` is 10, so
  40 units hold four nets apart: two pairs are drawn too close whatever the
  router does. That one aisle is 45% of the findings;
* uniform widening is not it either: ``COL_AISLE`` 50/60/70/80 lands on 31/33/6/6
  findings **and** 2-3 ``NET_UNROUTABLE``, because spending width on every gap
  re-wraps the shelves and the parts that have to talk to each other end up in
  different rows (``evidence/141/probe_blocking.txt``);
* a stronger price is not it: (0,2,0) through (0,50,0) all report 61-64.

So the fix is width spent **only where the traffic is**, which is what
``plan_placement`` now does: each aisle is sized from the number of nets whose
pins leave the boxes on either side of it (``layout.net_exits``), the page is
laid out again with those aisles, and the *rows* — which parts sit together —
are not revisited.

**What it is worth, honestly.** 47 -> **34** findings on the golden board, page
area 1090x365 against 1090x350 (**+4.3%**). Not the "under 20" the task hoped
for, and the reason is measured rather than argued: every page that reaches
6-13 findings (the aisle at 55, 60, 70 or 80 units) loses one or two nets to
``NET_UNROUTABLE``, and a page that cannot be wired is not a better drawing.
``evidence/141/probe_scan_fine.txt`` has the whole table. The questions the
router would have to answer to go further are recorded in the 141 handover:
the loss is *order* sensitivity (the same net routes perfectly well alone and is
sealed by whoever went first), not a property of the geometry.
"""

from __future__ import annotations

from collections import Counter

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import generate, layout
from boardwise.engines.generate import (
    canvas_pin_offsets,
    generate_plan,
    strip_dangling_nets,
)
from boardwise.parsers.schematic import build_pin_offsets, build_schematic_model

GOLDEN = "tests/fixtures/ch340_golden.epro2"

_CACHE: dict[str, object] = {}


def _golden():
    """The golden model, offsets and plan, built once (each is seconds of work)."""
    if "plan" not in _CACHE:
        model = strip_dangling_nets(build_schematic_model(GOLDEN))
        offsets = canvas_pin_offsets(build_pin_offsets(GOLDEN))
        _CACHE["model"] = model
        _CACHE["offsets"] = offsets
        _CACHE["plan"] = generate_plan(model, offsets)
    return _CACHE["model"], _CACHE["offsets"], _CACHE["plan"]


def _content_bbox(plan) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for place in plan.geometry:
        if place.bbox:
            xs += [place.bbox.x0, place.bbox.x1]
            ys += [place.bbox.y0, place.bbox.y1]
    for wire in plan.wires:
        for x, y in wire.points:
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------------
# 1. the rule: a gap is as wide as the nets crossing it need
# --------------------------------------------------------------------------


def test_a_gap_holds_as_many_nets_as_it_is_asked_to():
    """``_gap_width`` is the ruler in the packer's units.

    ``WIRE_CLEARANCE`` is 10 and one grid unit at each end keeps the outermost
    lanes off the boxes, so ``d`` nets abreast want ``10 * d`` units and the
    packing's own gap is the floor. The numbers here are the arithmetic the
    golden page's measurements land on: an aisle of 40 is where four nets fit
    and the fifth is one lane too many.
    """
    assert layout._gap_width(1, 40.0) == 40.0
    assert layout._gap_width(4, 40.0) == 40.0
    assert layout._gap_width(5, 40.0) == 50.0
    assert layout._gap_width(6, 40.0) == 60.0
    assert layout._gap_width(7, 40.0) == 70.0
    # never narrower than the packing's own gap
    for demand in range(0, 9):
        assert layout._gap_width(demand, 40.0) >= 40.0


def test_stepping_down_can_only_ever_give_back_the_width_it_added():
    """The fallback's lever: fewer nets accounted for, never a narrower gap."""
    for demand in range(0, 9):
        widths = [layout._gap_width(demand, 40.0, spare) for spare in range(0, 4)]
        assert widths == sorted(widths, reverse=True), (demand, widths)
    # a spare big enough for the whole demand is the packing's own gap again
    for demand in range(0, 5):
        assert layout._gap_width(demand, 40.0, demand + 1) == 40.0


def _funnel_board(count: int = 5) -> tuple[DesignModel, dict]:
    """Two parts in one shelf with ``count`` nets running between them.

    The shape the aisle rule is for: every net leaves one part on the edge that
    faces the other, and their pins sit at different heights, so each net needs
    a lane of its own inside the aisle rather than a crossing.
    """
    left, right = [], []
    components: dict[str, Component] = {}
    for index in range(count):
        name = f"N{index + 1}"
        left.append(Pin(number=str(index + 1), name=str(index + 1), net=name))
        right.append(Pin(number=str(index + 1), name=str(index + 1), net=name))
    components["U"] = Component(uid="u", designator="U", pins=left)
    components["V"] = Component(uid="v", designator="V", pins=right)
    model = DesignModel(components=components)
    for index in range(count):
        name = f"N{index + 1}"
        model.nets[name] = Net(name=name, pins=[("U", str(index + 1)), ("V", str(index + 1))])
    offsets = {
        "U": {str(i + 1): (80.0, float(i * 20)) for i in range(count)},
        "V": {str(i + 1): (0.0, float(100 + i * 20)) for i in range(count)},
    }
    return model, offsets


def _aisle(placements, left: str, right: str) -> float:
    boxes = {place.designator: place.bbox for place in placements}
    return boxes[right].x0 - boxes[left].x1


def test_five_nets_in_one_aisle_get_the_fifth_lane():
    """The synthetic case the rule exists for: more nets than lanes.

    Five nets leave the two parts that face this aisle, and the packing's own
    aisle is 40 units — four lanes at the ruler's 10-unit pitch — so the fifth
    net has no lane of its own and is drawn inside a neighbour's; that is the
    whole of what ``WIRE_TOO_CLOSE`` measures. Sizing the aisle from the demand
    buys it the lane, and the golden page is where the finding count that comes
    out of this is pinned (on a board this small the router can take the long
    way round, so the *capacity* is what this test is about — the capacity is
    what was wrong).
    """
    model, offsets = _funnel_board()
    exits = layout.net_exits(model, offsets)
    demand = len(exits["U"]["E"] | exits["V"]["W"])
    assert demand == 5, demand

    plain = layout.plan_placement(offsets, ["U", "V"])
    widened = layout.plan_placement(offsets, ["U", "V"], exits=exits)
    assert _aisle(plain, "U", "V") == layout.COL_AISLE
    assert _aisle(plain, "U", "V") // layout.WIRE_CLEARANCE < demand, (
        "precondition: the plain aisle really is short of lanes"
    )
    assert _aisle(widened, "U", "V") == layout._gap_width(demand, layout.COL_AISLE)
    assert _aisle(widened, "U", "V") // layout.WIRE_CLEARANCE >= demand


def test_the_wider_aisle_still_wires_every_net():
    """Giving the aisle room must not cost a net — the same promise the golden
    board is held to, checked where every net is visible at once."""
    model, offsets = _funnel_board()
    exits = layout.net_exits(model, offsets)
    for placements in (
        layout.plan_placement(offsets, ["U", "V"]),
        layout.plan_placement(offsets, ["U", "V"], exits=exits),
    ):
        pins: dict[tuple[str, str], tuple[float, float]] = {}
        for place in placements:
            for number, (dx, dy) in offsets.get(place.designator, {}).items():
                pins[(place.designator, number)] = (place.x + dx, place.y + dy)
        routes, routing = layout.route_nets(model, pins, placements)
        assert [v.render() for v in layout.blocking_violations(routing)] == []
        assert {route.net for route in routes} == set(model.nets)
        # and the wires that come out of it are wires: ends on pin tips
        assert all(len(poly) >= 2 for route in routes for poly in route.polylines)


# --------------------------------------------------------------------------
# 2. the demand: nets, and only the nets that leave on that side
# --------------------------------------------------------------------------


def _facing_pair() -> tuple[DesignModel, dict]:
    """A on the left, B on the right, their pins on the edges that face.

    ``A`` has two pins of the *same* net on its west edge (one wire, not two)
    and one pin leaving east; ``B`` faces ``A`` with two different nets. So the
    aisle between them is crossed by three nets, and ``A``'s west edge sends
    one.
    """
    a = Component(
        uid="a", designator="A",
        pins=[
            Pin(number="1", name="1", net="SHARED"),
            Pin(number="2", name="2", net="SHARED"),
            Pin(number="3", name="3", net="OUT"),
        ],
    )
    b = Component(
        uid="b", designator="B",
        pins=[Pin(number="1", name="1", net="SHARED"), Pin(number="2", name="2", net="SOLO")],
    )
    model = DesignModel(components={"A": a, "B": b})
    model.nets["SHARED"] = Net(name="SHARED", pins=[("A", "1"), ("A", "2"), ("B", "1")])
    model.nets["SOLO"] = Net(name="SOLO", pins=[("B", "2")])
    model.nets["OUT"] = Net(name="OUT", pins=[("A", "3")])
    offsets = {
        # A is 100 wide; its west pins sit at the same x, its east pin at the
        # far edge. B's pins are both on its only edge, the one facing A.
        "A": {"1": (0.0, 0.0), "2": (0.0, 20.0), "3": (100.0, 0.0)},
        "B": {"1": (0.0, 0.0), "2": (0.0, 20.0)},
    }
    return model, offsets


def test_the_demand_counts_nets_by_the_side_they_leave_on():
    """A gap's demand is the nets leaving the two boxes facing it, each once.

    Counting *pins* instead would count a net twice for two pins on one edge and
    would size the gap for a wire that is not there; counting the board's nets
    instead would size every gap for the traffic that never touches it.
    """
    model, offsets = _facing_pair()
    exits = layout.net_exits(model, offsets)
    assert exits["A"]["W"] == {"SHARED"}, exits["A"]
    assert exits["A"]["E"] == {"OUT"}, exits["A"]
    assert exits["B"]["W"] == {"SHARED", "SOLO"}, exits["B"]
    # the aisle between them carries all three nets, and each of them once
    assert len(exits["A"]["E"] | exits["B"]["W"]) == 3


def test_the_aisle_carries_the_traffic_the_two_boxes_face_it_with():
    """The golden aisle: seven nets leave the pair of boxes facing it.

    Six of them in fact run through it (measured on the routed page) — a net
    with a pin on one of those edges is a net that has to come out into the
    aisle, and the demand is deliberately the count of *those*, not of the
    board's nets that happen to span the same x. The difference is why the
    page is widened by what it can afford rather than to the last unit: see
    :func:`test_the_golden_page_is_the_widest_the_router_still_wires`.
    """
    model, offsets, _plan = _golden()
    exits = layout.net_exits(model, offsets)
    demand = len(exits["U5"]["E"] | exits["USB1"]["W"])
    assert demand == 7, demand
    # every other aisle on the page is under the fixed aisle's own capacity
    for left, right in (("U1", "C1"), ("C1", "C25"), ("U3", "U5"), ("USB1", "X1")):
        assert len(exits[left]["E"] | exits[right]["W"]) <= 4, (left, right)


# --------------------------------------------------------------------------
# 3. the packing: rows stay put, only the crowded aisle moves
# --------------------------------------------------------------------------


def test_the_rooms_are_spent_on_the_aisle_that_needs_them():
    """On the golden page exactly one aisle is over-subscribed, and it moves.

    The rows and their members come from the plain packing and are not revisited
    (``_widen_gaps`` walks them again), so the only boxes that move are the ones
    standing on the far side of the crowded aisle, and they move **right** by
    the width the aisle gained. Row one does not move at all: the same rule
    would give the leading strip 80 units, and that trade was measured and
    declined — 40 units of the page's scarcest space for one finding
    (``_widen_gaps``'s own note).
    """
    model, offsets, plan = _golden()
    order = list(generate._layout_order(model)[1])
    base = layout.plan_placement(offsets, order)
    rows = {p.designator: p.bbox.y0 for p in base if p.bbox}
    plan_boxes = {p.designator: p.bbox for p in plan.geometry if p.bbox}

    for designator, box in plan_boxes.items():
        assert box.y0 == rows[designator], f"{designator} changed shelf"
    assert plan_boxes["U1"].x0 == 40.0, "the leading strip must not be bought room"
    for designator in ("U1", "C1", "C25", "C3", "C6", "C7", "C4", "C5", "C9"):
        base_box = next(p.bbox for p in base if p.designator == designator)
        assert plan_boxes[designator] == base_box, f"{designator} moved needlessly"

    aisle = plan_boxes["USB1"].x0 - plan_boxes["U5"].x1
    assert aisle == 50.0, aisle
    assert plan_boxes["USB1"].x0 - next(p.bbox for p in base if p.designator == "USB1").x0 == 10.0
    assert plan_boxes["X1"].x0 - next(p.bbox for p in base if p.designator == "X1").x0 == 10.0


def test_a_board_whose_aisles_are_wide_enough_is_packed_exactly_as_before():
    """The rule is a no-op unless a gap is genuinely over-subscribed.

    This is what keeps the change off every sparse page: the demand-aware
    packing and the plain one are the same function of the boxes when no aisle
    has more than four nets facing it.
    """
    model, offsets, _plan = _golden()
    order = list(generate._layout_order(model)[1])
    exits = layout.net_exits(model, offsets)
    plain = layout.plan_placement(offsets, order)
    generous = layout.plan_placement(offsets, order, exits=exits, spare_lanes=99)
    assert generous == plain
    # and a board with no nets at all has no demand to spend
    empty = {designator: {} for designator in offsets}
    assert layout.plan_placement(offsets, order, exits={}) == plain
    assert empty  # the offsets are still there; nothing reads them as demand


# --------------------------------------------------------------------------
# 4. what the golden board measures, before and after
# --------------------------------------------------------------------------


def test_the_golden_tally_moves_down_and_by_the_measured_amount():
    """47 -> 34. Pinned, not hoped for.

    The count is what the wider aisle is worth on this page: from 47 findings at
    the packing's own 40 units to 34 at the 50 the router can still wire. The
    remaining pages below are not available — see the module docstring — so this
    number is the whole of the improvement, and it is the number the next person
    should beat.
    """
    _model, _offsets, plan = _golden()
    hits = [v for v in plan.violations if v.code == "WIRE_TOO_CLOSE"]
    assert len(hits) == 34, len(hits)
    for row in hits:
        assert "run 5 apart" in row.detail


def test_the_golden_page_grows_by_what_the_aisle_cost_and_no_more():
    """The trade the task asked to see stated: findings against area.

    The content box is 1090 x 350 before and 1090 x 365 after: the wider aisle
    moves boxes 10 units to the right inside a row that was already wide enough,
    so the page does **not** grow sideways at all. The height moves because one
    wire takes a slightly different way round, which is a routing detail, not a
    layout one.
    """
    _model, _offsets, plan = _golden()
    x0, y0, x1, y1 = _content_bbox(plan)
    assert (x1 - x0, y1 - y0) == (1090.0, 365.0), (x0, y0, x1, y1)
    before, after = 1090.0 * 350.0, 1090.0 * 365.0
    assert after / before < 1.30, after / before


def test_the_wider_aisle_costs_no_net_and_no_hard_finding():
    """Connectivity outranks readability, and the gate is what says so.

    The page the packing *asks* for is 70 units of aisle (seven nets abreast)
    and the router loses ``RX`` on it; the page in force is the widest one below
    that which routes. So the plan must be clean of every blocking code, and
    every net with two placed pins must have wires.
    """
    model, _offsets, plan = _golden()
    assert [v.render() for v in layout.blocking_violations(plan.violations)] == []
    routed = {wire.net for wire in plan.wires if len(wire.points) >= 2}
    wanted = {
        name
        for name, net in model.nets.items()
        if sum(1 for member in net.pins if member in plan.pin_positions) >= 2
    }
    assert routed == wanted


def test_the_wider_page_is_still_the_same_netlist():
    """A different page is still the same schematic: every wire ends on a pin.

    The router's contract is that a polyline endpoint is a pin tip or a same-net
    junction; re-laying the page out must not bend that, and the gate re-checks
    it (``ENDPOINT_NOT_TERMINAL`` / ``CROSS_NET_SHORT``), so the assertion is
    that none of those appear while the wires are all there.
    """
    _model, _offsets, plan = _golden()
    tally = Counter(v.code for v in plan.violations)
    for code in ("ENDPOINT_NOT_TERMINAL", "CROSS_NET_SHORT", "WIRE_THROUGH_BOX"):
        assert code not in tally, tally
    assert plan.wires, "the board still has wires"
    assert len(plan.net_names) > 0


# --------------------------------------------------------------------------
# 5. the safety net: a page the router cannot wire is not the page in force
# --------------------------------------------------------------------------


def test_a_page_that_cannot_be_wired_is_given_up(monkeypatch):
    """The widest page is only taken if every net still routes on it.

    The router is made to lose a net on any page whose ``U5|USB1`` aisle is
    wider than the packing's own, which is exactly the measured failure of the
    70-unit page — and the plan that comes out must be the plain packing's, not
    the pretty one.
    """
    real = layout.route_nets

    def refuses_wide_pages(model, pin_positions, placements):
        boxes = {p.designator: p.bbox for p in placements if p.bbox}
        aisle = boxes["USB1"].x0 - boxes["U5"].x1
        routes, violations = real(model, pin_positions, placements)
        if aisle > layout.COL_AISLE:
            return routes, violations + [
                layout.Violation("NET_UNROUTABLE", "net RX", "no route at any separation price")
            ]
        return routes, violations

    monkeypatch.setattr(generate.layout, "route_nets", refuses_wide_pages)
    model, offsets, _plan = _golden()
    fallback = generate_plan(model, offsets)
    order = list(generate._layout_order(model)[1])
    plain = layout.plan_placement(offsets, order)
    assert fallback.geometry == plain
    assert [v.render() for v in layout.blocking_violations(fallback.violations)] == []
    hits = [v for v in fallback.violations if v.code == "WIRE_TOO_CLOSE"]
    assert len(hits) == 47, len(hits)


def test_the_page_in_force_is_the_widest_one_that_verifies(monkeypatch):
    """The other half of the same net: a page that routes is kept, even if
    giving it less room would route too.

    Counting the router's own answers: with every page allowed, the plan must be
    the widest one that came out clean, which on this board is the second page
    tried (aisle 50).
    """
    pages: list[float] = []
    real = layout.route_nets

    def records(model, pin_positions, placements):
        boxes = {p.designator: p.bbox for p in placements if p.bbox}
        pages.append(boxes["USB1"].x0 - boxes["U5"].x1)
        return real(model, pin_positions, placements)

    monkeypatch.setattr(generate.layout, "route_nets", records)
    model, offsets, _plan = _golden()
    plan = generate_plan(model, offsets)
    boxes = {p.designator: p.bbox for p in plan.geometry if p.bbox}
    assert boxes["USB1"].x0 - boxes["U5"].x1 == 50.0
    assert pages[0] == 70.0, pages
    assert pages[-1] == 50.0, pages
    assert len(pages) == 2, pages


def test_the_router_retries_a_board_it_lost_a_net_on(monkeypatch):
    """The retry exists because a lost net is a property of the *order*.

    141 measured it: ``RX`` routes perfectly well on its own and is unroutable
    once three bigger nets have taken the strip's lanes, and the failing set
    walks from net to net as the order changes. So a pass that loses a net is
    re-run with the losers promoted, and the board keeps the better answer.
    """
    assert layout.ROUTE_RETRY_LIMIT >= 2
    seen: list[list[str]] = []
    real = layout._route_pass

    def counting(model, pin_positions, placements, priority=None):
        seen.append(list(priority or ()))
        return real(model, pin_positions, placements, priority=priority)

    monkeypatch.setattr(generate.layout, "_route_pass", counting)
    model, offsets, _plan = _golden()
    generate_plan(model, offsets)
    assert seen, "no pass ran"
    assert any(promoted for promoted in seen), (
        "no page needed the retry, so this test is not exercising it"
    )


@pytest.mark.parametrize("spare", [0, 1, 2])
def test_every_page_the_solver_tries_stays_inside_the_sheet(spare):
    """A widened page still has to fit: the sheet's frame is not negotiable."""
    model, offsets, _plan = _golden()
    order = list(generate._layout_order(model)[1])
    exits = layout.net_exits(model, offsets)
    geometry = layout.plan_placement(offsets, order, exits=exits, spare_lanes=spare)
    for place in geometry:
        if place.bbox is None:
            continue
        assert place.bbox.x0 >= layout.FRAME
        assert place.bbox.x1 <= layout.SHEET_WIDTH - layout.FRAME
        assert place.bbox.y0 >= layout.FRAME
        assert place.bbox.y1 <= layout.SHEET_HEIGHT - layout.FRAME
