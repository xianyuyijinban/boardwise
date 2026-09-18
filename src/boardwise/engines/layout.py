"""Sheet-geometry layout engine for the draw flow (revision 3/4, task 006).

Pure geometry: no bridge, no editor, no I/O. Everything is a function over
plain dataclasses so unit tests pin the rules exactly. All coordinates are
*editor canvas* units (y grows downward, origin top-left) — the space the
bridge actions speak. Symbol offsets arrive in *file* space (y up); callers
convert once at the boundary
(:func:`boardwise.engines.generate.canvas_pin_offsets`).

The five hard constraints (task revision 3) and where they live:

1. placement inside the frame, clear of the title block, boxes never
   overlapping — :func:`plan_placement` (shelf packing: boxes align their
   left/top edges to the packing cursor, columns advance by width + aisle,
   rows by height + channel, so non-overlap holds *by construction*), and
   :func:`validate_full` re-checks it on the finished geometry;
2. wires are Manhattan polylines whose endpoints are only pin tips or
   same-net junctions — :func:`route_nets` chains each net's pins
   tip-to-tip through a stateful grid BFS;
3. no segment crosses a component bounding box — boxes are BFS obstacles;
   the only segments inside a box are the straight pin-exit stubs of that
   box's own pins, whitelisted explicitly by the validator;
4. net ports / power flags attach to their net's wire — the router returns
   an on-wire attach point per net; the validator re-checks;
5. annotations keep :data:`LABEL_CLEARANCE` from every foreign box.

Cross-net rule (measured editor behaviour, stated honestly): EasyEDA Pro
draws junction dots when a wire *endpoint* lands on a wire — a T or an
end — while two wires simply crossing continue through unconnected. So the
router hard-blocks foreign wire *endpoints*, permits perpendicular
crossings of foreign wire interiors, and forbids running *along* a foreign
wire (parallel overlap). The validator turns any foreign-endpoint-on-wire
into ``CROSS_NET_SHORT``; pure crossings are legal by design. Visual
separation is a first-pass preference (one-cell inflation around earlier
nets); a net that fails with it retries without — connectivity outranks
aesthetics.

Routing grid: :data:`GRID` = 5 canvas units. EasyEDA pin offsets are
multiples of 5 (measured on the golden library), and the shelf packing
keeps origins on the same lattice, so every pin tip lands exactly on a
grid cell and wire endpoints stay exact.
"""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from boardwise.core.model import DesignModel, Net, is_ground_net

# --- sheet calibration constants (A4 landscape, editor canvas units) ------
#
# Calibration constants, not format facts; the machine calibration step may
# adjust them without touching the algorithms.

SHEET_WIDTH = 1169.0
SHEET_HEIGHT = 826.0

#: Keep-out between anything (boxes, wire ends) and the sheet edge.
FRAME = 10.0

#: The title block sits in the bottom-right corner (canvas y grows downward).
#: Conservative: if the real block is smaller this only costs layout space.
TITLE_BLOCK = (SHEET_WIDTH - 330.0, SHEET_HEIGHT - 110.0, SHEET_WIDTH - 10.0, SHEET_HEIGHT - 10.0)

#: Minimum gap between component boxes, and box-to-frame / box-to-title.
BOX_GAP = 30.0

#: Pin-extent -> bounding-box inflation (covers the symbol body).
BOX_PAD = 20.0

#: Horizontal gap between boxes in one row (also the routing aisle width).
COL_AISLE = 40.0

#: Vertical gap between rows (also the routing channel height).
ROW_CHANNEL = 60.0

#: Minimum distance between an annotation and any foreign bounding box.
LABEL_CLEARANCE = 20.0

#: Routing grid cell size (canvas units). Divides every observed pin offset.
GRID = 5.0

_DIRS: dict[str, tuple[int, int]] = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}
_OPPOSITE: dict[str, str] = {"N": "S", "S": "N", "W": "E", "E": "W"}


def _axis(direction: str) -> str:
    """'h' for horizontal moves (E/W), 'v' for vertical ones (N/S)."""
    return "h" if direction in ("E", "W") else "v"


@dataclass
class Rect:
    """Axis-aligned rectangle; ``x1 >= x0`` and ``y1 >= y0``."""

    x0: float
    y0: float
    x1: float
    y1: float

    def intersects(self, other: "Rect") -> bool:
        """Strict-interior overlap: shared edges are not an intersection."""
        return (
            self.x0 < other.x1 and other.x0 < self.x1
            and self.y0 < other.y1 and other.y0 < self.y1
        )

    def contains_point(self, x: float, y: float, margin: float = 0.0) -> bool:
        return (
            self.x0 - margin < x < self.x1 + margin
            and self.y0 - margin < y < self.y1 + margin
        )

    def distance_to_point(self, x: float, y: float) -> float:
        """Euclidean distance from the point to the rect (0 when inside)."""
        dx = max(self.x0 - x, 0.0, x - self.x1)
        dy = max(self.y0 - y, 0.0, y - self.y1)
        return math.hypot(dx, dy)


@dataclass
class Segment:
    """One Manhattan wire segment; exactly one of the axes is constant."""

    x0: float
    y0: float
    x1: float
    y1: float
    net: str

    def points(self) -> tuple[tuple[float, float], tuple[float, float]]:
        return (self.x0, self.y0), (self.x1, self.y1)

    def is_manhattan(self) -> bool:
        return abs(self.x0 - self.x1) < 1e-9 or abs(self.y0 - self.y1) < 1e-9


