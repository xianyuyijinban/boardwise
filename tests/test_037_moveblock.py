"""037: `move-block` — the group, the wires, and the identity judgement.

The slice exists because of one measurement (`outputs/037_probe.txt`): the host
moves a part and **leaves its wire where it was**, so a safe local move has to take
the wires off and draw them again. Everything below is either that mechanism, a
refusal that keeps it from guessing, or the acceptance's main judgement — the
netlist is *identical* after a move, read as a partition of pins (never as names).

Seams, all named: the bridge is a fake that answers `sch.geometry` /
`sch.component_pins` / `sch.netlist` and records every write; the live export is
monkeypatched (`cli._live_project_export` → bytes, `cli._model_from_export` → a
`DesignModel` the test builds), because the real pair parses an `.epro2` and a
fixture cannot move a part between two reads.
"""

from __future__ import annotations

import json

import pytest

from boardwise import cli
from boardwise.cli import _finding_signature
from boardwise.core.changeplan import (
    ADD_COMPONENT_KIND,
    MOVE_BLOCK_KIND,
    ChangePlan,
    ChangePlanError,
    PlanIsland,
    PlanMove,
    PlanSource,
    PlanWireOp,
    add_component_plan,
    move_block_plan,
    sha256_of,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import moveblock as mb

FRAME = {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}


def _geometry(*, components, wires=(), netlabels=(), bboxes=None):
    """A `sch.geometry` dump in the measured shape, plus the page frame."""
    return {
        "components": [
            {"primitiveId": f"p-{name}",
             "state": {"Designator": name, "X": x, "Y": y, "Rotation": rotation,
                       "ComponentType": "part"}}
            for name, x, y in components
            for rotation in [0.0]
        ] + [{"primitiveId": "sheet-1",
              "state": {"ComponentType": "sheet", "Designator": "", "X": 0, "Y": 0}}],
        "wires": [
            {"primitiveId": primitive_id,
             "state": {"Line": [c for pair in points for c in pair], "Net": net}}
            for primitive_id, net, points in wires
        ],
        "netlabels": [{"state": {"Net": name, "X": x, "Y": y}}
                      for name, x, y in netlabels],
        "bboxes": {"sheet-1": FRAME, **(bboxes or {})},
        "meta": {"available": {"components": True, "wires": True, "bboxes": True}},
    }


def _live(*components):
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
    def __init__(self, *, geometry, after_geometry=None, pins=None, after_pins=None,
                 netlists=(), modify_fails=False, modify_silent=False, deletes=(),
                 geometry_sequence=None):
        self.geometry = list(geometry)
        #: A full per-read sequence, for tests that need a *middle* reading (the
        #: read-back after a failed modify must show nothing moved, and the one
        #: after that must show the move).
        self.geometry_sequence = list(geometry_sequence or [])
        self.after_geometry = after_geometry
        self.pins = pins or {}
        self.after_pins = after_pins if after_pins is not None else (pins or {})
        self.netlists = list(netlists)
        self.writes: list[tuple[str, dict]] = []
        self.calls: list[str] = []
        self.reads = 0
        self.netlist_reads = 0
        self.modify_fails = modify_fails
        self.modify_attempts = 0
        self.modify_silent = modify_silent
        self.deletes = list(deletes)

    async def call(self, action, params=None, **route):
        params = params or {}
        self.calls.append(action)
        if action == "doc.list":
            return {"active": {"uuid": "page-1", "type": "page"},
                    "projects": [{"projectUuid": "proj-1", "focused": True}]}
        if action == "sys.identity":
            return {"consistent": True, "consistentBasis": "project-uuid"}
        if action == "sch.geometry":
            self.reads += 1
            if self.geometry_sequence:
                return self.geometry_sequence[
                    min(self.reads - 1, len(self.geometry_sequence) - 1)]
            if self.reads == 1:
                return self.geometry[0]
            if self.after_geometry is not None:
                return self.after_geometry
            return self.geometry[-1]
        if action == "sch.netlist":
            self.netlist_reads += 1
            index = min(self.netlist_reads - 1, len(self.netlists) - 1)
            return {"text": json.dumps(self.netlists[index] if self.netlists
                                       else {"components": {}})}
        if action == "sch.component_pins":
            table = self.pins if self.reads <= 1 else self.after_pins
            return {"primitiveId": params.get("primitiveId"),
                    "pins": [{"X": x, "Y": y, "PinNumber": number, "PinName": number}
                             for number, (x, y) in sorted(
                                 (table.get(params.get("primitiveId")) or {}).items())]}
        if action == "sch.modify_primitive":
            self.writes.append((action, params))
            self.modify_attempts += 1
            if self.modify_silent:
                return None
            if self.modify_fails and self.modify_attempts <= self.modify_fails:
                raise _BridgeError("CONNECTOR_ERROR",
                                   "TypeError: Cannot destructure property 'cmdKey'")
            return {"before": {"x": 0, "y": 0, "rotation": 0, "mirror": False},
                    "after": {"x": params.get("x"), "y": params.get("y"),
                              "rotation": 0, "mirror": False}}
        if action == "sch.delete_primitives":
            self.writes.append((action, params))
            ids = list(params.get("primitiveIds") or [])
            return self.deletes or None if False else (
                {"deleted": ids if not self.deletes else self.deletes,
                 "notFound": [], "failed": []}
            )
        if action == "sch.place_wire":
            self.writes.append((action, params))
            return {"uuid": f"new-{len(self.writes)}"}
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
    models = list(sequence)

    async def _export(call, notes):
        return b"export-bytes"

    def _parse(blob, notes):
        return models.pop(0) if models else None

    monkeypatch.setattr(cli, "_live_project_export", _export)
    monkeypatch.setattr(cli, "_model_from_export", _parse)


def _model(*, components=(), nets=None, pins=None):
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


# --------------------------------------------------------------------------
# fixtures: a two-part group joined by one wire, and a four-pin block
# --------------------------------------------------------------------------

#: Two LDOs side by side; U1 pin5 is wired to U2 pin1 (the "two pins, one wire"
#: shape the probe measured the host's drag behaviour on).
PAGE = _geometry(
    components=[("U1", 300.0, 300.0), ("U2", 600.0, 300.0)],
    wires=[("w-link", "GROUP_NET", [(345.0, 310.0), (345.0, 320.0), (555.0, 320.0)])],
    bboxes={"p-U1": {"minX": 240, "minY": 255, "maxX": 365, "maxY": 345},
            "p-U2": {"minX": 540, "minY": 255, "maxX": 665, "maxY": 345},
            "w-link": {"minX": 345, "minY": 310, "maxX": 555, "maxY": 320}},
)

PINS = {
    "p-U1": {"1": (255.0, 320.0), "2": (255.0, 300.0), "3": (255.0, 280.0),
             "4": (345.0, 290.0), "5": (345.0, 310.0)},
    "p-U2": {"1": (555.0, 320.0), "2": (555.0, 300.0), "3": (555.0, 280.0),
             "4": (645.0, 290.0), "5": (645.0, 310.0)},
}

LIVE_BEFORE = _live(("U1", {"1": "", "2": "", "3": "", "4": "", "5": "GROUP_NET"}),
                    ("U2", {"1": "GROUP_NET", "2": "", "3": "", "4": "", "5": ""}))

#: After a (+100, 0) move: the same two pins, the same net — positions changed.
PAGE_AFTER = _geometry(
    components=[("U1", 400.0, 300.0), ("U2", 700.0, 300.0)],
    wires=[("new-w", "GROUP_NET", [(445.0, 310.0), (445.0, 320.0), (655.0, 320.0)])],
    bboxes={"p-U1": {"minX": 340, "minY": 255, "maxX": 465, "maxY": 345},
            "p-U2": {"minX": 640, "minY": 255, "maxX": 765, "maxY": 345},
            "new-w": {"minX": 445, "minY": 310, "maxX": 655, "maxY": 320}},
)

LIVE_AFTER = LIVE_BEFORE


def _group_pins(table, names):
    return {f"p-{name}": dict(table.get(f"p-{name}") or {}) for name in names}


def _move_plan(tmp_path, *, dx=100.0, dy=0.0, designators=("U1", "U2"), name="plan.json"):
    """A two-part move plan built the way the CLI builds it, minus the bridge."""
    group = [
        mb.Part(designator=item, primitive_id=f"p-{item}", x=x, y=300.0, rotation=0.0,
                at=(x, 300.0))
        for item, x in (("U1", 300.0), ("U2", 600.0))
        if item in designators
    ]
    pins = {item.designator: PINS[f"p-{item.designator}"] for item in group}
    wires = mb.plan_wires(PAGE, group, pins, dx, dy)
    plan = move_block_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        moves=[
            PlanMove(designator=item.designator, primitive_id=item.primitive_id,
                     from_at=item.at, from_rotation=item.rotation,
                     to_at=(item.x + dx, item.y + dy))
            for item in group
        ],
        wire_ops=[mb.wire_op_from(item) for item in wires],
        islands=mb.plan_islands(
            {("U1", "5"): "GROUP_NET", ("U2", "1"): "GROUP_NET"}, group, pins),
        designators=[item.designator for item in group],
        dx=dx, dy=dy,
        baseline_findings=["some-rule|WARN|old|1|"],
    )
    path = tmp_path / name
    plan.dump(path)
    return path, plan


