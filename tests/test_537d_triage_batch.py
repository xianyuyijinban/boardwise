"""537D1b1 — `boardwise triage-batch`: one atomic batch of warning verdicts.

The single-row command (`boardwise triage`, 063/070/537B) answers one warning at
a time, which is the right unit for a judgement and the wrong unit for a review:
a real board leaves several warnings to judge, and a caller that has to run the
command once per row can be interrupted halfway — leaving a report whose gate
already moved for row 1 while row 2 was never written (or worse, rejected).

This command is that batch, and its promise is **all or nothing**:

* the whole input is validated and applied **in memory** before any writer runs
  — an unknown key, an empty reason, a word outside the vocabulary, a three-word
  verdict on a slot with no per-item text, or the same key twice in the input
  refuses the **whole** batch with exit 2, and every artifact keeps its bytes;
* the input names a key at most once (a repeat would let order decide which
  verdict wins — a fake idempotence); a key the **report** carries twice is a
  different thing (a pre-070/hand-edited report): every matching slot is updated,
  the count is disclosed as `duplicateReportKeys`, and the console says so;
* each row goes through `_merge_triage_entry` and the 537B admissibility
  predicate, `_apply_warning_triage` rebuilds `completion`/`conclusion` **once**
  for the batch, and the four existing writers land the sidecar, `report.json`,
  `report.md` and `board-report.md`. `review-summary.md` is never touched;
* exit 0 means **the batch was applied**, not that the board passed — the
  report's own gate is quoted, never re-decided here.

The board is 063's synthetic crystals board (three real offline WARNs) plus one
synthetic text-less `host-erc` row, generated the way 537B generates it (a
wrapper around `warning_triage_slots`, so the row survives a re-run with the same
key). Anonymous synthetic data only; no editor, no daemon.
"""

from __future__ import annotations

import json

import pytest

import boardwise.cli as cli
import test_063_warning_triage as t063
import test_537b_triage_manual as t537b
from boardwise.engines.checkup import TRIAGE_UNJUDGEABLE, TRIAGE_VERDICTS

HOST_ERC_KEY = t537b.HOST_ERC_KEY
HOST_ERC_COUNT = t537b.HOST_ERC_COUNT

#: The artifacts a batch may rewrite. A refused batch must leave every one of
#: them byte-identical (and a file that did not exist must still not exist).
ARTIFACTS = (
    "report.json",
    "warning-triage.json",
    "report.md",
    "board-report.md",
    "review-summary.md",
    "live-evidence.json",
)

