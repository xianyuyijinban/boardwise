"""102 / B3 value parsing: in a Value field a package size code **is** the value.

Source: the audit (repo-root ``.tmp_bug_report.md``, gitignored -- section
``## 8.``) and the task book ``tasks/102-b3-value-sizecodes.md``.

``core.values._mid_letter_readings`` is one scan behind two callers -- a board's
Value field and a part number (071 §2) -- and one of its steps is **MPN** grammar:
a leading package size code comes off the digit run before the mantissa is read
(071 §3②, ``CRCW0603``10``K0``). A Value field has no vendor prefix, so there is
nothing to strip and the run itself is its mantissa -- the rule the module already
writes down. Applied to a Value field that step eats the value: ``160n``, the
spelling ``core.parts.quantity_slug`` addresses the shelf by (``cap.160n_0402``),
loses its mantissa whole and reads as nothing, and 087 §8's rule then bites -- a
rule handed a value it cannot read skips the part, so a 160 nF decoupling
capacitor is invisible to the decoupling rule. The audit swept both size alphabets
against the three unit letters and measured **54** such spellings, all ``None``.

What is pinned here: those 54 read, and they read **what they spell** -- the
digits in the unit letter's place (``105n`` is 105 nF, ``0805u`` 805 µF,
``01005p`` 1005 pF), which is exactly what the ``vendor_prefix=False`` branch's
own comment says a Value field's run is. The size code's leading zero is padding,
not a significant figure, so ``0805n`` reads what ``805n`` has always read and
``0603n`` what the suffix spelling ``0603nF`` has always read.

The spellings outside the audit's 54 are pinned against readings that already
exist, or assembled from parts, rather than written out as literals: this file is
part of the corpus sweep the batch re-runs (the harvest reads this repository's
own text), and that sweep has to count the 54 and nothing else -- see
``outputs/102/SUMMARY.txt`` §语料回归.

The refusals the earlier batches pinned stay refused: a run longer than the
trade's mantissa that is not a size code (``12345n``, ``12345u7``), a leading zero
that is no size code's padding (``0u1``, ``0n``), a designator in front of the
notation (``C4u7``) and a trailing unit letter (``4u7F``). The MPN side does not
move at all: the strip is a part number's grammar, and a part number is not a
Value field.
"""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary, make_key, quantity_slug
from boardwise.rules.decap import DecapRequiredCaps
from boardwise.rules.params import RcCutoff
from boardwise.rules.values import (
    mpn_resistance_readings,
    parse_capacitance_farads,
    parse_resistance_ohms,
)

#: The audit's sweep: every metric (three figures) and imperial (four and five
#: figures) package size code against all three unit letters, with the reading
#: each states. ``105e-12`` is 105 pF -- the digits, in the unit letter's place --
#: and ``1005e-12`` is what the imperial spelling ``01005p`` states (its leading
#: zero is the size code's padding, not a figure).
AUDIT_READINGS = (
    ("105p", 105e-12), ("105n", 105e-9), ("105u", 105e-6),
    ("160p", 160e-12), ("160n", 160e-9), ("160u", 160e-6),
    ("188p", 188e-12), ("188n", 188e-9), ("188u", 188e-6),
    ("201p", 201e-12), ("201n", 201e-9), ("201u", 201e-6),
    ("321p", 321e-12), ("321n", 321e-9), ("321u", 321e-6),
    ("322p", 322e-12), ("322n", 322e-9), ("322u", 322e-6),
    ("451p", 451e-12), ("451n", 451e-9), ("451u", 451e-6),
    ("453p", 453e-12), ("453n", 453e-9), ("453u", 453e-6),
    ("01005p", 1005e-12), ("01005n", 1005e-9), ("01005u", 1005e-6),
    ("0201p", 201e-12), ("0201n", 201e-9), ("0201u", 201e-6),
    ("0402p", 402e-12), ("0402n", 402e-9), ("0402u", 402e-6),
    ("0603p", 603e-12), ("0603n", 603e-9), ("0603u", 603e-6),
    ("0805p", 805e-12), ("0805n", 805e-9), ("0805u", 805e-6),
    ("1206p", 1206e-12), ("1206n", 1206e-9), ("1206u", 1206e-6),
    ("1210p", 1210e-12), ("1210n", 1210e-9), ("1210u", 1210e-6),
    ("1812p", 1812e-12), ("1812n", 1812e-9), ("1812u", 1812e-6),
    ("2010p", 2010e-12), ("2010n", 2010e-9), ("2010u", 2010e-6),
    ("2512p", 2512e-12), ("2512n", 2512e-9), ("2512u", 2512e-6),
)

