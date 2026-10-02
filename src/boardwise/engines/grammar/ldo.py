"""ldo: 053 sec.3's third grammar, executed — the one that needs a symbol profile.

The table (053 sec.3, verbatim):

    | ldo | core / in_caps[] / out_caps[] / in / out / gnd |
    in 左 core 中 out 右；电容各归所属节点就近；地表达统一（同符号或同标签不混用）|
    in→core→out 主干；各电容与所属节点直连 | EN 脚、NR 电容、可调版（组合
    voltage-divider）|

**The binding judgment, one level finer than the table.** The core is not found
by designator, value or symbol name; it is found by its **pins' electrical
roles**:

1. A part is a **core candidate** when its SymbolProfile gives it a `VIN`, a
   `VOUT` and a `GND` pin (`base.role_pins_of`: the profile's own `electricalRole`
   where it has one, otherwise the pin *name* through `ROLE_BY_PIN_NAME` — the
   two sources 053 sec.3 names), **and** each of those roles is on a net in the
   CircuitSpec. **A role is a set of pins** (055 G1): any pin of the role being a
   net member connects it — the measured AMS1117 draws VOUT on both sides of the
   body — and a pin listed in `nc[]` is explicitly handled (`base.
   role_pins_connected`). A spec pin token is matched by pin number first, then
   by pin name, and which one matched goes into the evidence: a binding matched
   by name is a weaker claim than one matched by number.
2. `in` / `out` / `gnd` are the nets on those three pins, and they must be three
   *different* nets. A core whose VIN and VOUT share a net is shorted: refused as
   `circuit-invalid`, naming the net (053 sec.5 scenario 11's input class).
3. `in_caps` are the two-terminal parts from `in` to `gnd`, `out_caps` those from
   `out` to `gnd` — structural, not by designator prefix: 052 sec.5's point is
   that a decoupling branch *is a branch between those two nets*, and a symbol
   change must not move it out of the role. The core is never one of its own caps.
4. Where the presentation declares modules, caps are collected from the core's own
   module: a decoupling capacitor belonging to the *next* module stays there
   (052 sec.5).
5. A two-terminal part from ground to some **other** core pin's net is an
   `aux_branch` — 053 sec.3's "NR 电容" variant. Those pin nets are read from the
   same profile, so an NR capacitor is tied to the NR pin and an EN pull-down to
   the EN pin without either being named here.

**Two role names the table does not have.**

* `aux_branch` — a two-terminal part from ground to a core pin net that is neither
  `in` nor `out` (the "NR 电容" variant; an EN pull-down has the same shape).
* `core` binds once per regulator, so a module holding two regulators on the same
  `in`/`out`/`gnd` triple binds `core` twice. It is the one role the table lets
  repeat without being an `[]` list, because it is the same core role twice — and
  a reader can tell by the evidence which nets each core bound.

**The constraints.** `in`/`out` are *nets*, and a constraint names *parts*, so
the sides are expressed through the parts that sit on them: each `in_cap` is
`left-of` the core and `near` it, each `out_cap` `right-of` and `near`, and an
`aux_branch` is `near`. Which side is which follows `sidePreferences.input` /
`.output`, so an LDO drawn input-right is the same binding with `right-of`
instead of `left-of`.

**What this batch does not do:** the adjustable version's feedback divider is a
voltage-divider nested inside this grammar. 053 sec.3 recognises the composition
without implementing it ("本批只记组合接口注释，不实现嵌套"), so the seam is the
caller's: bind `voltage-divider` over the same circuit, let the presentation's
module split do the scoping, and keep this grammar's `out_caps` for the branches
that really hang on the output. Nothing here guesses a divider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...core.circuitspec import CircuitSpec, SpecPart
from ...core.presentationspec import SIDES, PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    ABOVE,
    BELOW,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    UNIFORM_GND,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    RoleConnection,
    bound_result,
    connected_net_sets,
    evidence,
    module_of_part,
    modules_of_part,
    net_clause,
    net_provenance,
    part_clause,
    part_provenance,
    profile_for,
    refused_result,
    role_pins,
    role_pins_connected,
    two_terminal_parts,
    weakest_provenance,
)

__all__ = [
    "AUX_BRANCH",
    "CORE_ROLES",
    "EXTRA_ROLES",
    "GRAMMAR",
    "NAME",
    "ROLES",
    "LdoGrammar",
    "grammar",
]

NAME = "ldo"

#: The role table, verbatim from 053 sec.3.
ROLES: tuple[str, ...] = ("core", "in_caps", "out_caps", "in", "out", "gnd")

#: The role this batch adds for the third-pin branch the table lists as a variant
#: but does not name.
EXTRA_ROLES: tuple[str, ...] = ("aux_branch",)

AUX_BRANCH = "aux_branch"

#: The pins that make a part a regulator core.
CORE_PIN_ROLES: tuple[str, ...] = ("VIN", "VOUT", "GND")


@dataclass(frozen=True)
class _Core:
    """One candidate core, as the pin-role judgment found it."""

    part_id: str
    symbol_ref: str
    in_net: str
    out_net: str
    gnd_net: str
    #: ``(role, spec pin token, how the token matched)`` for VIN / VOUT / GND.
    pin_match: tuple[tuple[str, str, str], ...] = ()
    #: One clause per role that has several pins (a duplicated supply pin, an
    #: explicit NC beside a wired one — 055 G1). Evidence, not geometry: which
    #: pin of the role the binding used, and why the others are not a gap.
    role_notes: tuple[str, ...] = ()
    module: str = ""
    profile: SymbolProfile | None = None

    def describe(self) -> str:
        """``U1(AMS1117): VIN→VIN_3V3 VOUT→3V3 GND→GND``."""
        return (
            f"{self.part_id}({self.symbol_ref}): "
            f"VIN→{self.in_net} VOUT→{self.out_net} GND→{self.gnd_net}"
        )


class LdoGrammar:
    """053 sec.3's ldo grammar. Reads the SymbolProfile of each part it judges."""

    name = NAME

    def __init__(self, profiles: Mapping[str, SymbolProfile] | None = None) -> None:
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
        cores, failures = self._cores(circuit, presentation)
        if cores:
            return self._result(circuit, presentation, cores)
        return refused_result(failures)

    # ------------------------------------------------------------- internals

    def _cores(
        self, circuit: CircuitSpec, presentation: PresentationSpec
    ) -> tuple[list[_Core], list[GrammarFailure]]:
        """Every fully-connected core candidate, module-scoped and ordered.

        A refusal comes back only when *nothing* bound — a page holding one part
        without a profile next to a regulator that has one is not a reason to
        refuse the regulator.
        """
        problems: list[GrammarFailure] = []
        candidates: list[_Core] = []
        profiled = False
        for part in sorted(circuit.parts, key=lambda item: item.id):
            profile = profile_for(part, self.profiles)
            if profile is None:
                continue
            profiled = True
            core, problem = _core_from(part, profile, circuit, presentation)
            if problem is not None:
                problems.append(problem)
            elif core is not None:
                candidates.append(core)

        if candidates:
            candidates.sort(
                key=lambda core: (
                    0 if core.module else 1,
                    core.part_id,
                    core.in_net,
                    core.out_net,
                )
            )
            return candidates, []

        # Nothing bound: report what is missing from the library (a part with no
        # profile cannot even be judged) and, when something *was* readable, that
        # what was readable is not a regulator's pin set.
        report = list(problems)
        unprofiled = _unprofiled_failure(circuit, self.profiles)
        if unprofiled is not None:
            report.append(unprofiled)
        if profiled and not problems:
            report.append(_no_core_failure(circuit))
        return [], report

    def _result(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        cores: list[_Core],
    ) -> GrammarResult:
        core = cores[0]
        runners = _runner_up_note(cores)
        in_side = presentation.side_for("input") or "left"
        out_side = presentation.side_for("output") or "right"
        if in_side not in SIDES:
            in_side = "left"
        if out_side not in SIDES:
            out_side = "right"
        in_caps = _caps_on(circuit, presentation, core, core.in_net)
        out_caps = _caps_on(circuit, presentation, core, core.out_net)
        aux = _aux_caps(circuit, presentation, core)
        prov = weakest_provenance(
            net_provenance(circuit, core.in_net),
            net_provenance(circuit, core.out_net),
            net_provenance(circuit, core.gnd_net),
            part_provenance(circuit.part(core.part_id)),
        )

        bindings: list[RoleBinding] = [
            RoleBinding(
                role="core",
                part_id=core.part_id,
                evidence=evidence(
                    "role=core: the part whose symbol profile puts VIN, VOUT and "
                    "GND on three different nets",
                    part_clause(circuit, core.part_id),
                    _profile_clause(core),
                    f"core chosen: {core.describe()}",
                    f"provenance={prov}",
                    runners,
                ),
            )
        ]
        for role, net_id, where in (
            ("in", core.in_net, "the net on the core's VIN pin"),
            ("out", core.out_net, "the net on the core's VOUT pin"),
            ("gnd", core.gnd_net, "the net on the core's GND pin"),
        ):
            bindings.append(
                RoleBinding(
                    role=role,
                    part_id=net_id,
                    evidence=evidence(
                        f"role={role}: {where}",
                        _spec_net_clause(circuit, net_id),
                        _profile_clause(core),
                        f"provenance={weakest_provenance(net_provenance(circuit, net_id), prov)}",
                        runners,
                    ),
                )
            )

        constraints: list[RelativeConstraint] = []
        for role, caps, node, side in (
            ("in_caps", in_caps, core.in_net, in_side),
            ("out_caps", out_caps, core.out_net, out_side),
        ):
            side_kind = _side_kind(side, LEFT_OF if role == "in_caps" else RIGHT_OF)
            for cap in caps:
                bindings.append(
                    RoleBinding(
                        role=role,
                        part_id=cap,
                        evidence=evidence(
                            f"role={role}: a two-terminal part from {node} to "
                            f"{core.gnd_net} — a supply branch of the core, read "
                            "from the nets and not from a designator prefix",
                            part_clause(circuit, cap),
                            f"core chosen: {core.describe()}",
                            f"provenance={weakest_provenance(part_provenance(circuit.part(cap)), prov)}",
                            runners,
                        ),
                    )
                )
                constraints.append(
                    RelativeConstraint(
                        kind=side_kind,
                        subject=cap,
                        object=core.part_id,
                        reason=(
                            "053 sec.3: an LDO's input and output are on opposite "
                            f"sides — {cap} sits on the "
                            f"{'input' if role == 'in_caps' else 'output'} side "
                            f"({node}), so it goes {_side_word(side_kind)} "
                            f"{core.part_id} "
                            f"(sidePreferences.{'input' if role == 'in_caps' else 'output'}"
                            f"={side})"
                        ),
                    )
                )
                constraints.append(
                    RelativeConstraint(
                        kind=NEAR,
                        subject=cap,
                        object=core.part_id,
                        reason=(
                            "053 sec.3: each capacitor is placed with the node it "
                            f"serves — {cap} stays next to {core.part_id} on the "
                            f"{'input' if role == 'in_caps' else 'output'} side "
                            f"({node}), not across a module boundary"
                        ),
                    )
                )

        for part_id, pin_clause, pin_net in aux:
            bindings.append(
                RoleBinding(
                    role=AUX_BRANCH,
                    part_id=part_id,
                    evidence=evidence(
                        f"role={AUX_BRANCH}: a two-terminal part from ground to the "
                        f"core's {pin_clause} net {pin_net} — 053 sec.3's NR "
                        "capacitor variant (an EN pull-down is the same shape)",
                        part_clause(circuit, part_id),
                        _profile_clause(core),
                        f"provenance={weakest_provenance(part_provenance(circuit.part(part_id)), prov)}",
                    ),
                )
            )
            constraints.append(
                RelativeConstraint(
                    kind=NEAR,
                    subject=part_id,
                    object=core.part_id,
                    reason=(
                        f"053 sec.3: the auxiliary branch {part_id} belongs to the "
                        f"core's {pin_clause} — close to {core.part_id}, not "
                        "across a module boundary"
                    ),
                )
            )

        obligations: list[GrammarObligation] = [
            GrammarObligation(
                kind=DIRECT_WIRE,
                nets=(core.in_net, core.out_net),
                reason=(
                    "053 sec.3: in→core→out is wired, so which regulator feeds "
                    "which rail is never read by chasing labels"
                ),
            ),
            GrammarObligation(
                kind=UNIFORM_GND,
                nets=(core.gnd_net,),
                reason=(
                    "053 sec.3: this module's ground is expressed one way "
                    "throughout — one symbol style or one label, never mixed"
                ),
            ),
        ]
        for node, caps in ((core.in_net, in_caps), (core.out_net, out_caps)):
            if caps:
                obligations.append(
                    GrammarObligation(
                        kind=OWNED_BRANCH,
                        nets=(node,),
                        reason=(
                            "053 sec.3: " + ",".join(caps) + " read as owned by "
                            f"{node} — attached to the node they decouple, not "
                            "floating unowned"
                        ),
                    )
                )
        for part_id, pin_clause, pin_net in aux:
            obligations.append(
                GrammarObligation(
                    kind=OWNED_BRANCH,
                    nets=(pin_net,),
                    reason=(
                        f"053 sec.3: {part_id} reads as owned by the core's "
                        f"{pin_clause} net"
                    ),
                )
            )
        return bound_result(bindings, constraints, obligations)


