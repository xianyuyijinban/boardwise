"""Tests for the 011d rules: DECAP-1, PARAM-1/2/3/4, CONN-usb-cc (task 011d
secs.3.1-3.5), the facts-schema extension (sec.2), and the golden board's
measured expectations."""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.rules.base import OUTCOME_STATES
from boardwise.rules.decap import DecapRequiredCaps, _looks_like_capacitor
from boardwise.rules.facts import UsbCcPulldown
from boardwise.rules.params import (
    DividerOutput,
    LedCurrent,
    RcCutoff,
    ValueMpnMatch,
)
from boardwise.rules.values import (
    decode_eia_3digit,
    mpn_value_code,
    parse_capacitance_farads,
)

PROV = "test datasheet, p.1, http://example.com/ds.pdf"


def _ldo_entry(mpn: str = "RT9013-33GB") -> PartEntry:
    return PartEntry(
        key="ic.ldo.test", value=mpn, mpn=mpn, lcsc="C47773",
        category="ic.ldo",
        facts={
            "supply_pins": [{
                "pins": ["1"], "name": "VIN",
                "v_operating": [2.2, 5.5], "provenance": PROV,
            }],
            "required_caps": [
                {"pin": "1", "value": "1uF", "provenance": PROV},
                {"pin": "5", "value": "1uF", "provenance": PROV},
            ],
        },
    )


def _uart_entry() -> PartEntry:
    """The CH340G shape: two supply modes, V3 records mode-tagged."""
    return PartEntry(
        key="ic.usb-uart.test", value="CH340G", mpn="CH340G",
        lcsc="C14267", category="ic.usb-uart",
        facts={
            "supply_pins": [
                {"pins": ["16"], "name": "VCC-5V",
                 "v_operating": [4.0, 5.3], "mode": "5V", "provenance": PROV},
                {"pins": ["16"], "name": "VCC-3V3",
                 "v_operating": [2.9, 3.6], "mode": "3.3V", "provenance": PROV},
            ],
            "required_caps": [
                {"pin": "16", "value": "0.1uF", "provenance": PROV},
                {"pin": "4", "value": "0.1uF", "mode": "5V",
                 "provenance": PROV},
            ],
            "must_connect": [
                {"pin": "4", "to": "VCC", "mode": "3.3V",
                 "provenance": PROV},
            ],
        },
    )


def _led_entry(vf=(2.7, 3.2), if_max=30.0) -> PartEntry:
    return PartEntry(
        key="led.test", value="LED-X", mpn="LED-X", lcsc="C1",
        category="led",
        facts={"led": {"vf_v": list(vf), "if_max_ma": if_max,
                       "provenance": PROV}},
    )


def _library(*entries: PartEntry) -> PartLibrary:
    return PartLibrary(parts=list(entries))


def _golden_like_model(vin_net="+5V", vcc_cap_value="2.2uF") -> DesignModel:
    """The golden board's fact-bearing skeleton: an LDO from +5V to VCC, the
    CH340G on VCC, and the parts the decap check must tell apart."""
    model = DesignModel()
    model.components["U5"] = Component(
        uid="u5", designator="U5", mpn="RT9013-33GB", lcsc_part="C47773",
        pins=[Pin("1", "VIN", vin_net), Pin("5", "VOUT", "VCC")],
    )
    model.components["U1"] = Component(
        uid="u1", designator="U1", mpn="CH340G", lcsc_part="C14267",
        pins=[Pin("16", "VCC", "VCC"), Pin("4", "V3", "NET1")],
    )
    model.components["C5"] = Component(
        uid="c5", designator="C5", value="",
        mpn="CL10A225KA8NNNC",
        pins=[Pin("1", "A", "GND"), Pin("2", "B", vin_net)],
    )
    model.components["C9"] = Component(
        uid="c9", designator="C9", value=vcc_cap_value,
        mpn="CL10A225KA8NNNC",
        pins=[Pin("1", "A", "GND"), Pin("2", "B", "VCC")],
    )
    model.components["C6"] = Component(
        uid="c6", designator="C6", value="100nF",
        mpn="CC0603KRX7R9BB104",
        pins=[Pin("1", "A", "GND"), Pin("2", "B", "VCC")],
    )
    model.nets = {
        vin_net: Net(vin_net, [("U5", "1"), ("C5", "2")]),
        "VCC": Net("VCC", [("U5", "5"), ("U1", "16"), ("C9", "2"), ("C6", "2")]),
        "NET1": Net("NET1", [("U1", "4")]),
        "GND": Net("GND", [("C5", "1"), ("C9", "1"), ("C6", "1")]),
    }
    return model


def _states(rule, model) -> dict[str, list]:
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for outcome in rule.outcomes(model):
        grouped[outcome.state].append(outcome)
    return grouped


# ------------------------------------------------------------- value parsers


def test_the_capacitance_parser_requires_a_unit():
    assert parse_capacitance_farads("100nF") == pytest.approx(1e-7)
    assert parse_capacitance_farads("0.1uF") == pytest.approx(1e-7)
    assert parse_capacitance_farads("22uF") == pytest.approx(2.2e-5)
    assert parse_capacitance_farads("10pF") == pytest.approx(1e-11)
    # A bare number is ambiguous by orders of magnitude: never guessed.
    assert parse_capacitance_farads("100") is None
    assert parse_capacitance_farads("") is None


