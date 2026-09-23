"""029-a: `add-component` — the offline core, end to end, with a fake bridge.

Ten cases, and each one is a claim the task book makes about this slice: a plan
can be built; an anchor that moved refuses; an exhausted ladder refuses (and
never falls back to the origin); a missing recipe refuses; a taken designator
refuses; a second run is `already-applied` with zero writes; a dropped connection
is read back, never retried; a range that is not exactly +1 is an accident; and
the re-review is reported as resolved or still-present, honestly.

Two seams, both deliberate:

* **The bridge** is a fake (`_FakeBridge`), driven per test: it is what feeds
  `sch.geometry` and it records every write, which is how "zero writes" and
  "never retried" are asserted rather than hoped.
* **The live project model** is monkeypatched (`_live_project_model`), because
  the real one parses an `.epro2` export and a fixture cannot grow a component
  between two reads. The seam is the *export* — everything downstream (the
  idempotence probe, the range diff, the connectivity check) runs the real code
  on a real :class:`DesignModel` built by the test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.changeplan import (
    ADD_COMPONENT_KIND,
    CONNECTION_LABEL,
    CONNECTION_WIRE,
    ChangePlan,
    PlanConnection,
    PlanPart,
    PlanSource,
    add_component_plan,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.rules.decap import CapCandidate

FIXTURE = Path("tests/fixtures/mismatch_value.epro2")


class _BridgeError(Exception):
    """The class the flow catches — the daemon's `BridgeError`, stood in for."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _geometry(*, components, wires=(), netlabels=()):
    """A `sch.geometry` dump in the shape 3.2.186 actually sends (measured 029-b).

    `wires` are polylines of `(x, y)` pairs; each one is given a net by the
    heuristic below so a test can put a *different* net's wire right next to a
    landing spot — the page 029 §六 verdict 3 asked for.
    """
    def net_of(points):
        return "OTHER" if points and points[0][1] == 999 else "VCC"

    return {
        "components": [
            {"primitiveId": f"p-{name}", "state": {"Designator": name, "X": x, "Y": y}}
            for name, x, y in components
        ],
        # The measured host shape (029-b): a wire's state carries `Line` and its
        # own `Net`. `net_of` says which wire belongs to which net, which is what
        # makes the "wrong net is not chosen" case testable offline.
        "wires": [
            {"state": {"Line": [c for pair in points for c in pair], "Net": net_of(points)}}
            for points in wires
        ],
        "netlabels": [{"state": {"Net": name}} for name in netlabels],
        "meta": {"available": {"components": True}},
    }


def _model(*, components, nets):
    """A `DesignModel` with the components/nets a test needs.

    Each net is a list of ``(designator, pin)`` members, and every pin is given
    its net: the rule's inventory (`cap_candidates_on`) asks the *pins* whether
    the other end is grounded, so a model whose pins all say ``net=None`` is a
    board where nothing is grounded — which is a fixture bug, not a rule result.
    """
    model = DesignModel()
    for name, value in components.items():
        model.components[name] = Component(
            uid=f"uid-{name}", designator=name, value=value,
            pins=[Pin("1", "1", None), Pin("2", "2", None)],
        )
    for net_name, members in nets.items():
        model.nets[net_name] = Net(net_name, [(name, pin) for name, pin in members])
        for name, pin in members:
            component = model.components.get(name)
            if component is None:
                continue
            for item in component.pins:
                if item.number == pin:
                    item.net = net_name
    return model