@dataclass
class Violation:
    """One self-check failure, human-readable on every field."""

    code: str
    subject: str
    detail: str

    def render(self) -> str:
        return f"[{self.code}] {self.subject}: {self.detail}"


@dataclass
class Placement:
    """One component placement with its computed box.

    ``(x, y)`` is the component *origin* — what the editor API places by —
    while ``bbox`` is the keep-out box around the pin extents. The two do
    not coincide because box alignment normalizes per component (box left /
    top edges land on the packing cursor, not the origin).
    """

    designator: str
    x: float
    y: float
    bbox: Rect | None


@dataclass
class RoutedNet:
    """One net's wiring: tip-to-tip polylines plus its on-wire attach point."""

    net: str
    polylines: list[list[tuple[float, float]]] = field(default_factory=list)
    attach: tuple[float, float] | None = None
    kind: str = "port"  # 'port' | 'Ground' | 'Power'


@dataclass
class LayoutPlan:
    """The full geometric plan, ready for validation and execution."""

    placements: list[Placement] = field(default_factory=list)
    routes: list[RoutedNet] = field(default_factory=list)
    pin_positions: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)


# --------------------------------------------------------------------------
# bounding boxes
# --------------------------------------------------------------------------


def component_bbox(x: float, y: float, offsets: dict[str, tuple[float, float]]) -> Rect | None:
    """Bounding box of a component placed at origin (x, y), from its offsets.

    The box spans the pin-tip extents inflated by :data:`BOX_PAD`. ``None``
    for a component with no known pins (cannot be bounded).
    """
    if not offsets:
        return None
    xs = [x + dx for dx, _dy in offsets.values()]
    ys = [y + dy for _dx, dy in offsets.values()]
    return Rect(min(xs) - BOX_PAD, min(ys) - BOX_PAD, max(xs) + BOX_PAD, max(ys) + BOX_PAD)


def _relative_box(offsets: dict[str, tuple[float, float]]) -> tuple[float, float, float, float] | None:
    """Box relative to the component origin: ``(dx0, dy0, dx1, dy1)``."""
    if not offsets:
        return None
    xs = [dx for dx, _dy in offsets.values()]
    ys = [dy for _dx, dy in offsets.values()]
    return (min(xs) - BOX_PAD, min(ys) - BOX_PAD, max(xs) + BOX_PAD, max(ys) + BOX_PAD)


# --------------------------------------------------------------------------
# placement (shelf packing; constraint 1 holds by construction)
# --------------------------------------------------------------------------


def plan_placement(
    offsets: dict[str, dict[str, tuple[float, float]]],
    order: list[str],
) -> list[Placement]:
    """Shelf-pack the components in ``order`` inside the usable sheet area.

    Boxes align their left/top edges to the packing cursor; columns advance
    by ``width + COL_AISLE`` and rows by ``row_height + ROW_CHANNEL``. A row
    that would reach past the right edge — or into the title block's x-range
    while its band overlaps the title block's y-range — wraps to the next
    row. A box that fits nowhere is still emitted, at its last candidate
    spot, so the validator reports it by name instead of it vanishing.

    Origins are snapped to :data:`GRID` so every pin tip lands on the
    routing lattice (offsets are multiples of 5, measured).
    """

    def snap(value: float) -> float:
        return round(value / GRID) * GRID

    placements: list[Placement] = []
    row_y = snap(FRAME + BOX_GAP)
    row_height = 0.0
    cursor_x = snap(FRAME + BOX_GAP)
    title_x0, title_y0, _tx1, _ty1 = TITLE_BLOCK

    def wraps(width: float, band_bottom: float) -> bool:
        if cursor_x + width > SHEET_WIDTH - FRAME - BOX_GAP:
            return True
        if band_bottom > title_y0 - BOX_GAP and cursor_x + width > title_x0 - BOX_GAP:
            return True
        return False

    for designator in order:
        rel = _relative_box(offsets.get(designator, {}))
        if rel is None:
            # pin-less: cannot be bounded; park it and let the validator speak
            placements.append(Placement(designator, cursor_x, row_y, None))
            cursor_x += COL_AISLE * 2
            continue
        bx0, by0, bx1, by1 = rel
        w, h = bx1 - bx0, by1 - by0
        if row_height and wraps(w, row_y + row_height):
            row_y = snap(row_y + row_height + ROW_CHANNEL)
            row_height = 0.0
            cursor_x = snap(FRAME + BOX_GAP)
        origin_x = snap(cursor_x - bx0)
        origin_y = snap(row_y - by0)
        box = component_bbox(origin_x, origin_y, offsets.get(designator, {}))
        placements.append(Placement(designator, origin_x, origin_y, box))
        row_height = max(row_height, h)
        cursor_x += w + COL_AISLE
    return placements


# --------------------------------------------------------------------------
# routing (stateful grid BFS; constraints 2, 3, 4 hold by construction)
# --------------------------------------------------------------------------


