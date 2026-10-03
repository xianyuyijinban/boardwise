"""ARCH closure (093 A3a): architecture self-consistency and **who said so**.

090 A1 built the contract, 091 A2a turned it into a repair *direction*, 092 A2b
spent it on two questions no board field can answer. None of those three moved a
severity: an intent stated a requirement, and the rule said what the two numbers
were. This batch is where intent first reaches the **grading**, so the line 052
§4 drew is written down as a table before any rule uses it:

===========================  ======  ================================================
the contract says           grade   what the row means
===========================  ======  ================================================
``user_stated``             ERROR   the engineer's own statement is violated by the
                                     drawing — a contradiction with a person's word
``verified_recipe``         WARN    a checked recipe, but not the engineer's signature:
                                     confirm before acting (see below)
``ai_asserted``             WARN    a draft disagreeing with the drawing is a hint,
                                     never a violation (052 §4)
absent (no contract)        —       nothing to contradict: **no row at all**, which
                                     is A1/A2's zero-movement reading, kept
nothing to do with intent    WARN   a **structural** closure, present or absent on the
                                     drawing itself: the shelf or the netlist states
                                     the requirement, so no contract is needed
===========================  ======  ================================================

Three notes on that table, because each one is a decision rather than a reading
of the words:

* **``verified_recipe`` grades as WARN, not ERROR.** The batch's table names two
  rows; the third tier of the contract's own vocabulary sits in between them
  (090 §二: ``user_stated`` > ``verified_recipe`` > ``ai_asserted``). ERROR is
  reserved for *the engineer's own statement* — the parent's own words are
  "工程师自己声明的架构被图纸违反" — and a recipe somebody else verified is not
  that. So both weaker tiers are WARN, and they are never confused: each row
  carries its own sentence saying which tier spoke. Moving a tier across this
  line is a one-row change to :data:`INTENT_GRADES`;
* **the ERROR tier is the only one that blocks a write.** ``edit/draw apply``
  grades the findings a run *grows* (#55 ruling B) and ``--force`` never releases
  an ERROR — see ``tests/test_093_arch_closure.py``, which drives this batch's
  ERROR through the gate's own function rather than a hand-made severity;
* **a structural rule needs no contract.** Whether an open-drain output has a
  pull-up, and whether a reset pin has anything on it, are facts about the
  drawing and the shelf; the grade is WARN, and the row names its source, its
  subject and its fix. An INFO **measurement** row is filed when the closure is
  satisfied — the 092 discipline ("测量永远报"): silence about a closed structure
  reads exactly like a rule that never looked.

One row of that table is answered **outside** :data:`INTENT_GRADES`, and it is
worth saying why rather than leaving it to the rule: a `user_stated` **waiver**
(the contract withdrawing its own requirement, ``closure: "waived"`` — 094 A3b)
is **INFO**, not ERROR. The two rows point in opposite directions. ERROR is for a
statement the drawing *contradicts*; a waiver is a statement that stops asking, so
there is nothing left to contradict — and it is the engineer's own decision, which
is exactly the kind of thing the tool exists to *report* rather than re-derive.
:data:`WAIVER_GRADE` / :data:`DRAFT_WAIVER_GRADE` carry the pair: a draft may not
exempt itself from a requirement it wrote (052 §4), so anything weaker than
`user_stated` is a WARN.

What each rule reads, and where its subject comes from:

* :class:`ArchRailVoltageClash` — ``arch-rail-voltage-clash``. The contract's
  ``requirements.rails[net=…].targetVoltage`` against the **drawing's own**
  verdict for the same net (:func:`boardwise.core.power_domains.infer_net_domains`).
  Both sources' raw fields and values travel in the message: this rule says the
  two documents disagree, and *which* one is wrong is the engineer's call — the
  same refusal 091 A2a made about an MPN/Value conflict. A drawing that prices
  no voltage for the net files nothing ("图上判不出 → 不查"), and neither does a
  rail the contract never priced;
* :class:`OpenDrainPullup` — ``arch-opendrain-pullup``. The shelf's
  ``pull_required`` records **marked** ``open_drain`` (F2's nFAULT, issue #56's
  data side): an open-drain output needs an external pull-up, and "there is a
  resistor from this net to a power-class rail" is that closure. The marker is
  what makes it this rule's subject rather than
  ``conn-usb-cc-pulldown``'s — a connector's CC pin is a *pull-down to ground*
  requirement (the same fact kind, the opposite direction), and a rule that read
  every ``pull_required`` record as a pull-up would report every correctly
  designed Type-C socket as a violation. A ``decisions[]`` entry declaring the
  pin uses the MCU's internal pull-up closes it too when it is ``user_stated`` —
  F2's own legitimate exit, since the dependency is real but invisible on the
  drawing. The subject is any component with such a shelf entry, whatever its
  designator prefix: ``DRV1`` is not ``U<digit>``, and widening ``IC_PATTERN``
  (which would put the part through every facts rule) is deliberately **not**
  this batch's change;
* :class:`NrstClosure` — ``arch-nrst-closure``. A controller (the shelf's
  ``category: ic.mcu``, or the architecture walk's existing evidence —
  :func:`boardwise.core.architecture.controller_evidence`) whose NRST/RESET pin
  sits on a net with nothing else on it: no capacitor, no key, no test point, no
  programmer pin (F3's shape, where the label is drawn but nothing is on the net).
* :class:`ArchSenseBiasClosure` — ``arch-sense-bias-closure`` (094 A3b, case F1).
  A chain the contract declares a bidirectional current sense needs a bias that
  can actually hold its node, and this rule *does the arithmetic* rather than
  asking whether something was drawn: the bias source's Thévenin resistance
  (``R_th = R_up‖R_dn + Rs``) against the sense resistance, and the voltage the
  node gets from it (``V_bias × R_sense/(R_th + R_sense)`` — F1's own formula,
  whose measured answer was 15.7µV against the 1.65V wanted). ``R_th ≥ R_sense``
  is graded by :func:`intent_grade` over the chain's provenance; the decade in
  between is a WARN; ``R_th ≤ R_sense/10`` or an op-amp output driving the net is
  an INFO measurement.

  **The ``1/10`` is this rule's own declared criterion, not a standard** — no
  datasheet says a bias source must be at most a tenth of the sense resistance. It
  is published as :data:`BIAS_CLOSURE_RATIO` and printed beside the numbers it was
  applied to, so a reader can disagree with the figure rather than with a threshold
  buried in an expression; the class docstring carries the same statement in full.
  **The topologies it prices** are two instances of one formula: a divider mid-net
  (``R_up`` to a power-class rail, ``R_dn`` to ground, the mid-point reaching the
  sense net through a series resistor ``Rs``) and a series resistor straight onto a
  priced rail (the rail's source impedance is zero). A resistor whose far net is
  neither is a topology this build cannot price — UNKNOWN naming what to draw,
  never a guess. New in
  this batch is the contract's side of it: an optional
  ``closure: "waived"`` on the signal, which is how the engineer's own decision
  (F1's R4: "0.1Ω 直采，不加放大器") becomes an INFO row quoting its rationale
  instead of a violation the tool keeps re-deriving.

Every rule that concludes from "what else is on this net" is listed in
:data:`boardwise.rules.unproven.NET_MEMBERSHIP_RULES` — on a net the per-page
merge welded blind, the row is UNKNOWN quoting the merge's own sentence, exactly
as issue #19 requires (see :mod:`boardwise.rules.unproven`).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..core.architecture import controller_evidence
from ..core.circuitspec import (
    PROVENANCE_AI,
    PROVENANCE_USER_STATED,
    PROVENANCE_VERIFIED,
)
from ..core.designintent import (
    BIAS_TOKENS,
    KIND_CURRENT_SENSE,
    POLARITY_BIDIRECTIONAL,
    SECTION_RAILS,
    SECTION_SIGNALS,
    IntentDecision,
    IntentSource,
    write_path,
)
from ..core.model import Component, DesignModel, is_ground_net
from ..core.parts import PartEntry
from ..core.power_domains import domain_of, infer_net_domains, voltage_from_net_name
from ..core.values import parse_voltage_volts
from .base import Finding, FindingTarget, Outcome
from .connectivity import parse_resistance_ohms
from .facts import FactsRule, _pin_net
from .unproven import unproven_nets, unproven_outcome

LEVEL = "L2-facts"

#: The intent → severity table (module docstring). One row per tier of the
#: contract's own vocabulary, so "what grade does a violated statement get" is
#: answered by data rather than by a chain of ifs inside a rule.
#:
#: ``PROVENANCE_USER_STATED`` is the only ERROR: it is the engineer's statement,
#: and the drawing contradicting it is what the tier exists for. The two weaker
#: tiers are WARN with their own wording — a draft may not be graded as a
#: violation (052 §4), and a recipe somebody verified is stronger than a guess
#: but is still not the engineer's own word.
INTENT_GRADES: dict[str, str] = {
    PROVENANCE_USER_STATED: "ERROR",
    PROVENANCE_VERIFIED: "WARN",
    PROVENANCE_AI: "WARN",
}

#: The grade a violation gets when the entry states a tier this build does not
#: know (a hand-built document, a future token). WARN, not ERROR: ERROR requires
#: a statement this build can *name*, and an unreadable tier is not one.
UNKNOWN_GRADE = "WARN"

#: The grade a **structural** closure violation gets (the table's fourth row).
#: Not "INFO with a loud message": a missing pull-up and a naked reset pin are
#: defects the drawing itself establishes, so they are WARN.
STRUCTURAL_GRADE = "WARN"

#: What a satisfied structural closure is reported as: a measurement (INFO), so
#: a reader can tell "checked and fine" from "never looked".
MEASUREMENT_GRADE = "INFO"

#: The key an open-drain pull-up is marked with inside a shelf ``pull_required``
#: record. The record itself is the shelf's existing shape (``pin`` / ``to`` /
#: ``expected_value`` / ``provenance``); this one boolean is what says the
#: requirement is an **external pull-up for an open-drain output** rather than a
#: connector's pull-down, and therefore which rule judges it.
OPEN_DRAIN_KEY = "open_drain"

#: The words a design decision may use to declare that the pin's pull-up is the
#: controller's **internal** one (F2's exit: "除非固件把 PB12 配成内部上拉").
#: Matched case-insensitively against the decision's prose; two languages,
#: because the contract is written by this project's engineer in Chinese and the
#: datasheets it quotes are English.
INTERNAL_PULLUP_TOKENS: tuple[str, ...] = (
    "内部上拉",
    "内部弱上拉",
    "内建上拉",
    "internal pull",
)

#: The pin-name segment that means "this is the reset pin": ``NRST``, ``nRST``,
#: ``RESET``, ``RESET#``, and the compound spellings a library symbol uses
#: (``PG10-NRST``). The name is split on everything that is not alphanumeric and
#: a **segment** has to be the word, so ``PRESET``, ``NRSTX`` and a bare
#: ``PB12`` are not reset pins — while a compound name that carries the word
#: (``NRST_DRV``, ``RESET_CONF``) is one, because the symbol really is naming a
#: reset there.
RESET_SEGMENTS: frozenset[str] = frozenset({"nrst", "rst", "reset", "nreset"})

#: The citation F3's finding rests on. Kept as one string here and quoted by
#: every row, because the *fix* is what the citation is for.
NRST_CITATION = (
    "ST AN5093（STM32G4 硬件设计指南）NRST 章节建议复位脚对地 100nF 滤波"
    "（F3 实案记录引用；该记录的原文来自检索片段，未读到 PDF 正文）"
)


# ---------------------------------------------------------------------------
# the grading table
# ---------------------------------------------------------------------------


def intent_grade(entry: object) -> tuple[str, str]:
    """``(severity, why)`` for a drawing that contradicts this intent entry.

    The one place :data:`INTENT_GRADES` is read, so "who said it decides how
    loud a contradiction is" cannot drift between the rules that consume it.
    ``why`` is the sentence a row carries: each tier gets its own words, so a
    reader of a WARN can tell a *recipe* apart from a *draft* without knowing
    the table — and so a row never reads as a statement about a design nobody
    has signed (052 §4).

    An entry with no provenance at all reads as the contract's default
    (``ai_asserted``, the draft tier) rather than as a missing answer: the
    parser already normalises it that way, and a second normalisation here
    would let a hand-built document grade differently from a loaded one.
    """
    provenance = str(getattr(entry, "provenance", "") or "") or PROVENANCE_AI
    severity = INTENT_GRADES.get(provenance, UNKNOWN_GRADE)
    if provenance == PROVENANCE_USER_STATED:
        return severity, (
            "分级 ERROR（093 §〇）：这条声明是 `user_stated` —— 工程师自己声明的"
            "架构被图纸违反，不是草稿不一致"
        )
    if provenance == PROVENANCE_VERIFIED:
        return severity, (
            "分级 WARN（093 §〇）：这条声明是 `verified_recipe` —— 别人验证过的配方，"
            "不是工程师本人声明，请确认后再动"
        )
    if provenance == PROVENANCE_AI:
        return severity, (
            "分级 WARN（093 §〇）：这条声明是 `ai_asserted` 草稿（052 §4）—— 草图与"
            "图纸不一致只能当提示，确认前不要照改"
        )
    return severity, (
        f"分级 WARN（093 §〇）：这条声明的 provenance 是 {provenance!r}，本 build 的"
        "分级表里没有这一档；下判决要有说得出的来源，所以按待确认 WARN 报"
    )


# ---------------------------------------------------------------------------
# shared readings
# ---------------------------------------------------------------------------


def _components(model: DesignModel) -> list[Component]:
    """Every component, by designator — the walk order every rule here uses."""
    return [model.components[key] for key in sorted(model.components)]


def _members(model: DesignModel, net: str | None) -> list[tuple[str, str]]:
    """``[("U1", "7"), …]`` — the pins on a net, in the netlist's own order."""
    if not net:
        return []
    node = model.nets.get(net)
    return [] if node is None else [(str(des), str(pin)) for des, pin in node.pins]