def test_the_eia_decoder_decodes_in_the_callers_unit():
    assert decode_eia_3digit("471", 1.0) == pytest.approx(470.0)
    assert decode_eia_3digit("104", 1e-12) == pytest.approx(1e-7)
    assert decode_eia_3digit("225", 1e-12) == pytest.approx(2.2e-6)


def test_the_mpn_code_finder_whitelists_shapes_and_guards_packages():
    assert mpn_value_code("FRC0805J471 TS") == "471"
    assert mpn_value_code("CL10A225KA8NNNC") == "225"
    assert mpn_value_code("CC0603KRX7R9BB104") == "104"
    # A part number with no code, or two conflicting ones, is None.
    assert mpn_value_code("") is None
    assert mpn_value_code("CGA0603X5R105K500JT") is None  # 105 vs 500
    # The CH340G lesson: "CH340G" would decode to "34 pF" -- the guard and
    # the caller's kind check keep a regulator from masquerading as a cap.
    assert mpn_value_code("CH340G") == "340"  # the finder is dumb; callers gate


def test_the_mpn_code_finder_refuses_notations_that_are_not_eia():
    """Task 015: three notations were being hard-read as EIA codes, and each
    witnessed false contradiction came from one of them.

    The refusal is of the **whole token**, not of one candidate: dropping a
    candidate can promote another, and ``C1608X5R1V225KT000E`` is the proof --
    with ``225`` dropped, ``000`` becomes the only code left and the part
    reports as 0 F.

    Each class has a witness the other two leave alone, which is what makes a
    single-guard mutation visible (task 015 sec.4.2).
    """
    # R as the decimal point: a 1 mΩ shunt is not "00 x 10^1". Keep this list
    # to the parts only the R guard refuses -- adding an HGC part number here
    # would hide a broken voltage guard behind a working R guard.
    assert mpn_value_code("RE2512F3R001") is None
    assert mpn_value_code("JER2512F3R005") is None
    assert mpn_value_code("RE1206F1R000") is None
    assert mpn_value_code("RE1206F1R100") is None
    # value + tolerance letter + voltage rating: the second group is a
    # rating, so neither group is a value on its own.
    assert mpn_value_code("HGC1206R5106K500NSPJ") is None  # 106K500 = 10µF/50V
    assert mpn_value_code("HGC0603R5225K500NTHJ") is None
    assert mpn_value_code("HHV1206R7475K101NSPJ") is None
    assert mpn_value_code("CGA0603X7R104K500JT") is None
    # The electrolytic layout: a case size, or a voltage before the value --
    # PA50V330M10x15 is 50 V, 330 µF ±20 %, 10x15 mm, and "330M" is not EIA.
    assert mpn_value_code("PA50V330M10x15") is None
    assert mpn_value_code("PA50V330M") is None
    # The strict shapes are untouched, the package guard included: a
    # resistor's size-tolerance-value tail (0805 J 471) is not read as a
    # voltage rating, the X7R/X5R dielectric is not an R decimal point, and a
    # size is still not a value.
    assert mpn_value_code("FRC0805J471 TS") == "471"
    assert mpn_value_code("FRC0805F4122TS") is None
    assert mpn_value_code("CL10B105KA8NNNC") == "105"
    assert mpn_value_code("CC0603KRX7R9BB104") == "104"
    assert mpn_value_code("GRM1885C1H122JA01D") == "122"
    assert mpn_value_code("0805W8F1003T5E") is None
    # Unchanged from before 015: this one is None by *ambiguity* (225 vs the
    # packaging group 000), which is the pre-existing reason, not a refusal.
    assert mpn_value_code("C1608X5R1V225KT000E") is None


def test_a_capacitor_is_never_claimed_from_an_mpn_code_alone():
    """CH340G decodes to "34 pF"; only the shelf's category (or the value
    field, or the C-designator+code conjunction) may call something a cap."""
    lib = _library(_ldo_entry())
    ch340 = Component(uid="u", designator="U1", value="", mpn="CH340G")
    assert not _looks_like_capacitor(ch340, lib)
    real_cap = Component(uid="c", designator="C9", value="2.2uF")
    assert _looks_like_capacitor(real_cap, lib)
    unshelfed = Component(uid="c", designator="C5", value="",
                          mpn="CL10A225KA8NNNC")
    # C-prefix + decodable code: the weak-but-honest conjunction.
    assert _looks_like_capacitor(unshelfed, lib)


# ------------------------------------------------------------ DECAP-1


def test_decap_the_v3_wiring_is_a_mode_sensitive_violation():
    """The oracle's V3 defect, ruled 2026-09-19: VCC=3.3V puts U1 in 3.3V
    mode, where the manual requires V3 tied to VCC -- the board ties it to a
    capacitor instead. The 5V-mode V3 capacitor record does NOT apply."""
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(DecapRequiredCaps(library=lib), _golden_like_model())
    violations = {o.subject: o for o in states["VIOLATION"]}
    assert "U1 pin4" in violations
    assert "3.3V" in violations["U1 pin4"].message
    # Exactly one violation: the inactive 5V-mode V3 record stayed silent.
    # (Mutation M1 pins this -- a mode-blind rule fires twice here.)
    assert len(states["VIOLATION"]) == 1
    # The mode-sensitive 5V capacitor record stayed silent: the board is not
    # in 5V mode, and the rule knew it.
    assert not any("mode '5V'" in o.message for o in states["UNKNOWN"])
    assert any(
        o.subject == "U1 pin16" and o.state == "OK" for o in states["OK"]
    )


