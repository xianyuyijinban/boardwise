"""PCB geometric measurement primitives (task 125, stick 1 / 125a).

This module is the stage-B foundation of the PCB review roadmap: it produces
**numbers and coordinates only** — stackup composition, track width
statistics, component-to-component spacing, loop areas. Whether a number is
acceptable belongs to review rules or to the model reading the report
(工具出数、模型裁定), so no threshold and no verdict ever appears here, and
function names say measure/read/compute, never check/validate.

**Units.** Identical discipline to :mod:`boardwise.core.geometry`: every
input and every returned value is in **mils**. No implicit millimetre
conversion anywhere in this module; callers convert with
:func:`boardwise.core.geometry.mil_to_mm` at the report edge if they must.

**Empty input.** Unknown net names yield zeroed statistics, unknown
designators yield ``None``, and unknown loop anchors raise ``ValueError`` —
the same "never raise on absent copper" discipline as
:meth:`boardwise.core.geometry.BoardGeometry.net`, with the one documented
exception (an anchor string the caller asked us to resolve and could not be
found is a caller error, not absent copper).

**Interface note for stick 2 (125b).** :func:`pad_corners` is deliberately
reusable: 125b's clearance engine consumes the same rotated-rectangle corner
sets for pads, tracks-as-capsules and pour polygons. Keep its contract
(4 CCW corners in board coordinates) stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .geometry import (
    BBox,
    BoardGeometry,
    LayerInfo,
    NetGeometry,
    PadGeometry,
    Point,
    TrackSegment,
    ViaGeometry,
)
from .model import is_ground_net

__all__ = [
    "StackupInfo",
    "read_stackup",
    "LayerWidthStats",
    "WidthStats",
    "track_width_stats",
    "track_width_table",
    "ComponentDistance",
    "component_distance",
    "pad_corners",
    "pad_edge_distance",
    "LoopArea",
    "loop_area",
    "ClearanceResult",
    "net_clearance",
    "clearances_vs",
    "PourIsland",
    "PourConnectivity",
    "pour_connectivity",
    "RegionCopper",
    "RegionCopperItem",
    "region_copper",
    "OBTUSE_CORNER_DEG",
    "TrackCorner",
    "track_corner_angle",
    "vias_in_region",
    "via_layers",
    "vias_on_pad",
    "reference_layer_for",
    "ProjectionRow",
    "ProjectionReport",
    "return_path_projection",
]


# ---------------------------------------------------------------------------
# pad shape helpers (125b reuses these)
# ---------------------------------------------------------------------------


def pad_corners(pad: PadGeometry) -> list[Point]:
    """The pad's four corner points in board coordinates, counter-clockwise.

    Every pad is modelled as a **rotated rectangle**: ``width`` x ``height``
    centred on ``(x, y)`` and rotated by ``angle`` degrees CCW in the y-up
    board frame (the same convention as
    :meth:`boardwise.core.geometry.ComponentPlacement.transform`;
    ``PadGeometry.angle`` is board-frame since task 125a — the parser
    composes the component rotation at instantiation).

    Non-rectangular shapes (``ELLIPSE``, ``OVAL``, circles) are measured as
    their bounding rectangle: the rectangle contains the true shape, so
    distances derived from these corners are a **conservative under-estimate**
    of the real edge-to-edge spacing. That is the safe direction for
    clearance evidence; the exact stadium/ellipse refinement is left to a
    later stick if a rule ever needs it.

    **Public since 126b** (it was the private ``_pad_corners`` when 125 wrote
    it, with a note saying 125b would consume it). It became public when the
    PCB review rules needed it from another layer: ``pcb-component-spacing``
    reads every pad's corners to decide whether a part hangs off the board
    outline, and the repository's layer rule forbids importing a ``_``-prefixed
    name across a layer. A pad's corners are geometry, not an implementation
    detail — the fact that this module happens to compute them from
    ``width``/``height``/``angle`` is its business, and a caller asking for the
    outline of a rotated rectangle is asking a question the shape answers the
    same way. :data:`_pad_corners` remains as an alias so the 125 tests, which
    pin the private spelling, keep saying what they said.
    """
    hw = pad.width / 2.0
    hh = pad.height / 2.0
    rad = math.radians(pad.angle)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return [
        Point(pad.x + dx * cos_a - dy * sin_a, pad.y + dx * sin_a + dy * cos_a)
        for dx, dy in ((hw, hh), (-hw, hh), (-hw, -hh), (hw, -hh))
    ]


#: The name 125 used before 126b promoted :func:`pad_corners`. Kept so the 125
#: suite (which pins the private spelling as "125b's interface") stays green;
#: it is the same function object, not a second implementation.
_pad_corners = pad_corners


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)


def _on_segment(a: Point, b: Point, p: Point, eps: float = 1e-9) -> bool:
    """True when ``p`` lies on segment ``ab`` (``p`` is collinear)."""
    return (
        min(a.x, b.x) - eps <= p.x <= max(a.x, b.x) + eps
        and min(a.y, b.y) - eps <= p.y <= max(a.y, b.y) + eps
    )


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Proper or touching intersection of segments ``p1p2`` and ``p3p4``."""
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    eps = 1e-9
    if abs(d1) <= eps and _on_segment(p3, p4, p1):
        return True
    if abs(d2) <= eps and _on_segment(p3, p4, p2):
        return True
    if abs(d3) <= eps and _on_segment(p1, p2, p3):
        return True
    if abs(d4) <= eps and _on_segment(p1, p2, p4):
        return True
    return False


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    """Distance from point ``p`` to segment ``ab``, in mils."""
    dx = b.x - a.x
    dy = b.y - a.y
    if dx == 0 and dy == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))


def _segment_distance(p1: Point, p2: Point, p3: Point, p4: Point) -> float:
    """Minimum distance between segments ``p1p2`` and ``p3p4`` (0 if touching)."""
    if _segments_intersect(p1, p2, p3, p4):
        return 0.0
    return min(
        _point_segment_distance(p1, p3, p4),
        _point_segment_distance(p2, p3, p4),
        _point_segment_distance(p3, p1, p2),
        _point_segment_distance(p4, p1, p2),
    )


def _edges(corners: list[Point]) -> list[tuple[Point, Point]]:
    """Closed edge list of a corner polygon (4 corners -> 4 segments)."""
    return [
        (corners[i], corners[(i + 1) % len(corners)]) for i in range(len(corners))
    ]


def _bbox_distance(a: BBox, b: BBox) -> float:
    """Minimum distance between two axis-aligned bboxes (0 when overlapping)."""
    dx = max(a.min_x - b.max_x, b.min_x - a.max_x, 0.0)
    dy = max(a.min_y - b.max_y, b.min_y - a.max_y, 0.0)
    return math.hypot(dx, dy)


# ---------------------------------------------------------------------------
# stackup
# ---------------------------------------------------------------------------


@dataclass
class StackupInfo:
    """What the board's layer stack says, without any judgement attached."""

    #: Copper layers of the physical stackup, sorted by ``layer_id``.
    copper_layers: list[LayerInfo] = field(default_factory=list)
    copper_count: int = 0
    #: Copper layers that actually carry at least one element (pad / track /
    #: pour), sorted and de-duplicated. Vias have no single ``layer_id`` (they
    #: span layers vertically), so they do not contribute here.
    used_copper_layer_ids: list[int] = field(default_factory=list)


def read_stackup(board: BoardGeometry) -> StackupInfo:
    """Read the board's copper stackup.

    Primary source is the physical stackup (``LAYER_PHYS`` records, parsed
    into :attr:`BoardGeometry.stackup`): the ``LAYER`` table alone defines
    every inner layer the *editor* supports — all 32 of them on the 毕设FOC
    fixture even though its driver board is a 4-layer board (岳 2026-10-07
    亲裁), so counting ``is_copper`` layer definitions would read 34 where
    the fabrication truth is 4. A stackup entry is copper when its layer's
    :attr:`LayerInfo.is_copper` is true; entries whose layer has no
    ``LayerInfo`` at all are skipped (unclassifiable — no guessing).

    Hand-built boards and files without ``LAYER_PHYS`` fall back to
    :meth:`BoardGeometry.copper_layers` (the ``LAYER`` definitions).
    """
    if board.stackup:
        seen: set[int] = set()
        copper: list[LayerInfo] = []
        for entry in board.stackup:
            info = board.layers.get(entry.layer_id)
            if info is None or not info.is_copper or info.layer_id in seen:
                continue
            seen.add(info.layer_id)
            copper.append(info)
        copper.sort(key=lambda info: info.layer_id)
    else:
        copper = board.copper_layers()

    used: set[int] = set()
    for layer_id in (
        [p.layer_id for p in board.pads]
        + [t.layer_id for t in board.tracks]
        + [p.layer_id for p in board.pours]
    ):
        if layer_id is None:
            continue
        info = board.layers.get(layer_id)
        if info is not None and info.is_copper:
            used.add(layer_id)

    return StackupInfo(
        copper_layers=copper,
        copper_count=len(copper),
        used_copper_layer_ids=sorted(used),
    )


# ---------------------------------------------------------------------------
# track widths
# ---------------------------------------------------------------------------


@dataclass
class LayerWidthStats:
    """Track statistics inside one layer."""

    track_count: int = 0
    min_width: float = 0.0
    total_length: float = 0.0


@dataclass
class WidthStats:
    """Track statistics for one net. All-zero when the net has no tracks."""

    net: str = ""
    track_count: int = 0
    min_width: float = 0.0  # 0.0 when the net has no tracks
    max_width: float = 0.0
    total_length: float = 0.0
    #: Keyed by ``layer_id``. Tracks with no layer are counted in the totals
    #: but have no per-layer home, so they are absent here.
    per_layer: dict[int, LayerWidthStats] = field(default_factory=dict)


def track_width_stats(board: BoardGeometry, net: str) -> WidthStats:
    """Width/length statistics of one net's tracks (all-zero if unknown)."""
    tracks = board.tracks_for_net(net)
    stats = WidthStats(net=net, track_count=len(tracks))
    if not tracks:
        return stats
    stats.min_width = min(t.width for t in tracks)
    stats.max_width = max(t.width for t in tracks)
    stats.total_length = sum(t.length for t in tracks)
    for track in tracks:
        if track.layer_id is None:
            continue
        layer = stats.per_layer.setdefault(track.layer_id, LayerWidthStats())
        layer.track_count += 1
        layer.total_length += track.length
        layer.min_width = (
            track.width
            if layer.track_count == 1
            else min(layer.min_width, track.width)
        )
    return stats


