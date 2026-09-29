"""Tests for the 011d rules: DECAP-1, PARAM-1/2/3/4, CONN-usb-cc (task 011d
secs.3.1-3.5), the facts-schema extension (sec.2), and the golden board's
measured expectations."""

from __future__ import annotations

import time

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
    mpn_resistance_candidates,
    mpn_resistance_readings,
    mpn_value_code,
    mpn_value_code_anchor,
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
    """Outcome states for one model — or, for a project, for **each board** (040b).

    A rule judges one netlist, so on a multi-board project it is run per board and
    the rows are concatenated; a ref that exists on two boards appears on both,
    which is what the assertions below want (every placement must be waived).
    """
    boards = getattr(model, "boards", None) or [model]
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for board_model in boards:
        for outcome in rule.outcomes(board_model):
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


def test_the_capacitance_parser_reads_the_greek_mu_spelling():
    """Task 055: MICRO SIGN and GREEK SMALL LETTER MU are one unit to a reader
    and two code points to Python.

    ``re.IGNORECASE`` folds them together (both casefold to U+03BC), so the
    Greek spelling *matched* the pattern and then reached the unit map as a key
    it did not hold — ``KeyError: 'μf'`` out of the decap rule, where the
    contract is "unreadable -> None". All three spellings below are what a
    keyboard or an IME produces for the same capacitor value.
    """
    assert parse_capacitance_farads("22\u03bcF") == pytest.approx(2.2e-5)
    assert parse_capacitance_farads("4.7\u03bcF") == pytest.approx(4.7e-6)
    assert parse_capacitance_farads("4.7\u03bcf") == pytest.approx(4.7e-6)
    # The same unit spelled with the capital mu, and with the micro sign.
    assert parse_capacitance_farads("22\u039cF") == pytest.approx(2.2e-5)
    assert parse_capacitance_farads("22\u00b5F") == pytest.approx(2.2e-5)
    # The unit letter is still required: a Greek mu alone is a bare number.
    assert parse_capacitance_farads("4.7\u03bc") is None


def test_the_capacitance_parser_returns_none_for_units_it_does_not_read():
    """The parser answers, it never raises (task 055): what it cannot read is
    None — a rule reporting UNKNOWN is an answer, a traceback out of the review
    path is not. The unit map's own totality is pinned by the Greek-mu cases
    above, whose spelling reaches the lookup and must not find a ``KeyError``."""
    for spelling in ("22uFarad", "22F", "22kF", "F", "22", ""):
        assert parse_capacitance_farads(spelling) is None


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


def test_the_mid_letter_resistance_notation_decodes():
    """Task 043: the trade prints a multiplier *inside* the value.

    ``4K7`` is 4.7 kΩ, ``4R7`` is 4.7 Ω, ``10K2`` is 10.2 kΩ, ``1M0`` is 1 MΩ —
    and the EIA three-digit reader used to mine a *wrong code* out of that shape
    (``RC0603FR-074K7L`` came back as ``074`` = 70 kΩ, which is the WARN 043 was
    filed for). These are the readings the decoder must produce, in ohms.
    """
    def values(mpn: str) -> list[float]:
        return [value for value, _notation in mpn_resistance_readings(mpn)]

    assert values("4K7") == [4700.0]
    assert values("4R7") == [4.7]
    assert values("10K2") == [10200.0]
    assert values("1M0") == [1000000.0]
    assert values("200K") == [200000.0]
    assert values("4R70") == [4.7]
    assert values("R47") == []
    # 071 §4: a letter with no digit run in front of it states no value at all
    # (`R47` is a series' own numbering), so this reading is gone. The board-side
    # spelling ``R47`` = 0.47 Ω is read by `parse_resistance_ohms`'s board
    # grammar, which is a different question from "what does this MPN say".
    assert values("2R2") == [2.2]
    assert 47400.0 in values("47K4")    # two readings; see the case below
    # The vendor-prefix case, verbatim: Yageo's `-07` is a coding, and by shape it
    # reads as a longer mantissa. Both readings are legitimate, so both are
    # returned and the rule lets the board's own value choose.
    assert mpn_resistance_readings("RC0603FR-074K7L") == [
        (4700.0, "4K7"), (74700.0, "74K7"),
    ]
    assert mpn_resistance_readings("RC0603FR-07200KL") == [(200000.0, "200K")]
    assert values("RCA03392KFLF") == [2000.0, 92000.0, 392000.0]
    assert mpn_resistance_readings("FRC0805F4R70TS") == [(4.7, "4R70")]


def test_the_mid_letter_decoder_refuses_what_it_cannot_read():
    """The refusals are as important as the readings (043): a guess here becomes
    a false BOM contradiction, which is exactly what the batch was filed for.

    * the **shunt** convention (``R005``/``R100``/``3R005``) writes thousandths
      with the coding digits in front of the ``R`` — ``JER2512F3R005`` is a 5 mΩ
      part, and reading it as 3.005 Ω would turn a correct board into a
      violation. It stays UNKNOWN, as before 043;
    * lowercase ``m`` (milli in some houses, mega in others);
    * an MPN that states its value in EIA three-digit form has *no* mid-letter
      reading at all — that path is untouched;
    * a zero-ohm reading is not evidence of anything.
    """
    assert mpn_resistance_readings("RE2512F3R001") == []
    assert mpn_resistance_readings("JER2512F3R005") == []
    assert mpn_resistance_readings("RE1206F1R000") == []
    assert mpn_resistance_readings("RE1206F1R100") == []
    assert mpn_resistance_readings("1m0") == []
    assert mpn_resistance_readings("0R0") == []
    assert mpn_resistance_readings("") == []
    # EIA-only MPNs: the decoder that owns them is `mpn_value_code`, unchanged.
    assert mpn_resistance_readings("FRC0805J471 TS") == []
    assert mpn_value_code("FRC0805J471 TS") == "471"
    # A capacitor MPN can contain mid-letter-looking groups (X7R9 reads as 7.9 Ω),
    # which is why only a caller that already knows the part is a resistor may
    # consult this decoder — the rule gates on `_kind_of` before calling it.
    assert mpn_resistance_readings("CC0603KRX7R9BB104")


def test_the_letter_exponent_field_is_read_as_a_low_ohm_reading():
    """Task 046 G1: 厚声 prints a ≤±1% part's resistance as three figures plus an
    exponent *character*, and the small exponents are letters — ``J`` = 10^-1,
    ``K`` = 10^-2. So ``0603WAF220KT5E`` (verified 2.2 Ω ±1% on the LCSC product
    page) is ``220 x 10^-2``, and the mid-letter reader's ``220K`` = 220 kΩ /
    ``20K`` = 20 kΩ are both wrong for it: the rule quoted "decodes to 2e+04 Ω"
    for a board that correctly declares 2.2 Ω.

    The reading is **added**, not swapped in: shape-wise the same characters
    really are the mid-letter notation too, so the set keeps both and the board's
    own value chooses (043's doctrine). ``0603WAF330JT5E`` is the neighbour that
    pins the other exponent letter at 33 Ω — it read as 33 Ω through the EIA code
    before this change and must not drift.
    """
    def values(mpn: str) -> list[float]:
        return [value for value, _notation in mpn_resistance_readings(mpn)]

    assert mpn_resistance_readings("0603WAF220KT5E") == [
        (2.2, "220K (letter-exponent field)"),
        (20000.0, "20K"),
        (220000.0, "220K"),
    ]
    assert mpn_resistance_readings("0603WAF330JT5E") == [
        (33.0, "330J (letter-exponent field)"),
    ]
    # The size head is the whole guard, and this is its exclusive witness: the
    # same field without one is not read (it is not a part number this house
    # prints), so dropping the head requirement turns this line red.
    assert 2.2 not in values("WAF220KT5E")
    # The *numeric* exponent family (`1002` = 100 x 10^2 = 10 kΩ) is a sibling
    # judgment with its own witness — task 048, the test below. What this shape
    # owns is the **letter** alphabet, and the notation text says which reader
    # spoke: widening this regex to digits would relabel 048's readings.
    assert mpn_resistance_readings("0603WAF220KT5E")[0][1] == (
        "220K (letter-exponent field)"
    )


