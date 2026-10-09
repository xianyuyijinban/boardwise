"""143f: the two `engines/subcircuit.py` holes from `outputs/143_dig/07`.

Both are about the same thing: the plan's own postconditions are the **only**
thing standing between a wrong board and the word "done" (there is no rule for
this plan kind), so a claim they cannot check must be a problem, never a pass —
and the rail they name must be the **page's** rail, not a literal.

* 洞1 — `postcondition_problems` never asked whether the new node *is* the
  ground rail (a divider tap welded to ground is one island, and every other net
  is elsewhere, so both old tests were satisfied by a short); the divider's node
  was read as a **single pin** (`toPin` targets were not members), against which
  "these pins share one island" is empty; and a plan with no `NODE_X` marker lost
  the whole node check with no problem and no note.
* 洞2 — `GROUND_NET` was the literal `"GND"` and the plan's ground leg was
  checked against that same constant, so a page whose rail is `VSS`/`PGND` got a
  **second** ground planted on it, certified by the plan's own postcondition.

Reproductions: `outputs/143_dig/07/p2_node_may_be_ground.py`,
`p3_role_rulers.py` (C), `p4_ground_is_a_literal.py`.
"""

from __future__ import annotations

import dataclasses

import pytest

from boardwise.core.changeplan import (
    CONNECTION_WIRE,
    PlanAttachment,
    PlanPart,
    PlanSource,
    insert_subcircuit_plan,
)
from boardwise.core.model import GROUND_NET_PREFIXES
from boardwise.engines import addcomponent, subcircuit
from test_036_subcircuit import (  # noqa: E402  (tests import each other, see tests/conftest.py)
    DIVIDER_PAGE,
    PAGE,
    RC_AFTER,
    RC_LIVE,
    RC_PIN_COORDS,
    _geometry,
    _rc_plan,
)

FRAME = {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}


# --------------------------------------------------------------------------
# builders (the dig scripts' own, so the witnesses are the same boards)
# --------------------------------------------------------------------------


def _rc_plan_with(connections):
    """The shipped rc-lowpass plan, with the connections the caller names."""
    tpl = subcircuit.template(subcircuit.TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, PAGE, ["U3", "U9"])
    series_r, shunt_c = group.parts
    return insert_subcircuit_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        template=subcircuit.TEMPLATE_RC_LOWPASS,
        parts=[PlanPart(lcsc="C1x", value="1k", designator=series_r.designator,
                        role="series-r", x=series_r.x, y=series_r.y),
               PlanPart(lcsc="C2x", value="1n", designator=shunt_c.designator,
                        role="shunt-c", x=shunt_c.x, y=shunt_c.y)],
        connections=connections,
        anchor="U3", anchor_pin="5", anchor_at=(345.0, 310.0),
        attachment=PlanAttachment(kind="wire", primitive_id="w-attach",
                                  detail="the wire on the pin", at=(345.0, 310.0)),
        before_net="N1",
        baseline_findings=[],
    )


def _divider_plan():
    """The shipped divider plan, plus its two parts (020-style, as p2 builds it)."""
    tpl = subcircuit.template(subcircuit.TEMPLATE_DIVIDER)
    group = subcircuit.plan_group((100.0, 100.0), tpl, DIVIDER_PAGE, ["U3"])
    top, bottom = group.parts
    connections = subcircuit.divider_connections(
        top_r=top, bottom_r=bottom, anchor_net="N2", anchor_at=(100.0, 100.0),
        geometry=DIVIDER_PAGE,
    )
    plan = insert_subcircuit_plan(
        PlanSource(input_sha256="b" * 64, page_uuid="page-1"),
        template=subcircuit.TEMPLATE_DIVIDER,
        parts=[PlanPart(lcsc="C1x", value="10k", designator=top.designator,
                        role="divider-top", x=top.x, y=top.y),
               PlanPart(lcsc="C2x", value="10k", designator=bottom.designator,
                        role="divider-bottom", x=bottom.x, y=bottom.y)],
        connections=connections,
        anchor="N2", anchor_pin="", anchor_at=(100.0, 100.0),
        attachment=None, before_net="N2", baseline_findings=[],
    )
    return plan, top, bottom


