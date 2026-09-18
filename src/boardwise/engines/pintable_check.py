"""Pin-table checking (task 008c, work item 2) — three gates, all fail-closed.

The firmware pin table (``core/pintable.py``) is a *claim* about the board. This
module is what makes the claim checkable, and it is the first of 008c's four
verifiers to be written because the other three all take a pin table as input.

The three gates are the task book's, verbatim:

1. **the MCU block's symbol has the pin.** ``offsets`` on the MCU template's
   symbol is measured geometry — it lists the pin numbers the library symbol
   actually exposes. A table naming a pin the symbol does not have would draw a
   wire into thin air, so it is refused before anything is assembled. (The
   "ghost pin number" negative case.)
2. **one pin, one row.** A number appearing twice is two contradictory claims
   about one ball of silicon; the later row would silently win. (The "one pin
   under two names" negative case.)
3. **the two-way difference against the spec.** Firmware uses a pin the
   schematic does not connect ⇒ **defect**. The schematic connects a signal port
   to the MCU block the firmware never mentions ⇒ **open question**, listed
   separately: the board may legitimately have a pin the firmware has not grown
   into yet, and calling that a defect would make the checker wrong about real
   boards. The vocabulary check is a fourth gate implied by the contract: an
   unknown ``function`` is already refused at load time.

Nothing here compares against the golden ``.epro2``: the pin table is a
*generation-side* artifact, so the answer may not be consulted (008c's closed-book
rule, enforced by the spec verifier's first gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.blocks import BlockTemplate, BoardSpec
from ..core.pintable import PinTable

#: How a finding is classified. The split is the task book's, and it carries the
#: *judgement*: a defect blocks, an open question does not but must be printed.
DEFECT = "defect"
OPEN_QUESTION = "open-question"
NOTE = "note"


@dataclass
class PinFinding:
    """One result of checking a pin table."""

    kind: str  # 'defect' | 'open-question' | 'note'
    rule: str  # which gate
    message: str
    evidence: list[str] = field(default_factory=list)

    @property
    def is_defect(self) -> bool:
        return self.kind == DEFECT

    def render(self) -> str:
        where = f" ({'; '.join(self.evidence)})" if self.evidence else ""
        return f"[{self.kind}] {self.rule}: {self.message}{where}"


@dataclass
class PinReport:
    """Everything the three gates had to say about one pin table."""

    findings: list[PinFinding] = field(default_factory=list)
    #: Counts, so a caller can print a one-line verdict without re-walking.
    checked_pins: int = 0
    matched_nets: int = 0

    @property
    def defects(self) -> list[PinFinding]:
        return [f for f in self.findings if f.kind == DEFECT]

    @property
    def open_questions(self) -> list[PinFinding]:
        return [f for f in self.findings if f.kind == OPEN_QUESTION]

    @property
    def notes(self) -> list[PinFinding]:
        return [f for f in self.findings if f.kind == NOTE]

    @property
    def ok(self) -> bool:
        """True when nothing blocks. Open questions do **not** block."""
        return not self.defects

    def render(self) -> list[str]:
        lines = [
            f"pin table check: {self.checked_pins} pin(s) checked, "
            f"{self.matched_nets} net(s) matched against the spec, "
            f"{len(self.defects)} defect(s), "
            f"{len(self.open_questions)} open question(s)"
        ]
        lines.extend(f"  {finding.render()}" for finding in self.findings)
        return lines

    def as_json(self) -> dict[str, object]:
        return {
            "checked_pins": self.checked_pins,
            "matched_nets": self.matched_nets,
            "ok": self.ok,
            "defects": [
                {"rule": f.rule, "message": f.message, "evidence": f.evidence}
                for f in self.defects
            ],
            "open_questions": [
                {"rule": f.rule, "message": f.message, "evidence": f.evidence}
                for f in self.open_questions
            ],
            "notes": [
                {"rule": f.rule, "message": f.message, "evidence": f.evidence}
                for f in self.notes
            ],
        }


def _mcu_pin_numbers(
    template: BlockTemplate, component_ref: str
) -> tuple[set[str], str]:
    """``(pin numbers, why-not)`` for one component's symbol.

    Returns the empty set and a reason when the component is not there or its
    symbol carries no pins — the caller turns "why-not" into a *note*, never into
    a pass: a check that could not run must not read as a check that passed.
    """
    component = next((c for c in template.components if c.ref == component_ref), None)
    if component is None:
        return set(), (
            f"block {template.name!r} has no component {component_ref!r}, so there "
            "is no symbol to check pin numbers against"
        )
    symbol = template.symbols.get(component.symbol)
    if symbol is None:
        return set(), (
            f"component {component_ref!r} names symbol {component.symbol!r}, which "
            "is not in the block"
        )
    if not symbol.offsets:
        return set(), (
            f"symbol {component.symbol!r} of {component_ref!r} has no pin offsets, "
            "so it cannot say which pin numbers exist"
        )
    return set(symbol.offsets), ""


def check_pin_table(
    table: PinTable,
    *,
    mcu_block: BlockTemplate | None = None,
    mcu_component: str = "",
    spec: BoardSpec | None = None,
    mcu_block_id: str = "",
) -> PinReport:
    """Run the three gates over one pin table.

    ``mcu_block`` + ``mcu_component`` enable gate 1; ``spec`` + ``mcu_block_id``
    enable gate 3. Each is optional so the gates can be exercised separately,
    and a gate that could not run says so in a note rather than staying silent.
    """
    report = PinReport(checked_pins=len(table.pins))
    wired = table.numbers()

    # ---- gate 1: the pin numbers exist on the MCU block's symbol
    if mcu_block is not None:
        if not mcu_component:
            report.findings.append(
                PinFinding(
                    kind=NOTE,
                    rule="pin-numbers-exist",
                    message=(
                        "no MCU component was named, so the pin numbers were not "
                        "checked against a symbol — this is *not* a pass"
                    ),
                )
            )
        else:
            numbers, why_not = _mcu_pin_numbers(mcu_block, mcu_component)
            if why_not:
                report.findings.append(
                    PinFinding(kind=NOTE, rule="pin-numbers-exist", message=why_not)
                )
            else:
                known = len(numbers)
                ghosts = sorted(
                    pin.number for pin in table.pins if pin.number not in numbers
                )
                for number in ghosts:
                    pin = next(p for p in table.pins if p.number == number)
                    report.findings.append(
                        PinFinding(
                            kind=DEFECT,
                            rule="pin-numbers-exist",
                            message=(
                                f"pin {number} is not on the symbol of "
                                f"{mcu_component} — the block's {known} pin number(s) "
                                "are the evidence for which pins exist, and this is "
                                "not one of them"
                            ),
                            evidence=[f"{number} as {pin.function} on {pin.net!r}"],
                        )
                    )
                report.findings.append(
                    PinFinding(
                        kind=NOTE,
                        rule="pin-numbers-exist",
                        message=(
                            f"checked {len(table.pins)} pin number(s) against "
                            f"{mcu_component}'s {known} symbol pin(s)"
                        ),
                    )
                )
    else:
        report.findings.append(
            PinFinding(
                kind=NOTE,
                rule="pin-numbers-exist",
                message=(
                    "no MCU block was supplied, so the pin numbers were not checked "
                    "against a symbol — this is *not* a pass"
                ),
            )
        )

    # ---- gate 2: one pin number, one row
    seen: dict[str, int] = {}
    for order, pin in enumerate(table.pins):
        if pin.number in seen:
            first = table.pins[seen[pin.number]]
            report.findings.append(
                PinFinding(
                    kind=DEFECT,
                    rule="one-pin-one-row",
                    message=(
                        f"pin {pin.number} appears twice — as {pin.function} on "
                        f"{pin.net!r} and as {first.function} on {first.net!r}; the "
                        "second row would silently win, so neither is believed"
                    ),
                    evidence=[
                        f"row {seen[pin.number]}: {first.function}/{first.net}",
                        f"row {order}: {pin.function}/{pin.net}",
                    ],
                )
            )
        else:
            seen[pin.number] = order

    # ---- gate 3: the two-way difference against the spec
    if spec is None or not mcu_block_id:
        report.findings.append(
            PinFinding(
                kind=NOTE,
                rule="spec-difference",
                message=(
                    "no spec (or no MCU block id) was supplied, so the firmware's "
                    "nets were not compared against the connections — this is *not* "
                    "a pass"
                ),
            )
        )
    else:
        instance = spec.instance(mcu_block_id)
        if instance is None:
            report.findings.append(
                PinFinding(
                    kind=NOTE,
                    rule="spec-difference",
                    message=(
                        f"the spec has no block {mcu_block_id!r}, so there is nothing "
                        "to compare the pin table against"
                    ),
                )
            )
        else:
            # Direction 1: firmware named a net the spec never connects.
            spec_nets = {connection.net for connection in spec.connections}
            unnamed = [pin for pin in table.pins if not pin.net]
            for pin in unnamed:
                report.findings.append(
                    PinFinding(
                        kind=DEFECT,
                        rule="spec-difference",
                        message=(
                            f"firmware uses pin {pin.number} as {pin.function} but "
                            "names no net, so the schematic cannot have connected it"
                        ),
                        evidence=[f"{pin.number} {pin.function}"],
                    )
                )
            for net in sorted(table.nets()):
                if net not in spec_nets:
                    pins = sorted(p.number for p in table.pins if p.net == net)
                    report.findings.append(
                        PinFinding(
                            kind=DEFECT,
                            rule="spec-difference",
                            message=(
                                f"firmware puts {', '.join(pins)} on net {net!r}, "
                                "which the spec never connects — the firmware uses a "
                                "pin the schematic does not wire"
                            ),
                            evidence=[f"net {net}"],
                        )
                    )
                else:
                    report.matched_nets += 1
            # Direction 2: the spec connects a signal port the firmware never named.
            mcu_ports = {
                role: port for role, port in _ports_on(instance.template)
            }
            spec_signal_nets: dict[str, list[str]] = {}
            for connection in spec.connections:
                for block_id, role in connection.ports:
                    if block_id != mcu_block_id:
                        continue
                    port = mcu_ports.get(role)
                    if port is None or port.net_class != "signal":
                        continue
                    spec_signal_nets.setdefault(connection.net, []).append(role)
            firmware_nets = table.nets()
            for net in sorted(spec_signal_nets):
                if net in firmware_nets:
                    continue
                report.findings.append(
                    PinFinding(
                        kind=OPEN_QUESTION,
                        rule="spec-difference",
                        message=(
                            f"the spec connects the MCU block's port(s) "
                            f"{', '.join(sorted(spec_signal_nets[net]))} to net "
                            f"{net!r}, but the firmware pin table never uses it — "
                            "either the firmware has not grown into that pin yet or "
                            "the pin table is incomplete"
                        ),
                        evidence=[f"net {net}"],
                    )
                )

    return report


def _ports_on(template: BlockTemplate):
    """``role -> port`` for a template. Named so the checker reads as prose."""
    return [(port.role, port) for port in template.interface]


__all__ = [
    "DEFECT",
    "NOTE",
    "OPEN_QUESTION",
    "PinFinding",
    "PinReport",
    "check_pin_table",
]