def test_the_numeric_exponent_field_is_read():
    """Task 048: the same 厚声 ordering field as 046's ``220K``, with a **digit**
    exponent instead of a letter — three significant figures and a power of ten.
    ``0603WAF1002T5E`` is 100 x 10^2 = 10 kΩ and ``0805W8F1003T5E`` is
    100 x 10^3 = 100 kΩ; before this reading existed both came back UNKNOWN
    ("contains no decodable EIA value code"), which is the plate of UNKNOWNs
    046's own report left open on the two 毕设 boards.

    The 5% (E-24) members of the family put a ``0`` in front of the two
    significant figures — ``0805W8J0103T5E`` = 010 x 10^3 = 10 kΩ is the worked
    example in the ordering rule — and the same reading handles them, because a
    leading zero leaves the significand unchanged.
    """
    def values(mpn: str) -> list[float]:
        return [value for value, _notation in mpn_resistance_readings(mpn)]

    assert mpn_resistance_readings("0603WAF1002T5E") == [
        (10000.0, "1002 (numeric-exponent field)"),
    ]
    assert mpn_resistance_readings("0805W8F1003T5E") == [
        (100000.0, "1003 (numeric-exponent field)"),
    ]
    # The 5% form: `0` prefix, two significant figures, digit exponent.
    assert mpn_resistance_readings("0805W8J0103T5E") == [
        (10000.0, "0103 (numeric-exponent field)"),
    ]
    assert mpn_resistance_readings("0805W8J0100T5E") == [
        (10.0, "0100 (numeric-exponent field)"),
    ]
    assert values("0603WAJ0122T5E") == [1200.0]
    # The size head is this shape's guard too, and the exclusive witness for it:
    # the same field without a head is not a part number this house prints.
    assert values("WAF1002T5E") == []
    # ...and the tape suffix is part of the shape: `0603WAF1002` (no tail) is a
    # plain four-figure E-96 reading, which the E-96 reader owns.
    assert mpn_resistance_readings("0603WAF1002") == [(10000.0, "1002 (E-96)")]
    # A zero-ohm jumper reads as nothing (a zero reading is not evidence).
    assert values("0603WAF0000T5E") == []
    # **Overlap with `_e96_reading` (task 048's analysis, pinned):** the two
    # shapes cannot both fire on this family, because this one requires the token
    # to end in `T<tape code>` while E-96 requires it to end in four figures. The
    # proof is the notation text — no E-96 label appears on a `...T5E` token even
    # though `1003` would be a legal E-96 code.
    assert not [
        text for _value, text in mpn_resistance_readings("0805W8F1003T5E")
        if "(E-96)" in text
    ]
    # Where both *could* read the same token they agree, so the value-keyed
    # dedup in the readings set has nothing to arbitrate: `1003` = 100 x 10^3 by
    # either convention.
    assert values("0805W8F1003") == [100000.0]
    # Untouched: the 046 letter alphabet, and a capacitor MPN whose `1608` is not
    # a size head at all (the shape cannot swallow it).
    assert (2.2, "220K (letter-exponent field)") in mpn_resistance_readings(
        "0603WAF220KT5E"
    )
    assert mpn_resistance_readings("C1608X5R1V225KT000E") == [
        (5.1, "5R1"), (5000.0, "5K"), (25000.0, "25K"), (225000.0, "225K"),
    ]
    # The rule-level conversion this exists for: the 毕设FOC board's R20/R23
    # declare 100 kΩ against this MPN and used to be UNKNOWN -- now an OK row
    # quoting the field the reader saw.
    lib = _library(_ldo_entry())
    model = DesignModel()
    for ref in ("R20", "R23"):
        model.components[ref] = Component(
            uid=ref.lower(), designator=ref, value="100kΩ",
            mpn="0805W8F1003T5E", pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert states["VIOLATION"] == [] and states["UNKNOWN"] == []
    assert sorted(o.subject for o in states["OK"]) == ["R20", "R23"]
    assert all("1003" in o.message for o in states["OK"])


def test_the_e96_four_figure_code_is_read():
    """Task 046 G2: the E-96 four-figure code (three significant figures plus a
    power of ten) at the end of a token. Viking's ``AR03BTCX5001`` is a 5.00 kΩ
    part, and ``5001`` is the code; before this reading existed the mid-letter
    reader's ``R03`` = 0.03 Ω was the only thing the rule could quote (it asked
    how a board declaring 5 kΩ could be 166666x off).

    The four-figure package guard is its own list (2512 included, which the
    three-figure guard never needed) and the leading-zero rule is separate —
    each has its witness below, so neither can be dropped silently.
    """
    def values(mpn: str) -> list[float]:
        return [value for value, _notation in mpn_resistance_readings(mpn)]

    # 071 §4: the mid-letter `R03` reading is gone (a series-name letter with no
    # mantissa), so the E-96 code is the token's only reading -- which is exactly
    # what the board's 5 kΩ is compared against.
    assert mpn_resistance_readings("AR03BTCX5001") == [
        (5000.0, "5001 (E-96)"),
    ]
    # A group that completes a size is a size: 1206 / 2512 would read as 120 MΩ
    # / 251 GΩ without the guard. Since 071 §4 the `R03` reading is gone as well,
    # so the witness is "no reading at all" -- and it still fails if the guard
    # goes (the group would come back as 1.2e8 / 2.51e11).
    assert values("AR03BTCX1206") == []
    assert values("AR03BTCX2512") == []
    # A leading zero is not a significant figure.
    assert values("AR03BTCX0500") == []
    # The group has to be a whole run at the token's end: `...05001`'s tail is
    # not a code of its own (the lookbehind), and a longer run is not read.
    assert values("AR03BTCX05001") == []
    # A single tolerance letter after the figures is part of the shape.
    assert (5000.0, "5001 (E-96)") in mpn_resistance_readings("AR03BTCX5001F")


def test_a_polymer_electrolytic_mpn_is_not_read_as_a_capacitor_code():
    """Task 046 G3: Aishi's ``SPZ``/``SPA`` polymer parts print their capacitance
    in **microfarads** — ``SPZ1HM100E07O00RAXXX`` is a 10 µF part, and the EIA
    path (whose capacitor base unit is the picofarad) read its ``100`` as 10 pF.

    The capacitor path returns a single code, so there is no reading *set* to add
    the right value to: the honest answer is to refuse the token, which the rule
    reports as UNKNOWN, never as a contradiction. The series prefix is the guard
    and this MPN is its exclusive witness; the ordinary EIA capacitor code is
    untouched right below it.
    """
    assert mpn_value_code("SPZ1HM100E07O00RAXXX") is None
    assert mpn_value_code("SPZ0J101E05O00RAXXX") is None
    # Unchanged: a plain three-figure capacitor code is still read.
    assert mpn_value_code("CC0603KRX7R9BB104") == "104"
    # ...and at the rule level the part is UNKNOWN, never a VIOLATION -- which
    # is the whole point of the oracle's exception ruling.
    lib = _library(_ldo_entry())
    model = DesignModel()
    model.components["C71"] = Component(
        uid="c71", designator="C71", value="10uF",
        mpn="SPZ1HM100E07O00RAXXX", pins=[Pin("1", "A", "VCC")])
    # The real board's C71/C72 carry the MPN and an *empty* value, so they are
    # skipped outright (no kind evidence -- the pre-existing behaviour that 046
    # does not change, and the reason these two never reached the eval).
    model.components["C72"] = Component(
        uid="c72", designator="C72", value="",
        mpn="SPZ1HM100E07O00RAXXX", pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert states["VIOLATION"] == []
    assert {o.subject for o in states["UNKNOWN"]} == {"C71"}
    assert all(o.subject != "C72" for o in states["OK"])


def test_an_electrolytic_voltage_code_before_the_value_is_not_an_eia_code():
    """Issue 18: ``ERR1VM101E07OT`` is a 100 µF aluminium electrolytic whose
    code reads ``1V`` (the trade's voltage code, 35 V on the supplier's own
    entry) + ``M`` (±20 %) + ``101`` (100 µF, the capacitance **in
    microfarads**). The electrolytic guard knew only a printed voltage
    (``50V330``) and a case size (``10x15``), so this shape slipped past it and
    the ``101`` was read against the picofarad base as 100 pF — turning the
    board's correct 100 µF declaration into a BOM contradiction.

    The refusal is of the whole token, and the tolerance letter is pinned to
    the trade's ``[MKGJT]``: a letter-blind class would swallow the ceramic
    witnesses below as well (``...R9BB104`` reads as ``9BB104``). Each voltage
    code and tolerance letter here decodes to a wrong code without the guard,
    and none of them is caught by the other three guards — which is what makes
    a mutation in this branch visible.
    """
    assert mpn_value_code("ERR1VM101E07OT") is None
    # The family: the voltage code varies (0J / 1C / 1E / 1H / 1V / 2A, 1V
    # being the 35 V above), and so does the tolerance letter.
    assert mpn_value_code("ERR0JM101E07OT") is None
    assert mpn_value_code("ERR1CM221E11OT") is None
    assert mpn_value_code("ERR1EM471E13OT") is None
    assert mpn_value_code("ERR1HM102E16OT") is None
    assert mpn_value_code("ERR2AM101E07OT") is None
    assert mpn_value_code("ERR1VK471E13OT") is None
    assert mpn_value_code("ERR1VJ101E07OT") is None
    assert mpn_value_code("ERR1VG220E11OT") is None
    # The ceramic parts whose EIA code sits behind a dielectric run keep being
    # read — refusing them is the regression the tolerance class prevents.
    assert mpn_value_code("CC0603KRX7R9BB104") == "104"
    assert mpn_value_code("CC0805KRX7R9BB104") == "104"
    assert mpn_value_code("CC0603KRX7R9BB103") == "103"
    assert mpn_value_code("CC0402JRNPO9BN300") == "300"
    assert mpn_value_code("CC0603JRNPO9BN560") == "560"
    assert mpn_value_code("CL10A225KA8NNNC") == "225"
    assert mpn_value_code("GRM1885C1H122JA01D") == "122"


def test_the_shunt_field_between_a_tolerance_letter_and_r():
    """Task 046 G4: ``FRL1210FR400TS`` (FOJAN, verified 400 mΩ ±1%) writes its
    fraction right after the ``R`` with the tolerance letter in front — ``FR400``
    — so the shape is ``<tolerance letter>R<digits>`` and the value is
    ``digits / 10^len``. The EIA path used to read the ``400`` as 40 Ω, and the
    ``R``-as-decimal-point guard could not stop it because the character in front
    of the ``R`` is a letter, not a digit.

    Three neighbours pin the guard's edges: ``AR03BTCX5001`` (``A`` is not a
    tolerance letter), ``RC0603FR-074K7L`` (that ``R`` is followed by a dash) and
    ``JER2512F3R005`` (a digit in front of the ``R`` — 043's refusal, which stays
    a refusal).
    """
    assert mpn_resistance_readings("FRL1210FR400TS") == [
        (0.4, "FR400 (shunt field)"),
    ]
    # The EIA reader must not mine the `400` out of that field either.
    assert mpn_value_code("FRL1210FR400TS") is None
    # Neighbours, unchanged except where 071 §4 removed a reading of its own:
    # `AR03BTCX5001`'s `R03` = 0.03 Ω was a series name, not a value, so its only
    # reading now is the E-96 one.
    assert mpn_resistance_readings("AR03BTCX5001") == [
        (5000.0, "5001 (E-96)"),
    ]
    assert mpn_resistance_readings("RC0603FR-074K7L") == [
        (4700.0, "4K7"), (74700.0, "74K7"),
    ]
    assert mpn_resistance_readings("JER2512F3R005") == []
    assert mpn_value_code("JER2512F3R005") is None
    # The rule reads the board's 400 mΩ against it: the FPC board's R1 is this
    # part, and the pcb view's `40 Ω` was the decoder's error, not the board's.
    lib = _library(_ldo_entry())
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value="400mΩ",
        mpn="FRL1210FR400TS", pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert states["VIOLATION"] == [] and states["UNKNOWN"] == []
    (ok,) = states["OK"]
    assert ok.subject == "R1" and "0.4" in ok.message


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
    so it stays the WARN it always was -- now with the amplitude and the anchor
    quoted.

    The anchor is what 071 §1 C added to this row: ``FRC0805J471 TS`` states its
    size (``0805``) in the same token, so the three digits are a code field and
    the reading may accuse the BOM line. Without it the same ratio would be
    UNKNOWN -- the amplitude and the ruling are quoted either way, which is what
    keeps both rows auditable rather than silent."""
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["U3"] = Component(
        uid="u3", designator="U3", value="4.7kΩ",
        mpn="FRC0805J471 TS", lcsc_part="C2907329",
        pins=[Pin("1", "A", "VCC")],
    )
    rule = ValueMpnMatch(library=lib)
    (finding,) = rule.check(model)
    assert finding.severity == "WARN"
    assert finding.target is not None and finding.target.component_ref == "U3"
    states = _states(rule, model)
    assert states["UNKNOWN"] == []
    (violation,) = states["VIOLATION"]
    assert violation.subject == "U3"
    assert "470" in violation.message and "4700" in violation.message
    assert "10.00x apart" in violation.message
    assert "3x tolerance" in violation.message
    assert "锚点：值码带封装语境" in violation.message


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
    OK (the graduation board's five), and 25x -- at the tolerance -- is the
    boundary. 071 §1 moved that row's *state* (VIOLATION -> UNKNOWN) and left
    the arithmetic alone, which is what this test pins: the three OK rows keep
    their amplitudes and so does the withheld one.

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
    assert states["VIOLATION"] == []
    (unknown,) = [o for o in states["UNKNOWN"] if o.subject == "C37"]
    assert "25.00x apart" in unknown.message


def test_param4_a_mid_letter_mpn_matches_the_board_value():
    """Task 043's own case: the 高速板's R27.

    ``RC0603FR-074K7L`` states 4.7 kΩ in the mid-letter notation, the board says
    ``4.7kΩ``, and before 043 the EIA reader mined ``074`` out of that MPN and
    reported a 14.89x contradiction. The row is now OK, names the notation it
    read, and carries the MPN's *other* legitimate reading as evidence (by shape
    ``74K7`` is readable too, and a reader has to be able to see that).
    """
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R27"] = Component(
        uid="r27", designator="R27", value="4.7kΩ", mpn="RC0603FR-074K7L",
        pins=[Pin("1", "A", "VCC")])
    rule = ValueMpnMatch(library=lib)
    assert rule.check(model) == [], "043: no WARN for a matching mid-letter MPN"
    states = _states(rule, model)
    assert states["VIOLATION"] == [] and states["UNKNOWN"] == []
    (ok,) = states["OK"]
    assert ok.subject == "R27"
    assert "4700" in ok.message and "'4K7'" in ok.message
    assert any("74700" in line and "74K7" in line for line in ok.evidence), ok.evidence


def test_param4_a_mid_letter_mpn_that_really_disagrees_is_still_a_violation():
    """The other half: the widened reader must not turn a real BOM mismatch into
    silence. The comparison is made against the **closest** of the MPN's readings
    — the most favourable one, which is what keeps the amplitude doctrine's
    "don't kill it dead" behaviour (2026-09-21) intact — so 1 MΩ against a part
    whose readings are 4.7 kΩ / 74.7 kΩ is a WARN quoting the closer of the two
    and naming every reading it could have been.

    The anchor is why this row may speak (071 §1 C): ``074K7``'s longest reading
    is the notation as written (the shorter ``4K7`` is the vendor-prefix guess),
    so the reading the comparison lands on is a code field.
    """
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R27"] = Component(
        uid="r27", designator="R27", value="1MΩ", mpn="RC0603FR-074K7L",
        pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    (violation,) = states["VIOLATION"]
    assert violation.subject == "R27"
    assert "13.39x apart" in violation.message
    assert "锚点：中缀正规形" in violation.message
    assert any("74K7" in line and "4K7" in line for line in violation.evidence), (
        "the violation quotes all the readings it could have been"
    )


def test_param4_a_big_enough_gap_against_an_ambiguous_mpn_is_still_waived():
    """The amplitude path applies to the closest reading, so a 100 kΩ declared
    against a `{4.7k, 74.7k}` MPN lands on "1.34x, below the 3x tolerance" — an OK
    row that quotes both numbers, exactly as the ruling asks. Pinned because the
    alternative (measuring against the *first* reading) would fire a WARN here.
    """
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["R27"] = Component(
        uid="r27", designator="R27", value="100kΩ", mpn="RC0603FR-074K7L",
        pins=[Pin("1", "A", "VCC")])
    states = _states(ValueMpnMatch(library=lib), model)
    assert states["VIOLATION"] == []
    (ok,) = states["OK"]
    assert "1.34x" in ok.message
    assert any("74K7" in line for line in ok.evidence)


def test_param4_the_two_tolerances_are_not_swapped_at_their_boundaries():
    """3x exactly lands on the violation side ("ratio >= threshold"), and the same
    ratio is a long way under the capacitor tolerance -- the boundary test that
    keeps the two constants from being swapped. 071 §1 C left both arithmetic
    paths exactly where they were and split the two rows by *anchor* instead
    (see the assertions below)."""
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
    # Two rows at their tolerance boundaries, and 071 §1 C splits them by anchor
    # rather than by kind: `FRC0805J102 TS` states its size (0805 -> ③) and warns,
    # while `CL10B104KB8NNNC` states no size at all -- its `104` is three digits
    # in a string, so 25x is withheld. The arithmetic is identical in both.
    violations = {o.subject: o.message for o in states["VIOLATION"]}
    assert sorted(violations) == ["R9"]
    assert "3.00x apart" in violations["R9"]
    withheld = {o.subject: o.message for o in states["UNKNOWN"]}
    assert sorted(withheld) == ["C9"]
    assert "25.00x apart" in withheld["C9"]
    assert any(o.subject == "C10" for o in states["OK"])


def test_param4_a_zero_side_leaves_the_ratio_undefined_and_stays_a_violation():
    """``min <= 0``: 0/0 and x/0 are not amplitudes. A 0-ohm value against a
    470-ohm MPN still contradicts, and the message says why it was not
    waived instead of inventing a ratio (071 §1 C: the reading is anchored, so
    the row may say so out loud)."""
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
    # 071 §1 C keeps that row a WARN (the MPN states its size, `0805`) while the
    # three refused tokens above are UNKNOWN, so the two families meet here and
    # are told apart by their own messages.
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
    assert "U11" not in unknown
    assert "U10" not in unknown, "a decoded code is judged, never refused"
    assert any(o.subject == "U10" for o in states["OK"])
    refused = next(o for o in states["UNKNOWN"] if o.subject == "R43")
    assert "contains no decodable EIA value code" in refused.message


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


def test_param4_an_electrolytic_mpn_is_unknown_not_a_contradiction():
    """Issue 18, at the rule level: the board's 100 µF electrolytic (value
    ``100uF``, MPN ``ERR1VM101E07OT``) reports UNKNOWN and raises nothing —
    the 100 pF the decoder used to read out of that MPN is the artifact, not
    the board's value.

    The same decision as 015's ``PA50V330M…`` electrolytics and 046's polymer
    series: a token written in a notation this decoder does not read is
    refused as a whole, and the rule says "not a notation I read" instead of
    guessing a value out of its digits.
    """
    lib = _library(_ldo_entry(), _uart_entry())
    model = DesignModel()
    model.components["C1"] = Component(
        uid="c1", designator="C1", value="100uF", mpn="ERR1VM101E07OT",
        pins=[Pin("1", "A", "VCC")])
    rule = ValueMpnMatch(library=lib)
    states = _states(rule, model)
    assert states["VIOLATION"] == []
    assert rule.check(model) == []
    (unknown,) = states["UNKNOWN"]
    assert unknown.subject == "C1"
    assert "notation that is not EIA" in unknown.message


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


def _usb_model_with_the_socket_grounded():
    """The FPC board's shape (049 P3): the socket has a foot on each of the two
    nets — its CC pin on the CC net, its GND pin on ``GND`` — and it comes first
    in the net's member order, ahead of the real pull-down."""
    model = _usb_model()
    model.components["USB1"].pins.append(Pin("1", "GND", "GND"))
    model.nets["GND"].pins.insert(0, ("USB1", "1"))
    return model


