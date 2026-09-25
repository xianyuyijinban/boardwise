"""Facts-driven rules (task 011c): CONN-2/3, PWR-1/2, PATH-1.

Unlike the L1 heuristics in :mod:`boardwise.rules.connectivity`, these rules
read the curated part library (:mod:`boardwise.core.parts`) and the voltage-
domain inference (:mod:`boardwise.core.power_domains`). Every one implements
the four-state protocol: a rule that cannot decide says UNKNOWN and names the
missing fact — "no facts for U3" drives the library's intake priority, which
is the whole point of the outcome vocabulary.

Common subject rule: these rules look at **U-prefixed** components (ICs by
designation). A component with a shelf entry whose category is not ``ic.*``
gets NOT_APPLICABLE; a component with no entry gets UNKNOWN, naming what the
library lacks. Passive parts never reach the rules at all, so "no facts for
R24" cannot flood the report with non-questions.

Each rule documents where it decides from — ``source`` is a datasheet citation
or ``house rule``; an empty source is a debt (task 011 sec.3), and none of
these carry one.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..core.model import Component, DesignModel, Net
from ..core.parts import PartEntry, PartLibrary, find_facts
from ..core.power_domains import (
    domain_of,
    infer_net_domains,
    ldo_output_pin,
)
from .base import Finding, FindingTarget, Outcome, OutcomeRule
from .connectivity import parse_resistance_ohms

LEVEL = "L2-facts"
#: An IC by designation is ``U`` followed by a digit — ``U1``/``U3``/``U5``,
#: never ``USB1`` (a connector whose prefix merely *starts* with U).
IC_PATTERN = re.compile(r"^U\d")
#: Where the lazy library loads from when a test does not inject one. The CLI
#: runs from the repository root, so the relative default matches it.
DEFAULT_LIBRARY_PATH = "blocklib/parts.json"

# Subject category classification. A shelf entry can be an IC, explicitly
# something else, or carry no category at all (measured: the golden board's
# U3 resolves to C2907329, an old v1-era entry with `category: null`) — and
# those three answers must not collapse: "explicitly not an IC" is
# NOT_APPLICABLE, "cannot tell" is UNKNOWN naming the missing facts.
_IC = "ic"
_NON_IC = "non-ic"
_CATEGORY_UNKNOWN = "unknown"


def _category_state(entry: PartEntry) -> str:
    # The 039 gate, at the one choke point every facts rule passes through: an
    # entry whose facts are unverified is **unclassified as far as the rules are
    # concerned**, whatever `category` says. There is no partial trust — an
    # author who typed a category and facts but has not been reviewed is the
    # exact case the gate exists for — and putting the check here rather than in
    # each rule is what keeps a rule from forgetting it. A `true` entry (every
    # entry written before the field existed) is untouched.
    if not entry.facts_verified:
        return _CATEGORY_UNKNOWN
    category = entry.category or ""
    if category.startswith("ic"):
        return _IC
    if category:
        return _NON_IC
    return _CATEGORY_UNKNOWN


#: What a closed gate adds to a rule's message (task 039 §WI-4). "No facts" and
#: "facts nobody has verified" are the same thing to a consumer — both leave
#: `entry.facts` None — but they are different work orders: the first is a
#: curation task, the second a **review**. Only the entry can tell them apart,
#: so the rule asks it rather than guessing from an empty dict.
_GATE_NOTE = (
    " — candidate entry: facts_verified is false, so nothing in it drives a "
    "rule yet (the flip is the review)"
)


def _facts_absent_reason(entry: PartEntry) -> str:
    """Why the shelf cannot judge this part, in the entry's own terms.

    Three answers, never two: "nothing recorded", "a claim nobody vouched for",
    and "no facts and not even a verified entry" are three different next acts,
    and collapsing them would make the report's honest silence a lie.
    """
    if entry.facts_verified:
        return "its shelf entry has no facts"
    if entry.candidate_facts:
        return "its shelf entry claims facts nobody has verified" + _GATE_NOTE
    return "its shelf entry has no facts and is itself unverified" + _GATE_NOTE


def _category_absent_reason(entry: PartEntry) -> str:
    """The same three answers about the classification rather than the facts."""
    if entry.facts_verified:
        return "its shelf entry has no category"
    return "its shelf entry is unverified, so it is unclassified too" + _GATE_NOTE


def _gate_review_note(entry: PartEntry) -> str:
    """What a candidate's intake item *is*: a review, not a recording.

    Empty for every verified entry, so the intake line a curated part produces
    is byte-identical to what it was before the gate existed.
    """
    if entry.facts_verified:
        return ""
    return (
        " — or read the recorded facts, and if they are right, set "
        "facts_verified to true (that flip IS the review)"
    )


class FactsRule(OutcomeRule):
    """Base for rules that read the curated shelf.

    The library is injectable (tests pass a tiny synthetic shelf); without
    injection it loads lazily from :data:`DEFAULT_LIBRARY_PATH`, because
    module-level BUILTIN_RULES instances outlive any single run.
    """

    library_path: str = DEFAULT_LIBRARY_PATH

    def __init__(self, library: PartLibrary | None = None) -> None:
        self._library = library

    @property
    def library(self) -> PartLibrary:
        if self._library is None:
            from ..core.parts import load_parts

            self._library = load_parts(self.library_path)
        return self._library

    def entry_for(self, comp: Component) -> PartEntry | None:
        """Exact-match identity only (find_facts' contract — no fuzzy)."""
        entry = None
        if comp.mpn:
            entry = find_facts(self.library, mpn=comp.mpn)
        if entry is None and comp.lcsc_part:
            entry = find_facts(self.library, lcsc=comp.lcsc_part)
        return entry

    def ics(self, model: DesignModel) -> list[Component]:
        return [
            comp
            for comp in model.components.values()
            if IC_PATTERN.match(comp.designator)
        ]

    def findings_from(self, rows: list[tuple]) -> list[Finding]:
        """VIOLATION rows become findings; the rest is silence with reasons.

        A row is ``(outcome, severity)``, optionally followed by a third
        element carrying the row's :class:`FindingTarget` (task 016). Only
        ``param-value-mpn-match`` produces the three-element form; every other
        caller passes pairs and is unaffected.
        """
        findings: list[Finding] = []
        for row in rows:
            outcome, severity = row[0], row[1]
            target = row[2] if len(row) > 2 else None
            if outcome.state != "VIOLATION":
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=severity or "ERROR",
                    level=self.level,
                    message=outcome.message,
                    evidence=list(outcome.evidence),
                    target=target,
                )
            )
        return findings


