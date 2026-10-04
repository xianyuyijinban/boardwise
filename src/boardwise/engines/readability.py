"""The independent readability checker: 052 sec.6's hard half, executable.

052 sec.8 asks for a checker that works "from the plan and the specs alone, with
no access to the compiler's insides": the negative cases the whole drawing
pipeline rests on — a short, a wire on the wrong pin, an NC pin that got
connected, text printed on a component — have to be detectable **without**
trusting the generator's own bookkeeping. So this module imports no generator
and no compiler (there is none yet, and the import list is pinned by a test):
it consumes exactly a :class:`~boardwise.core.layoutplan.LayoutPlan`, a
:class:`~boardwise.core.circuitspec.CircuitSpec`, a
:class:`~boardwise.core.presentationspec.PresentationSpec` and the
:class:`~boardwise.core.symbolprofile.SymbolProfile` set those parts were drawn
with, and answers with findings.

**What it returns** (053 sec.2's declared shape)::

    CheckResult.hard_violations   list[HardViolation]   kind + objects + evidence
                  .grammar_findings list[Any]           empty unless injected
                  .soft_metrics     dict[str, float]    raw values, never a total
                  .soft_reasons     dict[str, list[str]] one line per deduction

`grammar_findings` is **always empty here**: executing a drawing grammar (is the
divider's tap visible, does the capacitor belong to the output node) is the
grammar module's job (053 sec.3, a different batch), and this file reaches it
only through the injected ``grammar_checker`` — the injection point exists and
is pinned by a test, so the two modules never have to import each other.
`soft_metrics` has no total by design (052 sec.6: "不能只报 aesthetics=4.2"),
and every key in `soft_reasons` is a key in `soft_metrics`.

**The nine hard constraints**, each with its own kind (the vocabulary is in
:data:`HARD_KINDS`, and violations are emitted in this order):

======================================  ==========================================
kind                                    what it refuses
======================================  ==========================================
``netlist-partition-mismatch``          the netlist derived from the plan has a
                                        different member partition *or* states a
                                        net name `CircuitSpec.nets` does not (a
                                        short, a wire on the wrong pin, a node the
                                        spec never declared, a swapped flag)
``dangling-wire-end``                   a wire end lands on nothing at all
``undeclared-junction``                 a wire vertex tees into another wire's
                                        span and the plan declares no junction
``wire-through-body``                   a wire crosses some non-end part's body
``text-overlap``                        two text boxes intersect, or text lands on
                                        a foreign part's body
``out-of-page``                         something leaves the page, or enters a
                                        keep-out region
``user-lock-violated``                  the plan does not honour a user lock
``nc-pin-connected``                    an explicit NC pin got wired up
``required-pin-not-connected``          a declared net member is connected to nothing
======================================  ==========================================

**The page-level domain (056 sec.3), a second vocabulary beside the nine.** Once
several modules are drawn on one page, four questions stop being answerable
inside a module, and :func:`check_page` asks them — the nine constraints above
are unchanged and keep their names, their order and their meanings:

==================================  ==========================================
kind                                what it refuses
==================================  ==========================================
``module-frame-overflow``           a module frame leaves the stated page
``module-frame-overlap``            two module frames overlap, or are closer than
                                    the page's own module-gap constant
``geometry-outside-module-frames``  a part, a text, a name anchor or a wire end
                                    that lies in no module frame at all
``module-part-unassigned``          a placed part belongs to no module, or to two
``wire-through-module-frame``       a wire runs through a frame that is not one
                                    of the frames its own two ends are in, or
                                    leaves one of them and comes back
``shared-net-expression-split``     one shared net stated a wire in one place and
                                    a name in another, or a label in one module
                                    and a flag in the other
``main-path-edge-not-wired``        a flow edge the presentation marks
                                    `mainPath` whose connection is not a wire
``page-keepout-conflict``           a stated keep-out lands on a module frame
==================================  ==========================================

Two of those deserve the reason they exist. ``wire-through-module-frame`` is
*not* the nine's ``wire-through-body``: a wire may legally pass through the empty
part of a module's frame (between its bodies), and the rule the page owes is that
it does not — "绕行义务在线不在框" (056 sec.3) — except for the one escape run
between a port and its own frame's edge. And ``shared-net-expression-split`` is
the page's version of ``uniform-gnd``: two modules that name the same net must
name it the same way, because the join happens **by name**, and a net that is a
wire in one module and a label in the other is a drawing whose reader cannot tell
whether the two are one connection (the exception is a whole ``mainPath`` edge,
which is one wire and no name at either end).

What this domain deliberately does **not** do: it does not require the frames to
be *exactly* the module's bounding box. A frame is a stated page fact, and what
the checker tests is what makes it usable — that it holds its module's own
geometry, that it is clear of the other frames, that it is on the page, and that
the wires respect it. Recomputing the exact box would be re-running the
compiler's own bounding computation, which is the one thing an independent check
may not do.

**Object names.** Violations name what they are about, with the document area as
the prefix, so a reader can go straight to it: plan side ``parts[R1]``,
``segments[0]``, ``junctions[2]``, ``labels[3]``, ``powerSymbols[0]``,
``texts[1]``; spec side ``circuitSpec.nets[VIN]``, ``circuitSpec.nc[R1.2]``,
``presentationSpec.userLocks[R1]``; and ``pins[R1.2]`` for a pin, which is a
derived notion both sides share.

**Units and tolerances.** Every coordinate is in *canvas units* (0.01 in —
:data:`boardwise.core.symbolprofile.Box`'s unit, i.e. 10 mil), the same space
`LayoutPlan` and `SymbolProfile` use. Two coordinates are equal when they agree
to :data:`PRECISION` (6) decimals, i.e. within :data:`TOL` = 1e-6 canvas units:
the drawing world is a grid of integers, so *exact* equality is the rule, and
rounding to 1e-6 is what removes the float noise a rotation introduces
(``cos(90°)`` is 6.1e-17, not 0). Tolerance is never used to forgive a real
offset — a wire 0.5 units off a pin tip is a dangling end, not a rounding
difference.

**How the netlist is derived** (:func:`derive_netlist`, no generator state):

* every placed pin's tip is mapped into page coordinates with the **same**
  rigid transform the parser uses (:func:`boardwise.core.geometry.transform_point`
  — mirror, then CCW rotation, then the part's origin). A symbol profile's tip
  is a *local* coordinate; forgetting the pose would silently move every pin of
  every rotated part;
* a wire vertex landing on another wire's span joins them (the editor
  junction-dots that; 053 sec.2 makes the missing dot its own finding), while
  two wires that merely cross stay separate — that is measured editor behaviour
  (`engines/layout.py`'s "two wires simply crossing continue through
  unconnected"), and it is why a crossing is a soft metric and not a connection;
* a pin, a net label or a power symbol touching a wire joins that wire's node,
  wherever along the span it sits;
* entities that share one point join (a label sitting exactly on a pin tip);
* label and power-symbol entries with the **same net id** join, wherever they
  are on the page — that is what a label *means*.

The comparison with `CircuitSpec.nets` is a comparison of **partitions** and of
the **names the drawing states**, never of segment net-id strings (052 sec.4):
a segment's own `net` is decoration, and two drawings of one circuit that name
their nodes differently must both pass. The partition carries the membership
(and a pin the spec never mentions counts, on the spec's side, as a node of its
own — a plan that joins it to something has invented a connection); the labels
and power symbols carry the naming, because a swapped flag on two one-pin nets
leaves both partitions looking identical.

**Two things it deliberately does not check**, so that a later reader does not
mistake silence for approval:

* whether the plan's ``symbol_hash`` / ``source`` digests still match the
  profiles and specs handed in — that is a *staleness* question about the plan
  and belongs to whoever binds a preview to it (052 sec.4);
* a junction dot that sits on nothing, and a pin whose tip lies mid-span on a
  foreign wire without a declared junction. The first is not a connection
  question, and the second does not change what the editor connects; both are
  visible in the derivation, which is why they are named here rather than
  silently assumed away.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.geometry import transform_point
from boardwise.core.layoutplan import LayoutPlan
from boardwise.core.pagelayoutplan import PageLayoutPlan
from boardwise.core.presentationspec import PresentationSpec, main_path_wire
from boardwise.core.symbolprofile import (
    Box,
    SymbolProfile,
    check_box,
    role_siblings,
)

__all__ = [
    "CHECKER_NAME",
    "DEFAULT_GRID",
    "HARD_KINDS",
    "KIND_DANGLING_WIRE_END",
    "KIND_GEOMETRY_OUTSIDE_FRAMES",
    "KIND_MAIN_PATH_EDGE_NOT_WIRED",
    "KIND_MODULE_FRAME_OVERFLOW",
    "KIND_MODULE_FRAME_OVERLAP",
    "KIND_MODULE_PART_UNASSIGNED",
    "KIND_NC_PIN_CONNECTED",
    "KIND_NETLIST_PARTITION",
    "KIND_OUT_OF_PAGE",
    "KIND_PAGE_KEEPOUT_CONFLICT",
    "KIND_REQUIRED_PIN_NOT_CONNECTED",
    "KIND_SHARED_NET_EXPRESSION_SPLIT",
    "KIND_TEXT_OVERLAP",
    "KIND_UNDECLARED_JUNCTION",
    "KIND_USER_LOCK_VIOLATED",
    "KIND_WIRE_THROUGH_BODY",
    "KIND_WIRE_THROUGH_MODULE_FRAME",
    "PAGE_CHECKER_NAME",
    "PAGE_KINDS",
    "PAGE_MODULE_GAP",
    "PRECISION",
    "TOL",
    "UNMEASURED",
    "CheckResult",
    "DerivedNetlist",
    "HardViolation",
    "ReadabilityError",
    "check",
    "check_page",
    "derive_netlist",
]

#: What a caller writes into ``LayoutEvidence.checker`` so a report says which
#: checker produced its findings — the version is part of the name because a
#: later checker changes what "no findings" means.
CHECKER_NAME = "boardwise-readability/1"

#: Decimal places at which two coordinates count as equal (see the module
#: docstring). The drawing world is an integer grid, so the rule is *exact*
#: equality and this only absorbs float noise from a rotation.
PRECISION = 6

#: The tolerance in canvas units, i.e. ``10 ** -PRECISION``.
TOL = 10.0 ** -PRECISION

#: The routing lattice `engines/layout.py` measures (:data:`boardwise.engines.
#: layout.GRID`, echoed rather than imported so the unit rule here is visible in
#: one place). One grid unit is the "same column/row" slack the alignment metric
#: uses; a caller placing on another lattice passes its own.
DEFAULT_GRID = 5.0

#: The value a soft metric takes when the inputs cannot measure it (fewer than
#: two text boxes; no page box). Explicit rather than 0.0, because "0 units
#: apart" is a real, very bad answer that must not double as "cannot tell".
UNMEASURED = -1.0

KIND_NETLIST_PARTITION = "netlist-partition-mismatch"
KIND_DANGLING_WIRE_END = "dangling-wire-end"
KIND_UNDECLARED_JUNCTION = "undeclared-junction"
KIND_WIRE_THROUGH_BODY = "wire-through-body"
KIND_TEXT_OVERLAP = "text-overlap"
KIND_OUT_OF_PAGE = "out-of-page"
KIND_USER_LOCK_VIOLATED = "user-lock-violated"
KIND_NC_PIN_CONNECTED = "nc-pin-connected"
KIND_REQUIRED_PIN_NOT_CONNECTED = "required-pin-not-connected"

#: The nine kinds, in the order the constraints are checked and reported
#: (053 sec.2's list order). A test pins the tuple's length so a tenth kind
#: cannot appear without the contract being updated deliberately.
HARD_KINDS: tuple[str, ...] = (
    KIND_NETLIST_PARTITION,
    KIND_DANGLING_WIRE_END,
    KIND_UNDECLARED_JUNCTION,
    KIND_WIRE_THROUGH_BODY,
    KIND_TEXT_OVERLAP,
    KIND_OUT_OF_PAGE,
    KIND_USER_LOCK_VIOLATED,
    KIND_NC_PIN_CONNECTED,
    KIND_REQUIRED_PIN_NOT_CONNECTED,
)

# ------------------------------------------------- the page-level domain (056)

#: What a caller writes into ``PageLayoutPlan.pageEvidence.checker``. A second
#: vocabulary, not a tenth constraint: the nine above judge a drawing, these
#: judge a *page* made of drawings, and a report that merged the two would make
#: "which layer refused" unanswerable (052 sec.8).
PAGE_CHECKER_NAME = "boardwise-page-readability/1"

KIND_MODULE_FRAME_OVERFLOW = "module-frame-overflow"
KIND_MODULE_FRAME_OVERLAP = "module-frame-overlap"
KIND_GEOMETRY_OUTSIDE_FRAMES = "geometry-outside-module-frames"
KIND_MODULE_PART_UNASSIGNED = "module-part-unassigned"
KIND_WIRE_THROUGH_MODULE_FRAME = "wire-through-module-frame"
KIND_SHARED_NET_EXPRESSION_SPLIT = "shared-net-expression-split"
KIND_MAIN_PATH_EDGE_NOT_WIRED = "main-path-edge-not-wired"
KIND_PAGE_KEEPOUT_CONFLICT = "page-keepout-conflict"

#: The eight page kinds, in the order :func:`check_page` reports them.
PAGE_KINDS: tuple[str, ...] = (
    KIND_MODULE_FRAME_OVERFLOW,
    KIND_MODULE_FRAME_OVERLAP,
    KIND_GEOMETRY_OUTSIDE_FRAMES,
    KIND_MODULE_PART_UNASSIGNED,
    KIND_WIRE_THROUGH_MODULE_FRAME,
    KIND_SHARED_NET_EXPRESSION_SPLIT,
    KIND_MAIN_PATH_EDGE_NOT_WIRED,
    KIND_PAGE_KEEPOUT_CONFLICT,
)

#: The clear space two module frames must keep (056 sec.2's "模块间距 ≥ 页级
#: 常量"). Echoed here the way :data:`DEFAULT_GRID` is, so the number the rule is
#: applied with is visible where it is applied; `engines/pagecompiler.py` places
#: frames with it and passes its own if it uses another.
PAGE_MODULE_GAP = 40.0

# 097 removed ``PAGE_HIGH_FANOUT``: 069 sec.7 retired the member count at page
# scale ("a rail is a bus at any fan-out") and 096 moved the crossing net's
# wire-or-name decision to
# :func:`~boardwise.core.presentationspec.main_path_wire`, so the constant's only
# remaining reader was the ``check_page(high_fanout=...)`` parameter that was
# accepted and validated but consulted by no rule. Both went together — a number
# kept "for the caller" is a second way of saying what nothing reads.


class ReadabilityError(ValueError):
    """The checker cannot judge these inputs.

    Raised for a structural impossibility rather than for a violation: a plan
    whose part names a symbol no profile was given cannot have its pins
    derived, so constraints 1, 2, 4, 8 and 9 could not be checked at all.
    Reporting "no violations" in that state would be the one answer this
    checker may never give.
    """


@dataclass(frozen=True)
class HardViolation:
    """One failing hard constraint: its kind, the objects it names, the evidence.

    Frozen and self-describing for the same reason `engines/layout.Violation`
    is ("human-readable on every field"): a violation is a value that ends up in
    a report, and a report line that does not say *which* two segments overlap
    costs the reader a search.
    """

    kind: str
    objects: tuple[str, ...]
    evidence: str

    def render(self) -> str:
        """One line, the shape ``LayoutEvidence.hard_violations`` holds."""
        return f"[{self.kind}] {' + '.join(self.objects)}: {self.evidence}"


@dataclass
class CheckResult:
    """What one check found: findings and raw metrics, never a score."""

    hard_violations: list[HardViolation] = field(default_factory=list)
    #: Empty in this batch unless a `grammar_checker` was injected; the values
    #: are whatever that checker returned, stored verbatim.
    grammar_findings: list[Any] = field(default_factory=list)
    #: Raw values in canvas units (or counts / ratios, said per key below).
    soft_metrics: dict[str, float] = field(default_factory=dict)
    #: metric -> the lines that explain it; keys are always in `soft_metrics`.
    soft_reasons: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """No hard violation, so the drawing is deliverable.

        Deliberately not "and no grammar finding": the grammar layer is a
        separate contract (053 sec.3), and a result could not be `ok` for the
        hard half while carrying findings the caller has chosen not to inject.
        """
        return not self.hard_violations


@dataclass(frozen=True)
class DerivedNetlist:
    """The netlist read off the drawing, independent of any generator state.

    `pin_group` is the *partition* (052 sec.4's comparison unit): every pin maps
    to the sorted tuple of pins it is one node with — itself alone when nothing
    touches it. Sorted and tuple-keyed so two runs and two dictionaries compare
    equal exactly.
    """

    #: ``"<partId>.<pin>"`` -> the tip's page coordinates.
    pin_points: dict[str, tuple[float, float]]
    #: pin -> the sorted group of pins that are one node with it.
    pin_group: dict[str, tuple[str, ...]]
    #: Pins with a conductor on them: a wire, a label or a power symbol. The
    #: question "is this pin attached to anything" is not the same as "is it
    #: alone on its node" (a pin can be wired to a dead end), and both are
    #: asked below.
    wired_pins: frozenset[str]
    #: node (the sorted pin tuple) -> the net ids the drawing states on it, by
    #: the labels and power symbols that hang on that node. Empty for a node
    #: the drawing does not name — which is fine, a net may be carried by wires
    #: alone — and absent for a node with no pin on it.
    node_names: dict[tuple[str, ...], tuple[str, ...]] = field(default_factory=dict)

    @property
    def groups(self) -> tuple[tuple[str, ...], ...]:
        """The distinct nodes, sorted — the partition itself."""
        return tuple(sorted(set(self.pin_group.values())))

    def group_of(self, pin: str) -> tuple[str, ...]:
        """The pins on `pin`'s node, sorted; empty for a pin that is not placed."""
        return self.pin_group.get(pin, ())

    def names_of(self, pin: str) -> tuple[str, ...]:
        """The net ids the drawing states on `pin`'s node, sorted (maybe empty)."""
        return self.node_names.get(self.pin_group.get(pin, ()), ())


# ------------------------------------------------------------------ derivation


@dataclass(frozen=True)
class _PlacedPart:
    """One plan part with its profile applied: pins in page coordinates."""

    part_id: str
    symbol_ref: str
    pins: dict[str, tuple[float, float]]
    body: Box | None


def derive_netlist(
    layout_plan: LayoutPlan,
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile],
) -> DerivedNetlist:
    """Read the netlist the drawing actually makes (see the module docstring).

    Public because it is the single most checkable claim of this module and
    because a caller debugging "why does the checker think these are one node"
    wants it without re-running the whole check. Every rule it applies is
    listed in the module docstring; nothing here consults a spec, so the result
    is a fact about the picture.
    """
    profile_map = _profile_map(profiles)
    return _derive(layout_plan, _placed_parts(layout_plan, profile_map))


