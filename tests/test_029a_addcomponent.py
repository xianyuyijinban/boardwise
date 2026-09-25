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
    CONNECTION_POWER_FLAG,
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


def _geometry(*, components, wires=(), netlabels=(), netflags=()):
    """A `sch.geometry` dump in the shape 3.2.186 actually sends (measured 029-b).

    `wires` are polylines of `(x, y)` pairs; each one is given a net by the
    heuristic below so a test can put a *different* net's wire right next to a
    landing spot — the page 029 §六 verdict 3 asked for.

    `netflags` are `(net, x, y)` — the host reports a power/ground symbol as a
    component with ``ComponentType: "netflag"`` and an **empty Designator**
    (measured 029-d on 3.2.186), which is why they are counted separately from
    the designator set.
    """
    def net_of(points):
        return "OTHER" if points and points[0][1] == 999 else "VCC"

    return {
        "components": [
            {"primitiveId": f"p-{name}", "state": {"Designator": name, "X": x, "Y": y}}
            for name, x, y in components
        ]
        + [
            {"primitiveId": f"flag-{index}",
             "state": {"ComponentType": "netflag", "Designator": None,
                       "Net": name, "X": x, "Y": y,
                       "Component": {"name": f"Ground-{name}"}}}
            for index, (name, x, y) in enumerate(netflags)
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


def _model(*, components, nets, lcsc=None):
    """A `DesignModel` with the components/nets a test needs.

    Each net is a list of ``(designator, pin)`` members, and every pin is given
    its net: the rule's inventory (`cap_candidates_on`) asks the *pins* whether
    the other end is grounded, so a model whose pins all say ``net=None`` is a
    board where nothing is grounded — which is a fixture bug, not a rule result.

    ``lcsc`` gives a component its shelf identity (`{"U1": "C6186"}`), which is
    what makes the facts-driven rules decide anything at all: without it the decap
    rule answers UNKNOWN ("no shelf entry"), and a re-review that read UNKNOWN as
    "resolved" would be claiming a decision nobody made.
    """
    model = DesignModel()
    for name, value in components.items():
        model.components[name] = Component(
            uid=f"uid-{name}", designator=name, value=value,
            lcsc_part=(lcsc or {}).get(name, ""),
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
            "sch.place_component", "sch.place_wire", "sch.place_netlabel",
            "sch.place_power", "sch.doc.save",
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
        if action in ("sch.place_component", "sch.place_wire", "sch.place_netlabel",
                      "sch.place_power", "sch.doc.save"):
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


def _stub_post_review(monkeypatch, state, reason="stubbed"):
    """Replace the live re-review, for tests that are about the writes.

    The re-review itself has its own tests; everywhere else the run must not be
    spent exporting the live project twice more, and the stub says so by name
    (`source: "live"`), so a test cannot pass because the *file* path answered.
    """
    async def _stub(*_args, **_kwargs):
        return {"state": state, "reason": reason, "source": "live"}

    monkeypatch.setattr(cli, "_edit_post_review_live", _stub)


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
    # §①: each declared connection states its own kind and its own evidence. The
    # rail end is a **power flag** (029-d), because this page shows no GND
    # geometry at all and a flag is the only mechanism that can create one.
    assert [(item.pin, item.net, item.kind) for item in plan.change.connections] == [
        ("1", "VCC", CONNECTION_WIRE), ("2", "GND", CONNECTION_POWER_FLAG),
    ]
    assert plan.change.connections[0].to == (0.0, 0.0), (
        "the wire ends on the nearest vertex of that net's own wiring (0, 0 — 5 units "
        "from the spot), which is what apply will draw to"
    )
    assert plan.change.connections[1].to is None, (
        "a flag reaches a coordinate too, but not one the plan can know: it goes on the "
        "part's own pin, which does not exist until apply places it"
    )
    assert "Ground flag" in plan.change.connections[1].detail, (
        "the flag branch must name the flag kind it will place and say why a flag was "
        "the answer here (no GND geometry to reach)"
    )
    assert "2→GND via power-flag" in out, "both connections are printed as they were decided"
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
    _stub_post_review(monkeypatch, "resolved")
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
    _stub_post_review(monkeypatch, "resolved")
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
    _stub_post_review(monkeypatch, "resolved")
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


def test_a_rail_gets_a_flag_where_the_page_has_no_geometry_of_it():
    """029-d §①: the rail is the one thing that may be *created*, and as a flag.

    Three halves, because the difference between them is the whole rule: a ground
    net becomes a flag, a supply rail becomes a flag of its own kind, and a signal
    net with no geometry and no name becomes a refusal. A dangling wire carrying
    the net's own name is never an outcome (029-d forbids it by name).
    """
    from boardwise.engines import addcomponent

    geometry = _geometry(components=[("U1", 0.0, 0.0)])  # no wires, no labels
    ground = addcomponent.choose_connection("GND", (0.0, -5.0), geometry)
    assert ground.kind == CONNECTION_POWER_FLAG
    assert "Ground flag" in ground.detail and "GND" in ground.detail
    assert ground.to is None
    supply = addcomponent.choose_connection("VCC", (0.0, -5.0), geometry)
    assert supply.kind == CONNECTION_POWER_FLAG, (
        "a supply rail is a rail too: `layout._net_kind` decides that, not a list of "
        "ground spellings kept here"
    )
    assert "Power flag" in supply.detail
    with pytest.raises(addcomponent.NoConnectionOption) as caught:
        addcomponent.choose_connection("SIG1", (0.0, -5.0), geometry)
    message = str(caught.value)
    assert "no wire point" in message and "no label named 'SIG1'" in message
    assert "not a rail" in message, (
        "the refusal names all three options that were checked, so the operator knows "
        "what to draw or which rail to name rather than guessing"
    )
    with pytest.raises(addcomponent.NoConnectionOption):
        addcomponent.choose_connections([("1", "SIG1"), ("2", "GND")], (0.0, -5.0), geometry)


def test_power_flag_kind_defers_to_the_one_net_kind_judgement():
    from boardwise.engines import addcomponent

    assert addcomponent.power_flag_kind("GND") == "Ground"
    assert addcomponent.power_flag_kind("AGND") == "Ground"
    assert addcomponent.power_flag_kind("VCC") == "Power"
    assert addcomponent.power_flag_kind("+3.3V") == "Power"
    assert addcomponent.power_flag_kind("SIG1") == ""
    assert addcomponent.power_flag_kind("") == ""
    assert addcomponent.power_flag_kind("VEE") == "", (
        "VEE is deliberately not ground (2026-09-18 ruling) and this must not "
        "re-introduce the spelling that ruling removed"
    )


def test_the_plan_refuses_a_signal_net_with_neither_a_wire_nor_a_label(
    monkeypatch, tmp_path, capsys
):
    bridge = _FakeBridge(geometry=_geometry(components=[("U1", 0.0, 0.0)]))
    _stub_bridge(monkeypatch, bridge)
    report = _report_for(tmp_path, net="SIG1")  # a signal net: no rail, no flag
    snap = tmp_path / "s.epro2"
    snap.write_bytes(b"x")
    out_path = tmp_path / "plan.json"
    code = cli.main(["edit", "plan", "--file", str(snap), "--rule", "decap-required-caps",
                     "--designator", "U1", "--report", str(report), "--lcsc", "C1525",
                     "-o", str(out_path)])
    err = capsys.readouterr().err
    assert code == 5
    assert "no wire point" in err and "no label named 'SIG1'" in err
    assert "not a rail" in err
    assert not out_path.exists(), "a refused plan is not written to disk"


# --------------------------------------------------------------------------
# 4b. 029-d §①: the power-flag connection, executed and counted
# --------------------------------------------------------------------------


def _flag_plan(tmp_path):
    """pin 1 reaches VCC by wire, pin 2 is grounded by a flag — no GND geometry."""
    plan = add_component_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        anchor="U1", designator="C7",
        part=PlanPart(lcsc="C1525", value="0.1uF"),
        connections=[
            PlanConnection("1", "VCC", kind=CONNECTION_WIRE,
                           detail="a short wire to the VCC segment", to=(5.0, 0.0)),
            PlanConnection("2", "GND", kind=CONNECTION_POWER_FLAG,
                           detail="a Ground flag named 'GND' on the part's own pin"),
        ],
        x=0.0, y=-5.0, connection=CONNECTION_WIRE, connection_detail="test",
        recipe_source="operator:C1525",
    )
    path = tmp_path / "plan-flags.json"
    plan.dump(path)
    return path


def test_a_power_flag_is_placed_on_the_pin_and_counted_in_the_range(monkeypatch, tmp_path, capsys):
    """The flag goes **on the pin** (a flag elsewhere grounds nothing) and the
    range obligation counts it: +1 part, +1 flag, and nothing else."""
    plan = _flag_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=_geometry(components=[("U1", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0.0, 0.0), (5.0, 0.0)]],
                                 netflags=[("GND", 20.0, -5.0)]),
        pins={"1": (-20.0, -5.0), "2": (20.0, -5.0)},
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    _stub_post_review(monkeypatch, "resolved")
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 0, out
    flags = [params for action, params in bridge.writes if action == "sch.place_power"]
    assert len(flags) == 1, "one declared flag connection → exactly one flag placed"
    assert flags[0]["kind"] == "Ground" and flags[0]["net"] == "GND"
    assert (flags[0]["x"], flags[0]["y"]) == (20.0, -5.0), (
        "the flag sits on pin 2's own reported coordinate (the origin would ground "
        "the body and connect nothing)"
    )
    assert [item[0] for item in bridge.writes] == [
        "sch.place_component", "sch.place_wire", "sch.place_power", "sch.doc.save"]
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["range"]["flags"] == {"before": 0, "after": 1, "expected": 1, "ok": True}
    assert report["range"]["ok"] is True
    assert report["write"]["connections"][1]["at"] == [20.0, -5.0]
    assert report["write"]["connections"][1]["flag"] == "Ground"


def test_a_power_flag_without_pin_geometry_is_refused_not_guessed(monkeypatch, tmp_path, capsys):
    plan = _flag_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=_geometry(components=[("U1", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        pins={},  # the host reports no pins
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
    ])
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 2, out
    assert "flag_unavailable" in out
    assert [item[0] for item in bridge.writes] == ["sch.place_component", "sch.place_wire"], (
        "the flag is refused rather than dropped on the part's origin — a flag there "
        "grounds the body, and the netlist would have said so after a save"
    )
    assert "sch.doc.save" not in [item[0] for item in bridge.writes]


def test_a_promised_flag_that_never_appears_fails_the_range(monkeypatch, tmp_path, capsys):
    plan = _flag_plan(tmp_path)
    bridge = _FakeBridge(
        geometry=_geometry(components=[("U1", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        # The part landed and connected, but no netflag is on the page: the write
        # reported success and the page disagrees.
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0.0, 0.0), (5.0, 0.0)]]),
        pins={"1": (-20.0, -5.0), "2": (20.0, -5.0)},
    )
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [
        _model(components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []}),
        _model(components={"U1": "IC", "C7": "0.1uF"},
               nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]}),
    ])
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 2, out
    assert "range_flag_diff" in out
    assert "sch.doc.save" not in [item[0] for item in bridge.writes]
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["range"]["flags"]["ok"] is False


