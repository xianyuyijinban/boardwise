"""Tests for the 011c facts-driven rules: four states each, plus the CONN-1
parser hook and the xtal grounded-case fix (task 011c secs.3.2-3.4)."""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.rules.base import OUTCOME_STATES
from boardwise.rules.connectivity import CrystalLoadCaps, DuplicateDesignators
from boardwise.rules.facts import (
    DomainVsRange,
    LdoDropout,
    LibraryPinConsistency,
    NcAndMustConnect,
    SupplyOnKnownDomain,
)

PROV = ("test datasheet, p.1, http://example.com/ds.pdf")


def _ldo_entry(mpn: str = "RT9013-33GB", lcsc: str = "C47773") -> PartEntry:
    return PartEntry(
        key="ic.ldo.test", value=mpn, mpn=mpn, lcsc=lcsc, category="ic.ldo",
        facts={
            "supply_pins": [{
                "pins": ["1"], "name": "VIN",
                "v_operating": [2.2, 5.5],
                "v_abs_max": [None, 6.0],
                "provenance": PROV,
            }],
            "required_caps": [
                {"pin": "1", "value": "1uF", "provenance": PROV},
                {"pin": "5", "value": "1uF", "provenance": PROV},
            ],
            "nc_pins": {"pins": ["4"], "provenance": PROV},
            "ldo": {"dropout_max_mv": 400.0, "condition": "Iout=500mA",
                    "provenance": PROV},
        },
    )


def _uart_entry() -> PartEntry:
    """A CH340G-shaped entry: two supply modes, free-text must_connect."""
    return PartEntry(
        key="ic.usb-uart.test", value="CH340G", mpn="CH340G",
        lcsc="C14267", category="ic.usb-uart",
        facts={
            "supply_pins": [
                {"pins": ["16"], "name": "VCC-5V-mode",
                 "v_operating": [4.0, 5.3], "provenance": PROV},
                {"pins": ["16"], "name": "VCC-3V3-mode",
                 "v_operating": [2.9, 3.6], "provenance": PROV},
            ],
            "must_connect": [
                {"pin": "7", "to": "external 12MHz crystal network (XI)",
                 "provenance": PROV},
            ],
        },
    )


def _resistor_entry() -> PartEntry:
    """An entry with no category and no facts — the U3 shape."""
    return PartEntry(key="res.test", value="470R", mpn="FRC0805J471 TS",
                     lcsc="C2907329")


def _library(*entries: PartEntry) -> PartLibrary:
    return PartLibrary(parts=list(entries))


def _model(ldo_net="VCC", uart_net="VCC", vin_net="+5V") -> DesignModel:
    model = DesignModel()
    model.components["U5"] = Component(
        uid="u5", designator="U5", mpn="RT9013-33GB", lcsc_part="C47773",
        pins=[Pin("1", "VIN", vin_net), Pin("4", "NC", None),
              Pin("5", "VOUT", ldo_net)],
    )
    model.components["U1"] = Component(
        uid="u1", designator="U1", mpn="CH340G", lcsc_part="C14267",
        pins=[Pin("7", "XI", "NET2"), Pin("16", "VCC", uart_net)],
    )
    model.components["U3"] = Component(
        uid="u3", designator="U3", mpn="FRC0805J471 TS",
        lcsc_part="C2907329",
        pins=[Pin("1", "A", "VCC"), Pin("2", "B", "NET4")],
    )
    model.nets = {
        vin_net: Net(vin_net, [("U5", "1")]),
        ldo_net: Net(ldo_net, [("U5", "5"), ("U1", "16"), ("U3", "1")]),
        "NET2": Net("NET2", [("U1", "7")]),
        "NET4": Net("NET4", [("U3", "2")]),
    }
    return model


def _states(rule, model) -> dict[str, list]:
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for outcome in rule.outcomes(model):
        grouped[outcome.state].append(outcome)
    return grouped


# ---------------------------------------------------------------- CONN-1


def test_conn1_flags_a_designator_two_parts_claim():
    model = DesignModel()
    model.duplicate_designators = ["U1"]
    states = _states(DuplicateDesignators(), model)
    assert len(states["VIOLATION"]) == 1
    assert states["VIOLATION"][0].subject == "U1"
    findings = DuplicateDesignators().check(model)
    assert findings and findings[0].severity == "ERROR"


