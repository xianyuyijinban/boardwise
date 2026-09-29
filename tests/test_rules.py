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
        # 071 §2: the trade's mid-letter notation, which the board side could not
        # read at all before -- a rule handed an unreadable value skips the part
        # entirely, which is worse than a miss (issue #23).
        ("4K7", 4700.0),
        ("4k7", 4700.0),
        ("1K0", 1000.0),
        ("2M2", 2.2e6),
        ("100R", 100.0),
        ("47R", 47.0),
        ("22R", 22.0),
        ("10R", 10.0),
        ("4K7Ω", 4700.0),
        # The reverse example 071 called out: `0R5` is the *board* grammar's
        # (`R` as the decimal point, inherited from connectivity), and that branch
        # is tried first, so this value keeps the 0.5 it always had. The MPN-side
        # reader still refuses it (a bare `0` mantissa is not a value).
        ("0R5", 0.5),
        # `4.7kΩ` is the board grammar's 4700 and must not go through the
        # mid-letter scan, which would read the `7K` after the dot as 7000.
        ("4.7kΩ", 4700.0),
        # `R47` = 0.47 Ω is the board grammar's too (a leading `R` means 0.xxx),
        # while the MPN side refuses the same spelling: inside a part number a
        # leading letter with no digit run in front of it is a series name (071
        # §4). One grammar, two questions -- "what does this board declare" vs
        # "what does this part number say".
        ("R47", 0.47),
    ],
)
def test_parse_resistance_ohms(text, ohms):
    assert parse_resistance_ohms(text) == pytest.approx(ohms)


@pytest.mark.parametrize("text", ["", "  ", "abc", "n/a"])
def test_parse_resistance_ohms_rejects_garbage(text):
    assert parse_resistance_ohms(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "10MF",   # a millifarad capacitor, not `10M`: the notation must span it
        "1MF",
        "4K7 1%",  # a tolerance is not part of the value field
        "0K1",     # no mantissa
        "R", "K", "M",  # a letter alone states nothing
        "K47", "M22",  # a letter with no digit run in front of it states nothing
    ],
)
def test_the_mid_letter_reading_must_span_the_whole_value_field(text):
    """071 §2: the Value field *is* the value, so the notation has to cover it.

    The MPN reader hands back every reading a vendor field could be (``074K7``),
    because a part number carries prefixes; a board value carries none, and
    ``10MF`` is a millifarad capacitor rather than ``10M`` = 10 MΩ — which is
    what `_kind_of` would otherwise call a resistor (the value-unit inference
    asks the resistance parser first).

    ``K47``/``M22`` are the empty-run guard's own witnesses on this side: with no
    digit run in front of the letter there is no mantissa, and the board grammar
    (which reads ``R47`` as 0.47 Ω) does not read a leading ``K``/``M`` that way
    at all.
    """
    assert parse_resistance_ohms(text) is None


def test_one_ohm_parser_reads_the_board_and_the_mpn():
    """071 §2, the repository's "one verdict, one implementation" rule.

    The board-value parser and the MPN decoder used to read the mid-letter
    notation differently (one knew it, the other did not), so the two sides of
    one comparison disagreed about what the same spelling meant. Now there is one
    implementation in `rules/values.py` and `connectivity` re-exports it, which
    is what these two identities pin.
    """
    from boardwise.rules import connectivity, params, values

    assert connectivity.parse_resistance_ohms is not values.parse_resistance_ohms
    for text in ("4K7", "4.7kΩ", "0R01", "10mΩ", "1MΩ", "470"):
        assert connectivity.parse_resistance_ohms(text) == values.parse_resistance_ohms(text)
        assert params.parse_resistance_ohms(text) == values.parse_resistance_ohms(text)
    # The MPN side keeps its own entry point (per-kind: only a known resistor may
    # ask it), and it reads the same notation through the same scan.
    assert values.mpn_resistance_readings("4K7") == [(4700.0, "4K7")]
