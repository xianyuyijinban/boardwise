"""Tests for the metrics harness (task 011a): matching, counts, report."""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.annotations import annotations_from_json
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.review_eval import (
    evaluate_annotations,
    load_board_model,
    render_text_report,
)
from boardwise.rules.base import Outcome, OutcomeRule, Rule, Finding

SCHEMA = "boardwise-review-annotations/1"


def _model() -> DesignModel:
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1", value="widget",
        pins=[Pin("1", "VCC", "VCC"), Pin("2", "GND", "GND")],
    )
    model.components["U10"] = Component(
        uid="u10", designator="U10", value="other",
        pins=[Pin("1", "A", "A")],
    )
    model.components["R5"] = Component(
        uid="r5", designator="R5", value="10k",
        pins=[Pin("1", "A", "A"), Pin("2", "GND", "GND")],
    )
    model.nets = {
        "VCC": Net("VCC", [("U1", "1")]),
        "GND": Net("GND", [("U1", "2")]),
        "A": Net("A", [("U10", "1")]),
    }
    return model


class _FireOnU1(Rule):
    """Emits one WARN whose evidence names U1 only."""

    id = "fire-u1"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message="U1: something worth flagging",
                evidence=["U1 pin1 @ VCC"],
            )
        ]


class _FireOnU10(Rule):
    """Emits one WARN whose evidence names U10 only."""

    id = "fire-u10"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message="U10: something worth flagging",
                evidence=["U10 pin1 @ A"],
            )
        ]


class _Silent(Rule):
    id = "silent-rule"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return []


class _FireOnU1Too(Rule):
    """A second rule that also names U1 -- the case that caused the steal."""

    id = "fire-u1-too"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message="U1: read as part of something else",
                evidence=["U1 pin1 @ VCC"],
            )
        ]


def _aset(items: list[dict], **overrides) -> object:
    body = {
        "schema": SCHEMA,
        "board": "toy",
        "source": "tests/fixtures/toy.epro2",
        "items": items,
    }
    body.update(overrides)
    return annotations_from_json(body, "<test>")


def _defect(ref: str, hint: str, **extra) -> dict:
    return {"ref": ref, "rule_hint": hint, "kind": "defect",
            "severity": "WARN", "note": "n", **extra}


def _exception(ref: str, hint: str, **extra) -> dict:
    return {"ref": ref, "rule_hint": hint, "kind": "exception", "note": "n", **extra}


def _metrics(evaluation, rule_id):
    return next(m for m in evaluation.metrics if m.rule_id == rule_id)


RULES = [_FireOnU1(), _FireOnU10(), _Silent()]


