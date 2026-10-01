"""power-entry: 088's fourth grammar — the power inlet as its own drawing.

The drawing it promises, in 岳's own words over the 24 V input screenshot:

    | power-entry | entry / shunt / rail / gnd |
    顶轨 +V、底轨 GND 各一条**实体横线**；entry（连接器）终结轨的输入端，三条两脚支路
    在两轨之间竖放、从顶轨下垂到底轨；位号/容值文字在各支路左侧不压线 |
    支路数弹性（1 TVS + N 体电容同构）、entry 可在左端或在右端 |

**The binding judgment.** Only the first two steps are structural; the third one
is a fact this grammar cannot derive, and saying so is the point:

1. `rail` is a net whose `class` is `power` and `gnd` a net whose `class` is
   `gnd`. Missing either class is a `facts-missing` refusal naming the class to
   write — the same wording `rc-lowpass` uses, for the same reason: a net that
   states nothing is class `signal`, which is neither.
2. **The entry cannot be found topologically.** Every part across
   `rail ↔ gnd` is isomorphic on the drawing: a connector, a TVS diode and an
   electrolytic are three pins between the same two nets, and no reading of the
   partition says which of them is the inlet. So the fact comes from the
   document: the rail's `openInterfaces` entry whose `direction` is `input` or
   `source` carries `part` — "this open end is realised by CN1" — and that part
   is the `entry` (088 §一.2, `SpecOpenInterface.part`).
   * rail states no such interface, or states one with an empty `part` →
     `facts-missing`, naming the field to write;
   * the named part does not exist, or is not a two-terminal part across this
     rail and this ground → `circuit-invalid`, naming the part and what it is
     actually connected to.
3. `shunt` is **every other** two-terminal part from the rail to that ground
   (the TVS and the bulk capacitors are the same shape, and nothing here reads a
   designator prefix, a value or a package name — 052 §5). Where the
   presentation declares modules, the shunts are collected from the entry's own
   module, as `rc-lowpass` and `ldo` do: a bulk capacitor belonging to the next
   module is that module's business.

**What this grammar does not promise.** The order the branches are drawn in is
not part of the promise. Nothing in the electrical fact fixes it — three parts
across the same two nets are three interchangeable edges of a multigraph, and
053 §6 forbids a scenario-specific constant in a grammar table. The compiler
lays them out by part id; 岳's hand drawing puts the TVS nearest the inlet, and
that is a reading of *his* sheet, not a clause of the grammar (088 §五.3).

**The constraints.** The rails are rows, so:

* `same-row` between the `entry` and each `shunt`: every part's rail-side pin
  lands on the same horizontal line as the entry's. The kind alone cannot say
  *which* end, so the reason names the pin — the same discipline `rc-lowpass`
  uses for the RC trunk. One thing this grammar measures and does **not** paper
  over: the entry and a shunt share **both** rails, so the compiler's
  `_relation_points` samples whichever of the two sorts first by net id and no
  constraint can name the net it means (088 §二's "实测不够再加"). Measured on
  the landed plan: with the inlet spanning the two rows, **both** rows satisfy it
  whichever one is sampled (the inlet's rail pin and its ground pin are each on a
  row with every branch's), so the sampled row does not decide the drawing.
* `left-of` / `right-of`, **entry as subject, each shunt as object**: the entry
  terminates the row at the input end and every branch is on the far side of
  it. The kind's own definition ("subject on the power side when that side is
  the left one") carries this without inventing a coordinate, and which of the
  two it is comes from `sidePreferences.input` — so `input: right` is the same
  binding as `input: left` with the drawing turned round. **This is why 088
  §二's candidate new kind `at-end` was not needed**: the existing pair states
  it, and adding a kind would have changed the vocabulary every other grammar
  is measured against.
* `near` between each `shunt` and the `entry`: the branch is this rail's local
  topology and does not read as crossing into another module (052 §5).

**The obligations.** Two `direct-wire` obligations, **one per rail** (`(rail,)`
and `(gnd,)`), are the load-bearing ones: **the rails are solid conductors**, not
a string of flags that happen to share a name. That is the whole difference from
the 069 page-level "a rail is a bus at any fan-out" style, and it is why the
compiler's expression policy matters — a `direct-wire` net is answered `wire`
*before* its class is even looked at (`drawcompiler._expression_style`), so the
promise wins over the bus rule. Measured on the landed plan: both rails come out
as wires (`plan.segments`), and 069 §7's supplied rail flag is still there beside
them — the flag is on, the line is whole (088 §二's "端头旗照常出，轨线本体不许被
拆成旗点" holds).

**Why one obligation per rail and not one `(rail, gnd)` chain.** The compiler
reads a `direct-wire` obligation as *electrical order*: `_chain_net_ranks` gives
each net it names a rank, and a chain part whose pins are on two ranked nets must
lie **along** the chain axis (`drawcompiler._pose_satisfies` →
`_on_one_line(tips, ctx.progress)`). Naming both rails in one tuple therefore
ranked them both and forced the inlet to lie flat along the row with its ground
pin on the *rail* row — the drawing then reached the return row through a riser
wire instead of terminating it. Two single-net obligations rank each rail at 0
(a fresh obligation starts its own numbering), so the inlet has no chain-pin pair
to satisfy and is posed by its own symbol: **pins across the two rows**, every
branch hanging between them, both rails solid from the inlet to the last branch.
That is 岳's sheet, and it costs nothing outside this grammar — the change is in
what the obligation *names*, not in how the compiler reads one.

`uniform-gnd` says this module's ground is expressed one way throughout, and
`owned-branch` says each branch reads as hanging off the rail it belongs to.
"""