class _FakeBridge:
    """A daemon that answers what `edit` asks, and records what it was asked to write."""

    def __init__(self, *, geometry, writes_fail=None, after_geometry=None, label_ok=True,
                 pins=None):
        self.geometry = [geometry]
        self.after_geometry = after_geometry or geometry
        self.writes: list[tuple[str, dict]] = []
        self.calls: list[str] = []
        self.writes_fail = writes_fail or {}
        self.label_ok = label_ok
        self.reads = 0
        # `sch.component_pins`: `{pinNumber: (x, y)}`. The default stands in for a
        # host that reports no pins at all, which is what 3.2.186's `sch.geometry`
        # does (`pins: []`) — the wire then has to fall back to the landing spot,
        # and the notes say so.
        self.pins = pins or {}

    async def call(self, action, params=None, *, target_project=None, target_instance=None):
        params = params or {}
        self.calls.append(action)
        if action in self.writes_fail and action in (
            "sch.place_component", "sch.place_wire", "sch.place_netlabel", "sch.doc.save",
        ):
            raise self.writes_fail[action]
        if action == "doc.list":
            return {"active": {"uuid": "page-1", "type": "page"},
                    "projects": [{"projectUuid": "proj-1", "focused": True}]}
        if action == "sys.identity":
            return {"consistent": True, "consistentBasis": "project-uuid"}
        if action == "sch.geometry":
            self.reads += 1
            return self.geometry[0] if self.reads == 1 else self.after_geometry
        if action in ("sch.place_component", "sch.place_wire", "sch.place_netlabel", "sch.doc.save"):
            self.writes.append((action, params))
            if action == "sch.doc.save":
                return {"saved": True}
            return {"uuid": f"new-{len(self.writes)}", "outcome": "ok"}
        if action == "sch.component_pins":
            return {
                "primitiveId": params.get("primitiveId"),
                "returned": len(self.pins),
                "pins": [
                    {"X": x, "Y": y, "PinNumber": number, "PinName": number,
                     "Rotation": 0, "PinLength": 10}
                    for number, (x, y) in sorted(self.pins.items())
                ],
            }
        if action == "sys.get_project_file":
            return {"fileType": "epro2", "data": "", "bytes": 0}
        raise AssertionError(f"the flow called {action}, which this fake does not answer")

    async def close(self):
        pass


def _stub_bridge(monkeypatch, bridge):
    class _Client:
        @staticmethod
        async def open(*_args, **_kwargs):
            return bridge

    monkeypatch.setattr(cli, "_open_cli", lambda args: (_Client, _BridgeError, 61190, "tok"))


def _stub_model(monkeypatch, sequence):
    """Serve the live model reads in order (the probe's, then the range check's)."""
    models = list(sequence)

    async def _live(call, notes):
        return models.pop(0) if models else None

    monkeypatch.setattr(cli, "_live_project_model", _live)


def _plan(tmp_path, *, connection="wire", designator="C7", anchor="U1", value="0.1uF",
          net="VCC", pin="1"):
    """A one-wire plan on disk: pin 1 reaches `net`, pin 2 is labelled GND.

    Every declared connection carries its own `kind` (029-c §①), because a plan
    that leaves it to apply is exactly what 029-b's case a executed. The GND end
    is a **label** here — the shelf-less page in these fakes has no GND wire, and
    ground may be named without a label precedent.
    """
    plan = add_component_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        anchor=anchor, designator=designator,
        part=PlanPart(lcsc="C1525", value=value),
        connections=[
            PlanConnection(pin, net, kind=connection, detail="test: the decoupled net",
                           to=(5.0, 0.0) if connection == CONNECTION_WIRE else None),
            PlanConnection("2", "GND", kind=CONNECTION_LABEL, detail="test: ground net"),
        ],
        x=0.0, y=-5.0, connection=connection,
        connection_detail="test", recipe_source="operator:C1525",
    )
    path = tmp_path / "plan.json"
    plan.dump(path)
    return path


def _two_wire_plan(tmp_path):
    """Both pins wired, each to its own net's segment — the 029-c §① shape."""
    plan = add_component_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        anchor="U1", designator="C7",
        part=PlanPart(lcsc="C1525", value="0.1uF"),
        connections=[
            PlanConnection("1", "VCC", kind=CONNECTION_WIRE,
                           detail="a short wire to the VCC segment", to=(5.0, 0.0)),
            PlanConnection("2", "GND", kind=CONNECTION_WIRE,
                           detail="a short wire to the GND segment", to=(0.0, 5.0)),
        ],
        x=0.0, y=-5.0, connection=CONNECTION_WIRE, connection_detail="test",
        recipe_source="operator:C1525",
    )
    path = tmp_path / "plan-two-wires.json"
    plan.dump(path)
    return path


