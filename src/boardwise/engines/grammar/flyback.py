"""flyback: 113's sixth grammar — the isolated flyback converter's core.

The drawing it promises, from 岳's rulings during 110 (the UC3845B page that
was electrically right and looked like nothing in particular — 48 lint ERRORs
from a hand-drawn layout):

    | flyback | transformer / switch / sense / clamp-R/C/D / sec-D / output-caps /
               feedback-divider / error-amp / opto / compensation / aux-D/C +
               bus / switch-node / src / pgnd / aux / vcc / vout / sec-gnd /
               fb-sense / clamp |
    T1 居中，原边朝输入侧、副边朝输出侧（隔离界竖直）；RCD 钳位贴原边上方；
    Q1 竖放于原边下端；sense 电阻在 Q1 source 与原边地之间直连；
    反馈副边成链（VOUT→分压→TL431→光耦 LED 水平成链），光耦是唯一允许竖直
    跨越隔离带的器件；双地分族（PGND / SEC_GND）各自统一、绝不连通。

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
  is no part carrying a pin on each ground family (no isolation device: a
  flyback without a transformer-to-secondary barrier is not an isolated
  flyback); the primary loop is open (bus and switch node with no winding
  between them); the secondary rectifier's direction is unstated (both its ends
  inside one ground family: the rectifier phase cannot be read, and a
  rectifier's phase is what says which winding is hot).

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
(e) 反馈副边成链, 光耦唯一跨带        ``same-row``(分压臂, 误差放大, opto) +
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
from ...core.presentationspec import PresentationSpec
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
    SAME_ROW,
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
        return self._result(circuit, state, readings)

    # ------------------------------------------------------------- internals

    def _result(
        self,
        circuit: CircuitSpec,
        state: "_State",
        readings: list[FlybackReading],
    ) -> GrammarResult:
        found = readings[0]
        runners = _runner_up_note(readings)

        bindings: list[RoleBinding] = []
        constraints: list[RelativeConstraint] = []
        obligations: list[GrammarObligation] = []

        in_side = "left"
        out_side = "right"

        # ---- the anchor: T1, and the four things measured against it
        self._bind_transformer(circuit, found, bindings, constraints, runners)

        # ---- the primary side: switch, sense
        self._bind_primary(circuit, found, bindings, constraints, runners)

        # ---- the clamp (optional)
        self._bind_clamp(circuit, found, bindings, constraints, runners)

        # ---- the secondary side
        self._bind_secondary(circuit, found, bindings, constraints, runners,
                             out_side)

        # ---- the feedback chain
        self._bind_feedback(circuit, found, bindings, constraints, runners,
                            out_side)

        # ---- the auxiliary chain (optional)
        self._bind_aux(circuit, found, bindings, constraints, runners)

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
        obligations.extend(_obligations(circuit, found, in_side, out_side))

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
        # the source→sense→ground loop is one vertical run.
        constraints.append(RelativeConstraint(
            kind=BELOW,
            subject=found.switch,
            object=found.transformer,
            reason=(
                "岳 110 裁决 c: the main switch is drawn **vertically** at the "
                "lower end of the primary winding — the loop C+→Np→Q1→Rsense→C− "
                "is then one column, which is the smallest area a 1.2 W "
                "converter can have. `below` is the word base.py gives for "
                "'nearer the ground end', and the primary is the power end"
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
            kind=BELOW,
            subject=found.sense,
            object=found.switch,
            reason=(
                f"岳 110 裁决 d: {found.sense} is below {found.switch} — the "
                "switch drains into it and it returns to the primary ground, so "
                "the source→sense→ground leg is the ground-side end of the "
                "primary column, in that order"
            ),
        ))

    def _bind_clamp(
        self,
        circuit: CircuitSpec,
        found: FlybackReading,
        bindings: list[RoleBinding],
        constraints: list[RelativeConstraint],
        runners: str,
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
                kind=ABOVE,
                subject=part_id,
                object=found.switch,
                reason=(
                    f"岳 110 裁决 b: {part_id} is drawn above the switch it "
                    "clamps — the clamp sits on the rail side, above the drain "
                    "spike it catches, rather than inside the power loop. The "
                    "reference is the **switch** and not the transformer on "
                    "purpose: `above` is measured against the pin the branch "
                    "hangs off, and a transformer's switch-node pin is at the "
                    "bottom of its body in every legal pose, so promising "
                    "'above the transformer' for a branch off that pin is a "
                    "relation the compiler can only refuse (measured, not "
                    "assumed — the refusal names the posed pin). The clamp is "
                    "still tied to the winding by the `near` beside it"
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

        # The output filter returns to the secondary ground, which the
        # presentation puts below (sidePreferences.gnd), so the shunt bodies
        # leave their rail downward — the same clause 053 sec.3 states for the
        # RC low-pass's own capacitor.
        for part_id in found.output_caps:
            constraints.append(RelativeConstraint(
                kind=BELOW,
                subject=part_id,
                object=found.sec_d,
                reason=(
                    f"岳 110 裁决 a/f: {part_id} hangs below the rectifier it "
                    f"filters — it returns {found.vout} to {found.sec_gnd}, and "
                    "the ground side is the bottom one (sidePreferences.gn"
                    "d), so the secondary is a rail on top and its own return "
                    "underneath"
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
        out_side: str,
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

        # (e) 反馈副边成链: the whole secondary feedback chain is one row, so
        # VOUT→divider→error amp→LED reads left to right without a jump. The
        # error amplifier is the row's **anchor**, so it is not paired with
        # itself — an earlier version looped over the chain including the
        # anchor and emitted `same-row(U4, U4)`, which is a relation with one
        # endpoint and has no meaning for the compiler to keep.
        for part_id in (*found.divider, found.opto):
            constraints.append(RelativeConstraint(
                kind=SAME_ROW,
                subject=part_id,
                object=found.error_amp,
                reason=(
                    f"岳 110 裁决 e: {part_id} is on the feedback chain's row — "
                    f"VOUT→divider→{found.error_amp}→the optocoupler's LED runs "
                    "horizontally on the secondary side, so the loop is read in "
                    "one sweep instead of by chasing labels"
                ),
            ))
        for part_id in found.divider:
            constraints.append(RelativeConstraint(
                kind=NEAR,
                subject=part_id,
                object=found.error_amp,
                reason=(
                    f"岳 110 裁决 e: {part_id} hugs {found.error_amp} — the "
                    "divider is the error amplifier's own local topology"
                ),
            ))

        # (e) the opto is the one part allowed to cross: it is stated on both
        # sides of the band, and nothing else is. The two relations are the
        # crossing — one to the secondary partner, one to the primary
        # compensation — and they are stated **once each**, in opposite
        # directions, which is what "spans" reads as. An earlier version
        # emitted both `left-of` and `right-of` for the same pair, which is a
        # contradiction the compiler can only satisfy by refusing the page.
        band_side = LEFT_OF if out_side == "right" else RIGHT_OF
        constraints.append(RelativeConstraint(
            kind=band_side,
            subject=found.opto,
            object=found.error_amp,
            reason=(
                f"岳 110 裁决 e: the optocoupler is drawn on the output side of "
                f"{found.error_amp} — it is the **only** part this grammar "
                "allows to cross the isolation band, and it crosses by being "
                "stated on both sides of it (this relation, and the one below)"
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
                    "this network, and nothing else is between the two grounds"
                ),
            ))
            constraints.append(RelativeConstraint(
                kind=BELOW,
                subject=part_id,
                object=found.opto,
                reason=(
                    f"the compensation capacitor returns the COMP node to "
                    f"{found.pgnd}, and the ground side is the bottom one "
                    "(sidePreferences.gnd)"
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
            kind=BELOW,
            subject=found.aux_c,
            object=found.aux_d,
            reason=(
                f"the auxiliary capacitor hangs below the rectifier it filters — "
                f"it returns {found.vcc} to {found.pgnd}, and the ground side is "
                "the bottom one (sidePreferences.gnd)"
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


def _side_kind(side: str, left: str, right: str) -> str:
    """The horizontal word for a stated side, defaulting to the left one.

    The same resolution `_side_kind` does in the other grammars, and for the
    same reason: a side preference is a statement about the page, and a page
    whose input enters from the right is the same drawing mirrored — the word
    changes, the relation's meaning does not.
    """
    return right if side == "left" else left


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
    """
    out: list[FlybackReading] = []
    for opto in _isolation_device(state, sec_gnd, pgnd, transformer):
        for error_amp in _error_amp_on(state, sec_gnd, opto, transformer):
            for tap, arms in _divider_strings(state, vout, sec_gnd, sec_d):
                cathode = _cathode_node(state, error_amp, sec_gnd)
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
    state: _State, sec_gnd: str, pgnd: str, transformer: str
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
    """
    error_amp = _error_amp_for(state, sec_gnd, transformer)
    if not error_amp:
        return []
    cathode = _cathode_node(state, error_amp, sec_gnd)
    if not cathode:
        return []
    out: list[str] = []
    for part_id in sorted(state.part_nets):
        if part_id in (transformer, error_amp):
            continue
        nets = set(state.part_nets[part_id])
        if pgnd in nets and cathode in nets:
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
    """

    ground_set = set(state.ground)
    power_set = set(state.power)
    out: list[str] = []
    for part_id in sorted(state.part_nets):
        if part_id in state.edges or part_id == transformer:
            continue  # two-terminal parts are elements; the anchor is bound
        nets = set(state.part_nets[part_id])
        if sec_gnd not in nets:
            continue
        signal = [
            net_id for net_id in sorted(nets) if net_id not in ground_set
            and net_id not in power_set
        ]
        if len(signal) >= 2:  # the tap and the cathode: an amplifier
            out.append(part_id)
    return out[0] if out else ""


