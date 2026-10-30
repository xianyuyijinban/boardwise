"""The milliohm shunt's own MPN amplitude tolerance (oracle ruling 2026-10-30).

The oracle reported three shunts on one real board -- ``R21``/``R28``/``R32``
carrying ``0.05 Ω`` against an MPN that decodes to ``0.1 Ω`` -- and the 015
batch-2 3x band turned that 2.00x disagreement into a silent OK. The ruling is
a **shunt-specific 1.5x** (``MPN_AMPLITUDE_TOLERANCE_SHUNT``): below it the row
keeps the old "OK with its amplitude quoted" shape, at or above it the row goes
where every other contradiction already went -- WARN when the MPN reading is
anchored, UNKNOWN when it is not. Ordinary resistors stay at 3x and capacitors
at 25x; nothing here widens or bypasses the anchor gate.

The board itself is not a replayable fixture in this repository (no annotated
reviewset carries a shunt whose MPN disagrees), so every case below is
synthetic and says so. What it pins is the arithmetic and the routing, not a
re-measurement of the oracle's board.
"""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, DesignModel, Pin
from boardwise.rules.base import OUTCOME_STATES
from boardwise.rules.connectivity import ShuntSenseLink
from boardwise.rules.params import (
    MPN_AMPLITUDE_TOLERANCE_C,
    MPN_AMPLITUDE_TOLERANCE_R,
    MPN_AMPLITUDE_TOLERANCE_SHUNT,
    ValueMpnMatch,
    _is_shunt_resistor,
)
from boardwise.rules.values import parse_resistance_ohms

#: ``WSL2512R1000FEA`` is a 2512 shunt whose ``R1000`` field reads 0.1 Ω and
#: carries the package-context anchor (``WSL2512`` names the size in the same
#: token), so a contradiction on it is the WARN it always was.
ANCHORED_SHUNT_MPN = "WSL2512R1000FEA"
#: ``RL2512FK-070R1L`` reads the same 0.1 Ω through the mid-letter ``0R1`` but
#: states no package, so it is unanchored: the same 2.00x must be withheld.
UNANCHORED_SHUNT_MPN = "RL2512FK-070R1L"


def _model(**values: tuple[str, str]) -> DesignModel:
    model = DesignModel()
    for designator, (value, mpn) in values.items():
        model.components[designator] = Component(
            uid=designator.lower(),
            designator=designator,
            value=value,
            mpn=mpn,
            pins=[Pin("1", "A", "N1")],
        )
    return model


def _rows(model: DesignModel) -> list:
    return [row[0] for row in ValueMpnMatch()._rows(model)]


def _states(model: DesignModel) -> dict[str, list]:
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for outcome in ValueMpnMatch().outcomes(model):
        grouped[outcome.state].append(outcome)
    return grouped


def _ruled(model: DesignModel, designator: str):
    (outcome,) = [o for o in ValueMpnMatch().outcomes(model)
                  if o.subject == designator]
    return outcome


# --------------------------------------------------------------- the ruling


def test_the_shunt_tolerance_is_the_oracles_2026_10_30_number():
    """The constant, pinned beside the two it sits between.

    It is a ruling, not a physics constant: 0.05 Ω against a 0.1 Ω MPN is
    exactly 2.00x, which has to land outside 1.5x and inside 3x for the ruling
    to be the one that changed the verdict."""
    assert MPN_AMPLITUDE_TOLERANCE_SHUNT == 1.5
    assert MPN_AMPLITUDE_TOLERANCE_SHUNT < MPN_AMPLITUDE_TOLERANCE_R == 3.0
    assert MPN_AMPLITUDE_TOLERANCE_C == 25.0


def test_the_shunt_judge_is_the_shunt_sense_link_one():
    """No second value window: the tolerance reads the evidence
    ``shunt-sense-link`` already uses (``classify_part`` resistor + a positive
    resistance ≤ 50 mΩ), so the two rules cannot drift apart."""
    link = ShuntSenseLink()
    cases = ["0Ω", "1mΩ", "50mΩ", "50.1mΩ", "100mΩ", "1Ω", "1kΩ", "100nF", ""]
    for value in cases:
        comp = Component(uid="r1", designator="R1", value=value, mpn="",
                         pins=[Pin("1", "A", "N1")])
        assert _is_shunt_resistor(comp) is link._is_shunt(comp), value
    assert _is_shunt_resistor(
        Component(uid="r1", designator="R1", value="50mΩ", mpn="")
    ) is True
    assert _is_shunt_resistor(
        Component(uid="r1", designator="R1", value="50.1mΩ", mpn="")
    ) is False, "the ceiling is the shunt rule's, boundary included"


# ------------------------------------------------- the reported shape: 2.00x


def test_the_reported_shunts_leave_the_tolerance_ok():
    """``R21``/``R28``/``R32`` at 0.05 Ω against a 0.1 Ω MPN: 2.00x, which used
    to read "below the 3x tolerance" and is now a contradiction.

    The MPN is anchored, so the row is the WARN every contradiction on an
    anchored reading already was -- no new severity, no new target shape."""
    model = _model(**{
        "R21": ("0.05Ω", ANCHORED_SHUNT_MPN),
        "R28": ("0.05Ω", ANCHORED_SHUNT_MPN),
        "R32": ("0.05Ω", ANCHORED_SHUNT_MPN),
    })
    states = _states(model)
    assert states["OK"] == [], "no shunt row may be waived at 2.00x any more"
    assert states["UNKNOWN"] == []
    violations = {o.subject: o for o in states["VIOLATION"]}
    assert sorted(violations) == ["R21", "R28", "R32"]
    for designator, outcome in violations.items():
        assert "2.00x apart, at or above the 1.5x tolerance" in outcome.message
        assert "3x tolerance" not in outcome.message
        assert "锚点：" in outcome.message
        assert designator in outcome.message
    findings = ValueMpnMatch().check(model)
    assert {f.target.component_ref for f in findings} == {"R21", "R28", "R32"}
    assert {f.severity for f in findings} == {"WARN"}


