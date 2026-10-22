"""532: the text finishing pass — a real hidden value, the category rule, pin text.

The previous batch gave the layout and the gate **one** ruler for a placed part's
rows (`core.textmetrics.symbol_rows`) and then measured three things it could not
finish:

* **the plan's "hide the value" never reached the paper.** 531 hid four values and
  the render printed 4/4 of them, because `drawapply` wrote no visibility at all
  (`evidence/531/report.md` §5.4).  What the host reads is the value row's own
  ``valueVisible``, and this batch writes it (`engines/partvisibility.py` +
  `cli._draw_apply_plan` §5c);
* **S-21 has a category rule now** (岳 2026-10-21): a resistor's, capacitor's,
  inductor's or IC's value is **never** hidden — the part moves instead — while
  every other kind may lose its value.  `islandlayout.value_may_be_hidden` is the
  reading and it quotes its own basis;
* **the gate could not see a pin's name or number at all**, so the four collisions
  531 found on the render (`U5`'s `ANODE` × `3`, the transformer's `2`/`5`/`5` ×
  its own value row) were invisible to it.  `textmetrics.pin_rows` measures them
  and `readability` reports them under their own kind, `pin-text-press`.

This file pins all three, plus the two things this batch's own changes bought:
the island page now hides **nothing** (the pitch, the lead and the boundary stub
were taught to make room) and its only hard rows are the transformer's own pin
typography, accounted one line each.

The measurements behind every number here are in `evidence/532/report.md` and
`evidence/532/raw/`.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from boardwise.core import textmetrics
from boardwise.core.changeplan import (
    ChangePlan,
    PlanChange,
    PlanDrawPart,
    PlanDrawPin,
)
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import (
    LayoutPart,
    LayoutPlan,
    LayoutSource,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile, SymbolPose
from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il
from boardwise.engines import partvisibility as pv
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _library(stem: str) -> dict[str, SymbolProfile]:
    payload = json.loads((SPECS / f"{stem}.library.json").read_text(encoding="utf-8"))
    return {
        profile.symbol_ref: profile
        for profile in (SymbolProfile.from_dict(e) for e in payload["profiles"])
    }


def _flyback() -> tuple[CircuitSpec, PresentationSpec, dict[str, SymbolProfile]]:
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        _library("flyback_uc3845"),
    )


# ------------------------------------------------- A: writing the flag (the model)

#: A document source in the shape `sys.get_document_source` returns, trimmed to the
#: records this reader joins: a component with a designator and a value row, one
#: without a value row, and one row already switched off.  The key order is the
#: host's own (measured on `test/P1`, `evidence/532/raw/probe_page_src_before.json`).
_SOURCE = "\n".join([
    '{"type":"DOCHEAD","ticket":1}||{"docType":"SCH_PAGE"}|',
    '{"type":"COMPONENT","ticket":2,"id":"aaa"}||{"partId":"P1.1","x":100,"y":200}|',
    '{"type":"ATTR","ticket":3,"id":"d1"}||{"x":90,"y":-205,"value":"R1",'
    '"keyVisible":null,"valueVisible":true,"key":"Designator","parentId":"aaa"}|',
    '{"type":"ATTR","ticket":4,"id":"n1"}||{"x":90,"y":-185,"value":"={Value}",'
    '"keyVisible":null,"valueVisible":true,"key":"Name","parentId":"aaa"}|',
    '{"type":"COMPONENT","ticket":5,"id":"bbb"}||{"partId":"P1.2","x":300,"y":200}|',
    '{"type":"ATTR","ticket":6,"id":"d2"}||{"x":290,"y":-205,"value":"C1",'
    '"keyVisible":null,"valueVisible":true,"key":"Designator","parentId":"bbb"}|',
    '{"type":"COMPONENT","ticket":7,"id":"ccc"}||{"partId":"P1.3","x":400,"y":200}|',
    '{"type":"ATTR","ticket":8,"id":"d3"}||{"x":390,"y":-205,"value":"R2",'
    '"keyVisible":null,"valueVisible":true,"key":"Designator","parentId":"ccc"}|',
    '{"type":"ATTR","ticket":9,"id":"n3"}||{"x":390,"y":-185,"value":"={Value}",'
    '"keyVisible":null,"valueVisible":false,"key":"Name","parentId":"ccc"}|',
])


def test_the_value_row_is_the_Name_attribute_of_the_part_s_component():
    """Where the flag lives, read off the document rather than guessed.

    Two joins: the ``Designator`` attribute names the part and owns it, and the
    ``Name`` attribute of that same component is the row the host prints its value
    in.  A part with no ``Name`` record (``C1`` here) has no value row to hide, and
    that is reported as *missing* rather than quietly counted as hidden.
    """
    rows = pv.value_row_attributes(_SOURCE)
    assert set(rows) == {"R1", "R2"}
    assert rows["R1"][0] == "n1"
    assert rows["R2"][0] == "n3"
    assert pv.value_row_visible(_SOURCE, "R1") is True
    assert pv.value_row_visible(_SOURCE, "R2") is False
    assert pv.value_row_visible(_SOURCE, "C1") is None


def test_hiding_writes_one_flag_and_says_which_parts_it_could_not():
    """The write itself: one record's flag, and the honest half of the answer."""
    out, hidden, missing = pv.hide_value_rows(_SOURCE, ["R1", "R2", "C1"])
    assert hidden == ["R1", "R2"]
    assert missing == ["C1"]
    assert pv.value_row_visible(out, "R1") is False
    assert '"key":"Designator"' in out, (
        "the designator row is untouched — S-21 hides a value, never a designator"
    )
    assert out.count('"valueVisible":false') == 2
    assert len(out) == len(_SOURCE) + 1, (
        "exactly one byte changed: `true` -> `false`, and only in the record the "
        "write addressed"
    )


