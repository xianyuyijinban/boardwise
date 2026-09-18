"""Review engine: run all built-in rules over a model and render reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ..core.model import DesignModel
from ..rules.base import SEVERITY_ORDER, Finding, Rule
from ..rules.connectivity import CrystalLoadCaps, DecouplingPerIC, ShuntSenseLink

#: Every rule applied by :func:`run_review`, in execution order.
BUILTIN_RULES: list[Rule] = [
    DecouplingPerIC(),
    CrystalLoadCaps(),
    ShuntSenseLink(),
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