def _profile_map(
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile],
) -> dict[str, SymbolProfile]:
    """Normalise the caller's profiles to ``symbolRef -> SymbolProfile``.

    Both spellings are accepted because both are natural at a call site: a
    mapping when the caller already keyed by symbol, an iterable when they are
    reading a directory of profiles. A mapping whose key disagrees with the
    profile's own ``symbol_ref`` is refused rather than trusted — silently
    checking a part against the wrong symbol's pins is the worst failure mode
    this module has.
    """
    out: dict[str, SymbolProfile] = {}
    if isinstance(profiles, Mapping):
        for key, profile in profiles.items():
            if not isinstance(profile, SymbolProfile):
                raise ReadabilityError(
                    f"profiles[{key!r}] is {type(profile).__name__}, expected a "
                    "SymbolProfile"
                )
            if str(key) != profile.symbol_ref:
                raise ReadabilityError(
                    f"profiles[{key!r}] holds the profile of "
                    f"{profile.symbol_ref!r} — a mapping is keyed by the symbol it "
                    "describes, or a part gets checked against another symbol's pins"
                )
            out[profile.symbol_ref] = profile
        return out
    try:
        items = list(profiles)
    except TypeError as exc:
        raise ReadabilityError(
            "profiles must be a mapping symbolRef -> SymbolProfile, or an iterable "
            f"of SymbolProfile, got {type(profiles).__name__}"
        ) from exc
    for index, profile in enumerate(items):
        if not isinstance(profile, SymbolProfile):
            raise ReadabilityError(
                f"profiles[{index}] is {type(profile).__name__}, expected a "
                "SymbolProfile"
            )
        if profile.symbol_ref in out:
            raise ReadabilityError(
                f"two profiles claim symbol {profile.symbol_ref!r} — one symbol has "
                "one geometry, or the pins of a part are ambiguous"
            )
        out[profile.symbol_ref] = profile
    return out


def _placed_parts(
    layout_plan: LayoutPlan, profile_map: Mapping[str, SymbolProfile]
) -> list[_PlacedPart]:
    """Map every plan part's profile into page coordinates."""
    out: list[_PlacedPart] = []
    for part in layout_plan.parts:
        profile = profile_map.get(part.symbol_ref)
        if profile is None:
            raise ReadabilityError(
                f"parts[{part.part_id}] is drawn with symbol {part.symbol_ref!r} and "
                "no profile for it was given — without the symbol's pin tips the "
                "netlist cannot be derived, and a check that skipped this part "
                "would report a circuit it never read"
            )
        pins = {
            str(pin.number): _in_page(pin.tip, part)
            for pin in profile.pins
        }
        out.append(_PlacedPart(
            part_id=part.part_id,
            symbol_ref=part.symbol_ref,
            pins=pins,
            body=_body_in_page(profile.body, part),
        ))
    return out


def _in_page(local: tuple[float, float], part: Any) -> tuple[float, float]:
    """A symbol-local point in page coordinates, through the part's pose.

    One function for pin tips and body corners so the two can never disagree
    about which rotation convention the drawing uses.
    """
    return transform_point(
        local[0], local[1],
        rotation=part.rotation, mirror=part.mirror, ox=part.x, oy=part.y,
    )


