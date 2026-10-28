"""The **render's** text ruler: how wide a string is where the host draws it.

Measured, not chosen. The host draws canvas text in Arial at
:data:`RENDER_TEXT_PX` (the ``font-size`` the render declares for every canvas
text node), the render's SVG user unit is the canvas unit (measured below), and
Arial's advances are the standard Helvetica ones in :data:`TEXT_ADVANCE_EM` — so
a string's width in canvas units is ``sum(em) x RENDER_TEXT_PX``, which is what
:func:`render_width` returns.

**150 corrected this from ``CANVAS_TEXT_UNITS``.** The module multiplied the
advance table by the *row height* (10 canvas units — how far apart the host
stacks two rows) instead of the *em* (7.148342), which made **every** text box
1.39893x too wide. Measured on `test/P22`'s render (2026-10-11, `outputs/150/`):
ten value rows' #0000FF ink ends within 0.44 units of the ``sum(em) x 7.148342``
prediction and 7-22 units short of the ``x 10`` one, and the same holds on
`test/P1`'s 145e render. 岳 caught the cost on P22: the lint reported a
conductor "printed through" `EE16_3+3_V02` that actually runs 19.9 units to the
right of the glyphs (`outputs/150/t2_verdict.md`).

The SVG user unit is the canvas unit — measured, not assumed: the render draws
the editor's own wire `c5b7922e` (reported `(315,700)-(315,680)`) as ``M 315 -680
v 10``, and a least-squares fit of the PNG's pixels against 65 reported wire runs
comes out at the pure viewBox scaling within 0.02 units.

Two callers need the same ruler and they must not each keep a copy:

* `drawlint` — the acceptance reads the render's own text nodes and measures the
  boxes it finds against this table (`render_text_px`/`canvas_text_units` are
  re-exported from that module's namespace because its thresholds are written in
  terms of them);
* `drawcompiler` — a part's designator and value are drawn by the *host* at the
  symbol's own anchors, so the box the compiler reserves for them has to be the
  box the host paints (146). The compiler's own `GLYPH_ADVANCE` table is
  deliberately wider — it reserves room for text the compiler places itself —
  and using it for the host's rows refuses pages the host draws clean:
  measured on the flyback row, R7's `17.8k 1% TH` and R8's `4.7k 1% 0603` value
  rows measure 57.8 and 61.1 units here (2.2 units apart, no overlap) and 73 and
  78 units through `GLYPH_ADVANCE` (13 units of overlap), which refused the whole
  candidate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "CANVAS_TEXT_UNITS",
    "DESIGNATOR_GROWTH",
    "FLAG_NAME_ROW",
    "RENDER_TEXT_PX",
    "RENDER_TEXT_SCALE",
    "TEXT_ADVANCE_EM",
    "TEXT_ADVANCE_EM_FALLBACK",
    "TEXT_ROW_HEIGHT",
    "TEXT_WIRE_PENETRATION",
    "WIRE_NAME_AXIS_HORIZONTAL",
    "WIRE_NAME_AXIS_VERTICAL",
    "WIRE_NAME_MODEL_EXCEPTION",
    "WIRE_NAME_ROW",
    "WireNameRow",
    "flag_name_box",
    "host_row_box",
    "pin_rows",
    "render_width",
    "symbol_rows",
    "wire_name_box",
    "wire_name_middle_run",
    "wire_name_row",
]

#: The px size the render's canvas text is drawn at — the ``font-size`` every
#: canvas text class declares, and so the em in canvas units. Measured on
#: `test/P1`'s render (2026-10-04) and re-checked on the 145e render
#: (2026-10-10): the render declares ``font-size:7.148342059336824px`` for every
#: canvas text class.
RENDER_TEXT_PX = 7.148342059336824

#: The pitch of the host's text rows, in canvas units: how far apart it stacks a
#: symbol's designator and value rows, and the height one row's box is modelled
#: at. **It is not the em** — 150 measured that a row's glyphs are
#: :data:`RENDER_TEXT_PX` tall per em and that multiplying Arial's advances by
#: this number instead made every box 1.39893x too wide.
CANVAS_TEXT_UNITS = 10.0
RENDER_TEXT_SCALE = CANVAS_TEXT_UNITS / RENDER_TEXT_PX

#: Character advances of the render's canvas font, in em units. The render
#: declares ``font-family: Arial`` for every canvas text class, and these are the
#: standard Helvetica/Arial advance widths; anything not tabled falls back to
#: :data:`TEXT_ADVANCE_EM_FALLBACK` (wide on purpose — over-estimating a box
#: keeps room, under-estimating makes it overlap).
TEXT_ADVANCE_EM: dict[str, float] = {
    " ": 0.278, "!": 0.278, '"': 0.355, "#": 0.556, "$": 0.556, "%": 0.889,
    "&": 0.667, "'": 0.191, "(": 0.333, ")": 0.333, "*": 0.389, "+": 0.584,
    ",": 0.278, "-": 0.333, ".": 0.278, "/": 0.278,
    "0": 0.556, "1": 0.556, "2": 0.556, "3": 0.556, "4": 0.556, "5": 0.556,
    "6": 0.556, "7": 0.556, "8": 0.556, "9": 0.556,
    ":": 0.278, ";": 0.278, "<": 0.584, "=": 0.584, ">": 0.584, "?": 0.556,
    "@": 1.015,
    "A": 0.667, "B": 0.667, "C": 0.722, "D": 0.722, "E": 0.667, "F": 0.611,
    "G": 0.778, "H": 0.722, "I": 0.278, "J": 0.5, "K": 0.667, "L": 0.556,
    "M": 0.833, "N": 0.722, "O": 0.778, "P": 0.667, "Q": 0.778, "R": 0.722,
    "S": 0.667, "T": 0.611, "U": 0.722, "V": 0.667, "W": 0.944, "X": 0.667,
    "Y": 0.667, "Z": 0.611,
    "a": 0.556, "b": 0.556, "c": 0.5, "d": 0.556, "e": 0.556, "f": 0.278,
    "g": 0.556, "h": 0.556, "i": 0.222, "j": 0.222, "k": 0.5, "l": 0.222,
    "m": 0.833, "n": 0.556, "o": 0.556, "p": 0.556, "q": 0.556, "r": 0.333,
    "s": 0.5, "t": 0.278, "u": 0.556, "v": 0.5, "w": 0.722, "x": 0.5,
    "y": 0.5, "z": 0.5, "_": 0.556, "|": 0.26, "~": 0.581,
    "\u00b5": 0.556, "\u03bc": 0.556, "\u03a9": 0.833, "\u00b0": 0.4,
}

TEXT_ADVANCE_EM_FALLBACK = 0.9


def render_width(text: str) -> float:
    """``text``'s advance in canvas units, as the render draws it.

    ``sum(em) x RENDER_TEXT_PX`` — the advance table times the em the render
    itself declares. 150: it used to be ``x CANVAS_TEXT_UNITS`` (the row pitch,
    10), which made every box 1.39893x too wide and cost the lint its L1
    credibility on 岳's own page (`outputs/150/t2_verdict.md`).
    """
    em = sum(TEXT_ADVANCE_EM.get(ch, TEXT_ADVANCE_EM_FALLBACK) for ch in text)
    return em * RENDER_TEXT_PX


#: The height of one row of a wire's net name as the host draws it. The same 10
#: canvas units every canvas text row occupies (measured 2026-10-10).
WIRE_NAME_ROW = CANVAS_TEXT_UNITS

#: The height of a placed part's own text row, and the pitch the host stacks its
#: two rows on when it re-anchors them itself: one number, because the host draws
#: a row 10 units tall and a pair of rows 10 apart wherever the symbols do not
#: declare a pitch (531 measured six such pairs on a live landing —
#: `evidence/531/raw/anchor_landed_before.txt`).
TEXT_ROW_HEIGHT = CANVAS_TEXT_UNITS

#: How much wider a **designator row** is reserved than the spec id it was
#: compiled from. The host prints the designator the project's pool **allocated**,
#: not the spec's id: on the 530F/531 landings on `test`, spec `C5` printed as
#: `C11`, `R4` as `R19`, `T1` as `T3` — the pool picks the lowest free number in
#: the project (`addcomponent.allocate_designator`), and a spec's own number is
#: kept only when it is already free (121c). So a row reserved at
#: ``render_width("R4")`` is ~4 units short of the ``R19`` the page draws, which
#: is a real (if small) `text-overlap` in a tight row. The bound observed on both
#: landings is **one extra character**; a caller that has to be safe against the
#: pool adds it, and a caller that measures a box the plan already states does
#: not (the box the plan holds is the row for the text the plan knows).
DESIGNATOR_GROWTH = render_width("0")


def pin_rows(
    profile,
    origin: tuple[float, float],
    pose=None,
) -> list[tuple[str, str, tuple[float, float, float, float]]]:
    """``(kind, text, box)`` for every **pin name/number row** the host paints.

    The rows `readability._text_boxes` was blind to until 532: on the flyback's
    landing the render carried four collisions between a part's own pin text and
    its own value row (`U5`'s `ANODE` × `3`, the transformer's `2`/`5` ×
    `EE16_3+3_V02`), and the gate could not see any of them because none of its
    five kinds of text is a pin's own typography.

    The rule is the **measurement** in `SymbolProfile.pin_text_offsets`
    (`evidence/532/raw/pin_text_offsets.txt`, taken off 531's own landing): a pin's
    name and number are drawn at a fixed offset from **that pin's tip**, on the
    pin's own axis. Let ``sx`` be the sign of the posed tip along x — the direction
    the pin points — then the row's anchor is ``(tip.x - sx*|dx|, tip.y + dy)``,
    the **name** grows away from the tip and the **number** grows toward it. Both
    halves of that were measured, not chosen: on `SOT23-3-TL431` the name row's
    anchor sits 13.7 from the tip and the number's 9.5, and the two anchors' text
    runs in opposite directions (the SVG's own ``text-anchor`` is ``start`` for one
    and ``end`` for the other, per row).

    A symbol that declares no offsets returns nothing, and so does a pin whose tip
    does not lie on the x axis: `pin_text_offsets` was measured on horizontal pins
    only, and a vertical pin's rows are unmeasured rather than zero. **The pose is
    part of that reading (201H-a):** the offsets are stated on the page's x axis, so
    a pose that turns the pin onto the page's y axis (rotation 90/270 on a symbol
    with horizontal pins) is unmeasured too — returning nothing there is what keeps
    a phantom row out of the gate and out of `islandlayout._clear_text_rows`, which
    would otherwise hide a legible value for a collision nobody drew.
    """
    offsets = getattr(profile, "pin_text_offsets", None) or {}
    kinds_of = getattr(profile, "pin_text_kinds", None) or {}
    if not offsets or not kinds_of:
        return []
    from .geometry import transform_point

    rotation = 0.0 if pose is None else float(getattr(pose, "rotation", 0) or 0.0)
    mirror = False if pose is None else bool(getattr(pose, "mirror", False))
    out: list[tuple[str, str, tuple[float, float, float, float]]] = []
    for pin in profile.pins:
        wanted = kinds_of.get(str(pin.number))
        if not wanted:
            continue
        tip = transform_point(
            pin.tip[0], pin.tip[1], rotation=rotation, mirror=mirror,
            ox=origin[0], oy=origin[1],
        )
        # The axis the measurement is stated on: the pin's own, after the pose. The
        # direction is the one from the symbol's origin **out to the tip** — the way
        # the pin points — taken on its dominant axis in the symbol's own frame
        # first, so a mirrored part is read by the same rule as an upright one.
        if abs(pin.tip[0]) >= abs(pin.tip[1]):
            outward_local = (1.0 if pin.tip[0] > 0 else -1.0, 0.0)
        else:
            outward_local = (0.0, 1.0 if pin.tip[1] > 0 else -1.0)
        if outward_local[1] != 0.0:
            continue  # the pin is not on the x axis: its rows are unmeasured
        far = transform_point(
            pin.tip[0] + outward_local[0], pin.tip[1] + outward_local[1],
            rotation=rotation, mirror=mirror, ox=origin[0], oy=origin[1],
        )
        # 201H-a: the offsets are a **horizontal** measurement and the row's side
        # (`sx`) is a page-x sign, so the pose has to leave the pin on the page's x
        # axis. A pose that turns it onto the y axis was never measured, and the old
        # reading kept the offset on page x regardless: it put a row 11 units beside
        # a tip that points along y — where the host draws nothing — and the gate,
        # which reads these same boxes, reported a `pin-text-press` the symbol does
        # not have, which `_clear_text_rows` then paid for with a real hidden value.
        # An unmeasured row is not a horizontal one either, so this answers "no row
        # this model knows", the same way a missing table does.
        dx, dy = far[0] - tip[0], far[1] - tip[1]
        if abs(dx) <= abs(dy):
            continue
        sx = 1.0 if dx > 0 else -1.0
        for kind, key, text, grows_away in (
            ("pinName", "name", str(pin.name or ""), True),
            ("pinNumber", "number", str(pin.number or ""), False),
        ):
            if key not in wanted or not text:
                continue
            offset = offsets.get(key)
            if offset is None:
                continue
            width = render_width(text)
            left = tip[0] - sx * offset[0]
            if (grows_away and sx > 0) or (not grows_away and sx < 0):
                box = (left - width, tip[1] + offset[1],
                       left, tip[1] + offset[1] + TEXT_ROW_HEIGHT)
            else:
                box = (left, tip[1] + offset[1],
                       left + width, tip[1] + offset[1] + TEXT_ROW_HEIGHT)
            out.append((kind, text, box))
    return out


def host_row_box(anchor: tuple[float, float], text: str) -> tuple[float, float, float, float]:
    """The box the host draws one row of a placed part's text in.

    ``anchor`` is the row's **lower-left** corner and the width is the render's
    own ruler (:func:`render_width`); the measurement behind both is in
    :func:`symbol_rows`.
    """
    width = render_width(text)
    return (anchor[0], anchor[1], anchor[0] + width, anchor[1] + TEXT_ROW_HEIGHT)


def symbol_rows(
    profile,
    origin: tuple[float, float],
    *,
    reference: str = "",
    value: str = "",
    pose=None,
) -> list[tuple[str, str, tuple[float, float, float, float]]]:
    """``(kind, text, box)`` for every row the host paints for a placed part.

    **One home for "where a part's own text is drawn"**, because two models of it
    is what let the island path measure a page nobody sees: the single-module
    path read the symbols' declared anchors (146/147) while the island path
    invented a side for every row, and the invented boxes were 50+ units from
    where the host prints (`evidence/531/report.md` §2).

    The rule is the one `outputs/147/20_text_row_pose.txt` measured and the
    library's own notes restate: the anchor is the symbol's declared text item
    offset from the part's **origin in the page frame**, and the row is
    :func:`render_width` wide by :data:`TEXT_ROW_HEIGHT` tall, anchored at its
    lower-left corner.

    **531 measured the pose half of that rule, and it is not absent.** 147 read
    "the host does not turn the row with the pose" off one page; a fresh landing
    of the island page on `test` (`evidence/531/raw/anchor_landed_before.txt`, 60
    host text nodes) says upright rows match their declaration to the unit (11/11)
    while rotated ones do not: `C0603` at rot 90 draws at ``(+15,-5)``/``(+15,-15)``
    where the declaration says ``(-5,+10)``/``(-5,-20)``; `CAP-SMD-220UF` at rot 90
    mirrored at ``(-5,+15)`` where it says ``(+15, 0)``; `R0603` at rot 90 at
    ``(+7, 0)`` where it says ``(-10, +5)``. So a declaration may carry the pose it
    was measured in (`SymbolText.rotation`/`.mirror`), and this function prefers
    the entry for the **part's own pose** and falls back to the pose-independent
    one. Two parts of one symbol in one pose can still differ by a couple of units
    (`R0603` at rot 270: `R19` measured ``+10``, `R20` ``+8``), so a caller must
    treat these boxes as the host's *intent* rather than as a ruler — which is
    exactly why the router ranks them among the legibility keys and why a value
    that they say is pressed is hidden rather than moved (`_clear_text_rows`).

    A symbol that declares no anchors returns nothing: a box nobody can measure
    is not a zero-area one, and the caller keeps its own fallback. The same is
    true, row by row, of a table that states a pose and is asked for a different
    one (:func:`_pick_text`): the row was never measured there, so no row is
    returned and the caller's own side ladder stands.
    """
    declared = getattr(profile, "texts", ())
    rotation = None if pose is None else _pose_field(pose, "rotation")
    mirror = None if pose is None else _pose_field(pose, "mirror")
    chosen: dict[str, object] = {}
    for kind in ("reference", "value"):
        entry = _pick_text(declared, kind, rotation, mirror)
        if entry is not None and entry.x is not None and entry.y is not None:
            chosen[kind] = entry
    drawn_value = getattr(profile, "value_row", "") or value
    # Declaration order, so a plan's `texts` list keeps the order the library
    # states (reference above value in every profile written so far).
    out: list[tuple[str, str, tuple[float, float, float, float]]] = []
    for entry in declared:
        if chosen.get(entry.kind) is not entry:
            continue
        # The string the **host draws**, which is the one whose width the box has
        # to be: `SymbolProfile.value_row` states it where the host's device name
        # is not the spec's value (measured, 4 of the flyback's 19 rows).
        text = reference if entry.kind == "reference" else drawn_value
        if not text:
            continue
        out.append((
            entry.kind,
            text,
            host_row_box((origin[0] + entry.x, origin[1] + entry.y), text),
        ))
    return out


def _pose_field(pose, name: str):
    return getattr(pose, name, None)


def _pick_text(declared, kind: str, rotation, mirror):
    """The entry for this row: the part's own pose first, then "any pose".

    A pose-qualified entry wins only on an exact match, and the pose-independent
    entry is the **only** fallback: a symbol measured in one pose and drawn in
    another keeps the declaration 146/147 wrote, which is what every library
    without 531's measurements still has.

    A table that holds *only* pose-qualified entries answers nothing for a pose it
    does not state — it returns ``None`` and the caller keeps its own fallback.
    534 r1 measured `R0603-5.1k` and `C0805-10uF` at rotation 270 only
    (``"+10,0"``/``"+15,0"``, not the rigid turning of their upright ``-10,+5``),
    and a 270 row reused at 90/180 would be an invented measurement dressed as a
    measured one.  A caller that names **no** pose at all is the older call
    (``rotation``/``mirror`` both ``None``): there the symbol's own single stated
    row stays the answer, which is the pre-534 behaviour CH343G / TYPE-C / H1 are
    drawn with — those three state their pose and nothing else.
    """
    entries = [entry for entry in declared if entry.kind == kind]
    if rotation is not None or mirror is not None:
        for entry in entries:
            if (
                entry.rotation is not None
                and abs(float(entry.rotation) - float(rotation or 0.0)) < 1e-9
                and bool(entry.mirror) == bool(mirror)
            ):
                return entry
    for entry in entries:
        if entry.rotation is None and entry.mirror is None:
            return entry
    if rotation is None and mirror is None:
        return entries[0] if entries else None
    return None

#: The one wire whose measured anchor this model does not explain: on the 145e
#: render FB_SENSE's name sits at the wire's arc-length midpoint, 12.5 units from
#: the midpoint of its longest run, where the other 15 named wires of the plan all
#: land on the run. Named here so a reader of the model knows which case it is
#: not.
WIRE_NAME_MODEL_EXCEPTION = "FB_SENSE"

#: How deep a conductor has to run **through** a text row before it is a defect
#: and not an edge graze (147). One number, two callers: `drawlint`'s L1 (`text
#: printed through a conductor`) measures the landed page with it, and
#: `readability`'s `text-on-wire` constraint refuses a *plan* with it — a
#: drawing the compiler accepted must not become a page the lint rejects.
#:
#: The value is `drawlint`'s calibration, kept verbatim: on the 2026-10-04
#: snapshots the accepted pages' worst crossing is a 6.5-unit corner graze,
#: while the true text-through-wire defects measure 21-38 units with a 10-unit
#: median. 150 kept the number and changed what is measured against it from the
#: chord to :func:`box_penetration`.
TEXT_WIRE_PENETRATION = 10.0

#: The row a **rail flag's own name** occupies, measured on the landed page
#: (2026-10-10, `test/P1`, the two rail flags the flyback page draws — a ground
#: flag prints no name at all). See :func:`flag_name_box`.
FLAG_NAME_ROW = CANVAS_TEXT_UNITS


def flag_name_box(glyph, anchor, text: str, *, axis_up: bool):
    """The box the host draws a **rail flag's name** in — measured, not chosen.

    A power flag's name is not a ``LayoutText`` and not a wire's own name: the
    host prints it beside the flag's glyph, and it chooses where. Measured on the
    145e/146 render, the two rail flags of the flyback page (``outputs/147/
    FINDINGS.md`` sec.2):

    * ``HVDC`` at ``(160, 690)`` rot 0 — glyph ``(155, 695)-(165, 700)``, name row
      ``(145.8, 700)-(174.2, 710)``;
    * ``SEC_12V`` at ``(280, 740)`` rot 180 — glyph ``(275, 730)-(285, 735)``, name
      row ``(259, 720)-(301, 730)``.

    So the row is the :data:`FLAG_NAME_ROW`-thick band **immediately beyond the
    glyph**, on the far side from the connection, centred on the flag's axis and
    as wide as the name. ``axis_up`` says which of the two cases this flag is:
    whether the glyph hangs *above* the connection (rot 0, row above it) or below
    (rot 180, row below it). Both measured flags hang on the vertical axis; a flag
    on the horizontal axis is the same rule transposed, and 147 says so rather
    than pretending it measured one.

    ``glyph`` is the box :func:`~boardwise.core.symbolprofile.flag_glyph_box`
    returns (``None`` when the profile states no extent, in which case the row is
    ``None`` as well — a box nobody can measure is not a zero-area one).
    """
    if glyph is None:
        return None
    width = render_width(text)
    cx = anchor[0]
    if axis_up:
        return (cx - width / 2.0, glyph[3], cx + width / 2.0, glyph[3] + FLAG_NAME_ROW)
    return (cx - width / 2.0, glyph[1] - FLAG_NAME_ROW, cx + width / 2.0, glyph[1])


def wire_name_box(points, text: str) -> tuple[float, float, float, float] | None:
    """The box the host draws a named wire's name in — measured, not chosen.

    The host does **not** let the compiler place a wire's net name: it anchors
    the text where the conductor is, which is a fact about the geometry the
    compiler already wrote. Measured on the 145e render (2026-10-10, the post-apply
    `export.render` of `test/P1` with all 12 named wires):

    * the anchor is the midpoint of the wire's **longest straight run**, where
      the runs are the wire's own pieces with collinear touching pieces merged
      (the host splits a run at every pin it passes — CLAMP's 110-unit vertical is
      split at C5.1 and the name's midpoint is still the whole run's);
    * the row is **start-anchored**: it runs to the right of that point along a
      horizontal run and downward along a vertical one, so the glyphs are not
      centred on the wire — a name on a short wire overhangs its far end;
    * the row is :data:`WIRE_NAME_ROW` tall and :func:`render_width` wide.

    15 of the plan's 16 named wires agree with this to the unit; FB_SENSE is the
    exception (:data:`WIRE_NAME_MODEL_EXCEPTION`) and no reading says why. So this
    is the measured rule, not a bound: a caller that has to be *safe* cannot be.

    Returns ``None`` for a wire with no run.

    **534 r18: this is the box half of :func:`wire_name_row`.** The box alone
    cannot say which way the row runs — D+'s row is 9.336 wide by 10 tall on the
    horizontal and 10 wide by 9.336 tall on the vertical, a ratio of 1.07, so
    "taller than wide" is not a direction test (that test is how two rotated rows
    on the CH343 sheet were called horizontal). A caller that has to *decide*
    something reads :func:`wire_name_row`; this function keeps the shape every
    existing caller already handles.
    """
    row = wire_name_row(points, text)
    return None if row is None else row.box


#: The two directions a wire's name row can run. Carried explicitly, because a
#: box cannot carry it (see :func:`wire_name_box`).
WIRE_NAME_AXIS_HORIZONTAL = "h"
WIRE_NAME_AXIS_VERTICAL = "v"


@dataclass(frozen=True)
class WireNameRow:
    """A named wire's row **and the run it was measured on**.

    ``box`` is what :func:`wire_name_box` returns; ``axis`` is the fact that box
    was losing (``WIRE_NAME_AXIS_HORIZONTAL`` / ``WIRE_NAME_AXIS_VERTICAL``);
    ``run`` is the two endpoints the row was anchored on, so a caller can argue
    about the carrier's *shape* (``drawcompiler``'s candidate filter) without
    re-deriving the merge rule here.
    """

    box: tuple[float, float, float, float]
    axis: str
    run: tuple[tuple[float, float], tuple[float, float]]

    @property
    def horizontal(self) -> bool:
        """Is the row printed along a horizontal run (i.e. left to right)?"""
        return self.axis == WIRE_NAME_AXIS_HORIZONTAL


def wire_name_row(points, text: str) -> WireNameRow | None:
    """The row the host draws this wire's name in, with its **direction**.

    The measurement is :func:`wire_name_box`'s (145e/147): midpoint of the
    wire's longest straight run, start-anchored along that run. What is new is
    that the run's direction is returned instead of being flattened into a box,
    so a vertical row is visible to a caller that must refuse it.

    Which run the host chooses is established for **up to three runs** (the
    longest, 22 of the 24 named rows on the CH343 sheet) and is **not**
    established above that: two 5-run carriers landed their name on the *middle*
    run instead (`local-label-carrier` D+/D-, 534 r18). This function therefore
    reports the model's own answer and does not claim to know the host's choice;
    :func:`wire_name_middle_run` exists so a caller can veto a carrier on the
    second candidate rule as well, without pretending it is the prediction.
    """
    runs = _straight_runs(points)
    if not runs:
        return None
    a, b = _longest_run(runs)
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    width = render_width(text)
    if abs(a[1] - b[1]) <= 1e-6:
        return WireNameRow(
            box=(mid[0], mid[1], mid[0] + width, mid[1] + WIRE_NAME_ROW),
            axis=WIRE_NAME_AXIS_HORIZONTAL,
            run=(a, b),
        )
    return WireNameRow(
        box=(mid[0], mid[1], mid[0] + WIRE_NAME_ROW, mid[1] + width),
        axis=WIRE_NAME_AXIS_VERTICAL,
        run=(a, b),
    )


def wire_name_middle_run(
    points,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The **middle** run of an odd-length run table, or ``None``.

    A second, not a replacement: the CH343 sheet's two 5-run carriers printed
    their name on run 3 while the model names the longest run, and no reading
    says why (534 r18 — the selection rule above three runs is *not* measured,
    so nothing here may be used as the prediction). It is a **veto** for a caller
    choosing a carrier shape: if either the longest run or this one is vertical,
    the carrier can be named vertically and is not a candidate.

    ``None`` for an even table (no middle run), for fewer than three runs, and
    for a wire with no run.
    """
    runs = _straight_runs(points)
    if len(runs) < 3 or len(runs) % 2 == 0:
        return None
    return runs[len(runs) // 2]


def _longest_run(runs):
    """The run the model anchors a name on: the longest one (first on a tie)."""
    return max(
        runs,
        key=lambda run: math.hypot(run[1][0] - run[0][0], run[1][1] - run[0][1]),
    )


def _straight_runs(points) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """A path's segments with collinear, touching consecutive pieces merged."""
    runs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for a, b in zip(points, points[1:]):
        if runs:
            pa, pb = runs[-1]
            if _collinear(pa, pb, b) and math.dist(pb, a) <= 1e-6:
                runs[-1] = (pa, b)
                continue
        runs.append((a, b))
    return runs


def _collinear(a, b, c) -> bool:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= 1e-6