def _pin_net(comp: Component, number: str) -> str | None:
    for pin in comp.pins:
        if pin.number == number:
            return pin.net
    return None


def _nc_target(designator: str, pin: str, net: str) -> FindingTarget:
    """The structured claim of an NC violation, as a **disconnect** (035 §1).

    ``expected_before`` is the net the pin sits on today and ``suggested_after``
    is the **empty string** — "no net" is the repair, and writing that down as an
    empty string (rather than, say, the word "NC") keeps the field meaning the
    same thing it does everywhere else: the net the pin should end up on.
    """
    return FindingTarget(
        component_ref=designator,
        pin_refs=[pin],
        net_refs=[net],
        expected_before=net,
        suggested_after="",
    )


def _must_connect_target(
    designator: str, pin: str, net: str | None, target: str
) -> FindingTarget:
    """The structured claim of a must_connect violation, as a **connect** or a
    **reconnect** (035 §1).

    ``suggested_after`` is the target net the shelf names; ``expected_before`` is
    where the pin is now — the empty string when it reaches no net at all, which
    is the connect form, and the wrong net's name when it reaches one, which is
    the reconnect form. ``net_refs`` lists both ends (current first, target last,
    and only the target when the pin is dangling) because a plan has to be able
    to name where it is going *and* what it is leaving.
    """
    current = net or ""
    return FindingTarget(
        component_ref=designator,
        pin_refs=[pin],
        net_refs=([current, target] if current else [target]),
        expected_before=current,
        suggested_after=target,
    )


def _identity(comp: Component) -> str:
    bits = [f"mpn {comp.mpn!r}" if comp.mpn else None,
            f"lcsc {comp.lcsc_part!r}" if comp.lcsc_part else None]
    return ", ".join(b for b in bits if b) or "no mpn, no lcsc number"


#: The four answers a pin-level obligation can get, and they are the rule's own
#: vocabulary (`Outcome.state`) — not a second one invented for repairs.
PIN_OK = "OK"
PIN_VIOLATION = "VIOLATION"
PIN_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PinRuling:
    """What the shelf's obligation for **one pin** comes to, and why (035).

    The per-pin form of this rule's judgement, extracted so the repair slice can
    ask "is this pin already as it should be?" through the *same* function that
    produced the finding (029's rule: the probe is the rule's own judgement, not a
    second, similar-looking test). ``target`` is filled only for a VIOLATION — an
    OK row has nothing to repair and an UNKNOWN row's honest answer is the fact it
    names.
    """

    state: str
    message: str
    evidence: list[str] = field(default_factory=list)
    target: FindingTarget | None = None
    missing_fact: str = ""


