"""075: the two exit-code edges 073's verdict rule did not reach.

073 made `verdict: incomplete` an exit code and put the process code,
`report.json`'s `summary.exitCode` and `report.md`'s 「（退出码 N）」 on one
arithmetic (issue #15's discipline). Two paths ran beside it:

* **A — the re-gates never moved the recorded code.** `boardwise need-datasheet`
  and `boardwise triage` rebuild `completion` from the report's own sections and
  write it back, and they left `summary.exitCode` as the *previous* run decided
  it. So a `complete` board (exit 0) with one mark on it read
  `verdict: incomplete` next to 「（退出码 0）」 in the same file — the tool
  contradicting itself. Both re-gates now recompute the code with the same
  mapping the run used (`_regate_exit_code` → `_exit_code_with_verdict`), in both
  directions, while **their own** exit code stays what it always was (0 whenever
  the report was written: those commands succeeded if they wrote it).
* **B — `review --live` stayed 0 on an empty model.** The empty-reading
  predicate is gated on `path is not None` (019/072: those notes are about a
  *file*), so a live run that obtained a model with 0 components and 0 nets
  returned 0 — while `checkup` on the same project returns 3
  (`coverage.modelEmpty` is not path-gated). Same predicate, same reading, now
  the same exit code, with the live path's own sentence (distinct from "no tier
  produced a model", which is the other live 3).

Offline only: fixtures are read, never written; the live path is exercised
through a stub of `_load_model_online` (no daemon, no editor, no connector).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component, DesignModel, Net
from boardwise.engines.checkup import render_report_markdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"
#: A board the offline rule engine reports an ERROR for — the priority test needs
#: a run that must keep exit 1 (`1` outranks `3`).
DCDC = FIXTURES / "DCDC-12V9V转5V3V3_2026-09-27.epro2"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Never touch the real `~/.boardwise` (config, audit, sidecars)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))


# --------------------------------------------------------------------------
# helpers: the real commands, offline
# --------------------------------------------------------------------------


def _clean_board(monkeypatch, *, triage: list[dict] | None = None) -> None:
    """Lift the facts trigger and the warning queue (058's own trick).

    What is left is a board the gate may call finished, which is the only way to
    see a *mark* move the verdict — and the exit code — on its own.
    """
    monkeypatch.setattr(cli, "unreviewed_parts", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "warning_triage_slots", lambda **kwargs: list(triage or []))


def _checkup(out: Path, board: Path = GOLDEN) -> tuple[int, dict]:
    code = cli.main(["checkup", "--file", str(board), "--out", str(out)])
    return code, _read(out)


def _read(out: Path) -> dict:
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def _markdown(out: Path) -> str:
    return (out / "report.md").read_text(encoding="utf-8")


def _warning_slot(key: str) -> dict:
    """One `warning_triage[]` slot, same shape `checkup` generates."""
    return {
        "key": key,
        "source": "boardwise-rule",
        "severity": "WARN",
        "count": 1,
        "text": "xtal-load-caps: 晶振没有匹配的负载电容",
        "textUnavailable": "",
        "attribution": {"scope": "finding", "page": None, "net": "", "module": None},
        "verdict": "",
        "reason": "",
        "evidence": ["findings[0] rule xtal-load-caps"],
    }


# --------------------------------------------------------------------------
# A1 — a mark moves the recorded code, and the three renderings move together
# --------------------------------------------------------------------------


def test_marking_a_pin_moves_the_recorded_exit_code_to_three(
    tmp_path, monkeypatch, capsys
):
    """0 → 3 in `report.json`, in `report.md`, and in the console's own line.

    Before 075 the report said `incomplete` and 「（退出码 0）」 at once. The
    *command's* exit code is the other question and stays 0: the mark was
    applied, which is what that code is about.
    """
    _clean_board(monkeypatch)
    out = tmp_path / "out"
    code, before = _checkup(out)
    assert before["completion"]["verdict"] == "complete"
    assert code == 0 and before["summary"]["exitCode"] == 0
    assert "（退出码 0）" in _markdown(out)
    capsys.readouterr()

    assert cli.main(
        ["need-datasheet", "--out", str(out), "--part", "U1", "--pins", "FB,ICG",
         "--reason", "脚义不明，等手册"]
    ) == 0
    printed = capsys.readouterr().out

    after = _read(out)
    assert after["completion"]["verdict"] == "incomplete"
    assert after["summary"]["exitCode"] == 3, "the recorded code follows the verdict"
    assert "（退出码 3）" in _markdown(out)
    assert "（退出码 0）" not in _markdown(out)
    # The console names both codes apart, because they are two questions.
    assert "  exitCode: 3" in printed
    assert "本命令自己的退出码是 0" in printed


def test_a_report_whose_code_fell_behind_is_brought_back_in_line(
    tmp_path, monkeypatch, capsys
):
    """The same recompute, for `triage`, on a report written by an older build.

    Until 075 no build wrote 3 for an `incomplete` verdict, so a report.json on
    disk can carry a code older than its own verdict. Re-gating has to leave the
    report's record true, not preserve a number that no longer describes it.
    """
    monkeypatch.setattr(cli, "warning_triage_slots", lambda **kwargs: [_warning_slot("k1")])
    out = tmp_path / "out"
    # The golden board keeps the gate at `incomplete` on its own (parts with no
    # datasheet), which is the shape this test needs.
    _checkup(out)
    capsys.readouterr()
    stale = _read(out)
    assert stale["completion"]["verdict"] == "incomplete"
    assert stale["summary"]["exitCode"] == 3
    # ... and this is what a build before 075 left on disk for the same gate.
    stale["summary"]["exitCode"] = 0
    (out / "report.json").write_text(
        json.dumps(stale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    assert cli.main(
        ["triage", "--out", str(out), "--key", "k1", "--verdict", "无害",
         "--reason", "与地平面同层，已核过电流回路"]
    ) == 0
    printed = capsys.readouterr().out

    after = _read(out)
    assert after["completion"]["verdict"] == "incomplete", "the gate is unchanged"
    assert after["summary"]["exitCode"] == 3
    assert "（退出码 3）" in _markdown(out)
    assert "  exitCode: 3" in printed
    assert "本命令自己的退出码是 0" in printed


def test_taking_the_mark_away_puts_the_code_back_to_zero(tmp_path, monkeypatch, capsys):
    """3 → 0: the other half of "one value", pinned where it can be reached.

    There is no CLI that *removes* a mark (`need-datasheet` only adds, and the
    sidecar is an audit trail), so the reverse direction is exercised on the
    re-gate itself: the same report, the same call, an empty mark list — which is
    what a report whose unknown was resolved comes back with.
    """
    _clean_board(monkeypatch)
    out = tmp_path / "out"
    _checkup(out)
    cli.main(
        ["need-datasheet", "--out", str(out), "--part", "U1", "--pins", "FB",
         "--reason", "先挂起，等手册"]
    )
    capsys.readouterr()
    report = _read(out)
    assert report["summary"]["exitCode"] == 3

    cli._apply_needs_datasheet(report, [])

    assert report["completion"]["verdict"] == "complete"
    assert report["summary"]["exitCode"] == 0
    assert "（退出码 0）" in render_report_markdown(report)


def test_filling_the_last_warning_keeps_the_zero(tmp_path, monkeypatch, capsys):
    """`triage` recomputes too, and never invents a 3.

    A board that only owed a triage verdict was never `incomplete`: pending
    triage is `complete-with-open-items` (073 keeps that at 0). Filling the last
    slot moves it to `complete` and the recorded code stays 0.
    """
    _clean_board(monkeypatch, triage=[_warning_slot("k1")])
    out = tmp_path / "out"
    code, before = _checkup(out)
    assert before["completion"]["verdict"] == "complete-with-open-items"
    assert before["completion"]["warningsPendingTriage"] == 1
    assert code == 0 and before["summary"]["exitCode"] == 0
    capsys.readouterr()

    assert cli.main(
        ["triage", "--out", str(out), "--key", "k1", "--verdict", "有益",
         "--reason", "这条提醒了我去核负载电容"]
    ) == 0
    printed = capsys.readouterr().out

    after = _read(out)
    assert after["completion"]["warningsPendingTriage"] == 0
    assert after["completion"]["verdict"] == "complete"
    assert after["summary"]["exitCode"] == 0
    assert "（退出码 0）" in _markdown(out)
    assert "  exitCode: 0" in printed


def test_an_error_board_keeps_its_one_across_a_mark(tmp_path, capsys):
    """The priority is unchanged: `1` (an ERROR was found) > `3` (nothing stated)."""
    out = tmp_path / "out"
    code, before = _checkup(out, DCDC)
    assert before["summary"]["errorCount"] > 0
    assert code == 1 and before["summary"]["exitCode"] == 1
    designator = before["model"]["designators"][0]
    capsys.readouterr()

    assert cli.main(
        ["need-datasheet", "--out", str(out), "--part", designator,
         "--reason", "这颗不许猜"]
    ) == 0

    after = _read(out)
    assert after["completion"]["verdict"] == "incomplete"
    assert after["summary"]["exitCode"] == 1
    assert "（退出码 1）" in _markdown(out)


@pytest.mark.parametrize(
    "recorded,verdict,expected",
    [
        (0, "incomplete", 3),
        (0, "complete-with-open-items", 0),
        (0, "complete", 0),
        (1, "incomplete", 1),
        (1, "complete", 1),
        (3, "complete", 0),
        (3, "complete-with-open-items", 0),
        (3, "incomplete", 3),
    ],
)
def test_the_regate_mapping_is_the_run_mapping_in_both_directions(
    recorded, verdict, expected
):
    """One mapping, read backwards for its base (075) — never a second rule.

    `_exit_code_with_verdict` only ever raises a 0, and a written report carries
    0, 1 or 3, so the recorded code determines the base it was raised from: a 3
    is a 0 the verdict raised. Re-gating therefore recomputes rather than
    re-decides.
    """
    assert cli._regate_exit_code({"exitCode": recorded}, verdict) == expected


def test_a_report_with_no_recorded_code_is_recomputed_from_zero():
    """A report written before the field existed: the verdict still decides."""
    assert cli._regate_exit_code({}, "incomplete") == cli.INCOMPLETE_EXIT_CODE
    assert cli._regate_exit_code({}, "complete") == 0
    assert cli._regate_exit_code({"exitCode": None}, "incomplete") == 3


# --------------------------------------------------------------------------
# B — `review --live` on an empty model: 3, like `checkup`
# --------------------------------------------------------------------------


def _live_stub(model: DesignModel, tier: str = "netlist"):
    """`_load_model_online`'s contract, without a daemon: `(model, board, …)`."""
    calls: list[dict] = []

    def load(args, *, notes, attempts, parse_stats=None):
        calls.append({"args": args, "notes": notes})
        return model, None, tier, {"project": {"name": "stub"}}, None

    return load, calls


def test_review_live_on_an_empty_model_is_exit_three(tmp_path, monkeypatch, capsys):
    """0 components and 0 nets read *live* is the state `checkup` calls exit 3.

    The sentence is the live one: `EMPTY_MODEL_NOTE` blames a file, and there is
    no file here — the connector answered, and what it answered with is empty.
    """
    load, calls = _live_stub(DesignModel())
    monkeypatch.setattr(cli, "_load_model_online", load)
    md = tmp_path / "live.md"

    code = cli.main(["review", "--live", "--md", str(md)])
    printed = capsys.readouterr().out

    assert calls, "the live tier was stubbed, so this ran the live branch"
    assert "(0 components, 0 nets)" in printed
    assert cli.LIVE_EMPTY_MODEL_NOTE in printed
    assert cli.EMPTY_MODEL_NOTE not in printed, "this reading came from the editor"
    assert cli.INCOMPLETE_EXIT_SENTENCE in printed
    assert code == 3
    assert cli.LIVE_EMPTY_MODEL_HINT in md.read_text(encoding="utf-8")


def test_review_live_with_parts_but_no_nets_is_not_an_empty_read(monkeypatch, capsys):
    """The negative: a partly-read model is not "nothing was read".

    `_model_read_nothing` is 0 components **and** 0 nets; a live page whose parts
    came through and whose nets did not is a reading that saw something. Pinned
    because the cheap way to write this gate is `components == 0 or nets == 0`,
    which would call every such page empty.
    """
    model = DesignModel(
        components={"R1": Component(uid="u1", designator="R1", value="10k")}, nets={}
    )
    load, _calls = _live_stub(model)
    monkeypatch.setattr(cli, "_load_model_online", load)

    code = cli.main(["review", "--live"])
    printed = capsys.readouterr().out

    assert "(1 components, 0 nets)" in printed
    assert cli.LIVE_EMPTY_MODEL_NOTE not in printed
    assert cli.EMPTY_MODEL_NOTE not in printed
    assert code == 0


def test_review_live_that_obtained_a_model_says_so_and_keeps_its_rules(
    monkeypatch, capsys
):
    """The 对照: a live reading with content is untouched by any of this."""
    model = DesignModel(
        components={"R1": Component(uid="u1", designator="R1", value="10k")},
        nets={"NET1": Net(name="NET1", pins=[("R1", "1")])},
    )
    load, _calls = _live_stub(model, tier="per-page")
    monkeypatch.setattr(cli, "_load_model_online", load)

    code = cli.main(["review", "--live"])
    printed = capsys.readouterr().out

    assert "(1 components, 1 nets)" in printed
    assert cli.LIVE_EMPTY_MODEL_NOTE not in printed
    assert code == 0


def test_review_live_with_no_tier_keeps_its_own_three(monkeypatch, capsys):
    """The other live 3 — "no model at all" — is a different sentence (073)."""
    monkeypatch.setattr(cli, "_load_model_online", lambda *a, **k: None)

    code = cli.main(["review", "--live"])
    captured = capsys.readouterr()

    assert code == 3
    assert "在线状态不可陈述" in captured.err
    assert cli.LIVE_EMPTY_MODEL_NOTE not in captured.out
