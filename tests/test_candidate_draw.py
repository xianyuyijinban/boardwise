"""Tests for candidate-model builders and the draw orchestration (006).

The geometry fallback is the path that must work *today* (the netlist
format is calibrated from a live sample later), so its tests are exact:
synthetic geometry dumps with known connectivity, and the per-pin verdict
the diff must produce. ``run_draw`` is driven against a fake bridge client
that records every action, so the orchestration — gate, order, fallback
ladder — is tested without an editor.
"""

from __future__ import annotations

import argparse
import json

import pytest

from boardwise.bridge.protocol import BridgeError, ErrorCodes
from boardwise.core.candidate import (
    GeometryError,
    NetlistFormatError,
    candidate_from_geometry,
    candidate_from_netlist,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.draw import (
    PERSISTENCE_NOT_PLACED,
    PERSISTENCE_PLACED,
    PERSISTENCE_SAVED_UNVERIFIED,
    PERSISTENCE_SAVED_VERIFIED,
    PERSISTENCE_UNKNOWN,
    PERSISTENCE_WORDS,
    TIMEOUT_CODE,
    DrawAborted,
    run_draw,
)
from boardwise.engines.generate import generate_plan, strip_dangling_nets


# --------------------------------------------------------------------------
# candidate_from_geometry
# --------------------------------------------------------------------------


def _geo(**overrides) -> dict:
    """A synthetic sch.geometry dump of one placed part (page mode)."""
    base = {
        "components": [
            {
                "primitiveId": "c1",
                "state": {"ComponentType": "part", "Symbol": "sym-r",
                           "X": 0, "Y": 0},
            },
        ],
        "pins": [],
        "wires": [
            {
                "primitiveId": "w1",
                "state": {"Net": "RX", "Line": [-100, 0, 100, 0]},
            },
        ],
        "netlabels": [],
        "meta": {"available": {"components": True, "wires": True, "pins": True}},
    }
    base.update(overrides)
    return base


# symbol offsets for the placed part, in file coordinates (y down): the
# part's two pins stick out to x = -100 and +100 at y = 0.
SYMBOL_DEFS = {"sym-r": {"1": (-100.0, 0.0), "2": (100.0, 0.0)}}
PART_POSITIONS = {(0.0, 0.0): "U1"}


def test_geometry_connects_pins_through_a_wire():
    model = candidate_from_geometry(_geo(), symbol_defs=SYMBOL_DEFS, part_positions=PART_POSITIONS)
    assert set(model.components) == {"U1"}
    pins = {p.number: p.net for p in model.components["U1"].pins}
    assert pins == {"1": "RX", "2": "RX"}, "both pin tips sit on the wire's endpoints"


def test_geometry_without_wire_names_clusters_deterministically():
    geo = _geo()
    geo["wires"][0]["state"]["Net"] = ""  # the wire exists but is unnamed
    model = candidate_from_geometry(geo, symbol_defs=SYMBOL_DEFS, part_positions=PART_POSITIONS)
    assert model.nets["NET1"].pins == [("U1", "1"), ("U1", "2")]


def test_geometry_accepts_pair_style_polylines_and_camel_case():
    geo = _geo()
    geo["wires"][0]["state"] = {"net": "RX", "line": [[-100, 0], [100, 0]]}
    model = candidate_from_geometry(geo, symbol_defs=SYMBOL_DEFS, part_positions=PART_POSITIONS)
    assert model.nets["RX"].pins == [("U1", "1"), ("U1", "2")]


def test_geometry_unplaced_parts_are_reported_not_fabricated():
    model = candidate_from_geometry(_geo(), symbol_defs=SYMBOL_DEFS, part_positions=PART_POSITIONS)
    assert "R1" not in model.components, (
        "only parts the dump actually shows become candidate components"
    )


def test_geometry_with_no_parts_raises():
    with pytest.raises(GeometryError):
        candidate_from_geometry(
            {"components": [], "pins": [], "wires": []},
            symbol_defs=SYMBOL_DEFS, part_positions=PART_POSITIONS,
        )


def test_netlist_parser_still_refuses_unknown_formats():
    with pytest.raises(NetlistFormatError):
        candidate_from_netlist("*NET\n*CON\nGND U1-1", netlist_type="Protel2")
    with pytest.raises(NetlistFormatError):
        candidate_from_netlist("not json at all")


# --------------------------------------------------------------------------
# run_draw against a fake client
# --------------------------------------------------------------------------


class FakeClient:
    """A BridgeClient stand-in that answers every action from fixtures."""

    def __init__(self, geometry: dict, netlist: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.geometry = geometry
        self.netlist = netlist or {
            "type": "EasyEDA",
            "source": "getNetlistFile",
            "size": 3,
            "text": "…",
        }

    async def call(self, action: str, params=None) -> dict:
        self.calls.append((action, params or {}))
        if action == "sch.netlist":
            return self.netlist
        if action == "sch.geometry":
            return self.geometry
        if action == "export.screenshot":
            return {"data": "c2hvdA=="}
        if action == "sch.doc.new":
            return {"schematicUuid": "s", "pageUuid": "p"}
        return {"uuid": f"u{len(self.calls)}"}


def _golden_model() -> DesignModel:
    model = DesignModel()
    # Mirrors the real golden board: U1's schematic attrs carry no
    # value/footprint/lcsc (the editor fills those from the library), and
    # pin 9 exists but is unconnected (schematic NO_CONNECT).
    model.components["U1"] = Component(
        uid="d1", designator="U1",
        pins=[Pin(number="1", name=""), Pin(number="2", name=""),
              Pin(number="9", name="")],
    )
    model.components["R1"] = Component(
        uid="d2", designator="R1", value="10k",
        pins=[Pin(number="1", name=""), Pin(number="2", name="")],
    )
    model.nets["GND"] = Net(name="GND", pins=[("U1", "1"), ("R1", "1")])
    model.nets["RX"] = Net(name="RX", pins=[("U1", "2"), ("R1", "2")])
    # like the real parsers: the net name lives on the pin too
    for net in model.nets.values():
        for des, number in net.pins:
            for pin in model.components[des].pins:
                if pin.number == number:
                    pin.net = net.name
    return model


#: FILE-space symbol offsets for the synthetic board (the draw flow
#: converts them to canvas space itself — that conversion is pinned by
#: the calibration tests).
GOLDEN_OFFSETS = {
    "U1": {"1": (-20.0, -10.0), "2": (-20.0, 10.0), "9": (0.0, -30.0)},
    "R1": {"1": (-20.0, 0.0), "2": (20.0, 0.0)},
}


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_run_draw_happy_path_executes_the_whole_plan():
    geo = {
        "components": [
            {"primitiveId": "c1", "state": {"Designator": "U1", "X": 0, "Y": 0}},
            {"primitiveId": "c2", "state": {"Designator": "R1", "X": 400, "Y": 0}},
        ],
        "pins": [],
        "wires": [],
        "netlabels": [],
    }
    client = FakeClient(geo)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS,
    ))

    actions = [a for a, _p in client.calls]
    assert actions[0] == "sch.doc.new"
    assert actions.count("sch.place_component") == 2
    assert "sch.place_power" in actions, "GND is named with a flag on its wire"
    assert "sch.place_text" in actions, "RX is named with a decorative text label"
    assert "sch.place_netport" not in actions, "ports are banned"
    assert "sch.place_wire" in actions, "RX is wired"
    assert result.naming_strategy == "text", "the default naming policy is reported"
    assert result.candidate_source == "geometry readback", (
        "the fake netlist text is unparseable; the fallback must engage"
    )
    assert result.comparison is not None
    assert not result.zero_diff, "an unwired candidate must differ"


