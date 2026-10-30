"""High-voltage net identity (task A, 2026-10-30): the 310 V rail reads, or says UNKNOWN.

**What the user reported** (oracle, not reproduced here): on their own 310 V board
the ``V_310V`` rail produced **zero** output, and hand-measured copper between
that rail and seven other nets sat at **43.0–55.6 mil** where IPC-2221 column B2
wants **100 mil** for a 301–500 V pair. This repository holds no anonymised
fixture of that board, so nothing below claims to have re-measured those seven
nets. The board here is **synthetic**: a net literally named ``V_310V``, one
ground net, and a 43.0 mil same-layer track pair — the geometry the report gives,
rebuilt from the arithmetic so the number can be checked by hand.

The three defects this batch closes, each pinned below:

1. ``parse_voltage_volts`` could not read the spellings that rail is named with —
   ``V_310V``, ``V310``, ``DC310``, ``310VDC`` — nor the digital rail's
   ``3V3D``. The contract's ``rails[].voltage`` therefore came back
   「not a voltage this build can read」 and the net was silently unpriced.
2. ``power_domains.voltage_from_net_name`` — the reader the **architecture**
   enumeration actually uses — had the same hole, so even a schematic whose net
   name states its voltage could not price it.
3. ``architecture._SUPPLY_PIN`` did not know the power-stage pin names
   (``P``/``+``/``-``/``DRAIN``/``SW``/``PVIN``/``HV``), so a net touched only by
   a rectifier bridge or an IPM had **no evidence at all** and never became a
   rail — and a net that is not a rail is a net ``pcb-voltage-spacing`` says
   nothing about, which reads as a pass.

Section 5 of the task book is honoured by construction: ``rules/pcb/ipc.py`` is
untouched, so the UNKNOWN population is the one it already had, reached now
because the net is finally a rail.
"""

from __future__ import annotations

import pytest

from boardwise.core.architecture import generate_architecture
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    TrackSegment,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.power_domains import voltage_from_net_name
from boardwise.core.values import parse_voltage_volts
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.ipc import VoltageSpacing

LAYERS = {
    1: LayerInfo(layer_id=1, name="Top Layer", layer_type="TOP"),
    2: LayerInfo(layer_id=2, name="Bottom Layer", layer_type="BOTTOM"),
}


# ---------------------------------------------------------------------------
# 1. the parser — the spellings a 310 V rail is actually named with
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "volts"),
    [
        ("V_310V", 310.0),  # the user's own net name
        ("V310", 310.0),
        ("V310V", 310.0),
        ("DC310", 310.0),  # the DC-marked prefix
        ("DC_310", 310.0),
        ("DC310V", 310.0),
        ("310VDC", 310.0),  # ... and the DC-marked suffix
        ("310 VDC", 310.0),
        ("3V3D", 3.3),  # mid-letter + the digital rail's domain letter
        ("+V_310V", 310.0),
    ],
)
def test_the_high_voltage_spellings_read_in_volts(text, volts):
    assert parse_voltage_volts(text) == pytest.approx(volts)


@pytest.mark.parametrize(
    ("text", "volts"),
    [
        ("3V3", 3.3),
        ("1V8", 1.8),
        ("3.3V", 3.3),
        ("3.30V", 3.3),
        ("3.3 V", 3.3),
        ("5V", 5.0),
        ("3V", 3.0),
        ("5V0", 5.0),
        ("310", 310.0),
        ("+310V", 310.0),
        ("+3.3", 3.3),
        ("-12V", -12.0),
        ("0.05", 0.05),
    ],
)
def test_every_earlier_reading_keeps_its_exact_value(text, volts):
    """The new branches are **additive**: no string one of them reads changes the
    number an older branch read, and no older reading is refused."""
    assert parse_voltage_volts(text) == pytest.approx(volts)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "V",
        "V3",  # the mid-letter form with an empty mantissa: still refused
        "0V5",
        "3V3V",  # a doubled unit
        "5V3V",
        "5V 1A",  # two tokens
        "3V123",
        "V030",  # leading zeros are not significant figures
        "DC030",
        "310V_BUS",  # a name with a suffix is not the field itself
        "V_310V_BUS",
        "HV+",
        "net7",
        "DC",
        "VDC",
        "1" * 100 + "V",
        None,
    ],
)
def test_a_string_this_cannot_state_is_still_refused(text):
    """Strict ``fullmatch``: no arbitrary prefix or suffix is read. ``V3`` in
    particular stays refused — the leading-``V`` branch demands either the unit
    marker behind the number or three bare digits, so the old negative did not
    quietly become a voltage."""
    assert parse_voltage_volts(text) is None


