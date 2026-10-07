"""058 (issue #8): the ⓪ 先问再判 gate — `needs_datasheet[]` and the command that fills it.

The accident this batch answers: a review went around `checkup`, and its author
judged two pins of a supply IC with no datasheet in hand — one a factory-blessed
floating input, the other a reference point, both verdicts wrong the next day.
Three gaps were accepted: the gate only lived inside the checkup report, its test
was "the shelf could not judge this part" rather than "**I** cannot read this
pin", and the SOP had no step that *asks for the datasheet before judging*.

So this file pins four things, and each one is a way the batch could fail:

* the report now carries **one** list of what it depends on, with the facts seed
  and the reviewer's marks as two triggers (`needs_datasheet`, schema `/6`);
* a mark **closes the gate** — `completion.verdict` becomes `incomplete` even when
  every part has facts and nothing else is owed (缺口②), and `report.md` says the
  report may not claim a pass (缺口①);
* the mark is **idempotent per `(part, pin)`** and leaves an audit trail beside
  the report rather than only in the report;
* `summary.mayClaimPassed` keeps its **narrow** meaning (053) — it still answers
  only "was any part left unjudged by the shelf?" and must not be read as the
  gate now that there is a second way to owe a datasheet.

The fixtures are the real CH340G board; the commands are the real CLI, offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import boardwise.cli as cli
from boardwise.core.model import DesignModel
from boardwise.engines.checkup import (
    NEEDS_DATASHEET_BLOCK,
    TRIGGER_FACTS,
    TRIGGER_MARKED,
    marked_parts,
    needs_datasheet_section,
    render_report_markdown,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"

#: The board's own WARN finding names this part, which is what makes
#: `dependentFindings` measurable instead of merely non-empty.
MARKED_PART = "U1"
MARKED_PINS = ["FB", "ICG"]
MARKED_REASON = "FB 悬空是否认可用法 / ICG 参考点不明"


# --------------------------------------------------------------------------
# helpers: the real commands, offline
# --------------------------------------------------------------------------


def _checkup(out: Path, *extra: str) -> dict:
    """Run the offline `checkup` and read the report it wrote.

    073: the exit code is decided by the verdict, so the helper asserts the
    **pairing** rather than a bare number (it was `== 0` until this batch): a
    reading that is `incomplete` — which the golden fixture's is, 4 parts without a
    datasheet — exits 3, anything else 0. The report is written either way.
    """
    code = cli.main(["checkup", "--file", str(GOLDEN), "--out", str(out), *extra])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    verdict = report["completion"]["verdict"]
    expected = 3 if verdict == "incomplete" else 0
    assert code == expected, f"checkup exited {code} for verdict {verdict} (073)"
    return report


def _mark(out: Path, *argv: str) -> int:
    return cli.main(["need-datasheet", "--out", str(out), *argv])


def _read(out: Path) -> dict:
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def _marked(report: dict) -> list[dict]:
    return [row for row in report["needs_datasheet"] if row["trigger"] == TRIGGER_MARKED]


def _clean_board(monkeypatch) -> None:
    """Lift the facts trigger and the warning queue.

    What is left is a board the review can call finished — which is the only way
    to see the *marked* trigger move the verdict on its own (缺口②): on any real
    fixture the unreviewed parts already hold the gate shut.
    """
    monkeypatch.setattr(cli, "unreviewed_parts", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "warning_triage_slots", lambda **kwargs: [])


# --------------------------------------------------------------------------
# ① the report carries the list, with the facts seed in it and marked empty
# --------------------------------------------------------------------------


def test_checkup_writes_the_section_with_the_facts_seed_and_nothing_marked(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    report = _checkup(out)
    printed = capsys.readouterr().out

    assert report["schema"] == "boardwise.checkup/7"
    seeded = report["unreviewed_parts"]
    assert seeded, "the golden board has parts the shelf cannot judge"
    rows = {row["part"]: row for row in report["needs_datasheet"]}
    assert set(rows) == {row["designator"] for row in seeded}
    for row in report["needs_datasheet"]:
        assert row["trigger"] == TRIGGER_FACTS
        assert row["pins"] == [], "a facts entry is the whole part, not a pin"
        assert row["factSeed"] is True
    # The seed is carried over, not recomputed: same channels, same identity
    # fields, same words — the section it came from is untouched (053's discipline).
    for seed in seeded:
        carried = rows[seed["designator"]]
        assert carried["channels"] == seed["channels"]
        assert carried["mpn"] == seed["mpn"]
        assert carried["supplier"] == seed["supplier"]
        assert carried["missingFacts"] == seed["missingFacts"]
        assert carried["reason"] == "；".join(seed["reasons"])
        assert "part" not in seed and seed["designator"], "unreviewed_parts kept its own shape"
    # Nothing is marked yet — the review has not started — so the gate's own
    # count is zero and the narrow field answers the facts question alone.
    assert report["completion"]["needsDatasheet"] == 0
    assert report["summary"]["mayClaimPassed"] is (not seeded)
    assert "needs_datasheet: " in printed and f"facts {len(seeded)}" in printed
    assert "审查者标记 0" in printed

    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "## 本报告依赖的未知项" in markdown
    assert f"facts {len(seeded)} 条 / 审查者标记 0 项" in markdown
    assert NEEDS_DATASHEET_BLOCK in markdown, "the seed alone already forbids a pass"
    assert "### 审查者标记" not in markdown, "no reviewer has marked anything yet"


# --------------------------------------------------------------------------
# ② a mark closes the gate — even when every part was judged and nothing else owes
# --------------------------------------------------------------------------


def test_a_marked_pin_is_incomplete_even_when_no_part_is_unreviewed(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    _clean_board(monkeypatch)
    out = tmp_path / "out"
    before = _checkup(out)
    capsys.readouterr()
    # The premise: without the mark this run is finished, and the narrow field
    # (which only ever asked about the shelf) says a pass may be claimed.
    assert before["completion"]["verdict"] == "complete"
    assert before["completion"]["needsDatasheet"] == 0
    assert before["summary"]["mayClaimPassed"] is True

    assert _mark(out, "--part", MARKED_PART, "--pins", ",".join(MARKED_PINS),
                 "--reason", MARKED_REASON) == 0
    printed = capsys.readouterr().out

    report = _read(out)
    marks = _marked(report)
    assert len(marks) == 1, "one entry per part, not one per pin"
    assert marks[0]["part"] == MARKED_PART
    assert marks[0]["pins"] == MARKED_PINS
    assert marks[0]["reason"] == MARKED_REASON
    assert marks[0]["factSeed"] is False, "this part had facts; it is the pin that is unknown"
    # subjects/designator matching: the board's own finding about U1 is what this
    # mark puts in doubt.
    assert marks[0]["dependentFindings"] == ["decap-required-caps@U1"]

    completion = report["completion"]
    assert completion["needsDatasheet"] == 1
    assert completion["verdict"] == "incomplete"
    assert "1 项管脚/器件待手册（审查者标记）" in completion["verdictWhy"]
    assert report["summary"]["conclusion"].endswith("；另有 1 项管脚待手册（已标记）")
    # ... and the narrow field is not what changed: it still answers only the
    # unreviewed question, which is why the verdict lives in `completion`.
    assert report["summary"]["mayClaimPassed"] is True
    assert "completion: incomplete" in printed

    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert NEEDS_DATASHEET_BLOCK in markdown
    assert "### 审查者标记（读不懂的管脚，1 项）" in markdown
    assert f"| {MARKED_PART} | FB、ICG |" in markdown
    assert "decap-required-caps@U1" in markdown
    assert "**verdict：`incomplete`**" in markdown

    # The sidecar is the audit trail: what was marked, by whom, when.
    sidecar = json.loads((out / "needs-datasheet.json").read_text(encoding="utf-8"))
    assert sidecar["schema"] == "boardwise.needs-datasheet/1"
    assert [(row["part"], row["pin"]) for row in sidecar["marks"]] == [
        (MARKED_PART, "FB"), (MARKED_PART, "ICG"),
    ]
    assert all(row["reason"] == MARKED_REASON and row["at"] for row in sidecar["marks"])


def test_a_mark_for_a_part_the_shelf_already_gave_up_on_shows_once(
    tmp_path, monkeypatch
):
    """Both triggers on the same part: marked wins the row, counted once.

    This is the case the SOP walks into — a part the shelf could not judge *and*
    whose function the reviewer could not read. It is one unknown with one
    datasheet, so the list shows the reviewer's more specific words and the part
    is counted once (058 §二: "计数只算一次").
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    seeded = _checkup(out)
    target = seeded["unreviewed_parts"][-1]["designator"]

    assert _mark(out, "--part", target, "--pins", "VCC", "--reason", "脚名与图不符") == 0
    report = _read(out)

    rows = [row for row in report["needs_datasheet"] if row["part"] == target]
    assert len(rows) == 1, "two triggers, one row"
    assert rows[0]["trigger"] == TRIGGER_MARKED
    assert rows[0]["pins"] == ["VCC"]
    assert rows[0]["factSeed"] is True
    # The seed's own information travels with the marked row rather than being lost.
    seed = next(row for row in report["unreviewed_parts"] if row["designator"] == target)
    assert rows[0]["channels"] == seed["channels"]
    assert rows[0]["mpn"] == seed["mpn"]
    assert rows[0]["reason"] == "脚名与图不符", "the reviewer's reason, not the shelf's"
    # Counted once: the facts trigger is already `unreviewedParts`.
    assert report["completion"]["needsDatasheet"] == 1
    assert report["completion"]["unreviewedParts"] == len(report["unreviewed_parts"])
    assert len(marked_parts(report["needs_datasheet"])) == 1


