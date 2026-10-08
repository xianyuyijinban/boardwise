"""Tests for the voltage-domain inference (task 011c sec.3.1)."""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartLibrary, PartEntry, load_parts
from boardwise.core.power_domains import (
    CONFLICT,
    KNOWN,
    UNKNOWN,
    domain_of,
    infer_net_domains,
    ldo_output_pin,
    ldo_output_voltage,
    ldo_output_voltage_facts,
    voltage_from_net_name,
)


DS = "test datasheet, p.1, http://example.com/ds.pdf"


def _ldo_entry(
    mpn: str, lcsc: str, out_pin: str, in_pin: str,
    cap_pins: tuple[str, ...] | None = None,
    fixed_output: dict | None = None,
) -> PartEntry:
    ldo: dict = {}
    if fixed_output is not None:
        ldo["fixed_output"] = fixed_output
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
                "provenance": DS,
            }],
            "required_caps": [
                {"pin": pin, "value": "1uF", "provenance": DS}
                for pin in (cap_pins if cap_pins is not None else (in_pin, out_pin))
            ],
            **({"ldo": ldo} if ldo else {}),
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


@pytest.mark.parametrize("name,volts", [
    ("+3V3", 3.3), ("+5V0", 5.0), ("+1V8", 1.8), ("+12V0", 12.0),
    ("+3.3V", 3.3), ("+12V", 12.0), ("+5V", 5.0),
])
def test_a_plus_prefixed_rail_prices_the_same_as_its_unprefixed_spelling(name, volts):
    """Issue #71: the ``+`` was accepted on one rail grammar and missing on the other.

    ``_V_FORM`` (``^\\+?(\\d+(\\.\\d+)?)V$``) carried ``^\\+?`` and ``_MN_FORM``
    (``^(\\d+)V(\\d)$``) did not — so ``+5V`` priced as 5 V while ``+3V3`` priced
    as **nothing**. The mid-letter half is exactly where the ``+`` lives in real
    boards (``+3V3``/``+5V0``/``+1V8`` are standard rail names, not typos), and
    the hole was reachable: ``arch-opendrain-pullup`` judges the far end of a
    pull-up resistor through this function, so a ``10k`` from nFAULT to ``+3V3``
    was reported "no pull-up" while the identical resistor to ``+5V`` passed.
    """
    hit = voltage_from_net_name(name)
    assert hit == (volts, f"net name {name!r}"), name
    # and the unprefixed spelling of the same rail is unchanged
    assert voltage_from_net_name(name.lstrip("+")) == (volts, f"net name {name.lstrip('+')!r}")


def test_the_plus_prefix_is_still_not_a_rail_of_its_own():
    """The fix widens the mid-letter grammar by exactly one character. ``+`` alone,
    ``12V34`` (two decimal digits is not a rail) and the unpriced names stay
    unpriced — the whitelist's discipline is to refuse, not to widen."""
    for name in ("+", "+12V34", "+V3", "++3V3", "VCC", "NET7"):
        assert voltage_from_net_name(name) is None, name


def test_a_bare_vcc_is_never_guessed():
    """Names lie: VCC/VDD/VBUS get no voltage from their name alone."""
    for name in ("VCC", "VDD", "VBUS", "VEE", "NET7", "VIN", ""):
        assert voltage_from_net_name(name) is None, name


def test_an_ldo_output_names_its_net_and_says_where_the_voltage_came_from():
    """Since issue #17 the source names its own kind: the shelf entry declares
    no output-voltage fact, so the 3.3 V is decoded from the MPN suffix and the
    report says so (see the dedicated tests below)."""
    model = _model_with_ldo()
    guesses = infer_net_domains(model, _library(_ldo_entry(
        "RT9013-33GB", "C47773", out_pin="5", in_pin="1")))
    assert guesses["VCC"].state == KNOWN
    assert guesses["VCC"].volts == 3.3
    assert guesses["VCC"].source.startswith("U5 RT9013-33GB output")
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