def test_usbcc_the_sockets_own_gnd_foot_does_not_shadow_the_pulldown():
    """049 P3, the 017 leftover: "a part with a foot on both nets" used to be the
    whole resistor test, and the socket satisfies it by construction. Whenever it
    came first, the real pull-down's value was never read and the rule could only
    answer UNKNOWN — measured on the FPC board, whose R24/R27 are 5.1K exactly as
    declared.
    """
    lib = _library(_usb_entry())
    rule = UsbCcPulldown(library=lib)
    model = _usb_model_with_the_socket_grounded()

    assert rule._resistance_to(model, "NET5", "GND") == (5100.0, "R24")
    assert rule._resistance_to(model, "NET6", "GND") == (5100.0, "R27")

    states = _states(rule, model)
    assert {o.subject for o in states["OK"]} == {"USB1 pin4", "USB1 pin10"}
    assert not states["VIOLATION"] and not states["UNKNOWN"]
    assert all("R24" in o.message or "R27" in o.message for o in states["OK"])


def test_usbcc_a_connector_alone_stays_the_unreadable_candidate():
    """With nothing resistor-like on the net, the socket keeps the *old* reading.

    The caller turns "no candidate at all" into an ERROR, so filling that branch
    from a bridging non-resistor would report the model's own duplicate-name
    artifact as a board defect — measured 2026-09-27 on the injected
    ``duplicate-designator`` board, where the duplicate name makes the model keep
    the other page's R24 and the CC net reads as having no resistor at all.
    """
    lib = _library(_usb_entry())
    rule = UsbCcPulldown(library=lib)
    model = _usb_model_with_the_socket_grounded()
    model.components.pop("R24")
    model.nets["NET5"] = Net("NET5", [("USB1", "10")])

    assert rule._resistance_to(model, "NET5", "GND") == (None, "USB1")
    states = _states(rule, model)
    assert [o.subject for o in states["UNKNOWN"]] == ["USB1 pin10"]
    assert not [o for o in states["VIOLATION"] if o.subject == "USB1 pin10"]


