"""`patch-pin`: repairing **one pin's** connection (035, M3's third slice).

016 changed a value, 029 created a part. This slice changes *connectivity* on a
pin that already exists, and the shelf's two obligations give it three shapes:

* **connect** — a `must_connect` pin reaches no net and must reach a named one;
* **disconnect** — an `nc_pins` pin sits on a net and must touch none;
* **reconnect** — a `must_connect` pin sits on the wrong net: off, then on.

Two rules the rest of the slice leans on:

* **The idempotence probe is the rule's own judgement.** `pin_ruling` (in
  `rules/facts.py`) is the same per-pin decision the rule's rows are built from,
  so "is this pin already as it should be?" is answered by the function that
  produced the finding — never by a second, similar-looking test.
* **A disconnect is proven on the canvas or not done at all.** The attachment a
  repair removes has to be *seen*: a wire whose endpoint lands exactly on the
  pin, or a net label sitting exactly on it. A wire passing through the pin
  mid-segment (a T), a second candidate, a net flag, or nothing at all is a
  refusal that names what was found — deleting the wrong thing is worse than
  deleting nothing (035 §2).

Nothing here talks to the bridge: the geometry is a `sch.geometry` dump and the
pin coordinates come from `sch.component_pins`, both fetched by the CLI. The
connect half reuses `engines/addcomponent.py`'s judgements (radius, orthogonal
routing, power-flag only for rails) rather than inventing a second set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.changeplan import ATTACHMENT_NETLABEL, ATTACHMENT_WIRE
from ..core.model import DesignModel, Net

#: How close a coordinate has to be to count as "the same point" on the canvas.
#: The editor speaks integer canvas units; anything under half a unit is the same
#: place, and a repair must never hinge on a rounding difference.
SAME_POINT = 0.5


def _state_of(entry: Any) -> dict[str, Any]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def same_point(a: tuple[float, float] | None, b: tuple[float, float] | None) -> bool:
    """Are two canvas coordinates the same place? (see :data:`SAME_POINT`)."""
    if a is None or b is None:
        return False
    return abs(a[0] - b[0]) <= SAME_POINT and abs(a[1] - b[1]) <= SAME_POINT


@dataclass(frozen=True)
class WireSegment:
    """One wire primitive: its id, the net it carries and its vertices.

    The host reports a wire's geometry as ``state.Line`` — a **flat** coordinate
    list — plus ``state.Net`` (measured 029-b; `addcomponent.wire_vertices` reads
    the same shape). A segment keeps the point *list*, because "which end is on
    the pin" and "does it pass through the pin" are different questions.
    """

    primitive_id: str
    net: str
    points: tuple[tuple[float, float], ...]

    @property
    def endpoints(self) -> tuple[tuple[float, float], ...]:
        return (self.points[0], self.points[-1]) if self.points else ()


def wire_segments(geometry: Any) -> list[WireSegment]:
    """Every wire primitive of a `sch.geometry` dump, as straight segments.

    Consecutive pairs of the reported point list are taken as the drawn segments
    (the host merges wires that touch into one primitive, so a single entry can
    carry several runs — exactly the shape that makes a mid-segment T possible).
    """
    out: list[WireSegment] = []
    if not isinstance(geometry, dict):
        return out
    for entry in geometry.get("wires") or []:
        state = _state_of(entry)
        raw = state.get("Line") or state.get("Points") or state.get("points") or []
        points: list[tuple[float, float]] = []
        if isinstance(raw, (list, tuple)) and raw and not isinstance(raw[0], (list, tuple)):
            coords = list(raw)
            for index in range(0, len(coords) - 1, 2):
                x, y = _number(coords[index]), _number(coords[index + 1])
                if x is not None and y is not None:
                    points.append((x, y))
        elif isinstance(raw, (list, tuple)):
            for pair in raw:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    x, y = _number(pair[0]), _number(pair[1])
                    if x is not None and y is not None:
                        points.append((x, y))
        if not points:
            continue
        out.append(
            WireSegment(
                primitive_id=str(entry.get("primitiveId") or state.get("PrimitiveId") or ""),
                net=_text(state.get("Net")),
                points=tuple(points),
            )
        )
    return out


def _on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Is ``point`` on the segment ``a``-``b`` (axis-aligned or else collinear)?

    A tolerance rather than exact arithmetic on purpose: the editor stores canvas
    units and a wire whose endpoint is "on the pin" is on it, whatever the last
    decimal says.
    """
    cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    span = abs(b[0] - a[0]) + abs(b[1] - a[1])
    if span == 0:
        return same_point(point, a)
    if abs(cross) / span > SAME_POINT:
        return False
    return (
        min(a[0], b[0]) - SAME_POINT <= point[0] <= max(a[0], b[0]) + SAME_POINT
        and min(a[1], b[1]) - SAME_POINT <= point[1] <= max(a[1], b[1]) + SAME_POINT
    )


