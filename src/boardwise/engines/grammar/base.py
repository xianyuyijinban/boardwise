"""The vocabulary the three drawing grammars share (053 sec.3, 052 sec.5).

A *drawing grammar* answers one question: given that this circuit is a voltage
divider, what must the drawing make visible? Its answer has three parts — the
roles (which part plays which arm), the relative relations (which arm is above
which, where the tap leaves) and the topology that must be readable without
chasing labels. It is deliberately **not** a template with coordinates: 052 sec.5
asks for "角色、相对关系、必须可见的拓扑及允许变体；坐标由真实符号、文字和空间计算",
and 053 sec.4 puts the coordinate work in the compiler, which consumes these
results.

Three properties this module enforces rather than trusts:

* **A relation is never a coordinate.** :class:`RelativeConstraint` has no x/y
  and its two endpoints are part ids; the compiler resolves them against the
  SymbolProfile and the space it has. That is what lets one grammar survive a
  different symbol (053 sec.5 scenario 2) instead of encoding one drawing.
* **A binding says how it knows.** :class:`RoleBinding.evidence` carries the
  facts that produced the binding *including their provenance*, so a circuit
  stated as `ai_asserted` yields visibly draft bindings (052 sec.4) rather than
  bindings that look like measurements.
* **Contradictions are refused, not smoothed over.** A result either claims `ok`
  and carries no failure, or fails and carries at least one failure in one of
  the four categories of 053 sec.4 — each with a concrete reason and, where one
  exists, an action.

The vocabularies, with the clause each item comes from.

**Constraint kinds.** `subject` and `object` are both **part ids**; the `reason`
carries the clause-level precision, because a bare kind cannot say *which end*
of a part it means.

===============  ==========================================================
``same-column``  one vertical axis (053 sec.3: 两电阻竖排同轴)
``same-row``     one horizontal axis (053 sec.3: 主干水平; the RC trunk)
``above``        subject nearer the power end than object
``below``        subject nearer the ground end than object
``left-of``      subject on the power side when that side is the left one
``right-of``     subject on the power side when that side is the right one
``adjacent``     nothing between them
``near``         same local group, no module boundary crossed
``horizontal-tap``  **added by this batch**: at the junction of subject and
                 object the tap stub leaves horizontally. 053 sec.3 states the
                 relation in prose ("tap 中点水平引出") and the table needs a
                 checkable name for it.
``vertical-tap``     the mirror case, for a chain drawn horizontally (053
                 sec.3's "横排镜像" variant)
===============  ==========================================================

**Obligation kinds.** `nets` names the nets the obligation is about; for
`direct-wire` the tuple is the chain **in electrical order**.

===============  ==========================================================
``direct-wire``  the local topology must be wired, not spelled with labels
                 (053 sec.3; 052 sec.5 "关键局部拓扑优先直连")
``visible-tap``  the tap is visible as a stub with a label or a port
``owned-branch`` the branch hanging on this node reads as owned by it, not as a
                 wire crossing into another module
``uniform-gnd``  **added by this batch**: this module's ground is expressed one
                 way throughout — one symbol style or one label, never mixed
                 (053 sec.3: "地表达统一（同符号或同标签不混用）")
===============  ==========================================================

**Failure categories** (053 sec.4, all four named here; the grammars of this
batch only produce the first two — the other two belong to the compiler and to
the readability checker):

==================  ======================================================
``facts-missing``   a fact the grammar needs was not stated: which fact, and
                    where to state it
``circuit-invalid`` the connections contradict the grammar's topology
``layout-unsat``    no legal layout inside the given budget (compiler)
``presentation-poor`` the intent does not say enough to draw it well (checker)
==================  ======================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence, runtime_checkable

from ...core.circuitspec import (
    PROVENANCE_AI,
    PROVENANCE_ENGINEER,
    PROVENANCE_VERIFIED,
    CircuitSpec,
    SpecNet,
    SpecPart,
)
from ...core.presentationspec import PresentationSpec
from ...core.symbolprofile import ROLE_BY_PIN_NAME, SymbolPin, SymbolProfile

__all__ = [
    "ABOVE",
    "ADJACENT",
    "BELOW",
    "CONSTRAINT_KINDS",
    "FAILURE_CATEGORIES",
    "FAILURE_CIRCUIT_INVALID",
    "FAILURE_FACTS_MISSING",
    "FAILURE_LAYOUT_UNSAT",
    "FAILURE_PRESENTATION_POOR",
    "HORIZONTAL_TAP",
    "LEFT_OF",
    "MAX_CHAIN_ARMS",
    "MAX_CHAINS",
    "NEAR",
    "NET_ROLES",
    "OBLIGATION_KINDS",
    "DIRECT_WIRE",
    "OWNED_BRANCH",
    "PROVENANCE_UNSTATED",
    "RIGHT_OF",
    "ROLE_NET",
    "ROLE_PART",
    "SAME_COLUMN",
    "SAME_ROW",
    "UNIFORM_GND",
    "VERTICAL_TAP",
    "VISIBLE_TAP",
    "DrawingGrammar",
    "GrammarError",
    "GrammarFailure",
    "GrammarObligation",
    "GrammarResult",
    "RelativeConstraint",
    "RoleBinding",
    "bound_result",
    "connected_net_sets",
    "declares_modules",
    "evidence",
    "is_net_role",
    "module_of_part",
    "modules_of_part",
    "net_clause",
    "net_provenance",
    "nets_of_class",
    "part_clause",
    "pins_of_part",
    "profile_for",
    "profile_pin_for",
    "refused_result",
    "role_pins",
    "series_paths",
    "shared_module",
    "two_terminal_parts",
    "weakest_provenance",
]


class GrammarError(ValueError):
    """A grammar binding was malformed — a programming error, not bad input.

    Input problems never raise: they come back as a :class:`GrammarFailure` in
    one of 053 sec.4's four categories, because a model writes the input and
    "grammar error" alone sends it back with nothing to compare against. This
    exception is for a caller that built a binding out of the vocabulary's set
    (a typo in a kind name) or asked for a grammar that does not exist.
    """


# ------------------------------------------------------------- vocabularies


#: Constraint kinds; see the module docstring for each one's clause.
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

CONSTRAINT_KINDS: tuple[str, ...] = (
    SAME_COLUMN,
    SAME_ROW,
    ABOVE,
    BELOW,
    LEFT_OF,
    RIGHT_OF,
    ADJACENT,
    NEAR,
    HORIZONTAL_TAP,
    VERTICAL_TAP,
)

#: Obligation kinds; see the module docstring for each one's clause.
DIRECT_WIRE = "direct-wire"
VISIBLE_TAP = "visible-tap"
OWNED_BRANCH = "owned-branch"
UNIFORM_GND = "uniform-gnd"

OBLIGATION_KINDS: tuple[str, ...] = (
    DIRECT_WIRE,
    VISIBLE_TAP,
    OWNED_BRANCH,
    UNIFORM_GND,
)

#: The four failure categories of 053 sec.4, in the task book's order.
FAILURE_FACTS_MISSING = "facts-missing"
FAILURE_CIRCUIT_INVALID = "circuit-invalid"
FAILURE_LAYOUT_UNSAT = "layout-unsat"
FAILURE_PRESENTATION_POOR = "presentation-poor"

FAILURE_CATEGORIES: tuple[str, ...] = (
    FAILURE_FACTS_MISSING,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
)

#: The role names that bind a **net** (every other role binds a part). The role
#: vocabulary itself is per grammar; this half of it is common, which is why it
#: is stated once: `in` / `out` / `gnd` / `tap` are the same four names in
#: voltage-divider, rc-lowpass and ldo (053 sec.3).
NET_ROLES: tuple[str, ...] = ("in", "out", "gnd", "tap")

#: What :attr:`RoleBinding.part_id` is holding — the same field carries either,
#: because a CircuitSpec names parts and nets by the same kind of stable logical
#: id (053 sec.2).
ROLE_PART = "part"
ROLE_NET = "net"

#: The token used when a fact said nothing. Absence is not confirmation (052
#: sec.4), so it is a value of its own rather than an empty string nobody reads.
PROVENANCE_UNSTATED = "unstated"

_PROVENANCE_RANK = {
    PROVENANCE_VERIFIED: 2,
    PROVENANCE_ENGINEER: 1,
    PROVENANCE_AI: 0,
    PROVENANCE_UNSTATED: -1,
}

#: How long a series chain this build will look for. A finite budget on purpose:
#: 053 sec.5's rule for the compiler applies to the grammar's search too — when
#: the budget runs out, say "not found inside the budget", never "no solution".
MAX_CHAIN_ARMS = 6

#: How many candidate chains a single search may return, for the pathological
#: case of a densely connected ground-referenced network.
MAX_CHAINS = 64


def is_net_role(role: str) -> bool:
    """Does this role bind a net rather than a part?"""
    return role in NET_ROLES


# ------------------------------------------------------------------ results


@dataclass(frozen=True)
class RoleBinding:
    """One role of a grammar, filled by one stable logical id.

    `part_id` is the CircuitSpec's own name for what was bound — a part id for
    a part role, a **net** id for a role in :data:`NET_ROLES` (053 sec.2 names
    parts and nets by the same kind of id, and 053 sec.3's role table writes
    `tap(net)` / `in(net)` / `gnd(net)` explicitly).

    `evidence` is the load-bearing field: the facts that produced this binding,
    as a ``"; "``-joined list of clauses, ending with ``provenance=<token>`` for
    the weakest provenance among those facts. 052 sec.4: an `ai_asserted`
    circuit may still be drawn, but its output is a visibly marked draft — and
    the marking has to travel with the binding, because that is what the
    compiler and the report read.
    """

    role: str
    part_id: str
    evidence: str

    def __post_init__(self) -> None:
        for field_name in ("role", "part_id", "evidence"):
            if not getattr(self, field_name):
                raise GrammarError(
                    f"RoleBinding.{field_name} is empty — a binding that does "
                    "not say what it bound, or why, is not a binding"
                )

    def to_jsonable(self) -> dict[str, object]:
        return {"role": self.role, "partId": self.part_id,
                "target": ROLE_NET if is_net_role(self.role) else ROLE_PART,
                "evidence": self.evidence}


@dataclass(frozen=True)
class RelativeConstraint:
    """A relation two parts must satisfy — **not** a coordinate (053 sec.4).

    Both endpoints are part ids and both must be named: a constraint with one
    endpoint would be a placement instruction, and placement is the compiler's
    job. `reason` states which clause the relation comes from *and* the part of
    it a bare kind cannot carry (for `same-row` on the RC trunk: which pin of
    the shunt sits on the row).
    """

    kind: str
    subject: str
    object: str
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in CONSTRAINT_KINDS:
            raise GrammarError(
                f"unknown constraint kind {self.kind!r}; this build knows "
                f"{list(CONSTRAINT_KINDS)}"
            )
        for field_name in ("subject", "object", "reason"):
            if not getattr(self, field_name):
                raise GrammarError(
                    f"RelativeConstraint.{field_name} is empty — a relation "
                    "names both endpoints and the clause it comes from"
                )

    def to_jsonable(self) -> dict[str, object]:
        return {"kind": self.kind, "subject": self.subject,
                "object": self.object, "reason": self.reason}


@dataclass(frozen=True)
class GrammarObligation:
    """A topology this grammar requires to be **visible** (053 sec.3).

    Statement, not a coordinate. `nets` is never empty and its order is
    meaningful where the kind has one: a `direct-wire` obligation lists its
    chain in electrical order, from the power end to the ground end.
    """

    kind: str
    nets: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in OBLIGATION_KINDS:
            raise GrammarError(
                f"unknown obligation kind {self.kind!r}; this build knows "
                f"{list(OBLIGATION_KINDS)}"
            )
        if not self.nets:
            raise GrammarError(
                f"obligation {self.kind!r} names no net — an obligation is "
                "about a net, and one that names none cannot be checked"
            )
        if not self.reason:
            raise GrammarError(f"obligation {self.kind!r} has no reason")

    def to_jsonable(self) -> dict[str, object]:
        return {"kind": self.kind, "nets": list(self.nets),
                "reason": self.reason}


@dataclass(frozen=True)
class GrammarFailure:
    """Why a grammar could not bind, in one of 053 sec.4's four categories.

    `detail` names the concrete conflict (which parts, which nets, which
    missing fact); `action` — when there is a known one — says what to change:
    expand the region, relax a lock, pick a symbol with a verified pin mapping,
    or where to write the missing fact. A failure without a detail would be the
    "invalid spec" answer 053 sec.4 exists to avoid.
    """

    category: str
    detail: str
    action: str = ""
    subject: str = ""

    def __post_init__(self) -> None:
        if self.category not in FAILURE_CATEGORIES:
            raise GrammarError(
                f"unknown failure category {self.category!r}; 053 sec.4 fixes "
                f"them as {list(FAILURE_CATEGORIES)}"
            )
        if not self.detail:
            raise GrammarError(
                f"failure {self.category!r} has no detail — a category alone "
                "tells the reader nothing to fix"
            )

    def to_jsonable(self) -> dict[str, object]:
        out: dict[str, object] = {"category": self.category,
                                  "detail": self.detail}
        if self.subject:
            out["subject"] = self.subject
        if self.action:
            out["action"] = self.action
        return out


@dataclass(frozen=True)
class GrammarResult:
    """What a grammar bound, and what it requires to stay readable.

    `ok` and `failures` are two halves of one fact, so they cannot disagree:
    claiming success while carrying failures (or failing with no stated reason)
    raises. The tuples keep the grammar's own reading order — the chain order —
    which is deterministic by construction (every iteration in this package is
    over sorted keys).
    """

    ok: bool
    bindings: tuple[RoleBinding, ...] = ()
    constraints: tuple[RelativeConstraint, ...] = ()
    obligations: tuple[GrammarObligation, ...] = ()
    failures: tuple[GrammarFailure, ...] = ()

    def __post_init__(self) -> None:
        if self.ok and self.failures:
            raise GrammarError(
                "a result cannot be ok and carry failures: "
                + "; ".join(item.detail for item in self.failures)
            )
        if not self.ok and not self.failures:
            raise GrammarError(
                "a failed result states no failure — 053 sec.4 requires the "
                "category, the reason and (where known) the action"
            )

    # ------------------------------------------------------------- reading

    def bindings_for(self, role: str) -> tuple[RoleBinding, ...]:
        """Every binding of this role, in chain order."""
        return tuple(item for item in self.bindings if item.role == role)

    def net_of(self, role: str) -> str:
        """The net bound to a net role, or ``""`` when nothing bound it."""
        found = self.bindings_for(role)
        if not found or not is_net_role(role):
            return ""
        return found[0].part_id

    def parts_of(self, role: str) -> tuple[str, ...]:
        """Every part id bound to this role, in chain order."""
        return tuple(item.part_id for item in self.bindings_for(role))

    def obligation_for(self, kind: str, net: str = "") -> GrammarObligation | None:
        """The first obligation of this kind, optionally on a given net."""
        for item in self.obligations:
            if item.kind != kind:
                continue
            if not net or net in item.nets:
                return item
        return None

    def to_jsonable(self) -> dict[str, object]:
        """The whole result, as the compiler and a report may read it."""
        return {
            "ok": self.ok,
            "bindings": [item.to_jsonable() for item in self.bindings],
            "constraints": [item.to_jsonable() for item in self.constraints],
            "obligations": [item.to_jsonable() for item in self.obligations],
            "failures": [item.to_jsonable() for item in self.failures],
        }


def bound_result(
    bindings: Sequence[RoleBinding],
    constraints: Sequence[RelativeConstraint] = (),
    obligations: Sequence[GrammarObligation] = (),
) -> GrammarResult:
    """A successful result. Order is the caller's reading order, kept as given."""
    return GrammarResult(
        ok=True,
        bindings=tuple(bindings),
        constraints=tuple(constraints),
        obligations=tuple(obligations),
    )


