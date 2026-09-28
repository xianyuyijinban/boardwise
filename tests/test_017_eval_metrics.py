"""Task 017 sec.5: UNKNOWN coverage and locate success in the metrics harness.

Two aggregates the harness did not have: how often a rule that reached a
conclusion could not decide (per rule x board pair, with the ``missing_fact``
sentences clustered by reason), and how often a finding names something a reader
can go and look at.

The red line that governs their arrival is in the first test:
``GOLDEN_BEFORE_017`` is the report of a fixed synthetic run taken from the
pre-017 harness (commit HEAD), and the current report must **start** with it,
byte for byte — a 017 metric may be appended to the report, never folded into a
number that was already published (011e / 014 / 015b are baselines).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from boardwise import cli as cli_module
from boardwise.core.annotations import annotations_from_json
from boardwise.core.model import (
    BoardModel,
    BoardRef,
    Component,
    DesignModel,
    Net,
    Pin,
    ProjectModel,
)
from boardwise.engines.review import BUILTIN_RULES
from boardwise.engines.review_eval import (
    FIX_CASES,
    FIX_ATTEMPT_OUTCOMES,
    FIX_OUTCOME_APPLIED,
    FIX_OUTCOME_FAILED,
    FIX_OUTCOME_IDEMPOTENT,
    FIX_OUTCOME_INTERRUPTED,
    FIX_OUTCOME_NOT_SIMULABLE,
    FIX_OUTCOME_RECHECK,
    FIX_OUTCOME_REFUSED,
    FIX_SUCCESS_KINDS,
    UNKNOWN_REASON_PATTERNS,
    evaluate_annotations,
    fix_success_rows,
    fix_success_total,
    render_text_report,
    rulebody_fingerprint,
    ruleset_fingerprint,
    unknown_reason_category,
)
from boardwise.rules.base import Finding, FindingTarget, Outcome, OutcomeRule, Rule

cli_main = cli_module.main

SCHEMA = "boardwise-review-annotations/1"

#: The pre-017 report of one fixed synthetic run (the same input as
#: ``_golden_report``), captured from ``HEAD`` before this batch touched the
#: harness. Not a summary of the old output — the old output.
GOLDEN_BEFORE_017 = (
    "boardwise review-eval: split=dev, 2 board(s)\n"
    "\n"
    "board toy (tests/fixtures/toy.epro2) [DRAFT (oracle review pending)]: 1 components, 2 nets, findings 0 ERROR / 1 WARN / 1 INFO\n"
    "  rule                   defects  det miss x-catch fp-exc fp-unexpl        precision           recall hp-find        hp-prec\n"
    "  golden-outcome               1    1    0       0      0         0       1/1 = 1.00       1/1 = 1.00       1     1/1 = 1.00\n"
    "  golden-bare                  0    0    0       0      0         1       0/1 = 0.00                —       0              —\n"
    "  VIOLATION     golden-outcome=0  golden-bare=legacy\n"
    "  OK            golden-outcome=1  golden-bare=legacy\n"
    "  UNKNOWN       golden-outcome=1  golden-bare=legacy\n"
    "  NOT_APPLICABLE golden-outcome=0  golden-bare=legacy\n"
    "  queries excluded: 0\n"
    "\n"
    "board toy (tests/fixtures/toy.epro2) [DRAFT (oracle review pending)]: 1 components, 2 nets, findings 0 ERROR / 1 WARN / 1 INFO\n"
    "  rule                   defects  det miss x-catch fp-exc fp-unexpl        precision           recall hp-find        hp-prec\n"
    "  golden-outcome               1    1    0       0      0         0       1/1 = 1.00       1/1 = 1.00       1     1/1 = 1.00\n"
    "  golden-bare                  0    0    0       0      0         1       0/1 = 0.00                —       0              —\n"
    "  VIOLATION     golden-outcome=0  golden-bare=legacy\n"
    "  OK            golden-outcome=1  golden-bare=legacy\n"
    "  UNKNOWN       golden-outcome=1  golden-bare=legacy\n"
    "  NOT_APPLICABLE golden-outcome=0  golden-bare=legacy\n"
    "  queries excluded: 0\n"
    "\n"
    "  split totals (dev) over 2 board(s), 2 carrying oracle records in this split:\n"
    "    defect detection (injected + native): 2/2 = 1.00  (cross-caught 0, missed 0)\n"
    "    high-priority precision (ERROR/WARN findings): 2/2 = 1.00  (0 contradicted an exception, 0 had no oracle record)\n"
)


def _model() -> DesignModel:
    design = DesignModel()
    design.components["U1"] = Component(
        uid="u1",
        designator="U1",
        value="widget",
        pins=[Pin("1", "VCC", "VCC"), Pin("2", "GND", "GND")],
    )
    design.nets = {"VCC": Net("VCC", [("U1", "1")]), "GND": Net("GND", [("U1", "2")])}
    return design


def _aset(items: list[dict], **overrides) -> object:
    body = {
        "schema": SCHEMA,
        "board": "toy",
        "source": "tests/fixtures/toy.epro2",
        "items": items,
    }
    body.update(overrides)
    return annotations_from_json(body, "<test>")


def _defect(ref: str, hint: str) -> dict:
    return {"ref": ref, "rule_hint": hint, "kind": "defect", "severity": "WARN", "note": "n"}


def _metrics(evaluation, rule_id):
    return next(m for m in evaluation.metrics if m.rule_id == rule_id)


def _plain_check_finding(rule_id: str, message: str, evidence: list[str] | None = None):
    return Finding(
        rule_id=rule_id,
        severity="WARN",
        level="test",
        message=message,
        evidence=list(evidence or []),
    )


class _GoldenOutcome(OutcomeRule):
    """The rule the golden report's input runs: one finding, two outcomes."""

    id = "golden-outcome"
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

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [
            Outcome(self.id, "OK", "U1 pin1"),
            Outcome(
                self.id,
                "UNKNOWN",
                "U1 pin2",
                missing_fact="facts for U1 (entry C1, mpn 'X', lcsc 'C1'): record supply_pins",
            ),
        ]