def _outward_direction(
    tip: tuple[float, float],
    box: Rect,
    sibling_tips: list[tuple[float, float]] = (),
) -> str:
    """The compass direction pointing out of the box edge the pin sits on.

    The pin exits through the *nearest* box edge — not the dominant axis
    from the box centre: a corner pin (equal distance to two edges) that
    exits along the edge would plow its corridor straight through the
    neighbouring pins' tips on that edge (measured: +5V's wire ran over
    six GND/D± pin tips on USB1's left edge). For corner pins the tie is
    broken by whichever stub run stays clear of the sibling tips.
    """
    dists = {
        "W": tip[0] - box.x0,
        "E": box.x1 - tip[0],
        "N": tip[1] - box.y0,
        "S": box.y1 - tip[1],
    }
    m = min(dists.values())
    cands = [d for d in ("W", "E", "N", "S") if dists[d] <= m + 1e-6]
    if len(cands) == 1:
        return cands[0]
    for d in cands:
        ux, uy = _DIRS[d]
        reach = dists[d] + GRID
        end = (tip[0] + ux * reach, tip[1] + uy * reach)
        stub_cells = set(_line_cells(tip, end))
        clear = all(
            _cell(t) not in stub_cells or (t[0], t[1]) == (tip[0], tip[1])
            for t in sibling_tips
        )
        if clear:
            return d
    return cands[0]


def _stub_end(tip: tuple[float, float], box: Rect, direction: str) -> tuple[float, float]:
    """One point just outside ``box``, straight out of ``tip``."""
    ux, uy = _DIRS[direction]
    if ux > 0:
        dist = box.x1 - tip[0]
    elif ux < 0:
        dist = tip[0] - box.x0
    elif uy > 0:
        dist = box.y1 - tip[1]
    else:
        dist = tip[1] - box.y0
    reach = max(dist, 0.0) + GRID
    return (tip[0] + ux * reach, tip[1] + uy * reach)


def _cell(point: tuple[float, float]) -> tuple[int, int]:
    return (int(round(point[0] / GRID)), int(round(point[1] / GRID)))


def _cell_point(cell: tuple[int, int]) -> tuple[float, float]:
    return (cell[0] * GRID, cell[1] * GRID)


def _line_cells(a: tuple[float, float], b: tuple[float, float]) -> list[tuple[int, int]]:
    """Grid cells along the straight Manhattan line a -> b (inclusive)."""
    (i0, j0), (i1, j1) = _cell(a), _cell(b)
    cells: list[tuple[int, int]] = []
    if i0 == i1:
        step = 1 if j1 >= j0 else -1
        for j in range(j0, j1 + step, step):
            cells.append((i0, j))
    else:
        step = 1 if i1 >= i0 else -1
        for i in range(i0, i1 + step, step):
            cells.append((i, j0))
    return cells


def _cells_to_points(cells: list[tuple[int, int]]) -> list[tuple[float, float]]:
    """Cell run -> collinear-merged point run."""
    pts = [_cell_point(c) for c in cells]
    if len(pts) <= 2:
        return pts
    run = [pts[0], pts[1]]
    for cur in pts[2:]:
        moves_in_x_now = abs(cur[0] - run[-1][0]) > 1e-9
        moved_in_x_last = abs(run[-1][0] - run[-2][0]) > 1e-9
        if moves_in_x_now == moved_in_x_last:
            run[-1] = cur  # same axis as the previous step: extend it
        else:
            run.append(cur)
    return run


def _net_kind(name: str) -> str:
    # Ground is decided in exactly one place (`core.model.is_ground_net`) — this
    # used to keep its own regex beside it, which is how the two drifted apart
    # on ``VEE`` and on the SGND/EGND spellings (2026-09-18 ruling, M0-P0c).
    if is_ground_net(name):
        return "Ground"
    if re.match(r"^(\+\d+(?:\.\d+)?V|V(CC|DD|BAT|PP)\d*|V\d+)$", name, re.IGNORECASE):
        return "Power"
    return "port"


def _bfs_chain(
    source: tuple[tuple[int, int], str],
    target: tuple[int, int],
    classify,
) -> list[tuple[tuple[int, int], str]] | None:
    """Deterministic stateful BFS: states are ``(cell, arrival direction)``.

    Leaving a 'straight' cell is only allowed along the arrival direction
    (own corridors may also retrace back); entering one is only allowed
    along its axis (own) or perpendicular to it (foreign). Returns the
    state path — the cells plus arrival directions — or ``None``.
    """
    parent: dict[tuple[tuple[int, int], str], tuple[tuple[int, int], str] | None] = {source: None}
    seen = {source}
    queue: deque[tuple[tuple[int, int], str]] = deque([source])
    while queue:
        state = queue.popleft()
        cell, arrival = state
        cls = classify(cell)
        if isinstance(cls, tuple):
            _, _wax, own = cls
            allowed = (arrival, _OPPOSITE[arrival]) if own else (arrival,)
        else:
            allowed = tuple(_DIRS)
        for d2 in allowed:
            di, dj = _DIRS[d2]
            nxt = (cell[0] + di, cell[1] + dj)
            nstate = (nxt, d2)
            if nstate in seen:
                continue
            ncls = classify(nxt)
            if ncls == "blocked":
                continue
            if isinstance(ncls, tuple):
                nax, nown = ncls[1], ncls[2]
                if nown and _axis(d2) != nax:
                    continue  # sideways into a corridor: dead end by rule
                if not nown and nax is not None and _axis(d2) == nax:
                    continue  # parallel overlap with a foreign wire
            seen.add(nstate)
            parent[nstate] = state
            if nxt == target:
                path = [nstate]
                while parent[path[-1]] is not None:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(nstate)
    return None