def refused_result(failures: Sequence[GrammarFailure]) -> GrammarResult:
    """A refused result: nothing bound, at least one stated reason."""
    return GrammarResult(ok=False, failures=tuple(failures))


@runtime_checkable
class DrawingGrammar(Protocol):
    """One drawing grammar: a name, and a bind over the two specs.

    Symbol profiles are a **construction** input, not a `bind` parameter: a
    grammar's judgment is a function of (circuit, presentation, library), and
    the library does not change between two calls on the same pair. Keeping them
    off the call keeps `bind` the two-document signature 053 sec.3 fixes, and
    keeps the compiler's own use of profiles (geometry) separate from the
    grammar's (pin roles).
    """

    name: str

    def bind(
        self, circuit: CircuitSpec, presentation: PresentationSpec
    ) -> GrammarResult:
        """Bind this grammar's roles, or refuse with 053 sec.4's categories."""
        ...


# ------------------------------------------------------- provenance helpers


def weakest_provenance(*values: str) -> str:
    """The weakest of these provenances, as the token an evidence string prints.

    Weakest-first rather than best-of, because a binding is only as good as its
    weakest fact (052 sec.4), and an unstated fact is weaker than all three.
    With no facts at all, the answer is :data:`PROVENANCE_UNSTATED`: nothing was
    stated, which is not the same claim as "verified".
    """
    if not values:
        return PROVENANCE_UNSTATED
    worst = PROVENANCE_VERIFIED
    for value in values:
        rank = _PROVENANCE_RANK.get(value or PROVENANCE_UNSTATED, -1)
        if rank < _PROVENANCE_RANK[worst]:
            worst = value or PROVENANCE_UNSTATED
    return worst


