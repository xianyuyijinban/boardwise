"""534 — a four-island page whose flow is written down must compile, and a
port label must not land on the run beside it.

The defect, as the task book's evidence has it: `blocklib/specs/ch343_uart`'s
four islands (three flow modules plus the `ch343_power` supply group) compile
without a flow (four candidates, but the USB connector ends
up *rightmost*), and adding

    "flow": [["usb_c", "ch343"], ["ch343", "hdr"]]

turned every one of the twelve variants into the same refusal:

    "[text-overlap] labels[3] 'D-' [203, 698, 217, 707] and segments[0] 'D+'
     [205, 690, 215, 699.336] intersect"

Two mechanisms, both measured (`evidence/534/compile_flow_repro.log`,
`evidence/534/compile_final2.log`):

1. `segments[0]` in that message is not the conductor but the **name row** the
   host prints on a wire that carries a name, and the wire carries one *because*
   the page put a D+ label at its pin (`core.layoutplan.label_wire_indices`). So
   the collision is a page label against a row the page's own label summoned.
2. `_label_box` tried four directions at one text gap and then fell through to a
   fallback that checked nothing; on a large part all four directions are blocked
   at that distance (the body on three sides, a tap stub on the fourth), so the
   unchecked fallback *was* the placement. `_module_boxes` made it worse: a wire
   contributed its whole polyline's bounding box (a meander's rectangle is mostly
   empty paper) and a straight run's box has zero height or width, which the
   strict overlap test can never see.

The fix is the smallest one that removes both: a wire contributes one padded box
per **run**, a rail flag's name row joins the avoidance list, and the four
directions are walked out over `_LABEL_RINGS` before the fallback is reached.
The valve lamp's wire (LED_A) is *not* a compiler matter: the spec already
promises it through `directWiringObligations`.

Evidence: `evidence/534/compile_flow_repro.log` (exit 5, before),
`evidence/534/compile_final2/` (exit 0, six candidates, before/after),
`evidence/534/connectivity_cand1.txt` (17/17 nets, no open pin).
"""

from __future__ import annotations

import copy
import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutSegment
from boardwise.core.pagelayoutplan import PageLayoutPlan
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import (
    FLAG_GLYPH_KIND_GND,
    FLAG_GLYPH_KIND_RAIL,
    flag_glyph_kind,
)
from boardwise.engines import drawapply
from boardwise.engines import pagecompiler as pc
from boardwise.core import pageframe

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
BOARD = "ch343_uart"
PAGE = (0.0, 0.0, 1170.0, 825.0)


def _budget():
    """The CLI's own page budget for a multi-island sheet (S-01's keep-out)."""
    budget = pc.PageCompileBudget(page_box=PAGE)
    budget.keepouts = pageframe.title_block_keepouts(PAGE)
    return budget


@pytest.fixture(scope="module")
def board():
    """The shipped four-island board, compiled once: `(presentation, result)`."""
    circuit = CircuitSpec.load(SPECS / f"{BOARD}.circuit.json")
    presentation = PresentationSpec.load(SPECS / f"{BOARD}.presentation.json")
    book = drawapply.load_library(SPECS / f"{BOARD}.library.json")
    return presentation, pc.compile_page(circuit, presentation, book, _budget())


def _order(page: PageLayoutPlan) -> list[str]:
    """The island order the reader sees: real columns, top to bottom.

    The page fills a grid in flow order and the reader walks it the way the page
    layer's own backflow rule does: down a **column**, then the next column to the
    right. ``y`` grows *upward* on this sheet (the title block keep-out sits at
    ``y 10..190``), so "top" is the larger ``y``.

    A column is a band of frames whose **x extents overlap** — not a single left
    edge. The old helper read one axis alone (all-in-one-column vs all-in-one-row)
    and, on a 2x2 page whose lower row's right-hand island starts a few units to
    the *left* of the upper row's (534's candidate 1: ``ch343`` x 483..771 above
    ``hdr`` x 479..671), a pure x sort interleaved the two rows and reported
    ``ch343_power, usb_c, hdr, ch343`` for a page that reads
    ``usb_c, ch343, ch343_power, hdr``. Grouping by x overlap gives the columns
    the page layer itself uses (the flow runs down a column between stacked
    frames, `readability`'s rule); the flow assertion stays exactly as strict.
    """
    frames = [(item.id, *item.frame) for item in page.modules]
    columns: list[list[tuple]] = []
    for frame in sorted(frames, key=lambda f: f[1]):
        for column in columns:
            low = min(item[1] for item in column)
            high = max(item[3] for item in column)
            if frame[1] < high and frame[3] > low:
                column.append(frame)
                break
        else:
            columns.append([frame])
    columns.sort(key=lambda column: min(item[1] for item in column))
    return [
        frame[0]
        for column in columns
        for frame in sorted(column, key=lambda f: (-f[4], f[1]))
    ]


