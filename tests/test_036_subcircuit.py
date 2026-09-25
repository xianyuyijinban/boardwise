"""036: `insert-subcircuit` — the two templates, end to end, with a fake bridge.

The first slice with **no driving rule**, so these tests are also the statement of
what replaces one: the plan's own postconditions (probed before the writes and
re-read after them), the plan's own preconditions, and the rules' verdict on what
was added (the finding set may shrink, never grow).

Seams, all deliberate and all named:

* **the bridge** is a fake that answers `sch.geometry` / `sch.component_pins` /
  `sch.netlist` and records every write — "zero writes", "never retried" and the
  write order are asserted, not hoped;
* **the live export** is monkeypatched (`cli._live_project_export` → bytes and
  `cli._model_from_export` → a `DesignModel` the test builds), because the real
  pair parses an `.epro2` and a fixture cannot grow two parts between two reads;
* **the facts shelf** is monkeypatched to a two-entry shelf, so the plan builder's
  footprint lookup is the real code path on a known input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.cli import _finding_signature
from boardwise.core.changeplan import (
    ADD_COMPONENT_KIND,
    CONNECTION_LABEL,
    CONNECTION_POWER_FLAG,
    CONNECTION_WIRE,
    INSERT_SUBCIRCUIT_KIND,
    TEMPLATE_DIVIDER,
    TEMPLATE_RC_LOWPASS,
    INSERT_CONNECTION_KINDS,
    ChangePlan,
    ChangePlanError,
    PlanAttachment,
    PlanConnection,
    PlanPart,
    PlanSource,
    add_component_plan,
    insert_subcircuit_plan,
    sha256_of,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines import addcomponent, subcircuit

PROV = "036 test fixture"
FIXTURE = Path("tests/fixtures/llc_board.epro2")


# --------------------------------------------------------------------------
# fixtures: pages, models, the fake bridge
# --------------------------------------------------------------------------

FRAME = {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}


def _geometry(*, components, wires=(), netflags=(), bboxes=None, netlabels=()):
    """A `sch.geometry` dump in the shape 3.2.186 sends (measured), plus `bboxes`."""
    return {
        "components": [
            {"primitiveId": f"p-{name}",
             "state": {"Designator": name, "X": x, "Y": y, "ComponentType": "part"}}
            for name, x, y in components
        ]
        + [
            {"primitiveId": "sheet-1",
             "state": {"ComponentType": "sheet", "Designator": "", "X": 0, "Y": 0}}
        ]
        + [
            {"primitiveId": f"flag-{index}",
             "state": {"ComponentType": "netflag", "Designator": None, "Net": name,
                       "X": x, "Y": y}}
            for index, (name, x, y) in enumerate(netflags)
        ],
        "wires": [
            {"primitiveId": primitive_id,
             "state": {"Line": [c for pair in points for c in pair], "Net": net}}
            for primitive_id, net, points in wires
        ],
        "netlabels": [
            {"state": {"Net": name, "X": x, "Y": y}} for name, x, y in netlabels
        ],
        "bboxes": {
            "sheet-1": FRAME,
            **(bboxes or {}),
        },
        "meta": {"available": {"components": True, "wires": True, "bboxes": True}},
    }


def _pins(payload):
    return {
        "primitiveId": payload.get("primitiveId"),
        "pins": [
            {"X": x, "Y": y, "PinNumber": number, "PinName": number,
             "Rotation": 0, "PinLength": 10}
            for number, (x, y) in sorted(payload.get("__pins", {}).items())
        ],
    }


def _model(*, components=(), nets=None, pins=None):
    """A `DesignModel` from ``{designator: (value, lcsc)}`` and a net table.

    ``pins`` names each component's pin numbers (default: 1 and 2), because the
    scan "did an existing pin change company?" only sees the pins the model has —
    a U3 that never had a pin 5 would hide exactly the change this is about.
    """
    model = DesignModel()
    for name, (value, lcsc) in components:
        numbers = (pins or {}).get(name, ["1", "2"])
        model.components[name] = Component(
            uid=f"uid-{name}", designator=name, value=value, lcsc_part=lcsc,
            pins=[Pin(str(number), str(number), None) for number in numbers],
        )
    for net_name, members in (nets or {}).items():
        model.nets[net_name] = Net(net_name, [tuple(item) for item in members])
        for name, pin in members:
            component = model.components.get(name)
            if component is None:
                continue
            for item in component.pins:
                if item.number == pin:
                    item.net = net_name
    return model


def _live(*components):
    """A live-netlist reading: ``(designator, {pin: net})`` pairs."""
    return {
        "components": {
            f"gge{index}": {
                "props": {"Designator": designator},
                "pinInfoMap": {number: {"net": net} for number, net in pins.items()},
            }
            for index, (designator, pins) in enumerate(components)
        }
    }


class _BridgeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class _FakeBridge:
    """Answers what the insert flows ask; records what they wrote."""

    def __init__(self, *, geometry, after_geometry=None, pins=None, after_pins=None,
                 netlists=(), writes_fail=(), delete_reply=None):
        self.geometry = list(geometry)
        self.after_geometry = after_geometry
        self.pins = pins or {}
        self.after_pins = after_pins if after_pins is not None else (pins or {})
        self.netlists = list(netlists)
        self.writes: list[tuple[str, dict]] = []
        self.calls: list[str] = []
        self.geometry_reads = 0
        self.netlist_reads = 0
        self.writes_fail = set(writes_fail)
        self.delete_reply = delete_reply or {}

    async def call(self, action, params=None, **route):
        params = params or {}
        self.calls.append(action)
        if action in self.writes_fail:
            raise _BridgeError("CONNECTOR_ERROR", f"the editor refused {action}")
        if action == "doc.list":
            return {"active": {"uuid": "page-1", "type": "page"},
                    "projects": [{"projectUuid": "proj-1", "focused": True}]}
        if action == "sys.identity":
            return {"consistent": True, "consistentBasis": "project-uuid"}
        if action == "sch.geometry":
            self.geometry_reads += 1
            if self.geometry_reads == 1:
                return self.geometry[0]
            if self.after_geometry is not None:
                return self.after_geometry
            return self.geometry[-1]
        if action == "sch.netlist":
            self.netlist_reads += 1
            index = min(self.netlist_reads - 1, len(self.netlists) - 1)
            return {"text": json.dumps(self.netlists[index])} if self.netlists else {
                "text": json.dumps({"components": {}})
            }
        if action == "sch.component_pins":
            table = self.pins if self.geometry_reads <= 1 else self.after_pins
            payload = dict(params)
            payload["__pins"] = table.get(params.get("primitiveId"), {})
            return _pins(payload)
        if action == "sch.delete_primitives":
            self.writes.append((action, params))
            return self.delete_reply or {
                "deleted": list(params.get("primitiveIds") or []),
                "notFound": [], "failed": [],
            }
        if action in ("sch.place_component", "sch.place_wire", "sch.place_power"):
            self.writes.append((action, params))
            return {"uuid": f"new-{len(self.writes)}", "outcome": "ok"}
        if action == "sch.doc.save":
            self.writes.append((action, params))
            return {"saved": True}
        raise AssertionError(f"the flow called {action}, which this fake does not answer")

    async def close(self):
        return None


def _stub_bridge(monkeypatch, bridge):
    class _Client:
        @staticmethod
        async def open(*_args, **_kwargs):
            return bridge

    monkeypatch.setattr(cli, "_open_cli", lambda args: (_Client, _BridgeError, 61190, "tok"))


def _stub_export(monkeypatch, sequence):
    """Serve `_live_project_export` / `_model_from_export` in order."""
    models = list(sequence)

    async def _export(call, notes):
        return b"export-bytes"

    def _parse(blob, notes):
        return models.pop(0) if models else None

    monkeypatch.setattr(cli, "_live_project_export", _export)
    monkeypatch.setattr(cli, "_model_from_export", _parse)


def _stub_shelf(monkeypatch, parts=()):
    library = PartLibrary(parts=list(parts))
    monkeypatch.setattr(cli, "_facts_library", lambda: (library, ""))


# --------------------------------------------------------------------------
# 1. the engine: landing, connections, postconditions
# --------------------------------------------------------------------------

PAGE = _geometry(components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0)],
                 wires=[("w-attach", "N1", [(345.0, 310.0), (600.0, 310.0)])],
                 bboxes={"p-U3": {"minX": 240, "minY": 255, "maxX": 365, "maxY": 345},
                         "p-U9": {"minX": 580, "minY": 255, "maxX": 660, "maxY": 345},
                         "w-attach": {"minX": 345, "minY": 310, "maxX": 600, "maxY": 310}})

#: A page whose only wiring is a feed stub away from every component — the
#: divider's anchor (a *net* vertex, not a pin), where both resistors have room.
DIVIDER_PAGE = _geometry(
    components=[("U3", 300.0, 300.0)],
    wires=[("w-feed", "N2", [(100.0, 100.0), (300.0, 100.0)])],
    bboxes={"p-U3": {"minX": 240, "minY": 255, "maxX": 365, "maxY": 345},
            "w-feed": {"minX": 100, "minY": 100, "maxX": 300, "maxY": 100}},
)


def test_the_template_parts_land_together_at_the_templates_offsets():
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, PAGE, ["U3", "U9"])
    assert [item.role for item in group.parts] == ["series-r", "shunt-c"]
    assert group.spot.index == 0, "an empty neighbourhood takes the ideal rung"
    assert group.parts[0].at == (345.0 + 8 * addcomponent.LANDING_GRID,
                                310.0 + 2 * addcomponent.LANDING_GRID)
    assert group.parts[1].at == (345.0 + 8 * addcomponent.LANDING_GRID,
                                310.0 + 8 * addcomponent.LANDING_GRID)
    # The page's own pool decides the numbers, and the two parts never share one.
    assert {item.designator for item in group.parts} == {"R1", "C1"}


def test_the_ladder_walks_until_both_parts_are_clear_and_never_lands_on_the_anchor():
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    # A small box exactly where the ideal rung would put the series resistor: the
    # group has to move, and it moves **as a group**.
    page = _geometry(
        components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0)],
        wires=[("w", "N1", [(345.0, 310.0), (600.0, 310.0)])],
        bboxes={"p-U3": {"minX": 383, "minY": 318, "maxX": 387, "maxY": 322}},
    )
    group = subcircuit.plan_group((345.0, 310.0), tpl, page, ["U3", "U9"])
    assert group.spot.index > 0, "the ideal rung is blocked, so the ladder stepped"
    for item in group.parts:
        assert item.at != (345.0, 310.0), "never the anchor itself (029 §二.4)"


def test_an_exhausted_ladder_refuses_and_names_the_positions():
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    # One box that swallows every rung of the ladder.
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     bboxes={"p-U3": {"minX": -2000, "minY": -2000,
                                      "maxX": 2000, "maxY": 2000}})
    with pytest.raises(addcomponent.LadderExhausted) as caught:
        subcircuit.plan_group((300.0, 300.0), tpl, page, ["U3"])
    assert len(caught.value.tried) == len(addcomponent.LADDER)


def test_the_page_frame_is_not_an_obstacle():
    """The A4 frame's box covers the whole sheet; honouring it refuses everything."""
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    page = _geometry(components=[("U3", 300.0, 300.0)])  # only the sheet + U3
    group = subcircuit.plan_group((345.0, 310.0), tpl, page, ["U3"])
    assert group.spot.index == 0
    assert subcircuit.sheet_ids(page) == {"sheet-1"}