# --------------------------------------------------------------------------
# 1. the engine: poses, the grid, the group
# --------------------------------------------------------------------------


def test_poses_and_the_group_resolve_by_designator():
    page = mb.poses(PAGE)
    assert set(page) == {"U1", "U2"}
    assert page["U2"].at == (600.0, 300.0) and page["U2"].primitive_id == "p-U2"
    group = mb.resolve_group(PAGE, ["U1"], {"U1": PINS["p-U1"]})
    assert [item.designator for item in group] == ["U1"]


def test_a_designator_that_is_not_there_is_refused_by_name():
    with pytest.raises(mb.MoveRefused) as caught:
        mb.resolve_group(PAGE, ["R7"], {"R7": {}})
    assert "R7 is not on the focused page" in str(caught.value)


def test_a_designator_carried_twice_is_ambiguity_and_refused():
    twice = _geometry(components=[("U1", 300.0, 300.0), ("U1", 320.0, 300.0)])
    with pytest.raises(mb.MoveRefused) as caught:
        mb.resolve_group(twice, ["U1"], {"U1": PINS["p-U1"]})
    assert "times — one designator, two parts" in str(caught.value)


def test_a_designator_with_no_pins_is_not_a_part():
    frame = _geometry(components=[("SHEET1", 0.0, 0.0)])
    with pytest.raises(mb.MoveRefused) as caught:
        mb.resolve_group(frame, ["SHEET1"], {"SHEET1": {}})
    assert "reports no pins" in str(caught.value)


