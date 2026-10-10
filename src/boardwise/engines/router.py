"""The orthogonal obstacle-avoiding search, shared (112).

`engines/drawcompiler.py` has carried this router since 053: obstacle boxes,
foreign wire edges, blocked points, and a Dijkstra over ``(node, arrival
direction)`` so a bend can be priced. The interactive draw flows
(`addcomponent.wire_route`, and through it `cli.py`'s four wire-drawing sites and
`engines/moveblock.py`'s redraw) could only emit a straight run or one L, so the
page's own routing could walk through a part body — 110's pressed-through
flyback page is the measured instance.

**One search, not two.** A second implementation of "a legal wire" would
eventually disagree with the one the readability checker grades against, and
that disagreement would only ever show up as a drawing the checker refuses. So
the class moved here verbatim; `drawcompiler` imports it back under its own
names, and its compiled output is byte-for-byte what it was (the zero-move gate
in `outputs/112/SUMMARY.md` is the evidence).

**What lives here and why.** The router needs float-tolerant equality (`_key`,
`_close`, `_rounded`), an interior clip test (`_segment_hits_box`), a
collinear-overlap test (`_collinear_overlap`), a tee test
(`_strictly_on_segment`) and a "is this point on that wire" test
(`_on_polyline`, whose two names the route and the segment checks share).
Every one of those is also used elsewhere in `drawcompiler`, so `drawcompiler`
imports them back rather than keeping a second copy — a second copy of
`_segment_hits_box` is a second opinion about where a body begins.

**What does not.** `_compress` (collapse collinear runs) is *not* the router's:
`_Router.route` returns raw lattice nodes and never calls it, while
`drawcompiler` runs every emitted segment through it and `pagecompiler` uses it
under the name `compress_path`. It stays in `drawcompiler`.

The lattice a router is handed is `residue + n * grid`, in canvas units — the
same 5-unit grid `engines/readability.py` calls "the same column or row".
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from heapq import heappop, heappush

from boardwise.core.symbolprofile import Box

#: Costs in lattice steps: a bend is worth staying straight, and crossing a
#: foreign wire perpendicularly is allowed but not free.
TURN_COST = 0.6
CROSS_COST = 2.0


def _rounded(point: tuple[float, float]) -> tuple[float, float]:
    """Trim float noise from a rotation (``cos(90°)`` is 6.1e-17, not 0)."""
    return (round(point[0], 6), round(point[1], 6))


def _close(left: float, right: float, tol: float = 1e-6) -> bool:
    return abs(left - right) <= tol


def _segment_hits_box(start: tuple[float, float], end: tuple[float, float], box: Box) -> bool:
    """Does the segment have a positive-length run inside the box's interior?

    The slab test the readability checker's own `_clip_to_box` uses (Liang–Barsky
    against the box inset by a hair): a wire lying exactly on an outline, or
    touching only a corner, is not crossing the box.
    """
    left, bottom, right, top = box[0] + 1e-6, box[1] + 1e-6, box[2] - 1e-6, box[3] - 1e-6
    if right <= left or top <= bottom:
        return False
    dx, dy = end[0] - start[0], end[1] - start[1]
    low, high = 0.0, 1.0
    for p, q in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - bottom),
        (dy, top - start[1]),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            if ratio > high:
                return False
            low = max(low, ratio)
        else:
            if ratio < low:
                return False
            high = min(high, ratio)
    return high - low > 1e-6

# -------------------------------------------------------------- the search


def _key(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 6), round(point[1], 6))


def _strictly_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    """Is `point` inside the segment, not at either end (the tee condition)?"""
    if _key(point) == _key(start) or _key(point) == _key(end):
        return False
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
        point[0] - start[0]
    )
    if abs(cross) > 1e-6:
        return False
    dot = (point[0] - start[0]) * (end[0] - start[0]) + (point[1] - start[1]) * (
        end[1] - start[1]
    )
    length = (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2
    return 0.0 < dot < length


def _on_polyline(point: tuple[float, float], points: Sequence[tuple[float, float]]) -> bool:
    for start, end in zip(points, points[1:]):
        if _key(point) == _key(start) or _key(point) == _key(end):
            return True
        if _strictly_on_segment(point, start, end):
            return True
    return False


class _Router:
    """Orthogonal obstacle-avoiding search on the compilation lattice.

    The furniture, and why each piece is there:

    * **obstacle boxes** — part extents and text boxes (053 sec.4: "文字 bbox
      参与避障") plus the keep-outs. A step whose segment cuts a box's interior
      is refused, with the checker's own clip test, so a path this search calls
      clear is clear to the layer that grades it;
    * **blocked points** — foreign pin tips, foreign labels and flags, and other
      nets' wire vertices. A wire vertex on any of them is a *connection* in the
      editor's model, which is exactly the short the readability contract
      refuses, so they are walls;
    * **foreign edges** — another net's wire. Its interior may be crossed
      perpendicularly (measured editor behaviour: a plain crossing does not
      join), but never run along, and never turned on: a turn or a parallel run
      would put a vertex of one wire on the other, which does join;
    * **cost** — a step costs one, a bend costs :data:`TURN_COST`, a crossing
      costs :data:`CROSS_COST`. The trunk is tried before any search, so the
      search only ever spends bends on what the trunk cannot reach;
    * **reserved points** (145a) — the lattice nodes a **lead this plan will draw**
      needs: a flag's lead, or a label's name stub (145a2). Those are drawn
      *after* the wires on this page, so without a reservation the wires take the
      lane and the lead is then either hung across one (074's defect) or refused
      / pushed off the side it belongs on. The reservation is the wiring order's
      missing half: `drawcompiler._lead_lane_reservations` decides each lead's
      lane *before* anything is routed, and every wire of another net treats
      those nodes as walls. Empty by default, so a router that knows nothing
      about leads behaves exactly as before.
    """

    def __init__(
        self,
        *,
        grid: float,
        residue: tuple[float, float],
        boxes: Sequence[Box],
        bounds: Box,
    ) -> None:
        self.grid = grid
        self.residue = residue
        self.boxes = list(boxes)
        self.bounds = bounds
        self.blocked: set[tuple[float, float]] = set()
        self.edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
        #: The net each edge belongs to, in step with ``edges`` (074): a refusal
        #: that says *which* foreign wire a lead ran through has to be able to name
        #: it, and "another net's run" is not a name. Both writers of ``edges`` in
        #: this module keep the two lists the same length —
        #: :func:`_set_foreign_edges`, which records the net of every run it
        #: collects, and :meth:`add_edge`, which reaches for no net in particular
        #: and so records none. A caller that assigns ``edges`` itself (057's page
        #: router does) leaves the names behind, and a reader that finds the two
        #: lists out of step reports the run without naming its net rather than
        #: naming the wrong one.
        self.edge_nets: list[str] = []
        #: 145a: the lattice nodes (**point -> owning net**) another net's flag
        #: lead has been promised. A wire of a different net may neither stand on
        #: one nor cross one, so a lane an earlier pass reserved stays usable
        #: when the flag is drawn at the end. Empty unless the caller reserves.
        self.reserved: dict[tuple[float, float], str] = {}
        #: The net being placed right now: its own reservations do not block it.
        self.reserved_exempt: str = ""
        #: 145a: set while the **reservation pass** is deciding the lanes, so its
        #: own search may not swallow a lane another flag already holds. Off for
        #: everything else — see `drawcompiler._flag_room`.
        self.reserve_strict: bool = False

    # ------------------------------------------------------------ geometry

    def node(self, point: tuple[float, float]) -> tuple[int, int]:
        return (
            round((point[0] - self.residue[0]) / self.grid),
            round((point[1] - self.residue[1]) / self.grid),
        )

    def point(self, node: tuple[int, int]) -> tuple[float, float]:
        return _rounded((
            self.residue[0] + node[0] * self.grid,
            self.residue[1] + node[1] * self.grid,
        ))

    def add_edge(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        if _key(start) != _key(end):
            self.edges.append((start, end))
            # ``edge_nets`` stays the same length as ``edges`` (see the attribute's
            # own note): a run added here is not being drawn by any one net.
            self.edge_nets.append("")

    def _in_bounds(self, node: tuple[int, int]) -> bool:
        point = self.point(node)
        return (
            self.bounds[0] - 1e-6 <= point[0] <= self.bounds[2] + 1e-6
            and self.bounds[1] - 1e-6 <= point[1] <= self.bounds[3] + 1e-6
        )

    def _wall(self, node: tuple[int, int]) -> bool:
        point = self.point(node)
        if _key(point) in self.blocked:
            return True
        owner = self.reserved.get(_key(point))
        if owner is not None and owner != self.reserved_exempt:
            return True
        for box in self.boxes:
            if (
                box[0] - 1e-6 < point[0] < box[2] + 1e-6
                and box[1] - 1e-6 < point[1] < box[3] + 1e-6
            ):
                return True
        return False

    def _step_free(
        self, node: tuple[int, int], other: tuple[int, int]
    ) -> bool:
        start = self.point(node)
        end = self.point(other)
        for box in self.boxes:
            if _segment_hits_box(start, end, box):
                return False
        for foreign in self.edges:
            if _collinear_overlap(start, end, foreign[0], foreign[1]):
                return False
        return True

    def crossing_at(self, point: tuple[float, float]) -> tuple[int, int] | None:
        """Is this point inside a foreign wire's span? (the join condition)"""
        return self._crossing(self.node(point))

    def _crossing(self, node: tuple[int, int]) -> tuple[int, int] | None:
        """The axis of the foreign edge this node lies inside, if any.

        A node inside a foreign wire's span is the one place a crossing can
        happen — and it may only be *crossed*, never turned on or run along,
        which is what the caller's stepping rules enforce from this answer.
        """
        point = self.point(node)
        for start, end in self.edges:
            if _strictly_on_segment(point, start, end):
                return (1, 0) if _close(start[1], end[1]) else (0, 1)
        return None

    # --------------------------------------------------------------- search

    def route(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
        *,
        targets: Sequence[tuple[float, float]] | None = None,
    ) -> list[tuple[float, float]] | None:
        """A cheapest orthogonal path from `start` to `goal` (or to any target).

        A* over ``(node, arrival direction)`` so a turn can be priced, with the
        stepping rules above. ``None`` means "not found inside the corridor the
        caller gave", which is what the caller reports — never "no solution".

        **The heuristic is what keeps this from being pathological** (116's
        performance post-mortem). Plain Dijkstra expands every state whose cost
        is at or below the answer, and the answer is roughly the Manhattan
        distance between the two pins — so the work is the *area of a diamond*
        around the route, over the whole page corridor. On the flyback page that
        is 52,800 lattice points × 4 arrival directions, and two of the nets
        116's order pass moved far enough to need a long detour took **98s and
        39s** each: 432s of a 433s compile, 1.57 billion function calls, with
        :meth:`_crossing` and :meth:`_step_free` rescanning every box and every
        foreign edge for every one of those states. The search was not wrong,
        it was quadratic in the page.

        The heuristic is the **Manhattan distance in lattice steps to the
        nearest goal**, in the same unit as an edge (one step costs 1.0), and a
        turn or a crossing only ever *adds* cost. That makes it admissible: it
        never overestimates, so A* still returns a path of the **same optimal
        cost** Dijkstra would — the same cheapest wire, not merely a cheap one.
        Expansion is now confined to the corridor around the optimal path rather
        than the whole page, which is the whole of the difference. The five
        existing grammars' 83 previews are byte-identical before and after
        (``tools/116_zero_move.py``), which is the check that a tie did not
        quietly reroute a wire.
        """
        goal_nodes = {self.node(point) for point in (targets or [goal])}
        start_node = self.node(start)
        if start_node in goal_nodes:
            return [self.point(start_node)]
        nearest = _nearest(goal_nodes)

        def estimate(node: tuple[int, int]) -> float:
            return float(
                abs(node[0] - nearest[0]) + abs(node[1] - nearest[1])
            )

        # Per-**call** memo of the two geometry answers the inner loop asks for
        # at every node. It is per call on purpose: ``self.edges`` is rebuilt and
        # appended to as each net is routed (``_set_foreign_edges``), so an
        # answer cached on the instance would be stale for the next net. Within
        # one search the foreign wires do not move, so the answer cannot change
        # and is asked for up to four times per node (once as ``other`` for each
        # of its neighbours, once as ``node`` on the way out).
        crossings: dict[tuple[int, int], tuple[int, int] | None] = {}
        walls: dict[tuple[int, int], bool] = {}

        def crossing_at_node(node: tuple[int, int]) -> tuple[int, int] | None:
            if node not in crossings:
                crossings[node] = self._crossing(node)
            return crossings[node]

        def wall_at_node(node: tuple[int, int]) -> bool:
            if node not in walls:
                walls[node] = self._wall(node)
            return walls[node]

        # The heap carries ``(f, counter, node, arrived, g)``: the A* priority
        # and the real cost both, so a stale entry is recognised by comparing its
        # own ``g`` with the ``g`` table rather than by re-deriving anything.
        frontier: list[tuple[float, int, tuple[int, int], int, float]] = []
        counter = 0
        heappush(frontier, (estimate(start_node), counter, start_node, 4, 0.0))
        best: dict[tuple[tuple[int, int], int], float] = {(start_node, 4): 0.0}
        parent: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
        while frontier:
            _, _, node, arrived, cost = heappop(frontier)
            state_in = (node, arrived)
            if best.get(state_in, math.inf) < cost - 1e-9:
                continue  # superseded while this entry sat in the heap
            if node in goal_nodes:
                return self._unwind(state_in, parent, start_node)
            here = crossing_at_node(node)
            for index, (dx, dy) in enumerate(steps):
                other = (node[0] + dx, node[1] + dy)
                if not self._in_bounds(other) or wall_at_node(other):
                    continue
                direction = index
                if not self._step_free(node, other):
                    continue
                moving = (1, 0) if dx != 0 else (0, 1)
                if here is not None and here == moving:
                    continue  # running along a foreign wire from inside it
                if here is not None and arrived < 4 and direction != arrived:
                    continue  # a crossing may not be turned on
                there = crossing_at_node(other)
                if there is not None and there == moving:
                    continue  # entering a foreign wire lengthwise
                total = cost + 1.0
                if arrived < 4 and arrived != direction:
                    total += TURN_COST
                if there is not None:
                    total += CROSS_COST
                state = (other, direction)
                if best.get(state, math.inf) <= total + 1e-9:
                    continue
                best[state] = total
                parent[state] = (node, arrived)
                counter += 1
                heappush(frontier, (
                    total + estimate(other), counter, other, direction, total))
        return None

    def _unwind(
        self,
        state: tuple[tuple[int, int], int],
        parent: Mapping[tuple[tuple[int, int], int], tuple[tuple[int, int], int]],
        start_node: tuple[int, int],
    ) -> list[tuple[float, float]]:
        nodes = [state[0]]
        while state[0] != start_node:
            state = parent[state]
            nodes.append(state[0])
        nodes.reverse()
        return [self.point(node) for node in nodes]

def _nearest(nodes: set[tuple[int, int]]) -> tuple[int, int]:
    """One of `nodes` to measure the heuristic against.

    Any member is admissible — the Manhattan distance to *a* goal is a lower
    bound on the distance to *the nearest* one — so this is a speed choice, not
    a correctness one, and picking the first keeps the search deterministic
    (two runs of one input must draw the same wire, 053 stage A).
    """
    return min(nodes)


def _collinear_overlap(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    """Do two segments lie on one line and share more than a point?

    A parallel run along a foreign wire is the case that must not happen: the
    editor joins wires that overlap, and a vertex of one on the other is a short.
    """
    if _close(a[1], b[1]) and _close(c[1], d[1]) and _close(a[1], c[1]):
        low = max(min(a[0], b[0]), min(c[0], d[0]))
        high = min(max(a[0], b[0]), max(c[0], d[0]))
        return high - low > 1e-6
    if _close(a[0], b[0]) and _close(c[0], d[0]) and _close(a[0], c[0]):
        low = max(min(a[1], b[1]), min(c[1], d[1]))
        high = min(max(a[1], b[1]), max(c[1], d[1]))
        return high - low > 1e-6
    return False


#: Public names for the two pieces an outside caller legitimately needs: the
#: class itself (the search) and the clip test (the only honest way to ask
#: "does this run cut a body?", since a second, looser copy of it would answer
#: differently from the one the router obeys).
Router = _Router
segment_hits_box = _segment_hits_box
collinear_overlap = _collinear_overlap
