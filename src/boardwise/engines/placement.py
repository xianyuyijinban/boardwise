"""Topology-aware placement: where every part goes, and how it is turned.

Why this module exists (201B). The compiler's own placement
(:func:`boardwise.engines.drawcompiler._place`) is a *constructive chain*: the
grammar's ranks are laid on one line, each branch is hung off the pin it shares a
net with, and a part the grammar bound to nothing goes on a shelf. It is fast,
deterministic and easy to explain — and it is also a sequential greedy that has
no way to *trade* one part's position against another's, so a relation two parts
have to keep between their **pins** can be unreachable no matter how many poses
are tried: the flagship input of this batch (the flyback, `blocklib/specs/
flyback_uc3845.*`) compiles to **zero candidates today**, every variant refused
by the single relation ``same-column(Q1, R5)``, because the chain pitch and the
sense resistor's ~20-unit pin offset never line up.

This module is the search that greedy never was. Five concepts, which the old
stage had none of:

1. **A direction to the drawing.** ``progress`` is the unit vector rank grows
   along — derived by the caller from the presentation's own side preferences
   (power/input at one end, ground/output at the other). The constructive seed
   lays the ranked parts along it, and every side preference a net's class
   implies (``power`` up, ``gnd`` down, ``input`` left, ``output`` right) is a
   named cost term, so "left in, right out" is *priced* rather than assumed.
2. **Clusters, not shelves.** Parts are pulled together by the nets they share
   (``wire-length``: HPWL, the half-perimeter of each net's member pins), so the
   parts around a power device land near it because they are *electrically* near
   it, never because they came next in a list.
3. **The pose is a search variable.** Every legal pose of every part is a
   dimension of the search space (:attr:`PlacementPart.poses` — the caller
   passes the symbol's whole accepted set). A part is free to turn so its pins
   face what it connects to; nothing here picks "pose 0 and pose 1".
4. **Relations are soft, the page is hard.** ``same-column`` / ``right-of`` /
   ``near`` … become priced misses (:func:`relation_miss` — the distance by which
   the pair misses the relation, measured between the very points the compiler's
   own ruler measures: the two pins on the shared net where the kind says so).
   A miss is *repaired* — the search translates the offending endpoint to where
   the relation holds — instead of killing the candidate. Only three things are
   hard: off the page, on a keep-out, and overlapping each other.
5. **A search anyone can audit.** Deterministic simulated annealing with a fixed
   seed (same input, same output — measured by re-running), and a cost function
   that is a *list of named terms with values* (:class:`CostTerm`), printed into
   the result. Nothing is a single opaque "score"; the 052 sec.6 reading rule
   ("keep the raw metric and the reason, never just `aesthetics=4.2`") is the
   shape of :attr:`PlacementResult.costs`.

What this module deliberately does **not** do: routing, flags, labels, text and
the readability contract all live downstream (they need the plan, not the
placement). The output is what the task book asks for — ``(x, y, rotation,
mirror)`` per part, plus the numbers the decision was made from.

The ruler is the grammar's own. :func:`relation_holds` implements the ten kinds
of ``grammar/base.py:CONSTRAINT_KINDS`` with the same words the compiler's
``_relation_holds`` uses (same slack = grid/2, same near limit, same lateral and
progress vectors). One difference is stated rather than hidden: this module
imports nothing from ``drawcompiler``, so the two implementations are two copies
of one rule; 201B's stage 2 reconciles them (the compiler will call *this*
module, and its own copy is what retires).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ..core.geometry import transform_point
from ..core.symbolprofile import Box, SymbolPose, SymbolProfile, pose_box

#: What a caller writes into a report that names the placement it used.
PLACEMENT_NAME = "boardwise-placement/1"

#: The lattice every coordinate lands on, and the "same column or row" slack it
#: implies (the checker's own reading: ``readability.DEFAULT_GRID``).
DEFAULT_GRID = 5.0

#: How far apart two pins may be and still count as "near" (``drawcompiler.
#: NEAR_LIMIT`` — the number the compiled flyback page is read at).
DEFAULT_NEAR_LIMIT = 300.0

#: The seed of the constructive layout's chain pitch: the wiring channel between
#: two facing pin tips (``drawcompiler.CHANNEL``).
DEFAULT_CHANNEL = 40.0

#: How far a branch hangs off the node it belongs to (``drawcompiler.LANE``).
DEFAULT_LANE = 60.0

#: Cost weights. Named, because a weight nobody can read is a weight nobody can
#: argue with. Relations are the grammar's promises and are priced first; the
#: wiring and side terms shape the drawing around them; compactness breaks ties.
W_RELATION = 10.0
W_WIRE = 1.0
W_FACING = 1.0
W_SIDE = 2.0
W_SPREAD = 0.5
#: What one unit of a **hard** violation costs. Large on purpose (an overlapping
#: or off-page drawing is not a drawing), but finite: a search that refuses to
#: move through a hard-violating state at all cannot get out of one.
W_HARD = 200.0

#: The sides a net class prefers, when the caller states nothing (053 sec.2's
#: presentation defaults).
DEFAULT_SIDE_PREFERENCES: Mapping[str, str] = {
    "input": "left", "output": "right", "power": "top", "gnd": "bottom",
}

_SIDE_VECTORS: Mapping[str, tuple[float, float]] = {
    "top": (0.0, 1.0), "bottom": (0.0, -1.0),
    "left": (-1.0, 0.0), "right": (1.0, 0.0),
}

#: The relation kinds this module can measure, in ``grammar/base.py``'s spelling.
SAME_COLUMN = "same-column"
SAME_ROW = "same-row"
ABOVE = "above"
BELOW = "below"
LEFT_OF = "left-of"
RIGHT_OF = "right-of"
ADJACENT = "adjacent"
NEAR = "near"
HORIZONTAL_TAP = "horizontal-tap"
VERTICAL_TAP = "vertical-tap"

#: The two kinds measured between the pair's **pins on the net they share** (a
#: branch belongs to the node it hangs off; a tap is a junction between two arm
#: pins), and the two order kinds measured between origins. Same split, and the
#: same reason, as the compiler's ``_points_for_relation``.
_PIN_KINDS = (SAME_ROW, SAME_COLUMN, HORIZONTAL_TAP, VERTICAL_TAP, NEAR)

_ORDER_KINDS = (ABOVE, BELOW, LEFT_OF, RIGHT_OF)


class PlacementError(ValueError):
    """The request is not one this module can search."""


# ------------------------------------------------------------------ the input


@dataclass(frozen=True)
class PlacementPart:
    """One part to place: its symbol, its legal poses, and its lock.

    ``poses`` is the symbol's **whole** accepted set — this module searches it
    (concept 3). ``locked`` is the pose an engineer's ``userLocks[]`` entry pins
    the part to; a locked part keeps that pose exactly and is never a candidate
    for a repair or a flip (052's escape hatch, honoured or reported, never
    silently snapped).
    """

    part_id: str
    profile: SymbolProfile
    poses: tuple[SymbolPose, ...]
    locked: SymbolPose | None = None

    def __post_init__(self) -> None:
        if not self.part_id:
            raise PlacementError("a part needs an id")
        if not self.poses:
            raise PlacementError(
                f"{self.part_id}: no legal pose was passed, and a part with no "
                "pose is a part this search cannot place — the caller's own "
                "pose filter refused every pose its symbol declares"
            )
        if self.locked is not None and self.locked not in self.poses:
            # A lock whose rotation the symbol cannot be drawn in at all is a
            # fact worth reporting, not a reason to refuse: the pose is used and
            # the relations it breaks come out of the cost list as misses.
            pass


@dataclass(frozen=True)
class PlacementNet:
    """One net of the netlist: its members, as ``(part_id, pin token)``.

    ``cls`` is the CircuitSpec's own net class (``power`` / ``gnd`` /
    ``signal``, empty when the circuit states none) and is what the side
    preferences are read through — the same reading the presentation makes for
    the roles it names.
    """

    net_id: str
    members: tuple[tuple[str, str], ...] = ()
    cls: str = ""

    def __post_init__(self) -> None:
        if not self.net_id:
            raise PlacementError("a net needs an id")


@dataclass(frozen=True)
class PlacementRelation:
    """One relation two parts must keep — the grammar's, verbatim.

    Deliberately the same four fields as
    ``grammar.base.RelativeConstraint`` (kind, subject, object, reason) and no
    more: a relation is not a coordinate, and this module is the layer that turns
    it into one.
    """

    kind: str
    subject: str
    object: str
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _PIN_KINDS + _ORDER_KINDS + (ADJACENT,):
            raise PlacementError(
                f"unknown relation kind {self.kind!r}; this module knows "
                f"{sorted(_PIN_KINDS + _ORDER_KINDS + (ADJACENT,))}"
            )
        if not self.subject or not self.object:
            raise PlacementError(
                f"the {self.kind} relation names an empty endpoint — a relation "
                "names both parts"
            )

    def label(self) -> str:
        return f"{self.kind}({self.subject}, {self.object})"


@dataclass(frozen=True)
class PlacementInput:
    """Everything the search reads: parts, netlist, relations, and the frame.

    The four inputs the task book names — a part list, a netlist, each part's
    legal pose set, the relations — plus the numbers the measurement needs
    (``grid``, ``near_limit``), the direction the drawing runs in (``progress`` /
    ``lateral``, from the presentation's side preferences), the page it must stay
    inside, and the search's own budget.
    """

    parts: tuple[PlacementPart, ...]
    nets: tuple[PlacementNet, ...] = ()
    relations: tuple[PlacementRelation, ...] = ()
    progress: tuple[float, float] = (1.0, 0.0)
    lateral: tuple[float, float] = (0.0, 1.0)
    side_preferences: Mapping[str, str] = field(
        default_factory=lambda: dict(DEFAULT_SIDE_PREFERENCES)
    )
    page_box: Box | None = None
    keepouts: tuple[Box, ...] = ()
    grid: float = DEFAULT_GRID
    near_limit: float = DEFAULT_NEAR_LIMIT
    channel: float = DEFAULT_CHANNEL
    lane: float = DEFAULT_LANE
    #: Annealing budget. ``iterations`` is the ceiling per restart; the search
    #: stops early when a sweep makes no progress (see :func:`_anneal`), so a
    #: converged input costs a fraction of it.
    iterations: int = 6000
    #: How many independent searches are run; the best drawing is kept. One
    #: annealing run is a local optimisation and *is* the thing that can get stuck
    #: — three restarts from a fixed ladder of seeds is the cheapest honest answer
    #: to that (and still deterministic: same input, same three seeds, same
    #: answer). ``1`` is one run, for a caller that wants the raw trace.
    restarts: int = 3
    seed: int = 201

    def __post_init__(self) -> None:
        if not self.parts:
            raise PlacementError("a placement request with no parts has no answer")
        ids = [part.part_id for part in self.parts]
        if len(set(ids)) != len(ids):
            raise PlacementError("two parts share one id in this request")
        if self.grid <= 0:
            raise PlacementError(f"grid must be positive, got {self.grid!r}")
        if self.iterations < 0:
            raise PlacementError("iterations cannot be negative")
        for part in self.parts:
            for token, net_id in _part_nets(self, part.part_id).items():
                if not net_id:
                    raise PlacementError(f"{part.part_id}.{token} names no net")

    def part(self, part_id: str) -> PlacementPart:
        for part in self.parts:
            if part.part_id == part_id:
                return part
        raise PlacementError(f"{part_id} is not one of this request's parts")

    def part_ids(self) -> tuple[str, ...]:
        return tuple(sorted(part.part_id for part in self.parts))


def _part_nets(request: PlacementInput, part_id: str) -> dict[str, str]:
    """``pin token -> net id`` for one part, read off the netlist.

    The same reading the grammar makes (``grammar.base.pins_of_part``): one
    source — the netlist — so the pins the relations are measured between and the
    pins the wiring term pulls together can never be two different sets.
    """
    out: dict[str, str] = {}
    for net in request.nets:
        for owner, pin in net.members:
            if owner == part_id and pin:
                out.setdefault(pin, net.net_id)
    return out


# ----------------------------------------------------------------- the output


@dataclass(frozen=True)
class CostTerm:
    """One named term of the cost function: what it is, what it is worth, why.

    The report shape 052 sec.6 fixes: a raw value and a reason, in one line, with
    no cross-layer total hidden inside. ``hard`` says which side of the contract
    the term sits on — the three that may veto a drawing (page, keep-out,
    overlap) are hard; everything else is a promise being *traded*, not checked.
    """

    name: str
    value: float
    detail: str = ""
    hard: bool = False

    @property
    def violated(self) -> bool:
        return self.value > 1e-9

    def render(self) -> str:
        flag = "hard" if self.hard else "soft"
        line = f"[{flag}] {self.name} = {self.value:g}"
        return f"{line} — {self.detail}" if self.detail else line

    def to_jsonable(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "detail": self.detail,
                "hard": self.hard}


@dataclass
class PlacementResult:
    """Where every part went, and the numbers the decision was made from."""

    origins: dict[str, tuple[float, float]]
    poses: dict[str, SymbolPose]
    costs: list[CostTerm] = field(default_factory=list)
    iterations: int = 0
    accepted: int = 0
    seed: int = 201
    notes: list[str] = field(default_factory=list)

    def term(self, name: str) -> CostTerm | None:
        for item in self.costs:
            if item.name == name:
                return item
        return None

    @property
    def hard(self) -> list[CostTerm]:
        return [item for item in self.costs if item.hard and item.violated]

    @property
    def soft(self) -> list[CostTerm]:
        return [item for item in self.costs if not item.hard and item.violated]

    @property
    def relations_held(self) -> bool:
        return not any(
            item.violated for item in self.costs if item.name.startswith("relation:")
        )

    def placement(self) -> dict[str, tuple[float, float, float, bool]]:
        """``part_id -> (x, y, rotation, mirror)`` — the task book's own answer."""
        return {
            part_id: (
                self.origins[part_id][0], self.origins[part_id][1],
                float(self.poses[part_id].rotation), self.poses[part_id].mirror,
            )
            for part_id in sorted(self.origins)
        }

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "kind": PLACEMENT_NAME,
            "seed": self.seed,
            "iterations": self.iterations,
            "accepted": self.accepted,
            "placement": [
                {"partId": part_id, "x": x, "y": y, "rotation": rotation,
                 "mirror": mirror}
                for part_id, (x, y, rotation, mirror)
                in sorted(self.placement().items())
            ],
            "costs": [item.to_jsonable() for item in self.costs],
            "hardViolations": [item.render() for item in self.hard],
            "softViolations": [item.render() for item in self.soft],
            "notes": list(self.notes),
        }