def route_nets(
    model: DesignModel,
    pin_positions: dict[tuple[str, str], tuple[float, float]],
    placements: list[Placement],
) -> tuple[list[RoutedNet], list[Violation]]:
    """Route every multi-pin net on a coarse grid, nets one after another.

    Each pin owns a straight *corridor* from its tip out of its own box
    (per the pin's outward direction); the BFS may only travel a corridor
    straight — so every inside-a-box segment is a sanctioned stub, and the
    validator whitelists exactly those. Each net is wired as a chain:
    tip1 -> tip2 -> tip3 …, so every polyline endpoint is a pin tip and
    consecutive links share a junction at the intermediate tips.

    Foreign nets' wires are obstacles with a measured twist: their
    *endpoints* (tips and junctions) are hard-blocked — a wire end landing
    on a foreign wire would make the editor draw a junction dot, i.e. a
    short — while their interiors may be crossed perpendicularly (no dot,
    no connection) and must never be run along (parallel overlap). Bigger
    nets route first; a net that fails with the one-cell separation
    inflation retries without it; a net that still fails is reported,
    never silently dropped.

    Returns ``(routes, violations)``.
    """
    violations: list[Violation] = []
    nx, ny = int(SHEET_WIDTH / GRID) + 1, int(SHEET_HEIGHT / GRID) + 1
    frame_cells = int(FRAME / GRID)
    tx0, ty0, tx1, ty1 = TITLE_BLOCK
    title_cells = {
        (i, j)
        for i in range(int(tx0 / GRID), int(tx1 / GRID) + 1)
        for j in range(int(ty0 / GRID), int(ty1 / GRID) + 1)
    }

    box_cells: dict[str, set[tuple[int, int]]] = {}
    for p in placements:
        if p.bbox is None:
            continue
        box_cells[p.designator] = {
            (i, j)
            for i in range(int(p.bbox.x0 / GRID), int(p.bbox.x1 / GRID) + 1)
            for j in range(int(p.bbox.y0 / GRID), int(p.bbox.y1 / GRID) + 1)
        }

    #: foreign wire cells -> their axis ('h'/'v'); enter perpendicular only
    routed_axis: dict[tuple[int, int], str] = {}
    routed_inflated: set[tuple[int, int]] = set()
    #: foreign wire ENDPOINTS (tips, junctions): hard obstacles, all passes
    routed_endpoints: set[tuple[int, int]] = set()
    routes: list[RoutedNet] = []

    def member_count(item) -> tuple[int, str]:
        name, net = item
        placed = sum(1 for m in net.pins if m in pin_positions)
        return (-placed, name)

    for name, _net in sorted(model.nets.items(), key=member_count):
        net = model.nets[name]
        members = sorted(
            (m for m in net.pins if m in pin_positions),
            key=lambda m: pin_positions[m],
        )
        if len(members) < 2:
            continue

        # per-pin corridor: (tip, outward direction, corridor cells)
        corridors: dict[tuple[str, str], tuple[tuple[float, float], str, list[tuple[int, int]]]] = {}
        for des, pin in members:
            tip = pin_positions[(des, pin)]
            box = next((p.bbox for p in placements if p.designator == des), None)
            if box is None:
                continue
            siblings = [
                (x, y)
                for (d2, _p2), (x, y) in pin_positions.items()
                if d2 == des and (x, y) != (tip[0], tip[1])
            ]
            direction = _outward_direction(tip, box, siblings)
            end = _stub_end(tip, box, direction)
            corridors[(des, pin)] = (tip, direction, _line_cells(tip, end))
        if len(corridors) < 2:
            violations.append(
                Violation(
                    "NET_UNROUTABLE",
                    f"net {name}",
                    "fewer than two pinned members have boxes",
                )
            )
            continue

        corridor_axis: dict[tuple[int, int], str] = {}
        for _tip, direction, cells in corridors.values():
            axis = _axis(direction)
            for cell in cells:
                corridor_axis.setdefault(cell, axis)

        inflate = [True]

        def classify(cell: tuple[int, int], net_cells: set[tuple[int, int]]):
            """'blocked' | 'free' | ('straight', axis, own).

            'straight' cells may only be entered along their axis and left
            along the arrival direction (own corridors may also retrace
            back): our own corridors (inside a box, so a turn there would
            draw over the body) and foreign wires (cross perpendicular,
            never run along or turn on them — a turn would put a wire
            endpoint on the foreign wire).
            """
            ax = corridor_axis.get(cell)
            if ax is not None:
                return ("straight", ax, True)
            i, j = cell
            if i < frame_cells or j < frame_cells or i >= nx - frame_cells or j >= ny - frame_cells:
                return "blocked"
            if cell in title_cells:
                return "blocked"
            for cells in box_cells.values():
                if cell in cells:
                    return "blocked"
            if cell in routed_endpoints:
                return "blocked"
            wax = routed_axis.get(cell)
            if wax is not None:
                return ("straight", wax, False)
            if inflate[0] and cell in routed_inflated:
                return ("straight", None, False)
            return "free"

        def wire_chain() -> list[list[tuple[float, float]]] | None:
            """Link the whole chain once; None when any link is unroutable.

            Every link runs tip -> tip, so every polyline endpoint is a pin
            tip (a dangling stub endpoint would be both a constraint
            violation and, on a foreign wire, a short). The link leaving
            tip_k sources at ``(tip_k, outward)`` for the first pin and
            ``(tip_k, inward)`` for later ones — at a corridor cell the
            BFS may only continue straight or (own corridor) retrace, and
            the inward way is blocked by the component's own body, so the
            chain always exits outward.
            """
            net_cells: set[tuple[int, int]] = set()
            polylines: list[list[tuple[float, float]]] = []

            prev_out = None
            prev_cell = None
            for idx, key in enumerate(members):
                tip, d_out, cells = corridors[key]
                ctip = _cell(tip)
                if idx == 0:
                    net_cells.update(cells)
                    prev_out, prev_cell = d_out, ctip
                    continue
                source = (prev_cell, _OPPOSITE[prev_out])
                path = _bfs_chain(source, ctip, lambda c: classify(c, net_cells))
                if path is None:
                    return None
                path_cells = [s[0] for s in path]
                net_cells.update(path_cells)
                polylines.append(_cells_to_points(path_cells))
                prev_out, prev_cell = d_out, ctip
            return polylines

        polylines = wire_chain()
        if polylines is None:
            inflate[0] = False
            polylines = wire_chain()
            inflate[0] = True
        if polylines is None:
            violations.append(
                Violation(
                    "NET_UNROUTABLE",
                    f"net {name}",
                    "no free route even without separation inflation",
                )
            )
            continue

        for poly in polylines:
            for (ax_, ay_), (bx_, by_) in zip(poly, poly[1:]):
                axis = "h" if abs(ay_ - by_) < 1e-9 else "v"
                i_lo, i_hi = sorted((int(round(ax_ / GRID)), int(round(bx_ / GRID))))
                j_lo, j_hi = sorted((int(round(ay_ / GRID)), int(round(by_ / GRID))))
                for i in range(i_lo, i_hi + 1):
                    for j in range(j_lo, j_hi + 1):
                        routed_axis.setdefault((i, j), axis)
        routed_inflated.update(
            (i + di, j + dj)
            for (i, j) in routed_axis
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
        )
        for poly in polylines:
            routed_endpoints.add(_cell(poly[0]))
            routed_endpoints.add(_cell(poly[-1]))

        own = {des for des, _pin in members}
        attach = _pick_attach_point(polylines, placements, own)
        routes.append(RoutedNet(net=name, polylines=polylines, attach=attach, kind=_net_kind(name)))

    return routes, violations


