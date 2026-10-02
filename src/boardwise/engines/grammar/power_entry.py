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

**What this grammar does not promise, and what 088b changed.** The order the
branches are drawn in is *declarable* — `PresentationSpec.modules[].branchOrder`
states the branches from the inlet end outwards, and the grammar carries it out
with a chain of `adjacent` between neighbours (see below for why that kind and not
`left-of`/`right-of`). The electrical fact still fixes nothing: three parts across
the same two nets are three interchangeable edges of a multigraph, and 053 §6
forbids a scenario-specific constant in a grammar table — so a part's *identity*
(which one is the TVS) is still not read here. What 岳's sheet says is a statement
about his drawing, and the document is where it is written: the model that writes
the presentation reads the values and packages (`SMCJ28CA` is a TVS), and the
grammar only checks that what it was told is about *this* module's branches.
**Absent** `branchOrder` the drawing is byte-for-byte 088's: the compiler lays the
branches out by part id, exactly as it did before.

**095: the order has three sources, and the middle one is the contract.** 088b
made 「TVS 贴入口」 declarable in every presentation; 095 lets the drawing read the
same fact from `DesignIntent`, where A2/A3 already put it — so the fact is stated
once and both the review and the drawing read it. The order is read from the
first source that speaks, in this order:

1. `PresentationSpec.modules[].branchOrder` — the drawing's own declaration, still
   first: what the sheet says about itself outranks anything else (**absence of
   it is not a statement**, so a declared order is never second-guessed);
2. the **intent**, when nothing is declared: a decision or a block that says one
   of this module's branches clamps the rail's spikes (`decisions[subject=<id>]`
   whose prose names a TVS/clamp, or a `blocks[]` whose `kind` does and whose
   `parts` list the branch) puts those branches nearest the inlet, the rest
   follow in designator order. The evidence names the entry it was read from, the
   contract's path and the entry's own `provenance` — an `ai_asserted` claim is
   carried out and **marked a draft** (052 §4: a guess may be drawn, never
   silently read as a requirement), and the binding's own weakest-provenance line
   weakens with it;
3. neither → the designator order, byte-for-byte 088's drawing.

**Both sources speaking is a refusal, not a precedence.** When a `branchOrder`
exists *and* the contract states which branches clamp, the two are two statements
of one fact — 岳's 「支路顺序」, said twice — and this grammar does not grade one
against the other: if the declared order puts a non-clamping branch before a
clamping one (i.e. the declared order denies what the contract asserts), the bind
is refused `circuit-invalid` with **both originals quoted** — the declared list as
written and the contract entry with its provenance — so a person decides which of
the two is wrong (the discipline A3a R1 applied on the review side). Two sources
that agree are not a conflict: the declaration is used, and the agreement is
written into the evidence.

What is compared is the *claim*, not a permutation: the intent says "these
branches clamp, so they stand before the rest", and it does **not** order the
clamping branches among themselves — that part of the derived order is this
grammar's own designator tie-break, and refusing over a tie-break would be a
false alarm — which the live discipline treats as costing what a wrong delete
costs (R2, `tasks/012-basic-experience.md`). Measured: `branchOrder=[C116,D1,C115]` with a
contract saying `D1` clamps is refused (C116 stands before D1); the same
declaration with the clamping branch first is carried out as declared.

