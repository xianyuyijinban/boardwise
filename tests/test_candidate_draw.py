"""Tests for candidate-model builders and the draw orchestration (006).

The geometry fallback is the path that must work *today* (the netlist
format is calibrated from a live sample later), so its tests are exact:
synthetic geometry dumps with known connectivity, and the per-pin verdict
the diff must produce. ``run_draw`` is driven against a fake bridge client
that records every action, so the orchestration — gate, order, fallback
ladder — is tested without an editor.
"""

from __future__ import annotations

import pytest

from boardwise.core.candidate import (
    GeometryError,
    NetlistFormatError,
    candidate_from_geometry,
    candidate_from_netlist,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.draw import DrawAborted, run_draw
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
        part_positions_canvas=True,
    )
    assert set(model.components) == {"U1"}, "canvas-mode position must match"
    pins = {p.number: p.net for p in model.components["U1"].pins}
    assert pins == {"1": "RX", "2": "RX"}
    # and the file-space convention still works unchanged (calibration path)
    file_model = candidate_from_geometry(
        geo, symbol_defs=offsets, part_positions={(100.0, -95.0): "U1"},
    )
    assert set(file_model.components) == {"U1"}


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
        part_positions_canvas=True,
    )
    assert set(model.components) == {"U1"}, "canvas-mode position must match"
    pins = {p.number: p.net for p in model.components["U1"].pins}
    assert pins == {"1": "RX", "2": "RX"}
    # and the file-space convention still works unchanged (calibration path)
    file_model = candidate_from_geometry(
        geo, symbol_defs=offsets, part_positions={(100.0, -95.0): "U1"},
    )
    assert set(file_model.components) == {"U1"}


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
