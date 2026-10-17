"""L1 connectivity rules.

All rules in this module are heuristics over the normalized netlist model.
They look at value strings, declarations and net membership — no schematic
geometry, no datasheet knowledge. Each finding message states the heuristic's
limits so readers can judge how much to trust it.

**Which parts count as what is not this module's own table any more (190).**
The rules that have to decide 「is this an IC / a capacitor / a resistor?」
ask :func:`boardwise.core.partkind.classify_part`, the same entry point
``rules/facts``, ``rules/sensebias`` and the PCB rules read — 岳 2026-10-16 ⑦
was the measured cost of a `U`-prefix test disagreeing with what the part's own
declaration says (three 330 kΩ resistors at `U` designators each asked for a
decoupling capacitor).

**The shelf goes in with the reading** (192B ②): the rules that ask that
question now hand over the same
:func:`boardwise.rules.facts.read_default_library` shelf the PCB-side readers
use (:func:`default_shelf`), because *not* handing it over is what made this
module answer 「connector」 about a part the shelf had already classified
``ic.usb-uart`` — two readings of one question, one holding the shelf and one
not. What stays this module's own contract is the **evidence**: no geometry, no
datasheet, and each finding still says which basis decided which side.
"""

from __future__ import annotations

import re

from ..core.model import Component, DesignModel, is_ground_net
from ..core.partkind import KIND_CAPACITOR, KIND_IC, KIND_RESISTOR, classify_part
from .base import Finding, Outcome, OutcomeRule, Rule

LEVEL = "L1-connectivity"


def parse_resistance_ohms(value: str) -> float | None:
    """Re-exported: the one ohm parser lives in ``rules/values.py`` (071 §2).

    It used to live here, with the trade's mid-letter notation (``4K7``)
    missing — so a board value written that way was None, and every rule reading
    a resistance skipped the part instead of judging it. The grammar now sits
    beside the MPN decoder that already knew the notation, and this function
    stays as the import path every caller already uses.
    """
    from .values import parse_resistance_ohms as _parse

    return _parse(value)


def default_shelf():
    """The project's own shelf, for this module's 判型 reads (192B ②).

    Read at **call time** from :func:`boardwise.rules.facts.read_default_library`
    (the one resolver every facts-reading rule shares: the user shelf when the
    tool is frozen, ``blocklib/parts.json`` in a checkout), and returned as
    ``None`` when it cannot be read — a shelfless reading is a narrower one, never
    an exception raised out of a rule.

    Why the L1 rules read a shelf at all: 190 put every 「what is this part?」 on
    one entry point, and an entry point whose strongest input is missing at two of
    its call sites answers a different question there. ``DecouplingPerIC`` was the
    measured case (see its docstring).
    """
    from .facts import read_default_library

    try:
        return read_default_library()
    except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
        return None


def _pin_net_evidence(comp: Component) -> list[str]:
    return [
        f"{comp.designator} pin{pin.number} @ {pin.net}"
        for pin in comp.pins
        if pin.net is not None
    ]


