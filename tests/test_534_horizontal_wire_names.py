"""534 r18 — a wire's **name row must be horizontal**, and the carrier is chosen for it.

The defect, measured on the shipped four-island `ch343_uart` sheet
(`.tmp_534/host-text-fix-diagnosis-r1/findings.md`, `final-postcheck-r1/text-diagnostic.json`):
two local-label carriers printed their net's name rotated a quarter turn. In the
host's SVG exactly two of 179 text nodes carried ``transform="rotate(-90 …)"`` —
`D+` at (210, 675) and `D-` at (200, 712.5) — and both are the **middle run** of a
carrier the compiler drew as `H-V-H` (the local-label ladder's bent rung,
`drawcompiler._local_label_paths`). The host names a wire along the run it picks;
the model names the longest run (`textmetrics.wire_name_row`), which on those two
shapes is horizontal, so every box test called the page clean while the page read
bottom-to-top.

Three facts this file pins, in that order:

1. **Direction is not a box shape.** `D+`'s row is 9.336 wide by 10 tall on the
   horizontal and 10 wide by 9.336 on the vertical — a ratio of 1.07. The
   earlier "taller than wide" test therefore called both rotated rows horizontal;
   `wire_name_row` carries the axis out of the run that was chosen instead, and
   `readability` refuses a vertical one (`name-row-vertical`).
2. **A carrier is refused by direction, never by its leg count.** The ladder
   keeps offering the bent family; what it no longer accepts is a shape whose
   longest run *or* whose odd-table middle run is vertical. A legal stagger — a
   4- or 5-run table that steps aside on a horizontal middle run — stays a
   candidate, because "more than two legs" is not the defect.
3. **The shipped sheet compiles to four horizontal `D+`/`D-` rows 20 units
   apart.** The straight rung grew (`drawcompiler.LOCAL_LABEL_RUNGS`) because a
   row one text row below its neighbour needs 58.32 units of run to make
   `drawlint`'s 20-unit duplicate-net gap; the two pins that were served by one
   step still take one step.

Evidence: `.tmp_534/horizontal-wire-name-fix-r1/` (`compile-summary.json`, the
legacy/fixed diff). The host's selection rule above three runs is **not**
established (534 r18: 22 of 24 named rows land on the longest run, the two
5-run local-label carriers on the middle one), so nothing here predicts it —
the middle run is used as a veto only.
"""

from __future__ import annotations

import math
import pathlib

import pytest

from boardwise.core import pageframe
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutLabel, LayoutPlan, LayoutSegment, label_wire_indices
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.textmetrics import (
    WIRE_NAME_AXIS_HORIZONTAL,
    WIRE_NAME_AXIS_VERTICAL,
    wire_name_box,
    wire_name_middle_run,
    wire_name_row,
)
from boardwise.engines import drawapply, readability
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
BOARD = "ch343_uart"
PAGE = (0.0, 0.0, 1170.0, 825.0)
EVIDENCE = ROOT / ".tmp_534" / "horizontal-wire-name-fix-r1"

#: Every net whose **wire** carries the drawing's name on the shipped sheet: the
#: two Type-C data nets, one carrier per USB data pin (`compile-summary.json`).
#: The sheet has **eleven** label nets (`LABEL_NETS` below) — a `LayoutLabel` is a
#: text row the host prints at a box the compiler placed, not a row the host
#: anchors on a wire (`core.layoutplan.label_wire_indices`), so it is not a
#: carrier and this batch cannot rotate it.
CARRIER_NETS = frozenset({"D+", "D-"})
LABEL_NETS = frozenset({
    "CTS", "D+", "D-", "DCD", "DSR", "DTR", "RI", "RTS", "RXD", "TXD", "V3",
})

#: The USB-C receptacle and the bridge, so the carriers are picked by **pin** and
#: not by a segment number: `D+` is A6/B6 and U1.5, `D-` is A7/B7 and U1.6.
USB = "USB1"
BRIDGE = "U1"
USB_REACH = 80.0

#: `drawlint.L5_DUPLICATE_NET_GAP` — the gap two rows of one net must keep.
NAME_ROW_GAP = 20.0


