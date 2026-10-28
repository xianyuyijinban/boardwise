"""534 — the page layer's two clearance defects, both measured on the four-island sheet.

`pagecompiler._module_boxes` builds the paper a page-placed label must avoid. Two
kinds of ink were missing or overstated there:

1. **A wire's own name.** A wire that *is* the drawing's label gets a net name the
   host prints at the midpoint of its longest straight run — a row that is ink, and
   that no run box covers. Two halves: a plan that already carries such a wire had
   no box for the row (now `readability._named_wire_rows`, the one statement of
   "which wires are named", `core.layoutplan.label_wire_indices`), and a label the
   **page** places can itself make a wire a name carrier after `_module_boxes` ran
   (now `_add_label` refreshes the table through `_note_name_rows`).
2. **A part's pin-tip hull was claimed as forbidden paper.** The table used
   `_part_extent` (body ∪ every pin tip). A pin *tip* is a point and the pin is a
   short lead off the body edge, so on a connector the hull covers the whole pin row
   and a page label anchored on one of those pins has nowhere legal to go: on this
   sheet all twelve ladder candidates were blocked and the unchecked fallback landed
   1.336 units inside the D+ name row — `labels[2] 'D-' [543, 698, 557, 707]`
   against `segments[5] 'D+' [545, 690, 555, 699.336]`, the only hard violation on an
   otherwise clean arrangement. The table now holds the drawn body
   (`readability._drawn_extents`' own extent), and only falls back to
   `_part_extent` when a profile states no body at all.

The rest of the ink is untouched and still avoided: texts (designator/value and,
since 532, the host's own pin rows), labels, flag glyphs and their name rows, one
box per wire run, and the named-wire rows.

The three-island page with the measured anchors (`tests/test_534_flow_page.py`) is a
*known* precondition: it is still 0 candidates for module-level reasons, and is not
this batch's subject.

Evidence: `evidence/534/page-wire-name-clearance.md`.
"""

from __future__ import annotations

import json
import pathlib

from boardwise.core import pageframe
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import (
    LayoutLabel,
    LayoutPlan,
    LayoutSegment,
    label_wire_indices,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.core.textmetrics import wire_name_box
from boardwise.engines import drawapply, readability
from boardwise.engines import pagecompiler as pc

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
BOARD = "ch343_uart"
PAGE = (0.0, 0.0, 1170.0, 825.0)
FOUR_ISLANDS = (
    ROOT / ".tmp_534" / "coreless" / "four-islands" / "presentation.json"
)


def _named_plan() -> LayoutPlan:
    """One wire that **is** a label (a label anchor on it) and one that is not."""
    labels = [
        LayoutLabel(
            net="D+", text="D+", bbox=(-4.0, -4.0, 4.0, 4.0), x=40.0, y=0.0,
        ),
    ]
    return LayoutPlan(
        segments=[
            LayoutSegment(net="D+", points=[(0.0, 0.0), (40.0, 0.0)]),
            LayoutSegment(net="D-", points=[(0.0, 50.0), (40.0, 50.0)]),
        ],
        labels=labels,
    )


def test_the_name_row_of_a_named_wire_is_occupied_paper():
    """`_module_boxes`: a labelled wire's name row is added, an unnamed wire's is not.

    The row is typography the run's own box does not cover — the host anchors it at
    the midpoint of the wire's longest run and grows it away from the conductor — so
    a label placed beside the run still lands on the name.
    """
    plan = _named_plan()
    carriers = label_wire_indices(plan)
    assert carriers == frozenset({0}), "the fixture must name exactly the D+ wire"
    rows = readability._named_wire_rows(plan)
    assert [name for name, _box, _owner, _text in rows] == ["segments[0]"]

    boxes = pc._module_boxes(plan, {})
    runs = sum(len(pc._run_boxes(item.points)) for item in plan.segments)
    # the fixture carries one label: its box and its anchor point are occupied too
    assert len(boxes) == runs + len(rows) + 2 * len(plan.labels), (
        "the only boxes beyond the runs and the labels must be the named rows: "
        f"{boxes}"
    )
    row = wire_name_box([(0.0, 0.0), (40.0, 0.0)], "D+")
    assert row is not None and rows[0][1] == row
    assert row in boxes, "the D+ name row is not in the avoid list"
    unnamed = wire_name_box([(0.0, 50.0), (40.0, 50.0)], "D-")
    assert unnamed is not None
    assert unnamed not in boxes, "a conductor of an unnamed wire prints no row"
    # The row is not the run's own box: it grows away from the conductor, which is
    # why the run boxes alone could not stand in for it.
    run = pc._run_boxes(plan.segments[0].points)[0]
    assert row[3] > run[3] and row != run


def test_a_page_label_refreshes_the_rows_its_own_wire_now_prints():
    """`_add_label`: the row a label summons joins the table for the *next* label.

    `_module_boxes` runs before any port is placed, so the row this label creates
    cannot be in it. Without the refresh the next label is placed against a table
    that is missing the very row the page just made the host print.
    """
    plan = LayoutPlan(
        segments=[LayoutSegment(net="D+", points=[(0.0, -10.0), (30.0, -10.0)])],
    )
    occupied: list = []
    pc._add_label(plan, "D+", (0.0, -10.0), (1.0, 0.0), occupied)
    rows = readability._named_wire_rows(plan)
    assert rows, "a label anchored on the wire must make it a name carrier"
    assert rows[0][1] in occupied, (
        "the row the page label summoned is not in the avoid list: the next label "
        "is placed against a table that predates it"
    )


def _four_island_presentation() -> PresentationSpec:
    """The shipped ch343 sheet re-cut into four islands, in memory.

    U1 alone, H1 alone, C1/C3/C4 as one `ch343_power` island, the USB end as it
    ships, and the shipped flow kept: the shape the page could not compile.
    """
    path = SPECS / f"{BOARD}.presentation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["modules"] = [
        {
            "id": "usb_c",
            "role": 'the USB end: the receptacle with its CC pulldowns, the VBUS reservoir and the VBUS lamp',
            "parts": ["USB1", "R1", "R2", "C2", "D1", "R3"],
            "grammarRef": "ic-periphery",
            "core": "USB1",
        },
        {
            "id": "ch343",
            "role": 'the bridge U1 alone: its own designator and value rows need the room C1/C3 were taking',
            "parts": ["U1"],
            "grammarRef": "ic-periphery",
            "core": "U1",
        },
        {
            "id": "ch343_power",
            "role": "U1's supply decoupling: C1 on +5V, C3 on V3, C4 on VCC, one island",
            "parts": ["C1", "C3", "C4"],
            "grammarRef": "ic-periphery",
        },
        {
            "id": "hdr",
            "role": 'the far end: the 2x5 header alone, where the peer board attaches',
            "parts": ["H1"],
            "grammarRef": "ic-periphery",
            "core": "H1",
        },
    ]
    return PresentationSpec.from_dict(payload)