def _read_members(model: DesignModel, net: str | None) -> list[tuple[str, str]]:
    """The pins *this file reads on its own account*, in designator order.

    ``_members`` answers in the netlist's own order, which is not a design fact:
    a netlist is a list, ``compare``/``reconcile_names`` reorder it, and the same
    board read twice can hand the same pins over the other way round (issue #57
    finding 6). A reading this file makes for itself — the resistors it collects,
    which of them is the shunt, the amplifier it names — goes through here
    instead, so a verdict and its evidence are a function of the board rather
    than of the order a list happened to arrive in. The two places that quote
    what the *netlist* says (``_quoted_members`` at the ARCH-1/ARCH-3 rows) keep
    the netlist's own order: their text is already published, and re-ordering it
    would move rows this batch does not touch.
    """
    return sorted(_members(model, net))


def _quoted(pins) -> str:
    """``"U1.7, C73.1"`` — a pin list as the rows quote it."""
    return ", ".join(f"{des}.{pin}" for des, pin in pins) or "（网里没有成员）"


def _quoted_members(model: DesignModel, net: str | None) -> str:
    return _quoted(_members(model, net))


def _power_class(guesses: dict, net: str | None) -> str:
    """Why ``net`` counts as a **power-class** rail — or ``""`` when it does not.

    Two sources, both already established in this codebase, and the same two
    :func:`boardwise.core.power_domains.infer_net_domains` uses: a net name that
    states its own voltage (``+12V``), and a rail the drawing prices through a
    regulator's output pin (``VCC`` under an AMS1117). Ground is not one of them
    — nothing prices a ground net as a rail — so a resistor to ground is a
    pull-*down*, which is exactly the distinction that keeps this rule from
    judging a connector's CC pins.
    """
    if not net or is_ground_net(net):
        return ""
    named = voltage_from_net_name(net)
    if named is not None:
        return f"net name {net!r} 报了 {named[0]:g} V"
    guess = guesses.get(net)
    if guess is not None and guess.is_known:
        return guess.source
    return ""


def _resistor_like(rule: FactsRule, comp: Component | None) -> bool:
    """Is this part a resistor? — the reading ``conn-usb-cc-pulldown`` uses.

    The shelf wins when it declares a category (a capacitor is not made a
    resistor by a value that happens to parse); a part with no entry, or an
    entry with no category, falls back to the value's own unit. One judgement,
    two rules, so "a resistor is on this net" cannot mean two things.
    """
    if comp is None:
        return False
    entry = rule.entry_for(comp)
    if entry is not None and entry.category:
        return entry.category == "resistor"
    return parse_resistance_ohms(comp.value or "") is not None


@dataclass(frozen=True)
class PullUp:
    """One resistor that bridges a net to a power-class rail — the closure's evidence."""

    designator: str
    value: str
    rail: str
    because: str


def _pull_up_to_power(model: DesignModel, guesses: dict, rule: FactsRule, net: str, holder: str) -> PullUp | None:
    """The first resistor from ``net`` to a power-class rail, or ``None``.

    Only parts the shelf (or their own value) calls resistors count, and only a
    rail this build can *price* counts as power-class: a capacitor from the net
    to a rail is a filter, not a pull-up, and a rule that accepted one would
    report the wrong thing as closed. ``holder`` is the part whose pin raised
    the question — its own two feet bridge nothing useful here.
    """
    for designator, _pin in _members(model, net):
        if designator == holder:
            continue
        comp = model.components.get(designator)
        if not _resistor_like(rule, comp):
            continue
        for pin in comp.pins:
            far = pin.net
            if not far or far == net:
                continue
            because = _power_class(guesses, far)
            if because:
                return PullUp(
                    designator=designator,
                    value=(comp.value or ""),
                    rail=far,
                    because=because,
                )
    return None


# ---------------------------------------------------------------------------
# R1: the contract's rail voltage against the drawing's own reading
# ---------------------------------------------------------------------------