def test_a_detected_defect_is_a_true_positive_with_a_raw_fraction():
    aset = _aset([_defect("U1", "fire-u1")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    metric = _metrics(evaluation, "fire-u1")
    assert (metric.detected, metric.missed, metric.false_positives) == (1, 0, 0)
    assert metric.precision == 1.0 and metric.recall == 1.0


def test_an_unregistered_hint_is_listed_and_counts_in_no_denominator():
    """The oracle's ground truth must not be hostage to rule progress (011c).

    A defect whose hint names a rule that does not exist yet must surface in
    the report's unregistered column — it is the priority list for the next
    rule batch — and must enter **no** rule's numerator or denominator.
    """
    aset = _aset([_defect("U1", "param-value-mpn-match")])
    evaluation = evaluate_annotations(aset, _model(), [_FireOnU1()])
    assert len(evaluation.unregistered) == 1
    line = evaluation.unregistered[0]
    assert "U1" in line and "defect" in line and "param-value-mpn-match" in line
    fire = _metrics(evaluation, "fire-u1")
    assert fire.defects_hinted == 0
    assert fire.detected == 0
    assert fire.defects_hinted == fire.detected + fire.caught_by_other + fire.missed
    # An unregistered *exception* lands in the same column.
    aset = _aset([_exception("U10", "conn-usb-cc-pulldown")])
    evaluation = evaluate_annotations(aset, _model(), [_FireOnU1()])
    assert len(evaluation.unregistered) == 1
    assert "exception" in evaluation.unregistered[0]


def test_an_unregistered_defect_never_cross_explains():
    """An unregistered hint has no metrics row -- and, since 014, no cross match.

    Before 014 the catch was still reported as a cross match (listed, nothing
    credited). The graduation board broke that: the U1.12 defect's hint
    (conn-osc-pin-net, deliberately unregistered) shares its ref with a
    decoupling WARN the oracle had ruled "a true L1-heuristic limitation" in
    the same sitting -- the cross match claimed that finding, moved it out of
    fp_unexplained, and lifted the rule's high-priority precision, which
    slipped the unregistered record into an M1 denominator and overwrote the
    B2 ruling. Now the unregistered defect explains nothing: the finding falls
    through to fp_unexplained of the rule that fired, and the record is listed
    verbatim in the unregistered column only.
    """
    aset = _aset([_defect("U1", "not-yet-built")])
    evaluation = evaluate_annotations(aset, _model(), [_FireOnU1()])
    assert evaluation.cross_matches == []
    fire = _metrics(evaluation, "fire-u1")
    assert (fire.defects_hinted, fire.detected, fire.caught_by_other) == (0, 0, 0)
    assert fire.fp_on_exception == 0 and fire.fp_unexplained == 1
    # The record itself is still listed, pairing-independent.
    assert len(evaluation.unregistered) == 1
    assert "not-yet-built" in evaluation.unregistered[0]


def test_the_unregistered_column_reaches_the_report():
    """What the engine found, the report must show — verbatim."""
    aset = _aset([_defect("U1", "param-value-mpn-match", note="bom/schematic clash")])
    evaluation = evaluate_annotations(aset, _model(), [_FireOnU1()])
    report = render_text_report(
        [evaluation], split="dev", rule_ids=["fire-u1"]
    )
    assert "no registered rule: 1 record(s)" in report
    assert "param-value-mpn-match" in report
    assert "bom/schematic clash" in report
    # And a clean set does not grow the section.
    clean = evaluate_annotations(
        _aset([_defect("U1", "fire-u1")]), _model(), [_FireOnU1()]
    )
    assert "no registered rule" not in render_text_report(
        [clean], split="dev", rule_ids=["fire-u1"]
    )


def test_a_defect_the_rules_stay_silent_on_is_missed():
    # R5: no rule fires on it, so the defect the oracle recorded there is
    # missed outright — recall 0/1 with no cross match to soften it.
    aset = _aset([_defect("R5", "silent-rule")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    metric = _metrics(evaluation, "silent-rule")
    assert (metric.defects_hinted, metric.detected, metric.missed) == (1, 0, 1)
    assert metric.recall == 0.0
    assert evaluation.cross_matches == []


def test_a_defect_caught_by_the_wrong_rule_keeps_the_hinted_rules_recall_at_zero():
    # fire-u10 fires on U10; the oracle assigned the U10 defect to silent-rule.
    # The defect was caught (by fire-u10), so it is not "missed" — but
    # silent-rule still did not detect it, and its recall must say 0/1.
    aset = _aset([_defect("U10", "silent-rule")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    silent = _metrics(evaluation, "silent-rule")
    fire = _metrics(evaluation, "fire-u10")
    assert (silent.defects_hinted, silent.detected, silent.caught_by_other) == (1, 0, 1)
    assert silent.missed == 0 and silent.recall == 0.0
    # the catching rule neither gains a detection nor a false positive
    assert fire.detected == 0 and fire.false_positives == 0
    assert evaluation.cross_matches == [
        "U10: hinted silent-rule, caught by fire-u10"
    ]


def test_a_violated_exception_is_a_false_positive_against_its_rule():
    aset = _aset([_exception("U1", "fire-u1")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    metric = _metrics(evaluation, "fire-u1")
    assert metric.fp_on_exception == 1 and metric.fp_unexplained == 0
    assert metric.precision == 0.0


def test_an_unexplained_finding_is_counted_in_its_own_column():
    aset = _aset([])  # the oracle annotated nothing
    evaluation = evaluate_annotations(aset, _model(), RULES)
    metric = _metrics(evaluation, "fire-u1")
    assert metric.fp_unexplained == 1 and metric.fp_on_exception == 0


def test_the_ref_match_never_crosses_designator_boundaries():
    # The finding names U10 only; an annotation for U1 must NOT match it.
    aset = _aset([_defect("U1", "fire-u10")])
    evaluation = evaluate_annotations(aset, _model(), [_FireOnU10()])
    metric = _metrics(evaluation, "fire-u10")
    assert (metric.detected, metric.missed) == (0, 1)
    # and the other direction: a U10 annotation against a U1-firing rule
    aset = _aset([_defect("U10", "fire-u1")])
    evaluation = evaluate_annotations(aset, _model(), [_FireOnU1()])
    metric = _metrics(evaluation, "fire-u1")
    assert (metric.detected, metric.missed) == (0, 1)


def test_a_defect_caught_by_a_different_rule_is_a_cross_match():
    aset = _aset([_defect("U1", "silent-rule")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    silent = _metrics(evaluation, "silent-rule")
    fire = _metrics(evaluation, "fire-u1")
    assert silent.caught_by_other == 1 and silent.missed == 0
    # the catching rule neither gains a detection nor a false positive
    assert fire.detected == 0 and fire.false_positives == 0
    assert evaluation.cross_matches == [
        "U1: hinted silent-rule, caught by fire-u1"
    ]


def test_the_hinted_rule_wins_its_own_defect_even_when_another_rule_names_the_ref_first():
    """Pairing order must not decide who gets credited (fixed 2026-09-20).

    Measured on the injected value/MPN board: ``param-led-current``'s finding
    named U3 (it is the series resistor the rule reads for the LED), and
    because it is scanned first it claimed the defect hinted to
    ``param-value-mpn-match`` -- det 0/1 with a cross match, for a rule that
    had fired exactly where the oracle said it would. Pass 1 now gives every
    finding first refusal on a defect hinted to *its own* rule.

    The board that exposed it no longer produces the colliding finding (the
    2026-09-19 revision of ``param-led-current``), which is precisely why this
    guard is pinned with synthetic rules: the ordering hazard outlives the
    measurement that found it.
    """
    aset = _aset([_defect("U1", "fire-u1")])
    evaluation = evaluate_annotations(
        aset, _model(), [_FireOnU1Too(), _FireOnU1()]
    )
    assert evaluation.cross_matches == []
    exact = _metrics(evaluation, "fire-u1")
    assert (exact.defects_hinted, exact.detected) == (1, 1)
    other = _metrics(evaluation, "fire-u1-too")
    # The other finding explained nothing, and stole nothing.
    assert (other.detected, other.caught_by_other) == (0, 0)
    assert other.fp_unexplained == 1


def test_queries_are_excluded_but_counted():
    aset = _aset([
        {"ref": "U1", "rule_hint": "", "kind": "query", "note": "undecided"},
        _defect("U1", "fire-u1"),
    ])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    assert evaluation.queries == 1
    assert _metrics(evaluation, "fire-u1").detected == 1


def test_holdout_items_are_excluded_unless_asked_for():
    aset = _aset([_defect("U1", "fire-u1", split="holdout")])
    evaluation = evaluate_annotations(aset, _model(), RULES, split="dev")
    assert evaluation.excluded_holdout == 1
    assert _metrics(evaluation, "fire-u1").defects_hinted == 0
    evaluation = evaluate_annotations(aset, _model(), RULES, split="all")
    assert evaluation.excluded_holdout == 0
    assert _metrics(evaluation, "fire-u1").detected == 1


def test_legacy_rules_report_no_outcome_counts_and_outcome_rules_do():
    class _OutcomeRule(OutcomeRule):
        id = "outcome-rule"
        title = "test"
        level = "test"
        source = "house rule"

        def check(self, model):
            return []

        def outcomes(self, model):
            return [
                Outcome(self.id, "OK", "U1 pin1"),
                Outcome(self.id, "UNKNOWN", "U1 pin2",
                        missing_fact="pin direction"),
                Outcome(self.id, "NOT_APPLICABLE", "U10"),
            ]

    aset = _aset([])
    evaluation = evaluate_annotations(aset, _model(), RULES + [_OutcomeRule()])
    assert _metrics(evaluation, "fire-u1").outcome_counts is None
    counts = _metrics(evaluation, "outcome-rule").outcome_counts
    assert counts == {
        "VIOLATION": 0, "OK": 1, "UNKNOWN": 1, "NOT_APPLICABLE": 1,
    }


def test_the_report_names_a_draft_set_and_keeps_raw_fractions():
    aset = _aset([_defect("U1", "fire-u1"), _exception("U10", "fire-u10")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    text = render_text_report(
        [evaluation], split="dev", rule_ids=[rule.id for rule in RULES]
    )
    assert "DRAFT (oracle review pending)" in text
    assert "1/1 = 1.00" in text
    assert "queries excluded: 0" in text


def test_load_board_model_parses_the_schematic_side_of_an_epro2():


    model = load_board_model(Path("tests/fixtures/ch340_golden.epro2"))
    assert len(model.components) == 17
    assert len(model.nets) == 13


def test_load_board_model_rejects_unknown_sources(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_board_model(tmp_path / "missing.epro2")
    bad = tmp_path / "board.brd"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported board source"):
        load_board_model(bad)


def test_the_real_ch340g_annotation_set_measures_the_known_false_positive():
    """Golden-board measurement after 011c (updated per the oracle's rulings).

    Two things this board must teach the harness: the xtal rule's grounded-case
    false positive is FIXED (fp-exc 0, the X1 exception record stays and pairs
    nothing), and the oracle's three unregistered-hint records (LED1 defect,
    R24/R27 exceptions) surface verbatim instead of vanishing.
    """

    from boardwise.core.annotations import load_annotations
    from boardwise.engines.review import BUILTIN_RULES

    aset = load_annotations(Path("reviewsets/ch340g_golden.json"))
    model = load_board_model(aset.source)
    evaluation = evaluate_annotations(aset, model, BUILTIN_RULES)
    xtal = _metrics(evaluation, "xtal-load-caps")
    assert xtal.fp_on_exception == 0
    assert xtal.exceptions_hinted == 1  # the X1 record still counts as hinted
    # 011d: the V3 query became a defect (oracle: the board never powered
    # up), every hint on the board is implemented, and both defects are
    # detected -- the unregistered column is empty.
    assert evaluation.queries == 0
    assert evaluation.unregistered == []
    decap = _metrics(evaluation, "decap-required-caps")
    assert (decap.defects_hinted, decap.detected) == (1, 1)
    mpn = _metrics(evaluation, "param-value-mpn-match")
    assert (mpn.defects_hinted, mpn.detected) == (1, 1)


def test_the_bishe_boards_a_section_is_detected_and_explained():
    """The A1/A2 landing, measured (011e sec.3 rulings of 2026-09-19), then
    signed under the 2026-09-20 final rulings (task 014).

    Two numbers, two different meanings. The 30 duplicates are **detected**
    (30/30): a real board, caught by a parser-level check that never had a
    real board to prove itself on before. The 10 value/MPN contradictions moved
    from the unexplained column to the exception column -- from "the oracle has
    not looked" to "the oracle looked and ruled the rule wrong -- here is why".

    The rule's own precision stays 0/10 on purpose: these ARE false positives,
    and the decoder fix / contradiction-magnitude concept the oracle named as
    M2 input are what will remove them. An exception record is how a known
    false positive stays counted instead of being argued away.

    014 additions, each measured against the harness as it actually behaves:
    the set is signed (no DRAFT stamp), the U1.12 defect lands in the
    unregistered column and nowhere else (an unregistered hint never
    cross-explains -- the decoupling WARN on U1 stays unexplained exactly as
    the B2 observation ruled it), and the X1 exception pairs no finding at all
    because the 013 fix silenced the rule before the record landed: it counts
    as hinted-and-looked-at, in no other column.
    """
    from boardwise.core.annotations import load_annotations
    from boardwise.engines.review import BUILTIN_RULES

    aset = load_annotations(Path("reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json"))
    evaluation = evaluate_annotations(
        aset, load_board_model(aset.source), BUILTIN_RULES, split="holdout"
    )
    # 014: the set is signed -- the report must not carry the DRAFT stamp.
    assert evaluation.reviewed
    # 014: exactly one unregistered record (the U1.12 defect), listed verbatim
    # in the no-registered-rule column, counted in no denominator -- and, per
    # the 014 cross-match fix, it does not explain the decoupling WARN that
    # happens to share its ref (that one stays unexplained, as B2 ruled it).
    assert len(evaluation.unregistered) == 1
    assert "U1" in evaluation.unregistered[0]
    assert "conn-osc-pin-net" in evaluation.unregistered[0]
    assert evaluation.cross_matches == []
    duplicate = _metrics(evaluation, "conn-duplicate-designators")
    assert (duplicate.defects_hinted, duplicate.detected, duplicate.missed) == (
        30, 30, 0,
    )
    mpn = _metrics(evaluation, "param-value-mpn-match")
    assert (mpn.exceptions_hinted, mpn.fp_on_exception) == (10, 10)
    assert mpn.fp_unexplained == 0, "A2 is ruled; nothing on it is unlooked-at"
    assert mpn.precision == 0.0, "and the rule is still the thing to fix"

    # B1 is a landed defect and the rule catches it: the real board's bulk-cap
    # shortfall is a true positive, same as the injected ones.
    decap = _metrics(evaluation, "decap-required-caps")
    assert (decap.defects_hinted, decap.detected, decap.missed) == (1, 1, 0)
    assert decap.hp_tp == 1 and decap.hp_fp_unexplained == 0

    # B2/B3 are ruled observation / still pending. The schema has no
    # "observation" kind, so with no item records these findings stay in the
    # unexplained column -- a wording gap, not a number gap: recording them as
    # exceptions would move them to fp_on_exception and leave every precision
    # figure untouched. The counts are pinned so that a future schema change
    # (or an accidental record) shows up here rather than in a report.
    #
    # 013 moved both numbers, and both moves are *recoveries*, not drift:
    # the Symbol-ATTR fallback brought the board's 25 early-placed R/C/L
    # parts back into the netlist, and two of B2's five findings turned out
    # to be artefacts of that same loss (caps the oracle was shown did not
    # exist in the model); B3's xtal warning vanished because the load caps
    # C20/C21 are now part of the graph it checks. 014 re-pinned B2 at 3 as
    # the oracle's final count and asserts the cross-match stays out.
    assert _metrics(evaluation, "decoupling-per-ic").fp_unexplained == 3
    assert _metrics(evaluation, "xtal-load-caps").fp_unexplained == 0
    # 014: the X1 exception pairs no finding -- the rule is quiet after 013 --
    # so the harness's actual behaviour is "hinted and looked at", full stop:
    # exceptions_hinted counts it, and nothing else moves (no fp_on_exception,
    # no unexplained). Pinned so the pairing mechanics can't drift silently.
    xtal = _metrics(evaluation, "xtal-load-caps")
    assert (xtal.exceptions_hinted, xtal.fp_on_exception) == (1, 0)
    # B4 is INFO: outside the high-priority denominator by construction.
    assert _metrics(evaluation, "shunt-sense-link").hp_findings == 0

    board_hp = sum(
        (metric.hp_tp for metric in evaluation.metrics),
        start=0,
    )
    assert board_hp == 31, "30 duplicates + the B1 bulk-cap shortfall"


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def _run_cli(*args: str):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "boardwise.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_review_eval_measures_the_real_annotation_set():
    result = _run_cli("review-eval", "--annotations", "reviewsets/ch340g_golden.json")
    assert result.returncode == 0, result.stderr
    assert "DRAFT (oracle review pending)" in result.stdout
    assert "xtal-load-caps" in result.stdout
    assert "0.00" not in result.stdout  # the grounded-case FP is fixed (011c)
    # 011d: every hint implemented, both defects detected, the no-registered-
    # rule column empty, and no queries left open.
    assert "queries excluded: 0" in result.stdout
    assert "no registered rule" not in result.stdout
    assert "1/1 = 1.00" in result.stdout  # decap-required-caps, precision
    assert "conn-usb-cc-pulldown" in result.stdout


def test_review_eval_reports_an_unknown_rule_hint_instead_of_rejecting(tmp_path):
    """Ruled in 011c sec.3.0: unregistered hints are a report column, not an error.

    The CLI used to exit 2 on them, which let rule progress censor the oracle's
    ground truth. Now the run measures and the column names what is missing.
    """
    bad = tmp_path / "unregistered.json"
    bad.write_text(
        _json_dumps({
            "schema": SCHEMA,
            "board": "toy",
            "source": "tests/fixtures/ch340_golden.epro2",
            "items": [{
                "ref": "U1", "rule_hint": "no-such-rule", "kind": "defect",
                "severity": "WARN", "note": "n",
            }],
        }),
        encoding="utf-8",
    )
    result = _run_cli("review-eval", "--annotations", str(bad))
    assert result.returncode == 0, result.stderr
    assert "no registered rule: 1 record(s)" in result.stdout
    assert "no-such-rule" in result.stdout


def test_review_eval_rejects_a_missing_source(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        _json_dumps({
            "schema": "boardwise-review-annotations/1",
            "board": "toy",
            "source": "tests/fixtures/does_not_exist.epro2",
            "items": [],
        }),
        encoding="utf-8",
    )
    result = _run_cli("review-eval", "--annotations", str(bad))
    assert result.returncode == 2
    assert "not found" in result.stderr


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# high-priority precision + split totals (task 011e sec.4.1)
# ---------------------------------------------------------------------------


class _ReportOnly(Rule):
    """Emits one INFO naming a designator no record mentions: a report."""

    id = "info-report"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message="Z9: fc = 159 Hz (reported, not graded)",
                evidence=["Z9 pin1"],
            )
        ]


def test_high_priority_precision_counts_determinate_claims_only():
    """sec.4.1's denominator, defined: ERROR/WARN, not "every finding".

    ``param-rc-cutoff`` reports one number per RC pair and grades nothing.
    Those findings are INFO, and counting them as false positives measures the
    reporter rather than the rule -- which is exactly what made the four-state
    VIOLATION column and the precision denominator lie before 011e sec.1.1
    (27 of them on board24v, 11 on the graduation board).
    """
    rules = [_FireOnU10(), _ReportOnly()]
    evaluation = evaluate_annotations(_aset([]), _model(), rules)
    warn = _metrics(evaluation, "fire-u10")
    info = _metrics(evaluation, "info-report")
    # With no records, both findings are unexplained...
    assert warn.false_positives == 1 and info.false_positives == 1
    # ...but only the determinate claim enters the high-priority pair.
    assert (warn.hp_findings, warn.hp_tp) == (1, 0) and warn.hp_precision == 0.0
    assert info.hp_findings == 0 and info.hp_precision is None


def test_a_cross_matched_finding_counts_as_explained_for_high_priority_precision():
    """The question is "did the oracle's records explain this claim", not "did
    the hint agree with the rule that fired"."""
    aset = _aset([_defect("U1", "fire-u10")])
    evaluation = evaluate_annotations(aset, _model(), RULES)
    assert _metrics(evaluation, "fire-u10").caught_by_other == 1
    fire_u1 = _metrics(evaluation, "fire-u1")
    assert (fire_u1.detected, fire_u1.hp_tp) == (0, 1)
    assert fire_u1.hp_precision == 1.0


def test_the_split_totals_carry_the_two_graduation_numbers():
    rules = [_FireOnU1()]
    evaluation = evaluate_annotations(_aset([_defect("U1", "fire-u1")]), _model(), rules)
    rule_ids = [rule.id for rule in rules]
    single = render_text_report([evaluation], split="dev", rule_ids=rule_ids)
    assert "split totals" not in single, "one board needs no totals row"
    text = render_text_report([evaluation, evaluation], split="dev", rule_ids=rule_ids)
    assert "split totals (dev) over 2 board(s), 2 carrying oracle records" in text
    assert "defect detection (injected + native): 2/2 = 1.00" in text
    assert "high-priority precision (ERROR/WARN findings): 2/2 = 1.00" in text


def test_the_split_totals_exclude_boards_with_no_oracle_records():
    """Silence is not a verdict.

    An unannotated board cannot make a finding false; counting its findings as
    unexplained would report "the oracle has not looked at this yet" as "the
    rules are wrong". The board counts are printed so the scope is visible.
    """
    rules = [_FireOnU1()]
    annotated = evaluate_annotations(_aset([_defect("U1", "fire-u1")]), _model(), rules)
    bare = evaluate_annotations(_aset([]), _model(), rules)
    text = render_text_report(
        [annotated, bare], split="dev", rule_ids=[rule.id for rule in rules]
    )
    assert "over 2 board(s), 1 carrying oracle records" in text
    # The bare board's WARN finding is absent from the denominator.
    assert "high-priority precision (ERROR/WARN findings): 1/1 = 1.00" in text