def test_the_four_island_page_compiles_and_the_data_labels_clear_every_name_row():
    """The four-island sheet at 1170x825: the page compiles and the D± names are clear.

    Before 534's body-only fix this was 0 candidates at every legal arrangement: the
    USB end's D- label could not be placed at all, because `_module_boxes` wrote the
    part's **pin-tip hull** (`_part_extent`) into the avoid table — a rectangle
    reaching 9.5 units past the connector's drawn body on every side — so all twelve
    ladder candidates were blocked and the unchecked fallback landed 1.336 units
    inside the D+ name row. With the body alone in the table the D- label takes the
    `+y` ring-2 box, just off the body edge and beside its own pins.

    The three assertions are the defect's three shapes, so a page that merely moves
    the collision cannot pass: no page label on a **name row**, on a **run**, or on
    a **drawn body**.
    """
    circuit = CircuitSpec.load(SPECS / f"{BOARD}.circuit.json")
    book = drawapply.load_library(SPECS / f"{BOARD}.library.json")
    budget = pc.PageCompileBudget(page_box=PAGE)
    budget.keepouts = pageframe.title_block_keepouts(PAGE)
    result = pc.compile_page(circuit, _four_island_presentation(), book, budget)
    assert result.ok, result.render_failures()
    for candidate in result.ranked:
        assert candidate.key[1] == 0
    page = result.pages[0]
    assert sorted(item.id for item in page.modules) == [
        "ch343", "ch343_power", "hdr", "usb_c",
    ]
    rows = readability._named_wire_rows(page.plan)
    assert any(text == "D+" for _n, _b, _o, text in rows)
    # 534 formal migration: D+/D- are named by `localLabelObligations`, so their
    # labels are the modules' own (they carry the pin's part id) instead of page
    # boundary labels with an empty owner. The statement under test is that both
    # data names exist and clear every row — not who owns the label.
    assert {item.net for item in page.plan.labels} >= {"D+", "D-"}
    # Every label on the page — the modules' own and the page's — faces the same three
    # hard checks below (name rows, runs, drawn bodies); the owner is not the subject.
    page_labels = list(page.plan.labels)
    runs = [
        box for item in page.plan.segments
        for box in pc._run_boxes([tuple(point) for point in item.points])
    ]
    bodies = [
        pc._body_box(book[part.symbol_ref], part)
        for part in page.plan.parts if part.symbol_ref in book
    ]
    bodies = [box for box in bodies if box is not None]
    for label in page_labels:
        for name, box, _owner, text in rows:
            assert not pc._overlaps(label.bbox, box), (
                f"page label {label.net!r} {label.bbox} sits on {name} {text!r} {box}"
            )
        for box in runs:
            assert not pc._overlaps(label.bbox, box), (
                f"page label {label.net!r} {label.bbox} sits on a run {box}"
            )
        for box in bodies:
            assert not pc._overlaps(label.bbox, box), (
                f"page label {label.net!r} {label.bbox} sits on a body {box}"
            )


