"""flyback: 113's sixth grammar — the isolated flyback converter's core.

The drawing it promises, from 岳's rulings during 110 (the UC3845B page that
was electrically right and looked like nothing in particular — 48 lint ERRORs
from a hand-drawn layout):

    | flyback | transformer / switch / sense / clamp-R/C/D / sec-D / output-caps /
               feedback-divider / error-amp / opto / compensation / aux-D/C +
               bus / switch-node / src / pgnd / aux / vcc / vout / sec-gnd /
               fb-sense / clamp |
    T1 居中，原边朝输入侧、副边朝输出侧（隔离界竖直 —— 两个"侧"都读
    `sidePreferences`，本文件不写死）；RCD 钳位贴原边上方（power 侧）；
    Q1 竖放于原边下端（gnd 侧）；sense 电阻在 Q1 source 与原边地之间直连；
    反馈副边成链（VOUT→分压→TL431→光耦 LED 水平成链），光耦是唯一跨
    隔离带的器件；双地分族（PGND / SEC_GND）各自统一、绝不连通。

**Every role is a structural judgment; nothing here reads a designator, a
value, a package or a symbol name** (052 sec.5). The one fact that is *not*
derivable — which ground family each node belongs to — is not a fact this
grammar asks for either: it reads the **net class** (`power` / `gnd`) and
**the partition**, both of which the CircuitSpec states.

**The transformer is the anchor, and it is found by its winding net classes**
(task book §角色表). A flyback transformer's three windings are electrically
distinct *shapes*, and each is recognisable from the nets its two ends sit on,
never from a pin name:

* ``Np`` — one end on a ``power``-class net (the bus), the other on the net
  the switch also drains. The switch node is *derived* first: it is the net a
  switch and the transformer's primary share, where "switch" is the part with
  one net on the bus side, one on a ground-referenced sense, and one leaving to
  a control net. The primary is then the winding that touches both the bus and
  that switch node.
* ``Ns`` — one end on a ``power``-class net that is **not** the bus (the
  output), the other on a net that a two-terminal part brings to the secondary
  ground. The secondary ground is the *second* ground family: a ``gnd``-class
  net that the transformer touches and that the primary ground does not.
* ``Naux`` — the transformer's remaining net pair, when the part has one. Its
  far end feeds a two-terminal part to a ``power``-class rail that is neither
  the bus nor the output: the auxiliary supply chain. A two-winding
  transformer has none, and that is **not** a refusal — an aux chain is
  optional, the role simply binds nothing (the same reading `rc-lowpass` gives
  a second shunt).

The judgement is symmetric where the circuit is symmetric and *names the
runners-up* where it is not, exactly as `rc_lowpass` does: every binding's
evidence ends with the other readings found but not bound, and the provenance
of the weakest fact that produced it (052 sec.4).

**What is refused, and in which category** (053 sec.4):

* ``facts-missing`` — the spec states no ``gnd`` family at all, or no
  ``power``-class bus. A ground / a bus is what the class is *for*; the
  message names the class to write.
* ``circuit-invalid`` — the two ground families are **one net** (isolation
  gone: this is a contradiction in the connections, not a missing fact); there
  is no part closing the barrier on any family pairing the circuit states (no
  isolation device: a flyback without a transformer-to-secondary barrier is
  not an isolated flyback); the primary loop is open (bus and switch node with
  no winding between them, or no sense from the source to a primary ground);
  the secondary rectifier's direction is unstated (both its ends inside one
  ground family: the rectifier phase cannot be read, and a rectifier's phase
  is what says which winding is hot).
  Which of those it is comes from the walk's own steps replayed
  (`_primary_prefixes`, `_winding_ends`, `_secondary`, `_divider_strings`), and
  the refusal reports **which leg of the chain was not readable** — never a
  guess about the two families' roles or about the parts' designators.

**What this grammar deliberately does not cover** (task book §范围裁定): the AC
entry and the rectifier bulk (M1/M2 — `power-entry` owns those), and the
controller's own periphery (M5 — `ic-periphery` owns it). Where a part belongs
to one of those it is left unbound; the evidence of the transformer says how
many parts this reading did not claim, so a reader can see the grammar's reach
rather than infer it. Neither of the other grammars' logic is copied here: this
module reads net classes and the partition, and states none of their roles.

**The constraints use only the existing vocabulary** (task book §范围裁定). The
seven 岳 rulings map onto it like this, and the mapping is the point — no new
constraint word is invented:

===================================  ========================================
岳's ruling                          expressed as
===================================  ========================================
(a) T1 居中, 原边朝输入/副边朝输出   ``left-of``/``right-of``(副边件, 原边件)
                                     — the isolation boundary is *vertical*,
                                     which is the horizontal pair of words
(b) RCD 钳位贴原边上方               ``near``(钳位件, T1) + ``above``(钳位, T1)
(c) Q1 竖放于原边下端                ``below``(switch, T1) + ``same-column``
                                     (switch, sense)
(d) sense 直连 source 与原边地        ``same-row``(switch, sense)
(e) 反馈副边成链, 光耦唯一跨带        ``left-of``(分压臂, 误差放大) +
                                     ``near``(分压臂/光耦, 误差放大) +
                                     ``left-of``(opto, 副边分压) /
                                     ``right-of``(opto, 原边补偿)
(f) 双地分族, 绝不连通               no relation is ever stated *between* a
                                     primary-side part and a secondary-side
                                     part except the opto's own two
(g) 电源脚引出打标识                  `uniform-gnd` per family + the
                                     ``direct-wire`` promises below
===================================  ========================================

**The obligations** name the three topologies that must be readable without
chasing labels: the primary loop (``direct-wire`` over bus → switch-node →
src), the secondary chain (``direct-wire`` over the rectifier → output →
divider tap), and the feedback chain (``direct-wire`` over the sense tap →
error amp cathode → opto LED). ``owned-branch`` says each local group reads as
belonging to its own node (the clamp, the aux cap, the compensation cap), and
``uniform-gnd`` is stated **once per family** — two obligations, never one,
because "one way" is a claim about a group and there are two groups
(088b's own rule that a family's rail is stated by its own outlet; the flyback
case is the two-family mirror of it).

The relation kinds above are all measured by `drawcompiler._relation_holds`
against real symbols, so every one of them is a promise the layout stage can
actually keep — which is what makes the end-to-end lint gate a fair test of the
grammar rather than of the compiler's patience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ...core.circuitspec import CircuitSpec
from ...core.presentationspec import SIDES, PresentationSpec
from ...core.symbolprofile import SymbolProfile
from .base import (
    ABOVE,
    ADJACENT,
    BELOW,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_COLUMN,
    UNIFORM_GND,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    bound_result,
    connected_net_sets,
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
    "ROLES_BY_ROLE",
    "FlybackGrammar",
    "FlybackReading",
    "grammar",
]

NAME = "flyback"

#: The role table, in the order a reader wants it: the anchor, the power stage,
#: the secondary, the feedback, the aux chain, then the nets.
ROLES: tuple[str, ...] = (
    # the anchor and the primary side
    "transformer", "switch", "sense",
    # the leakage clamp
    "clamp-R", "clamp-C", "clamp-D",
    # the secondary side
    "sec-D", "output-caps",
    # the feedback chain
    "feedback-divider", "error-amp", "opto", "compensation",
    # the auxiliary supply chain
    "aux-D", "aux-C",
    # the nets
    "bus", "switch-node", "secondary-node", "src", "pgnd",
    "aux", "vcc", "vout", "sec-gnd", "fb-sense", "clamp",
)

#: Why each role exists, one clause each. Published rather than kept in the
#: docstring alone because a role table a reader cannot look up is a role table
#: only its author can use — and the *judgment* behind each is what a reviewer
#: is here to check (this is the same discipline `ic_periphery` keeps its three
#: core sources under).
ROLES_BY_ROLE: dict[str, str] = {
    "transformer": (
        "the part with three winding net-pairs: Np on the bus and the switch "
        "node, Ns on the output and the secondary ground, Naux on the aux "
        "diode and the primary ground — read from the net classes on its pins, "
        "never from a pin name"
    ),
    "switch": (
        "the part with one net on the bus side, one on the switch node it "
        "shares with the primary, and one on the sense the source feeds"
    ),
    "sense": (
        "the two-terminal part from the switch's source net to the primary "
        "ground — the current-sense resistor, located structurally, not by its "
        "value"
    ),
    "clamp-R": (
        "the two-terminal parts of the leakage clamp's discharge string, "
        "running from the clamp node back to the bus"
    ),
    "clamp-C": "the two-terminal part of the clamp string that returns to the bus directly",
    "clamp-D": (
        "the two-terminal part between the switch node and the clamp node — "
        "the clamp diode, whose placement across Np is what makes the clamp a "
        "clamp"
    ),
    "sec-D": (
        "the two-terminal part between the secondary winding's hot node and the "
        "output rail — the rectifier, whose direction is the rectification "
        "phase"
    ),
    "output-caps": "the two-terminal parts from the output rail to the secondary ground",
    "feedback-divider": (
        "the two-terminal parts of the series string from the output rail to "
        "the secondary ground, whose junction is the sense tap"
    ),
    "error-amp": (
        "the part with one pin on the sense tap, one on the secondary ground, "
        "and one driving the isolation device's LED side — the reference / "
        "error amplifier"
    ),
    "opto": (
        "the part with **one pin on each ground family** — that is the "
        "isolation judgment itself, and it needs no pin name to be read"
    ),
    "compensation": "the two-terminal part from the controller's COMP node to the primary ground",
    "aux-D": "the two-terminal part from the auxiliary winding to a power rail that is neither bus nor output",
    "aux-C": "the two-terminal part from that same auxiliary rail to the primary ground",
    "bus": "the power-class net the primary winding's bus end sits on",
    "switch-node": "the net the switch drains and the primary winding's far end sits on",
    "secondary-node": (
        "the net the secondary winding's hot end sits on — the rectifier's "
        "input, and the node whose phase the winding's dot decides"
    ),
    "src": "the net the switch's source drives and the sense resistor feeds",
    "pgnd": "the gnd-class net the primary side returns to",
    "aux": "the net the auxiliary winding's far end sits on",
    "vcc": "the power-class net the auxiliary chain delivers to, when it has one",
    "vout": "the power-class net the secondary rectifier delivers to, which is not the bus",
    "sec-gnd": "the gnd-class net the secondary side returns to, which is not the primary ground",
    "fb-sense": "the net at the divider's junction, which the error amplifier reads",
    "clamp": "the node the clamp diode, the clamp capacitor and the clamp string meet at",
}

#: The roles whose absence is a refusal rather than an empty binding. A
#: flyback without these is not a flyback the drawing could be honest about;
#: the aux chain and the clamp are *not* in this tuple (both are optional in
#: real designs, and 110's own part list shows both may be absent).
REQUIRED_ROLES: tuple[str, ...] = (
    "transformer", "switch", "sense", "sec-D", "opto",
)


@dataclass
class FlybackReading:
    """One reading of this circuit as a flyback converter, as the walk found it.

    A *reading*, not a binding: several may survive the walk (a second ground
    family could be found two ways, a two-terminal part could be both the clamp
    string's arm and a divider arm), and the caller binds the first and names
    the rest in every binding's evidence — the discipline `rc_lowpass` and
    `ic_periphery` both keep.
    """

    transformer: str
    switch: str
    sense: str
    pgnd: str
    sec_gnd: str
    bus: str
    switch_node: str
    src: str
    vout: str
    sec_node: str
    sec_d: str
    opto: str
    error_amp: str
    divider: tuple[str, ...] = ()
    sense_tap: str = ""
    #: The optocoupler's LED cathode — the node the error amplifier drives
    #: and the opto consumes. It is the feedback chain's **wire**, and the
    #: two halves of the loop meet on it.
    led_cathode: str = ""
    #: The controller's compensation node, on the optocoupler's primary side.
    comp: str = ""
    output_caps: tuple[str, ...] = ()
    compensation: tuple[str, ...] = ()
    clamp: str = ""
    clamp_d: str = ""
    clamp_r: tuple[str, ...] = ()
    clamp_c: tuple[str, ...] = ()
    aux: str = ""
    aux_d: str = ""
    aux_c: str = ""
    vcc: str = ""
    note: str = ""

    def describe(self) -> str:
        """``HVDC→T1(Np)→SW/Q1→SRC→R5→PGND │ SEC_SW→D3→SEC_12V`` — a report line."""
        clamp = f", clamp {self.clamp_d}/{'+'.join(self.clamp_r)}/{'+'.join(self.clamp_c)}" if self.clamp_d else ""
        aux = f", aux {self.aux_d}" if self.aux_d else ""
        return (
            f"{self.bus}→{self.transformer}(Np)→{self.switch_node}/{self.switch}→"
            f"{self.src}→{self.sense}→{self.pgnd} │ "
            f"{self.sec_node}→{self.sec_d}→{self.vout}{clamp}{aux}"
        )


class FlybackGrammar:
    """113's flyback grammar."""

    name = NAME

    def __init__(self, profiles: Mapping[str, SymbolProfile] | None = None) -> None:
        # Structural judgment: the roles are read from the net classes and the
        # partition, so nothing here consults a profile. It is taken for a
        # uniform construction across the grammars (`DrawingGrammar`'s note).
        self.profiles: dict[str, SymbolProfile] = dict(profiles or {})

    # -------------------------------------------------------------- binding

    def bind(
        self,
        circuit: CircuitSpec,
        presentation: PresentationSpec,
        *,
        intent: object | None = None,
    ) -> GrammarResult:
        """Bind the flyback roles, or refuse with one of 053 sec.4's categories."""
        # 095 A4's contract is taken and not read. Which way the isolation band
        # runs comes from the presentation's own `sidePreferences` (stated in
        # the obligation reasons and the constraint kinds), and a contract
        # entry has no clause in this grammar to fill — the same position
        # `rc_lowpass` and `ic_periphery` take, for the same reason.
        ground = nets_of_class(circuit, "gnd")
        power = nets_of_class(circuit, "power")
        missing = _missing_class_failures(power, ground)
        if missing:
            return refused_result(missing)

        state = _State(circuit, two_terminal_parts(circuit), power, ground)
        merged = _short_failure(circuit, state)
        if merged is not None:
            return refused_result([merged])

        readings = _readings(state)
        if not readings:
            return refused_result([_no_flyback_failure(circuit, state)])
        return self._result(circuit, state, readings, presentation)

    # ------------------------------------------------------------- internals

    def _result(
        self,
        circuit: CircuitSpec,
        state: "_State",
        readings: list[FlybackReading],
        presentation: PresentationSpec,
    ) -> GrammarResult:
        found = readings[0]
        runners = _runner_up_note(readings)

        bindings: list[RoleBinding] = []
        constraints: list[RelativeConstraint] = []
        obligations: list[GrammarObligation] = []

        # Which way the isolation band runs comes from the presentation's own
        # `sidePreferences` — the same four reads `ldo`, `rc_lowpass`,
        # `power_entry`, `voltage_divider` and `ic_periphery` make. An earlier
        # version of this grammar had `in_side = "left"` / `out_side = "right"`
        # as constants while seven evidence strings still said "per
        # sidePreferences": the drawing kept the hardcoded direction on a
        # mirrored page (a page whose other modules all read the declaration),
        # and the reason text cited a declaration that had never been read.
        in_side = _declared_side(presentation, "input", "left")
        out_side = _declared_side(presentation, "output", "right")
        gnd_side = _declared_side(presentation, "gnd", "bottom")
        power_side = _declared_side(presentation, "power", "top")

        # ---- the anchor: T1, and the four things measured against it
        self._bind_transformer(circuit, found, bindings, constraints, runners)

        # ---- the primary side: switch, sense
        self._bind_primary(circuit, found, bindings, constraints, runners,
                           gnd_side)

        # ---- the clamp (optional)
        self._bind_clamp(circuit, found, bindings, constraints, runners,
                         power_side)

        # ---- the secondary side
        self._bind_secondary(circuit, found, bindings, constraints, runners,
                             out_side, gnd_side)

        # ---- the feedback chain
        self._bind_feedback(circuit, found, bindings, constraints, runners,
                            in_side, out_side, gnd_side)

        # ---- the auxiliary chain (optional)
        self._bind_aux(circuit, found, bindings, constraints, runners,
                       gnd_side)

        # ---- the nets
        for role, net_id, where in (
            ("bus", found.bus,
             "the power-class net the primary winding's bus end sits on — the "
             "rectifier bulk this converter is fed from (M1/M2 are "
             "power-entry's business; this grammar only needs the node)"),
            ("switch-node", found.switch_node,
             "the net the switch drains and the primary winding's far end "
             "sits on — the node whose spike the clamp catches"),
            ("secondary-node", found.sec_node,
             "the net the secondary winding's hot end sits on — the rectifier's "
             "input; the winding's other end is the secondary ground, which is "
             "what says this end is hot"),
            ("src", found.src,
             "the net the switch's source drives and the sense resistor reads"),
            ("pgnd", found.pgnd,
             "the gnd-class net the primary side returns to (one family of the "
             "two; the other is sec-gnd)"),
            ("aux", found.aux,
             "the net the auxiliary winding's far end sits on"),
            ("vcc", found.vcc,
             "the power-class net the auxiliary chain delivers to, which is "
             "neither the bus nor the output"),
            ("vout", found.vout,
             "the power-class net the secondary rectifier delivers to — the "
             "isolated output"),
            ("sec-gnd", found.sec_gnd,
             "the gnd-class net the secondary side returns to (the other "
             "family; the opto is what spans between them)"),
            ("fb-sense", found.sense_tap,
             "the junction of the feedback divider — the node the error "
             "amplifier reads, i.e. the output voltage expressed as a current"),
            ("clamp", found.clamp,
             "the node the clamp diode's far end, the clamp capacitor and the "
             "clamp string meet at"),
        ):
            if not net_id:
                continue
            bindings.append(RoleBinding(
                role=role,
                part_id=net_id,
                evidence=evidence(
                    f"role={role}: {where}",
                    _spec_net_clause(circuit, net_id),
                    f"reading chosen: {found.describe()}",
                    f"provenance={net_provenance(circuit, net_id)}",
                    runners,
                ),
            ))

        # ---- the obligations (053 sec.3's "必须可见的拓扑")
        obligations.extend(_obligations(circuit, found, in_side, out_side,
                                        gnd_side, power_side))

        return bound_result(bindings, constraints, obligations)

    # --------------------------------------------------------- role groups

    def _bind_transformer(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
    ) -> None:
        bindings.append(RoleBinding(
            role="transformer",
            part_id=found.transformer,
            evidence=evidence(
                f"role=transformer: {ROLES_BY_ROLE['transformer']}",
                _winding_clause(circuit, found),
                part_clause(circuit, found.transformer),
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.transformer))}",
                runners,
            ),
        ))

    def _bind_primary(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
        gnd_side: str,
    ) -> None:
        bindings.append(RoleBinding(
            role="switch",
            part_id=found.switch,
            evidence=evidence(
                f"role=switch: {ROLES_BY_ROLE['switch']}",
                part_clause(circuit, found.switch),
                f"it shares {found.switch_node} with the transformer's primary "
                f"far end and drains it to {found.src}",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.switch))}",
                runners,
            ),
        ))
        bindings.append(RoleBinding(
            role="sense",
            part_id=found.sense,
            evidence=evidence(
                f"role=sense: {ROLES_BY_ROLE['sense']}",
                part_clause(circuit, found.sense),
                f"it reads {found.src} (the switch's source net) against "
                f"{found.pgnd} (the primary ground)",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.sense))}",
                runners,
            ),
        ))

        # (c) Q1 竖放于原边下端：the switch hangs below the primary it drains,
        # and the sense resistor stands in the same column as the switch so
        # the source→sense→ground loop is one vertical run. "Below" is the
        # word for the **ground end** of the column, so it is derived from
        # `sidePreferences.gnd`: with the family declared at the top the same
        # relation is `above`, which is the same drawing mirrored.
        constraints.append(RelativeConstraint(
            kind=_side_kind(gnd_side, BELOW),
            subject=found.switch,
            object=found.transformer,
            reason=(
                "岳 110 裁决 c: the main switch is drawn **vertically** at the "
                "lower end of the primary winding — the loop C+→Np→Q1→Rsense→C− "
                "is then one column, which is the smallest area a 1.2 W "
                "converter can have. The constraint word is the one base.py "
                f"gives for 'nearer the ground end', and the ground family is "
                f"declared on the {gnd_side} "
                f"(sidePreferences.gnd={gnd_side!r})"
            ),
        ))
        constraints.append(RelativeConstraint(
            kind=SAME_COLUMN,
            subject=found.switch,
            object=found.sense,
            reason=(
                "岳 110 裁决 c/d: the sense resistor stands directly in the "
                "switch's column, so the source→sense→primary-ground return is "
                "one straight run and the sampling loop hugs ground; a bare "
                "kind cannot say which end, so this states the column of the "
                "**part**, and the reason carries which pin: the switch's "
                "source pin and the sense's source-side pin"
            ),
        ))
        constraints.append(RelativeConstraint(
            kind=NEAR,
            subject=found.sense,
            object=found.switch,
            reason=(
                f"岳 110 裁决 d: {found.sense} hugs {found.switch} — the "
                "sampling loop is local, and no module boundary is crossed"
            ),
        ))
        # The sense sits **below** the switch, which is both true of the
        # circuit (the sampling resistor returns to ground, so it is the
        # ground-side element) and load-bearing: `same-column` states the
        # column but carries no rank, so without this the compiler's chain
        # order put the transformer, the switch and the sense 4 ranks apart and
        # the pair was drawn 285 units from each other — the very scatter this
        # grammar exists to prevent.
        constraints.append(RelativeConstraint(
            kind=_side_kind(gnd_side, BELOW),
            subject=found.sense,
            object=found.switch,
            reason=(
                f"岳 110 裁决 d: {found.sense} is at the ground end of the "
                f"primary column, {_side_word(_side_kind(gnd_side, BELOW))} "
                f"{found.switch} — the switch drains into it and it returns to "
                "the primary ground, so the source→sense→ground leg is the "
                "ground-side end of the primary column, in that order "
                f"(sidePreferences.gnd={gnd_side!r})"
            ),
        ))

    def _bind_clamp(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
        power_side: str,
    ) -> None:
        if not found.clamp_d:
            return
        bindings.append(RoleBinding(
            role="clamp-D",
            part_id=found.clamp_d,
            evidence=evidence(
                f"role=clamp-D: {ROLES_BY_ROLE['clamp-D']}",
                part_clause(circuit, found.clamp_d),
                f"it sits between {found.switch_node} (the switch node) and "
                f"{found.clamp} (the clamp node)",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.clamp_d))}",
                runners,
            ),
        ))
        for role, part_ids, why in (
            ("clamp-R", found.clamp_r, ROLES_BY_ROLE["clamp-R"]),
            ("clamp-C", found.clamp_c, ROLES_BY_ROLE["clamp-C"]),
        ):
            for part_id in part_ids:
                bindings.append(RoleBinding(
                    role=role,
                    part_id=part_id,
                    evidence=evidence(
                        f"role={role}: {why}",
                        part_clause(circuit, part_id),
                        f"reading chosen: {found.describe()}",
                        f"provenance={part_provenance(circuit.part(part_id))}",
                        runners,
                    ),
                ))

        # The string is one compact group, stated as `near` between its
        # consecutive arms. `same-column` was tried first (053 sec.3's
        # "两电阻竖排同轴" read at the string level) and is **too strong a
        # promise here**: the clamp arms hang off the primary winding as
        # branches, and the compiler places each branch at its own node, so a
        # column between two of them is a relation the layout stage cannot keep
        # for a group that is not the chain — it refused the page with R3 and
        # R15 measured 355 units apart. `near` is what ruling (b) asks for
        # anyway (the loop is short, not stacked), and it is measured on the
        # group's own shared net.
        string = (*found.clamp_r, *found.clamp_c)
        for first, second in zip(string, string[1:]):
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=first,
                object=second,
                reason=(
                    f"岳 110 裁决 b: {first} and {second} are consecutive arms "
                    "of one series string off the clamp node, so they read as "
                    "one compact group — the clamp loop is the shortest one on "
                    "the page because it carries the leakage spike"
                ),
            ))

        # (b) RCD 钳位贴原边上方: near says it hugs the winding it protects;
        # `above` puts it on the rail side, which is where the spike is.
        for part_id in (found.clamp_d, *found.clamp_r, *found.clamp_c):
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=part_id,
                object=found.transformer,
                reason=(
                    f"岳 110 裁决 b: {part_id} hugs the primary winding it "
                    "protects — the clamp loop is the shortest one on the page, "
                    "because it carries the leakage spike"
                ),
            ))
            constraints.append(RelativeConstraint(
                kind=_side_kind(power_side, ABOVE),
                subject=part_id,
                object=found.switch,
                reason=(
                    f"岳 110 裁决 b: {part_id} is drawn on the **rail side** of "
                    f"the switch it clamps — "
                    f"{_side_word(_side_kind(power_side, ABOVE))} the drain "
                    "spike it catches, rather than inside the power loop; the "
                    f"rail side is declared as the {power_side} "
                    f"(sidePreferences.power={power_side!r}). The "
                    "reference is the **switch** and not the transformer on "
                    "purpose: the relation is measured against the pin the "
                    "branch hangs off, and a transformer's switch-node pin is at "
                    "the bottom of its body in every legal pose, so promising "
                    "'the rail side of the transformer' for a branch off that "
                    "pin is a relation the compiler can only refuse (measured, "
                    "not assumed — the refusal names the posed pin). The clamp "
                    "is still tied to the winding by the `near` beside it"
                ),
            ))

    def _bind_secondary(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
        out_side: str,
        gnd_side: str,
    ) -> None:
        bindings.append(RoleBinding(
            role="sec-D",
            part_id=found.sec_d,
            evidence=evidence(
                f"role=sec-D: {ROLES_BY_ROLE['sec-D']}",
                part_clause(circuit, found.sec_d),
                f"it carries {found.sec_node} (the secondary winding's hot "
                f"end) to {found.vout} (the output rail); the direction of the "
                "winding's dot is what says which end is hot, and the net "
                "classes say which of the two families each end belongs to",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.sec_d))}",
                runners,
            ),
        ))
        for part_id in found.output_caps:
            bindings.append(RoleBinding(
                role="output-caps",
                part_id=part_id,
                evidence=evidence(
                    f"role=output-caps: {ROLES_BY_ROLE['output-caps']}",
                    part_clause(circuit, part_id),
                    f"it returns {found.vout} to {found.sec_gnd}",
                    f"reading chosen: {found.describe()}",
                    f"provenance={part_provenance(circuit.part(part_id))}",
                    runners,
                ),
            ))
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=part_id,
                object=found.sec_d,
                reason=(
                    f"岳 110 裁决 a/f: {part_id} hugs the rectifier it filters — "
                    "the secondary is one local group, and nothing of it "
                    "reaches across the band to the primary"
                ),
            ))

        # The output filter returns to the secondary ground, whose side the
        # presentation declares (`sidePreferences.gnd`) and which this grammar
        # therefore reads rather than assumes — the same clause 053 sec.3
        # states for the RC low-pass's own capacitor.
        for part_id in found.output_caps:
            constraints.append(RelativeConstraint(
                kind=_side_kind(gnd_side, BELOW),
                subject=part_id,
                object=found.sec_d,
                reason=(
                    f"岳 110 裁决 a/f: {part_id} hangs off the rectifier it "
                    f"filters — it returns {found.vout} to {found.sec_gnd}, and "
                    f"the ground side is the {gnd_side} one "
                    f"(sidePreferences.gnd={gnd_side!r}), so the secondary is a "
                    "rail on one edge and its own return on the other"
                ),
            ))

        # (a) 副边朝输出侧: the secondary group is stated on the output side of
        # the transformer, which is what makes the isolation boundary vertical.
        # The isolation boundary is stated as `near` between the transformer's
        # secondary pin and the rectifier, not as an order kind between the two
        # parts. An order kind here is measured against **the rectifier's own
        # pin and its own origin** (`_pin_side_note` says so, and the compiler
        # refused the page naming the posed pin), and for a chain member those
        # two points are always on the same axis — so "the secondary is on the
        # output side of the transformer" can only be measured between the two
        # *parts*, which is what `near` plus the `below`/`above` pair on the
        # filter does. The drawing's vertical boundary is stated by those.
        for part_id in (found.sec_d, *found.output_caps):
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=part_id,
                object=found.transformer,
                reason=(
                    f"岳 110 裁决 a: {part_id} is on the output side of "
                    f"{found.transformer} — the primary faces the input and the "
                    f"secondary faces the output (output side "
                    f"{out_side!r} per sidePreferences), so the isolation "
                    "boundary the drawing shows is a vertical line with nothing "
                    "but the optocoupler across it. `near` rather than an order "
                    "kind, because an order kind between the transformer and "
                    "the rectifier is measured on the **rectifier's** own pin "
                    "against its own origin, and a chain member's two are "
                    "always on one axis — the compiler's refusal names the "
                    "posed pin and says so, and that is what settled this"
                ),
            ))

    def _bind_feedback(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
        in_side: str,
        out_side: str,
        gnd_side: str,
    ) -> None:
        for part_id in found.divider:
            bindings.append(RoleBinding(
                role="feedback-divider",
                part_id=part_id,
                evidence=evidence(
                    f"role=feedback-divider: {ROLES_BY_ROLE['feedback-divider']}",
                    part_clause(circuit, part_id),
                    f"the pair's junction {found.sense_tap} is the node the "
                    f"error amplifier reads; the VOUT 侧 arm is the one on "
                    f"{found.vout}",
                    f"reading chosen: {found.describe()}",
                    f"provenance={part_provenance(circuit.part(part_id))}",
                    runners,
                ),
            ))
        bindings.append(RoleBinding(
            role="error-amp",
            part_id=found.error_amp,
            evidence=evidence(
                f"role=error-amp: {ROLES_BY_ROLE['error-amp']}",
                part_clause(circuit, found.error_amp),
                f"it reads {found.sense_tap} and returns to "
                f"{found.sec_gnd}, and drives the isolation device's LED side",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.error_amp))}",
                runners,
            ),
        ))
        opto_binding = RoleBinding(
            role="opto",
            part_id=found.opto,
            evidence=evidence(
                f"role=opto: {ROLES_BY_ROLE['opto']}",
                part_clause(circuit, found.opto),
                f"its pins sit on both ground families — {found.sec_gnd} on the "
                f"LED side and {found.pgnd} on the transistor side — which is "
                "the isolation judgment itself; no pin name is read to reach it",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.opto))}",
                runners,
            ),
        )
        bindings.append(opto_binding)

        for part_id in found.compensation:
            bindings.append(RoleBinding(
                role="compensation",
                part_id=part_id,
                evidence=evidence(
                    f"role=compensation: {ROLES_BY_ROLE['compensation']}",
                    part_clause(circuit, part_id),
                    f"reading chosen: {found.describe()}",
                    f"provenance={part_provenance(circuit.part(part_id))}",
                    runners,
                ),
            ))

        # (e) 反馈副边成链 — **narrowed by 145a T2**, on 岳's ruling.
        #
        # The chain used to be stated as `same-row(divider, error-amp)` and
        # `same-row(opto, error-amp)`: every member of the secondary feedback
        # chain on one horizontal line. 144 measured what that costs, and it is
        # two things at once. It is the **opposite of 岳's own hand-drawn page**,
        # where R7 sits *over* R8 in a column (110's snapshot: R7 (930,300) above
        # R8 (930,360)) — the divider he drew is vertical, not a row. And laying
        # the arms in a row puts the FB_SENSE tap run under the row, straight
        # through the lane the divider's own ground pad needs for its flag
        # (measured: R8.2 reported 17 refusals, and the run that took the lane was
        # `(605,310)-(845,310)`).
        #
        # What the ruling is really about survives the narrowing: the chain is
        # read from the VOUT side leftwards, and each member hugs the error
        # amplifier. So each divider arm is stated `left-of` + `near` the error
        # amplifier, and the optocoupler keeps the `left-of` it already has from
        # the band-crossing relation below — no row is stated, so the divider may
        # stand as 岳 drew it. `left-of` rather than `right-of` because the
        # sidePreferences declaration, not this file, says which half is the input
        # one; when the secondary is drawn on the left the band relation flips and
        # so does this one.
        #
        # The error amplifier is the chain's **anchor** and is never paired with
        # itself: an earlier version looped over the chain including the anchor and
        # emitted `same-row(U4, U4)`, which is a relation with one endpoint and has
        # no meaning for the compiler to keep.
        chain_side = RIGHT_OF if out_side == "left" else LEFT_OF
        for part_id in found.divider:
            constraints.append(RelativeConstraint(
                kind=chain_side,
                subject=part_id,
                object=found.error_amp,
                reason=(
                    f"岳 110 裁决 e, narrowed by 145a T2: {part_id} stands on the "
                    f"VOUT side of {found.error_amp} — VOUT→divider→"
                    f"{found.error_amp}→the optocoupler's LED reads in one sweep. "
                    "The order is stated, the **row is not**: 岳's own page draws "
                    "the divider as a column, and laying it flat puts the tap run "
                    "through the divider's ground pad's flag lane (144)"
                ),
            ))
        for part_id in (*found.divider, found.opto):
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=part_id,
                object=found.error_amp,
                reason=(
                    f"岳 110 裁决 e, narrowed by 145a T2: {part_id} hugs "
                    f"{found.error_amp} — the chain is the error amplifier's own "
                    "local topology, and the optocoupler's own place on the chain "
                    "is stated by the band-crossing relation below (its "
                    f"{_side_word(chain_side)} {found.error_amp})"
                ),
            ))

        # (e) the opto is the one part allowed to cross: it is stated on both
        # sides of the band, and nothing else is. The two relations are the
        # crossing — one to the secondary partner, one to the primary
        # compensation — and they are stated **once each**, in opposite
        # directions, which is what "spans" reads as. An earlier version
        # emitted both `left-of` and `right-of` for the same pair, which is a
        # contradiction the compiler can only satisfy by refusing the page.
        # Which of the two words is "the input half" is the declaration's
        # (`sidePreferences.input` / `output`), not this file's.
        band_side = LEFT_OF if out_side == "right" else RIGHT_OF
        constraints.append(RelativeConstraint(
            kind=band_side,
            subject=found.opto,
            object=found.error_amp,
            reason=(
                f"岳 110 裁决 e: the optocoupler is drawn on the **input-side "
                f"half** of the band, {_side_word(band_side)} "
                f"{found.error_amp} — it is the **only** part this grammar "
                "allows to cross the isolation band, and it crosses by being "
                "stated on both sides of it (this relation, and the one below) "
                f"(input {in_side!r} / output {out_side!r} per sidePreferences)"
            ),
        ))
        for part_id in found.compensation:
            constraints.append(RelativeConstraint(
                kind=RIGHT_OF if out_side == "right" else LEFT_OF,
                subject=part_id,
                object=found.opto,
                reason=(
                    f"岳 110 裁决 e: {part_id} hangs off the optocoupler's "
                    f"**primary** side — the compensation network is the "
                    "controller's local topology, and it is the other half of "
                    "the same crossing: the opto is between the divider and "
                    "this network, and nothing else is between the two grounds "
                    f"(input {in_side!r} / output {out_side!r} per "
                    "sidePreferences)"
                ),
            ))
            constraints.append(RelativeConstraint(
                kind=_side_kind(gnd_side, BELOW),
                subject=part_id,
                object=found.opto,
                reason=(
                    f"the compensation capacitor returns the COMP node to "
                    f"{found.pgnd}, and the ground side is the {gnd_side} one "
                    f"(sidePreferences.gnd={gnd_side!r})"
                ),
            ))
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=part_id,
                object=found.opto,
                reason=(
                    f"岳 110 裁决 e/f: {part_id} hugs the optocoupler's primary "
                    "side — the compensation network stays compact and inside "
                    "the primary family"
                ),
            ))

    def _bind_aux(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
        gnd_side: str,
    ) -> None:
        if not found.aux_d:
            return
        bindings.append(RoleBinding(
            role="aux-D",
            part_id=found.aux_d,
            evidence=evidence(
                f"role=aux-D: {ROLES_BY_ROLE['aux-D']}",
                part_clause(circuit, found.aux_d),
                f"it carries {found.aux} (the auxiliary winding) to "
                f"{found.vcc}, which is neither {found.bus} nor {found.vout}",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.aux_d))}",
                runners,
            ),
        ))
        bindings.append(RoleBinding(
            role="aux-C",
            part_id=found.aux_c,
            evidence=evidence(
                f"role=aux-C: {ROLES_BY_ROLE['aux-C']}",
                part_clause(circuit, found.aux_c),
                f"it filters {found.vcc} against {found.pgnd}",
                f"reading chosen: {found.describe()}",
                f"provenance={part_provenance(circuit.part(found.aux_c))}",
                runners,
            ),
        ))
        constraints.append(RelativeConstraint(
            kind=_side_kind(gnd_side, BELOW),
            subject=found.aux_c,
            object=found.aux_d,
            reason=(
                f"the auxiliary capacitor hangs off the rectifier it filters on "
                f"the ground side — it returns {found.vcc} to {found.pgnd}, and "
                f"that side is the {gnd_side} one "
                f"(sidePreferences.gnd={gnd_side!r})"
            ),
        ))
        constraints.append(RelativeConstraint(
            kind=NEAR,
            subject=found.aux_c,
            object=found.aux_d,
            reason=(
                f"the auxiliary capacitor belongs to the auxiliary rectifier it "
                f"follows — one local chain off {found.aux}"
            ),
        ))
        constraints.append(RelativeConstraint(
            kind=NEAR,
            subject=found.aux_d,
            object=found.transformer,
            reason=(
                "the auxiliary rectifier is drawn next to the winding it reads — "
                "the aux chain is the transformer's own local topology"
            ),
        ))