def _runs(page: PageLayoutPlan) -> list[tuple]:
    """Every wire run of the merged page, as the padded box the page avoids."""
    boxes = []
    for item in page.plan.segments:
        points = [tuple(point) for point in item.points]
        boxes.extend(pc._run_boxes(points))
    return boxes


def test_the_declared_flow_compiles_and_the_connector_reads_first(board):
    """The board as shipped: flow written down, every candidate clean, USB left.

    Before the fix this is the task book's exit 5 — twelve variants, zero pages.
    The order assertion is the whole point of the flow: without it the same board
    compiles with `usb_c` on the **right** (`evidence/534/compile_final.log`,
    `usb_c@(865, 690)`), which is what a reader who enters at the connector cannot
    use.
    """
    presentation, result = board
    assert [
        (edge.from_module, edge.to_module) for edge in presentation.flow
    ] == [
        ("usb_c", "ch343"), ("ch343", "hdr"),
    ], "the shipped presentation must keep its flow: it is the fix's subject"
    assert result.ok, result.render_failures()
    assert not result.failures
    assert len(result.pages) >= 2, "two island widths are why this board needs a flow"

    for candidate in result.ranked:
        assert candidate.key[1] == 0, (
            f"a candidate page carries {candidate.key[1]:g} finding(s) — "
            "the page layer must be clean before it is ranked"
        )
    for page in result.pages[:2]:
        # 534 formal migration: the page is four islands; `ch343_power` is a supply
        # group the flow does not order (its position is the page's business), so the
        # declared order is read off the three flow modules only — exactly and in
        # order, never merely "appears before".
        assert sorted(item.id for item in page.modules) == [
            "ch343", "ch343_power", "hdr", "usb_c",
        ], (
            "the shipped page is four islands (three flow modules plus the "
            f"`ch343_power` supply group), got {[item.id for item in page.modules]}")
        walked = [item for item in _order(page) if item in ("usb_c", "ch343", "hdr")]
        assert walked == ["usb_c", "ch343", "hdr"], (
            f"island order {_order(page)} is not the declared flow")


def test_the_page_labels_never_sit_on_a_run_or_a_flag_s_name_row(board):
    """What the gate refused: a page-placed label inside another net's ink.

    Every label the page itself placed (the module's own labels carry a part id;
    a page label is the boundary statement and has none) is checked against every
    run of the merged drawing and against every rail flag's name row — the two
    boxes `_module_boxes` was missing. On the pre-fix code this test reproduces
    the reported collision: D- `[203, 698, 217, 707]` on the D+ pair's stub.
    """
    presentation, result = board
    assert result.ok, result.render_failures()
    runs = _runs(result.pages[0])
    for page in result.pages:
        rows = []
        for symbol in page.plan.power_symbols:
            profile = _book()[symbol.symbol_ref]
            glyph = pc._glyph_box(profile, symbol.rotation, (symbol.x, symbol.y))
            row = pc._flag_name_row(profile, symbol, glyph)
            if row is not None:
                rows.append(row)
        for label in page.plan.labels:
            if label.part_id is not None:
                continue
            for box in runs:
                assert not pc._overlaps(label.bbox, box), (
                    f"page label {label.net!r} {label.bbox} sits on a wire run {box}"
                )
            for row in rows:
                assert not pc._overlaps(label.bbox, row), (
                    f"page label {label.net!r} {label.bbox} sits on a flag name row "
                    f"{row}"
                )


def test_a_wire_is_avoided_run_by_run_not_as_its_bounding_rectangle(board):
    """`_module_boxes` asks per run, so a meander is not a wall.

    The two halves are the two ways a whole-polyline box fails: a straight run had
    zero height or width and the strict overlap test never saw it, while a detour
    round the part claimed paper its ink never touches.
    """
    straight = pc._run_boxes([(0.0, 0.0), (10.0, 0.0)])
    assert len(straight) == 1
    assert pc._overlaps(straight[0], (4.0, -1.0, 6.0, 1.0)), (
        "a run drawn as a zero-height rectangle is invisible to _overlaps"
    )
    assert straight[0][3] - straight[0][1] == pytest.approx(2 * pc._RUN_PAD)

    meander = [(0.0, 0.0), (0.0, 50.0), (100.0, 50.0), (100.0, 0.0)]
    runs = pc._run_boxes(meander)
    assert len(runs) == 3
    assert not any(
        pc._overlaps(box, (50.0, 10.0, 51.0, 11.0)) for box in runs
    ), "the middle of a detour is not the detour's"

    # And the avoidance list the label placement actually reads must be built
    # from those runs: a helper nothing calls would leave the defect in place.
    _, result = board
    assert result.ok, result.render_failures()
    plan = copy.deepcopy(result.pages[0].plan)
    plan.parts, plan.labels, plan.texts, plan.power_symbols = [], [], [], []
    plan.segments = [LayoutSegment(net="D+", points=meander)]
    boxes = pc._module_boxes(plan, {})
    assert len(boxes) == 3, "_module_boxes is not asking per run"
    assert not any(pc._overlaps(box, (50.0, 10.0, 51.0, 11.0)) for box in boxes), (
        "the meander's rectangle is still claimed as occupied paper"
    )