def _pick_attach_point(
    polylines: list[list[tuple[float, float]]],
    placements: list[Placement],
    own: set[str],
) -> tuple[float, float] | None:
    """The wire midpoint with the most room around it (constraint 5)."""
    best: tuple[float, float] | None = None
    best_score = -1.0
    boxes = [(p.designator, p.bbox) for p in placements if p.bbox]
    for poly in polylines:
        for (ax, ay), (bx, by) in zip(poly, poly[1:]):
            mx, my = (ax + bx) / 2, (ay + by) / 2
            score = min(
                (box.distance_to_point(mx, my) for des, box in boxes if des not in own),
                default=1e9,
            )
            if score > best_score:
                best_score = score
                best = (mx, my)
    return best


# --------------------------------------------------------------------------
# validation (the gate re-checks everything the construction promised)
# --------------------------------------------------------------------------


def _point_on_segment(point: tuple[float, float], seg: Segment, eps: float = 0.51) -> bool:
    (ax, ay), (bx, by) = seg.points()
    if abs(ax - bx) < 1e-9:  # vertical
        return (
            abs(point[0] - ax) <= eps
            and min(ay, by) - eps <= point[1] <= max(ay, by) + eps
        )
    if abs(ay - by) < 1e-9:  # horizontal
        return (
            abs(point[1] - ay) <= eps
            and min(ax, bx) - eps <= point[0] <= max(ax, bx) + eps
        )
    return False


#: An endpoint this close to *another* segment of its own net is a short
#: overhang past a junction rather than a floating end (measured: 4 units on
#: the golden page). A transform defect moves endpoints by tens or hundreds of
#: units, so this tolerance cannot hide one.
ENDPOINT_OVERHANG_TOLERANCE = 10.0


def _segment_distance(point: tuple[float, float], seg: Segment) -> float:
    """Distance from a point to a Manhattan segment (0 when it lies on it)."""
    (ax, ay), (bx, by) = seg.points()
    if abs(ax - bx) < 1e-9:  # vertical
        dy = max(min(ay, by) - point[1], 0.0, point[1] - max(ay, by))
        return math.hypot(point[0] - ax, dy)
    if abs(ay - by) < 1e-9:  # horizontal
        dx = max(min(ax, bx) - point[0], 0.0, point[0] - max(ax, bx))
        return math.hypot(point[1] - ay, dx)
    return float("inf")


def _segment_crosses_rect(seg: Segment, rect: Rect) -> bool:
    """True when the segment's interior intersects the rect's interior."""
    (ax, ay), (bx, by) = seg.points()
    if abs(ax - bx) < 1e-9:  # vertical
        if not (rect.x0 < ax < rect.x1):
            return False
        lo, hi = sorted((ay, by))
        return min(hi, rect.y1) > max(lo, rect.y0)
    if abs(ay - by) < 1e-9:  # horizontal
        if not (rect.y0 < ay < rect.y1):
            return False
        lo, hi = sorted((ax, bx))
        return min(hi, rect.x1) > max(lo, rect.x0)
    return False