GRAMMAR = FlybackGrammar


def grammar(
    profiles: Mapping[str, SymbolProfile] | None = None,
) -> FlybackGrammar:
    """A flyback grammar, optionally holding the library profiles."""
    return FlybackGrammar(profiles)


# ------------------------------------------------------------- the judgment


@dataclass
class _State:
    """The facts the walk reads, computed once."""

    circuit: CircuitSpec
    #: ``part id -> (net, net)`` for the two-terminal elements (`base.py`).
    edges: dict[str, tuple[str, str]]
    power: tuple[str, ...]
    ground: tuple[str, ...]
    #: ``part id -> its distinct nets``, ascending.
    part_nets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: ``net id -> the gnd-class nets it touches``; the two families live here.
    gnd_of_net: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for part in self.circuit.parts:
            self.part_nets[part.id] = tuple(
                sorted(set(pins_of_part(self.circuit, part.id).values()))
            )
        for net in self.circuit.nets:
            if net.cls == "gnd":
                self.gnd_of_net[net.id] = net.id

    def family(self, net_id: str) -> str:
        """Which ground family this net belongs to, or ``""``."""
        return net_id if net_id in self.ground else ""


def _declared_side(
    presentation: PresentationSpec, role: str, default: str
) -> str:
    """The side this page declares for `role`, or the document's default.

    Read the same way every sibling grammar reads it (`ldo`, `rc_lowpass`,
    `power_entry`, `voltage_divider`, `ic_periphery`), and with the same
    fallback: a preference that is not one of `SIDES` is not a statement about
    the page, so the document default is used instead of guessing.
    """
    side = presentation.side_for(role)
    return side if side in SIDES else default


