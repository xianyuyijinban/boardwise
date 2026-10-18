"""517: 被动件的参数从归档元数据本身拿全（层 0，零网络）.

Three seams, one file:

* the **parser** (:mod:`boardwise.core.metaparams`) — what a catalogue string
  (``LCSC Part Name`` / ``Type``) and an MPN state about a passive's value /
  tolerance / power / voltage, read conservatively (a token the grammar does
  not name is skipped, never guessed at);
* the **crosscheck** — three sources (archive / board ``Value`` / MPN),
  confirmed only when ≥2 agree; ≥2 available and clashing is a WARN with every
  reading written out; one alone confirms nothing;
* the **gate wiring** (:mod:`boardwise.engines.checkup`) — a confirmed part no
  longer lands in ``UNKNOWN_REASON_UNDECODABLE``'s path, with the evidence
  (which two sources agreed) in the trace rows; the four buckets
  (已确认 / 冲突 / 缺失 / 不可解析) counted separately, because a parse failure
  is not "missing data".

``UNKNOWN_REASON_UNDECODABLE``'s own semantics are untouched: it still names
exactly 「MPN 值码解不出，板上 Value 也读不出」, and the metadata check is asked
beside it, not through it.

The fixtures are **constructed components** (the board ``Value`` / ``props``
shape the parsers build from the tracked boards) — not a real board: the real
archive strings quoted (``330kΩ ±5% 250mW 厚膜电阻``,
``0603B103K500NT``) are the ones the task book measured, and the assertion is
about the grammar, not about any project.
"""

from __future__ import annotations

import pytest

from boardwise.core.metaparams import (
    CONFIRMED,
    SINGLE,
    WARN_CONFLICT,
    catalogue_params,
    confirmed_params,
    crosscheck,
    mpn_params,
    warns_params,
)
from boardwise.core.model import Component, DesignModel
from boardwise.engines.checkup import (
    META_STATE_CONFIRMED,
    META_STATE_CONFLICT,
    META_STATE_MISSING,
    META_STATE_UNPARSEABLE,
    UNKNOWN_REASON_UNDECODABLE,
    metadata_conflict_rows,
    metadata_parameter_rows,
    metadata_state_counts,
    unreviewed_parts,
)


def _component(designator: str, **kwargs) -> Component:
    return Component(uid=designator.lower(), designator=designator, **kwargs)


def _model(**components: Component) -> DesignModel:
    model = DesignModel()
    model.components.update(components)
    return model


# ---------------------------------------------------------------------------
# the catalogue parser: what it reads and what it refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value, tolerance, power, voltage",
    [
        # the task book's measured strings, verbatim
        ("330kΩ ±5% 250mW 厚膜电阻", 330e3, 0.05, 0.25, None),
        ("100nF ±10% 50V X7R 0603", 100e-9, 0.10, None, 50.0),
        ("330kΩ ±1% 1/4W 厚膜电阻", 330e3, 0.01, 0.25, None),
        # fractions, µ spellings, inductors
        ("4.7uH ±20% 1A", 4.7e-6, 0.20, None, None),
        ("22µF ±20% 16V", 22e-6, 0.20, None, 16.0),
        ("10Ω ±1% 0.25W", 10.0, 0.01, 0.25, None),
        ("1MΩ ±5%", 1e6, 0.05, None, None),
        ("100Ω ±1% 1/10W 厚膜电阻", 100.0, 0.01, 0.1, None),
    ],
)
def test_the_catalogue_grammar_reads_the_measured_strings(
    text, value, tolerance, power, voltage
):
    params = catalogue_params(text)
    read = params.stated()
    assert read["value"].value == pytest.approx(value)
    assert read["tolerance"].value == pytest.approx(tolerance)
    if power is None:
        assert "power" not in read
    else:
        assert read["power"].value == pytest.approx(power)
    if voltage is None:
        assert "voltage" not in read
    else:
        assert read["voltage"].value == pytest.approx(voltage)
    # every reading quotes the token it came from — the evidence rule
    assert read["value"].text in text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "X7R 0603",          # dielectric + size: nothing states a quantity
        "厚膜电阻",           # pure prose
        "电容式触摸按键芯片(TTP223)",  # an IC's catalogue name states no passive
        "0Ω jumper",         # zero is not a value
    ],
)
def test_the_catalogue_grammar_refuses_what_it_does_not_recognise(text):
    assert catalogue_params(text).stated() == {}