def test_decap_each_pin_is_judged_on_its_own_capacitor():
    """DECAP-2 as a test: VCC hosts several parts, but the check is per pin
    against the best grounded capacitor -- a shared rail never grants a
    blanket OK (and never lets one part's cap count for a pin it does not
    reach)."""
    lib = _library(_ldo_entry(), _uart_entry())
    states = _states(DecapRequiredCaps(library=lib), _golden_like_model())
    ok_subjects = {o.subject for o in states["OK"]}
    assert {"U1 pin16", "U5 pin1", "U5 pin5"} <= ok_subjects


def test_decap_an_unknown_cap_value_is_unknown_not_ok():
    lib = _library(_ldo_entry(), _uart_entry())
    model = _golden_like_model(vcc_cap_value="")  # C9's value unreadable
    model.components.pop("C6")  # no readable cap may rescue the pin
    # C9 keeps its shelf identity (so it still *counts* as a capacitor) but
    # loses its MPN: nothing left to establish its value from.
    model.components["C9"].mpn = ""
    shelf = lib.by_key()
    next(k for k in shelf if k == "ic.ldo.test")  # sanity: lib non-empty
    model.nets["VCC"] = Net("VCC", [
        ("U5", "5"), ("U1", "16"), ("C9", "2")])
    lib.parts.append(PartEntry(
        key="cap.c9", value="C9", mpn="C9-MPN", lcsc="C999",
        category="capacitor"))
    model.components["C9"].lcsc_part = "C999"
    states = _states(DecapRequiredCaps(library=lib), model)
    u5 = [o for o in states["UNKNOWN"] if o.subject == "U5 pin5"]
    assert len(u5) == 1 and "C9" in u5[0].missing_fact


def test_decap_components_without_facts_are_unknown():
    lib = _library(
        _ldo_entry(), _uart_entry(),
        PartEntry(key="res.470_0805", value="470R", mpn="FRC0805J471 TS",
                  lcsc="C2907329"),
    )
    model = _golden_like_model()
    model.components["U3"] = Component(
        uid="u3", designator="U3", value="1kΩ",
        mpn="FRC0805J471 TS", lcsc_part="C2907329",
        pins=[Pin("1", "A", "VCC")])
    states = _states(DecapRequiredCaps(library=lib), model)
    # U3's shelf entry (C2907329) carries no facts: named, not guessed.
    u3 = [o for o in states["UNKNOWN"] if o.subject == "U3"]
    assert len(u3) == 1 and "C2907329" in u3[0].missing_fact


def test_decap_the_v3_record_is_checked_when_5v_mode_is_active():
    """The mode gate swings both ways: on a 5V rail the V3 capacitor record
    applies and the tie-to-VCC obligation does not. The 5V rail is built
    honestly: an RT9013-50GB output on a net named 5V0 -- both sources agree
    on 5.0V, so the active mode is measured, not assumed."""
    ldo50 = PartEntry(
        key="ic.ldo.test", value="RT9013-50GB", mpn="RT9013-50GB",
        lcsc="C47773", category="ic.ldo",
        facts={
            "supply_pins": [{
                "pins": ["1"], "name": "VIN",
                "v_operating": [2.2, 5.5], "provenance": PROV,
            }],
            "required_caps": [
                {"pin": "1", "value": "1uF", "provenance": PROV},
                {"pin": "5", "value": "1uF", "provenance": PROV},
            ],
        },
    )
    lib = _library(ldo50, _uart_entry())
    model = _golden_like_model(vin_net="+12V")
    for comp in model.components.values():
        for pin in comp.pins:
            if pin.net == "VCC":
                pin.net = "5V0"
    model.nets["5V0"] = Net("5V0", [
        ("U5", "5"), ("U1", "16"), ("C9", "2"), ("C6", "2")])
    states = _states(DecapRequiredCaps(library=lib), model)
    violations = {o.subject: o.message for o in states["VIOLATION"]}
    # The 3.3V tie obligation is inactive on a 5V rail...
    assert not any("must sit on net 'VCC'" in m for m in violations.values()), violations
    # ...and the 5V-mode V3 capacitor record takes over: NET1 has none.
    assert any("pin4" in subject for subject in violations), violations
    assert any(o.subject == "U1 pin16" and o.state == "OK"
               for o in states["OK"])


# ------------------------------------------------------------ PARAM-4


def test_param4_a_contradiction_past_the_tolerance_is_the_violation():
    """4.7k against a 470-ohm MPN is 10x: past the R tolerance (2026-09-21),
    so it stays the WARN it always was -- now with the amplitude quoted."""
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["U3"] = Component(
        uid="u3", designator="U3", value="4.7kΩ",
        mpn="FRC0805J471 TS", lcsc_part="C2907329",
        pins=[Pin("1", "A", "VCC")],
    )
    findings = ValueMpnMatch(library=lib).check(model)
    assert len(findings) == 1 and findings[0].severity == "WARN"
    assert "470" in findings[0].message and "4700" in findings[0].message
    assert "10.00x apart" in findings[0].message
    assert "3x tolerance" in findings[0].message