from __future__ import annotations

from typing import Mapping

from ...core.circuitspec import CircuitSpec, SpecOpenInterface
from ...core.presentationspec import SIDES, PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_ROW,
    UNIFORM_GND,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    bound_result,
    declares_modules,
    evidence,
    modules_of_part,
    net_clause,
    net_provenance,
    nets_of_class,
    part_clause,
    part_provenance,
    pins_of_part,
    refused_result,
    two_terminal_parts,
    weakest_provenance,
)

__all__ = [
    "GRAMMAR",
    "NAME",
    "ROLES",
    "PowerEntryGrammar",
    "grammar",
]

NAME = "power-entry"

#: The role table, verbatim from 088 §一.
ROLES: tuple[str, ...] = ("entry", "shunt", "rail", "gnd")

#: The `openInterfaces[].direction` values that mean "the supply enters here".
#: `load` / `output` / `feedback` do not: they are the other end of the same
#: module, and a part named there is not what feeds the rail.
ENTRY_DIRECTIONS: tuple[str, ...] = ("input", "source")


class PowerEntryGrammar:
    """088's power-entry grammar. Structural; the entry comes from a stated fact."""

    name = NAME

    def __init__(self, profiles: Mapping[str, SymbolProfile] | None = None) -> None:
        # Nothing here reads a profile: the roles are read from the partition and
        # from `openInterfaces[].part`. Taken for a uniform construction across the
        # four grammars, the way `rc-lowpass` takes them.
        self.profiles: dict[str, SymbolProfile] = dict(profiles or {})

    # -------------------------------------------------------------- binding

    def bind(
        self, circuit: CircuitSpec, presentation: PresentationSpec
    ) -> GrammarResult:
        power = nets_of_class(circuit, "power")
        ground = nets_of_class(circuit, "gnd")
        missing = _missing_class_failures(power, ground)
        if missing:
            return refused_result(missing)

        rail = _rail_of(circuit, power)
        gnd = _ground_of(circuit, rail, ground)
        named = _entry_claims(circuit, rail)
        if not named:
            return refused_result([_no_entry_failure(circuit, rail)])
        problem = _entry_problem(circuit, rail, gnd, named)
        if problem is not None:
            return refused_result([problem])

        entry = named[0].part
        shunts = _shunts(circuit, presentation, rail, gnd, entry)
        return self._result(circuit, presentation, rail, gnd, entry, shunts, named)

    # ------------------------------------------------------------- internals

    def _result(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        rail: str,
        gnd: str,
        entry: str,
        shunts: tuple[str, ...],
        named: list[SpecOpenInterface],
    ) -> GrammarResult:
        in_side = presentation.side_for("input") or "left"
        if in_side not in SIDES:
            in_side = "left"
        side_kind = RIGHT_OF if in_side == "right" else LEFT_OF
        rail_pin = _pin_on(circuit, entry, rail)
        gnd_pin = _pin_on(circuit, entry, gnd)
        prov = weakest_provenance(
            net_provenance(circuit, rail),
            net_provenance(circuit, gnd),
            part_provenance(circuit.part(entry)),
            *(part_provenance(circuit.part(part_id)) for part_id in shunts),
        )
        shape = _describe(rail, gnd, entry, shunts)
        rivals = _claim_note(named)

        bindings: list[RoleBinding] = [
            RoleBinding(
                role="entry",
                part_id=entry,
                evidence=evidence(
                    "role=entry: the part the rail's own openInterfaces entry "
                    f"names in openInterfaces[].part (direction="
                    f"{named[0].direction or 'input'}) — the one fact this "
                    "grammar cannot derive, because a connector and a parallel "
                    "branch are the same shape between the same two nets",
                    part_clause(circuit, entry),
                    f"pins on this module's two rails: {rail_pin or '?'}→{rail}, "
                    f"{gnd_pin or '?'}→{gnd}",
                    f"inlet chosen: {shape}",
                    f"provenance={prov}",
                    rivals,
                ),
            ),
            RoleBinding(
                role="rail",
                part_id=rail,
                evidence=evidence(
                    "role=rail: the net of class 'power' this module's branches "
                    "and its inlet share — drawn as one solid conductor",
                    _spec_net_clause(circuit, rail),
                    f"members: {', '.join(_members(circuit, rail))}",
                    f"provenance={net_provenance(circuit, rail)}",
                    rivals,
                ),
            ),
            RoleBinding(
                role="gnd",
                part_id=gnd,
                evidence=evidence(
                    "role=gnd: the net of class 'gnd' every branch in this "
                    "module returns to",
                    _spec_net_clause(circuit, gnd),
                    f"members: {', '.join(_members(circuit, gnd))}",
                    f"provenance={net_provenance(circuit, gnd)}",
                    rivals,
                ),
            ),
        ]
        for part_id in shunts:
            bindings.append(
                RoleBinding(
                    role="shunt",
                    part_id=part_id,
                    evidence=evidence(
                        f"role=shunt: a two-terminal part from the rail {rail} to "
                        f"the ground {gnd}, read from the nets and not from a "
                        "designator prefix, a value or a package name",
                        part_clause(circuit, part_id),
                        f"pins on this module's two rails: "
                        f"{_pin_on(circuit, part_id, rail) or '?'}→{rail}, "
                        f"{_pin_on(circuit, part_id, gnd) or '?'}→{gnd}",
                        f"inlet chosen: {shape}",
                        f"provenance={weakest_provenance(part_provenance(circuit.part(part_id)), prov)}",
                        rivals,
                    ),
                )
            )

        constraints: list[RelativeConstraint] = []
        for part_id in shunts:
            constraints.append(
                RelativeConstraint(
                    kind=SAME_ROW,
                    subject=entry,
                    object=part_id,
                    reason=(
                        f"088 sec.2: the top rail {rail} is one row, and "
                        f"{part_id}'s {rail}-side pin "
                        f"({_pin_on(circuit, part_id, rail) or '?'}) lands on it, "
                        f"the same row the inlet's {rail}-side pin "
                        f"({rail_pin or '?'}) is on — the branch is read as "
                        "hanging off the rail, not as a second rail"
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=side_kind,
                    subject=entry,
                    object=part_id,
                    reason=(
                        "088 sec.2: the inlet terminates the row at the input end "
                        f"and {part_id} is on the far side of it "
                        f"(sidePreferences.input={in_side})"
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=NEAR,
                    subject=part_id,
                    object=entry,
                    reason=(
                        f"088 sec.2: {part_id} is the local topology of this rail "
                        f"— beside {entry}, close enough to read as one inlet "
                        "block, and not across a module boundary (052 sec.5)"
                    ),
                )
            )

        obligations: list[GrammarObligation] = [
            GrammarObligation(
                kind=DIRECT_WIRE,
                nets=(rail,),
                reason=(
                    f"088 sec.2: the rail is a solid conductor — every member of "
                    f"{rail} is wired to the same wire end to end, not spelled "
                    "out as flags that merely share a name"
                ),
            ),
            GrammarObligation(
                kind=DIRECT_WIRE,
                nets=(gnd,),
                reason=(
                    f"088 sec.2: the return rail is a solid conductor too — every "
                    f"member of {gnd} is wired to the same wire end to end; the "
                    "two rails are one chain in parallel, so neither is the "
                    "other's series element"
                ),
            ),
            GrammarObligation(
                kind=UNIFORM_GND,
                nets=(gnd,),
                reason=(
                    "088 sec.2: this module's ground is expressed one way "
                    "throughout — one symbol style or one label, never mixed"
                ),
            ),
            GrammarObligation(
                kind=OWNED_BRANCH,
                nets=(rail,),
                reason=(
                    "088 sec.2: "
                    + (", ".join(shunts) if shunts else "no branch")
                    + f" read as branches owned by the rail {rail} — attached to "
                    "the row they hang from, not crossing into another module"
                ),
            ),
        ]
        return bound_result(bindings, constraints, obligations)


GRAMMAR = PowerEntryGrammar


def grammar(
    profiles: Mapping[str, SymbolProfile] | None = None,
) -> PowerEntryGrammar:
    """A power-entry grammar, optionally holding the library profiles."""
    return PowerEntryGrammar(profiles)


# ------------------------------------------------------------- the judgment


def _rail_of(circuit: CircuitSpec, power: tuple[str, ...]) -> str:
    """Which power-class net is this module's rail.

    A power net that carries the fact channel wins — the rail whose own
    ``openInterfaces`` entry names a part is the one somebody stated an inlet
    for. Otherwise the id-first power net, which is a stable tie-break rather
    than a claim: `_claim_note` puts the runners-up into the evidence.
    """
    named = sorted(
        net_id for net_id in power
        if any(item.net == net_id and item.part for item in circuit.open_interfaces)
    )
    return named[0] if named else power[0]


def _ground_of(circuit: CircuitSpec, rail: str, ground: tuple[str, ...]) -> str:
    """The ground **this rail's own members** reach.

    A page can carry several ground nets; the one that matters here is the one
    the parts sitting on the rail also sit on — the module's return path, read
    from the partition rather than from a name. `id`-sorted first when several
    qualify, which is a tie-break and not a claim.
    """
    net = circuit.net(rail)
    owners = {member.partition(".")[0] for member in (net.members if net else ())}
    shared = [
        net_id
        for net_id in ground
        if (
            (other := circuit.net(net_id)) is not None
            and owners & {member.partition(".")[0] for member in other.members}
        )
    ]
    return (shared or list(ground))[0]


def _entry_claims(
    circuit: CircuitSpec, rail: str
) -> list[SpecOpenInterface]:
    """``openInterfaces`` entries on the rail that claim an inlet, in order.

    An entry qualifies when it states a direction that means "the supply enters
    here" **and** names the part that realises it. Both halves matter: a
    direction alone is a net's role, and a part alone is a part — only the pair
    says "CN1 feeds this rail".
    """
    found = []
    for item in circuit.open_interfaces:
        if item.net != rail or not item.part:
            continue
        if item.direction and item.direction not in ENTRY_DIRECTIONS:
            continue
        found.append(item)
    found.sort(key=lambda item: (item.part, item.direction))
    return found


def _entry_problem(
    circuit: CircuitSpec, rail: str, gnd: str, named: list[SpecOpenInterface]
) -> GrammarFailure | None:
    """Why the stated inlet cannot be one, or ``None`` when it is one."""
    claim = named[0]
    part = circuit.part(claim.part)
    if part is None:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=claim.part,
            detail=(
                f"openInterfaces[{rail}].part names {claim.part!r}, which this "
                f"CircuitSpec does not declare ({', '.join(circuit.part_ids())}) — "
                "an inlet that does not exist is an inlet that does not feed "
                "anything"
            ),
            action=(
                f"write the connector as a part of the circuit, or point "
                f"openInterfaces[{rail}].part at a part that exists"
            ),
        )
    pins = pins_of_part(circuit, part.id)
    here = sorted(set(pins.values()))
    if len(pins) != 2 or here != sorted({rail, gnd}):
        where = ", ".join(
            f"{pin}→{net}" for pin, net in sorted(pins.items())
        ) or "no connection stated"
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=part.id,
            detail=(
                f"openInterfaces[{rail}].part names {part.id!r}, but it is not a "
                f"two-terminal part across {rail} and {gnd} (its connections: "
                f"{where}) — the inlet of this module is the part that carries "
                "the rail onto the ground and nothing else"
            ),
            action=(
                f"state {part.id}'s two pins on {rail} and on {gnd} in "
                "CircuitSpec.nets[].members, or point openInterfaces[].part at "
                "the part that does"
            ),
        )
    others = [item.part for item in named[1:] if item.part != part.id]
    if others:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=part.id,
            detail=(
                f"{len(named)} open interfaces on {rail} each name a part that "
                f"feeds it ({', '.join([part.id, *others])}) — one rail has one "
                "inlet; which one it is has to be stated once"
            ),
            action=(
                "keep one openInterfaces[] entry on this rail and state the rest "
                "on their own nets, or split the circuit into two modules"
            ),
        )
    return None