def test_a_part_is_avoided_by_its_body_and_a_body_less_symbol_by_its_extent():
    """`_module_boxes`: the drawn body is the paper, the pin-tip hull is not.

    Three halves, and each one is a way the fix can go wrong: the paper between the
    body edge and a pin tip must be **given back** (that is the defect), the body
    itself must still be **refused** (that is the gate's own extent), and a symbol
    that states no body must keep the old extent — an unstated extent is not a
    measured zero, so it is not a measured "nothing to avoid" either.

    The pin states its length here on purpose (534 F2): a pin whose drawn length is
    unstated makes `_text_walls` stand the **whole part box** in for it, so "the
    hull is not paper" would be unprovable on that fixture — and that fallback is
    the other half of F2's own test. The free paper probed below is *beside* the
    lead, not across it: the lead itself is ink now.
    """
    body = (-10.0, -20.0, 10.0, 20.0)
    profile = SymbolProfile(
        symbol_ref="S1", body=body,
        pins=[SymbolPin(number="1", tip=(-25.0, 0.0), direction="left", length=15.0)],
    )
    part = pc.LayoutPart(part_id="S1", symbol_ref="S1", x=100.0, y=100.0, rotation=0)
    boxes = pc._module_boxes(LayoutPlan(parts=[part]), {"S1": profile})
    drawn = pc._body_box(profile, part)
    extent = pc._part_extent(profile, part)
    assert drawn is not None and extent[0] < drawn[0] - 1e-6, (
        "the fixture must have its pin tip outside the body, or it proves nothing"
    )
    assert drawn in boxes, "the drawn body is not avoided"
    assert extent not in boxes, "the pin-tip hull is still claimed as paper"

    centre_y = (drawn[1] + drawn[3]) / 2.0
    # Beside the lead (which runs along y = centre_y), between the body edge and
    # the tip: legal paper, and inside the hull, so this is the corner the fix
    # gives back.
    beside_pin = (extent[0] + 1.0, centre_y + 6.0, extent[0] + 13.0, centre_y + 14.0)
    assert not any(pc._overlaps(beside_pin, box) for box in boxes), (
        "the paper between the body edge and the pin tip is still blocked"
    )
    on_lead = (extent[0] + 1.0, centre_y - 0.5, extent[0] + 13.0, centre_y + 0.5)
    assert any(pc._overlaps(on_lead, box) for box in boxes), (
        "a label printed on the pin's own lead must be refused (F2)"
    )
    on_body = (drawn[0] + 2.0, centre_y - 4.0, drawn[0] + 6.0, centre_y + 4.0)
    assert any(pc._overlaps(on_body, box) for box in boxes), (
        "a label printed on the body must still be refused"
    )

    # A symbol that states no body: the old extent stays (here the part's own point).
    bare = SymbolProfile(symbol_ref="S2")
    bare_part = pc.LayoutPart(
        part_id="S2", symbol_ref="S2", x=5.0, y=7.0, rotation=0,
    )
    bare_boxes = pc._module_boxes(LayoutPlan(parts=[bare_part]), {"S2": bare})
    assert bare_boxes == [(5.0, 7.0, 5.0, 7.0)], (
        "a profile with no stated body must fall back to _part_extent, not vanish"
    )


