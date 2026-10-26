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

import copy
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
    LayoutText,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import (
    SymbolPin,
    SymbolProfile,
    SymbolPose,
    SymbolText,
)
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

    201H hides that row (S-21, `islandlayout._clear_text_rows`), so the checker's
    coverage is stated on the plan that still prints it: the value row is put back
    at the host's own anchor, which is exactly the state the gate has to see.  What
    this test owns is the **detection**, not the layout's decision.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    plan = copy.deepcopy(page.plan())
    t1 = next(part for part in plan.parts if part.part_id == "T1")
    t1.value_visible = True
    value = next(
        row for row in textmetrics.symbol_rows(
            book[t1.symbol_ref], (t1.x, t1.y), reference=t1.part_id,
            value=circuit.part(t1.part_id).value,
            pose=SymbolPose(rotation=t1.rotation, mirror=t1.mirror),
        ) if row[0] == "value"
    )
    plan.texts.append(
        LayoutText(
            kind="value", text=value[1], part_id=t1.part_id, bbox=value[2],
            x=(value[2][0] + value[2][2]) / 2.0,
            y=(value[2][1] + value[2][3]) / 2.0,
        )
    )
    checked = rb.check(plan, circuit, presentation, book)
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


def test_the_transformer_value_is_hidden_rather_than_printed_through_its_own_pins():
    """201H: S-21's first way out, taken for the row no placement can clear.

    T1's value anchor is the symbol's own text item, and the row is 50.27 wide with
    its top edge on the axis of pins 2/5 — it prints through its own pin name and
    number rows, which is the `pin-text-press` above.  A placement cannot separate
    two rows of one symbol, so the value goes, and it goes **for real**: the flag
    `drawapply` lands is `value_visible`, not an omission from the plan's text list
    (531's defect).  The designator stays, and so does every other part's value.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    plan = page.plan()
    t1 = next(part for part in plan.parts if part.part_id == "T1")
    assert t1.value_visible is False
    assert "EE16_3+3_V02" not in [text.text for text in plan.texts]
    assert not [
        text for text in plan.texts
        if text.part_id == "T1" and text.kind == "value"
    ], "the value row is not printed"
    assert [
        text for text in plan.texts
        if text.part_id == "T1" and text.kind == "reference"
    ], "the designator is never hidden"
    values = [text for text in plan.texts if text.kind == "value"]
    assert len(values) == len(plan.parts) - 1, (
        "every part but T1 still prints its value"
    )
    assert {text.part_id for text in values} == {
        part.part_id for part in plan.parts if part.part_id != "T1"
    }
    checked = rb.check(plan, circuit, presentation, book)
    assert not [
        item for item in checked.hard_violations
        if item.kind == rb.KIND_PIN_TEXT_PRESSED
    ], [item.render() for item in checked.hard_violations]
    assert checked.ok, [item.render() for item in checked.hard_violations]


def _own_pin_collision_profile(symbol_ref: str, *, pin_text: bool) -> SymbolProfile:
    """One symbol whose value row prints through its own pin name/number rows.

    The value anchor is ``(-20, -10)`` and the row is wide enough to reach both pin
    columns, while pins 1/2 sit on the x axis at ±20 — so a measured pin text table
    puts their rows in the band the value row occupies.  This is `T1`'s shape in
    miniature.  With ``pin_text=False`` the symbol declares no table at all, which
    is the library 532 measured as "no row this model knows about".
    """
    return SymbolProfile(
        symbol_ref=symbol_ref,
        body=(-5.0, -5.0, 5.0, 5.0),
        pins=[
            SymbolPin(number="1", name="1", tip=(-20.0, 0.0), direction="left"),
            SymbolPin(number="2", name="2", tip=(20.0, 0.0), direction="right"),
        ],
        texts=[
            SymbolText(kind="reference", x=-20.0, y=10.0),
            SymbolText(kind="value", x=-20.0, y=-10.0),
        ],
        pin_text_offsets=(
            {"name": (22.0, -4.915), "number": (15.0, -0.915)} if pin_text else {}
        ),
        pin_text_kinds=(
            {"1": ("name", "number"), "2": ("name", "number")} if pin_text else {}
        ),
    )


def test_a_resistor_keeps_its_value_printed_through_its_own_pins():
    """Counter-example 1: the category rule wins over the own-pin collision.

    R/C/L/IC values are never hidden (S-21, 岳 2026-10-21) — the part moves
    instead — so the own-pin half has to ask `value_may_be_hidden` before it hides
    anything, and say so in a note a reader can check.
    """
    value = "75k 1% 0603 resistor"
    profile = _own_pin_collision_profile("RPIN", pin_text=True)
    circuit = CircuitSpec.from_dict({
        "parts": [{"id": "R1", "symbolRef": "RPIN", "value": value}],
        "nets": [],
    })
    may_hide, basis = il.value_may_be_hidden({"RPIN": profile}, circuit, "R1")
    assert may_hide is False, basis
    rows = textmetrics.symbol_rows(
        profile, (0.0, 0.0), reference="R1", value=value,
    )
    pins = textmetrics.pin_rows(profile, (0.0, 0.0))
    assert any(
        kind == "value" and any(
            box[0] < pin[2] and pin[0] < box[2]
            and box[1] < pin[3] and pin[1] < box[3]
            for _kind, _text, pin in pins
        )
        for kind, _text, box in rows
    ), "the fixture has to collide for this test to measure anything"
    hidden, notes = il._clear_text_rows(  # noqa: SLF001
        {"RPIN": profile}, circuit, {}, ["R1"],
        {"R1": (0.0, 0.0)}, {"R1": SymbolPose()}, {"R1": (0.0, 0.0)},
        il.IslandBudget(),
    )
    assert hidden == {}, "a resistor's value is never hidden, whatever it presses"
    assert any("own pin name/number" in note for note in notes), notes


def test_a_symbol_with_no_measured_pin_text_is_not_guessed_at():
    """Counter-example 2: no pin text table, no collision, no hidden value.

    `pin_rows` returns nothing for a symbol that declares no measured offsets (a
    vertical pin, or a library without 532's table).  An unmeasured row is not a
    zero-area one: the own-pin half must not invent a press and hide a value the
    gate never saw.
    """
    profile = _own_pin_collision_profile("XFMRX", pin_text=False)
    circuit = CircuitSpec.from_dict({
        "parts": [{"id": "T1", "symbolRef": "XFMRX", "value": "EE16_3+3_V02"}],
        "nets": [],
    })
    assert textmetrics.pin_rows(profile, (0.0, 0.0)) == []
    may_hide, _basis = il.value_may_be_hidden({"XFMRX": profile}, circuit, "T1")
    assert may_hide is True, "the transformer is a part whose value may go"
    hidden, notes = il._clear_text_rows(  # noqa: SLF001
        {"XFMRX": profile}, circuit, {}, ["T1"],
        {"T1": (0.0, 0.0)}, {"T1": SymbolPose()}, {"T1": (0.0, 0.0)},
        il.IslandBudget(),
    )
    assert hidden == {}, notes
    assert not any("own pin name/number" in note for note in notes), notes


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


def test_the_island_page_delivers_with_an_empty_tolerance_account():
    """The acceptance: `ok=True`, and nothing left to tolerate.

    ﹝531's account was empty because the gate could not see the four rows that were
    there. 532's had exactly three — the transformer's own pin typography — and
    201H took those out by S-21's first way out (the value row is hidden, not
    printed through its own pins).  The **cap** is not what changed: it stays 3,
    and a kind over its cap still takes every one of its lines with it.
    """
    circuit, presentation, book = _flyback()
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok, [f.detail for f in result.failures]
    tolerated = [note for note in result.notes if note.startswith("tolerated: ")]
    assert tolerated == [], (
        "201H: the transformer's value row is hidden, so the three pin-text rows "
        f"that used to be tolerated are gone — {tolerated}"
    )
    limits = dict(dc.ISLAND_GATE_TOLERATED_LIMITS)
    assert limits[rb.KIND_PIN_TEXT_PRESSED] == 3, (
        "the cap is unchanged by this batch: 201H removed the rows, not the rule"
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


def test_the_island_page_hides_only_the_transformer_s_value():
    """S-21's landing, read off the plan: **one** row goes, and it is `T1`'s.

    531 hid four values here; 532 printed all nineteen because the row pitch, the
    lead and the boundary stub were taught to make room. 201H adds the one case
    those levers cannot answer — a value row printed through its **own** symbol's
    pin typography — so exactly one value is hidden and the note says why. The
    plan's ``value_visible`` is the flag the landing step writes, so this is the
    paper, not a comment.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    notes = [note for block in page.blocks for note in block.notes]
    dropped = [note for note in notes if "is not drawn" in note]
    assert len(dropped) == 1, dropped
    assert dropped[0].startswith("T1: the value 'EE16_3+3_V02' is not drawn"), (
        dropped[0]
    )
    assert "pin name/number" in dropped[0], (
        "the note states the real reason: the row prints through its own pins — "
        + dropped[0]
    )
    assert "no placement of this part can separate" in dropped[0], dropped[0]
    plan = page.plan()
    t1 = next(part for part in plan.parts if part.part_id == "T1")
    assert t1.value_visible is False
    assert all(part.value_visible for part in plan.parts if part.part_id != "T1")
    printed = {item.part_id for item in plan.texts if item.kind == "value"}
    assert printed == {part.part_id for part in plan.parts if part.part_id != "T1"}, (
        "every other part still prints its value row, and the plan's text list is "
        "where that shows"
    )
    assert len([item for item in plan.texts if item.kind == "value"]) == 18


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


