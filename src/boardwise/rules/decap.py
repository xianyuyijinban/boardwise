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

from ..core.decap import (
    CapCandidate,
    CapDecision,
    VALUE_SOURCE_MPN,
    VALUE_SOURCE_SCHEMATIC,
    VALUE_SOURCE_SHELF,
    VALUE_SOURCES_RECOVERED,
    bridges_to_ground as _bridges_to_ground,
    candidate_farads,
    cap_candidates_on,
    capacitance_text as _capacitance_text,
    component_looks_like_capacitor as _looks_like_capacitor,
    decide_required_cap,
    gated_capacitor as _gated_capacitor,
    looks_like_capacitor,
    recovered_capacitance,
    recovered_farads,
    value_source_label,
)
from ..core.model import Component, DesignModel, is_ground_net
from ..core.power_domains import domain_of, infer_net_domains
from .base import Finding, FindingTarget, Outcome
from .facts import (
    _CATEGORY_UNKNOWN,
    _NON_IC,
    FactsRule,
    _facts_absent_reason,
    _gate_review_note,
    _identity,
)
from .unproven import unproven_nets, unproven_outcome


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

    527D3 fix: 「already looks like one」 includes a class the tier gate refuses
    (:func:`_gated_capacitor`) — a capacitor the shelf named without a signature.
    Leaving it out here would make the row 「no grounded capacitor found on net
    X」 the answer for a part that **is** on the net with both terminals there,
    when what the reader needs to see is that it bridges nothing.
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
        if not _looks_like_capacitor(other, library) and not _gated_capacitor(
            other, library
        ):
            continue
        connected = {pin.net for pin in other.pins if pin.net is not None}
        if connected == {net_name}:
            found.append(other)
    return found


class DecapRequiredCaps(FactsRule):
    """DECAP-1: every required_caps record is satisfied on its own pin."""

    id = "decap-required-caps"
    title = "Declared decoupling capacitors are present, grounded, and sized"
    level = "L2-facts"
    source = (
        "the part's own required_caps / must_connect facts (datasheet "
        "provenance); mode sensitivity per task 011d sec.3.1"
    )
    #: 522: this rule computes a **number** — the capacitance on the pin against
    #: the capacitance the datasheet requires — so a machine-checked
    #: `required_caps` record (521 verified the quote verbatim) is enough. Which
    #: pin needs what is a datasheet reading, not a wiring conclusion; the wiring
    #: conclusions (`conn-nc-and-must-connect`) keep their human gate.
    REQUIRES_HUMAN_VERIFIED = False

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
                if volts is None or unproven_nets(model, (net,)):
                    # Issue #19's second half, on the mode question: the voltage
                    # may have been inferred from an LDO's output pin on a page
                    # that only *shares the net's name*, so the active mode is not
                    # established either. Same answer as "voltage unknown", and
                    # the mode-tagged record below reports it as UNKNOWN rather
                    # than silently not applying.
                    voltage_known = False
                    continue
                if operating[0] <= volts <= operating[1] and record.get("mode"):
                    hit.add(record["mode"])
        return hit, voltage_known

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(
            model, self.library, allow_machine=self._allow_machine
        )
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
            state = self._category_state(entry)
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
                            f"{comp.designator}: "
                            f"{_facts_absent_reason(entry, allow_machine=self._allow_machine)}, "
                            "so its required capacitors are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} (entry {entry.lcsc}, "
                            f"{_identity(comp)}): record required_caps"
                            + _gate_review_note(
                                entry, allow_machine=self._allow_machine
                            )
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
        self._stamp_trust(rows, model)
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

        # Issue #19: the per-page tier welded this net with every page that spells
        # the name the same way, so "a grounded capacitor of the required value is
        # on it" is not established — the capacitor may be on the other board (the
        # measured false pass), and "there is none" is not established either (a
        # cross-sheet capacitor on a one-board project is legal). Both directions
        # are withheld: the row is UNKNOWN.
        welded = unproven_nets(model, (net,))
        if welded:
            rows.append((
                unproven_outcome(
                    self.id,
                    f"{comp.designator} pin{pin}",
                    welded,
                    what=(
                        "whether a grounded capacitor of the required value "
                        f"{required_text!r} sits on it"
                    ),
                    evidence=evidence,
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