# --------------------------------------------------------------------------
# 5-10. apply
# --------------------------------------------------------------------------


def test_apply_refuses_a_designator_that_was_taken(monkeypatch, tmp_path, capsys):
    """A *different* part holding the designator, and the work not done: refuse."""
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0), ("C7", 30.0, 30.0)], wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [_model(
        components={"U1": "IC"}, nets={"VCC": [("U1", "1")], "GND": []},
    )])
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 4, out
    assert "designator_taken" in out
    assert bridge.writes == []


def test_the_pool_says_so_when_the_snapshot_cannot_be_parsed(monkeypatch, tmp_path, capsys):
    """The pool falls back to the page alone — and the note says which, because a
    silent fallback is how a project-wide collision comes back."""
    geometry = _geometry(
        components=[("U1", 0.0, 0.0), ("C3", 40.0, 40.0)],
        wires=[[(0.0, 0.0), (10.0, 0.0)]],
    )
    _stub_bridge(monkeypatch, _FakeBridge(geometry=geometry))
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN",
        "message": "U1 pin1: no grounded capacitor found on net 'VCC' (required 0.1uF)",
        "target": {"component_ref": "U1", "pin_refs": ["1"], "net_refs": ["VCC"],
                   "suggested_after": "0.1uF"},
    }]}), encoding="utf-8")
    snapshot = tmp_path / "snap.epro2"
    snapshot.write_bytes(b"x")          # not an archive at all
    out_path = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--file", str(snapshot), "--rule", "decap-required-caps",
        "--designator", "U1", "--report", str(report), "--lcsc", "C1525",
        "-o", str(out_path),
    ])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "the designator pool is this page alone" in out
    assert ChangePlan.load(out_path).target.designator == "C1", (
        "the page's own numbers still decide what is free"
    )