# --------------------------------------------------------------------------
# ③ idempotent per (part, pin), and honest about it
# --------------------------------------------------------------------------


def test_marking_the_same_pin_again_updates_the_reason_and_adds_no_row(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    _checkup(out)
    capsys.readouterr()
    assert _mark(out, "--part", MARKED_PART, "--pins", "FB,ICG", "--reason", "第一次") == 0
    first = capsys.readouterr().out
    assert "已新增" in first

    assert _mark(out, "--part", MARKED_PART, "--pins", "FB,ICG", "--reason", "第二次") == 0
    second = capsys.readouterr().out
    assert "已存在，已更新" in second

    sidecar = json.loads((out / "needs-datasheet.json").read_text(encoding="utf-8"))
    assert len(sidecar["marks"]) == 2, "one row per (part, pin), whatever the number of runs"
    assert {row["reason"] for row in sidecar["marks"]} == {"第二次"}
    report = _read(out)
    assert len(_marked(report)) == 1
    assert _marked(report)[0]["reason"] == "第二次"
    assert _marked(report)[0]["pins"] == ["FB", "ICG"]
    assert report["completion"]["needsDatasheet"] == 1


def test_a_whole_device_mark_needs_no_pins(capsys, tmp_path, monkeypatch):
    """`--pins` omitted means "the device itself is the unknown" (058 §三)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    _checkup(out)
    capsys.readouterr()
    assert _mark(out, "--part", "U9", "--reason", "整颗行为不明，手上没有手册") == 0
    report = _read(out)
    row = _marked(report)[0]
    assert row["part"] == "U9" and row["pins"] == []
    assert "（整颗器件）" in (out / "report.md").read_text(encoding="utf-8")
    # A part the report does not know is recorded, and said out loud rather than
    # silently accepted (a typo must not disappear into the gate).
    assert "位号" in capsys.readouterr().err


# --------------------------------------------------------------------------
# ④ the command is a file operation, and refuses when there is nothing to mark up
# --------------------------------------------------------------------------


def test_no_report_json_is_exit_three_and_writes_nothing(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "never-checked"
    assert _mark(out, "--part", "U7", "--reason", "没有报告") == 3
    err = capsys.readouterr().err
    assert "checkup" in err and "不存在" in err
    assert not out.exists() or not list(out.iterdir())


def test_an_unreadable_sidecar_is_a_note_for_checkup_and_a_stop_for_marking(
    capsys, tmp_path, monkeypatch
):
    """The audit trail is never overwritten by a command that cannot read it."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    _checkup(out)
    capsys.readouterr()
    sidecar = out / "needs-datasheet.json"
    sidecar.write_text("{ this is not JSON", encoding="utf-8")

    # `checkup` must still produce a report — it does not own that file.
    report = _checkup(out)
    assert "侧车读不了" in " ".join(report["source"]["notes"])
    assert report["needs_datasheet"] and all(
        row["trigger"] == TRIGGER_FACTS for row in report["needs_datasheet"]
    )
    assert sidecar.read_text(encoding="utf-8") == "{ this is not JSON"

    # The marking command refuses instead: it would have to rewrite it.
    assert _mark(out, "--part", MARKED_PART, "--reason", "读不出来就别动") == 2
    assert "侧车读不了" in capsys.readouterr().err
    assert sidecar.read_text(encoding="utf-8") == "{ this is not JSON"


def test_the_command_never_touches_the_editor(capsys, tmp_path, monkeypatch):
    """058 §三: purely offline. A bridge that refuses to open proves it."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    _checkup(out)
    capsys.readouterr()

    import boardwise.bridge.client as client_module

    def _explode(*args, **kwargs):
        raise AssertionError("need-datasheet must not open a bridge connection")

    monkeypatch.setattr(client_module, "BridgeClient", _explode)
    assert _mark(out, "--part", MARKED_PART, "--pins", "FB", "--reason", "离线") == 0
    assert len(_marked(_read(out))) == 1


def test_a_missing_reason_is_refused(capsys, tmp_path, monkeypatch):
    """The reason is what makes the list actionable, so it is not optional."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    _checkup(out)
    capsys.readouterr()
    # argparse refuses the absent flag outright (`2` is this CLI's "bad input").
    with pytest.raises(SystemExit) as caught:
        _mark(out, "--part", MARKED_PART, "--pins", "FB")
    assert caught.value.code == 2
    assert "--reason" in capsys.readouterr().err
    # ... and an empty one is refused by the command itself, not treated as "no
    # reason given, carry on".
    assert _mark(out, "--part", MARKED_PART, "--pins", "FB", "--reason", "   ") == 2
    assert "--reason" in capsys.readouterr().err
    assert not (out / "needs-datasheet.json").exists()
    assert _marked(_read(out)) == []


# --------------------------------------------------------------------------
# the section itself: merge, count, and the rendered gate
# --------------------------------------------------------------------------


def _seed(**overrides) -> dict:
    row = {
        "designator": "U3",
        "reasons": ["货架没有这颗料"],
        "channels": {"engineer": {"ok": False}, "lcsc": {"ok": False}, "official": {"ok": None}},
        "mpn": "NOWHERE1",
        "supplier": "C999",
        "missingFacts": ["supply_pins"],
    }
    row.update(overrides)
    return row


def test_the_section_merges_the_two_triggers_and_derives_dependent_findings():
    findings = [
        {"rule_id": "decap-required-caps", "severity": "WARN", "refs": ["U3", "C4"],
         "message": "U3 pin1 has no capacitor", "target": None},
        {"rule_id": "param-value-mpn-match", "severity": "ERROR", "refs": [],
         "message": "contradiction", "target": {"component_ref": "U3"}},
        {"rule_id": "unrelated-rule", "severity": "INFO", "refs": ["R4"],
         "message": "nothing to do with this part", "target": None},
    ]
    section = needs_datasheet_section(
        [_seed()],
        [{"part": "U3", "pin": "VCC", "reason": "脚位不明"},
         {"part": "U7", "pin": "", "reason": "整颗不明"}],
        findings,
    )
    assert [row["part"] for row in section] == ["U3", "U7"]
    merged, whole = section
    assert merged["trigger"] == TRIGGER_MARKED and whole["trigger"] == TRIGGER_MARKED
    assert merged["pins"] == ["VCC"] and whole["pins"] == []
    # `refs` and the plan target are both read — the same two sources the Chinese
    # summary uses, so "a finding about U3" means one thing in this report.
    assert merged["dependentFindings"] == ["decap-required-caps@U3", "param-value-mpn-match@U3"]
    assert whole["dependentFindings"] == []
    assert merged["channels"] == _seed()["channels"]
    assert marked_parts(section) == ["U3", "U7"]


def test_the_completion_section_counts_marked_parts_and_gates_on_them():
    """One per part (two pins, one count), and it is `incomplete` on its own."""
    from boardwise.cli import _completion_section

    marked = [
        {"part": "U7", "pins": ["FB", "ICG"], "trigger": TRIGGER_MARKED, "factSeed": False},
    ]
    section = _completion_section(
        model=DesignModel(),
        summary={"errorCount": 0},
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 0}},
        needs_datasheet=marked,
    )
    assert section["needsDatasheet"] == 1
    assert section["verdict"] == "incomplete"
    assert section["verdictWhy"] == ["1 项管脚/器件待手册（审查者标记）"]
    # A report from before this batch (no argument at all) keeps its old answer.
    legacy = _completion_section(
        model=DesignModel(),
        summary={"errorCount": 0},
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 0}},
    )
    assert legacy["needsDatasheet"] == 0 and legacy["verdict"] == "complete"


def test_the_markdown_section_forbids_a_pass_while_it_is_not_empty(tmp_path):
    """The one wording the section owns, in both states (058 §四)."""
    report = _checkup(tmp_path / "out")
    report.pop("needs_datasheet")
    report["needs_datasheet"] = []
    empty = render_report_markdown(report)
    assert "## 本报告依赖的未知项（needs_datasheet：facts 0 条 / 审查者标记 0 项）" in empty
    assert "本节为空" in empty
    assert NEEDS_DATASHEET_BLOCK not in empty

    opening = render_report_markdown({
        **report,
        "needs_datasheet": [
            {"part": "U7", "pins": ["FB"], "trigger": TRIGGER_MARKED, "reason": "脚义不明",
             "dependentFindings": ["decap-required-caps@U7"], "channels": {}, "factSeed": False},
        ],
    })
    assert NEEDS_DATASHEET_BLOCK in opening
    assert "### facts 触发" not in opening, "no seed in this copy"
    assert "| U7 | FB | 脚义不明 | decap-required-caps@U7 |" in opening
    # The template hands the model the same slot it must not fill while unknown.
    template = report["ai_slots"]["summary_template"]
    assert "【本报告依赖的未知项】" in template
    assert "这一节空着才允许写" in template