def test_the_grid_is_five_units_and_both_the_delta_and_the_pose_must_be_on_it():
    group = mb.resolve_group(PAGE, ["U1"], {"U1": PINS["p-U1"]})
    mb.check_grid(group, 100.0, 0.0)
    with pytest.raises(mb.MoveRefused) as caught:
        mb.check_grid(group, 102.0, 0.0)
    assert "not a multiple of the 5-unit grid" in str(caught.value)
    off = _geometry(components=[("U1", 302.0, 300.0)])
    group_off = mb.resolve_group(off, ["U1"], {"U1": PINS["p-U1"]})
    with pytest.raises(mb.MoveRefused) as caught:
        mb.check_grid(group_off, 100.0, 0.0)
    assert "is not on the 5-unit grid" in str(caught.value)


# --------------------------------------------------------------------------
# 2. the wires: internal shifts, boundary redraws, and the refusals
# --------------------------------------------------------------------------


def test_a_wire_between_two_group_pins_moves_with_the_group():
    group = mb.resolve_group(PAGE, ["U1", "U2"], {"U1": PINS["p-U1"], "U2": PINS["p-U2"]})
    wires = mb.plan_wires(PAGE, group, {"U1": PINS["p-U1"], "U2": PINS["p-U2"]}, 100.0, 0.0)
    assert len(wires) == 1
    after = wires[0].points_after
    assert after[0] == (445.0, 310.0) and after[-1] == (655.0, 320.0), (
        "the redraw connects the two moved pins"
    )
    assert len(after) == 3, (
        "reconstructed orthogonally: the reported point list is a set, not a path,"
        " and its consecutive pairs can be diagonal"
    )
    assert "internal wire (U1.5 ↔ U2.1)" in wires[0].why


