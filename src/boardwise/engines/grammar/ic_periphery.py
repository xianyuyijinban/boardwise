"""ic-periphery: 098's fifth grammar — an IC and what hangs off its own pins.

The drawing it promises, from 岳's CH340 module (098 sec.1):

    | ic-periphery | core / bridge / shunt / rail / gnd |
    核心 IC 居中，挂脚件各贴自己那一脚：晶振（bridge）跨核心两脚、负载电容
    与去耦/V3 电容（shunt）从核心一脚网回到 rail/gnd；跨模块信号在核心自己的
    脚上出网络标签，朝声明的那一侧 |

**The one fact this grammar cannot derive is which part is the core.** It is the
088 `entry` lesson in a new shape: every part of a module is "a part with pins",
and nothing about the partition says which of them the periphery is *around*. So
the fact is stated, and saying where it has to be stated is half the grammar.
Three sources, read in this order (098 sec.1, A4's three-source discipline):

1. ``PresentationSpec.modules[].core`` — the sheet's own declaration (new
   optional key, 098 sec.5): "this group is drawn around this part".
2. the **intent** — the contract's ``blocks[].parts``: a block that names
   exactly one part of this drawing carrying more than two pins says "this is
   the block's own IC". The evidence names the block, the contract's path and
   the entry's own ``provenance``; an `ai_asserted` claim is carried out and
   **marked a draft** (052 sec.4: a guess may be drawn, never silently read as a
   requirement).
3. the **partition** — a *unique strict maximum* of stated pin counts, and that
   maximum above two pins: exactly one part here has more pins than every other.
   Two parts tied at the top, or no part above two pins, is **not** a core: the
   answer is `facts-missing`, naming the two places the fact may be written.

**Sources that speak and disagree are refused, not ranked.** The three are three
statements of one fact, so a declaration saying one part and a partition saying
another is a contradiction the grammar does not grade: both originals are quoted
in a `circuit-invalid` refusal and a person says which is wrong (the discipline
088 §一.3 / 095 §一.3 applied to the same kind of disagreement). A source that
says nothing is not a conflicting source — an undeclared core whose partition is
ambiguous is `facts-missing`, and a declared core whose partition is ambiguous
binds, with the evidence saying that the declaration is what bound it.

**rail and gnd are read from the core's own pins**; the two classes are worded as
`rc-lowpass` and `power-entry` word them (053 sec.3: a net that states nothing is
class `signal`, which is neither):

* the rail is the `power` net the core's own pins sit on — 岳's sample has the
  module's supply on VCC, and this grammar draws the supply as a *reference*
  (a flag or a label, 069's own rule), never as the trunk of the drawing, which
  is why it states no `direct-wire` promise here (the difference from
  `power-entry`, whose rails **are** the drawing);
* the ground is the `gnd` net the core's pins sit on;
* neither found is `facts-missing`, naming the class to write, and a class that
  exists but which the core does not touch is `facts-missing` too, naming the
  core's own pin — "the supply is on this page, but not on this part".

**The periphery is two shapes, both read from the partition (052 sec.5: no
designator, value or package is ever read).** Where the presentation declares
modules, the collection is scoped to the core's own module, as `rc-lowpass` and
`power-entry` scope theirs: a part belonging to the next module is that module's
business.

* ``bridge`` — a two-terminal part whose **both** nets are the core's own pin
  nets and neither is the rail or the ground: 岳's crystal across XI/XO. It is
  the shape that ties two of the core's pins together, and it is what makes a
  cluster (below).
* ``shunt`` — a two-terminal part with one pin on a core pin net and the other
  on the rail or the ground: the two load capacitors, the decoupling capacitor
  and the V3 capacitor are one shape here, and the grammar says so by binding
  them one way rather than by guessing which is which from a value.
* a two-terminal part of this module that touches **no** core pin net is
  `circuit-invalid`, naming what it is actually connected to (098 sec.三): it is
  not this IC's periphery, and a module that collects other modules' parts
  produces a drawing whose branches hang off nothing.

**One compiler table had to learn the word `bridge`.** It is named in
`drawcompiler.BRANCH_ROLES` (the same kind of addition 088 made to `CHAIN_ROLES`
for `entry`): a part across two of its core's own pins still *hangs off* the pin
the drawing reads it from — 岳's crystal hangs off XI and reaches XO from there —
and a role named in neither of the compiler's role tuples is laid out on the free
shelf instead of at its pin. Nothing else in the compiler is special-cased: the
side statements above act as filters over the poses the compiler already tries.

**A cluster is structural, not named.** Two periphery parts belong to one cluster
when they share a core pin net that is neither the rail nor the ground — the
crystal and its load capacitors share XI/XO, and a decoupling capacitor on VCC
shares nothing with them, so it is a cluster of its own. The signal nets are what
the grouping reads; the ground is explicitly not, because a shared return is a
statement about the whole module, not about belonging (the rule
`drawcompiler._shared_nets` already applies to a branch's own owner).

**The constraints.** Four statements, all from the vocabulary 053 sec.3 fixed:

* ``near`` (periphery, core): the part hangs off its own core pin and reads as
  this IC's local topology, not as a wire crossing into another module. Measured,
  and stated rather than papered over: this kind is measured between the two
  parts' **pins on the shared net that sorts first** (`_points_for_relation`), and
  for a shunt that net is the ground — so what it actually measures is that the
  whole group is compact (the sample's furthest load capacitor sits 231 units from
  the core's own ground pin, inside the 300-unit local limit). A drawing that
  fans its branches out past that limit is refused, which is the promise working,
  not a false alarm.
* ``adjacent`` (bridge, shunt) for the pair that shares the bridge's **anchor
  pin** — the net `drawcompiler._shared_nets` gives the bridge, which is the net
  its branch is hung on. Measured: the crystal's *second* load capacitor hangs off
  the bridge's other pin, one pin-pitch lower, and `adjacent`'s own definition
  ("nothing between them") is measured on the two origins — a pair one pin-pitch
  apart laterally is not adjacent, so that pair is stated in the binding's
  `cluster:` evidence instead of being asserted as something the gate would
  refuse. Which of the two it is comes from the partition, never from a
  designator, a value or a package.
* ``left-of`` / ``right-of`` (signal, core) for a **cross-module signal**: a net
  whose only member in this module is a pin of the core, and which the
  presentation declares a direction for (``portRoles[net]``). The side is the
  declared one — `sidePreferences` for that direction. A signal with no declared
  direction gets no orientation constraint: absence is not a statement (052
  sec.4), and the evidence says so in the same breath.
* ``left-of`` / ``right-of`` (periphery, core) for **the drawing's orientation**,
  and this is the statement the declaration actually travels on. Measured: the
  label of a one-pin net is put at its pin with the pin's own escape direction,
  and the compiler's ranking hands back either mirror of the symbol (the sample's
  two mirror variants differ only in the compactness layer, 185554 vs 188081
  units², and the mirrored one wins there). `_points_for_relation` resolves part
  origins and shared pins and **never a net**, so the signal's own kind cannot
  move anything: it is read for the drawing's axis and for the order it states.
  The parts can move something — so each hanging part states the side it reads on
  **in the orientation the declared signals pick** (`_orientation_reading`: for
  each declared signal, whether its own pin already leaves on the declared side),
  and the pose that puts them there is the only one the gate keeps. The two
  mirror poses of the sample's own symbol are the two sides the declaration can
  choose, and swapping the declared sides leaves only the mirrored pose.

What the orientation reading does **not** do is decide between two declarations
that cannot both hold (one signal's pin says left and its declaration says right,
while another says the opposite): that is said in the evidence, not refused — a
declared side is a statement about the *page*, and a module compiled on its own
has no page to check it against.

**The obligations** are two, and neither is a conductor: `owned-branch` (every
hanging part reads as owned by this core, not as a branch of somebody else's
node) and `uniform-gnd` (this module's ground is expressed one way throughout).
`direct-wire` is deliberately **not** stated: the rail here is a supply
*reference* — a flag or a label, 069's own rule — and promising it as a wire
would be promising a trunk this drawing does not have (098 sec.2). `gnd-outlet`
is `power-entry`'s promise about the far end of a rail that is a conductor, and
this drawing has no such rail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...core.circuitspec import CircuitSpec
from ...core.designintent import DesignIntent, IntentSource
from ...core.presentationspec import PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    ADJACENT,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    UNIFORM_GND,
    GrammarError,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    bound_result,
    evidence,
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
    "IcPeripheryGrammar",
    "grammar",
]

NAME = "ic-periphery"

#: The role table, verbatim from 098 §一: the core, the part that ties two of its
#: pins together, the part that hangs one of its pins on a supply, and the two
#: nets that give the hanging parts a place to return to.
ROLES: tuple[str, ...] = ("core", "bridge", "shunt", "rail", "gnd")

#: How many pins a part must carry to be a candidate core at all (098 §一:
#: "脚数 > 2"). Two pins is the branch/bridge shape; the core is what they hang
#: off, so a circuit of two-terminal parts has no core in it.
MIN_CORE_PINS = 2

#: The two sides a single ``left-of``/``right-of`` can state. A declared side of
#: `top`/`bottom` says the signal leaves vertically, and neither kind carries it —
#: the evidence says so instead of inventing a horizontal statement.
_HORIZONTAL_SIDES: tuple[str, ...] = ("left", "right")

#: Where each fact came from, as the refusal and the evidence spell it.
_DECLARED_SOURCE = "modules[].core"
_INTENT_SOURCE = "intent blocks[]"
_PARTITION_SOURCE = "the partition"


class IcPeripheryGrammar:
    """098's ic-periphery grammar. Structural; the core comes from a stated fact."""

    name = NAME

    def __init__(self, profiles: Mapping[str, SymbolProfile] | None = None) -> None:
        # The profiles are read for one thing: the **drawing's orientation** — the
        # side a hanging part reads on is the side its core's own pin leaves in
        # (`_part_orientation`), and the symbol is where that direction is
        # written. Nothing else here reads the book: roles, clusters and the core
        # come from the partition and the documents. Taken as a construction input
        # for the same reason every grammar takes it (053 sec.3).
        self.profiles: dict[str, SymbolProfile] = dict(profiles or {})

    # -------------------------------------------------------------- binding

    def bind(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        *,
        intent: IntentSource | DesignIntent | None = None,
    ) -> GrammarResult:
        """Bind the core, its periphery and its supply references.

        ``intent`` is **optional and absent by default** (095 A4's seam): a bind
        handed no contract reads the same two documents it read before, and the
        core then comes from the declaration or from the partition.
        """
        scope_id, scope_parts = _scope(presentation)
        claims, conflict = _core_claims(
            circuit, presentation, intent, scope_id, scope_parts
        )
        if not claims:
            return refused_result([
                _no_core_failure(circuit, scope_id, scope_parts)
            ])
        # 098 §三: a source that names a part which cannot be a core is answered
        # *before* the sources are compared. "this name is not a part of this
        # circuit" and "the drawing and the partition name different parts" have
        # the same repair — fix the declaration — and the first one is the one a
        # reader can act on without weighing two statements.
        for part_id in sorted(claims):
            problem = _core_problem(circuit, part_id, scope_id, scope_parts)
            if problem is not None:
                return refused_result([problem])
        if conflict is not None:
            return refused_result([conflict])
        core = sorted(claims)[0] if len(claims) == 1 else ""

        core_nets = {net for net in pins_of_part(circuit, core).values()}
        power = nets_of_class(circuit, "power")
        ground = nets_of_class(circuit, "gnd")
        rail, gnd, supply_failures = _supply(circuit, core, core_nets, power, ground)
        if supply_failures:
            return refused_result(supply_failures)

        bridges, shunts, strays = _periphery(
            circuit, core, core_nets, rail, gnd, scope_parts
        )
        if strays:
            return refused_result([
                _stray_failure(circuit, core, part_id) for part_id in strays[:1]
            ])
        return self._result(
            circuit, presentation, claims[core], core, core_nets, rail, gnd,
            bridges, shunts, scope_id, scope_parts,
        )

    # ------------------------------------------------------------- internals

    def _result(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        claim: "_Claim",
        core: str,
        core_nets: set[str],
        rail: str,
        gnd: str,
        bridges: tuple[str, ...],
        shunts: tuple[str, ...],
        scope_id: str,
        scope_parts: tuple[str, ...],
    ) -> GrammarResult:
        """Everything bound, in the order the drawing reads it."""
        periphery = tuple(sorted(bridges + shunts))
        signals = _signals(circuit, core, core_nets, rail, gnd)
        pin_signals = core_nets - {rail, gnd}
        cluster_pairs = _cluster_pairs(circuit, pin_signals, bridges, shunts)
        orientation = _orientation_reading(
            self.profiles, circuit, core, presentation, signals
        )
        prov = weakest_provenance(
            part_provenance(circuit.part(core)),
            net_provenance(circuit, rail),
            net_provenance(circuit, gnd),
            *(part_provenance(circuit.part(part_id)) for part_id in periphery),
        )
        shape = _describe(rail, core, gnd, bridges, shunts)

        bindings: list[RoleBinding] = [
            RoleBinding(
                role="core",
                part_id=core,
                evidence=evidence(
                    "role=core: the part this drawing is arranged around — the "
                    "one fact this grammar cannot derive, because every part of a "
                    "module is a shape with pins and nothing about the partition "
                    "says which of them the others hang off",
                    claim.clause(),
                    part_clause(circuit, core),
                    f"pins on this module's two supplies: "
                    f"{_pin_on(circuit, core, rail) or '?'}→{rail}, "
                    f"{_pin_on(circuit, core, gnd) or '?'}→{gnd}",
                    f"the group this bind read: {shape}",
                    _scope_note(scope_id, scope_parts),
                    _partition_note(circuit, core),
                    _signal_note(circuit, signals, presentation),
                    orientation.note,
                    f"provenance={_core_provenance(prov, claim)}",
                ),
            ),
            RoleBinding(
                role="rail",
                part_id=rail,
                evidence=evidence(
                    "role=rail: the net of class 'power' this core's own pins sit "
                    "on — the supply this drawing references, drawn as a flag or "
                    "a label (069's rule) and not as a conductor here",
                    _spec_net_clause(circuit, rail),
                    f"members: {', '.join(_members(circuit, rail))}",
                    f"provenance={net_provenance(circuit, rail)}",
                ),
            ),
            RoleBinding(
                role="gnd",
                part_id=gnd,
                evidence=evidence(
                    "role=gnd: the net of class 'gnd' this core's own pins sit on "
                    "— every hanging part of this module returns to it",
                    _spec_net_clause(circuit, gnd),
                    f"members: {', '.join(_members(circuit, gnd))}",
                    f"provenance={net_provenance(circuit, gnd)}",
                ),
            ),
        ]
        for part_id in periphery:
            role = "bridge" if part_id in bridges else "shunt"
            bindings.append(
                RoleBinding(
                    role=role,
                    part_id=part_id,
                    evidence=evidence(
                        _role_sentence(
                            circuit, role, part_id, core, pin_signals, rail, gnd
                        ),
                        part_clause(circuit, part_id),
                        f"core pins this part reads off: "
                        + (", ".join(sorted(
                            set(_part_nets(circuit, part_id).values()) & core_nets
                        )) or "none"),
                        "cluster: " + _cluster_note(
                            circuit, pin_signals, periphery, part_id
                        ),
                        f"provenance={_binding_provenance(circuit, part_id, prov, claim)}",
                    ),
                )
            )

        constraints: list[RelativeConstraint] = []
        for part_id in periphery:
            constraints.append(
                RelativeConstraint(
                    kind=NEAR,
                    subject=part_id,
                    object=core,
                    reason=(
                        f"098 sec.2: {part_id} hangs off its own pin of {core} and "
                        "reads as this IC's local topology — beside the part it "
                        "belongs to, not across a module boundary (052 sec.5)"
                    ),
                )
            )
            part_side = _part_orientation(
                self.profiles, circuit, core, part_id, pin_signals,
                orientation.flip,
            )
            if part_side is not None:
                kind, side, why = part_side
                constraints.append(
                    RelativeConstraint(
                        kind=kind,
                        subject=part_id,
                        object=core,
                        reason=(
                            f"098 sec.2: {part_id} hangs off its own pin of "
                            f"{core}, and the symbol draws that pin {side}-ward "
                            f"({why}) — the part reads on the side its pin leaves "
                            "by, which is also the drawing's orientation: the "
                            "cross-module signals of this group leave on their "
                            "declared sides, and a core turned round would carry "
                            "them to the other side. Measured: without this "
                            "statement the compiler's own two mirror variants both "
                            "survive (the label of a one-pin net is put at its pin, "
                            "and that side follows the pose)"
                        ),
                    )
                )
        for bridge_id in bridges:
            for shunt_id in cluster_pairs.get(bridge_id, ()):
                if _anchor(circuit, bridge_id, pin_signals) != _anchor(
                    circuit, shunt_id, pin_signals
                ):
                    # 098 §二, measured: the kind says "nothing stands between
                    # them on one line", and a pair that hangs off two different
                    # core pins is one pin-pitch apart laterally — which the
                    # check reads as *not* adjacent. The cluster's second load
                    # capacitor hangs off the bridge's other pin, and the
                    # evidence's `cluster:` clause is where that membership is
                    # stated (the compiler's `_points_for_relation` measures
                    # origins here, and the two origins are a pin pitch apart).
                    continue
                constraints.append(
                    RelativeConstraint(
                        kind=ADJACENT,
                        subject=bridge_id,
                        object=shunt_id,
                        reason=(
                            f"098 sec.2: {bridge_id} and {shunt_id} are one cluster "
                            "— they hang off one pin net of "
                            f"{core} (the net the partition gives the bridge as its "
                            "anchor), so they stand next to each other on that line "
                            f"and {bridge_id} is the one nearer the pin (a load "
                            "capacitor belongs on the pins its crystal reads, and "
                            "which part is which is read from the partition, never "
                            "from a designator or a value)"
                        ),
                    )
                )
        for net_id in signals:
            orientation = _orientation(presentation, net_id)
            if orientation is not None:
                kind, side, why = orientation
                constraints.append(
                    RelativeConstraint(
                        kind=kind,
                        subject=net_id,
                        object=core,
                        reason=(
                            f"098 sec.2: {net_id} is a cross-module signal of this "
                            f"drawing — the core {core} states it on its own pin and "
                            f"the presentation declares it leaves on the {side} side "
                            f"({why}), so the signal stands on the {side} of the "
                            "core. The side is the declared one: this grammar "
                            "invents no direction"
                        ),
                    )
                )

        obligations: list[GrammarObligation] = [
            GrammarObligation(
                kind=OWNED_BRANCH,
                nets=(rail,),
                reason=(
                    "098 sec.2: "
                    + (", ".join(periphery) if periphery else "no hanging part")
                    + f" read as parts owned by the core {core} — each attached to "
                    "the pin it belongs to, not crossing into another module"
                ),
            ),
            GrammarObligation(
                kind=UNIFORM_GND,
                nets=(gnd,),
                reason=(
                    "098 sec.2: this module's ground is expressed one way "
                    "throughout — one symbol style or one label, never mixed"
                ),
            ),
        ]
        return bound_result(bindings, constraints, obligations)


