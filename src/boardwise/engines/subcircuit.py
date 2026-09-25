"""`insert-subcircuit`: putting an RC / divider template onto the page (036).

This slice is the first one with **no driving rule**. 016/029/035 all began with
a finding: a rule found a violation, the finding carried a target, and the plan
executed it. Here the decision is the *caller's* knowledge — the operator or the
AI says "this node needs a series R and a shunt C", names the template and the
recipe, and the harness does the rest: it refuses what it cannot do, previews
what it would do, verifies what it did, and knows when it has already done it.

Two templates, deliberately one of each shape:

* :data:`TEMPLATE_RC_LOWPASS` — series R with a shunt C to ground. It **removes**
  the wire that joined the anchor pin to its net (035's disconnect machinery,
  reused: the attachment must be proven on the canvas), so its range check is the
  canvas identity one.
* :data:`TEMPLATE_DIVIDER` — two resistors from a net to ground with the tap in
  the middle. It is a **pure create**, so its range check is the export one.

Three rules this module leans on, each borrowed rather than re-invented:

* **The plan states its own postconditions, and they are what is checked.**
  029/035 could ask the rule "is this still a violation?"; there is no rule here,
  so the probe and the verification read the plan's own claims — the parts are on
  the page, the pin islands are the ones the template promises — through one
  function, :func:`postcondition_problems`, used *before* the writes (idempotence)
  and *after* them (verification). "Already done" and "done" therefore cannot
  disagree.
* **A wire is drawn from the pin, not from the landing spot.** The plan cannot
  know where a part's pins will be — it is placed by the editor — so every wire's
  start is read from `sch.component_pins` after the placement (029-c's lesson).
  What the plan *does* fix is where each wire ends: the anchor point, the far end
  of the wire being removed, or another plan part's pin.
* **Never land on the origin.** The two parts are tried **together** along
  029's fixed ladder from the anchor, and a rung counts as free only when every
  part is clear of every existing primitive (the geometry's own bounding boxes,
  with the page frame excluded — it covers the whole sheet and is not an
  obstacle). An exhausted ladder is a refusal that names the positions.

Nothing here talks to the bridge: the geometry is a `sch.geometry` dump, the pin
coordinates come from `sch.component_pins` and the net membership from
`sch.netlist`, all fetched by the CLI.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.changeplan import (
    CONNECTION_POWER_FLAG,
    CONNECTION_WIRE,
    PlanConnection,
)
from . import addcomponent, patchpin
from .addcomponent import (
    LADDER,
    LANDING_GRID,
    LadderExhausted,
    LandingSpot,
    is_free,
)

TEMPLATE_RC_LOWPASS = "rc-lowpass"
TEMPLATE_DIVIDER = "divider"
TEMPLATES: tuple[str, ...] = (TEMPLATE_RC_LOWPASS, TEMPLATE_DIVIDER)

#: The plan's own name for the node a template **creates**. It is not a page net
#: name and the plan never writes it: the wires that form the node are placed
#: without a net, so the editor names the island itself. The read-back compares
#: **islands, not names** (036 §3: 自动网名不是身份) — the same rule 035 round 4
#: settled for `NET\d+` / `$…` spellings.
NODE_X = "X"

#: The rail the templates ground their shunt leg to. Written down once: the
#: template is "an RC to ground", so the ground is part of the definition rather
#: than a parameter nobody would vary here.
GROUND_NET = "GND"

#: How far the group is tried from the anchor, in `LANDING_GRID` steps. The
#: offsets are deliberately generous (the anchor is usually an IC, whose own
#: bounding box swallows the first few grids); the ladder then nudges the whole
#: group by up to two grids to dodge whatever else is there.
TEMPLATE_GROUP_LADDER = LADDER


@dataclass(frozen=True)
class TemplatePart:
    """One part of a template, in the template's own geometry."""

    role: str
    prefix: str
    #: Where this part sits relative to the anchor point, in **grid** steps.
    offset: tuple[int, int]
    #: Rotation in degrees, applied at placement. `divider`'s second resistor is
    #: turned 180° so its pin 1 ends up under the first one's pin 2 — the two
    #: pins then face each other and the tap is one straight wire.
    rotation: int = 0


@dataclass(frozen=True)
class Template:
    name: str
    summary: str
    removes: bool
    parts: tuple[TemplatePart, ...]