#: What the editor calls a net nobody named. Two spellings, measured 2026-09-24:
#:
#: * ``NET1``, ``NET2``, … — how an island with nothing to name it gets stored, and
#:   how the *export* spells the net of a pin that reaches nothing;
#: * ``$57N2`` — the editor's **internal id**, which is what its own netlist
#:   (`sch.netlist`) reports for a wire **nobody named**. Measured on the same
#:   board: the very same unnamed wire read `NET3` through the export and `$57N2`
#:   through `sch.netlist`, which is what made a plan built on the export answer
#:   `stale_before` for a board that had not moved.
#:
#: Both carry **no intent** — that is the whole test — so the judgements that ask
#: "did a person name this?" must not be fooled by which spelling they are handed.
_AUTO_NET_RE = re.compile(r"^(NET\d+|\$\S+)$", re.IGNORECASE)


def is_auto_net(name: str | None) -> bool:
    """Is this an editor-generated net name? (the ones that mean nothing)"""
    return bool(name) and bool(_AUTO_NET_RE.match(str(name).strip()))


def nc_violation(model: DesignModel, comp: Component, pin: str) -> tuple[bool, str]:
    """Is a declared-NC pin connected, and to what (035 round 2, ruling A)?

    Two ways to be connected, and they are the two ways a *named* intent can show
    up on a board:

    * the pin **shares its net with ≥2 pins** — something else is wired here;
    * the pin sits **alone on a net somebody named** (``GND``, ``NCNET``, …).
      Naming is intent: a hand-drawn net called ``GND`` that ends on an NC pin is
      a mistake to fix, not an island to ignore.

    A single-member **auto** net (``NET7``) is *not* a connection: it is the shape
    the editor leaves behind for a pin that reaches nothing — measured 035 on
    3.2.186, where deleting the wire off an NC pin left it alone on ``NET6``. Both
    the rule and the repair read this function, so "the repair worked" and "the
    rule is satisfied" cannot disagree (029's rule, round-2 ruling A).
    """
    net = _pin_net(comp, pin)
    company = pin_company(model, comp, pin)
    if company:
        mates = ", ".join(f"{name}.{number}" for name, number in sorted(company))
        return True, f"sits on net {net!r} with {mates}"
    if net and not is_auto_net(net):
        return True, f"sits alone on the named net {net!r}"
    return False, f"touches no net" + (f" (alone on {net!r})" if net else "")


def pin_dangles(model: DesignModel, comp: Component, pin: str) -> tuple[bool, str]:
    """Does this pin reach **nothing**? The same reading as `nc_violation`, inverted.

    Added 035 round 3, because the two directions need one vocabulary. The export
    gives a pin that reaches nothing a single-member auto net (measured
    2026-09-24: a dangling U3 pin5 reads ``NET5 [('U3','5')]``), so a
    `must_connect` judgement that only asked "does the pin's net equal the target?"
    called a *dangling* pin "on the wrong net 'NET5'" and built a reconnect — a
    removal, of which there was nothing to remove: the plan refused with "nothing
    recognisable attaches the pin" and the connect form could not run at all.

    Ruling A's measurement is why one reading serves both directions: a
    single-member auto net *is* the shape of a pin that reaches nothing, and being
    alone on a net somebody **named** is still being somewhere. Both the NC
    judgement and the must_connect one call this, so they cannot disagree.
    """
    connected, how = nc_violation(model, comp, pin)
    return (not connected), how


def pin_company(model: DesignModel, comp: Component, pin: str) -> list[tuple[str, str]]:
    """Every *other* pin that shares this pin's net (035, measured on the machine).

    Why "shares" rather than "has a net name": a real export can carry a pin that
    *looks* connected and is not. Measured 2026-09-24 on 3.2.186: deleting the
    wire off a declared-NC pin left the pin sitting alone on a single-member
    auto-net (`NET6 [('U3','4')]`) — the editor kept the net object after its wire
    was gone. A rule that asked "is the pin's net set?" would call that connected
    and refuse to believe a repair it had just watched succeed (035's
    real-machine leg hit exactly this: apply's own readback said disconnected
    while the re-review said "still sits on net 'NET6'").

    Counting company is the reading that holds in both directions: a pin alone on
    its net is connected to nothing, whether that net is auto-named or the old
    name — and a pin that shares a net with others is connected, whatever the net
    is called.
    """
    node = (model.nets or {}).get(_pin_net(comp, pin) or "")
    if node is None:
        return []
    return [
        (str(name), str(number))
        for name, number in node.pins
        if not (str(name) == comp.designator and str(number) == str(pin))
    ]


def pin_obligation(entry: PartEntry, pin: str) -> tuple[str, str] | None:
    """``(kind, detail)`` for a pin the shelf has an obligation about, else None.

    ``kind`` is ``"nc"`` (declared not-connected) or ``"must_connect"`` (must
    reach ``detail``). Mode-tagged must_connect records are **not** obligations
    here: they are conditional, this rule has no voltage evidence, and the
    mode-aware decap rule owns them (011d §3.1) — the rule keeps the
    unconditional records, and so does this.
    """
    facts = entry.facts or {}
    for candidate in (facts.get("nc_pins") or {}).get("pins", []):
        if str(candidate) == str(pin):
            return "nc", ""
    for record in facts.get("must_connect", []):
        if record.get("mode") is not None:
            continue
        if str(record.get("pin", "")) == str(pin):
            return "must_connect", str(record.get("to", ""))
    return None


