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

Two further aggregates are read out of the same run (task 017 sec.5).
**UNKNOWN coverage** says how often a rule that reached a conclusion could not
decide — counted per (rule x board) pair, with the ``missing_fact`` sentences
clustered by reason — because UNKNOWN is a signpost, not a failure, and a rule
that says "I cannot tell" instead of judging must not look like a rule that
passed. **Locate success** says how many findings name a part or a pin a reader
can go and look at (017 sec.5: a non-empty ``target``, or text whose designators
resolve). Both are rendered **after** every pre-017 section, and no earlier
number is rewritten by their arrival.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.annotations import AnnotationSet
from ..core.model import DesignModel
from ..rules.base import OUTCOME_STATES, Finding, Outcome, Rule
from .review import finding_refs, severity_counts

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

#: How many missing_fact clusters the report prints (017 sec.5 "top-N").
UNKNOWN_CLUSTER_TOP_N = 8

#: The reason vocabulary the harness reads out of ``Outcome.missing_fact``
#: (017 sec.5: "missing_fact clustering"). Ordered, and the **first** match
#: wins, which is why the narrow wordings come first: every shelf-facts sentence
#: starts with "facts for ...", and "identify the part and record ..." is one of
#: those, so the narrower statement has to be tested before the general one.
#:
#: Derived here rather than added to :class:`~boardwise.rules.base.Outcome` on
#: purpose. That prose is the only machine-readable signal the four-state
#: protocol carries about *why* a rule could not decide, and it already exists
#: on every UNKNOWN outcome (the constructor refuses one without it). A new
#: field would have to be filled correctly by every rule for the aggregate to
#: mean anything, and would say nothing until the whole rule pack was touched;
#: classifying the sentence keeps the burden in one place and makes a rule whose
#: wording the harness does not know show up as ``rule:<id>`` -- visible, and
#: never silently filed under "other".
UNKNOWN_REASON_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (category, re.compile(pattern))
    for category, pattern in (
        # The part's identity is not in the curated shelf: the work is intake.
        ("shelf-part-unknown", r"identify the part and record"),
        # The entry exists, the fact keys are empty (or still a candidate
        # awaiting the facts_verified flip -- the 039 gate's wording).
        ("shelf-facts-missing", r"\bfacts for "),
        # An obligation is prose, so connectivity alone cannot check it.
        ("free-text-target", r"is free text"),
        # Pin numbers / symbol pins: needs the library or the bridge, not a fact.
        ("resolver-missing", r"library resolver|library symbol "),
        # The pin's net is absent, or is on a net that cannot serve the rule.
        ("pin-net-unusable", r"\ba net on |\ba net for |the pin has no net"),
        # No source names the net's voltage, or two sources disagree.
        (
            "domain-unknown",
            r"no source names the voltage|known voltage on"
            r"|conflicting voltage sources|supply-pin net voltage",
        ),
        # A declared window/range the rule needs does not exist.
        (
            "window-undeclared",
            r"series-resistance window|input-range fact|input range for",
        ),
        # A value on the board side is missing or unparseable.
        ("value-unreadable", r"readable value|parseable value"),
        # ... and the one value that has to come out of an MPN code.
        ("mpn-undecodable", r"decodable EIA value code"),
    )
)


def unknown_reason_category(outcome: Outcome) -> str:
    """The machine-readable reason an outcome is UNKNOWN (017 sec.5).

    One of :data:`UNKNOWN_REASON_PATTERNS`, or ``rule:<rule_id>`` when no
    pattern matches — the fallback names the rule whose wording is unrecognised,
    which is the backlog entry, not a bucket to hide it in.
    """
    for category, pattern in UNKNOWN_REASON_PATTERNS:
        if pattern.search(outcome.missing_fact):
            return category
    return f"rule:{outcome.rule_id}"


