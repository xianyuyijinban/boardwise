"""534 batch 2 — the soft layer stops being a reading and becomes a floor.

Until 534 the numbers `readability._soft_metrics` measured were **recorded and
never compared** to anything: `evidence/534/quality/REPORT.md` measured the same
page at 1.32 bends per root (golden board 0.21), 6.90% crossings (golden 2/47) and
a 1-unit text gap, and the plan still carried `verdict: "pass"`. The floor added
here is the *style spec's own* numbers — S-09 (≤1 bend per root, 2 on one wire),
S-11 (2% of the drawn wire segments) and S-21 (2 canvas units between two
statements) — not the golden board's lucky readings: the golden board is the test
**of** the floor, so a threshold that refuses it is a wrong threshold.

What this file pins:

* the four constants are the spec's numbers, stated once (a board cannot move them);
* the golden flyback — the page S-01…S-21 was read off — passes with **nothing to
  name**, measured through the real document;
* a page whose numbers break the floor is named breach by breach (the ch340 page,
  which is measured here for exactly this: 6 crossings over 27 drawn segments);
* the island gate **refuses** on the floor, and a page that would otherwise be
  delivered comes back with the refusal in `rejected` and `ok == False`;
* the page path **records** the same breaches in its evidence instead of refusing,
  because a page's module interiors are drawn by the single-module compiler and a
  refusal there would have no drawer able to replace the page (534 REPORT §5 #8).
"""

from __future__ import annotations

import functools
import math
import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc
from boardwise.engines import readability

SPECS = pathlib.Path(__file__).resolve().parents[1] / "blocklib" / "specs"


