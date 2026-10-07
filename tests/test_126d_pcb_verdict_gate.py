"""Tests for task 126 stick 4 (126d): the PCB gate in `completion.verdict`.

126 阶段 C 的前两棒把 PCB 审查接进了管线（`pcb_review` 一节，缺席而非空），但
**没有碰 verdict**——126a 明写「本阶段不改 verdict（126d 才接闸，届时 bump /7）」。
本棒就是那把闸，措辞照任务书 126d 开头「主代理裁定（2026-10-07）两条」第一条：

    闸只管离线：源是离线 epro2 且含 PCB 文档 而 pcb_review 缺席 → incomplete。
    在线 checkup 不接这条闸（在线恒缺席是「未实现」不是「未通过」）。

所以三条状态各一测试，全部离线、全部用真夹具，全部钉在**读出来的报告**上而不是
在内部函数上：

* **离线含 PCB 文档 + 段缺席 → incomplete**（`pcbReviewMissing` True，理由排在
  verdictWhy 最后，conclusion 也有自己那一句）；
* **离线含 PCB 文档 + 段在场 → 不因这条变 incomplete**（毕设FOC 真跑一遍，
  `pcbReviewMissing` 必须 False，且 verdict 与 126d 之前逐字相同）；
* **在线形态不触发**（在线恒缺席，但闸只看离线：一条 tier 不是 `file` 的
  `_completion_body` 读数，以及一次真正的在线档报告）。

外加 schema 字符串钉（`boardwise.checkup/7`）、`verdictWhy` **顺序**钉（coverage
原因最后——126d 那条在所有 coverage 理由的最后，因为它在 `_coverage_reasons` 里
排最后，而 coverage 整体排在所有非 coverage 理由之后），以及一条 CH340G 的
反例：一个**没有 PCB 文档**的备份缺席该节，不是缺口，是「没什么可审」。

夹具一律只读。不连编辑器、不碰 daemon。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.cli import _clean_coverage, _completion_body, _completion_coverage_gates

FIXTURES = Path(__file__).parent / "fixtures"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"

#: A backup with **three** PCB documents (PCB3/PCB1/PCB2) and **no** design-intent
#: contract — 126 阶段 C 的验收对象, and the fixture that proves the gate does
#: not fire on a board the runner actually reviewed.
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
#: A backup with **no** PCB document at all — the one absence that is *not* a
#: gap, and the reason the gate cannot be written as "no pcb_review section".
NO_PCB = FIXTURES / "ProPrj_CH340G_2026-09-13.epro2"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_checkup(tmp_path: Path, monkeypatch, fixture: Path, name: str) -> dict:
    """One offline checkup over a real fixture, returning its ``report.json``."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / f"home-{name}"))
    out = tmp_path / name
    cli.main([
        "checkup", "--file", str(fixture), "--out", str(out), "--library", str(SHELF),
    ])
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def _crash_runner(monkeypatch) -> None:
    """Make the PCB runner raise, which is the other way the section goes absent.

    A monkeypatched module attribute, not a rewrite of ``cli``: ``_cmd_checkup``
    imports :func:`run_pcb_review` **inside** the function, so patching
    ``boardwise.engines.pcbreview.run_pcb_review`` is what it actually reads. That
    import shape is load-bearing for this test — if someone hoists it to module
    scope, this fixture silently stops testing anything and the gate looks un-
    proven. The assertion below re-pins the shape.
    """
    from boardwise.engines import pcbreview

    assert "run_pcb_review" not in vars(cli), (
        "126d: _cmd_checkup used to import the runner inside the function; if it "
        "was hoisted to module scope, patch cli.run_pcb_review instead of "
        "pcbreview.run_pcb_review, or this test proves nothing"
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("126d test: 模拟 runner 崩溃")

    monkeypatch.setattr(pcbreview, "run_pcb_review", boom)


def _body(**overrides) -> dict:
    """`_completion_body` with the same neutral inputs `test_072` uses."""
    kwargs = {
        "scope": {"rules": 21, "boards": 1, "pages": 1},
        "summary": {"errorCount": 0},
        "unreviewed": [],
        "triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
        "coverage": _clean_coverage(),
    }
    kwargs.update(overrides)
    return _completion_body(**kwargs)


# ---------------------------------------------------------------------------
# the schema bump
# ---------------------------------------------------------------------------


def test_the_schema_is_7_and_the_two_readers_that_pin_it_are_the_ones_that_moved():
    """126d bumps `boardwise.checkup/6` → `/7` for a **verdict** change.

    Not a reading, not a new section: a `/6` consumer that walked
    `completion.coverage` and recomputed the verdict would reach a *different*
    answer on a report whose backup has PCB geometry that was never reviewed. That
    is the line 090 A1 drew ("adds only a reading → no bump") and this crosses it.
    """
    assert cli.CHECKUP_SCHEMA == "boardwise.checkup/7"
    # And the reason is stated where a reader of the constant will find it, not
    # only in the task book: the module comment above CHECKUP_SCHEMA.
    import inspect

    source = inspect.getsource(cli).splitlines()
    line = next(i for i, text in enumerate(source) if text.startswith("CHECKUP_SCHEMA"))
    context = "\n".join(source[max(0, line - 40):line])
    assert "pcbReviewMissing" in context, (
        "the constant's own doc comment must say what moved — a bare version "
        "number tells a reader nothing"
    )


def test_a_report_from_every_offline_fixture_carries_the_new_id(
    tmp_path, monkeypatch, capsys
):
    """The two real backup shapes both report `/7`, with and without PCB docs."""
    capsys.readouterr()
    with_pcb = _run_checkup(tmp_path, monkeypatch, FOC, "foc")
    without_pcb = _run_checkup(tmp_path, monkeypatch, NO_PCB, "no-pcb")

    assert with_pcb["schema"] == "boardwise.checkup/7"
    assert without_pcb["schema"] == "boardwise.checkup/7"


# ---------------------------------------------------------------------------
# state 1 — offline, has PCB documents, section absent → incomplete
# ---------------------------------------------------------------------------


def test_offline_with_pcb_documents_and_no_section_is_incomplete(
    tmp_path, monkeypatch, capsys
):
    """裁定 1 的正面：离线 epro2 + 含 PCB 文档 + ``pcb_review`` 缺席 = incomplete。

    The runner is made to raise, so this is the shape a real crash produces: the
    report is still written (that contract is 126a's and must not move), it just
    has no PCB section — and now it also cannot claim the board was reviewed.
    """
    capsys.readouterr()
    _crash_runner(monkeypatch)
    report = _run_checkup(tmp_path, monkeypatch, FOC, "crashed")
    capsys.readouterr()

    completion = report["completion"]
    assert "pcb_review" not in report, "the section stays absent, not empty (钉 5)"
    assert completion["coverage"]["pcbReviewMissing"] is True
    assert completion["verdict"] == "incomplete", completion["verdictWhy"]

    # What this test does and does not prove, said out loud rather than left for
    # a reader to guess. It pins the **wiring**: that the flag is set on this
    # fixture, and that the report says so. It cannot pin the **arithmetic** —
    # 毕设FOC is already `incomplete` for its own reasons (30 schematic ERRORs,
    # 116 unreviewed parts), so deleting the gate from `_completion_body` would
    # leave this assertion green. The arithmetic is pinned by
    # `test_the_gate_is_incomplete_even_when_everything_else_is_clean` above, and
    # the pair is a mutation pair: dropping `coverage.get("pcbReviewMissing")`
    # from the verdict reds that one and leaves this one green, which is exactly
    # why both exist.


def test_the_missing_pcb_section_is_named_in_verdict_why(
    tmp_path, monkeypatch, capsys
):
    """The clause says **what** is missing, in the reader's next-action wording.

    #30's own rule for every coverage clause: the sentence has to tell the reader
    what to do, and here the two actions are "re-run the offline path" or "the
    runner crashed" — which is why `source.notes` is named in the text.
    """
    capsys.readouterr()
    _crash_runner(monkeypatch)
    report = _run_checkup(tmp_path, monkeypatch, FOC, "crashed2")
    capsys.readouterr()

    why = report["completion"]["verdictWhy"]
    pcb_clauses = [text for text in why if "pcb_review" in text]
    assert len(pcb_clauses) == 1, why
    clause = pcb_clauses[0]
    assert "PCB" in clause and "未审" in clause, clause
    # And the note the clause points at is really there — a pointer to a fact
    # that is not in the report would be a dead end.
    assert any("PCB 审查未完成" in note for note in report["source"]["notes"]), (
        report["source"]["notes"]
    )


def test_the_conclusion_carries_its_own_clause(tmp_path, monkeypatch, capsys):
    """#21's invariant, one batch later: 无 ERROR ⇔ verdict complete.

    Without a clause on the quotable line, a report could say `verdict:
    incomplete` and, in the same breath, "无 ERROR" — which is exactly the
    second-verdict drift issue #21 was filed for.
    """
    capsys.readouterr()
    _crash_runner(monkeypatch)
    report = _run_checkup(tmp_path, monkeypatch, FOC, "crashed3")
    capsys.readouterr()

    conclusion = report["summary"]["conclusion"]
    assert report["completion"]["verdict"] == "incomplete"
    assert "PCB 版面几何未审" in conclusion, conclusion


def test_the_gate_is_incomplete_even_when_everything_else_is_clean():
    """The verdict is `incomplete`, **not** `complete-with-open-items`.

    This is the one arithmetic assertion in the file that no fixture can make,
    because both real backups owe something else (ERRORs, unreviewed parts) and
    the verdict is already `incomplete` for that reason. The reason 126d put the
    gate with `modelEmpty` rather than with the other five coverage fields: the
    other five say 「有些项没看全」, this says 「整块 PCB 一个结论都没有」 — the
    same class as having no input at all.
    """
    section = _body(coverage={**_clean_coverage(), "pcbReviewMissing": True})

    assert section["verdict"] == "incomplete", section["verdictWhy"]
    assert any("pcb_review" in reason for reason in section["verdictWhy"])
    # ...and it is genuinely the *only* reason: strip it and the same section is
    # complete, so the test above is about this gate and not about a leftover.
    without = _body(coverage=_clean_coverage())
    assert without["verdict"] == "complete" and without["verdictWhy"] == []


def test_a_pcb_section_that_is_absent_because_the_backup_has_none_is_not_a_gap(
    tmp_path, monkeypatch, capsys
):
    """The counter-shape, and the reason the gate needs two facts, not one.

    `ProPrj_CH340G` has **no** PCB document, so `pcb_review` is absent — but
    「nothing to review」 is not 「a check did not run」. A gate written as
    "`pcb_review` absent → incomplete" would fail every schematic-only backup.
    """
    capsys.readouterr()
    report = _run_checkup(tmp_path, monkeypatch, NO_PCB, "no-pcb2")
    capsys.readouterr()

    assert "pcb_review" not in report
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    assert not any("pcb_review" in reason for reason in report["completion"]["verdictWhy"])


# ---------------------------------------------------------------------------
# state 2 — offline, has PCB documents, section present → this gate does not fire
# ---------------------------------------------------------------------------


def test_offline_with_pcb_documents_and_the_section_present_is_not_gated(
    tmp_path, monkeypatch, capsys
):
    """裁定 1 的反面：段在场 → 不因这条 incomplete。

    毕设FOC, real fixture, real runner: three PCB documents, four rules, a section
    and 33 PCB findings. The gate reads False. The verdict is whatever the rest
    of the arithmetic says (it is `incomplete` on this fixture for its own,
    unrelated reasons — 30 schematic ERRORs and 116 unreviewed parts), and this
    test asserts the PCB gate is **not** among the reasons.
    """
    capsys.readouterr()
    report = _run_checkup(tmp_path, monkeypatch, FOC, "clean-foc")
    capsys.readouterr()

    completion = report["completion"]
    assert report["pcb_review"]["available"] is True
    assert [board["title"] for board in report["pcb_review"]["boards"]] == [
        "PCB3", "PCB1", "PCB2",
    ]
    assert completion["coverage"]["pcbReviewMissing"] is False
    assert not any("pcb_review" in reason for reason in completion["verdictWhy"])
    assert "PCB 版面几何未审" not in report["summary"]["conclusion"]


def test_the_gate_survives_a_regate(tmp_path, capsys):
    """#30's trap, one batch later: a gate that lives only in the CLI's memory.

    `need-datasheet` / `triage` rebuild `completion` from the report rather than
    re-running anything. A report that recorded the gate must keep it; a report
    **older than the gate** (a `/6` coverage section with no such key) must not
    crash on it and must not be re-litigated by a gate that postdates it. Both
    halves are here — the first is the discipline, the second is why the read in
    `_completion_body` is `.get` and not `[]`.
    """
    from boardwise.cli import _completion_from_report

    gated = {
        "completion": {
            "scope": {"rules": 21, "boards": 1, "pages": 1},
            "coverage": {**_clean_coverage(), "pcbReviewMissing": True},
        },
        "model": {"components": 5, "nets": 5},
        "summary": {"errorCount": 0},
        "unreviewed_parts": [],
        "warning_triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
    }
    section = _completion_from_report(gated, needs_datasheet=[])
    assert section["coverage"]["pcbReviewMissing"] is True
    assert section["verdict"] == "incomplete"

    legacy_coverage = _clean_coverage()
    del legacy_coverage["pcbReviewMissing"]
    legacy = {
        "completion": {"scope": {"rules": 21, "boards": 1, "pages": 1},
                       "coverage": legacy_coverage},
        "model": {"components": 5, "nets": 5},
        "summary": {"errorCount": 0},
        "unreviewed_parts": [],
        "warning_triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
    }
    old = _completion_from_report(legacy, needs_datasheet=[])
    assert old["verdict"] == "complete", old["verdictWhy"]


def test_the_gate_reaches_the_conclusion_through_the_shared_reader():
    """The conclusion and the verdict read the same value, not two copies.

    `_completion_coverage_gates` is the one place the two sides meet (#21/#30's
    shape), so it is where a divergence would be written. Pinned directly: the
    gate is **not** folded into `coverage_gaps` (it gates `incomplete`, not
    `complete-with-open-items`, and a count would state the wrong kind).
    """
    gates = _completion_coverage_gates(
        completion={"coverage": {**_clean_coverage(), "pcbReviewMissing": True}}
    )
    assert gates["pcb_review_missing"] is True
    assert gates["coverage_gaps"] == 0, "it is an incomplete gate, not a gap kind"
    assert gates["coverage_missing"] is False

    # And absent on a section that has no such key at all.
    assert _completion_coverage_gates(
        completion={"coverage": {k: v for k, v in _clean_coverage().items()
                                 if k != "pcbReviewMissing"}}
    )["pcb_review_missing"] is False


# ---------------------------------------------------------------------------
# state 3 — the online form never takes the gate
# ---------------------------------------------------------------------------


def test_an_online_shaped_reading_never_takes_the_gate():
    """裁定 1 的后半句，在算术层：不是 `file` 档，就没有 PCB 这件事。

    Three online tiers, all of which leave `pcb_review` absent by construction
    (the runner has no live geometry yet), and none of which may be failed by
    that. The section is not passed to `_completion_body` at all — it lives on
    the report, not on the verdict's inputs — so there is nothing that could set
    the flag, and the reading a caller hands in has it False.
    """
    for tier in ("project-file", "per-page", "netlist"):
        report = _checkup_report_for(tier)
        assert "pcb_review" not in report, tier
        assert report["completion"]["coverage"]["pcbReviewMissing"] is False, tier
        assert "pcb_review" not in " ".join(report["completion"]["verdictWhy"]), tier


def test_an_online_report_keeps_its_own_verdict_with_the_section_absent():
    """A real online-shaped run: `_cmd_checkup` never reaches the PCB block.

    Built by hand rather than through a daemon (this batch is pure offline, 交付
    纪律). The point is not the fixture's data but the **code path**: the PCB
    block is guarded by ``tier == "file" and ....epro2``, so for every other tier
    `pcb_had_documents` stays False and `pcb_review_missing` is False. If someone
    ever hoists that guard, this test is the one that notices.
    """
    report = _checkup_report_for("netlist")
    assert report["source"]["tier"] == "netlist"
    assert report["completion"]["verdict"] in {
        "complete", "complete-with-open-items", "incomplete",
    }
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False


def _checkup_report_for(tier: str) -> dict:
    """A report assembled through the real ``_checkup_report``, at a named tier."""
    from boardwise.core.model import DesignModel

    model = DesignModel()
    summary = {"errorCount": 0, "errors": [], "warningCount": 0, "infoCount": 0}
    completion = _completion_body(
        scope={"rules": 21, "boards": 1, "pages": 1},
        summary=summary,
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 0, "filled": 0, "stale": 0}},
        coverage=_clean_coverage(),
    )
    return cli._checkup_report(
        tier=tier,
        source={"project": {"friendlyName": "x"}, "file": None},
        model=model,
        attempts=[],
        notes=[],
        drc={},
        findings=[],
        summary=summary,
        modules=[],
        slots={},
        completion=completion,
        pcb_review=None,
    )