class _GoldenBare(Rule):
    """A legacy rule with one finding no reader can locate."""

    id = "golden-bare"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message="the board carries a flag nobody can walk to",
                evidence=[],
            )
        ]


def _golden_report() -> str:
    evaluation = evaluate_annotations(
        _aset([_defect("U1", "golden-outcome")]),
        _model(),
        [_GoldenOutcome(), _GoldenBare()],
    )
    return render_text_report(
        [evaluation, evaluation],
        split="dev",
        rule_ids=["golden-outcome", "golden-bare"],
    )


def test_the_report_appends_and_never_rewrites_the_published_numbers():
    """One character of the pre-017 report is one character too many.

    011e / 014 / 015b's numbers are baselines. This pins the whole report of a
    fixed run against the bytes the pre-017 harness produced, so a 017 metric
    that leaks into an existing section (a new column, a changed rate, a moved
    line) fails here instead of quietly rewriting a published baseline.
    """
    text = _golden_report()
    assert text.startswith(GOLDEN_BEFORE_017)
    added = text[len(GOLDEN_BEFORE_017) :]
    assert "UNKNOWN coverage" in added
    assert "locate success" in added
    # And the append comes after the last pre-existing section, not before it.
    assert text.index("split totals") < text.index("UNKNOWN coverage")
    assert text.index("split totals") < text.index("locate success")


class _RuledOnce(OutcomeRule):
    """Ruled on the first board it was handed, on nothing on the second."""

    id = "ruled-once"
    title = "test rule"
    level = "test"
    source = "house rule"

    def __init__(self) -> None:
        self.boards_seen = 0

    def check(self, model: DesignModel) -> list[Finding]:
        return []

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        self.boards_seen += 1
        if self.boards_seen > 1:
            return []
        return [
            Outcome(self.id, "OK", "U1 pin1"),
            Outcome(self.id, "UNKNOWN", "U1 pin2", missing_fact="a net on U1 pin2"),
        ]


class _AlwaysDecides(OutcomeRule):
    """Implements the protocol and never says UNKNOWN."""

    id = "always-decides"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return []

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [Outcome(self.id, "OK", "U1 pin1")]


