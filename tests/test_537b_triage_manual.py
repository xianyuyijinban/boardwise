"""537B — the warning-triage hard gate: `needs-manual` for a slot with no text.

The gap this file pins, measured in the original session (seq 320 → seq 435):
the host's ERC answer is *only* per-kind totals (`drc.schematic.totals`), the
per-item text lives in the editor's bottom panel and has no read interface
(:data:`ERC_TEXT_UNAVAILABLE`) — and yet the slot was closeable with the three
words. Marking those warnings 「有害」 emptied `warningsPendingTriage` and the run
read as fully triaged while nobody had seen a single warning. Editing
`warning-triage.json` by hand did the same thing through the sidecar, so the gate
has to hold on both doors.

What is pinned:

* `TRIAGE_VERDICTS` stays exactly three words and `needs-manual` sits **beside**
  them (:data:`TRIAGE_UNJUDGEABLE` + the argparse vocabulary), not inside;
* a slot whose `text` is empty cannot be closed with a three-word verdict —
  neither by `boardwise triage` (which refuses and writes nothing) nor by a
  hand-edited sidecar (the merge refuses to fold it in, and says so in `notes`).
  On a `host-erc` row **deleting** the field is the same statement as leaving it
  empty (the source has no items to put there), so a hand-trimmed `report.json`
  is not a way around the gate either — while a `host-erc` row that does carry
  text stays judgeable;
* `needs-manual` is **written** (with a reason, which stays required) and still
  counts as pending; `completion` gains `warningsNeedsManual` and
  `manualReviewRequired`, additively;
* the console line, `report.md` and `completion.verdictWhy` count from the same
  arithmetic, and a verdict outside the vocabulary is never read as triaged;
* a `needs-manual` verdict survives a `checkup` re-run through the sidecar and is
  still pending afterwards;
* the three-word vocabulary on a slot that *has* text behaves exactly as 063/070
  left it.

The board is 063's synthetic crystal board (three real `xtal-load-caps` WARNs,
offline, no editor, no daemon). The **host-ERC row is synthesised where it is
generated**, not patched into `report.json` afterwards: the offline path never
asks an editor for ERC (``--file`` says so itself), so the honest way to get this
row is to hand it to `warning_triage_slots` — the fixture wraps that generator,
which means the row comes back on **every** re-run with the same key
(`host-erc:warn`, the recipe `triage_key` computes for this source). Written that
way the test exercises the real life cycle — generated, folded back from the
sidecar by key — and is not a row that a second `checkup` would sweep away.
"""

from __future__ import annotations

import json

import pytest

import boardwise.cli as cli
import test_063_warning_triage as t063
from boardwise.engines.checkup import (
    ERC_TEXT_UNAVAILABLE,
    TRIAGE_UNJUDGEABLE,
    TRIAGE_VERDICT_CHOICES,
    TRIAGE_VERDICTS,
    merge_triage_sidecar,
    triage_slot_is_closed,
    triage_verdict_is_admissible,
)

#: The key `triage_key` computes for a host-ERC row (063 §1). No other row of
#: this board can claim it, so the merge sees exactly one slot per key.
HOST_ERC_KEY = "host-erc:warn"

#: How many warnings the synthetic host answered for (a count with no items —
#: which is the whole point of the gap).
HOST_ERC_COUNT = 7


# --------------------------------------------------------------------------
# the synthetic host-ERC row, and the fixture that makes it come back
# --------------------------------------------------------------------------


def _host_erc_slot() -> dict:
    """One `host-erc` slot exactly as `warning_triage_slots` builds it: no text."""
    return {
        "key": HOST_ERC_KEY,
        "source": "host-erc",
        "severity": "warn",
        "count": HOST_ERC_COUNT,
        "text": "",
        "textUnavailable": ERC_TEXT_UNAVAILABLE,
        "attribution": {"scope": "host-wide", "page": None, "module": None},
        "verdict": "",
        "reason": "",
        "evidence": [f"drc.schematic.totals['warn'] = {HOST_ERC_COUNT}"],
    }


