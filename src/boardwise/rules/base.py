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