def _side_kind(side: str, default: str) -> str:
    """The constraint kind that puts something on this side of its anchor.

    Written the way `ldo._side_kind` is written, for the reason 143's drift
    audit gives: the seven grammars share this helper, and two spellings of it
    are two behaviours to keep in sync. (This file's earlier version returned
    *the opposite* horizontal word for a side and had no caller at all — the
    drift was real and it was dead code, which is how the hardcoded sides
    survived here while every sibling read the declaration.)
    """
    return {
        "left": LEFT_OF,
        "right": RIGHT_OF,
        "top": ABOVE,
        "bottom": BELOW,
        "": default,
    }.get(side, default)


def _side_word(kind: str) -> str:
    """The English word for a constraint kind (the same table `ldo` has)."""
    return {
        LEFT_OF: "left of",
        RIGHT_OF: "right of",
        ABOVE: "above",
        BELOW: "below",
        NEAR: "beside",
    }[kind]


def _missing_class_failures(
    power: tuple[str, ...], ground: tuple[str, ...]
) -> list[GrammarFailure]:
    out: list[GrammarFailure] = []
    if not ground:
        out.append(GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            detail=(
                "no net of class 'gnd': a flyback's whole drawing turns on the "
                "two ground families, and the grammar has to be told which nets "
                "they are — without that it cannot say which side of the band "
                "a part is on"
            ),
            action=(
                "write the class in CircuitSpec.nets[].class — the primary and "
                "the secondary ground are two separate nets both of class "
                "'gnd' (they are never one net in an isolated design)"
            ),
        ))
    if not power:
        out.append(GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            detail=(
                "no net of class 'power': the primary winding's bus end and the "
                "secondary rectifier's output are both power-class nodes, and "
                "the grammar reads the winding roles off those classes"
            ),
            action="write the class in CircuitSpec.nets[].class (power)",
        ))
    return out


