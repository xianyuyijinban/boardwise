"""rc-lowpass: 053 sec.3's second grammar, executed.

The table (053 sec.3, verbatim):

    | rc-lowpass | series / shunt / in / out / gnd |
    in→R→out 主干水平；C 从 out 节点向下支路到地，视觉归属 out 节点（贴近不跨模块）|
    主干直连；支路直连 | 多 C 并联、R 换磁珠（同构）|

**The binding judgment, one level finer than the table.** `out` is not found by
name — it is found by the *shunt*:

1. `gnd` is a net whose `class` is `gnd`; the series element must be fed by a
   net whose `class` is `power` (a low-pass on a rail). Missing either class is
   a `facts-missing` refusal naming the class to write.
2. A **series** candidate is a two-terminal part whose two pins land on two
   *different*, *non-ground* nets `{A, B}` — the same "two-terminal, not shorted"
   reading the divider uses.
3. `out` is whichever of `A`/`B` also carries a **shunt**: a two-terminal part
   from that net to ground. The side with the shunt is the output, the other side
   is the input. That is the whole judgment: "C 从 out 节点向下支路到地" is what
   *defines* out, and it is why a bare series resistor with no shunt to ground on
   either end is refused (`circuit-invalid`, naming the dead end) instead of
   being drawn as a low-pass.
4. Every other two-terminal part from `out` to that same ground is a second
   `shunt` — 053 sec.3's "多 C 并联" variant, bound as several `shunt` roles
   rather than as a special case.
5. Candidate order (a stable tie-break, runners-up named in the evidence):
   power-class input first, then a candidate whose every part sits in one
   declared module, then the presentation's own port role for `out` saying
   output/source, then net ids. Where the presentation declares modules, shunts
   are only collected from the series part's module — a decoupling capacitor
   belonging to the *next* module is that module's business (052 sec.5).

`R 换磁珠` is not handled: it is the same judgment, because a ferrite bead is a
two-terminal part between the same two nets. Nothing in this module reads a
symbol name, a designator prefix or a value — the roles are structural.

**The constraints, spelled out.** The trunk is horizontal (the table fixes it:
"主干水平"), so the two part-level relations are:

* `same-row` between `series` and each `shunt`: the shunt's **out-side pin**
  lands on the trunk row and its body hangs below. The kind alone cannot say
  which end, which is why the reason string states it — a constraint is a
  relation, not a rectangle.
* `near` between a `shunt` and the `series` part: the branch belongs to the out
  node it hangs from, close enough to read as one local topology.

Which **end** is the input side comes from `sidePreferences.input`, so an
input-on-the-right drawing is the same binding with `out` on the left; the
grammar states the trunk relation either way and never a coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...core.circuitspec import CircuitSpec
from ...core.presentationspec import PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    NEAR,
    OWNED_BRANCH,
    SAME_ROW,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    bound_result,
    connected_net_sets,
    declares_modules,
    evidence,
    module_of_part,
    modules_of_part,
    net_clause,
    net_provenance,
    nets_of_class,
    part_clause,
    part_provenance,
    refused_result,
    shared_module,
    two_terminal_parts,
    weakest_provenance,
)

__all__ = [
    "GRAMMAR",
    "NAME",
    "ROLES",
    "RcLowpassGrammar",
    "grammar",
]

NAME = "rc-lowpass"

#: The role table, verbatim from 053 sec.3.
ROLES: tuple[str, ...] = ("series", "shunt", "in", "out", "gnd")


@dataclass(frozen=True)
class _Lowpass:
    """One candidate low-pass, as the walk found it."""

    in_net: str
    out_net: str
    gnd_net: str
    series: str
    shunts: tuple[str, ...]
    module: str = ""

    def describe(self) -> str:
        """``VIN→R1→OUT(‖C1,C2)→GND`` — the spelling a report prints."""
        branch = "‖" + ",".join(self.shunts) if self.shunts else ""
        return f"{self.in_net}→{self.series}→{self.out_net}{branch}→{self.gnd_net}"


class RcLowpassGrammar:
    """053 sec.3's rc-lowpass grammar."""

    name = NAME

    def __init__(self, profiles: Mapping[str, SymbolProfile] | None = None) -> None:
        # Structural judgment: nothing here reads the profiles. They are taken
        # for a uniform construction across the grammars.
        self.profiles: dict[str, SymbolProfile] = dict(profiles or {})

    # -------------------------------------------------------------- binding

    def bind(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        *,
        intent: object | None = None,
    ) -> GrammarResult:
        # 095 A4's contract is taken and not read: only `power-entry` states a
        # branch order a decision could place (088b's `branchOrder` is its own
        # field), so this grammar has no clause for a contract entry to fill —
        # accepted for the uniform signature the dispatcher calls with.
        power = nets_of_class(circuit, "power")
        ground = nets_of_class(circuit, "gnd")
        missing = _missing_class_failures(power, ground)
        if missing:
            return refused_result(missing)

        edges = two_terminal_parts(circuit)
        candidates = _candidates(circuit, presentation, edges, power, ground)
        if not candidates:
            return refused_result([_no_lowpass_failure(circuit, edges, power, ground)])
        return self._result(circuit, presentation, candidates)

    # ------------------------------------------------------------- internals

    def _result(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        candidates: list[_Lowpass],
    ) -> GrammarResult:
        lowpass = candidates[0]
        runners = _runner_up_note(candidates)
        prov = weakest_provenance(
            net_provenance(circuit, lowpass.in_net),
            net_provenance(circuit, lowpass.out_net),
            net_provenance(circuit, lowpass.gnd_net),
            part_provenance(circuit.part(lowpass.series)),
            *(part_provenance(circuit.part(part_id)) for part_id in lowpass.shunts),
        )
        in_side = presentation.side_for("input") or "left"
        out_side = presentation.side_for("output") or "right"

        bindings: list[RoleBinding] = [
            RoleBinding(
                role="series",
                part_id=lowpass.series,
                evidence=evidence(
                    "role=series: the two-terminal part whose pins land on "
                    f"{lowpass.in_net} and {lowpass.out_net}, the two nets of the "
                    "trunk (neither is ground — a part across ground is a shunt, "
                    "not a series element)",
                    part_clause(circuit, lowpass.series),
                    f"low-pass chosen: {lowpass.describe()}",
                    f"provenance={prov}",
                    runners,
                ),
            )
        ]
        for role, net_id, where in (
            ("in", lowpass.in_net, "the far end of the series element from the "
                                   "shunt (the side with no branch to ground)"),
            ("out", lowpass.out_net, "the end that carries the shunt to ground — "
                                     "that branch is what makes this node the output"),
            ("gnd", lowpass.gnd_net, "the net the shunt returns to"),
        ):
            bindings.append(
                RoleBinding(
                    role=role,
                    part_id=net_id,
                    evidence=evidence(
                        f"role={role}: {where}",
                        _spec_net_clause(circuit, net_id),
                        f"provenance={net_provenance(circuit, net_id)}",
                        runners,
                    ),
                )
            )

        constraints: list[RelativeConstraint] = []
        obligations: list[GrammarObligation] = [
            GrammarObligation(
                kind=DIRECT_WIRE,
                nets=(lowpass.in_net, lowpass.out_net),
                reason=(
                    "053 sec.3: the trunk in→series→out is wired on one row, "
                    f"input {in_side} / output {out_side} per sidePreferences — "
                    "the input is never read by chasing labels"
                ),
            ),
            GrammarObligation(
                kind=DIRECT_WIRE,
                nets=(lowpass.out_net, lowpass.gnd_net),
                reason="053 sec.3: the branch out→gnd is wired, not labelled",
            ),
            GrammarObligation(
                kind=OWNED_BRANCH,
                nets=(lowpass.out_net,),
                reason=(
                    "053 sec.3: the capacitor branch reads as owned by the out "
                    "node — visually attached, not a wire crossing into another "
                    "module"
                ),
            ),
        ]

        for shuttle in lowpass.shunts:
            bindings.append(
                RoleBinding(
                    role="shunt",
                    part_id=shuttle,
                    evidence=evidence(
                        f"role=shunt: a two-terminal part from the out node "
                        f"{lowpass.out_net} to ground {lowpass.gnd_net}",
                        part_clause(circuit, shuttle),
                        f"low-pass chosen: {lowpass.describe()}",
                        f"provenance={weakest_provenance(part_provenance(circuit.part(shuttle)), prov)}",
                        runners,
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=SAME_ROW,
                    subject=lowpass.series,
                    object=shuttle,
                    reason=(
                        f"053 sec.3: the trunk {lowpass.in_net}→{lowpass.series}→"
                        f"{lowpass.out_net} is one row, and {shuttle}'s "
                        f"{lowpass.out_net}-side pin lands on it (the shunt body "
                        "hangs below the row) — so the branch is read as leaving "
                        "the out node, not as a second trunk"
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=NEAR,
                    subject=shuttle,
                    object=lowpass.series,
                    reason=(
                        f"053 sec.3: {shuttle} hugs the out node it belongs to — "
                        f"near {lowpass.series}'s {lowpass.out_net} end, and not "
                        "across a module boundary"
                    ),
                )
            )

        # `input`/`output` side preferences decide which way the row runs (stated
        # in the trunk obligation's reason); the relation itself does not change,
        # which is why no constraint depends on the side.
        return bound_result(bindings, constraints, obligations)


GRAMMAR = RcLowpassGrammar


def grammar(
    profiles: Mapping[str, SymbolProfile] | None = None,
) -> RcLowpassGrammar:
    """An rc-lowpass grammar, optionally holding the library profiles."""
    return RcLowpassGrammar(profiles)


# ------------------------------------------------------------- the judgment


def _candidates(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    edges: dict[str, tuple[str, str]],
    power: tuple[str, ...],
    ground: tuple[str, ...],
) -> list[_Lowpass]:
    """Every reading of this circuit as one low-pass, canonically ordered."""
    ground_set = set(ground)
    found: list[_Lowpass] = []
    for series in sorted(edges):
        first, second = edges[series]
        if first in ground_set or second in ground_set:
            continue
        for in_net, out_net in ((first, second), (second, first)):
            # **One candidate per ground family.** The ground is pinned here and
            # carried into the reading, exactly as `power_entry._shunts` pins
            # its `gnd` and `ldo._caps_on` pins `core.gnd_net`: a shunt is a
            # part from `out` to *that* ground, and a page that returns two
            # branches to two different families is two readings, one of them
            # bound and the other named among the runners-up. Collecting a
            # union of families and then naming one of them in the evidence is
            # what made the second shunt's own binding claim a ground it does
            # not touch (143 H6), and it left the second family with no
            # `direct-wire` promise at all — a name the drawing never states.
            for gnd_net in ground:
                shunts = _shunts(edges, series, out_net, gnd_net)
                if declares_modules(presentation):
                    scope = module_of_part(presentation, series)
                    if scope:
                        shunts = tuple(
                            part_id
                            for part_id in shunts
                            if scope in modules_of_part(presentation, part_id)
                        )
                if not shunts:
                    continue
                module = shared_module(presentation, (series, *shunts))
                found.append(
                    _Lowpass(
                        in_net=in_net,
                        out_net=out_net,
                        gnd_net=gnd_net,
                        series=series,
                        shunts=shunts,
                        module=module,
                    )
                )
    found.sort(key=_candidate_key(power, presentation))
    return found


def _shunts(
    edges: dict[str, tuple[str, str]], series: str, out_net: str, gnd_net: str
) -> tuple[str, ...]:
    """Two-terminal parts from `out` to **this** ground net, sorted.

    `gnd_net` is a parameter rather than a set of "any ground-class net" so
    that the ground the evidence names is the ground the part is on — the same
    reading `power_entry._shunts` and `ldo._caps_on` take.
    """
    return tuple(
        part_id
        for part_id in sorted(edges)
        if part_id != series
        and out_net in edges[part_id]
        and gnd_net in edges[part_id]
    )


def _candidate_key(power: tuple[str, ...], presentation: PresentationSpec):
    """The tie-break: rail first, module next, the author's port role, then ids.

    A preference order, not a claim of correctness — when two readings remain,
    every binding's evidence names the runners-up, and `PresentationSpec.modules`
    is the intended way to remove the ambiguity (052 sec.5).

    `gnd_net` is in the key because it is a **part of the reading**: two
    candidates that differ only in which family the branch returns to are two
    readings, and leaving it out would let `list.sort`'s stability decide
    between them by the order the loops ran (143 H6 is that shape — an answer
    settled by an ordering nobody stated).
    """
    power_set = set(power)

    def key(candidate: _Lowpass):
        return (
            0 if candidate.in_net in power_set else 1,
            0 if candidate.module else 1,
            0 if _port_role(presentation, candidate.out_net) in ("output", "source")
            else 1,
            candidate.in_net,
            candidate.out_net,
            candidate.series,
            candidate.shunts,
            candidate.gnd_net,
        )

    return key


def _port_role(presentation: PresentationSpec, net_id: str) -> str:
    return presentation.port_roles.get(net_id, "")


def _missing_class_failures(
    power: tuple[str, ...], ground: tuple[str, ...]
) -> list[GrammarFailure]:
    out: list[GrammarFailure] = []
    if not ground:
        out.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'gnd': a low-pass needs the ground its branch "
                    "returns to, and the grammar has to be told which net that is"
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
                    "no net of class 'power': the series element is fed by a rail, "
                    "and the grammar has to be told which net that is"
                ),
                action="write the class in CircuitSpec.nets[].class (power)",
            )
        )
    return out