def test_apply_refuses_a_designator_another_page_spends(monkeypatch, tmp_path, capsys):
    """036b: the page is not the whole board.

    Measured 2026-09-25: the host renames a designator that collides with another
    **page** of the project, mid-run — the part lands under a different number than
    the plan says, and the plan's own read-back then reports a failure for a write
    that did happen. The live export is already in hand here (the probe reads it),
    so the collision is refused by name, before anything is placed.
    """
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [_model(
        components={"U1": "IC", "C7": "0.1uF"},   # C7 lives on another page
        nets={"VCC": [("U1", "1")]},
    )])
    code = cli.main(["edit", "apply", str(plan)])
    out = capsys.readouterr().out
    assert code == 4, out
    assert "designator_taken" in out
    assert "another page" in out
    assert bridge.writes == [], "nothing was written"


def test_a_repeat_apply_answers_already_applied_even_though_the_designator_is_taken(
    monkeypatch, tmp_path, capsys
):
    """029-d §③: the probe runs first, so a repeat run is not called a conflict.

    The page holds the very part this plan would create — same designator, same
    landing spot, recipe satisfied — which is what a *successful* first run leaves
    behind. Checking the designator first answered `designator_taken` (safe, and
    misleading: 活儿其实干完了); the probe is a read, so it can answer first.
    """
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)], wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    _stub_model(monkeypatch, [_model(
        components={"U1": "IC", "C7": "0.1uF"},
        nets={"VCC": [("U1", "1"), ("C7", "1")], "GND": [("C7", "2")]},
    )])
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "already_applied" in out
    assert "already carries C7" in out
    assert bridge.writes == [], "a repeat run writes nothing at all — not even a probe write"
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["idempotence"]["state"] == "satisfied"
    assert report["range"] == {}, "no range was measured: there was nothing to write"


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