class ArchRailVoltageClash(FactsRule):
    """ARCH-1: the contract and the drawing price the same rail the same way.

    The two documents are read **without a winner**: the contract's
    ``targetVoltage`` is the requirement and the drawing's own verdict
    (:func:`infer_net_domains`) is what the board does, and this rule's job is
    the one 092's ``pwr-cap-voltage-rating`` explicitly declined — to say the
    two disagree. Which of them is wrong is not a tool's call (091 A2a made the
    same refusal about an MPN/Value conflict), so the row quotes both raw fields
    and both values and lets a person decide.

    Three silences, each with its own reason: no contract at all (nothing
    states a requirement — A1's zero-movement reading), no declared voltage for
    the rail (the subject is the clash, and 092's rule already reports the
    missing slot as ``intent-missing``), and a drawing that prices no voltage
    for the net ("图上判不出 → 不查" — a net nobody priced has nothing to
    disagree with).
    """

    id = "arch-rail-voltage-clash"
    title = "The contract's rail voltage and the drawing's own reading agree"
    level = LEVEL
    source = (
        "the design intent's requirements.rails[].targetVoltage against the "
        "drawing's own net-voltage inference (core.power_domains); the grade is "
        "the intent's own provenance (093 A3a, 093 §〇)"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        #: The contract this reading was handed (or ``None``) — handed in at
        #: construction like every other intent consumer (091 A2a's seam), so a
        #: module-level instance never carries one run's answer into the next.
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity, target)
            for outcome, severity, target in self._rows(model)
            if severity is not None
        ]

    def _rows(
        self, model: DesignModel
    ) -> list[tuple[Outcome, str | None, FindingTarget | None]]:
        if self.intent is None:
            # No contract, no requirement, nothing to contradict — the subject
            # *is* the declaration (092 A2b's reading, unchanged).
            return []
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None, FindingTarget | None]] = []
        for rail in self.intent.document.rails:
            declared = str(rail.value("targetVoltage") or "").strip()
            slot = write_path(SECTION_RAILS, rail.net, "targetVoltage")
            if not declared:
                continue
            stated = parse_voltage_volts(declared)
            if stated is None or stated <= 0:
                # A declaration this build cannot read is 092's row
                # (`pwr-cap-voltage-rating` reports it as `intent-missing`), and
                # reporting the same unreadable slot twice in two wordings is
                # how two rules start disagreeing.
                continue
            drawing, drawing_source, _why = domain_of(guesses, rail.net)
            if drawing is None:
                continue
            # Issue #19: the drawing's side of this comparison may have been
            # inferred from a regulator's output pin on a page that only shares
            # the net's name, so on a welded name neither "they agree" nor
            # "they clash" is established.
            welded = unproven_nets(model, (rail.net,))
            target = FindingTarget(net_refs=[rail.net])
            evidence = [
                f"合同 {slot} = {declared!r}（{stated:g} V）",
                f"图纸 {rail.net} = {drawing:g} V —— 来源：{drawing_source}",
            ]
            if welded:
                rows.append((
                    unproven_outcome(
                        self.id,
                        rail.net,
                        welded,
                        what=(
                            f"what voltage the drawing puts on rail {rail.net!r} "
                            "and therefore whether it agrees with the contract"
                        ),
                        evidence=evidence,
                    ),
                    MEASUREMENT_GRADE,
                    target,
                ))
                continue
            if abs(stated - drawing) < 1e-9:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=rail.net,
                        message=(
                            f"{rail.net}：合同 {slot} = {declared!r}（{stated:g} V）与"
                            f"图纸的读数 {drawing:g} V 一致（图纸依据："
                            f"{drawing_source}）—— 两处说得一样，无自洽问题"
                        ),
                        evidence=evidence,
                    ),
                    None,
                    target,
                ))
                continue
            severity, why = intent_grade(rail)
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=rail.net,
                    message=(
                        f"{rail.net}：合同 {slot} = {declared!r}（{stated:g} V）与图纸的"
                        f"读数 {drawing:g} V **不一致**（图纸依据：{drawing_source}）"
                        " —— 两个来源的原始字段与值都在这里，谁错由人裁：本工具只说"
                        "「两处说得不一样」，不替你选边。改一处：把该轨的声明改对，"
                        "或把图纸画到合同上。" + why
                    ),
                    evidence=evidence,
                ),
                severity,
                target,
            ))
        return rows


# ---------------------------------------------------------------------------
# R2: an open-drain output with nothing pulling it up
# ---------------------------------------------------------------------------


class OpenDrainPullup(FactsRule):
    """ARCH-2: an open-drain output the shelf declares has an external pull-up.

    The subject is the shelf's own claim — a ``pull_required`` record marked
    :data:`OPEN_DRAIN_KEY` — and for each such pin the question is "is there a
    resistor from this net to a power-class rail". Three answers:

    * there is one — **INFO** measurement, naming the resistor, its value and the
      rail it reaches (the closure, stated so a reader can disagree with it);
    * there is none, but a ``decisions[]`` entry names this pin's net and
      declares the controller's **internal** pull-up with provenance
      ``user_stated`` — **INFO**, quoting the decision as the basis (F2's own
      legitimate exit: the dependency is real, and a drawing cannot show it);
    * there is none — **WARN**, naming the pin, the net, the datasheet line it
      comes from and the fix (``10k`` to the rail the shelf names), plus a
      caveat when a *draft* decision claims an internal pull-up (a guess may not
      close anything — 052 §4).

    A pin that reaches no net at all files the same WARN: nothing is on it
    either, and "the pin is not drawn" is not a closure.
    """

    id = "arch-opendrain-pullup"
    title = "An open-drain output the shelf declares has an external pull-up"
    level = LEVEL
    source = (
        "the shelf's pull_required records marked open_drain (DRV8313 nFAULT "
        "pin18: TI SLVSBA5C p.3 pin table, 'open-drain output requires an "
        "external pullup'), against the net's members and the contract's "
        "decisions[] (093 A3a)"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity)
            for outcome, severity in self._rows(model)
            if severity is not None
        ]

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in _components(model):
            entry = self.entry_for(comp)
            if entry is None:
                continue
            for record in self._open_drain_records(entry):
                rows.append(self._row(model, guesses, comp, record))
        return rows

    @staticmethod
    def _open_drain_records(entry: PartEntry) -> list[dict]:
        """The shelf's pull requirements that are **open-drain pull-ups**.

        One filter, and it is the whole reason the marker exists: the same fact
        kind carries a connector's CC pull-down, which is the opposite
        requirement and another rule's subject (``conn-usb-cc-pulldown``).
        """
        out = []
        for record in (entry.facts or {}).get("pull_required", []):
            if isinstance(record, dict) and record.get(OPEN_DRAIN_KEY) is True:
                out.append(record)
        return out

    def _row(
        self, model: DesignModel, guesses: dict, comp: Component, record: dict
    ) -> tuple[Outcome, str | None]:
        ref = comp.designator
        pin = str(record.get("pin", ""))
        declared_to = str(record.get("to", ""))
        expected = str(record.get("expected_value", ""))
        citation = str(record.get("provenance", ""))
        subject = f"{ref} pin{pin}"
        name = _pin_name(comp, pin)
        identity = f"{subject}（{name}）" if name else subject
        net = _pin_net(comp, pin)
        requirement = (
            f"货架条目 {comp.mpn or comp.lcsc or ref} 的 pull_required[pin={pin}]"
            f" 标了 open_drain = true（要求：{expected} 上拉到 {declared_to!r}）"
            f"，出处：{citation}"
        )
        if net is None:
            return (
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=subject,
                    message=(
                        f"{identity} 不接任何网，所以这个开漏输出没有任何上拉 —— "
                        f"{requirement}。修法：给该脚加 {expected} 上拉到 "
                        f"{declared_to!r}（power-class 轨）"
                    ),
                    evidence=[f"{subject} @ (no net)", requirement],
                ),
                STRUCTURAL_GRADE,
            )
        evidence = [f"{subject} @ {net}", requirement]
        members = _quoted_members(model, net)
        # Issue #19: "a resistor from this net to a rail" is read from the net's
        # members, so on a name the per-page merge welded blind both the missing
        # pull-up and the found one are unestablished.
        welded = unproven_nets(model, (net,))
        if welded:
            return (
                unproven_outcome(
                    self.id,
                    subject,
                    welded,
                    what=f"whether a resistor pulling {net!r} up to a power rail sits on it",
                    evidence=evidence,
                ),
                MEASUREMENT_GRADE,
            )
        pull = _pull_up_to_power(model, guesses, self, net, ref)
        decision, draft_decision = self._internal_pullup_decision(model, net, ref, pin)
        if pull is not None:
            return (
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=subject,
                    message=(
                        f"{identity}在网 {net!r} 上有上拉：{pull.designator}"
                        f"（{pull.value}）跨到 {pull.rail!r}（power-class，依据："
                        f"{pull.because}）—— 开漏输出的外部上拉闭合（测量行）。"
                        f"{requirement}"
                    ),
                    evidence=[
                        *evidence,
                        f"{net} 成员：{members}",
                        f"{pull.designator} value {pull.value!r} @ {pull.rail}",
                    ],
                ),
                MEASUREMENT_GRADE,
            )
        if decision is not None:
            return (
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=subject,
                    message=(
                        f"{identity}在网 {net!r} 上没有上拉电阻，但合同 "
                        f"decisions[subject={decision.subject!r}] 声明「"
                        f"{decision.decision}」（provenance = "
                        f"{decision.provenance}）—— 按设计决策闭合（依据 = 设计决策，"
                        "不是图纸上的电阻）。这条依赖图纸上看不出来，固件里必须真的"
                        f"开这个内部上拉。{requirement}"
                    ),
                    evidence=[
                        *evidence,
                        f"{net} 成员：{members}",
                        f"合同 decisions[subject={decision.subject!r}] = "
                        f"{decision.decision!r}（{decision.provenance}）",
                    ],
                ),
                MEASUREMENT_GRADE,
            )
        draft_note = ""
        if draft_decision is not None:
            draft_note = (
                f"；合同里另有一条 decisions[subject={draft_decision.subject!r}]"
                f"（{draft_decision.provenance}）提到内部上拉，但 {draft_decision.provenance}"
                " 不是 user_stated，不按它判闭合（052 §4：草稿只能当提示）"
            )
        return (
            Outcome(
                rule_id=self.id,
                state="VIOLATION",
                subject=subject,
                message=(
                    f"{identity}在网 {net!r} 上没有上拉：网成员 {members} 里没有电阻"
                    "跨到 power-class 轨 —— 开漏输出悬空时该标志读不出来（F2 实案）。"
                    f"{requirement}。修法：给 {net!r} 加 {expected} 上拉到 "
                    f"{declared_to!r}（power-class 轨，如 VCC），或在合同 decisions[] 里"
                    f"写明「{subject} 用 MCU 内部上拉」并把这条依赖写进设计文档"
                    + draft_note
                ),
                evidence=[*evidence, f"{net} 成员：{members}"],
            ),
            STRUCTURAL_GRADE,
        )

    def _internal_pullup_decision(
        self, model: DesignModel, net: str, ref: str, pin: str
    ) -> tuple[IntentDecision | None, IntentDecision | None]:
        """``(the user_stated decision that closes it, the draft one that does not)``.

        The lookup is by **exact identity** (090's rule: one entry is one
        object): the pin's own spelling first (``DRV1.18``), then every
        designator on the net (F2's "固件把 PB12 配成内部上拉" is a statement
        about the MCU, not about the driver). Nothing else in the decision is
        matched fuzzily — only its prose is read, and only for the words in
        :data:`INTERNAL_PULLUP_TOKENS`.
        """
        if self.intent is None:
            return None, None
        subjects = [f"{ref}.{pin}"] + sorted({des for des, _pin in _members(model, net)})
        draft: IntentDecision | None = None
        for subject in subjects:
            decision = self.intent.decision(subject)
            if decision is None or not _declares_internal_pullup(decision):
                continue
            if decision.provenance == PROVENANCE_USER_STATED:
                return decision, draft
            draft = draft or decision
        return None, draft