def test_rc_lowpass_declares_the_four_connections_in_write_order():
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, PAGE, ["U3", "U9"])
    series_r, shunt_c = group.parts
    connections = subcircuit.rc_lowpass_connections(
        series_r=series_r, shunt_c=shunt_c, anchor_pin=(345.0, 310.0),
        rejoin_at=(600.0, 310.0), before_net="N1", geometry=PAGE,
    )
    assert [(item.designator, item.pin, item.net, item.kind) for item in connections] == [
        (series_r.designator, "1", subcircuit.NODE_X, CONNECTION_WIRE),
        (series_r.designator, "2", "N1", CONNECTION_WIRE),
        (shunt_c.designator, "1", subcircuit.NODE_X, CONNECTION_WIRE),
        (shunt_c.designator, "2", "GND", CONNECTION_POWER_FLAG),
    ]
    assert connections[0].to == (345.0, 310.0), "the node's first member is the anchor pin"
    assert connections[1].to == (600.0, 310.0), "back to the far end of the wire that comes off"


def test_the_ground_leg_is_a_wire_when_the_rail_is_reachable_and_a_flag_when_it_is_not():
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    with_ground = _geometry(components=[("U3", 300.0, 300.0)],
                            wires=[("w-gnd", "GND", [(385.0, 380.0), (500.0, 380.0)])])
    group = subcircuit.plan_group((345.0, 310.0), tpl, with_ground, ["U3"])
    choice = subcircuit.ground_connection(group.parts[1].designator, "2",
                                          group.parts[1].at, with_ground)
    assert choice.kind == CONNECTION_WIRE and choice.to == (385.0, 380.0)
    flag = subcircuit.ground_connection("C1", "2", (385.0, 340.0), PAGE)
    assert flag.kind == CONNECTION_POWER_FLAG and flag.to is None


def test_the_ground_leg_never_chooses_a_label():
    """The host's net-label API is unusable (SKILL pit 9), so `label` is neither a
    kind a plan may declare nor one this helper will hand back.

    Two readings: a page that *names* GND with a label still gets a flag (a label
    is never a connection here), and if the shared chooser ever offered a label
    anyway, the helper refuses rather than passing it on.
    """
    assert CONNECTION_LABEL not in INSERT_CONNECTION_KINDS
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     netlabels=[("GND", 4000.0, 4000.0)])
    choice = subcircuit.ground_connection("C1", "2", (4000.0, 4000.0), page)
    assert choice.kind == CONNECTION_POWER_FLAG

    original = addcomponent.choose_connection

    def _label_always(net, spot, geometry):
        from boardwise.engines.addcomponent import ConnectionChoice
        return ConnectionChoice(kind=CONNECTION_LABEL, detail="test", to=None)

    addcomponent.choose_connection = _label_always
    try:
        with pytest.raises(addcomponent.NoConnectionOption) as caught:
            subcircuit.ground_connection("C1", "2", (4000.0, 4000.0), page)
        assert "net-label" in str(caught.value)
    finally:
        addcomponent.choose_connection = original


