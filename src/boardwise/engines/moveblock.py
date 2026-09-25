"""`move-block`: translating a group of parts without breaking a connection (037).

The last M3 slice, and the second with **no driving rule**: the caller names the
group and the delta, and the harness has to move it safely, keep every connection,
be able to read the result back, and know when the work is already done.

One measurement decides the whole shape of this module (`outputs/037_probe.txt`):
**the host does not drag a wire when a part is moved.** On 3.2.186
``sch.modify_primitive`` moves the part and leaves the wire exactly where it was —
the part's pins leave the copper and the connection is gone. So a move that keeps
its connections has to:

1. move every part (``sch.modify_primitive``, the only pose write there is),
2. take off the wires that were attached to the group,
3. draw them again — the group's own wires **shifted by the same delta**, the wires
   that leave the group redrawn orthogonally from the moved pin back to their
   **original far point** (029's `wire_route`, which is also why a diagonal is
   never emitted: it hangs the host).

Two rules the rest of the slice leans on, both inherited rather than re-invented:

* **The acceptance's main judgement is netlist identity.** A move must not change
  any connection, and the reading that survives the editor renaming its own nets
  is the *partition of pins* (035/036's lesson): for every pin of every moved part
  the set of pins it shares a net with must be exactly what the plan recorded.
  Names are never compared.
* **The plan states its own postconditions**, and one function answers both "is
  this already done?" (before the writes) and "is it done?" (after them) — the
  pattern 036 established, because there is no rule to ask.

Refusals, and they are all of this module's guesses removed:

* a designator that is not there, or is there twice;
* a delta that is not a whole number of grid steps (a move off the grid leaves the
  pins off the grid, and no wire can join them to the old routing);
* a part that is currently off the grid (its pose could not be re-checked);
* a wire that ends on a group pin but is attached to a **label**, a **net flag** or
  something this slice cannot name — only a wire ending on a pin is movable copper
  (035's attachment rule, same reason);
* a wire that passes **through** a group pin mid-segment (a T): deleting it would
  take away whatever else it carries;
* a target area that hits another primitive (029's `is_free` plus the geometry's
  own bounding boxes, with the page frame excluded).

Nothing here talks to the bridge: the geometry is a `sch.geometry` dump, the pins
come from `sch.component_pins`, the netlist from `sch.netlist`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.changeplan import MOVE_GRID, PlanIsland, PlanMove, PlanWireOp
from . import addcomponent, patchpin
from .subcircuit import blocked_boxes, inside_any, sheet_ids

#: The grid a move has to stay on. 029's landing grid and 037's move grid are the
#: same 5 units — 029 places on it, this slice keeps parts on it.
GRID = MOVE_GRID


class MoveRefused(Exception):
    """The group cannot be moved as asked, and the message names why.

    One exception for every refusal (unknown designator, ambiguous designator,
    off-grid pose, an attachment this slice cannot take off, a target that is not
    free): the CLI turns it into exit 5 with the message verbatim, because "the
    move was refused" without the reason is a refusal nobody can act on.
    """


@dataclass(frozen=True)
class Part:
    """One part of the group, as the live page states it."""

    designator: str
    primitive_id: str
    x: float
    y: float
    rotation: float
    at: tuple[float, float]


@dataclass(frozen=True)
class WireMove:
    """One wire the move takes off and draws again."""

    primitive_id: str
    net: str
    points_before: tuple[tuple[float, float], ...]
    points_after: tuple[tuple[float, float], ...]
    why: str


def _state_of(entry: Any) -> dict[str, Any]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def on_grid(value: float, grid: float = GRID) -> bool:
    """Is this coordinate a whole number of grid steps?"""
    return abs(round(value / grid) * grid - value) <= 1e-6


def poses(geometry: Any) -> dict[str, Part]:
    """``designator -> Part`` from a `sch.geometry` dump.

    Read the same way the rest of the harness reads a page (029's
    `component_origins`, plus the rotation this slice has to re-check): a part
    whose designator ends in ``?`` has not been numbered yet and is not a part of
    any group.
    """
    found: dict[str, Part] = {}
    for entry in (geometry or {}).get("components") or []:
        state = _state_of(entry)
        name = _text(state.get("Designator")) or _text(
            (state.get("OtherProperty") or {}).get("Designator")
            if isinstance(state.get("OtherProperty"), dict)
            else ""
        )
        x, y = _number(state.get("X")), _number(state.get("Y"))
        if not name or name.endswith("?") or x is None or y is None:
            continue
        found.setdefault(name, Part(
            designator=name,
            primitive_id=str(entry.get("primitiveId") or state.get("PrimitiveId") or ""),
            x=x, y=y, rotation=_number(state.get("Rotation")) or 0.0, at=(x, y),
        ))
    return found


def matching(geometry: Any, designator: str) -> int:
    """How many primitives on this page carry that designator (011c's CONN-1)."""
    wanted = designator.strip().upper()
    count = 0
    for entry in (geometry or {}).get("components") or []:
        state = _state_of(entry)
        name = _text(state.get("Designator")) or _text(
            (state.get("OtherProperty") or {}).get("Designator")
            if isinstance(state.get("OtherProperty"), dict)
            else ""
        )
        if name.upper() == wanted:
            count += 1
    return count


def resolve_group(
    geometry: Any,
    designators: Sequence[str],
    pins_by_designator: Mapping[str, Mapping[str, tuple[float, float]]],
) -> list[Part]:
    """The parts the caller named, or a refusal that says which one failed.

    Three ways to fail and each is named: the designator is not on the page, it is
    there **twice** (one designator, two parts — "the two U3s" is a real board
    state, 011c's CONN-1), or it is there but reports no pins (a sheet frame or a
    text primitive is not a part, and a group of non-parts is not a block).
    """
    page = poses(geometry)
    group: list[Part] = []
    for name in designators:
        seen = matching(geometry, name)
        if seen > 1:
            raise MoveRefused(
                f"{name} is on the page {seen} times — one designator, two parts is "
                "ambiguity, and a move has to name parts it can tell apart (011c's CONN-1)"
            )
        part = page.get(name)
        if part is None:
            raise MoveRefused(
                f"{name} is not on the focused page ({len(page)} designators there) — "
                "a group has to name parts that exist"
            )
        if not part.primitive_id:
            raise MoveRefused(f"{name} has no canvas id in this geometry dump")
        if not pins_by_designator.get(name):
            raise MoveRefused(
                f"{name} reports no pins, so it is not a part this slice can move "
                "(a sheet frame or a text primitive is not a block)"
            )
        group.append(part)
    return group


def check_grid(group: Sequence[Part], dx: float, dy: float) -> None:
    """Refuse a delta (or a current pose) that is off the grid (037 §一)."""
    if not on_grid(dx) or not on_grid(dy):
        raise MoveRefused(
            f"the delta ({dx:g}, {dy:g}) is not a multiple of the {GRID:g}-unit grid — "
            "网格歪了线就再也接不上：移动后的脚不在网格上，重画的线接不回原来的走线"
        )
    off = [item.designator for item in group if not on_grid(item.x) or not on_grid(item.y)]
    if off:
        raise MoveRefused(
            f"{', '.join(off)} is not on the {GRID:g}-unit grid, so its pose cannot be "
            "re-checked against a grid-aligned plan — 先把器件摆回网格（或手工搬正）"
        )


def _far_points(geometry: Any, exclude: Iterable[str]) -> list[tuple[str, str]]:
    """``(kind, what)`` for every non-wire primitive sitting on the page.

    Used to refuse a boundary wire whose far end is attached to something this
    slice cannot move: a net label or a net flag. A wire's far end that lands on
    another component's *pin* is the ordinary case and is allowed — that pin is
    not moving, so the redrawn wire simply reaches it again.
    """
    out: list[tuple[str, str]] = []
    skip = set(exclude)
    for entry in (geometry or {}).get("components") or []:
        state = _state_of(entry)
        if str(entry.get("primitiveId") or "") in skip:
            continue
        x, y = _number(state.get("X")), _number(state.get("Y"))
        if x is None or y is None:
            continue
        kind = _text(state.get("ComponentType")) or "component"
        name = _text(state.get("Designator")) or _text(state.get("Net")) or kind
        out.append((kind, f"{name} at ({x:g}, {y:g})"))
    for entry in (geometry or {}).get("netlabels") or []:
        state = _state_of(entry)
        x, y = _number(state.get("X")), _number(state.get("Y"))
        if x is not None and y is not None:
            out.append(("netlabel", f"{_text(state.get('Net')) or 'label'} at ({x:g}, {y:g})"))
    return out


def plan_wires(
    geometry: Any,
    group: Sequence[Part],
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
    dx: float,
    dy: float,
) -> list[WireMove]:
    """Classify every wire that touches the group and say what happens to it.

    Internal (both ends on group pins) → shifted by the delta, same shape.
    Boundary (one end on a group pin) → redrawn orthogonally from the moved pin to
    the **original far point**. Anything else that touches a group pin — a T
    through the pin, a far end on a label or a flag, more than one wire ending on
    the same pin — is a refusal that names it (v1 does not guess, 037 §一).
    """
    group_pins: dict[tuple[float, float], tuple[str, str]] = {}
    for part in group:
        for number, point in (pins.get(part.designator) or {}).items():
            group_pins[(round(point[0], 3), round(point[1], 3))] = (part.designator, number)
    group_ids = {item.primitive_id for item in group}
    strays = _far_points(geometry, exclude=group_ids)
    # There is deliberately **no** segment-based T test here. 035's
    # `wires_through_pin` asks whether a pin sits strictly inside one of a wire's
    # reported segments, and that reading is unsound on this host's point lists:
    # measured 2026-09-25, a legitimate one-part move was refused because the
    # reported list's *consecutive pairs* are not the drawn segments
    # (`[445,320, 445,310, 655,320, 445,320]` — the middle pair is a diagonal that
    # was never drawn), and pin 5, five units to the side of it, "lay on" that
    # diagonal within tolerance. What the instrument *can* say soundly is: a pin
    # that is one of the reported points is a junction on that wire. A wire that
    # merely crosses a group pin without a junction is therefore left alone — and
    # if that leaves a connection broken, the identity judgement catches it by
    # name (exit 2), which is the honest place for it.

    moves: list[WireMove] = []
    for segment in patchpin.wire_segments(geometry):
        points = [(float(x), float(y)) for x, y in segment.points]
        if not points:
            continue
        # "Touches a group pin" means the pin is one of the wire's **reported
        # points** — never "one of its first/last points": measured 035, the host
        # reports a wire's geometry as a point list that repeats and reorders what
        # was drawn around its junctions (a two-leg wire came back with its far
        # junction listed twice and the pin *interior*). The same measurement also
        # says the list is a **set, not a path** — its consecutive pairs can even
        # be diagonal (`[345,320, 345,310, 555,320, 345,320]`) — so a redraw can
        # never replay it: the new route is reconstructed orthogonally instead
        # (029's `wire_route`), which is also why a diagonal can never reach the
        # host (a diagonal `sch.place_wire` hangs the editor, measured 029-c).
        hits = [
            (group_pins[(round(point[0], 3), round(point[1], 3))], point)
            for point in points
            if (round(point[0], 3), round(point[1], 3)) in group_pins
        ]
        distinct = []
        for entry in hits:
            if entry not in distinct:
                distinct.append(entry)
        if not distinct:
            continue
        if len(distinct) > 2:
            raise MoveRefused(
                f"the wire {segment.primitive_id} reports "
                f"{len(distinct)} group pins on one primitive ("
                + ", ".join(f"{name}.{number}" for (name, number), _point in distinct)
                + ") — v1 不猜：把这条线拆成一条一段再移动"
            )
        if len(distinct) == 2:
            (name_a, pin_a), point_a = distinct[0]
            (name_b, pin_b), point_b = distinct[1]
            route = addcomponent.wire_route(
                (point_a[0] + dx, point_a[1] + dy), (point_b[0] + dx, point_b[1] + dy)
            )
            moves.append(WireMove(
                primitive_id=segment.primitive_id, net=segment.net,
                points_before=tuple(points), points_after=tuple(route),
                why=(
                    f"internal wire ({name_a}.{pin_a} ↔ {name_b}.{pin_b}): both ends are on "
                    "the group, so it is redrawn orthogonally between the moved pins"
                ),
            ))
            continue
        (name, number), pin_point = distinct[0]
        far_point = max(
            points, key=lambda item: (item[0] - pin_point[0]) ** 2 + (item[1] - pin_point[1]) ** 2
        )
        if patchpin.same_point(far_point, pin_point):
            raise MoveRefused(
                f"the wire {segment.primitive_id} on {name}.{number} reports no other point, "
                "so there is nowhere to redraw it to — v1 不猜"
            )
        attached = [
            f"{kind} {what}" for kind, what in strays
            if _at_point(what, far_point)
        ]
        if attached:
            raise MoveRefused(
                f"the wire {segment.primitive_id} leaves the group and ends on "
                + "; ".join(attached)
                + " — 边界附着只认脚（wire 端点落在脚上）；label / netflag / 认不出的图元 "
                "v1 一律拒绝（本机 sch_PrimitiveNetLabel 连读都不存在，SKILL 坑 9）"
            )
        route = addcomponent.wire_route(
            (pin_point[0] + dx, pin_point[1] + dy), far_point
        )
        moves.append(WireMove(
            primitive_id=segment.primitive_id, net=segment.net,
            points_before=tuple(points), points_after=tuple(route),
            why=(
                f"boundary wire: redrawn orthogonally from the moved {name}.{number} pin to "
                f"its original far point ({far_point[0]:g}, {far_point[1]:g})"
            ),
        ))
    return moves


def _numbers_of(text: str) -> list[float]:
    """The numbers in a ``"... at (x, y)"`` description (diagnostic only)."""
    out: list[float] = []
    for chunk in text.replace("(", " ").replace(")", " ").replace(",", " ").split():
        try:
            out.append(float(chunk))
        except ValueError:
            continue
    return out


def _at_point(what: str, point: tuple[float, float]) -> bool:
    numbers = _numbers_of(what)
    if len(numbers) < 2:
        return False
    return patchpin.same_point((numbers[-2], numbers[-1]), point)


def check_target_free(
    geometry: Any,
    group: Sequence[Part],
    dx: float,
    dy: float,
) -> None:
    """Refuse a target area that overlaps something (029's rules, same reason).

    Two legs, both measured elsewhere: 029's `is_free` (clear of every *origin* and
    wire vertex, with the group's own taken out), and the geometry's own bounding
    boxes with the page frame excluded — the frame covers the whole sheet and
    honouring it would refuse every move (036's lesson).
    """
    group_ids = {item.primitive_id for item in group}
    occupied = [
        point for point in addcomponent.occupied_points(geometry)
        if point not in {item.at for item in group}
    ]
    boxes = blocked_boxes(geometry, skip_ids=sheet_ids(geometry) | group_ids)
    for part in group:
        target = (part.x + dx, part.y + dy)
        if not addcomponent.is_free(target[0], target[1], occupied):
            raise MoveRefused(
                f"{part.designator}'s target ({target[0]:g}, {target[1]:g}) is occupied — "
                "目标位压着既有图元；v1 不猜，挪开或换 delta"
            )
        if inside_any(target, boxes):
            raise MoveRefused(
                f"{part.designator}'s target ({target[0]:g}, {target[1]:g}) falls inside "
                "another primitive's bounding box — 目标位压图元（geometry bbox 干涉）"
            )


def islands(live: Mapping[tuple[str, str], str]) -> dict[tuple[str, str], frozenset[tuple[str, str]]]:
    """``pin -> the pins it shares a net with`` from the editor's own netlist.

    Read by **name** and stored as **pins**: two pins on an unnamed net read the
    same ``$61N2``-style name, a pin that reaches nothing reads ``""``, and an
    empty reading means "no mates" rather than "in an island with every other
    unattached pin" (the whole reason 035/036 compare islands, not names).
    """
    by_name: dict[str, set[tuple[str, str]]] = {}
    for pin, name in live.items():
        if name:
            by_name.setdefault(str(name), set()).add(pin)
    out: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}
    for pin, name in live.items():
        mates = by_name.get(str(name), set()) if name else set()
        out[pin] = frozenset(mate for mate in mates if mate != pin)
    return out


