"""531: the text ruler — where the host prints a part's own rows, measured.

The batch's subject is the 「量尺债」 522 warned about: the *same* page measured by
two models. The island path invented a side and a rung for every text row while
the single-module path read the symbols' declared anchors (146/147), and the two
disagreed by 50+ units — so the readability gate measured a page nobody sees, and
the collisions 岳 found by eye on the landed render (`evidence/530f/
530f_page_island.png`) never reached it:

* `R15`'s value `75k 1% 0603` printed across `C11`'s value `1nF/1kV` (糊成一行);
* the two resistors beside `R20` printing `R19R20` (designator over designator);
* `R23`'s and `R21`'s values touching in the feedback island.

`evidence/531/report.md` §2 is the measurement that turns those three sentences
into numbers, and this file pins the model that replaces the fiction:

**A. one ruler, three callers** — :func:`boardwise.core.textmetrics.symbol_rows` is
the only place a part's row box is computed, and the island plan's own rows are
that function's output (so the gate and the layout cannot drift apart again);

**B. the measured truth table** — upright rows are the symbol's declared offset to
the unit, and a rotated or mirrored part is re-anchored by the host, which is why a
declaration may now carry the pose it was measured in (`SymbolText.rotation` /
`.mirror`).  Both halves are pinned on the profiles this project ships;

**C. the string the host draws** — the value row's width is the width of the string
on the paper, and for four of the flyback's nineteen parts the host prints the
LCSC device's own name, not the spec's value (`SymbolProfile.value_row`);

**D. S-21 lands** — the row pitch fits the value row it has to print, and a value
that still collides is **hidden** with its reason rather than printed through the
neighbour;

**E. the real page** — the three collisions 岳 found are gone from the plan, the
page's own boxes do not overlap, and what is left is named.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import (
    SymbolProfile,
    SymbolText,
    pose_box,
)
from boardwise.core.symbolprofile import SymbolPin
from boardwise.core import textmetrics
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il

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


def _overlaps(first, second) -> bool:
    return not (
        first[2] <= second[0] or second[2] <= first[0]
        or first[3] <= second[1] or second[3] <= first[1]
    )


def _own_rows(block, part, circuit, book) -> list[tuple[str, str, tuple]]:
    profile = book[part.symbol_ref]
    pose = il.SymbolPose(rotation=part.rotation, mirror=part.mirror)
    return textmetrics.symbol_rows(
        profile, (part.x, part.y),
        reference=part.part_id, value=circuit.part(part.part_id).value, pose=pose,
    )


# --------------------------------------------------------------------- A: ruler


def test_a_plain_profile_with_no_pose_measures_the_declared_offset():
    """The pre-531 behaviour, kept exact: the declaration is the box.

    A symbol that states no pose (`rotation`/`mirror` both ``None``) is the
    library 146/147 wrote, and every profile in the repository before this batch is
    one.  The box is the anchor plus the render's own width, ten units tall — the
    same arithmetic `drawcompiler._declared_rows` and `placement.text_rows` make,
    which is the point: one function now, and this is its plain case.
    """
    profile = SymbolProfile(
        symbol_ref="R0603",
        texts=[SymbolText("reference", -10.0, 5.0), SymbolText("value", -10.0, -15.0)],
    )
    rows = textmetrics.symbol_rows(
        profile, (100.0, 200.0), reference="R7", value="1k 1% 0603",
    )
    assert [kind for kind, _text, _box in rows] == ["reference", "value"]
    ref, val = rows
    assert ref[2] == pytest.approx(
        (90.0, 205.0, 90.0 + textmetrics.render_width("R7"),
         205.0 + textmetrics.TEXT_ROW_HEIGHT), abs=1e-9,
    )
    assert val[2] == pytest.approx(
        (90.0, 185.0, 90.0 + textmetrics.render_width("1k 1% 0603"), 195.0), abs=1e-9,
    )


def test_a_pose_qualified_row_wins_only_for_its_own_pose():
    """The measured table is a table: exact pose first, declaration as fallback.

    `SymbolText.rotation`/`.mirror` are 531's addition and they are a measurement
    (`evidence/531/raw/anchor_landed_before.txt`): on the live landing every
    **upright** row matches its declaration to the unit and every rotated one is
    re-anchored by the host.  A lookup must therefore prefer the entry for the
    part's own pose and fall back to the pose-independent one — never the other way
    round, and never a pose-qualified entry from a *different* pose.
    """
    profile = SymbolProfile(
        symbol_ref="C0603",
        texts=[
            SymbolText("reference", -5.0, 10.0),
            SymbolText("value", -5.0, -20.0),
            SymbolText("reference", 15.0, -5.0, rotation=90.0, mirror=False),
            SymbolText("value", 15.0, -15.0, rotation=90.0, mirror=False),
        ],
    )
    upright = textmetrics.symbol_rows(
        profile, (0.0, 0.0), reference="C1", value="1nF",
        pose=il.SymbolPose(rotation=0.0, mirror=False),
    )
    assert upright[0][2][0] == -5.0 and upright[0][2][1] == 10.0
    quarter = textmetrics.symbol_rows(
        profile, (0.0, 0.0), reference="C1", value="1nF",
        pose=il.SymbolPose(rotation=90.0, mirror=False),
    )
    assert quarter[0][2][0] == 15.0 and quarter[0][2][1] == -5.0, (
        "the rot-90 row is the one measured in that pose"
    )
    assert quarter[1][2][1] == -15.0
    mirrored = textmetrics.symbol_rows(
        profile, (0.0, 0.0), reference="C1", value="1nF",
        pose=il.SymbolPose(rotation=90.0, mirror=True),
    )
    assert mirrored[0][2][0] == -5.0 and mirrored[0][2][1] == 10.0, (
        "a mirror is a different pose, so the upright declaration is the fallback"
    )


def test_the_shipped_profiles_carry_the_measured_pose_table():
    """The real document's own rows, from the real host, at every pose it uses.

    These six numbers are the measurement this batch exists for, so they are pinned
    where a reader can find them: on the landing of 2026-10-21 the host drew
    `C0603` at rot 90 at ``(+15, -5)`` where its upright declaration says
    ``(-5, +10)``, `CAP-SMD-220UF` at rot 90 mirrored at ``(-5, +15)`` where its
    declaration says ``(+15, 0)``, `R0603` at rot 90 at ``(+7, 0)`` where it says
    ``(-10, +5)``, and `C0603W` at rot 0 mirrored at ``(-10, +12)`` where it says
    ``(+15, 0)``.
    """
    book = _library("flyback_uc3845")
    measured = {
        ("C0603", 90.0, False): (-5.0, 10.0, 15.0, -5.0),
        ("CAP-TH-1NF-1KV", 90.0, False): (-10.0, 10.0, 15.0, 0.0),
        ("CAP-SMD-220UF", 90.0, True): (15.0, 0.0, -5.0, 15.0),
        ("DIO-DO41-UF4007", 270.0, False): (-5.0, 10.0, 15.0, -5.0),
        ("R0603", 90.0, False): (-10.0, 5.0, 7.0, 0.0),
        ("R0603", 270.0, False): (-10.0, 5.0, 10.0, 0.0),
        ("C0603W", 0.0, True): (15.0, 0.0, -10.0, 12.0),
    }
    for (symbol, rotation, mirror), (dx, dy, mx, my) in measured.items():
        profile = book[symbol]
        declared = next(
            t for t in profile.texts
            if t.kind == "reference" and t.rotation is None
        )
        assert (declared.x, declared.y) == (dx, dy), f"{symbol}'s upright declaration"
        row = textmetrics.symbol_rows(
            profile, (0.0, 0.0), reference="X1", value="v",
            pose=il.SymbolPose(rotation=rotation, mirror=mirror),
        )[0]
        assert (row[2][0], row[2][1]) == (mx, my), (
            f"{symbol} at rotation {rotation} mirror {mirror} is drawn at "
            f"({mx}, {my}) — the declaration is the *upright* anchor"
        )


# ------------------------------------------------------- B: the string on paper


def test_the_value_row_is_as_wide_as_the_string_the_host_draws():
    """`value_row`: the host prints the LCSC device name, not always our value.

    Measured off the landing's own `sch.netlist` (`Name` vs `Value`,
    `evidence/531/raw/netlist_after_names.txt`): four of the flyback's nineteen
    parts have a device name shorter than the spec's value, and the box has to be
    the drawn string's — `220uF/25V SMD electrolytic` measures 88.6 units where the
    drawn `220uF/25V-SMT` measures 52.2, and that phantom 36 units is enough for the
    gate to report a collision no reader can see.
    """
    book = _library("flyback_uc3845")
    profile = book["CAP-SMD-220UF"]
    assert profile.value_row == "220uF/25V-SMT"
    rows = textmetrics.symbol_rows(
        profile, (0.0, 0.0), reference="C13", value="220uF/25V SMD electrolytic",
        pose=il.SymbolPose(rotation=0.0, mirror=False),
    )
    value = next(row for row in rows if row[0] == "value")
    assert value[1] == "220uF/25V-SMT", (
        "the row says what is on the paper, so its box can be believed"
    )
    assert value[2][2] - value[2][0] == pytest.approx(
        textmetrics.render_width("220uF/25V-SMT"), abs=1e-9,
    )
    assert textmetrics.render_width("220uF/25V SMD electrolytic") > 80.0, (
        "and the spec string really is the wider one — otherwise this test "
        "measures nothing"
    )


# ------------------------------------------------------------- C: the real page


def test_every_row_in_the_island_plan_is_the_shared_models_output():
    """One source of truth, checked on the drawing rather than on the code.

    The gate measures the boxes the plan carries (`readability._text_boxes` reads
    `layout_plan.texts[i].bbox`); the layout measures the boxes
    :func:`textmetrics.symbol_rows` produces. Two models of one row is what this
    batch is about, so the plan's rows are compared with the model's, part by part
    and field by field: a drift between them cannot happen without this test going
    red.

    531 asserted that something **was** hidden here ("S-21's way out is not being
    used" otherwise). 532 removed that assertion rather than the mechanism, and the
    reason is a measurement: with the pitch sized by the parts' own reach, the lead
    cleared of their rows and the boundary stub allowed to try both ends, the
    flyback's island page no longer needs the way out at all — every one of its
    values fits, so nothing is hidden and nothing has to be. What is still checked
    is the invariant both batches share: **every** row the plan carries is the
    model's own output, and every row the plan does not carry is hidden with a note
    that says why.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    plan = page.plan()
    drawn = {(item.part_id, item.kind): (item.text, tuple(item.bbox))
             for item in plan.texts}
    hidden = {
        note.split(":")[0]
        for block in page.blocks for note in block.notes
        if "is not drawn" in note
    }
    for part_id in hidden:
        assert plan.part(part_id) is not None, (
            f"{part_id} has a row hidden by a note and is not even a part of the page"
        )
    checked = 0
    for block in page.blocks:
        for part in block.parts:
            for kind, text, box in _own_rows(block, part, circuit, book):
                here = (text, tuple(box))
                if kind == "value" and part.part_id in hidden:
                    assert (part.part_id, kind) not in drawn, (
                        f"{part.part_id}'s value is hidden by a note and yet the "
                        "plan draws it"
                    )
                    assert part.value_visible is False, (
                        f"{part.part_id}'s value is hidden by a note and the part "
                        "still says it is printed — the landing step would draw it"
                    )
                    continue
                got = drawn.get((part.part_id, kind))
                assert got is not None and got[0] == here[0], (
                    f"{part.part_id}'s {kind} row: the plan has {got} and the model "
                    f"has {here}"
                )
                # The plan's box goes through `json` on its way to a page, so the
                # comparison is unit-for-unit rather than bit-for-bit (the same
                # reading 530B's own `notes`-against-geometry tests make).
                assert all(
                    abs(a - b) < 1e-9 for a, b in zip(got[1], here[1])
                ), f"{part.part_id}'s {kind} row: {got[1]} vs {here[1]}"
                checked += 1
    assert checked >= len(plan.texts), (
        f"the plan carries {len(plan.texts)} rows and the model explains {checked}"
    )
    # 532: and the flag the landing step reads agrees with the plan's own text list,
    # part by part. A part whose value is absent from `texts` and whose
    # `value_visible` is still true is a row 531 measured being printed anyway.
    for part in plan.parts:
        printed = any(
            item.part_id == part.part_id and item.kind == "value"
            for item in plan.texts
        )
        assert part.value_visible == printed, (
            f"{part.part_id}: valueVisible={part.value_visible} but the plan "
            f"{'draws' if printed else 'omits'} its value row"
        )


def test_the_three_collisions_the_human_saw_are_what_the_old_model_hid():
    """The measurement this batch exists for, on the document as it was compiled.

    The landed page (`evidence/530f/raw/plan_p530f.json`) printed, with the model
    this batch replaces:

    * `R15`'s value `75k 1% 0603` `(108,400)-(149.7,410)` across `C11`'s
      `1nF/1kV` `(130,395)-(156.6,405)`;
    * `R19`'s designator `(130,275)-(143.1,285)` across `R20`'s `(142,275)-(155.1,285)`
      — the 「位号糊成 R19R20」 岳 read off the picture;
    * and `R19`'s value across `R20`'s as well.

    Those are the *declared* anchors of the specs' own part ids, which is what the
    single-module path would have measured all along: the island page's own boxes
    were 50+ units away from them.  Compiling the same document through the shared
    model now reports those rows exactly where the render has them, which is why
    they are the acceptance this file pins — and why the page the gate reads
    changed the moment the boxes stopped being a fiction.
    """
    circuit, presentation, book = _flyback()
    rows = []
    for part_id in sorted(circuit.part_ids()):
        part = circuit.part(part_id)
        profile = book[part.symbol_ref]
        rows.extend(
            (part_id, kind, text, box)
            for kind, text, box in textmetrics.symbol_rows(
                profile, (0.0, 0.0), reference=part_id, value=part.value,
            )
        )
    assert len(rows) == 38, f"the document's parts declare {len(rows) // 2} rows"

    def pair(a: str, b: str, kind: str) -> bool:
        first = next(row for row in rows if row[0] == a and row[1] == kind)
        second = next(row for row in rows if row[0] == b and row[1] == kind)
        return _overlaps(first[3], second[3])

    # At the origins the landed page used (the pairing the render shows): the two
    # parts of `primary`'s left column, and the two resistors of its row.
    def at(origin: tuple[float, float], part_id: str, kind: str):
        part = circuit.part(part_id)
        return next(
            box for k, _t, box in textmetrics.symbol_rows(
                book[part.symbol_ref], origin,
                reference=part_id, value=part.value,
            ) if k == kind
        )

    # The landed page's own origins and the designators the pool allocated to
    # them (`evidence/531/raw/plan_p530f.json`: spec `R15` is drawn as `R15`,
    # spec `C5` as `C11`, spec `R4`/`R5` as `R19`/`R20`).
    def landed(origin, reference, value, symbol, pose):
        return {
            kind: box
            for kind, _text, box in textmetrics.symbol_rows(
                book[symbol], origin, reference=reference, value=value, pose=pose,
            )
        }

    r15 = landed((118.0, 415.0), "R15", "75k 1% 0603", "R0603",
                 il.SymbolPose(rotation=90.0, mirror=False))
    c11 = landed((140.0, 415.0), "C11", "1nF/1kV", "CAP-TH-1NF-1KV",
                 il.SymbolPose(rotation=90.0, mirror=False))
    assert _overlaps(r15["value"], c11["value"]), (
        "the landed page's `R15` value row and the 1nF/1kV cap's are 22 units "
        "apart with 42- and 27-unit rows — the 糊成一行 岳 read off the picture"
    )
    r19 = landed((140.0, 270.0), "R19", "10k 0603", "R0603",
                 il.SymbolPose(rotation=270.0, mirror=False))
    r20 = landed((152.0, 270.0), "R20", "1R 1% 0603", "R0603",
                 il.SymbolPose(rotation=270.0, mirror=False))
    assert _overlaps(r19["reference"], r20["reference"]), (
        "the landed page's two 0603 resistors are 12 units apart and each prints a "
        "13-unit designator — 「位号糊成 R19R20」"
    )
    assert _overlaps(r19["value"], r20["value"]), (
        "and their values too: 29 and 39 units of row at a 12-unit pitch"
    )


def test_the_real_page_has_no_overlap_between_the_boxes_it_places():
    """The acceptance: after the fix, the gate's own overlap reading is zero.

    Both halves are checked, because 530F's delivery policy makes them different
    kinds of thing: the boxes *this compiler places* may not touch each other at all
    (`text-overlap` between two ``texts[i]`` is a hard finding, and so is a
    ``texts[i]`` row over a foreign body — `is_host_printed_row` is false for
    both), while a row the **host** prints is tolerated and accounted.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    plan = page.plan()
    # The gate's own object: `readability` reports a text over the ``drawn extent
    # of parts[…]``, which is the symbol's **body** (`_PlacedPart.body`), not
    # `_part_box`'s pin-inclusive box — a row across a neighbour's pin is not a
    # finding there, and this test must measure what the gate measures.
    bodies = {}
    for block in page.blocks:
        for part in block.parts:
            box = pose_box(
                book[part.symbol_ref].body,
                rotation=part.rotation, mirror=part.mirror, ox=part.x, oy=part.y,
            )
            if box is not None:
                bodies[part.part_id] = box
    texts = list(plan.texts)
    collisions = [
        (a.kind, a.text, b.kind, b.text)
        for a, b in itertools.combinations(texts, 2)
        if _overlaps(a.bbox, b.bbox)
    ]
    assert not collisions, f"two text boxes this compiler placed intersect: {collisions}"
    over_body = [
        (item.kind, item.text, part_id)
        for item in texts
        for part_id, body in bodies.items()
        if part_id != item.part_id and _overlaps(item.bbox, body)
    ]
    assert not over_body, f"a row this compiler placed lands on a foreign body: {over_body}"


def test_the_gate_reads_the_real_page_clean_and_the_trade_is_named():
    """The acceptance, and the trades it costs — all of them written down.

    531 read this page as "ok, with an empty tolerance account, four values hidden
    and a 38.33-unit S-05 breach". 532 reads it differently and every difference is
    a measurement rather than a policy change:

    * **nothing is hidden** — no value, no row. S-21's way out is still in the code
      (`islandlayout._clear_text_rows`, and the category rule below) but this page
      no longer needs it: the row pitch is now sized by where a part's own drawing
      actually reaches, a part's lead has to clear that drawing from the pin it
      serves, and a boundary stub whose outward end has no way out may try the
      segment's **other** end. All three were forced by the same sentence — a
      resistor's, capacitor's, inductor's or IC's value is never hidden
      (`岳 2026-10-21`, `islandlayout.VALUE_ALWAYS_PRINTED`) — so where 531 hid four
      values, 532 moves parts until they fit;
    * **the tolerance account is not empty, and what is in it is the transformer's
      own typography**: three `pin-text-press` rows (`T1`'s `2`/`5`/`5` against its
      own `EE16_3+3_V02`), the class `readability` could not see at all before this
      batch (it had no pin name/number rows among its five kinds). The page is
      delivered with them named, one line each, exactly as 530F's policy says;
    * the second decap of the `secondary` island stands **58.94** units from the
      pin it serves, against S-05's 30 — a bigger trade than 531's 38.33 and for
      the same reason (S-05 and "two decoupling parts on one pin" are mutually
      exclusive where the first one's value row is 52 units wide and may not be
      hidden). This module takes the page the gate accepts and says so; 岳 owns the
      ruling.
    """
    circuit, presentation, book = _flyback()
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok, [f.detail for f in result.failures]
    assert not [f for f in result.failures], "a delivered page carries no refusals"
    notes = list(result.notes)
    tolerated = [note for note in notes if note.startswith("tolerated: ")]
    assert len(tolerated) == 3, tolerated
    assert all("[pin-text-press]" in note for note in tolerated), tolerated
    page = il.island_page(circuit, presentation, book)
    block_notes = [note for block in page.blocks for note in block.notes]
    dropped = [note for note in block_notes if "is not drawn" in note]
    assert dropped == [], (
        f"this page hides nothing: every value fits at the pitch and the lead the "
        f"layout gives it — {dropped}"
    )
    pinned = [part for part in page.plan().parts if not part.value_visible]
    assert pinned == [], (
        f"and no part claims otherwise for the landing step — {pinned}"
    )
    decaps = [note for note in block_notes if note.startswith("decap ")]
    assert len(decaps) == 2, decaps
    gap = float(decaps[1].split("stands ")[1].split(" from")[0])
    assert gap == pytest.approx(58.9406, abs=0.01), (
        "the second decap's measured distance is the trade, so it is pinned: "
        + decaps[1]
    )
    assert gap > 30.0, "and it is over S-05 — that is the point of the note"