def pin_ruling(comp: Component, entry: PartEntry, model: DesignModel, pin: str) -> PinRuling:
    """This rule's judgement for one pin — the rule and the repair both call it."""
    obligation = pin_obligation(entry, pin)
    if obligation is None:
        return PinRuling(
            state=PIN_UNKNOWN,
            message=(
                f"{comp.designator} pin{pin}: the shelf records no nc_pins / "
                "must_connect obligation for this pin"
            ),
            missing_fact=(
                f"facts for {comp.designator} pin{pin} ({_identity(comp)}): record an "
                "nc_pins or must_connect obligation, or say there is none"
            ),
        )
    kind, target = obligation
    net = _pin_net(comp, pin)
    if kind == "nc":
        connected, how = nc_violation(model, comp, pin)
        if not connected:
            return PinRuling(
                state=PIN_OK,
                message=f"{comp.designator} pin{pin} is NC and {how}",
            )
        return PinRuling(
            state=PIN_VIOLATION,
            message=f"{comp.designator} pin{pin} is declared NC but {how}",
            evidence=[f"{comp.designator} pin{pin} @ {net or '(no net)'}"],
            target=_nc_target(comp.designator, str(pin), net or ""),
        )
    if target not in model.nets:
        return PinRuling(
            state=PIN_UNKNOWN,
            message=(
                f"{comp.designator} pin{pin}'s must_connect target is free text, "
                "not a net name"
            ),
            missing_fact=(
                f"must_connect target {target!r} on {comp.designator} pin{pin} is free "
                "text — connectivity alone cannot verify it"
            ),
        )
    if net == target:
        return PinRuling(
            state=PIN_OK,
            message=(
                f"{comp.designator} pin{pin} reaches its must_connect target net "
                f"{target!r}"
            ),
        )
    dangles, how = pin_dangles(model, comp, pin)
    if dangles:
        # Nothing to remove, so this is the **connect** form: `expected_before` is
        # the empty string, which is the plan's own word for "reaches nothing".
        return PinRuling(
            state=PIN_VIOLATION,
            message=(
                f"{comp.designator} pin{pin} must connect to net {target!r} and {how}"
            ),
            evidence=[f"{comp.designator} pin{pin} @ {net or '(no net)'}"],
            target=_must_connect_target(comp.designator, pin, None, target),
        )
    return PinRuling(
        state=PIN_VIOLATION,
        message=(
            f"{comp.designator} pin{pin} must connect to net {target!r} but sits on "
            f"{net!r}"
        ),
        evidence=[f"{comp.designator} pin{pin} @ {net}"],
        target=_must_connect_target(comp.designator, pin, net, target),
    )


class NcAndMustConnect(FactsRule):
    """CONN-2: declared-NC pins must be unconnected; must_connect pins must
    reach their target — machine-judgeable only when the target **is** a net
    name (``GND``/``VCC``); free text ("external 12MHz crystal network") gets
    UNKNOWN, because connectivity alone cannot read prose."""

    id = "conn-nc-and-must-connect"
    title = "Declared-NC pins stay unconnected; must_connect pins reach their target"
    level = LEVEL
    source = "house rule over the facts library's nc_pins / must_connect records"

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        # `row[0]`, not tuple-unpacking: since 035 the VIOLATION rows carry a
        # third element (their FindingTarget), and unpacking two names would turn
        # a repair capability into a crash in the states view — the same lesson
        # `DecapRequiredCaps.outcomes` records.
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _rows(self, model: DesignModel) -> list[tuple]:
        rows: list[tuple[Outcome, str | None]] = []
        for comp in self.ics(model):
            entry = self.entry_for(comp)
            if entry is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: no shelf entry, so its NC and "
                            "must-connect constraints cannot be checked"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} ({_identity(comp)}): "
                            "identify the part and record nc_pins / must_connect"
                        ),
                    ),
                    "ERROR",
                ))
                continue
            state = _category_state(entry)
            if state == _NON_IC:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="NOT_APPLICABLE",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: shelf category "
                            f"{entry.category!r} is not an IC — the rule speaks "
                            "to ICs only"
                        ),
                    ),
                    None,
                ))
                continue
            if state == _CATEGORY_UNKNOWN:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: {_facts_absent_reason(entry)}, "
                            "so its NC and must-connect constraints are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} (entry {entry.lcsc}, "
                            f"{_identity(comp)}): record nc_pins / must_connect"
                            + _gate_review_note(entry)
                        ),
                    ),
                    "ERROR",
                ))
                continue
            # Every obligation the shelf records for this part, judged **by the
            # one function** that also answers "is this pin already right?" for
            # the repair slice (035). The rows below are only plumbing around it:
            # a second per-pin judgement living here is exactly what the task
            # book forbids.
            for pin, _obligation in self._obligation_pins(entry):
                ruling = pin_ruling(comp, entry, model, pin)
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state=ruling.state,
                        subject=f"{comp.designator} pin{pin}",
                        message=ruling.message,
                        evidence=list(ruling.evidence),
                        missing_fact=ruling.missing_fact,
                    ),
                    "ERROR" if ruling.state == "VIOLATION" else None,
                    *([ruling.target] if ruling.target is not None else []),
                ))
        return rows

    @staticmethod
    def _obligation_pins(entry: PartEntry) -> list[tuple[str, str]]:
        """``(pin, kind)`` for every pin the shelf has an obligation about.

        Unconditional `must_connect` records only — a mode-tagged obligation is
        conditional and this rule has no voltage evidence (011d §3.1) — and the
        order is "NC pins first, then must-connect pins", the order the rows have
        always come in.
        """
        facts = entry.facts or {}
        out: list[tuple[str, str]] = []
        for pin in (facts.get("nc_pins") or {}).get("pins", []):
            out.append((str(pin), "nc"))
        for record in facts.get("must_connect", []):
            if record.get("mode") is not None:
                continue
            out.append((str(record.get("pin", "")), "must_connect"))
        return out