def _short_failure(circuit: CircuitSpec, state: _State) -> GrammarFailure | None:
    """A two-terminal element bridging the two ground families, or ``None``.

    This is a **contradiction**, not a missing fact: the spec states a
    connection that shorts across the isolation barrier. 110's topology table
    is explicit ("初次级双地不连通…必须两个网名"), and a part with one end on
    each family is exactly that short — the Y capacitor is the one real design
    that does it deliberately, and **the CircuitSpec has no way to say "this
    is deliberate"** (there is no `kind` on a part, only a symbol ref and a
    value, and neither is a statement about intent). So the grammar refuses and
    names the part, rather than binding a barrier it cannot see through.

    The transformer is excluded on purpose and for a stated reason: a
    three-winding flyback transformer *must* have one pin on each family (the
    auxiliary winding's cold end returns to the primary ground, the secondary
    winding's cold end to the secondary ground). That is the topology, not a
    short, and a check that refused it would refuse every correct flyback.
    """
    if len(state.ground) < 2:
        return None
    first, second = sorted(state.ground)[:2]
    wide = {
        part_id for part_id, nets in state.part_nets.items() if len(nets) >= 4
    }
    for part_id, (left, right) in sorted(state.edges.items()):
        if {left, right} == {first, second} and part_id not in wide:
            return GrammarFailure(
                category=FAILURE_CIRCUIT_INVALID,
                subject=part_id,
                detail=(
                    f"{part_id} is a two-terminal element with one end on "
                    f"{first} and the other on {second} — that is a conductor "
                    "straight across the isolation barrier, and an isolated "
                    "flyback has no such part. (A Y capacitor is the one real "
                    "design that does this deliberately; note that the "
                    "CircuitSpec cannot mark one as deliberate, which is why "
                    "the grammar refuses rather than binding a barrier it "
                    "cannot see through.)"
                ),
                action=(
                    f"remove {part_id} from one of the two grounds, or — if this "
                    "is the deliberate Y capacitor — state the isolation intent "
                    "somewhere the grammar can read it; the transformer is "
                    "exempt from this check because its auxiliary and "
                    "secondary cold ends legitimately return to different "
                    "families"
                ),
            )
    return None


def _readings(state: _State) -> list[FlybackReading]:
    """Every reading of this circuit as a flyback, canonically ordered.

    The walk is **structural and ordered**, and every step is a filter over the
    partition rather than a preference, so a circuit that is not a flyback
    produces no reading instead of a wrong one. The order is the one the
    topology fixes:

    1. the **switch** — the only part whose three nets are (a switch node, a
       sensed source, a control net). Nothing else in a power stage looks like
       that, and it does not need a name to be found;
    2. the **transformer** — a part with a winding on the switch node, and
       another on a power-class net, and a third pair left over (the aux
       winding, or the secondary's cold end). It is the anchor from here on;
    3. the two **ground families** — the primary ground is the one the sense
       returns to; the secondary ground is any other gnd-class net the
       transformer touches;
    4. the **rectifier**, its output rail, the **divider** and the **error
       amplifier**, the **optocoupler**;
    5. the optional **clamp** and **aux chain**, read off the primary.

    The discriminators are chosen so that the parts of a real converter cannot
    be confused with one another by accident; each is stated in the docstring
    of the function that applies it, and each is a property of the partition
    (a net's class, a part's pin count, a two-terminal part's two ends) rather
    than of a name, a value or a package.
    """
    found: list[FlybackReading] = []
    for switch_node in sorted(state.circuit.net_ids()):
        for switch in _switches_on(state, switch_node):
            for source in _sources_of(state, switch):
                for transformer in _transformers_on(state, switch_node, source):
                    for pgnd in _primary_grounds(state, source):
                        sense = _sense_on(state, switch, pgnd, source)
                        if not sense:
                            continue
                        for bus, sec_gnd in _winding_ends(
                            state, transformer, switch_node, pgnd
                        ):
                            for sec_d, vout, sec_node in _secondary(
                                state, transformer, sec_gnd, bus
                            ):
                                found.extend(_feedback_readings(
                                    state, transformer, switch, switch_node,
                                    source, sense, pgnd, sec_gnd, bus, vout,
                                    sec_node, sec_d,
                                ))
    found.sort(key=_reading_key)
    return found


def _switches_on(state: _State, switch_node: str) -> list[str]:
    """Parts that **drain** `switch_node` — the primary switch candidates.

    Three nets, one of them the switch node, and of the other two: one reaches
    a gnd-class net through a two-terminal part (that one is the source, and
    what reaches it is the sense resistor), the other reaches none (that one
    is the gate, driven by a controller). The clause "reaches no ground
    through a two-terminal part" is what separates a gate from a source, and
    it is the reason the walk never has to look at a pin name.
    """
    ground_set = set(state.ground)
    out: list[str] = []
    for part_id in sorted(state.part_nets):
        nets = set(state.part_nets[part_id])
        if len(nets) != 3 or switch_node not in nets:
            continue
        others = nets - {switch_node}
        grounded = [
            net_id for net_id in sorted(others)
            if any(other in ground_set for other in _nets_via(state, net_id, part_id))
        ]
        floating = [net_id for net_id in sorted(others) if net_id not in grounded]
        if len(grounded) == 1 and len(floating) == 1:
            out.append(part_id)
    return out


def _sources_of(state: _State, switch: str) -> list[str]:
    """The switch's source net: the one that reaches a ground directly."""
    ground_set = set(state.ground)
    return [
        net_id for net_id in state.part_nets.get(switch, ())
        if any(other in ground_set for other in _nets_via(state, net_id, switch))
    ]


def _transformers_on(
    state: _State, switch_node: str, source: str
) -> list[str]:
    """Parts with a winding between the switch node and something power-class.

    The primary winding's two ends are the bus and the switch node, so the
    transformer is the part that touches the switch node **and** a power-class
    net, and is not the switch itself. The pin count is the second clause: a
    two-terminal part on those two nets is a series element, not a winding.
    """
    power_set = set(state.power)
    switch_nets = set(state.part_nets.get(switch_node, ()))
    del switch_nets
    out: list[str] = []
    for part_id in sorted(state.part_nets):
        nets = set(state.part_nets[part_id])
        if part_id in state.edges:  # a two-terminal part is an element
            continue
        if switch_node in nets and (nets & power_set):
            out.append(part_id)
    del source
    return out