def evidence(*clauses: str) -> str:
    """Join the clauses of one evidence string; empty clauses are dropped."""
    return "; ".join(clause for clause in clauses if clause)


def part_provenance(part: SpecPart) -> str:
    """The provenance of a part, `unstated` when the spec said nothing."""
    return part.provenance or PROVENANCE_UNSTATED


def net_provenance(circuit: CircuitSpec, net_id: str, member: str = "") -> str:
    """The provenance of a net — or of one ``<partId>.<pin>`` member of it.

    A member's own provenance wins where the spec recorded one that differs
    (``SpecNet.member_provenance``); otherwise the net's.
    """
    net = circuit.net(net_id)
    if net is None:
        return PROVENANCE_UNSTATED
    if member and member in net.member_provenance:
        value = net.member_provenance[member]
    else:
        value = net.provenance
    return value or PROVENANCE_UNSTATED


def part_clause(circuit: CircuitSpec, part_id: str) -> str:
    """``part R1: 1→VIN@verified_recipe, 2→TAP@ai_asserted (part provenance=…)``.

    The clause form every binding's evidence uses for a part. A part whose
    connections the spec never states says exactly that instead of showing an
    empty list, because "no connection given" is not the same fact as "no pins"
    (053 sec.2).
    """
    part = circuit.part(part_id)
    pins = pins_of_part(circuit, part_id)
    if not pins:
        return (f"part {part_id}: no connection stated in the CircuitSpec "
                f"(part provenance={part_provenance(part) if part else PROVENANCE_UNSTATED})")
    items = ", ".join(
        f"{pin}→{pins[pin]}@{net_provenance(circuit, pins[pin], f'{part_id}.{pin}')}"
        for pin in sorted(pins)
    )
    provenance = part_provenance(part) if part else PROVENANCE_UNSTATED
    return f"part {part_id}: {items} (part provenance={provenance})"


