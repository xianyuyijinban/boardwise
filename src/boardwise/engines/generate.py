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

Coordinate spaces, stated once: the `.epro2` stores y opposite to the canvas, so
the **parser negates the axis once at its own boundary** and hands over canvas
coordinates; everything in this module and in
:mod:`boardwise.engines.layout` speaks *canvas* space, which is what the bridge
actions take. :func:`canvas_pin_offsets` is the name of that boundary, and it is
an *identity* today: it is kept, and kept named, as the one checkpoint a
coordinate guard can point at (the 010c measurement and
`tests/test_coordinate_guards.py` are what closed the double negation), not
because a conversion happens there. Canvas space is y-**up**, and one canvas
unit is 10 mil = 0.254 mm (`boardwise.core.symbolprofile.Box`), not one mil.

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
from boardwise.core.values import parse_capacitance_farads
from boardwise.engines import layout
from boardwise.engines.layout import Placement, RoutedNet, Violation

#: Kept for backwards compatibility of the CLI defaults; the layout engine
#: derives its own packing from the sheet constants instead.
DEFAULT_PITCH = 400.0

#: The capacitance unit spellings this ordering hint knows, **lower case**, and
#: the same keys `rules/values.parse_capacitance_farads` reads. It is kept as the
#: readable statement of the question ("does this value look like a capacitor at
#: all"), pinned to the reader's own unit table by a test so the two cannot drift
#: — **but it is not the ruler any more**: the ruler is the reader itself, so a
#: spelling the rule engine measures as a capacitor is a capacitor here too
#: (143e, D10: a case-sensitive substring test against the upper-case spellings
#: of this tuple is what made ``100NF``/``0.1UF`` — the commonest supplier
#: spellings — decoupling caps to the rule engine and strangers to this hint).
_DECOUPLING_HINTS = ("pf", "nf", "µf", "uf")


#: Naming strategies for signal nets (task 006b revision 3, sanctioned by
#: xianyuyijinban; ``auto`` added by the 134 ruling of 2026-10-08).
#:
#: The only API that creates a *real* net label is `createNetLabel`, which the
#: type package marks "ADD since EDA v4" — and the measured host is the v3.2
#: line, where the call never settles. So "how is a signal net named" is a
#: policy, not a constant, and the policy is explicit and reported:
#:
#: ``auto``  **the default**: name a signal net only where a name is the only
#:           way to read it — the net's wires run *long*
#:           (:data:`LONG_NET_LABEL_UNITS`) or its members sit on **more than
#:           one page**. Every other net is read off its wires, as a schematic
#:           is meant to be read. See :func:`needs_signal_label`.
#: ``wire``  the wire itself carries the net name (`sch_PrimitiveWire.create`
#:           with ``net``). Measured on the host: the editor's own netlist
#:           accepts it, so the net is electrically named — with **no visible
#:           *signal* label** (rails keep their flags, as under every strategy).
#:           Zero net ports.
#: ``text``  ``wire`` **plus** a free text primitive drawn beside the wire
#:           (a *decorative* name: visible to a reader, not an electrical
#:           object) for **every** signal net, however short. This is the
#:           screenful-of-labels complaint of 2026-10-08, so it is no longer the
#:           default; it stays available for a reader who wants a name on
#:           everything, and the report still says the name is drawn, not
#:           attached.
#: ``label`` the native ``sch.place_netlabel`` path. Kept behind a switch
#:           because it is the correct API on a v4 host and costs one flag to
#:           re-enable — dormant here, and timeout-protected.
#: ``none``  wires only: the wire still carries the net name, and **no signal
#:           name primitive is placed** at all. Power/ground rails keep their
#:           flags, as under every other strategy — this line used to read "no
#:           names at all", which contradicted :func:`naming_steps_for` and was
#:           the stale half (143e, D8): a rail's flag *is* that net's electrical
#:           naming rather than a decoration beside it, and the code has said so
#:           in both places it decides it.
#:
#: Every strategy governs **signal** nets; rails are always flagged, so read the
#: table above as "how a signal net is named", never as "what primitives appear".
#:
#: Net ports are never emitted by any strategy (xianyuyijinban's ban; the action stays
#: in the catalogue for the solver's last resort only).
NAMING_STRATEGIES = ("auto", "wire", "text", "label", "none")