class LibraryPinConsistency(OutcomeRule):
    """CONN-3: the board's pins against the library symbol's pins.

    The offline review has no bridge, so by default the rule answers one
    UNKNOWN and names exactly what is missing. A **resolver** — anything that
    maps a component to the library's pin-number set, or None when it cannot
    resolve the identity — can be injected (tests do; the live bridge wiring
    is deliberately not part of 011c). Drift is symmetric: a pin the board
    has but the library does not, and a pin the library has but the board
    lost, are both reported — the USB1 case from M6 was the second kind.
    """

    id = "conn-library-pins"
    title = "Board pins match the library symbol's pin numbers"
    level = LEVEL
    source = "house rule; motivated by the USB1 library drift measured in M6 (2026-09-19)"

    def __init__(self, resolver=None) -> None:
        # resolver: Component -> set[str] | None
        self._resolver = resolver

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        rows = self._rows(model)
        return [outcome for outcome, _severity in rows]

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        for outcome, severity in self._rows(model):
            if outcome.state != "VIOLATION":
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=severity or "ERROR",
                    level=self.level,
                    message=outcome.message,
                    evidence=list(outcome.evidence),
                )
            )
        return findings

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        if self._resolver is None:
            return [(
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject="library pin comparison",
                    message=(
                        "library pin comparison needs the live bridge; the "
                        "offline review has no resolver"
                    ),
                    missing_fact=(
                        "a library resolver (bridge): board pins vs the "
                        "library symbol's pin numbers, per part with an "
                        "identity"
                    ),
                ),
                None,
            )]
        rows: list[tuple[Outcome, str | None]] = []
        for comp in model.components.values():
            if not IC_PATTERN.match(comp.designator):
                continue
            library_pins = self._resolver(comp)
            if library_pins is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: the resolver could not resolve "
                            "its library symbol"
                        ),
                        missing_fact=(
                            f"library symbol for {comp.designator} "
                            f"({_identity(comp)})"
                        ),
                    ),
                    None,
                ))
                continue
            board_pins = {pin.number for pin in comp.pins}
            extra = sorted(board_pins - library_pins)
            missing = sorted(library_pins - board_pins)
            if not extra and not missing:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: all {len(board_pins)} board "
                            "pins match the library symbol"
                        ),
                    ),
                    None,
                ))
                continue
            for pin in extra:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=f"{comp.designator} pin{pin}",
                        message=(
                            f"{comp.designator} pin{pin} exists on the board "
                            "but not in the library symbol"
                        ),
                        evidence=[f"{comp.designator} pin{pin} @ board-only"],
                    ),
                    "ERROR",
                ))
            for pin in missing:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=f"{comp.designator} pin{pin}",
                        message=(
                            f"{comp.designator} pin{pin} exists in the library "
                            "symbol but not on the board (library drift, the "
                            "USB1/M6 shape)"
                        ),
                        evidence=[f"{comp.designator} pin{pin} @ library-only"],
                    ),
                    "WARN",
                ))
        return rows