def _body_in_page(body: Box | None, part: Any) -> Box | None:
    """The drawn extent, transformed and re-bounded.

    Four corners through the pose and an axis-aligned bound of the result: a box
    rotated by 90 degrees is no longer the same rectangle, and a check that kept
    the local box would test a region the symbol does not occupy.
    """
    if body is None:
        return None
    x0, y0, x1, y1 = body
    corners = [_in_page(corner, part) for corner in
               ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _derive(layout_plan: LayoutPlan, placed: list[_PlacedPart]) -> DerivedNetlist:
    """Union-find over every conductive element (see the module docstring)."""
    union = _UnionFind()
    pin_points: dict[str, tuple[float, float]] = {}
    for part in placed:
        for number, point in part.pins.items():
            pin_points[f"{part.part_id}.{number}"] = point

    segments = [segment.points for segment in layout_plan.segments]
    for index in range(len(segments)):
        union.find(f"seg:{index}")

    # A vertex of one wire on another wire's span is a tee: the editor joins it
    # (that is why a missing junction is a finding of its own). Two wires that
    # merely cross stay separate — measured editor behaviour.
    for index, points in enumerate(segments):
        for other, other_points in enumerate(segments):
            if index == other:
                continue
            if any(_on_polyline(point, other_points) for point in points):
                union.union(f"seg:{index}", f"seg:{other}")

    anchors: list[tuple[str, tuple[float, float]]] = [
        (f"lbl:{index}", (label.x, label.y))
        for index, label in enumerate(layout_plan.labels)
    ]
    anchors.extend(
        (f"pwr:{index}", (symbol.x, symbol.y))
        for index, symbol in enumerate(layout_plan.power_symbols)
    )
    # The net each label / power symbol *states*, by the ref that carries it.
    named: list[tuple[str, str]] = [
        (f"lbl:{index}", label.net)
        for index, label in enumerate(layout_plan.labels)
        if label.net
    ]
    named.extend(
        (f"pwr:{index}", symbol.net)
        for index, symbol in enumerate(layout_plan.power_symbols)
        if symbol.net
    )

    wired: set[str] = set()
    by_point: dict[tuple[float, float], list[str]] = {}
    for ref, point in anchors:
        by_point.setdefault(_key(point), []).append(ref)
    for pin, point in pin_points.items():
        ref = f"pin:{pin}"
        by_point.setdefault(_key(point), []).append(ref)
        for index, points in enumerate(segments):
            if _on_polyline(point, points):
                union.union(ref, f"seg:{index}")
                wired.add(pin)
        for anchor_ref, anchor_point in anchors:
            if _same_point(point, anchor_point):
                union.union(ref, anchor_ref)
                wired.add(pin)

    for ref, point in anchors:
        for index, points in enumerate(segments):
            if _on_polyline(point, points):
                union.union(ref, f"seg:{index}")

    # Anything sharing one point is one node: a label sitting on a pin tip, two
    # labels on one wire end, a power symbol dropped on a junction.
    for refs in by_point.values():
        for ref in refs[1:]:
            union.union(refs[0], ref)

    # Same net id over labels / power symbols: that is what a name means.
    by_name: dict[str, list[str]] = {}
    for ref, net_id in named:
        by_name.setdefault(net_id, []).append(ref)
    for refs in by_name.values():
        for ref in refs[1:]:
            union.union(refs[0], ref)

    nodes: dict[str, list[str]] = {}
    for pin in pin_points:
        nodes.setdefault(union.find(f"pin:{pin}"), []).append(pin)
    pin_group: dict[str, tuple[str, ...]] = {}
    group_of_root: dict[str, tuple[str, ...]] = {}
    for root, pins in nodes.items():
        group = tuple(sorted(pins))
        group_of_root[root] = group
        for pin in group:
            pin_group[pin] = group

    # The names each node carries: what the drawing *states* about which net a
    # node is (052 sec.4 compares naming semantics as well as partitions).
    # Nodes with no pin are not recorded — there is nothing to compare them to.
    names: dict[tuple[str, ...], set[str]] = {}
    for ref, net_id in named:
        group = group_of_root.get(union.find(ref))
        if group is not None:
            names.setdefault(group, set()).add(net_id)
    return DerivedNetlist(
        pin_points=pin_points,
        pin_group=pin_group,
        wired_pins=frozenset(wired),
        node_names={group: tuple(sorted(found)) for group, found in names.items()},
    )


# ------------------------------------------------------------------ the check


def check(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile],
    *,
    grammar_checker: Callable[..., Iterable[Any]] | None = None,
    page_box: Box | None = None,
    keepouts: Sequence[Box] = (),
    grid: float = DEFAULT_GRID,
) -> CheckResult:
    """Run the nine hard constraints and measure the soft metrics.

    ``profiles`` is the set of :class:`SymbolProfile` the plan's symbols were
    drawn with, as a mapping ``symbolRef -> SymbolProfile`` or any iterable of
    profiles. A plan part whose symbol is missing from it is a
    :class:`ReadabilityError`, not a silently skipped part.

    ``grammar_checker`` is the injection point for the *drawing grammar*
    (053 sec.3, another batch): when given, it is called as
    ``grammar_checker(layout_plan, circuit_spec, presentation_spec, profiles)``
    with the four inputs above — `profiles` already normalised to the mapping —
    and whatever iterable it returns is stored in `grammar_findings` verbatim,
    findings unread and unvalidated. When it is ``None`` (the default, and this
    batch), `grammar_findings` is empty. It is called even when hard violations
    are present: the two layers answer different questions and a caller that
    wants the grammar silenced can pass nothing.

    ``page_box`` is ``[minX, minY, maxX, maxY]`` in canvas units, because a
    :class:`LayoutPlan` deliberately carries no page size (a plan says where
    things are, not how big the sheet is) — the caller that knows the target
    sheet passes it. ``None`` means "the caller did not state a page", and the
    page half of constraint 6 is then **not evaluated** rather than guessed;
    ``keepouts`` (a title block, a reserved region) is still checked.
    ``grid`` is the lattice the alignment metric treats as "the same column or
    row" (:data:`DEFAULT_GRID` = :data:`boardwise.engines.layout.GRID`).

    Nothing here mutates an input, and the result is deterministic: violations
    come out in :data:`HARD_KINDS` order, and inside one constraint in the
    document order of the object that names them.
    """
    for value, expected in (
        (layout_plan, LayoutPlan),
        (circuit_spec, CircuitSpec),
        (presentation_spec, PresentationSpec),
    ):
        if not isinstance(value, expected):
            raise ReadabilityError(
                f"{expected.__name__} expected, got {type(value).__name__}"
            )
    if isinstance(grid, bool) or not isinstance(grid, (int, float)) or grid <= 0:
        raise ReadabilityError(
            f"grid must be a positive number of canvas units, got {grid!r}"
        )
    page = check_box(page_box, "page_box", ReadabilityError)
    keep = []
    for index, item in enumerate(keepouts):
        box = check_box(item, f"keepouts[{index}]", ReadabilityError)
        if box is None:
            raise ReadabilityError(
                f"keepouts[{index}] is not a box — an absent keep-out is one the "
                "caller should not have listed"
            )
        keep.append(box)

    profile_map = _profile_map(profiles)
    placed = _placed_parts(layout_plan, profile_map)
    net = _derive(layout_plan, placed)

    violations: list[HardViolation] = []
    violations.extend(_check_netlist(circuit_spec, net, profile_map))
    violations.extend(_check_wire_ends(layout_plan, net))
    violations.extend(_check_junctions(layout_plan))
    violations.extend(_check_bodies(layout_plan, placed))
    violations.extend(_check_text(layout_plan, placed))
    violations.extend(_check_page(layout_plan, placed, page, keep))
    violations.extend(_check_locks(presentation_spec, layout_plan))
    violations.extend(_check_nc(circuit_spec, net, profile_map))
    violations.extend(_check_required_pins(circuit_spec, net, placed, profile_map))

    findings: list[Any] = []
    if grammar_checker is not None:
        findings = list(
            grammar_checker(layout_plan, circuit_spec, presentation_spec, profile_map)
            or ()
        )

    metrics, reasons = _soft_metrics(layout_plan, presentation_spec, placed, page, grid)
    return CheckResult(
        hard_violations=violations,
        grammar_findings=findings,
        soft_metrics=metrics,
        soft_reasons=reasons,
    )


# ------------------------------------------------------- 1. netlist identity


def _check_netlist(
    circuit_spec: CircuitSpec,
    net: DerivedNetlist,
    profile_map: Mapping[str, SymbolProfile],
) -> list[HardViolation]:
    """Constraint 1: the plan's partition *and* naming are the spec's.

    Three directions, because the mistakes are not each other's negation:

    * **joined in the plan, not in the spec** — a wire merged two nodes the
      spec keeps apart, or attached a pin the spec never mentions (the
      "undeclared short", and the reason an unmentioned pin counts as a node of
      its own);
    * **declared as one node, split in the plan** — a wire is missing, or runs
      to the wrong pin;
    * **named as another net** — the membership is right but a label or power
      symbol on the node states a net id the spec does not use for those pins.
      052 sec.4 asks for naming semantics as well as the partition, and a
      membership-only comparison cannot see a swapped flag on two one-pin
      nets: both partitions are "each pin alone".

    Reported per merged group, per split net and per misnamed node, so one
    wiring mistake is one finding. A pin declared NC is out of the domain (and
    out of the naming check) because the spec's own schema already forbids it
    being a net member, and constraint 8 owns that mistake — reporting it twice
    would double-count.
    """
    out: list[HardViolation] = []
    nc_pins = {item.pin for item in circuit_spec.nc}
    spec_net_of = _role_node_expectations(circuit_spec, profile_map)
    domain = {pin for pin in net.pin_points if pin not in nc_pins}
    merged: set[tuple[str, ...]] = set()

    for group in net.groups:
        pins = [pin for pin in group if pin in domain]
        if len(pins) < 2:
            continue
        net_ids = {spec_net_of.get(pin, "") for pin in pins}
        if len(net_ids) == 1 and "" not in net_ids:
            continue  # every pin of this node is on one declared net
        merged.add(group)
        described = ", ".join(
            f"{pin} on net {spec_net_of[pin]!r}"
            if spec_net_of.get(pin)
            else f"{pin} unmentioned"
            for pin in pins
        )
        out.append(HardViolation(
            KIND_NETLIST_PARTITION,
            tuple(f"pins[{pin}]" for pin in pins),
            f"the plan makes these pins one node ({described}), but the spec does "
            "not put them on one net — an undeclared connection the drawing added",
        ))

    for spec_net in circuit_spec.nets:
        present = sorted(
            pin for pin, net_id in spec_net_of.items()
            if net_id == spec_net.id and pin in domain
        )
        if len(present) < 2:
            continue
        nodes: dict[tuple[str, ...], list[str]] = {}
        for pin in present:
            nodes.setdefault(net.group_of(pin), []).append(pin)
        if len(nodes) == 1:
            continue
        split = " ; ".join(
            ", ".join(pins) for _, pins in sorted(nodes.items())
        )
        out.append(HardViolation(
            KIND_NETLIST_PARTITION,
            ("circuitSpec.nets[%s]" % spec_net.id,)
            + tuple(f"pins[{pin}]" for pin in present),
            f"net {spec_net.id!r} puts these pins on one node, but the plan has "
            f"them on {len(nodes)} separate node(s): {split}",
        ))

    for group in net.groups:
        if group in merged or any(pin in nc_pins for pin in group):
            continue
        drawn = net.node_names.get(group, ())
        if not drawn:
            continue
        declared = sorted({spec_net_of[pin] for pin in group if spec_net_of.get(pin)})
        if declared == list(drawn):
            continue
        what = (
            "the spec puts them on " + ", ".join(repr(name) for name in declared)
            if declared
            else "the spec does not put them on any net"
        )
        out.append(HardViolation(
            KIND_NETLIST_PARTITION,
            tuple(f"circuitSpec.nets[{name}]" for name in declared)
            + tuple(f"pins[{pin}]" for pin in group),
            "the drawing states the net name(s) "
            + ", ".join(repr(name) for name in drawn)
            + " on the node these pins share, but "
            + what
            + " — a name is a claim about which node this is (052 sec.4)",
        ))
    return out


def _role_node_expectations(
    circuit_spec: CircuitSpec, profile_map: Mapping[str, SymbolProfile]
) -> dict[str, str]:
    """``pin -> the net it is on``, a role's other pins included (060 sec.2).

    The pins of one role are **one node inside the symbol**
    (`core.symbolprofile.role_siblings`): the measured AMS1117 draws VOUT on both
    sides of its body, and a spec that puts one of them on a net puts the node
    there. So the expectation this checker grades the drawing against includes
    them — a drawing that leaves one of them floating is reported, and a drawing
    that wires it is not reported as an "undeclared connection".

    Two spec statements are never bent: a pin in ``nc[]`` is an explicit
    no-connect, and a pin the spec itself puts on *another* net is the one-role-
    two-nets contradiction `circuit-invalid` owns.
    """
    declared: dict[str, str] = {}
    for spec_net in circuit_spec.nets:
        for member in spec_net.members:
            declared[member] = spec_net.id
    # **115-②, one ruler.** A spec writes ``<partId>.<pin>`` with whatever token
    # the symbol uses: the flyback's ``D1`` declares ``A``/``K`` (names) while the
    # very same library profile numbers them ``1``/``2``, and the sibling ``D2``
    # in the same document writes ``1``/``2``. The derived netlist's keys come
    # from the **profile's numbers**, so a name-spelled member never matched one
    # and the comparison graded two different keys — ``D1.A`` was "a pin the
    # symbol has not got" while ``D1.1`` sat on the drawn node unmentioned.
    #
    # Both spellings are resolved to the profile's number here, through the same
    # "number first, then name" rule :func:`drawcompiler._pin_of_token` and
    # ``grammar.base.profile_pin_for`` apply. Keeping the **number** as the one
    # key is deliberate: giving ``pins`` a name key as well would put one pad on
    # its own node **twice**, which corrupts the partition this whole constraint
    # compares. One key space, one ruler — no second, disagreeing measure.
    canonical: dict[str, str] = {}
    for member, net_id in declared.items():
        part_id, _, token = member.partition(".")
        part = circuit_spec.part(part_id)
        profile = profile_map.get(part.symbol_ref) if part is not None else None
        resolved = _profile_pin_ruler(profile, token)
        canonical[f"{part_id}.{resolved}"] = net_id
    declared = canonical
    nc_pins = {item.pin for item in circuit_spec.nc}
    nc_pins = {
        f"{pin.partition('.')[0]}.{_profile_pin_ruler(_profile_of(circuit_spec, profile_map, pin), pin.partition('.')[2])}"
        for pin in nc_pins
    }
    out = dict(declared)
    for member in sorted(declared):
        net_id = declared[member]
        part_id, _, token = member.partition(".")
        part = circuit_spec.part(part_id)
        profile = profile_map.get(part.symbol_ref) if part is not None else None
        if profile is None:
            continue
        for pin in role_siblings(profile, token):
            spelling = pin.number or pin.name
            if not spelling or spelling in nc_pins:
                continue
            siblings_net = (
                declared.get(f"{part_id}.{spelling}")
                or declared.get(f"{part_id}.{pin.name}")
            )
            if siblings_net and siblings_net != net_id:
                continue
            out.setdefault(f"{part_id}.{spelling}", net_id)
    return out