GRAMMAR = IcPeripheryGrammar


def grammar(
    profiles: Mapping[str, SymbolProfile] | None = None,
) -> IcPeripheryGrammar:
    """An ic-periphery grammar, optionally holding the library profiles."""
    return IcPeripheryGrammar(profiles)


# ------------------------------------------------------------- the core fact


@dataclass(frozen=True)
class _Claim:
    """One source saying which part is the core (098 sec.1).

    ``clause()`` is what the evidence prints and what a refusal quotes: the
    source, the place it was written, the statement **as written**, and who said
    it — the four things a reader needs to check the binding without opening the
    file (052 sec.4's discipline, and 095 §一.2's for a contract entry).
    """

    part_id: str
    source: str
    where: str
    text: str
    provenance: str
    path: str = ""

    def clause(self) -> str:
        """The original, quoted: 出处 + 原文 + 来源."""
        tail = f" (provenance={self.provenance})" if self.provenance else ""
        here = f", read from the contract {self.path}" if self.path else ""
        return f"{self.source} says the core is {self.part_id!r}: {self.text!r}{here}{tail}"


def _scope(
    presentation: PresentationSpec,
) -> tuple[str, tuple[str, ...]]:
    """``(module id, its parts)`` — the group this bind draws, or ``("", ())``.

    A drawing is one group (053 stage C compiles each module on its own), and the
    declaration that names the core is the strongest statement about which group
    it is: a presentation whose module states a core is drawing *that* module.
    With no such statement and exactly one declared module, the group is that
    module; otherwise the bind draws the whole circuit, which is what an
    undeclared presentation has always meant.
    """
    modules = [module for module in presentation.modules if module.parts]
    if not modules:
        return "", ()
    claimants = [module for module in modules if module.core]
    if len(claimants) == 1:
        return claimants[0].id, tuple(claimants[0].parts)
    if len(modules) == 1:
        return modules[0].id, tuple(modules[0].parts)
    return "", ()