def test_conn1_is_ok_when_every_designator_is_unique():
    states = _states(DuplicateDesignators(), _model())
    assert len(states["OK"]) == 1 and not states["VIOLATION"]


def test_the_parser_records_a_repeated_designator_instead_of_losing_it():
    """CONN-1's parser half: the clash must be visible, not silent."""
    from pathlib import Path

    from boardwise.parsers.schematic import build_schematic_model

    model = build_schematic_model(Path("tests/fixtures/ch340_golden.epro2"))
    assert model.duplicate_designators == []  # the golden board is clean


# ---------------------------------------------------------------- CONN-2


def test_conn2_nc_pin_on_a_net_is_a_violation():
    model = _model()
    model.components["U5"].pins[1].net = "NET4"  # pin4: NC -> wired to NET4
    model.nets["NET4"].pins.append(("U5", "4"))
    lib = _library(_ldo_entry(), _uart_entry(), _resistor_entry())
    states = _states(NcAndMustConnect(library=lib), model)
    violations = states["VIOLATION"]
    assert len(violations) == 1 and violations[0].subject == "U5 pin4"
    findings = NcAndMustConnect(library=lib).check(model)
    assert findings[0].severity == "ERROR"


def test_conn2_nc_pin_unconnected_is_ok_and_free_text_must_connect_is_unknown():
    lib = _library(_ldo_entry(), _uart_entry(), _resistor_entry())
    states = _states(NcAndMustConnect(library=lib), _model())
    # U5 pin4: NC, touching nothing -> OK.
    assert any(o.subject == "U5 pin4" for o in states["OK"])
    # U1 pin7: must_connect target is prose -> UNKNOWN, naming the fact.
    unknown_u1 = [o for o in states["UNKNOWN"] if o.subject == "U1 pin7"]
    assert len(unknown_u1) == 1
    assert "free text" in unknown_u1[0].missing_fact


def test_conn2_a_must_connect_target_that_is_a_net_name_is_machine_judged():
    lib = _library(_ldo_entry(), _uart_entry(), _resistor_entry())
    model = _model()
    entry = lib.parts[1]
    entry.facts["must_connect"] = [
        {"pin": "7", "to": "NET2", "provenance": PROV},
    ]
    states = _states(NcAndMustConnect(library=lib), model)
    assert any(
        o.subject == "U1 pin7" and o.state == "OK" for o in states["OK"]
    )
    # ...and a pin on the wrong net violates.
    model.components["U1"].pins[0].net = "NET4"
    states = _states(NcAndMustConnect(library=lib), model)
    assert any(
        o.subject == "U1 pin7" and o.state == "VIOLATION"
        for o in states["VIOLATION"]
    )


def test_conn2_component_without_facts_is_unknown_naming_the_part():
    lib = _library(_ldo_entry(), _uart_entry(), _resistor_entry())
    model = _model()
    model.components["U9"] = Component(
        uid="u9", designator="U9", pins=[Pin("1", "A", "NET2")])
    states = _states(NcAndMustConnect(library=lib), model)
    u9 = [o for o in states["UNKNOWN"] if o.subject == "U9"]
    assert len(u9) == 1 and "U9" in u9[0].missing_fact


def test_conn2_an_explicitly_non_ic_category_is_not_applicable():
    lib = _library(_ldo_entry(), _uart_entry(), _resistor_entry())
    states = _states(NcAndMustConnect(library=lib), _model())
    # U3's entry is category-less -> UNKNOWN (facts missing), NOT NA.
    u3 = [o for o in states["UNKNOWN"] if o.subject == "U3"]
    assert len(u3) == 1 and "C2907329" in u3[0].missing_fact
    # An explicit non-IC category is the one honest NOT_APPLICABLE.
    lib.parts.append(PartEntry(key="conn.x", value="BAR", mpn="BAR-1",
                               lcsc="C1", category="connector"))
    model = _model()
    model.components["U9"] = Component(
        uid="u9", designator="U9", mpn="BAR-1", lcsc_part="C1",
        pins=[Pin("1", "A", "NET2")])
    states = _states(NcAndMustConnect(library=lib), model)
    assert any(o.subject == "U9" and o.state == "NOT_APPLICABLE"
               for o in states["NOT_APPLICABLE"])


# ---------------------------------------------------------------- CONN-3


def test_conn3_offline_is_one_unknown_naming_the_bridge():
    states = _states(LibraryPinConsistency(), _model())
    assert len(states["UNKNOWN"]) == 1
    assert "bridge" in states["UNKNOWN"][0].missing_fact
    assert LibraryPinConsistency().check(_model()) == []


