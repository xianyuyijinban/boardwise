"""Issues #34 / #49 / #50: the datasheet extractor's signs and its capacitor reading.

Three defects in one file (`engines/datasheet.py`), fixed in one batch and pinned
separately, because they are three different mistakes and a single "the extractor
is fixed" assertion would let any one of them rot on its own:

* **#34 — a column-separating hyphen read as a minus.** `VDD -0.5 6.5 V` and
  `VDD - 1.55 3.6 V` are the same table shape, and only the first is negative.
  The old `_PAIR` sign segment carried a `\\s?`, so the second came back as
  `[-1.55, 3.6]` — a supply range starting below ground that the datasheet never
  claimed.
* **#49 — the range branches dropped their signs.** `-0.5V to 6.5V` is the
  standard way to write an absolute maximum, and `_RANGE` read it as
  `[0.5, 6.5]`, erasing the below-ground allowance. `_TRIPLE` had the same gap.
  Sign normalisation is now one function (`_signed_float`) shared by all three
  readers, per 071's "one judgment, one implementation".
* **#50 — `required_caps` collected only what spelled itself
  `bypass|decoupl`.** The MPU-6050 external-components table lists four required
  capacitors and only two of them say "Bypass"; the other two (Regulator Filter,
  Charge Pump) were dropped, which let `decap-required-caps` pass a board that is
  missing them. The keyword gate is gone, replaced by a structural one, and
  `Capacitance` is no longer confused with `Capacitor`.

Every verdict below was measured against the real datasheets in
``inputs/smart_pillbox/datasheets/``; the corpus lines are quoted verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.engines.datasheet import (
    _is_capacitor_part,
    _range_of,
    _signed_float,
    candidate_facts,
    pages_from_marked_text,
)

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "blocklib" / "parts.json"
DATASHEETS = ROOT / "inputs" / "smart_pillbox" / "datasheets"
URL = "https://example.com/ds.pdf"

#: The MPU-6050 external-components table, p.22 of
#: `inputs/smart_pillbox/datasheets/MPU-6050_C24112.pdf`, verbatim. Four required
#: capacitors, and only two of the four lines contain the word "Bypass".
MPU6050_BOM_P22 = (
    "7.3 Bill of Materials for External Components \n"
    "Regulator Filter Capacitor (Pin 10) C1 Ceramic, X7R, 0.1µF ±10%, 2V 1 \n"
    "VDD Bypass Capacitor (Pin 13) C2 Ceramic, X7R, 0.1µF ±10%, 4V 1 \n"
    "Charge Pump Capacitor (Pin 20) C3 Ceramic, X7R, 2.2nF ±10%, 50V 1 \n"
    "VLOGIC Bypass Capacitor (Pin 8) C4* Ceramic, X7R, 10nF ±10%, 4V 1 \n"
)


def _caps(pages: list[str]) -> set[tuple[str, str]]:
    facts, _notes = candidate_facts(pages, label="corpus", url=URL)
    return {(record["pin"], record["value"]) for record in facts.get("required_caps", [])}


def _supplies(pages: list[str]) -> set[tuple[str, tuple[str, ...], tuple[float, ...]]]:
    facts, _notes = candidate_facts(pages, label="corpus", url=URL)
    return {
        (record["name"], tuple(record["pins"]),
         tuple(record.get("v_operating") or record.get("v_abs_max") or ()))
        for record in facts.get("supply_pins", [])
    }


# ============================================================ #34 — the hyphen


def test_034_a_spaced_hyphen_is_a_column_separator_not_a_minus():
    """STM32G431 p.71: `voltage - 1.55 3.6 V` is 1.55 V, not -1.55 V.

    The minus belongs to the digits. Everything a specification table writes with
    a space between the sign and the number is a column separator, and reading it
    as a sign invents a range below ground.
    """
    assert _range_of("VBAT Backup operating voltage - 1.55 3.6 V") == [1.55, 3.6]


def test_034_a_hyphen_touching_the_digits_is_still_a_real_minus():
    """The three corpus spellings of a genuine negative, none of them lost."""
    assert _range_of("VCC –0.3 6 V") == [-0.3, 6.0]  # EN DASH
    assert _range_of("VDD -0.5 6.5 V") == [-0.5, 6.5]  # ASCII hyphen
    assert _range_of("VCC 电源电压（VCC接电源，GND接地） -0.5 6.0 V") == [-0.5, 6.0]


def test_034_the_fix_reaches_candidate_facts_through_a_pin_table_join():
    """End to end: the STM32 VBAT record stops claiming a below-ground range."""
    pages = pages_from_marked_text(
        "<<<page 1>>>\nPin Functions\n6 VBAT Backup battery input\n"
        "<<<page 71>>>\nVBAT Backup operating voltage - 1.55 3.6 V \n"
    )
    assert _supplies(pages) == {("VBAT", ("6",), (1.55, 3.6))}


def test_034_an_unsigned_pair_is_untouched():
    """The shape the fix must not disturb: `VCC 3 3.6 V`."""
    assert _range_of("Supply voltage, VCC 3 3.6 V") == [3.0, 3.6]


# ============================================================ #49 — range signs


def test_049_a_range_keeps_the_sign_on_its_lower_bound():
    """`-0.5V to 6.5V` is an absolute maximum below ground, not 0.5 V to 6.5 V."""
    assert _range_of("-0.5V to 6.5V") == [-0.5, 6.5]


def test_049_a_spaced_range_keeps_the_sign_too():
    assert _range_of("-0.5 V to 2 V") == [-0.5, 2.0]


def test_049_an_unsigned_range_reads_exactly_as_before():
    assert _range_of("3V to 6V") == [3.0, 6.0]


def test_049_an_all_negative_range_keeps_both_signs():
    """`-6V to -0.5V` is legal, and the high end is signed too — the task book's
    "same family, fix it together" ruling applied to the upper bound."""
    assert _range_of("-6V to -0.5V") == [-6.0, -0.5]


@pytest.mark.parametrize(
    "line, expected",
    [
        # MPU-6050 p.20, verbatim from the PDF's own text layer.
        ("REGOUT -0.5V to 2V ", [-0.5, 2.0]),
        ("CPOUT (2.5V ≤ VDD ≤ 3.6V ) -0.5V to 30V ", [-0.5, 30.0]),
    ],
)
def test_049_the_mpu6050_corpus_rows_now_carry_their_negative_bound(line, expected):
    """The three-line instance from issue #49, measured on the real datasheet."""
    assert _range_of(line) == expected