def _declares_internal_pullup(decision: IntentDecision) -> bool:
    """Does this decision say the pin's pull-up is the controller's internal one?"""
    text = f"{decision.decision} {decision.rationale}".lower()
    return any(token in text for token in INTERNAL_PULLUP_TOKENS)


# ---------------------------------------------------------------------------
# R3: a controller's reset pin with nothing on it
# ---------------------------------------------------------------------------


class NrstClosure(FactsRule):
    """ARCH-3: a controller's reset pin has something attached to it.

    Which parts are controllers is the architecture walk's existing reading
    (:func:`boardwise.core.architecture.controller_evidence`: the shelf's
    ``category: ic.mcu``, or the symbol's own ``P<port><n>`` pin names), and
    which pin is the reset is read off the pin's **name** — the netlist is the
    only place that says it, and ``PG10-NRST`` is how a library symbol writes it.

    The requirement is one sentence: something has to be on that net. A
    capacitor, a key, a test point, a programmer's header or a supervisor all
    count; anything else on the net counts too, because the rule is "the pin is
    not alone", not "the part is the right one" — a reviewer who wants to argue
    about the 100 nF reads the INFO row that names what is there.

    F3's shape is the single-member net: the drawing shows a net label and
    nothing is under it, which is indistinguishable from a plain mistake on a
    rendering. The row says so and names the consequences (noise and ESD on a
    motor platform; no connect-under-reset channel without NRST on the SWD
    header) and the fix.
    """

    id = "arch-nrst-closure"
    title = "A controller's reset pin has something on its net"
    level = LEVEL
    source = (
        "the controller recognition of core.architecture (shelf ic.mcu or the "
        "symbol's P<port><n> pins) against the reset pin's net members; "
        + NRST_CITATION
    )

    def __init__(self, library=None) -> None:
        super().__init__(library)

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity)
            for outcome, severity in self._rows(model)
            if severity is not None
        ]

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        rows: list[tuple[Outcome, str | None]] = []
        for comp in _components(model):
            evidence = controller_evidence(comp, self.library)
            if not evidence:
                continue
            for pin in _reset_pins(comp):
                rows.append(self._row(model, comp, pin, evidence))
        return rows

    def _row(self, model: DesignModel, comp: Component, pin, by: str) -> tuple[Outcome, str | None]:
        subject = f"{comp.designator} pin{pin.number}"
        identity = f"{subject}（{pin.name}）" if pin.name else subject
        where = f"控制器判据：{by}"
        if not pin.net:
            return (
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=subject,
                    message=(
                        f"{identity} 不接任何网 —— 复位脚裸奔：没有电容、没有按键、"
                        "没有测试点、也没有编程器引出（F3 实案形状）。后果：电机噪声/"
                        "静电容易造成随机复位；SWD 没有 NRST 就没有 connect-under-reset "
                        f"通道。修法：NRST 对地 100nF、并把 NRST 引到 SWD 座。依据："
                        f"{NRST_CITATION}；{where}"
                    ),
                    evidence=[f"{subject} @ (no net)", where],
                ),
                STRUCTURAL_GRADE,
            )
        members = _members(model, pin.net)
        evidence = [f"{subject} @ {pin.net}", f"{pin.net} 成员：{_quoted_members(model, pin.net)}", where]
        # Issue #19: "nothing else is on this net" is read from the net's
        # members, and on a welded name that count is not this board's.
        welded = unproven_nets(model, (pin.net,))
        if welded:
            return (
                unproven_outcome(
                    self.id,
                    subject,
                    welded,
                    what=f"whether anything else sits on this reset pin's net {pin.net!r}",
                    evidence=evidence,
                ),
                MEASUREMENT_GRADE,
            )
        if len(members) > 1:
            return (
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=subject,
                    message=(
                        f"{identity}在网 {pin.net!r} 上有 {len(members)} 个成员"
                        f"（{_quoted_members(model, pin.net)}）—— 复位脚不裸奔"
                        f"（测量行）。{where}"
                    ),
                    evidence=evidence,
                ),
                MEASUREMENT_GRADE,
            )
        return (
            Outcome(
                rule_id=self.id,
                state="VIOLATION",
                subject=subject,
                message=(
                    f"{identity}在网 {pin.net!r} 上是**单成员网**（网上只有它自己 "
                    f"—— 图纸里那条网络标签底下没有第二件东西，正是 F3 的形状）："
                    "没有电容、没有按键、没有测试点、也没有编程器引出。后果：电机噪声/"
                    "静电容易造成随机复位；SWD 没有 NRST 就没有 connect-under-reset "
                    f"通道。修法：NRST 对地 100nF（并把 NRST 引到 SWD 座）。依据："
                    f"{NRST_CITATION}；{where}"
                ),
                evidence=evidence,
            ),
            STRUCTURAL_GRADE,
        )


def _reset_pins(comp: Component) -> list:
    """The component's reset pins, by name, in pin order."""
    return [pin for pin in comp.pins if _is_reset_name(pin.name)]


#: A pin name split into its words: anything that is not alphanumeric separates
#: (`PG10-NRST` -> `PG10`, `NRST`; `RESET#` -> `RESET`).
_NAME_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")


def _is_reset_name(name: str | None) -> bool:
    """Is this pin name a reset? ``PG10-NRST`` yes, ``PRESET``/``NRSTX`` no."""
    return any(
        segment.lower() in RESET_SEGMENTS
        for segment in _NAME_SEPARATORS.split(str(name or ""))
    )


def _pin_name(comp: Component, number: str) -> str:
    for pin in comp.pins:
        if pin.number == number:
            return pin.name or ""
    return ""


# ---------------------------------------------------------------------------
# R4: the bias a bidirectional sense chain lands on (094 A3b, case F1)
# ---------------------------------------------------------------------------


#: The ratio this rule accepts as a **closed** bias: the bias source's Thévenin
#: resistance against the sense resistance (``R_th ≤ R_sense/10``).
#:
#: **This is this rule's own declared criterion, not a standard**, and it is a
#: named constant for exactly that reason: no datasheet and no app note says "a
#: bias source must be at most a tenth of the sense resistance". It is the line
#: this build draws between "the divider is the node's bias" (it can hold the node
#: where it says, to within a few percent) and "the divider is a stray load on a
#: node something else holds" — and a reader is meant to be able to disagree with
#: the *number* rather than with a threshold hidden in an expression. The
#: *arithmetic* beside it is F1's own and is not a criterion at all.
BIAS_CLOSURE_RATIO = 0.1

#: The grade a **`user_stated` waiver** gets (``closure: "waived"``): INFO, with
#: the decision's rationale quoted. The board is not judged against a requirement
#: its author withdrew, and the row says which decision withdrew it — so a reader
#: can disagree with the decision rather than with a silence.
WAIVER_GRADE = "INFO"

#: The grade a **weaker tier's waiver** gets: WARN. A draft exempting itself from
#: its own requirement is 052 §4's case exactly (a guess may not be the yardstick
#: a board is judged against), so the row is loud and names who waived what.
DRAFT_WAIVER_GRADE = "WARN"