def test_unknown_coverage_counts_pairs_not_outcomes():
    """A pair is a board the rule ruled on, not one UNKNOWN it emitted.

    The rule below reaches four conclusions on one board, two of them UNKNOWN:
    the pair count is 1/1, not 1/2 or 2/4 — the metric asks how often a rule that
    ruled could not decide, so a second UNKNOWN on the same board cannot move it.
    """
    class _FourOutcomes(OutcomeRule):
        id = "four-outcomes"
        title = "test rule"
        level = "test"
        source = "house rule"

        def check(self, model):
            return []

        def outcomes(self, model):
            return [
                Outcome(self.id, "OK", "U1 pin1"),
                Outcome(self.id, "OK", "U1 pin2"),
                Outcome(
                    self.id,
                    "UNKNOWN",
                    "U1 pin3",
                    missing_fact="a decodable EIA value code in the MPN of R24",
                ),
                Outcome(self.id, "UNKNOWN", "R24", missing_fact="a readable value on R24"),
            ]

    evaluation = evaluate_annotations(
        _aset([]), _model(), [_FourOutcomes(), _AlwaysDecides()]
    )
    ruled = _metrics(evaluation, "four-outcomes")
    assert (ruled.unknown_pairs, ruled.outcome_pairs) == (1, 1)
    decided = _metrics(evaluation, "always-decides")
    # The rule that always decided is in the denominator (it ruled) and not in
    # the numerator — that is what makes the ratio a coverage number.
    assert (decided.unknown_pairs, decided.outcome_pairs) == (0, 1)
    text = render_text_report(
        [evaluation], split="dev", rule_ids=["four-outcomes", "always-decides"]
    )
    assert "with at least one UNKNOWN: 1/2 = 0.50" in text
    assert re.search(r"four-outcomes\s+1/1 = 1\.00", text)
    assert re.search(r"always-decides\s+0/1 = 0\.00", text)
    assert len(evaluation.unknowns) == 2
    assert {outcome.missing_fact.split(" in ")[0] for outcome in evaluation.unknowns} == {
        "a decodable EIA value code",
        "a readable value on R24",
    }


def test_a_board_the_rule_ruled_nothing_on_is_not_a_pair():
    """An empty outcome list is "this board was not judged", not a clean pass."""
    project = ProjectModel(
        boards=[
            BoardModel(board=BoardRef(uuid="b1", title="Board1")),
            BoardModel(board=BoardRef(uuid="b2", title="Board2")),
        ]
    )
    rule = _RuledOnce()
    evaluation = evaluate_annotations(_aset([]), project, [rule])
    metric = _metrics(evaluation, "ruled-once")
    assert rule.boards_seen == 2, "the rule must be asked once per board"
    assert (metric.unknown_pairs, metric.outcome_pairs) == (1, 1)
    # The protocol is still implemented, so the four-state row is counts, not
    # "legacy": zeros are a verdict, a legacy row is the absence of one.
    assert metric.outcome_counts == {
        "VIOLATION": 0, "OK": 1, "UNKNOWN": 1, "NOT_APPLICABLE": 0,
    }
    text = render_text_report(
        [evaluation], split="dev", rule_ids=["ruled-once", "no-such-rule"]
    )
    assert re.search(r"ruled-once\s+1/1 = 1\.00", text)


def test_a_legacy_rule_stays_out_of_the_coverage_denominator():
    """No four-state protocol, no pair — the column says so instead of 0/0."""
    evaluation = evaluate_annotations(_aset([]), _model(), [_GoldenBare()])
    metric = _metrics(evaluation, "golden-bare")
    assert (metric.unknown_pairs, metric.outcome_pairs) == (0, 0)
    assert metric.outcome_counts is None
    text = render_text_report([evaluation], split="dev", rule_ids=["golden-bare"])
    assert (
        "legacy (no outcome protocol, so in no pair here): golden-bare" in text
    )


class _ThreeFindings(Rule):
    """One finding with a target, one with a ref in the text, one with neither."""

    id = "three-findings"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="ERROR",
                level=self.level,
                message="U1 is the wrong part",
                target=FindingTarget(component_ref="U1", pin_refs=["1"]),
            ),
            _plain_check_finding(self.id, "U1 pin2: the net is wrong", ["U1 pin2 @ GND"]),
            _plain_check_finding(self.id, "the board carries a flag nobody can walk to"),
        ]