@pytest.fixture
def host_erc(monkeypatch) -> str:
    """A text-less `host-erc` row on a real offline report — and on its re-runs.

    The patch sits on the **generator**, not on `report.json`: every `checkup`
    call re-generates the row with the same key, which is what the sidecar merge
    matches on. That is the difference between testing the merge and testing a
    row that a second run would simply drop.
    """
    real = cli.warning_triage_slots

    def wrapped(**kwargs):
        return [*real(**kwargs), _host_erc_slot()]

    monkeypatch.setattr(cli, "warning_triage_slots", wrapped)
    return HOST_ERC_KEY


def _board(tmp_path):
    """063's synthetic crystals board (three offline WARNs), reused as-is."""
    return t063._board(tmp_path)


def _reasons(report: dict) -> list[str]:
    return [str(slot.get("reason") or "") for slot in report["warning_triage"]]


def _notes(report: dict) -> str:
    return " ".join(report.get("source", {}).get("notes") or [])


def _manual_rows(report: dict) -> list[dict]:
    return (report.get("completion") or {}).get("manualReviewRequired") or []


# --------------------------------------------------------------------------
# ① the vocabulary: three words stay three words
# --------------------------------------------------------------------------


def test_needs_manual_sits_beside_the_three_words_and_never_joins_them():
    """537B §1: the old set is untouched, the new word is a peer of it."""
    assert set(TRIAGE_VERDICTS) == {"有益", "有害", "无害"}
    assert TRIAGE_UNJUDGEABLE == "needs-manual"
    assert TRIAGE_UNJUDGEABLE not in TRIAGE_VERDICTS, (
        "the fourth word must not be pushed into the three-word vocabulary — "
        "every reader of TRIAGE_VERDICTS treats a member as a closed judgement"
    )
    # ... and it *is* accepted by argparse: the command has to be able to write it.
    assert list(TRIAGE_VERDICT_CHOICES)[: len(TRIAGE_VERDICTS)] == list(TRIAGE_VERDICTS)
    assert TRIAGE_UNJUDGEABLE in TRIAGE_VERDICT_CHOICES


# --------------------------------------------------------------------------
# ② the merge: a hand-edited sidecar cannot close a slot with no text
# --------------------------------------------------------------------------


def test_the_merge_refuses_a_three_word_verdict_where_there_is_no_text():
    """537B §4: not merged, not `unmatched` — refused, and reported as refused."""
    slots = [
        {"key": HOST_ERC_KEY, "source": "host-erc", "severity": "warn",
         "count": HOST_ERC_COUNT, "text": "", "verdict": "", "reason": ""},
        {"key": "boardwise-rule:xtal-load-caps:Y1", "source": "boardwise-rule",
         "severity": "WARN", "count": 1, "text": "xtal-load-caps：没有负载电容",
         "verdict": "", "reason": ""},
    ]
    entries = [
        {"key": HOST_ERC_KEY, "verdict": "有害", "reason": "seq 320 的手改法", "source": "host-erc",
         "text": ""},
        {"key": HOST_ERC_KEY, "verdict": "大概没事", "reason": "词表外", "source": "host-erc"},
        {"key": "boardwise-rule:xtal-load-caps:Y1", "verdict": "无害", "reason": "有负载电容",
         "source": "boardwise-rule", "text": "xtal-load-caps：没有负载电容"},
    ]
    refused: list[dict] = []
    merged, matched, unmatched = merge_triage_sidecar(slots, entries, refused=refused)

    # The triple return is the contract (537B §4) — nothing about the shape moved.
    assert isinstance(merged, list) and isinstance(matched, int) and isinstance(unmatched, int)
    assert [slot["verdict"] for slot in merged] == ["", "无害"], (
        "the text-less row keeps its empty verdict; the textual one folds in"
    )
    assert (matched, unmatched) == (1, 0), (
        "a refused entry is neither merged nor unmatched: its key *does* exist here"
    )
    assert [entry["verdict"] for entry in refused] == ["有害", "大概没事"], (
        "both the three-word guess and the word outside the vocabulary are refused"
    )


