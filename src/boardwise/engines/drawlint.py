"""The draw lint readability checker (task 111 + 111a addendum): geometric
predicates over one live page's read-only snapshot.

110 (the flyback end-to-end) exposed the tool gap this closes: the defects a
human eye caught in re-review — a wire printed through the ``VCC`` label, a
value stacked on a part, a pin crossed mid-span — are all *purely geometric*,
so they can be judged by a machine gate instead of by the oracle's eye. This
module is that gate: it consumes one ``sch.geometry`` snapshot (plus the
editor's own render of the page for text geometry) and answers with findings
in the #55 vocabulary — ERROR / WARN / INFO, per predicate.

**Everything here is read-only, and everything is offline after the snapshot.**
The snapshot is captured through the bridge (``sch.geometry`` + the render the
same page already produces); the predicates run on the captured dict alone, so
a lint run can be replayed from a file with no daemon at all.

**The eleven predicates** (each maps to a defect class 110 actually showed;
L10 and L5b are the 111a addendum — 岳's editor DRC run, 2026-10-04):

=================================  ============================================  ======
predicate                          what it refuses                               level
=================================  ============================================  ======
``L1 text-on-wire``                a text box × a wire segment (own net's        ERROR
                                   attachment / same-net label excluded)
``L2 text-on-text``                two text boxes intersecting                   ERROR
``L3 text-on-part``                a text box × a *foreign* part's body          ERROR
``L4 wire-through-part``           a wire segment × a part body / foreign        ERROR
                                   pin (non-endpoint)
``L5 duplicate-annotation``        same-net flag + label, or two labels          ERROR
                                   closer than :data:`L5_DUPLICATE_NET_GAP`
``L6 wire-crossing``               wire × wire proper crossing, no junction      INFO/WARN
                                   (clustered per wire pair; ≥ :data:`L6_CLUSTER_WARN`
                                   crossings in a cluster, or more than
                                   :data:`L6_PAGE_WARN` clusters on the page, warn)
``L7 label-wire-clearance``        label/pin × foreign wire gap below            WARN
                                   :data:`L7_LABEL_WIRE_GAP`
``L8 flag-orientation``            a power/ground flag rotated off the vertical  ERROR
``L9 board-fill``                  the placed extent under-fills the sheet       INFO
``L10 out-of-bounds``              a part body, wire point, flag anchor or       ERROR
                                   text box beyond the sheet frame
                                   (:data:`L10_EDGE_EPS` inside the edge is legal)
``L5-wire-multiname``              one wire primitive carrying more than one     WARN
                                   same-net annotation — the host DRC reports
                                   导线有多个网络名 (the 110 named-stub shape)
=================================  ============================================  ======

**Text geometry is estimated, and says so.** The host exposes no text-extent
read (``sch_PrimitiveNetLabel`` is absent on this build — pit 9; ``sch.geometry``
reports ``netlabels: absent``), so each text box is estimated from the render's
text-node anchors with :func:`render_box` (the per-character advance table
``engines/drawcompiler.GLYPH_ADVANCE`` already in the repo, measured for the
same font family) unioned with its symbol's pin-name sidecar boxes, exactly the
estimate ``layout.annotation_box`` has always made for one net name. Every
finding carries ``estimate: true`` on its text geometry.

**Zero false positives outrank recall** (task 111's calibration discipline):
every threshold was measured on the accepted pages P22/P23/P24 first — the
predicate table below names the board evidence for each — and a predicate
whose evidence does not separate defect from noise stays INFO or off, never
"tuned until it fires".
"""

from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..core import textmetrics


#: The paint colours the editor's render uses for canvas text, measured on
#: the 3.2.186 renders of test/P1 and test/P22 (2026-10-04): symbols draw
#: their designator row in navy (#000080), their value row and pin names in
#: blue/blue-black (#0000FF / #000000), all under ``c_partid="part_attr"``;
#: page annotations (net labels, flag names) draw blue #0000FF with **no**
#: ``c_partid``. Sheet frame and title block draw #A00000 at 10px and in no
#: canvas class at all — both skipped. See ``_svg_text_nodes`` for the table.
FILL_DESIGNATOR = "#000080"
FILL_VALUE = "#0000FF"
FILL_PIN_NAME = "#000000"

#: Font size (SVG px) of the render's *pin* scale — the class the predicates
#: must not read as canvas text. The symbol draws each pin name/number one
#: per pin row inside the body, so two adjacent rows are 0-gap by
#: construction; the host also scales a symbol's designator/value row down
#: to this size when the text is wider than the row the symbol reserves
#: (measured 2026-10-04 on test/P22: U6/U1's designator rows). Both shapes
#: are body content.
RENDER_PIN_PX = 6.031413612565445

#: Font size (SVG units) of canvas text in the editor's render, the canvas-unit
#: character advance the glyph table is calibrated for, and the table itself.
#: **One ruler for the whole toolchain** since 146: the values live in
#: :mod:`boardwise.core.textmetrics`, because the *compiler* needs the same ruler
#: for the rows the host draws on a placed part (a symbol's own designator/value
#: anchors) — two copies would let the compiler reserve one box and the lint
#: measure another. Re-exported here because every threshold in this module is
#: written in terms of them.
RENDER_TEXT_PX = textmetrics.RENDER_TEXT_PX
CANVAS_TEXT_UNITS = textmetrics.CANVAS_TEXT_UNITS
RENDER_TEXT_SCALE = textmetrics.RENDER_TEXT_SCALE
TEXT_ADVANCE_EM = textmetrics.TEXT_ADVANCE_EM
TEXT_ADVANCE_EM_FALLBACK = textmetrics.TEXT_ADVANCE_EM_FALLBACK

#: The box every estimated text box is inflated by, canvas units, before any
#: intersection test: the estimate is an anchor + a width table, so half the
#: line height is already in :func:`render_box`; this is the slack that keeps
#: a threshold placed *at* the noise floor from reporting it (task 111: 零误报
#: 优先于检出率). Measured so every P22/P23/P24 clearance stays far outside.
TEXT_BOX_SLACK = 2.0

#: L1 — a wire must penetrate the text box deeper than this (chord length of
#: the segment's clip against the box, canvas units) to count as "printed
#: through the text". Calibrated on the 2026-10-04 snapshots: the accepted
#: pages' worst crossing is a 6.5-unit corner graze (P24's parallel stub
#: labels, whose glyph rows and neighbour conductors cannot be told apart at
#: estimate precision), while the pre-fix P1's true text-through-wire defects
#: measure 21–38 units with a 10-unit median — the threshold sits at that
#: median, 1.5× the accepted worst case.
L1_TEXT_WIRE_PENETRATION = 10.0

#: L2 — two text boxes overlapping by more than this much in **both**
#: dimensions report as stacked. Half a text row (5 of 10 canvas units) is
#: the estimate's own vertical noise: two rows drawn one row-step apart
#: overlap up to that in the estimate while the glyphs stay separate
#: (P24's parallel pin labels, 2026-10-04). The accepted pages' true minimum
#: gap between unrelated statements is 0.4 units *edge-to-edge* — no overlap
#: at all — so anything past half-a-row in both dimensions is the
#: HVDC/VDC-stacked-over-COMP shape, and anything less is estimate noise.
L2_TEXT_OVERLAP = 5.0

#: L5 — a flag and a label of the same net within this gap report as a
#: duplicate statement of one net, and two same-net labels closer than this
#: likewise — unless one is the flag's own name (the host draws it within
#: ~16 units of the flag anchor) or the labels share a carrier wire.
#: Measured on the accepted pages (P22's four GND flags + names, 2026-10-04).
L5_DUPLICATE_NET_GAP = 20.0

#: L5 — how far from its flag anchor the flag's own name may sit and still
#: count as that flag's statement (the glyph hangs 10..19 units out — pit 43's
#: measured flag geometry; the name rides the glyph).
L5_FLAG_OWN_NAME_GAP = 20.0

#: L7 — a label's anchor (glyph baseline) closer than this canvas units to a
#: *foreign* wire warns. The accepted pages' closest legal label-anchor to
#: foreign-wire distance measures ~7 units (P22/P23/P24 2026-10-04 — the
#: labels-between-parallel-runs shape keeps a full text row); set at half of
#: that so the warning only fires well inside the observed noise floor.
L7_LABEL_WIRE_GAP = 3.0

#: L8 — the rotations the host writes for a vertical power/ground flag. The
#: flag glyphs hang their bar on the connector's vertical (pit 43: the two
#: families face opposite ways at the *same* rotation, so the bar direction
#: is a per-family question, but "vertical" itself is these four angles —
#: any other rotation prints the flag's bar sideways).
FLAG_VERTICAL_ROTATIONS = frozenset({0, 90, 180, 270})