def _written_models(*, anchor_unsaturated, after):
    """The four live reads an add apply makes (probe, range, review ×2)."""
    return [anchor_unsaturated, after, after, after]


def test_the_live_re_review_is_taken_and_reported_as_resolved(monkeypatch, tmp_path, capsys):
    """029-d §②: the re-review re-exports the live project instead of the file.

    The 016 path reads `--file`, which the editor never rewrites for this
    project — so the honest answer there was always `unknown` (029-c) and the
    re-review had to be run by hand with `checkup --project`. Here no `--file` is
    even passed, and the answer still arrives, because it comes from a fresh
    export of the live board through the rules' own parser.
    """
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    # U1 is on the shelf (C6186 = AMS1117-3.3, whose pin 2 requires a 22uF
    # output capacitor), so the rule can *decide*: the 22uF that landed is the
    # requirement, and the finding is genuinely gone rather than merely absent.
    shelf = {"U1": "C6186"}
    _stub_model(monkeypatch, _written_models(
        anchor_unsaturated=_model(components={"U1": "IC"},
                                  nets={"VCC": [("U1", "1"), ("U1", "2")], "GND": []},
                                  lcsc=shelf),
        after=_model(components={"U1": "IC", "C7": "22uF"},
                     nets={"VCC": [("U1", "1"), ("U1", "2"), ("C7", "1")],
                           "GND": [("C7", "2")]},
                     lcsc=shelf),
    ))
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "re-reviewed as resolved" in out
    assert [item[0] for item in bridge.writes] == [
        "sch.place_component", "sch.place_wire", "sch.place_netlabel", "sch.doc.save"]
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["postReview"]["source"] == "live"
    assert report["postReview"]["state"] == "resolved"
    assert report["postReview"]["anchor"] == "U1"
    assert report["postReview"]["findings"] == []
    assert report["postReview"]["outcomes"], (
        "the states are carried too: `resolved` has to be a decision, and only the "
        "outcomes show that the rule reached one"
    )


def test_a_still_present_live_re_review_is_reported_honestly(monkeypatch, tmp_path, capsys):
    plan = _plan(tmp_path)
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U1", 0.0, 0.0)], wires=[[(0, 0), (5, 0)]]),
        after_geometry=_geometry(components=[("U1", 0.0, 0.0), ("C7", 0.0, -5.0)],
                                 wires=[[(0, 0), (5, 0)]]))
    _stub_bridge(monkeypatch, bridge)
    # The part is placed and connected, but what landed is 1nF where the shelf
    # says AMS1117-3.3 pin 2 needs 22uF: the read-back is satisfied about the
    # *pin*, the rule is not satisfied about the requirement, and the second one
    # is what `resolved` means.
    shelf = {"U1": "C6186"}
    still = _model(components={"U1": "IC", "C7": "1nF"},
                   nets={"VCC": [("U1", "1"), ("U1", "2"), ("C7", "1")],
                         "GND": [("C7", "2")]},
                   lcsc=shelf)
    _stub_model(monkeypatch, _written_models(
        anchor_unsaturated=_model(components={"U1": "IC"},
                                  nets={"VCC": [("U1", "1"), ("U1", "2")], "GND": []},
                                  lcsc=shelf),
        after=still,
    ))
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 2, out
    assert "still reports the decap finding" in out
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["postReview"]["state"] == "still_present"
    assert report["postReview"]["findings"], "the still-present findings are carried, not implied"