def _core_claims(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    intent: IntentSource | DesignIntent | None,
    scope_id: str,
    scope_parts: tuple[str, ...],
) -> tuple[dict[str, _Claim], GrammarFailure | None]:
    """Every source that says which part is the core (098 sec.1).

    Returns the claims keyed by part id, and — when the sources disagree — the
    refusal that quotes all of them. A source that says nothing contributes
    nothing; two sources that say the same thing are one claim with two
    originals, and both are printed.
    """
    claims: dict[str, _Claim] = {}
    for module in presentation.modules:
        if not module.core:
            continue
        claims.setdefault(module.core, _Claim(
            part_id=module.core,
            source=_DECLARED_SOURCE,
            where=f"modules[{module.id}].core",
            text=f"modules[{module.id}].core = {module.core!r}",
            provenance="",
        ))
    document, path = _intent_document(intent)
    if document is not None:
        for block in document.blocks:
            multi = [
                part_id
                for part_id in sorted(set(block.parts))
                if _in_scope(part_id, scope_parts)
                and _pin_count(circuit, part_id) > MIN_CORE_PINS
            ]
            if len(multi) != 1:
                # A block that names two multi-pin parts names a group, not a
                # core: "which of these is the one the others hang off" is
                # exactly what it did not say.
                continue
            claims.setdefault(multi[0], _Claim(
                part_id=multi[0],
                source=_INTENT_SOURCE,
                where=f"blocks[id={block.id!r}].parts",
                text=(
                    f"blocks[id={block.id!r}].parts = {list(block.parts)!r}"
                    + (f", kind={block.kind!r}" if block.kind else "")
                ),
                provenance=block.provenance,
                path=path,
            ))
    structural, note = _structural_core(circuit, scope_parts)
    if structural:
        claims.setdefault(structural, _Claim(
            part_id=structural,
            source=_PARTITION_SOURCE,
            where="the partition (CircuitSpec.nets[].members)",
            text=note,
            provenance="",
        ))
    if len({claim.part_id for claim in claims.values()}) > 1:
        return claims, _conflict_failure(circuit, scope_id, claims)
    return claims, None