# --------------------------------------------------------------------------
# issue #17 point one: an adjustable part's name is not an output voltage
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mpn,volts", [
    # Adjustable families, or fixed families written without their voltage
    # suffix: the trailing digits are part of the *name*. The pre-#17 reader
    # answered 1.7 V for LM317, 3.7 V for LM337, 1.3 V for RT9013 — all
    # fabrication, and the fabrication reached reports dressed as a fact
    # (`state=KNOWN, source="U1 LM317 output"`).
    ("LM317", None), ("LM337", None), ("LM117", None), ("LM350", None),
    ("LM1117", None), ("AMS1117", None), ("1117", None),
    ("SPX1117", None), ("LT1085", None), ("RT9013", None),
    # ...including a package letter where the voltage would have to be, and a
    # vendor prefix this reader has never heard of: the family match is on the
    # numeric stem, not on a list of prefixes.
    ("LM317T", None), ("LM317MDT-TR", None), ("R1117", None),
    # The two known suffix shapes keep decoding, verbatim.
    ("AMS1117-3.3", 3.3), ("AMS1117-5.0", 5.0), ("AMS1117-ADJ", None),
    ("RT9013-33GB", 3.3), ("RT9013-18GB", 1.8), ("RT9013-50GB", 5.0),
    ("LM1117MPX-3.3", 3.3), ("AMS1117-3.3V", 3.3), ("AMS1117-1.8", 1.8),
    # A part outside the guarded families keeps the suffix reading it always
    # had: an undelimited voltage tail is how a fixed LDO is normally named
    # (TLV70233, TPS7A2033), so #17 refuses the name-bearing digits of the
    # adjustable families, not the decoder.
    ("TPS7A2033", 3.3), ("", None),
])
def test_an_adjustable_name_is_never_read_as_an_output_voltage(mpn, volts):
    assert ldo_output_voltage(mpn) == volts


def test_the_family_list_is_known_families_not_a_proof_of_completeness():
    """Pinned so the limit is visible instead of discovered by a report reader.

    ``LT3083`` is an adjustable 3A regulator whose stem is not in the list, and
    ``CH340G`` is not a regulator at all: an *unlisted* name still lets the
    legacy suffix reading answer (8.3 V, 4.0 V). Both are unreachable in
    production — this reader is called only for an entry whose curated category
    is ``ic.ldo`` — and the designed answer for a new adjustable part is a
    curated ``ldo.fixed_output`` fact (or one more stem in
    :data:`_ADJUSTABLE_STEM`), never a guess. What the fix guarantees is the
    measured class: every family in the issue's table — and the classic
    siblings around them, ``TL783`` among them — answers None from now on.
    """
    assert ldo_output_voltage("LT3083") == 8.3
    assert ldo_output_voltage("CH340G") == 4.0
    assert ldo_output_voltage("TL783") is None


def test_an_adjustable_ldo_contributes_no_domain_at_all():
    """The end of the fabrication path: no voltage -> no domain -> no KNOWN."""
    model = _model_with_ldo(mpn="LM317", lcsc="C1234", vout_net="VCC")
    entry = _ldo_entry("LM317", "C1234", out_pin="5", in_pin="1")
    guesses = infer_net_domains(model, _library(entry))
    assert "VCC" not in guesses
    volts, _source, why_not = domain_of(guesses, "VCC")
    assert volts is None and "no source names" in why_not


def test_the_source_says_when_the_voltage_was_decoded_from_the_mpn():
    """`state=KNOWN` must not hide *who* is speaking: a suffix decode is a
    guess, and a report reader has to be able to tell it from a datasheet."""
    model = _model_with_ldo()
    guesses = infer_net_domains(model, _library(_ldo_entry(
        "RT9013-33GB", "C47773", out_pin="5", in_pin="1")))
    source = guesses["VCC"].source
    assert source.startswith("U5 RT9013-33GB output")
    assert "MPN" in source and "guess" in source
    assert "datasheet fact" in source


def test_a_declared_output_voltage_fact_wins_over_the_mpn_suffix():
    """The other half of #17 point two: when the shelf states the voltage with
    a page, that is what the source quotes — still no rule-output reshaping."""
    fact = {"volts": 3.3,
            "provenance": "Richtek RT9013 DS9013-10, p.3 (Fixed Output Voltage "
                          "3.3V), https://example.com/rt9013.pdf"}
    model = _model_with_ldo(mpn="RT9013", lcsc="C47773")  # no decodable suffix
    entry = _ldo_entry("RT9013", "C47773", out_pin="5", in_pin="1",
                       fixed_output=fact)
    guesses = infer_net_domains(model, _library(entry))
    assert guesses["VCC"].state == KNOWN and guesses["VCC"].volts == 3.3
    assert "p.3" in guesses["VCC"].source
    assert "datasheet" in guesses["VCC"].source
    assert ldo_output_voltage_facts(entry) == (3.3, fact["provenance"])


def test_a_shelf_entry_without_the_facts_has_no_declared_voltage():
    entry = _ldo_entry("RT9013-33GB", "C47773", out_pin="5", in_pin="1")
    assert ldo_output_voltage_facts(entry) is None
    assert entry.facts["required_caps"]  # the facts are there, the fact is not
    assert ldo_output_voltage_facts(PartEntry(
        key="ic.ldo.gated", value="LM317", mpn="LM317", lcsc="C1",
        category="ic.ldo", facts=None)) is None