# ------------------------------- F: the pose the measurement does not cover (201H audit)


def test_a_pin_the_pose_turned_onto_the_page_s_y_axis_has_no_measured_row():
    """201H-a: the offsets are a **horizontal** measurement, and the pose counts.

    `pin_text_offsets` was measured on pins lying on the page's x axis
    (`evidence/532/raw/pin_text_offsets.txt`), and the row's side is a page-x sign.
    A pose that turns the pin onto the page's y axis was never measured, so it has
    to read as "no row this model knows" — the same answer a symbol without the
    table gets. The alternative, which this test was written against, kept the
    offset on page x and put a phantom row 11 units beside a tip that points along
    y; the gate (which reads the same boxes) then reported `pin-text-press` for a
    collision the symbol does not have.
    """
    book = _library("flyback_uc3845")
    upright = textmetrics.pin_rows(
        book["XFMR-WE-749118105"], (420.0, 280.0), SymbolPose(),
    )
    assert len(upright) == 8, "the 0-degree reading is the measured one and stays"
    for rotation in (90, 270):
        rows = textmetrics.pin_rows(
            book["XFMR-WE-749118105"], (420.0, 280.0),
            SymbolPose(rotation=rotation),
        )
        assert rows == [], (
            f"at rotation {rotation} the transformer's pins lie on the page's y "
            "axis, which the measured table does not cover — an unmeasured row is "
            f"not a zero-area one, and not a horizontal one either: {rows}"
        )