class DecouplingPerIC(Rule):
    """Every IC should share at least one pin net with a capacitor.

    **Both halves of the sentence are judged by the shared 判型 entry point**
    (:func:`boardwise.core.partkind.classify_part`), not by a designator letter
    (190, 岳 2026-10-16 ⑦). Until 190 this rule was the ``U``/``C`` prefix test
    its own message apologised for — 「matches designator prefixes only (U*/C*),
    any C-prefixed part (including connectors) counts as a capacitor」 — and the
    measured cost was on 实板A: three ``U``-designated 330 kΩ chip resistors
    (``FRC1206J334 TS``) were each asked for a decoupling capacitor because
    nothing else could be read about them. What decides now:

    * **an IC** is a part the reading calls one (:data:`KIND_IC`) — a
      declaration (shelf category, 立创 metadata, the part's own name/footprint
      words) when there is one, and otherwise the designator's own family with
      the 3-pin floor applied (a two-pin part is never asked for a bypass
      capacitor — 127b's necessary condition, reused rather than re-argued);
    * **a capacitor** is a part the same reading calls one (:data:`KIND_CAPACITOR`),
      so a ``C``-designated connector stops counting and a capacitor declared by
      metadata counts wherever it is placed.

    **The shelf goes in** (192B ②). Until this batch the two reads above were
    made **without** a library — 「this module's contract is the netlist」 — and
    the measured cost was that this rule and the PCB facts rules answered
    differently about *one* part: ``超声波``'s ``U2`` (``USB2.0芯片CH340``, shelf
    category ``ic.usb-uart``) was an IC to ``rules/pcb/distance`` and to
    ``rules/facts``, and a **connector** here, so 「no decoupling capacitor near
    this IC」 was never asked about the one part on that board the shelf knew.
    Two readers of the same question, one of them holding the shelf and one not,
    is the 口径 split 190 exists to collapse; the shelf is the same
    :func:`boardwise.rules.facts.read_default_library` every other facts reader
    uses, and it is read **once** per rule run. A shelf that cannot be read
    degrades to the old shelfless reading rather than raising (the same
    discipline ``rules/pcb/distance.device_facts`` applies), and the finding still
    names the basis each side was read on.
    """

    id = "decoupling-per-ic"
    title = "Each IC should share at least one net with a decoupling capacitor"
    level = LEVEL
    source = ""

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        library = default_shelf()
        cap_nets: set[str] = set()
        capacitor_count = 0
        for comp in model.components.values():
            if classify_part(comp, library=library).kind != KIND_CAPACITOR:
                continue
            capacitor_count += 1
            cap_nets |= {
                pin.net for pin in comp.pins if pin.net is not None
            }
        for comp in model.components.values():
            read = classify_part(comp, library=library)
            if read.kind != KIND_IC:
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
                        "capacitor. Heuristic limits: both halves of the "
                        "judgement are the shared part-kind reading — an IC is "
                        "a part that reading calls one, a capacitor is a part it "
                        "calls one — so a two-pin part is never asked (127b's "
                        "pin floor) and a declaration wins over the designator "
                        "letter in both directions (a 330 kΩ resistor at a U "
                        "designator is not an IC; a connector at a C designator "
                        "is not a capacitor). Supply pins still cannot be told "
                        "from signal pins here."
                    ),
                    evidence=_pin_net_evidence(comp)
                    + [
                        f"part-kind reading: {read.kind} (basis {read.basis or 'none'}"
                        f" — {read.reason})",
                        f"capacitors counted on this board: {capacitor_count}",
                    ],
                )
            )
        return findings