def _carrier_plan(points) -> LayoutPlan:
    """One wire that **is** a label's carrier: a label anchor sits on it."""
    return LayoutPlan(
        segments=[LayoutSegment(net="D+", points=[list(p) for p in points])],
        labels=[
            LayoutLabel(
                net="D+", text="D+", bbox=(-4.0, -4.0, 4.0, 4.0),
                x=float(points[-1][0]), y=float(points[-1][1]),
            ),
        ],
    )


def _row_gap(a, b) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def _has_vertical_middle(points) -> bool:
    """Does this carrier's merged run table have an odd length and a vertical middle?"""
    middle = wire_name_middle_run([list(p) for p in points])
    return middle is not None and abs(middle[0][1] - middle[1][1]) > 1e-6


# ------------------------------------------------- 1. direction, not box shape


def test_the_box_cannot_say_which_way_a_name_row_runs():
    """"Taller than wide" is not a direction test — the ratio here is 1.07.

    This is the measurement that made the defect invisible: on a short net name
    the horizontal row (width = text, height = row) and the vertical one (width =
    row, height = text) are within 7% of each other, so the previous reading of
    "box height > 1.5 x box width" answered "horizontal" for both of the rotated
    rows on the CH343 sheet. The axis therefore comes from the run, not the box.
    """
    horizontal = wire_name_row([(0.0, 0.0), (40.0, 0.0)], "D+")
    vertical = wire_name_row([(0.0, 0.0), (0.0, 40.0)], "D+")
    assert horizontal is not None and vertical is not None
    assert horizontal.axis == WIRE_NAME_AXIS_HORIZONTAL
    assert vertical.axis == WIRE_NAME_AXIS_VERTICAL
    # the two boxes are the same pair of numbers transposed — no ratio test can
    # separate them, and picking the wider one as "horizontal" gets D+ wrong
    hw, hh = horizontal.box[2] - horizontal.box[0], horizontal.box[3] - horizontal.box[1]
    vw, vh = vertical.box[2] - vertical.box[0], vertical.box[3] - vertical.box[1]
    assert (round(hw, 6), round(hh, 6)) == (round(vh, 6), round(vw, 6))
    # the old API is the box half of the new one, unchanged
    assert horizontal.box == wire_name_box([(0.0, 0.0), (40.0, 0.0)], "D+")


def test_a_vertical_name_row_is_a_hard_violation():
    """`readability` reports it, and the kind is a hard one.

    A direction defect is not a collision: the row can sit in free space, clear of
    every body, every conductor and every other row, and still be unreadable. The
    three box constraints are blind to it by construction, which is why it needs
    its own kind rather than a new reading of `text-overlap`.
    """
    plan = _carrier_plan([(0.0, 0.0), (0.0, 40.0)])
    assert label_wire_indices(plan) == frozenset({0}), "the fixture must carry a name"
    violations = readability._check_named_wire_rows(plan)
    assert [item.kind for item in violations] == [readability.KIND_NAME_ROW_VERTICAL]
    assert violations[0].objects == ("segments[0]",)
    assert readability.KIND_NAME_ROW_VERTICAL in readability.HARD_KINDS
    # and a horizontal carrier of the same net is untouched
    assert readability._check_named_wire_rows(
        _carrier_plan([(0.0, 0.0), (40.0, 0.0)])
    ) == []


def test_a_wire_that_is_not_the_label_prints_no_row_to_refuse():
    """The gate reads the same carriers `_named_wire_rows` does — no more, no less."""
    plan = LayoutPlan(segments=[LayoutSegment(net="D+", points=[(0.0, 0.0), (0.0, 40.0)])])
    assert label_wire_indices(plan) == frozenset()
    assert readability._check_named_wire_rows(plan) == []


# --------------------------------------- 2. the carrier is refused by direction


