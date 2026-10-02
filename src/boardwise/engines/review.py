"""Review engine: run all built-in rules over a model and render reports."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from ..core.designintent import IntentSource
from ..core.model import DesignModel
from ..core.parts import DESIGNATOR_CATEGORIES
from ..rules.archclosure import (
    ArchRailVoltageClash,
    NrstClosure,
    OpenDrainPullup,
)
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
from ..rules.railratings import CapVoltageRating, LdoDissipation

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
    CapVoltageRating(),
    LdoDissipation(),
    ArchRailVoltageClash(),
    OpenDrainPullup(),
    NrstClosure(),
]

#: The rules that read a **DesignIntent** (091 A2a), by class. It is a table
#: rather than a name inside :func:`_rules_for` so that the next consumer (A3's
#: checker) joins by adding itself here and accepting the `intent=` keyword.
#:
#: 092 A2b added the two rail-rating rules: both are *driven* by the contract's
#: `requirements.rails[]` (a rail's `targetVoltage`, an output rail's
#: `continuousCurrent`), so without one they have no subject at all and file
#: nothing — which is what keeps a reading that names no intent unchanged.
#:
#: 093 A3a added two more carriers: `arch-rail-voltage-clash` is *driven* by the
#: same `requirements.rails[].targetVoltage` (and by its provenance, which now
#: decides the severity — the first time an intent moves a grade), and
#: `arch-opendrain-pullup` reads `decisions[]` for the one closure a drawing
#: cannot show (a pull-up the firmware enables). `arch-nrst-closure` is not here:
#: the shelf and the netlist are its whole subject.
INTENT_RULES: tuple[type[Rule], ...] = (
    ValueMpnMatch,
    CapVoltageRating,
    LdoDissipation,
    ArchRailVoltageClash,
    OpenDrainPullup,
)


def _rules_for(intent: IntentSource | None) -> list[Rule]:
    """The rule list one reading runs.

    Without a contract this returns :data:`BUILTIN_RULES` **itself** — the same
    objects, in the same order, no copy — so a reading that names no intent stays
    byte-for-byte what it was before 091 A2a. With one, each rule that reads an
    intent gets a *fresh instance* carrying it: the module-level instances are
    shared by every run in the process, so setting the answer on one of them would
    leak this reading's contract into the next one (the same reason
    `LibraryPinConsistency` takes its resolver at construction).
    """
    if intent is None:
        return BUILTIN_RULES
    return [
        rule.__class__(intent=intent) if isinstance(rule, INTENT_RULES) else rule
        for rule in BUILTIN_RULES
    ]


def run_review(
    model: DesignModel,
    *,
    rules_errored: list[str] | None = None,
    intent: IntentSource | None = None,
) -> list[Finding]:
    """Apply all built-in rules and return findings, most severe first.

    **Per board** (040b §WI-3): given a :class:`ProjectModel`, every rule runs on
    each board's own model and each finding carries that board's title. The rules
    themselves are untouched — a rule still judges one netlist, which is exactly
    why the boards must come to it separately. Given a plain
    :class:`DesignModel` (an ``.enet`` input, or one board's model on its own)
    the behaviour is what it always was, with ``board`` left empty.

    ``rules_errored`` is the collector :func:`_run_rules` writes broken rule ids
    into (#30 fork 2); a caller that hands one in gets a **partial report**
    instead of an exception.

    ``intent`` is the DesignIntent this reading was given (091 A2a) — the answer
    to "which side of a contradiction does the design stand behind?", which the
    rules that read one turn into a repair **direction**. It belongs to the
    reading, not to the process: a caller that names no contract gets the rule list
    unchanged (:func:`_rules_for`), and the contract's *file* is not read here —
    the caller resolves it (``IntentSource.load``), because which file a project's
    intent lives in is the caller's question, and a rule must not reach for a disk.
    """
    from ..core.model import ProjectModel

    rules = _rules_for(intent)
    if not isinstance(model, ProjectModel):
        return _run_rules(model, rules, rules_errored=rules_errored)

    findings: list[Finding] = []
    for board_model in model.boards:
        board_findings = _run_rules(board_model, rules, rules_errored=rules_errored)
        title = board_model.board.title
        for finding in board_findings:
            finding.board = title
        findings.extend(board_findings)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    return findings


def _run_rules(
    model: DesignModel, rules: list[Rule], *, rules_errored: list[str] | None = None
) -> list[Finding]:
    """One model, one rule list, sorted — the shape every caller of ``check`` uses.

    ``rules_errored`` is what decides how a **broken rule** is handled, and it is
    the caller's choice on purpose (#30 fork 2, the measured failure: a bare
    ``RuntimeError`` out of ``_run_rules`` aborted `checkup` and left a
    half-written ``--out``):

    * a caller that hands in a collector is asking for a *partial report* — each
      rule that raises is caught, its id is appended to the collector, and the
      remaining rules run to the end. The report says what is missing
      (`completion.coverage.rulesErrored`, and the verdict drops) instead of never
      being written.
    * a caller that passes nothing keeps the exception. That is `check_rules`,
      which serves `edit plan` and the repair flows: there, "the rule crashed" and
      "the rule found nothing" must not collapse into the same answer, so a bug
      stays a hard stop rather than a silent "nothing to plan".
    """
    findings: list[Finding] = []
    for rule in rules:
        try:
            findings.extend(rule.check(model))
        except Exception:  # noqa: BLE001 — one broken rule may not kill the whole report
            if rules_errored is None:
                raise
            rules_errored.append(rule.id)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    return findings


def refused_conclusions(model: object) -> int:
    """How many conclusions this reading's unproven nets **actually** withheld (#19/#30).

    Not the same number as `source.unprovenNets.rulesRefused`, and the two are
    kept apart on purpose:

    * ``rulesRefused`` (the existing field) is the **length of the registry**:
      "how many rules are capable of refusing a net-shaped judgement" — 9 on every
      per-page reading, whether or not one of them had anything to refuse.
    * this counts **instances**: one per `(rule, subject)` whose UNKNOWN outcome
      names :data:`UNPROVEN_BY_NAME` as the fact it is missing — the verdicts this
      reading actually withheld. That is the number the coverage gate can act on.

    Zero by construction for every reading but the per-page tier, and the rule walk
    is skipped entirely there: a refusal is scoped to names the merge welded blind
    (``DesignModel.unproven_nets``), so a model with no such name cannot withhold
    anything — and running the listed rules' outcome walks is not free (each loads
    the shelf).
    """
    from ..core.model import ProjectModel
    from ..rules.unproven import NET_MEMBERSHIP_RULES, UNPROVEN_BY_NAME

    boards = model.boards if isinstance(model, ProjectModel) else [model]
    if not any(getattr(board, "unproven_nets", None) for board in boards):
        return 0
    rules = [
        rule
        for rule in BUILTIN_RULES
        if rule.id in NET_MEMBERSHIP_RULES and hasattr(rule, "outcomes")
    ]
    total = 0
    for board_model in boards:
        if not getattr(board_model, "unproven_nets", None):
            continue
        for rule in rules:
            for outcome in rule.outcomes(board_model):
                if outcome.state != "UNKNOWN":
                    continue
                if UNPROVEN_BY_NAME in (outcome.missing_fact or ""):
                    total += 1
    return total


def check_rules(model: object, rules: list[Rule] | None = None) -> list[Finding]:
    """``rule.check`` for a model that may be a project: per board, board stamped.

    The single-rule CLI paths (``review --rule``, ``edit plan``, the repair
    flows) used to call ``rule.check(model)`` directly, which since 040b can be
    handed a project. One function so they cannot disagree about how a project is
    reviewed — and so the board attribution is not re-implemented per command.
    """
    from ..core.model import ProjectModel

    rules = BUILTIN_RULES if rules is None else rules
    model_obj: object = model
    if not isinstance(model_obj, ProjectModel):
        return _run_rules(model_obj, rules)  # type: ignore[arg-type]
    findings: list[Finding] = []
    for board_model in model_obj.boards:
        board_findings = _run_rules(board_model, rules)
        for finding in board_findings:
            finding.board = board_model.board.title
        findings.extend(board_findings)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    return findings


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def render_markdown(findings: list[Finding], model_meta: dict[str, Any]) -> str:
    """Render a human-readable report, findings grouped by severity.

    **Per board when the findings span more than one** (040b §WI-4): a project's
    report that mixes three boards' findings under one heading makes the reader
    check every ref's board to know which netlist a claim is about. A
    single-board report is byte-for-byte what it always was — no board heading,
    no change.
    """
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

    titles: list[str] = []
    for finding in findings:
        if finding.board and finding.board not in titles:
            titles.append(finding.board)
    if len(titles) > 1:
        for title in titles:
            lines.append(f"## {title}")
            lines.append("")
            _append_severity_groups(lines, [f for f in findings if f.board == title])
        unassigned = [f for f in findings if not f.board]
        if unassigned:
            lines.append("## (no board)")
            lines.append("")
            _append_severity_groups(lines, unassigned)
        return "\n".join(lines)

    _append_severity_groups(lines, findings)
    return "\n".join(lines)


def _append_severity_groups(lines: list[str], findings: list[Finding]) -> None:
    """Append the ERROR/WARN/INFO blocks of one severity sweep, in that order."""
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


#: A designator standing alone in prose: a short alpha prefix then digits, not
#: glued to a longer word (`U1` yes, `PC14`/`3V3`/`FRC0805J471` no).
#:
#: The prefix is *up to five* letters because `SCREW1..4` — the mounting holes
#: on the thesis FOC board, measured in 017 — are real designators an allow-list
#: of at most four could never see, so the finding that names one lost its ref
#: and the canvas lost its mark. A wider *shape* is not a looser judgement:
#: every candidate this matches still has to appear in
#: :data:`DESIGNATOR_PREFIXES`, and that list is what keeps the part numbers out.
_DESIGNATOR_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,5})(\d{1,4})(?![A-Za-z0-9_])")

#: The prefixes accepted as designators: the shelf table's own prefixes (the
#: project's existing statement of what a designator prefix means) plus the few
#: families it does not name. **An allow-list, not a heuristic on the shape** —
#: `AMS1117`, `SS34` and `CH340G` all *look* like designators, and a shape-only
#: rule would hand them to the canvas as refs that resolve to nothing. This same
#: list is why the five-letter shape above is safe: `SCREW` is named here and
#: `FRC0805J471` (`FRC` + `0805`, followed by `J`) is not.
#:
#: A missing prefix is a **silent** loss — the finding keeps its prose and loses
#: its ref, so `review-mark` loses the mark and (since 063) `triage_key` loses
#: the identity with it. `EC` (electrolytic capacitor) was missing exactly that
#: way (issue #13: the shelf's `C` does not cover the two-letter form); it is
#: added here, but the standing fix is :func:`finding_refs` reading the
#: structured ``target`` first rather than growing this list.
DESIGNATOR_PREFIXES: frozenset[str] = frozenset(DESIGNATOR_CATEGORIES) | frozenset(
    {
        "RV", "RP", "RT",   # potentiometer / preset
        "FB",               # ferrite bead
        "EC",               # electrolytic capacitor (`C` does not cover it)
        "NT", "ZD", "TVS",  # thermistor / zener / TVS
        "VR", "BT", "MK", "MIC", "TH", "ZZ",
        # Mounting hole / structural part: a designator the board really has,
        # in no shelf category (nothing to look up facts for) — named here so a
        # finding that mentions one still gets a mark on the canvas.
        "SCREW",
    }
)


#: A quoted value in a finding's prose: `C26 value 'C104'` / `value "10uF"`.
#: The quoted span is the *value* of the part named just before it, and a value
#: may look like a designator — `C104` is an EIA capacitance code that the token
#: shape reads as `C` + `104` (issue #16 measured exactly that line). Dropped
#: before the prose is scanned; the designator that precedes it is outside the
#: quotes and stays readable.
_VALUE_QUOTED = re.compile(r"\bvalues?\s+'[^']*'|\bvalues?\s+\"[^\"]*\"", re.IGNORECASE)


def finding_refs(finding: Finding) -> list[str]:
    """The designators a finding names, in first-seen order and deduplicated.

    The **structured** identity is read first, and — when it is there — *alone*:
    ``target.component_ref`` is the designator the rule itself put on the finding
    (task 016's :class:`~boardwise.rules.base.FindingTarget`, filled from the
    rule's own ``Outcome.subject`` since issue #16), in the model's own spelling.
    A rule that says what it is about is believed.

    Prose is a heuristic and it leaks in both directions, which is what the two
    issues measured. Issue #13 read the target too little: `EC` was not in
    :data:`DESIGNATOR_PREFIXES`, and a board whose designators are spelled `xR67`
    yields the prefix `xR`, which no allow-list of prefixes would ever name —
    both findings carried ``target.component_ref`` (``EC3`` / ``xR67``) and
    neither was read, so the finding *had* no ref: the canvas lost its mark and
    (063) the triage key degenerated to no identity at all. Issue #16 read it
    too loosely: the prose was scanned *as well*, so a finding about `U5 pin4`
    arrived with all 16 members of the net its message printed, a part number
    (`RT9013`, read as `RT` + `9013`, and `RT` is on the prefix allow-list) and a
    capacitor value (`C104`) came back as parts of the board. Both are the same
    reading, and it is the one :func:`boardwise.engines.checkup.triage_identity`
    already uses: the structured claim, or the text when there is none.

    The text is the fallback, and it stays for the rules that carry no target —
    evidence entries point at components by contract ("``C116 pin1 @ VM``"),
    while a message is prose and may mention a part number. One idiom is read as
    what it is: the quoted span in ``C26 value 'C104'`` is a value
    (:data:`_VALUE_QUOTED`), so `C104` is not a ref while `C26` still is. A
    finding may name several parts (a decoupling violation names the IC *and* the
    capacitor), so this returns a list; the caller decides how many marks that
    becomes — and a rule that wants an auxiliary part marked says so in its own
    target, rather than relying on this reader to guess it back out of a
    sentence.
    """
    target = getattr(finding, "target", None)
    component = str(getattr(target, "component_ref", "") or "").strip()
    if component:
        return [component]

    refs: list[str] = []
    seen: set[str] = set()

    def add(ref: str) -> None:
        ref = ref.strip()
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)

    for text in [*finding.evidence, finding.message]:
        for prefix, number in _DESIGNATOR_TOKEN.findall(
            _VALUE_QUOTED.sub("", text or "")
        ):
            if prefix.upper() not in DESIGNATOR_PREFIXES:
                continue
            add(f"{prefix.upper()}{number}")
    return refs


def render_json(findings: list[Finding]) -> str:
    """Render a machine-readable report.

    Each finding also carries ``refs`` — the designators its target and its
    evidence name (see :func:`finding_refs`) — which is what `boardwise
    review-mark` marks on the live canvas and what 063's triage key is built
    from. Derived here rather than added to :class:`Finding`, so the rules (and
    their tests) are untouched: this is a reading of what a rule already wrote,
    not a new claim the rule makes.
    """
    payload = {
        "summary": severity_counts(findings),
        "findings": [
            {**asdict(finding), "refs": finding_refs(finding)} for finding in findings
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