def test_a_mf_spelling_in_prose_is_refused_like_the_mid_letter_readers_refuse_it():
    """``1MF`` is a pseudo-reading, not a millifarad the catalogue states."""
    assert "value" not in catalogue_params("1MF 电容").stated()


def test_a_parameter_the_grammar_misses_is_absent_not_zero():
    """「解析失败 ≠ 缺资料」的另一半：缺字段就是缺字段，不是 0。"""
    params = catalogue_params("330kΩ 厚膜电阻")
    read = params.stated()
    assert read["value"].value == pytest.approx(330e3)
    assert "tolerance" not in read and "power" not in read


# ---------------------------------------------------------------------------
# the MPN reading: the values.py decoders, asked and scaled
# ---------------------------------------------------------------------------


def test_the_mpn_reader_decodes_the_ceramic_field():
    """``0603B104K500NT`` = 100 nF ±10% 50 V — value, tolerance, rating."""
    params = mpn_params("0603B104K500NT", kind="capacitor")
    read = params.stated()
    assert read["value"].value == pytest.approx(100e-9)
    assert read["tolerance"].value == pytest.approx(0.10)
    assert read["voltage"].value == pytest.approx(50.0)


def test_the_mpn_reader_decodes_the_frc_e96_field():
    params = mpn_params("FRC0603F1000TS", kind="resistor")
    assert params.stated()["value"].value == pytest.approx(100.0)


def test_an_ambiguous_mpn_is_no_reading_at_all():
    """Several candidates is the decoders' own 「ambiguous」 — None here too."""
    assert mpn_params("123456789012345678901234", kind="resistor").value is None


def test_an_inductor_mpn_is_refused_because_no_inductance_parser_exists():
    """Refusing the *value* is the honest answer; inventing a base would be a
    second decoder. The rating reader (092's) is shared and still reads."""
    params = mpn_params("FTC252012S100MB", kind="inductor")
    assert params.value is None


def test_a_tolerance_letter_is_read_only_in_the_field_position():
    """``K`` in the ceramic tail is ±10%; ``K`` elsewhere is not read at all."""
    assert mpn_params("RK73H1JTTD1002F", kind="resistor").tolerance is None


# ---------------------------------------------------------------------------
# the crosscheck: ≥2 agree confirms, ≥2 clash warns, 1 alone confirms nothing
# ---------------------------------------------------------------------------


def test_two_agreeing_sources_confirm_and_name_them():
    rows = crosscheck(
        "100nF ±10% 50V X7R 0603", "100nF", "ZZZZ123X", kind="capacitor"
    )
    assert rows["value"].state == CONFIRMED
    assert set(rows["value"].agreeing) == {"archive", "board"}


def test_archive_and_mpn_confirm_without_a_board_value():
    rows = crosscheck(
        "100nF ±10% 50V X7R 0603", "", "0603B104K500NT", kind="capacitor"
    )
    assert rows["value"].state == CONFIRMED
    assert set(rows["value"].agreeing) == {"archive", "mpn"}
    assert rows["tolerance"].state == CONFIRMED
    assert rows["voltage"].state == CONFIRMED


def test_two_clashing_sources_warn_and_write_every_reading_out():
    rows = crosscheck("330kΩ ±5%", "100kΩ", "ZZZZ777X", kind="resistor")
    row = rows["value"]
    assert row.state == WARN_CONFLICT
    assert row.readings["archive"] == pytest.approx(330e3)
    assert row.readings["board"] == pytest.approx(100e3)
    assert row.agreeing == ()
    # the WARN carries its evidence, not just numbers
    assert warns_params(rows)["value"] is row


def test_a_single_source_confirms_nothing():
    rows = crosscheck("330kΩ ±5% 250mW", "", "ZZZZ999X", kind="resistor")
    assert rows["value"].state == SINGLE
    assert confirmed_params(rows) == {}


def test_a_parameter_no_source_states_is_absent():
    assert "power" not in crosscheck(
        "330kΩ ±5%", "330kΩ", "ZZZZ111X", kind="resistor"
    )


