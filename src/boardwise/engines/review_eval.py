"""Metrics harness for the review rules (task 011a).

Reads oracle annotation sets (:mod:`boardwise.core.annotations`), runs the
rules over each annotated board, pairs findings against records, and reports
per-rule raw numerators/denominators — precision and recall are printed but
never without their fractions (task 011 sec.2: no packaged-up statistics).

Matching is deterministic and deliberately narrow:

1. a finding pairs with the closest *defect* whose ``rule_hint`` equals the
   finding's ``rule_id`` and whose ``ref`` is mentioned in the finding's
   evidence or message (word-boundary match: ``U1`` never matches ``U10``);
2. otherwise, with a defect hinted for a *different* rule (a cross match —
   the defect was caught, but by the wrong rule; reported, not folded away);
3. otherwise, with an *exception* it violated — a false positive;
4. otherwise it is an unexplained finding — also a false positive, but in
   its own column, because "the rule fired where the oracle sees nothing"
   and "the rule fired somewhere the oracle has not annotated" are different
   problems.

Queries are excluded from every numerator; they are counted, so the report
shows how much of the board the oracle has not ruled on yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.annotations import AnnotationSet
from ..core.model import DesignModel
from ..rules.base import OUTCOME_STATES, Finding, Rule
from .review import severity_counts

SPLIT_DEV = "dev"
SPLIT_HOLDOUT = "holdout"
SPLIT_ALL = "all"
SPLIT_CHOICES = (SPLIT_DEV, SPLIT_HOLDOUT, SPLIT_ALL)

#: A finding at one of these severities is a **determinate claim** -- the rule
#: says something is wrong, and a reader is expected to act. INFO means "here is
#: a measurement", so counting one as a false positive measures the reporter,
#: not the rule (011e sec.4.1 asks for the high-priority precision for exactly
#: this reason).
HIGH_PRIORITY_SEVERITIES = ("ERROR", "WARN")


def _ref_pattern(ref: str) -> re.Pattern[str]:
    """A designator as a whole token: ``U1`` must not match ``U10``/``XU1``."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(ref)}(?![A-Za-z0-9])")


def _mentions(finding: Finding, ref: str) -> bool:
    pattern = _ref_pattern(ref)
    for evidence in finding.evidence:
        if pattern.search(evidence):
            return True
    return bool(pattern.search(finding.message))


@dataclass
class RuleMetrics:
    """One rule's raw counts on one board. Nothing here is derived twice.

    ``missed`` is *derived*, not accumulated: hinted = detected +
    caught_by_other + missed. Recall's denominator is ``defects_hinted`` —
    a defect the oracle assigned to this rule that another rule happened to
    fire on is still not detected **by this rule**.
    """

    rule_id: str
    defects_hinted: int = 0
    detected: int = 0  # defects hinted here, paired with this rule's finding
    caught_by_other: int = 0  # defects hinted here, paired with another rule
    exceptions_hinted: int = 0
    fp_on_exception: int = 0  # this rule's finding violated an exception
    fp_unexplained: int = 0  # this rule's finding matched no record at all
    violations: int = 0  # findings emitted
    outcome_counts: dict[str, int] | None = None  # None = legacy rule
    #: The same three buckets restricted to **high-priority** findings -- the
    #: ones the rules assert at ERROR/WARN. A determinate claim is what the
    #: graduation criterion (011e sec.4.1) grades; an INFO is a report, and
    #: counting reports as false positives was measuring the wrong thing
    #: (011e sec.1.1 found `param-rc-cutoff`'s numeric rows drowning the
    #: denominator: 27 of them on board24v, 11 on the graduation board).
    hp_tp: int = 0
    hp_fp_exception: int = 0
    hp_fp_unexplained: int = 0

    @property
    def missed(self) -> int:
        return self.defects_hinted - self.detected - self.caught_by_other

    @property
    def false_positives(self) -> int:
        return self.fp_on_exception + self.fp_unexplained

    @property
    def precision(self) -> float | None:
        denom = self.detected + self.false_positives
        return self.detected / denom if denom else None

    @property
    def recall(self) -> float | None:
        return self.detected / self.defects_hinted if self.defects_hinted else None

    @property
    def hp_findings(self) -> int:
        """High-priority findings: what the rules asserted as a determinate
        problem, which is exactly what a reader may act on."""
        return self.hp_tp + self.hp_fp_exception + self.hp_fp_unexplained

    @property
    def hp_precision(self) -> float | None:
        return self.hp_tp / self.hp_findings if self.hp_findings else None