def _cathode_node(state: _State, error_amp: str, sec_gnd: str) -> str:
    """The error amplifier's net that is neither its ground nor the divider tap.

    Read as "the net no two-terminal part ties to ground or to the output":
    the cathode node is the one the opto alone reaches, and anything the
    divider owns is tied to a rail or to the tap's partner on ground.
    """
    ground_set = set(state.ground)
    power_set = set(state.power)
    nets = set(state.part_nets.get(error_amp, ()))
    for net_id in sorted(nets - {sec_gnd} - ground_set - power_set):
        tied = [
            other for other in _nets_via(state, net_id, error_amp)
            if other in ground_set or other in power_set
        ]
        if not tied:
            return net_id
    return ""


def _error_amp_on(
    state: _State, sec_gnd: str, opto: str, transformer: str
) -> list[str]:
    """The part that drives the optocoupler's LED and returns to the secondary ground.

    Two clauses, both from the partition: it touches the secondary ground, and
    it shares a net with the optocoupler that is **not** a ground net (the
    LED's cathode node). The transformer is excluded — it also touches the
    secondary ground and shares nets with the opto through the LED node in a
    schematic where the two are adjacent, and the anchor is already bound.
    """
    out: list[str] = []
    opto_nets = set(state.part_nets.get(opto, ()))
    for part_id in sorted(state.part_nets):
        if part_id in (opto, transformer):
            continue
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
    """
    return (
        reading.pgnd, reading.sec_gnd, reading.bus, reading.transformer,
        reading.switch, reading.opto,
    )


def _no_flyback_failure(circuit: CircuitSpec, state: _State) -> GrammarFailure:
    """Why no reading was found, naming the four shapes that matter."""
    wide = sorted(
        part_id for part_id, nets in state.part_nets.items() if len(nets) >= 4
    )
    if not wide:
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject="",
            detail=(
                "no part in this circuit has four or more distinct nets, so "
                "there is no transformer here: a flyback's windings are read "
                "from the net classes on a multi-net part's pins, and every "
                "part here is a two-terminal element. What is on the page: "
                f"{_listing(state)}"
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
    if not _isolation_device(state, sorted(state.ground)[1],
                             sorted(state.ground)[0], ""):
        return GrammarFailure(
            category=FAILURE_CIRCUIT_INVALID,
            subject="",
            detail=(
                "no part closes the feedback loop across the two ground "
                f"families ({', '.join(state.ground)}), so there is no isolation "
                "barrier: a flyback's regulation crosses optically, and the "
                "drawing's whole claim — two families, one crossing — needs a "
                f"part that does it. Multi-net parts here: {', '.join(wide)}"
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
            + ") and two ground families, but the flyback chain does not close: "
            f"no switch drains a switch node on the primary winding to a sense "
            f"resistor that returns to the primary ground, or no rectifier "
            f"carries a secondary winding to the output. What is on the page: "
            f"{_listing(state)}"
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
                f"{in_side!r}, power side above per sidePreferences) — the loop "
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
                "throughout, and in a way that never reads as the primary's — "
                "the two grounds are the isolation statement of the whole "
                "drawing, and a reader who cannot tell them apart is not "
                "reading isolation at all"
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