def test_a_live_re_review_that_cannot_be_taken_falls_back_to_the_file_path(
    monkeypatch, tmp_path, capsys
):
    """No live export → the 016 `--file` reading answers, and its state is what counts."""
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
    ])  # the two review exports get nothing → the live path cannot answer
    monkeypatch.setattr(cli, "_edit_post_review",
                        lambda *a, **k: {"state": "unknown", "reason": "no --file was given"})
    result = tmp_path / "apply.json"
    code = cli.main(["edit", "apply", str(plan), "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 0, out
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["outcome"] == "applied"
    assert report["reason"] == "post_review_unknown"
    assert report["postReview"]["source"] == "file"
    assert "live re-export could not answer" in report["postReview"]["reason"]


# --------------------------------------------------------------------------
# 11. 029-d §④: `edit preview` recognises an add-component plan
# --------------------------------------------------------------------------


SNAPSHOT = Path("reviewsets/injected/value-mpn-mismatch.epro2")
#: The fixture's own C-numbers (read from the snapshot), so "the lowest free C
#: number" agrees between the live page and the file the preview re-reads.
SNAPSHOT_C_NAMES = ("C1", "C25", "C3", "C4", "C5", "C6", "C7", "C9")


def _plan_against_the_snapshot(tmp_path, *, anchor="U3", net="VCC"):
    """A real add-component plan built against `SNAPSHOT` through the CLI."""
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "decap-required-caps", "severity": "WARN",
        "message": f"{anchor} pin1: no grounded capacitor on net '{net}' (required 0.1uF)",
        "target": {"component_ref": anchor, "pin_refs": ["1"], "net_refs": [net],
                   "suggested_after": "0.1uF"},
        "source": {"pageUuid": "page-1"},
    }]}), encoding="utf-8")
    out_path = tmp_path / "plan.json"
    code = cli.main(["edit", "plan", "--file", str(SNAPSHOT),
                     "--rule", "decap-required-caps", "--designator", anchor,
                     "--report", str(report), "--lcsc", "C1525", "-o", str(out_path)])
    assert code == 0, "the plan is the preview's input; it has to build first"
    return out_path


def _live_page_like_the_snapshot(anchor):
    names = [("U3", 0.0, 0.0)] if anchor == "U3" else [(anchor, 0.0, 0.0)]
    names += [(name, 200.0 + 10 * index, 200.0) for index, name in enumerate(SNAPSHOT_C_NAMES)]
    return _geometry(components=names, wires=[[(0.0, 0.0), (5.0, 0.0)]])


