"""166: the online `checkup` reviews the PCB too — and says so when it cannot.

The field finding this batch answers, measured on another machine: one and the
same board, `checkup --file <export>` reported 17 findings and the online
`checkup` reported **0** — while its report still claimed full coverage. Two
mechanisms, both silent:

* the `pcb_review` section was gated on ``tier == "file"``, so the online path
  never entered the runner at all;
* ``completion.coverage.pcbReviewMissing`` was hard-``False`` online (126d's
  ruling: online was 「未实现」, not 「未通过」), so nothing in the report said the
  board's layout had not been read.

The ruling's reasoning was sound and its consequence was not: a report that says
nothing about a check it never ran is a *silent completeness lie*, which is the
failure this repository's coverage section exists to prevent.

What these tests pin, in the two halves the batch has:

* **B, the closure** — the online project-file tier now hands the archive it
  downloaded (`sys.get_project_file` → base64 → bytes, already parsed for the
  schematic model) to the **same** runner the offline path uses, and the
  resulting `pcb_review` section is the offline one: same boards, same checks
  run, same findings. Tested by running both paths over one archive in one
  process and comparing them row for row, not by counting findings — a count
  would pass on a second, slightly different rule set;
* **A, the honest degradation** — the runs that *cannot* review the board
  (per-page / netlist tiers, an archive with no PCB document, a runner that
  raised) disclose it in ``completion.coverage.pcbReviewNotRun`` and in
  `source.notes`, and the disclosure moves **no verdict**: 126d's gate stays
  offline-only. Tested for each of the three ways an online run ends up without
  a section, plus a unit test on the section's own absent-not-empty shape.

The editor is the fake client `tests/test_checkup_cli.py` established (the
ladder under test is real, the archives are real `.epro2` fixtures); nothing here
touches a daemon, and the PCB-bearing fixture is used **read-only**.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_checkup_cli as base  # noqa: E402 — the fake bridge, reused, not respelled
from boardwise.cli import (
    PCB_ONLINE_HINT,
    _clean_coverage,
    _cmd_checkup,
    _coverage_section,
)
from boardwise.core.geometry import ParseStats
from boardwise.core.model import DesignModel

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The archive that makes the difference measurable: a real project export with a
#: PCB document (PCB1 / 49 placements / 4 copper layers) — the golden CH340
#: fixture the checkup tests use carries none, which is exactly why the online
#: gap went unnoticed there for so long.
PCB_ARCHIVE = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"

#: The runner identity the section must carry — the *same* engine both paths use.
PCB_RUNNER = "boardwise.engines.pcbreview"

fake_bridge = base.fake_bridge  # the isolation fixture (BOARDWISE_HOME + fake client)


def _answers(*, project_refusal: bool = False, page_blob: bytes | None = None,
             archive: bytes | None = None, drc: bool = True) -> dict:
    """The fake daemon's answers, with a PCB-bearing project archive by default.

    `_live_answers` is the established ladder fixture; only the *archive* differs
    here, because that is the whole variable this batch moves. A caller that wants
    a per-page fallback passes `project_refusal=True` and a page blob; one that
    wants the no-PCB-document path passes the golden archive.
    """
    answers = base._live_answers(
        project_refusal=project_refusal, page_blob=page_blob, drc=drc
    )
    if not project_refusal:
        blob = PCB_ARCHIVE.read_bytes() if archive is None else archive
        answers["sys.get_project_file"] = base._archive_payload(
            blob, scope="project", name=PCB_ARCHIVE.name
        )
    return answers


def _checkup(path: Path, **overrides) -> int:
    return _cmd_checkup(base._checkup_args(out=str(path), **overrides))


def _report(path: Path) -> dict:
    return json.loads((path / "report.json").read_text(encoding="utf-8"))


def _pcb_rows(report: dict) -> list[tuple]:
    """The PCB findings of a report, as comparable rows.

    Read out of the merged ``findings[]`` through the section's own index list —
    which is the contract `pcb_review.boards[].findings` exists for — rather than
    by filtering on the ``pcb-`` prefix, so a section whose indices had drifted
    off its own findings would fail this rather than pass it.
    """
    rows = []
    for board in report.get("pcb_review", {}).get("boards", []):
        for index in board["findings"]:
            finding = report["findings"][index]
            rows.append((
                board["title"], finding["rule_id"], finding["severity"],
                finding["message"], tuple(finding.get("refs") or ()),
                finding.get("board"),
            ))
    return rows


# --------------------------------------------------------------------------
# B: one archive, one pipeline, two entry points
# --------------------------------------------------------------------------


def test_the_live_run_reviews_the_pcb_out_of_the_project_archive(
    fake_bridge, tmp_path, capsys
):
    """The field defect, closed: a live `checkup` produced a real PCB section.

    Measured against the offline reading of the **same archive** — the claim is
    not "some PCB findings appeared", it is "the online and offline readings of
    one board are the same reading". `drc=False` keeps the comparison exact: the
    host DRC stage is a different question with its own sections, and its rule-set
    meta-audit can add rows of its own to `findings[]`, which would move the
    section's indices without touching its content (the run below, with the DRC
    stage on, pins that separately).
    """
    base._FakeBridgeClient.answers = _answers(drc=False)
    online_dir = tmp_path / "online"

    assert _checkup(online_dir) == 3, (
        "073: this fixture's verdict is incomplete for its own reasons "
        "(unreviewed parts) — the PCB section is what this test is about"
    )
    printed = capsys.readouterr().out

    online = _report(online_dir)
    assert online["source"]["tier"] == "project-file"
    section = online["pcb_review"]
    assert section["runner"] == PCB_RUNNER, "the online path must not carry its own runner"
    assert section["available"] is True
    assert [b["title"] for b in section["boards"]] == ["PCB1"]
    assert section["boards"][0]["components"] == 49
    assert section["boards"][0]["copperLayers"] == 4
    assert section["boards"][0]["boardUuid"] == "258938d3e4719586", (
        "the META link that lets the integrated report put PCB1 under Board1"
    )
    assert section["boards"][0]["findings"], "a board with 49 placements is not clean"

    # The offline half: the very same archive through `--file`, in this process.
    offline_dir = tmp_path / "offline"
    assert _checkup(offline_dir, file=str(PCB_ARCHIVE)) == 3
    offline = _report(offline_dir)

    assert offline["pcb_review"]["boards"] == section["boards"], (
        "boards[] carries title / boardUuid / counts / checksRun / finding indices; "
        "one archive read twice must answer all five identically"
    )
    assert _pcb_rows(online) == _pcb_rows(offline), (
        "the online PCB findings must be the offline PCB findings — same rules, "
        "same messages, same refs, same board attribution"
    )
    assert "PCB 审查：" in printed and "条 finding 已并入 findings[]" in printed
    # Not a disclosure case: the review ran, so there is nothing to disclose.
    assert "pcbReviewNotRun" not in online["completion"]["coverage"]


def test_a_live_run_with_the_drc_stage_on_still_carries_the_same_pcb_reading(
    fake_bridge, tmp_path
):
    """The same archive with the host DRC stage on — the *real* online shape.

    The DRC stage's rule-set meta-audit can append its own rows to `findings[]`
    before the PCB merge, so the section's indices shift. The content must not:
    the board's own numbers and its finding rows are compared to the offline
    reading again, this time through the index list rather than by equality of the
    two boards[] entries.
    """
    base._FakeBridgeClient.answers = _answers()
    online_dir = tmp_path / "online"
    assert _checkup(online_dir) == 3
    online = _report(online_dir)

    assert online["pcb_review"]["boards"][0]["components"] == 49
    assert online["pcb_review"]["runner"] == PCB_RUNNER
    assert online["drc"]["pcb"]["checked"] is True, "the DRC stage really ran here"

    offline_dir = tmp_path / "offline"
    assert _checkup(offline_dir, file=str(PCB_ARCHIVE)) == 3
    offline = _report(offline_dir)

    assert online["pcb_review"]["boards"][0]["checksRun"] == (
        offline["pcb_review"]["boards"][0]["checksRun"]
    )
    assert _pcb_rows(online) == _pcb_rows(offline)
    for index in online["pcb_review"]["boards"][0]["findings"]:
        assert online["findings"][index]["rule_id"].startswith("pcb-"), (
            "the index list must resolve inside **this** report, after whatever "
            "the DRC stage contributed"
        )
    assert "pcbReviewNotRun" not in online["completion"]["coverage"]


# --------------------------------------------------------------------------
# A: the three ways a live run ends up without a PCB section
# --------------------------------------------------------------------------


def test_a_live_run_without_the_project_archive_discloses_the_missing_pcb_review(
    fake_bridge, tmp_path, capsys
):
    """The per-page fallback: no whole-project archive, so no PCB to read.

    This is the tier the field machine's permission gate can produce, and it is
    where silence used to be complete — the run exits 3 for unrelated reasons and
    says nothing at all about the layout. Now both channels speak: the JSON
    (`coverage.pcbReviewNotRun`) and the human ones (a `source.notes` line, which
    `report.md` renders, and the console).
    """
    base._FakeBridgeClient.answers = _answers(
        project_refusal=True, page_blob=base._document_archive()
    )
    out = tmp_path / "online"
    assert _checkup(out) == 3
    printed = capsys.readouterr().out
    report = _report(out)

    assert report["source"]["tier"] == "per-page"
    assert "pcb_review" not in report
    disclosure = report["completion"]["coverage"]["pcbReviewNotRun"]
    assert disclosure["mode"] == "online"
    assert disclosure["tier"] == "per-page"
    assert "PCB 版面审查未跑" in disclosure["reason"]
    assert "per-page" in disclosure["reason"]
    assert disclosure["howToRun"] == PCB_ONLINE_HINT
    assert PCB_ONLINE_HINT in disclosure["note"] or "--file" in disclosure["howToRun"]

    notes = " ".join(report["source"]["notes"])
    assert "PCB 版面审查未跑" in notes, "the human channel must carry it too"
    assert "PCB 版面审查未跑" in printed
    assert "PCB 审查未完成" not in notes, (
        "『没跑』和『跑崩了』是两句话：no archive is not a crashed runner"
    )
    # A disclosure, not a penalty.
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    assert not any("PCB" in why for why in report["completion"]["verdictWhy"])


def test_an_archive_without_pcb_documents_discloses_that_there_was_nothing_to_read(
    fake_bridge, tmp_path
):
    """A whole-project archive that carries no PCB document (the CH340 golden one).

    The runner returns no section — correctly, 缺席而非空 (钉 5) — and the report
    says *which* absence this is: 「no PCB document in the archive」, not 「the check
    failed」. It is also **not** 126d's gate: a project with no PCB document has no
    geometry to miss, so `pcbReviewMissing` stays False whether it is read online
    or offline.
    """
    base._FakeBridgeClient.answers = _answers(archive=base.GOLDEN_BYTES)
    out = tmp_path / "online"
    assert _checkup(out) == 3
    report = _report(out)

    assert report["source"]["tier"] == "project-file"
    assert "pcb_review" not in report
    disclosure = report["completion"]["coverage"]["pcbReviewNotRun"]
    assert "没有 PCB 文档" in disclosure["reason"]
    assert "PCB 版面审查未跑" in disclosure["reason"]
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    assert "PCB 审查未完成" not in " ".join(report["source"]["notes"])


def test_a_raising_pcb_runner_is_disclosed_and_gates_nothing(
    fake_bridge, tmp_path, monkeypatch
):
    """The third way: the archive has PCB documents and the runner raised.

    The geometry was in hand and the check did not happen — the same shape 126d
    makes `incomplete` **offline** (`pcbReviewMissing`). Online it is disclosed
    instead, and this test pins both halves of that decision: the failure is loud
    (a note naming 未完成, plus the disclosure) and the verdict is untouched —
    a refused bridge call may not be reported as 「板子没通过审查」.

    The runner is broken from the outside (the same seam `_run_pcb_runner`
    imports it through) rather than by feeding a corrupt archive, so what is
    tested is the disclosure and not a parser edge case.
    """
    import boardwise.engines.pcbreview as engine

    def boom(*args, **kwargs):
        raise RuntimeError("166 test: the runner is deliberately broken")

    monkeypatch.setattr(engine, "run_pcb_review", boom)
    base._FakeBridgeClient.answers = _answers(drc=False)
    out = tmp_path / "online"
    assert _checkup(out) == 3
    report = _report(out)

    assert "pcb_review" not in report
    notes = " ".join(report["source"]["notes"])
    assert "PCB 审查未完成" in notes and "RuntimeError" in notes
    disclosure = report["completion"]["coverage"]["pcbReviewNotRun"]
    assert "审查管线未出结果" in disclosure["reason"]
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    assert not any("PCB" in why for why in report["completion"]["verdictWhy"])


# --------------------------------------------------------------------------
# the disclosure field's own shape
# --------------------------------------------------------------------------


def test_the_disclosure_is_absent_not_empty_and_is_no_gate():
    """`coverage.pcbReviewNotRun` is a reading: absent when there is nothing to say.

    Three things, all about the field rather than about a run:

    * the neutral coverage (`_clean_coverage`, what a caller with no coverage to
      hand in gets, and what every report written before this batch effectively
      carries) has **no** such key — so nothing re-litigates an old verdict;
    * `_coverage_section` omits it when its caller passes none, so an offline
      report's coverage section is unchanged by this batch, key for key;
    * when it *is* passed, it rides along **beside** the gates — the return value
      is the section's whole truth, and `pcbReviewMissing` is a separate key with
      a separate caller-supplied value, which is what keeps the online
      disclosure from being read as the offline gate.
    """
    assert "pcbReviewNotRun" not in _clean_coverage()

    kwargs = dict(
        model=DesignModel(), board=None, attempts=[], parse_stats=ParseStats(),
        rules_errored=[],
    )
    without = _coverage_section(**kwargs)
    assert "pcbReviewNotRun" not in without
    assert without["pcbReviewMissing"] is False

    disclosure = {
        "mode": "online", "tier": "netlist", "reason": "…未跑",
        "howToRun": PCB_ONLINE_HINT, "note": "…",
    }
    with_disclosure = _coverage_section(pcb_review_not_run=disclosure, **kwargs)
    assert with_disclosure["pcbReviewNotRun"] == disclosure
    assert with_disclosure["pcbReviewNotRun"] is not disclosure, (
        "the section owns a copy — a caller's dict must not be reachable through "
        "the report it produced"
    )
    assert with_disclosure["pcbReviewMissing"] is False
    assert {k: v for k, v in with_disclosure.items() if k != "pcbReviewNotRun"} == without
