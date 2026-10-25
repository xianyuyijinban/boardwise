"""534 — a page states its margin once: the frame padding is not charged twice.

The defect, as the task book's evidence has it: three islands of
`blocklib/specs/ch343_uart` were refused on a 1170 x 825 sheet with

    "enlarge the page to at least 1205.5 x ..."

while the three module frames only spanned 1165.5 units — the stated need was
``2 x frame_padding`` (40) too wide, and it grew with the page (1300 -> 1338),
so no sheet size could satisfy the arithmetic.

Mechanism: :func:`boardwise.engines.pagecompiler._module_frame` grows every
module drawing by ``frame_padding`` (20) on each side, and the readability checker
measures the room between two modules *frame to frame* (40 = 2 x 20). The page
then also placed frames against ``page ∓ PAGE_MARGIN`` (20), charging that same
20 a second time against the sheet: one 40-unit band was subtracted twice, once
as padding and once as margin. The frames may reach into the margin by exactly
their own padding (the visible drawing then lands ``PAGE_MARGIN`` inside the
paper), so the frame inset is ``PAGE_MARGIN - frame_padding`` and the stated need
is ``frames + 2 x max(0, PAGE_MARGIN - frame_padding)``.

Evidence: `evidence/534/compile_probe/variant_d_three_modules.presentation.json`
and `evidence/534/compile_probe/*.svg` — this board is the task book's own test
project, newly designed for 534 (evidence-boards convention: no real project is
named or touched).
"""

from __future__ import annotations

import test_056_pagecompiler as m056

from boardwise.engines import pagecompiler as pc

#: The chain scene (056 sec.4's case 2) is the smallest three-module page here:
#: `pwr` / `rc` / `div`, each a handful of parts, one flow edge per pair.
WIDE = (0.0, 0.0, 1400.0, 900.0)


def _compile(circuit, presentation, page_box):
    return pc.compile_page(
        circuit,
        presentation,
        m056.library(),
        pc.PageCompileBudget(page_box=page_box),
    )


def _span(frames) -> tuple[float, float]:
    return (
        max(box[2] for box in frames) - min(box[0] for box in frames),
        max(box[3] for box in frames) - min(box[1] for box in frames),
    )


def test_three_modules_fill_a_sheet_a_grid_wider_than_their_frames():
    """The 534 arithmetic: the frames are the thing the sheet must hold.

    Measured on the chain scene: the three frames span 815 x 376.5 and their own
    left edge sits 2 units off the page corner, so the smallest sheet that holds
    them is 817 wide — one margin per side, not two. The second half of the test
    is what fails on the old reading: that sheet is 40 units too small for
    "frames + 2 x PAGE_MARGIN + 2 x frame_padding".
    """
    circuit, presentation = m056.chain_circuit(), m056.chain_spec()
    wide = _compile(circuit, presentation, WIDE)
    assert wide.ok, m056.render(wide)
    span_w, span_h = _span([item.frame for item in wide.pages[0].modules])

    grid = pc.PageCompileBudget().grid
    tight = _compile(
        circuit, presentation, (0.0, 0.0, span_w + 2 * grid, span_h + 2 * grid)
    )
    assert tight.ok, m056.render(tight)

    too_small = _compile(
        circuit, presentation, (0.0, 0.0, span_w - 2 * grid, span_h - 2 * grid)
    )
    assert not too_small.ok
    assert too_small.failures
    assert "enlarge the page to at least" in too_small.failures[0].action, (
        too_small.failures[0].render()
    )


def test_the_frame_inset_is_the_margin_less_the_padding_it_already_carries():
    """The constants the 38-unit gap was made of, pinned one at a time.

    ``PAGE_MARGIN`` (20, the drawing-to-paper clear space) and the default
    ``frame_padding`` (20, the frame's own clearance) are equal today, so a frame
    may reach the sheet edge exactly and the inner area *is* the sheet. A larger
    padding must not eat the margin the drawing is promised, and a smaller one
    must not push the frames in: the inset is the *shortfall*, floored at zero.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    budget = pc.PageCompileBudget(page_box=page)
    assert budget.frame_padding == pc.PAGE_MARGIN == 20.0
    assert pc._frame_inset(budget) == 0.0
    assert pc._page_inner(page, budget) == page

    tight_frames = pc.PageCompileBudget(page_box=page, frame_padding=10.0)
    assert pc._frame_inset(tight_frames) == 10.0
    assert pc._page_inner(page, tight_frames) == (10.0, 10.0, 1160.0, 815.0)

    wide_frames = pc.PageCompileBudget(page_box=page, frame_padding=30.0)
    assert pc._frame_inset(wide_frames) == 0.0
    assert pc._page_inner(page, wide_frames) == page
