"""voltage-divider: 053 sec.3's first grammar, executed.

The table (053 sec.3, verbatim):

    | voltage-divider | upper_arm / lower_arm / tap / in / gnd |
    两电阻竖排同轴，upper 上 lower 下，tap 中点水平引出 |
    in→upper→tap→lower→gnd 全链直连；抽头直接可见（stub+标签/端口） |
    横排镜像、多抽头、并联支路 |

**The binding judgment, one level finer than the table.** The table names the
roles; what decides which part plays which is a walk of the *net graph of
two-terminal parts*:

1. `gnd` is a net whose `class` is `gnd`, `in` is a net whose `class` is
   `power`. Those two facts are input the grammar cannot derive — a net that
   states neither is a `facts-missing` refusal naming the class to fill in (the
   spec's own default is `signal`, which is not a ground).
2. An **arm** is a part with exactly two mentioned pins on two *different* nets
   (:func:`~boardwise.engines.grammar.base.two_terminal_parts`): a part whose two
   pins sit on one net is a short, not an arm, and is never bound as one.
3. A **chain** is a simple path `in → … → gnd` through at least **two** arms. One
   arm between `in` and `gnd` is not a divider — it has no midpoint — and if both
   arms of a "divider" are wired that way they are in parallel, which is the
   `circuit-invalid` case this grammar reports by name.
4. The chain's first arm is `upper_arm` (the power-side end), the last is
   `lower_arm` (the ground-side end), every net strictly between two arms is a
   `tap`, and an arm strictly between the two ends is a `middle_arm` (the table
   has no name for it; see below).
5. Where the presentation declares `modules`, the whole chain must live inside
   one of them; a chain that spans two declared modules is refused with a
   `circuit-invalid` naming each arm's module (052 sec.5's "不跨模块", made
   checkable).

`upper_arm` means the **power-side end**, so when `sidePreferences` puts power at
the bottom or on a side the roles keep their meaning and the geometry follows
the intent: the axis becomes horizontal and the ordering kind `left-of` /
`right-of`. That is what makes 053 sec.3's "横排镜像" a variant of this grammar
rather than a second grammar, and why no scenario-specific constant is needed.

**Two role names the table does not have.** The table names the two end arms of
a two-arm divider; the multi-tap ladder and the parallel branch need names for
what they add, and having them is the difference between the compiler knowing a
part belongs to this grammar and it having to guess:

* `middle_arm` — an arm strictly between the two ends of a chain of three or
  more arms (053 sec.3 "多抽头"; without it such a ladder has an arm nobody
  named).
* `tap_branch` — a two-terminal part hanging on a tap net, other than the
  chain's own arms (053 sec.3 "并联支路").

Both are *additions to*, not replacements for, the table: `upper_arm`,
`lower_arm`, `tap`, `in`, `gnd` bind exactly as the table says, and `ROLES`
below is the table itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...core.circuitspec import CircuitSpec
from ...core.presentationspec import PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    ABOVE,
    BELOW,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    HORIZONTAL_TAP,
    LEFT_OF,
    MAX_CHAIN_ARMS,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_COLUMN,
    SAME_ROW,
    VERTICAL_TAP,
    VISIBLE_TAP,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    bound_result,
    connected_net_sets,
    declares_modules,
    evidence,
    modules_of_part,
    net_clause,
    net_provenance,
    nets_of_class,
    part_clause,
    part_provenance,
    refused_result,
    series_paths,
    shared_module,
    two_terminal_parts,
    weakest_provenance,
)

__all__ = [
    "EXTRA_ROLES",
    "GRAMMAR",
    "MIN_ARMS",
    "NAME",
    "ROLES",
    "VoltageDividerGrammar",
    "grammar",
]

NAME = "voltage-divider"

#: The role table, verbatim from 053 sec.3.
ROLES: tuple[str, ...] = ("upper_arm", "lower_arm", "tap", "in", "gnd")

#: Roles added by this batch for the variants the table lists but does not name.
#: Kept apart from `ROLES` so a reader sees the table intact.
EXTRA_ROLES: tuple[str, ...] = ("middle_arm", "tap_branch")

MIDDLE_ARM = "middle_arm"
TAP_BRANCH = "tap_branch"

#: A divider needs a midpoint: a single arm from power to ground is not one.
MIN_ARMS = 2


@dataclass(frozen=True)
class _Chain:
    """One in→gnd ladder, as the walk found it."""

    in_net: str
    gnd_net: str
    arms: tuple[str, ...]
    taps: tuple[str, ...]
    module: str = ""

    def describe(self) -> str:
        """``VIN→R1→TAP→R2→GND`` — the spelling a report prints."""
        steps: list[str] = [self.in_net]
        for index, arm in enumerate(self.arms):
            steps.append(arm)
            if index < len(self.taps):
                steps.append(self.taps[index])
        steps.append(self.gnd_net)
        return "→".join(steps)


class VoltageDividerGrammar:
    """053 sec.3's voltage-divider grammar."""

    name = NAME

    def __init__(self, profiles: Mapping[str, SymbolProfile] | None = None) -> None:
        # The divider's judgment is purely topological, so nothing here reads
        # the profiles; they are accepted for a uniform construction across the
        # three grammars, and carried for the compiler's own use.
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

        edges = two_terminal_parts(circuit)
        chains, failures = self._chains(presentation, edges, power, ground)
        if failures:
            return refused_result(failures)
        if not chains:
            return refused_result([_no_chain_failure(circuit, edges, power, ground)])
        return self._result(circuit, presentation, edges, chains)

    # ------------------------------------------------------------- internals

    def _chains(
        self,
        presentation: PresentationSpec,
        edges: dict[str, tuple[str, str]],
        power: tuple[str, ...],
        ground: tuple[str, ...],
    ) -> tuple[list[_Chain], list[GrammarFailure]]:
        """Every candidate ladder, canonically ordered, plus any refusal.

        Order: longer ladders first (a multi-tap ladder is the more specific
        reading of one rail), then by net and part id. It is a stable tie-break,
        not a claim that the first candidate is the only reading — the runners-up
        are named in every binding's evidence.
        """
        found: list[_Chain] = []
        for in_net in power:
            for gnd_net in ground:
                for arms, nets in series_paths(
                    edges, in_net, gnd_net, max_arms=MAX_CHAIN_ARMS
                ):
                    if len(arms) < MIN_ARMS:
                        continue
                    found.append(
                        _Chain(
                            in_net=in_net,
                            gnd_net=gnd_net,
                            arms=arms,
                            taps=nets[1:-1],
                            module=shared_module(presentation, arms),
                        )
                    )
        found.sort(
            key=lambda chain: (
                -len(chain.arms), chain.in_net, chain.gnd_net, chain.arms, chain.taps
            )
        )
        if declares_modules(presentation):
            scoped = [chain for chain in found if chain.module]
            if not scoped and found:
                return [], [_cross_module_failure(presentation, found[0])]
            found = scoped
        return found, []

    def _result(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        edges: dict[str, tuple[str, str]],
        chains: list[_Chain],
    ) -> GrammarResult:
        chain = chains[0]
        runners = _runner_up_note(chains)
        power_side = presentation.side_for("power") or "top"
        gnd_side = presentation.side_for("gnd") or "bottom"
        axis, order_kind, tap_kind = _orientation(power_side, gnd_side)
        chain_nets = (chain.in_net, *chain.taps, chain.gnd_net)
        prov = weakest_provenance(
            *(net_provenance(circuit, net_id) for net_id in chain_nets),
            *(part_provenance(circuit.part(arm)) for arm in chain.arms),
        )

        bindings: list[RoleBinding] = []
        constraints: list[RelativeConstraint] = []
        branch_constraints: list[RelativeConstraint] = []
        obligations: list[GrammarObligation] = []

        for index, arm in enumerate(chain.arms):
            role = _arm_role(index, len(chain.arms))
            bindings.append(
                RoleBinding(
                    role=role,
                    part_id=arm,
                    evidence=evidence(
                        f"role={role}: {_arm_clause(index, chain)}",
                        part_clause(circuit, arm),
                        f"chain chosen: {chain.describe()}",
                        f"provenance={prov}",
                        runners,
                    ),
                )
            )

        for role, net_id in (("in", chain.in_net), ("gnd", chain.gnd_net)):
            bindings.append(
                RoleBinding(
                    role=role,
                    part_id=net_id,
                    evidence=evidence(
                        f"role={role}: the "
                        f"{'power' if role == 'in' else 'ground'} end of the chain "
                        f"{chain.describe()}",
                        _spec_net_clause(circuit, net_id),
                        f"provenance={net_provenance(circuit, net_id)}",
                        runners,
                    ),
                )
            )

        for index, tap in enumerate(chain.taps):
            upper = chain.arms[index]
            lower = chain.arms[index + 1]
            branches = _branches(presentation, edges, chain, tap)
            bindings.append(
                RoleBinding(
                    role="tap",
                    part_id=tap,
                    evidence=evidence(
                        f"role=tap: the net between arm {index + 1} ({upper}) and "
                        f"arm {index + 2} ({lower}) of the chain",
                        _spec_net_clause(circuit, tap),
                        part_clause(circuit, upper),
                        part_clause(circuit, lower),
                        f"provenance={weakest_provenance(net_provenance(circuit, tap), prov)}",
                        runners,
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=SAME_COLUMN if axis == "vertical" else SAME_ROW,
                    subject=upper,
                    object=lower,
                    reason=(
                        "053 sec.3: the two arms of a divider share one "
                        f"{'column' if axis == 'vertical' else 'row'} — segment "
                        f"{index + 1}/{len(chain.taps)} of {chain.describe()}"
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=order_kind,
                    subject=upper,
                    object=lower,
                    reason=(
                        f"053 sec.3: upper_arm {_order_words(order_kind)} lower_arm "
                        f"— {upper} is the end nearer {chain.in_net} "
                        f"(sidePreferences.power={power_side}, "
                        f"sidePreferences.gnd={gnd_side})"
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=tap_kind,
                    subject=upper,
                    object=lower,
                    reason=(
                        f"053 sec.3: the tap leaves the junction of {upper} and "
                        f"{lower} "
                        f"{'horizontally' if tap_kind == HORIZONTAL_TAP else 'vertically'}"
                        f" (tap={tap}) — stub plus label or port, directly visible"
                    ),
                )
            )
            obligations.append(
                GrammarObligation(
                    kind=VISIBLE_TAP,
                    nets=(tap,),
                    reason=(
                        "053 sec.3: the tap is directly visible (stub + label or "
                        "port), not absorbed by the upper/lower junction"
                    ),
                )
            )
            for branch in branches:
                bindings.append(
                    RoleBinding(
                        role=TAP_BRANCH,
                        part_id=branch,
                        evidence=evidence(
                            f"role={TAP_BRANCH}: a two-terminal part hanging on "
                            f"tap {tap}, not an arm of the chain",
                            part_clause(circuit, branch),
                            f"chain chosen: {chain.describe()}",
                            f"provenance={weakest_provenance(net_provenance(circuit, tap), part_provenance(circuit.part(branch)))}",
                        ),
                    )
                )
                branch_constraints.append(
                    RelativeConstraint(
                        kind=NEAR,
                        subject=branch,
                        object=upper,
                        reason=(
                            f"053 sec.3: a parallel branch on the tap stays with "
                            f"the tap node — {branch} is placed next to {upper} "
                            "(the arm the tap leaves), not across a module boundary"
                        ),
                    )
                )
            if branches:
                obligations.append(
                    GrammarObligation(
                        kind=OWNED_BRANCH,
                        nets=(tap,),
                        reason=(
                            f"053 sec.3: the parallel branch on {tap} reads as "
                            "owned by the tap node"
                        ),
                    )
                )

        # The chain's own relations first, then the branches hanging off it:
        # that is the order a reader follows the drawing in.
        constraints.extend(branch_constraints)
        obligations.insert(
            0,
            GrammarObligation(
                kind=DIRECT_WIRE,
                nets=chain_nets,
                reason=(
                    "053 sec.3: in→upper→tap→lower→gnd is wired end to end — a "
                    "divider is never read by chasing labels"
                ),
            ),
        )
        return bound_result(bindings, constraints, obligations)


GRAMMAR = VoltageDividerGrammar


def grammar(
    profiles: Mapping[str, SymbolProfile] | None = None,
) -> VoltageDividerGrammar:
    """A divider grammar, optionally holding the library profiles."""
    return VoltageDividerGrammar(profiles)


# ------------------------------------------------------------- the judgment


def _missing_class_failures(
    power: tuple[str, ...], ground: tuple[str, ...]
) -> list[GrammarFailure]:
    """The net-class facts the judgment cannot do without."""
    out: list[GrammarFailure] = []
    if not ground:
        out.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'gnd': the bottom of a divider is ground, "
                    "and the drawing grammar has to be told which net that is"
                ),
                action=(
                    "write the class in CircuitSpec.nets[].class — the class a "
                    "net gets when nothing says is 'signal', which is not ground"
                ),
            )
        )
    if not power:
        out.append(
            GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                detail=(
                    "no net of class 'power': the top of a divider is a supply "
                    "rail, and the grammar has to be told which net that is"
                ),
                action=(
                    "write the class in CircuitSpec.nets[].class (power), or "
                    "restate the circuit if the divider hangs on something else"
                ),
            )
        )
    return out


