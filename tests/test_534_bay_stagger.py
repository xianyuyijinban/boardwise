"""534 batch 3 — a distinct-pad sibling group staggers on its own reach.

The defect this test pins is the one batch 2 measured and batch 3 fixed. On the
shipped four-island board (`blocklib/specs/ch343_uart`) the USB-C island's
CC1/CC2/VBUS group is *one* group of branches: same owner, same escape direction,
but three **different pads**. The chain-and-shelf ladder prices every branch of a
group by its index — ``lane + step*index`` — which is right when the group hangs
off one tap (a fan, where the members really are one node) and wrong here: each
sibling's wire still ends at its own pad, so sibling *n* is pushed a lane past the
boxes of siblings ``0..n-1`` and the wire pays for a count nobody drew.

What the staircase cost, measured on this board (`evidence/534/compile_final2/`):
a 494.5-wide ``usb_c`` frame, CC2 drawn 500 long, 2860 units of wire in total.
What staggering on the parts' own reach costs (`evidence/534/compile_q3/`): 374
wide, CC2 360, 2655 total. Both readings are the compiler's own — the frame is
``modules[i].frame`` and the lengths are summed over ``plan.segments`` — so the
thresholds below sit between the two and say which side of the ladder price the
board is on, rather than freezing today's number.

The sheet is now the **four-island** page (534 formal migration): ``C4``, the
100 nF VCC/VIO decoupler, lives in the ``ch343_power`` supply island beside
``C1``/``C3``, and the page reads usb_c 1995 / ch343 290 / ch343_power 365 /
hdr 110 (total 2760). The guard below reads usb_c's own frame-filtered length
rather than the page total — the total would be measuring the other islands'
parts, not this pass.

The pass is allowed to be a no-op, and that half is pinned too: a group whose
anchors coincide is a fan (the ladder is what fans it) and a group the grammar
wrote an order between keeps the staircase as that order's own distance. The
crystal case is the measured reason the second half exists — collapsing
``adjacent(X1, C1)`` in ch340_serial put ``X1`` at -65 and the gate answered
``presentation-poor/X1``.

Evidence: `evidence/534/q3/NOTES.md`, `evidence/534/q3/table.py`,
`evidence/534/q3/cand1_page.png`.
"""

from __future__ import annotations

import types

import pytest

import test_534_flow_page as m534

from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc
from boardwise.engines.grammar.base import RelativeConstraint


def _compile():
    """The shipped board, compiled once (same budget the CLI uses)."""
    circuit, presentation, book = None, None, None
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import drawapply
    from boardwise.engines import pagecompiler as pc

    circuit = CircuitSpec.load(m534.SPECS / f"{m534.BOARD}.circuit.json")
    presentation = PresentationSpec.load(m534.SPECS / f"{m534.BOARD}.presentation.json")
    book = drawapply.load_library(m534.SPECS / f"{m534.BOARD}.library.json")
    budget = pc.PageCompileBudget(page_box=m534.PAGE)
    from boardwise.core import pageframe

    budget.keepouts = pageframe.title_block_keepouts(m534.PAGE)
    return pc.compile_page(circuit, presentation, book, budget)


@pytest.fixture(scope="module")
def page():
    result = _compile()
    assert not result.failures, result.failures
    return result.pages[0]


def _net_length(page, net: str) -> float:
    return sum(
        abs(b[0] - a[0]) + abs(b[1] - a[1])
        for segment in page.plan.segments
        if segment.net == net
        for a, b in zip(segment.points, segment.points[1:])
    )


def _total_length(page) -> float:
    return sum(
        abs(b[0] - a[0]) + abs(b[1] - a[1])
        for segment in page.plan.segments
        for a, b in zip(segment.points, segment.points[1:])
    )


