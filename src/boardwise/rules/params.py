"""PARAM rules (task 011d sec.3.2-3.4): LED current, divider output, RC
cutoff, and the value-vs-MPN cross-check.

All four are four-state rules over the netlist model, the shelf, and (where
voltages matter) the domain inference. Division of labour worth stating in
code, because two rules look at the same resistor:

- ``param-led-current`` judges the LED's series resistance using the
  **board's value field** (what the schematic declares), against the oracle's
  window for the 3V3 domain (revision of 2026-09-19, replacing the earlier
  current computation);
- ``param-value-mpn-match`` judges whether that declaration agrees with the
  part's MPN. A board can pass one and fail the other: a 1k board value
  gives a legal current while contradicting a 470-ohm MPN -- exactly the
  golden board's U3.
"""

from __future__ import annotations

import math

from ..core.model import Component, DesignModel, is_ground_net
from ..core.power_domains import domain_of, infer_net_domains
from .base import Finding, Outcome
from .facts import FactsRule
from .values import (
    decode_eia_3digit,
    mpn_value_code,
    parse_capacitance_farads,
)

LEVEL = "L2-facts"

#: The oracle's window for an indicator LED's series resistance, in ohms,
#: **inclusive**. Ruling of 2026-09-19: in the 3V3 domain the series resistance
#: must sit in [470, 2200] ohm, judged by the resistance value (4.7k is the
#: counter-example and violates); every other domain is UNKNOWN.
#:
#: Judging the *resistance* replaced the earlier current computation (floor
#: 0.5 mA, ceiling 50% of the datasheet If max). Three reasons, in the order
#: they matter: the window is the design intent a reviewer can read straight
#: off the BOM; it needs no LED facts, so an LED with no shelf entry is still
#: gradeable; and the old rule's verdict on the golden board's own 1k part was
#: UNKNOWN (Vf 2.7-3.2 V straddled the floor) for a part the oracle had just
#: ruled *correct* -- a rule that cannot say "fine" about the reference design
#: is measuring the wrong number.
LED_SERIES_BOUNDS_3V3 = (470.0, 2200.0)

#: The domain the window is stated for, and how far a KNOWN net voltage may
#: sit from it and still count as that domain.
LED_WINDOW_DOMAIN_V = 3.3
LED_DOMAIN_TOLERANCE_V = 0.05


def parse_resistance_ohms(value: str) -> float | None:
    """Re-exported helper: the L1 parser is the one ohm parser."""
    from .connectivity import parse_resistance_ohms as _parse

    return _parse(value)


def _kind_of(comp: Component, entry) -> str | None:
    """``"resistor"`` / ``"capacitor"`` / None -- shelf category first, then
    the value's unit. The unit inference is what lets the golden board's U3
    (a v1-era shelf entry with no category) be judged at all: its value
    ``1kΩ`` names a resistance."""
    category = (entry.category if entry is not None else "") or ""
    if category in ("resistor", "capacitor"):
        return category
    value = comp.value or ""
    if parse_resistance_ohms(value) is not None:
        return "resistor"
    if parse_capacitance_farads(value) is not None:
        return "capacitor"
    return None