def _pose_pressed_value_profile() -> SymbolProfile:
    """A value row that only the *unrotated* reading puts under a pin row.

    The value sits at ``(14, 19)`` and is 50 wide.  Upright, every pin row is on
    the page's x axis at ``y≈(-1, 9)`` — nothing presses it.  Turned 90 degrees,
    the old reading kept the number's offset on page x and produced a box at
    ``(11, 19)-(15, 29)`` beside a tip that points along +y, i.e. a row the host
    draws 15+ units away, and hid the value for it.
    """
    return SymbolProfile(
        symbol_ref="XFMRX",
        body=(-8.0, -12.0, 8.0, 12.0),
        pins=[
            SymbolPin(number="1", name="A", tip=(20.0, 0.0), direction="right"),
            SymbolPin(number="2", name="B", tip=(-20.0, 0.0), direction="left"),
        ],
        texts=[
            SymbolText(kind="reference", x=-20.0, y=40.0),
            SymbolText(kind="value", x=14.0, y=19.0),
        ],
        pin_text_offsets={"number": (15.0, -0.915)},
        pin_text_kinds={"1": ("number",), "2": ("number",)},
    )


def test_the_pose_cannot_hide_a_value_behind_a_pin_row_it_turned_vertical():
    """201H-a: no phantom press, so no `valueVisible=false` for a legible row.

    The row inside is may-hidable (a transformer), so `_clear_text_rows` is the one
    decision that can silently drop it — and it is the flag the landing step writes
    to the host (`cli._draw_apply_plan` §5c), i.e. a real loss on the paper.  The
    fixture is stated three ways so the measurement is the pose and nothing else.
    """
    profile = _pose_pressed_value_profile()
    circuit = CircuitSpec.from_dict({
        "parts": [{"id": "T9", "symbolRef": "XFMRX", "value": "EE16_3+3_V02"}],
        "nets": [],
    })
    may_hide, basis = il.value_may_be_hidden({"XFMRX": profile}, circuit, "T9")
    assert may_hide is True, basis

    def hidden_at(pose: SymbolPose) -> dict[str, str]:
        hidden, _notes = il._clear_text_rows(  # noqa: SLF001
            {"XFMRX": profile}, circuit, {}, ["T9"],
            {"T9": (0.0, 0.0)}, {"T9": pose},
            {"T9": (-8.0, -12.0, 8.0, 12.0)}, il.IslandBudget(),
        )
        return hidden

    assert hidden_at(SymbolPose()) == {}, (
        "upright the pin rows are on the x axis at y≈(-1, 9) and the value is at "
        "y∈(19, 29): nothing presses anything"
    )
    for rotation in (90, 270):
        assert hidden_at(SymbolPose(rotation=rotation)) == {}, (
            f"at rotation {rotation} the pins lie on the page's y axis, which is "
            "unmeasured — the value is not printed through a row nobody measured"
        )


