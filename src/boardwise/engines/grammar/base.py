"""The vocabulary the drawing grammars share (053 sec.3, 052 sec.5).

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

**A role is a set of pins, not a pin** (055 G1). The measured AMS1117 symbol
carries VOUT twice — once on each side of the body — and a grammar that reads
only the id-sorted first pin of a role reports a part whose duplicate is wired as
"the spec states no connection". So the rule this module states, once, is:
**any** pin of a role being a net member connects that role; a role's pin written
into ``nc[]`` is *explicitly handled* (recorded, never a "missing fact") and never
how the role gets its net; and two pins of one role on two different nets is a
contradiction, refused naming both nets because the pins are one node inside the
symbol. :func:`role_pins_connected` is that rule; :func:`role_pins` is only a
reading of "a" pin and must not be used to answer "is this role connected".

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
``gnd-outlet``   **added by 088b**: this net carries **exactly one** outlet
                 symbol of its own — the mark that says where the group's ground
                 rail terminates — placed at the rail's far end (背向 entry 那端)
                 and standing upright. The obligation names the net; the
                 compiler reads *which* end from the presentation's input side,
                 so `sidePreferences.input` mirrors the symbol with the drawing
                 (088b §一, 岳 2026-10-02: 「底轨要有一个、且只要一个出处符号」).
                 Distinct from `uniform-gnd`: that one forbids *mixing* styles,
                 this one requires the net to be *stated* by a symbol rather
                 than left as a bare conductor.
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
    PROVENANCE_USER_STATED,
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
    "GND_OUTLET",
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
    "RoleConnection",
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
    "nc_pins_of",
    "part_clause",
    "pins_of_part",
    "profile_for",
    "profile_pin_for",
    "refused_result",
    "role_pins",
    "role_pins_connected",
    "role_pins_of",
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
GND_OUTLET = "gnd-outlet"

OBLIGATION_KINDS: tuple[str, ...] = (
    DIRECT_WIRE,
    VISIBLE_TAP,
    OWNED_BRANCH,
    UNIFORM_GND,
    GND_OUTLET,
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
#: voltage-divider, rc-lowpass and ldo (053 sec.3), and `rail` (088) is the
#: supply bus of `power-entry`. A net role is what makes
#: :meth:`RoleBinding.to_jsonable` report ``target: "net"`` for it, and what the
#: compiler's slot pass skips when it walks bindings looking for parts.
#:
#: **113 adds the flyback's eleven net roles.** They are in this table rather
#: than in the module's own vocabulary because the table is what the compiler
#: reads (`drawcompiler` skips a net role when it walks bindings looking for
#: parts, in three places), and a net role the compiler did not recognise
#: would be laid out as a part — the bug 088's `entry` and 098's `bridge` were
#: each about, in the other direction. The set is a **membership table, not a
#: new kind**: it says which role names hold a net id, nothing more, so
#: extending it cannot change the meaning of any existing role, and every one
#: of the five existing grammars' roles is untouched. The flyback's net roles
#: are the ones its topology names: the bus it is fed from, the switch node,
#: the source, the two ground families, the auxiliary node and its rail, the
#: output, the sense tap and the clamp node.
NET_ROLES: tuple[str, ...] = (
    "in", "out", "gnd", "tap", "rail",
    # flyback (113)
    "bus", "switch-node", "secondary-node", "src", "pgnd", "aux", "vcc",
    "vout", "sec-gnd", "fb-sense", "clamp",
)

#: What :attr:`RoleBinding.part_id` is holding — the same field carries either,
#: because a CircuitSpec names parts and nets by the same kind of stable logical
#: id (053 sec.2).
ROLE_PART = "part"
ROLE_NET = "net"

#: The token used when a fact said nothing. Absence is not confirmation (052
#: sec.4), so it is a value of its own rather than an empty string nobody reads.
PROVENANCE_UNSTATED = "unstated"

#: The same ordering as `core.circuitspec._PROVENANCE_RANK`, which is the one
#: table that says what the order is (its comment says so, and this copy was
#: missing a key until 095 A4). `user_stated` is the DesignIntent channel's
#: spelling of the engineer tier (090 A1), and the grammar had no entry for it
#: because no fact reaching a grammar could spell it: the tokens a `CircuitSpec`
#: accepts are the three of `PROVENANCE_KINDS`. A contract is the first document
#: that can, so a binding whose claim is `user_stated` ranked it as *unstated* —
#: which made `weakest_provenance` raise `KeyError` one comparison later.
_PROVENANCE_RANK = {
    PROVENANCE_VERIFIED: 2,
    PROVENANCE_ENGINEER: 1,
    PROVENANCE_USER_STATED: 1,
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
        # Every name has to be a real net, not just "a non-empty tuple": a
        # `direct-wire` written as `('FB_SENSE', '')` passed this constructor
        # and then walked on — the compiler ranked the empty name into the
        # chain and dropped the real cathode net out of it (143 H2). The
        # constructor is the last place where the emptiness is unambiguously a
        # bug rather than a modelling choice, so it is caught here.
        empty = [index for index, net_id in enumerate(self.nets) if not net_id]
        if empty:
            raise GrammarError(
                f"obligation {self.kind!r} names an empty net at index "
                f"{empty[0]} — every entry of `nets` is a net id, and an empty "
                "one is a name no circuit can declare"
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
    """One drawing grammar: a name, and a bind over the two specs and a contract.

    Symbol profiles are a **construction** input, not a `bind` parameter: a
    grammar's judgment is a function of (circuit, presentation, library), and
    the library does not change between two calls on the same pair. Keeping them
    off the call keeps `bind` the two-document signature 053 sec.3 fixes, and
    keeps the compiler's own use of profiles (geometry) separate from the
    grammar's (pin roles).

    `intent` (095 A4) is the one **document** input added to that signature, and
    it is added because it is a document rather than a library: the fourth
    contract says what the board is *for*, and a promise about what a drawing must
    make visible may be stated there instead of in the presentation. It is
    keyword-only and ``None`` by default — a bind handed no contract behaves
    exactly as it did before 095 — and every grammar accepts it whether or not it
    reads one, so one dispatcher call serves all five (a grammar that reads none
    of it says so where it takes it, the same discipline as an unread profile).
    """

    name: str

    def bind(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        *,
        intent: object | None = None,
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


#: How a role's pins were resolved against the CircuitSpec (055 G1).
#: ``connected`` is every pin of the role the spec puts on a net, ``nets`` what
#: those pins are on, ``nc`` the role's pins the spec lists in ``nc[]``. The two
#: rules of 055 G1 are expressed by these three fields and nowhere else:
#: **any** same-role pin on a net connects the role, and an explicit NC is
#: "handled" (recorded, never a missing fact) without connecting anything.
@dataclass(frozen=True)
class RoleConnection:
    """One electrical role of one part, as the CircuitSpec connects it."""

    role: str
    #: ``(spec pin token, how it matched)`` for every pin of this role the spec
    #: puts on a net, in the profile's id order. ``how`` is
    #: :func:`profile_pin_for`'s answer (``"number"`` / ``"name"``).
    connected: tuple[tuple[str, str], ...] = ()
    #: The nets those pins sit on — distinct, ascending.
    nets: tuple[str, ...] = ()
    #: The role's pins the spec lists in ``nc[]`` (spec tokens), ascending.
    nc: tuple[str, ...] = ()
    #: Every pin of this role the profile carries (spec tokens), in id order.
    #: Kept so a refusal can name all of them — "connect one of these" is the
    #: actionable form of "this role has no net".
    tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.role:
            raise GrammarError("RoleConnection.role is empty")

    @property
    def net(self) -> str:
        """The one net this role is on, or ``""`` when it is not on exactly one.

        Empty covers three different facts — nothing connected, several pins on
        several nets, and several pins agreeing on one net is *not* one of them
        (that answer is the net). A caller that has to explain reads
        :attr:`connected` / :attr:`nets` / :attr:`nc` rather than this.
        """
        return self.nets[0] if len(self.nets) == 1 else ""

    @property
    def token(self) -> str:
        """The spec token of the pin this role resolved to, or ``""``."""
        return self.connected[0][0] if self.connected else ""

    @property
    def how(self) -> str:
        """How that token matched (``"number"`` / ``"name"``), or ``""``."""
        return self.connected[0][1] if self.connected else ""

    @property
    def all_nc(self) -> bool:
        """Is *every* pin of this role an explicit no-connect?

        The one shape where NC is not "handled, keep going": a role with no pin
        anywhere cannot carry its node, and the failure has to name the pins
        rather than leave the reader with a silent half-bound core.
        """
        return bool(self.tokens) and len(self.nc) == len(self.tokens)

    def note(self) -> str:
        """One evidence clause for a role that has several pins, or ``""``.

        A duplicated pin is a fact the reader of a binding has to see: which of
        the role's pins the binding used, and that the other one is an explicit
        NC rather than an omission (055 G1's motivating symbol).
        """
        if len(self.tokens) < 2:
            return ""
        parts: list[str] = []
        if self.connected:
            if len(self.connected) > 1:
                pins = ", ".join(token for token, _how in self.connected)
                parts.append(
                    f"pins {pins} are all on net {self.nets[0]} — one role, one node"
                )
            else:
                parts.append(
                    f"pin {self.token} carries the net {self.nets[0]}"
                )
        if self.nc:
            parts.append(
                "pin(s) " + ", ".join(self.nc) + " are listed in nc[] "
                "(an explicit no-connect, not a missing fact)"
            )
        rest = [
            token for token in self.tokens
            if token not in self.nc and token not in {item[0] for item in self.connected}
        ]
        if rest:
            parts.append("pin(s) " + ", ".join(rest) + " are not mentioned at all")
        return f"{self.role}: " + "; ".join(parts)


def role_pins_connected(
    circuit: CircuitSpec, part_id: str, profile: SymbolProfile, role: str
) -> RoleConnection:
    """Resolve **one role of one part** against the CircuitSpec (055 G1).

    The rule, and the reason it is not "the first pin of the role":

    * every pin the profile gives this role is considered, and **any** of them
      being a net member means the role is connected — a real symbol duplicates
      a supply pin (the measured AMS1117 has VOUT on both sides of the body), and
      a circuit may connect either one of the two;
    * a pin listed in ``nc[]`` is **explicitly handled**: it is recorded in
      :attr:`RoleConnection.nc` and never reported as a missing fact, and it is
      never how the role gets its net;
    * two of the role's pins on *two different* nets is not a choice to be made
      here — it is a contradiction (the pins are the same node inside the
      symbol, so the drawing would short those nets). The caller refuses it
      naming both nets; ``nets`` therefore has more than one entry.

    A spec pin token is matched by number first, then by name, through
    :func:`profile_pin_for` — the same ruler the callers already used.
    """
    pins_of_role = role_pins_of(profile).get(role, ())
    part_pins = pins_of_part(circuit, part_id)
    nc = nc_pins_of(circuit, part_id)
    connected: list[tuple[str, str]] = []
    tokens: list[str] = []
    nc_tokens: list[str] = []
    for pin in pins_of_role:
        token, how = profile_pin_for(part_pins, pin)
        if token:
            tokens.append(token)
            connected.append((token, how))
            continue
        # Not on a net. Which spelling the spec used for it is what a reader has
        # to write in nc[] or in a net member, so try the pin's own two names
        # against nc[] and report the one that hits.
        tokens.append(pin.number or pin.name)
        if pin.number and pin.number in nc:
            nc_tokens.append(pin.number)
        elif pin.name and pin.name in nc:
            nc_tokens.append(pin.name)
    return RoleConnection(
        role=role,
        connected=tuple(connected),
        nets=tuple(sorted({part_pins[token] for token, _how in connected})),
        nc=tuple(sorted(nc_tokens)),
        tokens=tuple(tokens),
    )



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

    The scoping rule of the grammars: where a presentation has declared
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


def role_pins_of(profile: SymbolProfile) -> dict[str, tuple[SymbolPin, ...]]:
    """``electrical role → **every** pin of it``, id-sorted and stable.

    The role is the profile's own ``electricalRole`` where it has one; where it
    does not, the pin's *name* is mapped through
    :data:`~boardwise.core.symbolprofile.ROLE_BY_PIN_NAME` — 053 sec.3 asks for
    exactly these two sources ("SymbolProfile electricalRole 或引脚名
    VIN/VOUT/GND").

    **A role is not one pin** (055 G1). Two GND pins are ordinary, and the real
    AMS1117 symbol this repo measured carries a *duplicated* VOUT on the other
    side of the body; a judgment that reads only the id-sorted first pin then
    reports a connected part as "no connection". So this returns them all, in id
    order, and the resolution rule lives in :func:`role_pins_connected`.
    """
    out: dict[str, list[SymbolPin]] = {}
    for pin in sorted(profile.pins, key=lambda item: (item.number, item.name)):
        role = pin.electrical_role or ROLE_BY_PIN_NAME.get(pin.name.strip().upper(), "")
        if role:
            out.setdefault(role, []).append(pin)
    return {role: tuple(pins) for role, pins in out.items()}


def role_pins(profile: SymbolProfile) -> dict[str, SymbolPin]:
    """``electrical role → its id-sorted first pin`` — a *reading*, not the ruler.

    For callers that only need to name *a* pin of a role (an evidence string, a
    report line). It is deliberately not how "is this role connected" is
    answered: that question is about every pin of the role and belongs to
    :func:`role_pins_connected` (055 G1 — the duplicated supply pin).
    """
    return {
        role: pins[0] for role, pins in role_pins_of(profile).items() if pins
    }


def nc_pins_of(circuit: CircuitSpec, part_id: str) -> frozenset[str]:
    """The pin **tokens** of this part the spec lists in ``nc[]``.

    Explicit no-connects, by the CircuitSpec's own rule (053 sec.2): "没给连接"
    and "NC" are different facts, and only the second one is a decision. Read
    here rather than in each grammar because the spelling is the spec's
    (``<partId>.<pin>``, already validated on the way in).
    """
    prefix = f"{part_id}."
    return frozenset(
        item.pin[len(prefix):] for item in circuit.nc if item.pin.startswith(prefix)
    )


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