def test_divider_declares_three_connections_with_the_tap_between_two_plan_pins():
    tpl = subcircuit.template(TEMPLATE_DIVIDER)
    group = subcircuit.plan_group((100.0, 100.0), tpl, DIVIDER_PAGE, ["U3"])
    top, bottom = group.parts
    connections = subcircuit.divider_connections(
        top_r=top, bottom_r=bottom, anchor_net="N2", anchor_at=(100.0, 100.0),
        geometry=DIVIDER_PAGE,
    )
    assert [(item.designator, item.pin, item.net) for item in connections] == [
        (top.designator, "1", "N2"),
        (top.designator, "2", subcircuit.NODE_X),
        (bottom.designator, "2", "GND"),
    ]
    assert connections[1].to_pin == f"{bottom.designator}.1"
    assert connections[1].to is None
    assert top.rotation == 0 and bottom.rotation == 180, (
        "the tap's two pins face each other because the lower resistor is turned"
    )
    assert connections[2].kind == CONNECTION_POWER_FLAG, "no GND geometry anywhere near"


def test_the_net_vertex_is_the_lowest_one_so_two_runs_plan_the_same_divider():
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     wires=[("w", "N1", [(600.0, 300.0), (600.0, 200.0), (700.0, 200.0)])])
    assert cli._net_vertex(page, "N1") == (600.0, 200.0)
    assert cli._net_vertex(page, "NOPE") is None


RC_AFTER = _geometry(
    components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0), ("R1", 385.0, 320.0),
                ("C1", 385.0, 350.0)],
    wires=[("w-r1", "X5", [(365.0, 320.0), (365.0, 310.0), (345.0, 310.0)]),
           ("w-r2", "N1", [(405.0, 320.0), (600.0, 310.0)]),
           ("w-c1", "X5", [(365.0, 350.0), (345.0, 350.0), (345.0, 310.0)])],
    netflags=[("GND", 405.0, 350.0)],
)

RC_PINS = {
    "p-U3": {"5": (345.0, 310.0), "1": (255.0, 320.0)},
    "p-U9": {"1": (600.0, 310.0)},
    "p-R1": {"1": (365.0, 320.0), "2": (405.0, 320.0)},
    "p-C1": {"1": (365.0, 350.0), "2": (405.0, 350.0)},
}

#: The same coordinates keyed the way the postcondition checker asks for them
#: (`(designator, pin)`, not by canvas id — the canvas id is the *bridge's* key).
RC_PIN_COORDS = {
    ("U3", "5"): (345.0, 310.0), ("R1", "1"): (365.0, 320.0), ("R1", "2"): (405.0, 320.0),
    ("C1", "1"): (365.0, 350.0), ("C1", "2"): (405.0, 350.0),
}

RC_LIVE = {
    ("U3", "5"): "X5", ("R1", "1"): "X5", ("C1", "1"): "X5",
    ("R1", "2"): "N1", ("C1", "2"): "GND",
}


def _rc_plan(tmp_path, *, before_net="N1", attachment=True):
    tpl = subcircuit.template(TEMPLATE_RC_LOWPASS)
    group = subcircuit.plan_group((345.0, 310.0), tpl, PAGE, ["U3", "U9"])
    series_r, shunt_c = group.parts
    connections = subcircuit.rc_lowpass_connections(
        series_r=series_r, shunt_c=shunt_c, anchor_pin=(345.0, 310.0),
        rejoin_at=(600.0, 310.0), before_net=before_net, geometry=PAGE,
    )
    plan = insert_subcircuit_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        template=TEMPLATE_RC_LOWPASS,
        parts=[PlanPart(lcsc="C1x", value="1k", designator=series_r.designator,
                        role="series-r", x=series_r.x, y=series_r.y),
               PlanPart(lcsc="C2x", value="1n", designator=shunt_c.designator,
                        role="shunt-c", x=shunt_c.x, y=shunt_c.y)],
        connections=connections,
        anchor="U3", anchor_pin="5", anchor_at=(345.0, 310.0),
        attachment=PlanAttachment(kind="wire", primitive_id="w-attach",
                                  detail="the wire on the pin", at=(345.0, 310.0))
        if attachment else None,
        before_net=before_net,
        baseline_findings=["rule|ERROR|something that was already there"],
    )
    path = tmp_path / "plan.json"
    plan.dump(path)
    return path, plan