#: The grade a **marginal** ratio gets (``R_sense/10 < R_th < R_sense``): WARN, on
#: the drawing's own numbers rather than on anybody's provenance. The bias is real
#: and its ratio is inside the decade the closure criterion wants — "look at this"
#: rather than "somebody's statement is contradicted".
MARGIN_GRADE = "WARN"

#: The physics the whole rule rests on, quoted by every failing row (F1's own
#: sentence, generalised off the 0.1Ω figure).
BIAS_PHYSICS = (
    "要让采样节点真坐在偏置电压上，偏置源内阻必须 ≪ 采样电阻 R_sense —— 电阻分压"
    "（R_up‖R_dn）再经一只串阻 Rs 送进来，物理上做不到（正确形态是运放缓冲/差分"
    "放大器把偏置电压送到求和点）。"
)


#: The pin-name prefixes that mean "this is the amplifier's output" — the reading
#: `NrstClosure` makes one function up, and for the same reason: which pin is the
#: output is written on the symbol, and the netlist is where a rule can read it.
#: A *segment* has to start with one of these, so `OUT`, `OUTA`, `OUT1`, `VOUT`
#: and `VOUTA` all count while `SHOUT` and a bare pin number do not.
OUTPUT_NAME_PREFIXES: tuple[str, ...] = ("out", "vout")


def _ohms(value: float) -> str:
    """One resistance, as a message writes it: ``10500Ω``, ``0.1Ω``, ``10kΩ``."""
    if value and abs(value) >= 1000 and abs(value) % 1000 == 0:
        return f"{value / 1000:g}kΩ"
    return f"{value:g}Ω"


def _volts(value: float | None) -> str:
    """One voltage, in the unit a reader can compare (F1 writes ``15.7µV``)."""
    if value is None:
        return "（算不出）"
    if value == 0:
        return "0V"
    magnitude = abs(value)
    if magnitude < 1e-3:
        return f"{value * 1e6:.1f}µV"
    if magnitude < 1:
        return f"{value * 1e3:.1f}mV"
    if magnitude >= 1e6:
        return f"{value / 1e6:g}MV"
    return f"{value:g}V"


def _orders(wanted: float | None, got: float | None) -> str:
    """How far apart two voltages are, in orders of magnitude (or ``""``)."""
    if not wanted or not got or wanted <= 0 or got <= 0:
        return ""
    ratio = wanted / got
    if ratio < 10:
        return ""
    return f"，差约 {int(math.floor(math.log10(ratio)))} 个数量级"


@dataclass(frozen=True)
class ResistorLeg:
    """One resistor sitting on a net, with its **other** end read.

    ``net`` is the net it was found on and ``far`` the net on the other side of
    it; ``far_power`` is :func:`_power_class`'s own reason string when the far net
    is a priced power rail (empty otherwise), and ``far_is_ground`` says whether
    the far end is ground — the two facts that decide which role the resistor
    plays (the shunt, a direct pull to a rail, one leg of a divider, or a stray).
    """

    designator: str
    value: str
    ohms: float
    net: str
    far: str
    far_is_ground: bool
    far_power: str


def _resistor_legs(
    model: DesignModel, guesses: dict, rule: FactsRule, net: str, *, exclude: str = ""
) -> list[ResistorLeg]:
    """Every resistor on ``net`` whose far end can be read, in designator order.

    A part the shelf (or its own value) does not call a resistor is skipped —
    :func:`_resistor_like`'s one judgement, the same the pull-up rule uses — and a
    resistor whose value does not parse as a resistance is skipped too: a row that
    printed ``R17（10kΩ）`` for a value nobody could read would be inventing the
    number the arithmetic then rests on.

    "In designator order" is a promise this docstring used to make and the code
    kept only by accident: it walked ``_members``, i.e. the netlist's own order,
    so the list — and with it ``shunts[0]`` — moved when the netlist did (issue
    #57 finding 6). It now reads through :func:`_read_members` and the promise is
    the code.
    """
    legs: list[ResistorLeg] = []
    for designator, _pin in _read_members(model, net):
        if designator == exclude:
            continue
        comp = model.components.get(designator)
        if not _resistor_like(rule, comp):
            continue
        far = next((pin.net for pin in comp.pins if pin.net and pin.net != net), "")
        if not far:
            continue
        ohms = parse_resistance_ohms(comp.value or "")
        if ohms is None or ohms <= 0:
            continue
        legs.append(ResistorLeg(
            designator=designator,
            value=(comp.value or ""),
            ohms=ohms,
            net=net,
            far=far,
            far_is_ground=is_ground_net(far),
            far_power=_power_class(guesses, far),
        ))
    return legs


#: The word the contract's own vocabulary uses for "this chain is a current
#: sense" (``KIND_CURRENT_SENSE``), read here as the **block** spelling of the
#: same claim: an ``IntentBlock`` whose ``kind`` is this says "these parts
#: realise this job" (A3a), and the part among them that sits on the chain to
#: ground is the contract's answer to "which resistor is the shunt".
SENSE_BLOCK_KIND = KIND_CURRENT_SENSE


def _declared_sense_parts(intent: IntentSource | None) -> dict[str, str]:
    """``designator -> "blocks[id='senseU'].parts"`` — the contract's role claims.

    Read as data, like every other consumer of this channel: the block is quoted,
    not interpreted. A document that carries none — the usual case, and every
    board without a contract — answers an empty mapping, which is "the contract
    said nothing", never "the contract said no".
    """
    declared: dict[str, str] = {}
    document = getattr(intent, "document", None)
    for block in getattr(document, "blocks", None) or []:
        if str(getattr(block, "kind", "") or "") != SENSE_BLOCK_KIND:
            continue
        where = f"blocks[id={getattr(block, 'id', '')!r}].parts"
        for part in getattr(block, "parts", None) or []:
            declared.setdefault(str(part), where)
    return declared


def _sense_shunt(
    intent: IntentSource | None, shunts: list[ResistorLeg]
) -> tuple[ResistorLeg | None, str, str]:
    """The sense shunt among ``shunts`` — by electrical role, never by list order.

    Returns ``(leg, declared_where, refusal)``: the shunt and the declaration that
    named it (empty when the reading fell back to structure), or — ``leg is
    None`` — the refusal saying why the two sources disagree. Two readings, in
    this order (issue #57 finding 6):

    * **the contract's role declaration** (A3a): a ``current-sense`` block whose
      ``parts`` name one of the resistors sitting on this chain to ground;
    * **the smallest resistance**: a sense shunt *is* the part that is orders of
      magnitude below the bleeders and dividers around it, so among the
      resistors to ground the smallest one is the sense part. Ties break on the
      designator, so the answer is a function of the board rather than of the
      order a list arrived in — which is the defect this replaces, ``shunts[0]``.

    When the declaration names a part that is **not** the smallest one, the two
    readings contradict each other and this build does not choose: "the contract
    is out of date" and "the smallest resistor is a bleeder, not the shunt" are
    both plausible, and which one to change is the engineer's decision. A
    declaration that names several of them is the same question in a third form.
    Both answer ``None`` and a sentence naming the parts and the numbers, which
    the caller files as a row.
    """
    smallest = min(shunts, key=lambda leg: (leg.ohms, leg.designator))
    declared = _declared_sense_parts(intent)
    named = [leg for leg in shunts if leg.designator in declared]
    if not named:
        return smallest, "", ""
    if len(named) > 1:
        listed = "、".join(
            f"{leg.designator}（{_ohms(leg.ohms)}）"
            for leg in sorted(named, key=lambda leg: leg.designator)
        )
        sources = "、".join(sorted({declared[leg.designator] for leg in named}))
        return None, "", (
            f"合同把 {listed} 都声明成这条链的电流采样件（{sources}）—— "
            "哪一颗是采样电阻，声明本身没说清"
        )
    only = named[0]
    if only.ohms > smallest.ohms:
        return None, "", (
            f"声明与结构矛盾：合同 {declared[only.designator]} 点名 "
            f"{only.designator}（{_ohms(only.ohms)}）是这条链的采样件，而网上到地的"
            f"电阻里阻值最小的是 {smallest.designator}（{_ohms(smallest.ohms)}）"
        )
    return only, declared[only.designator], ""


@dataclass(frozen=True)
class BiasSource:
    """A bias a chain's net really gets, priced (094 A3b).

    ``r_source`` is the source's own Thévenin resistance **before** the series
    resistor (R_up‖R_dn for a divider, 0 for a resistor straight onto a rail), and
    ``v_open`` is the voltage it would hold unloaded (the divider's ratio applied
    to its rail, or the rail itself). ``v_open`` is ``None`` when the rail behind
    it cannot be priced — in which case the *resistance* verdict still stands and
    the row says which rail has to be priced. ``is_divider`` is which of the two
    shapes this is, so a message can write the terms it actually used
    (``R_up‖R_dn + Rs``, or ``Rs`` alone) rather than a formula label that does
    not match the board.
    """

    designators: tuple[str, ...]
    shape: str
    r_source: float
    v_open: float | None
    volts_because: str
    is_divider: bool