def test_one_string_is_read_by_exactly_one_branch():
    """The alternation's own property: ``3V3D`` is the mid-letter branch's,
    ``310VDC`` the suffix branch's, ``V310`` the leading-``V`` branch's, and none
    of the four overlaps another (each value below is checked against the
    grammar's own arithmetic, not against a normalisation loop)."""
    assert parse_voltage_volts("3V3D") == pytest.approx(3.3)
    assert parse_voltage_volts("3V") == pytest.approx(3.0)
    assert parse_voltage_volts("DC3V3") is None  # not a DC-marked *number*
    assert parse_voltage_volts("V3.3") is None  # the bare half needs 3 digits


def test_a_rail_written_two_ways_is_one_rail_at_the_power_tree_gate(tmp_path):
    """``5V`` and ``5VDC`` were both unreadable before this batch, so the gate
    compared them as strings and reported a VIOLATION. They are the same rail
    written the two ways a person writes it, and the gate now says so."""
    from test_083_value_unification import _gate_power_tree, _power_spec

    spec = _power_spec(
        tmp_path,
        {"direction": "source", "voltage": "5V"},
        {"direction": "sink", "voltage": "5VDC"},
    )
    assert _gate_power_tree(spec).status == "pass"


# ---------------------------------------------------------------------------
# 2. the whitelist the architecture enumeration actually uses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "volts"),
    [
        ("V_310V", 310.0),
        ("V310", 310.0),
        ("DC310", 310.0),
        ("310VDC", 310.0),
        ("3V3D", 3.3),
        ("+5V", 5.0),
        ("5V0", 5.0),
        ("3V3", 3.3),
        ("1V8", 1.8),
    ],
)
def test_the_net_name_whitelist_prices_the_same_spellings(name, volts):
    assert voltage_from_net_name(name) == (volts, f"net name {name!r}")


@pytest.mark.parametrize(
    "name",
    [
        "VCC",  # a name that reads like a rail is not a declaration
        "VBUS",
        "VEE",
        "NET7",
        "V3",  # still unknown: no magnitude behind the marker
        "V030",
        "DC030",
        "310V_BUS",  # this reader prices rail *names*, not substrings
        "HV+",
        "HV_RET",
        "+",
        "+12V34",
        "",
    ],
)
def test_the_whitelist_did_not_widen_into_a_guesser(name):
    """The whitelist is **unconditional**: a net name it does not list is None,
    which is what keeps ``NET7``-style names out. The new forms are entries in
    it, not a fallback to a bare-number reader."""
    assert voltage_from_net_name(name) is None


# ---------------------------------------------------------------------------
# 3. the architecture enumeration — rails, and the power pins that make one
# ---------------------------------------------------------------------------


def _component(designator: str, pins: list[Pin]) -> Component:
    return Component(uid=f"u-{designator}", designator=designator, pins=list(pins))


def _model(components: list[Component]) -> DesignModel:
    model = DesignModel(components={c.designator: c for c in components})
    nets: dict[str, Net] = {}
    for component in components:
        for pin in component.pins:
            if not pin.net:
                continue
            nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                (component.designator, pin.number)
            )
    model.nets = nets
    return model


def _rail_voltages(model: DesignModel) -> dict[str, float | None]:
    result = generate_architecture(model, library=None)
    return {
        rail["net"]: rail["voltage"]
        for rail in result.section["chains"]["rails"]
    }


def test_a_net_named_v_310v_is_a_rail_at_310_v():
    model = _model([_component("J1", [Pin("1", "1", "V_310V"), Pin("2", "2", "GND")])])
    assert _rail_voltages(model).get("V_310V") == pytest.approx(310.0)


@pytest.mark.parametrize(
    "net", ["V310", "DC310", "310VDC", "V_310V"],
)
def test_every_310_v_spelling_prices_the_rail(net):
    model = _model([_component("J1", [Pin("1", "1", net)])])
    assert _rail_voltages(model).get(net) == pytest.approx(310.0)


def test_the_digital_rail_3v3d_is_3_3_v_and_vcc_stays_unknown():
    model = _model([
        _component("U1", [Pin("1", "VDD", "3V3D"), Pin("2", "VCC", "VCC")]),
    ])
    rails = _rail_voltages(model)
    assert rails["3V3D"] == pytest.approx(3.3)
    assert rails["VCC"] is None  # a rail the name cannot price: UNKNOWN, not zero