class ValueMpnMatch(FactsRule):
    """PARAM-4: the board's value field agrees with the MPN's decoded value.

    The decoder is a whitelist (EIA three-digit codes, package codes guarded);
    an MPN that decodes to nothing is UNKNOWN ("contains no decodable value"),
    never a guessed match. R24/R27 have no MPN at all and stay UNKNOWN for
    exactly that reason."""

    id = "param-value-mpn-match"
    title = "The board's value field matches the MPN's decoded value"
    level = LEVEL
    source = (
        "house rule (EIA three-digit code cross-check); the contradiction is "
        "a BOM/schematic mismatch, not a hazard"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        rows: list[tuple[Outcome, str | None]] = []
        for comp in model.components.values():
            entry = self.entry_for(comp)
            kind = _kind_of(comp, entry)
            if kind is None:
                continue  # neither resistor nor capacitor by any evidence
            code = mpn_value_code(comp.mpn or "")
            if code is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: its MPN "
                            f"{comp.mpn!r} contains no decodable EIA value "
                            "code (or two conflicting ones)"
                        ),
                        missing_fact=(
                            f"a decodable EIA value code in the MPN of "
                            f"{comp.designator}"
                        ),
                    ),
                    None,
                ))
                continue
            if kind == "resistor":
                declared = parse_resistance_ohms(comp.value or "")
                decoded = decode_eia_3digit(code, 1.0)
                unit = "Ω"
            else:
                declared = parse_capacitance_farads(comp.value or "")
                decoded = decode_eia_3digit(code, 1e-12)
                unit = "F"
            if declared is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: the MPN decodes to "
                            f"{decoded:.4g} {unit} but the board's value "
                            f"field {comp.value!r} is empty or unparsable"
                        ),
                        missing_fact=(
                            f"a parseable value field on {comp.designator}"
                        ),
                    ),
                    None,
                ))
                continue
            # Nominal equality with a relative tolerance: both numbers are
            # nominal declarations of the same part, so 470 vs 470.0 is a
            # match and 470 vs 1000 is a contradiction.
            if math.isclose(declared, decoded, rel_tol=1e-3):
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: board value "
                            f"{declared:.4g} {unit} matches MPN code "
                            f"{code} ({decoded:.4g} {unit})"
                        ),
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
                            f"{comp.designator}: board value "
                            f"{declared:.4g} {unit} contradicts its MPN "
                            f"({comp.mpn!r} decodes to {decoded:.4g} {unit}) "
                            "-- BOM and schematic disagree"
                        ),
                        evidence=[
                            f"{comp.designator} value {comp.value!r}",
                            f"{comp.designator} mpn {comp.mpn!r}",
                        ],
                    ),
                    "WARN",
                ))
        return rows