def test_postconditions_are_empty_for_a_finished_circuit(tmp_path):
    _, plan = _rc_plan(tmp_path)
    state = subcircuit.postcondition_problems(
        plan, live=RC_LIVE, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert state == {"live": [], "canvas": []}
    assert subcircuit.all_satisfied(state)


def test_a_missing_part_is_a_canvas_problem(tmp_path):
    _, plan = _rc_plan(tmp_path)
    page = _geometry(components=[("U3", 300.0, 300.0), ("R1", 385.0, 320.0)],
                     wires=[("w-r1", "X5", [(365.0, 320.0), (345.0, 310.0)])])
    state = subcircuit.postcondition_problems(
        plan, live=RC_LIVE, geometry=page, pins=RC_PIN_COORDS
    )
    assert state["live"] == []
    assert any("C1 (shunt-c) is not on the page" in item for item in state["canvas"])
    assert not subcircuit.all_satisfied(state)


def test_pins_on_different_islands_are_a_live_problem(tmp_path):
    _, plan = _rc_plan(tmp_path)
    live = dict(RC_LIVE)
    live[("C1", "1")] = "X9"
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert state["canvas"] == []
    assert any("are not one island" in item for item in state["live"])


def test_a_ground_pin_not_on_the_rail_is_a_live_problem(tmp_path):
    _, plan = _rc_plan(tmp_path)
    live = dict(RC_LIVE)
    live[("C1", "2")] = "$57N2"
    state = subcircuit.postcondition_problems(
        plan, live=live, geometry=RC_AFTER, pins=RC_PIN_COORDS
    )
    assert any("the ground leg is not connected" in item for item in state["live"])


def test_a_wire_that_does_not_reach_its_far_end_is_a_canvas_problem(tmp_path):
    _, plan = _rc_plan(tmp_path)
    page = _geometry(components=[("U3", 300.0, 300.0), ("R1", 385.0, 320.0),
                                 ("C1", 385.0, 350.0)],
                     wires=[("w-r1", "X5", [(365.0, 320.0), (345.0, 310.0)])])
    state = subcircuit.postcondition_problems(
        plan, live=RC_LIVE, geometry=page, pins=RC_PIN_COORDS
    )
    assert any("no wire ends at N1" in item for item in state["canvas"])


def test_existing_company_is_unchanged_by_a_legitimate_insert():
    """A **create** insert adds pins to existing nets; the pins that were already
    there keep exactly the company they had."""
    before = _model(components=[("U9", ("", "")), ("U3", ("", ""))],
                    pins={"U3": ["1", "2", "5"]},
                    nets={"N1": [("U9", "1")], "GND": [("U3", "2")]})
    after = _model(components=[("U9", ("", "")), ("U3", ("", "")),
                               ("R1", ("1k", "C1")), ("R2", ("1k", "C2"))],
                   pins={"U3": ["1", "2", "5"]},
                   nets={"N1": [("U9", "1"), ("R1", "1")],
                         "GND": [("U3", "2"), ("R2", "2")],
                         "X5": [("R1", "2"), ("R2", "1")]})
    assert subcircuit.existing_company_problems(before, after) == []


def test_existing_company_flags_a_pin_that_lost_its_netmate():
    before = _model(components=[("U3", ("", "")), ("U9", ("", ""))],
                    nets={"N1": [("U3", "5"), ("U9", "1")]})
    after = _model(components=[("U3", ("", "")), ("U9", ("", ""))],
                   nets={"N1": [("U3", "1")]})
    problems = subcircuit.existing_company_problems(before, after)
    assert any("U9.1 changed company" in item for item in problems), problems


def test_the_attachment_far_end_is_the_farthest_point_not_the_last_one():
    """Measured 2026-09-25: the host repeats a wire's junction points —
    ``[345, 320, 345, 310, 555, 320, 345, 320]`` for a two-segment wire — so "the
    last reported point" is the corner, and reconnecting there would reach nothing
    once the wire is gone."""
    geometry = _geometry(
        components=[("U3", 300.0, 300.0)],
        wires=[("w", "N1", [(345.0, 320.0), (345.0, 310.0), (555.0, 320.0),
                            (345.0, 320.0)])],
    )
    attachment = PlanAttachment(kind="wire", primitive_id="w",
                               detail="", at=(345.0, 310.0))
    assert cli._attachment_far_end(geometry, attachment) == (555.0, 320.0)
    # A wire that reports nothing but the pin has no far end at all.
    only_pin = _geometry(components=[("U3", 300.0, 300.0)],
                         wires=[("w", "N1", [(345.0, 310.0), (345.0, 310.0)])])
    assert cli._attachment_far_end(only_pin, attachment) is None


# --------------------------------------------------------------------------
# 2. the plan shape: round-trip, and the refusals each invariant buys
# --------------------------------------------------------------------------


def test_an_insert_plan_round_trips_through_json(tmp_path):
    path, plan = _rc_plan(tmp_path)
    again = ChangePlan.load(path)
    assert again.to_jsonable() == plan.to_jsonable()
    assert again.change.kind == INSERT_SUBCIRCUIT_KIND
    assert [item.designator for item in again.change.parts] == ["R1", "C1"]
    assert again.change.attachment.primitive_id == "w-attach"
    assert again.change.before_net == "N1"


def test_the_older_kinds_json_did_not_gain_the_insert_keys(tmp_path):
    """016/029/035 JSON 一字不变: the new fields are written only for this kind."""
    plan = add_component_plan(
        PlanSource(input_sha256="a" * 64), anchor="U1", designator="C7",
        part=PlanPart(lcsc="C1525", value="0.1uF"),
        connections=[
            PlanConnection("1", "VCC", kind=CONNECTION_WIRE, to=(5.0, 0.0)),
            PlanConnection("2", "GND", kind=CONNECTION_WIRE, to=(5.0, 20.0)),
        ],
        x=0.0, y=0.0, recipe_source="operator:C1525",
    )
    payload = plan.to_jsonable()
    assert set(payload["change"]["part"]) == {"lcsc", "value", "footprint"}
    assert set(payload["change"]["connections"][0]) == {"pin", "net", "kind", "detail", "to"}
    assert set(payload["target"]) == {
        "primitiveId", "designator", "expectedValue", "anchor", "assignedDesignator",
        "x", "y", "connection", "connectionDetail",
    }
    path = tmp_path / "old.json"
    plan.dump(path)
    assert ChangePlan.load(path).to_jsonable() == payload


def _insert_payload(**change_overrides):
    payload = {
        "planVersion": 1,
        "source": {"inputSha256": "a" * 64, "projectUuid": "", "pageUuid": "page-1",
                   "hostVersion": "", "connectorVersion": ""},
        "target": {"primitiveId": "", "designator": "U3", "expectedValue": "",
                   "anchor": "U3", "anchorNet": "", "pin": "5", "x": 345.0, "y": 310.0},
        "change": {
            "kind": INSERT_SUBCIRCUIT_KIND,
            "template": TEMPLATE_RC_LOWPASS,
            "parts": [
                {"designator": "R1", "role": "series-r", "lcsc": "C1x", "value": "1k",
                 "footprint": "", "x": 385.0, "y": 320.0, "rotation": 0},
                {"designator": "C1", "role": "shunt-c", "lcsc": "C2x", "value": "1n",
                 "footprint": "", "x": 385.0, "y": 340.0, "rotation": 0},
            ],
            "connections": [
                {"designator": "R1", "pin": "1", "net": "X", "kind": "wire",
                 "detail": "", "to": [345.0, 310.0]},
                {"designator": "R1", "pin": "2", "net": "N1", "kind": "wire",
                 "detail": "", "to": [600.0, 310.0]},
                {"designator": "C1", "pin": "1", "net": "X", "kind": "wire",
                 "detail": "", "to": [345.0, 310.0]},
                {"designator": "C1", "pin": "2", "net": "GND", "kind": "power-flag",
                 "detail": ""},
            ],
            "beforeNet": "N1",
            "attachment": {"kind": "wire", "primitiveId": "w-attach",
                           "detail": "the wire on the pin", "at": [345.0, 310.0]},
            "baselineFindings": [],
        },
        "preconditions": [],
        "expectedPostcondition": [],
    }
    payload["change"].update(change_overrides)
    return payload


@pytest.mark.parametrize(
    "mutate, keyword",
    [
        (lambda c: c.update(template="nope"), "change.template is 'nope'"),
        (lambda c: c["parts"][1].update(designator="R1"), "lists 'R1' twice"),
        (lambda c: c["parts"][0].update(lcsc=""), "lcsc is empty"),
        (lambda c: c["parts"][0].update(value=""), "value is empty"),
        (lambda c: c["parts"][0].pop("x"), "must be the landing point"),
        (lambda c: c["connections"][1].pop("to"), "neither `to`"),
        (lambda c: c["connections"][1].update(toPin="C1.1"), "says both `to` and `toPin`"),
        (lambda c: (c["connections"][1].pop("to"),
                     c["connections"][1].update(toPin="C9.1")),
         "does not name a pin of a planned part"),
        (lambda c: c["connections"][1].update(designator="R9"), "not one of the parts this plan places"),
        (lambda c: c["connections"][1].update(kind="label"), "label 不作为连接手段"),
        (lambda c: c["connections"][3].update(to=[1.0, 2.0]), "with a far-end point"),
        (lambda c: c.pop("attachment"), "must name the attachment"),
        (lambda c: c.update(beforeNet=""), "must state change.beforeNet"),
        (lambda c: c.pop("baselineFindings"), "baselineFindings must be a list"),
        (lambda c: c["parts"].append(
            {"designator": "R7", "role": "spare", "lcsc": "C9", "value": "1k",
             "x": 999.0, "y": 999.0}), "no connection mentions them"),
    ],
)
def test_an_insert_plan_refuses_the_shapes_apply_cannot_execute(mutate, keyword):
    payload = _insert_payload()
    mutate(payload["change"])
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert keyword in str(caught.value)


def test_a_divider_plan_must_not_carry_an_attachment_or_a_before_net():
    payload = _insert_payload(template=TEMPLATE_DIVIDER)
    payload["target"] = {"primitiveId": "", "designator": "", "expectedValue": "",
                         "anchor": "N1", "anchorNet": "N1", "pin": "",
                         "x": 600.0, "y": 300.0}
    payload["change"]["parts"] = [
        {"designator": "R1", "role": "divider-top", "lcsc": "C1x", "value": "1k",
         "x": 630.0, "y": 300.0},
        {"designator": "R2", "role": "divider-bottom", "lcsc": "C2x", "value": "1k",
         "x": 630.0, "y": 340.0, "rotation": 180},
    ]
    payload["change"]["connections"] = [
        {"designator": "R1", "pin": "1", "net": "N1", "kind": "wire", "to": [600.0, 300.0]},
        {"designator": "R1", "pin": "2", "net": "X", "kind": "wire", "toPin": "R2.1"},
        {"designator": "R2", "pin": "2", "net": "GND", "kind": "power-flag"},
    ]
    payload["change"].pop("attachment")
    payload["change"]["beforeNet"] = ""
    plan = ChangePlan.from_jsonable(payload)
    assert plan.change.template == TEMPLATE_DIVIDER
    assert plan.change.attachment is None and plan.change.before_net == ""

    with_attachment = json.loads(json.dumps(payload))
    with_attachment["change"]["attachment"] = {
        "kind": "wire", "primitiveId": "w", "at": [1.0, 2.0],
    }
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(with_attachment)
    assert "must not carry" in str(caught.value)

    with_net = json.loads(json.dumps(payload))
    with_net["change"]["beforeNet"] = "N1"
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(with_net)
    assert "must leave change.beforeNet empty" in str(caught.value)


def test_an_insert_target_must_anchor_on_exactly_one_thing():
    payload = _insert_payload()
    payload["target"]["anchorNet"] = "N1"
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "anchors on exactly one thing" in str(caught.value)
    payload = _insert_payload()
    payload["target"]["pin"] = ""
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "anchors on exactly one thing" in str(caught.value)


def test_the_finding_signature_is_the_subject_not_the_sentence():
    """Measured: the same decap complaint reworded itself after a legitimate
    insert, and a message-keyed signature called that a new finding."""
    from boardwise.rules.base import Finding, FindingTarget

    before = Finding(
        rule_id="decap-required-caps", severity="WARN",
        message="U3 pin5: no grounded capacitor found on net 'VOUT_U3' (required 1uF)",
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["5"],
                                        net_refs=["VOUT_U3"]),
    )
    after = Finding(
        rule_id="decap-required-caps", severity="WARN",
        message="U3 pin5: the grounded capacitor on 'VOUT_U3' is only 100nF (< required 1uF)",
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["5"],
                                        net_refs=["VOUT_U3"]),
    )
    assert _finding_signature(before) == _finding_signature(after)

    other_pin = Finding(
        rule_id="decap-required-caps", severity="WARN", message=after.message,
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["1"],
                                        net_refs=["NET3"]),
    )
    assert _finding_signature(other_pin) != _finding_signature(after)

    louder = Finding(
        rule_id="decap-required-caps", severity="ERROR", message=after.message,
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["5"],
                                        net_refs=["VOUT_U3"]),
    )
    assert _finding_signature(louder) != _finding_signature(after), "severity is part of it"

    # ...and an auto net that the editor renumbered is the same subject: measured,
    # a dangling pin's net went NET3 → NET4 when the insert added wiring elsewhere.
    renamed = Finding(
        rule_id="decap-required-caps", severity="WARN", message=before.message,
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["1"],
                                        net_refs=["NET4"]),
    )
    original = Finding(
        rule_id="decap-required-caps", severity="WARN", message=before.message,
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["1"],
                                        net_refs=["NET3"]),
    )
    assert _finding_signature(renamed) == _finding_signature(original)
    # A *named* net stays in the signature, because that one carries intent.
    gnd = Finding(
        rule_id="decap-required-caps", severity="WARN", message=before.message,
        level="L2", target=FindingTarget(component_ref="U3", pin_refs=["1"],
                                        net_refs=["GND"]),
    )
    assert _finding_signature(gnd) != _finding_signature(original)

    untargeted = Finding(rule_id="some-rule", severity="INFO", message="no target here",
                         level="L3")
    assert "no target here" in _finding_signature(untargeted)