def test_a_wire_leaving_the_group_is_redrawn_orthogonally_to_its_original_far_point():
    page = _geometry(
        components=[("U1", 300.0, 300.0), ("U2", 600.0, 300.0)],
        wires=[("w-link", "N", [(345.0, 310.0), (345.0, 320.0), (555.0, 320.0)])],
    )
    group = mb.resolve_group(page, ["U1"], {"U1": PINS["p-U1"]})
    wires = mb.plan_wires(page, group, {"U1": PINS["p-U1"]}, 100.0, 0.0)
    assert len(wires) == 1
    after = wires[0].points_after
    assert after[0] == (445.0, 310.0), "starts at the moved pin"
    assert after[-1] == (555.0, 320.0), "and reaches the far point that did not move"
    assert len(after) == 3, "two legs, so the route is orthogonal (029's rule)"


def test_a_wire_that_only_crosses_a_group_pin_is_left_alone_and_identity_catches_it():
    """Measured 2026-09-25: 035's segment-based T test is **unsound** on this host.

    The host reports a wire as a point **set** whose consecutive pairs can be
    diagonals that were never drawn, so "is the pin strictly inside a reported
    segment" both misses real junctions and invents false ones — it refused a
    legitimate one-part move on the machine. What the instrument can say soundly
    is "the pin is one of the reported points". A wire that merely crosses the pin
    is therefore not moved, and if that breaks a connection the netlist identity
    judgement reports it by name instead of a guess refusing the move.
    """
    page = _geometry(
        components=[("U1", 300.0, 300.0)],
        wires=[("w-t", "N", [(200.0, 310.0), (500.0, 310.0)])],
    )
    group = mb.resolve_group(page, ["U1"], {"U1": PINS["p-U1"]})
    assert mb.plan_wires(page, group, {"U1": PINS["p-U1"]}, 100.0, 0.0) == []
    # ...and a wire the pin *does* report a junction on is moved with it:
    joined = _geometry(
        components=[("U1", 300.0, 300.0)],
        wires=[("w-j", "N", [(345.0, 310.0), (200.0, 310.0)])],
    )
    group2 = mb.resolve_group(joined, ["U1"], {"U1": PINS["p-U1"]})
    moved = mb.plan_wires(joined, group2, {"U1": PINS["p-U1"]}, 100.0, 0.0)
    assert len(moved) == 1 and moved[0].points_after[0] == (445.0, 310.0)



def test_a_wire_wh_se_order_is_out_of_order_is_still_internal_or_boundary():
    """The host reports a wire's points with the junction **repeated** and out of
    order — measured 2026-09-25 on the real page: a two-leg wire from (345,310) to
    (555,320) came back as `[345, 320, 345, 310, 555, 320, 345, 320]`. Judging 'does
    it pass through this pin' from the *position* of a point in that list refused a
    perfectly ordinary wire (a T on U1.5 and U2.1, both of which are its own ends).
    The judgement is 035's helper, which asks whether the pin is strictly inside a
    segment — order and repeats do not matter there."""
    reported = _geometry(
        components=[("U1", 300.0, 300.0), ("U2", 600.0, 300.0)],
        wires=[("w-link", "N", [(345.0, 320.0), (345.0, 310.0), (555.0, 320.0),
                                 (345.0, 320.0)])],
    )
    group = mb.resolve_group(reported, ["U1", "U2"],
                             {"U1": PINS["p-U1"], "U2": PINS["p-U2"]})
    wires = mb.plan_wires(reported, group,
                          {"U1": PINS["p-U1"], "U2": PINS["p-U2"]}, 100.0, 0.0)
    assert len(wires) == 1 and wires[0].primitive_id == "w-link"

def test_a_boundary_wire_ending_on_a_label_is_refused():
    page = _geometry(
        components=[("U1", 300.0, 300.0)],
        wires=[("w-stub", "N", [(345.0, 310.0), (500.0, 310.0)])],
        netlabels=[("N", 500.0, 310.0)],
    )
    group = mb.resolve_group(page, ["U1"], {"U1": PINS["p-U1"]})
    with pytest.raises(mb.MoveRefused) as caught:
        mb.plan_wires(page, group, {"U1": PINS["p-U1"]}, 100.0, 0.0)
    assert "netlabel" in str(caught.value) and "v1 一律拒绝" in str(caught.value)