GRAMMAR = LdoGrammar


def grammar(profiles: Mapping[str, SymbolProfile] | None = None) -> LdoGrammar:
    """An ldo grammar holding the library profiles it will read."""
    return LdoGrammar(profiles)


# ------------------------------------------------------------- the judgment


def _core_from(
    part: SpecPart,
    profile: SymbolProfile,
    circuit: CircuitSpec,
    presentation: PresentationSpec,
) -> tuple[_Core | None, GrammarFailure | None]:
    """One part read as a regulator core, or the reason it could not be.

    ``(core, None)`` when the three roles bind; ``(None, failure)`` when the
    symbol says enough to call the part a core but the circuit contradicts it (a
    role with no net at all, a role whose every pin is an explicit NC, two pins
    of one role on two nets, or two of its supply roles shorted together);
    ``(None, None)`` when the part is simply not a regulator — not a failure,
    because most parts on a page are not.

    **Each role is resolved over all of its pins** (`base.role_pins_connected`,
    055 G1), which is what makes the real AMS1117 shape bind: its VOUT is drawn
    on both sides of the body, the circuit connects *one* of the two, and the
    other is either NC or not mentioned at all. Reading only the id-sorted first
    pin reported such a core as "the spec states no connection".
    """
    roles = role_pins(profile)
    if any(role not in roles for role in CORE_PIN_ROLES):
        return None, None

    resolved: dict[str, RoleConnection] = {}
    for role in CORE_PIN_ROLES:
        connection = role_pins_connected(circuit, part.id, profile, role)
        if connection.net:
            resolved[role] = connection
            continue
        if connection.all_nc:
            return None, GrammarFailure(
                category=FAILURE_CIRCUIT_INVALID,
                subject=part.id,
                detail=(
                    f"{part.id} ({part.symbol_ref}) leaves every {role} pin "
                    f"({', '.join(connection.tokens)}) as an explicit nc, so the "
                    f"core has no {role} node and cannot form in→core→out"
                ),
                action=(
                    f"connect one of {_tokens(part.id, connection.tokens)} to a "
                    "net in CircuitSpec.nets[].members — an LDO whose supply pin "
                    "is unconnected is not a regulator here"
                ),
            )
        if len(connection.nets) > 1:
            return None, GrammarFailure(
                category=FAILURE_CIRCUIT_INVALID,
                subject=part.id,
                detail=(
                    f"{part.id} ({part.symbol_ref}) has its {role} pins "
                    f"({', '.join(token for token, _how in connection.connected)}) "
                    f"on {len(connection.nets)} different nets ("
                    f"{', '.join(connection.nets)}) — the pins are one node inside "
                    "the symbol, so this connects those nets together"
                ),
                action=(
                    "put the duplicate pins on one net (whichever the symbol's "
                    "own pin table says is the same node), or split the part into "
                    "two symbols if they really are different outputs"
                ),
            )
        pin = roles[role]
        return None, GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            subject=part.id,
            detail=(
                f"{part.id} ({part.symbol_ref}) has a {role} pin "
                f"(number={pin.number!r}, name={pin.name!r}) but the CircuitSpec "
                "states no connection for it — neither a net member nor an "
                "explicit nc"
            ),
            action=(
                f"add <{part.id}.{pin.number or pin.name}> to a net in "
                "CircuitSpec.nets[].members, or list it in nc[] if it really "
                "is unconnected"
            ),
        )

    nets = {role: connection.nets[0] for role, connection in resolved.items()}
    if len(set(nets.values())) != len(nets):
        counts = {net: list(nets.values()).count(net) for net in set(nets.values())}
        shared = sorted(net for net, count in counts.items() if count > 1)[0]
        shorted = sorted(role for role in nets if nets[role] == shared)
        return None, GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject=part.id,
            detail=(
                f"{part.id} ({part.symbol_ref}) has {' and '.join(shorted)} on one "
                f"net {shared}: the core is shorted there and cannot form "
                "in→core→out"
            ),
            action=(
                "fix the connection (one of the three pins is on the wrong net), "
                "or restate the circuit if this part is not a regulator here"
            ),
        )
    return (
        _Core(
            part_id=part.id,
            symbol_ref=part.symbol_ref,
            in_net=nets["VIN"],
            out_net=nets["VOUT"],
            gnd_net=nets["GND"],
            pin_match=tuple(
                (role, resolved[role].token, resolved[role].how)
                for role in CORE_PIN_ROLES
            ),
            role_notes=tuple(
                note for note in (
                    resolved[role].note() for role in CORE_PIN_ROLES
                ) if note
            ),
            module=module_of_part(presentation, part.id),
            profile=profile,
        ),
        None,
    )


