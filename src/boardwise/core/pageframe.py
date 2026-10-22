"""Where the sheet's title block is — the keep-out S-01 is about.

`docs/schematic-style-spec.md` S-01 is a hard rule: 「标题栏是禁地，整图下方留白」
— content does not enter the title-block rectangle, and the drawing keeps ~15% of
the sheet height blank below it.  This module is the **first half of that
sentence**: it says, for a page and its declared sheet attributes, which
rectangle the title block occupies.  The second half (the blank band) is a
packing rule and lives in `islandlayout.PageBudget`.

**The block is the sheet symbol's own table, not a ratio.**  A page's frame is a
library *symbol* (嘉立创EDA专业版: 图纸符号) attached to the page; the title block
is a ``TABLE`` primitive inside that symbol, and the page's declared attributes
(``Width`` / ``Height`` / ``Border`` / ``Blade Width`` / ``Title Block`` /
``Title Block Position`` / the region counts) are attributes of the symbol.  Read
out of the golden fixtures — the same ``Drawing-Symbol_A4`` in
``ProPrj_ROBOT ctrl FOC`` (1655x1170) and ``ch340_golden`` (1170x825):

* ``TABLE.startX = 460, startY = -190``, ``colSizes`` summing to **700.0**,
  ``rowSizes`` summing to **180.0** — the block is 700 x 180, in canvas units;
* and the page's own copies of the symbol's attributes are *translated* with the
  page width and **not** with the page height: every field's x on the 1655-wide
  page is its x on the 1170-wide page **plus 485** (= 1655 - 1170), while every y
  is identical on the 825-tall and the 1170-tall page.  So the block is anchored
  to the **corner** and does not scale with the sheet: the two pages put it at
  ``(460, 10)-(1160, 190)`` and ``(945, 10)-(1645, 190)``.

That x-shift is the whole reason this is a model rather than a constant: a page
whose ``Width`` is not 1170 moves the block, and a keep-out that did not move
with it would leave the sheet's own title block outside the reserved area.

**The render agrees.**  ``evidence/521/521_page.svg`` (the editor's own
``export.render`` of the golden flyback page, 1170x825) draws that table at
``x 460..1160, y -190..-10`` screen = ``(460, 10)-(1160, 190)`` canvas — the same
numbers the file states, measured from the picture.  Both were checked in this
batch (``evidence/530g/probes/25_sheet_symbol.py`` and the SVG walk that reads
the ``table-*`` fill rects).

**The block is bigger than the legacy constant.**  `engines.layout.TITLE_BLOCK`
carves 320 x 100 at the bottom-right (``(W - 330, 10, W - 10, 110)``, task 006's
"标题栏禁区（右下 330×110）"); the real block is 700 x 180.  The legacy rectangle
is therefore a **subset** of the real one, which is why S-01 could not be kept by
the constant: on the flyback's own sheet the island page as packed before this
batch had 41 objects inside the *real* block (``evidence/530g/report.md``).  This
module states the real one; the legacy constant is left where it is, because
`engines.layout` is the shelf packer's own calibration and not this module's
caller.

**Positions.**  ``Title Block Position`` selects a corner.  Only **3 =
bottom-right** is measured (every page we have that is not ``Title Block = 0``
declares 3, and the render above shows a bottom-right block), and it is the only
value `TITLE_BLOCK_POSITION_MEASURED` holds; the other three corners are the
declared reading of the selector and are marked unmeasured.  An unknown or absent
value falls back to the measured corner — a keep-out that is stated and slightly
wrong costs layout space, and one that is skipped costs the rule.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .symbolprofile import Box

#: The block's own drawn size, in canvas units.  Sum of ``colSizes`` and of
#: ``rowSizes`` in the ``Drawing-Symbol_A4`` table — see the module docstring for
#: which two fixtures state it and which render draws it.
TITLE_BLOCK_SIZE: tuple[float, float] = (700.0, 180.0)

#: ``Blade Width`` as every fixture we have declares it — the frame inset, and so
#: the gap between the block and the sheet edge.  Used when a page does not state
#: one; a stated non-positive value is treated as "not stated" rather than as
#: "the block hangs off the sheet".
BLADE_WIDTH_DEFAULT: float = 10.0

#: ``Title Block Position`` -> ``(horizontal, vertical)`` corner.  The value is
#: read as a 2x2 grid (left, then right; top, then bottom within each column),
#: which is the one reading consistent with the measured value 3.
TITLE_BLOCK_POSITIONS: Mapping[str, tuple[str, str]] = {
    "1": ("left", "top"),
    "2": ("left", "bottom"),
    "3": ("right", "bottom"),
    "4": ("right", "top"),
}

#: The positions this repo has actually seen on a page.  A page's own render is
#: the evidence for 3 (module docstring); 1, 2 and 4 are declared, not measured,
#: and a future batch that can drive the editor should move them here one at a
#: time.
TITLE_BLOCK_POSITION_MEASURED: frozenset[str] = frozenset({"3"})

#: What ``Title Block Position`` falls back to when the page does not state a
#: usable value: the corner that was measured.
DEFAULT_TITLE_BLOCK_POSITION = "3"

#: ``Title Block`` -> the symbol's template selector, as far as this repo can
#: read it: every page that has a title block declares ``1``, and the one page
#: that declares ``0`` (级联多电平-主拓扑, 900x825) declares no block size at all.
#: That reading is **unverified** — nothing here has seen a page with ``0``
#: rendered — so it is only honoured by
#: :func:`title_block_from_sheet_attrs`, which is the reader that has the
#: attribute in front of it; a caller with no attributes (the compiler path)
#: always reserves the block, which is the safe direction to be wrong in.
NO_TITLE_BLOCK = "0"


def _as_float(value: Any) -> float | None:
    """``value`` as a float, or ``None`` when it is not a usable number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _corner(position: Any) -> tuple[str, str]:
    """``(horizontal, vertical)`` for a declared position, falling back to 3."""
    text = str(position).strip() if position is not None else ""
    return TITLE_BLOCK_POSITIONS.get(text, TITLE_BLOCK_POSITIONS[DEFAULT_TITLE_BLOCK_POSITION])