class SupplyOnKnownDomain(FactsRule):
    """PWR-1: every supply pin sits on a net whose voltage is known — and the
    report quotes the domain's source verbatim ("net name '+5V'" / "U5
    RT9013-33GB output"), because a voltage without its evidence is a rumour."""

    id = "pwr-supply-on-known-domain"
    title = "IC supply pins sit on nets with an inferred voltage"
    level = LEVEL
    source = (
        "house rule; domain inference per task 011c sec.3.1 (net-name "
        "whitelist + facts regulator outputs)"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in self.ics(model):
            entry = self.entry_for(comp)
            if entry is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: no shelf entry, so its supply "
                            "pins are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} ({_identity(comp)}): "
                            "identify the part and record supply_pins"
                        ),
                    ),
                    None,
                ))
                continue
            state = _category_state(entry)
            if state == _NON_IC:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="NOT_APPLICABLE",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: shelf category "
                            f"{entry.category!r} is not an IC"
                        ),
                    ),
                    None,
                ))
                continue
            if state == _CATEGORY_UNKNOWN:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: {_facts_absent_reason(entry)}, "
                            "so its supply pins are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} (entry {entry.lcsc}, "
                            f"{_identity(comp)}): record supply_pins"
                            + _gate_review_note(entry)
                        ),
                    ),
                    None,
                ))
                continue
            # One verdict per *pin*, not per record: a multi-mode part (the
            # CH340G's two VCC records) describes one physical pin.
            by_pin: dict[str, list[str]] = {}
            for record in (entry.facts or {}).get("supply_pins", []):
                for pin in record.get("pins", []):
                    by_pin.setdefault(str(pin), []).append(
                        str(record.get("name", "supply"))
                    )
            for pin, names in sorted(by_pin.items()):
                net = _pin_net(comp, pin)
                volts, source, why_not = domain_of(guesses, net)
                evidence = (
                    [f"{comp.designator} pin{pin} @ {net}"] if net else []
                )
                if volts is not None:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="OK",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} ({'/'.join(names)}) "
                                f"sits on {net!r} at {volts} V — {source}"
                            ),
                            evidence=evidence,
                        ),
                        None,
                    ))
                else:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="UNKNOWN",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin}'s net voltage "
                                "is unknown"
                            ),
                            evidence=evidence,
                            missing_fact=why_not,
                        ),
                        None,
                    ))
        return rows


class DomainVsRange(FactsRule):
    """PWR-2: the inferred domain voltage against the facts' ranges — two
    tiers, deliberately: exceeding ``v_abs_max`` is ERROR (destruction),
    exceeding ``v_operating`` while inside the absolute maximum is WARN
    (misuse, not death). A **multi-mode** part (CH340G: one 5V-mode record and
    one 3.3V-mode record, both on VCC/pin16) is OK when the measured voltage
    lands inside **any** record's operating range, and the message names the
    mode it hit."""

    id = "pwr-domain-vs-range"
    title = "Supply-pin voltage fits the datasheet's operating range"
    level = LEVEL
    source = "the part's own facts (v_operating / v_abs_max, each with datasheet provenance)"

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in self.ics(model):
            entry = self.entry_for(comp)
            if entry is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: no shelf entry, so its "
                            "operating ranges are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} ({_identity(comp)}): "
                            "identify the part and record v_operating / v_abs_max"
                        ),
                    ),
                    None,
                ))
                continue
            state = _category_state(entry)
            if state == _NON_IC:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="NOT_APPLICABLE",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: shelf category "
                            f"{entry.category!r} is not an IC"
                        ),
                    ),
                    None,
                ))
                continue
            if state == _CATEGORY_UNKNOWN:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: {_facts_absent_reason(entry)}, "
                            "so its operating ranges are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} (entry {entry.lcsc}, "
                            f"{_identity(comp)}): record v_operating / v_abs_max"
                        ),
                    ),
                    None,
                ))
                continue
            # One verdict per *pin*: the modes of a multi-mode part all
            # describe the same physical pin.
            by_pin: dict[str, list[dict]] = {}
            for record in (entry.facts or {}).get("supply_pins", []):
                for pin in record.get("pins", []):
                    by_pin.setdefault(str(pin), []).append(record)
            for pin, records in sorted(by_pin.items()):
                net = _pin_net(comp, pin)
                volts, _source, why_not = domain_of(guesses, net)
                if volts is None:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="UNKNOWN",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin}'s net voltage is "
                                "unknown, so no range can be applied"
                            ),
                            evidence=(
                                [f"{comp.designator} pin{pin} @ {net}"]
                                if net else []
                            ),
                            missing_fact=why_not,
                        ),
                        None,
                    ))
                    continue
                hit_modes = []
                over_operating = False
                over_abs: list[str] = []
                for record in records:
                    name = record.get("name", "supply")
                    operating = record.get("v_operating")
                    abs_max = record.get("v_abs_max")
                    if operating and operating[0] is not None and operating[1] is not None:
                        if operating[0] <= volts <= operating[1]:
                            hit_modes.append(name)
                        else:
                            over_operating = True
                    if abs_max:
                        low, high = abs_max
                        if (high is not None and volts > high) or (
                            low is not None and volts < low
                        ):
                            over_abs.append(
                                f"{name} abs max [{low}, {high}]"
                            )
                if over_abs:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="VIOLATION",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} at {volts} V "
                                f"exceeds its absolute maximum ({'; '.join(over_abs)})"
                            ),
                            evidence=[f"{comp.designator} pin{pin} @ {net} = {volts} V"],
                        ),
                        "ERROR",
                    ))
                elif hit_modes:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="OK",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} at {volts} V fits "
                                f"operating range of mode(s): {', '.join(hit_modes)}"
                            ),
                            evidence=[f"{comp.designator} pin{pin} @ {net} = {volts} V"],
                        ),
                        None,
                    ))
                elif over_operating:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="VIOLATION",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} at {volts} V is "
                                "outside every declared operating range (but "
                                "within the absolute maximum) — misuse, not "
                                "instant death"
                            ),
                            evidence=[f"{comp.designator} pin{pin} @ {net} = {volts} V"],
                        ),
                        "WARN",
                    ))
                else:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="OK",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} at {volts} V is "
                                "within the absolute maximum (no operating "
                                "range declared)"
                            ),
                            evidence=[f"{comp.designator} pin{pin} @ {net} = {volts} V"],
                        ),
                        None,
                    ))
        return rows


