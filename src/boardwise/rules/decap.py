"""DECAP-1: required decoupling capacitors, mode-sensitive (task 011d sec.3.1).

For an IC with ``required_caps`` facts, each record demands a capacitor on
the pin's net whose **other end is on a different ground net** and whose value
is not below the declared one. Three rules of honesty govern the check:

- **Mode sensitivity.** A record tagged ``mode`` applies only when the board
  actually runs that part in that mode; the mode is *measured* from the
  supply-pin net's inferred voltage against each supply record's operating
  range -- never from a net name's looks. If the voltage is unknown, a
  mode-tagged record is UNKNOWN (the mode cannot be determined), not OK.
  The CH340G V3 defect is exactly the mode-sensitive ``must_connect`` half
  of this rule: in 3.3V mode V3 must sit on VCC, and on the golden board it
  does not.
- **Per component, per pin.** A shared power rail having *a* capacitor does
  not make every part on it compliant (DECAP-2 is a scope statement, not a
  separate rule): the check runs per record and compares values.
- **The bridge, and the two shapes that are not one** (039 批①b, both measured
  on the thesis board). A capacitor with both terminals on the same net is not a
  candidate -- it bridges nothing -- and gets its own WARN naming it; and a
  capacitor that exists but whose value nobody declared makes the requirement
  UNKNOWN ("a capacitor is present, its value cannot be established"), not
  "no grounded capacitor found". And when the protected pin's own net **is** a
  ground net the rule decides nothing at all (UNKNOWN, naming that fact): a
  supply pin on a ground net is a connectivity question, and this rule used to
  answer it OK because a ground net is full of "grounded" capacitors.

A capacitor's value is taken from the board's ``value`` field when it
parses, else from its MPN's EIA code when that decodes unambiguously, else
the check is UNKNOWN -- a capacitor whose value cannot be established is not
evidence of compliance. "Not below the declared value" (>=) is the
engineering meaning of a decoupling requirement; the message always shows
both numbers so a reader can disagree with the semantics, and the task's own
golden expectation is phrased ">=1uF" (RT9013 pins).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..core.model import Component, DesignModel, is_ground_net
from ..core.power_domains import domain_of, infer_net_domains
from .base import Finding, FindingTarget, Outcome
from .facts import (
    _CATEGORY_UNKNOWN,
    _NON_IC,
    FactsRule,
    _category_state,
    _facts_absent_reason,
    _gate_review_note,
    _identity,
)
from .values import decode_eia_3digit, mpn_value_code, parse_capacitance_farads


def _capacitance_farads(comp: Component, library) -> float | None:
    """A parsed component's capacitor value — the shared reading, by fields.

    A wrapper over :func:`candidate_farads` so there is exactly one
    board-value-then-MPN-code implementation (see :class:`CapCandidate`).
    """
    return candidate_farads(
        CapCandidate(
            designator=comp.designator,
            value=comp.value or "",
            mpn=comp.mpn or "",
            lcsc=comp.lcsc_part or "",
            footprint=comp.footprint or "",
        ),
        library,
    )


_CAP_DESIGNATOR = re.compile(r"^C\d")

#: A footprint that is **only** a chip package size: `0603`, `C0603`, `C_0805`.
#: This is the shape a capacitor carries when nobody ever filled its value in
#: (measured: the thesis board's C34, footprint `0603`, `Name` attribute null),
#: and it is the weakest evidence :func:`looks_like_capacitor` accepts — the
#: designator must still be C-prefixed, and the whole footprint must be the size,
#: so a hand-drawn or oddly named part cannot slip in on this route.
_CHIP_SIZE_FOOTPRINT = re.compile(r"^(?:[A-Za-z]+[-_]?)?\d{4}$")


@dataclass(frozen=True)
class CapCandidate:
    """One capacitor candidate for a decoupling requirement, as an inventory item.

    Deliberately *not* a :class:`~boardwise.core.model.Component`: the offline
    rule reads the parsed board, and apply's idempotence probe reads the live
    page (`sch.geometry` + `sch.netlist`), and the two inventories have almost
    nothing in common except the four fields a decision needs. Keeping the
    decision below on this shape is what lets both sides call **one**
    implementation instead of writing two similar ones — the whole point of
    §二.5 ("repeat apply must never create a second part, and the probe is the
    rule's own judgement").
    """

    designator: str
    value: str = ""
    mpn: str = ""
    lcsc: str = ""
    footprint: str = ""
    #: Whether the candidate's other end is on a ground net. Only grounded
    #: candidates can satisfy a decoupling requirement; an ungrounded one is not
    #: evidence of anything (the rule says so, and so does apply).
    grounded: bool = False


def looks_like_capacitor(
    designator: str,
    value: str,
    mpn: str,
    lcsc: str,
    library=None,
    *,
    footprint: str = "",
) -> bool:
    """Is this inventory item a capacitor? — one predicate, two callers.

    Takes the fields rather than a ``Component`` so the live page (which has no
    ``Component``) can ask the same question. The rule's own wrapper
    (:func:`_looks_like_capacitor`) passes a parsed component's fields through
    here, so the offline rule and apply cannot answer differently.

    Three routes, strongest first, and the third one is 039 批①b's:

    1. the ``value`` parses as a capacitance;
    2. the shelf says ``category: capacitor``;
    3. positional + shape evidence: a **C-prefixed designator** *and* either a
       decodable MPN value code or a chip-size-only footprint.

    Route 3 is what separates "a capacitor is there but its value is not" from
    "there is no capacitor": a part matched only this way becomes a candidate
    whose value is unreadable, so the decision is ``unreadable`` (UNKNOWN, with
    the capacitor named) rather than ``missing`` ("no grounded capacitor
    found") — two different statements about the board, and only one of them
    true. It is deliberately the narrow conjunction: route 2 alone would trust a
    category the shelf may not have, and either signal alone would let a
    regulator with a capacitor-shaped MPN masquerade as one.
    """
    if parse_capacitance_farads(value or "") is not None:
        return True
    from ..core.parts import find_facts

    entry = None
    if library is None:
        # No shelf in hand (029-b measured this path from apply's probe): the
        # shelf questions simply have no answer, and the value/designator
        # evidence below still does. `find_facts(None, …)` used to raise
        # `AttributeError: 'NoneType' object has no attribute 'parts'` — a crash
        # in the middle of an apply, discovered on the machine because every
        # fixture net happened to be shelf-free.
        return bool(
            _CAP_DESIGNATOR.match(designator or "")
            and (
                mpn_value_code(mpn or "")
                or _CHIP_SIZE_FOOTPRINT.match((footprint or "").strip())
            )
        )
    if mpn:
        entry = find_facts(library, mpn=mpn)
    if entry is None and lcsc:
        entry = find_facts(library, lcsc=lcsc)
    if entry is not None and entry.category == "capacitor":
        return True
    # The conjunction: a C-prefixed designator (positional evidence) *and* a
    # decodable MPN code -- neither signal alone. This is what lets an
    # unshelfed capacitor (the golden board's C4/C5/C9, whose values live
    # only in their MPNs) be counted, without letting the regulator
    # (CH340G-shaped MPNs decode as "34 pF") masquerade as one.
    if _CAP_DESIGNATOR.match(designator or "") and mpn_value_code(mpn or ""):
        return True
    # ... and the same conjunction with the footprint's shape instead of the
    # MPN's code, for the part that says nothing about itself at all.
    if _CAP_DESIGNATOR.match(designator or "") and _CHIP_SIZE_FOOTPRINT.match(
        (footprint or "").strip()
    ):
        return True
    return False


def candidate_farads(candidate: CapCandidate, library=None) -> float | None:
    """The value of one candidate: board value first, else its MPN's EIA code.

    The MPN route needs the part to already look like a capacitor (see
    :func:`looks_like_capacitor`): an MPN's digits are not self-evidently a
    value code (``CH340G`` would decode to "34 pF" otherwise -- measured on the
    golden board's U1)."""
    from_board = parse_capacitance_farads(candidate.value or "")
    if from_board is not None:
        return from_board
    if not looks_like_capacitor(
        candidate.designator,
        candidate.value,
        candidate.mpn,
        candidate.lcsc,
        library,
        footprint=candidate.footprint,
    ):
        return None
    code = mpn_value_code(candidate.mpn or "")
    if code is not None:
        return decode_eia_3digit(code, 1e-12)
    return None


@dataclass(frozen=True)
class CapDecision:
    """What one decoupling requirement amounts to, given an inventory.

    ``state`` is one of ``unparseable`` / ``missing`` / ``unreadable`` /
    ``satisfied`` / ``too_small``; everything else is the evidence for it, so a
    caller can phrase its own message (the rule does, and apply's probe does)
    without recomputing anything.
    """

    state: str
    required_farads: float | None = None
    required_text: str = ""
    cap_designator: str = ""
    cap_farads: float | None = None

    @property
    def satisfied(self) -> bool:
        return self.state == "satisfied"


def decide_required_cap(
    declared_text: str,
    candidates: Sequence[CapCandidate],
    library=None,
) -> CapDecision:
    """**The one decision**: is this requirement met by this inventory?

    Both `decap-required-caps` and `edit apply`'s idempotence probe call this —
    the rule to report a violation, the probe to decide whether a previous run
    (or the operator's own hand) already satisfied it. §二.5 forbids a second,
    similar-looking implementation, and this function is where that is enforced:
    if the two ever disagree, they disagree here, visibly, in one place.

    The semantics are the rule's, unchanged:

    * ``missing``    — no candidate at all on the net.
    * ``unreadable`` — candidates exist but none has an establishable value
      (a cap whose value cannot be read is *not* evidence of compliance).
    * ``satisfied``  — the best readable candidate is ``>=`` the requirement
      ("not below the declared value" is the engineering meaning).
    * ``too_small``  — it exists and its value is below the requirement.
    * ``unparseable``— the requirement itself is not a capacitance.
    """
    required = parse_capacitance_farads(str(declared_text or ""))
    if required is None:
        return CapDecision("unparseable", required_text=str(declared_text or ""))
    best: tuple[CapCandidate, float] | None = None
    unreadable: CapCandidate | None = None
    for candidate in candidates:
        farads = candidate_farads(candidate, library)
        if farads is None:
            unreadable = unreadable or candidate
            continue
        if best is None or farads > best[1]:
            best = (candidate, farads)
    if best is None:
        if unreadable is not None:
            return CapDecision(
                "unreadable",
                required_farads=required,
                required_text=str(declared_text or ""),
                cap_designator=unreadable.designator,
            )
        return CapDecision(
            "missing", required_farads=required, required_text=str(declared_text or "")
        )
    candidate, farads = best
    return CapDecision(
        "satisfied" if farads + 1e-12 >= required else "too_small",
        required_farads=required,
        required_text=str(declared_text or ""),
        cap_designator=candidate.designator,
        cap_farads=farads,
    )


def _bridges_to_ground(comp: Component, net_name: str) -> bool:
    """One terminal on ``net_name``, the **other** on a different ground net.

    This is what "grounded" has to mean for a decoupling requirement to be met:
    a capacitor with both terminals on one net connects nothing, so it cannot
    decouple that net from anything. Measured (039 批①b): the thesis board's
    C115 carries ``330uF`` and both terminals on ``AGND``, and the pre-039b
    predicate counted it as satisfying a requirement on ``AGND``.
    """
    others = {
        pin.net for pin in comp.pins if pin.net is not None and pin.net != net_name
    }
    return any(is_ground_net(name) for name in others)


def cap_candidates_on(model: DesignModel, net_name: str, library=None) -> list[CapCandidate]:
    """Every decoupling candidate on ``net_name``, from the parsed board.

    A candidate must (a) be a capacitor by :func:`looks_like_capacitor` and
    (b) **bridge** the net to ground — one terminal here, the other on a
    *different* ground net. Both halves are requirements, not preferences: a
    part that is not a capacitor is not evidence, and a capacitor whose two
    terminals sit on the same net is not a bridge (039 批①b measured the second
    case on a real board). The *value* question is left to
    :func:`decide_required_cap` so that the same comparison serves both callers.
    """
    net = model.nets.get(net_name)
    if net is None:
        return []
    found: list[CapCandidate] = []
    for designator, _pin in net.pins:
        other = model.components.get(designator)
        if other is None:
            continue
        if not _looks_like_capacitor(other, library):
            continue
        if not _bridges_to_ground(other, net_name):
            continue
        found.append(
            CapCandidate(
                designator=other.designator,
                value=other.value or "",
                mpn=other.mpn or "",
                lcsc=other.lcsc_part or "",
                footprint=other.footprint or "",
                grounded=True,
            )
        )
    return found


def same_net_capacitors_on(
    model: DesignModel, net_name: str, library=None
) -> list[Component]:
    """Capacitors on ``net_name`` whose **every** terminal is on ``net_name``.

    The complement of :func:`_bridges_to_ground`, and the reason it exists as its
    own function: a capacitor drawn closed on itself is not a decoupling
    candidate (it is excluded above) *and* is worth one row of its own — "both
    terminals on one net" is either a schematic/soldering error or a netlist
    that cannot be read, and either way a reviewer should see it.

    Only capacitors that already look like capacitors reach this list; an
    unreadable part is C34's case (a candidate, not a phantom).
    """
    net = model.nets.get(net_name)
    if net is None:
        return []
    found: list[Component] = []
    seen: set[str] = set()
    for designator, _pin in net.pins:
        other = model.components.get(designator)
        if other is None or other.designator in seen:
            continue
        seen.add(other.designator)
        if len(other.pins) < 2:
            continue
        if not _looks_like_capacitor(other, library):
            continue
        connected = {pin.net for pin in other.pins if pin.net is not None}
        if connected == {net_name}:
            found.append(other)
    return found


def _looks_like_capacitor(comp: Component, library) -> bool:
    """Is this parsed component a capacitor? — the shared predicate, by fields.

    Kept as a `Component`-shaped wrapper because the rule's tests import it
    (``tests/test_011d_rules.py``), and because every caller inside the rule
    already has a component in hand. The judgement itself is
    :func:`looks_like_capacitor`, which the live-page side of apply calls with
    the same fields.
    """
    return looks_like_capacitor(
        comp.designator,
        comp.value or "",
        comp.mpn or "",
        comp.lcsc_part or "",
        library,
        footprint=comp.footprint or "",
    )


class DecapRequiredCaps(FactsRule):
    """DECAP-1: every required_caps record is satisfied on its own pin."""

    id = "decap-required-caps"
    title = "Declared decoupling capacitors are present, grounded, and sized"
    level = "L2-facts"
    source = (
        "the part's own required_caps / must_connect facts (datasheet "
        "provenance); mode sensitivity per task 011d sec.3.1"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        # Row shape is (outcome, severity), optionally with a third element (the
        # FindingTarget, task 016/029). Read as `row[0]` rather than unpacking two
        # names: the moment a row gained a target, tuple-unpacking here would
        # have turned a repair capability into a crash in the states view.
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _hit_modes(
        self,
        comp: Component,
        entry: PartEntry,
        model: DesignModel,
        guesses: dict,
    ) -> tuple[set[str], bool]:
        """Modes the board actually runs this part in, from measured voltage.

        Returns ``(hit_modes, voltage_known)``. A record without a mode is
        unconditional and never gates on this; records *with* a mode apply
        only when their operating range contains the supply pin's inferred
        voltage.
        """
        hit: set[str] = set()
        voltage_known = True
        for record in (entry.facts or {}).get("supply_pins", []):
            operating = record.get("v_operating")
            if not operating or operating[0] is None or operating[1] is None:
                continue
            for pin in record.get("pins", []):
                net = next(
                    (p.net for p in comp.pins if p.number == str(pin)), None
                )
                volts, _source, why_not = domain_of(guesses, net)
                if volts is None:
                    voltage_known = False
                    continue
                if operating[0] <= volts <= operating[1] and record.get("mode"):
                    hit.add(record["mode"])
        return hit, voltage_known

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        #: "(net, capacitor)" pairs already reported as bridging nothing, so a
        #: rail examined by three parts gets one row about its phantom capacitor
        #: rather than three (039 批①b).
        seen_phantoms: set[tuple[str, str]] = set()
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
                            "required capacitors are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} ({_identity(comp)}): "
                            "identify the part and record required_caps"
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
                            "so its required capacitors are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} (entry {entry.lcsc}, "
                            f"{_identity(comp)}): record required_caps"
                            + _gate_review_note(entry)
                        ),
                    ),
                    None,
                ))
                continue
            facts = entry.facts or {}
            required = facts.get("required_caps") or []
            must = facts.get("must_connect") or []
            if not required and not must:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: its facts name no required "
                            "capacitors and no must-connect pins"
                        ),
                        missing_fact=(
                            f"required_caps facts for {comp.designator} "
                            f"(entry {entry.lcsc})"
                        ),
                    ),
                    None,
                ))
                continue
            hit_modes, voltage_known = self._hit_modes(
                comp, entry, model, guesses
            )
            for record in required:
                mode = record.get("mode")
                if mode is not None and mode not in hit_modes:
                    if not voltage_known:
                        rows.append((
                            Outcome(
                                rule_id=self.id,
                                state="UNKNOWN",
                                subject=f"{comp.designator} pin{record['pin']}",
                                message=(
                                    f"{comp.designator} pin{record['pin']}'s "
                                    f"{mode!r}-mode requirement cannot be "
                                    "checked: the supply voltage is unknown, "
                                    "so the active mode is unknown"
                                ),
                                missing_fact=(
                                    f"the supply-pin net voltage for "
                                    f"{comp.designator} (needed to decide "
                                    f"whether mode {mode!r} is active)"
                                ),
                            ),
                            None,
                        ))
                    # An inactive mode's requirement simply does not apply:
                    # silence, because the record said when it applies and
                    # the board measured otherwise.
                    continue
                self._check_cap_record(comp, record, model, rows, seen_phantoms)
            for record in must:
                mode = record.get("mode")
                if mode is not None and mode not in hit_modes:
                    continue
                target = str(record.get("to", ""))
                pin = str(record.get("pin", ""))
                if target not in model.nets:
                    continue  # free text: CONN-2's report, not this rule's
                net = next(
                    (p.net for p in comp.pins if p.number == pin), None
                )
                if net == target:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="OK",
                            subject=f"{comp.designator} pin{pin}",
                            message=(
                                f"{comp.designator} pin{pin} sits on its "
                                f"required net {target!r}"
                                + (f" (mode {mode!r})" if mode else "")
                            ),
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
                                f"{comp.designator} pin{pin} must sit on net "
                                f"{target!r}"
                                + (f" in mode {mode!r}" if mode else "")
                                + f" but is on {net!r} — the datasheet's "
                                "wiring for the active mode is not what the "
                                "board does"
                            ),
                            evidence=[f"{comp.designator} pin{pin} @ {net}"],
                        ),
                        "WARN",
                    ))
        return rows

    def _check_cap_record(
        self,
        comp: Component,
        record: dict,
        model: DesignModel,
        rows: list[tuple[Outcome, str | None]],
        seen_phantoms: set[tuple[str, str]],
    ) -> None:
        pin = str(record.get("pin", ""))
        required_text = str(record.get("value", ""))
        net = next((p.net for p in comp.pins if p.number == pin), None)
        evidence = [f"{comp.designator} pin{pin} @ {net}"] if net else []

        if net and is_ground_net(net):
            # 039 批①b's boundary: when the protected pin sits on a **ground**
            # net, this rule does not decide anything — not "satisfied" and not
            # "missing". It used to say OK here, because a ground net always has
            # grounded capacitors on it (measured: the thesis board's U5 pin5 is
            # on AGND and its requirement was "met" by C115, a capacitor whose
            # own two terminals are both AGND). A supply pin landing on a ground
            # net is a **connectivity** question — a short, or a netlist that
            # cannot be read — and a capacitor rule must not answer it. The row
            # names the board fact and stops.
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin} sits on the ground net "
                        f"{net!r}, so its decoupling requirement cannot be "
                        "judged from here — a supply pin on a ground net is a "
                        "connectivity question, not a capacitor one"
                    ),
                    evidence=evidence,
                    missing_fact=(
                        f"a net for {comp.designator} pin{pin} that is not a "
                        f"ground net (it is on {net!r} today)"
                    ),
                ),
                None,
            ))
            return

        for phantom in same_net_capacitors_on(model, net, self.library):
            key = (net, phantom.designator)
            if key in seen_phantoms:
                continue
            seen_phantoms.add(key)
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=phantom.designator,
                    message=(
                        f"{phantom.designator}: both terminals are on net "
                        f"{net!r}, so it bridges nothing and cannot decouple "
                        f"it (required {required_text} for "
                        f"{comp.designator} pin{pin})"
                    ),
                    evidence=[
                        f"{phantom.designator} @ {net} (both terminals)",
                        f"{phantom.designator} value {phantom.value or ''!r}",
                    ],
                ),
                "WARN",
            ))

        candidates = cap_candidates_on(model, net, self.library) if net else []

        def target() -> FindingTarget:
            """The structured form of *this* row's claim (task 029 §二.1).

            ``component_ref`` is the IC that needs the capacitor (the anchor a
            repair hangs off), ``pin_refs``/``net_refs`` say which supply pin and
            which net, and ``suggested_after`` carries the recipe exactly as the
            facts shelf states it (``"0.1uF"``) — never a re-formatted number,
            because it is what the plan has to compare and place against.

            Built for the VIOLATION rows only: an OK row has nothing to repair,
            and an UNKNOWN row's honest answer is the missing fact it already
            names, not a plan.
            """
            return FindingTarget(
                component_ref=comp.designator,
                pin_refs=[pin],
                net_refs=[net] if net else [],
                suggested_after=required_text,
            )

        candidates = cap_candidates_on(model, net, self.library) if net else []
        decision = decide_required_cap(required_text, candidates, self.library)
        if decision.state == "unparseable":
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin}'s required capacitor "
                        f"value {record.get('value')!r} does not parse as a "
                        "capacitance"
                    ),
                    missing_fact=(
                        f"a parseable value in required_caps for "
                        f"{comp.designator} pin{pin}"
                    ),
                ),
                None,
            ))
            return
        declared = decision.required_farads
        assert declared is not None  # parseable by construction, above
        if decision.state == "missing":
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin}: no grounded capacitor "
                        f"found on net {net!r} (required "
                        f"{record.get('value')})"
                    ),
                    evidence=evidence,
                ),
                "WARN",
                target(),
            ))
            return
        cap = next(
            (
                model.components.get(candidate.designator)
                for candidate in candidates
                if candidate.designator == decision.cap_designator
            ),
            None,
        )
        if decision.state == "unreadable":
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin}: a capacitor is present on "
                        f"{net!r} ({decision.cap_designator}), but its value "
                        "cannot be established, so the required "
                        f"{record.get('value')} cannot be checked"
                    ),
                    evidence=evidence
                    + [f"{decision.cap_designator} value {(cap.value if cap else '')!r}"],
                    missing_fact=(
                        f"a readable value for capacitor {decision.cap_designator}"
                    ),
                ),
                None,
            ))
            return
        assert decision.cap_farads is not None
        if decision.state == "satisfied":
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin}: {decision.cap_designator} "
                        f"provides {_fmt_farads(decision.cap_farads)} >= required "
                        f"{_fmt_farads(declared)} to ground on {net!r}"
                    ),
                    evidence=evidence
                    + [f"{decision.cap_designator} value {(cap.value if cap else '')!r}"],
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
                        f"{comp.designator} pin{pin}: the grounded capacitor "
                        f"on {net!r} is only {_fmt_farads(decision.cap_farads)} "
                        f"(< required {_fmt_farads(declared)})"
                    ),
                    evidence=evidence
                    + [f"{decision.cap_designator} value {(cap.value if cap else '')!r}"],
                ),
                "WARN",
                target(),
            ))


def _fmt_farads(value: float) -> str:
    if value >= 1e-6:
        return f"{value / 1e-6:.3g}uF"
    if value >= 1e-9:
        return f"{value / 1e-9:.3g}nF"
    return f"{value / 1e-12:.3g}pF"