def title_block_box(
    page_box: Box,
    *,
    border: float = BLADE_WIDTH_DEFAULT,
    position: Any = DEFAULT_TITLE_BLOCK_POSITION,
) -> Box:
    """The title block's rectangle on ``page_box``, in the page's own coordinates.

    ``page_box`` is ``(x0, y0, x1, y1)`` in canvas units, y **up** (010c), exactly
    the box `drawcompiler.CompileBudget.page_box` and
    `islandlayout.PageBudget.page_box` take.  ``border`` is the frame inset
    (``Blade Width``); it is floored at 0 so a stated 0 puts the block flush with
    the corner instead of outside the sheet.

    The block keeps its own size (``TITLE_BLOCK_SIZE``) — it does not scale with
    the sheet — and is anchored to the corner ``position`` names, inset by
    ``border`` from both edges it touches.
    """
    width, height = TITLE_BLOCK_SIZE
    margin = _as_float(border)
    if margin is None or margin < 0:
        margin = BLADE_WIDTH_DEFAULT
    horizontal, vertical = _corner(position)
    if horizontal == "left":
        x0, x1 = page_box[0] + margin, page_box[0] + margin + width
    else:
        x0, x1 = page_box[2] - margin - width, page_box[2] - margin
    if vertical == "bottom":
        y0, y1 = page_box[1] + margin, page_box[1] + margin + height
    else:
        y0, y1 = page_box[3] - margin - height, page_box[3] - margin
    return (x0, y0, x1, y1)


def page_box_from_sheet_attrs(attrs: Mapping[str, Any]) -> Box | None:
    """The page's own box ``(0, 0, Width, Height)``, or ``None`` when unstated.

    A page's origin is its bottom-left corner in canvas units — the frame the
    island page packs in and the one `--page-box 0,0,W,H` states by hand — so a
    page reader that has the declared attributes has the box too. ``None`` means
    the page stated no usable ``Width``/``Height``; it never means A4.
    """
    width = _as_float(attrs.get("Width"))
    height = _as_float(attrs.get("Height"))
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return (0.0, 0.0, width, height)