def test_run_draw_self_check_failure_executes_nothing():
    """Revision 3's gate: violations abort BEFORE a single bridge call."""
    from boardwise.engines.draw import SelfCheckFailed

    # a U1 pin whose offset points far off the sheet: the box leaves the
    # frame and the gate must refuse
    bad_offsets = {
        "U1": {"1": (-20.0, -10.0), "2": (-20.0, 10.0), "9": (2000.0, 0.0)},
        "R1": {"1": (-20.0, 0.0), "2": (20.0, 0.0)},
    }
    model = _golden_model()
    model.nets["BAD"] = Net(name="BAD", pins=[("U1", "9"), ("R1", "1")])
    model.components["U1"].pins[2].net = "BAD"
    model.components["R1"].pins[0].net = "BAD"
    model.nets["GND"].pins = [("U1", "1"), ("R1", "2")]
    model.components["U1"].pins[0].net = "GND"
    model.components["R1"].pins[1].net = "GND"
    client = FakeClient(_geo())
    with pytest.raises(SelfCheckFailed) as excinfo:
        _run(run_draw(
            client, model, confirm=lambda: True, offsets=bad_offsets,
        ))
    assert any("OUT_OF_SHEET" in line for line in excinfo.value.violations)
    assert client.calls == [], "nothing may execute past a failed self-check"


def test_run_draw_gate_can_abort():
    client = FakeClient(_geo())
    with pytest.raises(DrawAborted):
        _run(run_draw(
            client, _golden_model(), confirm=lambda: False,
            offsets=GOLDEN_OFFSETS,
        ))
    assert client.calls == [], "nothing may execute before the gate passes"


def test_run_draw_records_failed_placements_and_continues():
    class PartialClient(FakeClient):
        async def call(self, action: str, params=None) -> dict:
            if action == "sch.place_component" and (params or {}).get("designator") == "R1":
                raise RuntimeError("LCSC C999 matched no library device")
            return await super().call(action, params)

    client = PartialClient(_geo())
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS,
    ))
    assert any("R1" in f.summary for f in result.failures), (
        "a failed placement is a report row, not a crash"
    )
    # the flow continued: naming and wiring still executed
    actions = [a for a, _p in client.calls]
    assert "sch.place_power" in actions
    assert "sch.place_text" in actions


def test_run_draw_flags_a_project_scoped_netlist():
    """The netlist is per project, not per page — say so instead of faking it.

    Measured 2026-09-14: leftover pages from earlier runs put 51 designators in
    one export, and the golden-named parts happened to sit on the page an
    earlier run had abandoned *before* the wires. Every pin then read as
    unconnected, which looks exactly like 54 broken connections.
    """
    _SCOPE_SAMPLE = """{
        "version": "2.0.0",
        "components": {
            "a": {"props": {"Designator": "U1"}, "pinInfoMap": {
                "1": {"name": "", "number": "1", "net": "GND", "props": {}},
                "2": {"name": "", "number": "2", "net": "RX", "props": {}},
                "9": {"name": "", "number": "9", "net": "", "props": {}}}},
            "b": {"props": {"Designator": "R1"}, "pinInfoMap": {
                "1": {"name": "", "number": "1", "net": "GND", "props": {}},
                "2": {"name": "", "number": "2", "net": "RX", "props": {}}}},
            "c": {"props": {"Designator": "U2"}, "pinInfoMap": {
                "1": {"name": "", "number": "1", "net": "GND", "props": {}}}}
        },
        "designRule": {}
    }"""
    client = FakeClient(_geo(), netlist={
        "type": "EasyEDA", "source": "getNetlistFile", "size": 0,
        "text": _SCOPE_SAMPLE,
    })
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS,
    ))
    scope_failure = [
        r for r in result.records
        if r.action == "candidate.scope" and not r.ok
    ]
    assert scope_failure, "an out-of-scope netlist must be reported, not silently diffed"
    assert "U2" in scope_failure[0].detail
    assert "outside the golden model" in scope_failure[0].detail


def test_run_draw_fails_fast_when_a_part_cannot_be_mapped():
    """F2: an unmappable part must stop the run BEFORE any wire is drawn.

    Round 4 drew the whole page and *then* discovered 51 differences whose
    root cause was a replaced library part. The gate exists so that failure
    mode costs nothing but a refusal: no wires, no names, an explicit
    reason.
    """
    # R1 comes back with pins the golden cannot address by number or name.
    _WRONG_NETLIST = """{
        "version": "2.0.0",
        "components": {
            "u1": {
                "props": {"Designator": "U1", "Unique ID": "u1"},
                "pinInfoMap": {
                    "1": {"name": "", "number": "1", "net": "GND", "props": {}},
                    "2": {"name": "", "number": "2", "net": "RX", "props": {}},
                    "9": {"name": "", "number": "9", "net": "", "props": {}}
                }
            },
            "r1": {
                "props": {"Designator": "R1", "Value": "10k", "Unique ID": "r1"},
                "pinInfoMap": {
                    "ANODE": {"name": "ANODE", "number": "ANODE", "net": "GND", "props": {}},
                    "CATHODE": {"name": "CATHODE", "number": "CATHODE", "net": "RX", "props": {}}
                }
            }
        },
        "designRule": {}
    }"""
    client = FakeClient(_geo(), netlist={
        "type": "EasyEDA", "source": "getNetlistFile", "size": 0,
        "text": _WRONG_NETLIST,
    })
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS,
    ))

    assert result.placement_report is not None
    assert not result.placement_report.ok
    assert "R1" in result.placement_report.blocks()

    # the refusal happened before the copper: no wire, no net name reached
    # the editor, and the run stopped rather than producing a broken page
    actions = [a for a, _p in client.calls]
    assert "sch.place_wire" not in actions
    assert "sch.place_text" not in actions
    assert result.comparison is None