def _divider_board(top, bottom):
    """The divider page after the insert (`p2`'s own canvas), plus its pin table."""
    geometry = {
        "components": [
            {"primitiveId": "p-U3",
             "state": {"Designator": "U3", "X": 300.0, "Y": 300.0, "ComponentType": "part"}},
            {"primitiveId": "p-R1",
             "state": {"Designator": top.designator, "X": top.x, "Y": top.y,
                       "ComponentType": "part"}},
            {"primitiveId": "p-R2",
             "state": {"Designator": bottom.designator, "X": bottom.x, "Y": bottom.y,
                       "ComponentType": "part"}},
            {"primitiveId": "sheet-1",
             "state": {"ComponentType": "sheet", "X": 0, "Y": 0}},
        ],
        "wires": [
            {"primitiveId": "w-feed",
             "state": {"Line": [100.0, 100.0, 300.0, 100.0], "Net": "N2"}},
            {"primitiveId": "w-top",
             "state": {"Line": [130.0, 100.0, 100.0, 100.0], "Net": "N2"}},
            {"primitiveId": "w-tap", "state": {"Line": [150.0, 100.0, 150.0, 140.0]}},
            {"primitiveId": "w-gnd", "state": {"Line": [150.0, 140.0, 150.0, 160.0]}},
        ],
        "bboxes": {"sheet-1": FRAME},
        "meta": {},
    }
    pins = {("U3", "1"): (200.0, 100.0), ("R1", "1"): (130.0, 100.0),
            ("R1", "2"): (150.0, 100.0), ("R2", "1"): (150.0, 140.0),
            ("R2", "2"): (150.0, 160.0)}
    return geometry, pins


# --------------------------------------------------------------------------
# 洞1 (a): the new node must not be the ground rail
# --------------------------------------------------------------------------


def test_a_node_welded_to_the_ground_rail_is_a_live_problem(tmp_path):
    """`p2`: the shunt's own node on GND — R2 bypassed, the output is 0 V."""
    _, plan = _rc_plan(tmp_path)
    live = dict(RC_LIVE)
    for key in (("R1", "1"), ("C1", "1"), ("C1", "2")):
        live[key] = "GND"
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert state["canvas"] == []
    assert any("shorted to ground" in item for item in state["live"]), state["live"]
    assert not subcircuit.all_satisfied(state), (
        "the node is one island and every other net is elsewhere — the two old "
        "judgements both hold on a short"
    )


def test_the_dividers_node_holds_both_ends_of_the_tap():
    """`p2`: `R1.2`→`R2.1` is one wire, so the node is two pins, not one."""
    plan, top, bottom = _divider_plan()
    assert subcircuit.node_members(plan) == [
        (top.designator, "2"), (bottom.designator, "1"),
    ], "reading only the connection's own pin makes 'one island' a single-pin claim"


def test_a_divider_tap_on_the_ground_rail_is_a_live_problem():
    plan, top, bottom = _divider_plan()
    geometry, pins = _divider_board(top, bottom)
    #: R1.1 on the anchor net, and the whole lower half — tap included — on GND.
    live = {("R1", "1"): "N2", ("R1", "2"): "GND",
            ("R2", "1"): "GND", ("R2", "2"): "GND"}
    state = subcircuit.postcondition_problems(plan, live=live, geometry=geometry, pins=pins)
    assert state["canvas"] == []
    assert any("shorted to ground" in item for item in state["live"]), state["live"]


def test_a_node_on_the_anchor_net_is_still_caught(tmp_path):
    """The series leg did not separate them — the reading that already worked."""
    _, plan = _rc_plan(tmp_path)
    live = dict(RC_LIVE)
    live[("R1", "1")] = live[("C1", "1")] = "N1"
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert any("did not separate them" in item for item in state["live"]), state["live"]


# --------------------------------------------------------------------------
# 洞1 (b): a plan the checker cannot read is a problem, not a pass
# --------------------------------------------------------------------------


def test_a_plan_that_names_no_node_is_a_problem_not_a_silent_pass(tmp_path):
    """`p3` C: the marker dropped, the whole node check used to vanish."""
    tpl = subcircuit.template(subcircuit.TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, PAGE, ["U3", "U9"])
    series_r, shunt_c = group.parts
    connections = subcircuit.rc_lowpass_connections(
        series_r=series_r, shunt_c=shunt_c, anchor_pin=(345.0, 310.0),
        rejoin_at=(600.0, 310.0), before_net="N1", geometry=PAGE,
    )
    renamed = [
        dataclasses.replace(item, net="") if item.net == subcircuit.NODE_X else item
        for item in connections
    ]
    plan = _rc_plan_with(renamed)
    live = {**RC_LIVE, ("R1", "1"): "NET9", ("C1", "1"): "NET9"}
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert state["canvas"] == []
    assert any("declares no new node" in item for item in state["live"]), state["live"]
    assert not subcircuit.all_satisfied(state), "nothing may read as done here"
    assert subcircuit.node_members(plan) == [], "the plan really carries no marker"


# --------------------------------------------------------------------------
# 洞1 (c) + 洞2: the ground leg, on the rail the plan named *and* on a ground
# --------------------------------------------------------------------------


def test_a_ground_leg_on_another_net_is_a_live_problem(tmp_path):
    _, plan = _rc_plan(tmp_path)
    live = dict(RC_LIVE)
    live[("C1", "2")] = "VSSA"
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert any("the ground leg is not connected" in item
               for item in state["live"]), state["live"]