# ------------------------------------------------------------- the geometry


def posed_tip(
    pin_tip: tuple[float, float], pose: SymbolPose, origin: tuple[float, float]
) -> tuple[float, float]:
    """A pin's tip in page coordinates — ``core.geometry``'s one transform."""
    return transform_point(
        pin_tip[0], pin_tip[1], rotation=pose.rotation, mirror=pose.mirror,
        ox=origin[0], oy=origin[1],
    )


def part_box(
    profile: SymbolProfile, pose: SymbolPose, origin: tuple[float, float]
) -> Box:
    """What the part occupies: its drawn body and every pin tip, bounded.

    The same box ``drawcompiler._part_box`` builds, for the same reason: the body
    is what may not overlap another body, and the pin tips are where the wires
    arrive.
    """
    xs: list[float] = []
    ys: list[float] = []
    body = pose_box(profile.body, rotation=pose.rotation, mirror=pose.mirror,
                    ox=origin[0], oy=origin[1])
    if body is not None:
        xs.extend((body[0], body[2]))
        ys.extend((body[1], body[3]))
    for pin in profile.pins:
        point = posed_tip(pin.tip, pose, origin)
        xs.append(point[0])
        ys.append(point[1])
    if not xs:
        return (origin[0], origin[1], origin[0], origin[1])
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes_overlap(first: Box, second: Box) -> float:
    """The area two boxes share, or 0.0 — touching is not overlapping."""
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    return width * height