def _profile_of(
    circuit_spec: CircuitSpec, profile_map: Mapping[str, SymbolProfile], pin: str
) -> SymbolProfile | None:
    """The profile of the part `pin` names, or ``None``."""
    part = circuit_spec.part(pin.partition(".")[0])
    return profile_map.get(part.symbol_ref) if part is not None else None


def _profile_pin_ruler(profile: SymbolProfile | None, token: str) -> str:
    """The **one** spelling this module reads a pin by: number first, then name.

    The same rule `drawcompiler._pin_of_token` and `grammar.base.profile_pin_for`
    apply, for the same reason — a spec may name a pin either way, and the two
    must not become two rulers. A token the profile cannot resolve is returned
    unchanged, so a spec naming a pin the symbol genuinely lacks is still
    reported as such (constraint 9's "the symbol has no such pin") instead of
    being silently folded onto some other pad.
    """
    if profile is None or not token:
        return token
    pin = profile.pin(token)
    if pin is not None:
        return str(pin.number)
    for candidate in profile.pins:
        if candidate.name == token:
            return str(candidate.number)
    return token


# ------------------------------------------------------------- 2. wire ends


def _check_wire_ends(
    layout_plan: LayoutPlan, net: DerivedNetlist
) -> list[HardViolation]:
    """Constraint 2: every wire end lands on something real.

    052 sec.6 lets an *open interface* or an explicit NC be electrically
    dangling; it does not let a wire end in mid-air. The net is legitimised by
    the label or port that names it, which is a thing at the wire's end — so a
    bare end is reported and the message says what would have marked it.
    """
    out: list[HardViolation] = []
    for index, segment in enumerate(layout_plan.segments):
        for position, point in enumerate((segment.points[0], segment.points[-1])):
            landing = _landing(layout_plan, net, point, skip_segment=index)
            if landing is None:
                out.append(HardViolation(
                    KIND_DANGLING_WIRE_END,
                    (f"segments[{index}]",),
                    f"its {'start' if position == 0 else 'end'} "
                    f"({point[0]:g}, {point[1]:g}) lands on nothing — no pin tip, "
                    "wire, junction, label or power symbol is there; an open "
                    "interface still has to be named by a label or port at its end",
                ))
    return out


def _landing(
    layout_plan: LayoutPlan,
    net: DerivedNetlist,
    point: tuple[float, float],
    *,
    skip_segment: int,
) -> str | None:
    """What `point` touches, or ``None``: the constraint-2 vocabulary, named."""
    for pin, tip in net.pin_points.items():
        if _same_point(point, tip):
            return f"pins[{pin}]"
    for index, segment in enumerate(layout_plan.segments):
        if index == skip_segment:
            continue
        if _on_polyline(point, segment.points):
            return f"segments[{index}]"
    for index, junction in enumerate(layout_plan.junctions):
        if _same_point(point, (junction.x, junction.y)):
            return f"junctions[{index}]"
    for index, label in enumerate(layout_plan.labels):
        if _same_point(point, (label.x, label.y)):
            return f"labels[{index}]"
    for index, symbol in enumerate(layout_plan.power_symbols):
        if _same_point(point, (symbol.x, symbol.y)):
            return f"powerSymbols[{index}]"
    return None


# -------------------------------------------------------------- 3. junctions


def _check_junctions(layout_plan: LayoutPlan) -> list[HardViolation]:
    """Constraint 3: a tee into another wire's span needs its junction dot.

    "Tee" means a vertex of one wire lying strictly inside another wire's drawn
    span; two wires meeting end-to-end, or crossing straight through each other,
    need no dot (the second is measured editor behaviour: a plain crossing is
    not a connection at all). A junction declared at the point satisfies it; the
    finding names both segments so the reader can see which wire has to move or
    which dot has to be added.
    """
    out: list[HardViolation] = []
    junction_points = [(item.x, item.y) for item in layout_plan.junctions]
    reported: set[tuple[int, tuple[float, float]]] = set()
    for index, segment in enumerate(layout_plan.segments):
        for point in segment.points:
            for other_index, other in enumerate(layout_plan.segments):
                if other_index == index:
                    continue
                if not _on_polyline(point, other.points):
                    continue
                if _same_point(point, other.points[0]):
                    continue
                if _same_point(point, other.points[-1]):
                    continue
                key = (index, _key(point))
                if key in reported:
                    continue
                if any(_same_point(point, item) for item in junction_points):
                    continue
                reported.add(key)
                out.append(HardViolation(
                    KIND_UNDECLARED_JUNCTION,
                    (f"segments[{index}]", f"segments[{other_index}]"),
                    f"a vertex of segments[{index}] at ({point[0]:g}, "
                    f"{point[1]:g}) tees into the span of segments[{other_index}] "
                    "and no junction is declared there — the editor draws the dot "
                    "and joins the nets; declare the junction or route to the "
                    "other wire's end",
                ))
    return out


# ----------------------------------------------------------------- 4. bodies


def _check_bodies(
    layout_plan: LayoutPlan, placed: list[_PlacedPart]
) -> list[HardViolation]:
    """Constraint 4: a wire may not cross a part it is not the end of.

    053 sec.2's wording is "非两端器件", so the exemption is exactly that: a part
    whose own pin tip sits at one of the segment's two outer points. A part that
    merely has a pin somewhere along the wire is *not* exempt — a wire running
    through a symbol's drawn extent is unreadable whichever pin it touches.
    """
    out: list[HardViolation] = []
    for index, segment in enumerate(layout_plan.segments):
        ends = (segment.points[0], segment.points[-1])
        for part in placed:
            if part.body is None:
                continue
            if any(_same_point(tip, end) for tip in part.pins.values() for end in ends):
                continue
            hit = _first_box_crossing(segment.points, part.body)
            if hit is None:
                continue
            out.append(HardViolation(
                KIND_WIRE_THROUGH_BODY,
                (f"segments[{index}]", f"parts[{part.part_id}]"),
                f"segments[{index}] crosses the drawn body of parts[{part.part_id}] "
                f"(box {_box_text(part.body)}) near ({hit[0]:g}, {hit[1]:g}) — a "
                "wire may only reach a part through that part's own pin",
            ))
    return out


def _first_box_crossing(
    points: list[tuple[float, float]], box: Box
) -> tuple[float, float] | None:
    """The midpoint of the first sub-edge with positive-length overlap, or None.

    The one ruler for "a polyline crosses this box", used by constraint 4 (a
    wire crossing a part's drawn body) and by the wire half of constraint 6 (a
    wire entering a keep-out): both ask the same question about the same two
    kinds of geometry, and two copies would be two tolerances.

    Strict interior: the box is inset by :data:`TOL`, so a wire running along
    the outline (or touching only a corner) has no positive-length interior
    overlap and does not count as crossing it. Measured per sub-edge — the
    bounding box of an L-shaped detour covers the box it went around, which is
    exactly the false positive this per-segment clip removes.
    """
    for start, end in _edges(points):
        inside = _clip_to_box(start, end, box)
        if inside is None:
            continue
        t0, t1 = inside
        return (
            start[0] + (t0 + t1) / 2 * (end[0] - start[0]),
            start[1] + (t0 + t1) / 2 * (end[1] - start[1]),
        )
    return None


# ------------------------------------------------------------------ 5. text


def _check_text(
    layout_plan: LayoutPlan, placed: list[_PlacedPart]
) -> list[HardViolation]:
    """Constraint 5: no text box intersects another, and no foreign text on a body.

    Labels and plain texts are one set of boxes (`LayoutPlan.all_text_boxes`
    makes the same point): a label is text on the canvas whether or not it is
    also electrical, so checking the two lists apart would miss a label printed
    over a value.

    A text that belongs to the part whose body it overlaps is **not** a
    violation: a symbol's designator, value and pin names are drawn by the symbol
    inside its own extent, and the contract here is about a *foreign* text
    landing on a component — including a note with no part at all, which is why
    the unowned case is reported.

    A **net label on a pin** is that pin's part's own text for this rule (099b):
    the label names the part's pin, so it belongs to it exactly as its value
    does, and printing it slightly across the symbol's edge is how a compact
    part is drawn — a 16-pin SOP-16 keeps its pin tips 9.5 units from the drawn
    body, less than half a label box, so the outward placement *is* an overlap
    and the alternative (a label centred on its own pin, half of it inside the
    symbol) is worse. `LayoutLabel.part_id` carries the owner; a label with no
    owner (a tap's stub end, a page boundary) keeps the strict rule, and every
    label is still checked against every *other* part's body.
    """
    out: list[HardViolation] = []
    boxes = _text_boxes(layout_plan)
    for left in range(len(boxes)):
        for right in range(left + 1, len(boxes)):
            name_a, box_a, _part_a, text_a = boxes[left]
            name_b, box_b, _part_b, text_b = boxes[right]
            if not _overlap(box_a, box_b):
                continue
            out.append(HardViolation(
                KIND_TEXT_OVERLAP,
                (name_a, name_b),
                f"{name_a} {text_a!r} {_box_text(box_a)} and {name_b} "
                f"{text_b!r} {_box_text(box_b)} intersect — overlapping text is "
                "unreadable whichever of the two it hides",
            ))
    for name, box, part_id, text in boxes:
        for part in placed:
            if part.body is None or part.part_id == part_id:
                continue
            if not _overlap(box, part.body):
                continue
            out.append(HardViolation(
                KIND_TEXT_OVERLAP,
                (name, f"parts[{part.part_id}]"),
                f"{name} {text!r} {_box_text(box)} lands on the drawn body of "
                f"parts[{part.part_id}] {_box_text(part.body)}",
            ))
    return out


def _text_boxes(
    layout_plan: LayoutPlan,
) -> list[tuple[str, Box, str, str]]:
    """``(name, box, partId, text)`` for every text on the canvas, labels included.

    ``partId`` is the owner of a *text* (`LayoutText.part_id` — a reference, a
    value) and, since 099b, the part whose pin a *label* names
    (`LayoutLabel.part_id`): both halves of the set hand the owner to
    `_check_text`, which exempts a text from its own part's body.
    """
    boxes: list[tuple[str, Box, str, str]] = [
        (f"texts[{index}]", item.bbox, item.part_id, item.text)
        for index, item in enumerate(layout_plan.texts)
    ]
    boxes.extend(
        (f"labels[{index}]", item.bbox, item.part_id, item.text)
        for index, item in enumerate(layout_plan.labels)
    )
    return boxes


# ------------------------------------------------------------ 6. page and keep


def _check_page(
    layout_plan: LayoutPlan,
    placed: list[_PlacedPart],
    page: Box | None,
    keepouts: Sequence[Box],
) -> list[HardViolation]:
    """Constraint 6: nothing leaves the page, nothing enters a keep-out.

    One kind for both halves because they are one promise ("不越页/禁区",
    052 sec.6): the drawing stays in the area it is allowed to use. Objects are
    part bodies, wires and text boxes; a body is only checked when the profile
    states one, since an unstated extent is not a measured zero.

    The keep-out half measures the two kinds of object differently, and
    deliberately so. A part's body and a text box **are** rectangles, so their
    own box is the object and the box test is the test. A wire is a *polyline*,
    and a polyline's bounding box is not the line: an L-shaped detour around a
    keep-out still has a box that covers it, so a box test would report a wire
    that never entered the region — the false positive that made "go around a
    keep-out" unsatisfiable. Wires are therefore clipped sub-segment by
    sub-segment with :func:`_first_box_crossing` (the same Liang–Barsky test
    constraint 4 uses, at the same :data:`TOL`), and the boundary semantics are
    that constraint's too: **positive-length overlap with the interior counts as
    entering**. A sub-segment running exactly along a keep-out edge, or touching
    only a corner, has no such overlap and is *not* reported — a keep-out states
    a region, and a wire on its outline is on the border of it, not inside it.

    The page half keeps the bounding box for every object, wires included: a
    page is an axis-aligned rectangle, and such a rectangle contains a set of
    points exactly when it contains their bounding box, so there the box *is*
    the line and the two tests cannot disagree.
    """
    out: list[HardViolation] = []
    # (name, bounding box, polyline) — the polyline is None for the two object
    # kinds that really are boxes.
    objects: list[tuple[str, Box, list[tuple[float, float]] | None]] = []
    for part in placed:
        if part.body is not None:
            objects.append((f"parts[{part.part_id}]", part.body, None))
    for index, segment in enumerate(layout_plan.segments):
        objects.append((
            f"segments[{index}]", _bounds(segment.points), list(segment.points),
        ))
    objects.extend(
        (name, box, None)
        for name, box, _part, _text in _text_boxes(layout_plan)
    )

    if page is not None:
        for name, box, _points in objects:
            escaped = _outside(box, page)
            if not escaped:
                continue
            out.append(HardViolation(
                KIND_OUT_OF_PAGE,
                (name,),
                f"{name} {_box_text(box)} leaves the page {_box_text(page)} on "
                f"{escaped}",
            ))
    for name, box, points in objects:
        for index, keep in enumerate(keepouts):
            if points is None:
                if not _overlap(box, keep):
                    continue
                out.append(HardViolation(
                    KIND_OUT_OF_PAGE,
                    (name,),
                    f"{name} {_box_text(box)} is inside keep-out "
                    f"keepouts[{index}] {_box_text(keep)}",
                ))
                continue
            hit = _first_box_crossing(points, keep)
            if hit is None:
                continue
            out.append(HardViolation(
                KIND_OUT_OF_PAGE,
                (name,),
                f"{name} {_box_text(box)} runs through keep-out "
                f"keepouts[{index}] {_box_text(keep)} near "
                f"({hit[0]:g}, {hit[1]:g})",
            ))
    return out


