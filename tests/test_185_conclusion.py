"""Tests for task 185: one authoritative `conclusion`, the datasheet trio, INSTANCE_STALE.

岳 2026-10-15 的 AI 使用者体验反馈三块，本文件逐块钉：

* **A — `report.json` 顶层的 `conclusion` 节**：五字段全是**既有数据的读**，
  `oneLiner` 必须与 `board-report.md` 的结论句**逐字同一份**（同一个生成函数
  `board_report_verdict`），`blockers` 必须逐字等于 `completion.verdictWhy`，
  `verdict`/`exitCode`/`mayClaimPassed` 三个分别是 `completion.verdict` /
  `summary.exitCode` / `summary.mayClaimPassed` 的读。三态（incomplete /
  complete-with-open-items / complete）各钉一遍，外加真夹具上端到端一遍——
  「同一个数」不许靠两次独立推导碰巧相等，必须是同一个调用。
* **B — `completion` 的三键计数**：`reviewerMarked`（现 `needsDatasheet` 窄义的正主）
  ≤ `needsDatasheetTotal`（`len(needs_datasheet[])`），且旧键 `== reviewerMarked`
  （保留原义、标注 deprecated），生成处那行注释也在场。
* **C — `INSTANCE_STALE`**：`--instance` 指向不在线的窗口时，错误码是新码（不再是
  `WINDOW_NOT_CONNECTED`，那个码留在词表里但 daemon 不再抛），且消息列出在线窗口的
  windowKey / 工程 / 页——就是 `bridge status` 那一行。

夹具一律只读。A/B 不连编辑器、不碰 daemon；C 那组起的是**测试用** daemon
（OS 随机端口 + `test_bridge` 的假 connector），既不连编辑器也不碰 61190 的真 daemon。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.checkup import (
    CONCLUSION_KEYS,
    board_report_verdict,
    conclusion_section,
    render_board_report,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]
SHELF = REPO / "blocklib" / "parts.json"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"

#: The heading `render_board_report` prints the conclusion under. The conclusion
#: *sentence* is the text after it; nothing above it in the file is a sentence.
VERDICT_HEADING = "### 整工程能不能投板："

#: The three words a conclusion sentence can start with (the report's own two
#: states plus the narrow fallback). Used to assert the line we extract really is
#: the file's first conclusion and not a stray match further down.
VERDICT_OPENERS = ("可以投板", "不能投板", "不能写「通过」")


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


def _verdict_sentence(markdown: str) -> str:
    """The conclusion sentence out of a ``board-report.md`` rendering.

    The report file opens with a heading and a note paragraph, so the conclusion
    is the text after :data:`VERDICT_HEADING`; this helper also asserts nothing
    *earlier* in the file already stated a conclusion, which is what makes
    "the first sentence" a checkable claim rather than a convention.
    """
    lines = markdown.splitlines()
    index = next(
        (i for i, line in enumerate(lines) if line.startswith(VERDICT_HEADING)), None
    )
    assert index is not None, f"no {VERDICT_HEADING!r} line in the board report"
    for earlier in lines[:index]:
        assert not any(opener in earlier for opener in VERDICT_OPENERS), (
            f"a conclusion sentence appears before the verdict heading: {earlier!r}"
        )
    return lines[index][len(VERDICT_HEADING):]


def _report(*, verdict: str, why: list[str], error_count: int = 0,
            error_entries: list[dict] | None = None,
            exit_code: int = 0, may_claim: bool = False,
            marked: int = 0, total: int = 0) -> dict:
    """A report shaped like the ones `checkup` writes, in the state asked for."""
    return {
        "summary": {
            "errorCount": error_count,
            "errors": list(error_entries or []),
            "exitCode": exit_code,
            "mayClaimPassed": may_claim,
        },
        "completion": {
            "verdict": verdict,
            "verdictWhy": list(why),
            "needsDatasheet": marked,
            "reviewerMarked": marked,
            "needsDatasheetTotal": total,
        },
    }


#: The three states, as the report's own gate names them. The `complete` state is
#: synthetic on purpose: no shipped fixture is clean (FOC carries 50 ERROR, ROBOT
#: 38 unreviewed parts), and the state that may claim a pass is exactly the one
#: that has to be exercised.
STATES = {
    "incomplete": _report(
        verdict="incomplete", why=["2 项 ERROR"], error_count=2, exit_code=1,
    ),
    "complete-with-open-items": _report(
        verdict="complete-with-open-items",
        why=["38 颗器件缺手册未审", "6 条 warning 待分诊"],
        marked=38, total=38,
    ),
    "complete": _report(verdict="complete", why=[], may_claim=True),
}


# ---------------------------------------------------------------------------
# A: the conclusion section is a read of the five exits, never a sixth opinion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", sorted(STATES))
def test_the_conclusion_reads_the_five_exits_in_every_state(state):
    """The section's five fields are the five older readings, value for value.

    The failure this pins: a second verdict arithmetic living in `conclusion`.
    Every assertion below compares against the section that already owned the
    value, so a `conclusion` that recomputed anything would have to agree with
    four other places to pass — which is the drift 185 A exists to remove.
    """
    report = STATES[state]
    section = conclusion_section(report)
    summary, completion = report["summary"], report["completion"]

    assert tuple(section) == CONCLUSION_KEYS, (
        "the section's key set is the task book's five, in order, and nothing else"
    )
    assert section["verdict"] == completion["verdict"]
    assert section["exitCode"] == summary["exitCode"]
    assert section["mayClaimPassed"] == summary["mayClaimPassed"]
    assert section["blockers"] == completion["verdictWhy"]
    assert section["oneLiner"] == board_report_verdict(report)["line"]


@pytest.mark.parametrize("state", sorted(STATES))
def test_the_one_liner_is_verbatim_the_board_reports_first_sentence(state):
    """`oneLiner` and the closing line of `board-report.md` are one string.

    Both sides are read out of the *rendering a person gets*, not out of a
    docstring: the sentence is parsed back out of the Markdown the report file
    carries, so a conclusion that built its own sentence (even an equal-looking
    one) fails the moment either side moves.
    """
    report = STATES[state]
    section = conclusion_section(report)
    sentence = _verdict_sentence(render_board_report(report))
    assert section["oneLiner"] == sentence
    assert sentence.startswith(VERDICT_OPENERS), (
        f"{state}: the closing line reads like a sentence: {sentence!r}"
    )
    # `complete` is the only state that may be quoted as a pass.
    assert (state == "complete") is section["oneLiner"].startswith("可以投板")


def test_the_writer_stores_the_conclusion_with_the_same_single_call(tmp_path):
    """`_write_checkup_report` derives both sections from **one** verdict call.

    This is the structural half of A's "同一生成点": the conclusion is handed the
    section's own verdict dict, so the two sections in `report.json` cannot be two
    derivations of the same report that happen to agree today.
    """
    from boardwise.cli import _write_checkup_report

    report = dict(STATES["complete-with-open-items"])
    report["board_report"] = {"stale": True}
    report["conclusion"] = {"stale": True}
    _write_checkup_report(tmp_path, report)
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert "stale" not in written["board_report"]
    assert "stale" not in written["conclusion"]
    assert written["conclusion"]["oneLiner"] == written["board_report"]["verdict"]["line"]
    assert written["conclusion"]["blockers"] == written["completion"]["verdictWhy"]


def test_a_report_without_a_completion_section_falls_back_to_the_narrow_reading():
    """A hand-built dict / pre-053 report still gets an honest section.

    There is no `verdictWhy` to quote there, so `blockers` is the narrow reasons
    `board_report_verdict` derived — one function's own list, still read and not
    re-derived, and `verdict` says the empty string rather than inventing a state.
    """
    report = {"summary": {"errorCount": 1, "exitCode": 1, "mayClaimPassed": False}}
    section = conclusion_section(report)
    verdict = board_report_verdict(report)
    assert section["verdict"] == ""
    assert section["blockers"] == verdict["blockers"]
    assert section["blockers"][0] == "1 项 ERROR"
    assert section["oneLiner"] == verdict["line"]
    assert section["exitCode"] == 1 and section["mayClaimPassed"] is False


def test_the_section_exists_end_to_end_and_says_what_the_file_says(
    tmp_path, monkeypatch
):
    """Real fixtures, real files: `report.json`'s `conclusion` == `board-report.md`.

    Two states on two shipped boards — FOC 1.1.0 (50 ERROR: `incomplete`, exit 1)
    and ROBOT ctrl FOC (no ERROR, but parts no rule could judge: also
    `incomplete`, exit 3). Both are refusals, which is the point: neither board may
    be quoted as a pass, and the two sentences differ because their blockers do.
    The `board-report.md` sentence is read off disk, the form the engineer and the
    AI both receive.
    """
    seen: dict[str, str] = {}
    for fixture, name, exit_code in (
        (FOC_110, "foc110", 1),
        (ROBOT, "robot", 3),
    ):
        report = _run_checkup(tmp_path, monkeypatch, fixture, name)
        conclusion = report["conclusion"]
        board_md = (tmp_path / name / "board-report.md").read_text(encoding="utf-8")
        assert conclusion["verdict"] == report["completion"]["verdict"] == "incomplete"
        assert conclusion["exitCode"] == report["summary"]["exitCode"] == exit_code
        assert conclusion["mayClaimPassed"] == report["summary"]["mayClaimPassed"] is False
        assert conclusion["blockers"] == report["completion"]["verdictWhy"]
        assert conclusion["oneLiner"] == _verdict_sentence(board_md), (
            f"{name}: report.json 的 conclusion.oneLiner 与 board-report.md 的结论句不同源"
        )
        # The file's own first sentence is the same string the JSON carries.
        assert board_md.index(conclusion["oneLiner"]) > board_md.index(VERDICT_HEADING)
        seen[name] = conclusion["oneLiner"]
    # ERROR臂和缺手册臂说的是两句不同的话（各自的 blockers 不同），所以上面两条
    # 「逐字一致」不是在断言一个常数句子。
    assert seen["foc110"] != seen["robot"]
    assert "ERROR" in seen["foc110"]
    assert "缺手册" in seen["robot"] and "待分诊" in seen["robot"]


# ---------------------------------------------------------------------------
# B: needsDatasheet 拆名 —— 三键都是同一张清单的三个读数
# ---------------------------------------------------------------------------


def _seed(designator: str) -> dict:
    return {
        "designator": designator,
        "mpn": "", "manufacturer": "", "value": "",
        "channels": ["本地库", "立创商城"], "missingFacts": ["mpn"],
        "reason": "规则判不了", "findings": [],
    }


def _marks() -> list[dict]:
    """The report's `needs_datasheet[]` for a two-part worklist, one hand-marked."""
    from boardwise.engines.checkup import needs_datasheet_section, marked_parts

    section = needs_datasheet_section(
        [_seed("U1"), _seed("U2")],
        [{"part": "U1", "pin": "FB", "reason": "脚位不明"}],
    )
    assert marked_parts(section) == ["U1"]
    return section