def _tokens(part_id: str, tokens: tuple[str, ...]) -> str:
    """``<U1.2>, <U1.4>`` — the spellings the spec would use for these pins."""
    return ", ".join(f"<{part_id}.{token}>" for token in tokens)


def _caps_on(
    circuit: CircuitSpec, presentation: PresentationSpec, core: _Core, node: str
) -> tuple[str, ...]:
    """Two-terminal parts from this node to the core's ground, module-scoped."""
    edges = two_terminal_parts(circuit)
    out: list[str] = []
    for part_id in sorted(edges):
        if part_id == core.part_id or node not in edges[part_id]:
            continue
        if core.gnd_net not in edges[part_id]:
            continue
        if core.module and core.module not in modules_of_part(presentation, part_id):
            continue
        out.append(part_id)
    return tuple(out)


def _aux_caps(
    circuit: CircuitSpec, presentation: PresentationSpec, core: _Core
) -> tuple[tuple[str, str, str], ...]:
    """``(part id, pin clause, its net)`` for branches on the core's other pins.

    The other pins come from the same profile role table, so a branch is tied to
    the pin it serves rather than to a net name: its far end is that pin, its
    near end the core's ground. A role is resolved over **all** of its pins
    (`base.role_pins_connected`, the same ruler the three core roles use, 055
    G1), so a duplicated EN pin behaves like a duplicated VOUT.
    """
    if core.profile is None:
        return ()
    roles = role_pins(core.profile)
    edges = two_terminal_parts(circuit)
    chain_nets = {core.in_net, core.out_net, core.gnd_net}
    out: list[tuple[str, str, str]] = []
    for role in sorted(roles):
        if role in CORE_PIN_ROLES:
            continue
        connection = role_pins_connected(circuit, core.part_id, core.profile, role)
        if not connection.net or connection.net in chain_nets:
            continue
        net = connection.net
        for part_id in sorted(edges):
            if part_id == core.part_id:
                continue
            if net not in edges[part_id] or core.gnd_net not in edges[part_id]:
                continue
            if core.module and core.module not in modules_of_part(presentation, part_id):
                continue
            out.append((part_id, f"{role} pin (spec token {connection.token})", net))
    return tuple(out)