# --------------------------------------------------------------- 7. user locks


def _check_locks(
    presentation_spec: PresentationSpec, layout_plan: LayoutPlan
) -> list[HardViolation]:
    """Constraint 7: a lock the engineer set is honoured or reported, never bent.

    052 sec.6 and 053 sec.5 scenario 12: "报告冲突+可选动作，不静默忽略锁定".
    Coordinates compare exactly (to :data:`TOL`): a lock is a decision, so a
    plan that snapped it to the grid differs from the lock and says so.
    """
    out: list[HardViolation] = []
    for lock in presentation_spec.user_locks:
        part = layout_plan.part(lock.part_id)
        name = f"presentationSpec.userLocks[{lock.part_id}]"
        if part is None:
            out.append(HardViolation(
                KIND_USER_LOCK_VIOLATED,
                (name,),
                f"the engineer locked {lock.part_id} at "
                f"({lock.x:g}, {lock.y:g}, {lock.rotation:g}°) but the plan does "
                "not place that part at all",
            ))
            continue
        moved = [
            f"{axis}: locked {locked:g}, placed {found:g}"
            for axis, locked, found in (
                ("x", lock.x, part.x),
                ("y", lock.y, part.y),
                ("rotation", lock.rotation, part.rotation),
            )
            if abs(locked - found) > TOL
        ]
        if not moved:
            continue
        out.append(HardViolation(
            KIND_USER_LOCK_VIOLATED,
            (name, f"parts[{part.part_id}]"),
            "the plan does not honour the lock (" + "; ".join(moved) + ")",
        ))
    return out


# --------------------------------------------------------------------- 8. NC


def _check_nc(
    circuit_spec: CircuitSpec, net: DerivedNetlist,
    profile_map: Mapping[str, SymbolProfile],
) -> list[HardViolation]:
    """Constraint 8: an explicit NC pin is not connected to anything.

    053 sec.2: "没给连接" ≠ NC, and NC is explicit — so the drawing owes the pin
    nothing at all. Either form of attachment counts as connected: another pin
    on the same derived node, or a conductor (wire, label, power symbol) sitting
    on the tip. A pin whose part is not placed cannot be connected and is not
    reported here. **115-②**: the lookup goes through :func:`_profile_pin_ruler`
    like every other spec-to-drawing comparison here, while the message keeps
    quoting the spec's own token.
    """
    out: list[HardViolation] = []
    for item in circuit_spec.nc:
        pin = item.pin
        key = f"{pin.partition('.')[0]}.{_profile_pin_ruler(_profile_of(circuit_spec, profile_map, pin), pin.partition('.')[2])}"
        if key not in net.pin_points:
            continue
        group = net.group_of(key)
        others = [other for other in group if other != key]
        attached = key in net.wired_pins
        if not others and not attached:
            continue
        if others:
            how = (
                "the plan puts it on the same node as "
                + ", ".join(f"pins[{other}]" for other in others)
            )
        else:
            how = "a wire, label or power symbol sits on its tip"
        out.append(HardViolation(
            KIND_NC_PIN_CONNECTED,
            (f"circuitSpec.nc[{pin}]", f"pins[{pin}]"),
            f"{pin} is declared NC but {how} — the drawing connects a pin the "
            "circuit says is deliberately unconnected",
        ))
    return out


# ---------------------------------------------------------- 9. required pins


def _check_required_pins(
    circuit_spec: CircuitSpec, net: DerivedNetlist, placed: list[_PlacedPart],
    profile_map: Mapping[str, SymbolProfile],
) -> list[HardViolation]:
    """Constraint 9: every pin a spec net names is actually connected to something.

    The complement of constraint 1, kept separate on purpose (053 sec.2): 1 asks
    "is the partition the same", 9 asks "is this declared pin connected at all".
    A wire run to the wrong pin passes 9 and fails 1; a pin with no wire at all
    fails both, which is honest — there is nothing to pick between them.

    "Connected" means another pin on its node, or **any** conductor on its tip
    (a wire that leads nowhere is still a wire, and the wireless end is
    constraint 2's finding). A pin that cannot be present at all — its part is
    not placed, or the symbol profile has no such pin — is reported with that
    reason, because a declared connection the drawing cannot even show is the
    strongest failure of the nine.
    """
    out: list[HardViolation] = []
    by_id = {part.part_id: part for part in placed}
    for spec_net in circuit_spec.nets:
        for pin in spec_net.members:
            name = f"circuitSpec.nets[{spec_net.id}]"
            # **115-②**: look the pad up under the one ruler's spelling
            # (:func:`_profile_pin_ruler`), while every message still quotes the
            # spec's own token — a reader is answering to their document, not to
            # the library's numbering.
            part_id, _, token = pin.partition(".")
            placed_part = by_id.get(part_id)
            key = f"{part_id}.{_profile_pin_ruler(_profile_of(circuit_spec, profile_map, pin), token)}"
            if key not in net.pin_points:
                if placed_part is None:
                    why = f"part {part_id} is not placed in the plan"
                else:
                    why = (
                        f"the profile of its symbol {placed_part.symbol_ref!r} has "
                        f"no pin {token}"
                    )
                out.append(HardViolation(
                    KIND_REQUIRED_PIN_NOT_CONNECTED,
                    (name, f"pins[{pin}]"),
                    f"{pin} is declared on net {spec_net.id!r} but it has no tip in "
                    f"the drawing — {why}",
                ))
                continue
            group = net.group_of(key)
            if len(group) > 1 or key in net.wired_pins:
                continue
            point = net.pin_points[key]
            out.append(HardViolation(
                KIND_REQUIRED_PIN_NOT_CONNECTED,
                (name, f"pins[{pin}]"),
                f"{pin} is declared on net {spec_net.id!r} but nothing is attached "
                f"to its tip ({point[0]:g}, {point[1]:g}) — no wire, label, power "
                "symbol or second pin on its node",
            ))
    return out


# ---------------------------------------------------------------- soft layer


