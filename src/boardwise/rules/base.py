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
class Finding:
    """One rule violation (or advisory note) with concrete evidence.

    ``evidence`` entries must point at specific components / nets / pins,
    e.g. ``"C116 pin1 @ VM"`` — never bare prose.
    """

    rule_id: str
    severity: Severity
    message: str
    level: str
    evidence: list[str] = field(default_factory=list)


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