def test_param4_a_contradiction_below_the_tolerance_is_ok_with_its_amplitude():
    """The same 1k-vs-470 pair the golden board carries: 2.13x < 3x is OK.

    "OK" here is not silence -- the row quotes the amplitude and the ruling,
    so a reader can see what was waived and re-judge it. This is the oracle's
    known cost (2026-09-21): the golden board's U3 is this very pair, and it
    was a signed 011c defect before the amplitude ruling.
    """
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["U3"] = Component(
        uid="u3", designator="U3", value="1kΩ",
        mpn="FRC0805J471 TS", lcsc_part="C2907329",
        pins=[Pin("1", "A", "VCC")],
    )
    states = _states(ValueMpnMatch(library=lib), model)
    assert states["VIOLATION"] == []
    assert ValueMpnMatch(library=lib).check(model) == []
    waived = next(o for o in states["OK"] if o.subject == "U3")
    assert "470" in waived.message and "1000" in waived.message
    assert "2.13x" in waived.message
    assert "below the 3x tolerance" in waived.message
    assert "015 batch-2" in waived.message
    # Evidence rides along, as it does for the violation.
    assert "U3 value '1kΩ'" in waived.evidence


def test_param4_the_amplitude_tolerances_are_the_oracles_ruling():
    """The numbers, pinned. They are a ruling, not a physics constant: the
    resistors' 3x is bracketed by the witnessed 2.13x (waived) and 4.70x
    (kept), and the capacitors' 25x is the project lead's interpolation over
    a witnessed 22x maximum (see the constant's comment)."""
    from boardwise.rules.params import (
        MPN_AMPLITUDE_TOLERANCE_C,
        MPN_AMPLITUDE_TOLERANCE_R,
    )

    assert MPN_AMPLITUDE_TOLERANCE_R == 3.0
    assert MPN_AMPLITUDE_TOLERANCE_C == 25.0
    assert MPN_AMPLITUDE_TOLERANCE_R < MPN_AMPLITUDE_TOLERANCE_C


def test_param4_the_tolerance_is_per_kind_and_the_boundary_is_inclusive():
    """A capacitor at an amplitude no resistor could reach: 10x and 22x are
    OK (the graduation board's five), and the ratio is at-or-above -> keep.

    The two kinds are read off the shelf category first, then the value's
    unit, which is what lets a 1k-ohm part under a U designator be judged at
    all (``_kind_of``).
    """
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    # Capacitors: 100nF declared against a 103 code (10 nF), which is the
    # graduation board's C28/C29 shape -- 10x, far past any resistor's
    # tolerance and still waived.
    model.components["C28"] = Component(
        uid="c28", designator="C28", value="100nF", mpn="CC0603KRX7R9BB103",
        pins=[Pin("1", "A", "VCC")])
    model.components["C29"] = Component(
        uid="c29", designator="C29", value="0.1uF", mpn="CC0603KRX7R9BB103",
        pins=[Pin("1", "A", "VCC")])
    # A 2.2uF declared against a 100nF code is 22x -- the graduation board's
    # C36/C44 shape.
    model.components["C36"] = Component(
        uid="c36", designator="C36", value="2.2uF", mpn="CL10B104KB8NNNC",
        pins=[Pin("1", "A", "VCC")])
    # 25x exactly: 2.5uF declared against a 100nF code.
    model.components["C37"] = Component(
        uid="c37", designator="C37", value="2.5uF", mpn="CL10B104KB8NNNC",
        pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    ok = {o.subject: o.message for o in states["OK"]}
    assert "10.00x" in ok["C28"] and "25x tolerance" in ok["C28"]
    assert "10.00x" in ok["C29"]
    assert "22.00x" in ok["C36"]
    assert [o.subject for o in states["VIOLATION"]] == ["C37"]
    assert "25.00x apart" in states["VIOLATION"][0].message


def test_param4_a_resistor_at_the_r_tolerance_is_not_waived():
    """3x exactly is the violation side ("ratio >= threshold"), and the same
    ratio is a long way under the capacitor tolerance -- the boundary test
    that keeps the two constants from being swapped."""
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R9"] = Component(
        uid="r9", designator="R9", value="3kΩ", mpn="FRC0805J102 TS",
        pins=[Pin("1", "A", "VCC")])  # 3000 vs 1000 = 3.00x
    model.components["C9"] = Component(
        uid="c9", designator="C9", value="2.5uF", mpn="CL10B104KB8NNNC",
        pins=[Pin("1", "A", "VCC")])
    model.components["C10"] = Component(
        uid="c10", designator="C10", value="2.49uF", mpn="CL10B104KB8NNNC",
        pins=[Pin("1", "A", "VCC")])  # 24.9x -- just under, still waived
    states = _states(ValueMpnMatch(library=lib), model)
    violations = {o.subject: o.message for o in states["VIOLATION"]}
    assert sorted(violations) == ["C9", "R9"]
    assert "3.00x apart" in violations["R9"]
    assert "25.00x apart" in violations["C9"]
    assert any(o.subject == "C10" for o in states["OK"])


def test_param4_a_zero_side_leaves_the_ratio_undefined_and_stays_a_violation():
    """``min <= 0``: 0/0 and x/0 are not amplitudes. A 0-ohm value against a
    470-ohm MPN still contradicts, and the message says why it was not
    waived instead of inventing a ratio."""
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R0"] = Component(
        uid="r0", designator="R0", value="0Ω", mpn="FRC0805J471 TS",
        pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert [o.subject for o in states["VIOLATION"]] == ["R0"]
    message = states["VIOLATION"][0].message
    assert "ratio undefined" in message
    assert "0 vs 470" in message
    assert not [o for o in states["OK"] if o.subject == "R0"]