class DuplicateDesignators(OutcomeRule):
    """CONN-1 (task 011c): one designator must mean exactly one part.

    Three kinds of repeat, and 040b makes the parser tell them apart (the 毕设
    project is the worked example: 3 boards, 30 refs, of which 28 are one name on
    two or three boards and 2 — U15, U16 — repeat *within* one page):

    * **twice on one page** — two parts answer to one name inside one netlist.
      ``model.duplicate_designators``.
    * **once on each of two pages of one board** — one design drawn across
      sheets, so the name still resolves to two parts in one netlist.
      ``model.cross_page_designators``.
    * **on more than one board** — ``model.cross_board_designators`` says which
      boards, and the first one listed reports it, so a project-scoped claim is
      made once instead of once per board.

    All three are ERROR, which is the oracle's A1 ruling (2026-09-19) unchanged:
    "the netlist, the BOM and the layout are all PROJECT-scoped, so two different
    parts answer to one name". 040 left a switch here
    (``CROSS_PAGE_REPEAT_IS_A_DEFECT``) because it could not tell the second kind
    from the third; now that it can, the switch has no reading left to guard and
    is gone. What 040b adds is not a verdict but a *subject*: the message says
    which board(s) the name spans, so "same board, another sheet" and "another
    board" read differently.

    **Which placement the model keeps (049, measured: first).** One name cannot
    hold two placements, so the model picks one — and since 049 it keeps the
    **first** one in the document. The copper layer is what decided it: on the
    thesis-FOC board both U15 and U16 are placed twice on one page, and the
    *first* placement's pins are the ones the PCB agrees with (U15's V+ on VCCA
    with its 100nF return, VEE/GND on AGND), while the later copy leaves those
    power pins unwired. The rule therefore says so in the message, because a
    reader who cannot tell which placement the netlist describes cannot use it.
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
            findings.append(self.finding_from_row(outcome, severity))
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
                        "one page; the model kept the first placement"
                    ),
                    evidence=[f"duplicate designator {designator}"],
                ),
                "ERROR",
            ))
        for designator, pages in sorted(model.cross_page_designators.items()):
            # An empty page list is what a consumer states when it knows a name
            # is on more than one page but cannot name them (the per-page tier
            # merging hand-built models). Say that, rather than "0 pages".
            where = "、".join(page[:8] for page in pages)
            if pages:
                message = (
                    f"{designator} is placed once on each of {len(pages)} pages "
                    f"of one board ({where}); one netlist holds the name twice, "
                    "so the model kept the first placement"
                )
                evidence = [
                    f"designator {designator} on {len(pages)} pages: "
                    + ", ".join(pages)
                ]
            else:
                message = (
                    f"{designator} is placed on more than one page of one board "
                    "(page ids unavailable in this reading); one netlist holds "
                    "the name twice"
                )
                evidence = [f"designator {designator} on more than one page"]
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=designator,
                    message=message,
                    evidence=evidence,
                ),
                "ERROR",
            ))
        for designator, titles in sorted(
            getattr(model, "cross_board_designators", {}).items()
        ):
            # One report per name, from the first board that carries it: the
            # claim is project-scoped, so repeating it on every board would make
            # one defect look like three.
            board = getattr(model, "board", None)
            if titles and board is not None and titles[0] != board.title:
                continue
            where = "、".join(titles)
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=designator,
                    message=(
                        f"{designator} is placed on more than one board ({where}); "
                        "the project's netlist, BOM and layout share one name for "
                        "two parts (oracle ruling A1, 2026-09-19)"
                    ),
                    evidence=[
                        f"designator {designator} on boards: " + ", ".join(titles)
                    ],
                ),
                "ERROR",
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

    Smoke check only: passes if *some* IC-classified component has pins on both
    terminal nets of the shunt. Series resistors / filter networks between
    shunt and IC are invisible at L1 and produce an INFO, not a WARN.

    **Both halves are the shared part-kind reading** (190): the shunt is a part
    :func:`boardwise.core.partkind.classify_part` calls a resistor, and the IC is
    one it calls an IC — not an ``R``/``U`` designator letter. The ohms test
    below is a different question and stays here: whether a *resistor* is a
    milliohm **shunt** is what its value says.

    The 50 mΩ ceiling names the *differential* shunt domain, and its distance
    from ``path-sampling-bias``'s 0.5 Ω (176) is a boundary between two
    questions, not a hole: a milliohm shunt in a high-current path is read by
    a sense amplifier across both terminals — the architecture the
    both-terminal-nets check above smokes for — while a larger series resistor
    (ROBOT's 100 mΩ phase shunts are the measured case) is read single-ended
    into an ADC pin, which is ``path-sampling-bias``'s territory, and that
    rule does file those. Raising this ceiling to meet that one would sweep
    every low-value series resistor into a differential question it is not
    asking, as INFO noise.
    """

    id = "shunt-sense-link"
    title = "Shunt resistors should reach a current-sense input on an IC"
    level = LEVEL
    source = ""

    #: Upper bound for "milliohm-level" shunts, in milliohms.
    max_shunt_milliohms = 50.0

    def _is_shunt(self, comp: Component) -> bool:
        if classify_part(comp).kind != KIND_RESISTOR:
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
            if classify_part(comp).kind == KIND_IC
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
                            f"{comp.designator} ({comp.value}): no IC has pins on "
                            f"**both** of its terminal nets {terminals[0]} / "
                            f"{terminals[1]} — an IC pin on one end alone is not "
                            "the sense link this rule smokes for. L1 capability "
                            "boundary: the link may run through series resistors "
                            "or a filter network, which a connectivity-only check "
                            "cannot see."
                        ),
                        evidence=_pin_net_evidence(comp),
                    )
                )
        return findings