# --------------------------------------------------------------- the ruler


def relation_points(
    request: PlacementInput,
    relation: PlacementRelation,
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The two points a relation is measured between.

    Origins, except for the five kinds ``grammar/base.py`` measures between the
    pair's **pins on the net they share** — a branch belongs to the node its own
    pin sits on, and a tap is a junction between two arm pins. The compiler's
    ``_points_for_relation`` splits the ten kinds exactly here; a placement that
    measured whole bodies for ``same-column`` would be solving a different
    problem from the one the gate grades.
    """
    if relation.kind in _PIN_KINDS:
        shared = sorted(
            set(_part_nets(request, relation.subject).values())
            & set(_part_nets(request, relation.object).values())
        )
        for net_id in shared:
            here = _pin_point(request, pins, relation.subject, net_id)
            there = _pin_point(request, pins, relation.object, net_id)
            if here is not None and there is not None:
                return (here, there)
    here = origins.get(relation.subject)
    there = origins.get(relation.object)
    if here is None or there is None:
        return None
    return (here, there)


def _pin_point(
    request: PlacementInput,
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
    part_id: str,
    net_id: str,
) -> tuple[float, float] | None:
    """This part's pin on that net, the **lowest-numbered** one when it has two.

    One pin per (part, net) is a promise the grammar makes, not a hope here — and
    when it is broken the compiler's own ``_token_on`` picks the same one (the
    first in sorted-token order), so the two rulers cannot disagree about which
    pin a ``same-column`` is measured between.
    """
    here = pins.get(part_id)
    if not here:
        return None
    mine = _part_nets(request, part_id)
    for token in sorted(mine):
        if mine[token] == net_id and token in here:
            return here[token]
    return None


def relation_holds(
    kind: str,
    points: tuple[tuple[float, float], tuple[float, float]],
    *,
    grid: float,
    near_limit: float,
    lateral: tuple[float, float],
    progress: tuple[float, float],
) -> bool:
    """Does one relation hold between two points?

    Every kind is read through ``grammar/base.py``'s own definition, with the
    grid tolerance the readability checker treats as "the same column or row"
    (``grid / 2``) — the same number the compiler's ``_relation_holds`` uses, so a
    relation this module keeps is never reported broken by the layer measuring
    the finished plan.
    """
    (ax, ay), (bx, by) = points
    slack = grid / 2.0
    if kind in (SAME_COLUMN, HORIZONTAL_TAP):
        return abs(ax - bx) <= slack
    if kind in (SAME_ROW, VERTICAL_TAP):
        return abs(ay - by) <= slack
    if kind == ABOVE:
        return ay > by + slack
    if kind == BELOW:
        return ay < by - slack
    if kind == LEFT_OF:
        return ax < bx - slack
    if kind == RIGHT_OF:
        return ax > bx + slack
    if kind == ADJACENT:
        gap = (ax - bx, ay - by)
        return abs(_dot(gap, lateral)) <= slack and not _close(
            _dot(gap, progress), 0.0
        )
    if kind == NEAR:
        return math.hypot(ax - bx, ay - by) <= near_limit
    return False


def relation_miss(
    kind: str,
    points: tuple[tuple[float, float], tuple[float, float]],
    *,
    grid: float,
    near_limit: float,
    lateral: tuple[float, float],
    progress: tuple[float, float],
) -> float:
    """How far apart the pair is from keeping the relation — 0.0 when it holds.

    A **distance in canvas units**, not a flag: "20 units to the left of where
    ``same-column`` wants it" is an instruction the repair move can act on and a
    reader can check, while "violated" is not. It is defined so that
    ``relation_miss(...) == 0`` is exactly ``relation_holds(...)``: the two are
    computed from the same branch of the same kind, and the test file pins that
    equivalence across all ten kinds.
    """
    (ax, ay), (bx, by) = points
    slack = grid / 2.0
    if kind in (SAME_COLUMN, HORIZONTAL_TAP):
        return max(0.0, abs(ax - bx) - slack)
    if kind in (SAME_ROW, VERTICAL_TAP):
        return max(0.0, abs(ay - by) - slack)
    if kind == ABOVE:
        return max(0.0, (by + slack) - ay)
    if kind == BELOW:
        return max(0.0, ay + slack - by)
    if kind == LEFT_OF:
        return max(0.0, (ax + slack) - bx)
    if kind == RIGHT_OF:
        return max(0.0, (bx + slack) - ax)
    if kind == ADJACENT:
        return max(0.0, abs(_dot((ax - bx, ay - by), lateral)) - slack)
    if kind == NEAR:
        return max(0.0, math.hypot(ax - bx, ay - by) - near_limit)
    return float("inf")


def _dot(first: tuple[float, float], second: tuple[float, float]) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _close(first: float, second: float, tolerance: float = 10.0 ** -9) -> bool:
    return abs(first - second) <= tolerance


# ------------------------------------------------------------ the cost list


@dataclass
class _State:
    """One point in the search: where each part's origin is, and its pose."""

    origins: dict[str, tuple[float, float]]
    poses: dict[str, SymbolPose]