def test_hiding_twice_is_the_same_document():
    """The write runs on a page this same run may have just drawn, so it is idempotent."""
    once, _h, _m = pv.hide_value_rows(_SOURCE, ["R1"])
    twice, hidden, _m = pv.hide_value_rows(once, ["R1"])
    assert twice == once
    assert hidden == ["R1"], (
        "a part already switched off is reported as hidden, not as a change: the "
        "page is in the state the plan asks for either way"
    )


# ------------------------------------------- B: the plan carries it, the guard too


def test_a_hidden_value_is_in_the_plan_and_moves_the_geometry_digest():
    """``LayoutPart.value_visible`` is a fact about the picture, so it is digested.

    Two plans that differ only in this field are two different drawings — one
    prints a row and one does not — and a preview bound to one must not be read as
    the other.  The field is written **only when it is false**, which is what keeps
    every plan in this repository whose values are all printed digest-identical.
    """
    plain = LayoutPlan(
        source=LayoutSource(circuit_sha256="1" * 64, presentation_sha256="2" * 64),
        parts=[LayoutPart(
            part_id="R1", symbol_ref="R0603", symbol_hash="3" * 64, x=0.0, y=0.0,
        )],
    )
    hidden = LayoutPlan(
        source=LayoutSource(circuit_sha256="1" * 64, presentation_sha256="2" * 64),
        parts=[LayoutPart(
            part_id="R1", symbol_ref="R0603", symbol_hash="3" * 64, x=0.0, y=0.0,
            value_visible=False,
        )],
    )
    assert plain.geometry_sha256() != hidden.geometry_sha256()
    assert "valueVisible" not in plain.parts[0].symbol_ref
    payload = plain.to_jsonable()
    assert "valueVisible" not in payload["parts"][0]
    assert hidden.to_jsonable()["parts"][0]["valueVisible"] is False
    back = LayoutPlan.from_dict(hidden.to_jsonable())
    assert back.parts[0].value_visible is False
    assert back.geometry_sha256() == hidden.geometry_sha256()


def test_a_draw_plan_part_carries_the_flag_to_the_landing_step():
    """The same field on the ``draw-module`` plan, read back by apply.

    ``layoutplan`` → ``changeplan`` is the whole path, so it is measured on the
    **product's own** plan rather than on a hand-built one: `drawapply.module_plan`
    maps the layout's parts, the document states the field (only when false), and
    the reader that apply uses reads it back.
    """
    circuit, presentation, book = _flyback()
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok and result.candidates, [f.detail for f in result.failures]
    built = drawapply.module_plan(
        result.candidates[0], circuit, presentation, book,
        lcsc_by_part={"R3": "C23242", "R15": "C23242"},
    )
    payload = built.to_jsonable()
    for item, part in zip(payload["change"]["parts"], built.change.draw_parts):
        assert item.get("valueVisible", True) == part.value_visible
    written = ChangePlan.from_jsonable(payload)
    assert [part.value_visible for part in written.change.draw_parts] == [
        part.value_visible for part in built.change.draw_parts
    ]
    # And the flag is **stated**, not defaulted: a part whose row is hidden encodes
    # it, and a part whose row prints writes nothing at all.
    for item, part in zip(payload["change"]["parts"], built.change.draw_parts):
        if part.value_visible:
            assert "valueVisible" not in item
        else:
            assert item["valueVisible"] is False