# --------------------------------------------------------------------------
# 3. the CLI: `edit plan --insert`, `edit preview`, `edit apply`
# --------------------------------------------------------------------------


def _divider_plan(tmp_path, *, anchor_net="N2", anchor_at=(100.0, 100.0), sha="a" * 64,
                  name="divider.json"):
    tpl = subcircuit.template(TEMPLATE_DIVIDER)
    group = subcircuit.plan_group(anchor_at, tpl, DIVIDER_PAGE, ["U3"])
    top, bottom = group.parts
    connections = subcircuit.divider_connections(
        top_r=top, bottom_r=bottom, anchor_net=anchor_net, anchor_at=anchor_at,
        geometry=DIVIDER_PAGE,
    )
    plan = insert_subcircuit_plan(
        PlanSource(input_sha256=sha, page_uuid="page-1"),
        template=TEMPLATE_DIVIDER,
        parts=[PlanPart(lcsc="C1x", value="10k", designator=top.designator,
                        role="divider-top", x=top.x, y=top.y, rotation=top.rotation),
               PlanPart(lcsc="C2x", value="10k", designator=bottom.designator,
                        role="divider-bottom", x=bottom.x, y=bottom.y,
                        rotation=bottom.rotation)],
        connections=connections,
        anchor_net=anchor_net, anchor_at=anchor_at,
        baseline_findings=[],
    )
    path = tmp_path / name
    plan.dump(path)
    return path, plan


# The feed wire's own bounding box (inflated by the 5-unit clearance) covers the
# group's ideal rung, so the plan walks two rungs down: R1 at y = 90, R2 at
# y = 130. The fixtures below say what the plan actually planned — the numbers
# come from `plan_group`, not from arithmetic done by hand.
DIVIDER_AFTER = _geometry(
    components=[("U3", 300.0, 300.0), ("R1", 130.0, 90.0), ("R2", 130.0, 130.0)],
    wires=[("w-top", "N2", [(110.0, 90.0), (110.0, 100.0), (100.0, 100.0)]),
           ("w-tap", "X7", [(150.0, 90.0), (150.0, 130.0)]),
           ("w-feed", "N2", [(100.0, 100.0), (300.0, 100.0)])],
    netflags=[("GND", 110.0, 130.0)],
)