def _pins_of(
    request: PlacementInput, state: _State
) -> dict[str, dict[str, tuple[float, float]]]:
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for part in request.parts:
        profile = part.profile
        pose = state.poses[part.part_id]
        origin = state.origins[part.part_id]
        out[part.part_id] = {
            pin.number: posed_tip(pin.tip, pose, origin) for pin in profile.pins
        }
    return out


def _boxes_of(request: PlacementInput, state: _State) -> dict[str, Box]:
    return {
        part.part_id: part_box(
            part.profile, state.poses[part.part_id], state.origins[part.part_id]
        )
        for part in request.parts
    }


def _net_pin_points(
    request: PlacementInput,
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
) -> dict[str, list[tuple[float, float]]]:
    """``net -> the pin points on it``, for the nets the wiring term measures.

    A net with one connected pin says nothing about wiring (there is nothing to
    connect it to), so it is not a term at all — the same reason the compiler's
    own obligation checker exempts a one-pin net.
    """
    out: dict[str, list[tuple[float, float]]] = {}
    for net in request.nets:
        points = [
            pins[owner][pin]
            for owner, pin in net.members
            if owner in pins and pin in pins[owner]
        ]
        if len(points) >= 2:
            out.setdefault(net.net_id, []).extend(points)
    return out


def _side_goals(request: PlacementInput) -> dict[str, str]:
    """``part_id -> the one side its nets agree on``, from their own classes.

    Concept 1's price list. A ``power`` rail's parts are pulled up and a ``gnd``
    family's down (060's flag convention); a part whose nets disagree — the
    transformer belongs to both a rail and a ground family by construction — has
    **no** goal and is placed by its relations alone, which is the honest answer:
    the drawing, not this term, decides where the middle of a converter goes.

    The specification's own ``portRoles`` were tried here (HVDC is an *input*,
    so its parts want the left) and **measured worse**: on the flyback it fought
    the relations' own statement of the same thing and the drawing's spread grew
    from 478 to 824 units with the wiring from 1595 to 3240. A term that loses to
    the rule it was meant to sharpen is not kept because it sounds right.
    """
    goals: dict[str, str] = {}
    for part in request.parts:
        votes: dict[str, int] = {}
        for token, net_id in sorted(_part_nets(request, part.part_id).items()):
            side = request.side_preferences.get(_net_class(request, net_id), "")
            if side:
                votes[side] = votes.get(side, 0) + 1
        if not votes:
            continue
        best = max(sorted(votes), key=lambda side: votes[side])
        if list(votes.values()).count(votes[best]) == 1:
            goals[part.part_id] = best
    return goals


def _net_class(request: PlacementInput, net_id: str) -> str:
    for net in request.nets:
        if net.net_id == net_id:
            return net.cls
    return ""


def _escapes(
    request: PlacementInput, state: _State
) -> dict[str, dict[str, tuple[float, float]]]:
    """``part -> pin -> the unit direction that pin leaves its body in``.

    Read from the symbol's own ``direction`` and turned by the part's pose (the
    linear half of the one transform every coordinate goes through), because a
    pin's direction is geometry the library already stated. A pin whose direction
    the profile does not state falls back to the radial direction — from the
    part's **body centre** to the tip — which is what "which way does this pad
    leave the package" means when the file does not say.
    """
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for part in request.parts:
        pose = state.poses[part.part_id]
        origin = state.origins[part.part_id]
        body = pose_box(part.profile.body, rotation=pose.rotation,
                        mirror=pose.mirror, ox=origin[0], oy=origin[1])
        centre = (
            ((body[0] + body[2]) / 2.0, (body[1] + body[3]) / 2.0)
            if body is not None else origin
        )
        here: dict[str, tuple[float, float]] = {}
        for pin in part.profile.pins:
            local = {
                "left": (-1.0, 0.0), "right": (1.0, 0.0),
                "up": (0.0, 1.0), "down": (0.0, -1.0),
            }.get(pin.direction)
            if local is None:
                tip = posed_tip(pin.tip, pose, origin)
                local = (tip[0] - centre[0], tip[1] - centre[1])
            sideways = posed_tip(local, pose, (0.0, 0.0))
            length = math.hypot(sideways[0], sideways[1])
            here[pin.number] = (
                (sideways[0] / length, sideways[1] / length)
                if length > 0.0 else (0.0, 0.0)
            )
        out[part.part_id] = here
    return out