The clause list is deliberately short — `tvs`, `clamp`/`钳位`, `泄放` — because
the contract's prose is prose: 浪涌/`surge` also names an inrush current, and a
bulk capacitor decoupling a rail is not a bleeder. A contract that wants a
structural statement (rather than a sentence a person reads) is a later batch's
field; today the grammar reads what is written and says where it read it, and the
same limit 053 §6 puts on designators applies here: nothing is inferred from a
part's value, package or prefix.

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
* `adjacent` between **neighbouring branches**, and only where the document
  states an order (088b §二): "these two stand next to each other along the rail,
  and this one is the nearer the inlet". Measured: the two horizontal order kinds
  cannot carry this. `right-of(D1, C115)` — the honest reading for an inlet on the
  right, "D1 is on the power side when that side is the right one" — is a
  statement the compiler's rank walk reads the other way round
  (`drawcompiler._rank_edges` maps `right-of(A, B)` to `(B, A)`, which is what the
  branch *rank* is built from, while the finished plan is graded against the
  relation's own definition by `_relation_holds`), so all six variants of 岳's
  sample came back "the relation right-of(D1, C115) is not honoured"; the same
  grammar mirrored to `input: left` drew the chain happily, and swapping the rank
  mapping instead moved the branches to the wrong *side* of the inlet (measured:
  the side a branch hangs on comes from the same rank comparison). Changing that
  reading is a change to a judge all four grammars share, so 088b did not make
  it (the batch's evidence has the measurements and the report states it). What
  the chain uses instead is the one kind whose statement is true in both
  orientations and whose check agrees with where the branches land: the pair's
  own order ("nothing between them" is what `adjacent` says, and the rank walk
  reads `adjacent(subject, object)` as "subject nearer the power end"). Measured:
  the chain draws D1 → C115 → C116 from the inlet end on both `input: right` and
  `input: left`, with the plan's own relation findings empty.

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
`gnd-outlet` (088b §一) is the fifth: this drawing's return rail terminates in
**exactly one** outlet symbol of its own, hung at the rail's far end and standing
upright — 岳 2026-10-02: 「底轨要有一个、且只要一个出处符号」. The obligation names
the net and the compiler reads *which* end from `sidePreferences.input`, so the
symbol mirrors with the drawing. It is stated on **every** bind: the first cut of
this batch gated it on a *declared* group to keep 088's own drawings untouched,
and the 2026-10-02 ruling (confirmed by the main agent on review) took that gate
away — 岳's sample declares no modules either, and 「加一个接地符号」 has no such
premise. The four 088 assertions this changes were the batch's own "today it is
like this, awaiting the ruling" pins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...core.circuitspec import CircuitSpec, SpecOpenInterface
from ...core.designintent import DesignIntent, IntentSource
from ...core.presentationspec import SIDES, PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    ADJACENT,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    GND_OUTLET,
    GrammarError,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    PROVENANCE_AI,
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
    "CLAMP_TOKENS",
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

#: The words a contract entry uses to say one of these branches **clamps** the
#: rail — 泄放类, the family 088b's R12 ruled belongs nearest the inlet. Read from
#: the prose of `decisions[]` (or from a `blocks[].kind`), never from a designator,
#: a value or a package name (053 §6).
#:
#: The list is short on purpose. A contract is prose, and a token that is *nearly*
#: right reads a bulk capacitor as a bleeder: 浪涌/`surge` also names a capacitor's
#: inrush current (「输入大电容提供浪涌电流」 is not a clamping statement), and
#: `diode` alone names a rectifier. What is stated is read and the entry is quoted
#: in the evidence, so a reader sees the sentence the order came from; a contract
#: that wants to state this structurally is a later batch's field (the module
#: docstring says so).
CLAMP_TOKENS: tuple[str, ...] = ("tvs", "clamp", "钳位", "泄放")



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
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        *,
        intent: IntentSource | DesignIntent | None = None,
    ) -> GrammarResult:
        """Bind, reading the branch order from the declaration or the contract.

        ``intent`` is **optional and absent by default**: a bind that is handed no
        contract behaves exactly as it did before 095 — the order is the
        declaration's, or the designator's (the module docstring has the three
        sources and what a disagreement does).
        """
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
        scope = _scope(presentation, entry)
        shunts = _shunts(circuit, presentation, rail, gnd, entry, scope)
        reading = _order_reading(
            circuit, presentation, scope, shunts, entry, rail, gnd, intent
        )
        if reading.failure is not None:
            return refused_result([reading.failure])
        return self._result(
            circuit, presentation, rail, gnd, entry, named, scope, reading
        )

    # ------------------------------------------------------------- internals

    def _result(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        rail: str,
        gnd: str,
        entry: str,
        named: list[SpecOpenInterface],
        scope: str,
        reading: _OrderReading,
    ) -> GrammarResult:
        """Everything bound, in the order the drawing will use (095 §一).

        ``reading.order`` is what every ordered thing here reads — the shunt
        bindings, their three constraints, the shape the evidence prints and the
        branch list in the `owned-branch` reason. 088b already did this with the
        *completed declaration* (its `_result` took the order in the parameter
        named `shunts`); 095 keeps that reading and adds one more source that can
        fill it, so a contract-ordered drawing's whole binding reads in its own
        order rather than in the designator order it was deliberately drawn
        against.
        """
        shunts = reading.order
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
        order_note = reading.note

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
                        order_note,
                        f"provenance={_binding_provenance(circuit, part_id, prov, reading)}",
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

        # 088b §二: the stated order, carried out between neighbours. Only stated
        # when a source states one — an undeclared, uncontracted drawing gets no
        # extra relation, which is what keeps 088's own constraint list (and its
        # geometry) exactly as it was. 095 §一 adds the contract as a second
        # source; the chain it emits is the same kind over the order it gave.
        pairs = zip(reading.order, reading.order[1:]) if reading.chained else ()
        for near_id, far_id in pairs:
            constraints.append(
                RelativeConstraint(
                    kind=ADJACENT,
                    subject=near_id,
                    object=far_id,
                    reason=(
                        f"088b sec.2: {reading.origin}, and {near_id} is the branch "
                        f"next to the inlet {entry} before {far_id} — nothing stands "
                        f"between them on the rail, and {near_id} is the one "
                        "nearer the inlet; a TVS nearest the inlet is what the "
                        "order is for (a spike is clamped before it reaches the "
                        "next branch), and the grammar reads the order, never the "
                        "designator or the value"
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
        # 088b §一 (岳 2026-10-02 裁决②, 主代理 2026-10-02 复验裁定「无条件」): every
        # power-entry drawing states its return rail with exactly one outlet symbol.
        # The first cut of this batch gated the promise on a *declared* group (so
        # 088's own module-level scenarios stayed byte-identical); the ruling is
        # that 「加一个接地符号」 has no such premise — 岳's sample does not declare
        # modules either, and a promise nobody fires is not the ruling. The gate is
        # gone: the obligation is stated on every bind, which is what changed the
        # four 088 assertions this ruling named (they were the "today it is like
        # this, awaiting the ruling" pins) and the 088 previews with them.
        obligations.append(
            GrammarObligation(
                kind=GND_OUTLET,
                nets=(gnd,),
                reason=(
                    f"088b sec.1 (岳 2026-10-02, unconditional): this drawing states "
                    f"its return rail {gnd} with exactly one outlet symbol of its "
                    "own — hung at the far end of the rail, the end away from "
                    f"the inlet {entry}, and standing upright; a ground left "
                    "as a bare conductor says nothing about where the return "
                    "leaves the group"
                ),
            )
        )
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
    scope: str,
) -> tuple[str, ...]:
    """Every two-terminal part from the rail to this ground but the inlet.

    Collected in **designator order**, which is the drawing order an undeclared
    document gets; the declared order is applied afterwards
    (:func:`_declared_order`), so the collection itself stays a reading of the
    partition.
    """
    edges = two_terminal_parts(circuit)
    return tuple(
        part_id
        for part_id in sorted(edges)
        if part_id != entry
        and rail in edges[part_id]
        and gnd in edges[part_id]
        and (not scope or scope in modules_of_part(presentation, part_id))
    )


def _scope(presentation: PresentationSpec, entry: str) -> str:
    """The entry's own module, when the presentation declares modules at all.

    Empty means "this drawing is not a declared group": either the presentation
    declares no modules, or the inlet is in none or in several. The two facts
    that read the group — where `branchOrder` comes from and whether the ground
    states an outlet (088b) — are both read from here, so a drawing without a
    group is 088's drawing.
    """
    if not declares_modules(presentation):
        return ""
    found = modules_of_part(presentation, entry)
    return found[0] if len(found) == 1 else ""


def _declared_order(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    scope: str,
    shunts: tuple[str, ...],
    entry: str,
    rail: str,
    gnd: str,
) -> tuple[tuple[str, ...], GrammarFailure | None]:
    """The branches in drawing order: the declared ones first, then the rest.

    The document's `branchOrder` is a statement of intent — 岳 2026-10-02: a TVS
    belongs nearest the inlet — and this grammar's whole part in it is to check
    that the statement is *about this module's branches* and then to carry it
    out. Two things are refused, both naming the designator:

    * a designator that is not a shunt of this module at all — it is the inlet,
      or a part across another net: the drawing has no branch to put there;
    * a designator that belongs to another module's drawing — the spec layer
      already refuses that (the order is stated over the declaring module's own
      `parts`), so reaching here means the two documents disagree.

    A **partial** declaration is completed rather than refused: the named
    branches keep their stated order and the rest follow in designator order.
    That is the same reading the module-level `flow` gets ("a partial order over
    ids, completed by name order"), it keeps "today's order" one rule instead of
    two, and it is what makes a *declared prefix* mean what it says — refusing
    would stop a drawing the compiler can make, over a document that already
    states the half that matters. The completion is stated in the binding
    evidence, so it is never invisible.
    """
    declaration = _branch_order_of(presentation, scope)
    if not declaration:
        return shunts, None
    named = set(shunts)
    unknown = [part_id for part_id in declaration if part_id not in named]
    if unknown:
        return shunts, _order_failure(
            circuit, presentation, scope, unknown, entry, rail, gnd
        )
    rest = sorted(part_id for part_id in shunts if part_id not in set(declaration))
    return tuple(declaration) + tuple(rest), None


def _order_failure(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    scope: str,
    unknown: list[str],
    entry: str,
    rail: str,
    gnd: str,
) -> GrammarFailure:
    """Name the designator the order cannot be about, and what it is instead."""
    subject = unknown[0]
    here = sorted(set(pins_of_part(circuit, subject).values()))
    if subject == entry:
        what = (
            f"it is the inlet of this module (openInterfaces[{rail}].part) — the "
            "branch order is about the branches that hang between the rails, and "
            "the inlet terminates them"
        )
    elif len(here) != 2:
        what = (
            f"it is not a two-terminal part of this module (its connections: "
            + (", ".join(
                f"{pin}→{net}"
                for pin, net in sorted(pins_of_part(circuit, subject).items())
            ) or "no connection stated")
            + ")"
        )
    else:
        what = (
            f"its two pins sit on {here[0]} and {here[1]}, not across {rail} and "
            f"{gnd} — a branch of this module hangs between those two rails"
        )
    others = (
        ""
        if len(unknown) == 1
        else f" ({', '.join(unknown[1:])} too)"
    )
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject=subject,
        detail=(
            f"modules[{scope}].branchOrder names {subject!r}, which is not a shunt "
            f"of this module{others}: {what}. The order states where the branches "
            "between the rails are drawn, from the inlet outwards — a designator "
            "outside that set describes a drawing that does not exist"
        ),
        action=(
            f"write modules[{scope}].branchOrder over the parts this module has "
            "across both rails (the inlet and the parts of other modules are not "
            "branches here), or drop the designator from the order"
        ),
    )


def _branch_order_of(
    presentation: PresentationSpec, scope: str
) -> tuple[str, ...]:
    """The entry's own module's stated branch order, or ``()``."""
    module = presentation.module(scope) if scope else None
    return tuple(module.branch_order) if module is not None else ()


def _order_note(
    presentation: PresentationSpec, scope: str, shunts: tuple[str, ...]
) -> str:
    """What the stated order was read as — including what it left unsaid.

    A partial declaration is completed in designator order, and saying so in the
    evidence is what keeps the completion from being invisible: a reader of the
    binding sees which branches the document placed and which it left to the
    default. Empty when the document states no order at all.
    """
    declaration = _branch_order_of(presentation, scope)
    if not declaration:
        return ""
    stated = (
        f"modules[{scope}].branchOrder states {', '.join(declaration)} from the "
        "inlet outwards"
    )
    rest = [part_id for part_id in shunts if part_id not in set(declaration)]
    if not rest:
        return stated + "; every branch of this module is named there"
    return (
        stated
        + f"; not named there, so drawn after them in designator order: "
        + ", ".join(rest)
    )


# ------------------------------------------------------------------ the order


#: The clause the `adjacent` chain's reason opens with when the order came from
#: the drawing's own declaration (088b's wording, unchanged: a declared drawing's
#: constraint list and its reasons are byte-for-byte 088b's).
_DECLARED_ORIGIN = "the document states this module's branch order (branchOrder)"

#: …and when it came from the contract instead (095 §一.2).
_INTENT_ORIGIN = (
    "the design intent states this module's branch order (the contract's own "
    "decisions, not branchOrder)"
)


@dataclass(frozen=True)
class _Claim:
    """One contract entry that says a branch clamps the rail (095 §一.2)."""

    part_id: str
    where: str
    text: str
    provenance: str

    def clause(self) -> str:
        """The entry as the evidence and the refusal quote it:原文 + 出处 + 来源."""
        return f"{self.where}: {self.text!r} (provenance={self.provenance})"


@dataclass(frozen=True)
class _OrderReading:
    """What the three sources of the branch order came to (095 §一).

    ``order`` is what the drawing uses; ``chained`` says whether a source spoke
    at all (no source → no `adjacent` chain, 088's constraint list); ``note`` is
    the evidence clause; ``origin`` opens the chain's own reason; ``provenance``
    holds the contract's provenance for the branches **the contract placed** —
    empty whenever the drawing rests on the declaration or on a designator.
    """

    order: tuple[str, ...]
    chained: bool
    note: str
    origin: str
    provenance: dict[str, str]
    failure: GrammarFailure | None = None


def _order_reading(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    scope: str,
    shunts: tuple[str, ...],
    entry: str,
    rail: str,
    gnd: str,
    intent: IntentSource | DesignIntent | None,
) -> _OrderReading:
    """The branch order, from the first source that speaks (095 §一).

    Three sources, in this order: the presentation's declaration, then the
    contract, then the designator order. A declaration and a contract that both
    speak are checked against each other (``_clamp_claims`` says what the contract
    claims); a declaration alone, or a contract alone, is carried out; nothing
    speaking at all is 088's drawing, byte for byte.
    """
    declaration = _branch_order_of(presentation, scope)
    claims, path = _clamp_claims(intent, shunts)
    if not claims:
        # No contract, or a contract that says nothing about this module's
        # branches — 088b, byte for byte.
        if not declaration:
            return _OrderReading(
                order=shunts, chained=False, note="", origin="", provenance={},
            )
        order, failure = _declared_order(
            circuit, presentation, scope, shunts, entry, rail, gnd
        )
        return _OrderReading(
            order=order,
            chained=True,
            note=_order_note(presentation, scope, shunts),
            origin=_DECLARED_ORIGIN,
            provenance={},
            failure=failure,
        )

    clamps = sorted(part_id for part_id in shunts if part_id in claims)
    rest = sorted(part_id for part_id in shunts if part_id not in claims)
    derived = tuple(clamps) + tuple(rest)
    if not declaration:
        return _OrderReading(
            order=derived,
            chained=True,
            note=_intent_note(
                claims, path, scope, clamps, rest, declared=False, agreed=False
            ),
            origin=_INTENT_ORIGIN,
            provenance={part_id: claims[part_id].provenance for part_id in clamps},
        )

    order, failure = _declared_order(
        circuit, presentation, scope, shunts, entry, rail, gnd
    )
    if failure is not None:
        # The declaration cannot be carried out at all: 088b's refusal, unchanged.
        # A contract does not make an order naming the inlet executable.
        return _OrderReading(
            order=shunts, chained=True, note="", origin=_DECLARED_ORIGIN,
            provenance={}, failure=failure,
        )
    offenders = _order_conflict(order, clamps)
    if offenders:
        return _OrderReading(
            order=order,
            chained=True,
            note="",
            origin=_DECLARED_ORIGIN,
            provenance={},
            failure=_conflict_failure(
                scope, declaration, order, offenders, clamps, claims, path
            ),
        )
    agreed = tuple(order) == derived
    return _OrderReading(
        order=order,
        chained=True,
        note=(
            _order_note(presentation, scope, shunts)
            + "; "
            + _intent_note(
                claims, path, scope, clamps, rest, declared=True, agreed=agreed
            )
        ),
        origin=_origin_clause(agreed),
        provenance={},
    )


def _clamp_claims(
    intent: IntentSource | DesignIntent | None, shunts: tuple[str, ...]
) -> tuple[dict[str, _Claim], str]:
    """``(claims, contract path)`` — which of this module's branches clamp.

    Read from two places, both of them the contract's own words (095 §一.2):

    * ``decisions[subject=<part>]``, whose ``decision`` (or ``rationale``) prose
      names the clamping family — 岳's 2026-10-02 ruling, stated once where the
      decisions live;
    * ``blocks[]``, when the block's ``kind`` names the family and its ``parts``
      list the branch — the same claim, written as a block instead of a sentence.

    A claim about a part that is **not** one of this module's branches is not read
    here, which is the scope rule the rest of this grammar already uses: a part
    across another module's nets is that module's business, and its own drawing is
    where its contract entry lands (088 §一.3).
    """
    document, path = _intent_document(intent)
    if document is None:
        return {}, ""
    named = set(shunts)
    claims: dict[str, _Claim] = {}
    for decision in document.decisions:
        if not _names_clamp(decision.decision, decision.rationale):
            continue
        if decision.subject not in named:
            continue
        claims.setdefault(decision.subject, _Claim(
            part_id=decision.subject,
            where=f"decisions[subject={decision.subject!r}]",
            text=(
                decision.decision if _names_clamp(decision.decision)
                else decision.rationale
            ),
            provenance=decision.provenance,
        ))
    for block in document.blocks:
        if not _names_clamp(block.kind):
            continue
        for part_id in block.parts:
            if part_id not in named:
                continue
            claims.setdefault(part_id, _Claim(
                part_id=part_id,
                where=f"blocks[id={block.id!r}].kind",
                text=block.kind,
                provenance=block.provenance,
            ))
    return claims, path


def _intent_document(
    intent: IntentSource | DesignIntent | None,
) -> tuple[DesignIntent | None, str]:
    """``(document, path)`` — the contract this bind reads, and where it came from.

    Both spellings are accepted because both reach a grammar naturally: the CLI
    hands over an :class:`IntentSource` (094's carrier — the document *and* the
    path a finding has to name), a test or an in-memory caller a bare
    :class:`DesignIntent`. A value that is neither is refused rather than ignored:
    a contract nothing can read would leave the drawing on its default order while
    the caller believes the contract was consumed.
    """
    if intent is None:
        return None, ""
    if isinstance(intent, IntentSource):
        return intent.document, str(intent.path or "")
    if isinstance(intent, DesignIntent):
        return intent, ""
    raise GrammarError(
        f"intent must be an IntentSource or a DesignIntent, got "
        f"{type(intent).__name__} — a contract this module cannot read is a "
        "contract it may not silently do without"
    )


def _names_clamp(*texts: str) -> bool:
    """Does this prose name the clamping family (:data:`CLAMP_TOKENS`)?"""
    haystack = " ".join(texts).casefold()
    return any(token.casefold() in haystack for token in CLAMP_TOKENS)


def _binding_provenance(
    circuit: CircuitSpec, part_id: str, prov: str, reading: _OrderReading
) -> str:
    """One branch's weakest fact, the contract included when it placed it.

    The claim's own provenance joins the chain only where the contract placed the
    branch (095 §一.2): then the drawing rests on the sentence the order came from,
    and an `ai_asserted` entry makes the binding a visible draft (052 §4).
    Composed rather than passed unconditionally, because `weakest_provenance` reads
    an empty value as `unstated` — weaker than every real provenance, which would
    make every untouched drawing look like a draft.
    """
    sources = [part_provenance(circuit.part(part_id)), prov]
    claim = reading.provenance.get(part_id, "")
    if claim:
        sources.append(claim)
    return weakest_provenance(*sources)


def _origin_clause(agreed: bool) -> str:
    """What the `adjacent` chain's reason opens with, in each of the three states."""
    if agreed:
        return (
            "the document states this module's branch order (branchOrder) and the "
            "design intent states the same one (the contract's own decisions)"
        )
    return _DECLARED_ORIGIN


def _intent_note(
    claims: dict[str, _Claim],
    path: str,
    scope: str,
    clamps: list[str],
    rest: list[str],
    *,
    declared: bool,
    agreed: bool,
) -> str:
    """The contract's claim as the binding evidence states it (095 §一.2).

    Three things a reader of the evidence has to be able to check without opening
    the contract: **which entry** said it (quoted), **where the contract is**, and
    **who said it** — the entry's own `provenance`, with a draft spelled out as a
    draft (052 §4). When the document declared no order, the same clause says that
    the contract's order is what the drawing carries out; when the declaration is
    what is carried out, it says which of the two the drawing rests on — and
    *agreement* is only claimed where the two orders really are the same one
    (``agreed``): a declaration that merely satisfies the claim, ordering the
    clamping branches the other way round, is stated as satisfied, not as equal.
    """
    where = (
        f"the contract {path}" if path
        else "the contract it was handed (no file named — an in-memory document)"
    )
    verb = "stands" if len(clamps) == 1 else "stand"
    stated = ", ".join(claims[part_id].clause() for part_id in clamps)
    ordering = (
        f"so {', '.join(clamps)} {verb} nearest the inlet and the rest follow in "
        f"designator order: {', '.join(rest)}"
        if rest
        else (
            f"so {', '.join(clamps)} {verb} nearest the inlet, and every branch of "
            "this module is one of them"
        )
    )
    note = f"the design intent states {stated}, {ordering} — read from {where}"
    if declared and rest and agreed:
        note += (
            f"; modules[{scope}].branchOrder states the same order, so nothing is "
            "re-ordered: the two sources agree"
        )
    elif declared and rest:
        note += (
            f"; modules[{scope}].branchOrder satisfies the claim — every clamping "
            "branch stands first — so the declaration is what the drawing carries "
            "out, and the contract orders nothing among the branches it did not "
            "name"
        )
    elif declared:
        note += (
            "; every branch of this module is one of the clamped ones, so the "
            "contract states nothing about their order among themselves — the "
            "declaration is what the drawing carries out"
        )
    if weakest_provenance(
        *(claims[part_id].provenance for part_id in clamps)
    ) == PROVENANCE_AI:
        note += (
            "; the contract states it as a draft (ai_asserted) — a guess may be "
            "read as a hint, and it is "
            + (
                "the declaration the drawing carries out (052 sec.4)"
                if declared
                else "carried out here because the document declares no order "
                     "(052 sec.4)"
            )
        )
    return note


def _order_conflict(order: tuple[str, ...], clamps: list[str]) -> list[str]:
    """The branches the declared order puts before **every** clamping one.

    The contract's claim is a set, not a permutation: it says "these clamp, so
    they stand nearest the inlet, the rest follow", and it orders nothing *inside*
    either group. So the disagreement is exactly this — a branch the contract did
    not name standing where a named one belongs — and a different order among the
    clamping branches themselves is not a conflict: that part of the order is this
    grammar's own designator tie-break, and refusing over it would be a false
    alarm (R2, `tasks/012-basic-experience.md`).
    """
    clamped = set(clamps)
    first = min(order.index(part_id) for part_id in clamps if part_id in order)
    return [
        part_id for part_id in order[:first] if part_id not in clamped
    ]


def _conflict_failure(
    scope: str,
    declaration: tuple[str, ...],
    order: tuple[str, ...],
    offenders: list[str],
    clamps: list[str],
    claims: dict[str, _Claim],
    path: str,
) -> GrammarFailure:
    """Both originals, side by side, and no verdict (095 §一.3).

    The two sources state one fact — which branch is nearest the inlet — and they
    contradict each other, so there is nothing to carry out: picking one would be
    this grammar grading an engineer's declaration against the contract that is
    the declaration's own source of truth. The refusal quotes the declared list as
    written and the contract entry with its provenance and its file, names what
    each of them implies, and asks a person to say which one is wrong.
    """
    where = (
        f"the contract {path}" if path
        else "the contract it was handed (no file named — an in-memory document)"
    )
    stated = "; ".join(claims[part_id].clause() for part_id in clamps)
    claims_verb = "clamps" if len(clamps) == 1 else "clamp"
    stands = "stands" if len(clamps) == 1 else "stand"
    offender_verb = "stands" if len(offenders) == 1 else "stand"
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject=clamps[0],
        detail=(
            f"modules[{scope}].branchOrder states [{', '.join(declaration)}] from "
            f"the inlet outwards, so {', '.join(offenders)} {offender_verb} before "
            f"{', '.join(clamps)}; the design intent states {stated} — read from "
            f"{where} — so {', '.join(clamps)} {claims_verb} the rail and {stands} "
            "nearest the inlet. The two sources state the same fact and they "
            "disagree, and this grammar does not carry either of them out: it will "
            "not grade the drawing's own declaration against the contract the "
            "declaration was written from (the review side's rule, A3a R1, applied "
            "to the drawing). One of the two is wrong and a person says which"
        ),
        action=(
            f"reconcile the two: write modules[{scope}].branchOrder as "
            f"[{', '.join(clamps)}"
            + (f", {', '.join(sorted(item for item in order if item not in set(clamps)))}"
               if any(item not in set(clamps) for item in order) else "")
            + "] if the contract is right, or change "
            f"{claims[clamps[0]].where} if the declaration is right — the grammar "
            "keeps the declaration first and refuses to pick a winner here"
        ),
    )


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