def test_a_war_never_masks_as_confirmed():
    """两路可得且不一致 → WARN，不静默选一个（任务书第 2 条）。"""
    rows = crosscheck("100nF", "10nF", "", kind="capacitor")
    assert rows["value"].state == WARN_CONFLICT
    assert confirmed_params(rows) == {}


# ---------------------------------------------------------------------------
# the gate wiring: confirmed parts leave the list, with their evidence
# ---------------------------------------------------------------------------


def test_a_confirmed_part_leaves_the_undecodable_path_with_its_evidence():
    """Archive + MPN agree on 100 nF, board ``Value`` empty: no 「值不可知」."""
    model = _model(
        C1=_component(
            "C1",
            value="",
            mpn="0603B104K500NT",
            props={"LCSC Part Name": "100nF ±10% 50V X7R 0603"},
        ),
    )
    reasons = {row["designator"]: row["reasons"] for row in unreviewed_parts(model)}
    assert UNKNOWN_REASON_UNDECODABLE not in reasons["C1"]
    rows = metadata_parameter_rows(model)
    assert [row["designator"] for row in rows] == ["C1"]
    # the deliverable: **which two** agreed
    assert set(rows[0]["confirmedBy"]) == {"archive", "mpn"}
    assert rows[0]["value"] == pytest.approx(100e-9)


def test_an_undecodable_mpn_with_an_agreeing_board_value_leaves_too():
    """The board value ``10kΩ 5%`` is unreadable by the strict parser (so the
    part is on the gate) and readable by the catalogue grammar — archive and
    board agree, and the part leaves with the pair named."""
    model = _model(
        R2=_component(
            "R2",
            value="10kΩ 5%",
            mpn="ZZZZX",
            props={"LCSC Part Name": "10kΩ ±5% 1/4W 厚膜电阻"},
        ),
    )
    reasons = {row["designator"]: row["reasons"] for row in unreviewed_parts(model)}
    assert UNKNOWN_REASON_UNDECODABLE not in reasons["R2"]
    rows = metadata_parameter_rows(model)
    assert set(rows[0]["confirmedBy"]) == {"archive", "board"}


def test_a_clashing_part_stays_on_the_gate_and_is_a_named_conflict():
    """Archive says 4.7 k, board ``Value`` says 10 k: WARN, never a silent pick.

    The board value is written the way boards write annotated values
    (``10kΩ 5%``) — unreadable by the strict parser, read by the catalogue
    grammar — and the MPN decodes to nothing, so the part really is on the
    「值不可知」 path; the metadata conflict is what keeps it there.
    """
    model = _model(
        R3=_component(
            "R3",
            value="10kΩ 5%",
            mpn="ZZZZX",
            props={"LCSC Part Name": "4.7kΩ ±5%"},
        ),
    )
    reasons = {row["designator"]: row["reasons"] for row in unreviewed_parts(model)}
    assert UNKNOWN_REASON_UNDECODABLE in reasons["R3"]
    conflicts = metadata_conflict_rows(model)
    assert [row["designator"] for row in conflicts] == ["R3"]
    detail = conflicts[0]["params"]["value"]
    assert detail["readings"]["archive"] == pytest.approx(4.7e3)
    assert detail["readings"]["board"] == pytest.approx(10e3)


def test_a_single_source_still_needs_the_datasheet_question():
    """One source alone confirms nothing — the part stays on the gate."""
    model = _model(
        R1=_component(
            "R1",
            value="",
            mpn="ZZZZX",
            props={"LCSC Part Name": "330kΩ ±5% 250mW"},
        ),
    )
    reasons = {row["designator"]: row["reasons"] for row in unreviewed_parts(model)}
    assert UNKNOWN_REASON_UNDECODABLE in reasons["R1"]
    assert metadata_parameter_rows(model) == []


def test_unknown_reason_undecodable_keeps_its_own_meaning():
    """The constant's text is untouched — 517 reads beside it, not through it."""
    assert "MPN" in UNKNOWN_REASON_UNDECODABLE and "Value" in UNKNOWN_REASON_UNDECODABLE


# ---------------------------------------------------------------------------
# the four buckets: missing ≠ unparseable, and confirmed parts are counted
# ---------------------------------------------------------------------------