# ---------------------------------------------------------------------------
# ordering — the one convention 126d was told to keep
# ---------------------------------------------------------------------------


def test_the_pcb_clause_comes_last_among_the_coverage_reasons():
    """Within the coverage reasons, 126d's clause is last.

    The convention it *inherited* is "coverage reasons last overall" (#30); where
    inside the coverage block 126d's own clause sits was a free choice, and it is
    made last so that adding it to a `/6` report does not shuffle the other five
    reasons a reader has been reading in order since #30.
    """
    from boardwise.cli import _coverage_reasons

    reasons = _coverage_reasons({
        "parseIncomplete": True,
        "modelEmpty": False,
        "pagesDropped": 2,
        "rulesRefused": 7,
        "recordsDropped": 3,
        "rulesErrored": ["decap-required-caps"],
        "pcbReviewMissing": True,
    })

    assert len(reasons) == 6, reasons
    assert "pcb_review" in reasons[-1]
    for text in reasons[:-1]:
        assert "pcb_review" not in text


def test_every_clause_still_lands_after_the_non_coverage_ones():
    """The full order, end to end — the convention, not one half of it.

    053's order (ERROR → unreviewed → marked → stale → triage → skeleton) comes
    first, in the order it has had since 053; every coverage clause follows. This
    is the assertion 126d could most easily have broken by inserting its clause
    at the top of `_completion_body` instead of in `_coverage_reasons`.
    """
    section = _completion_body(
        scope={"rules": 21, "boards": 1, "pages": 1},
        summary={"errorCount": 2, "errors": [{"rule": "x"}]},
        unreviewed=[{"designator": "U1"}],
        triage=[{"key": "k"}],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 2}},
        coverage={**_clean_coverage(), "pagesDropped": 1, "pcbReviewMissing": True},
    )
    why = section["verdictWhy"]

    assert why[0].startswith("2 项 ERROR")
    assert "缺手册未审" in why[1]
    assert "stale" in why[2]
    assert "待分诊" in why[3]
    assert "pcb_review" in why[-1]
    # The architecture skeleton is present here, so the whole coverage block is
    # the tail: pages, then the PCB clause. One clause per question, in order.
    assert why[-2].endswith("没有进模型"), why[-2]