def test_a_wire_that_touches_no_group_pin_is_left_alone():
    page = _geometry(
        components=[("U1", 300.0, 300.0), ("U9", 900.0, 300.0)],
        wires=[("w-other", "OTHER", [(800.0, 300.0), (860.0, 300.0)])],
    )
    group = mb.resolve_group(page, ["U1"], {"U1": PINS["p-U1"]})
    assert mb.plan_wires(page, group, {"U1": PINS["p-U1"]}, 100.0, 0.0) == []


def test_a_target_that_is_occupied_or_inside_a_box_is_refused():
    group = mb.resolve_group(PAGE, ["U1"], {"U1": PINS["p-U1"]})
    with pytest.raises(mb.MoveRefused) as caught:
        mb.check_target_free(PAGE, group, 300.0, 0.0)   # lands on U2's origin
    assert "is occupied" in str(caught.value)
    boxed = _geometry(
        components=[("U1", 300.0, 300.0)],
        bboxes={"blocker": {"minX": 380, "minY": 280, "maxX": 450, "maxY": 330}},
    )
    group2 = mb.resolve_group(boxed, ["U1"], {"U1": PINS["p-U1"]})
    with pytest.raises(mb.MoveRefused) as caught:
        mb.check_target_free(boxed, group2, 100.0, 0.0)
    assert "bounding box" in str(caught.value)


# --------------------------------------------------------------------------
# 3. the identity judgement
# --------------------------------------------------------------------------


def test_islands_group_by_name_and_an_empty_reading_has_no_mates():
    live = {("U1", "5"): "$61N2", ("U2", "1"): "$61N2", ("U3", "1"): "", ("U4", "1"): ""}
    reading = mb.islands(live)
    assert reading[("U1", "5")] == frozenset({("U2", "1")})
    assert reading[("U2", "1")] == frozenset({("U1", "5")})
    assert reading[("U3", "1")] == frozenset(), (
        "two unattached pins both read '' and must not look like one island"
    )


def test_netlist_differences_names_every_pin_that_changed_company():
    before = {("U1", "5"): "N", ("U2", "1"): "N", ("U9", "1"): "M"}
    after = {("U1", "5"): "N", ("U2", "1"): "M2", ("U9", "1"): "M"}
    problems = mb.netlist_differences(before, after)
    assert any("U1.5" in item and "U2.1" in item for item in problems)
    assert mb.netlist_differences(before, before) == []


def test_postconditions_check_poses_rotation_endpoints_and_the_identity(tmp_path):
    path, plan = _move_plan(tmp_path)
    live = {("U1", "5"): "GROUP_NET", ("U2", "1"): "GROUP_NET"}
    ok = mb.postcondition_problems(plan, geometry=PAGE_AFTER, live=live)
    assert ok == {"live": [], "canvas": []}, ok
    assert mb.all_satisfied(ok)

    # A part that did not move is a canvas problem...
    state = mb.postcondition_problems(plan, geometry=PAGE, live=live)
    assert any("U1 is at (300, 300)" in item for item in state["canvas"])
    # ...and a pin that changed company is a live one.
    split = {("U1", "5"): "GROUP_NET", ("U2", "1"): "OTHER"}
    state = mb.postcondition_problems(plan, geometry=PAGE_AFTER, live=split)
    assert any("changed company" in item for item in state["live"])
    assert not mb.all_satisfied(state)


# --------------------------------------------------------------------------
# 4. the plan shape
# --------------------------------------------------------------------------


