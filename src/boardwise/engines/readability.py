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
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import Box, SymbolProfile, check_box

__all__ = [
    "CHECKER_NAME",
    "DEFAULT_GRID",
    "HARD_KINDS",
    "KIND_DANGLING_WIRE_END",
    "KIND_NC_PIN_CONNECTED",
    "KIND_NETLIST_PARTITION",
    "KIND_OUT_OF_PAGE",
    "KIND_REQUIRED_PIN_NOT_CONNECTED",
    "KIND_TEXT_OVERLAP",
    "KIND_UNDECLARED_JUNCTION",
    "KIND_USER_LOCK_VIOLATED",
    "KIND_WIRE_THROUGH_BODY",
    "PRECISION",
    "TOL",
    "UNMEASURED",
    "CheckResult",
    "DerivedNetlist",
    "HardViolation",
    "ReadabilityError",
    "check",
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
    violations.extend(_check_netlist(circuit_spec, net))
    violations.extend(_check_wire_ends(layout_plan, net))
    violations.extend(_check_junctions(layout_plan))
    violations.extend(_check_bodies(layout_plan, placed))
    violations.extend(_check_text(layout_plan, placed))
    violations.extend(_check_page(layout_plan, placed, page, keep))
    violations.extend(_check_locks(presentation_spec, layout_plan))
    violations.extend(_check_nc(circuit_spec, net))
    violations.extend(_check_required_pins(circuit_spec, net, placed))

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
    circuit_spec: CircuitSpec, net: DerivedNetlist
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
    spec_net_of: dict[str, str] = {}
    for spec_net in circuit_spec.nets:
        for pin in spec_net.members:
            spec_net_of[pin] = spec_net.id
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
        present = [pin for pin in spec_net.members if pin in domain]
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
    """``(name, box, partId, text)`` for every text on the canvas, labels included."""
    boxes: list[tuple[str, Box, str, str]] = [
        (f"texts[{index}]", item.bbox, item.part_id, item.text)
        for index, item in enumerate(layout_plan.texts)
    ]
    boxes.extend(
        (f"labels[{index}]", item.bbox, "", item.text)
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


def _check_nc(circuit_spec: CircuitSpec, net: DerivedNetlist) -> list[HardViolation]:
    """Constraint 8: an explicit NC pin is not connected to anything.

    053 sec.2: "没给连接" ≠ NC, and NC is explicit — so the drawing owes the pin
    nothing at all. Either form of attachment counts as connected: another pin
    on the same derived node, or a conductor (wire, label, power symbol) sitting
    on the tip. A pin whose part is not placed cannot be connected and is not
    reported here.
    """
    out: list[HardViolation] = []
    for item in circuit_spec.nc:
        pin = item.pin
        if pin not in net.pin_points:
            continue
        group = net.group_of(pin)
        others = [other for other in group if other != pin]
        attached = pin in net.wired_pins
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
    circuit_spec: CircuitSpec, net: DerivedNetlist, placed: list[_PlacedPart]
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
            if pin not in net.pin_points:
                part_id = pin.partition(".")[0]
                part = by_id.get(part_id)
                if part is None:
                    why = f"part {part_id} is not placed in the plan"
                else:
                    why = (
                        f"the profile of its symbol {part.symbol_ref!r} has no pin "
                        f"{pin.partition('.')[2]}"
                    )
                out.append(HardViolation(
                    KIND_REQUIRED_PIN_NOT_CONNECTED,
                    (name, f"pins[{pin}]"),
                    f"{pin} is declared on net {spec_net.id!r} but it has no tip in "
                    f"the drawing — {why}",
                ))
                continue
            group = net.group_of(pin)
            if len(group) > 1 or pin in net.wired_pins:
                continue
            point = net.pin_points[pin]
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