def _bias_source(
    model: DesignModel, guesses: dict, rule: FactsRule, leg: ResistorLeg
) -> BiasSource | None:
    """Price the bias ``leg`` feeds, or ``None`` when this build cannot price it.

    Two shapes, both instances of the same arithmetic:

    * **a series resistor straight onto a power rail** — the rail is the source
      and its impedance is zero, so ``R_th`` is the resistor alone;
    * **a divider mid-net** — ``R_up`` to a power-class rail and ``R_dn`` to
      ground, which is F1's shape: ``R_th = R_up‖R_dn``, ``V_bias = V_rail ×
      R_dn/(R_up+R_dn)``.

    Anything else returns ``None``, and the caller then says the topology is not
    one this build can price instead of guessing what the engineer meant.
    """
    far = leg.far
    if leg.far_power:
        volts, source, why = domain_of(guesses, far)
        return BiasSource(
            designators=(leg.designator,),
            shape=(
                f"{leg.designator}（{_ohms(leg.ohms)}）直接上拉到 power-class 轨 "
                f"{far!r}（依据：{leg.far_power}）—— 轨内阻记 0"
            ),
            r_source=0.0,
            v_open=volts,
            volts_because=(source if volts is not None else why),
            is_divider=False,
        )
    up: ResistorLeg | None = None
    down: ResistorLeg | None = None
    for other in _resistor_legs(model, guesses, rule, far, exclude=leg.designator):
        if other.far_power and up is None:
            up = other
        elif other.far_is_ground and down is None:
            down = other
    if up is None or down is None:
        return None
    r_source = 1.0 / (1.0 / up.ohms + 1.0 / down.ohms)
    volts, source, why = domain_of(guesses, up.far)
    v_open = volts * down.ohms / (up.ohms + down.ohms) if volts is not None else None
    return BiasSource(
        designators=(leg.designator, up.designator, down.designator),
        shape=(
            f"分压 {up.designator}（{_ohms(up.ohms)}）@{up.far!r} / "
            f"{down.designator}（{_ohms(down.ohms)}）@GND，中点 {far!r} 经串阻 "
            f"{leg.designator}（{_ohms(leg.ohms)}）送到 {leg.net!r}"
        ),
        r_source=r_source,
        v_open=v_open,
        volts_because=(source if volts is not None else why),
        is_divider=True,
    )


def _is_bias_subject(signal: object) -> bool:
    """Is this contract entry the subject of the closure question?

    Two spellings, the same chain: a signal whose own ``kind`` says it is a
    current sense **and** whose polarity is bidirectional (F1's `U+`), or an entry
    that names a bias token in ``requires`` — a contract may state the closure
    requirement without spelling the polarity, and that statement is a subject too.
    """
    requires = [str(token) for token in (getattr(signal, "requires", None) or [])]
    if any(token in BIAS_TOKENS for token in requires):
        return True
    return (
        str(getattr(signal, "kind", "")) == KIND_CURRENT_SENSE
        and str(getattr(signal, "polarity", "")) == POLARITY_BIDIRECTIONAL
    )


def _is_output_name(name: str | None) -> bool:
    """Is this pin name an amplifier's output? ``OUTA``/``OUT1``/``VOUT`` yes."""
    return any(
        segment.lower().startswith(OUTPUT_NAME_PREFIXES)
        for segment in _NAME_SEPARATORS.split(str(name or ""))
        if segment
    )