def test_usbcc_a_capacitor_on_the_net_is_not_read_as_the_resistor():
    """A declared non-resistor is never the answer, whatever its value parses to."""
    lib = _library(_usb_entry(), PartEntry(
        key="cap.c0g", value="C", mpn="CAP-1", lcsc="C3", category="capacitor"))
    rule = UsbCcPulldown(library=lib)
    model = _usb_model()
    model.components["C40"] = Component(
        uid="c40", designator="C40", value="1uF", mpn="CAP-1", lcsc_part="C3",
        pins=[Pin("1", "A", "NET5"), Pin("2", "B", "GND")])
    model.nets["NET5"].pins.insert(0, ("C40", "1"))
    model.nets["GND"].pins.append(("C40", "2"))

    assert rule._resistance_to(model, "NET5", "GND") == (5100.0, "R24")


def test_the_fpc_boards_cc_pulldowns_are_ok_with_the_socket_on_both_nets():
    """The 017 leftover, closed on the real holdout board (049 P3)."""
    from boardwise.core.parts import load_parts
    from boardwise.engines.review_eval import load_board_model

    model = load_board_model("tests/fixtures/FPC触屏游戏机_2026-09-27.epro2")
    rule = UsbCcPulldown(library=load_parts("blocklib/parts.json"))
    states = _states(rule, model)
    assert {o.subject for o in states["OK"]} == {"USB1 pin4", "USB1 pin10"}
    assert not states["VIOLATION"] and not states["UNKNOWN"]
    assert sorted(o.message.split(":")[1].strip().split()[0]
                  for o in states["OK"]) == ["R24", "R27"]


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