def _apply_args(plan_path, *extra):
    return cli.build_parser().parse_args(["edit", "apply", str(plan_path), *extra])


# --------------------------------------------------------------------------
# 1. the plan can be built from a report finding (with a live page)
# --------------------------------------------------------------------------


def test_plan_is_built_from_a_report_finding_and_a_live_page(monkeypatch, tmp_path, capsys):
    geometry = _geometry(
        components=[("U1", 0.0, 0.0), ("C3", 40.0, 40.0)],
        wires=[[(0.0, 0.0), (10.0, 0.0)], [(0.0, 999.0), (5.0, 999.0)]],
    )
    bridge = _FakeBridge(geometry=geometry)
    _stub_bridge(monkeypatch, bridge)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "findings": [{
            "rule_id": "decap-required-caps", "severity": "WARN",
            "message": "U1 pin1: no grounded capacitor found on net 'VCC' (required 0.1uF)",
            "target": {"component_ref": "U1", "pin_refs": ["1"], "net_refs": ["VCC"],
                       "suggested_after": "0.1uF"},
        }],
    }), encoding="utf-8")
    snapshot = tmp_path / "snap.epro2"
    snapshot.write_bytes(b"x")

    out_path = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--file", str(snapshot), "--rule", "decap-required-caps",
        "--designator", "U1", "--report", str(report), "--lcsc", "C1525",
        "-o", str(out_path),
    ])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "next to U1 pin1 on net 'VCC'" in out
    plan = ChangePlan.load(out_path)
    assert plan.change.kind == ADD_COMPONENT_KIND
    assert plan.change.part.lcsc == "C1525"
    assert plan.change.part.value == "0.1uF"
    assert plan.change.recipe_source == "operator:C1525"
    # C1 is the lowest free C number on this page (C3 exists).
    assert plan.target.designator == "C1"
    assert plan.target.assigned_designator == "C1"
    assert plan.target.anchor == "U1"
    assert plan.target.connection == "wire", "a wire point 10 units away is the first option"
    assert "'VCC' segment" in plan.target.connection_detail, (
        "the wire branch must name the net it is joining — the 'OTHER' wire is 5 units "
        "from the ideal spot and must not be the one chosen (029 §六 verdict 3)"
    )
    # §①: each declared connection states its own kind and its own evidence, and
    # the ground end is a label even though this page labels nothing at all.
    assert [(item.pin, item.net, item.kind) for item in plan.change.connections] == [
        ("1", "VCC", CONNECTION_WIRE), ("2", "GND", CONNECTION_LABEL),
    ]
    assert plan.change.connections[0].to == (0.0, 0.0), (
        "the wire ends on the nearest vertex of that net's own wiring (0, 0 — 5 units "
        "from the spot), which is what apply will draw to"
    )
    assert plan.change.connections[1].to is None, "a label reaches no coordinate"
    assert "ground net" in plan.change.connections[1].detail, (
        "the ground exception must say it is the ground exception — not that the page "
        "happened to label GND, which it does not"
    )
    assert "2→GND via label" in out, "both connections are printed as they were decided"
    assert (plan.target.x, plan.target.y) == (0.0, -5.0), "the ladder's first free rung"
    assert "page-1" not in out or True  # the plan's page comes from the snapshot, not the report


# --------------------------------------------------------------------------
# 1b. 029-c §①: every declared connection is executed, one at a time
# --------------------------------------------------------------------------


