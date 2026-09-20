"""Review engine: run all built-in rules over a model and render reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ..core.model import DesignModel
from ..rules.base import SEVERITY_ORDER, Finding, Rule
from ..rules.connectivity import (
    CrystalLoadCaps,
    DecouplingPerIC,
    DuplicateDesignators,
    ShuntSenseLink,
)
from ..rules.decap import DecapRequiredCaps
from ..rules.facts import (
    DomainVsRange,
    LdoDropout,
    LibraryPinConsistency,
    NcAndMustConnect,
    SupplyOnKnownDomain,
    UsbCcPulldown,
)
from ..rules.params import (
    DividerOutput,
    LedCurrent,
    RcCutoff,
    ValueMpnMatch,
)

#: Every rule applied by :func:`run_review`, in execution order. The 011c
#: facts rules sit after the L1 heuristics: they are slower (library loads)
#: and their subjects overlap the L1 IC scan. The 011d batch follows them.
BUILTIN_RULES: list[Rule] = [
    DecouplingPerIC(),
    CrystalLoadCaps(),
    ShuntSenseLink(),
    DuplicateDesignators(),
    NcAndMustConnect(),
    LibraryPinConsistency(),
    SupplyOnKnownDomain(),
    DomainVsRange(),
    LdoDropout(),
    DecapRequiredCaps(),
    LedCurrent(),
    DividerOutput(),
    RcCutoff(),
    ValueMpnMatch(),
    UsbCcPulldown(),
]


def run_review(model: DesignModel) -> list[Finding]:
    """Apply all built-in rules and return findings, most severe first."""
    findings: list[Finding] = []
    for rule in BUILTIN_RULES:
        findings.extend(rule.check(model))
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    return findings


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def render_markdown(findings: list[Finding], model_meta: dict[str, Any]) -> str:
    """Render a human-readable report, findings grouped by severity."""
    counts = severity_counts(findings)
    lines = [
        "# boardwise review report",
        "",
        f"- Source: {model_meta.get('source', '(unknown)')}",
        f"- Components: {model_meta.get('components', '?')}",
        f"- Nets: {model_meta.get('nets', '?')}",
        f"- Findings: {counts['ERROR']} ERROR, {counts['WARN']} WARN, "
        f"{counts['INFO']} INFO",
        "",
    ]
    if not findings:
        lines.append("No findings.")
        lines.append("")
        return "\n".join(lines)
    for severity in ("ERROR", "WARN", "INFO"):
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        lines.append(f"## {severity} ({len(group)})")
        lines.append("")
        for finding in group:
            lines.append(f"- `{finding.rule_id}` [{finding.level}] {finding.message}")
            for item in finding.evidence:
                lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines)


def render_json(findings: list[Finding]) -> str:
    """Render a machine-readable report."""
    payload = {
        "summary": severity_counts(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