def validate_full(
    model: DesignModel,
    placements: list[Placement],
    routes: list[RoutedNet],
    pin_positions: dict[tuple[str, str], tuple[float, float]],
    *,
    frame: Rect | None = None,
    title_block: Rect | None = None,
    annotation_points: list[tuple[float, float]] | None = None,
) -> list[Violation]:
    """The gate: all five constraints against the finished geometry.

    ``pin_positions`` must be the *true* pin tips (canvas space). The v1
    replay feeds the true tips against v1's mirrored wire endpoints — that
    is exactly how the 0.3.x sign bug becomes a counted violation.

    ``frame`` / ``title_block`` override the calibration constants with
    *measured* geometry (task 006b: the target page's own sheet bbox and the
    ratio-derived keep-out). Defaults keep the solver path unchanged.

    ``annotation_points`` are the positions of the plan's flags / labels: a
    wire endpoint that carries a net annotation is a legal terminal (that is
    what the annotation is *for* — the reference rule set says a label must
    touch its wire, so the wire is expected to end there).
    """
    violations: list[Violation] = []
    sheet = frame if frame is not None else Rect(0.0, 0.0, SHEET_WIDTH, SHEET_HEIGHT)
    boxes = [(p.designator, p.bbox) for p in placements if p.bbox]
    title = title_block if title_block is not None else Rect(*TITLE_BLOCK)

    # --- constraint 1: placement
    for des, box in boxes:
        if (
            box.x0 < sheet.x0
            or box.y0 < sheet.y0
            or box.x1 > sheet.x1
            or box.y1 > sheet.y1
        ):
            violations.append(
                Violation(
                    "OUT_OF_SHEET",
                    f"component {des}",
                    f"box ({box.x0:.0f},{box.y0:.0f})-({box.x1:.0f},{box.y1:.0f}) "
                    "leaves the sheet frame",
                )
            )
        if box.intersects(title):
            violations.append(
                Violation(
                    "PLACEMENT_ON_TITLE_BLOCK",
                    f"component {des}",
                    "box enters the title block",
                )
            )
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            d1, b1 = boxes[i]
            d2, b2 = boxes[j]
            if b1.intersects(b2):
                violations.append(
                    Violation("BOX_OVERLAP", f"components {d1} and {d2}", "bounding boxes overlap")
                )

    # --- wires per net, with the pin-tip registry
    tips_by_net: dict[str, list[tuple[float, float]]] = {}
    pin_owner: dict[tuple[float, float], str] = {}
    for (des, pin), (x, y) in pin_positions.items():
        for net_name, net in model.nets.items():
            if (des, pin) in net.pins:
                tips_by_net.setdefault(net_name, []).append((x, y))
                pin_owner[(round(x, 2), round(y, 2))] = des

    all_segments: list[Segment] = []
    for route in routes:
        for poly in route.polylines:
            for (ax_, ay_), (bx_, by_) in zip(poly, poly[1:]):
                all_segments.append(Segment(ax_, ay_, bx_, by_, route.net))

    # --- constraints 2/3: Manhattan, in-frame, off the title block, boxes
    for seg in all_segments:
        if not seg.is_manhattan():
            violations.append(
                Violation("NON_MANHATTAN", f"net {seg.net}", f"segment {seg.points()} is diagonal")
            )
        for px, py in seg.points():
            if not (
                sheet.x0 <= px <= sheet.x1 and sheet.y0 <= py <= sheet.y1
            ):
                violations.append(
                    Violation(
                        "WIRE_OUT_OF_SHEET",
                        f"net {seg.net}",
                        f"endpoint ({px:.0f},{py:.0f}) outside the frame",
                    )
                )
            if title.contains_point(px, py):
                violations.append(
                    Violation(
                        "WIRE_ON_TITLE_BLOCK",
                        f"net {seg.net}",
                        f"point ({px:.0f},{py:.0f}) inside the title block",
                    )
                )
        for des, box in boxes:
            if not _segment_crosses_rect(seg, box):
                continue
            owner_hit = any(
                pin_owner.get((round(px, 2), round(py, 2))) == des for px, py in seg.points()
            )
            if not owner_hit:
                violations.append(
                    Violation(
                        "WIRE_THROUGH_BOX",
                        f"net {seg.net}",
                        f"segment {seg.points()} crosses component {des}'s box",
                    )
                )

    # --- constraint 2: polyline endpoints are pin tips or same-net junctions
    for route in routes:
        segs = [
            Segment(ax_, ay_, bx_, by_, route.net)
            for poly in route.polylines
            for (ax_, ay_), (bx_, by_) in zip(poly, poly[1:])
        ]
        tips = tips_by_net.get(route.net, [])
        anchors = [
            (round(x, 2), round(y, 2)) for x, y in (annotation_points or [])
        ]
        for poly in route.polylines:
            for endpoint in (poly[0], poly[-1]):
                if any(
                    abs(endpoint[0] - tx) < 0.51 and abs(endpoint[1] - ty) < 0.51
                    for tx, ty in tips
                ):
                    continue
                if any(
                    abs(endpoint[0] - ax) < 0.51 and abs(endpoint[1] - ay) < 0.51
                    for ax, ay in anchors
                ):
                    continue  # a name-bearing end is a terminal by definition
                on_other = sum(1 for s in segs if _point_on_segment(endpoint, s))
                if on_other < 2:
                    # An endpoint a few units past a junction is a *overhang*
                    # the human drew, not a floating end: measured on the
                    # golden page, one VCC leg runs 4 units beyond the flag's
                    # junction. A transform defect moves endpoints by tens or
                    # hundreds of units, so a short tolerance cannot hide one.
                    if any(
                        not _point_on_segment(endpoint, s)
                        and _segment_distance(endpoint, s) <= ENDPOINT_OVERHANG_TOLERANCE
                        for s in segs
                    ):
                        continue
                    violations.append(
                        Violation(
                            "ENDPOINT_NOT_TERMINAL",
                            f"net {route.net}",
                            f"endpoint ({endpoint[0]:.0f},{endpoint[1]:.0f}) is neither "
                            "a pin tip nor a same-net junction",
                        )
                    )

    # --- cross-net: an ENDPOINT on a foreign wire is a junction dot = short
    endpoints_by_net: dict[str, list[tuple[float, float]]] = {}
    segs_by_net: dict[str, list[Segment]] = {}
    for route in routes:
        endpoints_by_net[route.net] = [
            poly[i] for poly in route.polylines if len(poly) >= 2 for i in (0, len(poly) - 1)
        ]
        for poly in route.polylines:
            for (ax_, ay_), (bx_, by_) in zip(poly, poly[1:]):
                segs_by_net.setdefault(route.net, []).append(
                    Segment(ax_, ay_, bx_, by_, route.net)
                )
    net_names = sorted(segs_by_net)
    for i, net_a in enumerate(net_names):
        for net_b in net_names[i + 1:]:
            for ep in endpoints_by_net.get(net_a, []):
                for seg in segs_by_net[net_b]:
                    if _point_on_segment(ep, seg):
                        violations.append(
                            Violation(
                                "CROSS_NET_SHORT",
                                f"net {net_a} endpoint ({ep[0]:.0f},{ep[1]:.0f})",
                                f"lands on net {net_b}'s wire — the editor would "
                                "junction-dot it into a short",
                            )
                        )
            for ep in endpoints_by_net.get(net_b, []):
                for seg in segs_by_net[net_a]:
                    if _point_on_segment(ep, seg):
                        violations.append(
                            Violation(
                                "CROSS_NET_SHORT",
                                f"net {net_b} endpoint ({ep[0]:.0f},{ep[1]:.0f})",
                                f"lands on net {net_a}'s wire — the editor would "
                                "junction-dot it into a short",
                            )
                        )

    # --- constraints 4/5: annotations on-wire and clear
    for route in routes:
        if route.attach is None:
            # pure wire carriers (replays of older generators) carry no
            # annotation of their own — only annotation-bearing routes
            # must have an on-wire point
            if route.kind != "wire":
                violations.append(
                    Violation(
                        "NO_ATTACH_POINT",
                        f"net {route.net}",
                        "the router found no on-wire attach point",
                    )
                )
            continue
        ax, ay = route.attach
        segs = [
            Segment(px, py, qx, qy, route.net)
            for poly in route.polylines
            for (px, py), (qx, qy) in zip(poly, poly[1:])
        ]
        if not any(_point_on_segment(route.attach, s) for s in segs):
            violations.append(
                Violation(
                    "FLAG_NOT_ON_WIRE",
                    f"net {route.net}",
                    f"annotation at ({ax:.0f},{ay:.0f}) floats off the net's wires",
                )
            )
        net = model.nets.get(route.net)
        members = {des for des, _pin in net.pins} if net else set()
        for des, box in boxes:
            if des in members:
                continue
            if box.distance_to_point(ax, ay) < LABEL_CLEARANCE:
                violations.append(
                    Violation(
                        "LABEL_TOO_CLOSE",
                        f"net {route.net}",
                        f"annotation at ({ax:.0f},{ay:.0f}) is within "
                        f"{LABEL_CLEARANCE:.0f} of component {des}'s box",
                    )
                )
    return violations