def track_width_table(board: BoardGeometry) -> dict[str, WidthStats]:
    """Width statistics for every net that has at least one track."""
    table: dict[str, WidthStats] = {}
    for name in board.net_names():
        stats = track_width_stats(board, name)
        if stats.track_count >= 1:
            table[name] = stats
    return table


# ---------------------------------------------------------------------------
# component / pad distances
# ---------------------------------------------------------------------------


def pad_edge_distance(pad_a: PadGeometry, pad_b: PadGeometry) -> float:
    """Edge-to-edge distance between two pads, in mils (0 when touching).

    Both pads are measured as rotated rectangles (see :func:`pad_corners`);
    the distance is the minimum over the 16 edge-segment pairs, which is 0
    exactly when the rectangles intersect or touch. For ``ELLIPSE`` / ``OVAL``
    / circular shapes the bounding rectangle is used, so the result
    under-estimates the true spacing (rectangle contains the shape) — the
    conservative direction for spacing evidence.

    **Layer-blind on purpose.** This is the pure planar primitive: it answers
    「how far apart are these two rectangles in the board's plane」, and the
    caller decides what a layer-crossing pair means. See
    :func:`component_distance`, which is the layer-aware reader.
    """
    edges_a = _edges(pad_corners(pad_a))
    edges_b = _edges(pad_corners(pad_b))
    return min(
        _segment_distance(a1, a2, b1, b2)
        for a1, a2 in edges_a
        for b1, b2 in edges_b
    )


@dataclass
class ComponentDistance:
    """Measured spacing between two placed components."""

    component_a: str = ""
    component_b: str = ""
    #: Distance between the two anchors (``ComponentPlacement.position``).
    center_distance: float = 0.0
    #: Minimum edge-to-edge distance over the pad pairs (rotated rectangles).
    edge_distance: float = 0.0
    #: ``pin_number`` of the closest pad (its ``id`` when it has no number).
    pad_a: str = ""
    pad_b: str = ""


def _comparable_layers(board: BoardGeometry, pad: PadGeometry) -> set[int]:
    """The layers two pads may be compared on — the parser's reading, or 125's.

    A pad the parser resolved speaks through
    :attr:`PadGeometry.effective_layers`; a hand-built one (empty set) falls
    back to :func:`_element_layers`, which is the pre-127b derivation.

    The one widening applied here is for a board with **no ``LAYER`` table at
    all** (a synthetic fixture, a minimal hand-built ``BoardGeometry``): there
    :func:`_element_layers` can only answer 「every copper layer」 for a
    through-hole pad, and answers *nothing* for an SMD one, because the copper
    set it draws from is empty. Two pads that both say ``layer_id == 1`` plainly
    share a face, so the pad's own declared layer is admitted alongside. The
    widening is narrow on purpose: it is consulted **only when the board names
    no copper layer**, so on every real document (125a: PCB1 defines 34 copper
    ``LAYER`` records) it never fires and the layer table is the authority.
    """
    resolved = pad.effective_layers()
    if resolved:
        return resolved
    layers = _element_layers(board, pad)
    if not layers and pad.layer_id is not None and not _copper_layer_ids(board):
        return {pad.layer_id}
    return layers


def _comparable_pair(board: BoardGeometry, pad_a: PadGeometry, pad_b: PadGeometry) -> bool:
    """Should these two pads be measured against each other? (127b)

    Two refusals, both of which make the pair **unmeasurable** rather than
    **far apart** — and :func:`component_distance` treats them as "not counted",
    which is the direction a rule wants. Both are properties of the *pair*, so
    neither pad is excluded wholesale: a ``GND`` pad is measurable against its
    neighbour's ``SIG`` pad and exempt against its ``GND`` one.

    * **same-net** — two pads of one net meeting is the design's intent, not a
      placement defect. Note what this clause does **not** cover: ``U2.33``
      (``GND``) against ``U6.2`` (``PGND``) are *different* nets, so they are not
      exempt here even though two ground islands meeting in one place is
      equally intended. That case belongs to the net-level question, and
      :class:`~boardwise.rules.pcb.ipc.VoltageSpacing` is where the same-potential
      pair is asked (岳裁定 4). Keeping the two clauses apart is deliberate: one
      reads the copper, the other reads the design's declared voltages.
    * **cross-layer** — the pads share no copper layer, so in plan view their
      0.0 mil is the board's thickness rather than a layout fact. This is the
      127a root cause: PCB1's U4/U6/R17/C14 are placed on the bottom while
      their footprints' pads all say ``layer_id == 1``, and a layer-blind
      reading put six top x bottom pairs at "touching" on a board whose host
      DRC is clean. A through-hole pad spans every copper layer and is
      therefore comparable with everything, which is exactly right.

    A pad with **no** net is comparable with everything — 「I do not know what
    this is connected to」 is not a reason to call it unreachable, and refusing
    it would silently delete a real collision from the sweep.
    """
    if pad_a.net and pad_a.net == pad_b.net:
        return False
    layers_a = _comparable_layers(board, pad_a)
    layers_b = _comparable_layers(board, pad_b)
    if not layers_a or not layers_b:
        # The parser never established one pad's physical layers (a hand-built
        # board). Judging it against nothing would drop it from every sweep,
        # which is the silent direction; keep it and let the measurement be the
        # planar one.
        return True
    return bool(layers_a & layers_b)


def component_distance(
    board: BoardGeometry, des_a: str, des_b: str
) -> ComponentDistance | None:
    """Measure two components' spacing; ``None`` when either is unknown or padless."""
    comp_a = board.component(des_a)
    comp_b = board.component(des_b)
    if comp_a is None or comp_b is None:
        return None
    pads_a = board.pads_for_component(des_a)
    pads_b = board.pads_for_component(des_b)
    if not pads_a or not pads_b:
        return None

    # Task 127b: the nearest pair is taken over pad pairs that can actually be
    # close to each other — **cross-layer pairs are skipped** and **same-net
    # pairs are skipped**. Both refusals are stated for the *pair* rather than
    # for a pad in isolation, because they are facts about two pads: a pad on
    # ``GND`` is measurable against its neighbour's ``SIG`` pad and exempt
    # against its ``GND`` one, and exempting the pad itself would delete the
    # real collision the other pair is reporting.
    #
    # * *cross-layer*: a top pad and a bottom pad 0.0 mil apart in plan view
    #   are on opposite faces of a ~62 mil board; comparing them measures the
    #   board's thickness, not its layout. This is the 127a root cause: PCB1's
    #   U4/U6/R17/C14 are placed on the bottom while their footprints' pads all
    #   say ``layer_id == 1``, so a layer-blind reading put six top x bottom
    #   pairs at "touching" on a board whose host DRC is clean.
    # * *same-net*: two pads of one net meeting is the design's intent, not a
    #   placement defect (the measured cases on 毕设FOC PCB1 are of this shape —
    #   ``U2.33``/``U6.2`` is ``GND`` against ``PGND``, the two grounds'
    #   single-point join).
    #
    # A pair with **no** comparable pads left yields ``None`` — the same
    # "unmeasurable, not zero" answer an unknown designator gets — rather than
    # a fabricated distance.
    shaped_a = [(pad, pad_corners(pad)) for pad in pads_a]
    shaped_b = [(pad, pad_corners(pad)) for pad in pads_b]
    if not shaped_a or not shaped_b:
        return None
    bbox_a = [(pad, corners, BBox.from_points(corners)) for pad, corners in shaped_a]
    bbox_b = [(pad, corners, BBox.from_points(corners)) for pad, corners in shaped_b]

    best = math.inf
    best_pair: tuple[PadGeometry, PadGeometry] | None = None
    for pad_a, corners_a, box_a in bbox_a:
        edges_a = _edges(corners_a)
        for pad_b, corners_b, box_b in bbox_b:
            if not _comparable_pair(board, pad_a, pad_b):
                continue
            # Coarse bbox reject before the exact pass: shapes sit inside
            # their bboxes, so a pair whose bbox gap already loses to the
            # current best can never improve it.
            if box_a is not None and box_b is not None and _bbox_distance(box_a, box_b) >= best:
                continue
            distance = min(
                _segment_distance(a1, a2, b1, b2)
                for a1, a2 in edges_a
                for b1, b2 in _edges(corners_b)
            )
            if distance < best:
                best = distance
                best_pair = (pad_a, pad_b)

    if best_pair is None:
        # Every pad pair was refused — same-net, or no shared copper layer.
        # Both are "this pair cannot be measured", which is ``None`` (the
        # unmeasurable answer), not a fabricated zero.
        return None
    pa, pb = best_pair
    return ComponentDistance(
        component_a=des_a,
        component_b=des_b,
        center_distance=math.hypot(comp_a.x - comp_b.x, comp_a.y - comp_b.y),
        edge_distance=best,
        pad_a=pa.pin_number or pa.id,
        pad_b=pb.pin_number or pb.id,
    )


# ---------------------------------------------------------------------------
# loop area
# ---------------------------------------------------------------------------


@dataclass
class LoopArea:
    """Area enclosed by an ordered anchor loop."""

    #: The resolved anchors, in the order the caller gave them.
    anchor_points: list[Point] = field(default_factory=list)
    #: Shoelace area of the ordered anchor polygon (0.0 under 3 points).
    polygon_area: float = 0.0
    #: Anchor bbox area — an upper bound on ``polygon_area``, for coarse use.
    bbox_area: float = 0.0


def _resolve_anchor(board: BoardGeometry, anchor: str) -> Point:
    """Resolve one string anchor to a board point, or raise ``ValueError``.

    ``"C7"`` resolves to the centroid of every pad centre of component C7;
    ``"C7.1"`` resolves to the centre of C7's pad whose ``pin_number`` is
    ``"1"`` (falling back to the pad ``id`` when pins are unnumbered).
    """
    designator, dot, pin = anchor.partition(".")
    pads = board.pads_for_component(designator)
    if dot:
        for pad in pads:
            if pad.pin_number == pin or (pad.pin_number is None and pad.id == pin):
                return pad.center
        raise ValueError(
            f"unknown anchor {anchor!r}: no pad {pin!r} on component {designator!r}"
        )
    if not pads:
        raise ValueError(f"unknown anchor {anchor!r}: no such component or no pads")
    return Point(
        sum(p.x for p in pads) / len(pads),
        sum(p.y for p in pads) / len(pads),
    )