class ArchSenseBiasClosure(FactsRule):
    """ARCH-4: a bidirectional current-sense chain is biased into its ADC's window.

    F1 (ctrl FOC, `review-findings.md`) is both the case and the arithmetic. Two
    phase shunts of 0.1Ω are read straight into a single-supply ADC, so each node
    has to sit at VCC/2 to carry a negative half. The engineer's bias is R10/R16
    (1k each = a 500Ω source) through R17/R18 (10k) onto the 0.1Ω node:

        1.65V × 0.1Ω / (500Ω + 10000Ω + 0.1Ω) ≈ 15.7µV

    five orders below the 1.65V it wanted. The physics is the whole rule —
    :data:`BIAS_PHYSICS` — and a rule that can do the arithmetic can refuse to
    call that a bias.

    **The ``1/10`` is this rule's own declared criterion, not a standard.** No
    datasheet and no app note says "a bias source must be at most a tenth of the
    sense resistance"; it is the line this build draws between "the divider is the
    node's bias" and "the divider is a stray load on a node something else holds",
    it is published as :data:`BIAS_CLOSURE_RATIO`, and every row prints it beside
    the numbers it was applied to — so a reader can disagree with the *number*
    rather than with a threshold hidden in an expression. **The topologies it
    prices**, both instances of one formula: a **divider mid-net** (``R_up`` to a
    power-class rail, ``R_dn`` to ground, and the mid-point reaching the sense net
    through a series resistor ``Rs``, so ``R_th = R_up‖R_dn + Rs`` while ``V_bias``
    is the divider's own ratio applied to its rail), and a **series resistor
    straight onto a priced rail** (the rail is the source and its impedance is
    zero, so ``R_th = Rs``). In both, ``V_err = V_bias × R_sense/(R_th + R_sense)``
    is what the node actually gets. A resistor whose far net is neither a priced
    rail nor such a divider is a topology this build cannot price: UNKNOWN, naming
    what to draw, never a guess.

    **Five rows, decided in this order** (each names its subject, its reason and
    its numbers):

    * **waived** — the contract's own answer (``closure: "waived"``, the 094 A3b
      key): the chain is *knowingly* left unclosed (R4: "0.1Ω 直采，不加放大器").
      A `user_stated` waiver is **INFO** and quotes the rationale from
      ``decisions[]``; any weaker tier is a **WARN**, because a draft cannot
      exempt itself from a requirement it wrote (052 §4) — and the row says which
      tier spoke. The waiver is read *before* the drawing, and it is the reason
      this key exists: F1's outcome was a decision, not a defect;
    * **no bias network** — nothing on the net reaches a divider mid-net or a
      power rail (the shape the shipped export has): graded by
      :func:`intent_grade` over the signal's own provenance, so the engineer's own
      statement contradicted by the drawing is an **ERROR**;
    * **weak bias** — a bias exists and the arithmetic says it does nothing
      (``R_th ≥ R_sense``), again graded by :func:`intent_grade` (F1's live shape:
      10500Ω against 0.1Ω);
    * **marginal** — ``R_sense/10 < R_th < R_sense``: the ratio is inside the
      closure criterion's decade, so it is a **WARN** carrying both numbers rather
      than a verdict;
    * **closed** — ``R_th ≤ R_sense/10``, or the net is driven by an op-amp's
      output (an amplifier's output impedance is ohms, which makes the Thévenin
      arithmetic meaningless — so it is checked *first* and stated as its own
      shape): **INFO measurement** naming R_th, the sense resistance and the
      voltage the node gets. 092's discipline: "查过且没事" and "根本没看" must not
      read the same.

    **Two things it refuses to guess** (UNKNOWN, each naming the fact it wants and
    where to write it): a net that carries foreign resistors but whose topology is
    neither of the two priced shapes, and a net with no grounded resistor at all
    (without a sense resistance there is no ratio to compare). And one it cannot
    read rather than refuses: an op-amp on the net whose output pin is named by
    neither its symbol nor its shelf entry.

    The subject is the *contract's* statement, so a board nobody wrote a contract
    for files nothing here (A1/A2's zero-movement reading), and the net this row
    concludes from is subject to issue #19 — on a name the per-page merge welded
    blind, every row is UNKNOWN quoting the merge's own sentence.
    """

    id = "arch-sense-bias-closure"
    title = "A bidirectional current-sense chain is biased into its ADC's window"
    level = LEVEL
    source = (
        "the contract's requirements.signals[] (kind=current-sense, polarity="
        "bidirectional, or requires=[bias-reference]; closure=waived for a "
        "knowing waiver) against the net's own resistors and the rails the drawing "
        "prices; the arithmetic is F1's (ROBOT ctrl FOC review-findings.md: "
        "1.65V × 0.1Ω/(500Ω + 10kΩ + 0.1Ω) ≈ 15.7µV against the 1.65V wanted), and "
        "the 1/10 closure criterion is this rule's own declaration "
        "(BIAS_CLOSURE_RATIO) rather than a standard"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity, target)
            for outcome, severity, target in self._rows(model)
            if severity is not None
        ]

    def _rows(
        self, model: DesignModel
    ) -> list[tuple[Outcome, str | None, FindingTarget | None]]:
        if self.intent is None:
            # No contract, no chain declared bidirectional, no question (A1/A2's
            # zero-movement reading, kept: a reading that names no intent is
            # byte-for-byte what it was).
            return []
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None, FindingTarget | None]] = []
        for signal in self.intent.document.signals:
            if not _is_bias_subject(signal):
                continue
            rows.append(self._row(model, guesses, signal))
        return rows

    # ------------------------------------------------------------------ rows

    def _row(
        self, model: DesignModel, guesses: dict, signal: object
    ) -> tuple[Outcome, str | None, FindingTarget | None]:
        net = str(getattr(signal, "net", "") or "")
        target = FindingTarget(net_refs=[net])
        statement = write_path(SECTION_SIGNALS, net, "kind")
        where = (
            f"合同 {statement} = {getattr(signal, 'kind', '')!r}、polarity = "
            f"{getattr(signal, 'polarity', '')!r}、provenance = "
            f"{getattr(signal, 'provenance', '')!r}"
        )
        evidence = [f"链 {net!r} @ {getattr(signal, 'kind', '')}/"
                    f"{getattr(signal, 'polarity', '')}", where]
        swing = str(getattr(signal, "adc_swing", "") or "")
        if swing:
            evidence.append(
                f"合同 {write_path(SECTION_SIGNALS, net, 'adcSwing')} = {swing!r}（"
                "这条链落进的 ADC 窗口）"
            )
        # Issue #19: every row below concludes from what else sits on this net —
        # including the waiver's citation, which names the designators it found
        # there — so on a welded name the reading refuses before it judges.
        welded = unproven_nets(model, (net,))
        if welded:
            return (
                unproven_outcome(
                    self.id,
                    net,
                    welded,
                    what=(
                        f"whether the bias on chain {net!r} closes, and which parts "
                        "on it form that bias"
                    ),
                    evidence=evidence,
                ),
                MEASUREMENT_GRADE,
                target,
            )
        if getattr(signal, "waived", False):
            return self._waiver_row(model, intentsignal=signal, net=net,
                                    evidence=evidence, target=target)
        # The driven shape is checked **before** any arithmetic: an amplifier's
        # output impedance is ohms, so a Thévenin ratio computed across it would be
        # arithmetic about a node that is not held by resistors at all.
        driving = _opamp_output(model, self, net)
        if driving is not None:
            reference, pin_name, because = driving
            if because:
                return (
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=net,
                        message=(
                            f"{net}：网里有运放 {reference} 的输出脚"
                            + (f"（{pin_name}）" if pin_name else "")
                            + "直连 —— 偏置由运放输出馈入，输出阻抗在 Ω 级，**闭合成立**"
                            "（运放闭合形态，免检电阻分压算术：运放按测量行在这里，"
                            "不是因为查不出问题而沉默）。" + where
                        ),
                        evidence=[
                            *evidence,
                            f"{reference} 的输出脚 → {net}（判据：{because}）",
                        ],
                    ),
                    MEASUREMENT_GRADE,
                    target,
                )
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=net,
                    message=(
                        f"{net}：网上有运放 {reference}，但**哪一脚是输出读不出来**"
                        "（符号引脚名里没有 OUT 段，货架条目也没记输出脚）—— 运放闭合"
                        "成立的判据是「输出直连」，本规则不拿输入脚当输出。修法：把输出"
                        f"脚写进 blocklib/parts.corrections.json 的 {reference} 条目的 "
                        "fields.facts.output_pins（引脚号列表），或让符号的引脚名带 OUT。"
                        + where
                    ),
                    evidence=evidence,
                    missing_fact=(
                        f"{reference} 的输出脚：符号引脚名与货架 facts 都没说哪一脚是"
                        "输出 —— 写进 blocklib/parts.corrections.json 的该条目 "
                        "fields.facts.output_pins，或让符号引脚名带 OUT"
                    ),
                ),
                MEASUREMENT_GRADE,
                target,
            )
        legs = _resistor_legs(model, guesses, self, net)
        shunts = [leg for leg in legs if leg.far_is_ground]
        foreign = [leg for leg in legs if not leg.far_is_ground]
        evidence.append(
            f"{net} 成员：{_quoted(_read_members(model, net))}"
            + (
                "；网上的电阻：" + "、".join(
                    f"{leg.designator}（{_ohms(leg.ohms)} → {leg.far}）" for leg in legs
                ) if legs else "；网上没有可读的电阻"
            )
        )
        if not shunts:
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=net,
                    message=(
                        f"{net}：`{net}` 上没有到地的电阻，所以**采样电阻 R_sense 读不出来**"
                        " —— 没有它就没有 R_th 与 R_sense 的比值，本规则不下判断，也不"
                        "替它假定一个阻值。修法：把分流电阻画在 "
                        f"{net!r} 到地之间（F1 实案是 R4 = 0.1Ω），或在合同里说明这条链"
                        "的采样方式"
                    ),
                    evidence=evidence,
                    missing_fact=(
                        f"{net} 的采样电阻：网上没有到地的电阻，判不了偏置源内阻与采样"
                        "电阻的比值 —— 把分流电阻画在 "
                        f"{net!r} 到地之间，或在合同 "
                        f"requirements.signals[net={net}].reference/kind 里说明采样形态"
                    ),
                ),
                MEASUREMENT_GRADE,
                target,
            )
        shunt, declared_where, refusal = _sense_shunt(self.intent, shunts)
        if shunt is None:
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=net,
                    message=(
                        f"{net}：采样电阻 R_sense 判不出来 —— {refusal}。本规则不替它裁"
                        "哪一颗：采样电阻是这条链的电气定义（网上到地电阻里阻值最小的"
                        "那个），而声明是工程师的说法，两者矛盾时改哪一边是他的决定。"
                        "修法：把合同 blocks[].parts 改成真正的采样件，或把采样件画成 "
                        f"{net!r} 上到地电阻里阻值最小的那个。" + where
                    ),
                    evidence=evidence,
                    missing_fact=(
                        f"{net} 的采样电阻：{refusal} —— 要么把合同 blocks[].parts 改成"
                        "实际的采样件，要么把采样件画成网上到地电阻里阻值最小的那个"
                    ),
                ),
                MEASUREMENT_GRADE,
                target,
            )
        if not foreign:
            return self._unbiased_row(model, signal, net, shunt, evidence, target)
        source: BiasSource | None = None
        series: ResistorLeg | None = None
        for leg in foreign:
            source = _bias_source(model, guesses, self, leg)
            if source is not None:
                series = leg
                break
        if source is None or series is None:
            stray = "、".join(
                f"{leg.designator}（{_ohms(leg.ohms)} → {leg.far!r}）" for leg in foreign
            )
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=net,
                    message=(
                        f"{net}：网上确实有外来电阻（{stray}），但它们的远端网既不是"
                        "**power-class 轨**，也不是本规则能定价的**分压中点**（那里找不到"
                        "「一只到轨 + 一只到地」的配对）—— 拓扑对不上，本规则不猜它是"
                        "什么。修法：把偏置画成规则认得的形态（分压中点经串阻送到 "
                        f"{net!r}，或运放输出直接馈入），或在合同 "
                        f"requirements.signals[net={net}].closure 写 \"waived\" 明说这条"
                        "链放弃闭合"
                    ),
                    evidence=evidence,
                    missing_fact=(
                        f"{net} 的偏置拓扑：网上有外来电阻（{stray}），但它们的远端网不是"
                        "可定价的 power-class 轨、也不是有 R_up/R_dn 的分压中点 —— 要么"
                        f"把图画成规则认得的形态，要么在合同 "
                        f"requirements.signals[net={net}].closure 写 'waived'"
                    ),
                ),
                MEASUREMENT_GRADE,
                target,
            )
        r_sense = shunt.ohms
        r_th = source.r_source + series.ohms
        v_err = (
            source.v_open * r_sense / (r_th + r_sense)
            if source.v_open is not None
            else None
        )
        evidence.extend([
            f"采样电阻 {shunt.designator} = {_ohms(r_sense)} @ {net} → {shunt.far}"
            + (f"（{declared_where} 点名）" if declared_where else ""),
            f"偏置源：{source.shape}",
            f"R_th = {source.r_source:g} + {series.ohms:g} = {r_th:g}Ω；V_bias = "
            + (_volts(source.v_open) if source.v_open is not None else "读不出")
            + f"（{source.volts_because}）",
            f"R_sense/10 = {r_sense / 10:g}Ω（判据 BIAS_CLOSURE_RATIO = "
            f"{BIAS_CLOSURE_RATIO:g}，本规则自声明）",
        ])
        r_th_terms = (
            f"(R_up‖R_dn) + Rs = {source.r_source:g}Ω + {series.ohms:g}Ω"
            if source.is_divider
            else f"Rs + 0Ω（串阻直接接轨，轨内阻记 0）= {series.ohms:g}Ω + 0Ω"
        )
        arithmetic = (
            f"R_th = {r_th_terms} = {r_th:g}Ω；V_err = V_bias × "
            "R_sense/(R_th + R_sense) = "
            + (
                f"{_volts(source.v_open)} × {r_sense:g}Ω/({r_th:g}Ω + {r_sense:g}Ω)"
                f" ≈ {_volts(v_err)}"
                + _orders(source.v_open, v_err)
                if source.v_open is not None
                else "（V_bias 读不出：串阻背后那条轨谁都没定价，抬升电压这一半算不了，"
                     f"但 R_th = {r_th:g}Ω 已经越线）"
            )
        )
        if r_th >= r_sense:
            severity, why = intent_grade(signal)
            return (
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=net,
                    message=(
                        f"{net}：合同声明这条链是双向电流采样，图纸上「补的偏置」**电气上"
                        f"不成立** —— 偏置源内阻 R_th = {r_th:g}Ω **大于等于**采样电阻 "
                        f"R_sense = {r_sense:g}Ω，形同虚设。算术（F1 原式）：{arithmetic}"
                        + (
                            f"，而想要的是 {_volts(source.v_open)}"
                            if source.v_open is not None else ""
                        )
                        + "。" + BIAS_PHYSICS + "修法：改成运放缓冲/差分放大器把偏置电压送"
                        "到求和点（或把这条链在合同 "
                        f"requirements.signals[net={net}].closure 标 \"waived\" 并写明"
                        "接受什么后果）。" + where + "。" + why
                    ),
                    evidence=evidence,
                ),
                severity,
                target,
            )
        if r_th > r_sense * BIAS_CLOSURE_RATIO:
            return (
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=net,
                    message=(
                        f"{net}：偏置**比值存疑** —— R_th = {r_th:g}Ω 落在 "
                        f"R_sense/10（{r_sense / 10:g}Ω）与 R_sense（{r_sense:g}Ω）"
                        f"之间，低于本规则自声明的闭合判据的十分之一要求（判据 "
                        f"BIAS_CLOSURE_RATIO = {BIAS_CLOSURE_RATIO:g}，写在 "
                        "rules/archclosure.py 的模块 docstring 里）。算术（F1 原式）："
                        f"{arithmetic}。这不是「差 5 个数量级」那种硬伤，而是比值只差一个"
                        "数量级以内：偏置能抬起来一部分，但节点电压会跟着偏置源与采样"
                        "电阻的分压走，请确认这个误差在量程内可以接受（要闭合就换运放"
                        "缓冲）。" + where
                    ),
                    evidence=evidence,
                ),
                MARGIN_GRADE,
                target,
            )
        return (
            Outcome(
                rule_id=self.id,
                state="OK",
                subject=net,
                message=(
                    f"{net}：偏置**闭合成立** —— R_th = {r_th:g}Ω ≤ R_sense/10 = "
                    f"{r_sense / 10:g}Ω（判据 BIAS_CLOSURE_RATIO = "
                    f"{BIAS_CLOSURE_RATIO:g}，本规则自声明）。算术（F1 原式）："
                    f"{arithmetic}。测量行：查过且闭合，不是一个沉默。" + where
                ),
                evidence=evidence,
            ),
            MEASUREMENT_GRADE,
            target,
        )

    # -------------------------------------------------------------- the two
    #                                   rows whose words are not arithmetic

    def _waiver_row(
        self, model: DesignModel, *, intentsignal: object, net: str,
        evidence: list[str], target: FindingTarget | None,
    ) -> tuple[Outcome, str | None, FindingTarget | None]:
        """The contract waived this chain's closure — INFO, or WARN if a draft said so."""
        provenance = str(getattr(intentsignal, "provenance", "") or "")
        slot = write_path(SECTION_SIGNALS, net, "closure")
        decision, draft = self._waiver_decision(model, net)
        citation = ""
        if decision is not None:
            citation = (
                f"；合同 decisions[subject={decision.subject!r}] = "
                f"「{decision.decision}」"
                + (f"（rationale：{decision.rationale}）" if decision.rationale else "")
                + f"，provenance = {decision.provenance}"
            )
        else:
            citation = (
                "；合同 decisions[] 里没有为这条链背书的条目（豁免的理由没人写下来 —— "
                "给该链上的器件补一条 decisions[subject=…]，把接受什么后果写进 rationale）"
            )
        draft_note = ""
        if draft is not None:
            draft_note = (
                f"；另有一条 decisions[subject={draft.subject!r}]"
                f"（{draft.provenance}）提到这条链，但不是 user_stated，不按它背书"
            )
        statement = (
            f"合同 {slot} = {getattr(intentsignal, 'closure', '')!r}（provenance = "
            f"{provenance}）："
            + (
                "这条链的闭合是**工程师明示放弃的**"
                if provenance == PROVENANCE_USER_STATED
                else "这条链的闭合被声明放弃，但写这条声明的那一档不是工程师本人"
            )
            + citation
            + f"。读数依据：网成员 {_quoted_members(model, net)}；"
            f"合同 {write_path(SECTION_SIGNALS, net, 'kind')} = "
            f"{getattr(intentsignal, 'kind', '')!r}、polarity = "
            f"{getattr(intentsignal, 'polarity', '')!r}" + draft_note
        )
        if provenance == PROVENANCE_USER_STATED:
            return (
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=net,
                    message=(
                        f"{net}：**豁免（waived）成立** —— {statement}。"
                        "按合同不查这条链的偏置闭合（INFO 测量行：这是工程师签过字的"
                        "决定，不是漏掉的检查）。注意豁免的是**闭合检查**：双向信号落进"
                        "单电源 ADC 仍然只能测正半轴，量程损失是这项决策的代价，不是"
                        "工具不再关心的事"
                    ),
                    evidence=[
                        *evidence,
                        f"{slot} = {getattr(intentsignal, 'closure', '')!r}（{provenance}）",
                        citation.lstrip("；"),
                    ],
                ),
                WAIVER_GRADE,
                target,
            )
        return (
            Outcome(
                rule_id=self.id,
                state="VIOLATION",
                subject=net,
                message=(
                    f"{net}：合同写了**豁免**，但写它的这一条不是工程师本人声明的"
                    f"（provenance = {provenance}）—— 草稿不能自己豁免自己（052 §4："
                    "猜出来的需求只能当提示）。" + statement + "。修法：请工程师确认这条"
                    "豁免（把 provenance 改成 user_stated），或者照图纸把偏置补上"
                ),
                evidence=[
                    *evidence,
                    f"{slot} = {getattr(intentsignal, 'closure', '')!r}（{provenance}）",
                    citation.lstrip("；"),
                ],
            ),
            DRAFT_WAIVER_GRADE,
            target,
        )

    def _waiver_decision(
        self, model: DesignModel, net: str
    ) -> tuple[IntentDecision | None, IntentDecision | None]:
        """``(the user_stated decision backing the waiver, a draft one)``.

        Identity is exact, as everywhere in this channel (090: one entry is one
        object): the signal's own net first, then the designators on it — F1's R4
        decision is written against the *part*, which is where a person writes it.
        Nothing else is matched, and the prose is not read: the decision is quoted,
        not interpreted.

        The designators are read as a set in designator order — the same reading
        ``_user_stated_pullup`` makes in this file — so *which* decision is cited
        for a chain with several is a property of the board, not of the order the
        netlist listed its pins in (issue #57 finding 6).
        """
        if self.intent is None:
            return None, None
        subjects = [net] + sorted({des for des, _pin in _members(model, net)})
        draft: IntentDecision | None = None
        for subject in subjects:
            decision = self.intent.decision(subject)
            if decision is None:
                continue
            if decision.provenance == PROVENANCE_USER_STATED:
                return decision, draft
            draft = draft or decision
        return None, draft

    def _unbiased_row(
        self, model: DesignModel, signal: object, net: str, shunt: ResistorLeg,
        evidence: list[str], target: FindingTarget | None,
    ) -> tuple[Outcome, str | None, FindingTarget | None]:
        """No bias network at all — the shipped export's shape (F1 before the fix)."""
        severity, why = intent_grade(signal)
        swing = str(getattr(signal, "adc_swing", "") or "")
        return (
            Outcome(
                rule_id=self.id,
                state="VIOLATION",
                subject=net,
                message=(
                    f"{net}：合同声明这条链是双向电流采样"
                    + (f"（adcSwing = {swing!r}）" if swing else "")
                    + "，但图纸上**没有任何偏置网络** —— 网成员 "
                    f"{_quoted(_read_members(model, net))} 里，到地的电阻只有 "
                    f"{shunt.designator}（{_ohms(shunt.ohms)}，采样电阻），没有电阻通往"
                    "「分压样」中间网（一侧到 power-class 轨、一侧到地的中点），也没有"
                    "电阻直接上拉到 power-class 轨。双向信号落进单电源 ADC 必须有偏置把"
                    "它抬到窗口中央，所以这条链在图纸上**不闭合**。" + BIAS_PHYSICS
                    + "修法：加 R_up/R_dn 分压（F1 实案给的 1.65V 中点）经运放缓冲送"
                    f"到 {net!r}，或直接把放大器输出馈入；若确实接受只测正半轴，请在合同 "
                    f"requirements.signals[net={net}].closure 写 \"waived\" 并写明理由。"
                    + why
                ),
                evidence=evidence,
            ),
            severity,
            target,
        )