def test_param4_the_a2a_exceptions_become_unknown_not_contradictions():
    """The three exceptions the oracle ruled "the rule is wrong" (2026-09-20)
    as a rule-level assertion: R43's shunt (R notation) and C115/C116's
    electrolytics must report UNKNOWN and raise nothing (task 015 sec.2).

    Two different decisions meet on this board and must not be confused: the
    decoder *refuses* those three tokens (batch 1), while the amplitude
    ruling *grades* what the decoder still reads (batch 2). The witness below
    is the second half."""
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R43"] = Component(
        uid="r43", designator="R43", value="0.01Ω", mpn="JER2512F3R005",
        pins=[Pin("1", "A", "VCC")])
    model.components["C115"] = Component(
        uid="c115", designator="C115", value="330uF", mpn="PA50V330M10x15",
        pins=[Pin("1", "A", "VCC")])
    model.components["C116"] = Component(
        uid="c116", designator="C116", value="330uF", mpn="PA50V330M10x15",
        pins=[Pin("1", "A", "VCC")])
    # A part whose code is still read stays judged -- and since batch 2
    # "judged" means graded by amplitude, so the witness has to be one that
    # is actually past the tolerance: U10 as it stands on the real board
    # (1k vs 471 = 2.13x) is OK now, while 10k against the same MPN is not.
    model.components["U10"] = Component(
        uid="u10", designator="U10", value="1kΩ", mpn="FRC0805J471 TS",
        pins=[Pin("1", "A", "VCC")])
    model.components["U11"] = Component(
        uid="u11", designator="U11", value="10kΩ", mpn="FRC0805J471 TS",
        pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert [o.subject for o in states["VIOLATION"]] == ["U11"]
    unknown = {o.subject for o in states["UNKNOWN"]}
    assert {"R43", "C115", "C116"} <= unknown
    assert "U10" not in unknown, "a decoded code is judged, never refused"
    assert any(o.subject == "U10" for o in states["OK"])


def test_param4_matching_values_are_ok_and_undecodable_are_unknown():
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value="470Ω", mpn="FRC0805J471 TS",
        pins=[Pin("1", "A", "VCC")])
    model.components["R24"] = Component(
        uid="r24", designator="R24", value="5.1K",
        pins=[Pin("1", "A", "VCC")])  # no MPN at all
    model.components["C4"] = Component(
        uid="c4", designator="C4", value="",
        mpn="CGA0603X5R105K500JT",  # two candidate codes: ambiguous
        pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert any(o.subject == "R1" and o.state == "OK" for o in states["OK"])
    unknown_subjects = {o.subject for o in states["UNKNOWN"]}
    assert "R24" in unknown_subjects
    # C4 has neither a value unit nor a shelf entry: no kind evidence at
    # all, so the rule skips it entirely (no outcome, not even UNKNOWN --
    # "no evidence" is not a question the rule can ask).
    assert "C4" not in unknown_subjects
    assert all(o.subject != "C4" for o in states["OK"])


# ------------------------------------------------------------ PARAM-1


def _led_model(resistor="1kΩ", supply="3V3") -> DesignModel:
    """LED1 between GND and its anode net, optionally behind one resistor.

    ``resistor=None`` puts the LED's anode straight on ``supply``: there is
    nothing in series, which is its own case (0 ohm across the rail).
    """
    model = DesignModel()
    anode_net = supply if resistor is None else "NET4"
    model.components["LED1"] = Component(
        uid="led", designator="LED1", mpn="LED-X", lcsc_part="C1",
        footprint="LED0603",
        pins=[Pin("1", "K", "GND"), Pin("2", "A", anode_net)])
    nets = {
        "GND": Net("GND", [("LED1", "1")]),
        anode_net: Net(anode_net, [("LED1", "2")]),
    }
    if resistor is not None:
        model.components["R5"] = Component(
            uid="r5", designator="R5", value=resistor,
            pins=[Pin("1", "A", "NET4"), Pin("2", "B", supply)])
        nets["NET4"].pins.append(("R5", "1"))
        nets[supply] = Net(supply, [("R5", "2")])
    model.nets = nets
    return model


def test_param1_the_oracles_window_is_judged_on_the_resistance_value():
    """Ruling 2026-09-19: in the 3V3 domain an indicator LED's series
    resistance must sit in [470, 2200] ohm -- judged from the value field, not
    from a computed current.

    Both ends are **inclusive** and that is load-bearing: 2.2k is the oracle's
    own corrected value on the injected base board, so an exclusive top would
    flag the reference design.
    """
    lib = _library(_led_entry())
    for value in ("470Ω", "1kΩ", "2.2kΩ"):
        rule = LedCurrent(library=lib)
        states = _states(rule, _led_model(resistor=value))
        ok = [o for o in states["OK"] if o.subject == "LED1"]
        assert len(ok) == 1, (value, [o.message for o in states["VIOLATION"]])
        assert "[470, 2200]" in ok[0].message
    assert not rule.check(_led_model(resistor="1kΩ"))


def test_param1_a_resistance_outside_the_window_is_a_warn():
    """4.7k is the oracle's own counter-example (too dim to see); 100 ohm is
    the other side (too bright). Neither is a hazard, so both are WARN."""
    lib = _library(_led_entry())
    for value, word in (("4.7kΩ", "above"), ("100Ω", "below")):
        rule = LedCurrent(library=lib)
        model = _led_model(resistor=value)
        heat = [o for o in _states(rule, model)["VIOLATION"]
                if o.subject == "LED1"]
        assert len(heat) == 1 and word in heat[0].message, (value, heat)
        assert [f.severity for f in rule.check(model)] == ["WARN"]


def test_param1_the_rule_speaks_for_the_3v3_domain_only():
    """A 5 V rail is UNKNOWN -- not a pass and not a fail.

    The oracle stated a window for 3.3 V; stretching it to another domain
    would be the rule inventing a requirement, and silently passing the board
    would be the same invention wearing a friendlier face.
    """
    lib = _library(_led_entry())
    states = _states(LedCurrent(library=lib),
                     _led_model(resistor="1kΩ", supply="+5V"))
    unknown = [o for o in states["UNKNOWN"] if o.subject == "LED1"]
    assert len(unknown) == 1
    assert "3.3 V domain only" in unknown[0].message
    assert "5 V domain" in unknown[0].missing_fact
    assert not states["OK"] and not states["VIOLATION"]


def test_param1_an_unnamed_rail_is_unknown_not_a_window():
    """``VCC`` is a name the whitelist never guesses.

    It is 3.3 V on the golden board only because the RT9013-33GB's facts say
    so; with no such source the rule must not apply the window to a voltage
    nobody asserted.
    """
    lib = _library(_led_entry())
    states = _states(LedCurrent(library=lib),
                     _led_model(resistor="1kΩ", supply="VCC"))
    unknown = [o for o in states["UNKNOWN"] if o.subject == "LED1"]
    assert len(unknown) == 1
    assert "series resistor" in unknown[0].missing_fact
    assert not states["OK"] and not states["VIOLATION"]


def test_param1_the_rail_may_be_named_by_an_ldos_facts():
    """Same net name, one more fact -- and the same VCC that was UNKNOWN above
    becomes the 3.3 V domain. This is the golden board's actual path."""
    lib = _library(_led_entry(), _ldo_entry())
    model = _led_model(resistor="1kΩ", supply="VCC")
    model.components["U5"] = Component(
        uid="u5", designator="U5", mpn="RT9013-33GB", lcsc_part="C47773",
        pins=[Pin("1", "VIN", "+5V"), Pin("5", "VOUT", "VCC")])
    model.nets["+5V"] = Net("+5V", [("U5", "1")])
    model.nets["VCC"].pins.append(("U5", "5"))
    outcomes = [o for o in LedCurrent(library=lib).outcomes(model)
                if o.subject == "LED1"]
    assert [o.state for o in outcomes] == ["OK"]
    assert any("RT9013-33GB output" in line for line in outcomes[0].evidence)


def test_param1_no_series_resistor_in_the_3v3_domain_is_an_error():
    """0 ohm is a short across the rail: destructive, so ERROR -- while an
    out-of-window value stays WARN. The domain gate still applies: the same
    board with an unnamed rail is UNKNOWN, not a violation."""
    lib = _library(_led_entry())
    rule = LedCurrent(library=lib)
    model = _led_model(resistor=None)
    heat = [o for o in _states(rule, model)["VIOLATION"] if o.subject == "LED1"]
    assert len(heat) == 1 and "no series resistor" in heat[0].message
    assert [f.severity for f in rule.check(model)] == ["ERROR"]

    unnamed = _led_model(resistor=None, supply="VCC")
    assert not _states(rule, unnamed)["VIOLATION"], "no domain, no verdict"


def test_param1_an_led_with_no_shelf_entry_is_still_graded():
    """The verdict is the resistor's value, so the LED's own facts are not
    needed. The previous version was UNKNOWN for every LED without
    ``vf_v``/``if_max_ma`` -- this revision made that case gradeable."""
    lib = _library(_ldo_entry())  # no LED entry on the shelf
    outcomes = [o for o in LedCurrent(library=lib).outcomes(_led_model())
                if o.subject == "LED1"]
    assert [o.state for o in outcomes] == ["OK"]


# ------------------------------------------------- PARAM-2 / PARAM-3


def _divider_model(load_range=(1.0, 2.0), tolerance_entry=True) -> DesignModel:
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value="10kΩ",
        pins=[Pin("1", "A", "+5V"), Pin("2", "B", "TAP")])
    model.components["R2"] = Component(
        uid="r2", designator="R2", value="10kΩ",
        pins=[Pin("1", "A", "TAP"), Pin("2", "B", "GND")])
    model.components["U9"] = Component(
        uid="u9", designator="U9", mpn="LOAD-1", lcsc_part="C9",
        pins=[Pin("3", "EN", "TAP")])
    model.nets = {
        "+5V": Net("+5V", [("R1", "1")]),
        "TAP": Net("TAP", [("R1", "2"), ("R2", "1"), ("U9", "3")]),
        "GND": Net("GND", [("R2", "2")]),
    }
    return model