# --------------------------------------------------------------------------
# 006b: annotation lint (self-produced, per-category detail)
# --------------------------------------------------------------------------
#
# The reference gate's DRC only reports an aggregate count; 岳翔宇's ruling is
# that the per-item detail has to come from our own stack. These four
# categories are the ones a human reads as "unreadable": a name that floats
# off its wire, two names stacked on each other, a name sitting on a part, a
# name inside the title block.
#
# Predicted marker boxes come from the reference implementation's *measured*
# values (its `getPrimitivesBBox` calibration): a power/ground flag's box is
# 11x6 / 6x11 and the net-name text band runs 6 units per character with a
# floor of 31 units. Using one prediction function for both generation and
# checking is the reference's own hard-won rule — two rulers always disagree.

#: Height of a net-name text band, canvas units. Measured *down* from the
#: human's own label spacing on the golden page: the RX/TX/D+/D- labels are
#: 10 units apart and read cleanly, so the band has to be under 10.
LABEL_TEXT_HEIGHT = 9.0

#: Net-name text width: 6 units per character (reference-calibrated), with a
#: small floor. The reference's 31-unit floor belongs to *net ports* (whose
#: arrow box is padded); a net label is just text, and using 31 there made the
#: human's own "TX" label "overlap" a neighbouring capacitor.
LABEL_CHAR_WIDTH = 6.0
LABEL_MIN_TEXT_WIDTH = 12.0