def _arm_role(index: int, count: int) -> str:
    if index == 0:
        return "upper_arm"
    if index == count - 1:
        return "lower_arm"
    return MIDDLE_ARM


def _arm_clause(index: int, chain: _Chain) -> str:
    if index == 0:
        return "the power-side end of the series chain"
    if index == len(chain.arms) - 1:
        return "the ground-side end of the series chain"
    return (
        f"arm {index + 1} of a {len(chain.arms)}-arm chain, strictly between the "
        "two ends (053 sec.3's multi-tap variant)"
    )


def _orientation(power_side: str, gnd_side: str) -> tuple[str, str, str]:
    """``(axis, ordering kind, tap-stub kind)`` from the side preferences.

    Both ends on a vertical side → vertical axis, tap stub horizontal (the
    table's default drawing). Both on a horizontal side → the "横排镜像"
    variant. A mixed pair is not a chain direction, so the book's default
    (power top, ground bottom) is used and the choice is visible in the
    constraint reasons.
    """
    if power_side in ("top", "bottom") and gnd_side in ("top", "bottom"):
        return ("vertical", ABOVE if power_side == "top" else BELOW, HORIZONTAL_TAP)
    if power_side in ("left", "right") and gnd_side in ("left", "right"):
        return (
            "horizontal",
            LEFT_OF if power_side == "left" else RIGHT_OF,
            VERTICAL_TAP,
        )
    return ("vertical", ABOVE, HORIZONTAL_TAP)