class LedCurrent(FactsRule):
    """PARAM-1: an indicator LED's series resistance sits in the oracle's window.

    The judged quantity is the **board's value field** of the series
    resistor(s) -- the value-vs-MPN contradiction is
    ``param-value-mpn-match``'s business, not this rule's. In the 3V3 domain
    the oracle's window is :data:`LED_SERIES_BOUNDS_3V3` (inclusive); a supply
    rail at any other, or at no nameable, voltage is UNKNOWN with the reason
    attached, because the oracle has stated a window for the 3V3 domain only.

    Two properties are deliberate and were measured, not assumed:

    * **the LED's own facts are not required.** The verdict is the resistor's
      value, so an indicator LED with no shelf entry is still gradeable; the
      previous version was UNKNOWN for every LED without ``vf_v``/``if_max_ma``.
    * **the rule speaks only where the domain is known.** On the golden board
      the series resistor's far side is ``VCC`` -- a name that by itself is
      never guessed, and is 3.3 V here only because the RT9013-33GB's facts
      say so. Where nobody speaks for the rail, the verdict is UNKNOWN rather
      than a window applied to an invented voltage.

    Nothing in the rule is a *hazard* check: an out-of-window resistance is
    WARN (a BOM/design contradiction, the LED works or does not), while a LED
    with **no** series resistance at all is ERROR -- 0 ohm is a short across
    the rail, which is destructive rather than marginal.
    """

    id = "param-led-current"
    title = "An indicator LED's series resistance sits in the oracle's window"
    level = LEVEL
    source = (
        "oracle ruling (Yue, 2026-09-19): in the 3V3 domain an indicator "
        "LED's series resistance must sit in [470, 2200] ohm, judged by the "
        "resistance value (4.7k is the counter-example and violates); every "
        "other domain is UNKNOWN"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _leds(self, model: DesignModel) -> list[Component]:
        leds = []
        for comp in model.components.values():
            entry = self.entry_for(comp)
            if entry is not None and entry.category == "led":
                leds.append(comp)
                continue
            if "LED" in (comp.footprint or "").upper():
                leds.append(comp)
        return leds

    def _series_resistance(
        self, model: DesignModel, led: Component
    ) -> list[tuple[Component, float, str]]:
        """Resistors sharing a net with the LED, with their other-end nets.

        Resistors are identified by their value parsing as a resistance --
        **not** by the R designator prefix (the U3 lesson: an 0805 resistor
        lived under a U prefix)."""
        found: list[tuple[Component, float, str]] = []
        led_nets = {pin.net for pin in led.pins if pin.net}
        for comp in model.components.values():
            if comp.designator == led.designator:
                continue
            ohms = parse_resistance_ohms(comp.value or "")
            if ohms is None or ohms <= 0:
                continue
            nets = [pin.net for pin in comp.pins if pin.net]
            if not any(net in led_nets for net in nets):
                continue
            other = [net for net in nets if net not in led_nets]
            for net in other or nets:
                found.append((comp, ohms, net))
        return found

    def _supply_side(
        self,
        led: Component,
        resistors: list[tuple[Component, float, str]],
        guesses: dict,
    ) -> tuple[list[tuple[Component, float, str]], float | None, str]:
        """The series resistors on the supply side, and the rail behind them.

        A resistor counts when it shares a net with the LED **and** its far
        side sits on a net whose voltage somebody can name; that voltage is
        the domain the rule judges in. With no resistor at all the LED's own
        non-ground net is the supply side -- there is nothing in between, so
        "no series resistor" stays domain-gated instead of being assumed from
        the presence of two nets.

        Two silences that must not merge: *no resistor* (the LED sits straight
        across two nets) and *a resistor whose far side nobody names*. The
        first is graded as 0 ohm once the domain is known; the second is
        UNKNOWN, because summing an empty path would read as 0 ohm and report
        a missing resistor that is on the board.
        """
        path: list[tuple[Component, float, str]] = []
        volts: float | None = None
        net_name = ""
        for comp, ohms, net in resistors:
            value, _source, _why = domain_of(guesses, net)
            if value is None:
                continue
            path.append((comp, ohms, net))
            if volts is None:
                volts, net_name = value, net
        if path:
            return path, volts, net_name
        if resistors:
            return [], None, ""
        for pin in led.pins:
            if not pin.net or is_ground_net(pin.net):
                continue
            value, _source, _why = domain_of(guesses, pin.net)
            if value is not None:
                return [], value, pin.net
        return [], None, ""

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        low, high = LED_SERIES_BOUNDS_3V3
        window = f"[{low:g}, {high:g}] \u03a9"
        for led in self._leds(model):
            resistors = self._series_resistance(model, led)
            path, supply_volts, supply_net = self._supply_side(
                led, resistors, guesses
            )
            total = sum(ohms for _c, ohms, _n in path)
            evidence = [
                f"{led.designator} pins "
                + ", ".join(
                    f"{p.number}@{p.net or '(no net)'}" for p in led.pins
                ),
            ]
            if path:
                evidence.append(
                    "series resistance "
                    + "+".join(
                        f"{comp.designator}({ohms:.4g}\u03a9)" for comp, ohms, _n in path
                    )
                    + f" = {total:.4g} \u03a9"
                )
            if supply_volts is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: the oracle's window needs a "
                            "named supply voltage, and nothing names the rail "
                            "behind its series resistance"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"a known voltage on the far side of "
                            f"{led.designator}'s series resistor"
                            if resistors else
                            f"a known voltage on {led.designator}'s own nets"
                        ),
                    ),
                    None,
                ))
                continue
            if abs(supply_volts - LED_WINDOW_DOMAIN_V) > LED_DOMAIN_TOLERANCE_V:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: its series resistance sits on "
                            f"{supply_net!r} at {supply_volts:g} V, and the "
                            "oracle's window is stated for the 3.3 V domain "
                            "only"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"an oracle-approved series-resistance window for "
                            f"the {supply_volts:g} V domain"
                        ),
                    ),
                    None,
                ))
                continue
            if not path:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: no series resistor on its nets "
                            f"({supply_net!r} at {supply_volts:g} V) -- 0 \u03a9 is "
                            f"outside the oracle's window {window} for the "
                            "3.3 V domain, and nothing bounds the current"
                        ),
                        evidence=evidence,
                    ),
                    "ERROR",
                ))
                continue
            resistors_text = "+".join(
                f"{comp.designator}({ohms:.4g}\u03a9)" for comp, ohms, _n in path
            )
            # Quote the evidence that named the rail: the whole 011 family is
            # built on "who says so", and on the golden board the answer is an
            # LDO's facts rather than the net's own name.
            _volts, supply_source, _why_not = domain_of(guesses, supply_net)
            evidence.append(
                f"supply side {supply_net} = {supply_volts:g} V"
                + (f" per {supply_source}" if supply_source else "")
            )
            if low <= total <= high:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: series resistance "
                            f"{resistors_text} from {supply_net} "
                            f"({supply_volts:g} V) sits inside the oracle's "
                            f"window {window}"
                        ),
                        evidence=evidence,
                    ),
                    None,
                ))
            else:
                side = "below" if total < low else "above"
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: series resistance "
                            f"{resistors_text} from {supply_net} "
                            f"({supply_volts:g} V) is {side} the oracle's "
                            f"window {window} for the 3.3 V domain"
                        ),
                        evidence=evidence,
                    ),
                    "WARN",
                ))
        return rows