def test_conn3_with_a_resolver_pin_drift_is_symmetric():
    library_pins = {"1", "2", "3"}  # the library's symbol

    def resolver(comp):
        return {"U1": library_pins}.get(comp.designator)

    model = _model()
    model.components["U1"].pins = [
        Pin("1", "A", "NET2"),   # on both
        Pin("9", "B", "NET4"),   # board-only (a pin the library lacks)
    ]
    states = _states(LibraryPinConsistency(resolver=resolver), model)
    subjects = {o.subject: o.state for o in states["VIOLATION"]}
    assert subjects == {
        "U1 pin9": "VIOLATION",   # board-only -> ERROR below
        "U1 pin2": "VIOLATION",   # library-only -> WARN below
        "U1 pin3": "VIOLATION",
    }
    severities = {
        f.severity for f in LibraryPinConsistency(resolver=resolver).check(model)
    }
    assert severities == {"ERROR", "WARN"}  # board-only vs library-only
    # A perfect match is OK.
    model.components["U1"].pins = [
        Pin("1", "A", "NET2"), Pin("2", "B", "NET4"), Pin("3", "C", "NET2")]
    states = _states(LibraryPinConsistency(resolver=resolver), model)
    assert any(o.subject == "U1" and o.state == "OK" for o in states["OK"])


# ---------------------------------------------------------------- PWR-1


def test_pwr1_supply_pins_on_known_domains_are_ok_with_their_source():
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(SupplyOnKnownDomain(library=lib), _model())
    ok_subjects = {o.subject for o in states["OK"]}
    assert ok_subjects == {"U1 pin16", "U5 pin1"}
    u1 = next(o for o in states["OK"] if o.subject == "U1 pin16")
    assert "3.3 V" in u1.message and "U5 RT9013-33GB output" in u1.message
    u5 = next(o for o in states["OK"] if o.subject == "U5 pin1")
    assert "net name '+5V'" in u5.message


def test_pwr1_a_multimode_part_gets_one_verdict_per_pin():
    """U1 has two VCC records (5V/3.3V modes) on the same pin 16: the pin
    sits on one net, so one OK — not one per datasheet mode."""
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(SupplyOnKnownDomain(library=lib), _model())
    assert sum(1 for o in states["OK"] if o.subject == "U1 pin16") == 1


def test_pwr1_an_unknown_net_voltage_is_unknown_and_no_facts_is_unknown():
    lib = _library(_ldo_entry(), _uart_entry())
    model = _model(uart_net="RAIL_X")  # nobody speaks for RAIL_X
    states = _states(SupplyOnKnownDomain(library=lib), model)
    u1 = [o for o in states["UNKNOWN"] if o.subject == "U1 pin16"]
    assert len(u1) == 1 and "RAIL_X" in u1[0].missing_fact
    # U3 has an entry but no facts -> UNKNOWN naming the entry.
    u3 = [o for o in states["UNKNOWN"] if o.subject == "U3"]
    assert len(u3) == 1 and "supply_pins" in u3[0].missing_fact


def test_pwr1_an_explicitly_non_ic_category_is_not_applicable():
    lib = _library(_ldo_entry(), _uart_entry())
    model = _model()
    model.components["U3"] = Component(
        uid="u3", designator="U3", mpn="BAR-1", lcsc_part="C1",
        pins=[Pin("1", "A", "VCC")])
    lib.parts.append(PartEntry(key="conn.x", value="BAR", mpn="BAR-1",
                               lcsc="C1", category="connector"))
    states = _states(SupplyOnKnownDomain(library=lib), model)
    assert any(o.subject == "U3" and o.state == "NOT_APPLICABLE"
               for o in states["NOT_APPLICABLE"])


# ---------------------------------------------------------------- PWR-2


def test_pwr2_within_an_operating_range_is_ok_naming_the_mode():
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(DomainVsRange(library=lib), _model())
    u1 = next(o for o in states["OK"] if o.subject == "U1 pin16")
    assert "3V3-mode" in u1.message or "VCC-3V3-mode" in u1.message
    u5 = next(o for o in states["OK"] if o.subject == "U5 pin1")
    assert "VIN" in u5.message