#: The four size codes the audit lists that are also the **metric** spelling of
#: an imperial one, longest first: ``201`` is ``0201`` and ``321``/``322`` are
#: ``1206``/``1210``. Used by the agreement test below.
METRIC_SIZES = ("105", "160", "188", "201", "321", "322", "451", "453")
IMPERIAL_SIZES = (
    "01005", "0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010",
    "2512",
)

#: MICRO SIGN, GREEK SMALL LETTER MU and the GREEK CAPITAL LETTER MU the two of
#: them upper-case to (task 055): one unit, three code points. Assembled here
#: rather than written out so the corpus sweep sees no extra token.
MICRO_SPELLINGS = ("\u00b5", "\u03bc", "\u039c")

PROV = "test datasheet, p.1, http://example.com/ds.pdf"


@pytest.mark.parametrize("spelling,farads", AUDIT_READINGS)
def test_a_package_size_code_in_a_value_field_reads_as_its_own_figures(
    spelling: str, farads: float
) -> None:
    """``160n`` is 160 nF, ``0805u`` 805 µF: the audit's 54, one by one.

    The reading is the field's own figures, so what the ratio says is what the
    string spells -- no scale factors, no vendor guess, no size code coming off.
    """
    assert parse_capacitance_farads(spelling) == pytest.approx(farads, rel=1e-12)


def test_the_size_code_spelling_reads_what_the_number_and_the_suffix_spellings_read() -> None:
    """Two neighbours of the new reading, both of which have always read.

    ``805n`` is the padded number the size code ``0805`` spells, and it reads 805
    nF; ``0603nF`` is the suffix grammar's spelling of the same field, and it
    reads 603 nF. The new readings have to land on both -- the size code's
    leading zero is the spelling's padding, not a figure to refuse -- or one board
    would hold three spellings of one value with one of them invisible.
    """
    assert parse_capacitance_farads("805n") == pytest.approx(805e-9, rel=1e-12)
    assert parse_capacitance_farads("0805n") == pytest.approx(
        parse_capacitance_farads("805n"), rel=1e-12
    )
    assert parse_capacitance_farads("0603nF") == pytest.approx(603e-9, rel=1e-12)
    assert parse_capacitance_farads("0603n") == pytest.approx(
        parse_capacitance_farads("0603nF"), rel=1e-12
    )
    assert parse_capacitance_farads("0.603uF") == pytest.approx(603e-9, rel=1e-12)
    # The metric spelling of one size code and the imperial spelling of the same
    # size code carry the same figures (``201`` is ``0201``), so they agree.
    assert parse_capacitance_farads("201n") == pytest.approx(
        parse_capacitance_farads("0201n"), rel=1e-12
    )


def test_the_size_code_reads_in_every_micro_spelling() -> None:
    """One unit, three code points (055), and the size code does not change it."""
    for mu in MICRO_SPELLINGS:
        text = "160" + mu
        assert parse_capacitance_farads(text) == pytest.approx(160e-6, rel=1e-12)
    # The fraction the notation carries rides along as it does for any other run.
    assert parse_capacitance_farads("0805" + "u1") == pytest.approx(
        parse_capacitance_farads("805u1"), rel=1e-12
    )