def _order_words(order_kind: str) -> str:
    return {
        ABOVE: "above",
        BELOW: "below",
        LEFT_OF: "left-of",
        RIGHT_OF: "right-of",
    }[order_kind]


def _branches(
    presentation: PresentationSpec,
    edges: dict[str, tuple[str, str]],
    chain: _Chain,
    tap: str,
) -> tuple[str, ...]:
    """Two-terminal parts on this tap that are not arms of the chain.

    Restricted to the chain's module where one is declared: a branch reaching
    into another module is that module's business, not this grammar's (052
    sec.5).
    """
    out: list[str] = []
    for part_id in sorted(edges):
        if part_id in chain.arms or tap not in edges[part_id]:
            continue
        if chain.module:
            here = modules_of_part(presentation, part_id)
            if chain.module not in here:
                continue
        out.append(part_id)
    return tuple(out)


def _runner_up_note(chains: list[_Chain]) -> str:
    """``other candidates not bound: …`` — the readings this bind did not take."""
    if len(chains) < 2:
        return ""
    shown = "; ".join(chain.describe() for chain in chains[1:5])
    more = "" if len(chains) <= 5 else f"; +{len(chains) - 5} more"
    return (
        "other in→gnd chains found but not bound (this grammar instance bound "
        f"one chain): {shown}{more}"
    )