# --------------------------------------------------------------------------
# issue #17 point two: an ambiguous output pin is None, not the first one
# --------------------------------------------------------------------------


def test_the_output_pin_needs_exactly_one_non_supply_cap_pin():
    """The docstring always promised this; the reader used to return the first
    non-supply cap pin. A two-output entry (measured: caps on 2 and 5 with VIN
    on 3) silently answered whichever came first — ``"5"`` in the issue's
    arrangement, ``"2"`` in the one below — a coin toss reported as a fact."""
    ambiguous = _ldo_entry("LM1117", "C1", out_pin="2", in_pin="3",
                           cap_pins=("3", "2", "5"))
    assert ldo_output_pin(ambiguous) is None
    # The two measured entries resolve unambiguously, and still do.
    assert ldo_output_pin(_ldo_entry("AMS1117-3.3", "C6186", out_pin="2",
                                     in_pin="3")) == "2"
    assert ldo_output_pin(_ldo_entry("RT9013-33GB", "C47773", out_pin="5",
                                     in_pin="1")) == "5"
    # One pin recorded twice (a mode tag, a re-read) is still one pin.
    repeated = _ldo_entry("AMS1117-3.3", "C6186", out_pin="2", in_pin="3",
                          cap_pins=("3", "2", "2"))
    assert ldo_output_pin(repeated) == "2"
    # No non-supply cap at all is no answer, not a guess.
    assert ldo_output_pin(_ldo_entry("AMS1117-3.3", "C6186", out_pin="2",
                                     in_pin="3", cap_pins=("3",))) is None


def test_an_ambiguous_output_pin_contributes_no_domain():
    """A coin-toss pin must not become a KNOWN voltage on a real rail."""
    model = _model_with_ldo(mpn="LM1117-3.3", lcsc="C1", vout_net="VCC")
    ambiguous = _ldo_entry("LM1117-3.3", "C1", out_pin="2", in_pin="3",
                           cap_pins=("3", "5", "2"))
    assert ldo_output_pin(ambiguous) is None
    assert "VCC" not in infer_net_domains(model, _library(ambiguous))
    # The unambiguous reading of the same board still names the rail: this is
    # a refusal to guess, not a refusal to answer.
    unique = _ldo_entry("LM1117-3.3", "C1", out_pin="5", in_pin="2",
                        cap_pins=("2", "5"))
    guess = infer_net_domains(model, _library(unique))["VCC"]
    assert (guess.state, guess.volts) == (KNOWN, 3.3)


# --------------------------------------------------------------------------
# issue #17 acceptance 2: the shipped shelf's three decoded LDOs do not move
# --------------------------------------------------------------------------


_SHIPPED_LDOS = (
    # (shelf key, MPN, output pin, volts) — the decoded values as published
    # before this batch, pinned so a family guard cannot quietly eat one.
    ("ic.ams1117_3_3.c369933", "AMS1117-3.3", "2", 3.3),
    ("ic.ams1117_3_3.c6186", "AMS1117-3.3", "2", 3.3),
    ("ic.rt9013_33gb", "RT9013-33GB", "5", 3.3),
)


def test_the_shipped_shelf_ldo_entries_still_decode_to_their_voltage_and_pin():
    library = load_parts("blocklib/parts.json")
    for key, mpn, out_pin, volts in _SHIPPED_LDOS:
        entry = next(e for e in library.parts if e.key == key)
        assert entry.category == "ic.ldo"
        assert entry.mpn == mpn
        assert ldo_output_pin(entry) == out_pin, key
        assert ldo_output_voltage(entry.mpn) == volts, key
        # And end to end: the inference still names an output net at that volts.
        in_pin = next(p for record in entry.facts["supply_pins"]
                      for p in record.get("pins", []))
        model = DesignModel()
        model.components["U5"] = Component(
            uid="u5", designator="U5", mpn=mpn, lcsc_part=entry.lcsc,
            pins=[Pin(in_pin, "VIN", "+5V"), Pin(out_pin, "VOUT", "OUT_RAIL")])
        model.nets = {"+5V": Net("+5V", [("U5", in_pin)]),
                      "OUT_RAIL": Net("OUT_RAIL", [("U5", out_pin)])}
        guess = infer_net_domains(model, library)["OUT_RAIL"]
        assert (guess.state, guess.volts) == (KNOWN, volts), key
        assert guess.source.startswith(f"U5 {mpn} output"), key