#: L9 — the sheet fill under which the page reports its layout distribution.
#: Measured on the accepted pages (2026-10-04): P22 11.7%, P23 8.1%,
#: P24 5.3% of the sheet area carries placed content, and the oracle accepted
#: all three as finished pages — so an under-fill *report* may only fire below
#: the lowest accepted reading. P1's pre-fix placement measured 39.4%.
L9_FILL_RATIO = 0.04

#: L6 — two crossing points of the *same unordered wire-primitive pair*
#: closer than this in both coordinates are one crossing site, not several:
#: the host reports a bent wire as one primitive whose multi-segment run
#: crosses the neighbour's multi-segment run repeatedly at one corner (the
#: pre-fix P1's SW × HVDC reported 8 times for one visual crossing —
#: measured 2026-10-04, the raw per-segment list is 44 rows that collapse
#: to 22 clusters at this gap on P1 while every accepted page keeps its
#: own clusters intact: P22 1, P23 1 (its two crossings 150,715/160,720
#: stay one cluster — the pair reading is what the eye wants), P24 2).
L6_CLUSTER_GAP = 20.0

#: L6 — a wire pair that crosses this many times inside one cluster warns
#: (was INFO): the same two conductors crossing ≥3 times is 岳's
#: 「不必要交叉」 — one wiggle of either wire ends it. Set above the accepted
#: pages' worst *visual* cluster: P24's XO × 孤立段 double-cross measures 2
#: crossings (accepted), and P24's second pair reads 4 raw crossings only
#: because both wires backtrack on themselves — 4 points span 6.4 units,
#: far under a text row, so the chain closes as one 4-point cluster and the
#: threshold cannot separate it from the XO double-cross by count alone.
#: The separating ruler is the cluster's **convex spread**: the accepted
#: double-crosses span 10.0 (P23) and 16.4 (P24 XO) units, the backtrack
#: artifact 6.4 — so the WARN needs count ≥3 *and* spread > 8.0 units
#: (between the artifact's 6.4 and the smallest accepted span of 10.0; all
#: measured on the 2026-10-04 snapshots).
L6_CLUSTER_WARN = 3

#: L6 — the spread floor (canvas units, max pairwise distance inside one
#: cluster) under which multiple crossings of one pair count as the same
#: backtrack artifact, not N distinct visual crossings. Measured 2026-10-04:
#: P24's backtrack cluster spans 6.4, the accepted XO double-cross 16.4,
#: P23's 10.0 — 8.0 sits between artifact and accepted reality.
L6_CLUSTER_SPREAD = 8.0

#: L6 — more distinct crossing clusters on one page than this upgrades the
#: crossings to a single page-level WARN. Accepted pages measure 1 (P22),
#: 1 (P23) and 2 (P24) clusters (2026-10-04); the pre-fix P1 measures 22 —
#: the threshold sits at the first value that separates them (any value in
#: 3..21 does; 3 is the tightest honest reading of that gap).
L6_PAGE_WARN = 3

#: L10 — an object this close to the sheet edge counts as touching it, not
#: leaving it (框碰到框边不算出界): the frame is a border, and R19's top
#: rides it without crossing (岳's evidence, 2026-10-04). The accepted
#: pages' closest object to any edge measures 35 units inside (P22's 3V3
#: text) — 0.5 is far below any real clearance the estimate could confuse.
L10_EDGE_EPS = 0.5

#: L1/L3/L4 — a segment whose only contact with a body is an endpoint that is
#: one of the body's own pins is that pin's connection, not a crossing
#: (pit 24/26: the host reports attachment by point-set membership). Any
#: endpoint within this distance of a pin counts as landing on it.
PIN_LANDING_EPS = 1.0

#: The render sidecar a lint run wants next to the snapshot: the text geometry
#: comes from the editor's own render of the same page, and the run that
#: captures the snapshot must record that render's provenance alongside.
RENDER_SIDECAR_SUFFIX = ".render.svg"


# ---------------------------------------------------------------- findings


@dataclass
class LintFinding:
    """One predicate hit: predicate, severity, location, and the story."""

    predicate: str
    severity: str  # "ERROR" | "WARN" | "INFO" — the #55 vocabulary
    message: str
    x: float = 0.0
    y: float = 0.0
    objects: tuple[str, ...] = ()
    estimate: bool = False

    def as_dict(self) -> dict:
        out = {
            "predicate": self.predicate,
            "severity": self.severity,
            "message": self.message,
            "x": self.x,
            "y": self.y,
        }
        if self.objects:
            out["objects"] = list(self.objects)
        if self.estimate:
            out["estimate"] = True
        return out


# ------------------------------------------------------- primitive geometry


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _line_points(state: dict) -> list[tuple[float, float]]:
    """The reported point list of one wire, as (x, y) pairs.

    The host reports a wire as a flat coordinate list (and merges touching
    runs into one primitive with repeated vertices — pit 24/26); pairs it as
    it reports, without inventing segments the list does not state.
    """
    raw = state.get("Line") or []
    flat = [_num(v) for v in raw]
    if not flat or any(v is None for v in flat):
        return []
    return list(zip(flat[0::2], flat[1::2]))