DIVIDER_PINS = {
    "p-U3": {"1": (255.0, 320.0)},
    "p-R1": {"1": (110.0, 90.0), "2": (150.0, 90.0)},
    "p-R2": {"1": (150.0, 130.0), "2": (110.0, 130.0)},
}

DIVIDER_PIN_COORDS = {
    ("R1", "1"): (110.0, 90.0), ("R1", "2"): (150.0, 90.0),
    ("R2", "1"): (150.0, 130.0), ("R2", "2"): (110.0, 130.0),
}

DIVIDER_LIVE = {("R1", "1"): "N2", ("R1", "2"): "X7", ("R2", "1"): "X7",
                ("R2", "2"): "GND"}


def _rc_bridge(*, after_geometry=RC_AFTER, netlists=None, after_pins=None):
    return _FakeBridge(
        geometry=[PAGE],
        after_geometry=after_geometry,
        pins=RC_PINS,
        after_pins=after_pins if after_pins is not None else RC_PINS,
        netlists=netlists if netlists is not None else [
            _live(("U3", {"5": "N1", "1": ""}), ("U9", {"1": "N1"})),
            _live(("U3", {"5": "X5", "1": ""}), ("U9", {"1": "N1"}),
                  ("R1", {"1": "X5", "2": "N1"}), ("C1", {"1": "X5", "2": "GND"})),
        ],
    )


def _rc_models():
    before = _model(components=[("U3", ("", "")), ("U9", ("", ""))],
                    pins={"U3": ["1", "2", "5"]},
                    nets={"N1": [("U3", "5"), ("U9", "1")]})
    after = _model(components=[("U3", ("", "")), ("U9", ("", "")),
                               ("R1", ("1k", "")), ("C1", ("1n", ""))],
                   pins={"U3": ["1", "2", "5"]},
                   nets={"N1": [("U9", "1"), ("R1", "2")],
                         "GND": [("C1", "2")],
                         "X5": [("U3", "5"), ("R1", "1"), ("C1", "1")]})
    return before, after


def test_plan_insert_rc_lowpass_builds_the_plan_from_the_live_page(
    monkeypatch, tmp_path, capsys
):
    bridge = _FakeBridge(
        geometry=[PAGE], pins=RC_PINS,
        netlists=[_live(("U3", {"5": "N1"}), ("U9", {"1": "N1"}))],
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    _stub_shelf(monkeypatch, [PartEntry(key="r", mpn="R", lcsc="C1x", footprint_name="0603"),
                              PartEntry(key="c", mpn="C", lcsc="C2x", footprint_name="0603")])
    out = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5",
        "--r", "1k", "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x",
        "-o", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    assert plan.change.template == TEMPLATE_RC_LOWPASS
    assert [item.designator for item in plan.change.parts] == ["R1", "C1"]
    assert [item.value for item in plan.change.parts] == ["1k", "1n"]
    assert [item.footprint for item in plan.change.parts] == ["0603", "0603"], (
        "the shelf's own footprint name is recorded, not invented"
    )
    assert plan.change.attachment.primitive_id == "w-attach"
    assert plan.change.before_net == "N1"
    assert [(c.designator, c.pin, c.net, c.kind) for c in plan.change.connections] == [
        ("R1", "1", "X", CONNECTION_WIRE),
        ("R1", "2", "N1", CONNECTION_WIRE),
        ("C1", "1", "X", CONNECTION_WIRE),
        ("C1", "2", "GND", CONNECTION_POWER_FLAG),
    ]
    assert "insert rc-lowpass" in printed and "off: wire w-attach" in printed


def test_plan_insert_allocates_designators_that_are_free_in_the_whole_project(
    monkeypatch, tmp_path, capsys
):
    """Measured 2026-09-25: `sch.place_component` renumbers a designator that
    collides **anywhere in the project** — asking for R2 on a page with no R2
    produced R3, because another page carried an R2 — and the rename lands
    mid-run, so the plan's own postconditions stop holding. The pool is therefore
    the page *and* the export the plan already reads."""
    bridge = _FakeBridge(
        geometry=[PAGE], pins=RC_PINS,
        netlists=[_live(("U3", {"5": "N1"}), ("U9", {"1": "N1"}))],
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model(components=[("R1", ("1k", "")), ("C5", ("1n", ""))])])
    _stub_shelf(monkeypatch)
    out = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5",
        "--r", "1k", "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x",
        "-o", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    assert [item.designator for item in plan.change.parts] == ["R2", "C1"], (
        "R1 is spent project-wide, so the resistor skips it; C1 is genuinely free"
    )