class DividerOutput(FactsRule):
    """PARAM-2: a resistor divider's tap voltage (with tolerance) fits the
    load pin's declared input range.

    The declared range comes from the load's shelf facts: its supply_pins
    record for that pin, whose ``v_operating`` is the datasheet's declared
    window for the pin. A load pin with no such record is UNKNOWN ("the load
    pin's range is undeclared") -- the rule never invents a window. Tolerance
    comes from the shelf's ``Tolerance`` parameter when it parses; without it
    the message says the spread is nominal-only."""

    id = "param-divider-output"
    title = "A divider's tap voltage fits the load pin's declared range"
    level = LEVEL
    source = (
        "the load part's own supply_pins v_operating facts; resistor "
        "tolerance from the shelf's Tolerance parameter"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _tolerance(self, comp: Component) -> float:
        """The part's fractional tolerance from its shelf params, or 0."""
        entry = self.entry_for(comp)
        if entry is None:
            return 0.0
        text = entry.params.get("Tolerance", "")
        digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        try:
            return float(digits) / 100.0 if digits else 0.0
        except ValueError:
            return 0.0

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        resistors: dict[str, tuple[Component, float]] = {}
        for comp in model.components.values():
            ohms = parse_resistance_ohms(comp.value or "")
            if ohms is not None and ohms > 0:
                resistors[comp.designator] = (comp, ohms)

        rows: list[tuple[Outcome, str | None]] = []
        seen_dividers: set[tuple[str, str]] = set()
        for upper_desig, (upper, r_up) in resistors.items():
            upper_nets = [p.net for p in upper.pins if p.net]
            for top_net in upper_nets:
                volts, source, _why = domain_of(guesses, top_net)
                if volts is None or is_ground_net(top_net):
                    continue
                for bottom_desig, (bottom, r_down) in resistors.items():
                    if bottom_desig == upper_desig:
                        continue
                    bottom_nets = [p.net for p in bottom.pins if p.net]
                    shared = [
                        net for net in bottom_nets
                        if net in upper_nets and not is_ground_net(net)
                    ]
                    grounded = [net for net in bottom_nets if is_ground_net(net)]
                    if not shared or not grounded:
                        continue
                    tap = shared[0]
                    key = tuple(sorted((upper_desig, bottom_desig)))
                    if key in seen_dividers:
                        continue
                    seen_dividers.add(key)
                    loads = [
                        (designator, pin)
                        for designator, pin in model.nets[tap].pins
                        if designator not in (upper_desig, bottom_desig)
                    ]
                    if not loads:
                        continue  # an unloaded divider has no declared range
                    self._check_tap(
                        rows, model, guesses, upper_desig, bottom_desig,
                        r_up, r_down, volts, source, tap, loads,
                    )
        if not seen_dividers:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject="divider survey",
                    message=(
                        "no resistor divider between a known domain and "
                        "ground was found on this board"
                    ),
                ),
                None,
            ))
        return rows

    def _check_tap(
        self, rows, model, guesses, upper_desig, bottom_desig,
        r_up, r_down, volts, source, tap, loads,
    ) -> None:
        v_tap = volts * r_down / (r_up + r_down)
        # Tolerance: both resistors' spreads act on the ratio; the honest
        # cheap bound is the sum of their fractional tolerances.
        tol_upper = self._tolerance(model.components[upper_desig])
        tol_bottom = self._tolerance(model.components[bottom_desig])
        spread = (tol_upper + tol_bottom) * volts * r_down * r_up / (
            (r_up + r_down) ** 2
        )
        v_lo, v_hi = v_tap - spread, v_tap + spread
        for load_desig, load_pin in loads:
            load = model.components.get(load_desig)
            if load is None:
                continue
            entry = self.entry_for(load)
            records = (entry.facts or {}).get("supply_pins", []) if entry else []
            declared = next(
                (
                    record.get("v_operating")
                    for record in records
                    if load_pin in [str(p) for p in record.get("pins", [])]
                    and record.get("v_operating")
                ),
                None,
            )
            evidence = [
                f"divider {upper_desig}/{bottom_desig}: tap {tap} = "
                f"{v_tap:.3g} V (spread ±{spread:.3g} V) from "
                f"{volts:.3g} V per {source}",
                f"load {load_desig} pin{load_pin}",
            ]
            if declared is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"{load_desig} pin{load_pin} is fed by the "
                            f"{upper_desig}/{bottom_desig} divider but "
                            "declares no input range in its facts"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"an input-range fact for {load_desig} "
                            f"pin{load_pin}"
                        ),
                    ),
                    None,
                ))
                continue
            lo, hi = declared
            if lo is None or hi is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"{load_desig} pin{load_pin}'s declared range "
                            f"[{lo}, {hi}] is one-sided, so the tap cannot "
                            "be judged against it"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"a two-sided input range for {load_desig} "
                            f"pin{load_pin}"
                        ),
                    ),
                    None,
                ))
                continue
            if v_lo < lo or v_hi > hi:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"the {upper_desig}/{bottom_desig} divider's tap "
                            f"{v_tap:.3g} V (spread ±{spread:.3g} V) leaves "
                            f"{load_desig} pin{load_pin}'s declared range "
                            f"[{lo}, {hi}]"
                        ),
                        evidence=evidence,
                    ),
                    "WARN",
                ))
            else:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"the {upper_desig}/{bottom_desig} divider's tap "
                            f"{v_tap:.3g} V fits {load_desig} "
                            f"pin{load_pin}'s declared range [{lo}, {hi}]"
                        ),
                        evidence=evidence,
                    ),
                    None,
                ))


