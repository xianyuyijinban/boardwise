"""L1 connectivity rules.

All rules in this module are heuristics over the normalized netlist model.
They look at designator prefixes, value strings and net membership only —
no schematic geometry, no datasheet knowledge. Each finding message states
the heuristic's limits so readers can judge how much to trust it.
"""

from __future__ import annotations

import re

from ..core.model import Component, DesignModel, is_ground_net
from .base import Finding, Outcome, OutcomeRule, Rule

LEVEL = "L1-connectivity"


def parse_resistance_ohms(value: str) -> float | None:
    """Tolerantly parse a resistor value string into ohms.

    Accepted forms include ``"10mΩ"`` (0.01), ``"1mΩ"`` (0.001),
    ``"0.01"`` (0.01), ``"0R01"`` / ``"4R7"`` (R as decimal separator),
    ``"R010"`` (0.01), ``"10kΩ"`` / ``"10K"`` (1e4), ``"1MΩ"`` (1e6),
    ``"10Ω"`` / ``"10 ohm"`` (10). Returns None when unparseable.
    """
    s = value.strip()
    if not s:
        return None
    # Drop unit suffixes: Ω, ohm, ohms (any case).
    s = re.sub(r"(?i)\s*(?:ohms?|Ω)\s*$", "", s).strip()
    if not s:
        return None
    # "0R01" / "4R7": R acts as the decimal separator.
    m = re.fullmatch(r"(\d+)[Rr](\d+)", s)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    # "R010": leading R means 0.xxx.
    m = re.fullmatch(r"[Rr](\d+)", s)
    if m:
        return float(f"0.{m.group(1)}")
    # Plain number with an optional k/m/M multiplier suffix.
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM]?)", s)
    if not m:
        return None
    multiplier = {"": 1.0, "k": 1e3, "K": 1e3, "m": 1e-3, "M": 1e6}[m.group(2)]
    return float(m.group(1)) * multiplier


def _nets_with_prefix(model: DesignModel, prefix: str) -> set[str]:
    """Names of nets that contain at least one member with that designator prefix."""
    return {
        net.name
        for net in model.nets.values()
        if any(designator.startswith(prefix) for designator, _ in net.pins)
    }


def _pin_net_evidence(comp: Component) -> list[str]:
    return [
        f"{comp.designator} pin{pin.number} @ {pin.net}"
        for pin in comp.pins
        if pin.net is not None
    ]


class DecouplingPerIC(Rule):
    """Every IC (``U`` prefix) should share at least one pin net with a capacitor."""

    id = "decoupling-per-ic"
    title = "Each IC should share at least one net with a decoupling capacitor"
    level = LEVEL
    source = ""

    ic_prefix = "U"
    capacitor_prefix = "C"

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        cap_nets = _nets_with_prefix(model, self.capacitor_prefix)
        for comp in model.components.values():
            if not comp.designator.startswith(self.ic_prefix):
                continue
            pin_nets = {
                pin.net
                for pin in comp.pins
                if pin.net is not None and not is_ground_net(pin.net)
            }
            if pin_nets & cap_nets:
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="WARN",
                    level=self.level,
                    message=(
                        f"{comp.designator}: none of its pin nets contains a "
                        "capacitor. Heuristic limits: matches designator "
                        "prefixes only (U*/C*), cannot tell supply pins from "
                        "signal pins, and any C-prefixed part (including "
                        "connectors) counts as a capacitor."
                    ),
                    evidence=_pin_net_evidence(comp),
                )
            )
        return findings


#: Does a designator repeated **across pages** count as a defect?
#:
#: True = the two signed rulings stand: oracle A1 (2026-09-19) ruled the 毕设
#: board's 30 cross-page repeats ERROR defects ("the netlist, the BOM and the
#: layout are all PROJECT-scoped, so two different parts answer to one name"),
#: and the injected ``duplicate-designator`` variant (011d, signed the same day)
#: *is* a cross-page repeat by construction ("a second page carries a second
#: R24") whose record demands severity ERROR.
#:
#: False = 040 §WI-3's reading, that a multi-board project numbers each board's
#: own parts so a repeat across pages is legitimate. 040 implemented the
#: *distinction* (the model now says which kind a repeat is) but left this True:
#: flipping it would overturn an oracle ruling the task book did not cite, drop
#: the eval's high-priority precision 0.97 -> 0.88 and the injected variant's
#: only defect with it. The measured cost of False is in
#: ``outputs/040_summary.txt``; the flip is this one word and is the oracle's
#: call, not the parser's.
CROSS_PAGE_REPEAT_IS_A_DEFECT = True