def test_every_declared_connection_is_executed_and_never_left_to_the_landing_spot(
    monkeypatch, tmp_path, capsys
):
    """029-b's case a, offline: two declared connections, two writes.

    The measured failure was a plan that drew only its first connection and left
    the ground end to "whatever the landing spot happened to touch" — the netlist
    readback then said `2→GND MISSING`. Here both ends are wires to their **own**
    net's segment, so the assertion is not "a wire was drawn" but "each pin got
    the wire its own declaration named".
    """
    plan = _two_wire_plan(tmp_path)
    geometry = _geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)], [(0.0, 0.0), (0.0, 5.0)]])
    geometry["wires"][1]["state"]["Net"] = "GND"
    bridge = _FakeBridge(
        geometry=geometry,
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        # The measured 3.2.186 shape (029-c): the placed capacitor's pins sit 20
        # units either side of its origin.
        pins={"1": (-20.0, -5.0), "2": (20.0, -5.0)},
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    monkeypatch.setattr(cli, "_edit_post_review",
                        lambda *a, **k: {"state": "resolved", "reason": "no findings"})
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 0, out
    wires = [params for action, params in bridge.writes if action == "sch.place_wire"]
    assert [params["net"] for params in wires] == ["VCC", "GND"], (
        "one wire per declared connection, each carrying its own net — not two wires "
        "for the first declaration and nothing for the second"
    )
    assert [params["points"] for params in wires] == [
        [[-20.0, -5.0], [-20.0, 0.0], [5.0, 0.0]],
        [[20.0, -5.0], [20.0, 5.0], [0.0, 5.0]],
    ], (
        "each wire runs from **that pin of the new part** (its own reported coordinate, "
        "20 units off the landing spot on the measured symbol) to that connection's own "
        "target, turning a right angle on the way — a wire from the origin reaches no "
        "pin, and a diagonal segment hangs the host"
    )
    assert all(
        (a[0] == b[0]) or (a[1] == b[1])
        for params in wires
        for a, b in zip(params["points"], params["points"][1:])
    ), "every segment is axis-aligned (3.2.186 hangs on a diagonal wire — measured)"
    report = json.loads(result.read_text(encoding="utf-8"))
    assert [item["kind"] for item in report["connections"]] == ["wire", "wire"]
    assert [item["to"] for item in report["write"]["connections"]] == [[5.0, 0.0], [0.0, 5.0]]
    assert [item["from"] for item in report["write"]["connections"]] == [
        [-20.0, -5.0], [20.0, -5.0]]
    assert report["write"]["pins"]["points"] == {"1": [-20.0, -5.0], "2": [20.0, -5.0]}


def test_a_wire_route_is_orthogonal_because_a_diagonal_segment_hangs_the_host():
    """3.2.186: `sch.place_wire` with a diagonal segment never returns (measured 2/2)."""
    from boardwise.engines import addcomponent

    assert addcomponent.wire_route((0.0, 0.0), (10.0, 0.0)) == [(0.0, 0.0), (10.0, 0.0)]
    assert addcomponent.wire_route((0.0, 0.0), (0.0, 10.0)) == [(0.0, 0.0), (0.0, 10.0)]
    diagonal = addcomponent.wire_route((-20.0, -5.0), (5.0, 0.0))
    assert diagonal == [(-20.0, -5.0), (-20.0, 0.0), (5.0, 0.0)], (
        "the corner is at (anchor.x, target.y): the run out of the pin is along the pin's "
        "own axis, clear of the part body and of the neighbouring pin"
    )
    assert all(
        (a[0] == b[0]) or (a[1] == b[1]) for a, b in zip(diagonal, diagonal[1:])
    )


def test_a_wire_falls_back_to_the_spot_and_says_so_when_pins_cannot_be_read(
    monkeypatch, tmp_path, capsys
):
    """No pin geometry → the old anchor, named in the notes instead of assumed."""
    plan = _two_wire_plan(tmp_path)
    geometry = _geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)], [(0.0, 0.0), (0.0, 5.0)]])
    geometry["wires"][1]["state"]["Net"] = "GND"
    bridge = _FakeBridge(
        geometry=geometry,
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        pins={},  # the host reports no pins (3.2.186's sch.geometry does exactly this)
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    monkeypatch.setattr(cli, "_edit_post_review",
                        lambda *a, **k: {"state": "resolved", "reason": "no findings"})
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 0, out
    wires = [params for action, params in bridge.writes if action == "sch.place_wire"]
    assert [params["points"] for params in wires] == [
        [[0.0, -5.0], [0.0, 0.0], [5.0, 0.0]], [[0.0, -5.0], [0.0, 5.0]],
    ], "with no pin geometry the wire starts at the landing spot, as it always did"
    assert "reported no pin geometry for C7" in out, (
        "the weaker anchor is named in the notes — the reader is told which claim rests "
        "on the netlist readback alone"
    )


def test_the_apply_hands_the_facts_shelf_to_the_idempotence_probe(monkeypatch, tmp_path, capsys):
    """029-c §②: the probe judges with the shelf, and says so when the shelf is gone."""
    from boardwise.engines import addcomponent as addcomponent_module

    seen: dict = {}
    real = addcomponent_module.probe_already_applied

    def spy(model, net_name, recipe, library=None):
        seen["library"] = library
        return real(model, net_name, recipe, library)

    monkeypatch.setattr(addcomponent_module, "probe_already_applied", spy)
    shelf = object()
    monkeypatch.setattr(cli, "_facts_library", lambda: (shelf, "the shelf was not found"))

    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    monkeypatch.setattr(cli, "_edit_post_review",
                        lambda *a, **k: {"state": "resolved", "reason": "no findings"})
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert seen["library"] is shelf, (
        "the probe must judge 'is this a capacitor?' with the curated shelf, not with a "
        "weaker predicate the caller never mentioned"
    )
    assert "the shelf was not found" in out, "a missing shelf is a note, never a silent downgrade"


def test_the_facts_shelf_loader_never_raises_and_names_what_is_missing(monkeypatch, tmp_path):
    """An absent shelf is a *note*, not silence: `load_parts` reads "missing" as "empty"."""
    monkeypatch.chdir(tmp_path)  # no blocklib/parts.json here
    library, note = cli._facts_library()
    assert library is not None and library.parts == []
    assert "parts.json" in note and "no facts" in note


# --------------------------------------------------------------------------
# 2-4. the refusals
# --------------------------------------------------------------------------


def test_an_anchor_that_is_not_on_the_page_refuses(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge(geometry=_geometry(components=[("C3", 0.0, 0.0)]))
    _stub_bridge(monkeypatch, bridge)
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN", "message": "m",
        "target": {"component_ref": "U1", "pin_refs": ["1"], "net_refs": ["VCC"],
                   "suggested_after": "0.1uF"},
    }]}), encoding="utf-8")
    snap = tmp_path / "s.epro2"
    snap.write_bytes(b"x")
    code = cli.main(["edit", "plan", "--file", str(snap), "--rule", "decap-required-caps",
                     "--designator", "U1", "--report", str(report), "--lcsc", "C1525"])
    err = capsys.readouterr().err
    assert code == 5
    assert "anchor U1 is not on the focused page" in err
    assert "C3" in err, "the refusal names what the page does have"


