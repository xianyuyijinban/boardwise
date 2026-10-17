"""516 A1: the same-potential spacing exemption is narrowed to 「one node」.

岳 2026-10-17 裁定: ``pcb-voltage-spacing`` exempted **every** pair whose two nets
were *declared* at the same voltage, which on 实板 A swallowed the whole
high-side family — ``HV`` and ``U``/``V``/``W``/``ACL`` are all declared 311 V, so
none of their pairs was ever measured, and a 62.99 mil ``HV``↔``U`` gap that
IPC-2221 wants at 100 mil disappeared without a word.

The rule now exempts a pair only when the two nets are **one node**: both
grounds, or the same potential **and** copper that geometrically coincides. Any
other nominally-equal pair is judged by the **swing bound** ``max(|a|, |b|)`` —
two switching-phase lines at a nominal 311 V can differ by 311 V instantaneously
(one at 0, the other at 311), and ``required_spacing_mil(0.0) = 4 mil`` was the
wrong quantity, not merely a lenient one.

The geometry below is axis-aligned pads, so every distance is a subtraction: two
40 mil pads at ``x = 0`` and ``x = 100`` have a 60 mil edge gap.
"""

from __future__ import annotations

from boardwise.core.designintent import DesignIntent, IntentRail
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.ipc import VoltageSpacing, required_spacing_mil

LAYERS = {
    1: LayerInfo(layer_id=1, name="Top Layer", layer_type="TOP"),
    2: LayerInfo(layer_id=2, name="Bottom Layer", layer_type="BOTTOM"),
}


def _pad(component: str, pin: str, *, x: float, net: str, layer_id: int = 1) -> PadGeometry:
    """One axis-aligned 40x40 pad, so a gap is ``|x1 - x2| - 40``."""
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        footprint_layer_id=layer_id,
        x=x,
        y=0.0,
        width=40.0,
        height=40.0,
        shape="RECT",
        angle=0.0,
    )


def _board(pads: list[PadGeometry]) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        layers=dict(LAYERS),
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=0.0, y=0.0, layer_id=1)
            for d in sorted({pad.component for pad in pads})
        ],
        pads=list(pads),
        tracks=[],
    )


def _model(rows: list[tuple[str, list[str]]]) -> DesignModel:
    model = DesignModel()
    nets: dict[str, Net] = {}
    for designator, pin_nets in rows:
        pins = []
        for index, net in enumerate(pin_nets, start=1):
            pins.append(Pin(str(index), str(index), net))
            nets.setdefault(net, Net(name=net)).pins.append((designator, str(index)))
        model.components[designator] = Component(
            uid=f"u-{designator}", designator=designator, pins=pins
        )
    model.nets = nets
    return model


def _ctx(
    board: BoardGeometry,
    model: DesignModel | None = None,
    intent: DesignIntent | None = None,
) -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title="SYNTH", model=model, intent=intent, module_of={}
    )


def _contract(*, rails: list[IntentRail] = ()) -> DesignIntent:
    return DesignIntent(signals=[], rails=list(rails))


def test_two_nets_declared_at_311_v_are_measured_by_the_swing_bound():
    """The 实板 A case, in miniature: two 311 V nets 60 mil apart → WARN at 100.

    ``HV`` and ``U`` are both declared 311 V, which used to be the exemption.
    The swing between two phase lines at a nominal 311 V is 311 V, and
    ``required_spacing_mil(311.0)`` is **100.0 mil** — so a 60 mil gap is a real
    WARN that the old equality test removed before anyone measured it.
    """
    board = _board([_pad("J1", "1", x=0.0, net="HV"), _pad("J2", "1", x=100.0, net="U")])
    ctx = _ctx(
        board,
        _model([("J1", ["HV"]), ("J2", ["U"])]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "311V"}),
            IntentRail(net="U", slots={"voltage": "311V"}),
        ]),
    )
    assert required_spacing_mil(311.0) == 100.0
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1, [f.message for f in findings]
    finding = findings[0]
    assert finding.rule_id == "pcb-voltage-spacing"
    assert finding.severity == "WARN"
    assert finding.target.net_refs == ["HV", "U"]
    assert finding.target.measurement["value"] == 60.0
    assert "share a nominal potential" in finding.message
    assert "311" in finding.message
    assert "100.0 mil" in finding.message
    assert "bound max(|311|,|311|) = 311 V" in finding.message