@pytest.mark.parametrize("pin_name", ["P", "+", "-", "DRAIN", "SW", "PVIN", "HV"])
def test_a_power_stage_pin_makes_its_net_a_rail(pin_name):
    """Before this batch a rectifier bridge or an IPM pin named ``P``/``+``/``DRAIN``
    /``SW``/``PVIN``/``HV`` was not evidence of anything, so its net never entered
    the power tree — and a net outside the power tree gets no spacing row at all,
    which is exactly the silence the user reported as 「零输出」."""
    model = _model([
        _component("BR1", [Pin("1", pin_name, "BUS_X"), Pin("2", "1", "GND")]),
    ])
    rails = _rail_voltages(model)
    assert "BUS_X" in rails
    assert rails["BUS_X"] is None  # a rail, unpriced by name: UNKNOWN, never a guess


def test_return_pins_and_signal_nets_are_not_swept_into_the_power_tree():
    """The other direction of the same test: ``PGND1`` is still a return, not a
    supply, and a plain signal net is not a rail. A rail inventory that grows by
    accident is a rule that talks about nets it has nothing to say about."""
    model = _model([
        _component("DRV1", [
            Pin("1", "PGND1", "RET_NET"),  # all-return net: a reference
            Pin("2", "CANH", "CAN_H"),  # a signal pin
            Pin("3", "PA7", "U+"),
        ]),
    ])
    rails = _rail_voltages(model)
    assert "RET_NET" not in rails
    assert "CAN_H" not in rails
    assert "U+" not in rails


# ---------------------------------------------------------------------------
# 4. end-to-end: the 43.0 mil pair, and the UNKNOWN that replaces silence
# ---------------------------------------------------------------------------


def _pad(component: str, pin: str, *, x: float, y: float, net: str) -> PadGeometry:
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        footprint_layer_id=1,
        x=x,
        y=y,
        width=40.0,
        height=40.0,
        shape="RECT",
        angle=0.0,
    )


def _track(ident: str, *, x1: float, y1: float, x2: float, y2: float, net: str) -> TrackSegment:
    return TrackSegment(
        id=ident, net=net, layer_id=1, start=Point(x1, y1), end=Point(x2, y2), width=10.0,
    )


def _hv_board(gap_mil: float = 43.0) -> BoardGeometry:
    """A 310 V track on ``y = 0`` and a GND track on ``y = gap + 10``.

    Both 10 mil capsules, so the edge-to-edge gap is exactly ``gap_mil`` — two
    10 mil tracks on ``y = 0`` and ``y = 53`` are ``(53 - 5) - 5 = 43.0`` apart.
    The pads are parked 2000 mil up the board so they cannot be the closest pair.
    """
    pads = [
        _pad("J1", "1", x=0.0, y=2000.0, net="V_310V"),
        _pad("J2", "1", x=3000.0, y=2000.0, net="GND"),
    ]
    tracks = [
        _track("hv-1", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0, net="V_310V"),
        _track("gnd-1", x1=-100.0, y1=gap_mil + 10.0, x2=400.0, y2=gap_mil + 10.0,
               net="GND"),
    ]
    return BoardGeometry(
        source="synthetic",
        name="SYNTH-HV",
        layers=dict(LAYERS),
        components=[
            ComponentPlacement(id="c-J1", designator="J1", x=0.0, y=2000.0, layer_id=1),
            ComponentPlacement(id="c-J2", designator="J2", x=3000.0, y=2000.0, layer_id=1),
        ],
        pads=pads,
        tracks=tracks,
    )


def _hv_model(extra: list[Component] | None = None) -> DesignModel:
    """The schematic side: a connector whose pins are on the rail and on ground.

    The net name is the **only** voltage evidence — no contract is written in
    this test, so the 310 V has to come from the architecture enumeration, which
    is the path the user's board failed on.
    """
    return _model([
        _component("J1", [Pin("1", "1", "V_310V")]),
        _component("J2", [Pin("1", "1", "GND")]),
        *(extra or []),
    ])


def _ctx(board: BoardGeometry, model: DesignModel | None) -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title="SYNTH-HV", model=model, intent=None, module_of={},
    )


