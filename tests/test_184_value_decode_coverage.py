"""184 — 「未审器件」 was asking the wrong question, and the decoder was blind to four families.

The board feedback this file is the executable half of (岳 2026-10-15, real board
``.tmp_bug98b/实板A.epro2``): 34 of its 68 unreviewed parts were on the
list because ``mpn_value_code`` — one of *two* value decoders — does not spell
their part number. Every one of those parts has a readable ``Value`` field on the
board, and the resistance families it could not read are read by
``mpn_resistance_candidates``. So the gate asked "does the EIA whitelist know this
MPN?" while the review needs "can this part's value be known at all?".

Three things are pinned here, in the order they fail:

1. **the board's table** — the 14 MPNs of the feedback plus 6 control parts (the
   previously-decoded whitelist shapes and the two 国巨 spellings the feedback
   named), each with the value its own board declares it at;
2. **the four families the decoder was blind to** — FRC's four-figure E-96 field
   in front of a taping tail, Vishay's ``WSL…R1000…`` four-figure fraction, the
   ceramic ``<value><tol><voltage>NT`` field, and 国巨's vendor power code;
3. **the gate and the counts** — a readable board value is no longer an
   UNDECODABLE, an unreadable one still is, and the report's new
   ``unreviewedByReason`` split is counted from the rows it describes.

The board itself is **not** copied into this repository (它 is 岳's product board,
kept read-only in the working tree): every witness here is either a synthetic
model or a shelf entry / fixture that already lives in the repo, and the real
board's own before/after is recorded in ``outputs/184_value_decode/evidence.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component, DesignModel
from boardwise.core.parts import load_parts
from boardwise.core.values import (
    ANCHOR_E96_LETTER,
    decode_eia_3digit,
    mpn_resistance_candidates,
    mpn_value_code,
    parse_capacitance_farads,
    parse_resistance_ohms,
)
from boardwise.engines.checkup import (
    UNKNOWN_REASON_UNDECODABLE,
    unknown_parts,
    unreviewed_counts_by_reason,
)

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "blocklib" / "parts.json"
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"

_CAP_BASE = 1e-12
_OHM_BASE = 1.0


def component(designator: str, *, value: str = "", mpn: str = "", supplier: str = "C1") -> Component:
    return Component(
        uid=f"u-{designator}", designator=designator, value=value, footprint="",
        mpn=mpn, lcsc_part=supplier, props={},
    )


def model_of(*components: Component) -> DesignModel:
    return DesignModel(
        components={part.designator: part for part in components}, nets={}
    )


# --------------------------------------------------------------------------
# ① the feedback table
# --------------------------------------------------------------------------

#: ``(mpn, prefix, the board's own Value, expected EIA code, expected readings)``.
#:
#: The first 14 are the distinct MPNs of the feedback's 34 rows, with the ``Value``
#: string that board declares (``""`` where the field is empty — those are the
#: rows the MPN alone has to answer for). The last 6 are the control parts: the
#: two 国巨 spellings the feedback named, their 4K7 sibling from the 071 family,
#: and three shapes the whitelist already read (``CRCW06031K00FKEA``,
#: ``FRC0805J471``, ``CL10A225KA8NNNC``) so a new reader cannot pass by having
#: broken the old ones.
FEEDBACK_TABLE: tuple[tuple[str, str, str, str | None, tuple[float, ...]], ...] = (
    # --- the board's 14 (empty reading tuple = the EIA code is the reading) ---
    ("0603B103K500NT", "C", "10nF", "103", ()),
    ("0603B225K250NT", "C", "", "225", ()),
    ("CGA1206X7R104K501NT", "C", "100nF", "104", ()),
    ("ERA16V100M5X7", "C", "100uF", None, ()),
    ("FRC0603F1000TS", "R", "", None, (100.0,)),
    ("FRC0603F1500TS", "R", "150Ω", None, (150.0,)),
    ("0603WAF1001T5E", "R", "1kΩ", None, (1000.0,)),
    ("FRC0603F3301TS", "R", "3.3kΩ", None, (3300.0,)),
    ("WSL1206R1000FEA", "R", "100mΩ", None, (0.1,)),
    ("1206W4F2001T5E", "R", "2kΩ", None, (2000.0,)),
    ("FRC0603F4701TS", "R", "", None, (4700.0,)),
    ("1206W4F1004T5E", "R", "", None, (1_000_000.0,)),
    ("FRC0603F1002TS", "R", "10kΩ", None, (10_000.0,)),
    ("0603WAF1002T5E", "R", "10kΩ", None, (10_000.0,)),
    # --- the 6 controls ---
    ("RC0603FR-071KL", "R", "1kΩ", None, (1000.0,)),
    ("AC0603FR-071KL", "R", "1kΩ", None, (1000.0,)),
    ("RC0603FR-074K7L", "R", "4.7kΩ", None, (4700.0,)),
    ("CRCW06031K00FKEA", "R", "1kΩ", None, (1000.0,)),
    ("FRC0805J471", "R", "470Ω", "471", ()),
    ("CL10A225KA8NNNC", "C", "2.2uF", "225", ()),
)


@pytest.mark.parametrize(
    "mpn,prefix,value,code,readings", FEEDBACK_TABLE,
    ids=[row[0] for row in FEEDBACK_TABLE],
)
def test_every_feedback_part_is_value_decodable(
    mpn: str, prefix: str, value: str, code: str | None, readings: tuple[float, ...]
) -> None:
    """One row of the feedback table, asserted on **both** decoder entry points.

    What "decodable" has to mean for this row: the MPN states the EIA code the
    board's own ``Value`` field is written as, **or** the resistance reader finds
    the board's value among its readings. A row that only satisfies "some
    decoder returns something" would pass while reading the wrong number.
    """
    assert mpn_value_code(mpn) == code, mpn
    candidates = mpn_resistance_candidates(mpn) if prefix != "C" else []
    values = {ohms for ohms, _text, _anchor in candidates}
    # The readings the row *must* contain: a family that also guesses at a
    # vendor-prefixed mantissa (国巨's ``074K7`` also reading as ``74K7``, 046)
    # legitimately carries more than the board's value, so this is a "contains",
    # and the exact sets are pinned in the family tests below.
    assert set(readings) <= values
    assert bool(values) == bool(readings), mpn
    # The gate's predicate (184 part A): the value is knowable.
    part = component(f"{prefix}1", value=value, mpn=mpn)
    board = (
        parse_capacitance_farads(value) if prefix == "C" else parse_resistance_ohms(value)
    )
    assert board is not None or code is not None or candidates, mpn

    # And the two readings agree where both speak: the code scaled into the
    # part's unit is the value the board declares, and the candidates carry it.
    if board is not None and code is not None:
        base = _CAP_BASE if prefix == "C" else _OHM_BASE
        assert decode_eia_3digit(code, base) == pytest.approx(board), mpn
    if board is not None and readings:
        assert any(ohms == pytest.approx(board, rel=1e-9) for ohms in readings), mpn


def test_the_gate_does_not_flag_any_of_the_feedback_parts():
    """The whole table through the gate at once: none of the 20 is UNDECODABLE.

    This is the shape the real board had 34 times over. Every part here has an
    MPN and a supplier, so a row may only be on the list if its value really
    cannot be known — which is what the assertion below says.
    """
    parts = unknown_parts(model_of(*[
        component(f"{prefix}{index}", value=value, mpn=mpn)
        for index, (mpn, prefix, value, _code, _readings) in enumerate(FEEDBACK_TABLE)
    ]))
    assert parts == [], [part["designator"] for part in parts]


# --------------------------------------------------------------------------
# ② the four families (184 part B)
# --------------------------------------------------------------------------


def test_the_frc_family_is_read_from_its_four_figure_field():
    """FRC's E-96 spelling, whose code sits in front of a ``TS`` taping tail.

    ``_e96_reading``'s field has to *end* the token, so this family was read by
    nothing at all. The four figures and their anchor are checked against the
    shelf's own declared values below, and against the feedback board's five
    parts in the table above.
    """
    assert mpn_resistance_candidates("FRC0603F1000TS") == [
        (100.0, "1000 (FRC E-96 field)", ANCHOR_E96_LETTER)
    ]
    # The reading is anchored: the field is pinned by the family head, the size,
    # the tolerance letter and the tail (071 §1 C's "coded field" question).
    assert all(anchor == ANCHOR_E96_LETTER for _v, _t, anchor in mpn_resistance_candidates("FRC0603F1002TS"))
    # The family's E-24 spelling (three figures, no tail) is the whitelist's and
    # keeps reading: 471 = 470 Ω, the shelf's ``res.470_0805``.
    assert mpn_value_code("FRC0805J471") == "471"
    assert mpn_value_code("FRC0805J471 TS") == "471"
    # A figure group starting with 0 is not an E-96 code, the same refusal its
    # sibling makes. A field carrying an ``R`` point is not this shape at all,
    # and needs no help: ``FRC0805F4R70TS`` is 4.7 Ω (the shelf's
    # ``res.4o7_0805``) and the mid-letter reader has always read its ``4R70``
    # -- the new reader must stay off it, not take it over.
    assert mpn_resistance_candidates("FRC0603F0123TS") == []
    assert mpn_resistance_candidates("FRC0805F4R70TS") == [(4.7, "4R70", "")]


def test_the_wsl_family_is_read_from_its_four_figure_fraction():
    """``R`` as the decimal point with the whole fraction written out.

    043 refused ``<digit>R<digits>`` (``JER2512F3R005``) and 046 read ``FR400``
    with a tolerance letter in front; neither reaches ``WSL1206R1000FEA``, whose
    ``R`` follows the size's last digit. The refusal that matters stays: the
    5 mΩ shunt of 043 still has no reading here.
    """
    assert mpn_resistance_candidates("WSL1206R1000FEA") == [
        (0.1, "R1000 (WSL shunt field)", ANCHOR_E96_LETTER)
    ]
    assert mpn_resistance_candidates("WSL2010R0100FEA") == [
        (0.01, "R0100 (WSL shunt field)", ANCHOR_E96_LETTER)
    ]
    # 043's refusal is unchanged: the digits before the ``R`` are the coding.
    assert mpn_resistance_candidates("JER2512F3R005") == []


def test_the_capacitor_voltage_tail_names_the_value_group():
    """``<value><tolerance><voltage>NT``: the tail says which group is which.

    015 refuses a token that carries a ``<value><tol><voltage>`` tail, and that
    refusal is right for the raw records it was written for. The ``NT`` printing
    names the field, so the three figures **in front of** the tolerance letter are
    the value code and the three behind it are the rating — checked against the
    board's own declared values, which are 10nF and 100nF for the first two.
    """
    assert mpn_value_code("0603B103K500NT") == "103"
    assert decode_eia_3digit("103", _CAP_BASE) == pytest.approx(parse_capacitance_farads("10nF"))
    assert mpn_value_code("CGA1206X7R104K501NT") == "104"
    assert decode_eia_3digit("104", _CAP_BASE) == pytest.approx(parse_capacitance_farads("100nF"))
    assert mpn_value_code("0603B225K250NT") == "225"
    assert decode_eia_3digit("225", _CAP_BASE) == pytest.approx(2.2e-6)


def test_the_voltage_tail_refusal_is_untouched_for_every_token_without_the_tail():
    """The refusal is the *notation*, not "a voltage tail anywhere" (184).

    Every witness 015/025/072/094 relied on keeps answering ``None``: the
    electrolytics (``PA50V330M10x15``), the TDK field string whose tail figures
    are a **thickness** (``C1608X5R1V225KT000E``) and the polymer electrolytic
    that prints microfarads (``SPZ1HM100E07O00RAXXX``).

    **188a moved three tokens out of this list** (they are asserted in
    ``tests/test_188a_value_decode.py``): ``HGC0603R5106M250NTHJ`` (-> ``106``),
    ``HGC1206R5106K500NSPJ`` (-> ``106``) and ``CGA0603X7R104K500JT``
    (-> ``104``, the shelf's own ``cap.100n_0603.c6119867``). They were never
    *not this notation* — they are the same ``<value><tol><voltage>`` field as
    ``0603B103K500NT``, printed in another house's packaging code, which is what
    184's literal ``NT`` tail could not see. The refusal itself is unchanged:
    ``_non_eia_notation`` still answers ``True`` for them (see the 188a file).
    """
    for token in (
        "PA50V330M10x15",
        "C1608X5R1V225KT000E",
        "SPZ1HM100E07O00RAXXX",
    ):
        assert mpn_value_code(token) is None, token


def test_yageo_power_code_is_not_read_as_a_value_code():
    """"国巨's ``<size>FR-<two figures>`` prefix is a power code, not a value.

    ``RC0603FR-071KL`` answered ``"071"`` before 184 — the whitelist reading the
    vendor's own field. The whole token is refused rather than only the group
    behind the dash: the figures it is glued to are the value in the mid-letter
    notation, so a three-figure group further in is part of that value
    (``RC0603FR-07200KL``, the shelf's ``res.200k_0603`` at 200 kΩ, would have
    answered ``"200"``).
    """
    for token in (
        "RC0603FR-071KL",
        "AC0603FR-071KL",
        "RC0603FR-07200KL",
        "RC0402FR-075K1L",
        "RL0805FR-070R1L",  # 078 A1's date code, refused on the same footing
    ):
        assert mpn_value_code(token) is None, token
    # 071's family does not regress: the mid-letter candidates still carry the
    # values the boards declare (1 kΩ with the vendor's 7.1 kΩ guess, 4.7 kΩ).
    assert 1000.0 in {ohms for ohms, _t, _a in mpn_resistance_candidates("RC0603FR-071KL")}
    assert 4700.0 in {ohms for ohms, _t, _a in mpn_resistance_candidates("RC0603FR-074K7L")}
    assert 200_000.0 in {ohms for ohms, _t, _a in mpn_resistance_candidates("RC0603FR-07200KL")}


# --------------------------------------------------------------------------
# ③ the shelf agrees with the readers (the measurements, not the shapes)
# --------------------------------------------------------------------------


def test_the_shelf_resistors_agree_with_the_resistance_reader():
    """Two independent readings of one number, over the whole catalogue.

    The shelf states each part's value in its own ``value`` field; the part
    number states it in its own notation. Where the reader speaks, the two must
    be the same claim — this is the measurement behind the four new readers, and
    it is what would fail if one of them read a family's field the wrong way
    round.
    """
    library = load_parts(SHELF)
    checked = 0
    for entry in library.parts:
        if not entry.key.startswith("res."):
            continue
        declared = parse_resistance_ohms((entry.value or "").strip())
        readings = [ohms for ohms, _t, _a in mpn_resistance_candidates(entry.mpn or "")]
        if declared is None or not readings:
            continue
        assert any(ohms == pytest.approx(declared, rel=1e-9) for ohms in readings), (
            entry.key, entry.mpn, entry.value, readings
        )
        checked += 1
    # 17 of the shelved resistors today (the rest state their value in the E-24
    # spelling the whitelist reads, or are the shunts 043 refuses on purpose).
    assert checked == 17, checked


def test_no_shelved_passive_is_unreviewed_for_its_value():
    """Every shelved R/C is value-decodable — with the **board's** value.

    A shelf entry is a part this project already knows how to place; if its value
    could not be known, the gate would be telling the reviewer to go and read a
    datasheet for a part the catalogue has already priced. 55 entries checked,
    0 flagged.

    This is the branch the board's own ``Value`` field answers, and it is *only*
    that branch — which is why the sibling test below
    (:func:`test_every_shelved_passive_is_decodable_from_its_mpn_alone`) exists:
    a part whose ``Value`` field is empty is the shape 184 was reported for (5 of
    its 14 feedback rows were empty), and this test cannot see it. The挖洞 swarm
    measured exactly that gap (agent-342 中-1): putting ``value=entry.value``
    into the synthetic part made the test green while every capacitor whose MPN
    spelled the rating tail in another house's packaging code was reported
    「值不可知」 the moment the field was empty.
    """
    library = load_parts(SHELF)
    flagged = []
    for entry in library.parts:
        if entry.key.startswith("res."):
            prefix = "R"
        elif entry.key.startswith("cap."):
            prefix = "C"
        else:
            continue
        part = component(f"{prefix}1", value=entry.value or "", mpn=entry.mpn or "")
        if any(
            reason == UNKNOWN_REASON_UNDECODABLE
            for row in unknown_parts(model_of(part))
            for reason in row["reasons"]
        ):
            flagged.append(entry.key)
    assert flagged == []
    assert sum(
        1 for entry in library.parts
        if entry.key.startswith(("res.", "cap."))
    ) == 55


def test_every_shelved_passive_is_decodable_from_its_mpn_alone():
    """188a: the same traversal with the board's ``Value`` field **empty**.

    The 184 test above hands every synthetic part the shelf's own ``value``
    string, so it measures the board-value branch and nothing else. This one
    hands the part an MPN and nothing more — the production shape a part is in
    before the engineer fills the field in, and the shape that made 184 report a
    whole board.

    What it pins: the catalogue's passives are readable **from their part
    number**, with the exceptions below being deliberate refusals the repo has
    argued for elsewhere — not gaps. Each exception is named, so a new shelf
    entry that cannot answer from its MPN fails here instead of hiding behind
    its own ``value`` field.

    * caps — ``C1608X5R1V225KT000E`` (TDK's tail figures are a *thickness*, #72),
      ``PA50V330M10x15`` (015's electrolytic), ``SPT1HM2R2D11ORVZC`` and
      ``SPZ1HM100E07O00RAXXX`` (polymer/aluminium series that print microfarads,
      046/015 — the EIA path must not read their digits);
    * resistors — the two 0 Ω jumpers (``CRCW06030000Z0EAHP``, ``RE1206F1R000``:
      their MPNs state no value code at all), and the three shunts whose value
      field is ``R``-notation and therefore refused on purpose
      (``RE1206F1R100``, ``RE2512F3R001``, ``JER2512F3R005`` — 015 and 043).

    Before 188a this traversal flagged the four caps in the first group *plus
    every capacitor whose MPN states its value in the structural
    ``<value><tol><voltage><packaging>`` field* (11 of the catalogue's own,
    ``FCC0603B103K500CT`` through ``HHV1206R7475K101NSPJ``) — the false green the
    swarm measured.
    """
    library = load_parts(SHELF)
    expected_caps = {
        "cap.2u2_0603.c342978",
        "cap.pa50v330m10x15",
        "cap.spt1hm2r2d11orvzc",
        "cap.spz1hm100e07o00raxxx",
    }
    expected_resistors = {
        "res.0_0603",
        "res.0_1206",
        "res.100m_1206",
        "res.5m_2512",
        "res.re2512f3r001",
    }
    flagged_caps, flagged_resistors = set(), set()
    for entry in library.parts:
        if entry.key.startswith("res."):
            prefix, bucket = "R", flagged_resistors
        elif entry.key.startswith("cap."):
            prefix, bucket = "C", flagged_caps
        else:
            continue
        part = component(f"{prefix}1", mpn=entry.mpn or "")
        if any(
            reason == UNKNOWN_REASON_UNDECODABLE
            for row in unknown_parts(model_of(part))
            for reason in row["reasons"]
        ):
            bucket.add(entry.key)
    assert flagged_caps == expected_caps, sorted(flagged_caps)
    assert flagged_resistors == expected_resistors, sorted(flagged_resistors)


# --------------------------------------------------------------------------
# ④ the gate: "value unknowable", and the counts that report it
# --------------------------------------------------------------------------


def test_a_readable_board_value_is_no_longer_an_undecodable_mpn():
    """The core of 184 part A.

    ``ERA16V100M5X7`` is the witness: an electrolytic that prints microfarads, so
    ``_foreign_unit_code`` refuses its MPN (correctly — reading its ``100`` as an
    EIA code is what reported 10 pF for a 10 µF part, task 046). Before 184 that
    refusal alone put the part on the list; the board's own ``100uF`` is a value
    the rules can use, so the part is not unknown.
    """
    parts = unknown_parts(model_of(
        component("C6", value="100uF", mpn="ERA16V100M5X7"),
        component("R7", value="100mΩ", mpn="WSL1206R1000FEA"),
        component("R8", value="10kΩ", mpn="FRC0603F1002TS"),
    ))
    assert parts == []


def test_an_empty_board_value_with_an_unreadable_mpn_is_still_undecodable():
    """The reason that has to survive: nothing on the board and nothing in the MPN.

    Two rows: a resistor whose MPN states no notation this decoder reads, and a
    capacitor whose MPN is refused as a whole. The board's ``Value`` field is
    empty for both, so the value genuinely cannot be known — which is exactly
    what ``UNKNOWN_REASON_UNDECODABLE`` now means.

    The capacitor witness is 188a's correction: 184 wrote
    ``HGC1206R5106K500NSPJ`` here, which is *not* an unreadable part — it is the
    ``<value><tol><voltage>`` field (``106K500`` = 10 µF / 50 V) in another
    house's packaging code, and since 188a it reads ``106``. What the branch has
    to be witnessed by is a token whose digits really are in a notation this
    decoder does not read: 015's electrolytic (``50 V, 330 µF`` — the figures are
    microfarads, and ``330M`` is not EIA) and 046's polymer series, both of which
    keep their ``None``.
    """
    parts = unknown_parts(model_of(
        # The shelf's own 0 Ω jumper: its MPN states no value code this decoder
        # reads (``res.0_0603``), and there is no board value to fall back on.
        component("R7", value="", mpn="CRCW06030000Z0EAHP"),
        # 015's electrolytic layout, empty ``Value``: the MPN's figures are a
        # capacitance in microfarads, so the EIA path must not touch them.
        component("C7", value="", mpn="PA50V330M10x15"),
        # 046's polymer series — refused for the same reason (``100`` is 10 µF,
        # read against the picofarad base it reported 10 pF).
        component("C8", value="", mpn="SPZ1HM100E07O00RAXXX"),
    ))
    by_ref = {part["designator"]: part for part in parts}
    assert set(by_ref) == {"R7", "C7", "C8"}
    assert all(UNKNOWN_REASON_UNDECODABLE in part["reasons"] for part in parts)


def test_a_numeric_exponent_field_answers_for_a_part_with_no_board_value():
    """The R4 shape: no ``Value`` field, and the MPN carries the number.

    ``1206W4F1004T5E`` is 100 x 10^4 = 1 MΩ in 厚声's ordering field (048), which
    the resistance candidates have read since then — so a part with no board value
    is still decodable, and the gate must not list it.
    """
    parts = unknown_parts(model_of(component("R4", value="", mpn="1206W4F1004T5E")))
    assert parts == []


def test_the_inductor_branch_is_the_honest_one():
    """``L`` has no board-value branch, and that is deliberate.

    There is no inductance parser in ``core/values.py`` (``parse_inductance`` does
    not exist), so an inductor's value is only known when its MPN carries an EIA
    code. Reading ``10uH`` with the resistance grammar — or taking
    ``DFE252012PD-2R2M=P2``'s ``2R2`` for a resistance — would invent a number, so
    both of these stay on the list. That is the honest answer, and it is why the
    ``L`` rows are the one place this batch does not narrow the gate: measured on
    the feedback board, no ``L`` row was involved.
    """
    parts = unknown_parts(model_of(
        component("L1", value="10uH", mpn="FXL1040-330-M"),
        component("L2", mpn="DFE252012PD-2R2M=P2"),
    ))
    assert [part["designator"] for part in parts] == ["L1", "L2"]
    assert all(UNKNOWN_REASON_UNDECODABLE in part["reasons"] for part in parts)
    # Every inductor the shelf carries is in the same state (measured): the
    # whitelist reads none of their MPNs, so the L rows are the one family this
    # batch leaves exactly where it found them.
    for mpn in ("FXL1040-330-M", "DFE252012PD-2R2M=P2", "FTC252012S100MBCA"):
        assert mpn_value_code(mpn) is None, mpn


def test_an_ic_is_never_asked_about_its_mpn():
    """The prefix restriction, unchanged (025): an IC's MPN carries no code."""
    parts = unknown_parts(model_of(component("U9", mpn="LM358N")))
    assert parts == []


def test_unreviewed_counts_by_reason_counts_every_row_once_per_reason():
    """One aggregation over the section's own rows, keys sorted."""
    rows = [
        {"designator": "R1", "reasons": ["无 MPN", "供应商字段为空"]},
        {"designator": "C1", "reasons": ["供应商字段为空"]},
        {"designator": "R2", "reasons": ["无 MPN"]},
        "not a row",
    ]
    assert unreviewed_counts_by_reason(rows) == {"无 MPN": 2, "供应商字段为空": 2}
    assert unreviewed_counts_by_reason(None) == {}


def test_the_report_splits_the_unreviewed_count_by_reason(capsys, tmp_path, monkeypatch):
    """``summary.unreviewedByReason`` / ``completion.unreviewedByReason`` (184 part C).

    Counted from ``unreviewed_parts`` and nothing else, so the summary, the
    completion section and the rows cannot disagree; the old keys are untouched
    (``unreviewedParts``, ``mayClaimPassed``), and the ledger says the same split
    the JSON does.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    code = cli.main([
        "checkup", "--file", str(GOLDEN), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    capsys.readouterr()
    assert code == 3, "this board has unreviewed parts -> incomplete (073)"
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    rows = report["unreviewed_parts"]
    counted = unreviewed_counts_by_reason(rows)
    assert report["summary"]["unreviewedByReason"] == counted
    assert report["completion"]["unreviewedByReason"] == counted
    assert sum(counted.values()) >= len(rows) > 0
    # The pre-184 keys still mean what they meant.
    assert report["summary"]["unreviewedParts"] == len(rows)
    assert report["completion"]["unreviewedParts"] == len(rows)
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert f"## 未审器件（{len(rows)}）" in markdown
    assert "按原因计数：" in markdown
    for reason, count in counted.items():
        assert f"{reason} {count}" in markdown