def _load_entry(v_operating) -> PartEntry:
    return PartEntry(
        key="ic.load", value="LOAD-1", mpn="LOAD-1", lcsc="C9",
        category="ic.mcu",
        facts={"supply_pins": [{
            "pins": ["3"], "name": "EN",
            "v_operating": list(v_operating), "provenance": PROV,
        }]},
    )


def test_param2_a_tap_inside_the_declared_range_is_ok():
    lib = _library(_ldo_entry(), _load_entry((1.0, 3.0)))
    states = _states(DividerOutput(library=lib), _divider_model())
    # 5 V x 10k/20k = 2.5 V; tolerance undeclared on the synthetic parts.
    assert any(o.subject == "U9 pin3" and o.state == "OK"
               for o in states["OK"])


def test_param2_a_tap_outside_the_declared_range_is_a_violation():
    lib = _library(_ldo_entry(), _load_entry((1.0, 2.0)))
    states = _states(DividerOutput(library=lib), _divider_model())
    assert any(o.subject == "U9 pin3" and o.state == "VIOLATION"
               for o in states["VIOLATION"])


def test_param2_an_undeclared_load_range_is_unknown():
    lib = _library(_ldo_entry())  # no entry for the load
    states = _states(DividerOutput(library=lib), _divider_model())
    assert any(o.subject == "U9 pin3" and o.state == "UNKNOWN"
               and "input-range" in o.missing_fact for o in states["UNKNOWN"])


