"""DECAP-1: required decoupling capacitors, mode-sensitive (task 011d sec.3.1).

For an IC with ``required_caps`` facts, each record demands a capacitor on
the pin's net whose other end is grounded and whose value is not below the
declared one. Two rules of honesty govern the check:

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

from ..core.model import Component, DesignModel, is_ground_net
from ..core.power_domains import domain_of, infer_net_domains
from .base import Finding, Outcome
from .facts import (
    _CATEGORY_UNKNOWN,
    _NON_IC,
    FactsRule,
    _category_state,
    _identity,
)
from .values import decode_eia_3digit, mpn_value_code, parse_capacitance_farads


def _capacitance_farads(comp: Component, library) -> float | None:
    """The capacitor's value: board value first, else its MPN's EIA code.

    The MPN route needs the part to already look like a capacitor (see
    :func:`_looks_like_capacitor`): an MPN's digits are not self-evidently a
    value code (``CH340G`` would decode to "34 pF" otherwise -- measured on
    the golden board's U1)."""
    from_board = parse_capacitance_farads(comp.value or "")
    if from_board is not None:
        return from_board
    if not _looks_like_capacitor(comp, library):
        return None
    code = mpn_value_code(comp.mpn or "")
    if code is not None:
        return decode_eia_3digit(code, 1e-12)
    return None


def _grounded_cap_on(
    model: DesignModel, net_name: str, library
) -> tuple[Component, float | None] | None:
    """The best grounded capacitor on ``net_name``: the one with the largest
    *established* value. A cap with an unreadable value never wins -- "there
    is a cap but I cannot read it" is UNKNOWN territory, handled by the
    caller when no readable cap exists at all.

    A capacitor is identified by its board value parsing as a capacitance or
    its shelf category being ``capacitor`` -- never by the C designator
    prefix alone (the U3 lesson: prefixes lie), and never by an MPN code
    alone (the CH340G lesson: digits in an MPN are not a value claim)."""
    net = model.nets.get(net_name)
    if net is None:
        return None
    best: tuple[Component, float | None] | None = None
    unreadable: Component | None = None
    for designator, _pin in net.pins:
        other = model.components.get(designator)
        if other is None:
            continue
        if not _looks_like_capacitor(other, library):
            continue
        if not any(
            pin.net is not None and is_ground_net(pin.net)
            for pin in other.pins
        ):
            continue
        farads = _capacitance_farads(other, library)
        if farads is None:
            unreadable = unreadable or other
            continue
        if best is None or farads > best[1]:
            best = (other, farads)
    if best is not None:
        return best
    if unreadable is not None:
        return unreadable, None
    return None


_CAP_DESIGNATOR = re.compile(r"^C\d")


def _looks_like_capacitor(comp: Component, library) -> bool:
    if parse_capacitance_farads(comp.value or "") is not None:
        return True
    from ..core.parts import find_facts

    entry = None
    if comp.mpn:
        entry = find_facts(library, mpn=comp.mpn)
    if entry is None and comp.lcsc_part:
        entry = find_facts(library, lcsc=comp.lcsc_part)
    if entry is not None and entry.category == "capacitor":
        return True
    # The conjunction: a C-prefixed designator (positional evidence) *and* a
    # decodable MPN code -- neither signal alone. This is what lets an
    # unshelfed capacitor (the golden board's C4/C5/C9, whose values live
    # only in their MPNs) be counted, without letting the regulator
    # (CH340G-shaped MPNs decode as "34 pF") masquerade as one.
    if _CAP_DESIGNATOR.match(comp.designator) and mpn_value_code(
        comp.mpn or ""
    ):
        return True
    return False


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
        return [outcome for outcome, _s in self._rows(model)]

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
                            f"{comp.designator}: its shelf entry has no facts, "
                            "so its required capacitors are unknown"
                        ),
                        missing_fact=(
                            f"facts for {comp.designator} (entry {entry.lcsc}, "
                            f"{_identity(comp)}): record required_caps"
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
                self._check_cap_record(comp, record, model, rows)
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
    ) -> None:
        pin = str(record.get("pin", ""))
        declared = parse_capacitance_farads(str(record.get("value", "")))
        net = next((p.net for p in comp.pins if p.number == pin), None)
        evidence = [f"{comp.designator} pin{pin} @ {net}"] if net else []
        if declared is None:
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
        found = _grounded_cap_on(model, net, self.library) if net else None
        if found is None:
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
            ))
            return
        cap, farads = found
        if farads is None:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin}: a grounded capacitor "
                        f"({cap.designator}) is present on {net!r}, but its "
                        "value cannot be established (board value and MPN "
                        "code both unreadable)"
                    ),
                    evidence=evidence + [f"{cap.designator} value {cap.value!r}"],
                    missing_fact=(
                        f"a readable value for capacitor {cap.designator}"
                    ),
                ),
                None,
            ))
            return
        if farads + 1e-12 >= declared:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=f"{comp.designator} pin{pin}",
                    message=(
                        f"{comp.designator} pin{pin}: {cap.designator} "
                        f"provides {_fmt_farads(farads)} >= required "
                        f"{_fmt_farads(declared)} to ground on {net!r}"
                    ),
                    evidence=evidence + [f"{cap.designator} value {cap.value!r}"],
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
                        f"on {net!r} is only {_fmt_farads(farads)} "
                        f"(< required {_fmt_farads(declared)})"
                    ),
                    evidence=evidence + [f"{cap.designator} value {cap.value!r}"],
                ),
                "WARN",
            ))


def _fmt_farads(value: float) -> str:
    if value >= 1e-6:
        return f"{value / 1e-6:.3g}uF"
    if value >= 1e-9:
        return f"{value / 1e-9:.3g}nF"
    return f"{value / 1e-12:.3g}pF"