def net_clause(net: SpecNet) -> str:
    """``net VIN: class=power provenance=verified_recipe``."""
    return (f"net {net.id}: class={net.cls} "
            f"provenance={net.provenance or PROVENANCE_UNSTATED}")


# -------------------------------------------------------- topology helpers


def pins_of_part(circuit: CircuitSpec, part_id: str) -> dict[str, str]:
    """``pin token → net id`` for every pin of this part the spec mentions.

    The spec refuses a pin on two nets on the way in (`CircuitSpec.from_dict`),
    so this mapping is unambiguous. A pin the spec never mentions is absent —
    which is "unmentioned", not NC (053 sec.2).
    """
    out: dict[str, str] = {}
    for net in circuit.nets:
        for member in net.members:
            owner, _, pin = member.partition(".")
            if owner == part_id and pin:
                out[pin] = net.id
    return out


def connected_net_sets(circuit: CircuitSpec) -> dict[str, tuple[str, ...]]:
    """``part id → its distinct nets`` (sorted), for every part with a connection.

    Used for the diagnostics of a failed bind: naming what *is* connected is
    what turns "no chain found" into a message a reader can act on.
    """
    out: dict[str, tuple[str, ...]] = {}
    for part in circuit.parts:
        nets = sorted(set(pins_of_part(circuit, part.id).values()))
        if nets:
            out[part.id] = tuple(nets)
    return out