def test_param2_no_divider_on_the_board_is_reported_not_silent():
    lib = _library(_ldo_entry(), _load_entry((1.0, 2.0)))
    states = _states(DividerOutput(library=lib), DesignModel())
    assert any(o.state == "OK" for o in states["OK"])


def test_param3_an_rc_pair_reports_its_cutoff_as_info():
    lib = _library(_ldo_entry())
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value="10kΩ",
        pins=[Pin("1", "A", "SIG"), Pin("2", "B", "MID")])
    model.components["C1"] = Component(
        uid="c1", designator="C1", value="100nF",
        pins=[Pin("1", "A", "MID"), Pin("2", "B", "GND")])
    model.nets = {
        "SIG": Net("SIG", [("R1", "1")]),
        "MID": Net("MID", [("R1", "2"), ("C1", "1")]),
        "GND": Net("GND", [("C1", "2")]),
    }
    rule = RcCutoff(library=lib)
    findings = rule.check(model)
    assert len(findings) == 1 and findings[0].severity == "INFO"
    # 1/(2*pi*10k*100nF) = 159.15 Hz
    assert "fc = 159" in findings[0].message
    states = _states(rule, model)
    # 011e sec.1.1: the number rides in OK. A report-only measurement is not a
    # fault, and the VIOLATION column is what the oracle reads as "wrong".
    assert not states["VIOLATION"]
    reported = [o for o in states["OK"] if "fc =" in o.message]
    assert len(reported) == 1 and reported[0].subject == "R1/C1"


def test_param3_no_rc_pair_is_reported_not_silent():
    lib = _library(_ldo_entry())
    states = _states(RcCutoff(library=lib), DesignModel())
    assert any(o.state == "OK" for o in states["OK"])


# ------------------------------------------------- CONN-usb-cc-pulldown


def _usb_model(r24_value="5.1K", r27_value="5.1K") -> DesignModel:
    model = DesignModel()
    model.components["USB1"] = Component(
        uid="usb", designator="USB1", mpn="TYPE-C 16PIN", lcsc_part="C2765186",
        pins=[Pin("4", "CC2", "NET6"), Pin("10", "CC1", "NET5")])
    model.components["R24"] = Component(
        uid="r24", designator="R24", value=r24_value,
        pins=[Pin("1", "A", "NET5"), Pin("2", "B", "GND")])
    model.components["R27"] = Component(
        uid="r27", designator="R27", value=r27_value,
        pins=[Pin("1", "A", "NET6"), Pin("2", "B", "GND")])
    model.nets = {
        "NET5": Net("NET5", [("USB1", "10"), ("R24", "1")]),
        "NET6": Net("NET6", [("USB1", "4"), ("R27", "1")]),
        "GND": Net("GND", [("R24", "2"), ("R27", "2")]),
    }
    return model


def _usb_entry() -> PartEntry:
    return PartEntry(
        key="conn.type_c", value="TYPE-C", mpn="TYPE-C 16PIN",
        lcsc="C2765186", category="connector",
        facts={"pull_required": [
            {"pin": "4", "to": "GND", "expected_value": "5.1k",
             "provenance": PROV},
            {"pin": "10", "to": "GND", "expected_value": "5.1k",
             "provenance": PROV},
        ]},
    )


def test_usbcc_the_golden_boards_rd_pull_downs_are_ok():
    lib = _library(_usb_entry())
    states = _states(UsbCcPulldown(library=lib), _usb_model())
    ok_subjects = {o.subject for o in states["OK"]}
    assert ok_subjects == {"USB1 pin4", "USB1 pin10"}


def test_usbcc_a_missing_pulldown_is_a_violation():
    lib = _library(_usb_entry())
    model = _usb_model()
    model.components.pop("R27")
    model.nets["NET6"] = Net("NET6", [("USB1", "4")])
    states = _states(UsbCcPulldown(library=lib), model)
    assert any(o.subject == "USB1 pin4" and o.state == "VIOLATION"
               for o in states["VIOLATION"])


def test_usbcc_a_wrong_value_is_a_warn():
    lib = _library(_usb_entry())
    states = _states(UsbCcPulldown(library=lib), _usb_model(r24_value="10K"))
    wrong = [o for o in states["VIOLATION"] if o.subject == "USB1 pin10"]
    assert len(wrong) == 1
    findings = UsbCcPulldown(library=lib).check(_usb_model(r24_value="10K"))
    assert [f.severity for f in findings if "pin10" in f.message] == ["WARN"]