def loop_area(board: BoardGeometry, anchors: Sequence[str | Point]) -> LoopArea:
    """Area of the loop through the given anchors.

    Anchors are resolved in order (:func:`_resolve_anchor`); a raw
    :class:`Point` passes through untouched. An anchor string that resolves
    to nothing raises ``ValueError`` — that is a caller error, unlike the
    empty-copper cases elsewhere in this module which return empty results.
    """
    points = [
        anchor if isinstance(anchor, Point) else _resolve_anchor(board, anchor)
        for anchor in anchors
    ]
    area = 0.0
    if len(points) >= 3:
        total = 0.0
        for i, p in enumerate(points):
            q = points[(i + 1) % len(points)]
            total += p.x * q.y - q.x * p.y
        area = abs(total) / 2.0
    bbox = BBox.from_points(points)
    return LoopArea(
        anchor_points=points,
        polygon_area=area,
        bbox_area=0.0 if bbox is None else bbox.width * bbox.height,
    )


# ---------------------------------------------------------------------------
# clearance engine (125b)
# ---------------------------------------------------------------------------
#
# Shape model. Every copper element is reduced to one of two primitives:
#
# * a **capsule** — a closed polyline with a width. A track is its own
#   centre-line, a pad rectangle is its four corners, a via is a degenerate
#   2-point capsule of ``via_diameter``, a through-hole pad is a rectangle,
#   a pour is its polygon. Distance is then measured on the *centrelines*
#   and the two half-widths subtracted, which is exactly the edge-to-edge
#   distance for convex constant-width shapes and conservative (never
#   over-optimistic) for the general case.
#
# **Cross-layer semantics.** Elements on different copper layers are
# compared by their XY-plane projection distance — the 2D footprint gap,
# which lower-bounds the true 3D surface-to-surface spacing (creepage /
# clearance between different layers). ``ClearanceResult`` therefore reports
# the planar gap and carries the layer ids in its element descriptions;
# deciding what that gap means for a given net pair is the caller's job.
# Only elements on the *same* layer can be ``overlapping``: a top track
# crossing a bottom track in plan view is normal, not a short.
#
# **Vertical extent.** A via connects every copper layer except those in
# its ``unused_inner_layers``; a pad with a ``hole_diameter`` (through-hole)
# likewise spans every copper layer; an SMD pad exists only on its own
# ``layer_id``. These are the connect / overlap semantics, documented in
# :func:`_element_layers`.


class _Shape:
    """One copper element reduced to a centreline capsule.

    ``points`` is the closed outline's vertex list (2 points for a straight
    track or a round via) and ``radius`` its half width. ``layers`` is the
    set of copper layers the copper exists on — more than one for vias and
    through-hole pads. ``is_pour`` marks a filled polygon, the only kind
    whose interior counts as copper (so containment is a valid meeting test
    for it, via :func:`_point_in_polygon`).
    """

    __slots__ = ("points", "radius", "layers", "label", "bbox", "is_pour")

    def __init__(
        self,
        points: list[Point],
        radius: float,
        layers: set[int],
        label: str,
        *,
        is_pour: bool = False,
    ) -> None:
        self.points = points
        self.radius = radius
        self.layers = layers
        self.label = label
        self.is_pour = is_pour
        self.bbox = BBox.from_points(points)


def _copper_layer_ids(board: BoardGeometry) -> list[int]:
    """The board's copper layer ids (physical stackup, as read by 125a)."""
    return [li.layer_id for li in read_stackup(board).copper_layers]


def _element_layers(
    board: BoardGeometry, element, *, via: bool = False, plated: bool | None = None
) -> set[int]:
    """Copper layers one element physically occupies.

    * **via** — every copper layer except ``unused_inner_layers``. This is
      the vertical barrel plus its annular rings.
    * **pad** — :meth:`~boardwise.core.geometry.PadGeometry.effective_layers`,
      i.e. what the parser established about where the copper physically is
      (task 127b): all copper layers for a through-hole / Multi-Layer pad, and
      the **placement's own face** for an SMD pad. The footprint's ``layer_id``
      is *not* read when the parser has spoken — it names the part as the
      library stores it, and on a part flipped to the bottom face it still says
      ``1`` (measured: all 28 of PCB1's U4/U6/R17/C14 SMD pads say ``1`` while
      their placement says ``2``), which is what manufactured six top-x-bottom
      "touching" pairs on a board whose host DRC is clean. A pad the parser
      never resolved (``effective_layer_ids`` empty — a hand-built board, a
      synthetic fixture) **falls back to the pre-127b derivation**: all copper
      layers if it has a hole, otherwise its own ``layer_id``. That fallback is
      what keeps 125's own hand-built fixtures saying what they said, and it is
      the conservative direction — it is the reading 127b proved wrong only for a
      *flipped* pad, and a flipped pad is one the parser resolved.
    * **track / pour** — only its own ``layer_id``; the file states it and there
      is nothing to correct.

    Elements whose layer is missing land on the empty set and take
    part in nothing (the same "unclassifiable, never guessed" discipline as
    :func:`read_stackup`).
    """
    copper = _copper_layer_ids(board)
    if via:
        unused = {int(v) for v in getattr(element, "unused_inner_layers", [])}
        return {lid for lid in copper if lid not in unused}
    if isinstance(element, PadGeometry):
        resolved = element.effective_layers()
        if resolved:
            return resolved
        # Never resolved by the parser — the pre-127b derivation, kept so a
        # hand-built pad keeps behaving the way 125's fixtures pin it.
        layer_id = element.layer_id
        if layer_id is None:
            return set()
        if element.hole_diameter is not None and plated is not False:
            return set(copper)
        return {layer_id}
    layer_id = getattr(element, "layer_id", None)
    if layer_id is None:
        return set()
    if getattr(element, "hole_diameter", None) is not None and plated is not False:
        return set(copper)
    return {layer_id}


def _describe(kind: str, ident: str, layer_id: int | None) -> str:
    """One element's label for a clearance result.

    The raw ``layer_id`` is what the file says. For a **pad** that is the
    footprint's own value and is wrong on a flipped part (127a measured 28 of
    PCB1's pads claiming layer 1 while sitting on layer 2), so a label built from
    it tells a reader the copper is on the wrong face — which is the misattribution
    127b exists to remove. The caller therefore passes the *effective* layers and
    this function names the set, with the multi-layer case spelled out rather
    than rendered as a list.
    """
    if isinstance(layer_id, (set, frozenset)):
        if not layer_id:
            return f"{kind} {ident} on an unclassified layer"
        if len(layer_id) == 1:
            return f"{kind} {ident} on layer {next(iter(layer_id))}"
        return (
            f"{kind} {ident} on layers "
            f"{'/'.join(str(v) for v in sorted(layer_id))}"
        )
    return f"{kind} {ident} on layer {layer_id}"