class LdoDropout(FactsRule):
    """PATH-1: an LDO's input-net voltage minus its output-net voltage must
    clear the dropout fact, or the part cannot regulate. Either side unknown
    -> UNKNOWN. Load budgets and OR-ing supplies are not modelled (roadmap:
    out of scope) — the rule says so in every message."""

    id = "path-ldo-dropout"
    title = "LDO headroom (Vin - Vout) clears the dropout fact"
    level = LEVEL
    source = "the part's own ldo.dropout_max_mv fact (datasheet provenance)"

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in self.ics(model):
            entry = self.entry_for(comp)
            if entry is None:
                continue  # unknown supply identity is PWR/CONN-2's report
            state = _category_state(entry)
            if state == _NON_IC:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="NOT_APPLICABLE",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: shelf category "
                            f"{entry.category!r} is not an LDO"
                        ),
                    ),
                    None,
                ))
                continue
            if state == _CATEGORY_UNKNOWN:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: {_category_absent_reason(entry)}, "
                            "so whether it is an LDO is unknown"
                        ),
                        missing_fact=(
                            f"category and ldo facts for {comp.designator} "
                            f"(entry {entry.lcsc}, {_identity(comp)})"
                            + _gate_review_note(entry)
                        ),
                    ),
                    None,
                ))
                continue
            ldo = (entry.facts or {}).get("ldo") or {}
            if entry.category != "ic.ldo":
                # An IC that is not an LDO (U1 is ic.usb-uart): the rule
                # speaks to LDOs only, and the category is explicit.
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="NOT_APPLICABLE",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: shelf category "
                            f"{entry.category!r} is not an LDO"
                        ),
                    ),
                    None,
                ))
                continue
            dropout_mv = ldo.get("dropout_max_mv")
            in_pin = next(
                (p for record in (entry.facts or {}).get("supply_pins", [])
                 for p in record.get("pins", [])),
                None,
            )
            out_pin = ldo_output_pin(entry)
            if dropout_mv is None or in_pin is None or out_pin is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: its facts do not name a "
                            "dropout, an input pin and an output pin together"
                        ),
                        missing_fact=(
                            f"ldo facts for {comp.designator}: dropout_max_mv, "
                            "input pin and output pin must all be present"
                        ),
                    ),
                    None,
                ))
                continue
            vin, _s, vin_why = domain_of(guesses, _pin_net(comp, str(in_pin)))
            vout, _s2, vout_why = domain_of(guesses, _pin_net(comp, str(out_pin)))
            if vin is None or vout is None:
                missing = [w for w in (vin_why, vout_why) if w]
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: headroom cannot be computed — "
                            "one of its rail voltages is unknown"
                        ),
                        evidence=[
                            f"{comp.designator} pin{in_pin} @ "
                            f"{_pin_net(comp, str(in_pin))}",
                            f"{comp.designator} pin{out_pin} @ "
                            f"{_pin_net(comp, str(out_pin))}",
                        ],
                        missing_fact="; ".join(missing),
                    ),
                    None,
                ))
                continue
            headroom_mv = (vin - vout) * 1000.0
            evidence = [
                f"{comp.designator} pin{in_pin} @ "
                f"{_pin_net(comp, str(in_pin))} = {vin} V",
                f"{comp.designator} pin{out_pin} @ "
                f"{_pin_net(comp, str(out_pin))} = {vout} V",
            ]
            if headroom_mv >= dropout_mv:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: headroom {headroom_mv:.0f} mV "
                            f">= dropout {dropout_mv:.0f} mV (load budgets and "
                            "OR-ing supplies are not modelled)"
                        ),
                        evidence=evidence,
                    ),
                    None,
                ))
            else:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: headroom {headroom_mv:.0f} mV "
                            f"< dropout {dropout_mv:.0f} mV — the output "
                            "cannot hold its rated voltage"
                        ),
                        evidence=evidence,
                    ),
                    "ERROR",
                ))
        return rows