@dataclass
class BoardEvaluation:
    """Everything the harness concluded about one annotated board."""

    board: str
    source: str
    component_count: int
    net_count: int
    severity_counts: dict[str, int]
    metrics: list[RuleMetrics] = field(default_factory=list)
    queries: int = 0
    excluded_holdout: int = 0
    cross_matches: list[str] = field(default_factory=list)
    #: Oracle records whose ``rule_hint`` names a rule that is not registered.
    #: They are listed verbatim and enter **no** denominator: the ground truth
    #: must not be held hostage to rule progress, and an unregistered defect is
    #: exactly the priority list for the next rule batch (task 011c sec.3.0).
    unregistered: list[str] = field(default_factory=list)
    reviewed: bool = False

    @property
    def violations(self) -> int:
        return sum(m.violations for m in self.metrics)


def _rule_outcome_counts(rule: Rule, model: DesignModel) -> dict[str, int] | None:
    """Four-state counts from a rule that implements the Outcome protocol."""
    outcomes_method = getattr(rule, "outcomes", None)
    if outcomes_method is None:
        return None
    try:
        outcomes = outcomes_method(model)
    except NotImplementedError:
        return None
    counts = {state: 0 for state in OUTCOME_STATES}
    for outcome in outcomes:
        counts[outcome.state] = counts.get(outcome.state, 0) + 1
    return counts


def evaluate_annotations(
    aset: AnnotationSet,
    model: DesignModel,
    rules: list[Rule],
    *,
    split: str = SPLIT_DEV,
) -> BoardEvaluation:
    """Pair one board's oracle records against the rules' findings."""
    items = aset.items_for_split(split)
    defects = [item for item in items if item.kind == "defect"]
    exceptions = [item for item in items if item.kind == "exception"]
    excluded_holdout = len(aset.items) - len(items)

    findings: list[Finding] = []
    for rule in rules:
        findings.extend(rule.check(model))
    severity = severity_counts(findings)

    metrics = {
        rule.id: RuleMetrics(rule_id=rule.id) for rule in rules
    }
    for metric in metrics.values():
        metric.violations = sum(
            1 for finding in findings if finding.rule_id == metric.rule_id
        )
        metric.outcome_counts = _rule_outcome_counts(
            next(rule for rule in rules if rule.id == metric.rule_id), model
        )
    for item in defects:
        if item.rule_hint in metrics:
            metrics[item.rule_hint].defects_hinted += 1
    for item in exceptions:
        if item.rule_hint in metrics:
            metrics[item.rule_hint].exceptions_hinted += 1
    unregistered = [
        _unregistered_line(item)
        for item in (*defects, *exceptions)
        if item.rule_hint and item.rule_hint not in metrics
    ]

    paired_defects: set[int] = set()
    paired_exceptions: set[int] = set()
    cross_matches: list[str] = []

    def _exact_defect(finding: Finding) -> int | None:
        return next(
            (
                i
                for i, item in enumerate(defects)
                if i not in paired_defects
                and item.rule_hint == finding.rule_id
                and _mentions(finding, item.ref)
            ),
            None,
        )

    def _any_defect(finding: Finding) -> int | None:
        return next(
            (
                i
                for i, item in enumerate(defects)
                if i not in paired_defects
                # 014: an UNREGISTERED hint never cross-explains. The oracle
                # named no rule for it (here: conn-osc-pin-net, M2 backlog) and
                # ruled the same board's B2 findings "unexplained heuristic
                # limitations" independently -- letting the ref collision with
                # U1 claim one of them would overwrite that ruling and slip the
                # unregistered defect into an M1 precision denominator, exactly
                # what "stay out of every M1 denominator" forbids. The record
                # still lists in the unregistered column (built below, pairing
                # independent) and the finding it would have stolen falls
                # through to fp_unexplained as ruled.
                and item.rule_hint in metrics
                and _mentions(finding, item.ref)
            ),
            None,
        )

    def _violated_exception(finding: Finding) -> int | None:
        return next(
            (
                i
                for i, item in enumerate(exceptions)
                if i not in paired_exceptions
                and item.rule_hint == finding.rule_id
                and _mentions(finding, item.ref)
            ),
            None,
        )

    # Two passes, and the order is load-bearing. Pairing as we walked the
    # finding list let a *cross* match steal a defect from the rule it was
    # hinted to: a finding from another rule that happened to name the same
    # ref came first and claimed the record (measured 2026-09-20 on the
    # injected value/MPN board, where param-led-current's finding names U3 --
    # the series resistor it reads -- and took the defect that
    # param-value-mpn-match should have been credited with). Pass 1 gives
    # every finding first refusal on a defect hinted to *its own* rule;
    # pass 2 is for genuinely cross-caught or unexplained findings.
    claimed: set[int] = set()
    for index, finding in enumerate(findings):
        exact = _exact_defect(finding)
        if exact is not None:
            paired_defects.add(exact)
            metrics[finding.rule_id].detected += 1
            if finding.severity in HIGH_PRIORITY_SEVERITIES:
                metrics[finding.rule_id].hp_tp += 1
            claimed.add(index)

    for index, finding in enumerate(findings):
        if index in claimed:
            continue
        cross = _any_defect(finding)
        if cross is not None:
            paired_defects.add(cross)
            # Cross match: the defect WAS caught, but by a rule other than
            # the one the oracle hinted. Credited to the hinted rule (as
            # caught_by_other) and listed; the catching rule neither gains
            # a detection nor a false positive for it. An unregistered hint
            # has no metrics row — the catch is listed, nothing is credited
            # (task 011c sec.3.0: unregistered records enter no denominator).
            #
            # For the high-priority *precision* it does count as a true
            # positive: that question is "did the oracle's records explain
            # this finding", and a cross match is explained -- it caught a
            # real defect, just not the one the hint named.
            item = defects[cross]
            if item.rule_hint in metrics:
                metrics[item.rule_hint].caught_by_other += 1
            if finding.severity in HIGH_PRIORITY_SEVERITIES:
                metrics[finding.rule_id].hp_tp += 1
            cross_matches.append(
                f"{item.ref}: hinted {item.rule_hint}, caught by {finding.rule_id}"
            )
            continue
        violated = _violated_exception(finding)
        if violated is not None:
            paired_exceptions.add(violated)
            metrics[finding.rule_id].fp_on_exception += 1
            if finding.severity in HIGH_PRIORITY_SEVERITIES:
                metrics[finding.rule_id].hp_fp_exception += 1
            continue
        metrics[finding.rule_id].fp_unexplained += 1
        if finding.severity in HIGH_PRIORITY_SEVERITIES:
            metrics[finding.rule_id].hp_fp_unexplained += 1

    order = {rule.id: position for position, rule in enumerate(rules)}
    return BoardEvaluation(
        board=aset.board,
        source=aset.source,
        component_count=len(model.components),
        net_count=len(model.nets),
        severity_counts=severity,
        metrics=[metrics[rule.id] for rule in rules],
        queries=sum(1 for item in items if item.kind == "query"),
        excluded_holdout=excluded_holdout,
        cross_matches=cross_matches,
        unregistered=unregistered,
        reviewed=aset.is_reviewed,
    )