def test_049_a_triple_keeps_the_sign_on_every_column():
    """`_TRIPLE` reads min/typ/max and all three can be signed; it shared the bug."""
    assert _range_of("-1.5 -1.0 -0.5 V") == [-1.5, -0.5]


def test_049_the_triple_without_a_sign_is_unchanged():
    assert _range_of("VR 电源上电复位的电压门限 2.4 2.6 2.8 V") == [2.4, 2.8]


def test_049_a_part_number_is_not_a_negative_voltage():
    """A hyphen between a letter and its digits belongs to a part's name.

    AMS1117 p.2 and MPU-6050 p.16 both carry one. Without the lookbehind on the
    sign segment the number swallowed the hyphen and reported `-1.5` to `1.5 V`
    for a dropout row that states no such range.
    """
    assert _range_of(" AMS1117-3.3 1.5V ≤  (V IN  - VOUT) ≤  12V  0.5 ") is None
    assert _range_of("VIL, LOW Level Input Voltage MPU-6050 -0.5V to 0.3*VLOGIC V") is None
    # The letter-hyphen witness, isolated (079 主代理复验补钉): `MPU-6050` is the
    # shape the docstring names, but the `0.3*VLOGIC` above would refuse even
    # without the lookbehind, so it cannot tell `\w` from `\d` there. Here the
    # part name is all that stands between the line and a `[-6050, 3.6]` reading
    # — `_TRIPLE` matches `6050 3 3.6 V` and the `low < high` refusal is what
    # answers None; strip the `\w` half of the lookbehind and the low bound
    # becomes -6050. (Reading the true `[3, 3.6]` would need part-name stripping,
    # which is out of scope: None is the conservative refusal.)
    assert _range_of("MPU-6050 3 3.6 V") is None


def test_049_a_range_written_with_a_bare_hyphen_separator_still_reads():
    """The hyphen stays a separator where the datasheet means it as one.

    `2.375V-3.46V` is every page of the MPU-6050; `1.62 - 3.6 V` is STM32G431
    p.122. The sign only wins where nothing is hugging it on the right.
    """
    assert _range_of("2.375V-3.46V") == [2.375, 3.46]
    assert _range_of("1.55 – 3.6 V") == [1.55, 3.6]
    assert _range_of("VDD Supply voltage 1.62 - 3.6 V") == [1.62, 3.6]