def test_locate_success_counts_a_finding_with_no_target_in_the_denominator():
    """The finding nobody can locate is a miss, not an exclusion (017 sec.5).

    Three findings, two locatable — the structured target on the first, a
    designator in the evidence of the second. The third names no part at all and
    *must* enter the denominator, or the ratio would measure the rules that
    happen to be tidy instead of the rules that are.
    """
    evaluation = evaluate_annotations(_aset([]), _model(), [_ThreeFindings()])
    metric = _metrics(evaluation, "three-findings")
    assert (metric.findings_total, metric.findings_located) == (3, 2)
    assert metric.locate_rate == pytest.approx(2 / 3)
    text = render_text_report([evaluation], split="dev", rule_ids=["three-findings"])
    assert "designator, every severity: 2/3 = 0.67" in text
    assert re.search(r"three-findings\s+2/3 = 0\.67", text)


class _EmptyTarget(Rule):
    id = "empty-target"
    title = "test rule"
    level = "test"
    source = "house rule"

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message="the board carries a flag nobody can walk to",
                target=FindingTarget(),
            ),
            Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message="U1: a claim with a ref",
                evidence=["U1 pin1 @ VCC"],
            ),
        ]


def test_an_empty_target_locates_nothing_and_a_ref_still_does():
    evaluation = evaluate_annotations(_aset([]), _model(), [_EmptyTarget()])
    metric = _metrics(evaluation, "empty-target")
    assert (metric.findings_total, metric.findings_located) == (2, 1)


@pytest.mark.parametrize(
    "missing_fact,expected",
    [
        (
            "facts for U3 (mpn 'X', lcsc 'C1'): identify the part and record supply_pins",
            "shelf-part-unknown",
        ),
        (
            "facts for U3 (entry C2907329, mpn 'X', lcsc 'C1'): record supply_pins",
            "shelf-facts-missing",
        ),
        ("category and ldo facts for U8 (entry C9900097986, mpn 'MX1.25-LT-3')", "shelf-facts-missing"),
        ("ldo facts for U8: dropout_max_mv, input pin and output pin must all be present", "shelf-facts-missing"),
        (
            "must_connect target 'external 12MHz crystal network (XI)' on U1 pin7 is "
            "free text — connectivity alone cannot verify it",
            "free-text-target",
        ),
        (
            "a library resolver (bridge): board pins vs the library symbol's pin "
            "numbers, per part with an identity",
            "resolver-missing",
        ),
        ("library symbol for U1 (entry C114409, mpn 'STM32H743VIT6')", "resolver-missing"),
        ("a net on R24 pin1", "pin-net-unusable"),
        ("a net for U2 pin3 that is not a ground net (it is on 'GND' today)", "pin-net-unusable"),
        ("the pin has no net", "pin-net-unusable"),
        ("no source names the voltage of net 'VCC'", "domain-unknown"),
        ("the supply-pin net voltage for U2 (needed to decide whether mode 'x' is active)", "domain-unknown"),
        ("a known voltage on the far side of LED1's series resistor", "domain-unknown"),
        ("an oracle-approved series-resistance window for the 12 V domain", "window-undeclared"),
        ("an input-range fact for U5 pin4", "window-undeclared"),
        ("a two-sided input range for U5 pin4", "window-undeclared"),
        ("a readable value on R24", "value-unreadable"),
        ("a parseable value field on U1", "value-unreadable"),
        ("a readable value for capacitor C12", "value-unreadable"),
        ("a decodable EIA value code in the MPN of R24", "mpn-undecodable"),
    ],
)
def test_the_reason_vocabulary_reads_the_wording_the_rules_actually_use(
    missing_fact: str, expected: str
):
    """The categories are derived from real sentences, so they are pinned to them.

    Every string here is a ``missing_fact`` some rule in this repo writes (the
    shelf rules, the pin rulings, ``domain_of``'s why-not, the value readers).
    A rule that rewords one of them without a matching update here shows up as
    ``rule:<id>`` in the report — visible, which is the point — and this list is
    where the mapping is kept honest.
    """
    outcome = Outcome("some-rule", "UNKNOWN", "U1", missing_fact=missing_fact)
    assert unknown_reason_category(outcome) == expected


def test_an_unrecognised_wording_falls_back_to_the_rule_that_wrote_it():
    outcome = Outcome("brand-new-rule", "UNKNOWN", "U1", missing_fact="something nobody wrote before")
    assert unknown_reason_category(outcome) == "rule:brand-new-rule"
    # The fallback is a rule id, never a bucket called "other": the backlog line
    # is the rule whose wording the harness does not know yet.
    assert all(category != "other" for category, _pattern in UNKNOWN_REASON_PATTERNS)