# ------------------------- G: the note is a diagnosis, not the gate's verdict


def _row_inside_its_own_body_profile() -> SymbolProfile:
    """A part whose designator row is printed **inside its own symbol body**."""
    return SymbolProfile(
        symbol_ref="ROWBODY",
        body=(-20.0, -20.0, 20.0, 20.0),
        pins=[SymbolPin(number="1", name="A", tip=(30.0, 0.0), direction="right")],
        texts=[
            SymbolText(kind="reference", x=-10.0, y=-5.0),
            SymbolText(kind="value", x=-10.0, y=-40.0),
        ],
    )


def test_a_coarse_row_diagnosis_does_not_claim_the_gate_refuses():
    """201H-b: the note says what this module measured, and stops there.

    `_add_texts` reserves rows against a **coarse** box set that includes the
    part's own body and a one-unit wall around every conductor. The gate's reading
    is different in both places (a part's own artwork is not scored at all, and a
    conductor only counts at `TEXT_WIRE_PENETRATION`), so a note saying "the gate
    will refuse this page" is a claim about a verdict this module does not make —
    and on the delivered 201H page eight of them were false while the gate said
    `ok`. The wording has to separate the two, and a part's own body is not a
    neighbour.
    """
    profile = _row_inside_its_own_body_profile()
    circuit = CircuitSpec.from_dict({
        "parts": [{"id": "U9", "symbolRef": "ROWBODY", "value": "TL431"}],
        "nets": [],
    })
    block = il.IslandBlock(island_id="probe", role="", anchor="U9")
    il._add_texts(  # noqa: SLF001
        block, ["U9"], circuit, {"ROWBODY": profile},
        {"U9": (0.0, 0.0)}, {"U9": SymbolPose()},
        [(-20.0, -20.0, 20.0, 20.0)], il.IslandBudget(),
    )
    notes = [note for note in block.notes if "reference row" in note]
    assert len(notes) == 1, block.notes
    note = notes[0]
    assert "own symbol body" in note, (
        "the diagnosis has to say what it actually hit — the part's own artwork — "
        "not call it a neighbour: " + note
    )
    assert "neighbour" not in note, note
    assert "a coarse box test" in note and "not a verdict" in note, (
        "the note names its own reading as coarse and says the decision is the "
        "gate's: " + note
    )
    assert "readability" in note, note
    assert "will refuse this page" not in note, (
        "the module does not get to state the gate's verdict: " + note
    )