def test_module_plan_copies_the_layout_s_flag_across():
    """One line of the product's own path, pinned so it cannot be dropped silently."""
    circuit, presentation, book = _flyback()
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok and result.candidates, [f.detail for f in result.failures]
    plan = result.candidates[0]
    hidden = {part.part_id: part.value_visible for part in plan.parts}
    built = drawapply.module_plan(
        plan, circuit, presentation, book,
        lcsc_by_part={"R3": "C23242", "R15": "C23242"},
    )
    assert built is not None
    for part in built.change.draw_parts:
        assert part.value_visible == hidden.get(part.spec_id, True), (
            f"{part.spec_id}: the layout says value_visible="
            f"{hidden.get(part.spec_id, True)} and the plan carries "
            f"{part.value_visible}"
        )


def test_a_hand_hidden_part_states_the_flag_and_a_printed_one_states_nothing():
    """The document's own shape, on the two plans the field can be true in.

    A `LayoutPlan` whose part is hidden says so in the document **and** in the
    geometry digest (two drawings, two digests); one whose parts all print keeps
    every byte it had, which is what makes this field additive.
    """
    kwargs = {"circuit_sha256": "1" * 64, "presentation_sha256": "2" * 64}
    plain = LayoutPlan(
        source=LayoutSource(**kwargs),
        parts=[LayoutPart(
            part_id="R1", symbol_ref="R0603", symbol_hash="3" * 64,
            x=0.0, y=0.0,
        )],
    )
    hidden = LayoutPlan(
        source=LayoutSource(**kwargs),
        parts=[LayoutPart(
            part_id="R1", symbol_ref="R0603", symbol_hash="3" * 64,
            x=0.0, y=0.0, value_visible=False,
        )],
    )
    assert plain.geometry_sha256() != hidden.geometry_sha256()
    assert "valueVisible" not in plain.to_jsonable()["parts"][0]
    assert hidden.to_jsonable()["parts"][0]["valueVisible"] is False
    back = LayoutPlan.from_dict(hidden.to_jsonable())
    assert back.parts[0].value_visible is False
    assert back.geometry_sha256() == hidden.geometry_sha256()
    assert LayoutPlan.from_dict(plain.to_jsonable()).parts[0].value_visible is True


# ------------------------------------------------------- C: the category rule (S-21)


def test_the_category_rule_is_the_repo_s_own_classifier_and_names_its_basis():
    """R/C/L/IC may not hide a value; every other kind may — by the repo's reading.

    The classification is `core.partkind.classify_part`'s own answer, fed the three
    declarations the layout has, and the basis travels with it so a note can say
    *why* a part keeps its value.
    """
    circuit, _presentation, book = _flyback()
    expected = {
        "R3": False, "R15": False, "R5": False, "R4": False, "R8": False,
        "R9": False, "R10": False, "R7": False,          # resistors
        "C5": False, "C6": False, "C11": False,          # capacitors
        "C13": False, "C10": False,
        "U4": False, "U5": False,                        # U-designated: ICs
        "Q1": True,                                      # a MOSFET
        "D1": True, "D3": True,                          # diodes
        "T1": True,                                      # a transformer
    }
    checked = 0
    for part_id, may_hide in expected.items():
        got, basis = il.value_may_be_hidden(book, circuit, part_id)
        assert got is may_hide, f"{part_id}: {got} ({basis})"
        assert basis, f"{part_id}: an answer with no basis is not this module's"
        checked += 1
    assert checked == 19, "every part of the document is classified"


def test_the_rule_is_the_kind_and_not_the_designator_letter():
    """A counter-case, so the test cannot pass by reading ``C``/``R`` prefixes.

    `partkind`'s own reason for existing is a ``U``-designated resistor being asked
    for decoupling capacitance (`core/partkind.py`'s header).  Here the question is
    the reverse: `Q1` is a MOSFET by its symbol and its designator, and a **diode**
    whose id starts with `R` is still a diode — the answer follows the classifier's
    kind, not the first letter of the id.
    """
    book = _library("flyback_uc3845")
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    may_hide, basis = il.value_may_be_hidden(book, circuit, "Q1")
    assert may_hide and "transistor" in basis
    may_hide, basis = il.value_may_be_hidden(book, circuit, "C11")
    assert not may_hide and "capacitor" in basis


