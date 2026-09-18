"""Action-plan generator for the draw flow (task 006, revisions 2-4).

Turns a :class:`~boardwise.core.model.DesignModel` — normally parsed from the
golden board — into an *ordered action plan* the bridge can execute against a
blank schematic page, and — since revision 3 — the complete geometry for that
plan, computed *offline*:

1. placements come from :mod:`boardwise.engines.layout` (shelf packing inside
   the sheet frame, clear of the title block, boxes never overlapping);
2. wires and net names are routed *before* anything executes: the editor
   exposes no pin primitives on a schematic page (measured), so pin
   positions are ``placement + symbol offset`` — exact, because the flow
   places everything unrotated and unmirrored and the canvas units are 1:1
   with the file's. The router is a grid BFS that never crosses a component
   box, never lets two nets touch, and hands back an on-wire attach point
   for every net's port / power flag;
3. :func:`validate_full` re-checks all five hard constraints on the finished
   geometry; the draw flow prints the report and *refuses to execute* when
   anything fails.

Coordinate spaces, stated once: symbol offsets from the parser are in *file*
space (the .epru stream's y axis); the editor canvas negates y. Everything in
this module and in :mod:`boardwise.engines.layout` speaks *canvas* space —
:func:`canvas_pin_offsets` is the one conversion point.

Nets are named with editor-native primitives rather than ``createNetLabel``,
which the reference implementation measured hanging on EasyEDA 3.2.186
(#191) and which the type package marks "ADD since EDA v4" — on this host it
can never settle. Power/ground rails get one ``Ground``/``Power`` flag
attached to the wire. Signal nets follow the **naming strategy** (006b
revision 3, :data:`NAMING_STRATEGIES`): the wire carries the net name (the
editor's netlist accepts it, measured), and by default a decorative text
primitive is drawn beside it so a reader can see the name. Net ports are
never emitted. NC pins are never wired and are listed explicitly — the diff
report must distinguish "left open on purpose" from "forgotten".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from boardwise.core.model import DesignModel
from boardwise.engines import layout
from boardwise.engines.layout import Placement, RoutedNet, Violation

#: Kept for backwards compatibility of the CLI defaults; the layout engine
#: derives its own packing from the sheet constants instead.
DEFAULT_PITCH = 400.0

#: Value fragments that mark a capacitor-like part worth placing next to the
#: chip it decouples. Deliberately broad; a wrong guess only costs layout.
_DECOUPLING_HINTS = ("pF", "nF", "µF", "uF")


#: Naming strategies for signal nets (task 006b revision 3, sanctioned by 岳翔宇).
#:
#: The only API that creates a *real* net label is `createNetLabel`, which the
#: type package marks "ADD since EDA v4" — and the measured host is the v3.2
#: line, where the call never settles. So "how is a signal net named" is a
#: policy, not a constant, and the policy is explicit and reported:
#:
#: ``wire``  the wire itself carries the net name (`sch_PrimitiveWire.create`
#:           with ``net``). Measured on the host: the editor's own netlist
#:           accepts it, so the net is electrically named — with **no visible
#:           label**. Zero net ports.
#: ``text``  ``wire`` **plus** a free text primitive drawn beside the wire
#:           (a *decorative* name: visible to a reader, not an electrical
#:           object). This is the default, because 岳翔宇's rule is that a
#:           signal net's name must be *seen*, and text is the closest legal
#:           form on this host. The report must label it "text, not a native
#:           label".
#: ``label`` the native ``sch.place_netlabel`` path. Kept behind a switch
#:           because it is the correct API on a v4 host and costs one flag to
#:           re-enable — dormant here, and timeout-protected.
#: ``none``  wires only, no names at all.
#:
#: Net ports are never emitted by any strategy (岳翔宇's ban; the action stays
#: in the catalogue for the solver's last resort only).
NAMING_STRATEGIES = ("wire", "text", "label", "none")

#: The default strategy. ``text``: a reader sees the net name, and the report
#: says how it was drawn.
DEFAULT_NAMING_STRATEGY = "text"


def normalise_strategy(value: str | None) -> str:
    """Coerce a user-supplied strategy name, falling back to the default.

    An unknown value is *reported*, never silently swallowed: the caller is
    told what ran (``replay_or_solver`` returns the source; the draw gate and
    the CLI both print the strategy), because a naming policy that changes
    without saying so is exactly the failure mode this task exists to stop.
    """
    if value is None:
        return DEFAULT_NAMING_STRATEGY
    candidate = str(value).strip().lower()
    return candidate if candidate in NAMING_STRATEGIES else DEFAULT_NAMING_STRATEGY


@dataclass
class PlacementStep:
    """One ``sch.place_component`` call."""

    designator: str
    x: float
    y: float
    rotation: float = 0.0
    mirror: bool = False
    lcsc: str = ""
    keyword: str = ""
    value: str = ""
    footprint: str = ""
    #: An explicit library device pair. Used when a keyword's first hit is the
    #: wrong part (§G: R24/R27 must be a real 0402) — a search hands back the
    #: pair, and `lib.footprint.get` is what proves the package.
    device_uuid: str = ""
    library_uuid: str = ""

    def resolution(self) -> dict[str, str]:
        """The params that let the connector resolve a library device.

        Order matters: an explicit uuid pair is the most specific statement
        about *which* part is wanted, so it outranks an lcsc number, which in
        turn outranks a keyword.
        """
        if self.device_uuid:
            params = {"deviceUuid": self.device_uuid}
            if self.library_uuid:
                params["libraryUuid"] = self.library_uuid
            return params
        if self.lcsc:
            return {"lcsc": self.lcsc}
        if self.keyword:
            return {"keyword": self.keyword}
        return {}


@dataclass
class WireStep:
    """One ``sch.place_wire`` polyline, named with its net."""

    net: str
    points: list[tuple[float, float]]


@dataclass
class NetNameStep:
    """One naming action for a net.

    ``kind`` is the *action family*: ``'Ground'``/``'Power'`` for a flag,
    ``'label'`` for the native net-label action, ``'text'`` for the decorative
    fallback. ``decorative`` is set on the text form so the report can state
    plainly that the name is drawn, not electrically attached.
    """

    net: str
    kind: str  # 'Ground' | 'Power' | 'label' | 'text'
    x: float
    y: float
    rotation: float = 0.0
    mirror: bool = False
    decorative: bool = False


@dataclass
class ActionPlan:
    """The ordered plan: placements, then naming and wiring — all offline."""

    placements: list[PlacementStep] = field(default_factory=list)
    net_names: list[NetNameStep] = field(default_factory=list)
    wires: list[WireStep] = field(default_factory=list)
    #: (designator, pin number) pairs left unconnected on purpose.
    nc_pins: list[tuple[str, str]] = field(default_factory=list)
    #: Geometry placements (with boxes) — the validator's input.
    geometry: list[Placement] = field(default_factory=list)
    #: (designator, pin) -> canvas point of the pin tip, as planned. The
    #: self-check, the missing-pin report and the tests all read the tips
    #: from here instead of recomputing them a second way.
    pin_positions: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    #: The signal-naming policy this plan was built under (006b revision 3).
    naming_strategy: str = DEFAULT_NAMING_STRATEGY
    #: Everything the generator could not express, for the gate report.
    notes: list[str] = field(default_factory=list)
    #: Self-check failures; non-empty means DO NOT EXECUTE.
    violations: list[Violation] = field(default_factory=list)

    @property
    def decorative_names(self) -> list[NetNameStep]:
        """The naming steps that are visible text rather than electrical names."""
        return [step for step in self.net_names if step.decorative]

    def summary(self) -> str:
        """The human gate reads this before any action is executed."""
        return (
            f"components: {len(self.placements)}  "
            f"nets named: {len(self.net_names)}  "
            f"wires: {len(self.wires)}  "
            f"NC pins: {len(self.nc_pins)}  "
            f"naming: {self.naming_strategy}  "
            f"notes: {len(self.notes)}  "
            f"violations: {len(self.violations)}"
        )


def canvas_pin_offsets(
    file_offsets: dict[str, dict[str, tuple[float, float]]],
) -> dict[str, dict[str, tuple[float, float]]]:
    """File-space offsets -> editor canvas space (negate y, once, here).

    The parser's offsets are file-space; the editor canvas negates y
    (measured, and the calibration test pins it). Everything downstream —
    layout, routing, the wire steps — is canvas space, so the conversion
    happens exactly here and nowhere else.
    """
    return {
        designator: {number: (dx, -dy) for number, (dx, dy) in offsets.items()}
        for designator, offsets in file_offsets.items()
    }


def strip_dangling_nets(model: DesignModel) -> DesignModel:
    """Nets with a single member are dangling wires — clear them.

    A one-pin net names nothing: the golden board has a few leftover wire
    stubs (U1's unconnected pins carry short wires), the drawn board will
    not reproduce them (there is nothing to connect *to*), and the editor's
    own netlist reports such pins unconnected on the golden page (measured
    during the P1 calibration). Both sides must therefore treat these pins
    as unconnected, or the diff reports nine phantom differences.

    Returns a shallow-copy-equivalent model; the input is mutated too
    (callers own their model), but the return keeps the call site honest.
    """
    for name in list(model.nets):
        net = model.nets[name]
        if len(net.pins) >= 2:
            continue
        for des, pin in net.pins:
            component = model.components.get(des)
            if component is None:
                continue
            for p in component.pins:
                if p.number == pin:
                    p.net = None
        del model.nets[name]
    return model


def _is_power_net(name: str) -> bool:
    return layout._net_kind(name) in ("Ground", "Power")


def _decoupling_next_to_host(model: DesignModel, host: str) -> set[str]:
    """Designators of cap-like parts sharing a net with ``host``."""
    host_nets = {
        net.name
        for net in model.nets.values()
        if any(des == host for des, _pin in net.pins)
    }
    out: set[str] = set()
    for designator, component in model.components.items():
        if designator == host:
            continue
        if any(hint in component.value for hint in _DECOUPLING_HINTS):
            shares = {
                net.name
                for net in model.nets.values()
                if any(des == designator for des, _pin in net.pins)
            }
            if shares & host_nets:
                out.add(designator)
    return out


def _layout_order(model: DesignModel) -> tuple[str, list[str]]:
    """Host designator first, then components by connectivity distance.

    Breadth-first over "shares a net with", ties broken by designator so the
    order is stable for tests. The host is the component with the most pins.
    """
    if not model.components:
        return "", []
    host = max(
        model.components,
        key=lambda d: (len(model.components[d].pins), d),
    )
    adjacency: dict[str, set[str]] = {d: set() for d in model.components}
    for net in model.nets.values():
        deses = sorted({des for des, _pin in net.pins if des in adjacency})
        for a in deses:
            adjacency[a].update(b for b in deses if b != a)

    decoupling = _decoupling_next_to_host(model, host)
    order: list[str] = [host]
    seen = {host}
    # Decoupling caps come right after the host: that is the whole point.
    for designator in sorted(decoupling):
        order.append(designator)
        seen.add(designator)
    frontier = [host]
    while len(order) < len(model.components):
        nxt: list[str] = []
        for current in frontier:
            for neighbor in sorted(adjacency[current]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    nxt.append(neighbor)
        if not nxt:
            for designator in sorted(model.components):
                if designator not in seen:
                    seen.add(designator)
                    nxt.append(designator)
            nxt.sort()
        order.extend(nxt)
        frontier = nxt
    return host, order


def naming_steps_for(
    route: "RoutedNet",
    attach: tuple[float, float] | None,
    strategy: str,
) -> list[NetNameStep]:
    """The naming action(s) for one routed net, under ``strategy``.

    Power/ground rails always get their flag (the strategy governs *signal*
    nets only — the ban and the default are both about signal names). A signal
    net's steps depend on the strategy:

    * ``wire`` — nothing to place: the name rides on the wire itself;
    * ``text`` — one decorative text primitive at the attach point;
    * ``label`` — one native net label (dormant on the v3.2 host);
    * ``none`` — nothing.

    ``kind`` on the returned step is the action family the draw flow
    dispatches on; ``decorative`` marks the text form.
    """
    if attach is None:
        return []
    x, y = attach
    if route.kind in ("Ground", "Power"):
        return [NetNameStep(net=route.net, kind=route.kind, x=x, y=y)]
    if strategy == "text":
        return [
            NetNameStep(net=route.net, kind="text", x=x, y=y, decorative=True)
        ]
    if strategy == "label":
        return [NetNameStep(net=route.net, kind="label", x=x, y=y)]
    return []


def _keyword_for(component) -> str:
    """The keyword the connector searches when a part has no LCSC number.

    A bare value is a footgun: ``5.1K`` matches any 5.1K resistor the library
    happens to rank first, so a 0402 golden part silently becomes a 0603
    placement and every wire endpoint misses its pin tip (round 4, §E). The
    keyword must therefore carry a *footprint constraint* whenever we know
    one, and fall back to the library device title — which in this library is
    itself footprint-encoded (``Res_0402``) — before ever using a bare value.
    """
    value = (component.value or "").strip()
    title = (component.props.get("device_name") or "").strip()
    footprint = (component.footprint or "").strip()
    if value and footprint:
        return f"{value} {footprint}"
    if title:
        return title
    return value


def generate_plan(
    model: DesignModel,
    offsets: dict[str, dict[str, tuple[float, float]]],
    strategy: str | None = None,
) -> ActionPlan:
    """Build the complete, self-checked action plan for ``model``.

    ``offsets`` are *canvas-space* symbol offsets (see
    :func:`canvas_pin_offsets`). ``strategy`` is the signal-naming policy
    (:data:`NAMING_STRATEGIES`); ``None`` means the default. Pure: no bridge,
    no editor, no I/O. The returned plan carries its own geometry and
    self-check violations — a non-empty ``violations`` list means the draw flow
    must refuse to execute (revision 3's gate).
    """
    plan = ActionPlan()
    plan.naming_strategy = normalise_strategy(strategy)
    if not model.components:
        plan.notes.append("the model has no components; nothing to draw")
        return plan

    _host, order = _layout_order(model)
    geometry = layout.plan_placement(offsets, order)
    plan.geometry = geometry

    for place in geometry:
        component = model.components[place.designator]
        plan.placements.append(
            PlacementStep(
                designator=place.designator,
                x=place.x,
                y=place.y,
                lcsc=component.lcsc_part,
                keyword=_keyword_for(component),
                value=component.value,
                footprint=component.footprint,
            )
        )

    # pin positions in canvas space: origin + offset (all unrotated)
    pin_positions: dict[tuple[str, str], tuple[float, float]] = {}
    for place in geometry:
        for number, (dx, dy) in offsets.get(place.designator, {}).items():
            pin_positions[(place.designator, number)] = (place.x + dx, place.y + dy)
    plan.pin_positions = pin_positions

    for designator, pin in sorted(
        (des, pin.number)
        for des, component in model.components.items()
        for pin in component.pins
        if pin.net is None
    ):
        plan.nc_pins.append((designator, pin))

    routes, routing_violations = layout.route_nets(model, pin_positions, geometry)
    for route in routes:
        for poly in route.polylines:
            if len(poly) >= 2:
                plan.wires.append(WireStep(net=route.net, points=poly))
        if route.attach is not None:
            plan.net_names.extend(naming_steps_for(route, route.attach, plan.naming_strategy))
        else:
            plan.notes.append(f"net {route.net} routed but has no on-wire attach point")

    plan.violations = layout.validate_full(model, geometry, routes, pin_positions)
    plan.violations.extend(routing_violations)
    return plan


def self_check_report(plan: ActionPlan) -> list[str]:
    """Rendered self-check lines: one per violation, empty when clean."""
    return [v.render() for v in plan.violations]