def _shunts(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    rail: str,
    gnd: str,
    entry: str,
) -> tuple[str, ...]:
    """Every two-terminal part from the rail to this ground but the inlet."""
    edges = two_terminal_parts(circuit)
    scope = _scope(presentation, entry)
    return tuple(
        part_id
        for part_id in sorted(edges)
        if part_id != entry
        and rail in edges[part_id]
        and gnd in edges[part_id]
        and (not scope or scope in modules_of_part(presentation, part_id))
    )


def _scope(presentation: PresentationSpec, entry: str) -> str:
    """The entry's own module, when the presentation declares modules at all."""
    if not declares_modules(presentation):
        return ""
    found = modules_of_part(presentation, entry)
    return found[0] if len(found) == 1 else ""


# ------------------------------------------------------------------ clauses


def _pin_on(circuit: CircuitSpec, part_id: str, net_id: str) -> str:
    """The spec pin token of `part_id` that sits on `net_id`, or ``""``."""
    for pin, net in sorted(pins_of_part(circuit, part_id).items()):
        if net == net_id:
            return pin
    return ""


def _members(circuit: CircuitSpec, net_id: str) -> tuple[str, ...]:
    net = circuit.net(net_id)
    return tuple(sorted(net.members)) if net is not None else ()


def _describe(rail: str, gnd: str, entry: str, shunts: tuple[str, ...]) -> str:
    """``V24→CN1→(‖D1,C115,C116)→GND`` — the spelling a report prints."""
    branch = "‖" + ",".join(shunts) if shunts else ""
    return f"{rail}→{entry}{branch}→{gnd}"