def test_the_three_datasheet_keys_are_self_consistent():
    """`reviewerMarked` ≤ `needsDatasheetTotal`, and the old key equals the new one.

    `needsDatasheet` used to answer two questions at once (how many the reviewer
    marked / how big the worklist is); it keeps its narrow meaning, so the pair
    must not collide: on a worklist whose rows are mostly facts-triggered, the
    marked count is strictly smaller than the list.
    """
    from boardwise.cli import _completion_section
    from boardwise.core.model import DesignModel
    from boardwise.engines.checkup import marked_parts

    marks = _marks()
    section = _completion_section(
        model=DesignModel(),
        summary={"errorCount": 0},
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 0}},
        needs_datasheet=marks,
    )
    assert section["reviewerMarked"] == section["needsDatasheet"] == len(marked_parts(marks))
    assert section["needsDatasheetTotal"] == len(marks)
    assert section["reviewerMarked"] <= section["needsDatasheetTotal"]
    # Two rows, one of them hand-marked: the two numbers differ, which is the
    # whole reason the section needed a second name.
    assert (section["reviewerMarked"], section["needsDatasheetTotal"]) == (1, 2)


def test_the_deprecated_key_is_kept_and_labelled_at_its_generation_site():
    """`needsDatasheet` is not renamed — the report key keeps its reader.

    185 B's rule is 「只加不改」: a report key that changes name breaks every reader
    written against it, so the old name stays with its narrow meaning and the
    generation site says where to read instead. Both halves are asserted from the
    source, because that comment *is* the contract for the next reader.
    """
    source = (REPO / "src" / "boardwise" / "cli.py").read_text(encoding="utf-8")
    assert re.search(r"deprecated\s*→\s*reviewerMarked", source), (
        "cli.py 的生成处不再标 `deprecated → reviewerMarked`：旧键的去向又只能靠猜"
    )
    body = source[source.index("def _completion_body("):source.index("def _completion_section(")]
    assert '"reviewerMarked": marked_count' in body
    assert '"needsDatasheet": marked_count' in body
    assert '"needsDatasheetTotal": len(needs_datasheet or [])' in body


