"""534 batch 3 — a distinct-pad sibling group staggers on its own reach.

The defect this test pins is the one batch 2 measured and batch 3 fixed. On the
shipped three-island board (`blocklib/specs/ch343_uart`) the USB-C island's
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

from boardwise.engines import drawcompiler as dc
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


def test_the_usb_c_island_is_no_longer_priced_by_the_ladder(page):
    """Three readings, each between the ladder and the stylus.

    494.5 -> 369 wide, CC2 500 -> 220, 2860 -> 2415 total. The thresholds are the
    ladder's own numbers with room to spare: a regression that put a sibling back
    on ``lane*index`` (or pushed it along the perpendicular, the 324x398 and 990
    readings of the two rejected variants) lands at or above them, and any layout
    that moves a sibling along its own escape direction stays well below.
    """
    x0, _, x1, _ = _frame(page, "usb_c")
    assert x1 - x0 < 380.0, f"usb_c frame is {x1 - x0} wide — the plume is back"
    assert 150.0 < _net_length(page, "CC2") < 300.0, _net_length(page, "CC2")
    assert 2000.0 < _total_length(page) < 2500.0, _total_length(page)


def test_the_page_still_compiles_and_keeps_its_island_order(page):
    """Cheap insurance: the bay pass must not disturb what the flow decided."""
    result = _compile()
    assert not result.failures
    assert len(result.pages) >= 1
    # The flow is written down as usb_c -> ch343 -> hdr and the page draws it down
    # the sheet (y up), so the reader's order is the islands' descending origin y.
    order = [item.id for item in sorted(result.pages[0].modules, key=lambda m: -m.origin[1])]
    assert order == ["usb_c", "ch343", "hdr"], order


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