def _claim_note(named: list[SpecOpenInterface]) -> str:
    if len(named) < 2:
        return ""
    shown = ", ".join(
        f"{item.part} (direction={item.direction or 'input'})" for item in named[1:4]
    )
    more = "" if len(named) <= 4 else f"; +{len(named) - 4} more"
    return (
        "other open interfaces on this rail also name a part, not bound (this "
        f"grammar instance bound one): {shown}{more}"
    )


def _spec_net_clause(circuit: CircuitSpec, net_id: str) -> str:
    net = circuit.net(net_id)
    return net_clause(net) if net else f"net {net_id}: not declared in nets[]"


# ----------------------------------------------------------------- refusals


def _missing_class_failures(
    power: tuple[str, ...], ground: tuple[str, ...]
) -> list[GrammarFailure]:
    """The two classes this grammar needs, worded as `rc-lowpass` words them."""
    out: list[GrammarFailure] = []
    if not ground:
        out.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'gnd': a power inlet's branches return to "
                    "ground, and the grammar has to be told which net that is"
                ),
                action=(
                    "write the class in CircuitSpec.nets[].class — a net that "
                    "states nothing is class 'signal', which is not ground"
                ),
            )
        )
    if not power:
        out.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'power': the inlet feeds a rail, and the "
                    "grammar has to be told which net that is"
                ),
                action="write the class in CircuitSpec.nets[].class (power)",
            )
        )
    return out