def test_plan_insert_divider_anchors_on_a_net_vertex(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge(geometry=[DIVIDER_PAGE], pins=DIVIDER_PINS,
                         netlists=[_live(("U3", {"5": ""}))])
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    _stub_shelf(monkeypatch)
    out = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--insert", TEMPLATE_DIVIDER, "--net", "N2",
        "--r1", "10k", "--r1-lcsc", "C1x", "--r2", "10k", "--r2-lcsc", "C2x",
        "-o", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    assert plan.target.anchor_net == "N2" and plan.target.designator == ""
    assert plan.change.attachment is None and plan.change.before_net == ""
    assert plan.change.parts[1].rotation == 180
    assert plan.change.connections[1].to_pin == "R2.1"
    assert "net 'N2' vertex at (100, 100)" in printed


@pytest.mark.parametrize(
    "argv, keyword",
    [
        (["--insert", "rc-lowpass", "--pin", "U3.5", "--r", "1k"],
         "--r-lcsc (series resistor)"),
        (["--insert", TEMPLATE_RC_LOWPASS, "--r", "1k", "--r-lcsc", "C1x",
          "--c", "1n", "--c-lcsc", "C2x"],
         "--insert rc-lowpass anchors on a pin"),
        (["--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5", "--net", "N1",
          "--r", "1k", "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x"],
         "anchors on a pin"),
        (["--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5", "--r", "1k",
          "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x", "--r1", "1k"],
         "takes --r/--c, not --r1/--r2"),
        (["--insert", "nope", "--pin", "U3.5"], "no template named 'nope'"),
    ],
)
def test_plan_insert_refuses_a_request_it_cannot_turn_into_a_plan(
    monkeypatch, tmp_path, capsys, argv, keyword
):
    _stub_bridge(monkeypatch, _FakeBridge(geometry=[PAGE], pins=RC_PINS))
    code = cli.main(["edit", "plan", *argv, "-o", str(tmp_path / "p.json")])
    captured = capsys.readouterr()
    assert code == 5
    assert keyword in captured.err


def test_plan_insert_refuses_file_and_report(monkeypatch, tmp_path, capsys):
    _stub_bridge(monkeypatch, _FakeBridge(geometry=[PAGE], pins=RC_PINS))
    base = ["edit", "plan", "--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5",
            "--r", "1k", "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x"]
    assert cli.main([*base, "--file", str(tmp_path / "x.epro2")]) == 5
    assert "--insert builds from the live page" in capsys.readouterr().err
    assert cli.main([*base, "--report", str(tmp_path / "r.json")]) == 5
    assert "--insert takes no --report" in capsys.readouterr().err


def test_plan_insert_refuses_a_netlabel_attachment(monkeypatch, tmp_path, capsys):
    page = _geometry(components=[("U3", 300.0, 300.0)],
                     netlabels=[("N1", 345.0, 310.0)])
    bridge = _FakeBridge(geometry=[page], pins=RC_PINS,
                         netlists=[_live(("U3", {"5": "N1"}))])
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main([
        "edit", "plan", "--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5",
        "--r", "1k", "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x",
        "-o", str(tmp_path / "p.json"),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "sch_PrimitiveNetLabel: absent" in err and "本机没有删 netlabel 的能力" in err


def test_plan_insert_refuses_when_every_rung_is_occupied(monkeypatch, tmp_path, capsys):
    packed = _geometry(
        components=[("U3", 300.0, 300.0)],
        wires=[("w-attach", "N1", [(345.0, 310.0), (600.0, 310.0)])],
        bboxes={"big": {"minX": -500, "minY": -500, "maxX": 2000, "maxY": 2000}},
    )
    bridge = _FakeBridge(geometry=[packed], pins=RC_PINS,
                         netlists=[_live(("U3", {"5": "N1"}))])
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main([
        "edit", "plan", "--insert", TEMPLATE_RC_LOWPASS, "--pin", "U3.5",
        "--r", "1k", "--r-lcsc", "C1x", "--c", "1n", "--c-lcsc", "C2x",
        "-o", str(tmp_path / "p.json"),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "every position in the landing ladder is occupied" in err
    assert "绝不落原点" in err


def test_plan_insert_refuses_a_net_the_page_does_not_carry(monkeypatch, tmp_path, capsys):
    _stub_bridge(monkeypatch, _FakeBridge(geometry=[PAGE], pins=RC_PINS))
    _stub_export(monkeypatch, [_model()])
    code = cli.main([
        "edit", "plan", "--insert", TEMPLATE_DIVIDER, "--net", "NOPE",
        "--r1", "10k", "--r1-lcsc", "C1x", "--r2", "10k", "--r2-lcsc", "C2x",
        "-o", str(tmp_path / "p.json"),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "has no wire geometry on this page" in err


def test_preview_lists_the_insert_without_a_snapshot(tmp_path, capsys):
    path, _plan = _rc_plan(tmp_path)
    code = cli.main(["edit", "preview", str(path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "insert-subcircuit rc-lowpass" in printed
    assert "place   R1 (series-r) 1k C1x at (385, 320)" in printed
    assert "place   C1 (shunt-c) 1n C2x at (385, 350)" in printed
    assert "remove  wire w-attach at (345, 310)" in printed
    assert "wire    C1.2 → GND via power-flag" in printed
    assert "live page only — check with `edit apply`" in printed
    assert "postconditions (what apply will read back):" in printed


def test_preview_checks_the_model_when_the_export_is_given(tmp_path, capsys):
    digest = sha256_of(FIXTURE)

    def _renumber(path, plan, top="R91", bottom="R92"):
        """Free numbers on the fixture board: its own R1/R2 would be 'taken'."""
        old_top, old_bottom = plan.change.parts[0].designator, plan.change.parts[1].designator
        plan.change.parts[0].designator, plan.change.parts[1].designator = top, bottom
        for item in plan.change.connections:
            if item.designator == old_top:
                item.designator = top
            elif item.designator == old_bottom:
                item.designator = bottom
            if item.to_pin:
                item.to_pin = f"{bottom}.1"
        plan.dump(path)
        return plan

    path, plan = _divider_plan(tmp_path, anchor_net="NET1", sha=digest)
    _renumber(path, plan)
    code = cli.main(["edit", "preview", str(path), "--file", str(FIXTURE)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "sha256 matches the plan's" in printed
    assert "still unused" in printed and "[ok]" in printed

    # ...and a net the snapshot does not carry is a broken precondition.
    other, other_plan = _divider_plan(tmp_path, anchor_net="NOT_A_NET", sha=digest,
                                      name="divider_b.json")
    _renumber(other, other_plan)
    code = cli.main(["edit", "preview", str(other), "--file", str(FIXTURE)])
    assert code == 4
    assert "not in the snapshot" in capsys.readouterr().out


def test_preview_refuses_a_stale_snapshot_for_an_insert_plan(tmp_path, capsys):
    digest = sha256_of(FIXTURE)
    path, _plan = _divider_plan(tmp_path, sha=digest)
    wrong = tmp_path / "other.epro2"
    wrong.write_bytes(b"not the export the plan was built against")
    code = cli.main(["edit", "preview", str(path), "--file", str(wrong)])
    assert code == 4
    assert "快照已失效" in capsys.readouterr().err


def test_apply_insert_rc_lowpass_deletes_places_wires_and_saves(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _rc_plan(tmp_path)
    bridge = _rc_bridge()
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, list(_rc_models()))
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(plan_path), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert [action for action, _ in bridge.writes] == [
        "sch.delete_primitives",
        "sch.place_component", "sch.place_component",
        "sch.place_wire", "sch.place_wire", "sch.place_wire",
        "sch.place_power",
        "sch.doc.save",
    ], "off the old net first, then both parts, then their wires, then the save"
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["outcome"] == "applied"
    assert report["verification"]["live"] == [] and report["verification"]["canvas"] == []
    assert report["range"]["wiresVanished"] == ["w-attach"]
    assert "canvas identity" in report["rangeBasis"]
    assert report["findings"]["new"] == []
    assert report["persistence"] == "saved_unverified"
    # The node's wires are placed **without** a net name, so the editor names the
    # island itself (036 §3: compare islands, not names).
    wire_calls = [params for action, params in bridge.writes if action == "sch.place_wire"]
    assert wire_calls[1].get("net") == "N1", "the rejoin wire carries the old net's name"
    assert "net" not in wire_calls[0] and "net" not in wire_calls[2], (
        "the two X wires stay unnamed"
    )


def test_apply_insert_is_idempotent_when_the_postconditions_hold(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _rc_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=[RC_AFTER], after_geometry=RC_AFTER, pins=RC_PINS,
        netlists=[_live(("U3", {"5": "X5"}), ("R1", {"1": "X5", "2": "N1"}),
                        ("C1", {"1": "X5", "2": "GND"}))],
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])

    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "already_applied" in printed and "idempotent" in printed
    assert bridge.writes == [], "a repeat run writes nothing at all"


def test_apply_insert_refuses_a_half_done_circuit(monkeypatch, tmp_path, capsys):
    """The parts are on the page but the wiring is not there: that is the shape a
    crashed previous run leaves, and placing them again would make two halves."""
    plan_path, _plan = _rc_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=[RC_AFTER], after_geometry=RC_AFTER, pins=RC_PINS,
        netlists=[_live(("U3", {"5": ""}), ("R1", {"1": "N9", "2": "N1"}),
                        ("C1", {"1": "N8", "2": ""}))],
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])

    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 4
    assert "part_present_unfinished" in printed
    assert "再放一遍会变成两套半电路" in printed
    assert bridge.writes == []


def test_apply_insert_refuses_when_the_attachment_is_gone(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _rc_plan(tmp_path)
    page = _geometry(components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0)],
                     wires=[("w-other", "N1", [(345.0, 310.0), (600.0, 310.0)])])
    bridge = _FakeBridge(geometry=[page], pins=RC_PINS,
                         netlists=[_live(("U3", {"5": "N1"}))])
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])

    code = cli.main(["edit", "apply", str(plan_path)])
    captured = capsys.readouterr()
    assert code == 4
    assert "attachment_missing" in captured.out
    assert bridge.writes == []


def test_apply_insert_refuses_when_the_anchor_moved(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _rc_plan(tmp_path)
    bridge = _rc_bridge(
        netlists=[_live(("U3", {"5": "N7"}), ("U9", {"1": "N7"}))]
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])

    code = cli.main(["edit", "apply", str(plan_path)])
    captured = capsys.readouterr()
    assert code == 4
    assert "stale_before" in captured.out
    assert bridge.writes == [], "nothing was written"


def test_apply_insert_judges_unknown_when_one_leg_disagrees(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _rc_plan(tmp_path)
    bridge = _rc_bridge(netlists=[
        _live(("U3", {"5": "N1"}), ("U9", {"1": "N1"})),
        # ...and after the writes the editor's own netlist does not show one node.
        _live(("U3", {"5": "X5"}), ("U9", {"1": "N1"}),
              ("R1", {"1": "X5", "2": "N1"}), ("C1", {"1": "X9", "2": "GND"})),
    ])
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, list(_rc_models()))
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(plan_path), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 3, printed
    assert "verification_disagrees" in printed
    assert "双证缺一判 unknown" in printed
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["verification"]["live"], "the failing leg is named"
    assert report["verification"]["canvas"] == []


def test_apply_insert_fails_the_range_when_another_wire_vanished(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _rc_plan(tmp_path)
    after = _geometry(
        components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0), ("R1", 385.0, 320.0),
                    ("C1", 385.0, 350.0)],
        wires=[("w-r1", "X5", [(365.0, 320.0), (345.0, 310.0)]),
               ("w-r2", "N1", [(405.0, 320.0), (600.0, 310.0)]),
               ("w-c1", "X5", [(365.0, 350.0), (345.0, 310.0)])],
        netflags=[("GND", 405.0, 350.0)],
    )
    page = _geometry(components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0)],
                     wires=[("w-attach", "N1", [(345.0, 310.0), (600.0, 310.0)]),
                            ("w-innocent", "N1", [(600.0, 310.0), (600.0, 200.0)])])
    bridge = _FakeBridge(geometry=[page], after_geometry=after, pins=RC_PINS,
                         netlists=_rc_bridge().netlists)
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, list(_rc_models()))

    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 2
    assert "range_canvas_diff" in printed
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_apply_insert_fails_when_a_rule_reports_something_new(
    monkeypatch, tmp_path, capsys
):
    """There is no rule of our own to re-review, so every rule gets a say: the
    finding set may shrink, never grow."""
    plan_path, _plan = _rc_plan(tmp_path)
    bridge = _rc_bridge()
    _stub_bridge(monkeypatch, bridge)
    before = _model(components=[("U3", ("", "")), ("U9", ("", ""))],
                    pins={"U3": ["1", "2", "5"]},
                    nets={"N1": [("U3", "5"), ("U9", "1")]})
    # The insert also left an LDO's supply pin on a net with no capacitor, which
    # `decap-required-caps` reports — a finding the plan's baseline never had.
    grown = _model(components=[("U3", ("", "")), ("U9", ("", "C47773")),
                               ("R1", ("1k", "")), ("C1", ("1n", ""))],
                   pins={"U3": ["1", "2", "5"], "U9": ["1", "5"]},
                   nets={"N1": [("U9", "1"), ("R1", "2")],
                         "GND": [("C1", "2")],
                         "X5": [("U3", "5"), ("R1", "1"), ("C1", "1")]})
    _stub_export(monkeypatch, [before, grown])

    code = cli.main(["edit", "apply", str(plan_path), "--json", str(tmp_path / "a.json")])
    printed = capsys.readouterr().out
    assert code == 2, printed
    assert "new_findings" in printed
    report = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert report["findings"]["new"], "the new lines are printed, not just counted"
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_apply_insert_divider_is_a_pure_create_and_judges_the_export(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _divider_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=[DIVIDER_PAGE], after_geometry=DIVIDER_AFTER, pins=DIVIDER_PINS,
        netlists=[_live(("U3", {"1": ""},), ("R1", {"1": "N2", "2": "X7"}),
                        ("R2", {"1": "X7", "2": "GND"}))],
    )
    _stub_bridge(monkeypatch, bridge)
    before = _model(components=[("U3", ("", ""))], pins={"U3": ["1"]},
                    nets={"N2": [("U3", "1")]})
    after = _model(components=[("U3", ("", "")), ("R1", ("10k", "")), ("R2", ("10k", ""))],
                   pins={"U3": ["1"]},
                   nets={"N2": [("U3", "1"), ("R1", "1")],
                         "X7": [("R1", "2"), ("R2", "1")],
                         "GND": [("R2", "2")]})
    _stub_export(monkeypatch, [before, after])
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(plan_path), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert [action for action, _ in bridge.writes] == [
        "sch.place_component", "sch.place_component",
        "sch.place_wire", "sch.place_wire", "sch.place_power", "sch.doc.save",
    ], "a pure create never deletes"
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["range"]["outsideScope"] == []
    assert "project export" in report["rangeBasis"]
    assert "wiresVanished" not in report["range"], "no delete leg, no canvas identity claim"


def test_apply_insert_divider_flags_an_out_of_scope_change(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _divider_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=[DIVIDER_PAGE], after_geometry=DIVIDER_AFTER, pins=DIVIDER_PINS,
        netlists=[_live(("U3", {"1": ""},), ("R1", {"1": "N2", "2": "X7"}),
                        ("R2", {"1": "X7", "2": "GND"}))],
    )
    _stub_bridge(monkeypatch, bridge)
    before = _model(components=[("U3", ("", "")), ("U9", ("", ""))],
                    pins={"U3": ["1"]},
                    nets={"N2": [("U3", "1"), ("U9", "1")]})
    after = _model(components=[("U3", ("", "")), ("U9", ("", "")),
                               ("R1", ("10k", "")), ("R2", ("10k", ""))],
                   pins={"U3": ["1"]},
                   nets={"N2": [("U3", "1"), ("R1", "1")]})
    _stub_export(monkeypatch, [before, after])

    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 2
    assert "outside_scope" in printed
    assert "U9.1 changed company" in printed
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_apply_insert_refuses_a_designator_or_spot_taken_between_plan_and_apply(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _rc_plan(tmp_path)
    page = _geometry(components=[("U3", 300.0, 300.0), ("U9", 620.0, 300.0),
                                 ("R1", 385.0, 320.0)],
                     wires=[("w-attach", "N1", [(345.0, 310.0), (600.0, 310.0)])])
    bridge = _FakeBridge(geometry=[page], pins=RC_PINS,
                         netlists=[_live(("U3", {"5": "N1"}))])
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 4
    assert "part_present_unfinished" in printed or "designator_taken" in printed
    assert bridge.writes == []