def test_two_equal_nets_with_room_to_spare_stay_silent():
    """The swing bound is not a noise generator: 5 V against 5 V at 60 mil passes.

    ``required_spacing_mil(5.0)`` is 4 mil, and the pads are 60 mil apart, so two
    5 V rails beside each other are still silence — the fix only moves rows whose
    gap is genuinely under the band the swing bound names.
    """
    board = _board([
        _pad("J1", "1", x=0.0, net="RAIL_A"),
        _pad("J2", "1", x=100.0, net="RAIL_B"),
    ])
    ctx = _ctx(
        board,
        _model([("J1", ["RAIL_A"]), ("J2", ["RAIL_B"])]),
        _contract(rails=[
            IntentRail(net="RAIL_A", slots={"voltage": "5V"}),
            IntentRail(net="RAIL_B", slots={"voltage": "5V"}),
        ]),
    )
    assert required_spacing_mil(5.0) == 4.0
    assert VoltageSpacing().check(ctx) == []


def test_two_grounds_are_still_exempt():
    """Both grounds remain one node — 岳裁定 4's ``GND``/``PGND`` case, unchanged.

    Two pads 42 mil apart (a 2.0 mil gap, **not** overlapping) is the case that
    makes the clause load-bearing: 2.0 mil is under the 4 mil the 0–15 V band
    allows, so without 「two grounds are one node」 this pair would be a WARN. The
    coincidence clause cannot rescue it — the copper does not touch — and the
    swing bound is 0 V for two grounds.
    """
    from boardwise.core.model import is_ground_net

    assert is_ground_net("GND") and is_ground_net("PGND")
    board = _board([_pad("G1", "1", x=0.0, net="GND"), _pad("G2", "1", x=42.0, net="PGND")])
    ctx = _ctx(board, _model([("G1", ["GND"]), ("G2", ["PGND"])]), None)
    assert VoltageSpacing().check(ctx) == []


def test_two_names_the_design_ties_are_exempt_even_at_one_potential():
    """Same potential **and** coincident copper → one node, however they are named.

    Two 5 V names whose pads sit on top of each other are one conductor the
    design joined on purpose (the generalised ``GND``/``PGND`` story): the
    overlap clause exempts them at a same potential.
    """
    board = _board([
        _pad("J1", "1", x=0.0, net="RAIL_A"),
        _pad("J2", "1", x=0.0, net="RAIL_B"),
    ])
    ctx = _ctx(
        board,
        _model([("J1", ["RAIL_A"]), ("J2", ["RAIL_B"])]),
        _contract(rails=[
            IntentRail(net="RAIL_A", slots={"voltage": "5V"}),
            IntentRail(net="RAIL_B", slots={"voltage": "5V"}),
        ]),
    )
    assert VoltageSpacing().check(ctx) == []


def test_different_voltage_copper_that_coincides_is_a_short_not_an_exemption():
    """The load-bearing half of the clause: overlap alone is **not** an exemption.

    Two **different**-voltage nets whose copper overlaps are a short, not a
    single-point join, and the rule must still say so — 126c pins the same fact
    on a ``+5V``/``GND`` pair at 0.0 mil. Reading the overlap clause as bare
    geometry would swallow exactly the class of silence this fix removes.
    """
    board = _board([
        _pad("J1", "1", x=0.0, net="RAIL_A"),
        _pad("J2", "1", x=0.0, net="RAIL_B"),
    ])
    ctx = _ctx(
        board,
        _model([("J1", ["RAIL_A"]), ("J2", ["RAIL_B"])]),
        _contract(rails=[
            IntentRail(net="RAIL_A", slots={"voltage": "5V"}),
            IntentRail(net="RAIL_B", slots={"voltage": "12V"}),
        ]),
    )
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1, [f.message for f in findings]
    assert findings[0].severity == "WARN"
    assert "short" in findings[0].message
    assert "7 V apart" in findings[0].message