def _no_entry_failure(circuit: CircuitSpec, rail: str) -> GrammarFailure:
    """The rail exists but nobody said what feeds it."""
    stated = [
        item for item in circuit.open_interfaces if item.net == rail
    ]
    if stated:
        seen = ", ".join(
            f"direction={item.direction or 'unspecified'}"
            + ("" if item.part else ", part empty")
            for item in stated
        )
        # Which half is missing is two different repairs, so name the one that
        # actually is: a stated part with a direction that does not mean "the
        # supply enters here" is not a missing part, and telling the reader to
        # write one would send them to fix what is already written.
        why = (
            "no part"
            if not any(item.part for item in stated)
            else f"no direction that means the supply enters here ("
                 f"{', '.join(ENTRY_DIRECTIONS)} expected)"
        )
        detail = (
            f"net {rail} states an open interface ({seen}) but {why}, so the "
            "grammar cannot tell the inlet from a parallel branch — every part "
            "across this rail and ground looks the same in the partition"
        )
    else:
        detail = (
            f"net {rail} states no open interface at all, so the grammar cannot "
            "tell the inlet from a parallel branch — every part across this "
            "rail and ground looks the same in the partition"
        )
    return GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject=rail,
        detail=detail,
        action=(
            "which connector feeds the rail — state it in openInterfaces[].part "
            f"on net {rail}: add an entry {{'net': '{rail}', 'direction': "
            "'input', 'role': 'rail', 'part': '<the connector part id>'}}"
        ),
    )