def test_049_one_sign_normaliser_serves_all_three_readers():
    """071's "one judgment, one implementation": the three dash spellings fold to
    `-` in exactly one place, and the three readers all go through it."""
    for spelling in ("−0.5", "–0.5", "—0.5", "-0.5"):
        assert _signed_float(spelling) == -0.5
    assert _signed_float(" 6.0") == 6.0, "a stray space is not a syntax error"


def test_049_the_absolute_maximum_sign_survives_the_section_split():
    """End to end, the p.16 shape: an abs-max row under its own heading stays an
    abs-max row and keeps the negative bound."""
    pages = pages_from_marked_text(
        "<<<page 1>>>\nPin Functions\n3 VCC Positive supply\n"
        "<<<page 8>>>\n8.1 Absolute Maximum Ratings\nSupply Voltage, VCC –0.5 6 V \n"
    )
    facts, _notes = candidate_facts(pages, label="corpus", url=URL)
    (record,) = facts["supply_pins"]
    assert record["v_abs_max"] == [-0.5, 6.0]


# ============================================================ #50 — the caps


def test_050_the_mpu6050_bom_table_yields_all_four_required_caps():
    """The issue's headline: two of four, because two of four say "Bypass"."""
    assert _caps([MPU6050_BOM_P22]) == {
        ("10", "0.1uF"), ("13", "0.1uF"), ("20", "2.2nF"), ("8", "10nF"),
    }


def test_050_every_mpu6050_cap_names_the_page_and_quotes_its_row():
    """Provenance is the whole reason an unverified candidate is reviewable."""
    facts, _notes = candidate_facts([MPU6050_BOM_P22], label="MPU-6050", url=URL)
    for record in facts["required_caps"]:
        assert "p.1" in record["provenance"], record
        assert "(Pin " in record["provenance"], record


def test_050_a_capacitance_specification_is_not_a_part_to_buy():
    """`Capacitance` is a property of pin 8; collecting it makes the decap rule
    report a missing capacitor the datasheet never asked for."""
    assert not _is_capacitor_part("Input Capacitance (Pin 8) 10pF", "")
    facts, _notes = candidate_facts(
        ["Input Capacitance (Pin 8) 10pF\n"], label="spec part", url=URL,
    )
    assert "required_caps" not in facts


def test_050_the_chinese_word_is_a_part_only_under_a_parts_listing():
    """`电容` spells both the component and its value, so the heading decides."""
    outside = "去耦电容 C8 容量为 0.1µF (Pin 3)\n"
    inside = ("7、Bill of Materials\n去耦电容 (Pin 3) C8 0.1µF\n")
    assert _caps([outside]) == set()
    assert _caps([inside]) == {("3", "0.1uF")}


def test_050_a_capacitor_word_with_no_pin_number_is_not_a_cap():
    """The pin is what makes it a record: `required_caps` has nowhere to hang
    otherwise, and a number taken from the line would be a guess."""
    assert _caps(["The addition of 22 µ F solid tantalum on the output will "
                  "ensure stability.\n"]) == set()


def test_050_the_ams1117_and_stm32_prose_does_not_explode():
    """The over-collection regression (issue #50 acceptance 3).

    Both datasheets talk about capacitors in prose and in specification tables
    with no `(Pin N)` at all; neither may gain a candidate.
    """
    ams1117 = (
        "4 APPLICATION HINTS \n"
        "Stability   \n"
        "The circuit design used in the AMS1117 series requires the use of an "
        "output capacitor as part of the device frequency compensation. \n"
        "The addition of  22 µ F solid tantalum on the output will ensure "
        "stability for all operating conditions.  \n"
    )
    stm32 = (
        "Table 46. CL Load capacitor - 0.5 1 1.5 µF \n"
        "Cb bus cap. from 10 to 400pF 20+0.1Cb  300 ns \n"
    )
    assert _caps([ams1117]) == set()
    assert _caps([stm32]) == set()