def _soft_metrics(
    layout_plan: LayoutPlan,
    presentation_spec: PresentationSpec,
    placed: list[_PlacedPart],
    page: Box | None,
    grid: float,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """The raw optimization values of 052 sec.6, with one reason per deduction.

    No total, no weight (053 sec.7: "软指标无总分"): ranking candidates happens
    in the caller's layers, and a single number here would make "fewer
    millimetres of wire" trade against "the tap is unreadable".

    Keys, in canvas units unless said otherwise: ``crossings`` (count of
    intersecting segment *pairs*, one per pair), ``bends`` (count), ``wire_length``,
    ``unaligned_part_pairs`` (count), ``min_text_gap``, ``occupied_ratio`` (parts
    + text, of the page) and ``whitespace_ratio`` (its complement). A value of
    :data:`UNMEASURED` means the inputs cannot answer, and says so in the reason.
    """
    metrics: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    crossings: list[str] = []
    for left, right, point in _crossings(layout_plan):
        crossings.append(
            f"segments[{left}] x segments[{right}] at "
            f"({point[0]:g}, {point[1]:g})"
        )
    metrics["crossings"] = float(len(crossings))
    if crossings:
        reasons["crossings"] = crossings

    bends: list[str] = []
    total_bends = 0
    for index, segment in enumerate(layout_plan.segments):
        count = _bend_count(segment.points)
        total_bends += count
        if count:
            bends.append(
                f"segments[{index}] (net {segment.net!r}): {count} bend(s)"
            )
    metrics["bends"] = float(total_bends)
    if bends:
        reasons["bends"] = bends

    lengths = [
        (index, _polyline_length(segment.points))
        for index, segment in enumerate(layout_plan.segments)
    ]
    metrics["wire_length"] = sum(length for _, length in lengths)
    reasons["wire_length"] = [
        f"{len(lengths)} segment(s); longest segments[{index}] = {length:g} units"
        for index, length in sorted(lengths, key=lambda item: (-item[1], item[0]))[:3]
    ] or ["no segments"]

    unaligned, unmoduled = _unaligned_pairs(layout_plan, presentation_spec, grid)
    metrics["unaligned_part_pairs"] = float(len(unaligned))
    if unaligned:
        reasons["unaligned_part_pairs"] = unaligned
    if unmoduled:
        reasons.setdefault("unaligned_part_pairs", []).append(
            f"{len(unmoduled)} part(s) belong to no module "
            f"({', '.join(unmoduled)}) — no pair involving them was compared"
        )

    boxes = _text_boxes(layout_plan)
    gap, gap_reasons = _min_text_gap(boxes)
    metrics["min_text_gap"] = gap
    if gap_reasons:
        reasons["min_text_gap"] = gap_reasons

    occupied, area_reasons = _occupancy(layout_plan, placed, page)
    metrics["occupied_ratio"] = occupied
    metrics["whitespace_ratio"] = (
        UNMEASURED if occupied == UNMEASURED else 1.0 - occupied
    )
    reasons["whitespace_ratio"] = area_reasons
    return metrics, reasons


def _crossings(
    layout_plan: LayoutPlan,
) -> list[tuple[int, int, tuple[float, float]]]:
    """Every pair of segments crossing with no shared vertex, in order."""
    out: list[tuple[int, int, tuple[float, float]]] = []
    for left in range(len(layout_plan.segments)):
        for right in range(left + 1, len(layout_plan.segments)):
            for start_a, end_a in _edges(layout_plan.segments[left].points):
                for start_b, end_b in _edges(layout_plan.segments[right].points):
                    point = _proper_crossing(start_a, end_a, start_b, end_b)
                    if point is not None:
                        out.append((left, right, point))
                        break
                else:
                    continue
                break
    return out


def _bend_count(points: list[tuple[float, float]]) -> int:
    """Interior vertices where the wire changes direction."""
    count = 0
    for before, corner, after in zip(points, points[1:], points[2:]):
        incoming = (corner[0] - before[0], corner[1] - before[1])
        outgoing = (after[0] - corner[0], after[1] - corner[1])
        cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
        dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
        if abs(cross) > TOL or dot <= 0:
            count += 1
    return count


def _unaligned_pairs(
    layout_plan: LayoutPlan, presentation_spec: PresentationSpec, grid: float
) -> tuple[list[str], list[str]]:
    """Modules' parts not sharing a column or a row (one grid unit of slack).

    052 sec.6 counts alignment among the optimization targets, and a module of
    parts on no common line is what makes a group read as scattered — so the
    pairs are counted per module (053 sec.2: "同模块内 x 或 y 差 ≤1 网格单位视为
    对齐"). Parts in no module are named as not compared, rather than silently
    dropped.
    """
    pairs: list[str] = []
    placed = {part.part_id: part for part in layout_plan.parts}
    in_module: set[str] = set()
    for module in presentation_spec.modules:
        members = [part_id for part_id in module.parts if part_id in placed]
        in_module.update(members)
        for left in range(len(members)):
            for right in range(left + 1, len(members)):
                a = placed[members[left]]
                b = placed[members[right]]
                if abs(a.x - b.x) <= grid or abs(a.y - b.y) <= grid:
                    continue
                pairs.append(
                    f"modules[{module.id}]: parts[{a.part_id}] and parts[{b.part_id}] "
                    f"share neither x nor y (dx={a.x - b.x:g}, dy={a.y - b.y:g}, "
                    f"grid={grid:g})"
                )
    unmoduled = sorted(part.part_id for part in layout_plan.parts
                       if part.part_id not in in_module)
    return pairs, unmoduled


def _min_text_gap(
    boxes: list[tuple[str, Box, str, str]],
) -> tuple[float, list[str]]:
    """The smallest gap between two text boxes, and why it is what it is."""
    if len(boxes) < 2:
        return UNMEASURED, [
            f"{len(boxes)} text box(es) on the page — one gap needs two boxes; "
            f"{UNMEASURED:g} is the 'cannot measure' value, not a distance"
        ]
    best: tuple[float, str, str] | None = None
    zero = 0
    for left in range(len(boxes)):
        for right in range(left + 1, len(boxes)):
            name_a, box_a, _pa, _ta = boxes[left]
            name_b, box_b, _pb, _tb = boxes[right]
            gap = _box_gap(box_a, box_b)
            if gap == 0.0:
                zero += 1
            if best is None or gap < best[0]:
                best = (gap, name_a, name_b)
    assert best is not None
    reasons = [
        f"closest pair {best[1]} and {best[2]}: {best[0]:g} units apart "
        "(canvas units, edge to edge)"
    ]
    if zero:
        reasons.append(
            f"{zero} text box pair(s) overlap — see this run's text-overlap "
            "violations"
        )
    return best[0], reasons


def _occupancy(
    layout_plan: LayoutPlan, placed: list[_PlacedPart], page: Box | None
) -> tuple[float, list[str]]:
    """Parts + text, as a fraction of the page; the union, not a sum of boxes."""
    if page is None:
        return UNMEASURED, [
            "no page_box was given, so the page area is unknown and neither "
            f"occupancy nor whitespace can be measured ({UNMEASURED:g} is the "
            "'cannot measure' value)"
        ]
    page_area = (page[2] - page[0]) * (page[3] - page[1])
    if page_area <= 0:
        return UNMEASURED, [
            f"page_box {_box_text(page)} encloses no area, so no ratio exists"
        ]
    boxes = [part.body for part in placed if part.body is not None]
    boxes.extend(box for _name, box, _part, _text in _text_boxes(layout_plan))
    occupied_area = _union_area(boxes)
    ratio = occupied_area / page_area
    return ratio, [
        f"page {page[2] - page[0]:g} x {page[3] - page[1]:g} = {page_area:g} units^2; "
        f"{len(boxes)} box(es) cover {occupied_area:g} units^2 = {ratio * 100:.2f}%",
        f"whitespace = 1 - {ratio:.4f} = {1.0 - ratio:.4f}",
    ]


def _union_area(boxes: Sequence[Box]) -> float:
    """Area covered by the union of `boxes`, by coordinate compression.

    A sum of areas would double-count two overlapping bodies and make a crowded
    drawing look emptier than it is; the union is the honest answer and the
    rectangle count here is small (tens).
    """
    if not boxes:
        return 0.0
    xs = sorted({box[0] for box in boxes} | {box[2] for box in boxes})
    ys = sorted({box[1] for box in boxes} | {box[3] for box in boxes})
    area = 0.0
    for left in range(len(xs) - 1):
        for bottom in range(len(ys) - 1):
            mid_x = (xs[left] + xs[left + 1]) / 2
            mid_y = (ys[bottom] + ys[bottom + 1]) / 2
            if any(
                box[0] <= mid_x <= box[2] and box[1] <= mid_y <= box[3]
                for box in boxes
            ):
                area += (xs[left + 1] - xs[left]) * (ys[bottom + 1] - ys[bottom])
    return area


# ------------------------------------------------------------------- geometry


def _key(point: tuple[float, float]) -> tuple[float, float]:
    """The identity of a point: rounded to :data:`PRECISION` (see the docstring)."""
    return (round(point[0], PRECISION), round(point[1], PRECISION))


def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Points equal to :data:`TOL` — exact in a grid world, noise-tolerant in float."""
    return abs(a[0] - b[0]) <= TOL and abs(a[1] - b[1]) <= TOL


def _edges(
    points: Sequence[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The polyline's straight sub-edges."""
    return list(zip(points, points[1:]))


def _on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    """Is `point` on the segment ``start``–``end``, within :data:`TOL`?

    Perpendicular distance and the projection parameter, both scaled by the
    segment's own length so the tolerance means a distance in canvas units and
    not an angle.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= TOL:
        return _same_point(point, start)
    px, py = point[0] - start[0], point[1] - start[1]
    if abs(px * dy - py * dx) > TOL * length:
        return False
    dot = px * dx + py * dy
    return -TOL * length <= dot <= length * length + TOL * length


def _on_polyline(
    point: tuple[float, float], points: Sequence[tuple[float, float]]
) -> bool:
    return any(_on_segment(point, start, end) for start, end in _edges(points))


def _proper_crossing(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    """The point where two segments cross *through* each other, or ``None``.

    Strictly interior to both: a shared endpoint, a tee, and a collinear
    overlap are all excluded, because none of them is a crossing (and all of
    them are something else, checked elsewhere).
    """
    ab_len = math.hypot(b[0] - a[0], b[1] - a[1])
    cd_len = math.hypot(d[0] - c[0], d[1] - c[1])
    if ab_len <= TOL or cd_len <= TOL:
        return None
    abc = _cross(a, b, c)
    abd = _cross(a, b, d)
    cda = _cross(c, d, a)
    cdb = _cross(c, d, b)
    eps_ab = TOL * ab_len
    eps_cd = TOL * cd_len
    if not (
        ((abc > eps_ab and abd < -eps_ab) or (abc < -eps_ab and abd > eps_ab))
        and ((cda > eps_cd and cdb < -eps_cd) or (cda < -eps_cd and cdb > eps_cd))
    ):
        return None
    denominator = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
    if abs(denominator) <= TOL:
        return None
    t = (
        (c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])
    ) / denominator
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def _cross(
    origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    return (a[0] - origin[0]) * (b[1] - origin[1]) - (
        a[1] - origin[1]
    ) * (b[0] - origin[0])


def _clip_to_box(
    start: tuple[float, float], end: tuple[float, float], box: Box
) -> tuple[float, float] | None:
    """The parameter range of the segment strictly inside `box`, or ``None``.

    Liang–Barsky against the box inset by :data:`TOL`: a wire lying exactly on
    the outline, or touching only a corner, has no positive-length interior and
    is not "crossing" the box.
    """
    left, bottom, right, top = box[0] + TOL, box[1] + TOL, box[2] - TOL, box[3] - TOL
    if right <= left or top <= bottom:
        return None
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
                return None  # parallel to this slab and outside it
            continue
        ratio = q / p
        if p < 0:
            if ratio > high:
                return None
            low = max(low, ratio)
        else:
            if ratio < low:
                return None
            high = min(high, ratio)
    if high - low <= TOL:
        return None
    return (low, high)


def _overlap(a: Box, b: Box) -> bool:
    """Do the two boxes share area (strictly, by more than :data:`TOL`)?"""
    return (
        min(a[2], b[2]) - max(a[0], b[0]) > TOL
        and min(a[3], b[3]) - max(a[1], b[1]) > TOL
    )


def _box_gap(a: Box, b: Box) -> float:
    """Edge-to-edge distance between two boxes, 0 when they overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def _outside(box: Box, page: Box) -> str:
    """Which bounds of `page` the box leaves, in one phrase ("" when none)."""
    parts = []
    if box[0] < page[0] - TOL:
        parts.append(f"the left edge by {page[0] - box[0]:g} units")
    if box[1] < page[1] - TOL:
        parts.append(f"the bottom edge by {page[1] - box[1]:g} units")
    if box[2] > page[2] + TOL:
        parts.append(f"the right edge by {box[2] - page[2]:g} units")
    if box[3] > page[3] + TOL:
        parts.append(f"the top edge by {box[3] - page[3]:g} units")
    return " and ".join(parts)


def _bounds(points: Sequence[tuple[float, float]]) -> Box:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _polyline_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in _edges(points)
    )


def _box_text(box: Box) -> str:
    return f"[{box[0]:g}, {box[1]:g}, {box[2]:g}, {box[3]:g}]"