def _cluster_report():
    class _Clustered(OutcomeRule):
        id = "clustered"
        title = "test rule"
        level = "test"
        source = "house rule"

        def check(self, model):
            return []

        def outcomes(self, model):
            return [
                Outcome(self.id, "UNKNOWN", "U1", missing_fact="a net on R24 pin1"),
                Outcome(self.id, "UNKNOWN", "U1", missing_fact="a net on R25 pin1"),
                Outcome(
                    self.id,
                    "UNKNOWN",
                    "U1",
                    missing_fact="a decodable EIA value code in the MPN of C1",
                ),
            ]

    evaluation = evaluate_annotations(_aset([]), _model(), [_Clustered()])
    return render_text_report([evaluation], split="dev", rule_ids=["clustered"])


def test_the_clusters_rank_by_size_and_show_what_is_inside_a_bucket():
    text = _cluster_report()
    assert "missing_fact clusters: 2 reason category(ies), by count:" in text
    # Two pin-net sentences collapse into one bucket of 2 with 2 distinct texts,
    # so "which fact to record next" can be read off the report: the sample
    # sentence is printed, and the distinct count says a sample is not the whole
    # bucket.
    assert "2  pin-net-unusable" in text
    assert "(2 distinct text(s))" in text
    assert "e.g. a net on R24 pin1" in text
    assert "1  mpn-undecodable" in text
    assert "(1 distinct text(s))" in text
    assert text.index("pin-net-unusable") < text.index("mpn-undecodable")


def test_the_cluster_list_is_a_top_n_and_says_how_many_it_left_out():
    """Nine categories, eight shown — the truncation is stated, not hidden."""
    texts = [
        "a net on R1 pin1",                                       # pin-net-unusable
        "a decodable EIA value code in the MPN of C1",            # mpn-undecodable
        "a readable value on R2",                                 # value-unreadable
        "an input-range fact for U5 pin4",                        # window-undeclared
        "facts for U3 (mpn 'X', lcsc 'C1'): identify the part and record supply_pins",
        "facts for U3 (entry C1, mpn 'X'): record supply_pins",   # shelf-facts-missing
        "library symbol for U1 (entry C1)",                       # resolver-missing
        "no source names the voltage of net 'VCC'",               # domain-unknown
        "must_connect target 'x' on U1 pin7 is free text",        # free-text-target
    ]

    class _Many(OutcomeRule):
        id = "many"
        title = "test rule"
        level = "test"
        source = "house rule"

        def check(self, model):
            return []

        def outcomes(self, model):
            return [
                Outcome(self.id, "UNKNOWN", f"U{n}", missing_fact=fact)
                for n, fact in enumerate(texts)
            ]

    evaluation = evaluate_annotations(_aset([]), _model(), [_Many()])
    text = render_text_report([evaluation], split="dev", rule_ids=["many"])
    section = text.split("missing_fact clusters")[1]
    assert "missing_fact clusters: 9 reason category(ies), top 8 by count:" in text
    assert section.count("e.g. ") == 8
    # The one left out is the last by the documented order: count descending,
    # then category name — with every count at 1, the alphabetically last.
    assert "window-undeclared" not in section
    assert "shelf-part-unknown" in section


def test_the_report_carries_the_provenance_a_run_has_to_record():
    """017 sec.5: every run records the tool and ruleset it measured with.

    Two rule segments, because a rule *improvement* -- the downstream action this
    batch feeds -- usually leaves the id list alone and always moves the sources.
    """
    text = _golden_report()
    assert f"ruleset {ruleset_fingerprint(['golden-outcome', 'golden-bare'])} " in text
    assert "over 2 rule id(s)" in text
    assert "tool boardwise " in text
    assert ruleset_fingerprint(["a", "b"]) != ruleset_fingerprint(["b", "a"])
    body = rulebody_fingerprint()
    assert body is not None, "a checkout has its rule sources on disk"
    assert re.search(rf"rulebody {body}\b", text)
    assert re.fullmatch(r"[0-9a-f]{8}", body)
    # And the default directory really is this repo's rules package (not, say,
    # the cwd) -- asserted against an absolute path, not against the function.
    repo_rules = Path(__file__).resolve().parents[1] / "src" / "boardwise" / "rules"
    assert body == rulebody_fingerprint(repo_rules)