#: `--json` may never overwrite these, however it spells the path.
PROTECTED = (
    "report.json",
    "report.md",
    "board-report.md",
    "review-summary.md",
    "live-evidence.json",
    "warning-triage.json",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _snapshot(out) -> dict:
    """Every artifact's bytes, or ``None`` where the file does not exist."""
    from pathlib import Path

    directory = Path(out)
    return {
        name: (directory / name).read_bytes() if (directory / name).is_file() else None
        for name in ARTIFACTS
    }


def _input(tmp_path, rows, *, name="batch.json", schema="boardwise.triage-batch/1"):
    """Write a batch input file and return its path."""
    path = tmp_path / name
    payload = {"schema": schema, "entries": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _raw_input(tmp_path, text: str, *, name="batch.json"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _batch(out, input_path, *extra: str) -> int:
    """Run the command as the CLI would, exactly as a caller spells it."""
    return cli.main(
        ["triage-batch", "--out", str(out), "--input", str(input_path), *extra]
    )


def _json_result(capsys, out, input_path) -> tuple[int, dict]:
    code = _batch(out, input_path, "--json", "-")
    printed = capsys.readouterr().out
    return code, json.loads(printed)


def _slots_for(report: dict, key: str) -> list[dict]:
    return [slot for slot in report["warning_triage"] if str(slot.get("key") or "") == key]


def _manual_rows(report: dict) -> list[dict]:
    return (report.get("completion") or {}).get("manualReviewRequired") or []


@pytest.fixture
def host_erc(monkeypatch) -> str:
    """537B's text-less `host-erc` row, regenerated on every `checkup`."""
    real = cli.warning_triage_slots

    def wrapped(**kwargs):
        return [*real(**kwargs), t537b._host_erc_slot()]

    monkeypatch.setattr(cli, "warning_triage_slots", wrapped)
    return HOST_ERC_KEY


def _prepared(tmp_path, monkeypatch):
    """A real offline report (3 crystals, optionally + host-ERC) and its keys."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    t063._clean_board(monkeypatch)
    board, out = t063._board(tmp_path), tmp_path / "out"
    report = t063._checkup(board, out)
    return board, out, t063._keys(report)


# --------------------------------------------------------------------------
# ① the happy path: a mixed batch, applied once, in both places
# --------------------------------------------------------------------------


def test_a_mixed_batch_lands_in_the_report_the_sidecar_and_the_gate(
    capsys, tmp_path, monkeypatch, host_erc
):
    """Three words on a row with text + `needs-manual` on the text-less row."""
    board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    text_key = next(key for key in keys if key != HOST_ERC_KEY)
    assert len(keys) == 4, "3 crystals + 1 host-ERC row"
    before = t063._read(out)
    assert before["completion"]["warningsPendingTriage"] == 4
    assert before["completion"]["warningsNeedsManual"] == 0
    summary_before = _snapshot(out)["review-summary.md"]

    manual_reason = "主机 ERC 只给合计，逐条文本要人去面板看"
    rows = [
        {"key": text_key, "verdict": "无害", "reason": "该脚是测试焊盘"},
        {"key": HOST_ERC_KEY, "verdict": TRIAGE_UNJUDGEABLE, "reason": manual_reason},
    ]
    code = _batch(out, _input(tmp_path, rows))
    printed = capsys.readouterr().out

    assert code == 0, "the batch was applied — not a statement that the board passed"
    report = t063._read(out)
    judged = _slots_for(report, text_key)
    assert len(judged) == 1
    assert (judged[0]["verdict"], judged[0]["reason"]) == ("无害", "该脚是测试焊盘")
    manual_slot = _slots_for(report, HOST_ERC_KEY)[0]
    assert (manual_slot["verdict"], manual_slot["reason"]) == (
        TRIAGE_UNJUDGEABLE,
        manual_reason,
    )

    completion = report["completion"]
    assert completion["warningsPendingTriage"] == 3, "2 crystals + the needs-manual row"
    assert completion["warningsNeedsManual"] == 1
    assert len(_manual_rows(report)) == completion["warningsNeedsManual"], (
        "the list and the count are the same arithmetic"
    )
    assert _manual_rows(report) == [
        {
            "key": HOST_ERC_KEY,
            "source": "host-erc",
            "count": HOST_ERC_COUNT,
            "reason": manual_reason,
        }
    ]
    assert completion["verdict"] == "complete-with-open-items"
    assert "needs-manual" in "；".join(completion["verdictWhy"])

    sidecar = t063._sidecar(out)
    assert len(sidecar["entries"]) == 2
    assert {entry["key"] for entry in sidecar["entries"]} == {text_key, HOST_ERC_KEY}

    # Console: how many rows, where the gate stands, and the conclusion.
    assert "2 条判决已应用" in printed
    assert "新增 2 / 更新 0" in printed
    assert "待分诊 3" in printed and "needs-manual 1" in printed
    assert "conclusion:" in printed

    # The one artifact the batch may not write: the model's own skeleton.
    assert _snapshot(out)["review-summary.md"] == summary_before
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "待分诊 warning 3" in markdown
    assert manual_reason in markdown


def test_the_same_batch_again_updates_and_adds_no_sidecar_row(
    capsys, tmp_path, monkeypatch, host_erc
):
    """Idempotent by key: a re-run changes the counts in the console, not the rows."""
    board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    text_key = next(key for key in keys if key != HOST_ERC_KEY)
    rows = [
        {"key": text_key, "verdict": "有害", "reason": "真没有负载电容"},
        {"key": HOST_ERC_KEY, "verdict": TRIAGE_UNJUDGEABLE, "reason": "要人工看"},
    ]
    path = _input(tmp_path, rows)
    assert _batch(out, path) == 0
    capsys.readouterr()

    assert _batch(out, path) == 0
    second = capsys.readouterr().out
    assert "更新 2" in second and "新增 0" in second
    assert len(t063._sidecar(out)["entries"]) == 2, "one row per key, however many runs"
    # ... and a `checkup` re-run folds both back, still pending where it matters.
    after = t063._checkup(board, out)
    assert "已并入 2 条" in capsys.readouterr().out
    assert after["completion"]["warningsPendingTriage"] == 3
    assert after["completion"]["warningsNeedsManual"] == 1
    assert _slots_for(after, text_key)[0]["verdict"] == "有害"
    assert _slots_for(after, HOST_ERC_KEY)[0]["verdict"] == TRIAGE_UNJUDGEABLE


# --------------------------------------------------------------------------
# ② atomicity: a bad row anywhere refuses the whole batch, byte for byte
# --------------------------------------------------------------------------


def _two_rows(keys: list[str]) -> list[dict]:
    text_keys = [key for key in keys if key != HOST_ERC_KEY]
    return [
        {"key": text_keys[0], "verdict": "无害", "reason": "这一行本身是合法的"},
        {"key": text_keys[1], "verdict": "有害", "reason": "第二行也合法"},
    ]


def test_a_second_row_with_an_unknown_key_leaves_every_byte_alone(
    capsys, tmp_path, monkeypatch, host_erc
):
    """The failure has to be found *before* row 1 is written — not after."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    rows = _two_rows(keys)
    rows[1] = {"key": "boardwise-rule:typo:Y9", "verdict": "有益", "reason": "抄错了 key"}
    before = _snapshot(out)

    assert _batch(out, _input(tmp_path, rows)) == 2
    err = capsys.readouterr().err
    assert "boardwise-rule:typo:Y9" in err and "没有 key" in err
    assert "第 2 行" in err or "2 行" in err
    assert "当前待分诊的 key" in err, "the refusal lists what could have been named"
    assert _snapshot(out) == before, "row 1 was legal, and still nothing was written"
    assert t063._verdicts(t063._read(out)) == ["", "", "", ""]


def test_a_second_row_of_a_textless_three_word_verdict_leaves_every_byte_alone(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B's predicate, asked for the whole batch up front."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    text_key = next(key for key in keys if key != HOST_ERC_KEY)
    rows = [
        {"key": text_key, "verdict": "无害", "reason": "合法的一行"},
        {"key": HOST_ERC_KEY, "verdict": "有害", "reason": "一条计数不是一条警告"},
    ]
    before = _snapshot(out)

    assert _batch(out, _input(tmp_path, rows)) == 2
    err = capsys.readouterr().err
    assert "没有逐条文本" in err and "needs-manual" in err and HOST_ERC_KEY in err
    assert _snapshot(out) == before
    assert not (out / "warning-triage.json").exists()


def test_duplicate_input_keys_are_refused_even_when_identical(
    capsys, tmp_path, monkeypatch
):
    """Order must never decide which verdict wins — not even for equal content."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    row = {"key": keys[0], "verdict": "无害", "reason": "同一行写了两遍"}
    before = _snapshot(out)

    assert _batch(out, _input(tmp_path, [row, dict(row)])) == 2
    err = capsys.readouterr().err
    assert "重复" in err and keys[0] in err
    assert _snapshot(out) == before
    assert not (out / "warning-triage.json").exists()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"entries": [{"key": "k", "verdict": "无害", "reason": "r"}]},
                     id="no-schema"),
        pytest.param({"schema": "boardwise.triage-batch/2",
                      "entries": [{"key": "k", "verdict": "无害", "reason": "r"}]},
                     id="wrong-schema"),
        pytest.param({"schema": "boardwise.triage-batch/1", "entries": []},
                     id="empty-entries"),
        pytest.param({"schema": "boardwise.triage-batch/1", "entries": "nope"},
                     id="entries-not-a-list"),
        pytest.param({"schema": "boardwise.triage-batch/1", "entries": ["nope"]},
                     id="row-not-an-object"),
        pytest.param({"schema": "boardwise.triage-batch/1",
                      "entries": [{"key": "k", "verdict": "无害"}]},
                     id="no-reason"),
        pytest.param({"schema": "boardwise.triage-batch/1",
                      "entries": [{"key": "k", "verdict": "无害", "reason": "   "}]},
                     id="blank-reason"),
        pytest.param({"schema": "boardwise.triage-batch/1",
                      "entries": [{"key": "  ", "verdict": "无害", "reason": "r"}]},
                     id="blank-key"),
        pytest.param({"schema": "boardwise.triage-batch/1",
                      "entries": [{"key": "k", "verdict": "大概没事", "reason": "r"}]},
                     id="word-outside-the-vocabulary"),
        pytest.param({"schema": "boardwise.triage-batch/1",
                      "entries": [{"key": "k", "verdict": "", "reason": "r"}]},
                     id="empty-verdict"),
        pytest.param([{"key": "k", "verdict": "无害", "reason": "r"}],
                     id="top-level-array"),
    ],
)
def test_malformed_input_is_exit_two_and_writes_nothing(
    capsys, tmp_path, monkeypatch, payload
):
    """Structural validation happens before the report is even touched."""
    _board, out, _keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = _snapshot(out)

    assert _batch(out, path) == 2
    assert capsys.readouterr().err, "a refusal says why"
    assert _snapshot(out) == before
    assert not (out / "warning-triage.json").exists()


def test_invalid_json_and_a_missing_input_are_exit_two(capsys, tmp_path, monkeypatch):
    _board, out, _keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    before = _snapshot(out)

    assert _batch(out, _raw_input(tmp_path, "{ not json")) == 2
    assert "JSON" in capsys.readouterr().err, "the refusal names the input it read"
    # A missing input is the same refusal, and still writes nothing.
    assert _batch(out, tmp_path / "never-written.json") == 2
    assert capsys.readouterr().err
    assert _snapshot(out) == before


# --------------------------------------------------------------------------
# ②b the types the strict object promises: JSON strings, and a report shape
#     the command can actually re-gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"reason": {"not": "text"}}, id="reason-is-an-object"),
        pytest.param({"reason": ["not", "text"]}, id="reason-is-an-array"),
        pytest.param({"reason": 123}, id="reason-is-a-number"),
        pytest.param({"reason": None}, id="reason-is-null"),
        pytest.param({"key": 123}, id="key-is-a-number"),
        pytest.param({"key": None}, id="key-is-null"),
        pytest.param({"key": ["x"]}, id="key-is-an-array"),
    ],
)
def test_a_non_string_key_or_reason_is_exit_two_and_writes_nothing(
    capsys, tmp_path, monkeypatch, override
):
    """`str(...)` is not validation: `{"not": "text"}` is not a reason.

    The row otherwise names a real key with a legal verdict, so the only thing
    wrong with it is a JSON type — which is exactly the boundary a loader that
    coerces would quietly write down (`reason="{...}"`) and exit 0 on.
    """
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    row = {"key": keys[0], "verdict": "无害", "reason": "合法理由", **override}
    before = _snapshot(out)

    assert _batch(out, _input(tmp_path, [row])) == 2
    err = capsys.readouterr().err
    assert "字符串" in err and ("key" in err or "reason" in err)
    assert _snapshot(out) == before, "nothing was written for the legal-looking row"
    assert not (out / "warning-triage.json").exists()
    assert t063._verdicts(t063._read(out)) == ["", "", ""]


@pytest.mark.parametrize(
    "bad_triage",
    [
        pytest.param({"not": "a list"}, id="warning-triage-is-an-object"),
        pytest.param("nope", id="warning-triage-is-a-string"),
        pytest.param([["not", "a", "dict"]], id="a-row-is-an-array"),
        pytest.param([{"key": "ok"}, "nope"], id="a-later-row-is-a-string"),
    ],
)
def test_a_malformed_warning_triage_is_exit_two_and_not_a_traceback(
    capsys, tmp_path, monkeypatch, bad_triage
):
    """`[dict(slot) ...]` on a dict of strings raises `ValueError` — not an answer.

    A report whose `warning_triage` is not a list of objects cannot be triaged;
    the command has to say so with exit 2 (the CLI's "bad input") before any
    writer, instead of letting the copy expression decide what happens.
    """
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    report = t063._read(out)
    report["warning_triage"] = bad_triage
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    before = _snapshot(out)
    path = _input(tmp_path, [{"key": keys[0], "verdict": "无害", "reason": "合法"}])

    code = _batch(out, path)  # must return, not raise
    assert code == 2
    err = capsys.readouterr().err
    assert "warning_triage" in err
    assert _snapshot(out) == before
    assert not (out / "warning-triage.json").exists()


@pytest.mark.parametrize(
    "summary",
    [
        pytest.param("missing", id="summary-missing"),
        pytest.param([], id="summary-is-an-array"),
        pytest.param("text", id="summary-is-a-string"),
    ],
)
def test_a_report_that_cannot_be_regated_is_exit_two_before_any_write(
    capsys, tmp_path, monkeypatch, summary
):
    """`_apply_warning_triage` is in-memory; its shape errors map to exit 2.

    The catch is deliberately narrow (and does not wrap the writers): a
    `KeyError`/`TypeError`/`ValueError`/`AttributeError` from the re-gate means
    this report cannot carry a verdict, so the batch is refused as bad input —
    not a traceback, and not a half-written directory.
    """
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    report = t063._read(out)
    if summary == "missing":
        report.pop("summary")
    else:
        report["summary"] = summary
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    before = _snapshot(out)
    path = _input(tmp_path, [{"key": keys[0], "verdict": "无害", "reason": "合法"}])

    code = _batch(out, path)  # must return, not raise
    assert code == 2
    err = capsys.readouterr().err
    assert "整批不写" in err or "结构" in err
    assert _snapshot(out) == before


# --------------------------------------------------------------------------
# ③ the report's own duplicate key: every match updated, and disclosed
# --------------------------------------------------------------------------


def test_a_key_the_report_carries_twice_updates_both_and_is_disclosed(
    capsys, tmp_path, monkeypatch
):
    """A pre-070/hand-edited report: never silently judge one of the two."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    key = keys[0]
    report = t063._read(out)
    duplicated = dict(_slots_for(report, key)[0])
    report["warning_triage"].append(duplicated)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rows = [{"key": key, "verdict": "无害", "reason": "两行同 key，都该更新"}]
    assert _batch(out, _input(tmp_path, rows)) == 0
    after = t063._read(out)
    matched = _slots_for(after, key)
    assert len(matched) == 2
    assert [slot["verdict"] for slot in matched] == ["无害", "无害"], (
        "both matching slots carry the verdict"
    )
    assert [slot["reason"] for slot in matched] == ["两行同 key，都该更新"] * 2

    # ... and it is said, not left for the caller to discover.
    capsys.readouterr()
    code, payload = _json_result(capsys, out, _input(tmp_path, rows, name="again.json"))
    assert code == 0
    assert payload["duplicateReportKeys"] == [key]
    assert payload["applied"][0]["matched"] == 2


# --------------------------------------------------------------------------
# ④ the result envelope: complete, honest about its own exit code
# --------------------------------------------------------------------------


def test_the_result_json_is_complete_and_carries_no_board_verdict(
    capsys, tmp_path, monkeypatch, host_erc
):
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    text_key = next(key for key in keys if key != HOST_ERC_KEY)
    rows = [
        {"key": text_key, "verdict": "有益", "reason": "隔壁页有阻容"},
        {"key": HOST_ERC_KEY, "verdict": TRIAGE_UNJUDGEABLE, "reason": "人工复核"},
    ]
    code, payload = _json_result(capsys, out, _input(tmp_path, rows))

    assert code == 0
    assert payload["schema"] == "boardwise.triage-batch-result/1"
    assert "ok" not in payload, "exit 0 means applied, not a board-level pass"
    applied = payload["applied"]
    assert [row["key"] for row in applied] == [text_key, HOST_ERC_KEY]
    assert [row["verdict"] for row in applied] == ["有益", TRIAGE_UNJUDGEABLE]
    assert [row["reason"] for row in applied] == ["隔壁页有阻容", "人工复核"]
    assert [row["matched"] for row in applied] == [1, 1]
    assert [row["added"] for row in applied] == [1, 1]
    assert [row["updated"] for row in applied] == [0, 0]
    assert (payload["added"], payload["updated"]) == (2, 0) == (
        sum(row["added"] for row in applied),
        sum(row["updated"] for row in applied),
    )
    assert payload["duplicateReportKeys"] == []
    assert payload["warning_triage"] == t063._read(out)["warning_triage"]
    assert payload["completion"] == t063._read(out)["completion"]
    assert payload["conclusionSection"] == t063._read(out)["conclusion"]
    assert payload["conclusion"] == t063._read(out)["summary"]["conclusion"]
    assert payload["report"] == str(out / "report.json")
    assert payload["sidecar"] == str(out / "warning-triage.json")
    assert payload["reportMd"] == str(out / "report.md")
    assert payload["boardReport"] == str(out / "board-report.md")
    # The command's own exit code is not the board's: the report records its own.
    assert payload["completion"]["verdict"] == "complete-with-open-items"


def test_json_mode_keeps_the_console_out_of_stdout(capsys, tmp_path, monkeypatch):
    """`--json -` is JSON and nothing else; `--json PATH` writes the same bytes."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    rows = [{"key": keys[0], "verdict": "无害", "reason": "字节对齐"}]
    path = _input(tmp_path, rows)

    # First run: establish the idempotent state, console only (no `--json`).
    assert _batch(out, path) == 0
    console = capsys.readouterr().out
    assert console.startswith(" "), "the human summary is not JSON"
    assert "条判决已应用" in console
    assert not console.lstrip().startswith("{")

    # Second run, stdout form.
    assert _batch(out, path, "--json", "-") == 0
    captured = capsys.readouterr().out
    blob = captured.encode("utf-8")
    parsed = json.loads(captured)
    assert parsed["schema"] == "boardwise.triage-batch-result/1"
    assert not captured.startswith(" "), "no console line sneaked into the JSON stream"
    assert captured.endswith("\n")

    # Third run, file form — and stdout stays empty.
    target = tmp_path / "result.json"
    report_before = (out / "report.json").read_bytes()
    assert _batch(out, path, "--json", str(target)) == 0
    assert capsys.readouterr().out == "", "`--json PATH` owns stdout for nothing"
    assert target.read_bytes() == blob, "the two forms are the same UTF-8 bytes"
    assert b"\r\n" not in blob, "bytes, not Windows line endings"
    # The same state applied twice is a fixed point, which is what made the
    # comparison meaningful: the report did not move under the second run.
    assert (out / "report.json").read_bytes() == report_before


# --------------------------------------------------------------------------
# ⑤ the output path is chosen before any writer runs
# --------------------------------------------------------------------------


def test_a_protected_output_path_is_refused_before_any_write(
    capsys, tmp_path, monkeypatch, host_erc
):
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    text_key = next(key for key in keys if key != HOST_ERC_KEY)
    path = _input(tmp_path, [{"key": text_key, "verdict": "无害", "reason": "合法"}])
    before = _snapshot(out)

    for name in (*PROTECTED, "batch.json"):
        target = tmp_path / name if name == "batch.json" else out / name
        assert _batch(out, path, "--json", str(target)) == 2, name
        err = capsys.readouterr().err
        assert "拒绝" in err or "保护" in err, name
        assert _snapshot(out) == before, f"{name}: not one artifact may move"
        if name in ("warning-triage.json", "live-evidence.json"):
            assert not (out / name).exists(), f"{name} must not appear on a refusal"


def test_the_input_file_is_a_protected_output_path_too(
    capsys, tmp_path, monkeypatch
):
    """`--json` at the input would eat the batch it is reporting on."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    path = _input(tmp_path, [{"key": keys[0], "verdict": "无害", "reason": "r"}])
    input_before = path.read_bytes()
    before = _snapshot(out)

    assert _batch(out, path, "--json", str(path)) == 2
    assert capsys.readouterr().err
    assert path.read_bytes() == input_before
    assert _snapshot(out) == before


def test_a_directory_as_output_path_is_exit_two(capsys, tmp_path, monkeypatch):
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    path = _input(tmp_path, [{"key": keys[0], "verdict": "无害", "reason": "r"}])
    before = _snapshot(out)
    target = tmp_path / "a-directory"
    target.mkdir()

    assert _batch(out, path, "--json", str(target)) == 2
    assert capsys.readouterr().err
    assert _snapshot(out) == before


# --------------------------------------------------------------------------
# ⑥ the doors it does not open: no report, unreadable sidecar
# --------------------------------------------------------------------------


def test_no_report_json_is_exit_three_and_writes_nothing(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "never-checked"
    path = _input(tmp_path, [{"key": "host-erc:warn", "verdict": "无害", "reason": "r"}])

    assert _batch(out, path) == 3
    err = capsys.readouterr().err
    assert "report.json" in err and "不存在" in err and "checkup" in err
    assert not out.exists() or not list(out.iterdir())


def test_an_unreadable_sidecar_stops_the_batch_and_is_not_overwritten(
    capsys, tmp_path, monkeypatch
):
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    sidecar = out / "warning-triage.json"
    sidecar.write_text("{ this is not JSON", encoding="utf-8")
    before = _snapshot(out)
    path = _input(tmp_path, [{"key": keys[0], "verdict": "无害", "reason": "r"}])

    assert _batch(out, path) == 2
    assert "侧车读不了" in capsys.readouterr().err
    assert _snapshot(out) == before
    assert sidecar.read_text(encoding="utf-8") == "{ this is not JSON"


def test_an_unreadable_report_is_exit_two_and_left_alone(
    capsys, tmp_path, monkeypatch
):
    """`report.json` is the input this command reads and never repairs."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    (out / "report.json").write_text("{ this is not JSON", encoding="utf-8")
    before = _snapshot(out)
    path = _input(tmp_path, [{"key": keys[0], "verdict": "无害", "reason": "r"}])

    assert _batch(out, path) == 2
    assert "report.json" in capsys.readouterr().err
    assert _snapshot(out) == before, "a report that cannot be read is not overwritten"
    assert not (out / "warning-triage.json").exists()


# --------------------------------------------------------------------------
# ⑦ the single-row command is untouched
# --------------------------------------------------------------------------


def test_the_single_row_triage_command_still_behaves(capsys, tmp_path, monkeypatch):
    """537D1b1 adds a command; 063/070/537B keep their contract."""
    _board, out, keys = _prepared(tmp_path, monkeypatch)
    capsys.readouterr()
    key = keys[0]

    # argparse still demands the three flags ...
    with pytest.raises(SystemExit) as caught:
        t063._triage(out, "--key", key, "--verdict", "无害")
    assert caught.value.code == 2
    assert "--reason" in capsys.readouterr().err
    # ... and one row still lands exactly where it did before.
    assert t063._triage(out, "--key", key, "--verdict", "无害", "--reason", "测试焊盘") == 0
    printed = capsys.readouterr().out
    assert "verdict: 已新增" in printed
    assert t063._verdicts(t063._read(out)) == ["无害", "", ""]
    assert len(t063._sidecar(out)["entries"]) == 1


def test_the_batch_command_requires_its_own_two_arguments(capsys):
    """One vocabulary, two commands — and the new one demands `--out` + `--input`."""
    assert set(TRIAGE_VERDICTS) == {"有益", "有害", "无害"}
    with pytest.raises(SystemExit) as caught:
        cli.main(["triage-batch", "--out", "x"])
    assert caught.value.code == 2
    assert "--input" in capsys.readouterr().err