def test_the_reported_shape_is_still_withheld_without_an_anchor():
    """The same 2.00x on an unanchored reading is UNKNOWN, not WARN: 1.5x
    decides *which* existing path the row takes, it does not lower the bar for
    accusing a BOM line (071 §1 C)."""
    model = _model(R21=("0.05Ω", UNANCHORED_SHUNT_MPN))
    outcome = _ruled(model, "R21")
    assert outcome.state == "UNKNOWN"
    assert "2.00x apart, at or above the 1.5x tolerance" in outcome.message
    assert "字符串解码无锚点，低置信" in outcome.message
    assert outcome.missing_fact
    assert ValueMpnMatch().check(model) == []


# --------------------------------------------------------------- the edges


def test_149x_on_a_shunt_is_still_an_ok_with_its_amplitude():
    """1.49x is the last waived step, and the waiver is not silence: the row
    quotes the amplitude and names the 2026-10-30 ruling instead of the 015
    one that produced 3x."""
    assert 0.0745 / 0.05 == pytest.approx(1.49)
    model = _model(R21=("0.05Ω", "WSL2512R0745FEA"))
    states = _states(model)
    assert states["VIOLATION"] == [] and states["UNKNOWN"] == []
    (waived,) = states["OK"]
    assert "1.49x" in waived.message
    assert "below the 1.5x tolerance" in waived.message
    assert "2026-10-30" in waived.message
    assert "015 batch-2" not in waived.message, (
        "the 3x quote belongs to the ordinary-resistor ruling, not this one"
    )
    assert "R21 value '0.05Ω'" in waived.evidence


def test_150x_exactly_is_outside_the_tolerance():
    """The boundary is inclusive on the contradiction side, as it was at 3x and
    25x: a ratio *strictly* below the tolerance is OK.

    0.075/0.05 is 1.4999999999999998 in binary floating point, so this also
    pins the rounded comparison that keeps a rounding error from stepping over
    the boundary the ruling drew."""
    assert 0.075 / 0.05 < 1.5  # the dust this test exists for
    model = _model(R21=("0.05Ω", "WSL2512R0750FEA"))
    outcome = _ruled(model, "R21")
    assert outcome.state == "VIOLATION"
    assert "1.50x apart, at or above the 1.5x tolerance" in outcome.message


def test_an_ordinary_resistor_at_213x_is_unmoved():
    """The golden board's 1k-vs-470 pair: 2.13x is below the *resistors'* 3x
    and stays the OK 015 bought, with the 015 ruling quoted. The shunt band
    must not leak into parts the shunt rule does not call shunts."""
    model = _model(R7=("1kΩ", "FRC0805J471 TS"))
    states = _states(model)
    assert states["VIOLATION"] == [] and states["UNKNOWN"] == []
    (waived,) = states["OK"]
    assert "2.13x" in waived.message
    assert "below the 3x tolerance" in waived.message
    assert "015 batch-2" in waived.message


def test_a_milliohm_resistor_above_the_shunt_ceiling_keeps_3x():
    """A 100 mΩ series resistor is not a differential shunt (ROBOT's phase
    shunts are the measured case): the 1.5x band stops at the shunt rule's
    50 mΩ ceiling, and 100 mΩ vs 200 mΩ is still the ordinary 2.00x pass."""
    assert _is_shunt_resistor(
        Component(uid="r9", designator="R9", value="100mΩ", mpn="")
    ) is False
    model = _model(R9=("100mΩ", "WSL2512R2000FEA"))
    outcome = _ruled(model, "R9")
    assert outcome.state == "OK"
    assert "2.00x" in outcome.message
    assert "below the 3x tolerance" in outcome.message


def test_a_capacitor_is_unmoved():
    """The capacitor band is 25x and this batch does not touch it: the
    graduation board's 10x shape is still waived with 25x quoted."""
    model = _model(C28=("100nF", "CC0603KRX7R9BB103"))
    outcome = _ruled(model, "C28")
    assert outcome.state == "OK"
    assert "10.00x" in outcome.message
    assert "below the 25x tolerance" in outcome.message


def test_a_zero_valued_part_keeps_its_undefined_ratio_path():
    """A 0 Ω part is not a shunt (``_is_shunt`` refuses it), and the zero side
    has no ratio at all -- that branch is untouched and still the anchored
    contradiction it always was."""
    assert parse_resistance_ohms("0Ω") == 0.0
    model = _model(R5=("0Ω", ANCHORED_SHUNT_MPN))
    outcome = _ruled(model, "R5")
    assert outcome.state == "VIOLATION"
    assert "leaves the ratio undefined" in outcome.message
    assert "so no tolerance applies" in outcome.message
    assert "at or above the" not in outcome.message


def test_the_rule_still_answers_one_row_per_part():
    """Cheap structural guard: the tolerance sits inside one branch, so every
    component still produces exactly one row and the four-state vocabulary is
    the one the harness aggregates."""
    model = _model(
        R21=("0.05Ω", ANCHORED_SHUNT_MPN),
        R9=("100mΩ", "WSL2512R2000FEA"),
        C28=("100nF", "CC0603KRX7R9BB103"),
        U3=("470Ω", "WSL2512R1000FEA"),
    )
    rows = _rows(model)
    assert sorted(o.subject for o in rows) == ["C28", "R21", "R9", "U3"]
    assert {o.state for o in rows} <= set(OUTCOME_STATES)