def test_a_move_plan_round_trips_and_refuses_the_shapes_apply_cannot_execute(tmp_path):
    path, plan = _move_plan(tmp_path)
    again = ChangePlan.load(path)
    assert again.to_jsonable() == plan.to_jsonable()
    assert again.change.kind == MOVE_BLOCK_KIND
    assert [item.designator for item in again.change.moves] == ["U1", "U2"]
    assert again.change.wire_ops[0].kind == "redraw"
    assert again.change.islands[0].pin.startswith("U")

    payload = plan.to_jsonable()
    payload["change"]["moves"][0]["to"]["x"] = 402.0          # off-grid
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "not a multiple of the 5-unit grid" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"]["moves"] = []
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "change.moves must list the parts" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"]["moves"][1]["designator"] = "U1"
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "lists 'U1' twice" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"]["moves"][0]["primitiveId"] = ""
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "primitiveId is empty" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"]["wireOps"][0]["kind"] = "translate"
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "this build redraws wires" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"]["wireOps"][0]["primitiveId"] = ""
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "primitiveId is empty" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"].pop("islands")
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "change.islands must record" in str(caught.value)

    payload = plan.to_jsonable()
    payload["change"].pop("baselineFindings")
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "baselineFindings must be a list" in str(caught.value)

    payload = plan.to_jsonable()
    payload["target"].pop("designators")
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "target.designators must name the group" in str(caught.value)

    payload = plan.to_jsonable()
    payload["target"]["dy"] = None
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "target.dy must be a number" in str(caught.value)


def test_the_older_kinds_did_not_gain_the_move_keys():
    """016/029/035/036 JSON 一字不变: the move keys are written only for move-block."""
    plan = add_component_plan(
        PlanSource(input_sha256="a" * 64), anchor="U1", designator="C7",
        part=__import__("boardwise.core.changeplan", fromlist=["PlanPart"]).PlanPart(
            lcsc="C1525", value="0.1uF"),
        connections=[],
        x=0.0, y=0.0, recipe_source="operator:C1525",
    )
    payload = plan.to_jsonable()
    assert "moves" not in payload["change"] and "wireOps" not in payload["change"]
    assert "islands" not in payload["change"]
    assert set(payload["target"]) == {
        "primitiveId", "designator", "expectedValue", "anchor", "assignedDesignator",
        "x", "y", "connection", "connectionDetail",
    }
    assert payload["change"]["kind"] == ADD_COMPONENT_KIND


def test_every_m3_kind_is_executable_so_the_later_kinds_table_is_empty():
    from boardwise.core import changeplan

    assert changeplan._LATER_KINDS == {}
    assert MOVE_BLOCK_KIND in changeplan.SUPPORTED_KINDS
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable({
            "planVersion": 1, "source": {"inputSha256": "a" * 64},
            "target": {"designator": "U1"}, "change": {"kind": "teleport"},
        })
    message = str(caught.value)
    assert "teleport" in message and "M3 follow-ups" not in message


def test_the_finding_signature_is_the_subject_not_the_sentence():
    """037 reuses 036's signature: a reworded finding about the same subject is not
    a new one, and an auto-renumbered net is not either."""
    from boardwise.rules.base import Finding, FindingTarget

    first = Finding(rule_id="r", severity="WARN", message="before", level="L2",
                    target=FindingTarget(component_ref="U1", pin_refs=["5"],
                                         net_refs=["NET3"]))
    second = Finding(rule_id="r", severity="WARN", message="after", level="L2",
                     target=FindingTarget(component_ref="U1", pin_refs=["5"],
                                          net_refs=["NET4"]))
    assert _finding_signature(first) == _finding_signature(second)


# --------------------------------------------------------------------------
# 5. the CLI: `edit plan --move`, `edit preview`, `edit apply`
# --------------------------------------------------------------------------


def _move_bridge(*, after_geometry=PAGE_AFTER, netlists=(LIVE_BEFORE, LIVE_AFTER),
                 modify_fails=0, after_pins=None):
    return _FakeBridge(geometry=[PAGE], after_geometry=after_geometry, pins=PINS,
                       after_pins=after_pins if after_pins is not None else PINS,
                       netlists=list(netlists), modify_fails=modify_fails)


def test_plan_move_builds_the_plan_from_the_live_page(monkeypatch, tmp_path, capsys):
    _stub_bridge(monkeypatch, _move_bridge())
    _stub_export(monkeypatch, [_model(components=[("U1", ("", "")), ("U2", ("", ""))])])
    out = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--move", "--designators", "U1,U2", "--dx", "100", "--dy", "0",
        "-o", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    assert plan.change.kind == MOVE_BLOCK_KIND
    assert [(item.designator, item.to_at) for item in plan.change.moves] == [
        ("U1", (400.0, 300.0)), ("U2", (700.0, 300.0))]
    assert plan.change.wire_ops[0].primitive_id == "w-link"
    assert plan.change.wire_ops[0].points_after[0] == (445.0, 310.0)
    assert [item.pin for item in plan.change.islands] == (
        [f"U1.{n}" for n in ("1", "2", "3", "4", "5")]
        + [f"U2.{n}" for n in ("1", "2", "3", "4", "5")]
    )
    assert "move    U1 (p-U1) (300, 300) rot 0° → (400, 300)" in printed
    assert "identity: 10 pin(s) recorded" in printed