def test_a_real_report_carries_all_three_keys(tmp_path, monkeypatch):
    """End to end: the trio is in `report.json` and reads the section's own list."""
    report = _run_checkup(tmp_path, monkeypatch, ROBOT, "robot")
    completion = report["completion"]
    for key in ("needsDatasheet", "reviewerMarked", "needsDatasheetTotal"):
        assert key in completion, key
    assert completion["needsDatasheet"] == completion["reviewerMarked"]
    assert completion["needsDatasheetTotal"] == len(report["needs_datasheet"])
    assert completion["reviewerMarked"] <= completion["needsDatasheetTotal"]
    # ROBOT has parts no rule could judge and nobody marked by hand: the total is
    # the facts seed, and the marked count is zero — the pair the old single key
    # could not tell apart.
    assert completion["reviewerMarked"] == 0
    assert completion["needsDatasheetTotal"] > 0
    # The total is the worklist's length, and the worklist folds a part's rows
    # together — so it is `<=` the unreviewed rows, never assumed equal (a
    # designator on two boards has a row in `unreviewed_parts[]` for each board).
    assert completion["needsDatasheetTotal"] <= len(report["unreviewed_parts"])


def test_the_regate_path_refreshes_the_conclusion_and_the_report_file(
    tmp_path, monkeypatch
):
    """`boardwise need-datasheet` rebuilds `completion` — the section must follow.

    The one place a report is **re-gated** after it was written: the mark adds a
    question, `completion` is rebuilt from the report's own sections, and both
    ledgers plus `board-report.md` are re-written (058 §三 / 154). `conclusion`
    travels with them because it is written where every report is written
    (:func:`boardwise.cli._write_checkup_report`), which is the sync the task book
    called out — without it the JSON would carry a verdict the sentence beside it
    had already left behind.

    A designator the worklist does **not** already carry is marked, so the retotal
    is visible as `+1` rather than folded into an existing row.
    """
    report = _run_checkup(tmp_path, monkeypatch, ROBOT, "robot")
    before = report["conclusion"]
    total_before = report["completion"]["needsDatasheetTotal"]
    on_the_list = {str(row["part"]) for row in report["needs_datasheet"]}
    fresh = next(
        d for d in report["model"]["designators"] if d not in on_the_list
    )
    out = tmp_path / "robot"

    assert cli.main([
        "need-datasheet", "--out", str(out), "--part", fresh,
        "--reason", "图上读不出这颗器件在位功能",
    ]) == 0

    after = json.loads((out / "report.json").read_text(encoding="utf-8"))
    conclusion = after["conclusion"]
    assert conclusion["oneLiner"] != before["oneLiner"], (
        "标记没进结论句：报告被重判了而 conclusion 还是旧的"
    )
    assert conclusion["verdict"] == after["completion"]["verdict"]
    assert conclusion["exitCode"] == after["summary"]["exitCode"]
    assert conclusion["mayClaimPassed"] == after["summary"]["mayClaimPassed"]
    assert conclusion["blockers"] == after["completion"]["verdictWhy"]
    assert conclusion["oneLiner"] == _verdict_sentence(
        (out / "board-report.md").read_text(encoding="utf-8")
    ), "重判后 report.json 的结论句与磁盘上的 board-report.md 不同源"
    # The trio moved with the mark, in the direction the mark implies.
    assert after["completion"]["reviewerMarked"] == 1
    assert after["completion"]["needsDatasheetTotal"] == total_before + 1
    assert after["completion"]["needsDatasheet"] == 1