def _opamp_output(
    model: DesignModel, rule: FactsRule, net: str
) -> tuple[str, str, str] | None:
    """``(designator, pin name, why it is the output)`` for an amplifier on ``net``.

    ``None`` when no amplifier is on the net, and an **empty** ``why`` when one is
    but its output pin cannot be read (the caller reports UNKNOWN then, naming the
    fact to write — "the amplifier drives this net" and "the amplifier's *input*
    sits on this net" are opposite conclusions).

    An op-amp is recognised from the **shelf** (``category: ic.opamp``) — the same
    source the rest of this file reads parts from, and deliberately not a
    designator-prefix guess. Which of its pins is the output is then read from two
    places, in this order: the shelf entry's own ``facts.output_pins`` (explicit
    data wins), then the **pin name** the netlist carries
    (:func:`_is_output_name`, the reading ``NrstClosure`` makes for a reset pin).

    The walk is :func:`_read_members`, so "the amplifier on this net" is the same
    part whichever order the netlist listed it in (issue #57 finding 6).
    """
    for designator, pin in _read_members(model, net):
        comp = model.components.get(designator)
        entry = rule.entry_for(comp) if comp is not None else None
        if entry is None or entry.category != "ic.opamp":
            continue
        name = _pin_name(comp, pin)
        declared = (entry.facts or {}).get("output_pins")
        if isinstance(declared, (list, tuple)) and str(pin) in {
            str(item) for item in declared
        }:
            return designator, name, (
                f"货架条目 {entry.mpn or entry.lcsc or designator} 的 "
                f"facts.output_pins 点名了引脚 {pin}"
            )
        if _is_output_name(name):
            return designator, name, f"引脚名 {name!r}"
        return designator, name, ""
    return None