def _pad_key(pad: PadGeometry) -> str:
    """A pad identifier unique within a net.

    ``PadGeometry.id`` is the *footprint template* id and repeats across
    every placement of that footprint — on the 毕设FOC main board ``e14``
    names nine different capacitors' pin 2, so a bare id list cannot tell
    them apart. The designator + pin pair is what a reader can act on; the
    template id is kept in parentheses when it is the only handle left.
    """
    if pad.component:
        return f"{pad.component}.{pad.pin_number or pad.id}"
    return pad.id


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Even-odd containment test for a closed polygon.

    Used to recognise a pad / via that is *embedded* in a pour polygon. A
    real pour is solid copper around its own net's pads, so the pad sits in
    the pour's interior, strictly away from the pour outline's edges — the
    outline-to-pad edge distance would report a non-zero gap even though the
    two are the same electrically-connected copper. This containment test is
    the polygon "包含判定" the task book calls for.
    """
    inside = False
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        # On-edge counts as inside (a pad exactly on the boundary touches).
        if _point_segment_distance(point, a, b) <= 1e-9:
            return True
        if (a.y > point.y) != (b.y > point.y):
            x_at = a.x + (point.y - a.y) / (b.y - a.y) * (b.x - a.x)
            if point.x < x_at:
                inside = not inside
    return inside


#: Sentinel for copper whose layer could not be determined; never equal to a
#: real copper layer id, so it never pairs with one.
_UNKNOWN_LAYER = -1


def _poured_supersedes(board: BoardGeometry) -> set[str]:
    """Ids of ``POUR`` regions whose *result* the file also carries.

    **135, the de-duplication rule.** A ``POUR`` record is the region the
    designer drew; the ``POURED`` with the same parent id is what the pour
    engine actually produced from it — the same region minus the clearance
    voids, possibly as several islands. They are one piece of copper described
    twice, so counting both would report every poured region twice over (a
    doubled pour area, and an island whose members include a region and its
    own result).

    The **result** is the one that is kept wherever both exist: it is the
    copper that is really there, and it is what the island count is supposed to
    be measuring. A ``POURED`` with no surviving parent — the ``e-xxxx`` ids
    the editor dropped before saving — has no region to supersede, so it
    stands on its own; it is the only description of that copper.

    Returned as the set of superseded **region** ids (``PourShape.id`` values
    of the ``POUR`` records), so a caller can skip exactly those.
    """
    return {
        pour.poured_from
        for pour in board.pours
        if pour.kind == "poured" and pour.poured_from
    }


def _net_shape_records(
    board: BoardGeometry, net: NetGeometry, *, with_area: bool
) -> list[tuple[str, _Shape, float]]:
    """Every copper element of one net as ``(id, shape, pour_area)``.

    ``with_area`` controls whether the tuple's third slot carries the
    ``fill`` / ``poly`` pour's shoelace area (square mils, for
    :func:`pour_connectivity`) or a plain ``0.0``. Either way the element
    order is deterministic: tracks, then vias, then pads, then pours — the
    order :class:`NetGeometry` stores them in.

    **Which pour record is read (135).** ``POURED`` — the pour *result* — now
    contributes polygons, and when it has a surviving ``POUR`` parent the
    parent is skipped: one region, one piece of copper. See
    :func:`_poured_supersedes`.
    """
    superseded = _poured_supersedes(board)
    out: list[tuple[str, _Shape, float]] = []
    for track in net.tracks:
        layers = _element_layers(board, track)
        if not layers:
            continue
        out.append(
            (
                track.id,
                _Shape(
                    [track.start, track.end],
                    max(track.width, 0.0) / 2.0,
                    layers,
                    _describe("track", track.id, track.layer_id),
                    is_pour=False,
                ),
                0.0,
            )
        )
    for via in net.vias:
        layers = _element_layers(board, via, via=True)
        if not layers:
            continue
        out.append(
            (
                via.id,
                _Shape(
                    [via.center, via.center],
                    max(via.via_diameter, 0.0) / 2.0,
                    layers,
                    _describe("via", via.id, sorted(layers)[0]),
                    is_pour=False,
                ),
                0.0,
            )
        )
    for pad in net.pads:
        layers = _element_layers(board, pad)
        if not layers:
            continue
        out.append(
            (
                _pad_key(pad),
                _Shape(
                    pad_corners(pad),
                    0.0,  # pad is a bare rectangle: the corners are the outline
                    layers,
                    # 127b: the **effective** layers, not ``pad.layer_id``. A
                    # label reading "layer 1" for a pad whose copper is on
                    # layer 2 is the misattribution this fix removed, and the
                    # message is where a reader would have been misled.
                    _describe("pad", _pad_key(pad), layers),
                    is_pour=False,
                ),
                0.0,
            )
        )
    for pour in net.pours:
        # 135: a `POURED` contributes its parsed result polygons, and a
        # `POUR` region that has a `POURED` result is skipped — the region and
        # its result are one piece of copper described twice, and the *result*
        # is the truthful one. A `POURED` whose parent is gone from the file
        # contributes on its own. See `_poured_supersedes`.
        #
        # 131f: `kind == "pour"` (a region with no result in the file) joins
        # `fill` and `poly` here. A POUR record is the pour **region** as the
        # editor holds it — the user's own outline, with its own `netName` and
        # `layerId`, in board coordinates (measured: 毕设FOC 1.0.0 carries 27 of
        # them, ROBOT 3, 药箱 4) — so it is the same kind of copper claim the
        # other two already make. Leaving it out is what made 毕设FOC's `AGND`
        # pours under the crystal invisible to every consumer of this list
        # (125b's island count, the clearance engine, and `region_copper`).
        if pour.kind not in ("fill", "poly", "pour", "poured") or len(pour.points) < 2:
            continue
        if pour.kind != "poured" and pour.id in superseded:
            continue
        layers = _element_layers(board, pour)
        out.append(
            (
                pour.id,
                _Shape(
                    pour.points,
                    0.0,
                    layers or {_UNKNOWN_LAYER},
                    _describe(f"pour {pour.kind}", pour.id, pour.layer_id),
                    is_pour=True,
                ),
                pour.area if with_area else 0.0,
            )
        )
    return out


def _net_shapes(board: BoardGeometry, net: NetGeometry) -> list[_Shape]:
    """Just the shapes of :func:`_net_shape_records` (clearance engine)."""
    return [shape for _, shape, _ in _net_shape_records(board, net, with_area=False)]


def _capsule_distance(a: _Shape, b: _Shape, *, connectivity: bool) -> float:
    """Edge-to-edge distance between two capsules (0 when they touch/overlap).

    Computed as the minimum centrelines-to-centrelines distance over the
    edge-segment pairs, minus both half-widths, floored at 0. Exact for the
    convex constant-width shapes this module produces (tracks, vias, pad
    rectangles, convex pours).

    **Containment is handled by caller intent, because it means different
    things in the two callers:**

    * ``connectivity=True`` (same net, :func:`pour_connectivity`) — a shape
      whose body falls inside a pour polygon is one piece of copper with it.
      A real pour is solid copper around its own net's pads, so those pads
      sit in the pour's interior and never reach its outline; the outline
      distance would call them islands. Returns 0.
    * ``connectivity=False`` (two different nets, the clearance engine) —
      containment is **not measurable** and this returns ``math.inf`` so the
      pair drops out of the minimum. A foreign pad sitting inside a pour's
      *outer* outline tells us nothing: the pour's real copper has clearance
      voids cut around foreign pads, and those voids are not in the model.
      Reporting 0.0 would manufacture a short that may not exist, and
      reporting the outline distance would over-state the gap; returning
      "unmeasurable" is the only honest reading. This is a documented blind
      spot, not an oversight — it is what keeps ``clearances_vs`` from
      degenerating to all-zeros on a poured board.
    """
    contained = (a.is_pour and any(_point_in_polygon(p, b.points) for p in b.points)) or (
        b.is_pour and any(_point_in_polygon(p, a.points) for p in a.points)
    )
    if contained:
        return 0.0 if connectivity else math.inf
    edges_a = _edges(a.points)
    edges_b = _edges(b.points)
    center_distance = min(
        _segment_distance(p1, p2, p3, p4)
        for p1, p2 in edges_a
        for p3, p4 in edges_b
    )
    return max(0.0, center_distance - a.radius - b.radius)


def _overlapping(a: _Shape, b: _Shape) -> bool:
    """True when two elements on a shared layer have intersecting copper.

    Only same-layer pairs can overlap (:func:`_capsule_distance`'s
    cross-layer callers never reach here), and an unmeasurable
    containment pair (``math.inf``) is not an overlap — it is the absence
    of information, not evidence of a short.
    """
    if not (a.layers & b.layers):
        return False  # no shared copper layer: cannot be a planar short
    return _capsule_distance(a, b, connectivity=False) == 0.0


def _best_pair(
    shapes_a: list[_Shape], shapes_b: list[_Shape]
) -> tuple[float, _Shape, _Shape] | None:
    """The closest capsule pair across two lists, via bbox coarse reject.

    Returns ``None`` when either list is empty, or when **every** pair came
    back unmeasurable (a foreign element wholly inside a pour outline — see
    :func:`_capsule_distance`; such a net pair is absent from the result
    rather than reported as 0.0). The bbox of a capsule is the outline's
    axis-aligned box; two boxes that overlap may still have separated
    capsules, and two that are farther apart than the current best can never
    improve it, so the coarse test is a safe prune in both directions.
    """
    if not shapes_a or not shapes_b:
        return None
    best = math.inf
    best_pair: tuple[_Shape, _Shape] | None = None
    for sa in shapes_a:
        for sb in shapes_b:
            if sa.bbox is None or sb.bbox is None:
                continue
            if _bbox_distance(sa.bbox, sb.bbox) >= best:
                continue
            distance = _capsule_distance(sa, sb, connectivity=False)
            if distance < best:
                best = distance
                best_pair = (sa, sb)
    if best_pair is None:
        return None
    return best, best_pair[0], best_pair[1]


@dataclass
class ClearanceResult:
    """Measured spacing between two nets, plus the closest pair's identity.

    ``distance`` is the minimum edge-to-edge gap over every cross-net
    element pair. For elements on different layers this is the **XY-plane
    projection distance** — the conservative lower bound on the true 3D
    spacing, not the surface-to-surface gap; the layer ids are recoverable
    from ``element_a`` / ``element_b``.

    ``overlapping`` is True only when the closest pair shares a copper layer
    and its shapes actually intersect (a planar short on that layer). A
    top-layer track crossing a bottom-layer track in plan view is not
    overlapping — that is ordinary routing.

    **Known blind spot.** A pair whose only relationship is that one shape
    sits *inside* a pour's outer outline is unmeasurable, not 0.0: the
    pour's real copper has clearance voids around foreign pads and those
    voids are not in the geometry model. Such pairs are excluded from the
    minimum rather than guessed at (see :func:`_capsule_distance`); a net
    pair with no measurable pair at all yields ``None``.

    ``shared_layer_ids`` (127b) is the intersection of the two elements' copper
    layers, and it is what tells a caller whether ``distance`` is a claim about
    the pair at all: an **empty** intersection is a cross-layer pair, whose
    ``distance`` is the plan-view projection of two shapes separated vertically
    by at least the board's prepreg (measured: 62 mil on the 毕设FOC fixture,
    against IPC-2221's 4 mil band). That is a real distance and not a
    violation; a caller that judged such a pair by the projection would be
    measuring the board's thickness. :attr:`shares_a_layer` is the one-word form.
    """

    net_a: str = ""
    net_b: str = ""
    distance: float = 0.0
    element_a: str = ""
    element_b: str = ""
    overlapping: bool = False
    #: Copper layers the closest pair both occupy. Empty for a cross-layer
    #: pair, whose ``distance`` is a plan-view projection rather than a
    #: surface-to-surface gap (see the class docstring).
    shared_layer_ids: list[int] = field(default_factory=list)

    @property
    def shares_a_layer(self) -> bool:
        """Whether the closest pair's copper can actually meet (same layer)."""
        return bool(self.shared_layer_ids)


def net_clearance(
    board: BoardGeometry, net_a: str, net_b: str
) -> ClearanceResult | None:
    """Minimum spacing between two nets; ``None`` if either has no copper.

    The unknown-net case returns ``None`` rather than raising, matching
    :meth:`BoardGeometry.net`. A net paired with itself is ``None`` too —
    there is no meaningful self-clearance — and so is a pair whose only
    relationship is an unmeasurable pour containment (see
    :class:`ClearanceResult`).
    """
    geo_a = board.net(net_a)
    geo_b = board.net(net_b)
    if net_a == net_b or not geo_a.element_count or not geo_b.element_count:
        return None
    shapes_a = _net_shapes(board, geo_a)
    shapes_b = _net_shapes(board, geo_b)
    best = _best_pair(shapes_a, shapes_b)
    if best is None:
        return None
    distance, sa, sb = best
    return ClearanceResult(
        net_a=net_a,
        net_b=net_b,
        distance=distance,
        element_a=sa.label,
        element_b=sb.label,
        overlapping=_overlapping(sa, sb),
        # 127b: the layer intersection is what tells a caller whether the
        # projected distance is a same-layer gap at all.
        shared_layer_ids=sorted(sa.layers & sb.layers),
    )


def clearances_vs(board: BoardGeometry, net: str) -> dict[str, float]:
    """The net's minimum distance to every other net, keyed by net name.

    Only nets that carry at least one *measurable* element appear; nets
    with no shape (e.g. only layer-less copper this module cannot place)
    are absent rather than reported as 0.0. This is the per-net
    on-demand API the architecture pins (no all-nets matrix).
    """
    geo = board.net(net)
    if not geo.element_count:
        return {}
    shapes = _net_shapes(board, geo)
    if not shapes:
        return {}
    result: dict[str, float] = {}
    for other in board.net_names():
        if other == net:
            continue
        geo_other = board.net(other)
        shapes_other = _net_shapes(board, geo_other)
        if not shapes_other:
            continue
        best = _best_pair(shapes, shapes_other)
        if best is None:
            continue
        result[other] = best[0]
    return result


# ---------------------------------------------------------------------------
# pour / copper connectivity (125b)
# ---------------------------------------------------------------------------


@dataclass
class PourIsland:
    """One connected copper island of a net (see :func:`pour_connectivity`)."""

    island_id: int = 0
    #: One identifier per copper element in this island, in the order
    #: :func:`_net_shape_records` yields them (tracks, vias, pads, pours).
    #: Tracks / vias / pours use their record id; pads use
    #: :func:`_pad_key` (``"C7.2"``) because the raw template id repeats
    #: across placements. A length mismatch against the net's element count
    #: means elements were skipped (unclassifiable layer), not deduplicated.
    element_ids: list[str] = field(default_factory=list)
    #: Summed area of the ``kind in {fill, poly, pour}`` pour polygons inside the
    #: island (square mils; tracks and vias contribute no area).
    area: float = 0.0
    #: Sorted copper layer ids the island touches.
    layer_ids: list[int] = field(default_factory=list)