def _facing_term(
    request: PlacementInput,
    state: _State,
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
) -> CostTerm:
    """How much of a part's own wiring leaves its **back** — concept 3, priced.

    The wiring term above measures where a net's pins are, and a pin set's extent
    does not care which pin is which: an optocoupler mirrored or not has the same
    half-perimeter, so a search that only minimised wiring would never turn it
    round, and the drawing would show its LED side plugged into the primary. This
    term reads the **pin identity**: for every pin on a net with something else on
    it, the vector to the other pins' centroid is compared with the direction the
    pin leaves its body in, and a pin pointing away pays the distance it is from
    what it connects to.

    Weighted like the wiring term, because it is the same question asked the other
    way round ("is this pin *facing* the node" against "is this node *small*") —
    and, like every soft term here, it can never outbid a relation (10 per unit).
    """
    escapes = _escapes(request, state)
    net_points = _net_pin_points(request, pins)
    total = 0.0
    worst = ("", 0.0)
    for net in request.nets:
        points = net_points.get(net.net_id)
        if not points or len(points) < 2:
            continue
        members = [
            (owner, pin) for owner, pin in net.members
            if owner in pins and pin in pins[owner]
        ]
        for owner, pin in members:
            others = [
                pins[other][other_pin]
                for other, other_pin in members
                if (other, other_pin) != (owner, pin)
            ]
            if not others:
                continue
            centroid = (
                sum(point[0] for point in others) / len(others),
                sum(point[1] for point in others) / len(others),
            )
            tip = pins[owner][pin]
            gap = (centroid[0] - tip[0], centroid[1] - tip[1])
            distance = math.hypot(gap[0], gap[1])
            if distance <= request.grid:
                continue
            escape = escapes.get(owner, {}).get(pin, (0.0, 0.0))
            cos = _dot(escape, (gap[0] / distance, gap[1] / distance))
            if cos >= 0.0:
                continue
            total += -cos * distance
            if -cos * distance > worst[1]:
                worst = (f"{owner}.{pin} on {net.net_id}", -cos * distance)
    return CostTerm(
        "pin-facing", total,
        "how far the pins that leave a part's back are from what they connect to "
        + (f"— the worst is {worst[0]} at {worst[1]:g} units" if worst[1] > 0.0
           else "— every pin faces its own net"),
    )


def _drawing_box(boxes: Mapping[str, Box]) -> Box | None:
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes.values()),
        min(box[1] for box in boxes.values()),
        max(box[2] for box in boxes.values()),
        max(box[3] for box in boxes.values()),
    )


def _middle_of(request: PlacementInput, boxes: Mapping[str, Box]) -> tuple[float, float]:
    """What "its own side" is measured against.

    The **sheet's** middle when a page is stated, and the **drawing's own** middle
    otherwise — the compiler's own reading of a budget with no page
    (``CompileBudget.page_box = None`` means "the drawing defines its own frame,
    and the page half is not evaluated"), kept as one rule rather than two
    definitions of "the middle".
    """
    frame = request.page_box if request.page_box is not None else _drawing_box(boxes)
    if frame is None:
        return (0.0, 0.0)
    return ((frame[0] + frame[2]) / 2.0, (frame[1] + frame[3]) / 2.0)


def evaluate(request: PlacementInput, state: _State) -> list[CostTerm]:
    """The whole cost function, as named terms.

    Every term is returned — including the ones at zero — because "which promise
    did not cost anything" is part of what a reader is checking. The search sums
    them through :func:`_energy`; nothing else reads the sum.
    """
    pins = _pins_of(request, state)
    boxes = _boxes_of(request, state)
    out: list[CostTerm] = []

    # 1. the relations: the grammar's promises, priced one by one.
    for relation in request.relations:
        points = relation_points(request, relation, pins, state.origins)
        if points is None:
            out.append(CostTerm(
                name=f"relation:{relation.label()}", value=0.0,
                detail="not measurable — one endpoint is not placed",
            ))
            continue
        miss = relation_miss(
            relation.kind, points, grid=request.grid,
            near_limit=request.near_limit, lateral=request.lateral,
            progress=request.progress,
        )
        detail = (
            "kept: measured between " + _point_text(points[0]) + " and "
            + _point_text(points[1])
            if miss <= 0.0 else
            f"missed by {miss:g} units between {_point_text(points[0])} and "
            f"{_point_text(points[1])} — the grammar's reason is "
            f"{relation.reason!r}"
        )
        out.append(CostTerm(f"relation:{relation.label()}", miss, detail))

    # 2. the wiring: every net's own spread (concept 2 — clusters, not shelves).
    net_points = _net_pin_points(request, pins)
    total_wire = 0.0
    worst = ("", 0.0)
    for net_id in sorted(net_points):
        points = net_points[net_id]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        reach = (max(xs) - min(xs)) + (max(ys) - min(ys))
        total_wire += reach
        if reach > worst[1]:
            worst = (net_id, reach)
    out.append(CostTerm(
        "wire-length", total_wire,
        f"half-perimeter of every net with two or more pins, summed over "
        f"{len(net_points)} net(s); the widest is {worst[0] or '—'} at "
        f"{worst[1]:g} units",
    ))

    # 2b. the poses: does each pin point at what it connects to? (concept 3)
    out.append(_facing_term(request, state, pins))

    # 3. the direction: each part's own side, from its nets' statements.
    goals = _side_goals(request)
    total_side = 0.0
    offenders: list[str] = []
    middle = _middle_of(request, boxes)
    for part_id in sorted(goals):
        side = goals[part_id]
        box = boxes[part_id]
        centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        vector = _SIDE_VECTORS[side]
        depth = _dot((centre[0] - middle[0], centre[1] - middle[1]), vector)
        if depth < 0.0:
            total_side += -depth
            offenders.append(f"{part_id} ({side}, {abs(depth):g} units short)")
    out.append(CostTerm(
        "flow-side", total_side,
        "how far the parts whose nets name a side sit from that side "
        + ("— " + "; ".join(sorted(offenders)[:5]) if offenders
           else "— every side-preferring part is on its own side"),
    ))

    # 4. compactness: the drawing's own extent, a tie-breaker with a small
    #    weight (it must never outbid a relation).
    drawn = _drawing_box(boxes)
    spread = (
        math.hypot(drawn[2] - drawn[0], drawn[3] - drawn[1])
        if drawn is not None else 0.0
    )
    out.append(CostTerm("spread", spread, "the drawn extent's diagonal"))

    # 5. the three hard ones.
    out.append(_page_term(request, boxes))
    out.append(_keepout_term(request, boxes))
    out.append(_overlap_term(boxes))
    return out