@dataclass(frozen=True)
class Attachment:
    """The one thing a disconnect may take off a pin — proven on the canvas."""

    kind: str               # wire | netlabel — see changeplan.ATTACHMENT_KINDS
    primitive_id: str
    at: tuple[float, float]
    detail: str


class AttachmentRefused(Exception):
    """No single, provable attachment — the disarm is refused, not guessed."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def attachment_on_pin(geometry: Any, pin_at: tuple[float, float]) -> Attachment:
    """What attaches this pin to its net, or a refusal that says what was found.

    The recognised attachments are the two that can be *proven* from a
    `sch.geometry` dump: a wire whose **endpoint** lands on the pin, and a net
    label sitting on it. Everything else is refused with its own words:

    * a wire that only **passes through** the pin (a T) — deleting it would take
      away whatever else it carries;
    * **more than one** candidate — we cannot tell which one the repair means;
    * a **net flag** on the pin — a real attachment, but not one this slice
      recognises (a flag is a component, and the two-kind rule is 035 §2);
    * a **net label** (the parent's 035 ruling 1): the host this runs on exposes
      no net-label primitive at all (``sch.geometry`` reports
      ``read sch_PrimitiveNetLabel: absent``), and the connector's delete index
      carries no net-label class — so a label is *named* and refused, never
      silently worked around by deleting something else;
    * **nothing** — the pin's net comes from something we cannot see.
    """
    wires = wire_segments(geometry)
    # "Lands on the pin" means the pin is one of the wire's **reported points** —
    # not "one of its first/last points": the host reports a wire's geometry as a
    # point list that can repeat and reorder what was drawn around its junctions
    # (measured 035: the two-point wire (345,290)→(405,290) was reported as
    # `[405,290, 345,290]`, and an L `(345,290)→(345,300)→(255,300)` came back as
    # `[345,300, 345,290, 255,300, 345,300]` — the pin is *interior* there). A
    # wire that reports the pin as one of its points is drawn to it.
    endpoints = [
        segment for segment in wires
        if any(same_point(point, pin_at) for point in segment.points)
    ]
    # A T is a wire that only *passes over* the pin: the pin lies between two
    # reported points and is not itself one of them.
    through = [
        segment for segment in wires
        if segment not in endpoints
        and any(
            _on_segment(pin_at, segment.points[i], segment.points[i + 1])
            for i in range(len(segment.points) - 1)
        )
    ]
    labels = [
        _state_of(entry) for entry in (geometry or {}).get("netlabels") or []
        if same_point(
            (_number(_state_of(entry).get("X")), _number(_state_of(entry).get("Y"))),
            pin_at,
        )
    ]
    flags = [
        entry for entry in (geometry or {}).get("components") or []
        if _text(_state_of(entry).get("ComponentType")) == "netflag"
        and same_point(
            (_number(_state_of(entry).get("X")), _number(_state_of(entry).get("Y"))),
            pin_at,
        )
    ]

    candidates = len(endpoints) + len(labels)
    if len(endpoints) + len(labels) + len(through) + len(flags) > 1 or candidates == 0:
        raise AttachmentRefused(_why_ambiguous(pin_at, endpoints, labels, through, flags))
    if labels:
        state = labels[0]
        net = _text(state.get("Net")) or _text(state.get("Text"))
        raise AttachmentRefused(
            f"({pin_at[0]:g}, {pin_at[1]:g}) carries a **net label** {net!r}, and this "
            "machine has no way to delete one: the host exposes no net-label primitive "
            "(`sch.geometry` reports `read sch_PrimitiveNetLabel: absent`) and the "
            "connector's delete index carries no net-label class. 本机没有删 netlabel 的"
            "能力 —— 拒绝，不许改成删别的东西（035 裁决 1）"
        )
    segment = endpoints[0]
    # Name the far end, not "the second point in the list": the host reports a
    # fresh wire's endpoints in whichever order it likes (measured 035: drawn
    # (345,290)→(405,290), reported [405,290, 345,290]), so the *other* end is the
    # one that is not the pin.
    far = next(
        (point for point in segment.points if not same_point(point, pin_at)), None
    )
    return Attachment(
        kind=ATTACHMENT_WIRE,
        primitive_id=segment.primitive_id,
        at=pin_at,
        detail=(
            f"the wire {segment.primitive_id} carrying net {segment.net!r} has an endpoint "
            f"on the pin at ({pin_at[0]:g}, {pin_at[1]:g})"
            + (f" (its other end is ({far[0]:g}, {far[1]:g}))" if far else "")
        ),
    )


def _why_ambiguous(
    pin_at: tuple[float, float],
    endpoints: list[WireSegment],
    labels: list[dict[str, Any]],
    through: list[WireSegment],
    flags: list[dict[str, Any]],
) -> str:
    """Name what was found, so the refusal is actionable rather than a shrug."""
    where = f"({pin_at[0]:g}, {pin_at[1]:g})"
    if not (endpoints or labels or through or flags):
        return (
            f"nothing recognisable attaches {where}: no wire endpoint, no label, no flag. "
            "The pin's net comes from something this slice cannot see — refusing to guess "
            "(035 §2.2)"
        )
    parts: list[str] = []
    if len(endpoints) > 1:
        parts.append(
            f"{len(endpoints)} wires end on it ("
            + ", ".join(f"{s.primitive_id} ({s.net!r})" for s in endpoints) + ")"
        )
    if len(labels) > 1:
        parts.append(f"{len(labels)} net labels sit on it")
    if through:
        parts.append(
            "a wire passes through it mid-segment (T-shape): "
            + ", ".join(f"{s.primitive_id} ({s.net!r})" for s in through)
        )
    if flags:
        net = _text(_state_of(flags[0]).get("Net"))
        parts.append(
            f"a net flag {net!r} sits on it (a flag is a component, and this slice "
            "recognises only wire and net label — 035 §2)"
        )
    return (
        f"{where}: " + "; ".join(parts) + " — 分不清该删哪一个，拒绝（035 §2.2："
        "T 型/多于一个/找不到一律不猜）"
    )


def wire_endpoints_on_pin(geometry: Any, pin_at: tuple[float, float], net: str = "") -> list[str]:
    """Ids of the wires with an endpoint on this pin (optionally of one net).

    The canvas proof of a `wire` connection: after apply, at least one wire has to
    end on the pin, or nothing was joined. Counted for a *report*, never as the
    verdict — the netlist readback is what decides (029's rule).
    """
    out: list[str] = []
    for segment in wire_segments(geometry):
        if net and segment.net != net:
            continue
        if any(same_point(point, pin_at) for point in segment.points):
            out.append(segment.primitive_id)
    return out


def wires_through_pin(geometry: Any, pin_at: tuple[float, float]) -> list[str]:
    """Ids of the wires that pass **through** the pin (a mid-segment T)."""
    out: list[str] = []
    for segment in wire_segments(geometry):
        if any(same_point(point, pin_at) for point in segment.points):
            continue
        if any(
            _on_segment(pin_at, segment.points[i], segment.points[i + 1])
            for i in range(len(segment.points) - 1)
        ):
            out.append(segment.primitive_id)
    return out


def primitive_present(geometry: Any, primitive_id: str) -> bool:
    """Is this wire id still on the page? (the disconnect's range check)."""
    return any(segment.primitive_id == primitive_id for segment in wire_segments(geometry))


def flag_on_pin(geometry: Any, pin_at: tuple[float, float], net: str = "") -> bool:
    """Does a net flag sit on the pin, optionally named `net` (029's mechanism)."""
    for entry in (geometry or {}).get("components") or []:
        state = _state_of(entry)
        if _text(state.get("ComponentType")) != "netflag":
            continue
        if net and (_text(state.get("Net")) != net):
            continue
        if same_point(
            (_number(state.get("X")), _number(state.get("Y"))), pin_at
        ):
            return True
    return False


def net_label_on_pin(geometry: Any, pin_at: tuple[float, float]) -> bool:
    """Does a net label sit on the pin? (unobservable on this host; see 035 ruling)"""
    for entry in (geometry or {}).get("netlabels") or []:
        state = _state_of(entry)
        if same_point((_number(state.get("X")), _number(state.get("Y"))), pin_at):
            return True
    return False


def live_pin_nets(payload: Any) -> dict[tuple[str, str], str]:
    """``(designator, pin) -> net name`` from an ``sch.netlist`` answer (035 round 3).

    The editor's **own** netlist is the fresh reading: measured 2026-09-24 on
    3.2.186, it separates two pins the moment the wire between them is deleted,
    while the project *export* went on reporting them together at 0 s, after a
    save, 30 s later and after a page switch — the export does not recompute for a
    deletion. The shape it answers in is
    ``components[<id>].pinInfoMap[<pin>].net``, and it reports **names**: a pin on
    an unnamed (auto) net reads ``""``.

    That last fact is why the flow pairs this with a canvas leg and refuses to
    call a half-checked repair done: the name proves what it can prove, the canvas
    proves the rest, and "one leg only" is `unknown`, not success.
    """
    data = payload
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        import json

        try:
            data = json.loads(payload["text"])
        except ValueError:
            return {}
    if not isinstance(data, dict):
        return {}
    out: dict[tuple[str, str], str] = {}
    for component in (data.get("components") or {}).values():
        if not isinstance(component, dict):
            continue
        props = component.get("props") if isinstance(component.get("props"), dict) else {}
        designator = _text(props.get("Designator"))
        pins = component.get("pinInfoMap")
        if not designator or not isinstance(pins, dict):
            continue
        for number, info in pins.items():
            net = _text((info or {}).get("net")) if isinstance(info, dict) else ""
            out[(designator, str(number))] = net
    return out


def overlay_live_nets(
    model: DesignModel, live_nets: dict[tuple[str, str], str]
) -> DesignModel:
    """Put the editor's fresh connectivity **on top of** an exported model (035 三轮).

    The re-review after a repair judges the pin with `rules.facts.pin_ruling`,
    which reads a parsed ``DesignModel``. The project export is the source of that
    model everywhere else, but a *deletion* does not make the export recompute
    (measured 2026-09-24: it went on joining the deleted wire's two pins at 0 s,
    after a save, 30 s later and after a page switch), so a re-review built on it
    reports a **correct** repair as still broken — the delete form would never be
    able to say "applied". `sch.netlist` is the reading that is fresh, so where a
    run removed something the pin membership is taken from it:

    * every pin the live netlist names is re-seated — its ``net`` set, its old
      memberships dropped wherever they were;
    * the net **names** survive even when the live reading leaves one with no
      member pin, because a name is what the `must_connect` judgement compares
      against (dropping it would turn "reaches its target" into "unknown").

    The model is the caller's own freshly built one and is updated in place.
    """
    nets = {
        name: Net(name=name, pins=list(node.pins))
        for name, node in (model.nets or {}).items()
    }
    for component in model.components.values():
        for pin in component.pins:
            here = (str(component.designator), str(pin.number))
            if here not in live_nets:
                continue
            for node in nets.values():
                if here in node.pins:
                    node.pins = [member for member in node.pins if member != here]
            net = live_nets[here]
            pin.net = net or None
            if net:
                nets.setdefault(net, Net(name=net, pins=[])).pins.append(here)
    model.nets = nets
    return model


def pin_net(model: DesignModel, designator: str, pin: str) -> str | None:
    """The net name a pin sits on in a parsed model, or ``None``.

    Reads the component's own pins (the same source `rules/facts.py` uses), so a
    plan's `before_net` and this check cannot disagree about what "the pin is on
    that net" means.
    """
    component = model.components.get(designator)
    if component is None:
        return None
    for item in component.pins:
        if item.number == pin:
            return item.net
    return None


def pin_group(model: DesignModel, designator: str, pin: str) -> frozenset[tuple[str, str]]:
    """Every pin that shares a net with this one (itself included, when known).

    A frozenset of ``(designator, pin)`` pairs rather than a net *name*: the
    editor renumbers auto-nets whenever a wire changes (measured in 029: NET1…
    NET7 shuffled between two reads of the same page), while the **partition** of
    pins is stable. Every readback judgement here is built on the partition for
    that reason.
    """
    for _name, net in (model.nets or {}).items():
        members = frozenset((str(name), str(number)) for name, number in net.pins)
        if (designator, pin) in members:
            return members
    return frozenset({(designator, pin)})


def _groups(model: DesignModel, *, exclude: tuple[str, str] | None) -> set[frozenset[tuple[str, str]]]:
    groups: set[frozenset[tuple[str, str]]] = set()
    for _name, net in (model.nets or {}).items():
        members = frozenset((str(name), str(number)) for name, number in net.pins)
        if exclude is not None:
            members = members - {exclude}
        if members:
            groups.add(members)
    return groups


def outside_scope_differences(
    before: DesignModel, after: DesignModel, *, designator: str, pin: str
) -> list[str]:
    """Netlist changes **other than** the repaired pin's own connection (035 §3).

    The acceptance asks for "范围外网表零差异", and this is how that is judged
    without trusting net *names*: every pin's company (its connected group, with
    the repaired pin taken out of it) has to be identical before and after. A
    deleted wire that also carried another pin shows up here as that pin's group
    losing a member — the accident the range check exists to catch.
    """
    before_groups = _groups(before, exclude=(designator, pin))
    after_groups = _groups(after, exclude=(designator, pin))
    problems: list[str] = []
    for group in sorted(before_groups - after_groups, key=lambda g: sorted(g)):
        problems.append(
            f"these pins were connected before and are not any more: "
            + ", ".join(f"{name}.{number}" for name, number in sorted(group))
        )
    for group in sorted(after_groups - before_groups, key=lambda g: sorted(g)):
        problems.append(
            f"these pins are connected now and were not before: "
            + ", ".join(f"{name}.{number}" for name, number in sorted(group))
        )
    return problems


def readback_verdict(
    model: DesignModel, *, designator: str, pin: str, before_net: str, after_net: str
) -> str:
    """Did the pin end up where the plan said? ``""`` = yes, else the reason.

    Three claims, one per form:

    * **connect / reconnect** (``after_net`` non-empty): the pin's own net is
      ``after_net`` — the name *we* put there (a wire carries it, a flag is named
      with it), so this one name is ours to check;
    * **disconnect** (``after_net`` empty): the pin's group is the pin **alone**
      and its name is no longer ``before_net``. "Alone" is the honest read of
      "touches nothing": an unconnected pin gets its own auto-named net in the
      editor's export (measured 029-b: `NET5 [('U9','3')]`).
    """
    now = pin_net(model, designator, pin)
    if after_net:
        if now == after_net:
            return ""
        return (
            f"{designator} pin{pin} sits on {now!r} in the project's own netlist, not "
            f"on the promised {after_net!r}"
        )
    # The disconnect verdict is the **rule's own** reading of "connected" (035
    # round-2 ruling A): shares a net with someone, or sits alone on a net
    # somebody *named* (naming is intent). A single-member auto net (`NET7`) is the
    # shape the editor leaves for a pin that reaches nothing, so that one is a
    # success — and reading it the same way here and in the rule is what makes
    # "the repair worked" and "the rule is satisfied" the same statement.
    from ..rules import facts as facts_rules

    component = model.components.get(designator)
    if component is None:
        return f"{designator} is not in the re-exported project at all"
    connected, how = facts_rules.nc_violation(model, component, pin)
    if connected:
        return f"{designator} pin{pin} is still connected — it {how}"
    return ""