# ---------------------------------------------- 071: the MPN bleed-stop batch


def _one_part(kind: str, value: str, mpn: str):
    """One component on its own board, with the shelf's kind left to the value."""
    model = DesignModel()
    designator = "R1" if kind == "resistor" else "C1"
    model.components[designator] = Component(
        uid=designator.lower(), designator=designator, value=value, mpn=mpn,
        pins=[Pin("1", "A", "VCC")],
    )
    return model, designator


def _state_of(kind: str, value: str, mpn: str) -> tuple[str, list[object]]:
    model, designator = _one_part(kind, value, mpn)
    rule = ValueMpnMatch(library=_library(_ldo_entry(), _uart_entry()))
    states = _states(rule, model)
    for state, rows in states.items():
        if any(o.subject == designator for o in rows):
            return state, rows
    return "<no row>", []


def test_071_the_metric_size_code_is_not_a_value_code():
    """Issue #22: ``GRM188R71C104KA01D`` is a 100 nF capacitor whose ``188`` is
    the metric size (1.6x0.8 mm), not a value.

    Read as a value it put two candidates in the EIA reader's list, ambiguity
    turned the whole token into None, and the rule reported "contains no
    decodable value code" for a part the board declares correctly -- a *silent
    miss* dressed up as honesty. The size code is grammar (071 §3①): the metric
    sizes are a finite industry list, and a token states its size once, at the
    front.
    """
    assert mpn_value_code("GRM188R71C104KA01D") == "104"
    # The value code sharing a metric size's spelling is not touched as long as
    # it is not the token's *leading* field: `CL10A105KA8NNNC` is 1 uF and 105
    # is also the 0402 metric size.
    assert mpn_value_code("CL10A105KA8NNNC") == "105"
    assert mpn_value_code("CL10B105KA8NNNC") == "105"
    assert mpn_value_code("GRM1885C1H122JA01D") == "122"
    assert mpn_value_code("CC0603KRX7R9BB104") == "104"
    # At the rule level the miss becomes a verdict it can state: 100 nF declared
    # and 104 in the MPN agree.
    state, rows = _state_of("capacitor", "100nF", "GRM188R71C104KA01D")
    assert state == "OK", rows
    assert "0.0000001" in rows[0].message or "1e-07" in rows[0].message
    # ...and a part that really disagrees is an honest WARN: the token states its
    # size (`188` -> anchor ③), 100 uF against the code's 100 nF is 1000x, far
    # past the 25x capacitor tolerance.
    state, rows = _state_of("capacitor", "100uF", "GRM188R71C104KA01D")
    assert state == "VIOLATION", rows
    assert "锚点：值码带封装语境" in rows[0].message


def test_071_a_board_value_in_the_mid_letter_notation_is_read():
    """Issue #23: ``4K7`` is 4.7 kΩ, and the board side could not read it.

    The two parsers disagreed about one notation: the MPN decoder knew
    ``4K7``/``1K0``/``2M2``/``100R`` (task 043) and the board parser did not, so
    a rule handed a value it could not read skipped the part outright -- no row
    at all, which is worse than a UNKNOWN. 071 §2 merged them into one
    implementation in `rules/values.py`.
    """
    from boardwise.rules.connectivity import parse_resistance_ohms

    for text, ohms in (("4K7", 4700.0), ("1K0", 1000.0), ("2M2", 2.2e6), ("100R", 100.0)):
        assert parse_resistance_ohms(text) == pytest.approx(ohms)
    assert mpn_resistance_readings("4K7") == [(4700.0, "4K7")]
    state, rows = _state_of("resistor", "4K7", "RC0603FR-074K7L")
    assert state == "OK", rows
    # The reverse example the task book named: `0R5` was already the board
    # grammar's 0.5 Ω (R as the decimal point) and keeps it -- that branch runs
    # first, which is also what keeps `4.7kΩ` at 4700 instead of the mid-letter
    # reader's 7000.
    assert parse_resistance_ohms("0R5") == 0.5
    assert parse_resistance_ohms("4.7kΩ") == 4700.0
    assert mpn_resistance_readings("0R5") == []


