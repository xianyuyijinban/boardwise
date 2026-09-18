"""Tests for the 006b revision-4 identity-aware comparison (F4).

Round 4's USB1 "28 differences" were an addressing artifact: the golden pin
numbers (``1..14``) no longer pointed at the placed part's pins (``A1B12``,
``B5``…), so every pin compared unequal for a reason that had nothing to do
with the drawing. ``compare_models(..., pin_maps=...)`` closes that gap by
translating the *addressing* through the pin map, while leaving the *verdict*
untouched — a genuinely disconnected pin must still be reported.

These tests use small, hand-built models so the pin-level contract is
unambiguous; the golden fixtures carry the same behaviour end to end.
"""

from __future__ import annotations

from boardwise.core.compare import compare_models
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.verify import PinMap, build_pin_map, MATCH_DRIFTED


def _model(designator: str, pins: list[tuple[str, str, str]], nets: dict) -> DesignModel:
    """A one-part model: pins as (number, name, net)."""
    model = DesignModel()
    model.components[designator] = Component(
        uid=designator, designator=designator,
        pins=[Pin(number=n, name=nm, net=net or None) for n, nm, net in pins],
    )
    for name, members in nets.items():
        model.nets[name] = Net(name=name, pins=list(members))
    return model


#: The golden part: pins 1..4, connected 1->A, 2->A, 3->B, 4->(open).
GOLDEN = _model(
    "J1",
    [("1", "GND", "A"), ("2", "GND", "A"), ("3", "VBUS", "B"), ("4", "NC", "")],
    {"A": [("J1", "1"), ("J1", "2")], "B": [("J1", "3")]},
)

#: The same part after the library renamed every pin to a pad name. The
#: signals are identical; only the addressing moved.
PLACED = _model(
    "J1",
    [("P1", "GND", "A"), ("P2", "GND", "A"), ("P3", "VBUS", "B"), ("P4", "NC", "")],
    {"A": [("J1", "P1"), ("J1", "P2")], "B": [("J1", "P3")]},
)


def _map_for(golden, placed):
    return {"J1": build_pin_map("J1", golden.components["J1"], placed.components["J1"])}


def test_drifted_map_is_built_by_name():
    pin_map = _map_for(GOLDEN, PLACED)["J1"]
    assert pin_map.kind == MATCH_DRIFTED
    assert pin_map.ok
    assert pin_map.remap("3") == "P3"


def test_without_a_map_the_drift_shows_as_phantom_differences():
    """The trap: numbers address numbers, so every pin looks wrong."""
    report = compare_models(GOLDEN, PLACED)
    # 4 pins differ in net, plus every placed pin reads as "extra".
    assert len(report.pin_differences) >= 4
    subjects = {d.subject for d in report.pin_differences}
    assert "J1.1" in subjects and "J1.3" in subjects


def test_with_a_map_the_drift_disappears():
    """F4: translate the addressing, and the same board compares clean."""
    report = compare_models(GOLDEN, PLACED, pin_maps=_map_for(GOLDEN, PLACED))
    assert not report.pin_differences, [d.render() for d in report.pin_differences]
    assert not report.net_differences, [d.render() for d in report.net_differences]


def test_a_real_disconnection_survives_the_map():
    """The map translates addressing; it never hides a lost connection."""
    broken = _model(
        "J1",
        [("P1", "GND", "A"), ("P2", "GND", "A"), ("P3", "VBUS", ""), ("P4", "NC", "")],
        {"A": [("J1", "P1"), ("J1", "P2")]},
    )
    report = compare_models(GOLDEN, broken, pin_maps=_map_for(GOLDEN, broken))
    assert [d.subject for d in report.pin_differences] == ["J1.3"]
    assert report.pin_differences[0].golden == "B"


def test_exact_part_is_unaffected_by_a_present_map():
    """A map that is exact must behave exactly like no map at all."""
    pin_map = build_pin_map("J1", GOLDEN.components["J1"], GOLDEN.components["J1"])
    with_map = compare_models(GOLDEN, GOLDEN, pin_maps={"J1": pin_map})
    without = compare_models(GOLDEN, GOLDEN)
    assert with_map.total == without.total == 0


def test_map_is_only_consulted_for_drifted_parts():
    """An exact map on one part must not perturb another part's comparison."""
    golden = GOLDEN
    placed = _model(
        "J1",
        [("1", "GND", "A"), ("2", "GND", "A"), ("3", "VBUS", "WRONG"), ("4", "NC", "")],
        {"A": [("J1", "1"), ("J1", "2")]},
    )
    exact = build_pin_map("J1", golden.components["J1"], placed.components["J1"])
    assert exact.kind != MATCH_DRIFTED  # numbers line up
    report = compare_models(golden, placed, pin_maps={"J1": exact})
    # The wrong net is still caught; the addressing is not re-interpreted.
    assert [d.subject for d in report.pin_differences] == ["J1.3"]


def test_a_part_without_a_map_keeps_legacy_behaviour():
    report = compare_models(GOLDEN, PLACED, pin_maps={})
    legacy = compare_models(GOLDEN, PLACED)
    assert report.total == legacy.total


def test_empty_pin_map_object_is_safe():
    assert compare_models(GOLDEN, PLACED, pin_maps=None).total == \
        compare_models(GOLDEN, PLACED).total