def two_terminal_parts(circuit: CircuitSpec) -> dict[str, tuple[str, str]]:
    """``part id → (net, net)`` for the parts that are two-terminal elements.

    Two-terminal is read from the spec: exactly two mentioned pins, on two
    **different** nets. A part whose two pins sit on one net is a short, not a
    series arm (053 sec.5 scenario 11), and it is excluded here on purpose so
    that a short cannot be bound as an arm of anything.
    """
    out: dict[str, tuple[str, str]] = {}
    for part in circuit.parts:
        pins = pins_of_part(circuit, part.id)
        nets = sorted(set(pins.values()))
        if len(pins) == 2 and len(nets) == 2:
            out[part.id] = (nets[0], nets[1])
    return out


def nets_of_class(circuit: CircuitSpec, cls: str) -> tuple[str, ...]:
    """Every net of this class, id-sorted (the stable tie-break order)."""
    return tuple(sorted(net.id for net in circuit.nets if net.cls == cls))


def series_paths(
    edges: Mapping[str, tuple[str, str]],
    start: str,
    goal: str,
    *,
    max_arms: int = MAX_CHAIN_ARMS,
    max_paths: int = MAX_CHAINS,
) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Every ``start → goal`` chain through two-terminal parts, bounded.

    Returns ``(part ids, net ids)`` pairs with ``nets[0] == start``,
    ``nets[-1] == goal`` and ``len(parts) == len(nets) - 1``: the parts are the
    arms in electrical order and the middle nets are the taps between them.

    Two properties are deliberate. It is a **multigraph** — two parts between
    the same pair of nets are two edges, so two arms wired in parallel are
    visible as two chains instead of one. And it is **bounded** (`max_arms`,
    `max_paths`) and deterministic (adjacency sorted by ``(net, part)``), which
    is what lets a caller say "not found inside the budget" rather than "there
    is no chain".
    """
    graph: dict[str, list[tuple[str, str]]] = {}
    for part_id in sorted(edges):
        first, second = edges[part_id]
        graph.setdefault(first, []).append((second, part_id))
        graph.setdefault(second, []).append((first, part_id))
    for key in graph:
        graph[key].sort()

    found: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def walk(
        net: str,
        parts: tuple[str, ...],
        nets: tuple[str, ...],
        visited: frozenset[str],
    ) -> None:
        if len(found) >= max_paths or len(parts) >= max_arms:
            return
        for neighbour, part_id in graph.get(net, ()):
            if part_id in parts:
                continue
            if neighbour == goal:
                found.append((parts + (part_id,), nets + (neighbour,)))
                continue
            if neighbour in visited or neighbour not in graph:
                continue
            walk(
                neighbour,
                parts + (part_id,),
                nets + (neighbour,),
                visited | {neighbour},
            )

    if start in graph and start != goal:
        walk(start, (), (start,), frozenset({start}))
    found.sort(key=lambda item: (len(item[0]), item[0], item[1]))
    return found


# ------------------------------------------------------------ module scoping


def modules_of_part(presentation: PresentationSpec, part_id: str) -> tuple[str, ...]:
    """Every declared module listing this part, in document order.

    A part in two modules is a contradiction in the presentation document, not
    something this layer hides: it is reported as written, and callers that need
    "the" module use :func:`module_of_part`, which says when there is no single
    answer.
    """
    return tuple(
        module.id for module in presentation.modules if part_id in module.parts
    )


def module_of_part(presentation: PresentationSpec, part_id: str) -> str:
    """The single declared module listing this part, or ``""``.

    Empty covers both "no module lists it" and "several do" — the two cases
    differ in their message, so a caller that has to explain uses
    :func:`modules_of_part`.
    """
    found = modules_of_part(presentation, part_id)
    return found[0] if len(found) == 1 else ""


def declares_modules(presentation: PresentationSpec) -> bool:
    """Does the presentation group parts into modules at all?"""
    return any(module.parts for module in presentation.modules)


def shared_module(presentation: PresentationSpec, part_ids: Sequence[str]) -> str:
    """The one module every part is in, or ``""`` (none, or several answers).

    The scoping rule of the three grammars: where a presentation has declared
    modules, a grammar instance lives inside one of them, and a chain or a
    branch that would cross a boundary is either refused or left unbound
    (052 sec.5: a branch must not read as crossing into another module).
    """
    if not part_ids:
        return ""
    shared: set[str] | None = None
    for part_id in part_ids:
        here = set(modules_of_part(presentation, part_id))
        shared = here if shared is None else (shared & here)
    if not shared:
        return ""
    return sorted(shared)[0]


# ----------------------------------------------------------- symbol profiles


def profile_for(
    part: SpecPart, profiles: Mapping[str, SymbolProfile] | None
) -> SymbolProfile | None:
    """The profile of this part's library symbol, or ``None``.

    Looked up by ``symbolRef`` — the same key a LayoutPlan records — because a
    part's id is a circuit name, not a library name.
    """
    if not profiles or not part.symbol_ref:
        return None
    return profiles.get(part.symbol_ref)


def profile_pin_for(part_pins: Mapping[str, str], pin: SymbolPin) -> tuple[str, str]:
    """``(spec pin token, how it matched)`` for a profile pin, or ``("", "")``.

    The spec writes ``<partId>.<pin>`` with the token the symbol uses. Number
    first, then the pin's own name — and which one matched is returned, because
    it goes into the evidence string: a binding that matched by name is not the
    same claim as one that matched by number.
    """
    if pin.number and pin.number in part_pins:
        return (pin.number, "number")
    if pin.name and pin.name in part_pins:
        return (pin.name, "name")
    return ("", "")


def role_pins(profile: SymbolProfile) -> dict[str, SymbolPin]:
    """``electrical role → its pin`` for one profile, id-sorted and stable.

    The role is the profile's own ``electricalRole`` where it has one; where it
    does not, the pin's *name* is mapped through
    :data:`~boardwise.core.symbolprofile.ROLE_BY_PIN_NAME` — 053 sec.3 asks for
    exactly these two sources ("SymbolProfile electricalRole 或引脚名
    VIN/VOUT/GND"). Where a role has several pins (two GND pins is ordinary),
    the id-sorted first wins and the caller's evidence says so.
    """
    out: dict[str, SymbolPin] = {}
    for pin in sorted(profile.pins, key=lambda item: (item.number, item.name)):
        role = pin.electrical_role or ROLE_BY_PIN_NAME.get(pin.name.strip().upper(), "")
        if role and role not in out:
            out[role] = pin
    return out


# --------------------------------------------------------------- next batch
#
# TODO(053 batch 2): the readability checker consumes a binding plus the plan,
# never the compiler's internals (053 sec.2's "独立" requirement). Its entry
# point is fixed here so this batch needs no import of
# `boardwise.engines.readability` (the other batch owns that file):
#
#     def check(binding: GrammarResult, layoutPlan: LayoutPlan,
#               profiles: Mapping[str, SymbolProfile]) -> list[Finding]: ...
#
# What it reads from this result: `constraints` (does the plan keep the
# relations), `obligations` (are the required topologies visible), and the
# `failures` of a refused bind (a refused grammar is not a passed check).