def _clip(text: str, limit: int = 140) -> str:
    """Truncate, never paraphrase: the full text lives in the source object."""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _ref_pattern(ref: str) -> re.Pattern[str]:
    """A designator as a whole token: ``U1`` must not match ``U10``/``XU1``."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(ref)}(?![A-Za-z0-9])")


def _mentions(finding: Finding, ref: str) -> bool:
    pattern = _ref_pattern(ref)
    for evidence in finding.evidence:
        if pattern.search(evidence):
            return True
    return bool(pattern.search(finding.message))


def _locates(finding: Finding) -> bool:
    """Whether a finding's claim names something a reader can go and look at.

    Two ways, both from task 017 sec.5: the structured ``target`` (016) names a
    component/pin/net, or the text names a designator, read with the same
    :func:`~boardwise.engines.review.finding_refs` the JSON renderer marks
    findings with. A ``FindingTarget`` left entirely empty is *not* a location —
    it is a rule that built the object without filling it — and neither is a
    finding whose prose names no part; both are the measurement, not a bug in it.
    """
    target = finding.target
    if target is not None and (
        target.component_ref or target.primitive_id or target.pin_refs or target.net_refs
    ):
        return True
    return bool(finding_refs(finding))


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
    #: Findings this rule emitted that a reader can go and look at (017 sec.5,
    #: :func:`_locates`). Its denominator is :attr:`findings_total` -- **every**
    #: finding, including one that carries neither a target nor a designator,
    #: because "how often a claim can be located" is only a measurement if the
    #: ones that cannot are counted as misses.
    findings_located: int = 0
    outcome_counts: dict[str, int] | None = None  # None = legacy rule
    #: (rule x board) pairs over the four-state protocol (017 sec.5): how many
    #: boards this rule reached at least one conclusion on, and how many of those
    #: conclusions included an UNKNOWN. A board the rule returned *no* outcome
    #: rows for is not a pair — the measure is "how often a rule that ruled
    #: could not decide", not "how many boards exist", and a rule that reached no
    #: conclusion at all has nothing to be covered here.
    outcome_pairs: int = 0
    unknown_pairs: int = 0
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

    @property
    def findings_total(self) -> int:
        """Every finding this rule emitted, at any severity -- the denominator
        of :attr:`locate_rate`. The same number as :attr:`violations`, named for
        what it counts *here* (011e sec.4.1 grades a different question with that
        one)."""
        return self.violations

    @property
    def locate_rate(self) -> float | None:
        if not self.findings_total:
            return None
        return self.findings_located / self.findings_total


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
    #: Every UNKNOWN outcome the rules reached on this board, **verbatim** (017
    #: sec.5). The counts live in the metrics; the sentences are kept because the
    #: cluster report has to show what is inside a bucket, and because "which
    #: fact to record next" is answered by the sentence, not by the category.
    unknowns: list[Outcome] = field(default_factory=list)

    @property
    def violations(self) -> int:
        return sum(m.violations for m in self.metrics)


def _rule_outcomes(rule: Rule, model: DesignModel) -> list[Outcome] | None:
    """A rule's outcomes, or ``None`` for a rule that does not make them.

    The one call site that runs a rule's four-state side: the counts and the
    UNKNOWN sentences (017 sec.5) are both read from this list, so a rule is
    asked once per board and cannot answer differently to two readers.
    """
    outcomes_method = getattr(rule, "outcomes", None)
    if outcomes_method is None:
        return None
    try:
        return list(outcomes_method(model))
    except NotImplementedError:
        return None


def evaluate_annotations(
    aset: AnnotationSet,
    model: DesignModel,
    rules: list[Rule],
    *,
    split: str = SPLIT_DEV,
) -> BoardEvaluation:
    """Pair one board's oracle records against the rules' findings.

    ``model`` may be a whole project (040b): the rules then run **per board**,
    exactly as ``boardwise review`` runs them, and the counts aggregate over the
    boards. The oracle's records are project-scoped (they name refs, not boards),
    so pairing is unchanged — which is the point: the batch changed the model
    the rules read, not the verdicts they reach.
    """
    from ..core.model import ProjectModel

    items = aset.items_for_split(split)
    defects = [item for item in items if item.kind == "defect"]
    exceptions = [item for item in items if item.kind == "exception"]
    excluded_holdout = len(aset.items) - len(items)

    board_models: list[DesignModel] = (
        list(model.boards) if isinstance(model, ProjectModel) else [model]
    )
    findings: list[Finding] = []
    for board_model in board_models:
        for rule in rules:
            findings.extend(rule.check(board_model))
    severity = severity_counts(findings)
    findings_by_rule: dict[str, list[Finding]] = {}
    for finding in findings:
        findings_by_rule.setdefault(finding.rule_id, []).append(finding)

    metrics = {
        rule.id: RuleMetrics(rule_id=rule.id) for rule in rules
    }
    unknowns: list[Outcome] = []
    for metric in metrics.values():
        own = findings_by_rule.get(metric.rule_id, [])
        metric.violations = len(own)
        metric.findings_located = sum(1 for finding in own if _locates(finding))
        rule = next(rule for rule in rules if rule.id == metric.rule_id)
        totals: dict[str, int] = {state: 0 for state in OUTCOME_STATES}
        makes_outcomes = False
        for board_model in board_models:
            outcomes = _rule_outcomes(rule, board_model)
            if outcomes is None:
                continue
            makes_outcomes = True
            if outcomes:
                metric.outcome_pairs += 1
            board_unknown = False
            for outcome in outcomes:
                totals[outcome.state] = totals.get(outcome.state, 0) + 1
                if outcome.state != "UNKNOWN":
                    continue
                board_unknown = True
                unknowns.append(outcome)
            if board_unknown:
                metric.unknown_pairs += 1
        if makes_outcomes:
            # A rule that implements the protocol keeps a counts row even when it
            # reached no conclusion here: that is 0s, not "legacy" (the row a
            # rule with no ``outcomes()`` at all gets).
            metric.outcome_counts = totals
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
        component_count=sum(len(m.components) for m in board_models),
        net_count=sum(len(m.nets) for m in board_models),
        severity_counts=severity,
        metrics=[metrics[rule.id] for rule in rules],
        queries=sum(1 for item in items if item.kind == "query"),
        excluded_holdout=excluded_holdout,
        cross_matches=cross_matches,
        unregistered=unregistered,
        reviewed=aset.is_reviewed,
        unknowns=unknowns,
    )


def _unregistered_line(item: object) -> str:
    """One line for the unregistered-hint column: ref / kind / hint / note.

    The note is truncated, not paraphrased — the full text lives in the
    annotation file, and this column's job is to be visible, not to retell.
    """
    severity = getattr(item, "severity", "") or ""
    kind = getattr(item, "kind", "")
    note = getattr(item, "note", "")
    head = f"{item.ref} [{kind}" + (f", {severity}" if severity else "") + "]"
    return f"{head} hint {item.rule_hint!r}: {_clip(note)}"


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
    lines.extend(_render_coverage(evaluations, rule_ids))
    return "\n".join(lines) + "\n"


def _render_coverage(
    evaluations: list[BoardEvaluation], rule_ids: list[str]
) -> list[str]:
    """UNKNOWN coverage, locate success, fix-success and provenance (017 sec.5).

    **Appended after every existing section on purpose.** The numbers above this
    block are frozen baselines (011e / 014 / 015b), and 017 may add a metric, not
    rewrite one: the first line of this block is the first character of the
    report a 017 run changes.
    """
    from .. import __version__

    lines: list[str] = []
    flagged = sum(m.unknown_pairs for e in evaluations for m in e.metrics)
    pairs = sum(m.outcome_pairs for e in evaluations for m in e.metrics)
    lines.append(
        "\n  UNKNOWN coverage (017 sec.5) — (rule x board) pairs the rule ruled "
        "on, with at least one UNKNOWN: "
        + _fmt_ratio(flagged, pairs, flagged / pairs if pairs else None)
        + "; a pair is one board on which the rule reached an outcome"
    )
    legacy: list[str] = []
    for rule_id in rule_ids:
        rows = [m for e in evaluations for m in e.metrics if m.rule_id == rule_id]
        if not rows:
            continue
        if not any(row.outcome_counts is not None for row in rows):
            legacy.append(rule_id)
            continue
        unknown = sum(row.unknown_pairs for row in rows)
        ruled = sum(row.outcome_pairs for row in rows)
        lines.append(
            f"    {rule_id:26} "
            + _fmt_ratio(unknown, ruled, unknown / ruled if ruled else None)
        )
    if legacy:
        lines.append(
            "    legacy (no outcome protocol, so in no pair here): "
            + ", ".join(legacy)
        )
    unknowns = [outcome for evaluation in evaluations for outcome in evaluation.unknowns]
    if unknowns:
        clusters: dict[str, list[Outcome]] = {}
        for outcome in unknowns:
            clusters.setdefault(unknown_reason_category(outcome), []).append(outcome)
        ranked = sorted(clusters.items(), key=lambda entry: (-len(entry[1]), entry[0]))
        # The sentence inside a bucket, not just its size: "which fact to record
        # next" is answered by the text. The sample is the first occurrence in
        # evaluation order (rule order, then the rule's own order), so the same
        # run always prints the same line -- it shows the bucket, it does not
        # summarise it.
        shown = ranked[:UNKNOWN_CLUSTER_TOP_N]
        lines.append(
            f"    missing_fact clusters: {len(ranked)} reason category(ies), "
            + (f"top {len(shown)} by count:" if len(shown) < len(ranked) else "by count:")
        )
        for category, group in shown:
            texts = {outcome.missing_fact for outcome in group}
            lines.append(
                f"      {len(group):>5}  {category:24} "
                f"({len(texts)} distinct text(s))"
            )
            lines.append(f"             e.g. {_clip(group[0].missing_fact)}")
    located = sum(m.findings_located for e in evaluations for m in e.metrics)
    total = sum(m.findings_total for e in evaluations for m in e.metrics)
    lines.append(
        "\n  locate success (017 sec.5) — findings whose target names a part/pin "
        "or whose text names a designator, every severity: "
        + _fmt_ratio(located, total, located / total if total else None)
    )
    for rule_id in rule_ids:
        rows = [m for e in evaluations for m in e.metrics if m.rule_id == rule_id]
        here = sum(row.findings_total for row in rows)
        if not here:
            continue
        found = sum(row.findings_located for row in rows)
        lines.append(
            f"    {rule_id:26} " + _fmt_ratio(found, here, found / here)
        )
    lines.append(
        "\n  fix success (017 sec.5): pending — depends on 016 (edit apply -> "
        "resolved probe); this build reports no number rather than 0"
    )
    lines.append(
        "  provenance: tool boardwise "
        f"{__version__}, ruleset {ruleset_fingerprint(rule_ids)} over "
        f"{len(rule_ids)} rule id(s), rulebody "
        + (rulebody_fingerprint() or "unavailable (frozen, no source)")
    )
    return lines


def ruleset_fingerprint(rule_ids: list[str]) -> str:
    """A short digest of the rule **set** a report was measured with (017 sec.5).

    The digest covers the ordered rule ids, not the rules' bodies: a rule's id is
    its contract-level identity, so adding, removing or reordering rules moves
    this number, while a change inside a rule's body does not.
    :func:`rulebody_fingerprint` is the other half — what those rules *say* —
    and the report prints both, because a number measured before a rule
    improvement and a number measured after it are different measurements even
    when the set is identical.
    """
    return hashlib.sha256("\n".join(rule_ids).encode("utf-8")).hexdigest()[:8]


def rulebody_fingerprint(rules_dir: str | Path | None = None) -> str | None:
    """sha256/8 over the rules package's **source files**, or ``None`` if unreadable.

    Recipe: take every ``*.py`` that sits directly in ``src/boardwise/rules/``,
    sort by file name, feed each file's name and then its bytes into one sha256,
    and keep the first 8 hex digits. Names are part of the stream so that moving
    a rule between files cannot leave the digest unchanged.

    What it covers: the rule bodies, their shared helpers in that directory
    (``base.py``), their wording (``i18n.py``) — everything that decides what a
    rule concludes and how it says it. What it does **not** cover, and the reason
    both segments are printed: anything a rule *calls* from outside the
    directory. ``engines/`` and ``core/`` helpers, the parsers, the curated shelf
    (``blocklib/parts.json``) and the harness itself can all move a number
    without moving this digest, so a report still needs the commit it was run at.

    ``None`` means "this build cannot see its own rule sources", which is the
    frozen state: a PyInstaller onefile carries the rules in the PYZ as bytecode,
    and ``packaging/boardwise.spec``'s ``datas`` adds the connector bundle, the
    manifest, SKILL.md and the shelf — no Python sources. The caller prints
    ``rulebody unavailable (frozen, no source)``: a missing digest must not read
    as an unchanged one, and a release build must not fail on a bookkeeping line.
    """
    try:
        directory = (
            Path(rules_dir)
            if rules_dir is not None
            else Path(__file__).resolve().parent.parent / "rules"
        )
        if not directory.is_dir():
            return None
        sources = sorted(path for path in directory.iterdir() if path.suffix == ".py")
        if not sources:
            return None
        digest = hashlib.sha256()
        for path in sources:
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(path.read_bytes())
    except OSError:
        return None
    return digest.hexdigest()[:8]


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
    """The schematic model for an annotated board.

    M1 reviews schematics, so ``.epro2`` goes through the schematic parser
    (the PCB-netlist view that ``boardwise review`` defaults to is empty for
    schematic-only exports — measured 2026-09-19 on the golden fixture).

    Since 040b a ``.epro2`` yields a :class:`ProjectModel` (one model per board);
    the harness runs the rules per board, as the CLI does. ``.enet`` netlists stay
    a single :class:`DesignModel` — they have no boards to partition.
    """
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"annotated board source not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".enet":
        from ..parsers.enet import parse_enet

        return parse_enet(path)
    if suffix == ".epro2":
        from ..parsers.schematic import build_project_model

        return build_project_model(path)
    raise ValueError(
        f"{path}: unsupported board source {suffix or '(no suffix)'}; "
        "expected .epro2 or .enet"
    )