def test_the_43_mil_pair_between_310_v_and_ground_is_a_warn_at_100_mil():
    """The user's reading, rebuilt synthetically: 43.0 mil of same-layer copper
    between the 310 V rail and ground. The band is the 301–500 V row of
    :data:`~boardwise.rules.pcb.ipc.VOLTAGE_SPACING_MIL`, i.e. **100 mil**, and
    the row is a WARN whose message carries all three numbers (the voltage, the
    requirement, the measurement)."""
    findings = VoltageSpacing().check(_ctx(_hv_board(), _hv_model()))
    (warn,) = findings
    assert warn.rule_id == "pcb-voltage-spacing"
    assert warn.severity == "WARN"
    # pairs are walked in sorted name order, so GND comes first here
    assert "net 'GND' (0 V) and net 'V_310V' (310 V)" in warn.message
    assert "are 310 V apart" in warn.message
    assert "gives 100.0 mil" in warn.message
    assert "measured gap is 43.0 mil" in warn.message
    assert "track hv-1 on layer 1" in warn.message
    assert "track gnd-1 on layer 1" in warn.message
    assert warn.target.net_refs == ["GND", "V_310V"]


def test_the_warn_keeps_the_87d_measurement_detail():
    """#87④'s structured element identity is **not** a casualty of this batch: the
    WARN's ``target.measurement`` still carries ``element_a_detail`` /
    ``element_b_detail`` / ``shared_layer_ids``, sourced from geometry."""
    findings = VoltageSpacing().check(_ctx(_hv_board(), _hv_model()))
    (warn,) = findings
    measurement = warn.target.measurement
    assert measurement is not None
    assert measurement["kind"] == "clearance"
    assert measurement["value"] == pytest.approx(43.0, abs=0.05)
    assert measurement["element_a_detail"] == {
        "kind": "track", "component": "", "pin": "", "layers": [1],
    }
    assert measurement["element_b_detail"] == {
        "kind": "track", "component": "", "pin": "", "layers": [1],
    }
    assert measurement["shared_layer_ids"] == [1]


def test_a_power_pin_only_rail_is_an_unknown_row_not_silence():
    """The half of the user's report that is not a spacing number: 「零输出」.

    A net that carries a bridge/IPM power pin but no stated voltage now enters
    the power tree, so ``pcb-voltage-spacing`` has to say something about it —
    an **INFO UNKNOWN** naming the net, which is a work order; the old behaviour
    was no row at all, which a reader takes as a pass. ``rules/pcb/ipc.py`` is
    untouched: this row is its existing UNKNOWN population, reached because the
    net is finally a rail.
    """
    model = _hv_model([
        _component("BR1", [Pin("1", "P", "BUS_P"), Pin("2", "-", "BUS_N")]),
        _component("J3", [Pin("1", "1", "BUS_P"), Pin("2", "1", "BUS_N")]),
    ])
    board = _hv_board()
    board = BoardGeometry(
        source=board.source,
        name=board.name,
        layers=board.layers,
        components=board.components,
        pads=board.pads,
        tracks=[
            *board.tracks,
            _track("p-1", x1=0.0, y1=-800.0, x2=40.0, y2=-800.0, net="BUS_P"),
            _track("n-1", x1=0.0, y1=-900.0, x2=40.0, y2=-900.0, net="BUS_N"),
        ],
    )
    findings = VoltageSpacing().check(_ctx(board, model))
    unknowns = {
        finding.target.net_refs[0]: finding
        for finding in findings
        if finding.severity == "INFO" and "no established voltage" in finding.message
    }
    assert set(unknowns) == {"BUS_P", "BUS_N"}
    assert "has no established voltage" in unknowns["BUS_P"].message


def test_a_plain_signal_net_gets_no_row_and_no_spacing_is_invented():
    """The counter-case that keeps the rule quiet: ``CAN_H`` is not a rail, so it
    is neither an UNKNOWN nor a pair — the width of the UNKNOWN population is the
    reason the first test could be written as an equality."""
    model = _hv_model([
        _component("U9", [Pin("1", "CANH", "CAN_H"), Pin("2", "CANL", "CAN_L")]),
    ])
    board = _hv_board()
    board = BoardGeometry(
        source=board.source,
        name=board.name,
        layers=board.layers,
        components=board.components,
        pads=board.pads,
        tracks=[
            *board.tracks,
            _track("can-1", x1=0.0, y1=-800.0, x2=40.0, y2=-800.0, net="CAN_H"),
            _track("can-2", x1=0.0, y1=-900.0, x2=40.0, y2=-900.0, net="CAN_L"),
        ],
    )
    findings = VoltageSpacing().check(_ctx(board, model))
    assert "CAN_H" not in {ref for finding in findings for ref in finding.target.net_refs}
    assert "CAN_L" not in {ref for finding in findings for ref in finding.target.net_refs}
