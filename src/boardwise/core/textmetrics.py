"""The **render's** text ruler: how wide a string is where the host draws it.

Measured, not chosen. The host draws canvas text in Arial at
:data:`RENDER_TEXT_PX` px, the render's canvas unit comes out at
:data:`CANVAS_TEXT_UNITS`, and Arial's advances are the standard Helvetica ones
in :data:`TEXT_ADVANCE_EM` — so a string's width in canvas units is
``sum(em) x CANVAS_TEXT_UNITS``, which is what :func:`render_width` returns.

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

__all__ = [
    "CANVAS_TEXT_UNITS",
    "FLAG_NAME_ROW",
    "RENDER_TEXT_PX",
    "RENDER_TEXT_SCALE",
    "TEXT_ADVANCE_EM",
    "TEXT_ADVANCE_EM_FALLBACK",
    "TEXT_WIRE_PENETRATION",
    "WIRE_NAME_MODEL_EXCEPTION",
    "WIRE_NAME_ROW",
    "flag_name_box",
    "render_width",
    "wire_name_box",
]

#: The px size the render's canvas text is drawn at, and the canvas units one
#: text row occupies. Both measured on `test/P1`'s render (2026-10-04) and
#: re-checked on the 145e render (2026-10-10): the render declares
#: ``font-size:7.148342059336824px`` for every canvas text class, and one row is
#: 10 canvas units tall.
RENDER_TEXT_PX = 7.148342059336824
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
    """``text``'s advance in canvas units, as the render draws it."""
    em = sum(TEXT_ADVANCE_EM.get(ch, TEXT_ADVANCE_EM_FALLBACK) for ch in text)
    return em * CANVAS_TEXT_UNITS


#: The height of one row of a wire's net name as the host draws it. The same 10
#: canvas units every canvas text row occupies (measured 2026-10-10).
WIRE_NAME_ROW = CANVAS_TEXT_UNITS

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
#: median.
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
    """
    runs = _straight_runs(points)
    if not runs:
        return None
    a, b = max(
        runs,
        key=lambda run: math.hypot(run[1][0] - run[0][0], run[1][1] - run[0][1]),
    )
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    width = render_width(text)
    if abs(a[1] - b[1]) <= 1e-6:
        return (mid[0], mid[1], mid[0] + width, mid[1] + WIRE_NAME_ROW)
    return (mid[0], mid[1], mid[0] + WIRE_NAME_ROW, mid[1] + width)


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