def _frame(page, module_id: str):
    module = next(item for item in page.modules if item.id == module_id)
    x0, y0, x1, y1 = module.frame
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _parts_union_width(page, module_id: str) -> float:
    """Width of the module's own parts, their reference/value texts, and its flags.

    Those boxes move with the part, so they are the drawing's own footprint. The
    frame is that footprint + ``FRAME_PADDING`` on both sides; a wire or label box
    that widened it beyond them is exactly the outward plume this test refuses (the
    bay ladder pushes siblings out in ``lane*index`` steps, and
    `evidence/534/compile_final2/` measured a 494.5-wide frame that way).

    A **flag** sits on the footprint side of that line, not the plume side: its
    glyph is centred on its anchor and the anchor is an electrical node (the flag
    hangs on this pin), so how far the glyph reaches is not a placement choice
    somebody could have made nearer the middle. Measured on the four-island sheet:
    ``usb_c``'s rightmost ink is the GND flag on R3's right pin tip at x 365,
    whose 20-wide glyph reaches **375** — ten units past the part and past every
    text, and exactly the ten units by which the frame reads 394.5 while its parts
    and texts alone span **344.5** (the 354.5 above is that plus the glyph; 394.5
    = 354.5 + 2x20). The box is
    :func:`pagecompiler._glyph_box`, the same one the frame and
    `readability._flag_glyph_box` measure. A rail flag's printed name row is not
    counted: it reaches 1.5 past the glyph, inside the 20-unit padding the frame
    adds, and the frame does not measure it either.

    Wires and label boxes stay out, so the plume is still refused: mutation-checked
    with the run stretched to x 385 and with a label box moved 180 right — both
    still fail the equality below.
    """
    book = drawapply.load_library(m534.SPECS / f"{m534.BOARD}.library.json")
    x0, y0, x1, y1 = _frame(page, module_id)
    boxes = []
    for part in page.plan.parts:
        profile = book.get(part.symbol_ref)
        if profile is None:
            continue
        box = pc._part_extent(profile, part)
        centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        if x0 < centre[0] < x1 and y0 < centre[1] < y1:
            boxes.append(box)
    for text in page.plan.texts:
        centre = ((text.bbox[0] + text.bbox[2]) / 2.0,
                  (text.bbox[1] + text.bbox[3]) / 2.0)
        if x0 < centre[0] < x1 and y0 < centre[1] < y1:
            boxes.append(text.bbox)
    for symbol in page.plan.power_symbols:
        box = pc._glyph_box(book.get(symbol.symbol_ref), symbol.rotation,
                            (symbol.x, symbol.y))
        if box is None:
            box = (symbol.x, symbol.y, symbol.x, symbol.y)
        centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        if x0 < centre[0] < x1 and y0 < centre[1] < y1:
            boxes.append(box)
    assert boxes, f"no part boxes inside the {module_id} frame"
    return max(box[2] for box in boxes) - min(box[0] for box in boxes)


def _module_length(page, module_id: str) -> float:
    """The wire length inside one module's frame — the reading that island owns.

    A segment belongs to a module when **every** point of it is inside that
    module's frame. A segment that straddles the frame is neither dropped nor
    counted twice: it fails loud, because a cross-module wire would make "this
    island's length" mean nothing (this page states ``page_cross_module_wire_length
    == 0``, so in practice nothing straddles).
    """
    x0, y0, x1, y1 = _frame(page, module_id)
    total = 0.0
    for segment in page.plan.segments:
        inside = [x0 <= x <= x1 and y0 <= y <= y1 for x, y in segment.points]
        if all(inside):
            total += sum(
                abs(b[0] - a[0]) + abs(b[1] - a[1])
                for a, b in zip(segment.points, segment.points[1:])
            )
        elif any(inside):
            raise AssertionError(
                f"segment {segment.net} {segment.points} straddles the {module_id} "
                f"frame {(x0, y0, x1, y1)}: its length cannot be attributed to one "
                "island, so this reading would be a guess"
            )
    return total