def test_071_a_package_size_prefix_is_not_a_mantissa():
    """Issue #24: the digit run in front of a letter may head with the size.

    ``CRCW0603``10K0FKEA is a 10.0 kΩ part, and read whole its run spells
    ``060310``: as a mantissa that is ``310K0`` = 310 kΩ, a reading that crosses
    the size field into the value field. A board declaring 310K **passed** on it
    -- a false pass built on a reading that is not a code field. The size comes
    off first (071 §3②), the true reading survives, and a board that really
    disagrees now gets an honest WARN (071 §1 C: the canonical mid-letter form is
    an anchor).
    """
    assert mpn_resistance_readings("CRCW060310K0FKEA") == [(10000.0, "10K0")]
    state, rows = _state_of("resistor", "310kΩ", "CRCW060310K0FKEA")
    assert state == "VIOLATION", rows
    assert "1e+04" in rows[0].message, "the row quotes the true reading, not 310 kΩ"
    assert "锚点：中缀正规形" in rows[0].message
    state, _rows = _state_of("resistor", "10kΩ", "CRCW060310K0FKEA")
    assert state == "OK"
    # The second witness of the same issue, and of anchor ①: KOA's E-96 field
    # with its tolerance letter.
    assert mpn_resistance_readings("RK73H1JTTD1002F") == [(10000.0, "1002 (E-96)")]
    state, rows = _state_of("resistor", "47kΩ", "RK73H1JTTD1002F")
    assert state == "VIOLATION" and "锚点：值码带相邻容差字母" in rows[0].message


def test_071_a_series_name_letter_states_no_value():
    """Issue #26: a letter with no digit run in front of it is a series name.

    ``WR06X1002FTL``'s ``R06`` was read as 0.06 Ω and ``GRM188R71C104KA01D``'s
    ``R71`` as 0.71 Ω -- in both cases the series' own letter followed by the
    series' numbering, and the digits that follow belong to another field
    (``1002`` is an E-96 code no reader owns yet, ``104`` is the value code).
    A letter right after a letter is the same case, because the digit run before
    the letter is then empty by construction (071 §4).
    """
    assert mpn_resistance_readings("WR06X1002FTL") == []
    assert mpn_resistance_readings("AR03BTCX5001") == [(5000.0, "5001 (E-96)")]
    state, rows = _state_of("resistor", "1kΩ", "WR06X1002FTL")
    assert state == "UNKNOWN", rows
    # The old reading made this a contradiction (0.06 Ω against 1 kΩ is 16666x),
    # i.e. a WARN on a part whose value the decoder simply cannot read.
    assert "0.06" not in rows[0].message


def _electrolytic_witnesses() -> list[tuple[str, str, str]]:
    """The five electrolytics issue #25 names, the capacitance each states, and shape.

    Four manufacturers and three voltage positions, which is the issue's own count
    and the reason the gate had to be a class rather than a shape:

    * Nichicon ``UVR1H101MPD`` and Rubycon ``16ZLH470MEFC`` -- the trade's voltage
      code (``1H`` = 50 V, ``ZLH``) in front of the capacitance;
    * Panasonic ``EEU-FC1H101`` and Chemi-con ``50YXF100MEFC`` -- a series field
      with the voltage code inside it;
    * ``NRWA221M35V`` -- the printed voltage as a suffix.

    None of them states a package size, so none of the digits is a code field
    (071 §1 C): that is exactly what ``ANCHOR_PACKAGE_CONTEXT`` asks.
    """
    return [
        ("UVR1H101MPD", "100uF", "Nichicon VR, voltage code 1H in front"),
        ("50YXF100MEFC", "100uF", "Chemi-con YXF, voltage code inside the series"),
        ("NRWA221M35V", "220uF", "printed voltage as a suffix"),
        ("16ZLH470MEFC", "470uF", "Rubycon ZLH, voltage code in the series"),
        ("EEU-FC1H101", "100uF", "Panasonic FC, voltage code in the series"),
    ]


def test_071_the_electrolytic_family_is_unknown_never_a_warn():
    """Issue #25's class, at the rule level: five electrolytic parts, no WARN.

    Every witness here is one the decoder **does read** -- its digits land in a
    three-figure group, so ``mpn_value_code`` returns a code, the rule compares a
    100 uF board against "10 pF" and would call it a BOM contradiction. That is
    the shape of every false WARN this batch exists for, and 071 §1 C closes it as
    a class: the reading carries no syntactic anchor, so it may not accuse,
    whatever the next voltage position turns out to be.
    """
    for mpn, value, shape in _electrolytic_witnesses():
        code, anchor = mpn_value_code_anchor(mpn)
        assert code is not None, (
            f"{mpn} ({shape}): the witness must be one the decoder *reads*, "
            "otherwise it was already UNKNOWN before 071"
        )
        assert anchor == "", f"{mpn} ({shape}): no package size, so no anchor"
        state, rows = _state_of("capacitor", value, mpn)
        assert state == "UNKNOWN", f"{mpn} ({shape}): {state} {(rows[0].message if rows else '')}"
        assert "字符串解码无锚点，低置信" in rows[0].message
    # The refused family stays refused (task 015 / #18): the gate does not have to
    # do the work the decoder's own guards already do.
    for mpn, value in (
        ("ERR1VM101E07OT", "100uF"),
        ("PA50V330M10x15", "330uF"),
        ("SPZ1HM100E07O00RAXXX", "10uF"),
    ):
        state, rows = _state_of("capacitor", value, mpn)
        assert state == "UNKNOWN", mpn
        assert "contains no decodable EIA value code" in rows[0].message


def test_071_the_three_anchors_are_what_lets_a_reading_accuse():
    """071 §1 C: the three anchors, the unanchored case, and the anchor's labels.

    The ruling's own examples, at both layers -- the readings layer that decides
    which anchor a reading carries, and the rule layer where the anchor is the
    difference between a WARN and a UNKNOWN. The unanchored half is the point of
    the option: those readings are not refused (they still *match* a board that
    agrees with them, and they still waive an amplitude below the tolerance), they
    are simply not allowed to be the only witness against a BOM line.
    """
    from boardwise.rules.values import (
        ANCHOR_E96_LETTER,
        ANCHOR_MID_LETTER,
        ANCHOR_PACKAGE_CONTEXT,
        mpn_resistance_candidates,
        mpn_value_code_anchor,
    )

    # ① a four-figure code with a letter at the digits: E-96 with its tolerance
    # letter, 厚声's ordering field with its T tail, the shunt field.
    assert mpn_resistance_candidates("RK73H1JTTD1002F") == [
        (10000.0, "1002 (E-96)", ANCHOR_E96_LETTER)
    ]
    assert mpn_resistance_candidates("0603WAF1002T5E") == [
        (10000.0, "1002 (numeric-exponent field)", ANCHOR_E96_LETTER)
    ]
    assert mpn_resistance_candidates("FRL1210FR400TS") == [
        (0.4, "FR400 (shunt field)", ANCHOR_E96_LETTER)
    ]
    # ...and without the adjacent letter there is no anchor: `5001` at the end of
    # a token is four digits, not a statement.
    assert mpn_resistance_candidates("AR03BTCX5001") == [
        (5000.0, "5001 (E-96)", "")
    ]
    # ② the canonical mid-letter form: the whole run, after the size comes off.
    assert mpn_resistance_candidates("CRCW060310K0FKEA") == [
        (10000.0, "10K0", ANCHOR_MID_LETTER)
    ]
    # The shorter reading of `074K7` is the vendor-prefix guess, so it carries
    # none -- at most one of the two can be right.
    assert mpn_resistance_candidates("RC0603FR-074K7L") == [
        (4700.0, "4K7", ""),
        (74700.0, "74K7", ANCHOR_MID_LETTER),
    ]
    # ③ an EIA three-digit code with a package size in the same token.
    assert mpn_value_code_anchor("CC0603KRX7R9BB104") == ("104", ANCHOR_PACKAGE_CONTEXT)
    assert mpn_value_code_anchor("GRM188R71C104KA01D") == ("104", ANCHOR_PACKAGE_CONTEXT)
    # ...and three digits with no size spelling anywhere in the token carry none
    # (the #25 shape, and the value code that shares a metric size's spelling).
    assert mpn_value_code_anchor("CL10B104KB8NNNC") == ("104", "")
    assert mpn_value_code_anchor("UVR1H101MPD") == ("101", "")

    # At the rule layer, one witness per anchor and two without: the same shape of
    # disagreement, three WARNs and two withheld rows.
    for kind, value, mpn, expected in (
        ("resistor", "310kΩ", "CRCW060310K0FKEA", "VIOLATION"),
        ("resistor", "47kΩ", "RK73H1JTTD1002F", "VIOLATION"),
        ("resistor", "3300", "0603WAF1002T5E", "VIOLATION"),
        ("resistor", "330", "MF1/4W-1K±1%-ST52", "VIOLATION"),
        ("capacitor", "100uF", "GRM188R71C104KA01D", "VIOLATION"),
        # 100 uF against the 104 code's 100 nF is 1000x, past the 25x capacitor
        # tolerance -- and it is withheld, because `CL10B104KB8NNNC` states no
        # package size anywhere (as a resistor, `104` = 100 kΩ would be 100x).
        ("capacitor", "100uF", "CL10B104KB8NNNC", "UNKNOWN"),
        ("capacitor", "100uF", "UVR1H101MPD", "UNKNOWN"),
    ):
        state, rows = _state_of(kind, value, mpn)
        assert state == expected, f"{mpn}: {state} {rows[0].message[:120] if rows else ''}"


