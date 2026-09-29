"""063 (issue #12): the triage verdict survives a re-run — sidecar + `boardwise triage`.

Issue #12 (measured on the real board): `warning_triage[]` was the one AI slot
with no way back in. Filling `verdict`/`reason` by hand left
`completion.warningsPendingTriage` at its old value, and re-running `checkup`
regenerated the slots and dropped every judgement silently. The control group is
`needs_datasheet[]`, which 058 gave a sidecar and a writing command — so this is
the same shape, not a new one.

Four things are pinned here, and each one is a way the fix could fail:

* every slot carries a stable `key` (three sources, three recipes) — the identity
  a verdict is written against and matched on;
* `checkup` folds the sidecar back onto the slots it just generated, and says
  what it merged and what it could not match (an audit trail is reported, never
  deleted);
* `boardwise triage` writes one verdict into the report **and** the sidecar, is
  idempotent per `key`, and refuses a key the report does not carry;
* the issue's own path end to end: checkup → 3 verdicts → checkup again, with the
  verdicts, the pending count and the report's wording still agreeing.

The board is **synthetic** — a minimal `.epru` inside a real ZIP, built here. Its
three crystals draw `xtal-load-caps` WARNs, which is what makes three real triage
slots offline: no fixture from ``tests/fixtures/``, no editor, no daemon.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import boardwise.cli as cli
from boardwise.core.model import DesignModel
from boardwise.engines.checkup import (
    TRIAGE_VERDICTS,
    merge_triage_sidecar,
    triage_key,
    warning_triage_slots,
)

#: The rule the synthetic board trips, and the designators it trips on — the
#: three warnings this file has to keep alive across re-runs.
WARN_RULE = "xtal-load-caps"
CRYSTALS = ("Y1", "Y2", "Y3")


# --------------------------------------------------------------------------
# a synthetic board: three crystals, three wires, three WARNs
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    """One `.epru` line: a JSON envelope, `||`, a JSON body, `|`."""
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _symbol(uuid: str, pins: list[tuple[str, float, float]]) -> list[str]:
    out = [_record("DOCHEAD", {"docType": "SYMBOL", "uuid": uuid, "editVersion": "3.2.149"}),
           _record("META", {"title": "XTAL", "docType": "SYMBOL"}, id_="meta-1")]
    for index, (number, x, y) in enumerate(pins):
        pin_id = f"{uuid}-pin{index}"
        out.append(_record("PIN", {"x": x, "y": y, "zIndex": index + 2}, id_=pin_id))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Number", "value": number},
                           id_=f"{pin_id}-n"))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Name", "value": f"P{number}"},
                           id_=f"{pin_id}-name"))
    return out


def _board(tmp_path: Path) -> Path:
    """A one-page `.epro2` whose crystals each sit on a net with no load cap.

    Each crystal's pin 1 is an endpoint of its own wire, so the pin is on a net —
    which is all `xtal-load-caps` needs to call it a warning. Kept deliberately
    thin: the file exists to give `checkup` three real WARN findings, not to
    reproduce a board.
    """
    lines = [_record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": "page-1"}),
             _record("CANVAS", {"originX": 0, "originY": 0, "unit": "0.01inch"}, id_="canvas-1")]
    lines += _symbol("sym-xtal", [("1", 0.0, 0.0), ("2", 20.0, 0.0)])
    for index, designator in enumerate(CRYSTALS):
        part = f"inst-{designator}"
        x, y = 300.0 + index * 200.0, -500.0
        lines.append(_record("COMPONENT", {"partId": part, "x": x, "y": y, "rotation": 0,
                                          "isMirror": False, "zIndex": 10}, id_=f"c-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Designator", "value": designator},
                             id_=f"d-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Symbol", "value": "sym-xtal"},
                             id_=f"s-{part}"))
        group = f"grp-{index}"
        lines.append(_record("WIRE", {"zIndex": 40}, id_=group))
        lines.append(_record("LINE", {"lineGroup": group, "startX": x, "startY": y,
                                      "endX": x + 100.0, "endY": y}))
        lines.append(_record("ATTR", {"parentId": group, "key": "NET", "value": f"SIG_{index}"},
                             id_=f"net-{index}"))
    path = tmp_path / "synth_crystals.epro2"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


# --------------------------------------------------------------------------
# helpers: the real commands, offline
# --------------------------------------------------------------------------


def _checkup(board: Path, out: Path) -> dict:
    """Run the offline `checkup` and read the report it wrote.

    073: the exit code is decided by the verdict, so the assertion is the pairing
    (`incomplete` → 3, else 0) and not a bare number: it was `== 0` until this batch.
    """
    code = cli.main(["checkup", "--file", str(board), "--out", str(out)])
    report = _read(out)
    verdict = report["completion"]["verdict"]
    expected = 3 if verdict == "incomplete" else 0
    assert code == expected, f"checkup exited {code} for verdict {verdict} (073)"
    return report


def _triage(out: Path, *argv: str) -> int:
    return cli.main(["triage", "--out", str(out), *argv])


def _read(out: Path) -> dict:
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def _keys(report: dict) -> list[str]:
    return [str(slot.get("key") or "") for slot in report["warning_triage"]]


def _verdicts(report: dict) -> list[str]:
    return [slot["verdict"] for slot in report["warning_triage"]]


def _clean_board(monkeypatch) -> None:
    """Lift the datasheet trigger, leaving the warnings as the only open items.

    On this board the three crystals have no MPN, so the facts gate alone holds
    the verdict at `incomplete`. Patching it out is what makes "the last warning
    judged" observable as `complete` — the same isolation `test_039c` and
    `test_058` use, and it changes nothing about the triage path under test.
    """
    monkeypatch.setattr(cli, "unreviewed_parts", lambda *args, **kwargs: [])


def _sidecar(out: Path) -> dict:
    return json.loads((out / "warning-triage.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# ① the slot key: three sources, three recipes, one stable identity
# --------------------------------------------------------------------------


def _drc() -> dict:
    """A DRC section shaped like the one `drc.py` builds: counts + PCB leaves."""
    return {
        "schematic": {
            "checked": True, "pagesChecked": 2, "pageCount": 2,
            "countsBasis": "host-wide", "totals": {"warn": 2, "error": 1},
        },
        "pcb": {
            "checked": True,
            "groups": [
                {"index": 0, "leafs": [
                    {"ruleName": "Clearance", "explanation": "too close", "net": "VCC",
                     "severity": "warn", "severitySource": "host", "globalIndex": "w1"},
                    {"ruleName": "SilkOverPad", "explanation": "", "net": "",
                     "severity": "warn", "globalIndex": "w2"},
                    {"ruleName": "Clearance", "explanation": "an error is not a warning",
                     "net": "GND", "severity": "error", "globalIndex": "e1"},
                ]},
            ],
        },
    }


def _findings() -> list[dict]:
    return [
        {"rule_id": WARN_RULE, "severity": "WARN", "message": "Y1: no grounded cap",
         "refs": ["Y1"]},
        {"rule_id": "param-led-current", "severity": "ERROR", "message": "an ERROR", "refs": []},
    ]


def test_every_slot_carries_a_key_and_the_recipe_differs_per_source():
    """063 §1: `host-erc:<severity>` / `pcb-drc:<severity>:<label>:<net>` / `boardwise-rule:<id>:<refs>`."""
    slots = warning_triage_slots(
        model=DesignModel(),
        drc=_drc(),
        findings=_findings(),
        modules=[],
    )
    assert [slot["source"] for slot in slots] == [
        "host-erc", "pcb-drc", "pcb-drc", "boardwise-rule",
    ]
    assert [slot["key"] for slot in slots] == [
        "host-erc:warn",
        "pcb-drc:warn:Clearance:VCC",
        "pcb-drc:warn:SilkOverPad:",  # no net: the recipe keeps the trailing field
        f"boardwise-rule:{WARN_RULE}:Y1",
    ]
    # One recipe per source, spelled out where the identity is built — the keys
    # an old report would already have been written against.
    labeled = {slot["source"]: slot["key"] for slot in slots if slot["source"] != "pcb-drc"}
    assert labeled == {"host-erc": "host-erc:warn", "boardwise-rule": f"boardwise-rule:{WARN_RULE}:Y1"}
    # The ERROR leaf and the ERROR finding are not triage candidates at all.
    assert all("Clearance:GND" not in slot["key"] for slot in slots)


def test_the_key_is_the_sources_recipe_not_the_row_order():
    """The key is computed from the source data, so a reordered report re-keys nothing."""
    assert triage_key({"source": "host-erc", "severity": "warn"}) == "host-erc:warn"
    assert triage_key(
        {"source": "pcb-drc", "severity": "warn", "attribution": {"net": "VCC"}}, label="Clearance"
    ) == "pcb-drc:warn:Clearance:VCC"
    assert triage_key(
        {"source": "boardwise-rule", "severity": "WARN"}, rule_id=WARN_RULE, refs=["Y1", "Y2"]
    ) == f"boardwise-rule:{WARN_RULE}:Y1,Y2"


def test_the_merge_fills_matches_and_reports_what_it_could_not_match():
    slots = [
        {"key": "a", "verdict": "", "reason": ""},
        {"key": "b", "verdict": "", "reason": ""},
    ]
    entries = [
        {"key": "b", "verdict": "无害", "reason": "测试网络", "source": "boardwise-rule", "text": "…"},
        {"key": "gone", "verdict": "有益", "reason": "旧警告", "source": "pcb-drc", "text": "…"},
        {"key": "a", "verdict": "", "reason": "还没判", "source": "pcb-drc", "text": "…"},
        "not a dict",
    ]
    merged, matched, unmatched = merge_triage_sidecar(slots, entries)
    assert [slot["verdict"] for slot in merged] == ["", "无害"]
    assert merged[1]["reason"] == "测试网络"
    assert (matched, unmatched) == (1, 2), (
        "matched = entries that carried a verdict; the row with no decision is neither"
    )
    # ... and the slots handed in are not mutated: the merge is a reading.
    assert [slot["verdict"] for slot in slots] == ["", ""]


# --------------------------------------------------------------------------
# ② checkup folds the sidecar back in, and says so
# --------------------------------------------------------------------------


def test_checkup_merges_a_matching_sidecar_and_reports_the_rest(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    before = _checkup(board, out)
    capsys.readouterr()
    keys = _keys(before)
    assert _verdicts(before) == ["", "", ""], "nothing is judged yet"

    # A sidecar as `boardwise triage` would have left it, plus one entry whose
    # warning is gone from the board (`gone`) and one that decided nothing.
    entries = [
        {"key": keys[0], "verdict": "有害", "reason": "没有负载电容会起振不稳",
         "source": "boardwise-rule", "text": "Y1"},
        {"key": "boardwise-rule:xtal-load-caps:Y9", "verdict": "无害", "reason": "旧警告",
         "source": "boardwise-rule", "text": "Y9"},
        {"key": keys[1], "verdict": "", "reason": "还没判", "source": "boardwise-rule", "text": "Y2"},
    ]
    (out / "warning-triage.json").write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False), encoding="utf-8"
    )
    after = _checkup(board, out)
    printed = capsys.readouterr().out
    notes = " ".join(after["source"]["notes"])

    assert _verdicts(after) == ["有害", "", ""], "only the decided row comes back"
    assert after["warning_triage"][0]["reason"] == "没有负载电容会起振不稳"
    assert after["completion"]["warningsPendingTriage"] == 2
    # The undecided sidecar row (`keys[1]`, matched but carrying no verdict) is
    # neither merged nor "unmatched": there is no decision in it to put back.
    assert "里的 1 条分诊结论已并入本次报告（按 key 匹配）" in notes
    assert "1 条分诊结论没有对应槽位" in notes and "不删" in notes
    assert "已并入 1 条" in printed and "另 1 条没匹配上" in printed
    # checkup never writes that file: the audit trail is the triage command's.
    on_disk = _sidecar(out)
    assert on_disk["entries"] == entries


def test_a_bare_array_sidecar_is_the_same_information(tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    keys = _keys(_checkup(board, out))
    (out / "warning-triage.json").write_text(
        json.dumps([{"key": key, "verdict": "无害", "reason": "手工写的"} for key in keys[:2]],
                   ensure_ascii=False),
        encoding="utf-8",
    )
    assert _verdicts(_checkup(board, out)) == ["无害", "无害", ""]


def test_an_unreadable_sidecar_is_a_note_for_checkup_and_a_stop_for_triage(
    capsys, tmp_path, monkeypatch
):
    """The audit trail is never overwritten by a command that cannot read it."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    keys = _keys(_checkup(board, out))
    capsys.readouterr()
    sidecar = out / "warning-triage.json"
    sidecar.write_text("{ this is not JSON", encoding="utf-8")

    # `checkup` must still produce a report — it does not own that file.
    report = _checkup(board, out)
    assert "分诊侧车读不了" in " ".join(report["source"]["notes"])
    assert _verdicts(report) == ["", "", ""]
    assert sidecar.read_text(encoding="utf-8") == "{ this is not JSON"

    assert _triage(out, "--key", keys[0], "--verdict", "无害", "--reason", "读不出来就别动") == 2
    assert "侧车读不了" in capsys.readouterr().err
    assert sidecar.read_text(encoding="utf-8") == "{ this is not JSON"