def _primary_grounds(state: _State, source: str) -> list[str]:
    """The ground family the primary side returns to.

    Read from the **sense resistor's own other end**, not from a hop: the
    sense is the part between the source and the primary ground, so the ground
    it reaches is the family. A ground the source reaches only through a
    longer chain is not this one, and picking it would move the whole
    isolation boundary.
    """
    ground_set = set(state.ground)
    out: list[str] = []
    for part_id, (first, second) in sorted(state.edges.items()):
        ends = {first, second}
        if source not in ends or not (ends & ground_set):
            continue
        for net_id in sorted(ends & ground_set):
            if net_id not in out:
                out.append(net_id)
    return out


def _sense_on(
    state: _State, switch: str, pgnd: str, source: str
) -> str:
    """The two-terminal part from the source to the primary ground.

    Exactly one such part in a current-mode converter, and it is the one whose
    two ends are the source and the primary ground. A part that reaches the
    primary ground from some *other* node (a gate stopper, a bleed resistor)
    is not it, because its other end is not the source.
    """
    switch_nets = set(state.part_nets.get(switch, ()))
    for part_id, (first, second) in sorted(state.edges.items()):
        if part_id in switch_nets:
            continue
        if {first, second} == {source, pgnd}:
            return part_id
    return ""


def _winding_ends(
    state: _State, transformer: str, switch_node: str, pgnd: str
) -> list[tuple[str, str]]:
    """``(bus, secondary ground)`` readings for this transformer.

    The **bus** is the power-class net on the winding whose other end is the
    switch node — that pair *is* the primary. The **secondary ground** is a
    ground-class net the transformer touches that is not the primary ground,
    and it must be reached by a winding the primary is not part of, which is
    the partition's way of saying "this is the secondary's cold end". A
    two-winding transformer has no third pair, and the auxiliary winding's
    cold end is the primary ground — so the walk finds the secondary ground
    from the *other* winding's cold end, and the aux chain from the leftover.
    """
    nets = set(state.part_nets.get(transformer, ()))
    power_set = set(state.power)
    ground_set = set(state.ground)
    # The **bus** is the power-class net that shares the transformer with the
    # switch node — the primary winding is exactly the pair of pins on those
    # two nets, so the test is "both are the transformer's own pins", not
    # "they are one node" (they are not: the switch is between them). The
    # earlier version asked whether the two nets were *connected*, which is
    # false for every working converter and found no bus at all.
    buses = sorted(
        net_id for net_id in nets
        if net_id in power_set and switch_node in nets
    )
    out: list[tuple[str, str]] = []
    for bus in buses:
        for sec_gnd in sorted(ground_set - {pgnd}):
            if sec_gnd in nets:
                out.append((bus, sec_gnd))
    return out


def _shares(state: _State, net_id: str, other: str) -> bool:
    """Are these two nets one node as far as a two-terminal part is concerned?"""
    return net_id == other or bool(_nets_via(state, net_id, other))


def _secondary(
    state: _State, transformer: str, sec_gnd: str, bus: str
) -> list[tuple[str, str, str]]:
    """``(rectifier, output rail, secondary hot node)`` readings.

    A rectifier is a two-terminal part with one end on a net the transformer
    touches and the other on a power-class net that is **not** the bus, and
    whose winding end is *not* a ground net — the winding's cold end is the
    one on the secondary ground, so the rectifier hangs off the other, hot,
    end. That fixes the rectification phase from the partition rather than
    from a dot on the symbol: the end sharing the secondary ground is cold,
    and the rectifier's other end is the output.
    """
    out: list[tuple[str, str, str]] = []
    tx_nets = set(state.part_nets.get(transformer, ()))
    power_set = set(state.power)
    ground_set = set(state.ground)
    for part_id, (first, second) in sorted(state.edges.items()):
        for hot, out_net in ((first, second), (second, first)):
            if hot not in tx_nets or out_net not in power_set or out_net == bus:
                continue
            if hot in ground_set:
                continue
            # The winding end this rectifier hangs off must be the **other**
            # end of the secondary: the transformer's own pin on the secondary
            # ground, not a hop through an element. A one-hop search finds
            # nothing here, because the cold end is a pin of the transformer,
            # which is exactly the point — the rectifier is on the winding, not
            # on some other branch.
            if not (tx_nets & ground_set):
                continue
            if sec_gnd not in tx_nets:
                continue
            out.append((part_id, out_net, hot))
    return out


def _feedback_readings(
    state: _State,
    transformer: str,
    switch: str,
    switch_node: str,
    source: str,
    sense: str,
    pgnd: str,
    sec_gnd: str,
    bus: str,
    vout: str,
    sec_node: str,
    sec_d: str,
) -> list[FlybackReading]:
    """Complete the reading once the secondary exists, or return nothing.

    The feedback half is four recognitions, each from the partition, and each
    deliberately excludes the parts already claimed so that a part cannot be
    two roles at once (the real source of the "D3 read as an output capacitor"
    class of mistake):

    * the **divider** — a series string of exactly two two-terminal parts from
      the output rail to the secondary ground, whose junction is the tap. A
      capacitor across the same two nets is *not* a string (it is a single
      arm), and the output connector is not a string either;
    * the **error amplifier** — the part that reads the tap and returns to the
      secondary ground, and is neither the transformer (which also touches
      both families) nor the optocoupler (which is found next);
    * the **optocoupler** — the part with a pin on **each** ground family,
      excluding the transformer and the error amplifier, and having a net that
      is neither the bus, the output, the switch node, the source, nor the
      secondary node. That last clause is what says it is the *feedback*
      barrier rather than the transformer;
    * the **compensation** — the two-terminal parts from the optocoupler's
      primary-side nets to the primary ground, excluding the sense (which is
      the current-sense, not the loop compensation) and the transformer.

    The **cathode** the reading carries is the net the optocoupler itself
    shares with the error amplifier (the LED's own node, which is the only net
    on the secondary that the two have in common), and a reading whose cathode
    cannot be read is **not emitted** rather than emitted half-formed: a
    `direct-wire` obligation built from `(sense_tap, "")` names a net that does
    not exist, and `drawcompiler` then ranks a phantom net into the chain
    (143 H2 — the empty name also walked straight past
    `GrammarObligation.__post_init__`, which checked only that the tuple was
    non-empty, so the net-name half is checked there now too).
    """
    out: list[FlybackReading] = []
    strings = _divider_strings(state, vout, sec_gnd, sec_d)
    taps = tuple(tap for tap, _arms in strings)
    for opto in _isolation_device(state, sec_gnd, pgnd, transformer, taps):
        for error_amp in _error_amp_on(state, sec_gnd, opto, transformer):
            for tap, arms in strings:
                cathode = _cathode_node(state, error_amp, sec_gnd, tap, opto)
                if not cathode:
                    continue  # no cathode, no reading: a half one is a lie
                comp = _comp_node(state, opto, pgnd)
                out.append(FlybackReading(
                    transformer=transformer,
                    switch=switch,
                    sense=sense,
                    pgnd=pgnd,
                    sec_gnd=sec_gnd,
                    bus=bus,
                    switch_node=switch_node,
                    src=source,
                    vout=vout,
                    sec_node=sec_node,
                    sec_d=sec_d,
                    opto=opto,
                    error_amp=error_amp,
                    divider=arms,
                    sense_tap=tap,
                    led_cathode=cathode,
                    comp=comp,
                    output_caps=_output_caps(state, vout, sec_gnd, sec_d, arms),
                    compensation=_compensation(state, pgnd, opto, sense),
                    **_clamp(state, switch_node, bus),
                    **_aux(state, transformer, bus, vout, pgnd),
                    note=(
                        f"reached by the partition alone: {transformer} has "
                        f"{len(state.part_nets.get(transformer, ()))} distinct "
                        "nets and the roles were separated by net class, pin "
                        "count and two-terminal structure — no pin name, "
                        "designator, value or package was read"
                    ),
                ))
    return out


def _isolation_device(
    state: _State,
    sec_gnd: str,
    pgnd: str,
    transformer: str,
    taps: tuple[str, ...] = (),
) -> list[str]:
    """The part with a pin on the primary ground and on the **LED cathode net**.

    The isolation judgment, stated once, and getting it right took four tries
    — the shape is the lesson, so each wrong version is named here:

    * "a pin on each ground family" finds **nothing** in a correct design,
      because the opto's LED returns through the error amplifier rather than
      to the secondary ground directly;
    * "reaches the other family" finds **everything**, because every
      secondary capacitor reaches its own ground;
    * "shares a non-ground net with any secondary part" finds every *primary*
      part too, because they all share the opto's net with it;
    * excluding by pin count drops the opto itself (four nets, same as a
      three-winding transformer).

    The reading that holds is the **loop's own wire**: the optocoupler's LED
    cathode is the node the error amplifier drives and nothing else on the
    secondary side drives — it is a one-degree node on the secondary, joined
    to the primary by exactly one part. So: find the error amplifier's
    non-ground, non-secondary-ground net that is *not* the divider tap (that
    is the cathode node), and the barrier is the part with a pin on it **and**
    a pin on the primary ground, excluding the anchor.

    `transformer` is the **anchor, and it must be the real one**: the anchor
    is excluded so that a three-winding transformer (which touches both
    families and every winding's node) is not read as the error amplifier.
    An earlier caller passed `""` here — meant as "nothing to exclude" — but
    the exclusion is by id, so nothing *was* excluded: the transformer was
    then read as the error amplifier, its winding node came back as the
    "cathode", and the whole barrier question was answered by designator
    order (143 H1). `taps` are the divider junctions the caller has already
    read; with none given, every non-ground net of the amplifier stays a
    candidate, which is the question this function is being asked anyway
    ("is there a barrier here at all?").
    """
    error_amp = _error_amp_for(state, sec_gnd, transformer)
    if not error_amp:
        return []
    cathodes = set(_cathode_candidates(state, error_amp, sec_gnd, taps))
    if not cathodes:
        return []
    out: list[str] = []
    for part_id in sorted(state.part_nets):
        if part_id in (transformer, error_amp):
            continue
        nets = set(state.part_nets[part_id])
        if pgnd in nets and (nets & cathodes):
            out.append(part_id)
    return out


def _error_amp_for(
    state: _State, sec_gnd: str, transformer: str
) -> str:
    """The part reading the divider tap and returning to the secondary ground.

    The partition reading: on the secondary ground, and carrying a net that no
    two-terminal part ties to the output rail or to ground — i.e. it is the
    part sitting *between* the divider and the opto rather than either of
    them. The caller has already found the divider, so this is the last piece
    the loop needs, and it is the same shape `ldo` reads its core.

    Two things are not small-signal amplifiers and are named rather than
    inferred: a two-terminal part (an element — its two ends already say what
    it is) and a part with **four or more nets** (the anchor's own shape: a
    winding set, an optocoupler, a controller). The anchor is passed in and
    also excluded by id, but the shape clause is what keeps the answer right
    when the anchor's id is not known to the caller — which is exactly the
    slide 143 H1 found, where an empty anchor let the transformer itself be
    read as the amplifier and the diagnosis then depended on designator order.
    """
    ground_set = set(state.ground)
    power_set = set(state.power)
    out: list[str] = []
    for part_id in sorted(state.part_nets):
        if part_id in state.edges or part_id == transformer:
            continue  # two-terminal parts are elements; the anchor is bound
        nets = set(state.part_nets[part_id])
        if len(nets) >= 4:
            continue  # the anchor's shape: windings, an opto, a controller
        if sec_gnd not in nets:
            continue
        signal = [
            net_id for net_id in sorted(nets) if net_id not in ground_set
            and net_id not in power_set
        ]
        if len(signal) >= 2:  # the tap and the cathode: an amplifier
            out.append(part_id)
    return out[0] if out else ""