def test_the_usb_c_island_is_no_longer_priced_by_the_ladder(page):
    """Four readings for the USB island — the one the bay pass is about.

    Measured on the four-island sheet: usb_c frame **394.5** wide (the staircase
    read 494.5; the two rejected perpendicular variants 324x398 and 990), CC2
    **130** (staircase 500, batch-3 360), usb_c's own wire **1995** (the
    staircase's 2860 was a page total).

    The width is not frozen as a number. The frame is the module's **own
    footprint** — its parts and their reference/value texts, R1's body at x 20.5
    to R3's right pin tip at x 365 — plus the flags anchored inside it (the GND
    flag on that pin reaches x 375) plus ``FRAME_PADDING`` on both sides, and the
    first assertion says exactly that. A plume that pushed a sibling out along
    the ladder would widen the frame past that footprint and fail; that is what
    the 494.5 reading is. ``< 460`` stays as a coarse backstop below 494.5 and
    far below 990.

    What the batch did add — the D+/D- local-label carriers on USB1.A6/B6/A7/B7
    and the CC1 orthogonal detour around C2 — changes this island's **length**
    (1995) and height, never its width: those runs stay inside the footprint
    horizontally, so the anti-plume reading does not price them.
    """
    x0, _, x1, _ = _frame(page, "usb_c")
    footprint = _parts_union_width(page, "usb_c")
    assert (x1 - x0) == pytest.approx(footprint + 2 * pc.FRAME_PADDING), (
        f"usb_c frame is {x1 - x0} wide but its own parts/texts/flags span {footprint} "
        f"(+2x{pc.FRAME_PADDING:g} padding): a wire or label box widened the "
        "island — the plume is back")
    assert x1 - x0 < 460.0, f"usb_c frame is {x1 - x0} wide — the plume is back"
    assert 100.0 < _net_length(page, "CC2") < 300.0, _net_length(page, "CC2")
    assert 1700.0 < _module_length(page, "usb_c") < 2100.0, _module_length(
        page, "usb_c"
    )
    # The four islands partition the page: 1995 + 290 + 365 + 110 = 2760. Summed
    # here so a segment that fell outside every frame cannot go quietly
    # unmeasured.
    modules = sum(
        _module_length(page, name)
        for name in ("usb_c", "ch343", "ch343_power", "hdr")
    )
    assert modules == pytest.approx(_total_length(page)), (
        f"island lengths sum to {modules} but the page wires total "
        f"{_total_length(page)}"
    )


def test_the_page_still_compiles_and_keeps_its_island_order(page):
    """Cheap insurance: the bay pass must not disturb what the flow decided."""
    result = _compile()
    assert not result.failures
    assert len(result.pages) >= 1
    # The sheet is four islands; the declared flow orders usb_c -> ch343 -> hdr
    # only, and `ch343_power` is the supply group the flow leaves unordered (its
    # position is the page's business). The reader's order is the page's own grid
    # — x-overlapping columns, top to bottom — the same reading the flow test
    # uses, not origin y (a stacked column is free to change that).
    modules = sorted(item.id for item in result.pages[0].modules)
    assert modules == ["ch343", "ch343_power", "hdr", "usb_c"], modules
    walked = [name for name in m534._order(result.pages[0])
              if name in ("usb_c", "ch343", "hdr")]
    assert walked == ["usb_c", "ch343", "hdr"], walked


def _binding(*constraints):
    return types.SimpleNamespace(
        constraints=tuple(
            RelativeConstraint(kind, subject, obj, kind)
            for kind, subject, obj in constraints
        )
    )


def test_a_group_the_grammar_ordered_keeps_the_staircase():
    """``_declared_among`` — the measured reason the ch340 crystal is excluded.

    ``adjacent(X1, C1)`` is the grammar stating the distance between two siblings;
    flattening that to one bay overrules the spec and the gate says so.
    """
    ctx = types.SimpleNamespace(binding=_binding(("adjacent", "X1", "C1")))
    assert dc._declared_among(ctx, ("X1", "C1")) is True


def test_a_relation_that_leaves_the_group_does_not_exclude_it():
    """The predicate asks "did the spec speak about *these two*", nothing wider."""
    ctx = types.SimpleNamespace(binding=_binding(("adjacent", "X1", "U1")))
    assert dc._declared_among(ctx, ("CC1", "CC2")) is False


def test_a_single_member_group_is_never_treated_as_ordered():
    """One member has no pair to be ordered, and the pass skips it upstream."""
    ctx = types.SimpleNamespace(binding=_binding(("adjacent", "X1", "C1")))
    assert dc._declared_among(ctx, ("X1",)) is False
