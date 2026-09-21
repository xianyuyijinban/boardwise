"""Review engine: run all built-in rules over a model and render reports."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from ..core.model import DesignModel
from ..core.parts import DESIGNATOR_CATEGORIES
from ..rules.base import SEVERITY_ORDER, Finding, Rule
from ..rules.connectivity import (
    CrystalLoadCaps,
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
#:
#: ``decoupling-per-ic`` is **retired here** (task 015 sec.2; oracle ruling
#: 011f B2 "L1 heuristic limitation, retire in M2"). The class and its tests
#: stay in ``rules/connectivity.py`` -- retirement is not deletion, and the
#: rule must stay runnable for review: re-add it to this list and
#: ``test_011d_rules.py::test_decoupling_per_ic_is_retired_from_the_builtin_rules``
#: goes red.
BUILTIN_RULES: list[Rule] = [
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


#: A designator standing alone in prose: a short alpha prefix then digits, not
#: glued to a longer word (`U1` yes, `PC14`/`3V3`/`FRC0805J471` no).
_DESIGNATOR_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,4})(\d{1,4})(?![A-Za-z0-9_])")

#: The prefixes accepted as designators: the shelf table's own prefixes (the
#: project's existing statement of what a designator prefix means) plus the few
#: families it does not name. **An allow-list, not a heuristic on the shape** —
#: `AMS1117`, `SS34` and `CH340G` all *look* like designators, and a shape-only
#: rule would hand them to the canvas as refs that resolve to nothing.
DESIGNATOR_PREFIXES: frozenset[str] = frozenset(DESIGNATOR_CATEGORIES) | frozenset(
    {
        "RV", "RP", "RT",   # potentiometer / preset
        "FB",               # ferrite bead
        "NT", "ZD", "TVS",  # thermistor / zener / TVS
        "VR", "BT", "MK", "MIC", "TH", "ZZ",
    }
)


def finding_refs(finding: Finding) -> list[str]:
    """The designators a finding names, in first-seen order and deduplicated.

    Read out of ``evidence`` first and ``message`` second — evidence entries
    point at components by contract ("``C116 pin1 @ VM``"), while a message is
    prose and may mention a part number. A finding may name several parts (a
    decoupling violation names the IC *and* the capacitor), so this returns a
    list; the caller decides how many marks that becomes.
    """
    refs: list[str] = []
    seen: set[str] = set()
    for text in [*finding.evidence, finding.message]:
        for prefix, number in _DESIGNATOR_TOKEN.findall(text or ""):
            if prefix.upper() not in DESIGNATOR_PREFIXES:
                continue
            ref = f"{prefix.upper()}{number}"
            if ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
    return refs


def render_json(findings: list[Finding]) -> str:
    """Render a machine-readable report.

    Each finding also carries ``refs`` — the designators its evidence names —
    which is what `boardwise review-mark` marks on the live canvas. Derived here
    rather than added to :class:`Finding`, so the rules (and their tests) are
    untouched: this is a reading of what a rule already wrote, not a new claim
    the rule makes.
    """
    payload = {
        "summary": severity_counts(findings),
        "findings": [
            {**asdict(finding), "refs": finding_refs(finding)} for finding in findings
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