def _cathode_candidates(
    state: _State, error_amp: str, sec_gnd: str, taps: tuple[str, ...] = ()
) -> list[str]:
    """The amplifier's nets that can be the LED cathode, sorted.

    Everything except its own ground, the ground family, the power rails and
    the divider's junction(s): what is left is the node the optocoupler alone
    drives. The tap is excluded **as the tap** (the caller read it from
    `_divider_strings`) rather than by the proxy that used to stand in for it
    — see `_cathode_node` for what that proxy cost.
    """
    skip = {sec_gnd, *taps} | set(state.ground) | set(state.power)
    return [
        net_id
        for net_id in sorted(state.part_nets.get(error_amp, ()))
        if net_id not in skip
    ]


def _cathode_node(
    state: _State, error_amp: str, sec_gnd: str, tap: str = "",
    opto: str = "",
) -> str:
    """The error amplifier's net that is neither its ground nor the divider tap.

    The clause is the docstring's own: the amplifier sits between the divider
    and the optocoupler, so its net that is not the tap is the node the
    optocoupler drives. Earlier versions read it as "the net no two-terminal
    part ties to ground or to the rail", which is a *proxy* for "is the tap"
    and a bad one: it is also true of the LED cathode the moment a normal
    compensation capacitor is drawn across it, so a legitimate type-2 network
    on the LED erased the whole reading and the grammar refused a circuit that
    is right (143 H3: `VOUT—C—LED_K` and `LED_K—C—SEC_GND` both became "no
    isolation barrier"). It also made the answer depend on which nets happened
    to carry a bypass part, i.e. on the drawing's incidentals rather than on
    the topology.

    With several nets left over — an amplifier that reads more than one node
    besides the tap — the net it **shares with the optocoupler** is the
    cathode (that is what the barrier is made of), then the one nothing ties
    to a rail or to ground, and only then the id order. The id order is a
    tie-break, never the reading: 143 H1/H2 are both cases of that order
    standing in for a judgment.
    """
    candidates = _cathode_candidates(state, error_amp, sec_gnd,
                                     (tap,) if tap else ())
    if not candidates:
        return ""
    if opto:
        shared = [net_id for net_id in candidates
                  if net_id in set(state.part_nets.get(opto, ()))]
        if shared:
            return shared[0]
    if len(candidates) == 1:
        return candidates[0]
    rail_set = set(state.ground) | set(state.power)
    for net_id in candidates:
        tied = [
            other for other in _nets_via(state, net_id, error_amp)
            if other in rail_set
        ]
        if not tied:
            return net_id
    return candidates[0]


def _error_amp_on(
    state: _State, sec_gnd: str, opto: str, transformer: str
) -> list[str]:
    """The part that drives the optocoupler's LED and returns to the secondary ground.

    Two clauses, both from the partition: it touches the secondary ground, and
    it shares a net with the optocoupler that is **not** a ground net (the
    LED's cathode node). The transformer is excluded — it also touches the
    secondary ground and shares nets with the opto through the LED node in a
    schematic where the two are adjacent, and the anchor is already bound.
    Two-terminal parts are excluded too, the same clause its twin
    `_error_amp_for` has always carried ("two-terminal parts are elements"):
    without it a capacitor across the output and the secondary ground was a
    candidate error amplifier, and it could *win* — the reading list was
    sorted by a key that did not name the amplifier, so `C11 < U4` was the
    whole arbitration (143 H2: an output capacitor bound as the error amp, and
    the feedback `direct-wire` obligation written as `(FB_SENSE, '')`).
    """
    out: list[str] = []
    opto_nets = set(state.part_nets.get(opto, ()))
    for part_id in sorted(state.part_nets):
        if part_id in (opto, transformer):
            continue
        if part_id in state.edges:
            continue  # two-terminal parts are elements
        nets = set(state.part_nets[part_id])
        if sec_gnd not in nets:
            continue
        signal = [
            net_id for net_id in sorted(nets & opto_nets) if net_id not in set(state.ground)
        ]
        if signal:
            out.append(part_id)
    return out


def _comp_node(state: "_State", opto: str, pgnd: str) -> str:
    """The optocoupler's primary-side node — the loop's other end.

    The opto has one pin on the primary ground (its emitter) and one on a net
    nothing else on the primary touches: that net is where the controller's
    compensation network hangs, and it is the point the feedback loop's other
    half ends at. The sense resistor is excluded because it is the *current*
    loop's node, not the voltage loop's — a page that shares them has one loop,
    and the grammar says which one it drew.
    """
    ground_set = set(state.ground)
    for net_id in sorted(state.part_nets.get(opto, ())):
        if net_id == pgnd or net_id in ground_set:
            continue
        tied_to_ground = [
            other for other in _nets_via(state, net_id, opto)
            if other in ground_set
        ]
        if tied_to_ground:
            return net_id
    return ""


def _divider_strings(
    state: _State, vout: str, sec_gnd: str, sec_d: str
) -> list[tuple[str, tuple[str, ...]]]:
    """Series strings of exactly two two-terminal arms from `vout` to `sec_gnd`.

    A divider is exactly this: an upper arm and a lower arm in series, their
    junction being the tap. The **exactly two** clause is what keeps a
    capacitor across the output (a single arm, no tap) and the output
    connector (also a single arm) out of the role, and excluding the rectifier
    keeps the winding's hot end from being read as a divider arm. The tap is
    then the net the error amplifier reads — checked by the caller, so a
    string with nothing reading it is not a divider.
    """
    out: list[tuple[str, tuple[str, ...]]] = []
    edges = dict(state.edges)
    for top_arm in sorted(edges):
        if top_arm == sec_d:
            continue
        if vout not in edges[top_arm] or sec_gnd in edges[top_arm]:
            continue
        tap = edges[top_arm][0] if edges[top_arm][1] == vout else edges[top_arm][1]
        for bottom_arm in sorted(edges):
            if bottom_arm in (top_arm, sec_d):
                continue
            if sec_gnd not in edges[bottom_arm] or tap not in edges[bottom_arm]:
                continue
            out.append((tap, (top_arm, bottom_arm)))
    return out


def _output_caps(
    state: _State, vout: str, sec_gnd: str, sec_d: str, arms: tuple[str, ...]
) -> tuple[str, ...]:
    """The two-terminal parts from the output rail to the secondary ground.

    Every part across those two nets **except** the ones already claimed: the
    rectifier (it is not across them), the divider's two arms, and the
    output **terminal**. The terminal is a connector rather than a capacitor,
    but the partition cannot tell a two-terminal connector from a two-terminal
    capacitor — both are "a part between the output and the secondary ground".
    So the grammar binds the set (which is the honest reading: the output's
    local shunt group) and its evidence names each part's own two ends, and
    the `SEC_12V` / `SEC_GND` obligation is what says the group is one. **A
    single capacitor is the common case and is the one bound; a page with
    several shunts across the output binds them all, which is 053 sec.3's
    "多 C 并联" variant read the same way `rc_lowpass` reads its second shunt.**
    """
    return tuple(
        part_id for part_id, (first, second) in sorted(state.edges.items())
        if {first, second} == {vout, sec_gnd} and part_id not in arms
    )


def _compensation(
    state: _State, pgnd: str, opto: str, sense: str
) -> tuple[str, ...]:
    """The two-terminal parts from the optocoupler's primary side to primary ground.

    The compensation network hangs off the controller's COMP node, which the
    optocoupler's transistor shares. The clause that separates it from the
    current-sense resistor is the **net**: the sense is on the source (it was
    bound as the sense already, and is excluded by id), while the compensation
    is on a net the opto reaches that the source does not. A part already bound
    as the sense is excluded by name-of-role rather than by id, so a circuit
    that legitimately reuses one part is refused rather than double-bound.
    """
    opto_nets = set(state.part_nets.get(opto, ()))
    out: list[str] = []
    for part_id, (first, second) in sorted(state.edges.items()):
        if pgnd not in (first, second):
            continue
        other = second if first == pgnd else first
        if other not in opto_nets or part_id == sense:
            continue
        out.append(part_id)
    return tuple(out)


def _nets_via(state: _State, net_id: str, exclude: str) -> list[str]:
    """The nets one hop from `net_id` through a two-terminal part."""
    out: list[str] = []
    for part_id, (first, second) in state.edges.items():
        if part_id == exclude:
            continue
        if first == net_id:
            out.append(second)
        elif second == net_id:
            out.append(first)
    return out


def _direct_to(state: _State, part_id: str, net_id: str) -> bool:
    """Does this part reach `net_id` **directly** (one of its own ends)?

    The RCD string is capacitor + resistor in series from the clamp node back
    to the bus, and the two roles are told apart by which end each part has on
    the bus: the capacitor's other plate is on the bus, while the resistor's
    other end is on the resistor that precedes it. That is the whole split,
    and it is a partition question — no value, no package, no designator.
    """
    return net_id in set(state.part_nets.get(part_id, ()))


def _clamp(state: _State, switch_node: str, bus: str) -> dict[str, object]:
    """The RCD clamp across the primary: diode, capacitor, discharge string.

    Read as one chain, because that is what it is: a two-terminal part from
    the switch node to a clamp node (the diode), and from that clamp node a
    series string back to the bus. The string is walked as a **walk**, not as
    a fixed length — 110's own part list is a capacitor **and two** resistors
    in series (C5 + R3 + R15, 2×75 kΩ for the voltage rating), so a
    two-arm assumption silently bound the bulk capacitor C4 as the clamp's
    resistor and the diode as its capacitor. Both were wrong in the same way:
    the walk had stopped at the first arm instead of following the chain to
    the bus.

    The split within the string is the one that says which arm is which: the
    arm whose own end **is** the bus is the capacitor's partner side, and the
    one that reaches the bus through the next arm is the discharge resistor.
    With several resistors in series they are all `clamp-R` and the one
    capacitor is `clamp-C`, which is 053 sec.3's "多 C 并联 / R 换磁珠"
    variant read at the string level.

    An optional chain: a design with no clamp binds none of these roles,
    which is not a refusal.
    """
    empty: dict[str, object] = {
        "clamp": "", "clamp_d": "", "clamp_r": (), "clamp_c": (),
    }
    power_set = set(state.power)
    for part_id, (first, second) in sorted(state.edges.items()):
        for node, clamp_net in ((first, second), (second, first)):
            if node != switch_node or clamp_net in power_set:
                continue
            string = _chain_from(state, clamp_net, goal=bus, skip=part_id)
            if not string:
                continue
            return {
                "clamp": clamp_net,
                "clamp_d": part_id,
                # Which arm is the capacitor and which is the discharge string
                # is decided by **where the arm sits on the line**, not by
                # which of them touches the bus. 110's clamp node carries C5
                # (to the bus) and R3+R15 in series (to the bus), so both
                # branches end at the bus and "the one on the bus" picks
                # whichever comes first in id order. The reading that holds:
                # the capacitor is the branch that is a **single arm** from
                # the clamp node, and the discharge string is the branch of
                # two or more — a lone arm across a DC node is the snubber's
                # capacitor, and a run of arms is the resistor that bleeds it
                # off. Where both branches are single arms, the arm on the
                # bus is the capacitor and the other is the resistor, which
                # is the one-arm-each case 110's own simpler clamp uses.
                **_clamp_split(state, clamp_net, string, bus),
            }
    return empty


def _clamp_split(
    state: "_State", clamp_net: str, string: tuple[str, ...], bus: str
) -> dict[str, tuple[str, ...]]:
    """``{"clamp_c": (...), "clamp_r": (...)}`` for the string's arms.

    Grouped by the branch each arm leaves the clamp node on, then the branch
    of one arm is the capacitor and the branch of several is the discharge
    string. Both are read from the partition — no value, no package, no
    designator — and the tie case (two single-arm branches) falls back to the
    arm whose own end is the bus.
    """
    branches: dict[str, list[str]] = {}
    for part_id in string:
        ends = set(state.part_nets.get(part_id, ()))
        if clamp_net not in ends:
            continue
        far = sorted(ends - {clamp_net})[0] if ends - {clamp_net} else ""
        branches.setdefault(far, []).append(part_id)
    # The arm that leaves the clamp node **straight for the bus** is the
    # capacitor: it is the only one of the string that spans clamp node → bus
    # in a single element. Every other branch runs through further arms, and
    # those are the discharge string — even when its last arm also lands on
    # the bus, which is precisely 110's page (C5 spans it; R3+R15 do not).
    direct = [
        parts[0] for parts in branches.values()
        if len(parts) == 1
        and bus in set(state.part_nets.get(parts[0], ()))
    ]
    if direct:
        rest = tuple(
            part_id for part_id in string if part_id not in direct
        )
        return {"clamp_c": tuple(direct), "clamp_r": rest}
    return {
        "clamp_c": tuple(
            p for p in string if _direct_to(state, p, bus)
        ),
        "clamp_r": tuple(
            p for p in string if not _direct_to(state, p, bus)
        ),
    }