def test_run_draw_continues_when_the_readback_is_unavailable():
    """Not knowing must stay distinct from knowing it is broken.

    The netlist export is the measured-flaky step on this host; when it
    yields nothing, the placement gate cannot run — and *that* must not
    block a draw that 006 could complete. The failure is recorded instead.
    """
    client = FakeClient(_geo(), netlist={"type": "EasyEDA", "size": 0, "text": ""})
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS,
    ))
    assert result.placement_report is None
    assert any(
        r.action == "verify.placements" and not r.ok for r in result.records
    ), "the missing readback is reported as a step, not silently swallowed"
    actions = [a for a, _p in client.calls]
    assert "sch.place_wire" in actions, "the draw still completed"
    # and the final diff still ran (via the geometry fallback)
    assert result.candidate_source == "geometry readback"
    assert result.comparison is not None


def test_run_draw_prefers_the_netlist_and_classifies_enrichment():
    """The measured EasyEDA netlist JSON is the primary candidate source."""
    _NETLIST_SAMPLE = """{
        "version": "2.0.0",
        "components": {
            "gge57": {
                "props": {"Designator": "U1", "Name": "CH340G", "Value": "CH340G",
                           "Unique ID": "gge57"},
                "pinInfoMap": {
                    "1": {"name": "GND", "number": "1", "net": "GND", "props": {}},
                    "2": {"name": "TXD", "number": "2", "net": "RX", "props": {}},
                    "9": {"name": "CTS#", "number": "9", "net": "", "props": {}}
                }
            },
            "gge58": {
                "props": {"Designator": "R1", "Name": "10k", "Value": "10k",
                           "Unique ID": "gge58"},
                "pinInfoMap": {
                    "1": {"name": "1", "number": "1", "net": "GND", "props": {}},
                    "2": {"name": "2", "number": "2", "net": "RX", "props": {}}
                }
            }
        },
        "designRule": {}
    }"""
    geo = {
        "components": [],
        "pins": [],
        "wires": [],
        "netlabels": [],
    }
    client = FakeClient(geo, netlist={
        "type": "EasyEDA", "source": "getNetlistFile", "size": 0,
        "text": _NETLIST_SAMPLE,
    })
    # golden side has NO lcsc/value for U1: the netlist's filled values are
    # library enrichment and must not fail the run.
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS,
    ))
    assert result.candidate_source == "netlist export"
    assert result.placement_report is not None
    assert result.placement_report.ok

    # The verdict's netlist must be read AFTER the wires. Step 2b's placement
    # readback happens before any wire exists; reusing it for the diff reported
    # every pin as unconnected (measured 2026-09-14: 54 phantom pin
    # differences). Three exports are therefore correct, not wasteful.
    actions = [a for a, _p in client.calls]
    netlist_at = [i for i, a in enumerate(actions) if a == "sch.netlist"]
    assert len(netlist_at) == 3, (
        "one export for the placement gate, and the verdict takes two — the "
        "second because the editor recomputes connectivity after the wires "
        "land (measured 2026-09-15: the first verdict read reported U1.16 "
        "unconnected on a page that was already correct). Reusing the gate's "
        "readback for the verdict would diff an unwired page."
    )
    assert actions.index("sch.place_wire") < netlist_at[-1], (
        "the verdict's netlist must come after the wires are placed"
    )
    assert result.zero_diff, (
        "pin nets match (GND/RX) and U1.9 is unconnected on both sides; "
        f"diff was: {result.comparison.render() if result.comparison else None}"
    )
    assert any("U1" in note for note in result.enrichment_notes)
    assert result.screenshot_b64 == "c2hvdA=="


def test_geometry_canvas_mode_matches_plan_positions():
    """The draw flow passes CANVAS part positions (positive y); the builder
    must match them verbatim — negating them (file convention) found
    nothing on the real P6 page (2026-09-14 morning draw)."""
    geo = {
        "components": [
            {"primitiveId": "c1", "state": {"ComponentType": "part", "Symbol": "sym-r",
                                             "X": 100, "Y": 95}},
        ],
        "pins": [],
        "wires": [
            {"primitiveId": "w1", "state": {"Net": "RX", "Line": [80, 95, 120, 95]}},
        ],
        "netlabels": [],
    }
    canvas_positions = {(100.0, 95.0): "U1"}
    offsets = {"sym-r": {"1": (-20.0, 0.0), "2": (20.0, 0.0)}}
    model = candidate_from_geometry(
        geo, symbol_defs=offsets, part_positions=canvas_positions,
    )
    assert set(model.components) == {"U1"}, "the editor's own position must match"
    pins = {p.number: p.net for p in model.components["U1"].pins}
    assert pins == {"1": "RX", "2": "RX"}
    # There is no second convention any more (task 010c): a negated key finds
    # nothing, which is the assertion that pins it — the builder used to hit a
    # file-space fallback, and that fallback is what mirrored hand-authored
    # geometry.
    file_model = candidate_from_geometry(
        geo, symbol_defs=offsets, part_positions={(100.0, -95.0): "U1"},
    )
    assert set(file_model.components) == set()