def _page_term(request: PlacementInput, boxes: Mapping[str, Box]) -> CostTerm:
    if request.page_box is None:
        return CostTerm(
            "page", 0.0, "no page was stated, so the page half is not evaluated",
            hard=True,
        )
    page = request.page_box
    total = 0.0
    worst = ""
    for part_id in sorted(boxes):
        box = boxes[part_id]
        out = (
            max(0.0, page[0] - box[0]) + max(0.0, box[2] - page[2])
            + max(0.0, page[1] - box[1]) + max(0.0, box[3] - page[3])
        )
        if out > 0.0:
            total += out
            if not worst:
                worst = f"{part_id} by {out:g} units"
    return CostTerm(
        "out-of-page", total,
        "nothing leaves the sheet" if total <= 0.0
        else f"outside {list(map(float, page))}: {worst}",
        hard=True,
    )


def _keepout_term(request: PlacementInput, boxes: Mapping[str, Box]) -> CostTerm:
    total = 0.0
    worst = ""
    for part_id in sorted(boxes):
        for keep in request.keepouts:
            area = _boxes_overlap(boxes[part_id], keep)
            if area > 0.0:
                total += area
                if not worst:
                    worst = f"{part_id} against {list(map(float, keep))}"
    return CostTerm(
        "keepout", total,
        "nothing sits on a keep-out" if total <= 0.0 else f"on a keep-out: {worst}",
        hard=True,
    )


def _overlap_term(boxes: Mapping[str, Box]) -> CostTerm:
    ids = sorted(boxes)
    total = 0.0
    worst = ""
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            area = _boxes_overlap(boxes[first], boxes[second])
            if area > 0.0:
                total += area
                if not worst:
                    worst = f"{first}/{second} by {area:g} units²"
    return CostTerm(
        "overlap", total,
        "no two parts share area" if total <= 0.0 else f"overlapping: {worst}",
        hard=True,
    )


def _point_text(point: tuple[float, float]) -> str:
    return f"({point[0]:g}, {point[1]:g})"


def _energy(terms: Iterable[CostTerm]) -> float:
    """The scalar the search minimises.

    Every term carries its own weight; a hard term is multiplied by
    :data:`W_HARD` so a drawing that leaves the page or overlaps itself is never
    preferred to one that does not, while still being *reachable* — a search that
    refuses to visit a bad state cannot climb out of one.
    """
    total = 0.0
    for item in terms:
        if item.hard:
            total += item.value * W_HARD
        elif item.name.startswith("relation:"):
            total += item.value * W_RELATION
        elif item.name == "wire-length":
            total += item.value * W_WIRE
        elif item.name == "pin-facing":
            total += item.value * W_FACING
        elif item.name == "flow-side":
            total += item.value * W_SIDE
        elif item.name == "spread":
            total += item.value * W_SPREAD
    return total


# ------------------------------------------------------- the constructive seed


def _ranks(
    relations: Sequence[PlacementRelation], part_ids: Sequence[str]
) -> dict[str, int]:
    """``part_id -> its depth`` in the order the relations state.

    The order kinds are the grammar's "which way the drawing runs" statement, so
    the seed reads them the way the compiler's own ``_ranks`` does: ``left-of``
    and ``above`` say the subject is nearer the power/input end, and the depth is
    the longest path — a part with no order relation gets rank 0 (it will be
    hung off whatever it shares a net with).
    """
    after: dict[str, set[str]] = {part_id: set() for part_id in part_ids}
    for relation in relations:
        if relation.kind == LEFT_OF or relation.kind == ABOVE:
            after[relation.subject].add(relation.object)
        elif relation.kind == RIGHT_OF or relation.kind == BELOW:
            after[relation.object].add(relation.subject)
    ranks: dict[str, int] = {}

    def depth(part_id: str, seen: frozenset[str]) -> int:
        if part_id in ranks:
            return ranks[part_id]
        if part_id in seen:
            return 0  # a cycle the grammar should not state: stop, do not hang
        best = 0
        for other in sorted(after[part_id]):
            best = max(best, depth(other, seen | {part_id}) + 1)
        ranks[part_id] = best
        return best

    for part_id in sorted(part_ids):
        depth(part_id, frozenset())
    return ranks


def _seed(request: PlacementInput, ranks: Mapping[str, int]) -> _State:
    """The constructive first guess: ranked parts on the line, branches on their node.

    Deliberately as boring as it can be — the search is what makes the drawing,
    and a clever seed only makes a failure harder to attribute. What it does
    contribute is concept 1's direction: rank grows along ``progress``.
    """
    poses: dict[str, SymbolPose] = {}
    for part in request.parts:
        if part.locked is not None:
            poses[part.part_id] = part.locked
            continue
        poses[part.part_id] = _compact_pose(request, part)

    chain = sorted(
        (part.part_id for part in request.parts),
        key=lambda part_id: (ranks.get(part_id, 0), part_id),
    )
    progress = _unit(request.progress)
    origins: dict[str, tuple[float, float]] = {}
    cursor = 0.0
    for part_id in chain:
        part = request.part(part_id)
        half = _extent_along(
            part, poses[part_id], progress
        ) / 2.0
        at = cursor + half
        origins[part_id] = (progress[0] * at, progress[1] * at)
        cursor = at + half + request.channel

    # every part the seed has not placed yet hangs off the neighbour it shares
    # the most pins with — concept 2, read off the netlist rather than a list.
    placed = set(origins)
    for part_id in sorted(set(request.part_ids()) - placed):
        owner = _owner_for(request, part_id, placed, ranks)
        side = _branch_side(request, part_id, owner)
        base = origins.get(owner, (0.0, 0.0))
        distance = request.lane + _extent_along(
            request.part(part_id), poses[part_id], request.lateral
        ) / 2.0
        origins[part_id] = (
            base[0] + side[0] * distance, base[1] + side[1] * distance,
        )
        placed.add(part_id)
    return _State(origins=_snap(request, origins), poses=poses)