def _chain_from(
    state: "_State", top: str, goal: str, skip: str, max_arms: int = 4
) -> tuple[str, ...]:
    """The arms that carry the clamp string from `top` back to `goal`.

    The clamp node is a **junction**, not a point on a path: the capacitor
    leaves it straight for the bus while the discharge resistors leave it for
    each other and only the last of them reaches the bus. So this is not a
    path search — a path search has to pick an order through the junction and
    therefore drops one branch (three earlier versions did exactly that: one
    bound the bulk capacitor as the clamp's resistor, one returned the
    capacitor alone, one returned the capacitor and half the string).

    What the string *is* is: every two-terminal part reachable from the clamp
    node **without passing through the switch node, the switch, or any
    primary ground**, that still has the bus on one of its own ends or on the
    far end of a line of parts. The walk follows each line separately, and
    takes the lines that arrive at the bus. `max_arms` is `base.py`'s own
    chain budget — running out of it means "not found inside the budget",
    never "there is none" (053 sec.5).
    """
    stop = _stop_nets(state, skip)
    out: list[str] = []
    seen_nets = {top}
    seen_parts: set[str] = set()
    frontier = [top]
    for _ in range(max_arms):
        next_frontier: list[str] = []
        for here in frontier:
            for part_id, (first, second) in sorted(state.edges.items()):
                if part_id in seen_parts or part_id == skip:
                    continue
                ends = {first, second}
                if not (ends & {here}) or (ends & stop):
                    continue
                far = (ends - {here}).pop()
                if far in seen_nets:
                    continue
                seen_parts.add(part_id)
                next_frontier.append(far)
                seen_nets.add(far)
        if not next_frontier:
            break
        frontier = next_frontier
    # A part belongs to the string when it sits on a line that arrives at the
    # bus. Walking each line separately (rather than through a junction) is
    # what keeps the far resistor of a discharge string: R3 leaves the clamp
    # node and R15 leaves R3, and the line "clamp node → bus" contains both.
    lines: list[list[str]] = []
    reached: set[str] = set()
    for part_id in sorted(seen_parts):
        line = _line_through(state, part_id, top, goal, stop, max_arms)
        if line:
            lines.append(list(line))
            reached.update(line)
    return tuple(sorted(reached))


def _line_through(
    state: "_State",
    part_id: str,
    top: str,
    goal: str,
    stop: set[str],
    budget: int,
) -> tuple[str, ...]:
    """The line from `top` through `part_id` that arrives at `goal`.

    The walk starts **at the part**, not at the clamp node, because the clamp
    node is a junction and a walk from it has to choose a branch (the earlier
    version found two arms there, stopped, and returned nothing — which is how
    the capacitor went missing from the string altogether). From the part
    there is one way out on each side, and the side that reaches the bus
    within the budget is the line.
    """
    out = [part_id]
    for start in sorted(state.part_nets.get(part_id, ())):
        # The bus is where the line **ends**, not a net to walk through: the
        # first version expanded past it (HVDC → R15) and so never reported
        # the capacitor's own line at all.
        if start == goal:
            return tuple(out)
        here = start
        for _ in range(budget):
            onward = [
                other for other, pair in sorted(state.edges.items())
                if other not in out and (pair[0] == here or pair[1] == here)
                and not (set(pair) & stop)
            ]
            if len(onward) != 1:
                break
            nxt = _far_end(state, onward[0], here)
            out.append(onward[0])
            if nxt == goal:
                return tuple(out)
            here = nxt
    return ()


def _far_end(state: "_State", part_id: str, net_id: str) -> str:
    """The end of this two-terminal part that is not `net_id`."""
    first, second = state.edges[part_id]
    return second if first == net_id else first


def _stop_nets(state: "_State", skip: str) -> set[str]:
    """The nets the clamp string must not pass through.

    The switch node, the switch's own nets and the grounds: the string runs
    inside the primary's power loop and touching any of these would let the
    walk wander into the output chain (which is exactly what it did when the
    stop set was empty — the bulk capacitor, HVDC → PGND, was bound as the
    clamp's capacitor).
    """
    stop = set(state.ground)
    for net in state.circuit.nets:
        if net.cls == "power" and net.id not in state.power:
            stop.add(net.id)
    stop.add(skip)
    return stop


def _touches(state: "_State", parts: tuple[str, ...], net_id: str) -> bool:
    """Does any of these parts have an end on `net_id`?"""
    return any(
        net_id in set(state.part_nets.get(part, ())) for part in parts
    )


def _aux(
    state: _State, transformer: str, bus: str, vout: str, pgnd: str
) -> dict[str, str]:
    """The auxiliary supply chain: ``Naux → D → C → VCC``.

    The discriminator is the *third* power rail: a two-terminal part from a
    net the transformer touches to a power-class net that is neither the bus
    nor the output is the auxiliary rectifier, and the capacitor is the
    two-terminal part from that same rail to the primary ground. A two-winding
    transformer has no such net, and returns nothing.
    """
    empty = {"aux": "", "aux_d": "", "aux_c": "", "vcc": ""}
    tx_nets = set(state.part_nets.get(transformer, ()))
    power_set = set(state.power)
    for part_id, (first, second) in sorted(state.edges.items()):
        for winding, rail in ((first, second), (second, first)):
            if winding not in tx_nets:
                continue
            if rail not in power_set or rail in (bus, vout):
                continue
            for cap_id, pair in sorted(state.edges.items()):
                if cap_id == part_id or set(pair) != {rail, pgnd}:
                    continue
                return {
                    "aux": winding, "aux_d": part_id,
                    "aux_c": cap_id, "vcc": rail,
                }
    return empty


def _reading_key(reading: FlybackReading):
    """The stable tie-break: the most grounded reading first, then ids.

    A preference order, not a claim of correctness — the runners-up are named
    in every binding's evidence, and the intended way to remove an ambiguity
    is the same as everywhere else in this package: state the module split in
    the presentation.

    The **error amplifier**, the **tap** and the **cathode** are in the key:
    two readings that agree on the transformer, the switch, the opto and the
    two grounds are not the same reading, and leaving them out let
    `list.sort`'s stability decide by *insertion* order — which is the id
    order of the candidate parts. That is how a capacitor came to be bound as
    the error amplifier in 143 H2 (the key could not tell the two readings
    apart, so the tie-break was designator order). A key that names every role
    makes the tie-break a stated preference rather than an accident of
    sorting.
    """
    return (
        reading.pgnd, reading.sec_gnd, reading.bus, reading.transformer,
        reading.switch, reading.opto, reading.error_amp, reading.sense_tap,
        reading.led_cathode,
    )


def _primary_prefixes(state: _State) -> list[tuple[str, ...]]:
    """Every `(switch_node, switch, source, transformer, sense, pgnd)` the walk
    in `_readings` reaches before it needs a second winding end.

    The **same helpers** `_readings` uses, replayed a step at a time so that a
    refusal can say which step is missing. Nothing here is guessed: the primary
    ground comes from `_primary_grounds` (the sense's own other end), not from
    an id sort. 143 H1 is what happens when a refusal guesses instead:
    `sorted(state.ground)[1]` as "the secondary ground" is a claim about the
    alphabet, and the branch it produced depended on the id order of the parts.
    `sense` is `""` when the walk's own `_sense_on` states none, which is how
    the refusal can tell "the primary stage is not readable" from "the primary
    stage is fine and something later is missing".
    """
    out: list[tuple[str, ...]] = []
    for switch_node in sorted(state.circuit.net_ids()):
        for switch in _switches_on(state, switch_node):
            for source in _sources_of(state, switch):
                for transformer in _transformers_on(state, switch_node, source):
                    for pgnd in _primary_grounds(state, source):
                        out.append((
                            switch_node, switch, source, transformer,
                            _sense_on(state, switch, pgnd, source), pgnd,
                        ))
    return out


def _winding_shaped(state: _State) -> list[str]:
    """Parts that could be the transformer, by shape alone: four or more nets,
    one of them power-class and one of them gnd-class.

    Shape, not identity: this is what the first branch of the refusal can say
    without walking. The two class clauses are what keep an optocoupler or a
    controller (also four nets) out of the list — an earlier version asked only
    for the pin count, so a page whose transformer had been deleted reported
    "no part has four or more nets" while the optocoupler sat there with four
    (143 H1's sibling: the cheap test has to be a *shape*, too).
    """
    power_set = set(state.power)
    ground_set = set(state.ground)
    return sorted(
        part_id
        for part_id, nets in state.part_nets.items()
        if len(nets) >= 4
        and (set(nets) & power_set)
        and (set(nets) & ground_set)
    )