def test_the_rule_body_digest_moves_when_a_rule_source_moves(tmp_path):
    """The ledger has to see a one-line rule change, not just a rule added.

    Recipe under test: every ``*.py`` directly in the directory, sorted by name,
    each contributing its name and its bytes (``src/boardwise/rules/``).
    """
    (tmp_path / "a.py").write_text("ID = 'a'\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("ID = 'b'\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not python\n", encoding="utf-8")
    before = rulebody_fingerprint(tmp_path)
    assert before is not None and re.fullmatch(r"[0-9a-f]{8}", before)
    assert rulebody_fingerprint(tmp_path) == before, "stable across runs"
    # A non-source file is not part of the rule body.
    (tmp_path / "notes.txt").write_text("still not python\n", encoding="utf-8")
    assert rulebody_fingerprint(tmp_path) == before
    # One character inside one rule moves it.
    (tmp_path / "b.py").write_text("ID = 'B'\n", encoding="utf-8")
    changed = rulebody_fingerprint(tmp_path)
    assert changed != before
    # And so does a rule that arrives (or moves between files).
    (tmp_path / "b.py").write_text("ID = 'b'\n", encoding="utf-8")
    assert rulebody_fingerprint(tmp_path) == before
    (tmp_path / "a.py").write_text("ID = 'a'\nRENAMED = True\n", encoding="utf-8")
    assert rulebody_fingerprint(tmp_path) != before


def test_a_build_without_rule_sources_says_so_instead_of_guessing(
    tmp_path, monkeypatch
):
    """Frozen: the sources are not shipped, and the report must not invent one.

    ``packaging/boardwise.spec`` puts the rules in the PYZ as bytecode and
    ``datas`` carries no ``.py``, so a frozen process cannot read its own rule
    bodies. The two things that must hold there: no exception, and a line that
    reads as *missing*, never as unchanged.
    """
    assert rulebody_fingerprint(tmp_path / "nowhere") is None
    assert rulebody_fingerprint(tmp_path) is None, "an empty directory is no source"
    monkeypatch.setattr(
        "boardwise.engines.review_eval.rulebody_fingerprint", lambda *a, **k: None
    )
    text = _golden_report()
    line = next(l for l in text.splitlines() if "provenance" in l)
    assert line.endswith("rulebody unavailable (frozen, no source)")
    assert "unavailable" in line


def test_fix_success_now_prints_the_registered_m3_numbers():
    """017 sec.5's slot was left unfilled on purpose; the M3 close-out fills it.

    What is pinned here is that the slot *reports*, and that it reports the
    register — one line per change kind, the total, and a rate next to every
    fraction. The numbers themselves are pinned by the register tests below;
    this one is about the report saying them.
    """
    text = render_text_report(
        [evaluate_annotations(_aset([]), _model(), [_GoldenOutcome()])],
        split="dev",
        rule_ids=["golden-outcome"],
    )
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if "fix success" in line)
    assert "pending" not in lines[start], "the slot is no longer a promise to fill later"
    # One line per registered kind plus the total; spelled out of the register's
    # own length so a newly registered kind cannot fall outside the window read
    # here (054's drawing kind was appended last and joined it that way).
    body = lines[start + 1 : start + 2 + len(FIX_SUCCESS_KINDS)]
    for kind in FIX_SUCCESS_KINDS:
        line = next(item for item in body if item.strip().startswith(kind))
        assert "applied+saved+resolved" in line
        assert "(source: tasks/" in line
    total = next(item for item in body if item.strip().startswith("total"))
    assert f"{FIX_SUCCESS_TOTAL[1]}/{FIX_SUCCESS_TOTAL[0]}" in total