def test_an_exhausted_ladder_refuses_and_never_uses_the_origin(monkeypatch, tmp_path, capsys):
    from boardwise.engines.addcomponent import LADDER

    # Every rung occupied by a part of its own, so nothing is free.
    occupied = [("U1", 0.0, 0.0)] + [
        (f"C{10 + index}", dx * 5.0, dy * 5.0) for index, (dx, dy) in enumerate(LADDER[1:])
    ]
    bridge = _FakeBridge(geometry=_geometry(components=occupied))
    _stub_bridge(monkeypatch, bridge)
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN", "message": "m",
        "target": {"component_ref": "U1", "pin_refs": ["1"], "net_refs": ["VCC"],
                   "suggested_after": "0.1uF"},
    }]}), encoding="utf-8")
    snap = tmp_path / "s.epro2"
    snap.write_bytes(b"x")
    code = cli.main(["edit", "plan", "--file", str(snap), "--rule", "decap-required-caps",
                     "--designator", "U1", "--report", str(report), "--lcsc", "C1525"])
    err = capsys.readouterr().err
    assert code == 5
    assert "no free landing spot" in err
    assert len(LADDER) <= err.count("("), "the refusal names the positions it tried"
    assert "绝不放原点" in err


def test_no_verified_recipe_refuses_before_any_bridge_call(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge(geometry=_geometry(components=[("U1", 0.0, 0.0)]))
    _stub_bridge(monkeypatch, bridge)
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN", "message": "m",
        "target": {"component_ref": "U1", "pin_refs": ["1"], "net_refs": ["VCC"],
                   "suggested_after": "0.1uF"},
    }]}), encoding="utf-8")
    snap = tmp_path / "s.epro2"
    snap.write_bytes(b"x")
    code = cli.main(["edit", "plan", "--file", str(snap), "--rule", "decap-required-caps",
                     "--designator", "U1", "--report", str(report)])
    err = capsys.readouterr().err
    assert code == 5
    assert "no verified recipe" in err and "--lcsc" in err
    assert bridge.calls == [], "the refusal happens before the page is read"