def _cross_module_failure(
    presentation: PresentationSpec, chain: _Chain
) -> GrammarFailure:
    """The chain exists but the presentation's modules split it."""
    where = ", ".join(
        f"{arm} in {'/'.join(modules_of_part(presentation, arm)) or 'no module'}"
        for arm in chain.arms
    )
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject=chain.arms[0],
        detail=(
            f"the ladder {chain.describe()} crosses the declared module split: "
            f"{where} — a divider is one functional group (052 sec.5: a branch or "
            "a chain is not drawn across modules)"
        ),
        action=(
            "put every arm of this ladder in one PresentationSpec.modules[] "
            "entry, or fix the module split if the circuit is not one divider"
        ),
    )


def _spec_net_clause(circuit: CircuitSpec, net_id: str) -> str:
    """``net VIN: class=power provenance=…`` or a bare mention when absent."""
    net = circuit.net(net_id)
    return net_clause(net) if net else f"net {net_id}: not declared in nets[]"


def _no_chain_failure(
    circuit: CircuitSpec,
    edges: dict[str, tuple[str, str]],
    power: tuple[str, ...],
    ground: tuple[str, ...],
) -> GrammarFailure:
    """Why no ladder was found — naming what the parts *are* connected to.

    The two shapes worth naming are the parallel pair (both arms across the same
    two nets: no midpoint exists) and the dead-ended chain (the walk stopped
    somewhere that is not ground). Both are `circuit-invalid`: the connections,
    not a missing fact, are why the topology does not match.
    """
    parallel = sorted(
        part_id
        for part_id, nets in edges.items()
        if (nets[0] in power and nets[1] in ground)
        or (nets[1] in power and nets[0] in ground)
    )
    listing = _connection_listing(circuit, edges)
    if parallel:
        crossing = ", ".join(f"{pid}({','.join(edges[pid])})" for pid in parallel)
        detail = (
            f"{crossing} sit directly across a power rail and ground — two arms "
            "in parallel, not in series: they share no midpoint, so no net can be "
            "the tap (053 sec.5 scenario 11's shorted/parallel case)"
        )
        action = (
            "the arms of a divider share one midpoint: rewire one arm's end from "
            "ground (or power) onto the tap net, or restate the circuit if it is "
            "not a divider"
        )
    else:
        detail = (
            f"no chain of two or more two-terminal arms runs from {list(power)} to "
            f"{list(ground)} inside the {MAX_CHAIN_ARMS}-arm budget; what the "
            f"two-terminal parts connect is: {listing}"
        )
        action = (
            "check the CircuitSpec connections (a missing arm, an arm ending on "
            "an unmentioned net, a wrong net class), or enlarge the grammar's "
            "budget if the ladder really is longer than "
            f"{MAX_CHAIN_ARMS} arms"
        )
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject="",
        detail=detail,
        action=action,
    )


def _connection_listing(
    circuit: CircuitSpec, edges: dict[str, tuple[str, str]]
) -> str:
    """``R1(VIN,TAP), R2(TAP,X)`` — bounded, sorted, for a failure message."""
    items = [f"{part_id}({','.join(edges[part_id])})" for part_id in sorted(edges)]
    others = sorted(set(connected_net_sets(circuit)) - set(edges))
    items.extend(
        f"{part_id}({'/'.join(connected_net_sets(circuit)[part_id])})"
        for part_id in others[:4]
    )
    if len(items) > 12:
        return ", ".join(items[:12]) + f", … (+{len(items) - 12} more)"
    return ", ".join(items) or "no part states a connection"