def _no_lowpass_failure(
    circuit: CircuitSpec,
    edges: dict[str, tuple[str, str]],
    power: tuple[str, ...],
    ground: tuple[str, ...],
) -> GrammarFailure:
    """Why no low-pass was found, naming the two shapes that matter."""
    ground_set = set(ground)
    series_only = sorted(
        part_id
        for part_id, nets in edges.items()
        if nets[0] not in ground_set and nets[1] not in ground_set
    )
    listing = _connection_listing(circuit, edges)
    if series_only:
        detail = (
            "a two-terminal part sits between two non-ground nets "
            f"({_named(edges, series_only)}), but neither of its ends carries a "
            "branch to ground: without a shunt the output node does not exist, so "
            "there is nothing for the grammar to call 'out'"
        )
        action = (
            "add the capacitor branch from the output side to ground, or check "
            "that the branch is really on the same net (a branch on a third net "
            "is a different topology, not a low-pass)"
        )
    else:
        detail = (
            "every two-terminal part reaches ground directly — there is no series "
            f"element between two non-ground nets: {listing}"
        )
        action = (
            "check the CircuitSpec connections of the series element (one end "
            "on the wrong net, or an unmentioned net), and that the rail is "
            f"declared as class=power (declared now: {list(power)})"
        )
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID, subject="", detail=detail, action=action
    )


