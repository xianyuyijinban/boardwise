"""Issue #87④: additive, source-geometry element identity for voltage spacing."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from boardwise.core.designintent import IntentRail
from boardwise.core.geometry import (
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    TrackSegment,
    ViaGeometry,
)
from boardwise.core.measure import net_clearance
from boardwise.core.model import Pin
from boardwise.rules.pcb.ipc import VoltageSpacing, _clearance_measurement
import boardwise.core.measure as measure
from tools.contract_validate import validate

from test_126c_pcb_ipc_rules import (
    _component,
    _contract,
    _ctx,
    _model,
    _two_net_board,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "contracts/json/review-report-v1.schema.json").read_text(encoding="utf-8")
)
OLD_REPORT = json.loads(
    (ROOT / "contracts/differential/inputs/review-report.json").read_text(encoding="utf-8")
)
LAYERS = {
    1: LayerInfo(1, "Top", "TOP"),
    2: LayerInfo(2, "Bottom", "BOTTOM"),
}
STACKUP = [
    StackupEntry(1, 1, "copper", 1.0),
    StackupEntry(2, 2, "copper", 1.0),
]


def _reference_track(layer: int = 1) -> TrackSegment:
    return TrackSegment(
        "b-track", net="B", layer_id=layer,
        start=Point(100, 0), end=Point(110, 0), width=2,
    )


def _board_for(kind: str) -> BoardGeometry:
    pads: list[PadGeometry] = []
    tracks: list[TrackSegment] = [_reference_track()]
    vias: list[ViaGeometry] = []
    pours: list[PourShape] = []
    if kind == "track":
        tracks.insert(0, TrackSegment(
            "a-track", net="A", layer_id=1,
            start=Point(0, 0), end=Point(10, 0), width=2,
        ))
    elif kind == "pad":
        pads.append(PadGeometry(
            "template-id-not-a-pin", component="U9", pin_number="7A", net="A",
            footprint_layer_id=1, x=0, y=0, width=4, height=4,
            shape="RECT", hole_diameter=2,
        ))
    elif kind == "via":
        vias.append(ViaGeometry(
            "a-via", net="A", x=0, y=0, hole_diameter=2, via_diameter=6,
        ))
    elif kind == "pour":
        points = [Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)]
        pours.append(PourShape(
            "shared-record-id", net="A", layer_id=1, kind="poured",
            points=points, rings=[points],
        ))
    else:
        raise AssertionError(kind)
    return BoardGeometry(
        layers=LAYERS, stackup=STACKUP,
        pads=pads, tracks=tracks, vias=vias, pours=pours,
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("track", {"kind": "track", "component": "", "pin": "", "layers": [1]}),
        ("pad", {"kind": "pad", "component": "U9", "pin": "7A", "layers": [1, 2]}),
        ("via", {"kind": "via", "component": "", "pin": "", "layers": [1, 2]}),
        ("pour", {"kind": "pour", "component": "", "pin": "", "layers": [1]}),
    ],
)
def test_identity_comes_from_geometry_not_labels(kind, expected, monkeypatch):
    """A deliberately false label cannot affect the structured identity."""
    monkeypatch.setattr(measure, "_describe", lambda *args: "unrelated label")
    result = net_clearance(_board_for(kind), "A", "B", same_layer_only=True)
    assert result is not None
    assert result.element_a == result.element_b == "unrelated label"
    assert result.element_a_detail == expected
    assert result.element_b_detail == {
        "kind": "track", "component": "", "pin": "", "layers": [1],
    }
    assert result.shared_layer_ids == [1]
    measurement = _clearance_measurement(result)
    assert measurement["element_a_detail"] == expected
    assert measurement["shared_layer_ids"] == [1]


def test_unclassified_pour_layer_is_empty_not_the_internal_sentinel():
    points = [Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)]
    board = BoardGeometry(
        layers=LAYERS,
        tracks=[_reference_track()],
        pours=[PourShape("p", net="A", layer_id=None, kind="pour", points=points)],
    )
    result = net_clearance(board, "A", "B")
    assert result is not None
    assert result.element_a_detail == {
        "kind": "pour", "component": "", "pin": "", "layers": [],
    }
    assert "-1" not in json.dumps(_clearance_measurement(result))
    assert _clearance_measurement(result)["shared_layer_ids"] == []


def test_cross_layer_projection_is_not_written_as_a_same_layer_pair():
    board = BoardGeometry(
        layers=LAYERS,
        tracks=[
            TrackSegment("a", net="A", layer_id=1, start=Point(0, 0), end=Point(10, 0), width=2),
            _reference_track(layer=2),
        ],
    )
    assert net_clearance(board, "A", "B", same_layer_only=True) is None
    projected = net_clearance(board, "A", "B")
    assert projected is not None
    assert projected.element_a_detail["layers"] == [1]
    assert projected.element_b_detail["layers"] == [2]
    measurement = _clearance_measurement(projected)
    assert measurement["shared_layer_ids"] == []
    assert measurement["element_a_detail"]["layers"] == [1]
    assert measurement["element_b_detail"]["layers"] == [2]


def test_voltage_spacing_message_and_severity_are_unchanged():
    board = _two_net_board(
        lv_track_y=11.0, lv_track_width=10.0,
        lv_track_x=(-100.0, 400.0), pad_x=(-2000.0, 3000.0),
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")]),
            _component("J2", [Pin("1", "1", "LV"), Pin("2", "2", "GND")]),
        ]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "24V"}),
            IntentRail(net="LV", slots={"voltage": "5V"}),
        ]),
    )
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN"
    assert finding.message == (
        "net 'HV' (24 V) and net 'LV' (5 V) are 19 V apart: "
        "IPC-2221 (B2, uncoated) gives 4.0 mil, and the measured gap is 1.0 mil "
        "between track hv-1 on layer 1 and track lv-1 on layer 1"
    )


def _new_measurement() -> dict:
    return {
        "kind": "clearance", "value": 1.0, "unit": "mil",
        "element_a": "old label A", "element_b": "old label B",
        "component_a": "U1", "component_b": "", "within_one_footprint": False,
        "element_a_detail": {"kind": "pad", "component": "U1", "pin": "2", "layers": [1, 2]},
        "element_b_detail": {"kind": "track", "component": "", "pin": "", "layers": [1]},
        "shared_layer_ids": [1],
    }


def test_schema_accepts_new_identity_and_old_reports_without_it():
    assert SCHEMA["properties"]["schema"]["const"] == "boardwise.checkup/7"
    assert validate(OLD_REPORT, SCHEMA) == []
    report = deepcopy(OLD_REPORT)
    report["findings"][0]["rule_id"] = "pcb-voltage-spacing"
    report["findings"][0]["target"]["measurement"] = _new_measurement()
    assert validate(report, SCHEMA) == []

    # Every additive key may be absent; absence is not a claim of no element.
    measurement = report["findings"][0]["target"]["measurement"]
    for key in ("element_a_detail", "element_b_detail", "shared_layer_ids"):
        measurement.pop(key)
        assert validate(report, SCHEMA) == []


def test_schema_rejects_partial_identity_and_internal_layer_sentinel():
    report = deepcopy(OLD_REPORT)
    report["findings"][0]["target"]["measurement"] = _new_measurement()
    detail = report["findings"][0]["target"]["measurement"]["element_a_detail"]
    del detail["pin"]
    assert validate(report, SCHEMA)
    detail["pin"] = "2"
    detail["layers"] = [-1]
    assert validate(report, SCHEMA)