def test_the_value_reader_still_refuses_the_shapes_the_earlier_batches_pinned() -> None:
    """087's gap and 071's structural refusals, read across to this batch.

    The run has to be a size code for the new reading -- a longer run is still no
    mantissa (``12345n``, ``12345u7``: the trade's mantissa is three figures, and
    four figures after the letter is the cap ``4K700`` shows), a leading zero that
    is not a size code's padding still states nothing (``0u1``, ``0n``), and the
    whole-field anchoring is untouched (``C4u7``, ``4u7F``, ``100``). ``0603``
    with no unit letter is a size, not a value.
    """
    assert parse_capacitance_farads("0n") is None
    assert parse_capacitance_farads("00n") is None
    assert parse_capacitance_farads("0u1") is None
    assert parse_capacitance_farads("12345n") is None
    assert parse_capacitance_farads("12345u7") is None
    assert parse_capacitance_farads("4u700") is None
    assert parse_capacitance_farads("u7") is None
    assert parse_capacitance_farads("C4u7") is None
    assert parse_capacitance_farads("4u7F") is None
    assert parse_capacitance_farads("100") is None
    assert parse_capacitance_farads("0603") is None
    assert parse_capacitance_farads("IRF540N") is None


def test_the_resistance_twin_of_the_same_shape_is_registered_not_opened() -> None:
    """``160R`` is the same defect in the other notation, and it stays refused.

    The size-code strip is one rule for both notations (071 §2's "the difference
    between them is the letters"), so the resistance Value field has the same
    collision: ``160R`` -- 160 Ω, the R-suffix spelling ``47R`` has always read --
    loses its mantissa to the ``160`` size code. This batch fixes the audited
    family, the 54 **capacitance** spellings; the resistance twin is registered
    with the delivery (``outputs/102/SUMMARY.txt`` §遗留) for a ruling rather than
    decided here, because opening it would move the resistance reader's reading
    set by 18 spellings that no audit measured and no corpus token names.

    Pinning the refusal is how that stays visible: a later batch that opens the
    twin will fail here and have to say so.
    """
    for size in IMPERIAL_SIZES + METRIC_SIZES:
        assert parse_resistance_ohms(size + "R") is None


def test_the_shelf_spelling_the_slug_makes_is_one_the_reader_reads() -> None:
    """The audit's sting: ``cap.160n_0402`` is the shelf's own key, and it read as
    nothing.

    ``parts.quantity_slug`` calls ``160n`` the schematic spelling and
    ``make_key`` addresses the part by it, so the shelf and the board were two
    spellings of one value with only one of them readable (071 §2's complaint,
    filed about the resistance side). Both halves are pinned: the slug the key is
    built from reads, and it reads the same value the ``F`` that was dropped
    stated.
    """
    assert quantity_slug("160nF") == "160n"
    assert quantity_slug("0805nF") == "0805n"
    assert make_key(
        category="cap", value="160n", mpn="", footprint_name="C0402",
        title="", lcsc="",
    ) == "cap.160n_0402"
    assert parse_capacitance_farads(quantity_slug("160nF")) == pytest.approx(
        parse_capacitance_farads("160nF"), rel=1e-12
    )
    assert parse_capacitance_farads(quantity_slug("0805nF")) == pytest.approx(
        parse_capacitance_farads("0805nF"), rel=1e-12
    )