def test_geometry_canvas_mode_matches_plan_positions():
    """The draw flow passes CANVAS part positions (positive y); the builder
    must match them verbatim — negating them (file convention) found
    nothing on the real P6 page (2026-09-14 morning draw)."""
    geo = {
        "components": [
            {"primitiveId": "c1", "state": {"ComponentType": "part", "Symbol": "sym-r",
                                             "X": 100, "Y": 95}},
        ],
        "pins": [],
        "wires": [
            {"primitiveId": "w1", "state": {"Net": "RX", "Line": [80, 95, 120, 95]}},
        ],
        "netlabels": [],
    }
    canvas_positions = {(100.0, 95.0): "U1"}
    offsets = {"sym-r": {"1": (-20.0, 0.0), "2": (20.0, 0.0)}}
    model = candidate_from_geometry(
        geo, symbol_defs=offsets, part_positions=canvas_positions,
    )
    assert set(model.components) == {"U1"}, "the editor's own position must match"
    pins = {p.number: p.net for p in model.components["U1"].pins}
    assert pins == {"1": "RX", "2": "RX"}
    # There is no second convention any more (task 010c): a negated key finds
    # nothing, which is the assertion that pins it — the builder used to hit a
    # file-space fallback, and that fallback is what mirrored hand-authored
    # geometry.
    file_model = candidate_from_geometry(
        geo, symbol_defs=offsets, part_positions={(100.0, -95.0): "U1"},
    )
    assert set(file_model.components) == set()


# --------------------------------------------------------------------------
# the 006b replay path, driven through run_draw
# --------------------------------------------------------------------------


def test_run_draw_replays_the_golden_layout_when_given_one():
    """With the golden page's geometry supplied, the plan is a replay: golden
    rotations, rails as flags, signals as **labels** (never ports), and the
    gate still precedes every bridge call."""
    from boardwise.parsers.schematic import (
        build_pin_offsets,
        build_schematic_model,
        collect_page_layout,
    )

    golden_path = "tests/fixtures/ch340_golden.epro2"
    golden = strip_dangling_nets(build_schematic_model(golden_path))
    offsets = build_pin_offsets(golden_path)
    page = collect_page_layout(golden_path)

    client = FakeClient(_geo())
    result = _run(
        run_draw(
            client,
            golden,
            confirm=lambda: True,
            offsets=offsets,
            page_layout=page,
            bodies=None,
        )
    )
    assert result.plan_source == "golden replay"
    assert len(result.plan.placements) == 17
    # the frame falls back to the golden's declared size when the fake host
    # reports no sheet bbox — with provenance, never silently
    assert result.frame is not None
    assert result.frame.provenance == "declared-size"

    rotations = {step.designator: step.rotation for step in result.plan.placements}
    golden_rotations = {part.designator: part.rotation for part in page.parts}
    assert rotations == golden_rotations

    kinds = {step.kind for step in result.plan.net_names}
    assert kinds == {"Ground", "Power", "text"}
    actions = [action for action, _params in client.calls]
    assert "sch.place_netport" not in actions, "ports are banned on the replay path"
    assert "sch.place_text" in actions, "signals are named with decorative text by default"
    assert "sch.place_netlabel" not in actions, "the native label API is dormant (v4)"
    assert "export.render" in actions, "the acceptance image is a document render"
    assert actions[0] == "sch.geometry", "the frame is read before anything is created"
    assert actions[1] == "sch.doc.new", "the gate precedes every mutation"


def test_run_draw_naming_strategy_switch_controls_the_naming_actions():
    """`label` re-enables the native path; `wire` places no name at all."""
    client = FakeClient(_geo())
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS, strategy="label",
    ))
    actions = [action for action, _params in client.calls]
    assert "sch.place_netlabel" in actions, "the label strategy uses the native action"
    assert "sch.place_text" not in actions
    assert result.naming_strategy == "label"

    client = FakeClient(_geo())
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True,
        offsets=GOLDEN_OFFSETS, strategy="wire",
    ))
    actions = [action for action, _params in client.calls]
    assert "sch.place_text" not in actions, "the wire carries the name itself"
    assert "sch.place_netlabel" not in actions
    assert "sch.place_power" in actions, "rails keep their flags"
    assert result.naming_strategy == "wire"


def test_run_draw_reports_the_render_and_probe_separately():
    class RenderClient(FakeClient):
        async def call(self, action: str, params=None) -> dict:
            if action == "export.render":
                self.calls.append((action, params or {}))
                return {"format": "image/png", "encoding": "base64", "data": "cmVuZGVy"}
            return await super().call(action, params)

    from boardwise.parsers.schematic import build_pin_offsets, build_schematic_model

    golden_path = "tests/fixtures/ch340_golden.epro2"
    client = RenderClient(_geo())
    result = _run(
        run_draw(
            client,
            strip_dangling_nets(build_schematic_model(golden_path)),
            confirm=lambda: True,
            offsets=build_pin_offsets(golden_path),
            prefer_replay=False,
        )
    )
    assert result.render_b64 == "cmVuZGVy"
    assert result.screenshot_b64 == "c2hvdA==", "the screenshot stays a separate diagnostic"
    assert result.netlist_probe is not None


def test_census_counts_every_primitive_including_unlabelled_ones():
    """The netlist-failure census must never drop an unnamed primitive.

    The hypothesis under test (006b §A) is that a net-port primitive poisons
    the exporter. A census that silently skips records it cannot tag would
    hide exactly the row that matters, so unreadable records land in an
    explicit ``<unlabelled>`` bucket.
    """
    from boardwise.engines.draw import _census_types

    geometry = {
        "primitives": [
            {"type": "sch_PrimitiveComponent"},
            {"primitiveType": "sch_PrimitiveWire"},
            {"kind": "sch_PrimitiveNetPort"},
            {"className": "SCH_PrimitiveText"},
            {"name": "sch_PrimitivePin"},
            {"no": "recognisable", "tag": "here"},
            "not even a dict",
        ]
    }
    census = _census_types(geometry)
    assert census == {
        "sch_PrimitiveComponent": 1,
        "sch_PrimitiveWire": 1,
        "sch_PrimitiveNetPort": 1,
        "SCH_PrimitiveText": 1,
        "sch_PrimitivePin": 1,
        "<unlabelled>": 2,
    }, "no primitive may vanish from the census"


def test_census_is_empty_when_the_dump_has_no_primitive_list():
    from boardwise.engines.draw import _census_types

    assert _census_types(None) == {}
    assert _census_types({}) == {}
    assert _census_types({"primitives": "not a list"}) == {}


# --------------------------------------------------------------------------
# two conventions the machine forced us to translate
# --------------------------------------------------------------------------