def test_the_four_buckets_count_separately():
    model = _model(
        C1=_component(
            "C1", value="", mpn="0603B104K500NT",
            props={"LCSC Part Name": "100nF ±10% 50V X7R 0603"},
        ),
        C3=_component(
            "C3", value="10nF", mpn="ZZZZ456X",
            props={"LCSC Part Name": "100nF ±10% 50V"},
        ),
        R4=_component("R4", value="", mpn="ZZZZ666X", props={}),
        R5=_component("R5", value="", mpn="ZZZZ555X", props={"Type": "厚膜电阻"}),
    )
    counts = metadata_state_counts(model)
    assert counts[META_STATE_CONFIRMED] == 1
    assert counts[META_STATE_CONFLICT] == 1
    assert counts[META_STATE_MISSING] == 1
    assert counts[META_STATE_UNPARSEABLE] == 1


def test_a_parse_failure_is_never_counted_as_missing():
    """The product's core requirement, as a count: 不可解析 is its own bucket."""
    model = _model(
        R5=_component("R5", value="", mpn="ZZZZ555X", props={"Type": "厚膜电阻"}),
        R4=_component("R4", value="", mpn="ZZZZ666X", props={}),
    )
    counts = metadata_state_counts(model)
    assert counts.get(META_STATE_UNPARSEABLE) == 1
    assert counts.get(META_STATE_MISSING) == 1
    assert META_STATE_UNPARSEABLE != META_STATE_MISSING


def test_ics_and_thermistors_are_not_in_the_metadata_question():
    from boardwise.core.partkind import KIND_THERMISTOR  # noqa: F401

    model = _model(
        U1=_component(
            "U1", mpn="TTP223", pins=6,
            props={"LCSC Part Name": "电容式触摸按键芯片(TTP223)"},
        ),
        R7=_component(
            "R7", mpn="HNTC0603-103F3450FA",
            props={"LCSC Part Name": "NTC 热敏电阻"},
        ),
    )
    assert metadata_state_counts(model) == {}
    assert metadata_parameter_rows(model) == []
    assert metadata_conflict_rows(model) == []


def test_the_confirmed_count_covers_parts_the_rows_below_do_not_carry():
    """已确认 parts are not in `unreviewed_parts[]` — the bucket is their trace."""
    model = _model(
        C1=_component(
            "C1", value="", mpn="0603B104K500NT",
            props={"LCSC Part Name": "100nF ±10% 50V X7R 0603"},
        ),
    )
    assert "value" not in catalogue_params("").stated()  # import sanity
    remaining = [
        row for row in unreviewed_parts(model)
        if UNKNOWN_REASON_UNDECODABLE in row["reasons"]
    ]
    assert remaining == []
    assert metadata_state_counts(model)[META_STATE_CONFIRMED] == 1


# ---------------------------------------------------------------------------
# the report: the evidence and the buckets are written out
# ---------------------------------------------------------------------------


def test_the_report_prints_the_confirmed_evidence_and_the_conflicts():
    from boardwise.engines.checkup import render_report_markdown

    model = _model(
        C1=_component(
            "C1", value="", mpn="0603B104K500NT",
            props={"LCSC Part Name": "100nF ±10% 50V X7R 0603"},
        ),
        C3=_component(
            "C3", value="10nF", mpn="ZZZZ456X",
            props={"LCSC Part Name": "100nF ±10% 50V"},
        ),
    )
    report = {
        "unreviewed_parts": [
            {
                "designator": "C3", "mpn": "ZZZZ456X", "supplier": "",
                "reasons": [UNKNOWN_REASON_UNDECODABLE],
                "missingFacts": [], "channels": {},
            },
        ],
        "summary": {"errors": 0},
        "metadataValueConfirmed": metadata_parameter_rows(model),
        "metadataValueConflicts": metadata_conflict_rows(model),
        "metadataStateCounts": metadata_state_counts(model),
    }
    text = render_report_markdown(report)
    # the four buckets, with the 不可解析 ≠ 缺资料 discipline spelled out
    assert "元数据已确认 1" in text and "元数据冲突 1" in text
    assert "这是读法缺口，不是缺资料" in text
    # the confirmed part names **which two** sources agreed
    assert "`C1`" in text and "archive + mpn" in text
    # the conflict writes every reading out
    assert "board=1e-08" in text and "archive=1e-07" in text