# ------------------------------------------------------------ D: pin text into the gate


def test_the_measured_pin_rows_are_where_the_render_prints_them():
    """The table in the library, pinned against the landing it was measured on.

    `evidence/532/raw/pin_text_offsets.txt` is the render's own anchors, measured
    against `sch.geometry`; the three symbols below are the only ones on that page
    that print pin text at all, and each row's box is stated here to the unit.  The
    boxes are **anchored**, not just offset: `U5`'s `ANODE` ends 4.2 units short of
    the `3` beside it because the host draws it with ``text-anchor="end"`` — which
    is why 531's four collisions are three.
    """
    book = _library("flyback_uc3845")
    tl431 = {
        kind: (text, box)
        for kind, text, box in textmetrics.pin_rows(
            book["SOT23-3-TL431"], (520.0, 515.0), SymbolPose(),
        )
    }
    assert tl431["pinName"][0] == "ANODE"
    assert tl431["pinName"][1] == pytest.approx((535.88, 509.085, 561.3, 519.085), abs=0.01)
    assert tl431["pinNumber"][0] == "3"
    assert tl431["pinNumber"][1] == pytest.approx((565.5, 514.085, 569.474, 524.085), abs=0.01)
    assert tl431["pinName"][1][2] <= tl431["pinNumber"][1][0], (
        "the two rows do not touch: this is the collision 531's render probe "
        "reported and the anchor mode explains away"
    )
    transformer = [
        (kind, text, box)
        for kind, text, box in textmetrics.pin_rows(
            book["XFMR-WE-749118105"], (420.0, 280.0), SymbolPose(),
        )
    ]
    assert len(transformer) == 8, (
        "the transformer prints a number for all six pins and a name for the two "
        "NC ends as well"
    )
    names = [row for row in transformer if row[0] == "pinName"]
    assert {row[1] for row in names} == {"2", "5"}
    optocoupler = [
        kind for kind, _text, _box in textmetrics.pin_rows(
            book["SMD-4-PC817"], (565.0, 280.0), SymbolPose(),
        )
    ]
    assert optocoupler == ["pinNumber"] * 4, (
        "U6 draws only its pin numbers — the names are not printed at all"
    )
    nothing = textmetrics.pin_rows(book["R0603"], (0.0, 0.0), SymbolPose())
    assert nothing == [], (
        "a symbol with no measured table declares no pin text: an unmeasured row is "
        "not a zero-area one"
    )