def _structural_core(
    circuit: CircuitSpec, scope_parts: tuple[str, ...]
) -> tuple[str, str]:
    """``(part id, its original)`` for a unique strict pin-count maximum.

    The reading is the stated pins of each part — what the `CircuitSpec` says
    about the part, never what a library symbol or a package name suggests — and
    the answer is a part that carries more pins than *every* other part here,
    with that maximum above :data:`MIN_CORE_PINS`. A tie, or a maximum of two
    pins, is not a core: it is the case the declaration channel exists for.
    """
    counts = {
        part_id: _pin_count(circuit, part_id)
        for part_id in _candidates(circuit, scope_parts)
    }
    if not counts:
        return "", ""
    best = max(counts.values())
    if best <= MIN_CORE_PINS:
        return "", ""
    top = sorted(part_id for part_id, count in counts.items() if count == best)
    if len(top) != 1:
        return "", ""
    others = ", ".join(
        f"{part_id}={counts[part_id]}" for part_id in sorted(counts)
        if part_id != top[0]
    )
    return top[0], (
        f"the partition gives {top[0]} {best} stated pins, more than every other "
        f"part here ({others or 'no other part'})"
    )


def _candidates(
    circuit: CircuitSpec, scope_parts: tuple[str, ...]
) -> tuple[str, ...]:
    """The parts the core may be read from, in id order."""
    if scope_parts:
        return tuple(sorted(scope_parts))
    return tuple(sorted(part.id for part in circuit.parts))


def _in_scope(part_id: str, scope_parts: tuple[str, ...]) -> bool:
    return not scope_parts or part_id in scope_parts


def _pin_count(circuit: CircuitSpec, part_id: str) -> int:
    """How many pins the spec states for this part (never a symbol's pin count)."""
    return len(pins_of_part(circuit, part_id))