def _no_flyback_failure(circuit: CircuitSpec, state: _State) -> GrammarFailure:
    """Why no reading was found, naming the four shapes that matter.

    Every branch is a question about the **partition**, and none of them is
    answered by an id order or by a proxy:

    * is there a winding-shaped part at all (`_winding_shaped`)?
    * are there two ground families?
    * what does the walk itself reach (`_primary_prefixes`, `_winding_ends`,
      `_secondary`, `_divider_strings`) — and if the primary stage is readable
      while no part closes the barrier on any pairing of families the circuit
      states (`_isolation_device`), say exactly that, and otherwise report
      which leg of the chain is unread.

    An earlier version answered the barrier question by calling
    `_isolation_device` with `sorted(state.ground)[1] / [0]` as the two
    families and `""` as the transformer. The empty string was meant as
    "nothing to exclude", but the anchor is excluded **by id**, so nothing was
    excluded: the transformer was read as the error amplifier, its winding
    node as the LED cathode, and the branch fired for pages whose real fault
    was elsewhere — "no part closes the feedback loop across the two ground
    families (PGND, SEC_GND) … Multi-net parts here: T1, U5", denying the
    barrier while listing the optocoupler that made it. Which branch you got
    was decided by the id order of the parts (renaming `T1` to `Z9` changed the
    diagnosis; 143 H1).
    """
    wide = _winding_shaped(state)
    if not wide:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject="",
            detail=(
                "no part in this circuit has four or more distinct nets with "
                "one of them power-class and one gnd-class, so there is no "
                "transformer here: a flyback's windings are read from the net "
                "classes on a multi-net part's pins, and every part here is a "
                "two-terminal element (or a part whose nets do not reach both a "
                f"rail and a ground). What is on the page: {_listing(state)}"
            ),
            action=(
                "check the CircuitSpec connections of the transformer — its "
                "primary ends must sit on the bus and the switch node, and its "
                "secondary ends on the output rectifier and the secondary "
                "ground; a winding with one end unmentioned cannot be read"
            ),
        )
    if len(state.ground) < 2:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject="",
            detail=(
                f"the circuit declares {len(state.ground)} ground net(s) "
                f"({', '.join(state.ground) or 'none'}), but an isolated "
                "flyback needs two families — the primary ground and the "
                "secondary ground are never the same node, and with one family "
                "there is no isolation barrier for the drawing to show. Parts "
                "with four or more nets here: " + ", ".join(wide)
            ),
            action=(
                "declare the secondary ground as its own net of class 'gnd' "
                "and move the secondary side's members onto it; if this circuit "
                "really is non-isolated, it is not a flyback and the LDO or "
                "rc-lowpass grammar is the one that fits it"
            ),
        )
    primaries = _primary_prefixes(state)
    # The legs, read one at a time by the walk's own helpers. A leg counts as
    # read only when it produces the piece the step below it needs: the
    # primary leg is "the sense, the switch, and a winding end on the second
    # family", because a prefix that dies at `_winding_ends` is a reading of
    # nothing (the minimal circuit with its sense deleted has such a prefix —
    # the TL431 read as a switch on the secondary ground — and calling that
    # leg "read" would be the old mistake again in a new spelling).
    windings: list[tuple[str, str, str, str]] = []
    rectified: list[tuple[str, str, str, str, str, str]] = []
    barrier = False
    feedback_read = False
    for (switch_node, _switch, _source, transformer, sense, pgnd) in primaries:
        if not sense:
            continue
        for bus, sec_gnd in _winding_ends(state, transformer, switch_node, pgnd):
            windings.append((transformer, pgnd, bus, sec_gnd))
            # The coarse form of the barrier question: the error amplifier's
            # non-ground net that a part also carries to the primary ground.
            # No taps are passed — the divider may be exactly what is missing
            # (that is what this refusal is reporting), and the coarse question
            # is still a question about the partition rather than about an id
            # order.
            if _isolation_device(state, sec_gnd, pgnd, transformer):
                barrier = True
            for sec_d, vout, _sec_node in _secondary(
                state, transformer, sec_gnd, bus
            ):
                rectified.append((transformer, pgnd, bus, sec_gnd, vout, sec_d))
                strings = _divider_strings(state, vout, sec_gnd, sec_d)
                taps = tuple(tap for tap, _arms in strings)
                if strings and _isolation_device(
                    state, sec_gnd, pgnd, transformer, taps
                ):
                    feedback_read = True
    read = [
        "the primary stage and the winding ends (bus → switch → sense → "
        "primary ground, and the winding on the second family): "
        + ("read" if windings else "not read"),
        "the secondary rectifier (winding → rectifier → output rail): "
        + ("read" if rectified else "not read"),
        "the feedback chain (divider → error amplifier → LED cathode): "
        + ("read" if feedback_read else "not read"),
    ]
    if windings and not barrier:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject="",
            detail=(
                "no part closes the feedback loop across the two ground "
                f"families ({', '.join(state.ground)}), so there is no isolation "
                "barrier: a flyback's regulation crosses optically, and the "
                "drawing's whole claim — two families, one crossing — needs a "
                "part that does it. The barrier was looked for on every family "
                "pairing this circuit states — the primary ground the sense "
                "returns to, and each ground the transformer's other winding "
                f"ends on ({', '.join(f'{p}→{s}' for _t, p, _b, s in windings)}) "
                "— and on each of them there is no part that both sits on the "
                "primary ground and reaches the node the error amplifier drives "
                f"(the LED cathode). What is on the page: {_listing(state)}"
            ),
            action=(
                "check the feedback chain end to end: the divider's junction "
                "must reach the error amplifier, the error amplifier must "
                "drive the isolation device's LED, and that device's other "
                "side must sit on the primary ground. A chain broken anywhere "
                "along it leaves the drawing nothing to span the band with"
            ),
        )
    del circuit
    return GrammarFailure(
        category=FAILURE_CIRCUIT_INVALID,
        subject="",
        detail=(
            "this circuit has a transformer-shaped part (" + ", ".join(wide)
            + ") and two ground families, but the flyback chain does not close, "
            "so no reading of it as a flyback exists. The walk's own steps, "
            "read as far as the partition allows — " + "; ".join(read)
            + ". A leg that is not read is what has to be repaired: the bus "
            "net's class (power), the switch between the switch node and the "
            "sense, the sense between the source and the primary ground, the "
            "secondary rectifier between the winding's hot node and the output, "
            "or the divider→error-amplifier→LED-cathode chain. What is on the "
            f"page: {_listing(state)}"
        ),
        action=(
            "check the four connections the walk reads: the bus net's class "
            "(power), the switch between the switch node and the sense, the "
            "sense between the source and the primary ground, and the "
            "secondary rectifier between the secondary hot node and the output"
        ),
    )


def _listing(state: _State) -> str:
    items = [f"{part_id}({'/'.join(nets)})"
             for part_id, nets in sorted(state.part_nets.items()) if nets]
    if len(items) > 12:
        return ", ".join(items[:12]) + f", … (+{len(items) - 12} more)"
    return ", ".join(items) or "no part states a connection"


def _winding_clause(circuit: CircuitSpec, reading: FlybackReading) -> str:
    """The winding evidence: which net pair is which winding, and why."""
    pins = pins_of_part(circuit, reading.transformer)
    pairs = ", ".join(
        f"{pin}→{net}" for pin, net in sorted(pins.items())
    )
    return (
        f"{reading.transformer} winding pins as stated: {pairs} — Np is the "
        f"pair on {reading.bus} and {reading.switch_node} (the bus and the "
        f"switch node), Ns the pair on {reading.sec_node} and {reading.sec_gnd} "
        f"(the secondary rectifier's node and the secondary ground), Naux the "
        f"remaining pair"
        + (f" on {reading.aux} and {reading.pgnd}" if reading.aux else
           " (this transformer declares no auxiliary winding, so the aux roles "
           "bind nothing)")
    )


def _spec_net_clause(circuit: CircuitSpec, net_id: str) -> str:
    net = circuit.net(net_id)
    return net_clause(net) if net else f"net {net_id}: not declared in nets[]"


def _runner_up_note(readings: list[FlybackReading]) -> str:
    if len(readings) < 2:
        return ""
    shown = "; ".join(reading.describe() for reading in readings[1:5])
    more = "" if len(readings) <= 5 else f"; +{len(readings) - 5} more"
    return (
        "other flyback readings found but not bound (this grammar instance "
        f"bound one): {shown}{more}"
    )


def _obligations(
    circuit: CircuitSpec,
    reading: FlybackReading,
    in_side: str,
    out_side: str,
    gnd_side: str,
    power_side: str,
) -> list[GrammarObligation]:
    """The three topologies that must be readable without chasing labels.

    * the **primary loop** — bus, switch node, source and the sense's return
      are one conductor, so the loop the energy travels in is followed by
      eye;
    * the **secondary chain** — the rectifier's hot end, the output rail and
      the divider's top arm are one conductor, so the isolated output's origin
      is visible;
    * the **feedback chain** — the sense tap, the error amplifier's cathode
      and the optocoupler's LED are one conductor, so the loop closes on the
      page rather than across three labels.

    Plus one `owned-branch` per local group (the clamp, the aux cap, the
    compensation network) and one `uniform-gnd` **per family** — the flyback
    case is the two-family mirror of 088b's one-outlet rule, and one
    obligation for both families would say "expressed one way" about a set
    that is required to be two ways.
    """
    out: list[GrammarObligation] = [
        GrammarObligation(
            kind=DIRECT_WIRE,
            nets=(reading.bus, reading.switch_node, reading.src),
            reason=(
                "岳 110 裁决 c/d: the primary loop bus→switch node→source is "
                "wired on the page, not spelled with labels (input side "
                f"{in_side!r}, power side {power_side!r} per sidePreferences) — "
                "the loop "
                "a 1.2 W converter's whole EMI story lives in must be followable "
                "by eye. The **return** through the primary ground is its own "
                "wiring, reached from the sense, and is not named in this chain: "
                "the transformer's own ground pin (its auxiliary or secondary "
                "cold end) also sits on the primary ground, and putting that net "
                "in this tuple would make the compiler read the transformer's "
                "ground pin as the far end of the primary chain — which is the "
                "one thing it is not (base.py ranks a chain from these nets, so a "
                "competing pin here reorders the whole transformer)"
            ),
        ),
        GrammarObligation(
            kind=DIRECT_WIRE,
            nets=(reading.sec_node, reading.vout, reading.sense_tap),
            reason=(
                "岳 110 裁决 a/e: the secondary chain hot end→rectifier→output "
                "rail→the divider's VOUT-side arm is wired; it is the isolated "
                f"output's origin (output side {out_side!r} per "
                "sidePreferences), and a label there would hide the fact that "
                "this rail came from the transformer at all"
            ),
        ),
        GrammarObligation(
            kind=DIRECT_WIRE,
            nets=(reading.sense_tap, reading.led_cathode),
            reason=(
                "岳 110 裁决 e: the feedback chain sense tap→error "
                "amplifier→optocoupler LED is wired on the secondary side, and "
                "the loop closes on the page — the one crossing it makes is the "
                "optocoupler's, which is the point. The chain **ends at the "
                "LED**: the COMP node is on the optocoupler's other face — the "
                "primary side — and the crossing happens inside the symbol, so "
                "there is no wire to draw through it. An earlier version of "
                "this tuple ran the chain on to COMP; measured on the real "
                "PC817 symbol (2026-10-06, CAT at (-45,-10) / COL at (45,10)) "
                "that demands the LED_K and COMP pins be collinear on the "
                "chain axis, which are diagonal in every pose — zero accepted "
                "poses, and the page was only ever compiled because the spec's "
                "U5.2/U5.3 were swapped, making the demanded pair the two "
                "transistor pins instead. Every name here is a **net** "
                "(base.py's `GrammarObligation.nets` is a net tuple, and the "
                "compiler ranks the chain from it): an earlier version put "
                "part ids in it, which quietly reordered the compiler's chain "
                "and made every pose of the transformer illegal"
            ),
        ),
        GrammarObligation(
            kind=UNIFORM_GND,
            nets=(reading.pgnd,),
            reason=(
                "岳 110 裁决 f/g: the primary family is expressed one way "
                "throughout — one symbol style or one label, never mixed. This "
                "is a separate obligation from the secondary family's because "
                "'one way' is a claim about a group, and there are two groups"
            ),
        ),
        GrammarObligation(
            kind=UNIFORM_GND,
            nets=(reading.sec_gnd,),
            reason=(
                "岳 110 裁决 f/g: the secondary family is expressed one way "
                "throughout — and that half is checked: the compiler's "
                "`uniform-gnd` finding counts the styles of **this** net "
                "(`_uniform_gnd_finding`) and refuses a family that mixes a "
                "symbol with a label. The ruling's other half — that the "
                "secondary family never reads as the primary's — is stated "
                "here because it is what the drawing must do (two grounds a "
                "reader cannot tell apart are not an isolation statement at "
                "all), and it is stated **as unchecked**, because a promise "
                "written like a verified one is the same falsehood as a wrong "
                "binding (143 H7). Nothing checks it today and nothing can: the "
                "compiler's finding looks at one net at a time, so it cannot "
                "see that the two families share a symbol, and `gnd_flag` "
                "(`CompileBudget`) hands every gnd-class net the *same* flag "
                "ref, so there is no way to draw them differently. Making it "
                "checkable needs a comparison of the two families' style sets "
                "in `drawcompiler._uniform_gnd_finding` plus a per-net flag ref "
                "in `CompileBudget` — both outside this module, so this batch "
                "reports the gap instead of pretending the clause holds"
            ),
        ),
    ]
    if reading.clamp:
        out.append(GrammarObligation(
            kind=OWNED_BRANCH,
            nets=(reading.clamp,),
            reason=(
                f"岳 110 裁决 b: the RCD clamp on {reading.clamp} reads as owned "
                "by the primary winding it protects — a wire crossing in from "
                "the output side would read as part of the output instead"
            ),
        ))
    if reading.aux_d:
        out.append(GrammarObligation(
            kind=OWNED_BRANCH,
            nets=(reading.vcc,),
            reason=(
                f"the auxiliary chain on {reading.vcc} reads as owned by the "
                "auxiliary winding — the controller's supply is a local group "
                "off T1, not a branch of the output"
            ),
        ))
    for part_id in reading.compensation:
        out.append(GrammarObligation(
            kind=OWNED_BRANCH,
            nets=(reading.pgnd,),
            reason=(
                f"{part_id} reads as owned by the controller's own COMP node — "
                "the compensation network hangs off the optocoupler's primary "
                "side, and a branch drawn as somebody else's would make the "
                "loop's gain look like the divider's"
            ),
        ))
    del circuit
    return out