def test_editor_rotation_flips_the_sign_and_only_the_sign():
    """90/270 came back exchanged, 0/180 were right — the signature of a flip.

    Measured 2026-09-14: every two-pin passive replayed at 90 or 270 had its
    pins swapped relative to the golden, while 0 and 180 were correct. Negating
    an angle is the only transform with exactly that shape.
    """
    from boardwise.engines.draw import _editor_rotation

    assert _editor_rotation(0) == 0
    assert _editor_rotation(180) == 180
    assert _editor_rotation(90) == 270
    assert _editor_rotation(270) == 90
    # applying it twice is the identity — it is a flip, not an offset
    for angle in (0, 90, 180, 270):
        assert _editor_rotation(_editor_rotation(angle)) == angle


def test_derived_net_names_are_matched_by_members_not_by_name():
    """`$11N…` vs `NET1` is the same cluster; a different cluster is not."""
    from boardwise.engines.draw import _reconcile_derived_names

    golden = DesignModel()
    golden.nets["NET1"] = Net(name="NET1", pins=[("U1", "1"), ("R1", "1")])
    golden.nets["GND"] = Net(name="GND", pins=[("U1", "2")])

    candidate = DesignModel()
    candidate.nets["$11N9"] = Net(name="$11N9", pins=[("U1", "1"), ("R1", "1")])
    candidate.nets["$11N4"] = Net(name="$11N4", pins=[("U1", "1")])  # short by one
    for designator, pins in (("U1", ("1", "2")), ("R1", ("1",))):
        candidate.components[designator] = Component(
            uid=designator, designator=designator,
            pins=[Pin(number=n, name="", net=None) for n in pins],
        )
    for name, net in candidate.nets.items():
        for des, number in net.pins:
            for pin in candidate.components[des].pins:
                if pin.number == number:
                    pin.net = name

    assert _reconcile_derived_names(golden, candidate) == 1
    assert "$11N9" not in candidate.nets
    assert "NET1" in candidate.nets
    # the cluster that is missing a member keeps its own name and still fails
    assert "$11N4" in candidate.nets


def test_power_flags_get_the_same_rotation_correction_as_parts():
    """A flag at rot 90/270 must not point away from its wire.

    Measured 2026-09-15: the seven flag symbols in the golden all keep their
    pin at (0, 0), so the placement origin *is* the connection point and the
    netlist looked clean — which is exactly why the wrong visual direction hid
    for a round. The editor's rotation convention is the same one
    `place_component` needed correcting for, so the flag branch must use it
    too.
    """
    from boardwise.engines.draw import _editor_rotation
    from boardwise.parsers.schematic import (
        build_pin_offsets,
        build_schematic_model,
        collect_page_layout,
    )

    golden_path = "tests/fixtures/ch340_golden.epro2"
    golden = build_schematic_model(golden_path)
    page = collect_page_layout(golden_path)
    assert page.flags, "the golden fixture must carry power/ground flags"

    client = FakeClient(_geo())
    _run(run_draw(
        client, golden, confirm=lambda: True,
        offsets=build_pin_offsets(golden_path),
        page_layout=page, bodies=None,
    ))

    power_params = [p for a, p in client.calls if a == "sch.place_power"]
    assert len(power_params) == len(page.flags), "one flag per golden flag"
    # Compare as multisets: twelve of the flags are GND and their angles differ
    # per instance, so keying by net would collide.
    expected = sorted(_editor_rotation(f.rotation) for f in page.flags)
    placed = sorted(p["rotation"] for p in power_params)
    assert placed == expected, (
        "every flag must go through the same sign correction as a part"
    )


def test_drifted_endpoints_snap_to_placed_pin_positions():
    """真 F3: an endpoint aimed at a golden tip that does not exist moves.

    The replay points wires at the golden pin tips. For a drifted part those
    tips do not exist on the placed page (the library redrew the symbol), so
    the seventh path hands back the placed component's real pin coordinates
    and the endpoints move onto them — through F2's pin map, and nothing else
    in the plan changes.
    """
    import asyncio

    from boardwise.core.verify import (
        MATCH_DRIFTED,
        PinMap,
        PlacementCheck,
    )
    from boardwise.engines.draw import _snap_drifted_pins
    from boardwise.engines.generate import ActionPlan, NetNameStep, WireStep

    plan = ActionPlan()
    plan.pin_positions[("USB1", "1")] = (89.0, 755.0)
    plan.pin_positions[("USB1", "2")] = (89.0, 745.0)
    plan.wires.append(WireStep(net="GND", points=[(89.0, 755.0), (200.0, 700.0)]))
    plan.wires.append(WireStep(net="+5V", points=[(300.0, 300.0), (89.0, 745.0)]))
    plan.net_names.append(NetNameStep(net="GND", kind="Ground", x=89.0, y=755.0))

    class PinsClient:
        async def call(self, action, params):
            assert action == "sch.component_pins"
            assert params["primitiveId"] == "eb0579dc"
            return {"pins": [
                {"PinNumber": "A1B12", "X": 115.0, "Y": 755.0},
                {"PinNumber": "A4B9", "X": 115.0, "Y": 745.0},
            ]}

    check = PlacementCheck(
        designator="USB1", kind=MATCH_DRIFTED, detail="",
        pin_map=PinMap(
            designator="USB1", kind=MATCH_DRIFTED,
            pairs={"1": "A1B12", "2": "A4B9"},
        ),
    )
    moved = _run(
        _snap_drifted_pins(PinsClient(), plan, [check], {"USB1": "eb0579dc"}, [])
    )

    assert moved == 3, "two wire endpoints and one name anchor move"
    # The golden run is **kept**: the polyline still passes through the golden
    # tip and gains a straight stub from there to the placed pin. Re-routing
    # instead was measured twice to cross a neighbouring net inside the dense
    # pin field and merge with it.
    # the stub is straight (same y), and the synthetic golden run after it is
    # diagonal, so the orthogonalizer splits that run into an L as well
    assert plan.wires[0].points == [
        (115.0, 755.0), (89.0, 755.0), (200.0, 755.0), (200.0, 700.0),
    ]
    assert plan.wires[1].points == [
        (300.0, 300.0), (89.0, 300.0), (89.0, 745.0), (115.0, 745.0),
    ]
    assert (plan.net_names[0].x, plan.net_names[0].y) == (115.0, 755.0)


# --------------------------------------------------------------------------
# M0-P0d: persistence is three facts, and a timeout is not "nothing happened"
# --------------------------------------------------------------------------