def _conflict_failure(
    circuit: CircuitSpec, scope_id: str, claims: dict[str, _Claim]
) -> GrammarFailure:
    """Three sources, more than one answer: quote them all, decide nothing."""
    originals = "; ".join(claims[part_id].clause() for part_id in sorted(claims))
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject=sorted(claims)[0],
        detail=(
            "the sources of this drawing's core disagree: " + originals + ". Which "
            "part the drawing is arranged around is one fact, stated once — this "
            "grammar does not rank one source above another, because picking one "
            "would be it grading the sheet against the contract the sheet was "
            "written from (A3a R1's rule, on the drawing side). One of them is "
            "wrong and a person says which"
        ),
        action=(
            "reconcile them: write modules["
            + (scope_id or "<module>")
            + "].core as the part the group really hangs off, or correct the pin "
            "counts the partition reads in CircuitSpec.nets[].members, or change "
            "the intent block's parts — the grammar keeps every original above so "
            "the choice is made on the statements, not on this refusal"
        ),
    )


def _no_core_failure(
    circuit: CircuitSpec,
    scope_id: str,
    scope_parts: tuple[str, ...],
) -> GrammarFailure:
    """Nobody said, and the partition is ambiguous: name both places to write it."""
    counts = {
        part_id: _pin_count(circuit, part_id)
        for part_id in _candidates(circuit, scope_parts)
    }
    best = max(counts.values(), default=0)
    top = sorted(part_id for part_id, count in counts.items() if count == best)
    if best <= MIN_CORE_PINS:
        why = (
            "no part of this drawing carries more than "
            f"{MIN_CORE_PINS} pins ({_counts_text(counts)}) — every part here is "
            "the shape a peripheral has, and a peripheral is what hangs off a core"
        )
    else:
        why = (
            f"{len(top)} parts share the highest pin count of {best} "
            f"({_counts_text(counts)}), so which of them the others hang off is "
            "not in the partition"
        )
    module = scope_id or "<the module that draws this group>"
    return GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject=top[0] if len(top) == 1 else "",
        detail=(
            "the core of this drawing is not stated and cannot be derived: "
            + why
        ),
        action=(
            f"state which part is the core — write modules[{module}].core = "
            "'<the part id>' in the PresentationSpec (or the same fact as an "
            "intent blocks[] entry whose parts list exactly this drawing's "
            "multi-pin part)"
        ),
    )


def _counts_text(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{part_id}={counts[part_id]}" for part_id in sorted(counts))


def _core_problem(
    circuit: CircuitSpec,
    core: str,
    scope_id: str,
    scope_parts: tuple[str, ...],
) -> GrammarFailure | None:
    """Why the stated core cannot be one, or ``None`` when it can."""
    part = circuit.part(core)
    if part is None:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=core,
            detail=(
                f"the drawing states {core!r} as its core, and this CircuitSpec "
                f"does not declare it ({_counts_text({p.id: _pin_count(circuit, p.id) for p in circuit.parts})}) "
                "— a core that does not exist is not a part the others hang off"
            ),
            action=(
                f"write {core!r} as a part of the circuit, or point the core at a "
                "part this circuit declares"
            ),
        )
    if scope_parts and core not in scope_parts:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=core,
            detail=(
                f"the drawing states {core!r} as its core, and modules[{scope_id}]"
                f".parts does not list it ({', '.join(scope_parts)}) — the group "
                "that draws this core has to contain it, or the periphery is read "
                "from the wrong parts"
            ),
            action=(
                f"add {core!r} to modules[{scope_id}].parts, or point "
                f"modules[{scope_id}].core at a part this module lists"
            ),
        )
    pins = pins_of_part(circuit, core)
    if len(pins) <= MIN_CORE_PINS:
        where = ", ".join(f"{pin}→{net}" for pin, net in sorted(pins.items()))
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=core,
            detail=(
                f"the drawing states {core!r} as its core, but the spec gives it "
                f"{len(pins)} stated pin(s)"
                + (f" ({where})" if where else " (no connection stated)")
                + " — a core is what the peripherals hang off, and a part of two "
                "pins or fewer is itself a peripheral, not the part the drawing is "
                "arranged around"
            ),
            action=(
                f"state {core!r}'s pins in CircuitSpec.nets[].members, or name the "
                "part this drawing is really arranged around as the core"
            ),
        )
    return None


# ----------------------------------------------------------- supply / periphery


def _supply(
    circuit: CircuitSpec,
    core: str,
    core_nets: set[str],
    power: tuple[str, ...],
    ground: tuple[str, ...],
) -> tuple[str, str, list[GrammarFailure]]:
    """``(rail, gnd, failures)`` — the two supply references, from the core's pins.

    The classes are read the way `rc-lowpass` reads them (a net that states
    nothing is class `signal`), and *which* net of the class belongs to this
    drawing is read from the core's own pins: a page may carry several power
    nets, and the one that matters is the one this part is on. The id sorted
    first is a tie-break, not a claim, and the evidence prints the members.
    """
    failures: list[GrammarFailure] = []
    if not power:
        failures.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'power': this drawing references the supply "
                    "this core runs from, and the grammar has to be told which net "
                    "that is"
                ),
                action=(
                    "write the class in CircuitSpec.nets[].class — a net that "
                    "states nothing is class 'signal', which is not a supply"
                ),
            )
        )
    if not ground:
        failures.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'gnd': the hanging parts of this drawing "
                    "return to ground, and the grammar has to be told which net "
                    "that is"
                ),
                action=(
                    "write the class in CircuitSpec.nets[].class — a net that "
                    "states nothing is class 'signal', which is not ground"
                ),
            )
        )
    if failures:
        return "", "", failures
    rail = _net_on_core(circuit, core, core_nets, power, "power")
    gnd = _net_on_core(circuit, core, core_nets, ground, "gnd")
    if rail is None:
        failures.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=core,
                detail=(
                    f"the core {core} sits on no net of class 'power' (its stated "
                    f"pins are on {_core_nets_text(circuit, core, core_nets)}) — "
                    "the supply exists on this page, but not on this part, so the "
                    "drawing has no rail to reference"
                ),
                action=(
                    f"state {core}'s supply pin on the power net it runs from in "
                    "CircuitSpec.nets[].members"
                ),
            )
        )
    if gnd is None:
        failures.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=core,
                detail=(
                    f"the core {core} sits on no net of class 'gnd' (its stated "
                    f"pins are on {_core_nets_text(circuit, core, core_nets)}) — "
                    "the parts hanging off it have no return path to read"
                ),
                action=(
                    f"state {core}'s ground pin on the ground net in "
                    "CircuitSpec.nets[].members"
                ),
            )
        )
    return rail or "", gnd or "", failures