class RcCutoff(FactsRule):
    """PARAM-3: report an RC network's -3 dB cutoff as a number (INFO).

    No requirement channel exists for "what the design needed", so the rule
    reports and refuses to grade -- an INFO that invents a pass/fail would be
    worse than silence. Topology recognised: a resistor and a capacitor in
    series between a net and ground (a low-pass to ground).

    **The number rides in the OK state, not in VIOLATION.** Until 011e the rows
    were emitted as ``VIOLATION`` and ``check()`` downgraded them to INFO, which
    made the four-state table lie: VIOLATION is the column the oracle reads as
    "the rules found something wrong", and a report-only measurement is not
    that. Measured on the graduation board: 11 of its VIOLATION cells were
    these numbers, and on an unannotated board every one of them landed in the
    harness's unexplained column and inflated the precision denominator. The
    state now says what is true -- a measurement was taken and nothing was
    violated -- and the finding channel stays exactly as it was (INFO), which
    is why ``check()`` keys off the row's severity hint rather than its state.
    """

    id = "param-rc-cutoff"
    title = "RC networks' -3 dB cutoff, reported as a number"
    level = LEVEL
    source = "house rule (report-only): fc = 1 / (2*pi*R*C)"

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        for outcome, severity in self._rows(model):
            # The severity hint is the "this row is a report" marker: the
            # survey row (no pair found) carries None and stays silent.
            if severity is None:
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=severity,
                    level=self.level,
                    message=outcome.message,
                    evidence=list(outcome.evidence),
                )
            )
        return findings

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        pairs: list[tuple[Component, float, Component, float, str]] = []
        resistors: dict[str, float] = {}
        capacitors: dict[str, float] = {}
        for comp in model.components.values():
            ohms = parse_resistance_ohms(comp.value or "")
            if ohms is not None and ohms > 0:
                resistors[comp.designator] = ohms
            farads = parse_capacitance_farads(comp.value or "")
            if farads is not None:
                capacitors[comp.designator] = farads
        seen: set[tuple[str, str]] = set()
        for r_desig, ohms in resistors.items():
            r_nets = [
                p.net for p in model.components[r_desig].pins if p.net
            ]
            for c_desig, farads in capacitors.items():
                if c_desig == r_desig:
                    continue
                key = tuple(sorted((r_desig, c_desig)))
                if key in seen:
                    continue
                c_nets = [
                    p.net for p in model.components[c_desig].pins if p.net
                ]
                shared = [
                    net for net in c_nets
                    if net in r_nets and not is_ground_net(net)
                ]
                capped = [net for net in c_nets if is_ground_net(net)]
                if not shared or not capped:
                    continue
                # A pair sharing a *known supply rail* is decoupling, not a
                # signal low-pass (the golden board's U3+C6 on VCC): the RC
                # rule would otherwise file every decoupling cap as a
                # "filter" and drown the report.
                if any(domain_of(guesses, net)[0] is not None for net in shared):
                    continue
                seen.add(key)
                pairs.append((
                    model.components[r_desig], ohms,
                    model.components[c_desig], farads, shared[0],
                ))
        rows: list[tuple[Outcome, str | None]] = []
        if not pairs:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject="RC survey",
                    message=(
                        "no resistor-to-ground capacitor pair (RC low-pass "
                        "topology) was found on this board"
                    ),
                ),
                None,
            ))
        for r_comp, ohms, c_comp, farads, net in pairs:
            fc = 1.0 / (2.0 * math.pi * ohms * farads)
            text = f"{fc:,.0f} Hz" if fc >= 1 else f"{fc:.3g} Hz"
            rows.append((
                Outcome(
                    rule_id=self.id,
                    # OK, not VIOLATION: a measurement is not a fault (011e
                    # sec.1.1). The finding this row still produces is INFO.
                    state="OK",
                    subject=f"{r_comp.designator}/{c_comp.designator}",
                    message=(
                        f"RC {r_comp.designator}({ohms:.4g}Ω) + "
                        f"{c_comp.designator}({c_comp.value}) on {net!r}: "
                        f"fc = {text} (-3 dB cutoff; reported, not graded -- "
                        "no requirement channel exists)"
                    ),
                    evidence=[
                        f"{r_comp.designator} value {r_comp.value!r}",
                        f"{c_comp.designator} value {c_comp.value!r}",
                    ],
                ),
                "INFO",
            ))
        return rows