def test_a_plan_whose_ground_leg_is_filed_under_no_ground_net_is_a_problem():
    """A plan may not silently drop the ground claim — same shape as the node.

    Both templates ground their shunt leg, so a connection record with no
    ground-family net in it is the record and the template disagreeing, not a
    plan that abstained from grounding.
    """
    tpl = subcircuit.template(subcircuit.TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, PAGE, ["U3", "U9"])
    series_r, shunt_c = group.parts
    connections = subcircuit.rc_lowpass_connections(
        series_r=series_r, shunt_c=shunt_c, anchor_pin=(345.0, 310.0),
        rejoin_at=(600.0, 310.0), before_net="N1", geometry=PAGE,
    )
    #: The same leg, filed under a name no one reads as a rail.
    connections = [
        dataclasses.replace(item, net="OUT") if item.pin == "2" and item.net == "GND"
        else item
        for item in connections
    ]
    plan = _rc_plan_with(connections)
    live = {**RC_LIVE, ("C1", "2"): "OUT"}
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert any("declares no ground leg" in item for item in state["live"]), state["live"]
    assert not subcircuit.all_satisfied(state)


# --------------------------------------------------------------------------
# 洞2: the page's own ground spelling
# --------------------------------------------------------------------------


def test_the_ground_net_is_the_pages_own_spelling():
    # Nothing on the page is a ground → the template's own flag names the rail.
    assert subcircuit.ground_net_for(PAGE) == subcircuit.GROUND_NET == "GND"
    assert subcircuit.page_ground_nets(PAGE) == []
    vss = _geometry(components=[("U3", 300.0, 300.0)],
                    wires=[("w-vss", "VSS", [(385.0, 355.0), (500.0, 355.0)])])
    assert subcircuit.ground_net_for(vss) == "VSS"
    # A flag is a spelling too: a page whose only ground is a flag has one.
    flagged = _geometry(components=[("U3", 300.0, 300.0)], netflags=[("PGND", 10.0, 10.0)])
    assert subcircuit.ground_net_for(flagged) == "PGND"
    # Every spelling this repo knows is read the same way — the literal is one of
    # them, never the definition.
    assert set(GROUND_NET_PREFIXES) >= {"GND", "VSS", "PGND", "AGND"}


def test_a_plain_gnd_beside_another_ground_family_still_means_GND():
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     wires=[("a", "AGND", [(1.0, 1.0), (2.0, 2.0)]),
                            ("b", "GND", [(3.0, 3.0), (4.0, 4.0)])])
    assert subcircuit.ground_net_for(page) == "GND"


def test_two_ground_families_and_no_plain_GND_refuse_rather_than_guess():
    """R3: the choice is the circuit's, and guessing makes a second ground."""
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     wires=[("a", "VSS", [(1.0, 1.0), (2.0, 2.0)]),
                            ("b", "PGND", [(3.0, 3.0), (4.0, 4.0)])])
    with pytest.raises(addcomponent.NoConnectionOption) as caught:
        subcircuit.ground_net_for(page)
    assert "VSS" in str(caught.value) and "PGND" in str(caught.value)


def test_the_ground_leg_joins_the_pages_rail_instead_of_planting_a_second_ground():
    """`p4`: on a VSS page the reachable rail is found (wire), not a GND flag."""
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     wires=[("w-vss", "VSS", [(385.0, 355.0), (500.0, 355.0)])])
    leg = subcircuit.ground_connection("C1", "2", (385.0, 350.0), page)
    assert leg.net == "VSS", "the literal 'GND' would plant a second ground"
    assert leg.kind == CONNECTION_WIRE and leg.to == (385.0, 355.0)


def test_the_whole_template_reads_the_pages_rail():
    """End to end through `rc_lowpass_connections`, not just the helper."""
    page = _geometry(
        components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0)],
        wires=[("w-attach", "N1", [(345.0, 310.0), (600.0, 310.0)]),
               ("w-vss", "VSS", [(385.0, 355.0), (500.0, 355.0)])],
        bboxes={"p-U3": {"minX": 240, "minY": 255, "maxX": 365, "maxY": 345}},
    )
    tpl = subcircuit.template(subcircuit.TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, page, ["U3", "U9"])
    series_r, shunt_c = group.parts
    connections = subcircuit.rc_lowpass_connections(
        series_r=series_r, shunt_c=shunt_c, anchor_pin=(345.0, 310.0),
        rejoin_at=(600.0, 310.0), before_net="N1", geometry=page,
    )
    assert connections[3].net == "VSS"
    # And a plan whose ground leg reads back as the second ground it used to
    # plant is refused, rather than certified by the constant it was built from.
    plan = _rc_plan_with(connections)
    live = {**RC_LIVE, ("C1", "2"): "GND"}
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert any("the ground leg is not connected" in item
               for item in state["live"]), state["live"]