TEMPLATE_DEFS: Mapping[str, Template] = {
    TEMPLATE_RC_LOWPASS: Template(
        name=TEMPLATE_RC_LOWPASS,
        summary=(
            "series R into the pin's old net, shunt C from the new node to GND; "
            "the wire that joined the pin to its net is removed first"
        ),
        removes=True,
        parts=(
            TemplatePart(role="series-r", prefix="R", offset=(8, 2)),
            TemplatePart(role="shunt-c", prefix="C", offset=(8, 8)),
        ),
    ),
    TEMPLATE_DIVIDER: Template(
        name=TEMPLATE_DIVIDER,
        summary=(
            "R1 from the anchor net down to the tap, R2 from the tap to GND; "
            "nothing is removed"
        ),
        removes=False,
        parts=(
            TemplatePart(role="divider-top", prefix="R", offset=(6, 0)),
            TemplatePart(role="divider-bottom", prefix="R", offset=(6, 8), rotation=180),
        ),
    ),
}


def template(name: str) -> Template:
    """The named template, or :class:`KeyError` naming the ones there are."""
    try:
        return TEMPLATE_DEFS[name]
    except KeyError:
        raise KeyError(
            f"no template named {name!r}; this build has "
            + ", ".join(sorted(TEMPLATE_DEFS))
        ) from None


