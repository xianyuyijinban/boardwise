"""Tests for the voltage-domain inference (task 011c sec.3.1)."""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartLibrary, PartEntry
from boardwise.core.power_domains import (
    CONFLICT,
    KNOWN,
    UNKNOWN,
    domain_of,
    infer_net_domains,
    ldo_output_pin,
    ldo_output_voltage,
    voltage_from_net_name,
)


def _ldo_entry(mpn: str, lcsc: str, out_pin: str, in_pin: str) -> PartEntry:
    return PartEntry(
        key="ic.ldo.test",
        value=mpn,
        mpn=mpn,
        lcsc=lcsc,
        category="ic.ldo",
        facts={
            "supply_pins": [{
                "pins": [in_pin],
                "name": "VIN",
                "v_operating": [2.2, 5.5],
                "provenance": "test datasheet, p.1, http://example.com/ds.pdf",
            }],
            "required_caps": [
                {"pin": in_pin, "value": "1uF",
                 "provenance": "test datasheet, p.1, http://example.com/ds.pdf"},
                {"pin": out_pin, "value": "1uF",
                 "provenance": "test datasheet, p.1, http://example.com/ds.pdf"},
            ],
        },
    )


def _library(*entries: PartEntry) -> PartLibrary:
    return PartLibrary(parts=list(entries))


def _model_with_ldo(
    mpn: str = "RT9013-33GB", lcsc: str = "C47773",
    vin_net: str = "+5V", vout_net: str = "VCC",
) -> DesignModel:
    model = DesignModel()
    model.components["U5"] = Component(
        uid="u5", designator="U5", mpn=mpn, lcsc_part=lcsc,
        pins=[Pin("1", "VIN", vin_net), Pin("5", "VOUT", vout_net)],
    )
    model.nets = {
        vin_net: Net(vin_net, [("U5", "1")]),
        vout_net: Net(vout_net, [("U5", "5")]),
    }
    return model


def test_a_whitelisted_net_name_yields_a_voltage_with_its_source():
    for name, volts in (("+5V", 5.0), ("12V", 12.0), ("3.3V", 3.3),
                        ("5V0", 5.0), ("3V3", 3.3), ("1V8", 1.8)):
        hit = voltage_from_net_name(name)
        assert hit == (volts, f"net name {name!r}"), name


def test_a_bare_vcc_is_never_guessed():
    """Names lie: VCC/VDD/VBUS get no voltage from their name alone."""
    for name in ("VCC", "VDD", "VBUS", "VEE", "NET7", "VIN", ""):
        assert voltage_from_net_name(name) is None, name


def test_an_ldo_output_names_its_net_with_the_facts_as_source():
    model = _model_with_ldo()
    guesses = infer_net_domains(model, _library(_ldo_entry(
        "RT9013-33GB", "C47773", out_pin="5", in_pin="1")))
    assert guesses["VCC"].state == KNOWN
    assert guesses["VCC"].volts == 3.3
    assert guesses["VCC"].source == "U5 RT9013-33GB output"
    # The input net is named by its own name, not by the LDO.
    assert guesses["+5V"].state == KNOWN
    assert "+5V" in guesses["+5V"].source


def test_conflicting_sources_yield_a_conflict_naming_both_sides():
    model = _model_with_ldo(mpn="RT9013-18GB", vout_net="3V3")
    # The MPN says 1.8 V but the net name says 3.3 V.
    guesses = infer_net_domains(model, _library(_ldo_entry(
        "RT9013-18GB", "C47773", out_pin="5", in_pin="1")))
    guess = guesses["3V3"]
    assert guess.state == CONFLICT
    assert guess.volts is None
    assert "1.8 V per U5 RT9013-18GB output" in guess.detail
    assert "3.3 V per net name" in guess.detail
    # And domain_of turns that into a missing-fact string, not a voltage.
    volts, _source, why_not = domain_of(guesses, "3V3")
    assert volts is None and "conflicting" in why_not


def test_a_net_no_source_speaks_for_is_unknown():
    model = _model_with_ldo()
    # A third rail with a passive pin on it: neither its name nor any LDO
    # output speaks for it, so the honest answer is UNKNOWN.
    model.components["R9"] = Component(
        uid="r9", designator="R9", value="10k",
        pins=[Pin("1", "A", "RAIL_X"), Pin("2", "B", "GND")],
    )
    model.nets["RAIL_X"] = Net("RAIL_X", [("R9", "1")])
    guesses = infer_net_domains(model, _library(_ldo_entry(
        "RT9013-33GB", "C47773", out_pin="5", in_pin="1")))
    # No entry at all: absence IS the unknown, and domain_of names it.
    assert "RAIL_X" not in guesses
    volts, _source, why_not = domain_of(guesses, "RAIL_X")
    assert volts is None and "no source" in why_not


def test_an_unqueried_net_has_no_entry_and_domain_of_says_so():
    model = _model_with_ldo()
    guesses = infer_net_domains(model, _library(_ldo_entry(
        "RT9013-33GB", "C47773", out_pin="5", in_pin="1")))
    assert "GND" not in guesses
    volts, _source, why_not = domain_of(guesses, "GND")
    assert volts is None and "no source names the voltage" in why_not


def test_the_output_pin_comes_from_the_facts_not_the_net_name():
    entry = _ldo_entry("AMS1117-3.3", "C6186", out_pin="2", in_pin="3")
    assert ldo_output_pin(entry) == "2"
    assert ldo_output_voltage("AMS1117-3.3") == 3.3
    assert ldo_output_voltage("RT9013-33GB") == 3.3
    # An adjustable part has no fixed output: nothing may be invented.
    assert ldo_output_voltage("AMS1117-ADJ") is None


def test_a_shelf_entry_without_the_ldo_shape_contributes_nothing():
    model = _model_with_ldo(mpn="CH340G", lcsc="C14267", vout_net="VCC")
    entry = PartEntry(key="ic.ch340g", value="CH340G", mpn="CH340G",
                      lcsc="C14267", category="ic.usb-uart")
    guesses = infer_net_domains(model, _library(entry))
    assert "VCC" not in guesses  # no source names it: not even a guess