@pytest.mark.parametrize(
    "argv, keyword",
    [
        (["--move", "--dx", "100", "--dy", "0"], "--move needs --designators"),
        (["--move", "--designators", "U1", "--dx", "100"], "--move needs both --dx and --dy"),
        (["--move", "--designators", "U1", "--dx", "102", "--dy", "0"],
         "not a multiple of the 5-unit grid"),
        (["--move", "--designators", "U1,U1", "--dx", "100", "--dy", "0"],
         "lists a designator twice"),
        (["--move", "--designators", "R7", "--dx", "100", "--dy", "0"],
         "R7 is not on the focused page"),
        (["--move", "--designators", "U1", "--dx", "300", "--dy", "0"],
         "is occupied"),
        (["--move", "--designators", "U1", "--dx", "100", "--dy", "0",
          "--insert", "divider"], "neither --report nor --insert"),
    ],
)
def test_plan_move_refuses_what_it_cannot_plan(monkeypatch, tmp_path, capsys, argv, keyword):
    _stub_bridge(monkeypatch, _move_bridge())
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "plan", *argv, "-o", str(tmp_path / "p.json")])
    captured = capsys.readouterr()
    assert code == 5
    assert keyword in captured.err


def test_plan_move_refuses_a_file(monkeypatch, tmp_path, capsys):
    _stub_bridge(monkeypatch, _move_bridge())
    code = cli.main(["edit", "plan", "--move", "--designators", "U1",
                     "--dx", "100", "--dy", "0", "--file", str(tmp_path / "x.epro2")])
    assert code == 5
    assert "does not read --file" in capsys.readouterr().err


def test_preview_lists_a_move_plan_without_a_snapshot(tmp_path, capsys):
    path, _plan = _move_plan(tmp_path)
    code = cli.main(["edit", "preview", str(path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "plan: move-block U1, U2 by (100, 0)" in printed
    assert "move    U1 (p-U1) (300, 300) rot 0° → (400, 300)" in printed
    assert "wire    w-link net GROUP_NET" in printed
    assert "live page only — check with `edit apply`" in printed


def test_apply_move_moves_the_parts_redraws_the_wire_and_saves(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _move_plan(tmp_path)
    bridge = _move_bridge()
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [
        _model(components=[("U1", ("", "")), ("U2", ("", ""))]),
        _model(components=[("U1", ("", "")), ("U2", ("", ""))]),
    ])
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan_path), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert [action for action, _ in bridge.writes] == [
        "sch.modify_primitive", "sch.modify_primitive",
        "sch.delete_primitives", "sch.place_wire", "sch.doc.save",
    ], "parts first, then the wire off, then its replacement, then the save"
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["identity"]["differences"] == []
    assert report["verification"]["ok"] is True
    assert report["range"]["wiresVanished"] == ["w-link"]
    assert report["range"]["authorized"] == ["w-link"]
    assert "canvas identity" in report["rangeBasis"]
    assert report["persistence"] == "saved_unverified"


def test_apply_move_is_idempotent_when_the_poses_and_the_netlist_hold(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _move_plan(tmp_path)
    bridge = _move_bridge(netlists=(LIVE_AFTER,))
    bridge.geometry = [PAGE_AFTER]          # the group is already where the plan says
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "already_applied" in printed and "idempotent" in printed
    assert bridge.writes == []


def test_apply_move_refuses_a_pose_that_moved_since_the_plan(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _move_plan(tmp_path)
    moved = _geometry(components=[("U1", 305.0, 300.0), ("U2", 600.0, 300.0)],
                      wires=[("w-link", "GROUP_NET",
                              [(345.0, 310.0), (345.0, 320.0), (555.0, 320.0)])])
    bridge = _move_bridge()
    bridge.geometry = [moved]
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "apply", str(plan_path)])
    captured = capsys.readouterr()
    assert code == 4
    assert "stale_pose" in captured.out
    assert bridge.writes == []


def test_apply_move_refuses_when_a_wire_it_would_take_off_is_gone(
    monkeypatch, tmp_path, capsys
):
    plan_path, _plan = _move_plan(tmp_path)
    stripped = _geometry(components=[("U1", 300.0, 300.0), ("U2", 600.0, 300.0)])
    bridge = _move_bridge()
    bridge.geometry = [stripped]
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "apply", str(plan_path)])
    captured = capsys.readouterr()
    assert code == 4
    assert "wire_missing" in captured.out
    assert bridge.writes == []