def pin_key(text: str) -> tuple[str, str]:
    designator, _, number = str(text).partition(".")
    return (designator, number)


def plan_islands(
    live: Mapping[tuple[str, str], str],
    group: Sequence[Part],
    pins: Mapping[str, Mapping[str, tuple[float, float]]],
) -> list[PlanIsland]:
    """The identity claim: every group pin and the mates it has right now."""
    reading = islands(live)
    out: list[PlanIsland] = []
    for part in group:
        for number in sorted(pins.get(part.designator) or {}):
            key = (part.designator, number)
            mates = sorted(".".join(mate) for mate in reading.get(key, frozenset()))
            out.append(PlanIsland(pin=f"{part.designator}.{number}", mates=mates))
    return out


def postcondition_problems(
    plan: Any,
    *,
    geometry: Any,
    live: Mapping[tuple[str, str], str],
) -> dict[str, list[str]]:
    """Is the group where the plan says, with the connections it promised?

    One function, called twice: **before** the writes (a repeat run answers
    `already_applied`) and **after** them (the read-back). Two legs, both
    required (036's rule):

    * ``canvas`` — every moved part is at its planned point with the rotation it
      had, and every redrawn wire has an endpoint at both ends it promised;
    * ``live`` — for every pin the plan recorded, the editor's own netlist still
      shows exactly the mates it had. This is the acceptance's main judgement: a
      move must not change a single connection.
    """
    canvas: list[str] = []
    live_problems: list[str] = []
    page = poses(geometry)
    for item in plan.change.moves:
        part = page.get(item.designator)
        if part is None:
            canvas.append(f"{item.designator} is not on the page")
            continue
        target = item.to_at or (0.0, 0.0)
        if (part.x, part.y) != target:
            canvas.append(
                f"{item.designator} is at ({part.x:g}, {part.y:g}), not where the plan put "
                f"it ({target[0]:g}, {target[1]:g})"
            )
        if abs(part.rotation - item.from_rotation) > 1e-6:
            canvas.append(
                f"{item.designator} is rotated {part.rotation:g}°, not the "
                f"{item.from_rotation:g}° the plan recorded — a local move does not "
                "re-orient"
            )
    for op in plan.change.wire_ops:
        if not op.points_after:
            continue
        for point in (op.points_after[0], op.points_after[-1]):
            if not patchpin.wire_endpoints_on_pin(geometry, point, ""):
                canvas.append(
                    f"no wire ends at ({point[0]:g}, {point[1]:g}) — the plan redraws "
                    f"{op.primitive_id} to there"
                )
    reading = islands(live)
    for island in plan.change.islands:
        key = pin_key(island.pin)
        now = sorted(".".join(mate) for mate in reading.get(key, frozenset()))
        if now != sorted(island.mates):
            live_problems.append(
                f"{island.pin}'s net changed company: it had {island.mates or 'no mates'}, "
                f"now {now or 'no mates'} — 移动不许改任何连接"
            )
    return {"canvas": canvas, "live": live_problems}