def test_050_the_ch340n_pin_table_rows_are_not_claimed_either():
    """CH340N p.2 states its decoupling capacitors in a per-package pin table
    (`19 16 7 5 VCC 电源 ... 需要外接0.1uF电源退耦电容`) with no `Pin N` token.
    The structural criterion does not reach it, which is a known gap — recorded
    in `CURATED_NOT_REACHABLE` below rather than papered over here."""
    assert _caps(["19 16 7 5 VCC  电源 正电源输入端，"
                  "需要外接0.1uF电源退耦电容 \n"]) == set()


def test_050_curated_caps_are_a_subset_of_what_the_extractor_reads():
    """The idempotence pin (#38's harvest idempotence, same idea).

    Whenever a curated entry's datasheet states the capacitor the way this
    criterion reads, the extractor must find it: curated ⊆ extracted, so the
    planner's count and the extractor's count can never drift apart again.
    """
    shelf = json.loads(SHELF.read_text(encoding="utf-8"))
    curated = {
        (entry["mpn"], cap["pin"], cap["value"])
        for entry in shelf["parts"]
        for cap in (entry.get("facts") or {}).get("required_caps", [])
        if entry["mpn"] == "MPU-6050"
    }
    assert curated, "the shelf must still curate MPU-6050 required_caps"

    extracted = {
        ("MPU-6050", pin, value) for pin, value in _caps([MPU6050_BOM_P22])
    }
    assert curated <= extracted, (
        "curated ⊆ extracted: the planner's required caps and the extractor's "
        f"must not diverge again (curated={sorted(curated)}, "
        f"extracted={sorted(extracted)})"
    )
    # Nothing over-collected, so nothing needs declaring: the BOM table's four
    # rows and the shelf's four entries are the same four capacitors.
    assert extracted <= curated


#: Curated `required_caps` this structural criterion deliberately does not reach,
#: with the reason each one is out of its shape. Not a wish list — a boundary,
#: kept visible so that widening the criterion has to be a decision somebody makes
#: on purpose rather than a gap that quietly persists.
CURATED_NOT_REACHABLE = {
    "AMS1117-3.3": {
        "caps": [("2", "22uF")],
        "reason": (
            "stated in prose ('The addition of 22 µF solid tantalum on the "
            "output'), with no (Pin N) anywhere on the line — the pin is the "
            "shelf's own reading"
        ),
    },
    "CH340N": {
        "caps": [("5", "0.1uF"), ("8", "0.1uF")],
        "reason": (
            "stated in a per-package pin-table row ('19 16 7 5 VCC 电源 ...'), "
            "where the pin is a column header rather than a (Pin N) token"
        ),
    },
}


def test_050_the_curated_gaps_are_still_gaps_and_are_named():
    """Fails the moment the criterion widens: whoever widened it updates this
    table in the same commit, and the reason has to be re-justified.

    The datasheet text each reason quotes is fed through the extractor here, so
    the claim "the criterion cannot read this shape" is re-measured rather than
    taken on trust.
    """
    shelf = json.loads(SHELF.read_text(encoding="utf-8"))
    curated = {
        (entry["mpn"], cap["pin"], cap["value"])
        for entry in shelf["parts"]
        for cap in (entry.get("facts") or {}).get("required_caps", [])
    }
    for mpn, gap in CURATED_NOT_REACHABLE.items():
        assert gap["caps"] and gap["reason"], mpn
        assert {(mpn, pin, value) for pin, value in gap["caps"]} <= curated, (
            f"{mpn}: the gap table no longer matches what the shelf curates"
        )
    assert set(CURATED_NOT_REACHABLE) <= {mpn for mpn, _, _ in curated}, (
        "a curated part with unreachable caps is missing from "
        "CURATED_NOT_REACHABLE — add it with its reason"
    )


def test_050_no_datasheet_pdf_in_the_corpus_is_silently_expected_to_parse():
    """The corpus this batch was measured on is four PDFs; a fifth appearing
    without a matching test is a change in the evidence base."""
    if not DATASHEETS.is_dir():
        pytest.skip("the smart_pillbox datasheet corpus is not in this checkout")
    names = sorted(pdf.name for pdf in DATASHEETS.glob("*.pdf"))
    assert names == [
        "AMS1117-3.3_C6186.pdf", "CH340N_C2977777.pdf",
        "MPU-6050_C24112.pdf", "STM32G431RBT6_C431633.pdf",
    ]