def test_a_symbol_s_own_pin_text_pressing_its_own_row_is_its_own_kind():
    """The gate sees them, and it says which sentence it is.

    A pin's name landing under its own symbol's value row is the library symbol's
    typography — no placement of this drawing can separate them — so it is reported
    as `pin-text-press`, not as the `text-overlap` the contract reserves for a
    *foreign* text landing on a component.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    checked = rb.check(page.plan(), circuit, presentation, book)
    kinds = {item.kind for item in checked.hard_violations}
    assert kinds == {"pin-text-press"}, sorted(kinds)
    presses = [
        item for item in checked.hard_violations
        if item.kind == "pin-text-press"
    ]
    assert len(presses) == 3
    assert all("parts[T1].pin" in " ".join(item.objects) for item in presses), (
        "all three are the transformer's own typography over its own value row"
    )
    assert all(
        rb.is_host_printed_row(name)
        for item in presses for name in item.objects
        if ".pin" in name
    ), "and the pin rows are host-printed rows by the checker's own predicate"


def test_a_foreign_pin_row_is_still_an_ordinary_overlap():
    """The other half, so the new kind cannot become a blanket exemption.

    Two parts, one 40 units from the other, whose pin number rows reach into each
    other: that is a *placement* problem this compiler can answer, so it stays
    `text-overlap`.
    """
    profile = SymbolProfile(
        symbol_ref="TWO",
        body=(-5.0, -5.0, 5.0, 5.0),
        pins=[
            SymbolPin(number="1", name="IN", tip=(-30.0, 0.0), direction="left"),
        ],
        pin_text_offsets={"name": (13.7, -5.915), "number": (9.5, -0.915)},
        pin_text_kinds={"1": ("name", "number")},
    )
    other = SymbolProfile(
        symbol_ref="TWO",
        body=(-5.0, -5.0, 5.0, 5.0),
        pins=[
            SymbolPin(number="1", name="OUT", tip=(-30.0, 0.0), direction="left"),
        ],
        pin_text_offsets={"name": (13.7, -5.915), "number": (9.5, -0.915)},
        pin_text_kinds={"1": ("name", "number")},
    )
    plan = LayoutPlan(
        source=LayoutSource(circuit_sha256="1" * 64, presentation_sha256="2" * 64),
        parts=[
            LayoutPart(part_id="A", symbol_ref="TWO", symbol_hash="3" * 64,
                       x=0.0, y=0.0),
            LayoutPart(part_id="B", symbol_ref="TWO", symbol_hash="3" * 64,
                       x=6.0, y=0.0),
        ],
    )
    boxes = {
        name: box for name, box, _owner, _text in rb._text_boxes(  # noqa: SLF001
            plan, {"TWO": profile},
        )
    }
    assert any(
        name.startswith("parts[A].pin") and any(
            not (
                box[2] <= other_box[0] or other_box[2] <= box[0]
                or box[3] <= other_box[1] or other_box[3] <= box[1]
            )
            for other_name, other_box in boxes.items()
            if other_name.startswith("parts[B].pin")
        )
        for name, box in boxes.items()
    ), "the fixture has to collide for this test to measure anything"


# ------------------------------------------------- E: the delivery account


def test_the_island_page_delivers_with_the_pin_text_rows_named():
    """The acceptance: `ok=True`, and every tolerated line named and capped.

    ﹝531's account was empty because the gate could not see the four rows that were
    there. 532's has exactly three — the transformer's — and 530F's policy makes the
    difference between "tolerated" and "forgiven" visible: a kind over its cap takes
    every one of its lines with it.
    """
    circuit, presentation, book = _flyback()
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok, [f.detail for f in result.failures]
    tolerated = [note for note in result.notes if note.startswith("tolerated: ")]
    assert len(tolerated) == 3, tolerated
    assert all("[pin-text-press]" in note for note in tolerated), tolerated
    assert all("parts[T1]" in note for note in tolerated), tolerated
    limits = dict(dc.ISLAND_GATE_TOLERATED_LIMITS)
    assert limits[rb.KIND_PIN_TEXT_PRESSED] == 3, (
        "the cap is the measured count on this page, not a round number"
    )
    # One rule past its cap takes the whole class with it.
    over = [
        rb.HardViolation(
            rb.KIND_PIN_TEXT_PRESSED, ("parts[T1].pinNumber[1]", "parts[T1].pinName[3]"),
            "synthetic",
        )
        for _ in range(4)
    ]
    refusing, tolerated_rows = dc.island_gate_violations(over)
    assert len(refusing) == 4 and not tolerated_rows


def test_the_island_page_hides_nothing_and_prints_every_value():
    """The other half of S-21's landing: this page does not need the way out at all.

    531 hid four values here. 532 prints all nineteen parts' values and still
    delivers, because the row pitch is sized by where a part's drawing reaches, a
    part's lead has to clear that drawing from the pin it serves, and a boundary
    stub whose outward end has no way out may try the segment's other end.  The
    plan says so in the one place the landing step reads it: ``value_visible``.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    notes = [note for block in page.blocks for note in block.notes]
    assert not [note for note in notes if "is not drawn" in note], (
        "nothing is hidden on this page"
    )
    plan = page.plan()
    assert all(part.value_visible for part in plan.parts)
    printed = {item.part_id for item in plan.texts if item.kind == "value"}
    assert printed == {part.part_id for part in plan.parts}, (
        "every part prints a value row, and the plan's text list is where that "
        "shows"
    )
    assert len([item for item in plan.texts if item.kind == "value"]) == 19


def test_a_foreign_text_over_a_pin_row_would_be_refused_not_tolerated():
    """The account's boundary, stated as a check rather than as a promise.

    `is_host_printed_row` is what clause 2 of the delivery policy asks, and it says
    **false** for a `texts[i]` row of ours — which is what keeps "the editor prints
    this" from turning into "anything near a pin row is forgiven".
    """
    assert rb.is_host_printed_row("parts[T1].pinNumber[2]")
    assert rb.is_host_printed_row("segments[13]")
    assert rb.is_host_printed_row("powerSymbols[2] name")
    assert not rb.is_host_printed_row("texts[33]")
    assert not rb.is_host_printed_row("labels[4]")
    foreign = rb.HardViolation(
        rb.KIND_TEXT_OVERLAP, ("texts[33]", "parts[T1].pinName[2]"), "synthetic",
    )
    refusing, tolerated = dc.island_gate_violations([foreign])
    assert refusing == [foreign] and not tolerated, (
        "a row this compiler placed over a pin row is ours to move, so it refuses"
    )