def _spec_net_clause(circuit: CircuitSpec, net_id: str) -> str:
    net = circuit.net(net_id)
    return net_clause(net) if net else f"net {net_id}: not declared in nets[]"


def _profile_clause(core: _Core) -> str:
    clause = (
        f"profile {core.symbol_ref}: "
        + ", ".join(
            f"{role}→spec pin {token} (matched by {how})"
            for role, token, how in core.pin_match
        )
    )
    if core.role_notes:
        clause += "; " + "; ".join(core.role_notes)
    return clause


def _side_kind(side: str, default: str) -> str:
    """The constraint kind that puts something on this side of the core."""
    return {
        "left": LEFT_OF,
        "right": RIGHT_OF,
        "top": ABOVE,
        "bottom": BELOW,
        "": default,
    }.get(side, default)


def _side_word(kind: str) -> str:
    return {
        LEFT_OF: "left of",
        RIGHT_OF: "right of",
        ABOVE: "above",
        BELOW: "below",
        NEAR: "beside",
    }[kind]


def _runner_up_note(cores: list[_Core]) -> str:
    if len(cores) < 2:
        return ""
    shown = "; ".join(core.describe() for core in cores[1:5])
    more = "" if len(cores) <= 5 else f"; +{len(cores) - 5} more"
    return (
        "other core candidates found but not bound (this grammar instance bound "
        f"one): {shown}{more}"
    )