def annotation_box(
    x: float, y: float, net: str, flag_body: Rect | None = None
) -> Rect:
    """Predicted rendered box of a net annotation.

    Without ``flag_body`` (a net *label*) the box is the text band centred on
    the anchor. With it (a power/ground *flag*), the box is the flag's own
    **measured** glyph — a flag draws its body offset from the electrical
    anchor, 10..19 units out on this library — unioned with the text band
    placed on the far side of the glyph, which is where both the reference
    calibration and the golden page put the net name.
    """
    width = max(LABEL_MIN_TEXT_WIDTH, LABEL_CHAR_WIDTH * len(net))
    if flag_body is None:
        half = width / 2.0
        return Rect(
            x - half, y - LABEL_TEXT_HEIGHT / 2.0, x + half, y + LABEL_TEXT_HEIGHT / 2.0
        )
    mid_x = (flag_body.x0 + flag_body.x1) / 2.0
    mid_y = (flag_body.y0 + flag_body.y1) / 2.0
    dx = mid_x - x
    dy = mid_y - y
    if abs(dx) >= abs(dy):
        band = (
            Rect(flag_body.x1, mid_y - LABEL_TEXT_HEIGHT / 2.0, flag_body.x1 + width,
                 mid_y + LABEL_TEXT_HEIGHT / 2.0)
            if dx >= 0
            else Rect(flag_body.x0 - width, mid_y - LABEL_TEXT_HEIGHT / 2.0,
                      flag_body.x0, mid_y + LABEL_TEXT_HEIGHT / 2.0)
        )
    else:
        band = (
            Rect(mid_x - width / 2.0, flag_body.y1, mid_x + width / 2.0,
                 flag_body.y1 + LABEL_TEXT_HEIGHT)
            if dy >= 0
            else Rect(mid_x - width / 2.0, flag_body.y0 - LABEL_TEXT_HEIGHT,
                      mid_x + width / 2.0, flag_body.y0)
        )
    return Rect(
        min(flag_body.x0, band.x0), min(flag_body.y0, band.y0),
        max(flag_body.x1, band.x1), max(flag_body.y1, band.y1),
    )


def lint_annotations(
    placements: list[Placement],
    routes: list[RoutedNet],
    net_names: list[Any],
    title_block: Rect | None = None,
    boxes: list[Rect] | None = None,
    members_by_net: dict[str, set[str]] | None = None,
) -> list[Violation]:
    """Four annotation categories, one violation row each.

    ``net_names`` are the plan's naming steps (anything with ``net``/``x``/
    ``y`` attributes — ``generate.NetNameStep`` is the concrete type; the
    signature stays duck-typed so this module keeps its "no engine imports"
    rule). ``boxes`` are pre-computed predicted marker boxes, parallel to
    ``net_names``; the replay passes them because it knows each flag's
    measured glyph, and generation and checking must use the same ruler.

    Every annotation must sit on one of *its own* net's wire segments — the
    editor does not treat an overlapping marker and pin coordinate as a
    connection (EasyEDA electrical rules), so a floating name is not merely
    ugly.
    """
    violations: list[Violation] = []
    segs_by_net: dict[str, list[Segment]] = {}
    for route in routes:
        bucket = segs_by_net.setdefault(route.net, [])
        for poly in route.polylines:
            for (px, py), (qx, qy) in zip(poly, poly[1:]):
                bucket.append(Segment(px, py, qx, qy, route.net))

    boxes_by_part = [(p.designator, p.bbox) for p in placements if p.bbox]

    predicted: list[tuple[Any, Rect]] = []
    for index, step in enumerate(net_names):
        net = str(getattr(step, "net", "") or "")
        x = float(getattr(step, "x", 0.0))
        y = float(getattr(step, "y", 0.0))
        box = boxes[index] if boxes and index < len(boxes) else annotation_box(x, y, net)
        predicted.append((step, box))

        own = segs_by_net.get(net, [])
        if not any(_point_on_segment((x, y), seg) for seg in own):
            violations.append(
                Violation(
                    "LABEL_FLOATS",
                    f"net {net}",
                    f"annotation at ({x:.0f},{y:.0f}) is not on any of its own wires",
                )
            )
        for des, part_box in boxes_by_part:
            if des in (members_by_net or {}).get(net, set()):
                continue  # a name next to its own net's part is normal
            if part_box.intersects(box):
                violations.append(
                    Violation(
                        "LABEL_ON_COMPONENT",
                        f"net {net}",
                        f"annotation at ({x:.0f},{y:.0f}) overlaps component {des}",
                    )
                )
        if title_block is not None and box.intersects(title_block):
            violations.append(
                Violation(
                    "LABEL_ON_TITLE_BLOCK",
                    f"net {net}",
                    f"annotation at ({x:.0f},{y:.0f}) falls inside the title block",
                )
            )

    for i in range(len(predicted)):
        step_a, box_a = predicted[i]
        for j in range(i + 1, len(predicted)):
            step_b, box_b = predicted[j]
            if not box_a.intersects(box_b):
                continue
            violations.append(
                Violation(
                    "LABEL_OVERLAP",
                    f"nets {getattr(step_a, 'net', '?')} and {getattr(step_b, 'net', '?')}",
                    f"annotations at ({getattr(step_a, 'x', 0):.0f},{getattr(step_a, 'y', 0):.0f})"
                    f" and ({getattr(step_b, 'x', 0):.0f},{getattr(step_b, 'y', 0):.0f}) overlap",
                )
            )
    return violations


def lint_report(violations: list[Violation]) -> list[str]:
    """One rendered line per violation, plus a per-code tally line."""
    if not violations:
        return ["layout lint: 0 violations"]
    lines = [v.render() for v in violations]
    tally: dict[str, int] = {}
    for v in violations:
        tally[v.code] = tally.get(v.code, 0) + 1
    summary = ", ".join(f"{code} x{count}" for code, count in sorted(tally.items()))
    lines.append(f"layout lint: {len(violations)} violation(s) — {summary}")
    return lines