#: The default strategy. ``auto``: a name is placed where a reader cannot get
#: the net from the wires alone, and nowhere else.
DEFAULT_NAMING_STRATEGY = "auto"

#: How long a signal net's wires must run before ``auto`` names it, in **canvas
#: units** — and one canvas unit is **10 mil = 0.254 mm** (0.01 in;
#: `boardwise.core.symbolprofile.Box`), which is also the unit
#: :func:`boardwise.engines.layout.polyline_length` answers in. The comparison
#: is therefore apples to apples; what was wrong was the arithmetic around it.
#:
#: **岳裁 2026-10-08：长距离才打.** The threshold answers "how far can a reader
#: follow a net", not "how many labels look tidy".
#:
#: **Units, stated once (143e, D4).** This comment used to price the ruling at
#: one unit to one mil (0.0254 mm) and read "1500 mil is ~38 mm, about 1.3x the
#: width of a big chip body and a bit over a third of an A4 landscape sheet
#: (:data:`~boardwise.engines.layout.SHEET_WIDTH` = 1169)". At the real factor
#: the constant is **1500 units = 15 000 mil = 381 mm**, which is longer than the
#: A4 landscape sheet is *wide* (1169 units = 297 mm): the sentence's own
#: arithmetic held under neither reading. As it stands, ``auto`` names a signal
#: net only when its wires run across practically the whole page (measured on
#: the golden board: 1 of 10 signal nets). The 38 mm the ruling was written for
#: is 150 canvas units (= 1500 mil), and under it 10 of 10 golden signal nets are
#: named — the screenful-of-labels state 134 was asked to end.
#:
#: **So the constant is left where it is, and that is deliberate**: moving it
#: 1500 -> 150 is a policy ruling (岳's, not a unit fix), and the honest unit
#: statement above is what makes the choice weighable. **House rule, the exact
#: number pending 岳's confirmation**: one named constant, so moving it moves the
#: policy for every page at once.
#:
#: What it is *not*: a clearance. Under it a net is read from its wires, and a
#: name on it would be a primitive without information — and every primitive is
#: one more chance to land on a part (see
#: :func:`boardwise.engines.layout.clear_label_point`).
LONG_NET_LABEL_UNITS = 1500.0


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
    #: (designator, pin number) pairs the netlist connects but the plan could
    #: **not place** — no position in the offsets table, so no wire reaches them
    #: (143e, D2). The counterpart of :attr:`nc_pins`, and deliberately a
    #: separate list: "left open on purpose" and "we could not draw it" must
    #: never be read as the same thing (module docstring).
    unplaced_pins: list[tuple[str, str]] = field(default_factory=list)
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
    """Pin offsets in, pin offsets out — canvas space, and **no conversion**.

    It used to negate y here ("file-space offsets -> canvas"), which is the
    second half of the double negation task 010c removed. The measurement behind
    that removal (M1, 2026-09-18): the `.epro2` stores y opposite to the canvas
    (`stored_y = -canvas_y`, 35/42 parts exact), so the parser negates once at
    its own boundary and hands over canvas coordinates. A second negation here
    did not cancel for hand-authored geometry — it mirrored it.

    Kept, and kept named, as the *checkpoint* the coordinate guards point at
    (`tests/test_coordinate_guards.py`): it is the one place a reader can look to
    see that no conversion happens on this side any more, instead of having to
    audit every engine call site for a stray sign.
    """
    return {
        designator: {number: (dx, dy) for number, (dx, dy) in offsets.items()}
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


def _is_capacitor_value(value: str) -> bool:
    """Is ``value`` a capacitance the **rule engine's own reader** accepts?

    One reader, not two (143e, D10). ``rules/values.parse_capacitance_farads``
    is what every rule measures capacitors with, so asking it here is the only
    way "a capacitor to the rules" and "a capacitor to the layout order" cannot
    disagree — the promise the mu-fold comment below already made. The
    case-sensitive substring test that stood here read only the lowercase
    spellings, so ``100NF`` and ``0.1UF`` (what a supplier's BOM writes) were
    capacitors to the rules and strangers to this hint; the reader also knows
    the trade's mid-letter notation (``4u7``, ``2n2``), which no hint list could
    have covered. A wrong guess only costs layout, so honesty about the ruler
    costs nothing.
    """
    return parse_capacitance_farads(value) is not None


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
        # The Greek small mu (U+03BC) is what a Chinese/Greek IME types for
        # "micro" and the MICRO SIGN (U+00B5) is what the library spells it
        # with; the reader folds the two together itself (its `_CAP_RE` carries
        # ``re.IGNORECASE`` and normalises the key), so `22μF` is a capacitor
        # here exactly as it is there — and so is every other spelling it reads.
        if _is_capacitor_value(component.value):
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


def net_pages_in_model(model: DesignModel, net_name: str) -> tuple[str, ...] | None:
    """The pages ``net_name``'s members sit on, or ``None`` for "no page data".

    Two sources, both already the model's own statement about itself:

    * :attr:`DesignModel.unproven_nets` — a name the per-page merge (issue #19)
      saw on more than one page. An **empty tuple is a real answer**: the tier
      merged models that carry no page ids, so it knows the name is shared and
      cannot name the pages. Hence the ``is not None`` test, never truthiness.
    * :attr:`DesignModel.cross_page_designators` — for the weaker case where no
      name was flagged but a designator sits on several pages; its members'
      pages are read off that. Used only when ``unproven_nets`` says nothing.

    ``None`` means *no evidence of more than one page*, which for a single-page
    reading is exactly right: one page's export *is* its connectivity.
    """
    pages = model.unproven_pages(net_name)
    if pages is not None:
        return pages
    net = model.nets.get(net_name)
    if net is None:
        return None
    found: set[str] = set()
    for des, _pin in net.pins:
        found.update(model.cross_page_designators.get(des, ()))
    return tuple(sorted(found)) or None


def is_cross_page_net(model: DesignModel, net_name: str) -> bool:
    """Does ``net_name``'s membership span **more than one page**?

    This is the second half of the ``auto`` strategy (岳裁 2026-10-08: 跨页
    才打). A net whose members are spread over sheets cannot be read off one
    sheet's wires — the reader on sheet 2 sees a wire with no far end — so it is
    named even when it is short. ``unproven_nets`` counts pages, so a welded
    name (page ids unknown, empty tuple) is cross-page *by construction*: it was
    seen twice.
    """
    pages = net_pages_in_model(model, net_name)
    if pages is None:
        return False
    if not pages:
        return True  # seen on more than one page; the tier could not name them
    return len(pages) > 1


def needs_signal_label(
    route: "RoutedNet",
    *,
    model: DesignModel | None = None,
    threshold: float = LONG_NET_LABEL_UNITS,
) -> tuple[bool, str]:
    """Does this **signal** net need a visible name? ``(yes, why)``.

    The ``auto`` strategy's whole decision, in one function so the answer can be
    read, tested and reported without running a plan (岳裁 2026-10-08: 信号网
    只在两种情况打标签). A net qualifies on either of two grounds:

    * **long distance** — its wires run further than ``threshold`` canvas units
      (:data:`LONG_NET_LABEL_UNITS`). Long is measured as the *routed* length
      (:func:`layout.polyline_length`), not the straight pin-to-pin distance,
      because the routed length is what the reader actually has to trace.
    * **cross page** — its members sit on more than one page
      (:func:`is_cross_page_net`); see there for what counts as evidence.

    Rails never reach this function: they always get their flag, and a power or
    ground flag is a *different* thing from a signal name (it is the naming of
    the net, not a decoration beside it).
    """
    if route.kind in ("Ground", "Power"):
        return (False, "rail: always flagged, never a signal label")
    length = layout.polyline_length(route.polylines)
    if length > threshold:
        return (
            True,
            f"long distance: {length:.0f} > {threshold:.0f} units of routed wire",
        )
    if model is not None and is_cross_page_net(model, route.net):
        return (True, "cross page: members sit on more than one sheet")
    return (
        False,
        f"short ({length:.0f} <= {threshold:.0f}) and single-page: read it off the wires",
    )


def naming_steps_for(
    route: "RoutedNet",
    attach: tuple[float, float] | None,
    strategy: str,
) -> list[NetNameStep]:
    """The naming action(s) for one routed net, under ``strategy``.

    Power/ground rails always get their flag (the strategy governs *signal*
    nets only — the ban and the default are both about signal names). A signal
    net's steps depend on the strategy:

    * ``auto`` — nothing, unless :func:`needs_signal_label` says the net is
      long or cross-page. ``attach`` is then only the *first* candidate: the
      caller resolves the final anchor through
      :func:`boardwise.engines.layout.clear_label_point`, which keeps the name
      on this net's wire but off everything else;
    * ``wire`` — nothing to place: the name rides on the wire itself;
    * ``text`` — one decorative text primitive at the attach point;
    * ``label`` — one native net label (dormant on the v3.2 host);
    * ``none`` — nothing.

    ``kind`` on the returned step is the action family the draw flow
    dispatches on; ``decorative`` marks the text form.

    ``auto`` needs the model to answer the cross-page half of its question and
    the routes to answer the distance half, so it is resolved by
    :func:`generate_plan`, which has both; this function is what decides the
    *form* of the step once the caller has answered *whether* there is one.
    """
    if attach is None:
        return []
    x, y = attach
    if route.kind in ("Ground", "Power"):
        return [NetNameStep(net=route.net, kind=route.kind, x=x, y=y)]
    if strategy == "auto":
        return [
            NetNameStep(net=route.net, kind="text", x=x, y=y, decorative=True)
        ]
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


#: How many pages the solver lays out before settling: the demanded channel
#: widths, WIDTH_STEP nets' worth narrower again, and so on, then the plain
#: packing (141). Every attempt costs a full routing of the sheet, so the list
#: is short — and its last entry is the packing the engine had before, which
#: always has an answer.
WIDTH_ATTEMPTS = 3

#: How many nets' worth of width the solver gives back per attempt. Two, not
#: one, is a cost decision with a measurement behind it: on the golden board the
#: pages at 60 and at 55 units of aisle are *both* unwireable and the page at 50
#: is the one that works, so stepping by one only pays for a routing that is
#: known to fail. The cost is real — the golden page takes ~20 seconds to lay
#: out and route — and the risk is bounded by the last attempt being the plain
#: packing, which is always tried.
WIDTH_STEP = 2


def _choose_geometry(model: DesignModel, offsets, order, attempt):
    """The widest channel allocation the router can actually wire (141).

    Sizing the page's gaps by the traffic that crosses them
    (:func:`~boardwise.engines.layout.plan_placement`) is what makes a crowded
    aisle readable, and it is not free: on the golden board the aisle carrying
    six nets is where 45% of the ``WIRE_TOO_CLOSE`` findings live, and giving it
    room takes the count from 47 to 34 — but giving it the *whole* width it asks
    for loses a net (measured: six nets abreast want 60 units, and the router
    cannot wire ``NET2`` on the page that has them). Readability must never
    outrank connectivity, so pages are tried widest first and the search stops
    at the first one that routes with nothing hard on it.

    Returns ``(geometry, pin_positions, routes, routing_violations,
    violations)`` for the page it settled on.
    """
    exits = layout.net_exits(model, offsets)
    pages = [
        layout.plan_placement(offsets, order, exits=exits,
                              spare_lanes=spare * WIDTH_STEP)
        for spare in range(0, WIDTH_ATTEMPTS - 1)
    ] if exits else []
    pages.append(layout.plan_placement(offsets, order))

    best = None
    for geometry in pages:
        pins, routes, routing_violations, violations = attempt(geometry)
        blocking = layout.blocking_violations(violations)
        if not blocking:
            return geometry, pins, routes, routing_violations, violations
        if best is None or len(blocking) < len(best[0]):
            best = (blocking, geometry, pins, routes, routing_violations, violations)
    _, geometry, pins, routes, routing_violations, violations = best
    return geometry, pins, routes, routing_violations, violations


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
    must refuse to execute (revision 3's gate). The geometry is the first page
    in :data:`WIDTH_ATTEMPTS` that routes cleanly; see :func:`_choose_geometry`.
    """
    plan = ActionPlan()
    plan.naming_strategy = normalise_strategy(strategy)
    if not model.components:
        plan.notes.append("the model has no components; nothing to draw")
        return plan

    _host, order = _layout_order(model)

    def attempt(geometry: list[layout.Placement]):
        """Everything the plan needs to be judged: geometry, pins and routes."""
        pins: dict[tuple[str, str], tuple[float, float]] = {}
        for place in geometry:
            for number, (dx, dy) in offsets.get(place.designator, {}).items():
                pins[(place.designator, number)] = (place.x + dx, place.y + dy)
        wired, wired_violations = layout.route_nets(model, pins, geometry)
        checked = layout.validate_full(model, geometry, wired, pins)
        checked.extend(wired_violations)
        return pins, wired, wired_violations, checked

    geometry, pin_positions, routes, routing_violations, violations = _choose_geometry(
        model, offsets, order, attempt
    )
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

    plan.pin_positions = pin_positions

    #: 143e, D2/D3: **what the plan could not draw, said out loud.**
    #:
    #: The router filters its net members by "has a known position"
    #: (:func:`layout.route_nets`), and ``validate_full`` reads its pin tips from
    #: the same table — so a netlist pin the offsets table cannot place is
    #: invisible to *both*: not wired, not reported, and not in ``nc_pins``
    #: (that list is built from ``pin.net is None``, which says "left open on
    #: purpose"). "We could not place it" masquerading as "left open on purpose"
    #: is exactly the confusion the module docstring forbids, so the two states
    #: get a list and a note each. A **pin-less component** is the same disease
    #: one level up: it has no keep-out box either, so constraint 1 cannot look
    #: at where it landed, and nothing else would have said so.
    plan.unplaced_pins = [
        (designator, pin)
        for _net_name, net in sorted(model.nets.items())
        for designator, pin in net.pins
        if (designator, pin) not in plan.pin_positions
    ]
    for designator, pin in plan.unplaced_pins:
        plan.notes.append(
            f"pin {designator}.{pin} is connected in the netlist but has no known "
            "position, so no wire reaches it — UNPLACED, not left open on purpose"
        )
    routed_nets = {route.net for route in routes}
    for net_name, net in sorted(model.nets.items()):
        if net_name in routed_nets or len(net.pins) < 2:
            continue
        plan.notes.append(
            f"net {net_name} is in the netlist but nothing was drawn for it"
        )
    for place in geometry:
        if place.bbox is None:
            plan.notes.append(
                f"component {place.designator} has no known pins, so it has no "
                "bounding box: the self-check cannot see where it landed"
            )

    for designator, pin in sorted(
        (des, pin.number)
        for des, component in model.components.items()
        for pin in component.pins
        if pin.net is None
    ):
        plan.nc_pins.append((designator, pin))

    #: 136: a net the router only managed by giving up its separation
    #: preference is said out loud in the plan's notes. The geometry itself is
    #: re-measured by :func:`validate_full` below, which reports whatever ended
    #: up genuinely too close as ``WIRE_TOO_CLOSE`` — this note is the *why*,
    #: that violation is the *how much*.
    for row in routing_violations:
        if row.code == "SEPARATION_GIVEN_UP":
            plan.notes.append(f"{row.subject}: {row.detail}")

    members_by_net = {
        name: {des for des, _pin in net.pins} for name, net in model.nets.items()
    }
    #: names already placed, so two labels never stack (the avoidance search's
    #: "what is on the page so far"). Populated as the loop places them.
    taken: list[tuple[float, float, str]] = []
    for route in routes:
        for poly in route.polylines:
            if len(poly) >= 2:
                plan.wires.append(WireStep(net=route.net, points=poly))
        if route.attach is None:
            plan.notes.append(f"net {route.net} routed but has no on-wire attach point")
            continue

        is_rail = route.kind in ("Ground", "Power")
        wanted, why = needs_signal_label(route, model=model)
        # Rails are exempt from the ``auto`` gate: a ground/power flag is the
        # *naming* of that net, not a decoration beside it, so it is placed
        # wherever the router anchored it exactly as under every other
        # strategy. Only signal names go through "does this net need one?".
        if plan.naming_strategy == "auto" and not is_rail and not wanted:
            # Read off the wires. Nothing is placed, so nothing is avoided and
            # nothing is reported as a missing name.
            continue
        if plan.naming_strategy == "auto" and not is_rail:
            point, problem = layout.clear_label_point(
                routes,
                route.net,
                geometry,
                members_by_net.get(route.net, set()),
                title_block=layout.Rect(*layout.TITLE_BLOCK),
                taken=taken,
            )
            if point is None:
                plan.notes.append(problem)
                continue
        else:
            point = route.attach
        steps = naming_steps_for(route, point, plan.naming_strategy)
        for step in steps:
            if step.kind in ("Ground", "Power"):
                continue
            if plan.naming_strategy == "auto":
                # `why` is `needs_signal_label`'s answer, and that function only
                # ever answers the ``auto`` question.
                plan.notes.append(f"net {step.net} is named because {why}")
            else:
                # 143e, D7: ``text``/``label`` name *every* signal net, so
                # printing `why` here produced "net X is named because short …
                # read it off the wires" — a note that contradicted itself and
                # contradicted the strategy, on the one screen 岳 signs off from.
                plan.notes.append(
                    f"net {step.net} is named because strategy "
                    f"{plan.naming_strategy} names every signal net"
                )
        plan.net_names.extend(steps)
        taken.extend((step.x, step.y, step.net) for step in steps)

    plan.violations = violations

    #: 143e, D1: **the anchors the plan draws go back through the gate.**
    #:
    #: The solver path used to validate annotation geometry against
    #: ``route.attach`` — the router's *candidate* — while ``auto`` hands the
    #: name to :func:`layout.clear_label_point`, which may return a different
    #: point (measured on the golden board: the one moved label is drawn 975
    #: units from the point the gate measured), and ``wire``/``none`` and every
    #: short signal net under ``auto`` put nothing there at all while still being
    #: measured. So ``LABEL_TOO_CLOSE`` / ``LABEL_FLOATS`` / ``LABEL_OVERLAP`` /
    #: ``LABEL_ON_TITLE_BLOCK`` could never fire on a name this generator
    #: produced, and a moved name could sit on a part, on a stranger's wire or in
    #: the title block with the gate reporting clean. Both annotation rulers run
    #: here, on the anchors the draw flow will actually execute:
    #:
    #: * :func:`layout.annotation_anchor_violations` — constraints 4/5, the
    #:   *same* function :func:`layout.validate_full` measures with, fed the real
    #:   anchors instead of the candidate (on-wire, and ``LABEL_CLEARANCE`` from
    #:   every foreign box);
    #: * :func:`layout.lint_annotations` — the four per-category readability
    #:   findings the replay path already runs, using ``generate``'s own
    #:   predicted text boxes so generation and checking share one ruler.
    #:
    #: ``plan.violations`` is what the draw gate reads, so this is what makes the
    #: module docstring's promise ("validate_full re-checks all five hard
    #: constraints on the finished geometry") true of the finished page rather
    #: than of a candidate that the plan then moves away from. The *page* was
    #: picked earlier without these rows — a label finding can therefore appear
    #: on the chosen page instead of the solver trying a narrower one; reported
    #: is what matters, and re-choosing a page for a label is 岳's call if the
    #: finding ever blocks a board that used to draw.
    plan.violations.extend(
        layout.annotation_anchor_violations(
            model,
            routes,
            geometry,
            [(step.net, step.x, step.y) for step in plan.net_names],
        )
    )
    plan.violations.extend(
        layout.lint_annotations(
            geometry,
            routes,
            plan.net_names,
            layout.Rect(*layout.TITLE_BLOCK),
            members_by_net=members_by_net,
        )
    )
    return plan


def self_check_report(plan: ActionPlan) -> list[str]:
    """Rendered self-check lines: one per violation, empty when clean."""
    return [v.render() for v in plan.violations]