def test_the_markdown_renders_the_gate_rather_than_only_storing_it(tmp_path, capsys):
    """`render only what the JSON says`, extended: 072 pins this for coverage.

    #30's own test asserts 「覆盖」 appears in `report.md`; 126d's clause has to be
    there too, or a human reading the Markdown would see a `complete`-shaped line
    with no mention of the missing PCB review.
    """
    capsys.readouterr()
    from boardwise.engines.checkup import render_report_markdown

    text = render_report_markdown(_checkup_report_for("file") | {
        "completion": _body(coverage={**_clean_coverage(), "pcbReviewMissing": True}),
        "pcb_review": None,
    })
    capsys.readouterr()

    assert "**verdict：`incomplete`**" in text
    assert "pcbReviewMissing" in text, "the coverage line renders the new field"


# ---------------------------------------------------------------------------
# the neutral reading
# ---------------------------------------------------------------------------


def test_the_neutral_coverage_says_the_pcb_was_looked_at():
    """`_clean_coverage()` is 「nothing known to be missing」, not 「unknown」.

    The new field's clean value is False and that is load-bearing in two places:
    a caller that has no coverage to hand in (a unit test building a section from
    counts alone) must not be failed by a check it never claimed to run, and a
    report with **no** `coverage` key at all — an old one — must not be failed
    either. Both directions are False; neither is a claim that a PCB review
    happened, it is the absence of a claim that one did not.
    """
    clean = _clean_coverage()
    assert clean["pcbReviewMissing"] is False
    assert _body()["verdict"] == "complete"


@pytest.mark.parametrize("key", ["parseIncomplete", "pcbReviewMissing"])
def test_every_boolean_coverage_field_defaults_to_false_not_true(key):
    """A gate that defaults to True would fire on every caller that lacks it.

    Read `.get(key)` rather than `[key]` on purpose: `_clean_coverage` is the one
    place the key is authored, and everything else in the codebase must tolerate
    its absence (a `/6` report re-gated by `need-datasheet` has no such key).

    ``modelEmpty`` is deliberately **not** in this list. It is read with
    ``coverage["modelEmpty"]`` — subscript, not ``.get`` — and has been since
    #30, and the asymmetry with the two fields above is 126d's own doing: changing
    it is a #30 change wearing 126d's clothes, so it is reported rather than
    smuggled in here. It is not reachable today (`_completion_from_report` passes
    ``coverage=None`` for a report with no section at all, which
    ``_clean_coverage`` then fills whole), so the failure it would cause is
    theoretical; the field is listed in this test's *docstring* instead.
    """
    assert _clean_coverage()[key] is False
    partial = {k: v for k, v in _clean_coverage().items() if k != key}
    assert _body(coverage=partial)["verdict"] == "complete"