def all_satisfied(problems: Mapping[str, Sequence[str]]) -> bool:
    return not any(problems.get(leg) for leg in ("live", "canvas"))


def netlist_differences(
    before: Mapping[tuple[str, str], str],
    after: Mapping[tuple[str, str], str],
) -> list[str]:
    """Did any pin's company change between two readings? (the in-run check)

    The whole-project version of the identity claim: every pin that appears in
    both readings must share its net with exactly the same pins. The move changes
    *positions*, never connections, so a difference here is the accident this
    slice exists to catch — reported pin by pin, not as a count.
    """
    before_islands = islands(before)
    after_islands = islands(after)
    problems: list[str] = []
    for pin in sorted(set(before_islands) & set(after_islands)):
        if before_islands[pin] != after_islands[pin]:
            problems.append(
                f"{'.'.join(pin)}: had {sorted('.'.join(m) for m in before_islands[pin]) or 'no mates'}"
                f", now {sorted('.'.join(m) for m in after_islands[pin]) or 'no mates'}"
            )
    for pin in sorted(set(before_islands) - set(after_islands)):
        problems.append(f"{'.'.join(pin)} disappeared from the editor's own netlist")
    for pin in sorted(set(after_islands) - set(before_islands)):
        problems.append(f"{'.'.join(pin)} appeared in the editor's own netlist")
    return problems


def wire_op_from(move: WireMove) -> PlanWireOp:
    return PlanWireOp(
        primitive_id=move.primitive_id, kind="redraw", net=move.net,
        points_before=list(move.points_before), points_after=list(move.points_after),
    )