def test_a_page_label_may_not_print_on_a_pin_lead_but_may_sit_beside_it():
    """534 F2：body→pin tip 之间那根**引线**是墨，`body∪tip` 的凸包仍然不是。

    审查实测的 R0402：body ``[-10,-20,10,20]``，pin tip ``(0,50)``，于是这根脚在
    body 中心线上画一条 ``y 20..50`` 的引线；一枚 page label 落在了
    ``(-19.5, 33, 19.5, 42)``——正压在这条引线上、却完全避开 body。`_module_boxes`
    旧代码只放 body，于是它被当成干净纸面收下，而 readability 对「文字压引线」没有
    硬闸。四半，每一半都是修法可以走歪的一种：

    1. 引线自己（`PIN_TEXT_WALL` 厚的细盒）必须在集合里；
    2. 审查的 label 盒必须被拒——而且它确实不碰 body（否则这条用例证明的是别的）；
    3. 合法座位仍在：紧挨引线、位于 body 边与 tip 之间（**在凸包里**）的盒子必须空着，
       否则就是把刚还回去的角料又按凸包收回去了；
    4. 两条既有保守回退不能丢：`pin.length` 缺失 → 整个 part box；`body` 缺失 →
       `_part_extent`。

    变异验证（撤销「加入 pin walls」）：第 1、2 条与 `_label_box` 那半立刻变红——旧
    集合里 ``(-7, 33, 7, 42)`` 就是被收下的座位，正压在引线上。
    """
    body = (-10.0, -20.0, 10.0, 20.0)
    profile = SymbolProfile(
        symbol_ref="R0402", body=body,
        pins=[SymbolPin(number="1", tip=(0.0, 50.0), direction="up", length=30.0)],
    )
    part = pc.LayoutPart(part_id="R1", symbol_ref="R0402", x=0.0, y=0.0, rotation=0)
    plan = LayoutPlan(parts=[part])
    boxes = pc._module_boxes(plan, {"R0402": profile})

    # 1) 引线盒在场：tip (0,50) 向内 30 到 body 边 (0,20)，厚度 PIN_TEXT_WALL。
    lead = (-0.5, 19.5, 0.5, 50.5)
    assert lead in boxes, boxes
    assert pc._body_box(profile, part) in boxes, boxes

    # 2) 审查的那枚 label：压引线、不压 body，今天必须被拒。
    review_label = (-19.5, 33.0, 19.5, 42.0)
    assert pc._overlaps(review_label, lead), (review_label, lead)
    assert not pc._overlaps(review_label, body), (review_label, body)
    assert any(pc._overlaps(review_label, box) for box in boxes), (
        "a page label on the body-to-tip lead is still accepted: " + repr(boxes)
    )

    # 3) 凸包不是纸：紧挨引线、在 body 边与 tip 之间（且在 body∪tip 的凸包内）的座位
    #    必须空着。这四个数就是「回到 _part_extent」时会立刻变红的那块角料。
    extent = pc._part_extent(profile, part)
    assert extent == (-10.0, -20.0, 10.0, 50.0), extent
    assert extent not in boxes, "the body∪pin-tip hull is back in the occupied set"
    beside_lead = (2.0, 34.0, 8.0, 43.0)
    assert (
        beside_lead[0] > lead[2] and beside_lead[1] > body[3]
        and extent[0] <= beside_lead[0] and beside_lead[2] <= extent[2]
        and extent[1] <= beside_lead[1] and beside_lead[3] <= extent[3]
    ), "the fixture must sit inside the hull and clear of body and lead"
    assert not any(pc._overlaps(beside_lead, box) for box in boxes), boxes

    # ... and the seating rule now walks off the lead instead of taking that rung.
    old_seat = pc._label_box("D+", (0.0, 25.0), (0.0, 1.0), [body])
    assert pc._overlaps(old_seat, lead), old_seat
    new_seat = pc._label_box("D+", (0.0, 25.0), (0.0, 1.0), boxes)
    assert new_seat != old_seat, (old_seat, new_seat)
    assert not any(pc._overlaps(new_seat, box) for box in boxes), (new_seat, boxes)

    # 4a) 有 body、pin.length 缺失：`_text_walls` 自己回退全 part box（保守、照旧）。
    loose = SymbolProfile(
        symbol_ref="R0402", body=body,
        pins=[SymbolPin(number="1", tip=(0.0, 50.0), direction="up")],
    )
    loose_boxes = pc._module_boxes(plan, {"R0402": loose})
    assert loose_boxes == [extent], loose_boxes
    assert any(pc._overlaps(beside_lead, box) for box in loose_boxes), (
        "the conservative fallback must still claim the whole part box"
    )

    # 4b) body 缺失：`_part_extent`（这里就是 pin tip 一个点）照旧。
    no_body = SymbolProfile(
        symbol_ref="R0402",
        pins=[SymbolPin(number="1", tip=(0.0, 50.0), direction="up", length=30.0)],
    )
    no_body_boxes = pc._module_boxes(plan, {"R0402": no_body})
    assert no_body_boxes == [pc._part_extent(no_body, part)], no_body_boxes