def test_the_merge_refuses_a_deleted_text_field_on_a_host_erc_row_too():
    """537B follow-up: 「无逐条文本」 is a **host-ERC fact**, not only an empty field.

    Measured by the reviewer: a slot `{"source": "host-erc"}` whose `text` key had
    been deleted was read as judgeable, so a hand-trimmed `report.json` cleared
    pending exactly like the seq 320 verdict did. The source is the evidence here —
    the host's ERC answer has no items to put in that field
    (:data:`ERC_TEXT_UNAVAILABLE`) — so on this source a missing field is the same
    statement as an empty one.
    """
    slots = [
        {"key": HOST_ERC_KEY, "source": "host-erc", "severity": "warn",
         "count": HOST_ERC_COUNT, "verdict": "", "reason": ""},  # no `text` key at all
    ]
    entries = [{"key": HOST_ERC_KEY, "verdict": "有害", "reason": "删了 text 再判",
                "source": "host-erc"}]
    refused: list[dict] = []
    merged, matched, unmatched = merge_triage_sidecar(slots, entries, refused=refused)

    assert [slot["verdict"] for slot in merged] == [""], "the deleted field is no shortcut"
    assert (matched, unmatched) == (0, 0), "refused: neither merged nor a miss"
    assert len(refused) == 1 and refused[0]["verdict"] == "有害"


def test_a_host_erc_row_that_does_carry_text_is_judgeable():
    """The boundary the fix must not overshoot: a host row **with** text is judgeable.

    Today's generator writes no text for this source, but the gate reads the
    evidence rather than the provenance: if a future read interface fills the field
    in, the three words become admissible for it and nothing here has to move.
    """
    with_text = {"key": HOST_ERC_KEY, "source": "host-erc", "severity": "warn",
                 "count": 1, "text": "Clearance：too close", "verdict": "",
                 "reason": ""}
    assert triage_verdict_is_admissible(with_text, "有害") is True
    assert triage_slot_is_closed({**with_text, "verdict": "有害"}) is True
    # ... while the same row without the text is closed by neither.
    without = {key: value for key, value in with_text.items() if key != "text"}
    assert triage_verdict_is_admissible(without, "有害") is False
    assert triage_slot_is_closed({**without, "verdict": "有害"}) is False


# --------------------------------------------------------------------------
# ③ the command: refuses to close, writes nothing; writes needs-manual
# --------------------------------------------------------------------------