class DuplicateDesignators(OutcomeRule):
    """CONN-1 (task 011c): one designator must mean exactly one part.

    Two kinds of repeat, and 040 §WI-3 made the parser tell them apart (on the
    毕设 board: 30 refs repeat across 3 pages that are three boards; two of them,
    U15/U16, repeat *within* one page):

    * **twice on one page** — two parts answer to one name inside one netlist,
      which is what binds BOM, layout and review together. The parser records
      these in ``model.duplicate_designators``.
    * **once each on two pages** — either a multi-board project numbering each
      board's own ``R1``, or one design drawn across subsheets. The parser
      records these in ``model.cross_page_designators``, with the pages.

    Both are reported, and the message says which kind it is and on which pages
    — the reading is no longer "somewhere, twice". Whether the second kind is a
    defect is a ruling, not a parser question: see
    :data:`CROSS_PAGE_REPEAT_IS_A_DEFECT` (True today, on oracle A1 plus the
    signed injected variant).
    """

    id = "conn-duplicate-designators"
    title = "Designators must be unique across the whole project"
    level = LEVEL
    source = "house rule; the parser records the clashes (011c sec.3.2, 040 §WI-3)"

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _severity in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        for outcome, severity in self._rows(model):
            # The severity hint is the row's kind marker (same idiom as
            # RcCutoff): None means "this row is not a report" -- the clean
            # board's single OK row.
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
        rows: list[tuple[Outcome, str | None]] = []
        for designator in model.duplicate_designators:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=designator,
                    message=(
                        f"{designator} is used by more than one placed part on "
                        "one page; the model kept only the last placement"
                    ),
                    evidence=[f"duplicate designator {designator}"],
                ),
                "ERROR",
            ))
        for designator, pages in sorted(model.cross_page_designators.items()):
            where = "、".join(page[:8] for page in pages)
            defect = CROSS_PAGE_REPEAT_IS_A_DEFECT
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION" if defect else "OK",
                    subject=designator,
                    message=(
                        f"{designator} is placed once on each of {len(pages)} "
                        f"pages ({where}) -- "
                        + (
                            "every board of a multi-board project numbers its own "
                            "parts, so this is reported, not graded"
                            if not defect else
                            "the model kept only the last placement, and a "
                            "project-scoped netlist/BOM cannot hold one name for "
                            "two parts"
                        )
                    ),
                    evidence=[
                        f"designator {designator} on {len(pages)} pages: "
                        + ", ".join(pages)
                    ],
                ),
                "ERROR" if defect else "INFO",
            ))
        if not rows:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject="designator uniqueness",
                    message=(
                        f"all {len(model.components)} designators are unique "
                        "across the parsed pages"
                    ),
                ),
                None,
            ))
        return rows


class CrystalLoadCaps(Rule):
    """Each crystal pin net should hold a capacitor whose other end is grounded."""

    id = "xtal-load-caps"
    title = "Crystal pins should each see a load capacitor to ground"
    level = LEVEL
    source = ""

    crystal_prefixes = ("X", "Y")
    capacitor_prefix = "C"
    frequency_pattern = re.compile(r"(mhz|khz)", re.IGNORECASE)

    def _is_crystal(self, comp: Component) -> bool:
        if comp.designator[:1] in self.crystal_prefixes:
            return True
        return bool(self.frequency_pattern.search(comp.value or ""))

    def _has_grounded_cap(self, model: DesignModel, net_name: str) -> bool:
        net = model.nets.get(net_name)
        if net is None:
            return False
        for designator, _ in net.pins:
            if not designator.startswith(self.capacitor_prefix):
                continue
            candidate = model.components[designator]
            for pin in candidate.pins:
                if pin.net != net_name and is_ground_net(pin.net):
                    return True
        return False

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        for comp in model.components.values():
            if not self._is_crystal(comp):
                continue
            pin_nets = sorted(
                {
                    pin.net
                    for pin in comp.pins
                    if pin.net is not None and not is_ground_net(pin.net)
                }
            )
            # Pins already sitting on ground are skipped outright: a 4-pad
            # crystal's case pads (X1 pins 2/4) live on GND, and demanding a
            # grounded capacitor on the ground net itself cannot succeed by
            # construction — the false positive 011a measured and 011c
            # sec.3.3 rules must be skipped, not annotated away.
            missing = [
                net for net in pin_nets if not self._has_grounded_cap(model, net)
            ]
            if missing:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="WARN",
                        level=self.level,
                        message=(
                            f"{comp.designator}: no grounded capacitor found on "
                            f"net(s) {', '.join(missing)}. Heuristic limits: "
                            "crystals are detected by X/Y designator or a "
                            "MHz/KHz value string; any C-prefixed part counts "
                            "as a capacitor and its value is not checked."
                        ),
                        evidence=_pin_net_evidence(comp),
                    )
                )
        return findings


class ShuntSenseLink(Rule):
    """Milliohm shunt resistors should connect to an IC's sense pins.

    Smoke check only: passes if *some* U-prefixed component has pins on both
    terminal nets of the shunt. Series resistors / filter networks between
    shunt and IC are invisible at L1 and produce an INFO, not a WARN.
    """

    id = "shunt-sense-link"
    title = "Shunt resistors should reach a current-sense input on an IC"
    level = LEVEL
    source = ""

    resistor_prefix = "R"
    ic_prefix = "U"
    #: Upper bound for "milliohm-level" shunts, in milliohms.
    max_shunt_milliohms = 50.0

    def _is_shunt(self, comp: Component) -> bool:
        if not comp.designator.startswith(self.resistor_prefix):
            return False
        ohms = parse_resistance_ohms(comp.value or "")
        if ohms is None or ohms <= 0:  # 0Ω jumpers are not sense shunts
            return False
        return ohms * 1000.0 <= self.max_shunt_milliohms

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        ics = [
            comp
            for comp in model.components.values()
            if comp.designator.startswith(self.ic_prefix)
        ]
        for comp in model.components.values():
            if not self._is_shunt(comp):
                continue
            terminals = sorted(
                {pin.net for pin in comp.pins if pin.net is not None}
            )
            if len(terminals) != 2:
                continue
            linked = any(
                all(
                    any(pin.net == net for pin in ic.pins)
                    for net in terminals
                )
                for ic in ics
            )
            if not linked:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="INFO",
                        level=self.level,
                        message=(
                            f"{comp.designator} ({comp.value}): no IC pins found "
                            f"on its terminal nets {terminals[0]} / {terminals[1]}. "
                            "L1 capability boundary: the sense link may run "
                            "through series resistors or a filter network, "
                            "which a connectivity-only check cannot see."
                        ),
                        evidence=_pin_net_evidence(comp),
                    )
                )
        return findings