def title_block_from_sheet_attrs(
    attrs: Mapping[str, Any],
    *,
    default_position: Any = DEFAULT_TITLE_BLOCK_POSITION,
) -> Box | None:
    """The title block's rectangle for a page's declared sheet attributes.

    ``attrs`` is what a page reader hands over — `parsers.schematic.PageLayout`'s
    ``sheet_attrs``, i.e. the ``Width``/``Height``/``Border``/``Blade Width``/
    ``Title Block``/``Title Block Position``/region-count strings straight out of
    the file.  The page box is then ``(0, 0, Width, Height)``: a page's own origin
    is its bottom-left corner in canvas units (the same frame the island page packs
    in), which is why the width is what moves the block and the height is not read
    by it at all.

    ``None`` means **"this page states no title block"**, and there is exactly one
    such case here: ``Title Block`` is :data:`NO_TITLE_BLOCK`, or the page states
    no usable ``Width``/``Height``.  The region counts (``X``/``Y Region Count``)
    are deliberately **not** read: they divide the frame into the zone ticks the
    editor draws, and the block's size and place are independent of them — the
    two measured pages declare 6x4 and put the same 700x180 block in the corner.
    """
    template = str(attrs.get("Title Block", "") or "").strip()
    if template == NO_TITLE_BLOCK:
        return None
    box = page_box_from_sheet_attrs(attrs)
    if box is None:
        return None
    border = _as_float(attrs.get("Blade Width"))
    position = attrs.get("Title Block Position")
    if position is None or not str(position).strip():
        position = default_position
    return title_block_box(box, border=border, position=position)


def title_block_keepouts(page_box: Box | None) -> tuple[Box, ...]:
    """The keep-out a compile states for a page it was handed, or ``()`` for none.

    This is the compiler's side of the module: the compile stages are handed a
    *page box* and nothing else (no attributes, no reader of the file), so the
    block is derived from the box with the measured defaults — the declared corner
    and the declared frame inset.  ``None`` (no page stated) means the drawing
    defines its own frame, and a drawing with no sheet has no sheet's title block
    to keep out of.
    """
    if page_box is None:
        return ()
    return (title_block_box(page_box),)


#: The prefix of the note a compile writes into the **plan** when it reserved a
#: sheet's title block.  A plan is a file that travels (054 §四.1) and the
#: landing stage is a different run, so the fact "this drawing was packed for
#: this sheet, with the block kept out" has to be written down — a landing that
#: could not read it could not tell a protected drawing from the 530F/532 one
#: that landed 32 primitives in the title block.
KEEP_OUT_NOTE_PREFIX = "S-01 plan keep-out:"

#: ``page box (x0, y0, x1, y1)`` and ``title block (...)`` as
#: :func:`keep_out_note` writes them.  Parsed back by
#: :func:`page_keep_out_from_notes`; both tuples are plain ``%g`` floats so the
#: text is readable in a plan and exact enough to compare with a live page.
_KEEP_OUT_PATTERN = re.compile(
    r"page box \(\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*\)"
    r"\s*,?\s*(?:title block|keep-out)\s*\(\s*"
    r"([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*\)"
)


def keep_out_note(page_box: Box, keepouts: Iterable[Box]) -> str:
    """The note a compile writes so a later landing can read what it reserved.

    One line, machine-readable on the way back in
    (:func:`page_keep_out_from_notes`), and it says **which page** as well as
    which rectangle: a plan packed for a 1170-wide sheet landed on a 1655-wide
    one must be refused, and the block on the two is not the same rectangle.
    """
    boxes = tuple(keepouts)
    if not boxes:
        return f"{KEEP_OUT_NOTE_PREFIX} nothing was reserved"
    rect = boxes[0]
    return (
        f"{KEEP_OUT_NOTE_PREFIX} page box ({page_box[0]:g}, {page_box[1]:g}, "
        f"{page_box[2]:g}, {page_box[3]:g}), title block ({rect[0]:g}, {rect[1]:g}, "
        f"{rect[2]:g}, {rect[3]:g}) — the sheet's own table (700x180, anchored to the "
        "declared corner) is a keep-out, so the packing and the gate both cleared it"
    )


def page_keep_out_from_notes(notes: Iterable[Any]) -> tuple[Box, Box] | None:
    """``(page_box, title_block)`` out of a plan's own notes, or ``None``.

    ``None`` is the answer for a plan that never reserved anything — the two
    drawings that landed in a title block (530F deviation 4, 532's page A) carry
    exactly this shape, and the landing stage reads it as a refusal rather than
    as an absence of news.
    """
    for note in notes:
        text = str(note)
        if not text.startswith(KEEP_OUT_NOTE_PREFIX):
            continue
        found = _KEEP_OUT_PATTERN.search(text)
        if found is None:
            continue
        values = tuple(float(item) for item in found.groups())
        return (
            (values[0], values[1], values[2], values[3]),
            (values[4], values[5], values[6], values[7]),
        )
    return None
