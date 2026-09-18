"""Rule tests: real fixture (assertions based on verified fixture facts)
plus small synthetic models for the negative paths the fixture lacks."""

from pathlib import Path

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.parsers.enet import parse_enet
from boardwise.rules.base import Finding
from boardwise.rules.connectivity import (
    CrystalLoadCaps,
    DecouplingPerIC,
    ShuntSenseLink,
    parse_resistance_ohms,
)

FIXTURE = Path(__file__).parent / "fixtures" / "board24v.enet"


@pytest.fixture(scope="module")
def fixture_model():
    return parse_enet(FIXTURE)


def make_model():
    """Tiny model builder: add_comp("C1", "100nF", [("1", "VCC"), ("2", "GND")])."""
    model = DesignModel()

    def add_comp(designator, value="", pins=()):
        comp = Component(uid=designator.lower(), designator=designator, value=value)
        comp.pins = [Pin(number=str(n), name=str(n), net=net) for n, net in pins]
        model.components[designator] = comp
        for pin in comp.pins:
            if pin.net is not None:
                net = model.nets.setdefault(pin.net, Net(name=pin.net))
                net.pins.append((designator, pin.number))
        return comp

    return model, add_comp


# --- Fixture facts (verified by direct inspection of board24v.enet) ---
# - U18 (DRV8350), U19/U21 (2x6 headers): every U* part shares a pin net
#   with a C* part -> decoupling rule finds nothing.
# - No X/Y designators and no MHz/KHz values -> crystal rule finds nothing.
# - R39/R40/R43 are 1mΩ shunts on (PGND, IA+/IB+/IC+); U19/U21 have pins on
#   both terminal nets of each shunt -> shunt rule finds nothing.


def test_decoupling_on_fixture(fixture_model):
    findings = DecouplingPerIC().check(fixture_model)
    assert isinstance(findings, list)
    assert findings == []


def test_xtal_on_fixture(fixture_model):
    findings = CrystalLoadCaps().check(fixture_model)
    assert findings == []


def test_shunt_on_fixture(fixture_model):
    findings = ShuntSenseLink().check(fixture_model)
    assert findings == []


# --- Negative paths on synthetic models ---


def test_decoupling_flags_ic_without_caps():
    model, add = make_model()
    add("U1", pins=[("1", "VCC"), ("2", "GND")])
    findings = DecouplingPerIC().check(model)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.rule_id == "decoupling-per-ic"
    assert f.severity == "WARN"
    assert "U1 pin1 @ VCC" in f.evidence

    add("C1", "100nF", [("1", "VCC"), ("2", "GND")])
    assert DecouplingPerIC().check(model) == []


def test_xtal_flags_missing_load_caps():
    model, add = make_model()
    add("X1", "8MHz", [("1", "XTAL_IN"), ("2", "XTAL_OUT")])
    findings = CrystalLoadCaps().check(model)
    assert len(findings) == 1
    assert findings[0].severity == "WARN"
    assert "XTAL_IN" in findings[0].message

    add("C1", "18pF", [("1", "XTAL_IN"), ("2", "GND")])
    add("C2", "18pF", [("1", "XTAL_OUT"), ("2", "GND")])
    assert CrystalLoadCaps().check(model) == []


def test_shunt_without_ic_link_is_info():
    model, add = make_model()
    add("R1", "10mΩ", [("1", "PGND"), ("2", "ISNS")])
    add("U1", pins=[("1", "VCC"), ("2", "GND")])
    findings = ShuntSenseLink().check(model)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "shunt-sense-link"
    assert f.severity == "INFO"
    assert "R1 pin2 @ ISNS" in f.evidence

    add("U2", pins=[("1", "ISNS"), ("2", "PGND")])
    assert ShuntSenseLink().check(model) == []


def test_zero_ohm_jumper_is_not_a_shunt():
    model, add = make_model()
    add("R1", "0Ω", [("1", "NETA"), ("2", "NETB")])
    assert ShuntSenseLink().check(model) == []


# --- Resistance value parser ---


@pytest.mark.parametrize(
    "text, ohms",
    [
        ("10mΩ", 0.01),
        ("1mΩ", 0.001),
        ("0.01", 0.01),
        ("0R01", 0.01),
        ("R010", 0.01),
        ("4R7", 4.7),
        ("10Ω", 10.0),
        ("10 ohm", 10.0),
        ("10kΩ", 10000.0),
        ("1MΩ", 1e6),
        ("0Ω", 0.0),
    ],
)
def test_parse_resistance_ohms(text, ohms):
    assert parse_resistance_ohms(text) == pytest.approx(ohms)


@pytest.mark.parametrize("text", ["", "  ", "abc", "n/a"])
def test_parse_resistance_ohms_rejects_garbage(text):
    assert parse_resistance_ohms(text) is None