class FaultClient(FakeClient):
    """A ``FakeClient`` that can be told to fail a named action.

    Three shapes, because they are three different facts:

    * a **timeout** — the daemon stopped waiting. The editor was never told to
      cancel, so the write may still have landed;
    * a **refusal** — the editor answered, and said no;
    * a **disconnect** — the socket died mid-run.

    ``fail`` maps an action to ``(exception, times)``; ``times=None`` means
    "always". An attempt that raises is still recorded in ``calls``, so a retry
    shows up as a second entry rather than as nothing at all.

    ``die_after`` models the daemon being killed: the first ``k`` calls answer
    normally, and everything from the ``k+1``-th on fails with a disconnect.
    That is the scenario-B shape — a *moment* the transport died, not a
    per-action fault — and it is what makes "some writes landed and the rest are
    unknown" reproducible offline.
    """

    def __init__(
        self,
        geometry: dict,
        netlist: dict | None = None,
        *,
        fail=None,
        die_after: int | None = None,
    ):
        super().__init__(geometry, netlist)
        self.fail = dict(fail or {})
        self.die_after = die_after

    async def call(self, action: str, params=None) -> dict:
        if self.die_after is not None and len(self.calls) >= self.die_after:
            self.calls.append((action, params or {}))
            raise BridgeError(
                ErrorCodes.DISCONNECTED,
                f"the daemon connection closed while {action!r} was in flight",
            )
        plan = self.fail.get(action)
        if plan is not None:
            exc, times = plan
            self.calls.append((action, params or {}))
            if times is None or times > 0:
                if times is not None:
                    self.fail[action] = (exc, times - 1)
                raise exc
        return await super().call(action, params)


def _timeout(action: str) -> BridgeError:
    return BridgeError(
        ErrorCodes.TIMEOUT, f"{action} timed out after 30s"
    )


def test_the_timeout_code_the_flow_watches_for_is_the_one_the_daemon_sends():
    """``draw`` reads the code by string, so a rename must not pass silently.

    `engines/` does not import `bridge/` (the transport arrives as a duck-typed
    client), which means the flow holds its own copy of the timeout code. This
    is the test that keeps the copy honest — without it, changing
    `ErrorCodes.TIMEOUT` would quietly turn every timeout back into a plain
    failure and the re-read path would stop running.
    """
    assert TIMEOUT_CODE == ErrorCodes.TIMEOUT


def test_a_timed_out_write_reads_the_page_back_and_is_never_retried():
    """The ruling's core case (M0-P0d, 裁决 2).

    ``sch.place_component`` times out. The daemon dropped the pending future
    without cancelling the editor, so the part may be on the page — and a retry
    would put a second one on the same spot. The flow must therefore look and
    report, never re-issue.
    """
    client = FaultClient(_geo(), fail={"sch.place_component": (_timeout("sch.place_component"), None)})
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))

    actions = [a for a, _p in client.calls]
    # one attempt per planned part — the count is the no-retry evidence
    assert actions.count("sch.place_component") == 2, actions

    readbacks = [
        r for r in result.records
        if r.action == "sch.geometry" and "read the page back" in r.summary
    ]
    assert len(readbacks) == 2, "every timed-out write gets its own readback"
    assert all(r.ok for r in readbacks), "the read itself answered"

    unknowns = [r for r in result.records if r.action == "persistence.sch.place_component"]
    assert len(unknowns) == 2
    for record in unknowns:
        assert not record.ok
        assert "UNKNOWN" in record.summary
        assert "nothing was retried" in record.summary
        assert "may still have landed" in record.detail
        # The reason covers both failure shapes, because the readback is what
        # makes either one safe to report as unknown.
        assert "not a cancellation" in record.detail
        assert "not a failed write" in record.detail

    assert [r.action for r in result.timeouts] == ["sch.place_component"] * 2


def test_a_timed_out_write_is_still_recorded_as_a_timeout_not_a_refusal():
    """A timeout and a refusal are different failures and must not merge.

    Until M0-P0d both arrived as ``None`` from the same helper, which is why the
    re-read could not be attached to the timeout alone.
    """
    client = FaultClient(_geo(), fail={"sch.doc.new": (_timeout("sch.doc.new"), None)})
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    staged = [r for r in result.records if r.action == "sch.doc.new"]
    assert staged and staged[0].timed_out
    assert not staged[0].ok


def test_a_refused_write_is_not_a_timeout_and_gets_no_readback():
    """An answer that says no is not an absence of an answer."""
    client = FaultClient(
        _geo(),
        fail={"sch.doc.new": (
            BridgeError(ErrorCodes.CONNECTOR_ERROR, "the editor refused"), None
        )},
    )
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    record = [r for r in result.records if r.action == "sch.doc.new"][0]
    assert not record.ok
    assert not record.timed_out
    assert result.timeouts == []
    assert not [
        r for r in result.records
        if r.action == "sch.geometry" and "read the page back" in r.summary
    ], "no timeout means no readback obligation"


def test_a_page_that_never_appeared_is_not_placed():
    """Nothing written is its own state, not a weaker "saved"."""
    client = FaultClient(
        _geo(),
        fail={"sch.doc.new": (
            BridgeError(ErrorCodes.CONNECTOR_ERROR, "the editor refused"), None
        )},
    )
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.persistence == PERSISTENCE_NOT_PLACED
    assert result.save_ok is False


def test_a_refused_save_is_reported_rather_than_discarded():
    """The connector *throws* when the editor refuses a save (audit D).

    The flow used to ignore the save's answer entirely, so a refused save was
    indistinguishable from a successful one and the report stayed silent about
    the exact fact this task exists to state.
    """
    client = FaultClient(
        _geo(),
        fail={"sch.doc.save": (
            BridgeError(
                ErrorCodes.CONNECTOR_ERROR,
                "sch_Document.save() returned false — the project may need a manual save",
            ),
            None,
        )},
    )
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.save_ok is False
    refusals = [r for r in result.records if r.action == "persistence.save"]
    assert refusals, "a refused save must leave a row, not vanish"
    assert all(not r.ok for r in refusals)
    assert "did NOT accept a save" in refusals[0].summary
    assert result.persistence in (PERSISTENCE_PLACED, PERSISTENCE_NOT_PLACED), (
        "without a save ack the run cannot claim saved_unverified"
    )