def _named(edges: dict[str, tuple[str, str]], part_ids: list[str]) -> str:
    return ", ".join(f"{part_id}({','.join(edges[part_id])})" for part_id in part_ids)


def _connection_listing(circuit: CircuitSpec, edges: dict[str, tuple[str, str]]) -> str:
    items = [f"{part_id}({','.join(edges[part_id])})" for part_id in sorted(edges)]
    others = sorted(set(connected_net_sets(circuit)) - set(edges))
    items.extend(
        f"{part_id}({'/'.join(connected_net_sets(circuit)[part_id])})"
        for part_id in others[:4]
    )
    if len(items) > 12:
        return ", ".join(items[:12]) + f", … (+{len(items) - 12} more)"
    return ", ".join(items) or "no part states a connection"


def _spec_net_clause(circuit: CircuitSpec, net_id: str) -> str:
    net = circuit.net(net_id)
    return net_clause(net) if net else f"net {net_id}: not declared in nets[]"


def _runner_up_note(candidates: list[_Lowpass]) -> str:
    if len(candidates) < 2:
        return ""
    shown = "; ".join(candidate.describe() for candidate in candidates[1:5])
    more = "" if len(candidates) <= 5 else f"; +{len(candidates) - 5} more"
    return (
        "other low-pass readings found but not bound (this grammar instance bound "
        f"one): {shown}{more}"
    )