def _library(stem: str) -> dict[str, SymbolProfile]:
    import json

    payload = json.loads((SPECS / f"{stem}.library.json").read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    return book


@functools.lru_cache(maxsize=None)
def _compiled(stem: str) -> tuple[dc.CompileResult, dict[str, SymbolProfile]]:
    circuit = CircuitSpec.load(SPECS / f"{stem}.circuit.json")
    presentation = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
    book = _library(stem)
    return dc.compile(circuit, presentation, book, dc.CompileBudget(max_candidates=64)), book


# ------------------------------------------------------------------ the numbers


def test_the_floors_numbers_are_the_specs_numbers_not_a_boards_readings():
    """S-09, S-11 and S-21 are the source; 530F's golden readings are not.

    The golden flyback measured 0.21 bends per root and 4.3% crossings — if the
    floor had been set from it (0.5, 5%) a page at 1.3 bends per root would still
    be delivered, which is what 534 REPORT §4 measured. Each constant is asserted
    with its designator so a future edit has to argue with the spec.
    """
    assert readability.SOFT_FLOOR_BENDS_PER_ROOT == 1.0, (
        "S-09's target is one bend per root, not the golden board's 0.21"
    )
    assert readability.SOFT_FLOOR_BENDS_MAX == 2.0, (
        "S-09 states a single wire is allowed at most two bends"
    )
    assert readability.SOFT_FLOOR_CROSSING_SHARE == 0.02, (
        "S-11's cap is 2% of the drawn wire segments (the FOC sheet: 2 of 248)"
    )
    assert readability.SOFT_FLOOR_TEXT_GAP == 2.0, (
        "S-21: two statements closer than 2 canvas units read as one"
    )
    # The crossing allowance is a share of *edges*, not of roots: one crossing in a
    # 39-root page that draws 96 edges is 1.04%, and the spec's cap is a share of
    # what is drawn (the golden flyback's own crossing sits at exactly that scale).
    assert max(1.0, math.ceil(readability.SOFT_FLOOR_CROSSING_SHARE * 96)) == 2.0


# ------------------------------------------------------------------ the goldens


def test_the_golden_flyback_passes_the_floor_with_nothing_to_name():
    """S-01…S-21 were read off this page, so it must pass — or the floor is wrong."""
    compiled, book = _compiled("flyback_uc3845")
    assert compiled.ok, [item.render() for item in compiled.failures]
    assert len(compiled.candidates) == 1
    plan = compiled.candidates[0]
    breaches = readability.soft_floor_violations(
        plan, plan.evidence.soft_metrics, book,
    )
    assert breaches == [], (
        "the golden board is refused by the soft floor — the thresholds are wrong, "
        f"not the board: {breaches}"
    )


def test_the_golden_flyback_is_still_delivered_by_the_island_gate():
    """The floor is a gate now, so "the golden board still comes out" is a claim."""
    compiled, _ = _compiled("flyback_uc3845")
    assert compiled.ok
    assert compiled.candidates, "no candidate survived the gate"
    assert not compiled.rejected, (
        "the golden board was rejected: "
        + "; ".join(item.reason for item in compiled.rejected)
    )


def test_a_measured_page_that_breaks_the_floor_is_named_breach_by_breach():
    """The ch340 page draws 6 crossings over 27 segments — 22%, against S-11's 2%.

    It is not gated (it compiles the single-module path, whose page is the peer's
    wiring problem rather than a topology the gate could re-pick), but the floor
    must still *name* it: a reading nobody states is the state 534 found.
    """
    compiled, book = _compiled("ch340_serial")
    assert compiled.ok
    plan = compiled.candidates[0]
    metrics = plan.evidence.soft_metrics
    assert metrics["crossings"] >= 6.0, metrics
    breaches = readability.soft_floor_violations(plan, metrics, book)
    assert breaches, f"the floor says nothing about {metrics}"
    assert any(line.startswith("S-11:") for line in breaches), breaches
    assert any(line.startswith("S-09:") for line in breaches), breaches


# ------------------------------------------------------------------- the teeth


def test_the_island_gate_refuses_a_page_that_breaks_the_floor(monkeypatch):
    """Wiring, not arithmetic: the floor is consulted and its verdict is a refusal.

    The golden page passes on its own numbers (above), so the floor is made to
    report one breach here — the point is that `_try_island_variants` turns it
    into a `RejectedCandidate` and the result's `ok` becomes False, which no test
    could observe while the soft layer was only recorded.
    """
    compiled, _ = _compiled("flyback_uc3845")
    assert compiled.ok
    _compiled.cache_clear()

    monkeypatch.setattr(
        readability,
        "soft_floor_violations",
        lambda plan, metrics, profiles: ["S-11: 99 crossing(s) — synthetic"],
    )
    try:
        refused, _ = _compiled("flyback_uc3845")
    finally:
        _compiled.cache_clear()
    assert not refused.ok, "the island gate delivered a page over the soft floor"
    assert refused.rejected, "no rejection was recorded"
    assert any(
        "soft floor" in item.reason for item in refused.rejected
    ), [item.reason for item in refused.rejected]
    assert any(
        "S-11: 99 crossing(s)" in line
        for item in refused.rejected for line in item.violations
    ), [item.violations for item in refused.rejected]


def test_the_page_path_records_the_floor_in_its_evidence():
    """534's page refuses nothing (its modules are the peer's drawing) but states it."""
    circuit = CircuitSpec.load(SPECS / "ch343_uart.circuit.json")
    presentation = PresentationSpec.load(SPECS / "ch343_uart.presentation.json")
    book = _library("ch343_uart")
    result = pc.compile_page(
        circuit, presentation, book,
        pc.PageCompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok, [item.reason for item in result.failures]
    notes = result.pages[0].plan.evidence.notes
    floor_notes = [note for note in notes if "soft floor" in note]
    assert floor_notes, notes[-3:]
    # 534 formal migration: the four-island page breaches S-09 (bends) and S-21
    # (two statements 1 unit apart); S-11 is no longer among them. The note still
    # has to say "recorded not refused", which is the behaviour under test.
    assert "recorded not refused" in floor_notes[-1], floor_notes[-1]
    assert "S-09" in floor_notes[-1] and "S-21" in floor_notes[-1], floor_notes[-1]