def _net_on_core(
    circuit: CircuitSpec,
    core: str,
    core_nets: set[str],
    nets: tuple[str, ...],
    cls: str,
) -> str | None:
    """The id-sorted first net of this class the core's own pins sit on."""
    found = [net_id for net_id in nets if net_id in core_nets]
    return found[0] if found else None


def _core_nets_text(
    circuit: CircuitSpec, core: str, core_nets: set[str]
) -> str:
    pins = pins_of_part(circuit, core)
    return ", ".join(
        f"{pin}→{net}" for pin, net in sorted(pins.items())
    ) or "no connection stated"


def _periphery(
    circuit: CircuitSpec,
    core: str,
    core_nets: set[str],
    rail: str,
    gnd: str,
    scope_parts: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """``(bridges, shunts, strays)`` — every two-terminal part of this drawing.

    Three shapes and nothing else (098 sec.1):

    * ``bridge`` — both nets are the core's own pin nets and neither is the rail
      or the ground: the part that ties two of the core's pins together;
    * ``shunt`` — one pin on a core pin net, the other on the rail or the ground;
    * ``stray`` — no pin on any core pin net at all: not this core's periphery,
      and a refusal rather than a silently unbound part (098 sec.三).

    A part that touches a core pin net but is neither shape — one pin on the core
    and the other on a net nothing else here shares, the series element of a
    signal path — is **left unbound**: this grammar's role table has no name for
    a signal path, and inventing one would be inventing a promise 053 sec.3 never
    made.
    """
    signals = core_nets - {rail, gnd}
    edges = two_terminal_parts(circuit)
    bridges: list[str] = []
    shunts: list[str] = []
    strays: list[str] = []
    for part_id in sorted(edges):
        if part_id == core or not _in_scope(part_id, scope_parts):
            continue
        here = set(edges[part_id])
        if here and here <= signals:
            bridges.append(part_id)
        elif here & {rail, gnd} and (here - {rail, gnd}) <= signals:
            shunts.append(part_id)
        elif not (here & core_nets):
            strays.append(part_id)
    return tuple(bridges), tuple(shunts), tuple(strays)


def _stray_failure(
    circuit: CircuitSpec, core: str, part_id: str
) -> GrammarFailure:
    """A part of this module that touches none of the core's pins."""
    pins = pins_of_part(circuit, part_id)
    where = ", ".join(f"{pin}→{net}" for pin, net in sorted(pins.items()))
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject=part_id,
        detail=(
            f"{part_id} is a two-terminal part of this drawing and it touches no "
            f"pin net of the core {core} (its connections: "
            f"{where or 'none stated'}) — it is not this core's periphery, so the "
            "drawing has no pin of the core to hang it off; another module's parts "
            "are that module's business"
        ),
        action=(
            f"state {part_id}'s connections so one end lands on a pin net of "
            f"{core} (or on its rail/ground), or leave {part_id} to the module it "
            "belongs to"
        ),
    )


def _signal_nets(
    circuit: CircuitSpec, part_id: str, signals: set[str]
) -> frozenset[str]:
    """This part's own nets that are core pin nets and not the rail/ground."""
    return frozenset(set(_part_nets(circuit, part_id).values()) & signals)


def _anchor(circuit: CircuitSpec, part_id: str, signals: set[str]) -> str:
    """The core pin net this part hangs off, as the compiler reads it.

    ``drawcompiler._shared_nets`` anchors a branch on the shared net that is not
    the return path, id-sorted first when there are two candidates — so a part
    across two of the core's pins (a crystal) hangs off the first of them, and a
    part with one pin on the core and one on the rail hangs off the core-side
    one. The grammar has to read the same rule for the two facts that depend on
    it: which parts stand on one line, and whether a pair can be *adjacent* at
    all (below).
    """
    found = sorted(_signal_nets(circuit, part_id, signals))
    return found[0] if found else ""