def _unregistered_line(item: object) -> str:
    """One line for the unregistered-hint column: ref / kind / hint / note.

    The note is truncated, not paraphrased — the full text lives in the
    annotation file, and this column's job is to be visible, not to retell.
    """
    severity = getattr(item, "severity", "") or ""
    kind = getattr(item, "kind", "")
    note = getattr(item, "note", "")
    if len(note) > 140:
        note = note[:137].rstrip() + "..."
    head = f"{item.ref} [{kind}" + (f", {severity}" if severity else "") + "]"
    return f"{head} hint {item.rule_hint!r}: {note}"


def _fmt_ratio(numerator: int, denominator: int, ratio: float | None) -> str:
    if denominator == 0:
        return "—"
    return f"{numerator}/{denominator} = {ratio:.2f}"


def render_text_report(
    evaluations: list[BoardEvaluation],
    *,
    split: str,
    rule_ids: list[str],
) -> str:
    """Human-readable per-rule report. Raw fractions always accompany rates."""
    lines = [
        f"boardwise review-eval: split={split}, "
        f"{len(evaluations)} board(s)",
    ]
    for evaluation in evaluations:
        reviewed = "reviewed" if evaluation.reviewed else "DRAFT (oracle review pending)"
        lines.append(
            f"\nboard {evaluation.board} ({evaluation.source}) [{reviewed}]: "
            f"{evaluation.component_count} components, {evaluation.net_count} nets, "
            f"findings {evaluation.severity_counts['ERROR']} ERROR / "
            f"{evaluation.severity_counts['WARN']} WARN / "
            f"{evaluation.severity_counts['INFO']} INFO"
        )
        header = (
            f"  {'rule':22} {'defects':>7} {'det':>4} {'miss':>4} {'x-catch':>7} "
            f"{'fp-exc':>6} {'fp-unexpl':>9} {'precision':>16} {'recall':>16} "
            f"{'hp-find':>7} {'hp-prec':>14}"
        )
        lines.append(header)
        for metric in evaluation.metrics:
            precision = _fmt_ratio(
                metric.detected, metric.detected + metric.false_positives,
                metric.precision,
            )
            recall = _fmt_ratio(
                metric.detected, metric.defects_hinted, metric.recall
            )
            hp_precision = _fmt_ratio(
                metric.hp_tp, metric.hp_findings, metric.hp_precision
            )
            lines.append(
                f"  {metric.rule_id:22} {metric.defects_hinted:>7} {metric.detected:>4} "
                f"{metric.missed:>4} {metric.caught_by_other:>7} "
                f"{metric.fp_on_exception:>6} {metric.fp_unexplained:>9} "
                f"{precision:>16} {recall:>16} "
                f"{metric.hp_findings:>7} {hp_precision:>14}"
            )
        if evaluation.cross_matches:
            for entry in evaluation.cross_matches:
                lines.append(f"  cross match: {entry}")
        if evaluation.unregistered:
            lines.append(
                f"  no registered rule: {len(evaluation.unregistered)} record(s) "
                "hint rules that do not exist yet — listed verbatim, counted in "
                "no denominator:"
            )
            for entry in evaluation.unregistered:
                lines.append(f"    {entry}")
        four_state = {
            metric.rule_id: metric.outcome_counts for metric in evaluation.metrics
        }
        if any(counts is not None for counts in four_state.values()):
            for state in OUTCOME_STATES:
                cells = []
                for rule_id in rule_ids:
                    counts = four_state.get(rule_id)
                    cells.append(str(counts[state]) if counts else "legacy")
                lines.append(f"  {state:13} " + "  ".join(f"{rule_id}={cell}" for rule_id, cell in zip(rule_ids, cells)))
        lines.append(
            f"  queries excluded: {evaluation.queries}"
            + ("" if evaluation.excluded_holdout == 0 else
               f"; holdout items excluded here: {evaluation.excluded_holdout}")
        )
    if len(evaluations) > 1:
        lines.extend(_render_split_totals(evaluations, split))
    return "\n".join(lines) + "\n"