def test_apply_move_fails_the_identity_judgement_when_a_connection_changes(
    monkeypatch, tmp_path, capsys
):
    """The acceptance's main judgement: a move may not change any connection."""
    plan_path, _plan = _move_plan(tmp_path)
    broken = _live(("U1", {"1": "", "2": "", "3": "", "4": "", "5": "GROUP_NET"}),
                   ("U2", {"1": "SOMEWHERE_ELSE", "2": "", "3": "", "4": "", "5": ""}))
    bridge = _move_bridge(netlists=(LIVE_BEFORE, broken))
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    result = tmp_path / "a.json"
    code = cli.main(["edit", "apply", str(plan_path), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 2, printed
    assert "netlist_changed" in printed
    report = json.loads(result.read_text(encoding="utf-8"))
    assert any("U1.5" in item for item in report["identity"]["differences"])
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_apply_move_fails_the_range_when_another_wire_vanished(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _move_plan(tmp_path)
    page = _geometry(
        components=[("U1", 300.0, 300.0), ("U2", 600.0, 300.0)],
        wires=[("w-link", "GROUP_NET", [(345.0, 310.0), (345.0, 320.0), (555.0, 320.0)]),
               ("w-innocent", "OTHER", [(700.0, 400.0), (760.0, 400.0)])],
    )
    after = _geometry(
        components=[("U1", 400.0, 300.0), ("U2", 700.0, 300.0)],
        wires=[("new-w", "GROUP_NET", [(445.0, 310.0), (445.0, 320.0), (655.0, 320.0)])],
    )
    bridge = _move_bridge(after_geometry=after)
    bridge.geometry = [page]
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 2
    assert "range_canvas_diff" in printed
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_apply_move_judges_unknown_when_the_canvas_leg_disagrees(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _move_plan(tmp_path)
    bridge = _move_bridge(after_geometry=PAGE)      # the parts did not move on the canvas
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [_model()])
    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 3, printed
    assert "verification_disagrees" in printed
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_apply_move_retries_once_when_the_host_broke_before_changing_anything(
    monkeypatch, tmp_path, capsys
):
    """Measured: the host's `modify` intermittently throws a TypeError *before*
    changing the pose (`outputs/037_probe.txt`). The flow reads the pose back, and
    only because that proves nothing landed does it try once more."""
    plan_path, _plan = _move_plan(tmp_path)
    bridge = _move_bridge(modify_fails=1)
    bridge.geometry_sequence = [PAGE, PAGE, PAGE_AFTER]
    _stub_bridge(monkeypatch, bridge)
    _stub_export(monkeypatch, [
        _model(components=[("U1", ("", "")), ("U2", ("", ""))]),
        _model(components=[("U1", ("", "")), ("U2", ("", ""))]),
    ])
    code = cli.main(["edit", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert bridge.modify_attempts == 3, "one retry for the first part, then the second"
    assert "is tried once more" in printed


def test_apply_move_fails_when_a_rule_reports_something_new(monkeypatch, tmp_path, capsys):
    plan_path, _plan = _move_plan(tmp_path)
    bridge = _move_bridge()
    _stub_bridge(monkeypatch, bridge)
    grown = _model(components=[("U9", ("", "C47773"))], pins={"U9": ["1", "5"]},
                   nets={"VIN_RAW": [("U9", "1")]})
    _stub_export(monkeypatch, [_model(), grown])
    code = cli.main(["edit", "apply", str(plan_path), "--json", str(tmp_path / "a.json")])
    printed = capsys.readouterr().out
    assert code == 2, printed
    assert "new_findings" in printed
    report = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert report["findings"]["new"]
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]
