"""Task 169: the PCB runner's ``except: continue`` is no longer silent.

166 left one thing behind on the PCB side. :func:`run_pcb_review` catches every
exception a rule raises and drops the rule — the report survives, which is the
口径 that stays — but it dropped it **without saying so**. A rule that raised
left exactly the same trace as a rule that ran and found nothing: it was missing
from that board's ``checksRun``, and the finding count was short by whatever it
would have said. The measured incident was a run in which
``pcb-polarity-orientation`` was simply absent — 59 rows became 57 — and it
could not be reproduced afterwards, because there was nothing left to look at.

The schematic side has had the channel since #30 fork 2
(``completion.coverage.rulesErrored``, written by
:func:`boardwise.engines.review._run_rules`). 169 gives the PCB runner the same
one rather than inventing a second vocabulary: the ``pcb_review`` section grows
a ``rules_errored`` list, and ``cli`` merges those ids into the **existing**
``rulesErrored`` the coverage gate already carries, so the verdict's ``verdictWhy``
clause and the console note speak about both walks.

Two groups:

* **一、the runner** — a rule that raises is named, the other rules are
  untouched, a rule that raises on **one** board still answers on the others,
  and 「nothing raised」 is an empty list rather than a missing key;
* **二、the report** — the offline ``checkup`` path carries the id into
  ``pcb_review.rules_errored`` **and** into ``completion.coverage.rulesErrored``,
  the real rules still produce their rows, and the console has a line the reader
  cannot miss.
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise import cli
from boardwise.engines.pcbreview import (
    BUILTIN_PCB_RULES,
    RUNNER_ID,
    run_pcb_review,
)
from boardwise.rules.base import Finding, FindingTarget
from boardwise.rules.pcb.base import PcbReviewContext, PcbRule

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"

#: The runner reads this at call time (``rule_list = BUILTIN_PCB_RULES if rules
#: is None else rules``), so injecting it here exercises the real call path.
BOOM_ID = "pcb-169-boom"
STANDIN_ID = "pcb-169-standin"


class _Boom(PcbRule):
    """A rule that always raises — the incident, made reproducible."""

    id = BOOM_ID
    title = "raise on purpose"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        raise RuntimeError("pcb-169-boom: this rule is broken on purpose")


class _StandIn(PcbRule):
    """A rule that always answers, so 「the rest still ran」 has something real."""

    id = STANDIN_ID
    title = "stand-in"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                message=f"stand-in row on {ctx.board_title}",
                level="L1-pcb-geometry",
                evidence=[f"{ctx.board_title} probe"],
                target=FindingTarget(component_ref="U1"),
            )
        ]


# --------------------------------------------------------------------------
# 一、the runner
# --------------------------------------------------------------------------


def test_a_raising_rule_is_named_and_the_other_rules_are_untouched():
    """The whole point: the id survives, and nothing else changes.

    ``checksRun`` still refuses to claim the broken rule ran (126a's contract),
    and the id now appears in ``rules_errored`` beside it — so a reader can tell
    「skipped because it raised」 from 「ran and found nothing」, which before 169
    was the same absence in two different costumes.
    """
    findings, section = run_pcb_review(FOC, rules=[_Boom(), _StandIn()])

    assert section is not None
    assert section["rules_errored"] == [BOOM_ID]
    # The working rule is completely unaffected: one row per PCB document, and
    # its id is the only thing in every board's checksRun. (1.0.0 carries two
    # PCB documents — ``PCB1`` and ``PCB2``.)
    assert [f.board for f in findings] == ["PCB1", "PCB2"]
    assert {f.rule_id for f in findings} == {STANDIN_ID}
    for board in section["boards"]:
        assert board["checksRun"] == [STANDIN_ID]
        assert BOOM_ID not in board["checksRun"]


def test_a_rule_that_raises_on_one_board_still_answers_on_the_others():
    """The flat list must not wipe out a rule's real rows elsewhere.

    A rule can raise on one PCB document and answer on the next — the two views
    differ per document — so 「named in ``rules_errored``」 and 「its rows are
    gone」 are not the same statement. The list is a disclosure about the run,
    not a verdict about the rule.
    """
    raised_on: list[str] = []

    class _Fragile(PcbRule):
        id = "pcb-169-fragile"
        title = "raise on PCB1 only"
        source = "house rule（岳 2026-10 待裁）"

        def check(self, ctx: PcbReviewContext) -> list[Finding]:
            if ctx.board_title == "PCB1":
                raised_on.append(ctx.board_title)
                raise ValueError("only 毕设FOC's PCB1 trips this")
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    message=f"survived on {ctx.board_title}",
                    level="L1-pcb-geometry",
                    evidence=[ctx.board_title],
                    target=FindingTarget(component_ref="U1"),
                )
            ]

    findings, section = run_pcb_review(FOC, rules=[_Fragile()])

    assert raised_on == ["PCB1"]
    assert section["rules_errored"] == ["pcb-169-fragile"]
    assert [f.board for f in findings] == ["PCB2"], "the other board still answers"
    by_title = {board["title"]: board for board in section["boards"]}
    assert by_title["PCB1"]["checksRun"] == []
    assert by_title["PCB2"]["checksRun"] == ["pcb-169-fragile"]


def test_a_rule_that_raises_on_two_boards_is_named_once():
    """Deduplicated: the list is 「which rules raised」, not a per-board tally."""
    _, section = run_pcb_review(FOC, rules=[_Boom()])
    assert section["rules_errored"] == [BOOM_ID]


def test_no_raise_is_an_empty_list_not_a_missing_key():
    """The section exists because rules ran, so the empty reading is real.

    Absent-not-empty is for facts about *whether* a step happened (126a's
    ``pcb_review`` itself, 166's ``pcbReviewNotRun``); this key says 「every rule
    that ran, answered」, which is a reading a run that ran rules always has.
    """
    _, section = run_pcb_review(FOC, rules=[_StandIn()])
    assert "rules_errored" in section
    assert section["rules_errored"] == []
    assert section["runner"] == RUNNER_ID


# --------------------------------------------------------------------------
# 二、the report
# --------------------------------------------------------------------------


def test_checkup_carries_pcb_rules_errored_into_the_section_coverage_and_a_note(
    capsys, tmp_path, monkeypatch
):
    """End to end on the real fixture: section + coverage + a console line.

    The broken rule is injected into :data:`BUILTIN_PCB_RULES` beside the real
    ones, so the assertion 「其余规则结果不受影响」 is made against the real rule
    set: ``pcb-mcu-supply-groups`` (131e) still produces its 毕设FOC rows while
    the broken rule is named. The id reaches the report twice — once in the
    section that owns it, once in the coverage gate that already had the
    channel — and the console carries a line naming the PCB walk.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "boardwise.engines.pcbreview.BUILTIN_PCB_RULES",
        [*BUILTIN_PCB_RULES, _Boom()],
        raising=True,
    )
    out = tmp_path / "pcb-169"
    cli.main([
        "checkup", "--file", str(FOC), "--out", str(out), "--library", str(SHELF),
    ])
    console = capsys.readouterr().out
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    section = report["pcb_review"]
    assert section["rules_errored"] == [BOOM_ID]
    assert section["runner"] == RUNNER_ID
    # The disclosure is in the coverage gate too, under the key that was already
    # there — no second vocabulary was invented for the PCB walk.
    assert report["completion"]["coverage"]["rulesErrored"] == [BOOM_ID]
    # ... and the broken rule contributes no rows at all (it raised), while the
    # real rules are unaffected.
    assert not [row for row in report["findings"] if row["rule_id"] == BOOM_ID]
    assert [
        row for row in report["findings"] if row["rule_id"] == "pcb-mcu-supply-groups"
    ], "131e's rule still produces its rows beside a broken one"
    for board in section["boards"]:
        assert BOOM_ID not in board["checksRun"]
    # The visible line: on the console, and in the report's own notes.
    assert "条规则执行出错" in console
    assert BOOM_ID in console
    assert "PCB 审查" in console
    notes = report["source"]["notes"]
    assert any(
        "条规则执行出错" in note and BOOM_ID in note and "PCB 审查" in note
        for note in notes
    ), notes