@dataclass
class PourConnectivity:
    """How a net's copper breaks into connected islands.

    ``island_count`` is the number of electrically-connected copper groups
    the union-find found. A net whose copper is all one piece has
    ``island_count == 1``. Unknown nets yield ``island_count == 0`` with an
    empty ``islands`` list — absent copper, never an exception.
    """

    net: str = ""
    island_count: int = 0
    islands: list[PourIsland] = field(default_factory=list)


class _UnionFind:
    """Minimal union-find over indices (path compression + union by size)."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))
        self._size = [1] * size

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._size[ra] < self._size[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]


def _touching(a: _Shape, b: _Shape) -> bool:
    """True when two shapes share copper on a layer and their bodies meet.

    Meeting is either touching / crossing on a shared layer, or one shape
    sitting inside the other — the containment case matters because a real
    pour is solid copper around its own net's pads, so those pads never
    touch the pour's outline but are one piece of copper with it
    (:func:`_point_in_polygon`).

    Cross-layer proximity never connects: shapes with no layer in common
    are separate islands. A via is not "near" an inner pour in this sense —
    it is the *multi-layer capsule* that occupies both, and it is the via
    that does the joining, not the two pours that flank it.
    """
    if not (a.layers & b.layers):
        return False
    return _capsule_distance(a, b, connectivity=True) <= 1e-9


def pour_connectivity(board: BoardGeometry, net: str) -> PourConnectivity:
    """Connected copper islands of one net, via union-find over touching shapes.

    **Connectivity semantics.** Two elements are in the same island when
    their copper *touches or crosses on a layer they share*:

    * a track endpoint / body meeting a pad, via, or pour;
    * a via joining every copper layer it spans (all copper layers minus
      ``unused_inner_layers``), which is what bridges a top pour to an
      inner-layer pour;
    * a through-hole pad (``hole_diameter`` set) spanning every copper
      layer, likewise bridging top and bottom pours;
    * an SMD pad existing only on its own layer, so it connects a pour on
      that layer and nothing on the opposite face.

    **Pour sources.** Every pour kind contributes: ``fill`` / ``poly`` /
    ``pour`` (the ``FILL`` / ``POLY`` / ``POUR`` region outlines) and
    ``poured`` (the ``POURED`` *result*, which 135 parses into board
    coordinates). A ``POUR`` region that a ``POURED`` result supersedes is
    **not** counted — one region and its result are one piece of copper, and
    the result is the truthful one (:func:`_poured_supersedes`); a ``POURED``
    whose region is gone from the file is counted on its own.
    ``POUR`` joined ``fill`` and ``poly`` in 131f and is what made this number
    change on the boards that store their planes that way: 毕设FOC 1.0.0's
    ``AGND`` read 67 islands without it and reads 1 with it, ROBOT's ``GND``
    194 → 1, 药箱's ``GND`` 225 → 1, while ``llc`` (which stores no ``POUR``)
    is untouched. 135 then swapped region geometry for result geometry on top
    of that, which changes the **numbers** again without changing their
    meaning — same islands, less area (the clearance voids are now excluded),
    and more of them where the pour engine fragmented a plane the region drew
    as one piece. Measured: 毕设FOC 1.0.0's ``GND`` 46 → 39 islands and
    12 350.0 → 10 614.0 sq mil, ``AGND`` 2 059 037.0 → 1 433 311.2 sq mil
    (still one island — a smaller plane, not a broken one); ROBOT's ``GND``
    1 island / 7 494 300 sq mil → **15** islands / 2 210 304.2 sq mil — that
    board's ``GND`` region is one solid plane, and the result says the pour
    engine cut it into fifteen pieces. 药箱's ``GND`` stays at 1 island,
    9 201 550 → 7 151 163.8 sq mil.

    Islands are numbered by the flat order :func:`_net_shape_records`
    yields (tracks, then vias, then pads, then pours), and
    ``element_ids`` follows the same order. The result is deterministic.
    """
    geo = board.net(net)
    shapes_with_ids = _net_shape_records(board, geo, with_area=True)
    if not shapes_with_ids:
        return PourConnectivity(net=net, island_count=0, islands=[])

    n = len(shapes_with_ids)
    uf = _UnionFind(n)
    for i in range(n):
        si = shapes_with_ids[i][1]
        for j in range(i + 1, n):
            sj = shapes_with_ids[j][1]
            bi, bj = si.bbox, sj.bbox
            if bi is None or bj is None:
                continue
            # Coarse reject: shapes whose bboxes are farther apart than 0
            # cannot touch, so skip the exact test. (0 is the touch
            # threshold; a positive bbox gap already proves separation.)
            if _bbox_distance(bi, bj) > 1e-9:
                continue
            if _touching(si, sj):
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    # Order islands by their first member's flat index for a stable island_id.
    ordered = sorted(groups.values(), key=lambda members: members[0])
    islands: list[PourIsland] = []
    for island_id, members in enumerate(ordered):
        members.sort()
        element_ids: list[str] = []
        area = 0.0
        layers: set[int] = set()
        for idx in members:
            elem_id, shape, pour_area = shapes_with_ids[idx]
            element_ids.append(elem_id)
            area += pour_area
            layers |= {lid for lid in shape.layers if lid != -1}
        islands.append(
            PourIsland(
                island_id=island_id,
                element_ids=element_ids,
                area=area,
                layer_ids=sorted(layers),
            )
        )
    return PourConnectivity(net=net, island_count=len(islands), islands=islands)
# ---------------------------------------------------------------------------
# region inventory (131f)
# ---------------------------------------------------------------------------


@dataclass
class RegionCopperItem:
    """One copper element whose body lies inside a queried region.

    ``element_kind`` is the four kinds of thing this model holds —
    ``"pad"`` / ``"track"`` / ``"via"`` / ``"pour"`` — and ``element_id`` is the
    identifier a reader can act on: the raw record id for a track, via or
    pour, and :func:`_pad_key` (``"C7.2"``) for a pad, because the footprint
    template id repeats across every placement of that footprint.

    ``layer_ids`` is the copper the element physically occupies
    (:func:`_element_layers`): one face for an SMD pad and a track, the whole
    board for a via or a through-hole pad. A pour carries the single layer the
    file states for it. ``net`` is the net as the document writes it and is
    ``None`` when the element carries none — unclassifiable, never guessed.

    **This is a presence record, not a distance.** ``overlap_bbox`` says how
    much of the element's bounding box falls inside the region, which is a
    coarse measure of *how much copper is there*; it is not a clearance and a
    caller must not read it as one (see :func:`region_copper`).
    """

    element_kind: str = ""
    element_id: str = ""
    net: str | None = None
    layer_ids: list[int] = field(default_factory=list)
    overlap_bbox: BBox | None = None
    #: The element's own ``kind`` for a pour (``fill`` / ``poly`` / ``pour``);
    #: empty for every other element kind, which has no such field.
    pour_kind: str = ""


@dataclass
class RegionCopper:
    """Everything the board has inside one rectangular region, per copper layer.

    **Only numbers, never a verdict.** The question this answers is 「what is
    under here」, not 「is this acceptable」: whether copper under a crystal is a
    keepout violation, a thermal pad or nothing at all is a rule's call, and this
    module states no threshold (the module's own contract). An empty
    ``layers_by_id`` therefore means 「nothing found」, and the caller reads that
    as an observation, not as a pass.
    """

    #: The queried rectangle, kept so a finding can quote the region it measured.
    region: BBox | None = None
    #: ``{layer id: [items]}`` over the **requested** layers, sorted by the
    #: element order below within each layer. Layers with nothing in them are
    #: present with an empty list, so a reader can see that a layer was asked
    #: about and came back empty — an absent key would be indistinguishable
    #: from a layer that was never asked.
    layers_by_id: dict[int, list[RegionCopperItem]] = field(default_factory=dict)
    #: The copper layers the caller asked about, in the order it asked.
    requested_layer_ids: list[int] = field(default_factory=list)
    #: Copper elements whose layers could not be classified at all (no layer in
    #: the file, or a pad the parser never resolved). They cannot be filed under
    #: a layer, so they are named here rather than silently dropped — the same
    #: "unclassifiable, never guessed" discipline as :func:`read_stackup`.
    unclassified: list[RegionCopperItem] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """How many elements were found, across every requested layer."""
        return sum(len(items) for items in self.layers_by_id.values()) + len(
            self.unclassified
        )

    def is_empty(self) -> bool:
        """True when nothing at all was found in the region."""
        return self.total_count == 0


def _segment_crosses_box(
    p1: Point, p2: Point, box: BBox, radius: float
) -> bool:
    """Does a capsule (segment + half-width ``radius``) reach into ``box``?

    Exact for the case that decides the answer cheaply: an endpoint inside the
    box. Otherwise the capsule's own bbox is inflated by the radius and tested
    against the box, which over-accepts a capsule that passes the box's corner
    diagonally without reaching it. That direction is deliberate — see
    :func:`region_copper`'s contract, where a false 「there is copper here」 is
    a narrower error than a missed one.
    """
    for point in (p1, p2):
        if (
            box.min_x - 1e-9 <= point.x <= box.max_x + 1e-9
            and box.min_y - 1e-9 <= point.y <= box.max_y + 1e-9
        ):
            return True
    if radius <= 0.0:
        return False
    inflated = BBox(
        min(p1.x, p2.x) - radius,
        min(p1.y, p2.y) - radius,
        max(p1.x, p2.x) + radius,
        max(p1.y, p2.y) + radius,
    )
    return not (
        inflated.max_x < box.min_x
        or inflated.min_x > box.max_x
        or inflated.max_y < box.min_y
        or inflated.min_y > box.max_y
    )


def _boxes_overlap(a: BBox, b: BBox) -> bool:
    """Axis-aligned bbox intersection test, touching included."""
    return not (
        a.max_x < b.min_x
        or a.min_x > b.max_x
        or a.max_y < b.min_y
        or a.min_y > b.max_y
    )


def _intersect_box(a: BBox, b: BBox) -> BBox | None:
    """The overlap of two axis-aligned boxes, or ``None`` when disjoint."""
    if not _boxes_overlap(a, b):
        return None
    return BBox(
        max(a.min_x, b.min_x),
        max(a.min_y, b.min_y),
        min(a.max_x, b.max_x),
        min(a.max_y, b.max_y),
    )


def _polygon_meets_box(polygon: list[Point], box: BBox) -> bool:
    """Does a filled polygon have any area inside ``box``?

    **Containment semantics, not distance semantics** — the trap 131f calls
    out. A pad sitting *inside* a pour has a capsule distance of ``math.inf``
    from it (:func:`_capsule_distance`'s documented blind spot: a foreign pad
    inside a pour's outer outline is unmeasurable, because the pour's real
    copper has clearance voids cut around foreign pads that the model does not
    carry). A region query asking 「is there copper here」 must not inherit that
    blindness, so it asks the geometric question instead:

    * any vertex inside the box, or
    * any box corner inside the polygon (:func:`_point_in_polygon`), or
    * any polygon edge crossing a box edge.

    The three together are the standard polygon/box overlap test and are exact
    for a simple polygon, which is what a pour outline is.
    """
    if not polygon:
        return False
    for point in polygon:
        if (
            box.min_x - 1e-9 <= point.x <= box.max_x + 1e-9
            and box.min_y - 1e-9 <= point.y <= box.max_y + 1e-9
        ):
            return True
    corners = [
        Point(box.min_x, box.min_y),
        Point(box.max_x, box.min_y),
        Point(box.max_x, box.max_y),
        Point(box.min_x, box.max_y),
    ]
    if any(_point_in_polygon(corner, polygon) for corner in corners):
        return True
    box_edges = _edges(corners)
    return any(
        _segments_intersect(p1, p2, p3, p4)
        for p1, p2 in _edges(polygon)
        for p3, p4 in box_edges
    )


def region_copper(
    board: BoardGeometry,
    bbox: BBox,
    layers: Sequence[int] | None = None,
) -> RegionCopper:
    """Inventory the copper inside a rectangular region, per copper layer.

    The region question is 「what copper lies under this rectangle」, asked of
    the whole board rather than of a net: pads, tracks, vias and pour polygons
    all count, and each is filed under the copper layer(s) it physically
    occupies (:func:`_element_layers` — an SMD pad on its own face, a via and a
    through-hole pad across the board).

    ``layers`` restricts the answer to those copper layer ids and defaults to
    the board's copper stackup. It is a *restriction*, never an expansion: an
    element on a layer the caller did not ask about is not reported under any
    other layer either, and an element whose layers cannot be classified at all
    lands in :attr:`RegionCopper.unclassified`.

    **How containment is decided — the 131f trap.** The obvious reuse would be
    the clearance engine's capsule distance, and it is wrong here in the
    direction that matters: :func:`_capsule_distance` returns ``math.inf`` for
    a shape sitting *inside* a pour's outline, precisely so a foreign pad in a
    pour cannot be reported as a 0-mil short. 「Unmeasurable, drop the pair」 is
    the honest reading of a *spacing* question and the wrong reading of an
    *inventory* question — the foreign pad is exactly the copper a reader asking
    「what is under the crystal」 needs to be told about. So the test here is
    geometric: point-in-box for a pad or via body, an inflated-bbox plus
    endpoint test for a track's capsule (:func:`_segment_crosses_box`), and a
    true polygon/box overlap for a pour (:func:`_polygon_meets_box`). The
    over-acceptance the capsule test allows at a box corner is the safe
    direction here and is documented on each helper.

    **Performance.** Every element's own bbox is computed once and tested
    against the region box before any exact test, so a region of a few hundred
    square mils over a board with a few thousand elements is a few thousand
    integer-ish comparisons plus the handful of exact tests that survive — the
    exact tests are never reached for an element nowhere near the region.

    **No verdict.** Nothing here says whether the copper found is allowed; see
    :class:`RegionCopper`.
    """
    requested = (
        sorted({int(layer) for layer in layers})
        if layers is not None
        else sorted(_copper_layer_ids(board))
    )
    report = RegionCopper(region=bbox, requested_layer_ids=requested)
    superseded = _poured_supersedes(board)
    for layer_id in requested:
        report.layers_by_id[layer_id] = []
    wanted = set(requested)

    def file_item(
        element_kind: str,
        element_id: str,
        net: str | None,
        layer_ids: set[int],
        overlap: BBox | None,
        pour_kind: str = "",
    ) -> None:
        item = RegionCopperItem(
            element_kind=element_kind,
            element_id=element_id,
            net=net,
            layer_ids=sorted(layer_ids),
            overlap_bbox=overlap,
            pour_kind=pour_kind,
        )
        filed = False
        for layer_id in item.layer_ids:
            if layer_id in wanted:
                report.layers_by_id[layer_id].append(item)
                filed = True
        if not filed and not item.layer_ids:
            report.unclassified.append(item)

    for pad in board.pads:
        corners = pad_corners(pad)
        own = BBox.from_points(corners)
        if own is None or not _boxes_overlap(own, bbox):
            continue  # coarse reject: the pad's body is nowhere near the region
        if not _polygon_meets_box(corners, bbox):
            continue
        file_item(
            "pad",
            _pad_key(pad),
            pad.net,
            _element_layers(board, pad),
            _intersect_box(own, bbox),
        )
    for track in board.tracks:
        radius = max(track.width, 0.0) / 2.0
        if not _segment_crosses_box(track.start, track.end, bbox, radius):
            continue
        own = BBox.from_points([track.start, track.end])
        file_item(
            "track",
            track.id,
            track.net,
            _element_layers(board, track),
            _intersect_box(own, bbox) if own is not None else None,
        )
    for via in board.vias:
        if not _segment_crosses_box(via.center, via.center, bbox, max(via.via_diameter, 0.0) / 2.0):
            continue
        own = BBox.from_points([via.center, via.center])
        file_item(
            "via",
            via.id,
            via.net,
            _element_layers(board, via, via=True),
            _intersect_box(own, bbox) if own is not None else None,
        )
    for pour in board.pours:
        # 135: a POURED result is inventoried here like any other pour, and a
        # POUR region it supersedes is skipped so the same copper is listed
        # once. A result whose region is gone from the file is listed on its
        # own — it is the only record of that copper.
        if len(pour.points) < 3:
            continue
        if pour.kind != "poured" and pour.id in superseded:
            continue
        own = pour.bbox
        if own is None or not _boxes_overlap(own, bbox):
            continue
        if not _polygon_meets_box(pour.points, bbox):
            continue
        file_item(
            "pour",
            pour.id,
            pour.net,
            _element_layers(board, pour),
            _intersect_box(own, bbox),
            pour_kind=pour.kind,
        )
    return report
# ---------------------------------------------------------------------------
# via queries (133a)
# ---------------------------------------------------------------------------
#
# :class:`~boardwise.core.geometry.ViaGeometry` already carries a via's whole
# physical description: ``center``, ``hole_diameter``, ``via_diameter`` and
# ``unused_inner_layers``. What no reader had was the three *questions* a via
# gets asked once those attributes are in hand — **where is it** (a region
# query), **which layers does it reach** (the layer-pair question the FOC
# package needs), and **is it on that pad** (the question a thermal-pad rule
# asks before it may call the pad's copper direct-connected).
#
# These answer only those. No size is graded, no via is called good or bad, and
# the unit discipline is the module's: mils in, mils out.


def via_layers(board: BoardGeometry, via: ViaGeometry) -> list[int]:
    """Copper layers the via's barrel and annular rings physically occupy.

    Every copper layer of the board's stackup (:func:`read_stackup`) **minus**
    ``unused_inner_layers`` — a blind or semi-blind via states the inner layers
    it does *not* reach, and those are subtracted rather than read as absent
    copper. The result is sorted.

    The reading is delegated to :func:`_element_layers`, the same derivation
    the clearance engine and :func:`region_copper` use for a via, so the three
    can never disagree about which layers a via touches. An empty result means
    the board names no copper layer at all (or the via is inside a
    :data:`_UNKNOWN_LAYER`) — unclassifiable copper, reported as such.
    """
    return sorted(_element_layers(board, via, via=True))


def vias_in_region(board: BoardGeometry, bbox: BBox) -> list[ViaGeometry]:
    """Every via whose body lies inside ``bbox``, in board order.

    The region test is the one :func:`region_copper` uses for a via — the via's
    **annular disc** (inflated by ``via_diameter / 2``) against the box, via
    :func:`_segment_crosses_box` — so a via that is only partly in the region is
    found, and one that merely passes the corner is over-accepted in the
    direction :func:`region_copper` documents.

    Net-blind on purpose: this answers 「is there any via here」, which is the
    question a rule asks *before* it knows which net it is looking at.
    """
    out: list[ViaGeometry] = []
    for via in board.vias:
        if _segment_crosses_box(
            via.center, via.center, bbox, max(via.via_diameter, 0.0) / 2.0
        ):
            out.append(via)
    return out


def vias_on_pad(board: BoardGeometry, pad: PadGeometry) -> list[ViaGeometry]:
    """Vias whose **centre** falls inside ``pad``'s corner rectangle.

    The rectangle is :func:`pad_corners`' — the pad's own bounding rotated
    rectangle — so a via centred in the pad's body is found and one merely
    straddling an edge is not. Only the centre is tested: a via half on and
    half off a pad is one copper feature spanning a boundary, and which side it
    「belongs to」 is a rule's call, so the number reported here is the share
    whose centre is unambiguously on the pad.
    """
    box = BBox.from_points(pad_corners(pad))
    if box is None:
        return []
    return [
        via
        for via in board.vias
        if box.min_x - 1e-9 <= via.x <= box.max_x + 1e-9
        and box.min_y - 1e-9 <= via.y <= box.max_y + 1e-9
    ]


# ---------------------------------------------------------------------------
# track corner angle (133a)
# ---------------------------------------------------------------------------


#: Folds whose interior angle is **at or above** this are left out of
#: :func:`track_corner_angle`'s list; anything below it is reported.
#:
#: It is a **geometric constant of the measurement, not a verdict**. TI
#: SLVA959B section 4 calls a right-angle bend on a gate or switching node worth
#: looking at, and 135 is the round number just inside 「visibly not sharp」; but
#: what is *acceptable* is 133b's rule (R13) to decide, and it may read the
#: reported angle and grade it differently. What the constant must never become
#: is a rule smuggled into the primitive.
#:
#: The angle is the **interior** one, so a straight continuation reads 180 and
#: falls outside the window by construction — there is no separate collinear test
#: to forget.
OBTUSE_CORNER_DEG = 135.0

#: Co-linearity tolerance for the straight-continuation test, in degrees, and the
#: same tolerance as a **boundary guard** on the corner window. A fold the user
#: drew at exactly 135 degrees comes back as ``134.99999999999955`` — the
#: ``acos`` of a dot product one ULP short of exact — so a bare
#: ``angle < 135.0`` comparison published 148 such folds on 毕设FOC 1.0.0 as
#: 「blunter than 135」 when they are the 135-degree bends the constant excludes.
#: The guard reads 「near the threshold」 as 「at the threshold」 and leaves the
#: fold out, which is the conservative direction: a fold that might be the
#: excluded 135 is not reported, and the constant still excludes it.
_CORNER_WINDOW_EPS_DEG = 1e-9


def _corner_angle_deg(prev_end: Point, joint: Point, next_end: Point) -> float | None:
    """Interior angle of the fold ``prev_end -> joint -> next_end``, in degrees.

    The angle **between the two segments as drawn from the joint**, which is the
    corner's interior angle: collinear continuation gives 180, a right-angle fold
    90, a hairpin (back on itself) 0. ``None`` when a segment has zero length —
    a degenerate segment has no direction, and inventing one would be a guess.
    """
    ax = prev_end.x - joint.x
    ay = prev_end.y - joint.y
    bx = next_end.x - joint.x
    by = next_end.y - joint.y
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la == 0.0 or lb == 0.0:
        return None
    cos = (ax * bx + ay * by) / (la * lb)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _in_corner_window(angle_deg: float) -> bool:
    """Whether a fold is sharper than :data:`OBTUSE_CORNER_DEG` and is reported.

    Two things live in this one comparison. The threshold is the **geometric
    constant**, not a verdict — see :data:`OBTUSE_CORNER_DEG`. The boundary
    guard is what keeps it from being read as 「135 minus a rounding error」:
    a fold drawn at exactly 135° comes back as 134.99999999999955 from the
    ``acos`` of a dot product one ULP short of exact, and a bare ``< 135.0``
    comparison would report all 148 of them on 毕设FOC 1.0.0 as bends. A
    straight continuation reads 180 and falls outside the window by
    construction, so no separate collinear test is needed — see
    :data:`_CORNER_WINDOW_EPS_DEG`.
    """
    return angle_deg < OBTUSE_CORNER_DEG - _CORNER_WINDOW_EPS_DEG


@dataclass
class TrackCorner:
    """One fold between two same-net, same-layer track segments.

    ``angle_deg`` is the **interior** angle (see :func:`_corner_angle_deg`):
    180 for a straight continuation, 90 for a right-angle bend. The list
    :func:`track_corner_angle` returns holds only folds *below*
    :data:`OBTUSE_CORNER_DEG`, so a caller reading the list never has to
    re-filter — while the angle itself is still reported verbatim, which is what
    lets 133b's R13 grade the numbers it is given.
    """

    #: Where the two segments meet — the shared endpoint.
    position: Point = Point(0.0, 0.0)
    #: Interior angle in degrees (0 hairpin, 90 right angle, 180 straight).
    angle_deg: float = 0.0
    #: The net both segments carry. ``None`` only when the board itself gives a
    #: track no net and the caller asked for the whole board; a same-net pair is
    #: a precondition, so a pair with a netless segment is never reported.
    net: str | None = None
    #: The layer both segments are on; ``None`` when the file states none.
    layer_id: int | None = None
    #: The two segment record ids, sorted, so the pair is order-independent.
    track_a: str = ""
    track_b: str = ""


def _endpoint_key(point: Point, eps: float = 1e-6) -> tuple[int, int]:
    """Quantised endpoint key, so floating-point twins match.

    The parser's own arithmetic leaves two tracks that mean to share an endpoint
    differing in the last bits; an exact float key would miss every real fold and
    report an empty board. Rounding to a thousandth-of-a-mil grid is finer than
    any junction tolerance an editor holds and coarse enough to absorb the noise
    — the same coarse-then-exact shape 125b uses throughout.
    """
    return (round(point.x / eps), round(point.y / eps))


def track_corner_angle(
    board: BoardGeometry, net: str | None = None
) -> list[TrackCorner]:
    """Report every non-obtuse fold in the board's (or one net's) routing.

    A **fold** is a pair of track segments that share an endpoint, carry the same
    net, and sit on the same layer. All three are preconditions, which is what
    keeps two unrelated meetings out of the list: a top track and a bottom track
    crossing in plan view never pair (different layer), and two tracks of
    different nets never pair (a same-layer crossing is a DRC matter, not a
    bend).

    Of those, the folds whose interior angle is **below
    :data:`OBTUSE_CORNER_DEG`** are reported: a 90° bend and a sharp 45° bend
    appear; a straight continuation (180°) and a gentle 140° fold do not. The
    threshold is a geometric constant, not a verdict — see its docstring.

    ``net=None`` sweeps the whole board; a net name narrows to that net's
    tracks. A pair where **either** segment carries no net is skipped, since
    「the same net as what」 has no answer; an unknown net name yields an empty
    list, the module's absent-copper discipline.

    Each pair is reported **once** however many endpoints it shares — two tracks
    that meet at both ends are one fold, not two.

    **Performance.** The pairing is index-based, not quadratic: segments are
    bucketed by ``(net, layer, quantised endpoint)`` in one pass, and only
    buckets holding more than one segment produce pairs. Measured on 毕设FOC
    1.0.0 (726 tracks, 850 distinct endpoints) at a few milliseconds.
    """
    tracks = board.tracks if net is None else board.net(net).tracks
    buckets: dict[
        tuple[str | None, int | None, tuple[int, int]], list[tuple[TrackSegment, bool]]
    ] = {}
    for track in tracks:
        for at_start, point in ((True, track.start), (False, track.end)):
            key = (track.net, track.layer_id, _endpoint_key(point))
            buckets.setdefault(key, []).append((track, at_start))

    corners: list[TrackCorner] = []
    seen: set[tuple[str, str]] = set()
    for (net_name, layer_id, _point), members in buckets.items():
        if len(members) < 2 or net_name is None:
            continue
        for i, (track_a, a_at_start) in enumerate(members):
            joint = track_a.start if a_at_start else track_a.end
            far_a = track_a.end if a_at_start else track_a.start
            for track_b, b_at_start in members[i + 1 :]:
                if track_a.id <= track_b.id:
                    pair = (track_a.id, track_b.id)
                else:
                    pair = (track_b.id, track_a.id)
                if pair in seen:
                    continue
                far_b = track_b.end if b_at_start else track_b.start
                angle = _corner_angle_deg(far_a, joint, far_b)
                if angle is None:
                    continue
                seen.add(pair)
                if not _in_corner_window(angle):
                    continue
                corners.append(
                    TrackCorner(
                        position=joint,
                        angle_deg=angle,
                        net=net_name,
                        layer_id=layer_id,
                        track_a=pair[0],
                        track_b=pair[1],
                    )
                )
    # Deterministic order, so a report is diffable between runs: net, layer,
    # position, then the two ids as the tiebreak.
    corners.sort(
        key=lambda corner: (
            corner.net or "",
            -1 if corner.layer_id is None else corner.layer_id,
            round(corner.position.x, 6),
            round(corner.position.y, 6),
            corner.track_a,
            corner.track_b,
        )
    )
    return corners


# ---------------------------------------------------------------------------
# return path projection (133a)
# ---------------------------------------------------------------------------
#
# 岳 2026-10-08 ruling: on a multi-layer board the return path is analysed by
# **projection** — a trace running on layer L wants a continuous reference
# plane on the layer physically adjacent to it, normally the nearest ground
# pour. This section produces that analysis as **numbers only**: for each trace
# it finds the adjacent reference layer, projects the trace onto it, and reports
# how much ground-class pour copper covers the projected footprint. Whether the
# reference layer *ought* to be a ground plane belongs to the rule layer and to
# the model; nothing here says so.


def _copper_layer_order(board: BoardGeometry) -> list[int]:
    """Copper layer ids in **physical** order (top of the stackup first).

    :func:`read_stackup` sorts its copper by ``layer_id``, and that is right for
    a *set* of layers but wrong for anything that asks about **neighbours**:
    EasyEDA Pro's ids are not an ordering. 毕设FOC 1.0.0's four copper layers
    carry ids 1 / 15 / 16 / 2 at ``z_index`` 1000 / 1002 / 1004 / 9000, so the
    physical order is 1, 15, 16, 2 — a signal on the top layer has Inner1
    directly beneath it, which is the whole reason a return plane lives there,
    and reading ids instead would have it sit 「below」 the bottom layer.

    The order therefore comes from ``LAYER_PHYS`` (``z_index`` ascending) when
    the board has one, and falls back to :func:`read_stackup`'s id order for a
    hand-built board or a file old enough to lack the table — the same fallback
    chain 125a established, and the one that keeps a two-layer synthetic board
    answering ``Top -> Bottom``.
    """
    ordered: list[int] = []
    seen: set[int] = set()
    for entry in sorted(board.stackup, key=lambda item: item.z_index):
        info = board.layers.get(entry.layer_id)
        if info is None or not info.is_copper or entry.layer_id in seen:
            continue
        seen.add(entry.layer_id)
        ordered.append(entry.layer_id)
    if ordered:
        return ordered
    return [info.layer_id for info in read_stackup(board).copper_layers]


def reference_layer_for(board: BoardGeometry, layer_id: int | None) -> int | None:
    """The adjacent reference layer for ``layer_id``, **below it preferred**.

    「Adjacent」 means neighbouring in the physical stackup's copper order, not
    adjacent in layer *id* — see :func:`_copper_layer_order` for why the two are
    different on a real board. Measured anchors:

    * 毕设FOC 1.0.0 (copper order 1 / 15 / 16 / 2): a top-layer signal (id 1)
      references **Inner1 (id 15)**, and Inner2 (16) references Inner1 (15) —
      each layer naming the plane physically beneath it, which is where a
      return current runs.
    * llc (copper order 1 / 2): a top-layer signal (id 1) has nothing beneath it
      and references the **bottom layer (id 2)** — the 向下优先 rule falling
      through to 向上 when there is no 下.

    A layer id the stackup does not name, or the board's only copper layer, has
    no reference and yields ``None``: nothing to project onto is absent
    information, never a guess. A whole-board sweep therefore produces **no**
    single answer, which is why :class:`ProjectionReport` leaves
    :attr:`ProjectionReport.reference_layer_id` at ``None`` unless the caller
    named one layer.
    """
    order = _copper_layer_order(board)
    if layer_id is None or layer_id not in order:
        return None
    index = order.index(layer_id)
    below = [lid for lid in order[:index] if lid != layer_id]
    if below:
        return below[-1]
    above = [lid for lid in order[index + 1 :]]
    return above[0] if above else None


def _ground_pours_on(
    board: BoardGeometry, layer_id: int
) -> list[tuple[str, str, list[Point], BBox | None]]:
    """Ground-class pour polygons on one layer, as ``(id, net, points, bbox)``.

    「Ground class」 is the net-name sieve :func:`is_ground_net` provides
    (``GND`` / ``AGND`` / ``PGND`` / ``VSS`` / ...). That sieve is a **name**,
    and its own docstring is explicit that it is a candidate rather than a proof
    — this module reads it as 「the nets this project calls ground」 and does no
    more. A pour with no net is not counted; a plane on a net this project never
    named ground is not counted, and that gap is a naming gap, not a verdict.

    ``fill`` / ``poly`` / ``pour`` and ``poured`` all contribute (135 parsed the
    poured *results* into board coordinates), subject to the same de-duplication
    every other consumer uses: a ``POUR`` region that a ``POURED`` supersedes is
    skipped, so one piece of ground copper is not counted twice.

    The bbox rides along because :func:`return_path_projection` asks the cheap
    question first: a pour whose own bbox does not meet a footprint cannot put
    copper inside it, whatever the corners say.
    """
    superseded = _poured_supersedes(board)
    out: list[tuple[str, str, list[Point], BBox | None]] = []
    for pour in board.pours:
        if pour.kind not in ("fill", "poly", "pour", "poured") or len(pour.points) < 3:
            continue
        if pour.kind != "poured" and pour.id in superseded:
            continue
        if pour.layer_id != layer_id or not pour.net or not is_ground_net(pour.net):
            continue
        out.append((pour.id, pour.net, pour.points, pour.bbox))
    return out


def _ground_corner_covered(
    ground_pours: list[tuple[str, str, list[Point], BBox | None]], corner: Point
) -> bool:
    """Does any ground pour polygon contain this corner point?"""
    return any(_point_in_polygon(corner, points) for _, _, points, _ in ground_pours)


@dataclass
class ProjectionRow:
    """One trace's projection onto its adjacent reference layer.

    ``projected`` is the trace's own footprint moved onto the reference layer.
    A projection **keeps its XY coordinates** — the shape is unchanged, only
    the layer it is read on changes — so it is the trace's two endpoints and the
    numbers can be checked against the board by hand.

    ``ground_pour_count`` / ``ground_items`` / ``corner_cover_mask`` say what was
    found under it, and :attr:`cover_status` is the classification of that
    finding. No field says whether the reference layer *ought* to be a plane —
    that is the rule layer's call (岳 2026-10-08 裁定③ asks for the projection
    analysis; it does not ask this module to grade it).
    """

    #: The trace's record id, so a row can be traced back to the copper.
    track_id: str = ""
    #: The trace's net, as the document writes it (``None`` when unstated).
    net: str | None = None
    #: The copper layer the trace runs on.
    layer_id: int | None = None
    #: The adjacent reference layer chosen by :func:`reference_layer_for`.
    #: ``None`` when the trace's layer has no neighbour — nothing to project
    #: onto, which is a fact about the stackup and not about the copper.
    reference_layer_id: int | None = None
    #: The trace's XY footprint projected onto ``reference_layer_id``.
    projected: list[Point] = field(default_factory=list)
    #: How much of the footprint the reference layer's ground copper covers:
    #: ``"covered"`` (every corner over ground), ``"partial"`` (some corners,
    #: not all) or ``"none"`` (no ground copper under the footprint at all).
    cover_status: str = "none"
    #: How many ground pours of the reference layer were found under this
    #: footprint, all of them by name (:func:`is_ground_net`).
    ground_pour_count: int = 0
    #: Ids of the ground pours found under the footprint (131f's ids).
    ground_items: list[str] = field(default_factory=list)
    #: One flag per footprint corner, in the order
    #: ``(min_x,min_y), (max_x,min_y), (max_x,max_y), (min_x,max_y)``.
    #: It is the **evidence** behind :attr:`cover_status`, so a reader can see
    #: 「3 of 4 corners over ground」 rather than a bare word.
    corner_cover_mask: list[bool] = field(default_factory=list)


@dataclass
class ProjectionReport:
    """Every traced segment's return-path projection, for one net or the board.

    ``rows`` holds one :class:`ProjectionRow` per trace segment considered, in
    board order, with :attr:`ProjectionRow.cover_status` aggregating into
    :attr:`cover_counts` so a caller can quote 「726 rows, 41 not covered」
    without walking the list. An unknown net yields no rows and all-zero counts
    — absent copper, never an exception.
    """

    #: The net queried; ``None`` for the whole-board sweep.
    net: str | None = None
    #: The reference layer, when the caller named ``layer`` explicitly — a whole
    #: board spanning several layers has no single reference, and leaving it
    #: ``None`` says so rather than picking one.
    reference_layer_id: int | None = None
    rows: list[ProjectionRow] = field(default_factory=list)
    #: ``{status: row count}`` over :attr:`rows`, for the summary a rule prints.
    cover_counts: dict[str, int] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        """How many traces were projected."""
        return len(self.rows)


def _footprint_corners(box: BBox) -> list[Point]:
    """The four corners of ``box``, in a fixed order (so masks are comparable)."""
    return [
        Point(box.min_x, box.min_y),
        Point(box.max_x, box.min_y),
        Point(box.max_x, box.max_y),
        Point(box.min_x, box.max_y),
    ]


def return_path_projection(
    board: BoardGeometry,
    net: str | None = None,
    *,
    layer: int | None = None,
    track_id: str | None = None,
) -> ProjectionReport:
    """Project traces onto their adjacent reference layer and report coverage.

    岳 2026-10-08 ruling: on a multi-layer board the return path is analysed by
    **projection**. For each trace segment of the queried net (or of the whole
    board):

    1. read the trace's copper layer;
    2. find its **adjacent reference layer** — the nearest layer in the physical
       stackup, below preferred (:func:`reference_layer_for`);
    3. project the trace's XY footprint onto that reference layer (a projection
       keeps its coordinates; only the layer it is read on changes);
    4. look at :func:`region_copper`'s inventory of that footprint on the
       reference layer, keep the **ground-class pour** copper among it
       (``GND`` / ``AGND`` / ``PGND`` / ``VSS`` / ... by name,
       :func:`is_ground_net`), and classify the coverage.

    ``net`` narrows to one net, ``layer`` to one copper layer, and ``track_id``
    to one segment; all three default to 「everything」. An unknown net yields
    ``rows == []``.

    **Coverage classes, and what they are not.**

    * ``"covered"`` — every corner of the projected footprint lies inside a
      ground pour on the reference layer.
    * ``"partial"`` — some corners do. This is the fragmenting case a
      projection analysis exists to surface: a plane that stops short of part of
      the trace's footprint.
    * ``"none"`` — no ground pour under the footprint at all.
    * ``"no_reference_layer"`` — the trace's layer has no neighbour, so there
      was nothing to project onto. That is a statement about the stackup.

    The classification is **corner-sampled**, which is a measurement, not a
    topology proof: it says whether the reference layer's ground copper reaches
    each corner of the projected footprint, and :attr:`ProjectionRow.
    corner_cover_mask` publishes the four flags so a reader can see the
    evidence. It does not claim to know whether the copper in between is
    continuous: the corners are sampled against polygons, and 135's parsed
    pour *results* are still polygons — a shape says what copper is where,
    not how the copper in between is joined. Both are the reason the answer is
    a coverage class and never a pass or a fail.

    **Performance.** :func:`region_copper` is a single linear pass per query,
    and the ground inventory is built once per layer rather than per row.
    """
    tracks = board.tracks if net is None else board.net(net).tracks
    if track_id is not None:
        tracks = [t for t in tracks if t.id == track_id]
    if layer is not None:
        tracks = [t for t in tracks if t.layer_id == layer]

    report = ProjectionReport(net=net, reference_layer_id=layer)
    if layer is not None:
        report.reference_layer_id = reference_layer_for(board, layer)

    ground_cache: dict[int, list[tuple[str, str, list[Point], BBox | None]]] = {}

    def ground_on(layer_id: int) -> list[tuple[str, str, list[Point], BBox | None]]:
        if layer_id not in ground_cache:
            ground_cache[layer_id] = _ground_pours_on(board, layer_id)
        return ground_cache[layer_id]

    for track in tracks:
        reference_layer_id = reference_layer_for(board, track.layer_id)
        projected = [track.start, track.end]
        if reference_layer_id is None:
            report.rows.append(
                ProjectionRow(
                    track_id=track.id,
                    net=track.net,
                    layer_id=track.layer_id,
                    reference_layer_id=None,
                    projected=projected,
                    cover_status="no_reference_layer",
                    ground_pour_count=0,
                    ground_items=[],
                    corner_cover_mask=[],
                )
            )
            continue

        # The footprint is the segment inflated by half its width: a return
        # current runs *under the copper*, not under the centreline.
        radius = max(track.width, 0.0) / 2.0
        box = BBox(
            min(track.start.x, track.end.x) - radius,
            min(track.start.y, track.end.y) - radius,
            max(track.start.x, track.end.x) + radius,
            max(track.start.y, track.end.y) + radius,
        )
        corners = _footprint_corners(box)
        ground_pours = ground_on(reference_layer_id)
        # Cheap question first: with no ground pour whose own bbox even meets
        # the footprint, there is nothing for a corner to be inside of, so both
        # the coverage test and the inventory are provably empty and the full
        # board walk is skipped. Same answer, and the reason is a fact about the
        # geometry rather than an assumption about the result.
        if not any(
            pour_box is not None and _boxes_overlap(pour_box, box)
            for _pid, _net, _points, pour_box in ground_pours
        ):
            report.rows.append(
                ProjectionRow(
                    track_id=track.id,
                    net=track.net,
                    layer_id=track.layer_id,
                    reference_layer_id=reference_layer_id,
                    projected=projected,
                    cover_status="none",
                    ground_pour_count=0,
                    ground_items=[],
                    corner_cover_mask=[False] * len(corners),
                )
            )
            continue

        mask = [_ground_corner_covered(ground_pours, corner) for corner in corners]
        found = sum(1 for flag in mask if flag)
        status = "none" if found == 0 else ("covered" if found == len(corners) else "partial")

        # 131f's inventory says what copper is in the footprint, by id; the
        # corner mask says whether the *ground* copper reaches all four corners.
        # Both are reported because neither alone is the answer: an id proves the
        # copper is there, the mask proves it spans the footprint.
        region = region_copper(board, box, [reference_layer_id])
        ground_items = sorted(
            {
                item.element_id
                for item in region.layers_by_id.get(reference_layer_id, [])
                if item.net is not None and is_ground_net(item.net)
            }
        )

        report.rows.append(
            ProjectionRow(
                track_id=track.id,
                net=track.net,
                layer_id=track.layer_id,
                reference_layer_id=reference_layer_id,
                projected=projected,
                cover_status=status,
                ground_pour_count=len(ground_items),
                ground_items=ground_items,
                corner_cover_mask=mask,
            )
        )

    counts: dict[str, int] = {}
    for row in report.rows:
        counts[row.cover_status] = counts.get(row.cover_status, 0) + 1
    report.cover_counts = counts
    return report