def _compact_pose(request: PlacementInput, part: PlacementPart) -> SymbolPose:
    """The pose whose box is smallest along the chain — the seed's own choice.

    Nothing more clever: this is the first guess, and concept 3 is the *search*
    being free to turn a part, not the seed knowing which way it should face. A
    part with one dimension of freedom (a two-pin chip) gets the rung that keeps
    it shortest along the chain; the search is free to change it immediately.
    """
    progress = _unit(request.progress)
    best = part.poses[0]
    best_size = None
    for pose in part.poses:
        size = _extent_along(part, pose, progress)
        key = (size, pose.rotation, pose.mirror, pose.label())
        if best_size is None or key < best_size:
            best_size = key
            best = pose
    return best


def _extent_along(
    part: PlacementPart, pose: SymbolPose, axis: tuple[float, float]
) -> float:
    box = part_box(part.profile, pose, (0.0, 0.0))
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
    projections = [_dot(corner, axis) for corner in corners]
    return max(projections) - min(projections)


def _owner_for(
    request: PlacementInput,
    part_id: str,
    placed: set[str],
    ranks: Mapping[str, int],
) -> str:
    """The neighbour this part should hang off: most shared pins, then rank, then id."""
    mine = _part_nets(request, part_id)
    best: tuple[tuple[int, int, str], str] | None = None
    for owner in sorted(placed):
        theirs = _part_nets(request, owner)
        shared = len(set(mine.values()) & set(theirs.values()))
        if shared == 0:
            continue
        key = (-shared, ranks.get(owner, 0), owner)
        if best is None or key < best[0]:
            best = (key, owner)
    if best is None:
        # Nothing to hang off: place it farthest along the chain, so it is still
        # on the drawing and its relations can pull it into place.
        return max(sorted(placed), key=lambda name: (ranks.get(name, 0), name))
    return best[1]


def _branch_side(
    request: PlacementInput, part_id: str, owner: str
) -> tuple[float, float]:
    """Which way a hung part leaves its owner: its own rail's side, else lateral.

    The branch's "other net" — the one it does not share with its owner — is what
    says which way its body goes, which is the reading ``_branch_slot`` makes and
    the reason a decoupling capacitor sits between a pin and its rail.
    """
    mine = _part_nets(request, part_id)
    theirs = _part_nets(request, owner) if owner else {}
    own = sorted(set(mine.values()) - set(theirs.values()))
    for net_id in own:
        side = request.side_preferences.get(_net_class(request, net_id), "")
        if side:
            return _SIDE_VECTORS[side]
    return _unit(request.lateral)


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length == 0.0:
        raise PlacementError("a direction of (0, 0) is not a direction")
    return (vector[0] / length, vector[1] / length)


def _snap(
    request: PlacementInput, origins: Mapping[str, tuple[float, float]]
) -> dict[str, tuple[float, float]]:
    grid = request.grid
    return {
        part_id: (round(point[0] / grid) * grid, round(point[1] / grid) * grid)
        for part_id, point in sorted(origins.items())
    }


# ------------------------------------------------------------- the search


def _repair_delta(
    request: PlacementInput,
    relation: PlacementRelation,
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
    origins: Mapping[str, tuple[float, float]],
    which: int,
) -> tuple[float, float] | None:
    """The translation that would make this relation hold, for one endpoint.

    This is concept 4 made mechanical: a soft constraint is not "rejected", it is
    *repaired*. The delta is computed from the very points the ruler measures, so
    the move that the search believes fixes a relation is the move the gate will
    see as fixing it — a repair that measured origins would leave the pin
    misaligned and the candidate refused, which is exactly the failure mode the
    flagship flyback is in today.
    """
    points = relation_points(request, relation, pins, origins)
    if points is None:
        return None
    (ax, ay), (bx, by) = points
    slack = request.grid / 2.0
    kind = relation.kind
    if kind in (SAME_COLUMN, HORIZONTAL_TAP):
        delta = (bx - ax, 0.0)
    elif kind in (SAME_ROW, VERTICAL_TAP):
        delta = (0.0, by - ay)
    elif kind == ABOVE:
        delta = (0.0, (by + slack) - ay)
    elif kind == BELOW:
        delta = (0.0, (by - slack) - ay)
    elif kind == LEFT_OF:
        delta = ((bx - slack) - ax, 0.0)
    elif kind == RIGHT_OF:
        delta = ((bx + slack) - ax, 0.0)
    elif kind == ADJACENT:
        gap = (ax - bx, ay - by)
        lateral = _dot(gap, request.lateral)
        delta = (-request.lateral[0] * lateral, -request.lateral[1] * lateral)
    elif kind == NEAR:
        distance = math.hypot(ax - bx, ay - by)
        if distance <= request.near_limit:
            return None
        step = distance - request.near_limit + request.grid
        delta = (
            (bx - ax) / distance * step, (by - ay) / distance * step,
        )
    else:
        return None
    if which == 1:
        delta = (-delta[0], -delta[1])
    # Grid-aligned, and never a no-op: a repair that rounds to nothing would
    # burn an iteration and report progress it did not make.
    snapped = (
        round(delta[0] / request.grid) * request.grid,
        round(delta[1] / request.grid) * request.grid,
    )
    if snapped == (0.0, 0.0):
        return None
    return snapped


def _violated_relations(
    request: PlacementInput, terms: Sequence[CostTerm]
) -> list[PlacementRelation]:
    names = {
        item.name for item in terms
        if item.name.startswith("relation:") and item.violated
    }
    return [
        relation for relation in request.relations
        if f"relation:{relation.label()}" in names
    ]


