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
)

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

    shaped_a = [(pad, pad_corners(pad)) for pad in pads_a]
    shaped_b = [(pad, pad_corners(pad)) for pad in pads_b]
    bbox_a = [(pad, corners, BBox.from_points(corners)) for pad, corners in shaped_a]
    bbox_b = [(pad, corners, BBox.from_points(corners)) for pad, corners in shaped_b]

    best = math.inf
    best_pair: tuple[PadGeometry, PadGeometry] | None = None
    for pad_a, corners_a, box_a in bbox_a:
        edges_a = _edges(corners_a)
        for pad_b, corners_b, box_b in bbox_b:
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

    assert best_pair is not None  # both pad lists are non-empty
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
    * **pad with a hole** (through-hole / plated or not) — every copper
      layer: the barrel is continuous and its lands exist on both faces.
    * **SMD pad / track / pour** — only its own ``layer_id``.

    Elements whose ``layer_id`` is missing land on the empty set and take
    part in nothing (the same "unclassifiable, never guessed" discipline as
    :func:`read_stackup`).
    """
    copper = _copper_layer_ids(board)
    if via:
        unused = {int(v) for v in getattr(element, "unused_inner_layers", [])}
        return {lid for lid in copper if lid not in unused}
    layer_id = getattr(element, "layer_id", None)
    if layer_id is None:
        return set()
    has_hole = getattr(element, "hole_diameter", None) is not None
    if has_hole and plated is not False:
        return set(copper)
    return {layer_id}


def _describe(kind: str, ident: str, layer_id: int | None) -> str:
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


def _net_shape_records(
    board: BoardGeometry, net: NetGeometry, *, with_area: bool
) -> list[tuple[str, _Shape, float]]:
    """Every copper element of one net as ``(id, shape, pour_area)``.

    ``with_area`` controls whether the tuple's third slot carries the
    ``fill`` / ``poly`` pour's shoelace area (square mils, for
    :func:`pour_connectivity`) or a plain ``0.0``. Either way the element
    order is deterministic: tracks, then vias, then pads, then pours — the
    order :class:`NetGeometry` stores them in.
    """
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
                    _describe("pad", _pad_key(pad), pad.layer_id),
                    is_pour=False,
                ),
                0.0,
            )
        )
    for pour in net.pours:
        # POURED records are the pour *result* whose stored path the parser
        # deliberately leaves empty (parent-relative, 1:10-scaled
        # coordinates, not board coordinates). Skip them, plus any other
        # pour with no usable outline.
        if pour.kind not in ("fill", "poly") or len(pour.points) < 2:
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
    """

    net_a: str = ""
    net_b: str = ""
    distance: float = 0.0
    element_a: str = ""
    element_b: str = ""
    overlapping: bool = False


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
    #: Summed area of the ``kind in {fill, poly}`` pour polygons inside the
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

    **Pour sources.** Only pours with ``kind in {"fill", "poly"}`` contribute
    polygons. ``POURED`` records are the *result* of a pour and the parser
    deliberately leaves their paths empty (their stored coordinates are
    parent-relative and scaled 1:10, not board coordinates — feeding them
    to geometry would corrupt every bbox), so they carry no shape here;
    connectivity rides on the ``FILL`` / ``POLY`` pour outlines plus tracks,
    vias and pads.

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
