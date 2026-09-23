"""`add-component`: placing the part a `decap-required-caps` finding is missing (029-a).

016 changed a string; this slice **creates** a part and connects it, so the
questions change shape: where does it land, what number does it get, how is it
joined to its net, and how does a second run know the work is already done. All
four are decided here, offline and pure, so they can be tested — and refused —
without an editor, a daemon or a socket.

Three rules the rest of the slice leans on:

* **The idempotence probe is the rule's own judgement** (§二.5). It is not
  re-implemented here: :func:`probe_already_applied` calls
  `rules.decap.cap_candidates_on` (the rule's inventory of grounded capacitors
  on a net) and `rules.decap.decide_required_cap` (the rule's comparison). A
  second, similar-looking judgement is exactly what the task book forbids, and
  "the two agreed last week" is not a property either of them can hold.
* **Determinism, never convenience.** The designator is the lowest free number
  for its prefix, the landing spot is a fixed ladder from the anchor, and the
  connection is decided by two named rules rather than by whichever call would
  succeed. Two runs of the same plan therefore produce the same numbers, and a
  reviewer can predict both before reading the code.
* **Refusals say what is missing.** An exhausted ladder names the positions it
  tried and what occupies them; a net that cannot be connected names both
  options that were checked. No fallback to the origin, and no unannounced
  label: a label is a named outcome of `choose_connection` (the page's own habit
  for that net, or the ground exception of 029-c), never something apply slips in
  when a wire would not reach. The M2 rules ("don't connect by label and call it
  done", "don't quietly choose") are enforced by the shape of that decision, not
  by a comment.

Nothing here talks to the bridge: the geometry it reads is a `sch.geometry`
dump, which the CLI fetches.

It lives in `engines/` rather than `core/` for the layer rule's sake
(`tests/test_layer_rules.py`): it *uses* a rule's judgement (§二.5) and a plan's
types, and `core` is allowed to import nothing from inside the package.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..rules.decap import CapDecision, CapCandidate, cap_candidates_on, decide_required_cap

#: The landing ladder's step, in canvas units. Deliberately the same 5-unit grid
#: `engines/layout.py` routes on (asserted in the tests): placing a part off the
#: grid would make every later wire either diagonal or off-grid, and this slice
#: inherits draw.py's wiring discipline rather than inventing one.
LANDING_GRID = 5.0

#: How far apart two component origins must be for the further one to count as
#: free space. One grid: a part whose origin sits *on* another part's cell is a
#: collision, and 5 units away is close enough to be suspicious.
LANDING_CLEARANCE = 5.0

#: The fixed ladder (§二.4), as grid offsets in the order the task book names:
#: the ideal spot, then up / down / left / right one grid, then the same at two
#: grids. Written down once, in one place, because "deterministic" is only true
#: if the order is data rather than a loop that someone later reorders.
LADDER: tuple[tuple[int, int], ...] = (
    (0, 0),
    (0, -1),
    (0, 1),
    (-1, 0),
    (1, 0),
    (0, -2),
    (0, 2),
    (-2, 0),
    (2, 0),
)

#: How close an existing piece of the target net must be to the landing spot for
#: a short wire to be an honest connection option, in canvas units. 100 units is
#: 1 inch at 0.01-inch schematic units — the distance at which a decoupling
#: capacitor stops being a decoupling capacitor, which is the same engineering
#: limit the facts shelf quotes ("within 0.5 inch of the pin").
CONNECT_RADIUS = 100.0

_DESIGNATOR_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


class LadderExhausted(Exception):
    """No position in the ladder is free.

    Carries what it tried and what got in the way: a refusal that cannot name
    the conflict is a refusal the operator cannot act on, and acting on it by
    hand is the whole point of the message.
    """

    def __init__(self, tried: Sequence[tuple[float, float]], occupied: Sequence[tuple[float, float]]):
        self.tried = list(tried)
        self.occupied = list(occupied)
        super().__init__(
            "every position in the landing ladder is occupied "
            f"({len(self.tried)} tried: "
            + ", ".join(f"({x:g}, {y:g})" for x, y in self.tried)
            + ")"
            + (
                "; nearest occupied: "
                + ", ".join(f"({x:g}, {y:g})" for x, y in self.occupied[:3])
                if self.occupied
                else ""
            )
        )


class NoConnectionOption(Exception):
    """No nearby wire of that net, no label of it on the page, not a ground net.

    All three checks are named in the message (029-c added the ground exception),
    because the operator's next move — which wire to draw — depends on knowing
    which of them failed.
    """

    def __init__(self, net: str, detail: str):
        self.net = net
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class LandingSpot:
    """Where the part goes, and which rung of the ladder it took."""

    x: float
    y: float
    offset: tuple[int, int]
    index: int

    @property
    def stepped(self) -> bool:
        return self.index > 0


@dataclass(frozen=True)
class ConnectionChoice:
    """How the new part joins its net, and the evidence for that choice."""

    kind: str  # changeplan.CONNECTION_WIRE / CONNECTION_LABEL
    detail: str
    #: Where the wire ends, for a `wire` choice (a vertex of that net).
    to: tuple[float, float] | None = None


def _state_of(entry: Any) -> dict[str, Any]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def component_origins(geometry: Any) -> dict[str, tuple[float, float]]:
    """``designator -> (x, y)`` for every component the page reports.

    Designators ending in ``?`` are skipped: that is the editor's own notation
    for a part that has not been numbered, and half-placed parts are not
    occupancy evidence ("the spot is free") nor designator evidence.
    """
    origins: dict[str, tuple[float, float]] = {}
    if not isinstance(geometry, dict):
        return origins
    for entry in geometry.get("components") or []:
        state = _state_of(entry)
        name = _text(state.get("Designator")) or _text(
            (state.get("OtherProperty") or {}).get("Designator")
            if isinstance(state.get("OtherProperty"), dict)
            else ""
        )
        x, y = _number(state.get("X")), _number(state.get("Y"))
        if not name or name.endswith("?") or x is None or y is None:
            continue
        origins.setdefault(name, (x, y))
    return origins


def primitive_id_of(geometry: Any, designator: str) -> str:
    """The canvas id of one component, from a `sch.geometry` dump (029-c).

    Needed for the branch where the placement's outcome went unknown but the
    read-back shows the part anyway: the write's own answer carried no id, and
    the part's pins can only be read by id (`sch.component_pins`).
    """
    if not isinstance(geometry, dict):
        return ""
    for entry in geometry.get("components") or []:
        if not isinstance(entry, dict):
            continue
        state = _state_of(entry)
        name = _text(state.get("Designator"))
        if name == designator:
            return str(entry.get("primitiveId") or state.get("PrimitiveId") or "")
    return ""


def pin_points(payload: Any) -> dict[str, tuple[float, float]]:
    """``pinNumber -> (x, y)`` from a `sch.component_pins` answer (029-c).

    This is the coordinate a wire has to *start* at. Measured on 3.2.186: a
    placed capacitor's pins sit **20 units either side of its origin**, so a wire
    drawn from the landing spot (which is the origin) touches neither — 029-b
    read `1→NET4 ok` off one export and 029-c re-measured the same page as the
    part sitting on its own auto net, which is what a wire that reaches nothing
    looks like. The pin's reported `X`/`Y` is the connection end (the outer end
    of the pin's own length), which is the point the editor joins wires to.
    """
    points: dict[str, tuple[float, float]] = {}
    if not isinstance(payload, dict):
        return points
    for item in payload.get("pins") or []:
        if not isinstance(item, dict):
            continue
        number = _text(item.get("PinNumber")) or _text(item.get("PinName"))
        x, y = _number(item.get("X")), _number(item.get("Y"))
        if number and x is not None and y is not None:
            points.setdefault(number, (x, y))
    return points


def wire_route(
    anchor: tuple[float, float], target: tuple[float, float]
) -> list[tuple[float, float]]:
    """The polyline from a pin to its target, **orthogonal** by construction (029-c).

    Measured on 3.2.186: `sch.place_wire` with a diagonal segment never returns —
    the call hangs until the daemon's 30 s timeout, twice out of twice, while the
    same call with an axis-aligned segment answers in ~0.4 s. The corner goes at
    ``(anchor.x, target.y)``: the first run leaves the pin along the axis it points
    at, which keeps it clear of the neighbouring pin (a run along the pin row would
    cross the part's own body). Same discipline `engines/layout.py` routes on.
    """
    ax, ay = float(anchor[0]), float(anchor[1])
    tx, ty = float(target[0]), float(target[1])
    if ax == tx or ay == ty:
        return [(ax, ay), (tx, ty)]
    return [(ax, ay), (ax, ty), (tx, ty)]


def occupied_points(geometry: Any) -> list[tuple[float, float]]:
    """Every occupied page point a landing spot must not collide with.

    Component origins *and* wire vertices: a spot sitting on a wire is not free
    either — the part would land on top of the routing and the wire would look
    like it connected something it does not touch.
    """
    points = list(component_origins(geometry).values())
    for x, y, _net in wire_vertices(geometry):
        points.append((x, y))
    return points


def is_free(x: float, y: float, occupied: Iterable[tuple[float, float]]) -> bool:
    return all(
        abs(x - ox) >= LANDING_CLEARANCE or abs(y - oy) >= LANDING_CLEARANCE
        for ox, oy in occupied
    )


def landing_spot(
    origin: tuple[float, float],
    occupied: Sequence[tuple[float, float]],
    ladder: Sequence[tuple[int, int]] = LADDER,
    grid: float = LANDING_GRID,
) -> LandingSpot:
    """The first free rung of the fixed ladder from ``origin``.

    Raises :class:`LadderExhausted` when none is free — **never** falls back to
    the page origin: a decoupling capacitor dropped at (0, 0) is not a repaired
    board, it is a part in the corner, and the far end of that mistake is a
    design that looks fixed and is not (岳 M2 red line, §二.4).
    """
    tried: list[tuple[float, float]] = []
    for index, (dx, dy) in enumerate(ladder):
        x, y = origin[0] + dx * grid, origin[1] + dy * grid
        tried.append((x, y))
        if is_free(x, y, occupied):
            return LandingSpot(x=x, y=y, offset=(dx, dy), index=index)
    raise LadderExhausted(tried, occupied)


def allocate_designator(names: Iterable[str], prefix: str) -> str:
    """The lowest free ``<prefix><n>`` (n >= 1) among ``names`` (§二.3).

    The pool is what the page shows, so the number is reproducible from the
    page alone; apply re-checks it before writing, because a human may have
    placed a part in between.
    """
    wanted = prefix.upper()
    used: set[int] = set()
    for name in names:
        match = _DESIGNATOR_RE.match((name or "").strip())
        if not match:
            continue
        if match.group(1).upper() != wanted:
            continue
        used.add(int(match.group(2)))
    number = 1
    while number in used:
        number += 1
    return f"{prefix}{number}"


def net_label_names(geometry: Any) -> set[str]:
    """The net names this page already carries as labels (case-sensitive as written)."""
    names: set[str] = set()
    if not isinstance(geometry, dict):
        return names
    for entry in geometry.get("netlabels") or []:
        state = _state_of(entry)
        name = _text(state.get("Net")) or _text(state.get("Text")) or _text(
            state.get("Name")
        )
        if name:
            names.add(name)
        label = state.get("Label")
        if isinstance(label, dict):
            inner = _text(label.get("Net")) or _text(label.get("Text"))
            if inner:
                names.add(inner)
    return names


def wire_vertices(geometry: Any) -> list[tuple[float, float, str]]:
    """``(x, y, net)`` for every wire vertex, in the shape the host actually sends.

    Measured on 3.2.186 (029-b, 2026-09-23): a wire's state is
    ``{PrimitiveType: "Wire", Line: [x1, y1, x2, y2, …], Net: "NET4", …}`` — a
    **flat** coordinate list, and the net **is** carried by the wire. The earlier
    reading (``state.Points``, "wires carry no net") was wrong, and it made both
    the occupancy test and the wire option blind: a page with a wire in hand
    looked wire-less. Reading the real shape here is what lets the connection
    choice demand the *right* net instead of settling for the nearest one.
    """
    found: list[tuple[float, float, str]] = []
    if not isinstance(geometry, dict):
        return found
    for entry in geometry.get("wires") or []:
        state = _state_of(entry)
        net = _text(state.get("Net"))
        line = state.get("Line") or state.get("Points") or state.get("points") or []
        if isinstance(line, (list, tuple)) and line and not isinstance(line[0], (list, tuple)):
            coords = list(line)
            for index in range(0, len(coords) - 1, 2):
                x, y = _number(coords[index]), _number(coords[index + 1])
                if x is not None and y is not None:
                    found.append((x, y, net))
        else:
            for pair in line:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    x, y = _number(pair[0]), _number(pair[1])
                    if x is not None and y is not None:
                        found.append((x, y, net))
    return found


def nearest_wire_point(
    spot: tuple[float, float], geometry: Any, net: str = ""
) -> tuple[float, float, float] | None:
    """The closest vertex **of ``net``'s own wiring** to ``spot``, or ``None``.

    ``net`` is required by every real caller: a wire of another net is not a
    connection option, it is the mistake this function used to be able to make
    (029 §六 verdict 3). Passing an empty ``net`` keeps the old, unjudged
    behaviour for diagnostics, and no flow uses it.
    """
    best: tuple[float, float, float] | None = None
    for x, y, vertex_net in wire_vertices(geometry):
        if net and vertex_net != net:
            continue
        distance = ((x - spot[0]) ** 2 + (y - spot[1]) ** 2) ** 0.5
        if best is None or distance < best[2]:
            best = (x, y, distance)
    return best


def choose_connection(net: str, spot: tuple[float, float], geometry: Any):
    """How **one** declared connection is made (029-c §①), or a refusal.

    Three outcomes, in the task book's order:

    1. **wire** — a vertex of *that net's own* wiring is within
       :data:`CONNECT_RADIUS`. Short loop, no name to invent.
    2. **label** — allowed when either the page already labels that net (copying
       its convention) **or** the net is a ground net. Ground is the deliberate
       exception: `GND` is how *every* schematic says ground, so requiring a
       label precedent for it would refuse the most standard drawing there is.
       Which of the two reasons applied is written into the detail.
    3. neither → :class:`NoConnectionOption`, naming both checks.
    """
    from ..core.changeplan import CONNECTION_LABEL, CONNECTION_WIRE
    from ..core.model import is_ground_net

    near = nearest_wire_point(spot, geometry, net)
    if near is not None and near[2] <= CONNECT_RADIUS:
        return ConnectionChoice(
            kind=CONNECTION_WIRE,
            detail=(
                f"a short wire to the existing {net!r} segment at ({near[0]:g}, {near[1]:g}), "
                f"{near[2]:.0f} units away (limit {CONNECT_RADIUS:g})"
            ),
            to=(near[0], near[1]),
        )
    labels = net_label_names(geometry)
    if is_ground_net(net):
        return ConnectionChoice(
            kind=CONNECTION_LABEL,
            detail=(
                f"a net label {net!r}: the net is a ground net, and naming ground is "
                "how a schematic states it even when this page shows no label precedent"
            ),
        )
    if net in labels:
        return ConnectionChoice(
            kind=CONNECTION_LABEL,
            detail=(
                f"a label named {net!r}, the way this page already names that net "
                f"({len(labels)} label name(s) on the page)"
            ),
        )
    raise NoConnectionOption(
        net,
        f"net {net!r} cannot be connected at ({spot[0]:g}, {spot[1]:g}): no wire "
        f"point within {CONNECT_RADIUS:g} units "
        + (
            f"(nearest is {near[2]:.0f} units away at ({near[0]:g}, {near[1]:g}))"
            if near is not None
            else "(the page has no wire points at all)"
        )
        + f", and this page uses no label named {net!r} (it is not a ground net "
        "either, which would have allowed one) — 两种连接手段都不成立，拒绝建 plan"
        "（不用全脚标签假装连通）",
    )


def choose_connections(
    pairs: Sequence[tuple[str, str]], spot: tuple[float, float], geometry: Any
) -> list[Any]:
    """One :class:`~boardwise.core.changeplan.PlanConnection` per declared pin.

    Every declared connection decides for itself, and a refusal on any of them
    refuses the whole plan: a part placed with three of its four pins connected
    is exactly the half-done state 029-b's case a produced, and it is worse than
    no plan because it looks finished.
    """
    from ..core.changeplan import PlanConnection

    chosen = []
    for pin, net in pairs:
        choice = choose_connection(net, spot, geometry)
        chosen.append(
            PlanConnection(
                pin=pin, net=net, kind=choice.kind, detail=choice.detail,
                to=getattr(choice, "to", None),
            )
        )
    return chosen


def probe_already_applied(
    model: Any,
    net_name: str,
    recipe: str,
    library: Any = None,
) -> CapDecision:
    """Is this decoupling requirement already satisfied on the live board?

    **The rule's own two functions**, called on a model parsed from the live
    project export: :func:`cap_candidates_on` for the inventory (which
    capacitors sit on this net, grounded) and :func:`decide_required_cap` for
    the comparison. §二.5 asks for exactly this and forbids the alternative; a
    probe that re-derived the answer from geometry would be a second judgement
    that agrees until the day it does not.
    """
    return decide_required_cap(
        recipe, cap_candidates_on(model, net_name, library), library
    )


@dataclass(frozen=True)
class RangeDiff:
    """What the page gained between two reads — the acceptance's `+1 +k` (§一)."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: int
    expected_added: str

    @property
    def ok(self) -> bool:
        return self.added == (self.expected_added,) and not self.removed

    def describe(self) -> str:
        bits = [
            f"added {list(self.added) or 'nothing'}",
            f"removed {list(self.removed) or 'nothing'}",
            f"unchanged {self.unchanged}",
        ]
        return ", ".join(bits)


def range_diff(before: Iterable[str], after: Iterable[str], expected_added: str) -> RangeDiff:
    """Compare two designator sets, so "exactly one part appeared" is a reading.

    The obligation is deliberately set-theoretic and narrow: the plan promises
    *one* new part, so anything else — a part that vanished, a designator that
    moved, two parts appearing because a previous run was half-done — is an
    accident report rather than a success (029 §一: a difference that is not
    exactly +1 is an accident even when the board looks better).
    """
    before_set, after_set = set(before), set(after)
    return RangeDiff(
        added=tuple(sorted(after_set - before_set)),
        removed=tuple(sorted(before_set - after_set)),
        unchanged=len(before_set & after_set),
        expected_added=expected_added,
    )