def _cluster_pairs(
    circuit: CircuitSpec,
    signals: set[str],
    bridges: tuple[str, ...],
    shunts: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    """``bridge id -> the shunts it shares a core pin net with`` (098 sec.1).

    A cluster is a set of periphery parts tied together by shared core pin nets
    that are neither the rail nor the ground — the crystal and its two load
    capacitors. The pairing a constraint needs is narrower than the cluster: the
    parts that share a net with *this* bridge, which is the statement "they hang
    off the pins this part reads". A part that reaches the same cluster through
    another part is not paired with this one.
    """
    nets = {
        part_id: _signal_nets(circuit, part_id, signals)
        for part_id in (*bridges, *shunts)
    }
    return {
        bridge_id: tuple(
            shunt_id
            for shunt_id in shunts
            if nets[bridge_id] & nets[shunt_id]
        )
        for bridge_id in bridges
    }


def _signals(
    circuit: CircuitSpec, core: str, core_nets: set[str], rail: str, gnd: str
) -> tuple[str, ...]:
    """Every cross-module signal of this drawing, in id order.

    A signal here is a net the module carries at **one** pin and names at the
    boundary: the core states it on its own pin and nothing else in the drawing
    is on it. Power and ground are not signals (they are the supply references),
    and a net two parts share is a local connection, not a label.
    """
    out: list[str] = []
    for net in circuit.nets:
        if net.id in (rail, gnd) or net.cls in ("power", "gnd"):
            continue
        if len(net.members) != 1:
            continue
        owner, _, _pin = net.members[0].partition(".")
        if owner != core or net.id not in core_nets:
            continue
        out.append(net.id)
    return tuple(sorted(out))


def _orientation(
    presentation: PresentationSpec, net_id: str
) -> tuple[str, str, str] | None:
    """``(kind, side, why)`` for a declared cross-module signal, or ``None``.

    The direction is the presentation's own ``portRoles[net]`` (053 sec.2's
    vocabulary for what a net *is* at the boundary) and the side is its
    ``sidePreferences`` entry for that direction. Nothing is invented: a signal
    with no declared direction, and a direction whose side is vertical, get no
    horizontal kind — the evidence says what was declared and what was not.
    """
    direction = presentation.port_roles.get(net_id, "")
    if not direction:
        return None
    side = presentation.side_for(direction)
    if side not in _HORIZONTAL_SIDES:
        return None
    kind = LEFT_OF if side == "left" else RIGHT_OF
    return kind, side, f"portRoles[{net_id!r}]={direction!r}, sidePreferences[{direction!r}]={side!r}"


def _part_orientation(
    profiles: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    core: str,
    part_id: str,
    signals: set[str],
    flip: int,
) -> tuple[str, str, str] | None:
    """``(kind, side, why)`` for the side a hanging part reads on, or ``None``.

    Read from the symbol the drawing uses: the **core's own pin** on the net this
    part hangs off, and that pin's escape direction — the branch is placed on the
    side the owner's pin leaves in (``drawcompiler._branch_offset_direction``) —
    **turned round when the drawing is** (``flip``, :func:`_orientation_reading`:
    the group's declared cross-module signals decide which of the two mirror
    poses the drawing takes).

    A pin that leaves left or right states a horizontal side; a pin that leaves
    up or down states none, because what the drawing can do is flip in x and a
    vertical pin is not moved by it (a decoupling capacitor stays above the pin
    it serves either way). No profile, no pin, or no direction is **not a
    statement** (052 sec.4): nothing is said and nothing is guessed.

    This is the drawing's *orientation*, and the statement is what carries it: a
    label of a one-pin net is put at its pin, and the branch is placed off its
    pin, so both follow the pose the compiler picks — and the compiler's own
    ranking will happily hand back the mirrored pose (measured on this batch's
    sample: the mirror variants differ only in the compactness layer, 185554 vs
    188081 units², and the mirrored one wins). A statement about a *part* is
    measurable — `_points_for_relation` resolves part origins and shared pins,
    and never a net — so the parts are where the declaration becomes a picture:
    the pose that puts them on the declared sides is the only one the gate keeps.
    """
    core_part = circuit.part(core)
    profile = profiles.get(core_part.symbol_ref) if core_part is not None else None
    if profile is None:
        return None
    anchor = _anchor(circuit, part_id, signals)
    token = _pin_on(circuit, core, anchor) if anchor else ""
    pin = _pin_of_token(profile, token)
    if pin is None or pin.direction not in _HORIZONTAL_SIDES:
        return None
    side = _turned(pin.direction) if flip else pin.direction
    kind = LEFT_OF if side == "left" else RIGHT_OF
    return kind, side, (
        f"SymbolProfile {profile.symbol_ref!r}: the core's pin "
        f"{pin.number or pin.name} ({token}→{anchor}) leaves {pin.direction}"
        + (" and the drawing is read turned round" if flip else "")
        + f", so {part_id} hangs off that pin on the {side}"
    )


def _turned(side: str) -> str:
    """The other horizontal side — what a mirrored core does to every pin."""
    return "right" if side == "left" else "left"


#: What a signal's declared side says about the drawing's own orientation.
_ORIENTATION_NOTE = (
    "the drawing's orientation, read from this group's declared cross-module "
    "signals: "
)
_ORIENTATION_CONFLICT = (
    "the drawing's orientation cannot be read from the declared cross-module "
    "signals — they do not agree on one, and a drawing has one orientation: "
)


@dataclass(frozen=True)
class _Orientation:
    """Which mirror of its own symbol this drawing is read in (098 §二).

    ``flip`` is 1 when the core is drawn turned round and 0 when it is drawn as
    the symbol has it. ``note`` is the evidence clause — including the case where
    the declarations contradict each other, which is said rather than refused:
    the declared side is a statement about the *page* (which module the signals
    talk to), and a module compiled on its own has no page to check it against.
    """

    flip: int
    note: str


def _orientation_reading(
    profiles: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    core: str,
    presentation: PresentationSpec,
    signals: tuple[str, ...],
) -> _Orientation:
    """The mirror the group's declared signals ask for, or the symbol's own.

    Each declared signal states a side, and the symbol's own pin for that net
    stands on a side of its own: the two agree in one of the two mirror poses and
    disagree in the other, so the declaration *picks* the pose — the one thing a
    declaration can do about a drawing that is a mirror of itself. Measured: with
    the sample's sides the un-mirrored pose is the only one that survives the
    gate, and swapping the two declared sides leaves only the mirrored pose.
    """
    core_part = circuit.part(core)
    profile = profiles.get(core_part.symbol_ref) if core_part is not None else None
    wanted: dict[str, str] = {}
    for net_id in signals:
        declared = _orientation(presentation, net_id)
        if declared is not None:
            wanted[net_id] = declared[1]
    if not wanted or profile is None:
        return _Orientation(0, "")
    flips: dict[str, int] = {}
    for net_id in sorted(wanted):
        token = _member_token(circuit, net_id)
        pin = _pin_of_token(profile, token)
        if pin is None or pin.direction not in _HORIZONTAL_SIDES:
            continue
        flips[net_id] = 0 if pin.direction == wanted[net_id] else 1
    if not flips:
        return _Orientation(0, "")
    if len(set(flips.values())) > 1:
        stated = "; ".join(
            f"{net_id} is declared {wanted[net_id]} and the symbol's own pin "
            f"leaves {_pin_of_token(profile, _member_token(circuit, net_id)).direction}"
            for net_id in sorted(flips)
        )
        return _Orientation(
            0,
            _ORIENTATION_CONFLICT
            + stated
            + " — so the drawing keeps the orientation the symbol itself has, "
            "and which of the two statements is wrong is a person's call",
        )
    flip = sorted(flips.values())[0]
    stated = ", ".join(
        f"{net_id}: declared {wanted[net_id]}, the symbol's own pin leaves "
        f"{_pin_of_token(profile, _member_token(circuit, net_id)).direction}"
        for net_id in sorted(flips)
    )
    return _Orientation(
        flip,
        _ORIENTATION_NOTE
        + stated
        + (
            " — the declared sides are the symbol's own, so the core is drawn as "
            "the symbol has it"
            if not flip else
            " — so the core is drawn turned round, which is the pose that leaves "
            "them on the sides the presentation declares"
        ),
    )


def _member_token(circuit: CircuitSpec, net_id: str) -> str:
    """The spec pin token of a one-member net (its member is ``<part>.<pin>``)."""
    net = circuit.net(net_id)
    if net is None or len(net.members) != 1:
        return ""
    _part, _, token = net.members[0].partition(".")
    return token


def _pin_of_token(profile: SymbolProfile, token: str):
    """The profile pin a spec token names: by number first, then by name.

    The same rule `drawcompiler._pin_of_token` and `grammar.base.profile_pin_for`
    apply, for the same reason: a spec writes ``<partId>.<pin>`` with whatever
    token the symbol uses.
    """
    if not token:
        return None
    found = profile.pin(token)
    if found is not None:
        return found
    for pin in profile.pins:
        if pin.name == token:
            return pin
    return None


# ------------------------------------------------------------------- clauses


def _role_sentence(
    circuit: CircuitSpec,
    role: str,
    part_id: str,
    core: str,
    signals: set[str],
    rail: str,
    gnd: str,
) -> str:
    nets = sorted(_signal_nets(circuit, part_id, signals))
    if role == "bridge":
        return (
            f"role=bridge: a two-terminal part across two pin nets of the core "
            f"{core} ({', '.join(nets) or 'its own two nets'}) — neither of them "
            "the rail or the ground, so it ties two of the core's pins together"
        )
    return (
        f"role=shunt: a two-terminal part from one pin net of the core {core} to "
        f"the rail {rail} or the ground {gnd}, read from the nets and not from a "
        "designator prefix, a value or a package name"
    )


def _scope_note(scope_id: str, scope_parts: tuple[str, ...]) -> str:
    if not scope_id:
        return ""
    return (
        f"the drawing's declared group: modules[{scope_id}].parts = "
        f"{list(scope_parts)}"
    )


def _partition_note(circuit: CircuitSpec, core: str) -> str:
    return (
        f"the partition gives {core} {_pin_count(circuit, core)} stated pin(s), "
        "which is what the structural reading compares"
    )


def _signal_note(
    circuit: CircuitSpec,
    signals: tuple[str, ...],
    presentation: PresentationSpec,
) -> str:
    """What this drawing's cross-module signals are, and what was declared of them.

    One clause, because it is the fact the drawing's *orientation* is read from:
    a signal with no declared direction is named as undeclared rather than left
    out — 052 sec.4's "absence is not a statement" reads as a fact a reader has
    to be able to see, or the missing side looks like a side nobody needed.
    """
    if not signals:
        return (
            "cross-module signals: none — every net this drawing carries is on a "
            "second pin of the group, so no boundary label is needed"
        )
    stated = []
    for net_id in signals:
        declared = _orientation(presentation, net_id)
        stated.append(
            f"{net_id} on the {declared[1]} ({declared[2]})" if declared
            else f"{net_id} (no declared direction — portRoles states none, so "
                 "this grammar states no side for it)"
        )
    return "cross-module signals of this drawing: " + "; ".join(stated)


def _cluster_note(
    circuit: CircuitSpec,
    signals: set[str],
    periphery: tuple[str, ...],
    part_id: str,
) -> str:
    """Which cluster this part stands in, spelled from the shared nets."""
    here = _signal_nets(circuit, part_id, signals)
    members = sorted(
        other for other in periphery
        if other == part_id or (here & _signal_nets(circuit, other, signals))
    )
    if len(members) < 2:
        return (
            f"{part_id} stands in a cluster of its own on "
            f"({', '.join(sorted(here)) or 'no pin net of its own'}) — no other "
            "hanging part of this drawing shares that pin net"
        )
    return (
        "{" + ", ".join(members) + "} share the pin net(s) "
        + (", ".join(sorted(here)) or "of this part")
    )


def _core_provenance(prov: str, claim: "_Claim") -> str:
    """The core binding's weakest fact, the contract's own entry included when there is one.

    Composed rather than passed unconditionally: `weakest_provenance` reads an
    empty value as `unstated`, which is weaker than every real provenance — so a
    claim that states none (a `modules[].core` line has no provenance of its own)
    would make every declared drawing look like a draft. The same composition
    `power_entry._binding_provenance` does for its branch claims.
    """
    if claim.provenance:
        return weakest_provenance(prov, claim.provenance)
    return prov


def _binding_provenance(
    circuit: CircuitSpec, part_id: str, prov: str, claim: _Claim
) -> str:
    """One part's weakest fact, the stated core included when it is a draft."""
    sources = [part_provenance(circuit.part(part_id)), prov]
    if claim.provenance:
        sources.append(claim.provenance)
    return weakest_provenance(*sources)


def _intent_document(
    intent: IntentSource | DesignIntent | None,
) -> tuple[DesignIntent | None, str]:
    """``(document, path)`` — the contract this bind reads, and where it came from.

    Both spellings are accepted because both reach a grammar naturally: the CLI
    hands over an :class:`IntentSource` (094's carrier — the document *and* the
    path a finding has to name), a test or an in-memory caller a bare
    :class:`DesignIntent`. A value that is neither is refused rather than
    ignored: a contract nothing can read would leave the drawing on its
    structural reading while the caller believes the contract was consumed.
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


def _pin_on(circuit: CircuitSpec, part_id: str, net_id: str) -> str:
    """The spec pin token of `part_id` that sits on `net_id`, or ``""``."""
    for pin, net in sorted(pins_of_part(circuit, part_id).items()):
        if net == net_id:
            return pin
    return ""


def _part_nets(circuit: CircuitSpec, part_id: str) -> dict[str, str]:
    """``spec pin token -> net id`` for this part (a reader, not a ruler)."""
    out: dict[str, str] = {}
    for net in circuit.nets:
        for member in net.members:
            owner, _, pin = member.partition(".")
            if owner == part_id and pin:
                out[pin] = net.id
    return out


def _members(circuit: CircuitSpec, net_id: str) -> tuple[str, ...]:
    net = circuit.net(net_id)
    return tuple(sorted(net.members)) if net is not None else ()


def _spec_net_clause(circuit: CircuitSpec, net_id: str) -> str:
    net = circuit.net(net_id)
    return net_clause(net) if net else f"net {net_id}: not declared in nets[]"


def _describe(
    rail: str,
    core: str,
    gnd: str,
    bridges: tuple[str, ...],
    shunts: tuple[str, ...],
) -> str:
    """``VCC→U1‖X1‖C1,C2,C3→GND`` — the spelling a report prints."""
    parts = [
        *[f"⟷{part_id}" for part_id in bridges],
        *[f"‖{part_id}" for part_id in shunts],
    ]
    return f"{rail}→{core}" + "".join(parts) + f"→{gnd}"