def _segments(points: Sequence[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Consecutive pairs of a point list — the **path** reading.

    Only :func:`_wire_segments` calls this, for the odd-length list the path
    reading is the only one available for; a wire's drawn segments come from
    ``Wire.segments`` (see that function for why the live host's even-length
    lists are pairs, not a path).
    """
    return list(zip(points, points[1:]))


def _wire_segments(state: dict) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The **drawn** segments of one reported wire (146).

    The render is the authority: a wire's segments are what the host's own
    exporter emits as ``<polyline>`` elements, and for `test/P1`'s 145e page
    those polylines are exactly the flat ``Line`` list taken **pairwise** —
    `(p0,p1)`, `(p2,p3)`, … — 24 wires out of 24, zero exceptions, and *no*
    wire matches the consecutive pairing. The host spells a two-segment wire
    ``[x1,y1, x2,y2, x3,y3, x4,y4]`` with the fourth vertex retracing the first
    (two runs meeting at a corner, not a path through it), so reading the list
    as a path invents a diagonal the page does not carry. CLAMP_B's
    ``[80,640, 80,680, 120,640, 80,640]`` is the measured case: the path reading
    adds a phantom `(80,680)-(120,640)` that runs through R3's value row, and 2
    of the 21 errors the 145e lint counted were exactly that phantom
    (`75k 1% 0603` and the page's SW-named wire were both reported through
    segments no polyline draws).

    A list with an **odd** number of points cannot be read pairwise, and the
    repo's own hand-written fixtures use that shape as a path
    (``[100,250, 100,300, 150,300]`` in `tests/test_057_page_offline.py`), so
    that reading is kept as the fallback rather than refused. Every wire the
    live host reported is even, and the pair reading is the one that matches
    the drawing (measured 2026-10-10 on `outputs/145e/render_P1.svg`).
    """
    raw = state.get("Line") or []
    flat = [_num(v) for v in raw]
    if not flat or any(v is None for v in flat):
        return []
    points = list(zip(flat[0::2], flat[1::2]))
    if len(points) % 2:
        return _segments(points)
    return [(points[i], points[i + 1]) for i in range(0, len(points) - 1, 2)]


def _pose(state: dict) -> tuple[float, float, float, bool]:
    """(x, y, rotation_degrees_ccw, mirrored) of one placed component."""
    return (
        _num(state.get("X")) or 0.0,
        _num(state.get("Y")) or 0.0,
        _num(state.get("Rotation")) or 0.0,
        bool(state.get("Mirror")),
    )


def _rotate(dx: float, dy: float, deg: float, mirror: bool) -> tuple[float, float]:
    """A part-local offset into page coordinates.

    Pit 11's coordinate contract: the file stores ``y = −canvas``, so a
    part-local *up* is a negative file dy; rotation is stored CCW in the
    file, and the mirror flips across the canvas's vertical axis **after**
    the rotation (pit 29: 先转后镜像).
    """
    rad = -deg  # file CCW over a y-down canvas reads as CW here
    cos, sin = _cos_sin(rad)
    x = dx * cos - dy * sin
    y = dx * sin + dy * cos
    if mirror:
        x = -x
    return x, y


def _cos_sin(deg: float) -> tuple[float, float]:
    import math

    rad = math.radians(deg)
    return math.cos(rad), math.sin(rad)


class Sheet:
    """One page, normalised from a ``sch.geometry`` snapshot.

    Everything the predicates need, read out once: the sheet frame, the part
    bodies (measured), the wires with their nets, the pins (offsets computed),
    the flags with their nets, and the text boxes (estimated from the render
    sidecar). A field the snapshot did not carry is an explicit ``None``, so a
    predicate can answer "unreadable" instead of inventing geometry.
    """

    def __init__(self, snapshot: dict, render_svg: str | None = None) -> None:
        self.snapshot = snapshot
        components = snapshot.get("components") or []
        self.parts: list[Part] = []
        self.flags: list[Flag] = []
        self.sheet_box: tuple[float, float, float, float] | None = None
        sheet_ids = set((snapshot.get("meta") or {}).get("sheets") or [])
        bboxes = snapshot.get("bboxes") or {}
        for entry in components:
            state = entry.get("state") or {}
            kind = str(state.get("ComponentType") or "")
            primitive = str(entry.get("primitiveId") or state.get("PrimitiveId") or "")
            if kind == "sheet" or primitive in sheet_ids:
                box = bboxes.get(primitive)
                if box:
                    self.sheet_box = (
                        _num(box.get("minX")) or 0.0,
                        _num(box.get("minY")) or 0.0,
                        _num(box.get("maxX")) or 0.0,
                        _num(box.get("maxY")) or 0.0,
                    )
                continue
            if kind == "part":
                self.parts.append(Part(primitive, state))
            elif kind == "netflag":
                self.flags.append(Flag(primitive, state))
        self.wires = [
            Wire(
                str(entry.get("primitiveId") or ""),
                (entry.get("state") or {}),
            )
            for entry in snapshot.get("wires") or []
            if isinstance(entry, dict)
        ]
        self.texts: list[TextBox] = []
        if render_svg:
            self.texts = text_boxes_from_render(render_svg, sheet=self)

    # -- derived access ---------------------------------------------------

    def part_at(self, primitive: str) -> "Part | None":
        for part in self.parts:
            if part.primitive == primitive:
                return part
        return None

    def flag_net_anchors(self) -> dict[str, list[tuple[float, float]]]:
        out: dict[str, list[tuple[float, float]]] = {}
        for flag in self.flags:
            out.setdefault(flag.net, []).append((flag.x, flag.y))
        return out

    def body_boxes(self) -> list[tuple[str, tuple[float, float, float, float]]]:
        return [
            (p.designator or p.primitive, p.page_body())
            for p in self.parts
            if p.page_body() is not None
        ]


@dataclass
class Part:
    """One placed part: origin, pose, measured body box, and its pins."""

    primitive: str
    state: dict
    designator: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    mirror: bool = False
    #: (min_x, min_y, max_x, max_y) in part-local coordinates — measured by
    #: the caller from a per-part bbox probe or a symbol profile. ``None``
    #: means the body extent is unknown and L3/L4 must say so.
    local_body: tuple[float, float, float, float] | None = None
    pins: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.x, self.y, self.rotation, self.mirror = _pose(self.state)
        self.designator = str(self.state.get("Designator") or "")

    def page_body(self) -> tuple[float, float, float, float] | None:
        if self.local_body is None:
            return None
        corners = [
            self.page_point(dx, dy)
            for dx in (self.local_body[0], self.local_body[2])
            for dy in (self.local_body[1], self.local_body[3])
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def page_point(self, dx: float, dy: float) -> tuple[float, float]:
        px, py = _rotate(dx, dy, self.rotation, self.mirror)
        return (self.x + px, self.y + py)


@dataclass
class Flag:
    """One power/ground flag: anchor, rotation, and the net it states."""

    primitive: str
    state: dict
    net: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0

    def __post_init__(self) -> None:
        self.x, self.y, self.rotation, _ = _pose(self.state)
        self.net = str(self.state.get("Net") or "")


@dataclass
class Wire:
    """One wire primitive: its reported points, its **drawn** segments, its net.

    ``points`` is the flat report read as pairs (the anchor grid every predicate
    and the tests use); ``segments`` is what the render actually draws, which is
    the pairwise reading for every wire the live host reports and the path
    reading only for an odd-length list — see :func:`_wire_segments`, and use it
    for anything that asks "does a conductor run through this"?.
    """

    primitive: str
    state: dict
    net: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        self.net = str(self.state.get("Net") or "")
        self.points = _line_points(self.state)
        self.segments = _wire_segments(self.state)


class TextBox:
    """One estimated text box, with the anchor and role it came from."""

    def __init__(
        self,
        text: str,
        box: tuple[float, float, float, float],
        *,
        kind: str,
        anchor: tuple[float, float],
        net: str = "",
        owner: str = "",
        estimate: bool = True,
    ) -> None:
        self.text = text
        self.box = box
        self.kind = kind  # "designator" | "value" | "label" | "pin-name"
        self.anchor = anchor
        self.net = net
        self.owner = owner
        self.estimate = estimate

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TextBox({self.text!r}, {self.box}, {self.kind})"


def text_width(text: str) -> float:
    """The canvas-unit advance of ``text`` at the render's canvas size.

    The ruler itself is :func:`boardwise.core.textmetrics.render_width` (one
    copy for the compiler and the lint alike, 146); this is the name every
    predicate in this module is written against.
    """
    return textmetrics.render_width(text)


def render_box(
    x: float, y: float, text: str, *, anchor: str = "start"
) -> tuple[float, float, float, float]:
    """The box canvas text occupies, from the render's anchor.

    The render draws annotation text at 7.148 SVG px where the compiler's
    advance table speaks 10-unit canvas text (:data:`RENDER_TEXT_SCALE`);
    box height is the text size, and the box starts at the anchor for
    ``start``-anchored nodes (the render's canvas text is uniformly
    start-anchored — measured 2026-10-04). The estimate is deliberately the
    *plain* box: :data:`TEXT_BOX_SLACK` is added only where a predicate
    wants its noise margin, so the threshold numbers below stay readable.

    The render's viewport is y-negated (SVG y-down over the canvas's y-up
    file coordinates — pit 11's ``y = −canvas``, one more place it shows):
    the reported anchor y is negated into canvas units, and the reported
    anchor is the text's **baseline** — the glyphs sit above it in the SVG
    viewport (smaller SVG y), which is *larger* canvas y after the flip.
    The box therefore spans ``canvas_y .. canvas_y + height`` — verified
    against C20 (test/P23): designator baseline at canvas 720, glyphs
    720..730 above the symbol's body; value baseline at 710, glyphs
    710..720 below the body (2026-10-04).
    """
    width = text_width(text)
    height = CANVAS_TEXT_UNITS
    if anchor == "middle":
        x0 = x - width / 2
    else:
        x0 = x
    canvas_y = -y
    return (x0, canvas_y, x0 + width, canvas_y + height)


def _svg_text_nodes(svg: str) -> list[tuple[float, float, str, str, str]]:
    """``(x, y, text, role, anchor)`` of the canvas text nodes in one render.

    Only the four measured classes read (measured 2026-10-04 on test/P22 and
    test/P1):

    - ``fill:#A00000`` at 10px — sheet frame (zone digits/letters); skipped.
    - inside a ``c_partid="part_pin"`` group (``c_partid="part_attr"``,
      ``fill:#000000``/``#0000FF``, one row per pin) — the symbol's pin-name
      and pin-number rows: body content, not free text; skipped.
    - ``c_partid="part_attr"`` + ``fill:#000080`` — the symbol's designator
      row; ``c_partid="part_attr"`` + ``fill:#0000FF`` — the symbol's value
      row. The symbol's own rows (099c's own-text rule).
    - no ``c_partid`` + ``fill:#0000FF`` — a **page annotation**: a wire's
      net label or a flag's net name, the free text the predicates judge.
    - no style class at all — title block / sheet zones; skipped.
    """
    out: list[tuple[float, float, str, str, str]] = []
    pattern = re.compile(
        r"<text ([^>]*?)style=\"([^\"]*)\"([^>]*?)>(.*?)</text>",
        re.S,
    )
    for match in pattern.finditer(svg):
        style = match.group(2)
        whole = match.group(0)
        fill_match = re.search(r"fill:(#\w+)", style)
        fill = fill_match.group(1).upper() if fill_match else ""
        part_attr = 'c_partid="part_attr"' in whole
        in_pin = 'c_partid="part_pin"' in whole
        size_match = re.search(r"font-size:\s*([\d.]+)px", style)
        size = float(size_match.group(1)) if size_match else 0.0
        if part_attr:
            # The host scales a symbol row down (6.03 px vs the 7.15 px row
            # size) when the text is wider than the row the symbol reserves;
            # the shrunken row keeps the row colour but draws at the *pin*
            # scale, and two shrunken rows of neighbouring pins are 0-gap by
            # construction — body content, not free text (measured 2026-10-04
            # on P22: U6/U1 render at 6.03 px). Treat any part_attr row at
            # the pin size as body content.
            if in_pin or (
                size_match and abs(size - RENDER_PIN_PX) < 0.5
            ):
                continue  # the symbol's pin rows and shrunken rows are body content
            if fill == FILL_DESIGNATOR:
                role = "designator"
            elif fill == FILL_VALUE:
                role = "value"
            else:
                continue  # pin-name black rows outside a pin group stay out
        else:
            if fill == FILL_VALUE:
                role = "annotation"
            else:
                continue
        anchor_match = re.search(r"text-anchor=\"(\w+)\"", whole)
        anchor = anchor_match.group(1) if anchor_match else "start"
        tspan = re.search(r"<tspan[^>]*>(.*?)</tspan>", match.group(4), re.S)
        content = tspan.group(1) if tspan else match.group(4)
        content = re.sub(r"<[^>]+>", "", content).strip()
        if not content:
            continue
        x_match = re.search(r"[\"\s]x=\"([-\d.eE]+)\"", whole)
        y_match = re.search(r"[\"\s]y=\"([-\d.eE]+)\"", whole)
        if not (x_match and y_match):
            continue
        out.append(
            (float(x_match.group(1)), float(y_match.group(1)), content, role, anchor)
        )
    return out


def text_boxes_from_render(svg: str, sheet: "Sheet | None" = None) -> list[TextBox]:
    """Every canvas text node of one render, as estimated boxes.

    The roles come from the render's own classes (see ``_svg_text_nodes``):
    an annotation is a page statement (a net label, a flag name), a
    designator/value is a symbol's own row. L3 exempts a part's own
    designator/value from its body by that role plus geometry; L1 keeps the
    strict reading for every box the render cannot classify.

    When the page's wires are available (``sheet``), every annotation whose
    anchor sits on a wire's reported point (or whose box contains the
    conductor's endpoint) takes that wire's net — the host draws a net name
    at the conductor it names (pit 9: the wire carries the name), and this is
    what lets L1 exempt a label from its own wire, L5 see which labels state
    which net, and L2 tell one statement from two.
    """
    boxes: list[TextBox] = []
    for x, y, content, role, anchor in _svg_text_nodes(svg):
        boxes.append(
            TextBox(
                content,
                render_box(x, y, content, anchor=anchor),
                kind=role,
                # anchor in canvas coordinates (the render reports SVG y, pit 11's flip)
                anchor=(x, -y),
                estimate=True,
            )
        )
    _rotate_vertical_boxes(boxes, svg)
    if sheet is not None:
        _assign_annotation_nets(boxes, sheet)
    return boxes


def _rotate_vertical_boxes(boxes: list[TextBox], svg: str) -> None:
    """Re-estimate the boxes of rotated (vertical) text nodes.

    Vertical net labels run along their conductor (a rail's name reads along
    the rail); the box is the text's own box pivoted onto the anchor, grown
    along +y. The rotation sign is the render's (SVG y-down), and a −90°
    node's text runs from the anchor downward in canvas terms — reading
    bottom-up on the page, which is how the host draws every vertical
    annotation measured (2026-10-04).
    """
    pattern = re.compile(
        r"<text ([^>]*?)style=\"([^\"]*)\"([^>]*?)>(.*?)</text>",
        re.S,
    )
    vertical: dict[tuple[float, float, str], str] = {}
    for match in pattern.finditer(svg):
        whole = match.group(0)
        rot = re.search(r'transform="rotate\((-?[\d.]+)', whole)
        if not rot or abs(float(rot.group(1))) % 360 == 0:
            continue
        tspan = re.search(r"<tspan[^>]*>(.*?)</tspan>", match.group(4), re.S)
        content = tspan.group(1) if tspan else match.group(4)
        content = re.sub(r"<[^>]+>", "", content).strip()
        x_match = re.search(r'[\"\s]x="([-\d.eE]+)"', whole)
        y_match = re.search(r'[\"\s]y="([-\d.eE]+)"', whole)
        if content and x_match and y_match:
            vertical[(float(x_match.group(1)), float(y_match.group(1)), content)] = (
                rot.group(1)
            )
    for box in boxes:
        key = (box.anchor[0], -box.anchor[1], box.text)
        angle = vertical.get(key) or vertical.get(
            (box.anchor[0], box.anchor[1], box.text)
        )
        if angle is None:
            continue
        width = text_width(box.text)
        x0 = box.box[0]
        y0 = box.box[1]
        box.box = (x0, y0, x0 + CANVAS_TEXT_UNITS, y0 + width)


def _assign_annotation_nets(boxes: list[TextBox], sheet: "Sheet") -> None:
    """Give each annotation the net of the wire it sits on.

    The anchor test is the box, not the anchor point: the host centres a
    flag's name on the flag anchor and clamps a wire label's box beside the
    conductor, so the anchor itself can sit a row off the reported point.
    A wire is this box's carrier when one of its reported points falls in
    the (slack-inflated) box **or** one of its spans touches the box at all
    (a label sitting on its own rail touches only the border — P22's 5V0,
    measured 2026-10-04).

    When several nets contact one box — a label sitting between two parallel
    conductors a row apart (P24's CH340G stub labels, measured 2026-10-04) —
    the winner is the contact whose conductor runs **through the label's own
    anchor**: distance from the anchor to the wire's nearest span, 0 for the
    naming wire and ~10 for the neighbours. Only a unique zero-distance (or
    an unambiguous single net) assigns; everything else leaves the box strict
    (net ``''``).
    """
    for box in boxes:
        if box.kind != "annotation":
            continue
        nets: set[str] = set()
        for wire in sheet.wires:
            if not wire.net:
                continue
            inflated = _inflate(box.box, TEXT_BOX_SLACK)
            on_point = any(
                inflated[0] <= p[0] <= inflated[2] and inflated[1] <= p[1] <= inflated[3]
                for p in wire.points
            )
            on_span = any(
                _segment_touches_box(a, b, box.box)
                for a, b in wire.segments
            )
            if on_point or on_span:
                nets.add(wire.net)
        if len(nets) == 1:
            box.net = next(iter(nets))
            continue
        if len(nets) > 1:
            anchored = [
                (
                    min(
                        _point_segment_distance(box.anchor, a, b)
                        for a, b in wire.segments
                    ),
                    wire.net,
                )
                for wire in sheet.wires
                if wire.net in nets
            ]
            anchored.sort()
            if anchored and anchored[0][0] <= 0.0 and (
                len(anchored) == 1 or anchored[1][0] > 0.0
            ):
                box.net = anchored[0][1]


# --------------------------------------------------------------- primitives


def _box_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _box_gap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """Cheapest distance between two boxes; 0 when they touch or overlap."""
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    import math

    return math.hypot(dx, dy)


def _inflate(
    box: tuple[float, float, float, float], by: float
) -> tuple[float, float, float, float]:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def _segment_intersection(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> tuple[float, float] | None:
    """The single crossing point of two segments, if they properly cross.

    Shared endpoints, T-splices (an endpoint of one on the span of the other)
    and collinear overlap all return ``None`` — they are how connected wiring
    reads, not how a crossing reads (074's ruler).
    """
    (x1, y1), (x2, y2) = a1, a2
    (x3, y3), (x4, y4) = b1, b2
    denom = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(denom) < 1e-12:
        return None  # parallel or collinear — not a point crossing
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denom
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denom
    if not (0.0 < t < 1.0 and 0.0 < u < 1.0):
        return None
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _point_segment_distance(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    import math

    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# ---------------------------------------------------------------- predicates


def _own_net_text_exemption(
    box: TextBox, wire: Wire, sheet: Sheet
) -> bool:
    """L1's exemption: the text belongs to this wire's own net.

    True when the text's net was established (by ``_assign_annotation_nets``
    from the page's own carriers) and names this wire's net, and the wire
    actually contacts the box (point in the slack-inflated extent, or span
    touching the box — a label sitting on its own rail touches only the
    border). A label of net N is the name of *every* conductor of N, so no
    segment of N can "cross" it. Labels whose net stayed ambiguous, and nets
    with no wire carrier, never take the exemption.
    """
    if not wire.net or not box.net or wire.net != box.net:
        return False
    inflated = _inflate(box.box, TEXT_BOX_SLACK)
    if any(
        inflated[0] <= p[0] <= inflated[2] and inflated[1] <= p[1] <= inflated[3]
        for p in wire.points
    ):
        return True
    return any(
        _segment_touches_box(a, b, box.box) for a, b in wire.segments
    )


def check_text_on_wire(sheet: Sheet) -> list[LintFinding]:
    """L1: any text box a wire segment runs through (own-net stubs exempt).

    The crossing must penetrate the box at least
    :data:`L1_TEXT_WIRE_PENETRATION` units — an edge graze at estimate
    precision is noise, a conductor running through the glyphs is the
    ST-through-"VCC" defect class.
    """
    out: list[LintFinding] = []
    for box in sheet.texts:
        for wire in sheet.wires:
            if _own_net_text_exemption(box, wire, sheet):
                continue
            for a, b in wire.segments:
                if not _segment_crosses_box(a, b, box.box):
                    continue
                chord = _segment_box_chord(a, b, box.box)
                if chord < L1_TEXT_WIRE_PENETRATION:
                    continue
                out.append(
                    LintFinding(
                        "L1-text-on-wire",
                        "ERROR",
                        f"{box.text!r} at ({box.box[0]:.0f},{box.box[1]:.0f}) "
                        f"is crossed by wire {wire.primitive[:8]} "
                        f"(net {wire.net or 'unnamed'}) for {chord:.0f} units "
                        "— text printed through a conductor reads as the "
                        "other net",
                        x=(box.box[0] + box.box[2]) / 2,
                        y=(box.box[1] + box.box[3]) / 2,
                        objects=(box.text, wire.primitive),
                        estimate=box.estimate,
                    )
                )
                break
    return out


def _segment_box_chord(
    a: tuple[float, float],
    b: tuple[float, float],
    box: tuple[float, float, float, float],
) -> float:
    """The length of segment a–b inside the box (0 when it does not enter)."""
    import math

    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in (
        (-dx, a[0] - box[0]),
        (dx, box[2] - a[0]),
        (-dy, a[1] - box[1]),
        (dy, box[3] - a[1]),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return 0.0
        else:
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
    if t1 <= t0:
        return 0.0
    return (t1 - t0) * math.hypot(dx, dy)


def _segment_crosses_box(
    a: tuple[float, float],
    b: tuple[float, float],
    box: tuple[float, float, float, float],
) -> bool:
    """True when segment a–b enters the box's **interior**.

    A segment running along the border, or touching a single corner, is a
    conductor drawn flush against a text row — tight, but readable, and it is
    how the host draws a wire that stops at a label's row (P23 2026-10-04:
    two accepted wires each graze one box edge). Only a segment that actually
    crosses into the inside reports.
    """
    if _point_in_box(a, box) or _point_in_box(b, box):
        return True
    corners = [
        (box[0], box[1]),
        (box[2], box[1]),
        (box[2], box[3]),
        (box[0], box[3]),
    ]
    for i in range(4):
        if _segment_intersection(a, b, corners[i], corners[(i + 1) % 4]):
            return True
    return False


def _segment_touches_box(
    a: tuple[float, float],
    b: tuple[float, float],
    box: tuple[float, float, float, float],
) -> bool:
    """True when segment a–b contacts the box at all — interior, border, or
    running along one side.

    The contact test (unlike the interior test L1 refuses on) is for *whose
    name is this*: a wire running along its own label's row is the conductor
    the label names, so collinear border contact counts.
    """
    if (
        box[0] <= a[0] <= box[2] and box[1] <= a[1] <= box[3]
    ) or (
        box[0] <= b[0] <= box[2] and box[1] <= b[1] <= box[3]
    ):
        return True
    corners = [
        (box[0], box[1]),
        (box[2], box[1]),
        (box[2], box[3]),
        (box[0], box[3]),
    ]
    for i in range(4):
        if _segment_intersection(a, b, corners[i], corners[(i + 1) % 4]):
            return True
        # collinear overlap with one side
        side = corners[i], corners[(i + 1) % 4]
        if _collinear_overlap(a, b, side[0], side[1]):
            return True
    return False


def _collinear_overlap(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> bool:
    """True when two segments lie **on the same line** and share more than a point.

    The cross-product zero test accepts any parallel pair, so the segments'
    own endpoints must also sit on the other's line before the interval
    overlap is believed.
    """
    (x1, y1), (x2, y2) = a1, a2
    (x3, y3), (x4, y4) = b1, b2
    cross = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(cross) > 1e-9:
        return False
    # parallel: coincidence means a point of one line satisfies the other's
    if abs((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) > 1e-9:
        return False
    # collinear: project onto the dominant axis and test interval overlap
    if abs(x2 - x1) >= abs(y2 - y1):
        lo1, hi1 = sorted((x1, x2))
        lo2, hi2 = sorted((x3, x4))
    else:
        lo1, hi1 = sorted((y1, y2))
        lo2, hi2 = sorted((y3, y4))
    return lo1 < hi2 and lo2 < hi1


def _point_in_box(
    point: tuple[float, float], box: tuple[float, float, float, float]
) -> bool:
    """Strictly inside (border excluded — see ``_segment_crosses_box``)."""
    return box[0] < point[0] < box[2] and box[1] < point[1] < box[3]


def check_text_on_text(sheet: Sheet) -> list[LintFinding]:
    """L2: two text boxes overlapping past the estimate's own noise.

    A designator/value pair (one symbol's stacked identity rows) and a wire
    label × flag name of the same net are one statement and exempt; two
    texts of *different* statements crowding — the HVDC/VDC-stacked-over-COMP
    shape — is what this refuses.
    """
    out: list[LintFinding] = []
    boxes = sheet.texts
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if _one_statement_rows(a, b) or _one_statement_rows(b, a):
                continue
            if _same_net_statement(a, b):
                continue
            overlap_x = min(a.box[2], b.box[2]) - max(a.box[0], b.box[0])
            overlap_y = min(a.box[3], b.box[3]) - max(a.box[1], b.box[1])
            if overlap_x > L2_TEXT_OVERLAP and overlap_y > L2_TEXT_OVERLAP:
                gap = _box_gap(a.box, b.box)
                out.append(
                    LintFinding(
                        "L2-text-on-text",
                        "ERROR",
                        f"{a.text!r} and {b.text!r} boxes overlap "
                        f"{overlap_x:.1f}×{overlap_y:.1f} units "
                        f"(threshold {L2_TEXT_OVERLAP:g}×{L2_TEXT_OVERLAP:g}, "
                        f"edge gap {gap:.1f}) — stacked text hides one of "
                        "the two",
                        x=(a.box[0] + a.box[2]) / 2,
                        y=(a.box[1] + a.box[3]) / 2,
                        objects=(a.text, b.text),
                        estimate=True,
                    )
                )
    return out


def _same_net_statement(a: TextBox, b: TextBox) -> bool:
    """True when both texts state the same net at the same conductor.

    Two TAP names on the two ends of one wire (P22's divider readback) are
    one statement drawn once per reader direction, not two competing labels —
    the page-statement question is L5's, not L2's. Requires both to be
    annotations of one net with boxes that actually intersect.
    """
    return (
        a.kind == "annotation"
        and b.kind == "annotation"
        and bool(a.net)
        and a.net == b.net
        and _box_overlap(a.box, b.box)
    )


def _one_statement_rows(a: TextBox, b: TextBox) -> bool:
    """True when a and b are the stacked rows of one statement, not two texts.

    The host draws a symbol's value row directly **below** its designator row
    (same anchor column, one row step apart), and a flag's net name directly
    at its glyph anchor — both with zero clearance by construction (measured
    2026-10-04 on P22/P23/P24 and P1: every legal designator/value pair is
    column-stacked rows; a column-aligned stacked pair is one statement's
    identity rows, not a collision). Two annotations of different nets, or a
    value printed over a foreign value at the same height, keep the strict
    rule.
    """
    if a.kind == b.kind and "annotation" not in (a.kind, b.kind):
        return False
    return _column_stacked(a.box, b.box)


def _column_stacked(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """One row directly above/below the other, anchor-aligned in a column.

    Horizontal alignment means the narrower box's span sits inside the wider
    box's span widened by the estimate's slack — a designator ``C20`` over
    the value ``100nF`` aligns; two same-height boxes do not. The vertical
    test is the same row-step adjacency: one box's top meets the other's
    bottom within the slack, so two rows of one symbol (and a wire's name
    drawn at its own conductor) pair up, while two texts side by side on one
    line never do.
    """
    x_overlap = min(a[2], b[2]) - max(a[0], b[0])
    if x_overlap <= 0:
        return False
    wider = a if (a[2] - a[0]) >= (b[2] - b[0]) else b
    narrower = b if wider is a else a
    aligned = (
        narrower[0] >= wider[0] - TEXT_BOX_SLACK
        and narrower[2] <= wider[2] + TEXT_BOX_SLACK
    )
    if not aligned:
        return False
    rows_adjacent = (
        abs(a[1] - b[3]) <= TEXT_BOX_SLACK or abs(b[1] - a[3]) <= TEXT_BOX_SLACK
    )
    return rows_adjacent


def check_text_on_part(sheet: Sheet) -> list[LintFinding]:
    """L3: a text box on a *foreign* part's measured body.

    The body extent comes from the per-part bbox probes (`sch.geometry` with
    ``bboxIds`` — the only measured body read this host gives); when the run
    could not measure a part's body, that part contributes no box and this
    predicate answers "unreadable" for it rather than guessing. Because the
    render does not say *which* part a symbol row belongs to, a
    designator/value row is exempt from every body it sits on **only** when
    it is inside exactly one body (its own); a row that sits over two bodies
    is foreign to at least one of them and reports.
    """
    out: list[LintFinding] = []
    bodies = sheet.body_boxes()
    for box in sheet.texts:
        if box.kind in ("designator", "value"):
            containing = [name for name, body in bodies if _box_overlap(box.box, body)]
            if len(containing) <= 1:
                continue
            foreign = [n for n in containing]
            out.append(
                LintFinding(
                    "L3-text-on-part",
                    "ERROR",
                    f"{box.text!r} at ({box.box[0]:.0f},{box.box[1]:.0f}) spans "
                    f"the bodies of {', '.join(foreign)} — text stacked over "
                    "more than one symbol",
                    x=(box.box[0] + box.box[2]) / 2,
                    y=(box.box[1] + box.box[3]) / 2,
                    objects=(box.text, *foreign),
                    estimate=box.estimate,
                )
            )
            continue
        for name, body in bodies:
            if not _box_overlap(box.box, body):
                continue
            out.append(
                LintFinding(
                    "L3-text-on-part",
                    "ERROR",
                    f"{box.text!r} at ({box.box[0]:.0f},{box.box[1]:.0f}) lands "
                    f"on the body of {name} — text stacked on a symbol hides "
                    "the symbol",
                    x=(box.box[0] + box.box[2]) / 2,
                    y=(box.box[1] + box.box[3]) / 2,
                    objects=(box.text, name),
                    estimate=box.estimate,
                )
            )
    return out


def check_wire_through_part(
    sheet: Sheet, pin_positions: dict[str, dict[str, tuple[float, float]]] | None = None
) -> list[LintFinding]:
    """L4: a wire segment through a part body, or through a foreign pin tip.

    ``pin_positions`` maps designator → pin number → page point when the run
    could read the pins; without it the pin half of the predicate answers
    "unreadable" and only the body half fires.
    """
    out: list[LintFinding] = []
    bodies = sheet.body_boxes()
    pins_by_wire_cache: dict[tuple[float, float], list[str]] = {}
    if pin_positions:
        for designator, pins in pin_positions.items():
            for number, point in pins.items():
                pins_by_wire_cache.setdefault(point, []).append(f"{designator}.{number}")
    for wire in sheet.wires:
        for a, b in wire.segments:
            for name, body in bodies:
                if not _segment_crosses_box(a, b, body):
                    continue
                # An endpoint landing on a pin inside that body is the wire's
                # own connection (pit 24's point-set rule), not a crossing.
                owner_designator = name
                landing = False
                for point in (a, b):
                    if not _point_in_box(point, body):
                        continue
                    if _near_pin(point, owner_designator, pin_positions):
                        landing = True
                if landing:
                    continue
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                out.append(
                    LintFinding(
                        "L4-wire-through-part",
                        "ERROR",
                        f"wire {wire.primitive[:8]} (net {wire.net or 'unnamed'}) "
                        f"runs through the body of {name} — a conductor printed "
                        "across a symbol",
                        x=mid[0],
                        y=mid[1],
                        objects=(wire.primitive, name),
                    )
                )
    return out


def _near_pin(
    point: tuple[float, float],
    designator: str,
    pin_positions: dict[str, dict[str, tuple[float, float]]] | None,
) -> bool:
    if not pin_positions:
        return False
    pins = pin_positions.get(designator)
    if not pins:
        return False
    for pin_point in pins.values():
        import math

        if math.hypot(point[0] - pin_point[0], point[1] - pin_point[1]) <= PIN_LANDING_EPS:
            return True
    return False


def check_duplicate_annotation(sheet: Sheet) -> list[LintFinding]:
    """L5: one net stated twice in the same region — the 110 feedback shape.

    Two flags of one net are the page's rail distribution, not a duplicate
    (P22 states GND with seven flags, accepted). A flag's **own name** is
    that flag's statement, not a second one (the host draws the name ~15
    units from the flag anchor — P22's four GND flags each with its name,
    accepted), so a flag × label pair only fires when the label is not that
    flag's own name. Same-net labels pair into a firing only when they sit
    on *different* conductors (two ends of one wire are one statement —
    P22's TAP readback pair, accepted); the same-wire test is the carrier
    wire the boxes touch.
    """
    out: list[LintFinding] = []
    annotations = [b for b in sheet.texts if b.kind == "annotation"]
    flag_anchors = sheet.flag_net_anchors()

    def flag_own_name(ax: float, ay: float, box: TextBox) -> bool:
        """The label is this flag's own name (drawn at the flag's glyph)."""
        return (
            math.hypot(box.anchor[0] - ax, box.anchor[1] - ay)
            <= L5_FLAG_OWN_NAME_GAP
        )

    for net, boxes in by_annotation_net(annotations).items():
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if _same_carrier(a, b, sheet):
                    continue
                gap = _box_gap(a.box, b.box)
                if gap >= L5_DUPLICATE_NET_GAP:
                    continue
                out.append(
                    LintFinding(
                        "L5-duplicate-annotation",
                        "ERROR",
                        f"net {net} is stated twice within "
                        f"{L5_DUPLICATE_NET_GAP:g} units ({a.text!r} and "
                        f"{b.text!r}, gap {gap:.1f}) — the feedback region "
                        "reads as two statements of one net",
                        x=(a.box[0] + a.box[2]) / 2,
                        y=(a.box[1] + a.box[3]) / 2,
                        objects=(a.text, b.text),
                        estimate=True,
                    )
                )
    for box in annotations:
        for ax, ay in flag_anchors.get(box.net or "", []):
            if flag_own_name(ax, ay, box):
                continue
            nearest = _box_nearest_point(box.box, ax, ay)
            gap = math.hypot(nearest[0] - ax, nearest[1] - ay)
            if gap >= L5_DUPLICATE_NET_GAP:
                continue
            out.append(
                LintFinding(
                    "L5-duplicate-annotation",
                    "ERROR",
                    f"net {box.net} is stated by a flag at ({ax:.0f},{ay:.0f}) "
                    f"and a label {box.text!r} {gap:.1f} units away — one net, "
                    "two statements, in the same region",
                    x=ax,
                    y=ay,
                    objects=(box.text, f"flag@({ax:.0f},{ay:.0f})"),
                    estimate=True,
                )
            )
    return out


def by_annotation_net(
    annotations: list[TextBox],
) -> dict[str, list[TextBox]]:
    out: dict[str, list[TextBox]] = {}
    for box in annotations:
        if box.net:
            out.setdefault(box.net, []).append(box)
    return out


def _same_carrier(a: TextBox, b: TextBox, sheet: Sheet) -> bool:
    """True when both labels sit on one wire primitive — one statement."""
    carriers_a = _label_carriers(a, sheet)
    carriers_b = _label_carriers(b, sheet)
    return bool(carriers_a & carriers_b)


def _label_carriers(box: TextBox, sheet: Sheet) -> set[str]:
    """The primitives of wires the box contacts (point or span)."""
    carriers: set[str] = set()
    inflated = _inflate(box.box, TEXT_BOX_SLACK)
    for wire in sheet.wires:
        if any(
            inflated[0] <= p[0] <= inflated[2] and inflated[1] <= p[1] <= inflated[3]
            for p in wire.points
        ) or any(
            _segment_touches_box(x, y, box.box) for x, y in wire.segments
        ):
            carriers.add(wire.primitive)
    return carriers


def _box_nearest_point(
    box: tuple[float, float, float, float], x: float, y: float
) -> tuple[float, float]:
    return (
        max(box[0], min(x, box[2])),
        max(box[1], min(y, box[3])),
    )


def check_wire_multiname(sheet: Sheet) -> list[LintFinding]:
    """L5b (WARN, 111a §规则二): one wire primitive carrying more than one
    same-net annotation — the shape the host DRC reports as 「导线 $1N77 有
    多个网络名: LED_A、LED_A」 (110's named-stub technique: each stub of one
    continuous conductor is named, so one primitive backs several same-name
    labels).

    The carrier test is :func:`_label_carriers` — the same contact rule L5's
    ``_same_carrier`` uses, so the two predicates are complementary by
    construction: L5 exempts same-carrier pairs from its ERROR (one wire, one
    statement by position), L5b counts exactly those same-carrier annotations
    and warns when they are more than one. A flag is not an annotation
    (kind ``"label"`` only) — flag + label in one region stays L5's case —
    and two *different*-net labels on one carrier are not a multiname.
    """
    out: list[LintFinding] = []
    annotations = [b for b in sheet.texts if b.kind == "annotation"]
    carriers: dict[str, list[TextBox]] = {}
    for box in annotations:
        for primitive in _label_carriers(box, sheet):
            carriers.setdefault(primitive, []).append(box)
    for primitive, boxes in carriers.items():
        if len(boxes) <= 1:
            continue
        by_net: dict[str, list[TextBox]] = {}
        for box in boxes:
            by_net.setdefault(box.net, []).append(box)
        wire_net = next(
            (w.net for w in sheet.wires if w.primitive == primitive), ""
        )
        for net, group in by_net.items():
            if len(group) <= 1:
                continue
            first = group[0]
            out.append(
                LintFinding(
                    "L5-wire-multiname",
                    "WARN",
                    f"wire {primitive[:8]} carries {len(group)} labels of one "
                    f"net ({', '.join(first.text for _ in [0] * min(len(group), 3))}"
                    f"{'…' if len(group) > 3 else ''}) — the host DRC reports "
                    "导线有多个网络名 for this wire; one continuous conductor "
                    "reads better with one name",
                    x=(first.box[0] + first.box[2]) / 2,
                    y=(first.box[1] + first.box[3]) / 2,
                    objects=(primitive, net, len(group)),
                    estimate=True,
                )
            )
    return out


def check_out_of_bounds(sheet: Sheet) -> list[LintFinding]:
    """L10 (ERROR, 111a §规则一): element geometry beyond the sheet frame.

    岳's evidence (2026-10-04): P1's +12V flag anchors at (1160,325) inside
    the 1170-wide sheet but its name's glyphs run past the edge, and R19's
    top rides the frame *without* crossing — legal. So the check reads every
    object's extent (part body box, wire points, flag anchors, text boxes —
    the estimate marks the text findings) and fires only past
    :data:`L10_EDGE_EPS` outside; touching the edge is inside. Parts whose
    body extent is unknown fall back to their origin point (the snapshot
    carries no per-part bbox unless ``--bodies`` fed one in). No sheet box in
    the snapshot → the predicate says nothing (L9's honest degradation).
    """
    if sheet.sheet_box is None:
        return []
    x0, y0, x1, y1 = sheet.sheet_box
    eps = L10_EDGE_EPS

    def beyond_box(box: tuple[float, float, float, float]) -> tuple[int, float]:
        """Which side(s) stick out past eps, and by how much."""
        worst = 0.0
        sides = 0
        for value, edge in (
            (x0 - box[0], "left"),
            (y0 - box[1], "bottom"),
            (box[2] - x1, "right"),
            (box[3] - y1, "top"),
        ):
            if value > eps:
                sides += 1
                worst = max(worst, value)
        return sides, worst

    out: list[LintFinding] = []
    for part in sheet.parts:
        body = part.page_body()
        if body is None:
            body = (part.x, part.y, part.x, part.y)
        sides, over = beyond_box(body)
        if not sides:
            continue
        out.append(
            LintFinding(
                "L10-out-of-bounds",
                "ERROR",
                f"part {part.designator or part.primitive[:8]} body extends "
                f"{over:.1f} units beyond the sheet frame "
                f"({x0:.0f},{y0:.0f})..({x1:.0f},{y1:.0f}) — off the printed "
                "area, the fabricator's eye never reaches it",
                x=(body[0] + body[2]) / 2,
                y=(body[1] + body[3]) / 2,
                objects=(part.designator or part.primitive,),
            )
        )
    for flag in sheet.flags:
        sides, over = beyond_box((flag.x, flag.y, flag.x, flag.y))
        if not sides:
            continue
        out.append(
            LintFinding(
                "L10-out-of-bounds",
                "ERROR",
                f"flag {flag.primitive[:8]} (net {flag.net or 'unnamed'}) at "
                f"({flag.x:.0f},{flag.y:.0f}) sits {over:.1f} units beyond "
                "the sheet frame",
                x=flag.x,
                y=flag.y,
                objects=(flag.primitive,),
            )
        )
    for wire in sheet.wires:
        for px, py in wire.points:
            sides, over = beyond_box((px, py, px, py))
            if not sides:
                continue
            out.append(
                LintFinding(
                    "L10-out-of-bounds",
                    "ERROR",
                    f"wire {wire.primitive[:8]} reaches ({px:.0f},{py:.0f}), "
                    f"{over:.1f} units beyond the sheet frame",
                    x=px,
                    y=py,
                    objects=(wire.primitive,),
                )
            )
    for box in sheet.texts:
        sides, over = beyond_box(box.box)
        if not sides:
            continue
        out.append(
            LintFinding(
                "L10-out-of-bounds",
                "ERROR",
                f"text {box.text!r} box extends {over:.1f} units beyond the "
                "sheet frame — the name runs off the printed area",
                x=(box.box[0] + box.box[2]) / 2,
                y=(box.box[1] + box.box[3]) / 2,
                objects=(box.text,),
                estimate=True,
            )
        )
    return out


def check_crossings(sheet: Sheet) -> list[LintFinding]:
    """L6 (INFO, one WARN shape — 111a §规则三): wire × wire proper crossings.

    Crossings are a soft indicator, never a refusal: a page can be perfectly
    correct and still carry them (110's CS_FILT × HVDC 十字). The raw
    per-segment list double-counts one visual crossing whenever either wire
    runs several segments (the pre-fix P1's SW × HVDC reported 8 rows for one
    corner), so rows are first **clustered per unordered wire-primitive
    pair**: crossings of the same pair within :data:`L6_CLUSTER_GAP` of each
    other are one cluster, reported once with its crossing count.

    Severity: a 1–2-crossing cluster stays INFO (P24's XO × 孤立段
    double-cross and P23's pair double-cross are accepted pages' legal
    shapes); a cluster of :data:`L6_CLUSTER_WARN` or more crossings warns —
    the same two conductors crossing repeatedly is 岳's 「不必要交叉」 — and
    a page with more than :data:`L6_PAGE_WARN` distinct clusters adds one
    page-level WARN. Same-net pairs never pair up (that is connected wiring).
    """
    wires = [w for w in sheet.wires if w.points]
    pairs: dict[tuple[str, str], tuple[Wire, Wire, list[tuple[float, float]]]] = {}
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            a_wire, b_wire = wires[i], wires[j]
            if a_wire.net and a_wire.net == b_wire.net:
                continue
            points: list[tuple[float, float]] = []
            for a_seg in a_wire.segments:
                for b_seg in b_wire.segments:
                    point = _segment_intersection(*a_seg, *b_seg)
                    if point is not None:
                        points.append(point)
            if points:
                pairs[(a_wire.primitive, b_wire.primitive)] = (a_wire, b_wire, points)

    def cluster_points(points: list[tuple[float, float]]):
        groups: list[list[tuple[float, float]]] = []
        for point in sorted(points):
            if groups and all(
                abs(point[0] - q[0]) <= L6_CLUSTER_GAP
                and abs(point[1] - q[1]) <= L6_CLUSTER_GAP
                for q in groups[-1]
            ):
                groups[-1].append(point)
            else:
                groups.append([point])
        return groups

    def spread(group: list[tuple[float, float]]) -> float:
        """Max pairwise distance inside one cluster — the backtrack artifact
        (a wire re-reading its own corner) spans nothing; a real multi-cross
        spans a wire width or more (:data:`L6_CLUSTER_SPREAD`'s evidence)."""
        return max(
            (
                math.hypot(a[0] - b[0], a[1] - b[1])
                for a in group
                for b in group
            ),
            default=0.0,
        )

    out: list[LintFinding] = []
    cluster_count = 0
    for (pa, pb), (a_wire, b_wire, points) in pairs.items():
        for group in cluster_points(points):
            cluster_count += 1
            count = len(group)
            cx = sum(p[0] for p in group) / count
            cy = sum(p[1] for p in group) / count
            if count >= L6_CLUSTER_WARN and spread(group) > L6_CLUSTER_SPREAD:
                severity = "WARN"
                tail = (
                    f" — one pair of conductors crossing {count} times is the "
                    "needless-crossing shape 岳's re-review flags; reroute "
                    "one of the two"
                )
            else:
                severity = "INFO"
                tail = " — a reader must check the two nets are not joined"
            out.append(
                LintFinding(
                    "L6-wire-crossing",
                    severity,
                    f"wires {pa[:8]} ({a_wire.net or 'unnamed'}) and "
                    f"{pb[:8]} ({b_wire.net or 'unnamed'}) cross {count} "
                    f"time(s) near ({cx:.0f},{cy:.0f}) with no junction"
                    + tail,
                    x=cx,
                    y=cy,
                    objects=(pa, pb),
                )
            )
    if cluster_count > L6_PAGE_WARN:
        out.append(
            LintFinding(
                "L6-wire-crossing",
                "WARN",
                f"the page carries {cluster_count} distinct crossing sites "
                f"(more than {L6_PAGE_WARN}) — the routing asks for an eye: "
                "most crossings read as unintentional on a finished page",
                x=sheet.sheet_box[0] if sheet.sheet_box else 0.0,
                y=sheet.sheet_box[1] if sheet.sheet_box else 0.0,
                objects=tuple(
                    primitive
                    for pair in pairs
                    for primitive in pair
                ),
            )
        )
    return out


def check_label_wire_clearance(
    sheet: Sheet, pin_positions: dict[str, dict[str, tuple[float, float]]] | None = None
) -> list[LintFinding]:
    """L7 (WARN): labels or pin tips closer than the calibrated gap to a
    *foreign* wire — the U3-region crowding 110 showed.

    The distance is the label's **anchor** (its glyph baseline) to the
    foreign wire's nearest *reported point*: the host reports a bent wire as
    one primitive whose pairwise reading draws phantom diagonals across the
    bend (pit 26 — "相邻对里有从没画过的对角线"), so segment distance reads a
    conductor where none is drawn, while the reported points are the corners
    the host actually asserts. The accepted pages' closest legal
    label-anchor-to-foreign-wire point measures ~10 units (P22/P23/P24
    2026-10-04 — the labels-between-parallel-runs shape keeps a full text
    row); the threshold sits at under half of that.
    """
    out: list[LintFinding] = []
    for box in sheet.texts:
        for wire in sheet.wires:
            if not wire.net or wire.net == box.net:
                continue
            if _own_net_text_exemption(box, wire, sheet):
                continue
            if not wire.points:
                continue
            distance = min(
                math.hypot(box.anchor[0] - p[0], box.anchor[1] - p[1])
                for p in wire.points
            )
            if distance >= L7_LABEL_WIRE_GAP:
                continue
            out.append(
                LintFinding(
                    "L7-label-wire-clearance",
                    "WARN",
                    f"{box.text!r} sits {distance:.1f} units off wire "
                    f"{wire.primitive[:8]} (net {wire.net}) — under the "
                    f"{L7_LABEL_WIRE_GAP:g}-unit clearance, the label reads as "
                    "possibly naming the wrong conductor",
                    x=(box.box[0] + box.box[2]) / 2,
                    y=(box.box[1] + box.box[3]) / 2,
                    objects=(box.text, wire.primitive),
                    estimate=True,
                )
            )
    return out


def check_flag_orientation(sheet: Sheet) -> list[LintFinding]:
    """L8: a power/ground flag whose rotation is off the vertical set."""
    out: list[LintFinding] = []
    for flag in sheet.flags:
        rotation = flag.rotation % 360
        if rotation in FLAG_VERTICAL_ROTATIONS:
            continue
        out.append(
            LintFinding(
                "L8-flag-orientation",
                "ERROR",
                f"flag {flag.primitive[:8]} (net {flag.net or 'unnamed'}) at "
                f"({flag.x:.0f},{flag.y:.0f}) is rotated {rotation:.0f}° — off "
                "the vertical set the flag bar reads from",
                x=flag.x,
                y=flag.y,
                objects=(flag.primitive,),
            )
        )
    return out


def check_board_fill(sheet: Sheet) -> LintFinding | None:
    """L9 (INFO): the page's placed extent under-fills the sheet.

    A *measurement*, worded as one: the reading itself is the finding, and the
    threshold only decides whether the page is worth a distribution note.
    """
    if sheet.sheet_box is None:
        return None
    points: list[tuple[float, float]] = []
    for part in sheet.parts:
        points.append((part.x, part.y))
    for flag in sheet.flags:
        points.append((flag.x, flag.y))
    for wire in sheet.wires:
        points.extend(wire.points)
    if len(points) < 2:
        return None
    xs = sorted(p[0] for p in points)
    ys = sorted(p[1] for p in points)

    def spread(values: list[float]) -> float:
        low = values[max(0, int(len(values) * 0.02))]
        high = values[min(len(values) - 1, int(len(values) * 0.98))]
        return max(high - low, 0.0)

    width = spread(xs)
    height = spread(ys)
    sheet_w = sheet.sheet_box[2] - sheet.sheet_box[0]
    sheet_h = sheet.sheet_box[3] - sheet.sheet_box[1]
    if sheet_w <= 0 or sheet_h <= 0:
        return None
    ratio = (width * height) / (sheet_w * sheet_h)
    if ratio >= L9_FILL_RATIO:
        return None
    return LintFinding(
        "L9-board-fill",
        "INFO",
        f"placed content spans {width:.0f}×{height:.0f} of the "
        f"{sheet_w:.0f}×{sheet_h:.0f} sheet ({ratio * 100:.1f}%) — the layout "
        "distribution is worth an eye before the page is called done",
        x=sheet.sheet_box[0] + sheet_w / 2,
        y=sheet.sheet_box[1] + sheet_h / 2,
    )


# ------------------------------------------------------------------ running


PREDICATES: tuple[tuple[str, str], ...] = (
    ("L1-text-on-wire", "ERROR"),
    ("L2-text-on-text", "ERROR"),
    ("L3-text-on-part", "ERROR"),
    ("L4-wire-through-part", "ERROR"),
    ("L5-duplicate-annotation", "ERROR"),
    ("L5-wire-multiname", "WARN"),
    ("L6-wire-crossing", "INFO/WARN"),
    ("L7-label-wire-clearance", "WARN"),
    ("L8-flag-orientation", "ERROR"),
    ("L9-board-fill", "INFO"),
    ("L10-out-of-bounds", "ERROR"),
)


def run_lint(
    snapshot: dict,
    render_svg: str | None = None,
    *,
    pin_positions: dict[str, dict[str, tuple[float, float]]] | None = None,
) -> list[LintFinding]:
    """All eleven predicates over one normalised page, in the table's order."""
    sheet = Sheet(snapshot, render_svg=render_svg)
    findings: list[LintFinding] = []
    findings.extend(check_text_on_wire(sheet))
    findings.extend(check_text_on_text(sheet))
    findings.extend(check_text_on_part(sheet))
    findings.extend(check_wire_through_part(sheet, pin_positions))
    findings.extend(check_duplicate_annotation(sheet))
    findings.extend(check_wire_multiname(sheet))
    findings.extend(check_crossings(sheet))
    findings.extend(check_label_wire_clearance(sheet, pin_positions))
    findings.extend(check_flag_orientation(sheet))
    fill = check_board_fill(sheet)
    if fill:
        findings.append(fill)
    findings.extend(check_out_of_bounds(sheet))
    return findings


def render_report(findings: list[LintFinding]) -> str:
    """The human report: grouped by severity, each line with its predicate."""
    if not findings:
        return "draw lint: no findings — the page reads clean."
    lines: list[str] = []
    for severity in ("ERROR", "WARN", "INFO"):
        rows = [f for f in findings if f.severity == severity]
        if not rows:
            continue
        lines.append(f"{severity} ({len(rows)}):")
        for finding in rows:
            lines.append(f"  [{finding.predicate}] {finding.message}")
    return "\n".join(lines)


# ------------------------------------------------------------ render sidecar


def render_svg_from_payload(payload: dict | None) -> str | None:
    """The SVG string out of one ``export.render`` format=svg answer.

    The text geometry lives in the editor's own render of the page; this is
    the one decoder for the base64 envelope the bridge returns.
    """
    if not isinstance(payload, dict):
        return None
    if str(payload.get("format") or "") != "image/svg+xml":
        return None
    data = payload.get("data")
    if not isinstance(data, str):
        return None
    try:
        return base64.b64decode(data).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — a broken render is an absence, not a crash
        return None