# --------------------------------------------------------------------------
# ③ the command: one verdict, written twice, idempotent, and refusing typos
# --------------------------------------------------------------------------


def test_a_verdict_lands_in_the_report_the_gate_and_the_markdown(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    before = _checkup(board, out)
    capsys.readouterr()
    key = _keys(before)[0]
    assert before["completion"]["warningsPendingTriage"] == 3
    assert before["completion"]["verdict"] == "incomplete"

    assert _triage(out, "--key", key, "--verdict", "有害", "--reason", "振子两脚都没有负载电容") == 0
    printed = capsys.readouterr().out
    report = _read(out)

    assert report["completion"]["warningsPendingTriage"] == 2, "the count is recomputed, not stale"
    assert "2 条 warning 待分诊" in report["completion"]["verdictWhy"]
    assert "另有 2 条 warning 待分诊" in report["summary"]["conclusion"]
    slot = next(slot for slot in report["warning_triage"] if slot["key"] == key)
    assert (slot["verdict"], slot["reason"]) == ("有害", "振子两脚都没有负载电容")
    assert "verdict: 已新增" in printed
    assert "warning_triage: 已分诊 1/3 条（待分诊 2）" in printed
    assert "completion: incomplete" in printed

    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert f"| 0 | {key} |" in markdown, "the key is the column `boardwise triage --key` eats"
    assert "| 有害 | 振子两脚都没有负载电容 |" in markdown
    assert "boardwise triage --out" in markdown, "the table names the command that fills it"

    # The sidecar is the audit trail: what was judged, and enough context for a
    # human to read it without the report beside it.
    sidecar = _sidecar(out)
    assert sidecar["version"] == 1
    entry = sidecar["entries"][0]
    assert entry["key"] == key and entry["verdict"] == "有害"
    assert entry["source"] == "boardwise-rule" and "Y1" in entry["text"]


def test_judging_the_same_key_again_updates_it_and_adds_no_row(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    key = _keys(_checkup(board, out))[0]
    capsys.readouterr()
    assert _triage(out, "--key", key, "--verdict", "有益", "--reason", "第一次") == 0
    assert "已新增" in capsys.readouterr().out

    assert _triage(out, "--key", key, "--verdict", "无害", "--reason", "第二次") == 0
    second = capsys.readouterr().out
    assert "已存在，已更新" in second

    entries = _sidecar(out)["entries"]
    assert len(entries) == 1, "one row per key, whatever the number of runs"
    assert (entries[0]["verdict"], entries[0]["reason"]) == ("无害", "第二次")
    report = _read(out)
    assert _verdicts(report) == ["无害", "", ""]
    assert report["completion"]["warningsPendingTriage"] == 2


def test_an_unknown_key_is_refused_by_name_and_lists_what_is_pending(
    capsys, tmp_path, monkeypatch
):
    """A typo must not be recorded against nothing (063 §4)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    keys = _keys(_checkup(board, out))
    capsys.readouterr()

    assert _triage(out, "--key", "boardwise-rule:typo:Y1", "--verdict", "无害",
                   "--reason", "抄错了 key") == 2
    err = capsys.readouterr().err
    assert "报告里没有 key = boardwise-rule:typo:Y1 的槽位" in err
    assert "当前待分诊的 key（3 条）" in err
    for key in keys:
        assert key in err, "every pending key is listed, so the next attempt can name one"
    # Nothing was written: no sidecar, and the report still holds its old count.
    assert not (out / "warning-triage.json").exists()
    assert _read(out)["completion"]["warningsPendingTriage"] == 3


def test_a_report_without_keys_says_to_re_run_checkup(capsys, tmp_path, monkeypatch):
    """A pre-063 report has no `key` to match on — said out loud, not guessed at."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "old"
    out.mkdir()
    (out / "report.json").write_text(json.dumps({
        "schema": "boardwise.checkup/5",
        "summary": {"errorCount": 0},
        "warning_triage": [{"source": "host-erc", "severity": "warn", "verdict": "", "reason": ""}],
    }), encoding="utf-8")
    assert _triage(out, "--key", "host-erc:warn", "--verdict", "无害", "--reason", "旧报告") == 2
    err = capsys.readouterr().err
    assert "没有 key" in err and "重跑 `boardwise checkup`" in err


def test_a_missing_reason_is_refused(capsys, tmp_path, monkeypatch):
    """The reason is what makes the verdict reviewable, so it is not optional."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    key = _keys(_checkup(board, out))[0]
    capsys.readouterr()
    # argparse refuses the absent flag outright (`2` is this CLI's "bad input").
    with pytest.raises(SystemExit) as caught:
        _triage(out, "--key", key, "--verdict", "无害")
    assert caught.value.code == 2
    assert "--reason" in capsys.readouterr().err
    # ... and an empty one is refused by the command itself.
    assert _triage(out, "--key", key, "--verdict", "无害", "--reason", "   ") == 2
    assert "--reason" in capsys.readouterr().err
    assert not (out / "warning-triage.json").exists()
    assert _verdicts(_read(out)) == ["", "", ""]


def test_no_report_json_is_exit_three_and_writes_nothing(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "never-checked"
    assert _triage(out, "--key", "host-erc:warn", "--verdict", "无害", "--reason", "没有报告") == 3
    err = capsys.readouterr().err
    assert "checkup" in err and "不存在" in err
    assert not out.exists() or not list(out.iterdir())


def test_the_command_never_touches_the_editor(capsys, tmp_path, monkeypatch):
    """063 §4: purely offline. A bridge that refuses to open proves it."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    key = _keys(_checkup(board, out))[0]
    capsys.readouterr()

    import boardwise.bridge.client as client_module

    def _explode(*args, **kwargs):
        raise AssertionError("triage must not open a bridge connection")

    monkeypatch.setattr(client_module, "BridgeClient", _explode)
    assert _triage(out, "--key", key, "--verdict", "无害", "--reason", "离线") == 0
    assert _verdicts(_read(out))[0] == "无害"


# --------------------------------------------------------------------------
# ④ issue #12's own path: judge, re-run, and the judgement is still there
# --------------------------------------------------------------------------


def test_issue_12_the_verdicts_survive_a_re_run_of_checkup(capsys, tmp_path, monkeypatch):
    """The regression the issue asks for: the whole path, twice through `checkup`."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    _clean_board(monkeypatch)
    board, out = _board(tmp_path), tmp_path / "out"
    before = _checkup(board, out)
    capsys.readouterr()
    keys = _keys(before)
    assert len(keys) == 3
    # The premise: with the datasheet gate lifted, the warnings alone hold the
    # gate at `complete-with-open-items` — and nothing is judged yet.
    assert before["completion"]["verdict"] == "complete-with-open-items"
    assert before["completion"]["warningsPendingTriage"] == 3
    assert "3 条 warning 待分诊" in before["completion"]["verdictWhy"]

    wanted = [
        ("有益", "阻容在隔壁页，这里只是符号画法"),
        ("有害", "真没有负载电容，起振裕量不够"),
        ("无害", "该脚是测试焊盘，不接实际电路"),
    ]
    for key, (verdict, reason) in zip(keys, wanted):
        assert _triage(out, "--key", key, "--verdict", verdict, "--reason", reason) == 0
    capped = _read(out)
    assert capped["completion"]["warningsPendingTriage"] == 0
    assert capped["completion"]["verdict"] == "complete"
    assert capped["completion"]["verdictWhy"] == []
    capsys.readouterr()

    # The re-run that used to drop everything (issue #12, gap ②).
    after = _checkup(board, out)
    printed = capsys.readouterr().out
    assert _verdicts(after) == [verdict for verdict, _ in wanted], "verdict 还在"
    assert [slot["reason"] for slot in after["warning_triage"]] == [
        reason for _, reason in wanted
    ]
    assert after["completion"]["warningsPendingTriage"] == 0, "pending = 0"
    assert not any("待分诊" in why for why in after["completion"]["verdictWhy"]), (
        "verdict 不再说「待分诊」"
    )
    assert after["completion"]["verdict"] == "complete"
    assert "已并入 3 条" in printed
    # ... and the reader-facing copy says the same thing as the JSON.
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "（待填）" not in markdown
    for verdict, reason in wanted:
        assert f"| {verdict} | {reason} |" in markdown
    assert "待分诊 warning 0" in markdown


def test_the_three_verdicts_are_the_only_vocabulary(capsys, tmp_path, monkeypatch):
    """`--verdict` is a closed set: a judgement outside it is not a judgement."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    key = _keys(_checkup(board, out))[0]
    capsys.readouterr()
    with pytest.raises(SystemExit) as caught:
        _triage(out, "--key", key, "--verdict", "大概没事", "--reason", "随手写的")
    assert caught.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert set(TRIAGE_VERDICTS) == {"有益", "有害", "无害"}