def _no_core_failure(circuit: CircuitSpec) -> GrammarFailure:
    """Something on the page was readable, and it is not a regulator."""
    nets = connected_net_sets(circuit)
    described = ", ".join(
        f"{part.id}({part.symbol_ref or 'no symbolRef'}"
        + (f", {'/'.join(nets[part.id])}" if part.id in nets else ", no connection")
        + ")"
        for part in sorted(circuit.parts, key=lambda item: item.id)[:8]
    )
    return GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject="",
        detail=(
            "no part maps VIN/VOUT/GND onto three different connected nets, so "
            "nothing on the page reads as a regulator core "
            f"(page: {described})"
        ),
        action=(
            "check that the profile's VIN/VOUT/GND pins are the symbol's real "
            "supply pins and that each is connected in the CircuitSpec — or, if "
            "the circuit is not a regulator, choose another grammar"
        ),
    )


def _unprofiled_failure(
    circuit: CircuitSpec, profiles: Mapping[str, SymbolProfile] | None
) -> GrammarFailure | None:
    """The parts whose symbol has no profile — the gap no judgment can read past.

    ``None`` when every part is profiled. One failure rather than one per symbol:
    what the caller has to fix is the library, and a list of ``part(symbolRef)``
    pairs is the actionable form of it.
    """
    missing = [
        part
        for part in sorted(circuit.parts, key=lambda item: item.id)
        if profile_for(part, profiles) is None
    ]
    if not missing:
        return None
    listed = ", ".join(
        f"{part.id}({part.symbol_ref or 'no symbolRef'})" for part in missing[:8]
    )
    if len(missing) > 8:
        listed += f", … (+{len(missing) - 8} more)"
    return GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject=missing[0].id,
        detail=(
            f"{listed} have no SymbolProfile, so their pin roles (VIN/VOUT/GND) "
            "cannot be read — and this grammar binds the core by its pins"
        ),
        action=(
            "add the profiles (symbolprofile.from_parsed_symbol over each "
            "symbol's SYMBOL document, or a library export), or choose a "
            "compatible symbol whose pin mapping is verified — never renumber "
            "pins to fit the layout"
        ),
    )