def test_the_bent_rung_of_the_ladder_is_refused_for_its_vertical_middle_run():
    """The `H-V-H` shapes the ladder offers are not candidates any more.

    This is the shape that printed the two rotated rows. The refusal is measured
    on the shape's own runs — the model's run is the horizontal tail, and the
    **middle run of the odd-length table** is the vertical one the host printed
    on — so no net name, coordinate or leg count enters the decision.
    """
    paths = dc._local_label_paths((215.0, 680.0), (-1.0, 0.0), 5.0)
    bent = [path for _direction, path in paths if len(path) > 2]
    assert bent, "the bent family must still be offered — it is refused, not deleted"
    for path in bent:
        middle = wire_name_middle_run(path)
        assert middle is not None and abs(middle[0][1] - middle[1][1]) > 1e-6, path
        reason = dc._carrier_name_reason(path, "D+")
        assert reason is not None and "vertical" in reason, (path, reason)
        # the model's own run on that shape is horizontal — which is exactly why
        # the box model alone accepted it
        row = wire_name_row(path, "D+")
        assert row is not None and row.horizontal


def test_a_legal_stagger_is_not_killed_for_its_leg_count():
    """Direction and gap decide; four, five or six legs do not.

    Both shapes step aside and both are legal: the 4-run table is even (no middle
    run) and its longest run is horizontal, the 5-run table's middle run *is* its
    horizontal tail. A rule written as "reject legs > 2" would refuse both, which
    is the unmeasured one-size rule this batch must not install.
    """
    four_run = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 20.0), (40.0, 20.0)]
    five_run = [
        (0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (25.0, 10.0), (25.0, 20.0), (45.0, 20.0),
    ]
    for path in (four_run, five_run):
        runs = len(path) - 1
        assert runs >= 4, "these are staggers, not straight runs"
        assert dc._carrier_name_reason(path, "D+") is None, path
        row = wire_name_row(path, "D+")
        assert row is not None and row.horizontal
    # ...while the same stagger with a vertical middle run is refused
    vertical_middle = [(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (30.0, 20.0)]
    assert dc._carrier_name_reason(vertical_middle, "D+") is not None
    # a plain straight run and a plain vertical run are decided by the same rule
    assert dc._carrier_name_reason([(0.0, 0.0), (40.0, 0.0)], "D+") is None
    assert dc._carrier_name_reason([(0.0, 0.0), (0.0, 40.0)], "D+") is not None


# --------------------------------------- 3. the shipped sheet, compiled for real


@pytest.fixture(scope="module")
def shipped():
    """The four-island board as shipped: `(circuit, presentation, book, result)`."""
    budget = pc.PageCompileBudget(page_box=PAGE)
    budget.keepouts = pageframe.title_block_keepouts(PAGE)
    circuit = CircuitSpec.load(SPECS / f"{BOARD}.circuit.json")
    presentation = PresentationSpec.load(SPECS / f"{BOARD}.presentation.json")
    book = drawapply.load_library(SPECS / f"{BOARD}.library.json")
    return circuit, presentation, book, pc.compile_page(circuit, presentation, book, budget)


def _carriers(plan) -> list[tuple[int, str, object]]:
    """Every `(segment index, net, row)` the page prints a name on."""
    indices = label_wire_indices(plan)
    out = []
    for index, segment in enumerate(plan.segments):
        if index not in indices or not segment.net:
            continue
        row = wire_name_row([list(p) for p in segment.points], segment.net)
        if row is not None:
            out.append((index, segment.net, row))
    return out


def test_every_name_row_on_the_shipped_sheet_is_horizontal(shipped):
    """The acceptance, stated page-wide: no carrier prints a rotated name."""
    _circuit, _presentation, _book, result = shipped
    assert result.ok, result.render_failures()
    page = result.pages[0]
    plan = page.plan
    carriers = _carriers(plan)
    assert carriers, "the page must print some names"
    assert {net for _index, net, _row in carriers} == CARRIER_NETS
    vertical = [
        (index, net, row.box) for index, net, row in carriers if not row.horizontal
    ]
    assert vertical == [], f"rotated name rows: {vertical}"


def test_the_four_d_carriers_are_horizontal_and_twenty_units_apart(shipped):
    """`D+`/`D-` are the four carriers that were rotated, one per Type-C data pin.

    Selected by pin, not by segment number: each of the two nets has three
    members (`USB1.A6/B6` + `U1.5`, `USB1.A7/B7` + `U1.6`), and the carriers under
    test are the two whose run **starts on the receptacle's own data pins**. The
    bridge end is named by a placed `LayoutLabel` (its anchor is on the bridge
    side of the sheet, and a label is a box the compiler places, not a row the
    host anchors on a wire) — so it is not a carrier and nothing there can rotate.

    Each carrier is a straight run now (the host has one run to name, so the
    model's guess cannot miss), the run it is named on is horizontal, and the two
    rows of one net keep `drawlint`'s 20-unit gap — the defect's own numbers,
    15.664 and 12.748 on the page before this fix.
    """
    _circuit, _presentation, _book, result = shipped
    assert result.ok, result.render_failures()
    page = result.pages[0]
    plan = page.plan
    receptacle = next(item for item in plan.parts if item.part_id == USB)
    bridge = next(item for item in plan.parts if item.part_id == BRIDGE)
    assert {item.net for item in plan.labels} == LABEL_NETS, (
        "the label universe moved — this test's carrier/label split reads it"
    )

    rows: dict[str, list] = {"D+": [], "D-": []}
    far: list[tuple[int, str, object]] = []
    other: list[str] = []
    for index, net, row in _carriers(plan):
        if net not in rows:
            other.append(net)
            continue
        (ax, ay), _tail = row.run
        reach = math.hypot(ax - receptacle.x, ay - receptacle.y)
        # Every `D+`/`D-` wire row is judged, on either side of the sheet — a row
        # near the bridge is not excused from being horizontal (the sheet is
        # compiled from island plans, and a carrier drawn after this stage would
        # be a wire row here only if the plan carries it).
        assert row.horizontal, (index, net, row.box)
        (ax, ay), (bx, by) = row.run
        assert abs(ay - by) <= 1e-6, (
            f"segments[{index}] ({net}) is named on a vertical run "
            f"({ax}, {ay})-({bx}, {by})"
        )
        if reach > USB_REACH:
            far.append((index, net, row))
            continue
        # The four under test are selected **by pin**: the run starts on the
        # receptacle's own data pins, not at a segment number.
        rows[net].append((index, row))
        assert [list(p) for p in plan.segments[index].points] == [[ax, ay], [bx, by]], (
            f"segments[{index}] ({net}) must be one straight run: the host has no "
            "second run to choose instead"
        )
    assert other == [], f"a net outside the data pair now carries a wire name: {other}"
    for net, items in rows.items():
        assert len(items) == 2, f"{net} must carry one name per receptacle data pin: {items}"
        assert _row_gap(items[0][1].box, items[1][1].box) >= NAME_ROW_GAP, (
            f"the two {net} rows are {_row_gap(items[0][1].box, items[1][1].box):g} "
            f"units apart ({items[0][1].box}, {items[1][1].box})"
        )
    # The bridge end: named **once** per net, and named horizontally. Whether that
    # name is a wire row or a placed label is the compiler's business at this
    # stage (a carrier drawn after the page plan would not appear here) — what
    # this batch owns is that whichever it is, it is not rotated, and there is
    # exactly one of it (two would be one statement printed twice).
    for net in rows:
        wire_rows = [row for _index, name, row in far if name == net]
        assert all(row.horizontal for row in wire_rows)
        on_bridge = [
            item for item in plan.labels
            if item.net == net
            and math.hypot(item.x - bridge.x, item.y - bridge.y) <= 100.0
        ]
        assert len(wire_rows) + len(on_bridge) == 1, (
            f"{net}'s bridge-side name must be stated exactly once — "
            f"{len(wire_rows)} wire row(s), {len(on_bridge)} label(s): "
            f"{[row.box for row in wire_rows]} {[item.bbox for item in on_bridge]}"
        )


def test_the_page_is_readable_and_nothing_else_moved(shipped):
    """`readability.check` is clean, and the fix moved only what it had to.

    The diff is taken against the same board compiled with the *previous* ladder
    (four straight rungs, no direction filter): the only objects allowed to
    change are the `D+`/`D-` carriers and the labels that sit at their far ends.
    Everything else — the island frames, every part's own rows, the rail flags,
    the pin rows, the NC verdict — has to be identical, or the cure has become a
    different disease.
    """
    circuit, presentation, book, result = shipped
    assert result.ok, result.render_failures()
    page = result.pages[0]
    plan = page.plan
    checked = readability.check(
        plan, circuit, presentation, book, page_box=PAGE,
        keepouts=pageframe.title_block_keepouts(PAGE),
    )
    assert checked.hard_violations == [], [item.render() for item in checked.hard_violations]

    def snapshot():
        return {
            "segments": [
                (item.net, tuple(tuple(p) for p in item.points)) for item in plan.segments
            ],
            "texts": [(item.part_id, item.text, item.bbox) for item in plan.texts],
            "flags": [(item.net, item.x, item.y, item.rotation)
                      for item in plan.power_symbols],
            "modules": [(item.id, item.frame) for item in page.modules],
        }

    legacy_run, legacy_filter = dc.LOCAL_LABEL_RUNGS, dc._carrier_name_reason
    legacy_check = readability._check_named_wire_rows
    try:
        dc.LOCAL_LABEL_RUNGS = 4
        dc._carrier_name_reason = lambda points, text: None
        readability._check_named_wire_rows = lambda layout_plan: []
        legacy_budget = pc.PageCompileBudget(page_box=PAGE)
        legacy_budget.keepouts = pageframe.title_block_keepouts(PAGE)
        legacy = pc.compile_page(circuit, presentation, book, legacy_budget)
    finally:
        dc.LOCAL_LABEL_RUNGS, dc._carrier_name_reason = legacy_run, legacy_filter
        readability._check_named_wire_rows = legacy_check
    assert legacy.ok, legacy.render_failures()

    old, new = snapshot(), snapshot()
    old_plan = legacy.pages[0].plan
    old_segments = [
        (item.net, tuple(tuple(p) for p in item.points)) for item in old_plan.segments
    ]
    assert len(new["segments"]) == len(old_segments), (
        "the fix must not add or drop a wire: "
        f"{len(old_segments)} -> {len(new['segments'])}"
    )
    changed = {
        f"{old_segments[index][0]!r}->{new['segments'][index][0]!r}"
        for index in range(len(new["segments"]))
        if old_segments[index] != new["segments"][index]
    }
    assert all(
        net in ("'D+'", "'D-'", "'CC1'") for pair in changed for net in pair.split("->")
    ), f"wires other than the D pair changed: {sorted(changed)}"
    # `CC1` is the one knock-on, and it is a *route*: the D+ carrier now owns the
    # band its old path bent around, so the router drops a redundant 5-unit jog.
    # Its net and both endpoints are unchanged, which is the connectivity fact.
    cc1_old = [item for item in old_segments if item[0] == "CC1"]
    cc1_new = [item for item in new["segments"] if item[0] == "CC1"]
    assert len(cc1_old) == len(cc1_new) == 1
    assert (cc1_old[0][1][0], cc1_old[0][1][-1]) == (cc1_new[0][1][0], cc1_new[0][1][-1])
    assert changed, "the fix must change the two carriers it is about"
    assert new["texts"] == old["texts"], "a part's own rows moved"
    assert new["flags"] == old["flags"], "a rail flag moved"
    assert new["modules"] == old["modules"], "an island frame moved"
    # the legacy page *was* the defect — but not in the model's own words: on those
    # two carriers the model names the longest run, which is horizontal, so
    # `wire_name_row` cannot see what the host did (it printed the *middle* run).
    # The shape is the evidence: two carriers whose merged run table is odd and
    # whose middle run is vertical — exactly what `_carrier_name_reason` refuses
    # now (`compile-summary.json` keeps the measured SVG `rotate(-90)` rows).
    rotating = [
        index for index, _net, _row in _carriers(old_plan)
        if _has_vertical_middle(old_plan.segments[index].points)
    ]
    assert len(rotating) == 2, (
        "the previous ladder must carry two shapes with a vertical middle run, or "
        f"this diff proves nothing: {rotating}"
    )
    refused = [
        index for index, net, _row in _carriers(old_plan)
        if dc._carrier_name_reason(
            [list(p) for p in old_plan.segments[index].points], net
        ) is not None
    ]
    assert refused == rotating, "the filter must refuse exactly the shapes the host rotated"


def test_the_compiled_summary_of_record_exists():
    """The batch's evidence file, so the numbers in the docstring are re-readable."""
    summary = EVIDENCE / "compile-summary.json"
    if not summary.exists():
        pytest.skip(f"evidence not captured in this checkout: {summary}")
    assert summary.stat().st_size > 0
