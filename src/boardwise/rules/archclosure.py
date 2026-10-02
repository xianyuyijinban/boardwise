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

Every rule that concludes from "what else is on this net" is listed in
:data:`boardwise.rules.unproven.NET_MEMBERSHIP_RULES` — on a net the per-page
merge welded blind, the row is UNKNOWN quoting the merge's own sentence, exactly
as issue #19 requires (see :mod:`boardwise.rules.unproven`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.architecture import controller_evidence
from ..core.circuitspec import (
    PROVENANCE_AI,
    PROVENANCE_USER_STATED,
    PROVENANCE_VERIFIED,
)
from ..core.designintent import (
    SECTION_RAILS,
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


def _quoted_members(model: DesignModel, net: str | None) -> str:
    members = _members(model, net)
    return ", ".join(f"{des}.{pin}" for des, pin in members) or "（网里没有成员）"


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