def test_a_clean_run_tops_out_at_saved_unverified():
    """The ceiling is structural, not an oversight.

    ``saved_verified`` needs a close-and-reopen, and the bridge cannot perform
    one: ``doc.open`` is a read that moves focus without reloading from disk and
    there is no close-project action (audit E). So a draw that went perfectly
    still may not say "saved" without a qualifier.
    """
    client = FakeClient(_geo())
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.save_ok is True
    assert result.persistence == PERSISTENCE_SAVED_UNVERIFIED
    assert result.saved_verified is False
    assert result.persistence != PERSISTENCE_SAVED_VERIFIED


def test_an_unreachable_editor_does_not_produce_a_second_page():
    """A disconnect mid-run: nothing is retried, one page was ever asked for."""
    client = FaultClient(
        _geo(), fail={"sch.place_wire": (OSError("connection closed"), None)}
    )
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    actions = [a for a, _p in client.calls]
    assert actions.count("sch.doc.new") == 1, "the page is never created twice"
    assert actions.count("sch.place_component") == 2, "placements are not retried"
    assert [r for r in result.records if r.action == "sch.place_wire"], (
        "the dead socket is reported per action"
    )
    assert result.save_ok is not True or result.persistence != PERSISTENCE_SAVED_VERIFIED


def test_a_partly_written_page_never_reaches_saved_unverified_over_a_timeout():
    """Half a page plus a timed-out save is "unknown", and must say so."""
    client = FaultClient(
        _geo(),
        fail={
            "sch.place_wire": (_timeout("sch.place_wire"), None),
            "sch.doc.save": (_timeout("sch.doc.save"), None),
        },
    )
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.save_ok is False
    assert result.persistence not in (
        PERSISTENCE_SAVED_UNVERIFIED, PERSISTENCE_SAVED_VERIFIED,
    )
    assert len(result.timeouts) >= 2
    # the wires were attempted exactly once each
    planned_wires = len(result.plan.wires)
    actions = [a for a, _p in client.calls]
    assert actions.count("sch.place_wire") == planned_wires


# --------------------------------------------------------------------------
# M0-P0d follow-up: a transport death is not "nothing was written"
# --------------------------------------------------------------------------


def test_a_transport_death_never_claims_nothing_was_written():
    """Scenario B, reproduced: the daemon dies after writes have landed.

    Measured on the real host 2026-09-18 — `taskkill` on the daemon mid-draw left
    five parts on the page, and the report said
    `persistence: not_placed — nothing was written`. A reader who believed it
    would redraw onto a page that already had them, ending with two sets of parts
    on one sheet. `not_placed` asserts an *absence*, so it may only be reached
    with evidence of the absence: zero writes acknowledged and none unanswered.
    """
    client = FaultClient(_geo(), die_after=5)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))

    assert result.persistence == PERSISTENCE_UNKNOWN, result.persistence
    assert result.persistence != PERSISTENCE_NOT_PLACED
    assert "nothing was written" not in PERSISTENCE_WORDS[result.persistence]

    # The parts really are on the page: the report has to say so.
    acknowledged = [r.action for r in result.acknowledged_writes]
    assert acknowledged.count("sch.place_component") == 2, acknowledged
    assert "sch.doc.new" in acknowledged, acknowledged
    assert result.unknown_writes, "the writes that never answered are listed too"


def test_the_dead_transport_is_never_read_as_an_empty_page():
    """A readback that cannot happen must say so, not report zero.

    The connection is gone, so the look itself fails — and "we could not look"
    is the one answer that must never be rendered as "there is nothing there".
    """
    client = FaultClient(_geo(), die_after=5)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))

    looks = [
        r for r in result.records
        if r.action == "sch.geometry" and "read the page back" in r.summary
    ]
    assert looks, "the flow must at least try to look"
    assert all(not r.ok for r in looks), "the socket is dead; the look cannot succeed"

    unknown = [r for r in result.records if r.action.startswith("persistence.")]
    assert unknown, unknown
    detail = " ".join(r.detail for r in unknown)
    assert "could not look" in detail or "there is nothing to read" in detail, detail
    assert "0 component(s)" not in detail, (
        "an unanswerable readback must never be phrased as a count"
    )


def test_the_page_is_looked_at_once_not_once_per_write():
    """A dead socket has one story; repeating it per write buries the one row.

    The first unknown write gets a real look. After that the flow records that it
    did not look again, and says why — which is information, not silence.
    """
    client = FaultClient(_geo(), die_after=5)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))

    looks = [
        r for r in result.records
        if r.action == "sch.geometry" and "read the page back" in r.summary
    ]
    assert len(looks) == 1, [r.summary for r in looks]
    assert len(result.unknown_writes) >= 2, "more than one write went unanswered"
    skipped = [
        r for r in result.records
        if r.action.startswith("persistence.") and "nothing to read" in r.detail
    ]
    assert skipped, "later writes must say the transport was already known to be gone"


def test_the_writes_are_never_reissued_after_a_transport_death():
    """The no-retry rule, on the disconnect path."""
    client = FaultClient(_geo(), die_after=5)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    actions = [a for a, _p in client.calls]
    assert actions.count("sch.doc.new") == 1
    assert actions.count("sch.place_component") == 2
    assert actions.count("sch.place_wire") == len(result.plan.wires)


def test_a_death_on_the_first_write_is_unknown_too():
    """A disconnect on the page creation is not evidence that no page was made.

    `sch.doc.new` timed out or lost its answer means the page may well exist, so
    the run cannot claim the page was never touched either.
    """
    client = FaultClient(_geo(), die_after=0)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.persistence == PERSISTENCE_UNKNOWN, result.persistence
    assert result.acknowledged_writes == []
    assert [r.action for r in result.unknown_writes] == ["sch.doc.new"]


def test_not_placed_still_belongs_to_a_refusal_before_any_write():
    """The guard on the other side: an *answer* of no is not an unknown.

    A refusal leaves no doubt — nothing was written — so `not_placed` stays
    correct, and must stay reachable, or the state would become unusable.
    """
    client = FaultClient(
        _geo(),
        fail={"sch.doc.new": (
            BridgeError(ErrorCodes.CONNECTOR_ERROR, "the editor refused"), None
        )},
    )
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.persistence == PERSISTENCE_NOT_PLACED
    assert result.acknowledged_writes == []
    assert result.unknown_writes == []
    assert "not one write was acknowledged" in PERSISTENCE_WORDS[PERSISTENCE_NOT_PLACED]


# --------------------------------------------------------------------------
# the CLI half: the exit code and the audit record must carry the same answer
# --------------------------------------------------------------------------


