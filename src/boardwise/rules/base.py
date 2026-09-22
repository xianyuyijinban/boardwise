"""Rule framework: findings and the rule base class.

Every rule is expected to document where it comes from (``source``):
a datasheet recommendation, an app note, a house rule. Empty strings are
allowed for now, but the field is an architectural commitment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import DesignModel

Severity = Literal["INFO", "WARN", "ERROR"]

#: Sort order for reports: most severe first.
SEVERITY_ORDER: dict[str, int] = {"ERROR": 0, "WARN": 1, "INFO": 2}


@dataclass
class FindingTarget:
    """What a finding is *about*, in fields a caller can act on (task 016).

    ``evidence`` is for a reader and ``message`` is prose; this is the same
    claim said in a shape a machine can use without re-parsing either. Every
    field defaults to empty, so a rule fills in only what it actually knows —
    an empty ``primitive_id`` means "not resolvable offline" (the live id only
    exists on the editor's canvas; the schematic parser keeps the symbol uuid
    instead, ``parsers/schematic.py``) and never "there is no primitive".

    ``expected_before`` / ``suggested_after`` are *as written on the board*,
    not normalised numbers, because they are what a repair has to compare
    against and write back.
    """

    component_ref: str = ""
    primitive_id: str = ""
    pin_refs: list[str] = field(default_factory=list)
    net_refs: list[str] = field(default_factory=list)
    expected_before: str = ""
    suggested_after: str = ""


@dataclass
class Finding:
    """One rule violation (or advisory note) with concrete evidence.

    ``evidence`` entries must point at specific components / nets / pins,
    e.g. ``"C116 pin1 @ VM"`` — never bare prose.

    ``target`` is the optional structured form of the same claim: absent
    (``None``) for every rule that has nothing to change, and it is what makes
    a finding repairable — see task 016's ``core.changeplan``, which refuses to
    act on a finding that carries no target.
    """

    rule_id: str
    severity: Severity
    message: str
    level: str
    evidence: list[str] = field(default_factory=list)
    target: FindingTarget | None = None


class Rule:
    """Base class for all rules."""

    id: str = ""
    title: str = ""
    level: str = ""
    source: str = ""

    def check(self, model: DesignModel) -> list[Finding]:
        raise NotImplementedError


#: The four states a rule can conclude about one subject (task 011 sec.7).
#: A finding maps to VIOLATION; the other three exist so a rule can say
#: *why it is silent* instead of being silent. UNKNOWN is neither a pass
#: nor a fail — it names the missing fact, which is what drives the fact
#: library's intake priority.
OUTCOME_STATES = ("VIOLATION", "OK", "UNKNOWN", "NOT_APPLICABLE")


@dataclass
class Outcome:
    """One rule conclusion about one subject, in four-state vocabulary.

    ``subject`` names what was judged (``"U1 pin16"``, ``"U1"``), never bare
    prose. For UNKNOWN, ``missing_fact`` says what fact would have let the
    rule decide — the harness aggregates these verbatim.
    """

    rule_id: str
    state: str  # one of OUTCOME_STATES
    subject: str
    message: str = ""
    evidence: list[str] = field(default_factory=list)
    missing_fact: str = ""

    def __post_init__(self) -> None:
        if self.state not in OUTCOME_STATES:
            raise ValueError(
                f"outcome state {self.state!r} not in {OUTCOME_STATES}"
            )
        if self.state == "UNKNOWN" and not self.missing_fact:
            raise ValueError(
                "an UNKNOWN outcome must name the fact it is missing"
            )


class OutcomeRule(Rule):
    """A rule that can also explain its silence, in four-state vocabulary.

    Legacy rules keep overriding only :meth:`check`; the harness then derives
    VIOLATION rows from their findings and reports their other states as
    "legacy" rather than inventing OK/UNKNOWN counts they never made.
    """

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        raise NotImplementedError