class UsbCcPulldown(FactsRule):
    """CONN 族 bonus (task 011d sec.3.5): a connector that *declares* CC
    pull-down requirements gets them verified -- each required pin's net must
    carry a resistor to the ``to`` net whose value matches the declaration.

    Resistors are identified by their board value parsing as a resistance,
    not by the R prefix (the U3 lesson). A missing resistor is a VIOLATION;
    a present one with a different nominal is a WARN (Rd tolerance is ±10%
    in the spec, so nominal mismatch is worth naming but not screaming
    about); an unparseable resistor value is UNKNOWN. Connectors without
    pull_required facts are NOT_APPLICABLE -- the rule only speaks where the
    shelf declares a requirement."""

    id = "conn-usb-cc-pulldown"
    title = "Declared CC pull-down resistors are present and correctly sized"
    level = LEVEL
    source = (
        "the connector's own pull_required facts (provenance cites the USB "
        "Type-C Rd requirement via ST AN5225 Table 6)"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _resistance_to(
        self, model: DesignModel, net: str | None, to_net: str
    ) -> tuple[float | None, str | None]:
        """The resistor from ``net`` to ``to_net``: (ohms | None, designator).

        None ohms with a designator means "a candidate exists but its value
        does not parse" -- UNKNOWN territory. None designator means no
        candidate at all."""
        if not net:
            return None, None
        for designator, _pin in model.nets.get(net, Net("x", [])).pins:
            comp = model.components.get(designator)
            if comp is None:
                continue
            nets = [p.net for p in comp.pins if p.net]
            if to_net not in nets:
                continue
            ohms = parse_resistance_ohms(comp.value or "")
            return ohms, comp.designator
        return None, None

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        rows: list[tuple[Outcome, str | None]] = []
        for comp in model.components.values():
            entry = self.entry_for(comp)
            if entry is None or entry.category != "connector":
                continue
            pulls = (entry.facts or {}).get("pull_required") or []
            if not pulls:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="NOT_APPLICABLE",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: its shelf entry declares no "
                            "pull requirements"
                        ),
                    ),
                    None,
                ))
                continue
            for record in pulls:
                pin = str(record.get("pin", ""))
                to_net = str(record.get("to", ""))
                expected = parse_resistance_ohms(
                    str(record.get("expected_value", ""))
                )
                net = next(
                    (p.net for p in comp.pins if p.number == pin), None
                )
                evidence = [f"{comp.designator} pin{pin} @ {net}"]
                if net is None:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="UNKNOWN",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} is on no net, so "
                                "its pull requirement cannot be checked"
                            ),
                            evidence=evidence,
                            missing_fact=(
                                f"a net on {comp.designator} pin{pin}"
                            ),
                        ),
                        None,
                    ))
                    continue
                ohms, r_desig = self._resistance_to(model, net, to_net)
                if r_desig is None:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="VIOLATION",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin}: no resistor to "
                                f"{to_net!r} found on {net!r} (required "
                                f"{record.get('expected_value')})"
                            ),
                            evidence=evidence,
                        ),
                        "ERROR",
                    ))
                    continue
                if ohms is None:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="UNKNOWN",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{r_desig} sits between {comp.designator} "
                                f"pin{pin} and {to_net!r}, but its value does "
                                "not parse as a resistance"
                            ),
                            evidence=evidence,
                            missing_fact=f"a readable value on {r_desig}",
                        ),
                        None,
                    ))
                    continue
                if expected is not None and math.isclose(
                    ohms, expected, rel_tol=1e-3
                ):
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="OK",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin}: {r_desig} "
                                f"({ohms:.4g}Ω) pulls to {to_net!r} as "
                                f"declared ({record.get('expected_value')})"
                            ),
                            evidence=evidence + [f"{r_desig} value matches"],
                        ),
                        None,
                    ))
                else:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="VIOLATION",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin}: {r_desig} is "
                                f"{ohms:.4g}Ω, not the declared "
                                f"{record.get('expected_value')} -- wrong "
                                "pull-down value"
                            ),
                            evidence=evidence,
                        ),
                        "WARN",
                    ))
        return rows


__all__ = [
    "DEFAULT_LIBRARY_PATH",
    "DomainVsRange",
    "FactsRule",
    "LdoDropout",
    "LibraryPinConsistency",
    "NcAndMustConnect",
    "SupplyOnKnownDomain",
    "UsbCcPulldown",
]