@dataclass(frozen=True)
class GroupPart:
    """One part of a planned group: what it is, where it goes, what it is called."""

    role: str
    designator: str
    x: float
    y: float
    rotation: int = 0

    @property
    def at(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class GroupPlacement:
    """Where a template's parts land, and which rung of the ladder they took."""

    origin: tuple[float, float]
    spot: LandingSpot
    parts: tuple[GroupPart, ...]


def _state_of(entry: Any) -> dict[str, Any]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def blocked_boxes(geometry: Any, *, skip_ids: Iterable[str] = ()) -> list[tuple[float, float, float, float]]:
    """Existing primitives' bounding boxes a landing spot must not sit in.

    Read from `sch.geometry`'s own ``bboxes`` map (measured 2026-09-25: an empty
    page reports exactly one, the A4 frame ``(0, 0)–(1170, 825)``). The sheet is
    **skipped**: it is the page, not an obstacle, and honouring it would make
    every rung of every ladder "occupied". Component *and* wire boxes are kept —
    landing a part on top of the routing is the same mistake as landing it on a
    part.
    """
    boxes: list[tuple[float, float, float, float]] = []
    raw = (geometry or {}).get("bboxes") if isinstance(geometry, dict) else None
    if not isinstance(raw, dict):
        return boxes
    skip = set(skip_ids)
    for primitive_id, box in raw.items():
        if str(primitive_id) in skip:
            continue
        if not isinstance(box, dict):
            continue
        min_x, min_y = _number(box.get("minX")), _number(box.get("minY"))
        max_x, max_y = _number(box.get("maxX")), _number(box.get("maxY"))
        if None in (min_x, min_y, max_x, max_y):
            continue
        boxes.append((min_x, min_y, max_x, max_y))
    return boxes


def sheet_ids(geometry: Any) -> set[str]:
    """The ids of the page's own frame/backdrop primitives (``ComponentType: sheet``)."""
    found: set[str] = set()
    for entry in (geometry or {}).get("components") or []:
        if _text(_state_of(entry).get("ComponentType")) == "sheet":
            found.add(str(entry.get("primitiveId") or _state_of(entry).get("PrimitiveId") or ""))
    found.discard("")
    return found


def inside_any(
    point: tuple[float, float],
    boxes: Sequence[tuple[float, float, float, float]],
    clearance: float = addcomponent.LANDING_CLEARANCE,
) -> bool:
    """Is this point inside (or within ``clearance`` of) one of the boxes?"""
    x, y = point
    for min_x, min_y, max_x, max_y in boxes:
        if (min_x - clearance) <= x <= (max_x + clearance) and (
            min_y - clearance
        ) <= y <= (max_y + clearance):
            return True
    return False


def plan_group(
    origin: tuple[float, float],
    tpl: Template,
    geometry: Any,
    names: Iterable[str],
    *,
    ladder: Sequence[tuple[int, int]] = TEMPLATE_GROUP_LADDER,
    grid: float = LANDING_GRID,
) -> GroupPlacement:
    """Land **every** part of the template, or refuse.

    The two parts move together: a rung counts only when all of them are free, so
    a run can never leave half a template on the page (that half-inserted state is
    worse than nothing — it looks finished). Freeness is 029's own test — clear of
    every component origin and wire vertex — *plus* the bbox interference check
    the task book asks for, with the page frame excluded.

    Raises :class:`~boardwise.engines.addcomponent.LadderExhausted` when no rung
    works; it never falls back to the anchor itself (029 §二.4's red line).
    """
    occupied = addcomponent.occupied_points(geometry)
    boxes = blocked_boxes(geometry, skip_ids=sheet_ids(geometry))
    pool = list(names)
    tried: list[tuple[float, float]] = []
    for index, (dx, dy) in enumerate(ladder):
        placements: list[GroupPart] = []
        pool = list(names)
        for part in tpl.parts:
            gx = part.offset[0] + dx
            gy = part.offset[1] + dy
            x, y = origin[0] + gx * grid, origin[1] + gy * grid
            designator = addcomponent.allocate_designator(pool, part.prefix)
            pool.append(designator)
            placements.append(
                GroupPart(role=part.role, designator=designator, x=x, y=y,
                          rotation=part.rotation)
            )
        tried.append(placements[0].at if placements else (0.0, 0.0))
        if all(
            is_free(item.x, item.y, occupied) and not inside_any((item.x, item.y), boxes)
            for item in placements
        ):
            return GroupPlacement(
                origin=(float(origin[0]), float(origin[1])),
                spot=LandingSpot(x=placements[0].x, y=placements[0].y, offset=(dx, dy), index=index),
                parts=tuple(placements),
            )
    raise LadderExhausted(tried, occupied)


# --------------------------------------------------------------------------
# the connections a template declares
# --------------------------------------------------------------------------


def _wire(designator: str, pin: str, net: str, to: tuple[float, float], detail: str) -> PlanConnection:
    return PlanConnection(
        designator=designator, pin=pin, net=net, kind=CONNECTION_WIRE,
        detail=detail, to=(float(to[0]), float(to[1])),
    )


def ground_connection(designator: str, pin: str, spot: tuple[float, float], geometry: Any) -> PlanConnection:
    """The shunt leg's ground: 029's `choose_connection`, minus the label option.

    `label` is dropped for this kind because the host's net-label API is measured
    unusable here (SKILL pit 9: ``sch_PrimitiveNetLabel: absent``) — a kind the
    page cannot carry is not an option, and 029 already prefers the wire and then
    the rail flag anyway.
    """
    choice = addcomponent.choose_connection(GROUND_NET, spot, geometry)
    if choice.kind not in (CONNECTION_WIRE, CONNECTION_POWER_FLAG):
        raise addcomponent.NoConnectionOption(
            GROUND_NET,
            f"the ground end of this template would need a {choice.kind!r} connection, "
            "and this slice only draws wires or places a rail flag (the host has no "
            "usable net-label API — SKILL pit 9)",
        )
    return PlanConnection(
        designator=designator, pin=pin, net=GROUND_NET, kind=choice.kind,
        detail=choice.detail, to=choice.to,
    )


def rc_lowpass_connections(
    *,
    series_r: GroupPart,
    shunt_c: GroupPart,
    anchor_pin: tuple[float, float],
    rejoin_at: tuple[float, float],
    before_net: str,
    geometry: Any,
) -> list[PlanConnection]:
    """The four connections of the RC template, in write order.

    1. ``R.1`` → the anchor pin (the new node's first member);
    2. ``R.2`` → the *far end of the wire being removed*, which is where the old
       net is still reachable once that wire is gone (the anchor's own endpoint
       disappears with it);
    3. ``C.1`` → the anchor pin (the node's second and third members meet there);
    4. ``C.2`` → ground, by 029's own choice function.
    """
    x = NODE_X
    return [
        _wire(
            series_r.designator, "1", x, anchor_pin,
            f"a short wire from {series_r.designator}.1 to the anchor pin at "
            f"({anchor_pin[0]:g}, {anchor_pin[1]:g}) — one side of the new node "
            f"{NODE_X!r}",
        ),
        _wire(
            series_r.designator, "2", before_net, rejoin_at,
            f"a short wire from {series_r.designator}.2 back to {before_net!r} at "
            f"({rejoin_at[0]:g}, {rejoin_at[1]:g}) — the far end of the wire this "
            "plan removes, so the old net keeps its other members",
        ),
        _wire(
            shunt_c.designator, "1", x, anchor_pin,
            f"a short wire from {shunt_c.designator}.1 to the anchor pin at "
            f"({anchor_pin[0]:g}, {anchor_pin[1]:g}) — the shunt side of {NODE_X!r}",
        ),
        ground_connection(shunt_c.designator, "2", shunt_c.at, geometry),
    ]


def divider_connections(
    *,
    top_r: GroupPart,
    bottom_r: GroupPart,
    anchor_net: str,
    anchor_at: tuple[float, float],
    geometry: Any,
) -> list[PlanConnection]:
    """The three connections of the divider template, in write order.

    1. ``R1.1`` → the anchor net's own recorded vertex (the stub that feeds the
       divider);
    2. ``R1.2`` → ``R2.1`` (the tap — both pins belong to *this* plan, so the
       target is another part's pin and its coordinate is read once both are
       placed);
    3. ``R2.2`` → ground.
    """
    return [
        _wire(
            top_r.designator, "1", anchor_net, anchor_at,
            f"a short wire from {top_r.designator}.1 to the existing {anchor_net!r} "
            f"segment at ({anchor_at[0]:g}, {anchor_at[1]:g})",
        ),
        PlanConnection(
            designator=top_r.designator, pin="2", net=NODE_X, kind=CONNECTION_WIRE,
            detail=(
                f"a short wire from {top_r.designator}.2 to {bottom_r.designator}.1 — "
                f"the tap {NODE_X!r}, whose coordinate is read after both parts are placed"
            ),
            to_pin=f"{bottom_r.designator}.1",
        ),
        ground_connection(bottom_r.designator, "2", bottom_r.at, geometry),
    ]


# --------------------------------------------------------------------------
# the plan's own postconditions, re-read on the board
# --------------------------------------------------------------------------


def _pin_key(designator: str, pin: str) -> tuple[str, str]:
    return (str(designator), str(pin))


def _island_name(live: Mapping[tuple[str, str], str], designator: str, pin: str) -> str:
    return str(live.get(_pin_key(designator, pin)) or "")


def postcondition_problems(
    plan: Any,
    *,
    live: Mapping[tuple[str, str], str],
    geometry: Any,
    pins: Mapping[tuple[str, str], tuple[float, float]],
) -> dict[str, list[str]]:
    """Every claim the plan makes about the finished board, re-read on it.

    One function, called twice: **before** the writes (so a repeat run answers
    `already_applied` — 036's idempotence judgement is the plan's own
    postconditions, not a rule re-run, because there is no rule) and **after**
    them (so "done" means the plan's claims hold, not that the writes returned).

    Two legs, both required, and they are returned separately because "which leg
    failed" is the difference between a wrong write and an unreadable page (§3:
    双证缺一判 unknown):

    * ``live`` — **the editor's own netlist**: the pins of the new node must share
      one island, the legs on either side must not, and the ground pin must be on
      the rail the plan named. Islands, not names: the editor spells an unnamed
      net ``NET7`` in one reading and ``$57N2`` in the other, and equality of two
      meaningless names is not evidence (035 round 4).
    * ``canvas`` — each part is on the page at its planned coordinate, and every
      wire in the plan has an endpoint at both ends it promised.

    An empty list in both is "the plan's postconditions hold".
    """
    live_problems: list[str] = []
    canvas_problems: list[str] = []
    origins = addcomponent.component_origins(geometry)
    for part in plan.change.parts:
        if part.designator not in origins:
            canvas_problems.append(
                f"{part.designator} ({part.role}) is not on the page — the plan places it "
                f"at ({float(part.x or 0.0):g}, {float(part.y or 0.0):g})"
            )
            continue
        at = origins[part.designator]
        if (at[0], at[1]) != (float(part.x or 0.0), float(part.y or 0.0)):
            canvas_problems.append(
                f"{part.designator} is at ({at[0]:g}, {at[1]:g}), not where the plan put it "
                f"({float(part.x or 0.0):g}, {float(part.y or 0.0):g})"
            )

    node_pins = [
        item for item in plan.change.connections if item.net == NODE_X
    ]
    other_nets: dict[tuple[str, str], str] = {}
    ground_pins: list[PlanConnection] = []
    for item in plan.change.connections:
        if item.net == NODE_X:
            continue
        if item.net == GROUND_NET:
            ground_pins.append(item)
        else:
            other_nets[_pin_key(item.designator, item.pin)] = item.net

    if node_pins:
        names = {
            _island_name(live, item.designator, item.pin) for item in node_pins
        }
        if "" in names or len(names) != 1:
            live_problems.append(
                "the new node's pins "
                + ", ".join(f"{item.designator}.{item.pin}" for item in node_pins)
                + " are not one island in the editor's own netlist — they read "
                + ", ".join(
                    f"{item.designator}.{item.pin}="
                    f"{_island_name(live, item.designator, item.pin)!r}"
                    for item in node_pins
                )
            )
        else:
            node_name = names.pop()
            for (designator, pin), net in sorted(other_nets.items()):
                if _island_name(live, designator, pin) == node_name:
                    live_problems.append(
                        f"{designator}.{pin} is on the same island as the new node "
                        f"({node_name!r}) but the plan keeps it on {net!r} — the series "
                        "leg did not separate them"
                    )
    for item in ground_pins:
        found_name = _island_name(live, item.designator, item.pin)
        if found_name != GROUND_NET:
            live_problems.append(
                f"{item.designator}.{item.pin} reads {found_name!r} in the editor's own "
                f"netlist, not {GROUND_NET!r} — the ground leg is not connected"
            )

    for item in plan.change.connections:
        if item.kind != CONNECTION_WIRE:
            continue
        start = pins.get(_pin_key(item.designator, item.pin))
        if start is None:
            canvas_problems.append(
                f"{item.designator}.{item.pin}'s own coordinates could not be read, so the "
                "wire this plan drew cannot be checked on the canvas"
            )
            continue
        if not patchpin.wire_endpoints_on_pin(geometry, start, ""):
            canvas_problems.append(
                f"no wire ends on {item.designator}.{item.pin} at ({start[0]:g}, {start[1]:g}) "
                "on the canvas"
            )
        target = wire_target(item, pins)
        if target is None:
            canvas_problems.append(
                f"the far end of the wire on {item.designator}.{item.pin} "
                f"({item.to_pin or item.net}) could not be located"
            )
            continue
        if not patchpin.wire_endpoints_on_pin(geometry, target, ""):
            canvas_problems.append(
                f"no wire ends at {item.to_pin or item.net} "
                f"({target[0]:g}, {target[1]:g}) — the far end of {item.designator}."
                f"{item.pin}'s wire is not attached"
            )
    return {"live": live_problems, "canvas": canvas_problems}


def all_satisfied(problems: Mapping[str, Sequence[str]]) -> bool:
    return not any(problems.get(leg) for leg in ("live", "canvas"))


def wire_target(
    item: PlanConnection, pins: Mapping[tuple[str, str], tuple[float, float]]
) -> tuple[float, float] | None:
    """Where a wire ends: the plan's own ``to``, or the pin it names with ``toPin``."""
    if item.to_pin:
        designator, _, pin = str(item.to_pin).partition(".")
        return pins.get(_pin_key(designator, pin))
    return item.to


def plan_pins(plan: Any) -> list[tuple[str, str]]:
    """Every ``(designator, pin)`` the plan connects — the read-back's subjects."""
    return [_pin_key(item.designator, item.pin) for item in plan.change.connections]


def plan_parts(plan: Any) -> dict[str, Any]:
    return {str(item.designator): item for item in plan.change.parts}


def company(model: Any, designator: str, pin: str) -> frozenset[tuple[str, str]]:
    """Every pin sharing this pin's net, itself excluded (a frozenset, may be empty)."""
    group = patchpin.pin_group(model, designator, pin)
    return frozenset(item for item in group if item != (str(designator), str(pin)))


def existing_company_problems(before: Any, after: Any) -> list[str]:
    """Did any pin that was **already there** change company? (036's create check)

    The out-of-scope question for a pure-create insert, and it cannot be 029's
    `outside_scope_differences`: that helper excludes the *one* pin a repair moved,
    while an insert legitimately adds **new** pins to existing nets (R1.1 joins the
    anchor net, R2.2 joins GND) — excluding one of them would leave the other
    looking like an out-of-scope addition. So the reading here is the complement:
    every pin that existed before must still share a net with exactly the same
    pins it shared it with before, *ignoring the newly added ones*.

    Both sides are the **export's** own reading (the same instrument), which is
    what makes the comparison meaningful: this path has no deletion, and a
    deletion is the one thing the export does not recompute (035 round 4).

    It is the **create** path's check only. A template that removes a wire
    legitimately changes company — the far end of that wire keeps its net and
    loses its old netmate to the resistor that replaces it — so `rc-lowpass` is
    judged on the canvas identity instead (036 §3), where "exactly the promised
    primitive is gone" is the claim that stays true.
    """
    before_pins = {
        (str(designator), str(item.number))
        for designator, component in (before.components or {}).items()
        for item in component.pins
    }
    problems: list[str] = []
    for designator, pin in sorted(before_pins):
        was = company(before, designator, pin)
        is_now = frozenset(
            item for item in company(after, designator, pin) if item in before_pins
        )
        if was != is_now:
            lost = sorted(was - is_now)
            gained = sorted(is_now - was)
            problems.append(
                f"{designator}.{pin} changed company: "
                + (f"lost {', '.join(f'{d}.{p}' for d, p in lost)}" if lost else "")
                + ("; " if lost and gained else "")
                + (f"gained {', '.join(f'{d}.{p}' for d, p in gained)}" if gained else "")
            )
    return problems