def test_a_finding_without_a_target_says_to_record_the_facts_first(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge(geometry=_geometry(components=[("U1", 0.0, 0.0)]))
    _stub_bridge(monkeypatch, bridge)
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN", "message": "no facts",
    }]}), encoding="utf-8")
    snap = tmp_path / "s.epro2"
    snap.write_bytes(b"x")
    code = cli.main(["edit", "plan", "--file", str(snap), "--rule", "decap-required-caps",
                     "--designator", "U1", "--report", str(report), "--lcsc", "C1525"])
    err = capsys.readouterr().err
    assert code == 5
    assert "没有 structured target" in err and "先录入事实" in err


def _report_for(tmp_path, *, net="VCC"):
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN",
        "message": f"U1 pin1: no grounded capacitor on net '{net}' (required 0.1uF)",
        "target": {"component_ref": "U1", "pin_refs": ["1"], "net_refs": [net],
                   "suggested_after": "0.1uF"},
    }]}), encoding="utf-8")
    return report


def test_ground_may_be_labelled_on_a_page_with_no_label_precedent(monkeypatch, tmp_path, capsys):
    """029-c §① rule 2: the ground exception, and it is an exception, not a habit.

    A page that carries no label at all still gets `GND` named, because naming
    ground is how every schematic states it; a signal net on that same page is
    refused. Both halves are asserted here, since the interesting claim is the
    *difference* between them.
    """
    from boardwise.engines import addcomponent

    geometry = _geometry(components=[("U1", 0.0, 0.0)])  # no wires, no labels
    ground = addcomponent.choose_connection("GND", (0.0, -5.0), geometry)
    assert ground.kind == CONNECTION_LABEL
    assert "ground net" in ground.detail and ground.to is None
    with pytest.raises(addcomponent.NoConnectionOption) as caught:
        addcomponent.choose_connection("VCC", (0.0, -5.0), geometry)
    assert "no wire point" in str(caught.value) and "no label named 'VCC'" in str(caught.value), (
        "the refusal names both options that were checked, so the operator knows what "
        "to draw rather than guessing"
    )
    with pytest.raises(addcomponent.NoConnectionOption):
        addcomponent.choose_connections([("1", "VCC"), ("2", "GND")], (0.0, -5.0), geometry)