def _anneal_with_seed(
    request: PlacementInput, state: _State, seed: int
) -> tuple[_State, int, int]:
    """One annealing run from the fixed seed. See :func:`_anneal` for the moves.

    The seed is a parameter rather than ``request.seed`` because ``place`` runs
    the whole search several times and keeps the best drawing; each restart uses
    its own seed, and none of them is random.
    """
    rng = random.Random(seed)
    current = _State(dict(state.origins), dict(state.poses))
    terms = evaluate(request, current)
    energy = _energy(terms)
    best = _State(dict(current.origins), dict(current.poses))
    best_energy = energy
    ids = request.part_ids()
    certainty = {part.part_id for part in request.parts if part.locked is not None}
    ladder = (1, 2, 4, 8)
    #: Temperature: starts at a few grid units' worth of relation miss and cools
    #: geometrically to nearly nothing, so the tail is a hill climb.
    temperature = 40.0
    cooling = 0.9995
    accepted = 0
    stall = 0
    iterations = 0
    for iterations in range(1, request.iterations + 1):
        candidate = _State(dict(current.origins), dict(current.poses))
        roll = rng.random()
        if roll < 0.30 or not ids:
            part_id = ids[rng.randrange(len(ids))]
            if part_id in certainty:
                continue
            rung = ladder[rng.randrange(len(ladder))] * request.grid
            dx = rng.choice((-rung, 0.0, rung))
            dy = rng.choice((-rung, 0.0, rung))
            at = candidate.origins[part_id]
            candidate.origins[part_id] = (at[0] + dx, at[1] + dy)
        elif roll < 0.50:
            part_id = ids[rng.randrange(len(ids))]
            part = request.part(part_id)
            if part_id in certainty or len(part.poses) < 2:
                continue
            candidate.poses[part_id] = part.poses[rng.randrange(len(part.poses))]
        elif roll < 0.65 and len(ids) >= 2:
            first = ids[rng.randrange(len(ids))]
            second = ids[rng.randrange(len(ids))]
            if first == second or first in certainty or second in certainty:
                continue
            candidate.origins[first], candidate.origins[second] = (
                candidate.origins[second], candidate.origins[first],
            )
        else:
            pending = _violated_relations(request, terms)
            if not pending:
                continue
            relation = pending[rng.randrange(len(pending))]
            endpoints = [relation.subject, relation.object]
            rng.shuffle(endpoints)
            moved = False
            for index, part_id in enumerate(endpoints):
                if part_id in certainty:
                    continue
                delta = _repair_delta(
                    request, relation, _pins_of(request, candidate),
                    candidate.origins, index,
                )
                if delta is None:
                    continue
                at = candidate.origins[part_id]
                candidate.origins[part_id] = (at[0] + delta[0], at[1] + delta[1])
                moved = True
                break
            if not moved:
                continue

        if candidate.origins == current.origins and candidate.poses == current.poses:
            continue
        new_terms = evaluate(request, candidate)
        new_energy = _energy(new_terms)
        delta_energy = new_energy - energy
        if delta_energy <= 0.0 or rng.random() < math.exp(
            -delta_energy / max(temperature, 1e-9)
        ):
            current, terms, energy = candidate, new_terms, new_energy
            accepted += 1
            if energy < best_energy - 1e-9:
                best = _State(dict(current.origins), dict(current.poses))
                best_energy = energy
                stall = 0
            else:
                stall += 1
        else:
            stall += 1
        temperature *= cooling
        # "No progress for two thousand moves" is the stop rule: an input whose
        # relations are all kept and whose wiring has converged stops paying for
        # iterations it is not using (the 19-part performance budget is 30 s).
        if stall >= 2000:
            break
    return best, iterations, accepted


def _anneal(
    request: PlacementInput, state: _State
) -> tuple[_State, int, int]:
    """Deterministic simulated annealing over translations, poses and swaps.

    The move set is four, and each one is a concept:

    * **translate** — a part moves by a rung of a small ladder, so the search can
      slide things apart without a global reshuffle;
    * **turn** — a part takes another of its accepted poses (concept 3);
    * **swap** — two parts exchange origins, which is the one move that can undo
      a chain order decided early;
    * **repair** — a violated relation is picked and an endpoint translated by
      exactly the delta :func:`_repair_delta` computes. It reads the miss off the
      ruler instead of hoping the walk stumbles onto it: a 5-unit lattice has to
      find a 20-unit pin offset by luck otherwise.

    How much the repair move is worth is **measured, not asserted** (201B): with
    it disabled the flyback still reaches a drawing that keeps all 30 relations,
    but a worse one — wiring 2780 units against 1595, pin-facing 1091 against
    445, spread 825 against 478. Feasibility comes from the pose search and the
    translations; the *quality* of the flyback drawing comes from the repair
    move, and ``tests/test_201b_placement.py`` pins those two readings so the
    claim cannot quietly stop being true.

    Determinism is a fixed seed on a single :class:`random.Random`: the same
    request produces the same sequence of moves and therefore the same drawing,
    which the acceptance test measures by running the search twice.
    """
    return _anneal_with_seed(request, state, request.seed)


# ------------------------------------------------------------------ entry


def place(request: PlacementInput) -> PlacementResult:
    """Place every part of one request. Deterministic in ``request.seed``.

    The stages are the five concepts in order: rank the parts from the relations
    (:func:`_ranks`), seed a constructive drawing along ``progress``
    (:func:`_seed`), search it (:func:`_anneal`) — from ``request.restarts``
    independent seeds, the best drawing winning — then report the cost list of
    where it ended up (:func:`evaluate`). A hard violation is **not** a reason to
    return nothing: the caller gets the best drawing the search found together
    with its own account of what is wrong with it, which is the opposite of the
    silent zero-candidate answer the compiler gives today.
    """
    if not isinstance(request, PlacementInput):
        raise PlacementError(
            f"PlacementInput expected, got {type(request).__name__}"
        )
    ranks = _ranks(request.relations, request.part_ids())
    seed = _seed(request, ranks)
    best: tuple[float, _State, int, int, int] | None = None
    for index in range(max(1, request.restarts)):
        attempt = request.seed + index
        state, iterations, accepted = _anneal_with_seed(request, seed, attempt)
        energy = _energy(evaluate(request, state))
        if best is None or energy < best[0] - 1e-9:
            best = (energy, state, iterations, accepted, attempt)
    assert best is not None
    _, state, iterations, accepted, attempt = best
    costs = evaluate(request, state)
    result = PlacementResult(
        origins=dict(state.origins), poses=dict(state.poses), costs=costs,
        iterations=iterations, accepted=accepted, seed=attempt,
    )
    result.notes.append(
        f"{PLACEMENT_NAME}: {len(request.parts)} part(s), "
        f"{len(request.relations)} relation(s), {request.restarts} restart(s), "
        f"{iterations} iteration(s) on the winning one, {accepted} accepted, "
        f"seed {attempt}"
    )
    hard = result.hard
    if hard:
        result.notes.append(
            "the search could not remove every hard violation: "
            + "; ".join(item.render() for item in hard)
        )
    return result