# ---------------------------------------------------------------------------
# C: INSTANCE_STALE
# ---------------------------------------------------------------------------


def test_instance_stale_is_in_the_vocabulary_and_the_old_code_is_retired():
    """Both codes exist; the daemon raises only the new one.

    `WINDOW_NOT_CONNECTED` stays in the vocabulary because connector and CLI
    builds in the field switch on the string (the same reason
    `CONNECTOR_ALREADY_ACTIVE` stays). What changed is who raises what, and that
    is a fact about `bridge/daemon.py`, so it is read from the source.
    """
    from boardwise.bridge.protocol import ErrorCodes

    assert ErrorCodes.INSTANCE_STALE == "INSTANCE_STALE"
    assert ErrorCodes.WINDOW_NOT_CONNECTED == "WINDOW_NOT_CONNECTED"
    daemon = (REPO / "src" / "boardwise" / "bridge" / "daemon.py").read_text(
        encoding="utf-8"
    )
    assert "ErrorCodes.INSTANCE_STALE" in daemon
    assert "ErrorCodes.WINDOW_NOT_CONNECTED" not in daemon, (
        "daemon 又抛回 WINDOW_NOT_CONNECTED 了：185 §C 把实例未命中统一到 INSTANCE_STALE"
    )


def test_a_stale_instance_is_refused_by_name_with_the_online_windows(tmp_path):
    """The refusal itself: code, the stale sentence, and the listing.

    Driven through the real daemon over a real WebSocket (the fake connector from
    `test_bridge`), because the refusal is decided in a routing method and a unit
    test of that method would not prove the frame carries it.

    The listing is the row `bridge status` prints — hub key, project and page —
    because the caller's next move is to copy one out of it. The page is reachable
    only from a **response** context (the handshake happens before any action has
    run), which is why the scenario routes one real call first: that is also how a
    live daemon learns it, so the test does not hand the hub a value it could not
    have had.
    """
    import asyncio

    from test_bridge import FakeConnector, WINDOW_A, WINDOW_B, _daemon, _hello, _start, run
    from boardwise.bridge.protocol import ErrorCodes, decode_frame, request_frame

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(
                port, "connector", token="t", instanceId=WINDOW_A,
                projectName="/test", projectUuid="uuid-test",
            )
            b_ws, _ = await _hello(
                port, "connector", token="t", instanceId=WINDOW_B,
                projectName="test2", projectUuid="uuid-test2",
            )
            fake_a = FakeConnector(
                a_ws,
                responses={"doc.list": {"window": "A"}},
                contexts={"doc.list": {"pageUuid": "page-a", "pageType": "sch"}},
            )
            a_task = asyncio.create_task(fake_a.serve())
            cli_ws, _ = await _hello(port, "cli")
            # Teach the hub window A's page (a routed call whose response carries
            # the context), then ask for a window that is not there.
            await cli_ws.send(
                request_frame("doc.list", {}, id="learn", target_instance=WINDOW_A))
            assert decode_frame(await cli_ws.recv())["ok"] is True
            assert daemon.window_for_instance(WINDOW_A).page_uuid == "page-a"

            await cli_ws.send(
                request_frame("doc.list", {}, id="x", target_instance="inst-gone"))
            reply = decode_frame(await cli_ws.recv())
            a_task.cancel()
            for ws in (cli_ws, a_ws, b_ws):
                await ws.close()
            return reply

    reply = run(scenario())
    assert reply["ok"] is False
    assert reply["error"]["code"] == ErrorCodes.INSTANCE_STALE
    message = reply["error"]["message"]
    assert "inst-gone" in message
    assert "实例可能已失效" in message and "重连" in message, (
        "消息必须说「实例可能已失效、页面重连后 id 会变」——否则调用方会读成"
        "「调用成功但没数据」（反馈 P5）"
    )
    # Every online window, as `bridge status` prints it: key, project, page.
    assert f"/test ({WINDOW_A})" in message and "页 sch page-a" in message
    assert f"test2 ({WINDOW_B})" in message
    # The machine-readable copy travels in `detail`, so a script does not parse prose.
    candidates = reply["error"]["detail"]["candidates"]
    assert [row["windowKey"] for row in candidates] == [WINDOW_A, WINDOW_B]
    assert [row["projectName"] for row in candidates] == ["/test", "test2"]
    assert candidates[0]["pageUuid"] == "page-a"
    assert "context" not in reply, "no window was chosen, so none is named"