def test_a_port_label_walks_outward_before_it_gives_up():
    """`_label_box`: four blocked directions are not an answer, four rings are.

    The occupied boxes are the ones 534 found on the USB connector: the part on
    three sides and a stub on the fourth, at one and at two text gaps. The label
    must step out to the third ring rather than return the unchecked fallback
    (the fallback is the north candidate at ring one, which is inside them).
    """
    half_x = pc.drawcompiler.text_width("D+") / 2.0 + pc.drawcompiler.TEXT_GAP
    half_y = pc.drawcompiler.TEXT_SIZE / 2.0 + pc.drawcompiler.TEXT_GAP
    point = (0.0, 0.0)
    occupied = [
        (-40.0, -40.0, -35.0, 40.0),   # the part, west of the pin edge
        (-half_x + 5.0, 40.0, half_x + 5.0, 60.0),      # a neighbouring run
    ]
    for ring in (1.0, 2.0):
        for direction in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)):
            offset = (
                (direction[0] * half_x * ring, 0.0) if direction[0]
                else (0.0, direction[1] * half_y * ring)
            )
            occupied.append((
                point[0] + offset[0] - 1.0, point[1] + offset[1] - 1.0,
                point[0] + offset[0] + 1.0, point[1] + offset[1] + 1.0,
            ))

    box = pc._label_box("D+", point, (1.0, 0.0), occupied)
    assert all(not pc._overlaps(box, item) for item in occupied), (
        f"the label {box} still lands on the boxes the page told it to avoid"
    )
    centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
    assert max(abs(centre[0]), abs(centre[1])) > 2.0 * max(half_x, half_y), (
        "a free spot at the first two rings was not built, so this proves nothing"
    )


def test_the_vbus_lamp_is_a_wire_because_the_spec_promises_it(board):
    """LED_A: a direct conductor inside the USB island, from the spec alone.

    `labelPolicy.local` is "wire", so the lamp's cathode and R3 must not be two
    labels. The promise is the presentation's own `directWiringObligations` entry
    (no compiler change): without it the module's candidate 0 falls back to
    naming both ends, with it candidate 0 draws the wire and the labels are gone.
    """
    presentation, result = board
    promised = {
        net for obligation in presentation.direct_wiring_obligations
        for net in obligation.nets
    }
    assert "LED_A" in promised, (
        "the shipped presentation must promise LED_A as a wire: "
        "labelPolicy.local is 'wire'"
    )
    assert result.ok, result.render_failures()
    page = result.pages[0]
    segments = [item for item in page.plan.segments if item.net == "LED_A"]
    labels = [item for item in page.plan.labels if item.net == "LED_A"]
    assert segments, "the lamp's return is missing from the page drawing"
    assert not labels, (
        f"LED_A is named {len(labels)} time(s) instead of drawn as a conductor"
    )


def _book():
    """`_module_boxes`'s own book, so a test can ask it the same question."""
    return drawapply.load_library(SPECS / f"{BOARD}.library.json")


def test_a_rail_flag_states_its_name_row_and_a_ground_flag_states_none():
    """`_flag_name_row`: the row the host prints beside a flag, or ``None``.

    A ground symbol is its own name; a rail's name row is the band past the glyph
    (`core.textmetrics.flag_name_box`, the readability checker's own measurement).
    The +5V row is what the D+ label was still landing on once the runs were
    right: `labels[2] 'D+' [168, 690.5, 182, 699.5]` against `'+5V'`
    `[168.541, 688, 181.459, 698]`.
    """
    book = _book()
    rail = book.get("PWR-+5V")
    ground = book.get("PWR-GND")
    assert rail is not None, "the library carries no rail flag"
    assert ground is not None, "the library carries no ground flag"
    assert flag_glyph_kind(rail) == FLAG_GLYPH_KIND_RAIL
    assert flag_glyph_kind(ground) == FLAG_GLYPH_KIND_GND

    for kind, profile in (
        (FLAG_GLYPH_KIND_RAIL, rail), (FLAG_GLYPH_KIND_GND, ground),
    ):
        symbol = pc.LayoutPowerSymbol(
            symbol_ref=profile.symbol_ref,
            symbol_hash=profile.geometry_hash(),
            net="+5V" if kind == FLAG_GLYPH_KIND_RAIL else "GND",
            x=200.0, y=700.0, rotation=0,
        )
        glyph = pc._glyph_box(profile, 0, (200.0, 700.0))
        row = pc._flag_name_row(profile, symbol, glyph)
        if kind == FLAG_GLYPH_KIND_GND:
            assert row is None, "a ground flag prints no name to avoid"
            continue
        assert row is not None
        assert row[1] >= glyph[3] - 1e-6, "a rot-0 rail names itself above its glyph"
        assert row[0] <= 200.0 <= row[2], "the row is centred on the flag's axis"