def _corpus_tokens() -> list[str]:
    """The repository's own part-number tokens (the #18 batch's notch).

    A whitespace-free run of at least four characters carrying at least three
    consecutive digits, harvested from the string literals of `tests/` and
    `reviewsets/` -- deliberately dumber than the decoder, so a token the decoder
    refuses is still *in* the corpus.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    token_re = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-\u00b5\u03bc/]{3,}")
    digit_re = re.compile(r"\d{3}")
    tokens: set[str] = set()
    for folder in ("tests", "reviewsets"):
        for path in (root / folder).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".md"}:
                continue
            if "__pycache__" in path.parts:
                continue
            for match in token_re.finditer(path.read_text(encoding="utf-8", errors="replace")):
                token = match.group(0).strip("._-")
                if len(token) >= 4 and digit_re.search(token):
                    tokens.add(token)
    return sorted(tokens)


def test_071_every_accusation_over_this_repos_own_corpus_names_its_anchor():
    """071 §1 C as an invariant, over every part number in this repository.

    The anchor gate is not a shape whitelist -- "which tokens are refused" is the
    enumeration that failed -- so what a corpus can pin is the two-sided property
    the gate actually is: **every** accusation the rule makes over the repo's own
    tokens names the anchor that let it accuse, and the corpus **still produces**
    accusations. A rule that quietly went back to refusing everything would fail
    the second half; one that went back to accusing on any string would fail the
    first. Each token is asked as a resistor declared at 1 kΩ and as a capacitor
    declared at 100 nF, so a token that happens to match one form cannot hide an
    accusation in the other.

    This is also the gate's mutation witness: take the anchor test out of the
    rule and the corpus fills with accusations that cannot name an anchor.
    """
    tokens = _corpus_tokens()
    assert len(tokens) > 1000, f"the corpus shrank to {len(tokens)} tokens"
    rule = ValueMpnMatch()
    accused: list[tuple[str, str]] = []
    for token in tokens:
        for kind, value in (("resistor", "1kΩ"), ("capacitor", "100nF")):
            model, _designator = _one_part(kind, value, token)
            findings = rule.check(model)
            if findings:
                accused.append((f"{kind}:{token}", findings[0].message))
    unnamed = [item for item in accused if "锚点：" not in item[1]]
    assert unnamed == [], (
        f"{len(unnamed)} accusation(s) that cannot name an anchor: {unnamed[:5]}"
    )
    assert len(accused) >= 5, (
        f"only {len(accused)} accusation(s) in the whole corpus: the gate may have "
        "gone back to refusing everything"
    )


# ------------------------------------- issues #27 / #31: the input has no ceiling


def test_027_a_string_over_the_cap_is_never_decompiled():
    """Issue #27: the decoders read a bounded number of characters, not a shape.

    The regexes are grammatical and unbounded -- ``_MID_LETTER_RE``'s ``\\d*`` and
    ``_ELECTROLYTIC_RE``'s ``\\d+[Vv]\\d{3}`` each backtrack over the digit run from
    every start position -- so a pure-digit string costs O(n²): the issue reports
    ``run_review`` at 28 s for an MPN of 32000 digits (8.3 s on the machine this
    was written on), each doubling x4. The repair is a length
    precheck at every entry that can be handed an outside string, **not** a
    bounded regex, and the difference is not stylistic: ``\\d{0,3}`` would undo
    071's infix repair, which needs the whole run ``060310`` before it can strip
    the size code ``0603`` -- handed only the last three digits it spells the
    pseudo-reading ``310K0`` again (issue #24).

    Every witness below is a string the **uncapped** decoder reads: a pin that
    already came back unreadable would stay green with the precheck removed. The
    cap is measured on the first whitespace-separated token, the piece the
    decoders read (an MPN's ``" TS"`` tail is a packaging note).
    """
    from boardwise.rules.values import parse_resistance_ohms

    digits = "1" * 1002  # a multiple of three: the one the EIA finder *does* read
    assert mpn_value_code(digits) is None
    assert mpn_value_code_anchor(digits) == (None, "")
    assert mpn_resistance_readings("1" * 1000 + "K") == []
    assert mpn_resistance_candidates("1" * 1000 + "K") == []
    assert parse_resistance_ohms("1" * 1000) is None
    assert parse_capacitance_farads("1" * 1000 + "uF") is None
    # At the rule level a decoder that no longer reads the token says so: the
    # part is UNKNOWN, not a silent OK off a reading nobody can vouch for.
    state, rows = _state_of("resistor", "1kΩ", "1" * 1000 + "K")
    assert state == "UNKNOWN", rows
    assert "contains no decodable EIA value code" in rows[0].message
    # 64 characters of first token are read, 65 are not -- the cap's own edge.
    assert mpn_value_code("X" * 61 + "471") == "471"
    assert mpn_value_code("X" * 62 + "471") is None
    # ...and it is the *first token* that is measured, so a packaging note after
    # a space does not push a readable MPN over the cap.
    assert mpn_value_code("471 " + "Y" * 200) == "471"
    assert mpn_value_code("X" * 62 + "471" + " " + "Y" * 200) is None


#: The two lengths issue #27's timing pin compares, in characters of pure digits.
#: The larger is eight times the smaller and the criterion is that the time grows
#: no faster than the length; a quadratic decoder costs ~64x. Both are measured in
#: the same run, so the machine cancels out of the ratio -- a **degenerate
#: criterion, not a performance baseline** (the 057 issue-#20 idiom): it cannot
#: see a small slowdown and is not meant to; what it sees is the shape where the
#: decoder walks every suffix of the run.
TIMING_SMALL_MPN = 1000
TIMING_LARGE_MPN = TIMING_SMALL_MPN * 8

#: The issue's own loose ceiling for the small run, and the slack the ratio check
#: allows for that run's noise. The ceiling is a *relative upper bound*: the
#: pre-fix cost at 1000 characters is 0.008 s on the machine this was written on
#: and 8.3 s at 32000, so 0.5 s is not a baseline anything is tuned against -- it
#: is the order of magnitude where "one unreadable MPN" would become a wall-clock
#: event, and the ratio check below is what actually fires on the defect.
TIMING_CEILING_S = 0.5
TIMING_SLACK_S = 0.05


def test_027_run_review_over_a_digits_only_mpn_is_bounded():
    """Issue #27, end to end: one long value must not become a wall-clock event.

    The rule ``run_review`` applies is the rule that reads the MPN, so this is the
    frame the issue reports in (28 s for a 32000-digit MPN) at the length the
    issue's own test used. Post-fix both runs cost the rule suite's fixed work and
    the MPN's length does not enter the cost at all.
    """
    from boardwise.engines.review import run_review

    def elapsed(mpn: str) -> float:
        model, _designator = _one_part("resistor", "1kΩ", mpn)
        started = time.perf_counter()
        run_review(model)
        return time.perf_counter() - started

    elapsed("RC0603FR-074K7L")  # warm the rule suite, not the decoder
    small = elapsed("1" * TIMING_SMALL_MPN)
    large = elapsed("1" * TIMING_LARGE_MPN)
    assert small < TIMING_CEILING_S, (
        f"{TIMING_SMALL_MPN} digits took {small:.2f} s (> {TIMING_CEILING_S:g} s)"
    )
    assert large <= small * (TIMING_LARGE_MPN / TIMING_SMALL_MPN) + TIMING_SLACK_S, (
        f"{TIMING_LARGE_MPN} digits took {large:.2f} s against "
        f"{small:.2f} s for {TIMING_SMALL_MPN}: {TIMING_LARGE_MPN / TIMING_SMALL_MPN:g}x "
        "the digits cost far more than the length ratio (a degenerate criterion "
        "-- see TIMING_SMALL_MPN)"
    )


def test_031_an_overflowing_board_value_no_longer_takes_the_review_down():
    """Issue #31: ``float`` overflows in silence, and ``math.log`` then raised.

    ``parse_resistance_ohms("1" * 400)`` came back as ``inf`` -- no error -- and
    ``params._closest_reading`` divided the decoded reading by it, ``log(0.0)``,
    which raised ``ValueError`` out of ``run_review``: one unreadable value field
    took the whole review down, converting "cannot read this" into "no report".
    Both halves of the fix are exercised here: the value is refused as unreadable,
    and the row the rule emits is the UNKNOWN it emits for any unparseable value.
    """
    from boardwise.engines.review import run_review
    from boardwise.rules.values import parse_resistance_ohms

    assert parse_resistance_ohms("1" * 400) is None
    assert parse_capacitance_farads("1" * 400 + "uF") is None
    mpn = "RK73H1JTTD1002F"  # an anchored reading: the path that reached math.log
    model, designator = _one_part("resistor", "1" * 400, mpn)
    run_review(model)  # pre-fix: ValueError out of here
    # The row the rule emits is the one it emits for any unparseable value field.
    # The part's *kind* has to come from somewhere and `_kind_of` reads it out of
    # the value as its last resort, so the shelf is what says this is a resistor
    # (a value the parser refuses carries no kind at all, and the rule has nothing
    # to judge -- the pre-existing path for "cannot tell what this part is").
    entry = PartEntry(
        key="resistor.test", value="10kΩ", mpn=mpn, lcsc="C1", category="resistor",
    )
    states = _states(ValueMpnMatch(library=_library(entry)), model)
    assert not states["VIOLATION"], states["VIOLATION"]
    assert [outcome.subject for outcome in states["UNKNOWN"]] == [designator]
    unknown = states["UNKNOWN"][0]
    assert "empty or unparsable" in unknown.message
    assert unknown.missing_fact == f"a parseable value field on {designator}"
    # The same MPN against a readable value still accuses, so the UNKNOWN above
    # is about the value field (and not the fixture having gone silent).
    state, _rows = _state_of("resistor", "47kΩ", mpn)
    assert state == "VIOLATION"


def test_031_the_finite_gate_does_not_depend_on_the_length_cap(monkeypatch):
    """The first of the two gates, on its own (the cap is widened away here).

    An overflow is "this value cannot be read", which is what every parser in
    ``rules/values.py`` answers for a string it does not recognise -- so the
    refusal sits in the parsers beside the length precheck rather than being left
    to the caller. Widening the cap is exactly the state the precheck would leave
    behind if somebody raised it for a legitimate long spelling, and the overflow
    still has to come back None.
    """
    from boardwise.rules import values
    from boardwise.rules.values import parse_resistance_ohms

    monkeypatch.setattr(values, "_too_long", lambda text: False)
    assert parse_resistance_ohms("1" * 400) is None
    assert parse_capacitance_farads("1" * 400 + "uF") is None


def test_031_the_reading_choice_survives_a_non_finite_declared_value():
    """The second gate: ``_closest_reading``'s own guard (issue #31, suggestion 2).

    The choice of candidate is a distance from the board's declared value, and an
    infinite or NaN declared value has no distance to anything -- ``item[0] / inf``
    is ``0.0`` and ``log`` of it raises. The function answers with the same
    conservative fallback it uses for "no declared value at all": the first
    reading, which is the one the message already says the value field could not
    be parsed for.
    """
    from boardwise.rules.params import _closest_reading
    from boardwise.rules.values import ANCHOR_MID_LETTER

    readings = [(4700.0, "4K7", ""), (74700.0, "74K7", ANCHOR_MID_LETTER)]
    for declared in (float("inf"), float("-inf"), float("nan")):
        assert _closest_reading(readings, declared) == readings[0]
    assert _closest_reading(readings, 4700.0) == readings[0]
    assert _closest_reading(readings, 74700.0) == readings[1]


def test_027_the_cap_changes_no_token_it_does_not_cover(monkeypatch):
    """The cap is a bound on *cost*, not a change of grammar (071's own corpus).

    For every part number in this repository that fits under the cap, the four
    entry points must answer exactly what they answer with the cap lifted -- which
    is what the pre-fix tree answers, since the only other change in this batch is
    the finite gate and no finite quantity changes a reading. A cap that quietly
    started refusing 40-character tokens (or that was typed as, say, 16) fails
    here, and so does a precheck that measured something other than the token the
    decoders read.
    """
    from boardwise.rules import values
    from boardwise.rules.values import parse_resistance_ohms

    def snapshot(token: str) -> tuple:
        return (
            mpn_resistance_candidates(token),
            mpn_value_code_anchor(token),
            parse_resistance_ohms(token),
            parse_capacitance_farads(token),
        )

    tokens = [t for t in _corpus_tokens() if len(t) <= values._MAX_DECODED_CHARS]
    assert len(tokens) > 1000, f"the corpus shrank to {len(tokens)} short tokens"
    capped = {token: snapshot(token) for token in tokens}
    monkeypatch.setattr(values, "_MAX_DECODED_CHARS", 10 ** 6)
    uncapped = {token: snapshot(token) for token in tokens}
    assert capped == uncapped