def test_the_command_refuses_to_close_a_slot_that_has_no_text(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B §2: the door `boardwise triage` used to leave open."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    before = t063._checkup(board, out)
    capsys.readouterr()
    assert HOST_ERC_KEY in t063._keys(before)
    assert before["completion"]["warningsPendingTriage"] == 4, "3 crystals + 1 host-ERC row"

    code = t063._triage(
        out, "--key", HOST_ERC_KEY, "--verdict", "有害", "--reason", "看起来挺严重"
    )
    err = capsys.readouterr().err
    assert code == 2, "a judgement that cannot be made is not recorded"
    assert "没有逐条文本" in err and "needs-manual" in err and HOST_ERC_KEY in err

    # Nothing was written, on either side of the command.
    assert not (out / "warning-triage.json").exists()
    after = t063._read(out)
    assert t063._verdicts(after) == ["", "", "", ""]
    assert after["completion"]["warningsPendingTriage"] == 4
    assert after["completion"]["warningsNeedsManual"] == 0


def test_the_command_refuses_a_host_erc_slot_whose_text_field_was_deleted(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B follow-up, the command door: deleting the field is not a way out.

    The reviewer measured this hole on the predicate; this pins it end to end from
    a **real** report — the host-ERC slot's `text` (and the `textUnavailable`
    sentence that explains it) removed by hand, then the three-word verdict asked
    for. It must still be refused, and the report must come back byte-identical.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    t063._checkup(board, out)
    capsys.readouterr()
    report_path = out / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for slot in report["warning_triage"]:
        if slot["key"] == HOST_ERC_KEY:
            slot.pop("text")
            slot.pop("textUnavailable")
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    trimmed = report_path.read_bytes()

    assert t063._triage(
        out, "--key", HOST_ERC_KEY, "--verdict", "有害", "--reason", "删了 text 想关掉"
    ) == 2
    err = capsys.readouterr().err
    assert "没有逐条文本" in err and "needs-manual" in err and HOST_ERC_KEY in err
    assert report_path.read_bytes() == trimmed, "a refusal writes nothing — not even a re-gate"
    assert not (out / "warning-triage.json").exists()


def test_needs_manual_is_written_and_the_row_is_still_pending(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B §3: written twice, still a debt, and listed for a human."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    t063._checkup(board, out)
    capsys.readouterr()
    reason = "主机 ERC 只给合计，逐条文本在编辑器底部面板——要人工去看"

    assert t063._triage(
        out, "--key", HOST_ERC_KEY, "--verdict", "needs-manual", "--reason", reason
    ) == 0
    printed = capsys.readouterr().out
    report = t063._read(out)

    slot = next(slot for slot in report["warning_triage"] if slot["key"] == HOST_ERC_KEY)
    assert (slot["verdict"], slot["reason"]) == ("needs-manual", reason)
    completion = report["completion"]
    assert completion["warningsPendingTriage"] == 4, "needs-manual is not a closed row"
    assert completion["warningsNeedsManual"] == 1
    assert _manual_rows(report) == [
        {"key": HOST_ERC_KEY, "source": "host-erc", "count": HOST_ERC_COUNT, "reason": reason}
    ], "the list says which row, how many warnings and why a human has to look"
    why = "；".join(completion["verdictWhy"])
    assert "4 条 warning 待分诊" in why
    assert "needs-manual" in why, "the clause has to say *why* the row is still open"

    # The console names the same two numbers, and the sidecar keeps the row.
    assert "待分诊 4" in printed and "needs-manual 1" in printed
    assert "已分诊 0/4" in printed
    entry = t063._sidecar(out)["entries"][0]
    assert (entry["key"], entry["verdict"], entry["reason"]) == (
        HOST_ERC_KEY, "needs-manual", reason
    )
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "待分诊 warning 4" in markdown
    assert "needs-manual" in markdown and reason in markdown


def test_needs_manual_is_accepted_on_a_slot_that_has_text_too(
    capsys, tmp_path, monkeypatch
):
    """The word is not a textless-only label: it is 「我判不了，得有人看」 anywhere.

    Pinned so the gate does not over-reach — `needs-manual` must never be refused,
    only *required* where the text is missing.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    t063._clean_board(monkeypatch)
    board, out = _board(tmp_path), tmp_path / "out"
    key = t063._keys(t063._checkup(board, out))[0]
    capsys.readouterr()

    assert t063._triage(
        out, "--key", key, "--verdict", "needs-manual",
        "--reason", "规则说没有负载电容，但这颗晶振在隔壁页，需要人看",
    ) == 0
    report = t063._read(out)
    completion = report["completion"]
    assert completion["warningsPendingTriage"] == 3, "still pending, still incomplete"
    assert completion["warningsNeedsManual"] == 1
    assert [row["key"] for row in _manual_rows(report)] == [key]


def test_needs_manual_still_needs_a_reason(capsys, tmp_path, monkeypatch, host_erc):
    """537B §2: 「必须有 reason」 holds for the new word too (`--reason` is required)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    t063._checkup(board, out)
    capsys.readouterr()

    with pytest.raises(SystemExit) as caught:
        t063._triage(out, "--key", HOST_ERC_KEY, "--verdict", "needs-manual")
    assert caught.value.code == 2
    assert "--reason" in capsys.readouterr().err
    assert t063._triage(
        out, "--key", HOST_ERC_KEY, "--verdict", "needs-manual", "--reason", "   "
    ) == 2
    assert "--reason" in capsys.readouterr().err
    assert not (out / "warning-triage.json").exists()
    assert t063._verdicts(t063._read(out)) == ["", "", "", ""]


# --------------------------------------------------------------------------
# ④ the sidecar door: a hand edit is refused, and checkup says so
# --------------------------------------------------------------------------


def test_a_hand_edited_sidecar_cannot_close_a_textless_slot(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B §4: the second door — measured, so the gate holds on both."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    t063._checkup(board, out)
    capsys.readouterr()
    sidecar = out / "warning-triage.json"
    entries = [
        {"key": HOST_ERC_KEY, "verdict": "有害", "reason": "手改侧车绕闸",
         "source": "host-erc", "text": ""},
    ]
    sidecar.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False), encoding="utf-8"
    )

    report = t063._checkup(board, out)
    printed = capsys.readouterr().out
    notes = _notes(report)

    assert t063._verdicts(report) == ["", "", "", ""], "not one row was folded in"
    assert report["completion"]["warningsPendingTriage"] == 4
    assert report["completion"]["warningsNeedsManual"] == 0
    assert "拒收" in notes and "1 条" in notes and "needs-manual" in notes
    assert "没有对应槽位" not in notes, "the key exists — this is a refusal, not a miss"
    assert "已并入 1 条" not in printed
    # checkup never writes that file: the audit trail keeps what was hand-written.
    assert json.loads(sidecar.read_text(encoding="utf-8"))["entries"] == entries


def test_needs_manual_survives_a_rerun_through_the_sidecar(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B §5: written, re-generated, folded back — and still pending.

    The row is not a leftover of this test: the fixture makes `checkup` generate
    it again with the same key on every run, which is exactly the life cycle a
    real host-ERC row has (063 §2's merge), so 「还在」 says something about the
    code and not about the test's own bookkeeping.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    t063._checkup(board, out)
    capsys.readouterr()
    reason = "合计 7 条警告没有逐条文本，需要人工在面板上看"
    assert t063._triage(
        out, "--key", HOST_ERC_KEY, "--verdict", "needs-manual", "--reason", reason
    ) == 0
    capsys.readouterr()

    after = t063._checkup(board, out)
    printed = capsys.readouterr().out
    slot = next(slot for slot in after["warning_triage"] if slot["key"] == HOST_ERC_KEY)
    assert (slot["verdict"], slot["reason"]) == ("needs-manual", reason), "判决还在"
    assert after["completion"]["warningsPendingTriage"] == 4, "仍 pending"
    assert after["completion"]["warningsNeedsManual"] == 1
    assert _manual_rows(after) == [
        {"key": HOST_ERC_KEY, "source": "host-erc", "count": HOST_ERC_COUNT, "reason": reason}
    ]
    assert "已并入 1 条" in printed


# --------------------------------------------------------------------------
# ⑤ one arithmetic: console, report.md, verdictWhy
# --------------------------------------------------------------------------


def test_the_console_the_markdown_and_the_gate_count_the_same(
    capsys, tmp_path, monkeypatch, host_erc
):
    """537B §3: three renderings of one number — and needs-manual keeps it above 0."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    # Same isolation `test_063` §④ uses: lift the datasheet trigger so the triage
    # backlog is the only thing the verdict can be reading.
    t063._clean_board(monkeypatch)
    board, out = _board(tmp_path), tmp_path / "out"
    before = t063._checkup(board, out)
    capsys.readouterr()
    assert before["completion"]["verdict"] == "complete-with-open-items"
    text_keys = [key for key in t063._keys(before) if key != HOST_ERC_KEY]
    assert len(text_keys) == 3
    for key, reason in zip(text_keys, ["隔壁页有", "真没有", "测试焊盘"]):
        assert t063._triage(
            out, "--key", key, "--verdict", "无害", "--reason", reason
        ) == 0
    manual_reason = "主机 ERC 无逐条文本，留人工复核"
    assert t063._triage(
        out, "--key", HOST_ERC_KEY, "--verdict", "needs-manual", "--reason", manual_reason
    ) == 0
    capsys.readouterr()

    final = t063._checkup(board, out)
    printed = capsys.readouterr().out
    completion = final["completion"]
    markdown = (out / "report.md").read_text(encoding="utf-8")

    assert completion["warningsPendingTriage"] == 1, "the needs-manual row is the one left"
    assert completion["warningsNeedsManual"] == 1
    assert completion["verdict"] == "complete-with-open-items", "not `complete`: a human is owed"
    assert "1 条 warning 待分诊" in "；".join(completion["verdictWhy"])
    assert "needs-manual" in "；".join(completion["verdictWhy"])
    assert "待分诊 1，其中 needs-manual 1" in printed
    assert "待分诊 warning 1" in markdown
    assert "needs-manual" in markdown and manual_reason in markdown
    # The list a reader acts on is the report's own, rendered from that same list.
    assert f"| {HOST_ERC_KEY} | host-erc | {HOST_ERC_COUNT} | {manual_reason} |" in markdown


# --------------------------------------------------------------------------
# ⑥ the read side: what counts as judged, and what never does
# --------------------------------------------------------------------------


def test_a_verdict_outside_the_vocabulary_is_never_read_as_triaged():
    """537B §3: a hand-edited report cannot smuggle in a fourth answer."""
    triage = [
        {"key": "k-unknown", "source": "boardwise-rule", "severity": "WARN", "count": 1,
         "text": "有文本", "verdict": "大概没事", "reason": "手改的"},
        {"key": "k-three", "source": "boardwise-rule", "severity": "WARN", "count": 1,
         "text": "有文本", "verdict": "无害", "reason": "有负载电容"},
        {"key": "k-manual", "source": "host-erc", "severity": "warn", "count": 3,
         "text": "", "verdict": "needs-manual", "reason": "无逐条文本"},
    ]
    completion = cli._completion_body(
        scope={}, summary={"errorCount": 0}, unreviewed=[], triage=triage,
        architecture={"totals": {"slots": 0, "filled": 0, "stale": 0}},
    )
    assert completion["warningsPendingTriage"] == 2, "the unknown word is not a judgement"
    assert completion["warningsNeedsManual"] == 1
    assert [row["key"] for row in completion["manualReviewRequired"]] == ["k-manual"]


def test_the_three_words_on_a_slot_with_text_behave_exactly_as_before(
    capsys, tmp_path, monkeypatch
):
    """537B §5: legacy behaviour of 063/070 is untouched — additive keys only."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    t063._clean_board(monkeypatch)
    board, out = _board(tmp_path), tmp_path / "out"
    before = t063._checkup(board, out)
    capsys.readouterr()
    assert before["completion"]["warningsPendingTriage"] == 3
    assert before["completion"]["warningsNeedsManual"] == 0
    assert _manual_rows(before) == []
    key = t063._keys(before)[0]

    assert t063._triage(out, "--key", key, "--verdict", "无害", "--reason", "测试网络") == 0
    after = t063._read(out)
    assert after["completion"]["warningsPendingTriage"] == 2
    assert after["completion"]["warningsNeedsManual"] == 0
    assert _manual_rows(after) == []
    why = "；".join(after["completion"]["verdictWhy"])
    assert "2 条 warning 待分诊" in why
    assert "needs-manual" not in why, "a board with no text-less row gains no new clause"
    assert _reasons(after)[0] == "测试网络"