def _draw_args(**overrides) -> argparse.Namespace:
    """The argparse surface ``_render_draw_result`` reads."""
    base = {"spec": "spec.json", "render": None, "screenshot": None}
    base.update(overrides)
    return argparse.Namespace(**base)


def _timed_out_run():
    client = FaultClient(
        _geo(), fail={"sch.place_wire": (_timeout("sch.place_wire"), None)}
    )
    return _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))


def test_a_timed_out_write_cannot_finish_green(capsys):
    """Exit 3, not 0: "the diff matched" is not "the page is right" (裁决 2).

    The scenario is the ruling's own: the page happens to diff clean, but a
    write timed out, so the page's state is unknown. A run whose outcome is
    unknown must not be able to report success — that was the whole bug, and
    the exit code is what a script reads.
    """
    from boardwise.cli import _render_draw_result
    from boardwise.core.compare import compare_models

    result = _timed_out_run()
    # Make the diff genuinely clean, so the timeout is the only complaint.
    result.comparison = compare_models(_golden_model(), _golden_model())
    assert result.comparison.is_empty

    code = _render_draw_result(result, _draw_args())
    printed = capsys.readouterr().out
    assert code == 3, "a timeout may not exit 0 through a clean diff"
    assert "the page's state" in printed and "UNKNOWN" in printed
    assert "persistence:" in printed


def test_a_transport_death_cannot_finish_green_and_names_what_landed(capsys):
    """Exit 3, and the report says which writes are on the page (M0-P0d follow-up).

    The interrupted run's exit code used to come out 1 (no diff ran), which is
    merely non-zero and says the wrong thing: the diff did not disagree, it never
    ran. 3 is the semantically right code — the state is unknown — and it has to
    outrank both 0 and 1, because "the diff differed" is also a claim about a
    page whose contents are no longer certain.
    """
    from boardwise.cli import _render_draw_result

    client = FaultClient(_geo(), die_after=5)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.comparison is None, "no diff ran in this scenario"

    code = _render_draw_result(result, _draw_args())
    printed = capsys.readouterr().out
    assert code == 3, "an interrupted run may not exit 1 as if the diff disagreed"
    assert "persistence: unknown" in printed
    assert "nothing was written" not in printed
    assert "were acknowledged before the run stopped" in printed
    assert "do NOT" in printed, "the reader must be warned before redrawing"
    assert "sch.place_component" in printed


def test_the_audit_log_alone_contradicts_nothing_was_written(tmp_path, monkeypatch):
    """The log has to answer this without the terminal scrollback.

    The daemon's own per-action records say `ok` and nothing about persistence,
    and the save payload never reaches them (audit F). So the `draw.persistence`
    line carries the count of acknowledged writes — the field a reader checks to
    see whether the page was touched.
    """
    from boardwise import cli as cli_module
    from boardwise.bridge import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    client = FaultClient(_geo(), die_after=5)
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    cli_module._audit_draw_persistence(result, 3)

    record = json.loads(
        next((tmp_path / "audit").glob("*.jsonl")).read_text(encoding="utf-8")
    )
    assert record["persistence"] == PERSISTENCE_UNKNOWN
    assert record["writesAcknowledged"] == len(result.acknowledged_writes)
    assert record["writesAcknowledged"] >= 3, "the page really was touched"
    assert record["writesUnknown"], "the unanswered writes are named"
    assert record["saveVerified"] is False
    assert "saved" not in record


def test_a_clean_run_without_timeouts_still_exits_zero(capsys):
    """The control: exit 3 must mean "a timeout happened", not "a draw ran"."""
    from boardwise.cli import _render_draw_result
    from boardwise.core.compare import compare_models

    client = FakeClient(_geo())
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    result.comparison = compare_models(_golden_model(), _golden_model())

    code = _render_draw_result(result, _draw_args())
    printed = capsys.readouterr().out
    assert code == 0
    assert "saved_unverified" in printed
    assert "NOT verified on disk" in printed, (
        "the report must not let a reader hear 'saved' without the qualifier"
    )


def test_the_persistence_state_reaches_the_audit_log(tmp_path, monkeypatch):
    """The log has to answer "did this run persist anything?" on its own.

    The daemon's per-action records say ``ok`` and nothing about persistence,
    and never carry the save's payload (audit F). So the CLI writes its own
    record — and the record's single ``persistence`` field is the only place a
    reader looks, which is what keeps "saved" out of the log unless it is true.
    """
    from boardwise import cli as cli_module
    from boardwise.bridge import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    result = _timed_out_run()
    cli_module._audit_draw_persistence(result, 3)

    written = list((tmp_path / "audit").glob("*.jsonl"))
    assert len(written) == 1, written
    records = [
        json.loads(line)
        for line in written[0].read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["action"] == daemon_module.AUDIT_DRAW_PERSISTENCE
    # The save *was* accepted here — the page content is what timed out — so the
    # state is saved_unverified and the two facts are kept apart rather than
    # merged into one verdict: unverified is not verified, and the timeout is
    # reported on its own.
    assert record["persistence"] == PERSISTENCE_SAVED_UNVERIFIED
    assert record["saveVerified"] is False
    assert record["exitCode"] == 3
    assert record["saveAccepted"] is True
    assert record["timeouts"] == ["sch.place_wire"] * len(result.plan.wires), (
        "one entry per timed-out call, and not one more (no retries)"
    )
    # No bare "saved" key exists to be misread: the state name is the answer.
    assert "saved" not in record


def test_the_verified_state_is_the_only_one_that_may_say_saved(tmp_path, monkeypatch):
    """``saved_verified`` is unreachable from a draw — so it must come from
    somewhere that really reopened, and only then may the log say so."""
    from boardwise import cli as cli_module
    from boardwise.bridge import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    client = FakeClient(_geo())
    result = _run(run_draw(
        client, _golden_model(), confirm=lambda: True, offsets=GOLDEN_OFFSETS,
    ))
    assert result.persistence == PERSISTENCE_SAVED_UNVERIFIED
    cli_module._audit_draw_persistence(result, 0)

    record = json.loads(
        next((tmp_path / "audit").glob("*.jsonl")).read_text(encoding="utf-8")
    )
    assert record["saveVerified"] is False, "a draw never verified anything on disk"
    assert record["persistence"] == PERSISTENCE_SAVED_UNVERIFIED