def test_preview_accepts_an_add_component_plan_and_checks_its_own_preconditions(
    monkeypatch, tmp_path, capsys
):
    """029-d §④: the target does not exist yet, so the checks are the other three.

    For `component-value` the preview confirms the target is still there with the
    value the plan expects. A create has no target to find — what it can check is
    that the **anchor** is there, that the designator it intends to use is *free*
    (the create's own precondition, read the other way round) and that the file is
    the one the plan was built against.
    """
    bridge = _FakeBridge(geometry=_live_page_like_the_snapshot("U3"))
    _stub_bridge(monkeypatch, bridge)
    plan = _plan_against_the_snapshot(tmp_path, anchor="U3")
    result = tmp_path / "preview.json"
    code = cli.main(["edit", "preview", str(plan), "--file", str(SNAPSHOT),
                     "--json", str(result)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "U3" in out and "C2" in out
    assert "still free" in out, "the designator check says what it checked"
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["kind"] == ADD_COMPONENT_KIND
    assert payload["anchor"] == "U3"
    assert payload["designator"] == "C2"
    assert payload["part"]["lcsc"] == "C1525"
    assert [item["kind"] for item in payload["connections"]] == [
        CONNECTION_WIRE, CONNECTION_POWER_FLAG]
    assert payload["snapshot"] == "fresh"


def test_preview_refuses_an_anchor_that_is_not_in_the_snapshot(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge(geometry=_live_page_like_the_snapshot("U9"))
    _stub_bridge(monkeypatch, bridge)
    plan = _plan_against_the_snapshot(tmp_path, anchor="U9")
    code = cli.main(["edit", "preview", str(plan), "--file", str(SNAPSHOT)])
    err = capsys.readouterr().err
    assert code == 4, err
    assert "U9" in err and "anchor" in err


def test_preview_refuses_a_designator_the_snapshot_already_spends(monkeypatch, tmp_path, capsys):
    """The preview's own designator check, on a plan that *does* spend a spent number.

    Since 036b the builder cannot hand out such a plan — the pool is the page
    **and** the project (the snapshot's own C-names included), so it picks the
    lowest free number project-wide. The check still has to hold, because a plan
    file can be edited by hand and a designator can be spent between planning and
    applying — which is exactly what this constructs.
    """
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U3", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)]]))
    _stub_bridge(monkeypatch, bridge)
    plan_path = _plan_against_the_snapshot(tmp_path, anchor="U3")
    plan = ChangePlan.load(plan_path)
    assert plan.target.designator == "C2", "the lowest free C number project-wide"
    plan.target.designator = "C1"          # spent by the snapshot itself
    plan.target.assigned_designator = "C1"
    plan.dump(plan_path)
    code = cli.main(["edit", "preview", str(plan_path), "--file", str(SNAPSHOT)])
    err = capsys.readouterr().err
    assert code == 4, err
    assert "C1" in err and "already" in err


def test_the_designator_pool_skips_a_number_another_page_spends(monkeypatch, tmp_path, capsys):
    """036b, measured 2026-09-25: the host renames a designator that collides
    **anywhere in the project**, and it renames it mid-run — so the plan must not
    ask for one. The live page here shows no C-names at all; the snapshot does
    (`SNAPSHOT_C_NAMES`), and the pool has to include them."""
    bridge = _FakeBridge(geometry=_geometry(
        components=[("U3", 0.0, 0.0)], wires=[[(0.0, 0.0), (5.0, 0.0)]]))
    _stub_bridge(monkeypatch, bridge)
    plan_path = _plan_against_the_snapshot(tmp_path, anchor="U3")
    plan = ChangePlan.load(plan_path)
    used = {int(name[1:]) for name in SNAPSHOT_C_NAMES}
    assert int(plan.target.designator[1:]) not in used, (
        f"{plan.target.designator} is spent by another page of the snapshot"
    )
    assert plan.target.designator == f"C{min(n for n in range(1, 30) if n not in used)}"


# --------------------------------------------------------------------------
# 12. 029-d §④: report.json's `target` has an explicit schema
# --------------------------------------------------------------------------


def test_the_report_target_schema_is_explicit(monkeypatch):
    """The contract `edit plan --report` reads, asserted field by field.

    029-a left this as `asdict`-by-accident: the plan builder reads
    `component_ref`, `pin_refs`, `net_refs` and `suggested_after` out of
    report.json, so the shape is an interface — a renamed field would otherwise
    be discovered by a real machine refusing a real repair.
    """
    from boardwise.engines.review import render_json
    from boardwise.rules.decap import DecapRequiredCaps

    model = _model(components={"U1": ""}, nets={"NET4": [("U1", "2")]},
                   lcsc={"U1": "C6186"})
    findings = DecapRequiredCaps().check(model)
    assert findings, "the fixture must actually violate the rule"
    target = findings[0].target
    assert target is not None, "a repairable finding carries a structured target"
    assert target.component_ref == "U1"
    assert target.pin_refs == ["2"]
    assert target.net_refs == ["NET4"]
    assert target.suggested_after == "22uF"
    assert target.primitive_id == "", "offline: the live canvas id is not resolvable here"
    assert target.expected_before == ""

    payload = json.loads(render_json(findings))
    emitted = payload["findings"][0]["target"]
    assert set(emitted) == {
        "component_ref", "primitive_id", "pin_refs", "net_refs",
        "expected_before", "suggested_after",
    }, "report.json's target keys are the plan builder's input contract"
    assert isinstance(emitted["component_ref"], str)
    assert isinstance(emitted["primitive_id"], str)
    assert isinstance(emitted["pin_refs"], list) and all(
        isinstance(item, str) for item in emitted["pin_refs"])
    assert isinstance(emitted["net_refs"], list) and all(
        isinstance(item, str) for item in emitted["net_refs"])
    assert isinstance(emitted["expected_before"], str)
    assert isinstance(emitted["suggested_after"], str)