def _pressed_value_symbols() -> tuple[SymbolProfile, SymbolProfile]:
    """Two may-hide parts: `T1`'s value presses its own pin, `T2`'s presses `T1`'s."""
    first = SymbolProfile(
        symbol_ref="PEER-A",
        body=(-5.0, -5.0, 5.0, 5.0),
        pins=[SymbolPin(number="1", name="A", tip=(20.0, 0.0), direction="right")],
        texts=[
            SymbolText(kind="reference", x=-20.0, y=40.0),
            SymbolText(kind="value", x=-20.0, y=-10.0),
        ],
        pin_text_offsets={"number": (15.0, -0.915)},
        pin_text_kinds={"1": ("number",)},
    )
    second = SymbolProfile(
        symbol_ref="PEER-B",
        body=(-15.0, -35.0, -5.0, -25.0),
        pins=[SymbolPin(number="1", name="A", tip=(20.0, 0.0), direction="right")],
        texts=[
            SymbolText(kind="reference", x=-20.0, y=40.0),
            SymbolText(kind="value", x=-20.0, y=-10.0),
        ],
    )
    return first, second


def test_a_hidden_value_row_is_not_a_foreign_row_for_the_parts_after_it():
    """201H-b: the row that is **not printed** stops being something to dodge.

    `_clear_text_rows` commits rows one at a time and later parts avoid earlier
    ones. A hidden row is not on the paper, so it must leave that set — otherwise
    the second part hides its own value to dodge a row the host never prints, and
    two values are lost where one collision existed.
    """
    first, second = _pressed_value_symbols()
    book = {"PEER-A": first, "PEER-B": second}
    circuit = CircuitSpec.from_dict({
        "parts": [
            {"id": "T1", "symbolRef": "PEER-A", "value": "EE16_3+3_V02"},
            {"id": "T2", "symbolRef": "PEER-B", "value": "EE16_3+3_V02"},
        ],
        "nets": [],
    })
    origins = {"T1": (0.0, 0.0), "T2": (0.0, -5.0)}
    poses = {"T1": SymbolPose(), "T2": SymbolPose()}
    boxes = {"T1": (-5.0, -5.0, 5.0, 5.0), "T2": (-15.0, -40.0, -5.0, -30.0)}
    rows = {
        part: [
            (kind, text, box) for kind, text, box in textmetrics.symbol_rows(
                book[circuit.part(part).symbol_ref], origins[part],
                reference=part, value=circuit.part(part).value, pose=poses[part],
            )
        ]
        for part in ("T1", "T2")
    }
    t1_value = next(box for kind, _t, box in rows["T1"] if kind == "value")
    t2_value = next(box for kind, _t, box in rows["T2"] if kind == "value")
    assert il._overlaps(t1_value, t2_value), (  # noqa: SLF001
        "the fixture has to collide for this test to measure anything"
    )
    hidden, _notes = il._clear_text_rows(  # noqa: SLF001
        book, circuit, {}, ["T1", "T2"], origins, poses, boxes, il.IslandBudget(),
    )
    assert list(hidden) == ["T1"], (
        "only the row that presses its own pin text goes; T2's value overlaps a "
        f"row the host will not print, so it is not pressed: {hidden}"
    )