def _render_split_totals(
    evaluations: list[BoardEvaluation], split: str
) -> list[str]:
    """The two numbers a graduation judgement reads (011e sec.4.1), with their
    raw fractions.

    **Scope: annotated boards only.** A board with no oracle records cannot make
    a finding a false positive -- silence is not a verdict, and counting an
    unannotated board's findings as unexplained would report "the oracle has not
    looked at this yet" as "the rules are wrong". The board counts are printed
    so the scope is visible rather than implied.

    **High-priority means ERROR/WARN findings.** Those are the determinate
    claims; an INFO is a measurement being reported (``param-rc-cutoff`` after
    011e sec.1.1 is the case in point), and grading a reporter on how often its
    reports were "right" is not a measurement of anything.
    """
    annotated = [
        evaluation
        for evaluation in evaluations
        if sum(m.defects_hinted + m.exceptions_hinted for m in evaluation.metrics) > 0
    ]
    metrics = [m for evaluation in annotated for m in evaluation.metrics]
    hinted = sum(m.defects_hinted for m in metrics)
    detected = sum(m.detected for m in metrics)
    hp_tp = sum(m.hp_tp for m in metrics)
    hp_exc = sum(m.hp_fp_exception for m in metrics)
    hp_unexpl = sum(m.hp_fp_unexplained for m in metrics)
    hp_total = hp_tp + hp_exc + hp_unexpl
    return [
        f"\n  split totals ({split}) over {len(evaluations)} board(s), "
        f"{len(annotated)} carrying oracle records in this split:",
        "    defect detection (injected + native): "
        + _fmt_ratio(detected, hinted, detected / hinted if hinted else None)
        + f"  (cross-caught {sum(m.caught_by_other for m in metrics)}, "
        + f"missed {sum(m.missed for m in metrics)})",
        "    high-priority precision (ERROR/WARN findings): "
        + _fmt_ratio(hp_tp, hp_total, hp_tp / hp_total if hp_total else None)
        + f"  ({hp_exc} contradicted an exception, "
        + f"{hp_unexpl} had no oracle record)",
    ]


def load_board_model(source: str | Path) -> DesignModel:
    """The schematic netlist for an annotated board.

    M1 reviews schematics, so ``.epro2`` goes through the schematic parser
    (the PCB-netlist view that ``boardwise review`` defaults to is empty for
    schematic-only exports — measured 2026-09-19 on the golden fixture).
    """
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"annotated board source not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".enet":
        from ..parsers.enet import parse_enet

        return parse_enet(path)
    if suffix == ".epro2":
        from ..parsers.schematic import build_schematic_model

        return build_schematic_model(path)
    raise ValueError(
        f"{path}: unsupported board source {suffix or '(no suffix)'}; "
        "expected .epro2 or .enet"
    )