#: One LDO whose pin 5 requires a 1 uF capacitor (011d's own fixture shape).
def _ldo_entry() -> PartEntry:
    return PartEntry(
        key="ic.ldo.test", value="RT9013-33GB", mpn="RT9013-33GB", lcsc="C47773",
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


def test_param3_an_rc_pair_spelled_with_a_size_code_is_measured() -> None:
    """The end-to-end leg, with the spelling a board writes when the size code
    comes first: ``C1 = 160n``.

    087 §8 measured what an unreadable value costs on this rule: the pair is
    invisible, the rule reports "no resistor-to-ground capacitor pair was found on
    this board" and the comment in the task book is blunt about it -- silence is
    worse than a miss. With the reading in place the pair is measured and the
    number is the one the two values state: fc = 1/(2*pi*1k*160nF) = 994.7 Hz.
    """
    lib = PartLibrary(parts=[_ldo_entry()])
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value="1K",
        pins=[Pin("1", "A", "SIG"), Pin("2", "B", "MID")])
    model.components["C1"] = Component(
        uid="c1", designator="C1", value="160n",
        pins=[Pin("1", "A", "MID"), Pin("2", "B", "GND")])
    model.nets = {
        "SIG": Net("SIG", [("R1", "1")]),
        "MID": Net("MID", [("R1", "2"), ("C1", "1")]),
        "GND": Net("GND", [("C1", "2")]),
    }
    reported = [
        o for o in RcCutoff(library=lib).outcomes(model) if "fc =" in o.message
    ]
    assert len(reported) == 1 and reported[0].subject == "R1/C1"
    assert "fc = 995 Hz" in reported[0].message
    # The evidence quotes the field as the board spells it, size code and all.
    assert "C1 value '160n'" in reported[0].evidence


def test_decap_a_cap_spelled_with_a_size_code_is_no_longer_invisible() -> None:
    """The defect's own sting, on the rule the task book names: the decoupling
    rule.

    C9 sits on VCC and its value is ``160n``. Unreadable, the part is not a
    capacitor the rule can judge, and the row says there is **no grounded
    capacitor on the net at all** -- the board is told to add the cap it already
    has (a VIOLATION, not a "cannot tell"). Readable, the same part is judged for
    what it is: 160 nF against a 1 uF requirement, too small, and the row names
    the figure it read.
    """
    lib = PartLibrary(parts=[_ldo_entry()])
    model = DesignModel()
    model.components["U5"] = Component(
        uid="u5", designator="U5", mpn="RT9013-33GB", lcsc_part="C47773",
        pins=[Pin("1", "VIN", "+5V"), Pin("5", "VOUT", "VCC")])
    model.components["C9"] = Component(
        uid="c9", designator="C9", value="160n",
        pins=[Pin("1", "A", "GND"), Pin("2", "B", "VCC")])
    model.nets = {
        "+5V": Net("+5V", [("U5", "1")]),
        "VCC": Net("VCC", [("U5", "5"), ("C9", "2")]),
        "GND": Net("GND", [("C9", "1")]),
    }
    rows = [
        o for o in DecapRequiredCaps(library=lib).outcomes(model)
        if o.subject == "U5 pin5"
    ]
    assert len(rows) == 1, rows
    row = rows[0]
    # The cap is seen now: the row judges its value instead of reporting the net
    # as bare.
    assert "no grounded capacitor found" not in row.message
    assert "160nF" in row.message and "1uF" in row.message
    assert "C9 value '160n'" in row.evidence
    # 160 nF is below the 1 uF the datasheet names, so the row is still a
    # VIOLATION -- the reading changes *what is judged*, not what is true.
    assert row.state == "VIOLATION"


def test_the_mpn_side_reads_the_size_code_as_a_prefix_and_a_value_field_does_not() -> None:
    """The strip is a part number's grammar: a Value field has no prefix to take.

    ``CRCW060310K0FEA`` states 10.0 kΩ behind its size code, so the MPN reader
    keeps reading it exactly as 071 §3② pinned (the strip and the anchored
    reading both). The same string handed to a **Value field** is not a value at
    all: a value field states one value and nothing else, which is what the
    anchoring refuses here. Nothing in this batch moves either answer.
    """
    assert mpn_resistance_readings("CRCW060310K0FEA") == [(10000.0, "10K0")]
    assert parse_resistance_ohms("CRCW060310K0FEA") is None
    assert parse_capacitance_farads("CRCW060310K0FEA") is None