def test_usbcc_an_unparseable_resistor_is_unknown():
    lib = _library(_usb_entry())
    model = _usb_model(r24_value="")
    states = _states(UsbCcPulldown(library=lib), model)
    assert any(o.subject == "USB1 pin10" and o.state == "UNKNOWN"
               for o in states["UNKNOWN"])


def test_usbcc_a_connector_without_requirements_is_not_applicable():
    lib = _library(PartEntry(
        key="conn.other", value="BAR", mpn="BAR", lcsc="C2",
        category="connector"))
    model = DesignModel()
    model.components["J1"] = Component(
        uid="j1", designator="J1", mpn="BAR", lcsc_part="C2",
        pins=[Pin("1", "A", "NET1")])
    model.nets = {"NET1": Net("NET1", [("J1", "1")])}
    states = _states(UsbCcPulldown(library=lib), model)
    assert any(o.subject == "J1" and o.state == "NOT_APPLICABLE"
               for o in states["NOT_APPLICABLE"])


# ------------------------------------------------- golden-board measurement


def test_the_golden_board_matches_the_task_book_expectations():
    """011d sec.3 right column, measured end to end on the real fixture."""
    from boardwise.engines.review import BUILTIN_RULES
    from boardwise.engines.review_eval import load_board_model

    model = load_board_model("tests/fixtures/ch340_golden.epro2")
    by_id = {rule.id: rule for rule in BUILTIN_RULES}
    states = {
        rule_id: _states(rule, model)
        for rule_id, rule in by_id.items()
        if rule_id in (
            "decap-required-caps", "param-led-current",
            "param-value-mpn-match", "conn-usb-cc-pulldown",
        )
    }
    # V3 defect: the mode-sensitive must_connect half fires (WARN).
    v3 = [o for o in states["decap-required-caps"]["VIOLATION"]
          if o.subject == "U1 pin4"]
    assert len(v3) == 1
    # U3's defect: value-vs-MPN -- a signed 011c defect that the 2026-09-21
    # amplitude ruling knowingly waives (1k against 470 is 2.13x, below the
    # 3x R tolerance). The record stays as the oracle signed it; the rule
    # reports OK **with the amplitude and the ruling quoted**, so the waiver
    # is visible on the row rather than inferred from silence.
    u3_violation = [o for o in states["param-value-mpn-match"]["VIOLATION"]
                    if o.subject == "U3"]
    assert u3_violation == []
    u3 = [o for o in states["param-value-mpn-match"]["OK"] if o.subject == "U3"]
    assert len(u3) == 1
    assert "2.13x" in u3[0].message and "015 batch-2" in u3[0].message
    assert "1kΩ" in u3[0].evidence[0]
    # R24/R27 exceptions stay quiet: the pull-down rule says OK.
    assert {o.subject for o in states["conn-usb-cc-pulldown"]["OK"]} == {
        "USB1 pin4", "USB1 pin10",
    }
    assert not states["conn-usb-cc-pulldown"]["VIOLATION"]
    # The LED's series resistance (U3, 1k) sits inside the oracle's 3V3
    # window. The 2026-09-19 revision replaced the current computation, whose
    # verdict here was UNKNOWN -- Vf 2.7-3.2 V straddled the 0.5 mA floor --
    # for a part the oracle had just ruled correct.
    assert any(o.subject == "LED1" and o.state == "OK"
               for o in states["param-led-current"]["OK"])


def test_the_graduation_boards_a2b_seven_are_ok_and_the_rule_has_no_violation_left():
    """Batch 2, measured on the real board it was ruled for.

    The oracle's A2b ruling ("this is not wrong, do not make it so absolute")
    names seven refs: U10/U14 at 2.13x and C28/C29/C36/C42/C44 at 10x-22x.
    All seven must come back OK **quoting their amplitude**, and the rule must
    report no contradiction anywhere on the board -- which is what turns the
    holdout measurement's precision term into zero.
    """
    from boardwise.core.parts import load_parts
    from boardwise.engines.review_eval import load_board_model

    model = load_board_model(
        "tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2"
    )
    rule = ValueMpnMatch(library=load_parts("blocklib/parts.json"))
    states = _states(rule, model)
    assert states["VIOLATION"] == []
    waived = {o.subject: o.message for o in states["OK"]}
    for ref in ("U10", "U14"):
        assert "2.13x" in waived[ref], ref
    for ref in ("C28", "C29", "C36", "C44"):
        assert "22.00x" in waived[ref], ref
    assert "10.00x" in waived["C42"]
    # The message carries the provenance of the waiver, not just the number.
    assert "015 batch-2" in waived["C42"] and "25x tolerance" in waived["C42"]


# ------------------------------------------------- rule-set retirement


def test_decoupling_per_ic_is_retired_from_the_builtin_rules():
    """Oracle ruling 011f B2 ("L1 heuristic limitation, retire in M2") landed
    as task 015 sec.2: the rule leaves ``BUILTIN_RULES`` and the class stays.

    Adding it back to the list is the mutation this test exists to catch.
    """
    from boardwise.engines.review import BUILTIN_RULES
    from boardwise.rules.connectivity import DecouplingPerIC

    ids = [rule.id for rule in BUILTIN_RULES]
    assert "decoupling-per-ic" not in ids
    assert len(ids) == 14
    # Retirement is not deletion: the rule is still importable, still its own
    # id, still runnable on its own (its own tests stay in test_rules.py).
    assert DecouplingPerIC().id == "decoupling-per-ic"