def test_the_json_report_keeps_the_field_slots_017_asks_for(tmp_path):
    """017 sec.5, "先在 schema 里留字段": the slots exist before the numbers do.

    Run through the real CLI, because the JSON report is the CLI's own contract
    (the text report is the human one) — and because a field that only a unit
    test builds by hand is not a field the next task can find.
    """
    out = tmp_path / "review-eval.json"
    code = cli_main(
        [
            "review-eval",
            "--annotations",
            "reviewsets/ch340g_golden.json",
            "--split",
            "dev",
            "--json",
            str(out),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["fix_success"]["status"] == "registered"
    assert payload["fix_success"]["total"] == {
        "attempts": FIX_SUCCESS_TOTAL[0],
        "applied_saved_resolved": FIX_SUCCESS_TOTAL[1],
    }
    assert {row["kind"] for row in payload["fix_success"]["kinds"]} == set(FIX_SUCCESS_KINDS)
    assert payload["provenance"]["rule_count"] == len(BUILTIN_RULES)
    assert payload["provenance"]["ruleset"] == ruleset_fingerprint(
        [rule.id for rule in BUILTIN_RULES]
    )
    # Both rule segments, and the body one is the real source digest here (a
    # checkout), not a placeholder the frozen path would also print.
    assert payload["provenance"]["rulebody"] == rulebody_fingerprint()
    assert payload["provenance"]["rulebody"] is not None
    board = payload["boards"][0]
    coverage = board["unknown_coverage"]
    assert 0 < coverage["with_unknown"] <= coverage["pairs"]
    assert coverage["unknowns"], "the raw sentences are kept, not just their buckets"
    assert all(entry["reason"] for entry in coverage["unknowns"])
    per_rule = {rule["rule_id"]: rule for rule in board["rules"]}
    assert (
        per_rule["conn-nc-and-must-connect"]["findings_located"]
        <= per_rule["conn-nc-and-must-connect"]["findings_total"]
    )


# ---------------------------------------------------------------------------
# the register behind the slot (M3 close-out, extended by 054's drawing kind)
# ---------------------------------------------------------------------------
#
# The numbers below are the ones the six task books record (016 §十.7–§十.8,
# 029/035/036/037 §交卷记录, 054 §五 with its run reports), counted by hand from
# their own accounts. They are re-stated here as literals on purpose:
# a test that read its expectation out of the register would agree with any
# register, including one that had lost a case. The tests that follow check that
# every entry is *traceable* — to a file that exists, to a section that exists in
# it, to the live log where one is named, and to a file the repo itself tracks
# rather than one only this machine happens to have — because the only way this
# slot can lie is by citing something that was never written.

#: kind -> (attempts, applied+saved+resolved), as the task books record them.
FIX_SUCCESS_TOTAL = (17, 15)

FIX_SUCCESS_EXPECTED = {
    "component-value": (1, 1),
    "add-component": (4, 3),
    "patch-pin": (5, 4),
    "insert-subcircuit": (2, 2),
    "move-block": (2, 2),
    "draw-module": (3, 3),
}

ROOT = Path(__file__).resolve().parents[1]


def test_the_register_counts_the_cases_the_task_books_record():
    """One row per kind, and the counts are the task books' own."""
    rows = {row.kind: (row.attempts, row.applied_saved_resolved) for row in fix_success_rows()}
    assert rows == FIX_SUCCESS_EXPECTED
    assert fix_success_total() == FIX_SUCCESS_TOTAL


def test_the_register_covers_exactly_the_kinds_changeplan_can_execute():
    """The registered kinds and the plan kinds are one list, honest from both ends."""
    from boardwise.core.changeplan import SUPPORTED_KINDS

    assert set(FIX_SUCCESS_KINDS) == set(SUPPORTED_KINDS), (
        "a change kind with no registered live case (or a register row for a kind "
        "the format cannot execute) has to be decided, not left to drift"
    )
    assert tuple(FIX_SUCCESS_KINDS) == tuple(SUPPORTED_KINDS), "and in the same order"


def test_only_the_two_attempt_outcomes_count_as_attempts():
    """The counting rule, read off the vocabulary rather than restated.

    A designed refusal (stale, taken designator, full ladder), an idempotence
    replay, a killed daemon and an un-simulable shape are *not* failed repairs,
    and the register has to say so structurally — if one of them ever counts,
    this test is where it shows.
    """
    assert set(FIX_ATTEMPT_OUTCOMES) == {FIX_OUTCOME_APPLIED, FIX_OUTCOME_FAILED}
    for case in FIX_CASES:
        assert case.outcome in {
            FIX_OUTCOME_APPLIED, FIX_OUTCOME_FAILED, FIX_OUTCOME_REFUSED,
            FIX_OUTCOME_IDEMPOTENT, FIX_OUTCOME_INTERRUPTED,
            FIX_OUTCOME_NOT_SIMULABLE, FIX_OUTCOME_RECHECK,
        }, case


def _cited_paths(source: str) -> list[tuple[str, str]]:
    """`source` as (path, section) pairs, split the one way the citation reads.

    A `source` is fragments joined by ` + ` (`tasks/X.md §五 + outputs/Y.json`),
    the path is the fragment's first word, and a live-log citation carries a
    `:start-end` line range that the file name stops before. Every reader of a
    citation goes through here, so the two tests below cannot drift apart.
    """
    cited = []
    for fragment in source.split(" + "):
        path, _, where = fragment.partition(" ")
        if path.startswith("outputs/"):
            path = path.split(":")[0]
        cited.append((path, where))
    return cited


@pytest.mark.parametrize("case", FIX_CASES, ids=lambda c: f"{c.kind}-{c.case[:22]}")
def test_every_registered_case_cites_a_task_book_and_a_section(case):
    """Each entry's `source` names a file that exists and a section in it.

    Paragraph-number markers are checked as substrings of the task book's own
    text; the register's whole claim is "this is written down somewhere", so a
    citation that names nothing is the one failure mode worth a test.
    """
    for path, where in _cited_paths(case.source):
        assert path.startswith(("tasks/", "outputs/")), case.source
        file = ROOT / path
        assert file.is_file(), f"{case.kind}: cited {path}, which does not exist"
        if not path.startswith("tasks/"):
            continue
        assert where.strip(), f"{case.kind}: {path} is cited without a section"
        text = file.read_text(encoding="utf-8")
        # Every word of the section line has to be in the task book — "§交卷记录
        # round-3" pins both the section and *which round* of it, and an en dash
        # inside a marker ("§十.7–§十.8") is an alternative, not a word.
        for token in where.lstrip("§").replace("–", " ").split():
            assert token in text, (
                f"{case.kind}: {path} does not contain {token!r} — the citation "
                "points at something that is not in the task book"
            )


@pytest.fixture(scope="module")
def tracked_paths() -> set[str]:
    """Every path `git ls-files` claims — the index a clean checkout starts from.

    Asked once for the module, not once per case. `skip` rather than red when
    there is no git to ask (a source tree unpacked outside a checkout has no
    index): a test that cannot answer its own question must not answer "no".
    """
    if shutil.which("git") is None:
        pytest.skip("no `git` on PATH — whether a cited file is tracked is unanswerable")
    try:
        out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, cwd=ROOT)
    except OSError as exc:  # a `git` that cannot even be run is no git to ask
        pytest.skip(f"`git` is not runnable here ({exc})")
    if out.returncode != 0:
        pytest.skip(
            "not a git working tree — there is no index to check citations "
            f"against ({out.stderr.decode('utf-8', 'replace').strip()})"
        )
    return {path for path in out.stdout.decode("utf-8", "replace").split("\0") if path}


@pytest.mark.parametrize("case", FIX_CASES, ids=lambda c: f"{c.kind}-{c.case[:22]}")
def test_every_registered_case_cites_a_tracked_file(case, tracked_paths):
    """The cited file has to be *in the repo*, not merely on this machine.

    `outputs/` is git-ignored, so acceptance evidence there is only in the repo
    because someone force-added it: a citation can pass the test above on the
    machine that wrote the file and still be broken for every clean checkout.
    Asking the index instead moves that discovery to the machine that can still
    fix it — issue #9, where eleven 054/035d citations had never been `git
    add`ed. Only tracked-ness is checked here; existence and the section marker
    stay the test above's business, so one claim fails in one place.
    """
    for path, _ in _cited_paths(case.source):
        assert path in tracked_paths, (
            f"{case.kind}: cites {path}, which `git ls-files` does not claim — "
            "`git add -f` it (outputs/ is ignored), or a clean checkout fails "
            "where this machine passes"
        )


def test_a_kind_with_no_recorded_case_reports_nothing_rather_than_zero():
    """The empty register is the honest empty: `—`, and a null rate in JSON."""
    rows = fix_success_rows(cases=())
    assert [row.attempts for row in rows] == [0] * len(FIX_SUCCESS_KINDS)
    assert all(row.rate is None for row in rows)
    assert fix_success_total(cases=()) == (0, 0)