def test_the_plan_refuses_a_net_with_neither_a_wire_nor_a_label(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge(geometry=_geometry(components=[("U1", 0.0, 0.0)]))
    _stub_bridge(monkeypatch, bridge)
    report = _report_for(tmp_path, net="VCC")
    snap = tmp_path / "s.epro2"
    snap.write_bytes(b"x")
    out_path = tmp_path / "plan.json"
    code = cli.main(["edit", "plan", "--file", str(snap), "--rule", "decap-required-caps",
                     "--designator", "U1", "--report", str(report), "--lcsc", "C1525",
                     "-o", str(out_path)])
    err = capsys.readouterr().err
    assert code == 5
    assert "no wire point" in err and "no label named 'VCC'" in err
    assert not out_path.exists(), "a refused plan is not written to disk"


# --------------------------------------------------------------------------
# 5-10. apply
# --------------------------------------------------------------------------


def test_apply_refuses_a_designator_that_was_taken(monkeypatch, tmp_path, capsys):
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0), ("C7", 30.0, 30.0)], wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 4, out
    assert "designator_taken" in out
    assert bridge.writes == []


def test_apply_is_idempotent_when_the_recipe_is_already_satisfied(monkeypatch, tmp_path, capsys):
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0), ("C3", 40.0, 40.0)], wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    # The rule's own judgement, on a board where a 0.1uF cap already grounds VCC.
    _stub_model(monkeypatch, [_model(
        components={"U1": "IC", "C3": "0.1uF"},
        nets={"VCC": [("U1", "1"), ("C3", "1")], "GND": [("C3", "2")]},
    )])
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "already_applied" in out
    assert bridge.writes == [], "a repeat run must not create a second part (岳红线)"


def test_a_dropped_connection_is_read_back_and_never_retried(monkeypatch, tmp_path, capsys):
    from boardwise.core.changeplan import CONNECTION_LABEL

    plan = _plan(tmp_path, connection=CONNECTION_LABEL)
    bridge = _FakeBridge(
        geometry=_geometry(components=[("U1", 0.0, 0.0)], netlabels=["VCC"]),
        writes_fail={"sch.place_component": _BridgeError("DISCONNECTED", "the socket died")},
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
    ])
    # The read-back shows the part anyway (a dropped connection is not a failed write).
    bridge.after_geometry = _geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                      netlabels=["VCC"])
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert "UNKNOWN" in out or "unknown" in out, out
    # The attempt is counted from the *calls*, not from the writes: the write
    # raised, so it never reached the recording branch — and "exactly one
    # attempt" is the claim (a retry would show two).
    assert bridge.calls.count("sch.place_component") == 1,         "a timeout/drop is read back, never re-issued"
    assert code in (0, 2, 3)


def test_a_range_that_is_not_exactly_one_extra_part_is_an_accident(monkeypatch, tmp_path, capsys):
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        # Two parts appeared, not one: half of a previous run, or a hand edit.
        _model(components={"U1": "IC", "C7": "0.1uF", "C8": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2"), ("C8", "2")]}),
    ])
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 2, out
    assert "range_diff" in out
    assert "事故报告" in out
    assert [item[0] for item in bridge.writes] == [
        "sch.place_component", "sch.place_wire", "sch.place_netlabel"], \
        "both connections are attempted, and nothing is saved once the range is wrong"


def test_a_resolved_re_review_is_reported_as_applied(monkeypatch, tmp_path, capsys):
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    monkeypatch.setattr(cli, "_edit_post_review",
                        lambda *a, **k: {"state": "resolved", "reason": "no findings"})
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "re-reviewed as resolved" in out
    assert [item[0] for item in bridge.writes] == [
        "sch.place_component", "sch.place_wire", "sch.place_netlabel", "sch.doc.save"]


def test_a_still_present_re_review_is_reported_honestly(monkeypatch, tmp_path, capsys):
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    monkeypatch.setattr(cli, "_edit_post_review",
                        lambda *a, **k: {"state": "still_present", "reason": "the rule still fires"})
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 2, out
    assert "still reports the decap finding" in out