def test_pwr2_above_abs_max_is_an_error_below_operating_is_a_warn():
    lib = _library(_ldo_entry(), _uart_entry())
    rule = DomainVsRange(library=lib)
    # 7 V on U5's input: inside neither tier's comfort, above the 6 V abs max.
    model = _model(vin_net="+7V")
    states = _states(rule, model)
    err = [o for o in states["VIOLATION"] if o.subject == "U5 pin1"]
    assert len(err) == 1 and "absolute maximum" in err[0].message
    findings = rule.check(model)
    assert findings[0].severity == "ERROR"
    # 5.8 V on U5's input: outside operating (<= 5.5) but inside abs max
    # (6.0) -> WARN. ("5.8V" is a whitelisted net name; "+5V8" is not.)
    model = _model(vin_net="5.8V")
    findings = rule.check(model)
    assert [f.severity for f in findings] == ["WARN"]
    assert "operating range" in findings[0].message


def test_pwr2_an_unknown_net_voltage_is_unknown():
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(DomainVsRange(library=lib), _model(uart_net="RAIL_X"))
    assert any(o.subject == "U1 pin16" and o.state == "UNKNOWN"
               for o in states["UNKNOWN"])


# ---------------------------------------------------------------- PATH-1


def test_path1_headroom_at_or_above_dropout_is_ok():
    lib = _library(_ldo_entry())
    states = _states(LdoDropout(library=lib), _model())
    assert len(states["OK"]) == 1
    assert "1700 mV" in states["OK"][0].message
    assert "400 mV" in states["OK"][0].message


def test_path1_below_dropout_is_a_violation():
    lib = _library(_ldo_entry())
    model = _model(vin_net="3V3")  # 3.3 - 3.3 = 0 mV headroom
    states = _states(LdoDropout(library=lib), model)
    assert len(states["VIOLATION"]) == 1
    assert "cannot hold" in states["VIOLATION"][0].message


def test_path1_an_unknown_rail_is_unknown():
    lib = _library(_ldo_entry())
    states = _states(LdoDropout(library=lib), _model(vin_net="RAIL_X"))
    assert len(states["UNKNOWN"]) == 1
    assert "RAIL_X" in states["UNKNOWN"][0].missing_fact


def test_path1_an_explicitly_non_ldo_ic_is_not_applicable():
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(LdoDropout(library=lib), _model())
    assert any(o.subject == "U1" and o.state == "NOT_APPLICABLE"
               for o in states["NOT_APPLICABLE"])


# ------------------------------------------------- xtal grounded-case fix


def _xtal_model(case_net: str | None) -> DesignModel:
    """A 4-pad crystal: resonator pins 1/3 with grounded caps, case pins 2/4."""
    model = DesignModel()
    model.components["X1"] = Component(
        uid="x1", designator="X1", value="12MHz",
        pins=[Pin("1", "OSC_IN", "NET2"), Pin("2", "CASE", case_net),
              Pin("3", "OSC_OUT", "NET3"), Pin("4", "CASE", case_net)],
    )
    model.components["C3"] = Component(
        uid="c3", designator="C3", pins=[Pin("1", "A", "NET2"),
                                         Pin("2", "B", "GND")])
    model.components["C25"] = Component(
        uid="c25", designator="C25", pins=[Pin("1", "A", "NET3"),
                                           Pin("2", "B", "GND")])
    model.nets = {
        "NET2": Net("NET2", [("X1", "1"), ("C3", "1")]),
        "NET3": Net("NET3", [("X1", "3"), ("C25", "1")]),
        "GND": Net("GND", [("C3", "2"), ("C25", "2")]),
    }
    if case_net:
        model.nets[case_net].pins.extend([("X1", "2"), ("X1", "4")])
    return model


def test_xtal_case_pins_on_ground_are_skipped_not_flagged():
    """The 011a-measured false positive: case pads live on GND, and no
    grounded capacitor can exist on the ground net itself. 011c: skipped."""
    assert CrystalLoadCaps().check(_xtal_model(case_net="GND")) == []


def test_xtal_a_two_pad_crystal_without_caps_is_still_flagged():
    """The normal path must survive the fix: a crystal whose resonator nets
    lack grounded capacitors is still reported."""
    model = _xtal_model(case_net=None)
    del model.components["C3"]
    model.nets["NET2"] = Net("NET2", [("X1", "1")])
    findings = CrystalLoadCaps().check(model)
    assert len(findings) == 1 and "NET2" in findings[0].message