class _UnionFind:
    """Minimal union-find over element names, with path compression.

    Local to this module rather than imported from
    `core.circuitspec._UnionFind`: a private name crossing a layer is what
    `tests/test_layer_rules.py` exists to forbid, and its canonical component
    order is a property of *specs*, not of a derivation.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, node: str) -> str:
        self._parent.setdefault(node, node)
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self._parent[root_right] = root_left


# ============================================== the page-level domain (056 sec.3)
#
# The nine constraints above judge one drawing. These eight judge a page made of
# several — where the frames sit, what happens to a wire when it leaves a module,
# and whether two modules say the same thing about a shared net. The two domains
# are separate functions on purpose: `check` is the 053 contract and keeps its
# inputs, its order and its meaning, and nothing here changes what it returns.


def module_frames(page_layout: PageLayoutPlan) -> dict[str, Box]:
    """``module id -> stated frame``, refusing a document with no module.

    A small reader rather than a policy: the frames are the *document's* facts,
    and :func:`check_page` verifies them against the geometry instead of
    recomputing them (see the module docstring).
    """
    return {module.id: module.frame for module in page_layout.modules}


def check_page(
    page_layout: PageLayoutPlan,
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile],
    *,
    keepouts: Sequence[Box] = (),
    module_gap: float = PAGE_MODULE_GAP,
) -> CheckResult:
    """Run the eight page constraints and measure the page's soft metrics.

    ``page_layout`` is a :class:`~boardwise.core.pagelayoutplan.PageLayoutPlan`:
    the merged drawing plus the module placement facts. The *drawing* half of the
    contract is the nine constraints, checked by :func:`check` on the merged plan
    — this function never re-judges it, and a caller that wants both runs both.
    The page box the frames are tested against is the document's own
    ``page_box`` (a page without one has nothing to be outside of).

    The module membership used here comes from the **presentation spec**, not from
    the document's own ``modules[*].parts``: the split is an input, and a document
    whose split disagrees with the spec it claims to come from is a
    :class:`ReadabilityError` rather than a page finding, because there is no
    reading of the page that makes both true.

    ``keepouts`` are the page-level reserved regions (a title block, a reserved
    area). ``module_gap`` is the clear space two frames must keep — the caller
    passes the values it compiled with; the defaults are this module's own
    statement of the same rules. There is deliberately **no member-count
    parameter**: 069 sec.7 retired the count at this scale ("a rail is a bus at
    any fan-out") and the one crossing net a page draws as a wire is the
    `mainPath` one (:func:`~boardwise.core.presentationspec.main_path_wire`,
    096), so a parameter nothing consults is not stated at all (097 removed the
    one that was accepted and validated but never read). The lattice grid is
    deliberately *not* a parameter either: the page domain measures frames and
    wires, not lattice alignment.
    """
    for value, expected in (
        (page_layout, PageLayoutPlan),
        (circuit_spec, CircuitSpec),
        (presentation_spec, PresentationSpec),
    ):
        if not isinstance(value, expected):
            raise ReadabilityError(
                f"{expected.__name__} expected, got {type(value).__name__}"
            )
    if isinstance(module_gap, bool) or not isinstance(module_gap, (int, float)) or module_gap <= 0:
        raise ReadabilityError(
            f"module_gap must be a positive number of canvas units, got {module_gap!r}"
        )
    reserved: list[Box] = []
    for index, item in enumerate(keepouts):
        box = check_box(item, f"keepouts[{index}]", ReadabilityError)
        if box is None:
            raise ReadabilityError(
                f"keepouts[{index}] is not a box — an absent keep-out is one the "
                "caller should not have listed"
            )
        reserved.append(box)

    frames = _checked_frames(page_layout, presentation_spec)
    plan = page_layout.plan
    placed = _placed_parts(plan, _profile_map(profiles))
    membership = _part_membership(plan, presentation_spec)
    cross = _cross_module_wires(plan, frames)

    violations: list[HardViolation] = []
    violations.extend(_check_frames_on_the_page(frames, page_layout.page_box))
    violations.extend(_check_frame_separation(frames, module_gap))
    violations.extend(_check_geometry_framed(plan, placed, frames, membership))
    violations.extend(_check_part_membership(plan, membership))
    violations.extend(_check_wires_clear_of_frames(plan, frames))
    violations.extend(_check_shared_expressions(
        plan, circuit_spec, presentation_spec, frames, cross,
    ))
    violations.extend(_check_main_paths(
        presentation_spec, circuit_spec, frames, cross,
    ))
    violations.extend(_check_page_keepouts(frames, reserved))

    metrics, reasons = _page_metrics(plan, presentation_spec, frames, cross)
    return CheckResult(
        hard_violations=violations, soft_metrics=metrics, soft_reasons=reasons,
    )


# ------------------------------------------------------------- page: readers


def _checked_frames(
    page_layout: PageLayoutPlan, presentation_spec: PresentationSpec
) -> dict[str, Box]:
    """The frames, after checking the document and the spec agree on the split.

    Two documents describe the split — the presentation (what the author asked
    for) and the page (what the compiler placed). They are allowed to *further
    detail* it (a grammar per module) but not to disagree about which parts form
    a module: a page whose frames group different parts from the spec it names is
    a page about a different circuit, and no finding would say so.
    """
    wanted = {module.id: sorted(module.parts) for module in presentation_spec.modules}
    found = {module.id: sorted(module.parts) for module in page_layout.modules}
    if wanted != found:
        only_here = sorted(set(found) - set(wanted))
        only_there = sorted(set(wanted) - set(found))
        detail = []
        if only_here:
            detail.append(f"the page places {', '.join(only_here)}, the spec does not")
        if only_there:
            detail.append(f"the spec declares {', '.join(only_there)}, the page does not")
        for module_id in sorted(set(wanted) & set(found)):
            if wanted[module_id] != found[module_id]:
                detail.append(
                    f"module {module_id!r} holds {', '.join(found[module_id])} on "
                    f"the page and {', '.join(wanted[module_id])} in the spec"
                )
        raise ReadabilityError(
            "the page document's module split is not the presentation spec's ("
            + "; ".join(detail)
            + ") — the checker reads the membership from the spec, so a page that "
            "groups other parts is not the page this spec describes"
        )
    return module_frames(page_layout)


def _part_membership(
    layout_plan: LayoutPlan, presentation_spec: PresentationSpec
) -> dict[str, tuple[str, ...]]:
    """``placed part -> the modules that claim it``, sorted."""
    out: dict[str, tuple[str, ...]] = {}
    for part in layout_plan.parts:
        out[part.part_id] = tuple(
            sorted(module.id for module in presentation_spec.modules
                   if part.part_id in module.parts)
        )
    return out


def _part_extent(part: _PlacedPart) -> Box:
    """A placed part's own box: its body unioned with its pin tips.

    The tips are part of the part's extent — a symbol's pin usually reaches past
    its body — and text avoidance in the compiler treats them as occupied, so
    the frame has to hold them too.
    """
    xs: list[float] = []
    ys: list[float] = []
    if part.body is not None:
        xs.extend((part.body[0], part.body[2]))
        ys.extend((part.body[1], part.body[3]))
    for point in part.pins.values():
        xs.append(point[0])
        ys.append(point[1])
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _inside(point: tuple[float, float], box: Box) -> bool:
    return (
        box[0] - TOL <= point[0] <= box[2] + TOL
        and box[1] - TOL <= point[1] <= box[3] + TOL
    )


def _box_inside(inner: Box, outer: Box) -> bool:
    return (
        inner[0] >= outer[0] - TOL and inner[1] >= outer[1] - TOL
        and inner[2] <= outer[2] + TOL and inner[3] <= outer[3] + TOL
    )


def _frames_of(point: tuple[float, float], frames: Mapping[str, Box]) -> tuple[str, ...]:
    """Every frame the point lies in, in module-id order."""
    return tuple(
        name for name, box in sorted(frames.items()) if _inside(point, box)
    )


# ------------------------------------------------------- page: the eight rules


def _check_frames_on_the_page(
    frames: Mapping[str, Box], page: Box | None
) -> list[HardViolation]:
    """A frame that leaves the sheet is a page that does not fit."""
    if page is None:
        return []
    out = []
    for name, box in sorted(frames.items()):
        leaving = _outside(box, page)
        if not leaving:
            continue
        out.append(HardViolation(
            kind=KIND_MODULE_FRAME_OVERFLOW,
            objects=(f"pageLayout.modules[{name}]",),
            evidence=(
                f"the frame {_box_text(box)} leaves the page {_box_text(page)}: "
                f"{leaving} — the page layer is expected to enlarge the page, move "
                "the module or refuse, never to draw outside the sheet"
            ),
        ))
    return out


def _check_frame_separation(
    frames: Mapping[str, Box], module_gap: float
) -> list[HardViolation]:
    """Frames must not overlap, and must keep the page's clear space."""
    names = sorted(frames)
    out = []
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            gap = _box_gap(frames[left], frames[right])
            if gap > module_gap - TOL:
                continue
            overlap = _overlap(frames[left], frames[right])
            out.append(HardViolation(
                kind=KIND_MODULE_FRAME_OVERLAP,
                objects=(f"pageLayout.modules[{left}]", f"pageLayout.modules[{right}]"),
                evidence=(
                    (
                        f"the two frames overlap ({_box_text(frames[left])} and "
                        f"{_box_text(frames[right])}) — each frame is a rigid body "
                        "on the page, and two bodies cannot share canvas"
                    )
                    if overlap
                    else (
                        f"the frames are {gap:g} canvas units apart, and the page's "
                        f"module gap is {module_gap:g} — the clear space is what "
                        "keeps two modules' annotations (a flag's stem, a label's "
                        "box) off each other"
                    )
                ),
            ))
    return out


def _check_geometry_framed(
    plan: LayoutPlan,
    placed: list[_PlacedPart],
    frames: Mapping[str, Box],
    membership: Mapping[str, tuple[str, ...]],
) -> list[HardViolation]:
    """Everything the page draws lies inside some module frame.

    The frames are the page's way of saying "this is where module M is", so a
    piece of geometry in no frame is either a frame that does not hold its own
    drawing or a drawing that the page does not account for; both make every
    other page constraint meaningless, which is why this is checked first.
    """
    if not frames:
        return []
    out: list[HardViolation] = []

    def framed(box: Box) -> bool:
        """Is this box held by some module frame? (containment, not overlap)"""
        return any(_box_inside(box, frame) for frame in frames.values())

    for part in sorted(placed, key=lambda item: item.part_id):
        box = _part_extent(part)
        if framed(box):
            continue
        out.append(HardViolation(
            kind=KIND_GEOMETRY_OUTSIDE_FRAMES,
            objects=(f"parts[{part.part_id}]",),
            evidence=(
                f"the part's extent {_box_text(box)} is in no module frame — the "
                "modules that claim it are "
                + (", ".join(membership.get(part.part_id, ())) or "none")
            ),
        ))
    for index, text in enumerate(plan.texts):
        if framed(text.bbox):
            continue
        out.append(HardViolation(
            kind=KIND_GEOMETRY_OUTSIDE_FRAMES,
            objects=(f"texts[{index}]",),
            evidence=(
                f"the text {text.text!r} occupies {_box_text(text.bbox)}, which is "
                "in no module frame — a text the page placed outside every module "
                "belongs to no group, and nothing keeps the next module off it"
            ),
        ))
    for index, label in enumerate(plan.labels):
        if framed(label.bbox) and _frames_of((label.x, label.y), frames):
            continue
        out.append(HardViolation(
            kind=KIND_GEOMETRY_OUTSIDE_FRAMES,
            objects=(f"labels[{index}]",),
            evidence=(
                f"the label {label.text!r} anchors at ({label.x:g}, {label.y:g}) "
                f"with its box at {_box_text(label.bbox)}, and neither is inside a "
                "module frame"
            ),
        ))
    for index, symbol in enumerate(plan.power_symbols):
        if _frames_of((symbol.x, symbol.y), frames):
            continue
        out.append(HardViolation(
            kind=KIND_GEOMETRY_OUTSIDE_FRAMES,
            objects=(f"powerSymbols[{index}]",),
            evidence=(
                f"the flag for net {symbol.net!r} anchors at "
                f"({symbol.x:g}, {symbol.y:g}), which is in no module frame"
            ),
        ))
    for index, segment in enumerate(plan.segments):
        for end, point in (("start", segment.points[0]), ("end", segment.points[-1])):
            if _frames_of(point, frames):
                continue
            out.append(HardViolation(
                kind=KIND_GEOMETRY_OUTSIDE_FRAMES,
                objects=(f"segments[{index}]",),
                evidence=(
                    f"the wire's {end} ({point[0]:g}, {point[1]:g}) is in no module "
                    f"frame — a wire end belongs inside the module whose drawing it "
                    f"is part of (net {segment.net!r})"
                ),
            ))
    return out


def _check_part_membership(
    plan: LayoutPlan, membership: Mapping[str, tuple[str, ...]]
) -> list[HardViolation]:
    """Every placed part belongs to exactly one module (056 sec.1)."""
    out = []
    for part in plan.parts:
        owners = membership.get(part.part_id, ())
        if len(owners) == 1:
            continue
        if len(owners) > 1:
            out.append(HardViolation(
                kind=KIND_MODULE_PART_UNASSIGNED,
                objects=(f"parts[{part.part_id}]",),
                evidence=(
                    f"the part is claimed by modules {', '.join(owners)} — a part "
                    "belongs to one group, and which one is what decides where its "
                    "branches hang and which frame holds it"
                ),
            ))
            continue
        out.append(HardViolation(
            kind=KIND_MODULE_PART_UNASSIGNED,
            objects=(f"parts[{part.part_id}]",),
            evidence=(
                "the part is placed on the page but belongs to no module — the "
                "page compiler groups the circuit into modules, and a part outside "
                "every group has no frame that has to hold it"
            ),
        ))
    return out


def _interior_runs(
    points: Sequence[tuple[float, float]], box: Box
) -> list[tuple[int, int]]:
    """Contiguous runs of sub-segments with a positive-length interior in `box`.

    Contiguity is what makes "the wire entered this frame once" checkable: a wire
    that leaves a module and comes back has two runs, and a wire that only passes
    through has a run without either end of the wire in the frame.
    """
    runs: list[tuple[int, int]] = []
    for index, (start, end) in enumerate(_edges(points)):
        inside = _clip_to_box(start, end, box) is not None
        if not inside:
            continue
        if runs and runs[-1][1] == index - 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def _check_wires_clear_of_frames(
    plan: LayoutPlan, frames: Mapping[str, Box]
) -> list[HardViolation]:
    """A wire may only run inside the frames its own two ends are in — once each.

    The page's version of `wire-through-body`, and deliberately not the same
    rule: a module frame is mostly empty canvas, so a wire *may* legally pass
    through the space between two of a module's parts while breaking nothing the
    nine constraints can see. 056 sec.3's rule is that it may not: the drawn
    connection leaves through one frame edge and arrives through the other's,
    and the wire's own module gets exactly one escape run.
    """
    if not frames:
        return []
    out: list[HardViolation] = []
    for index, segment in enumerate(plan.segments):
        points = segment.points
        ends = {_frames_of(points[0], frames), _frames_of(points[-1], frames)}
        allowed = {name for group in ends for name in group}
        for name, frame in sorted(frames.items()):
            runs = _interior_runs(points, frame)
            if not runs:
                continue
            if name not in allowed:
                out.append(HardViolation(
                    kind=KIND_WIRE_THROUGH_MODULE_FRAME,
                    objects=(f"segments[{index}]", f"pageLayout.modules[{name}]"),
                    evidence=(
                        f"net {segment.net!r} runs through module {name!r}'s frame "
                        f"{_box_text(frame)} although neither of the wire's ends is "
                        "in it — a neighbouring module's drawing is a body the page "
                        "routes around, and the detour is the wire's obligation "
                        "(056 sec.3)"
                    ),
                ))
                continue
            if len(runs) > 1:
                out.append(HardViolation(
                    kind=KIND_WIRE_THROUGH_MODULE_FRAME,
                    objects=(f"segments[{index}]", f"pageLayout.modules[{name}]"),
                    evidence=(
                        f"net {segment.net!r} has {len(runs)} separate runs inside "
                        f"module {name!r}'s frame — a wire leaves its own module "
                        "once and arrives at the other's once; a wire that re-enters "
                        "is one whose escape was not routed around the frame"
                    ),
                ))
    return out


def _cross_module_wires(
    plan: LayoutPlan, frames: Mapping[str, Box]
) -> list[tuple[int, str, str, str]]:
    """``(segment index, net, module A, module B)`` for every wire spanning frames."""
    out: list[tuple[int, str, str, str]] = []
    for index, segment in enumerate(plan.segments):
        start = _frames_of(segment.points[0], frames)
        end = _frames_of(segment.points[-1], frames)
        if not start or not end:
            continue
        first = start[0]
        last = end[0] if end[0] != first else (end[1] if len(end) > 1 else "")
        if last and last != first:
            out.append((index, segment.net, first, last))
    return out


def _name_anchors(
    plan: LayoutPlan, frames: Mapping[str, Box]
) -> dict[tuple[str, str], set[str]]:
    """``(module, net) -> the kinds of name stated there``, inside a frame.

    A *set*, because a module may state one net twice (a label added beside the
    flag it already carries) and that is exactly the mix the consistency rule is
    about — recording only one kind per pair would let the second statement hide
    behind the first. Only the names *inside* a frame count: a label sitting in the
    page gap is already reported as geometry outside every frame, and reading it as
    one module's statement would be a guess about which module it belongs to.
    """
    out: dict[tuple[str, str], set[str]] = {}
    for label in plan.labels:
        for name in _frames_of((label.x, label.y), frames):
            out.setdefault((name, label.net), set()).add("label")
    for symbol in plan.power_symbols:
        for name in _frames_of((symbol.x, symbol.y), frames):
            out.setdefault((name, symbol.net), set()).add("flag")
    return out


def _nets_by_module(
    circuit_spec: CircuitSpec, presentation_spec: PresentationSpec
) -> dict[str, tuple[str, ...]]:
    """``net id -> the modules that own members of it``, sorted.

    The scoping question every shared-net rule starts from, answered from the two
    documents and the circuit's own membership — never from the page's port
    table, which is the compiler's account of the same thing.
    """
    out: dict[str, tuple[str, ...]] = {}
    for net in circuit_spec.nets:
        owners = {member.partition(".")[0] for member in net.members}
        found = sorted(
            module.id for module in presentation_spec.modules
            if owners & set(module.parts)
        )
        out[net.id] = tuple(found)
    return out


def _check_shared_expressions(
    plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    frames: Mapping[str, Box],
    cross: Sequence[tuple[int, str, str, str]],
) -> list[HardViolation]:
    """One shared net is stated one way on the page (056 sec.3's consistency).

    The join between two modules happens **by name** in the editor (054 C7: the
    netlist is project-level), so the page may not leave a shared net half-wired
    and half-named, and may not name it with a flag in one module and a label in
    the other. The one exception is the whole `mainPath` edge: there the
    connection is a wire end to end, so no name is required at either end.
    """
    anchors = _name_anchors(plan, frames)
    wired: dict[str, set[str]] = {}
    for _index, net, left, right in cross:
        wired.setdefault(net, set()).update((left, right))
    out: list[HardViolation] = []
    for net_id, modules in sorted(_nets_by_module(circuit_spec, presentation_spec).items()):
        if len(modules) < 2:
            continue
        stated: dict[str, list[str]] = {"label": [], "flag": []}
        for module_id in modules:
            for kind in sorted(anchors.get((module_id, net_id), ())):
                stated[kind].append(module_id)
        if stated["label"] and stated["flag"]:
            out.append(HardViolation(
                kind=KIND_SHARED_NET_EXPRESSION_SPLIT,
                objects=(f"circuitSpec.nets[{net_id}]",),
                evidence=(
                    "the net is a label on "
                    + ", ".join(sorted(set(stated["label"])))
                    + " and a flag on "
                    + ", ".join(sorted(set(stated["flag"])))
                    + " — two drawings that name one net must name it the same way "
                    "(056 sec.3): the join happens by name, and a reader cannot tell "
                    "a flag from a label without checking both"
                ),
            ))
        joined = wired.get(net_id, set())
        named = sorted(set(stated["label"]) | set(stated["flag"]))
        if joined and named:
            out.append(HardViolation(
                kind=KIND_SHARED_NET_EXPRESSION_SPLIT,
                objects=(f"circuitSpec.nets[{net_id}]",),
                evidence=(
                    "the net is drawn as a wire between "
                    + " and ".join(sorted(joined))
                    + " and stated by name on " + ", ".join(named)
                    + " — a connection is either a wire from end to end or a name "
                    "at every end (056 sec.3: '一段线接一半再变标签' is what this "
                    "refuses)"
                ),
            ))
        if len(joined) > 2:
            out.append(HardViolation(
                kind=KIND_SHARED_NET_EXPRESSION_SPLIT,
                objects=(f"circuitSpec.nets[{net_id}]",),
                evidence=(
                    "the net is wired across "
                    + ", ".join(sorted(joined))
                    + f" ({len(joined)} modules) — a cross-module wire is a whole "
                    "flow edge between two modules; a net that reaches more of them "
                    "is expressed by name at each (053 sec.7's high fan-out rule, and "
                    "056 sec.3's exception is one edge wide)"
                ),
            ))
    return out


def _shared_nets(
    nets_by_module: Mapping[str, tuple[str, ...]], left: str, right: str
) -> list[str]:
    """The circuit's nets that have members in both modules, sorted."""
    return sorted(
        net_id for net_id, modules in nets_by_module.items()
        if left in modules and right in modules
    )


def _check_main_paths(
    presentation_spec: PresentationSpec,
    circuit_spec: CircuitSpec,
    frames: Mapping[str, Box],
    cross: Sequence[tuple[int, str, str, str]],
) -> list[HardViolation]:
    """A `mainPath` edge the reader is meant to follow is a wire, or it says so.

    056 sec.3: a main-path edge that ended up named instead of wired is reported
    and *named* — never silently downgraded. The rule here is the checkable half
    of that: the edge must be joined by a cross-module wire, and which shared net
    may *be* that wire is not this module's judgement — it is
    :func:`~boardwise.core.presentationspec.main_path_wire`, the same function the
    page compiler picks each port's style with (096). A second copy of the rule
    here (the member-count threshold 069 sec.7 retired: `power` with more than
    `high_fanout` members is a bus) is what made a four-member rail a wire to the
    compiler and a bus to the checker, so a page the compiler had just drawn was
    refused by the checker on the same pass.
    """
    nets_by_module = _nets_by_module(circuit_spec, presentation_spec)
    out: list[HardViolation] = []
    for edge in presentation_spec.main_path_edges():
        pair = {edge.from_module, edge.to_module}
        if not pair <= set(frames):
            continue  # a page that does not place both modules: the compiler refuses
        shared = _shared_nets(nets_by_module, edge.from_module, edge.to_module)
        eligible: list[str] = []
        for net_id in shared:
            net = circuit_spec.net(net_id)
            if main_path_wire(
                presentation_spec,
                net.cls if net is not None else None,
                (edge.from_module, edge.to_module),
            ):
                eligible.append(net_id)
        wired = [
            net_id for _index, net_id, left, right in cross
            if {left, right} == pair and net_id in eligible
        ]
        if wired:
            continue
        out.append(HardViolation(
            kind=KIND_MAIN_PATH_EDGE_NOT_WIRED,
            objects=(
                f"presentationSpec.flow[{edge.from_module}->{edge.to_module}]",
            ),
            evidence=(
                "the presentation marks this edge main-path, but no wire joins the "
                f"two modules ({_main_path_reason(shared, eligible)}) — the edge is "
                "wired end to end or the mark is dropped; a main-path edge is not "
                "downgraded to a name quietly"
            ),
        ))
    return out


def _main_path_reason(shared: Sequence[str], eligible: Sequence[str]) -> str:
    """Why a main-path edge has no wire: which of its shared nets it could use."""
    if not shared:
        return "the two modules share no net at all"
    buses = [net_id for net_id in shared if net_id not in set(eligible)]
    if not eligible:
        return (
            "the nets they share are all buses, which are always expressed by "
            f"name ({', '.join(buses)})"
        )
    return (
        "the nets they share that could be wired are "
        + ", ".join(eligible)
        + (
            ", and " + ", ".join(buses) + " is a bus"
            if buses
            else ""
        )
    )


def _check_page_keepouts(
    frames: Mapping[str, Box], keepouts: Sequence[Box]
) -> list[HardViolation]:
    """A page-level keep-out may not land on a module."""
    out = []
    for index, keep in enumerate(keepouts):
        for name, frame in sorted(frames.items()):
            if not _overlap(keep, frame):
                continue
            out.append(HardViolation(
                kind=KIND_PAGE_KEEPOUT_CONFLICT,
                objects=(f"keepouts[{index}]", f"pageLayout.modules[{name}]"),
                evidence=(
                    f"the keep-out {_box_text(keep)} overlaps module {name!r}'s "
                    f"frame {_box_text(frame)} — a reserved region and a module "
                    "cannot share the canvas, and the page may not shrink the "
                    "module's own drawing to get out of the way"
                ),
            ))
    return out


# ------------------------------------------------------- page: soft metrics


def _page_metrics(
    plan: LayoutPlan,
    presentation_spec: PresentationSpec,
    frames: Mapping[str, Box],
    cross: Sequence[tuple[int, str, str, str]],
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """The page's raw optimization values, one reason per value (052 sec.6).

    ``page_cross_module_wire_length``, ``page_backflow_length``,
    ``page_crossings``, ``page_bends``, ``page_min_module_gap`` and ``page_area``
    — never a total, and never mixed with the drawing's own metrics: this is what
    the page layer ranks on, and a single number would let a shorter wire buy back
    a backwards reading order.
    """
    metrics: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    lengths = [
        (index, _polyline_length(plan.segments[index].points))
        for index, _net, _left, _right in cross
    ]
    metrics["page_cross_module_wire_length"] = sum(
        length for _index, length in lengths
    )
    reasons["page_cross_module_wire_length"] = [
        f"segments[{index}] (net {plan.segments[index].net!r}) crosses "
        f"{left} -> {right}: {length:g} units"
        for (index, length), (_i, _net, left, right) in zip(lengths, cross)
    ] or ["no wire crosses a module boundary on this page"]

    backflow: list[str] = []
    total_backflow = 0.0
    centres = {
        name: ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        for name, box in frames.items()
    }
    for edge in presentation_spec.flow:
        if edge.from_module not in centres or edge.to_module not in centres:
            continue
        left, right = frames[edge.from_module], frames[edge.to_module]
        if _overlap(left, right) or _share_a_column(left, right):
            continue  # the flow runs down the page between two stacked frames
        dx = centres[edge.to_module][0] - centres[edge.from_module][0]
        if dx >= 0.0:
            continue
        total_backflow += abs(dx)
        backflow.append(
            f"flow {edge.from_module} -> {edge.to_module} runs "
            f"{abs(dx):g} units against the page's reading direction"
            + (" (main-path)" if edge.main_path else "")
        )
    metrics["page_backflow_length"] = total_backflow
    reasons["page_backflow_length"] = backflow or [
        "every flow edge runs in the page's reading direction (left to right "
        "within a row, then the next row down)"
    ]

    crossings = [
        f"segments[{left}] x segments[{right}] at ({point[0]:g}, {point[1]:g})"
        for left, right, point in _crossings(plan)
        if {left, right} & {index for index, _net, _l, _r in cross}
    ]
    metrics["page_crossings"] = float(len(crossings))
    if crossings:
        reasons["page_crossings"] = crossings

    bends = [
        f"segments[{index}] (net {plan.segments[index].net!r}): "
        f"{_bend_count(plan.segments[index].points)} bend(s)"
        for index, _net, _left, _right in cross
        if _bend_count(plan.segments[index].points)
    ]
    metrics["page_bends"] = float(
        sum(
            _bend_count(plan.segments[index].points)
            for index, _net, _left, _right in cross
        )
    )
    if bends:
        reasons["page_bends"] = bends

    gaps = [
        (left, right, _box_gap(frames[left], frames[right]))
        for index, left in enumerate(sorted(frames))
        for right in sorted(frames)[index + 1:]
    ]
    metrics["page_min_module_gap"] = (
        min(gap for _l, _r, gap in gaps) if gaps else UNMEASURED
    )
    reasons["page_min_module_gap"] = [
        f"{left} to {right}: {gap:g} units" for left, right, gap in gaps
    ] or ["a single module on the page, so there is no gap to measure"]

    if frames:
        box = _frame_bounds(frames.values())
        metrics["page_area"] = (box[2] - box[0]) * (box[3] - box[1])
        reasons["page_area"] = [
            f"the module frames occupy {box[2] - box[0]:g} x "
            f"{box[3] - box[1]:g} = {metrics['page_area']:g} units^2"
        ]
    else:
        metrics["page_area"] = UNMEASURED
        reasons["page_area"] = ["no module on the page, so it occupies nothing"]
    return metrics, reasons


def _share_a_column(left: Box, right: Box) -> bool:
    """Do two frames sit one above the other (their x ranges overlap)?

    The reading order is left to right within a row and then the next row down, so
    a flow that runs between two stacked frames is *going the right way* however
    their centres happen to line up; only a flow that has to travel back to the
    left is what "backflow" names.
    """
    return min(left[2], right[2]) - max(left[0], right[0]) > TOL


def _frame_bounds(frames: Iterable[Box]) -> Box:
    boxes = list(frames)
    return (
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    )
