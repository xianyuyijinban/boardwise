"""537D2a1: the content validator for one finalized ``review-summary.md``.

Why this file exists. `boardwise checkup` writes `review-summary.md` as a
skeleton and the model fills it. Nothing checked the result, so a delivery could
keep the skeleton comments, quote `summary.conclusion` instead of
`conclusion.oneLiner`, drop an evidence disclosure, or claim a pass the report
does not support — and still read as a finished review.

The validator is a pure function: it takes the already-written `report.json`
dict and the filled text, and returns `{code, path, message}` rows. `[]` means
**the text agrees with the report**, not that the board passed: a review with
pending warnings, a `needs-manual` row and a `partial` delivery is consistent
and must validate clean.

Everything here is anonymous and synthetic — no editor, no daemon, no real
project, no file read by the validator. Wherever it can be, the fixture is
built by the repository's **own** renderer (`render_review_summary`,
`environment_section`, `evidence_coverage` / `evidence_delivery`,
`conclusion_section`), so the acceptance case is a real skeleton that was really
filled, not a hand-written imitation of one.
"""

from __future__ import annotations

import ast
import copy
import inspect
import re

import pytest

from boardwise.engines import checkup
from boardwise.engines.checkup import (
    CHAINS_KEY,
    ENVIRONMENT_HEADING,
    REVIEW_SUMMARY_BLANK_ADVICE,
    REVIEW_SUMMARY_BLANK_ANALYSIS,
    chain_text,
    render_environment_markdown,
    render_review_summary,
)
from boardwise.engines.evidence import (
    EVIDENCE_HEADING,
    evidence_coverage,
    evidence_delivery,
    render_evidence_markdown,
)
from boardwise.engines import reviewfinalize
from boardwise.engines.reviewfinalize import (
    split_markdown_row,
    synchronize_review_summary_sections,
    validate_review_summary,
)

#: The three skeleton comments the finalize step replaces. Matched by prefix —
#: the rest of each comment is wording, exactly like the validator does.
SKELETON_1_RE = re.compile(r"<!-- AI 在这里写[^>]*-->")
SKELETON_3_RE = re.compile(r"<!-- needs_datasheet 非空时[^>]*-->")
SKELETON_4_RE = re.compile(r"<!-- 1\. / 2\. / 3\.[^>]*-->")

CONNECTION = (
    "已连接 `test` 工程（window-A）；本次审查的数据来自归档文件，焦点工程身份已核对。"
)

ANALYSIS = "去耦电容离 U1 的电源脚过远，回流路径被拉长；根因是布局而不是网表。"

ADVICE = "把 C1 移到 U1 的 VCC 脚 3 mm 内，地过孔就近打；改完重跑 checkup。"

NEXT_STEPS = (
    "1. 补一次实时 PCB 回读，把 `livePcb` 缺口关掉。\n"
    "2. 把 `C2`、`U3` 的手册放进货架。\n"
    "3. 复核那条 needs-manual warning。"
)


def _finding(index: int, severity: str, rule_id: str, message: str) -> dict:
    return {
        "index": index,
        "severity": severity,
        "rule_id": rule_id,
        "message": message,
        "refs": ["U1"],
        "target": {"component_ref": "U1"},
    }


def _chain(index: int, severity: str, rule_id: str, problem: str, refs: str) -> dict:
    return {
        "index": index,
        "severity": severity,
        "rule_id": rule_id,
        "project": "合成工程A",
        "board": "Board1",
        "page": "电源",
        "refs": refs,
        "problem": problem,
        "missing": [],
    }


def _triage() -> list[dict]:
    return [
        {"key": "w1", "source": "host-erc", "text": "VCC 有两个电源输出", "count": 1,
         "verdict": "有益"},
        {"key": "w2", "source": "host-erc", "text": "GND 与 PGND 同名", "count": 1,
         "verdict": "无害"},
        {"key": "w3", "source": "host-erc", "text": "", "count": 2,
         "verdict": "needs-manual"},
    ]


def _channels(status_override: dict | None = None) -> dict:
    channels = {
        "liveSchematic": {
            "status": "ok", "source": "live-sch", "detail": "实时原理图 12 器件",
            "artifacts": [], "errors": [], "steps": [],
        },
        "archivePcb": {
            "status": "not-applicable", "source": "archive", "detail": "归档里没有 PCB 文档",
            "artifacts": [], "errors": [], "steps": [],
        },
        "livePcb": {
            "status": "missing", "source": "live-pcb", "detail": "未完成实时 PCB 回读",
            "artifacts": [], "errors": [], "steps": [],
        },
        "schematicImage": {
            "status": "ok", "source": "image", "detail": "画布 2 页",
            "artifacts": [], "errors": [], "steps": [],
        },
        "pcbImage": {
            "status": "missing", "source": "image", "detail": "未完成 PCB 视觉复核",
            "artifacts": [], "errors": [], "steps": [],
        },
        "datasheets": {
            "status": "unavailable", "source": "datasheet",
            "detail": "2 颗缺已核验手册事实", "artifacts": [], "errors": [], "steps": [],
        },
    }
    for name, status in (status_override or {}).items():
        channels[name] = dict(channels[name], status=status)
    return channels


def _live_capture(*, focus_ok: bool = True, identity_verified: bool = True) -> dict:
    return {
        "schema": "boardwise.live-evidence/1",
        "ok": True,
        "executor": "test",
        "identity": {
            "verifiedAgainstReport": identity_verified,
            "expectedProjectUuid": "uuid-synthetic-1",
            "projectUuid": "uuid-synthetic-1",
        },
        "focusRestore": {
            "ok": focus_ok,
            "attempted": True,
            "status": "restored" if focus_ok else "failed",
            "error": None if focus_ok else {"code": "focus-failed", "message": "焦点没有复位"},
        },
        "artifacts": [],
        "steps": [],
    }


def _report(
    *,
    zero_findings: bool = False,
    pipe_in_chain: bool = False,
    suspected: bool = False,
    focus_ok: bool = True,
    identity_verified: bool = True,
    channel_status: dict | None = None,
) -> dict:
    """A synthetic report whose every section comes from its owning engine."""
    if zero_findings:
        findings: list[dict] = []
        chains: list[dict] = []
    else:
        findings = [
            _finding(0, "ERROR", "decap-required-caps", "去耦电容缺失或过远"),
            _finding(1, "WARN", "param-divider-output", "分压比与目标输出不符"),
        ]
        chains = [
            _chain(0, "ERROR", "decap-required-caps", "去耦电容缺失或过远 | 需复核",
                   "J1|J2" if pipe_in_chain else "C1、U1"),
            _chain(1, "WARN", "param-divider-output", "分压比与目标输出不符", "R1、R2"),
        ]
        chains[1]["page"] = "未标注"
        chains[1]["missing"] = ["page"]
    source = {
        "project": {"name": "合成工程A"},
        "tier": "file",
        "tierLabel": "离线文件",
        "boards": ["Board1"],
        "connectorVersion": None,
    }
    report: dict = {
        "schema": "boardwise.checkup/1",
        "source": source,
        "summary": {
            "exitCode": 0,
            "errorCount": 0,
            "warnCount": 3,
            "mayClaimPassed": False,
            "conclusion": "",
        },
        "findings": findings,
        CHAINS_KEY: chains,
        "warning_triage": _triage(),
        "completion": {
            "verdict": "complete-with-open-items",
            "verdictWhy": ["1 条 warning 待分诊/需人工复核"],
            "warningsPendingTriage": 1,
            "warningsNeedsManual": 1,
            "manualReviewRequired": [
                {"key": "w3", "source": "host-erc", "count": 2, "reason": "无逐条文本"},
            ],
            "acceptedUnknown": 0,
            "coverage": {},
        },
        "environment": checkup.environment_section(
            tier="file", source=source, expected_connector_version="0.5.0"
        ),
    }
    live_capture = _live_capture(focus_ok=focus_ok, identity_verified=identity_verified)
    channels = _channels(channel_status)
    report["evidence"] = {
        "schema": "boardwise.review-evidence/1",
        "channels": channels,
        "coverage": evidence_coverage(channels),
        "delivery": evidence_delivery(channels, live_capture),
        "liveCapture": live_capture,
    }
    if suspected:
        report["pcb_review"] = {
            "boards": [
                {"title": "Board1", "boardUuid": "board-uuid-1",
                 "crossView": {"status": "suspected", "checked": True}},
            ]
        }
    # The conclusion is the report's own section, derived from what is above —
    # never hand-written in this fixture (185: every field is a read).
    report["conclusion"] = checkup.conclusion_section(report)
    return report


def _section3(report: dict) -> str:
    """Section 3, filled with the counts the **report's own ledger** gives.

    Computed rather than hard-coded so a fixture whose triage changes still
    fills a consistent summary — the acceptance case must stay a real delivery,
    not a sentence that happens to match one.
    """
    slots = [slot if isinstance(slot, dict) else {} for slot in
             (report.get("warning_triage") or [])]
    pending = sum(1 for slot in slots if not checkup.triage_slot_is_closed(slot))
    manual = sum(1 for slot in slots if checkup.triage_slot_is_manual(slot))
    lines = [f"1. {len(slots) - pending} 条 warning 已分诊、待分诊 {pending} 条。"]
    if manual:
        lines.append(
            f"{len(lines) + 1}. 待人工复核 {manual} 条：`host-erc` 只回按 kind 的合计，"
            "逐条文本要工程师在底部面板看。"
        )
    lines.append(
        f"{len(lines) + 1}. 2 颗器件缺已核验手册事实（`C2`、`U3`）——去要 PDF，"
        "核实前不下规格结论。"
    )
    for board in (report.get("pcb_review") or {}).get("boards") or []:
        if isinstance(board, dict) and isinstance(board.get("crossView"), dict):
            if board["crossView"].get("status") == "suspected":
                lines.append(
                    f"{len(lines) + 1}. 跨视图疑似错版：`{board.get('title')}` 的 "
                    "crossView status=suspected，原理图与 PCB 的引脚映射对不上，需人工核对。"
                )
    return "\n".join(lines)


def _filled(report: dict, *, fill_analysis: bool = True, fill_advice: bool = True) -> str:
    """The real skeleton, really filled — the acceptance fixture."""
    text = render_review_summary(report, report[CHAINS_KEY])
    one_liner = report["conclusion"]["oneLiner"]
    text = text.replace("**结论：0**", f"**结论：{one_liner}**")
    assert "**结论：0**" not in text, "渲染器换了结论行的形状，填充助手需要跟着改"
    text = SKELETON_1_RE.sub(lambda _match: CONNECTION, text)
    text = SKELETON_3_RE.sub(lambda _match: _section3(report), text)
    text = SKELETON_4_RE.sub(lambda _match: NEXT_STEPS, text)
    assert "<!-- AI 在这里写" not in text
    assert "<!-- needs_datasheet 非空时" not in text
    assert "<!-- 1. / 2. / 3." not in text
    if fill_analysis:
        text = text.replace(REVIEW_SUMMARY_BLANK_ANALYSIS, ANALYSIS)
    if fill_advice:
        text = text.replace(REVIEW_SUMMARY_BLANK_ADVICE, ADVICE)
    return text


def _codes(issues: list[dict]) -> list[str]:
    return [issue["code"] for issue in issues]


def _row_lines(summary: str) -> list[int]:
    """Line indexes of section 2's data rows (header and separator skipped)."""
    lines = summary.splitlines()
    rows: list[int] = []
    inside = False
    seen = 0
    for number, text in enumerate(lines):
        if text.startswith("## 2."):
            inside = True
            seen = 0
            continue
        if inside and text.startswith("## "):
            break
        if inside and text.lstrip().startswith("|"):
            seen += 1
            if seen > 2:
                rows.append(number)
    return rows


def _edited_lines(summary: str, mutate) -> str:
    lines = summary.splitlines()
    mutate(lines)
    return "\n".join(lines) + ("\n" if summary.endswith("\n") else "")


def _expect(issues: list[dict], code: str) -> dict:
    for issue in issues:
        if issue["code"] == code:
            return issue
    pytest.fail(f"expected {code!r} in {_codes(issues)}")


# ---------------------------------------------------------------------------
# the acceptance case: pending + needsManual + partial still validates clean
# ---------------------------------------------------------------------------


def test_filled_summary_with_pending_manual_and_partial_is_clean():
    report = _report()
    summary = _filled(report)

    # The premises of this test, asserted rather than assumed: this is the shape
    # a real open review has, and it must not be reported as inconsistent.
    assert report["completion"]["warningsPendingTriage"] == 1
    assert report["completion"]["warningsNeedsManual"] == 1
    assert report["evidence"]["delivery"]["status"] == "partial"
    assert report["conclusion"]["mayQuotePassed"] is False
    assert "待分诊 1 条" in summary

    issues = validate_review_summary(report, summary)
    assert issues == [], issues


def test_zero_findings_skeleton_is_clean():
    report = _report(zero_findings=True)
    summary = _filled(report)
    assert "本次审查没有 finding" in summary
    assert validate_review_summary(report, summary) == []


def test_escaped_pipe_in_location_chain_is_one_cell():
    report = _report(pipe_in_chain=True)
    summary = _filled(report)
    # The renderer escaped the chain's own `|`, so the row still has 7 columns.
    raw = [line for line in summary.splitlines() if line.startswith("| 0 |")][0]
    assert "\\|" in raw
    cells = split_markdown_row(raw)
    assert cells is not None and len(cells) == 7
    assert cells[3].strip() == chain_text(report[CHAINS_KEY][0])
    assert "|" in cells[3]
    assert validate_review_summary(report, summary) == []


# ---------------------------------------------------------------------------
# 1. the main findings table
# ---------------------------------------------------------------------------


def test_missing_location_chains_is_reported():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    del broken[CHAINS_KEY]
    issues = validate_review_summary(broken, summary)
    _expect(issues, "location-chains-missing")


def test_location_chains_must_be_a_list():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken[CHAINS_KEY] = {"0": broken[CHAINS_KEY][0]}
    _expect(validate_review_summary(broken, summary), "location-chains-not-list")


def test_location_chains_count_mismatch():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken[CHAINS_KEY] = broken[CHAINS_KEY][:1]
    _expect(validate_review_summary(broken, summary), "location-chains-count-mismatch")


def test_table_heading_count_must_match_the_ledger():
    report = _report()
    summary = _filled(report).replace("## 2. 逐条问题（2 条）", "## 2. 逐条问题（5 条）")
    _expect(validate_review_summary(report, summary), "summary-findings-count-mismatch")


def test_unescaped_pipe_breaks_the_row_and_is_reported():
    report = _report()
    summary = _filled(report)
    assert "\\|" in summary
    broken = summary.replace("\\|", "|", 1)
    issues = validate_review_summary(report, broken)
    _expect(issues, "summary-findings-table-row-columns")


def test_deleted_row_is_reported():
    report = _report()
    summary = _filled(report)
    rows = _row_lines(summary)

    def mutate(lines: list[str]) -> None:
        del lines[rows[-1]]

    issues = validate_review_summary(report, _edited_lines(summary, mutate))
    _expect(issues, "summary-findings-table-row-missing")
    _expect(issues, "summary-findings-table-row-count")


def test_duplicated_row_is_reported():
    report = _report()
    summary = _filled(report)
    rows = _row_lines(summary)

    def mutate(lines: list[str]) -> None:
        lines.insert(rows[0] + 1, lines[rows[0]])

    issues = validate_review_summary(report, _edited_lines(summary, mutate))
    _expect(issues, "summary-findings-table-row-duplicate")
    _expect(issues, "summary-findings-table-row-count")


def test_swapped_rows_are_reported_as_order():
    report = _report()
    summary = _filled(report)
    rows = _row_lines(summary)

    def mutate(lines: list[str]) -> None:
        lines[rows[0]], lines[rows[1]] = lines[rows[1]], lines[rows[0]]

    issues = validate_review_summary(report, _edited_lines(summary, mutate))
    _expect(issues, "summary-findings-table-row-order")
    # The rows themselves still match their chains — this is an order defect,
    # not a content defect, and the two must not be conflated.
    assert "summary-findings-table-severity" not in _codes(issues)


def test_tampered_severity_cell_is_reported():
    report = _report()
    summary = _filled(report)
    broken = summary.replace("| ERROR |", "| WARN |", 1)
    _expect(validate_review_summary(report, broken), "summary-findings-table-severity")


def test_tampered_chain_cell_is_reported():
    report = _report()
    summary = _filled(report)
    broken = summary.replace("页:电源", "页:控制")
    _expect(validate_review_summary(report, broken), "summary-findings-table-chain")


def test_blank_analysis_and_advice_are_reported():
    report = _report()
    summary = _filled(report)
    no_analysis = summary.replace(ANALYSIS, "", 1)
    _expect(
        validate_review_summary(report, no_analysis),
        "summary-findings-table-analysis-empty",
    )
    no_advice = summary.replace(ADVICE, "", 1)
    _expect(
        validate_review_summary(report, no_advice),
        "summary-findings-table-advice-empty",
    )


def test_separator_must_have_the_same_seven_columns():
    report = _report()
    summary = _filled(report)
    broken = summary.replace("|---|---|---|---|---|---|---|", "|---|", 1)
    assert broken != summary
    issues = validate_review_summary(report, broken)
    _expect(issues, "summary-findings-table-separator")


def test_leftover_placeholder_cells_are_reported():
    report = _report()
    summary = _filled(report, fill_analysis=False, fill_advice=False)
    issues = validate_review_summary(report, summary)
    _expect(issues, "summary-blank-placeholder-residue")
    _expect(issues, "summary-findings-table-analysis-placeholder")
    _expect(issues, "summary-findings-table-advice-placeholder")


def test_todo_in_an_analysis_cell_is_reported():
    report = _report()
    summary = _filled(report).replace(ANALYSIS, "TODO 补根因分析", 1)
    _expect(validate_review_summary(report, summary), "summary-findings-table-analysis-todo")


def test_missing_or_unreadable_findings_heading():
    report = _report()
    summary = _filled(report)
    without = summary.replace("## 2. 逐条问题（2 条）", "## 二、逐条问题", 1)
    _expect(validate_review_summary(report, without), "summary-findings-heading-missing")
    no_count = summary.replace("（2 条）", "（若干）", 1)
    _expect(
        validate_review_summary(report, no_count),
        "summary-findings-heading-count-missing",
    )


def test_unreadable_findings_and_ledger_rows():
    report = _report()
    summary = _filled(report)

    findings_broken = copy.deepcopy(report)
    findings_broken["findings"] = "not a list"
    _expect(validate_review_summary(findings_broken, summary), "findings-not-list")

    rows_broken = copy.deepcopy(report)
    rows_broken[CHAINS_KEY] = [None, 3]
    issues = validate_review_summary(rows_broken, summary)
    _expect(issues, "location-chains-row-not-dict")

    index_broken = copy.deepcopy(report)
    index_broken[CHAINS_KEY][0] = {
        key: value for key, value in index_broken[CHAINS_KEY][0].items() if key != "index"
    }
    _expect(
        validate_review_summary(index_broken, summary),
        "location-chains-index-missing",
    )


def test_triage_ledger_must_be_a_list():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["warning_triage"] = {"w1": "有益"}
    _expect(validate_review_summary(broken, summary), "triage-ledger-not-list")


def test_zero_findings_table_may_not_carry_other_rows():
    report = _report(zero_findings=True)
    summary = _filled(report)
    broken = summary.replace(
        "| — | — | — | — | 本次审查没有 finding | — | — |",
        "| 0 | ERROR | some-rule | 合成工程A → Board1 → 页:电源 → U1 | 手写的 | 分析 | 建议 |",
    )
    _expect(validate_review_summary(report, broken), "summary-findings-table-zero-row")


# ---------------------------------------------------------------------------
# 2. the human sections and the skeleton's leftovers
# ---------------------------------------------------------------------------


def test_section_one_must_not_be_empty():
    report = _report()
    summary = _filled(report).replace(CONNECTION, "")
    _expect(validate_review_summary(report, summary), "summary-section-1-empty")


def test_section_three_and_four_must_not_be_empty():
    report = _report()
    summary = _filled(report)
    start = summary.index("## 3. 待确认")
    end = summary.index("## 4. 下一步")
    stripped = summary[:start] + "## 3. 待确认（本报告依赖的未知项）\n\n" + summary[end:]
    issues = validate_review_summary(report, stripped)
    _expect(issues, "summary-section-3-empty")
    no_next = _filled(report).replace(NEXT_STEPS, "")
    _expect(validate_review_summary(report, no_next), "summary-section-4-empty")


def test_missing_human_section_is_reported():
    report = _report()
    summary = _filled(report)
    start = summary.index("## 4. 下一步")
    without = summary[:start]
    _expect(validate_review_summary(report, without), "summary-section-4-missing")


def test_todo_placeholder_in_a_human_section_is_reported():
    report = _report()
    summary = _filled(report).replace(NEXT_STEPS, "1. TODO 补下一步")
    _expect(validate_review_summary(report, summary), "summary-section-4-todo")


def test_legal_wording_is_not_a_placeholder():
    """「需人工」「待手册」 and a `<MPN>` command example are content, not TODO."""
    report = _report()
    summary = _filled(report).replace(
        NEXT_STEPS,
        "1. 需人工复核那条 warning。\n"
        "2. 待手册到货后按手册修改，先去要 PDF。\n"
        "3. 命令照抄：`boardwise parts add <MPN> --lcsc <C码> --verified`。",
    )
    assert validate_review_summary(report, summary) == []


def test_skeleton_comment_residue_is_reported():
    report = _report()
    summary = _filled(report) + (
        "\n<!-- AI 在这里写一行：连上了哪个工程/哪个窗口；没连上写清楚怎么修。 -->\n"
    )
    _expect(validate_review_summary(report, summary), "summary-skeleton-comment-residue")


# ---------------------------------------------------------------------------
# 3. the one authoritative conclusion
# ---------------------------------------------------------------------------


def test_conclusion_line_must_equal_one_liner():
    report = _report()
    summary = _filled(report)
    one_liner = report["conclusion"]["oneLiner"]
    broken = summary.replace(one_liner, "本工程暂无阻塞项。", 1)
    _expect(validate_review_summary(report, broken), "summary-conclusion-mismatch")


def test_narrow_summary_conclusion_may_not_stand_in_for_one_liner():
    report = _report()
    summary = _filled(report)
    report["summary"]["conclusion"] = "干净，可以出图"
    broken = summary.replace(report["conclusion"]["oneLiner"], "干净，可以出图", 1)
    issues = validate_review_summary(report, broken)
    issue = _expect(issues, "summary-conclusion-mismatch")
    assert "summary.conclusion" in issue["message"]


def test_missing_or_malformed_conclusion_line():
    report = _report()
    summary = _filled(report)
    one_liner = report["conclusion"]["oneLiner"]
    without = summary.replace(f"**结论：{one_liner}**", "")
    _expect(validate_review_summary(report, without), "summary-conclusion-line-missing")
    malformed = summary.replace(f"**结论：{one_liner}**", f"**结论：{one_liner}（")
    _expect(validate_review_summary(report, malformed), "summary-conclusion-line-malformed")


def test_conclusion_section_must_exist_with_its_fields():
    report = _report()
    summary = _filled(report)
    without = copy.deepcopy(report)
    del without["conclusion"]
    _expect(validate_review_summary(without, summary), "conclusion-not-dict")

    blank = copy.deepcopy(report)
    blank["conclusion"] = {"verdict": "", "mayQuotePassed": False, "oneLiner": ""}
    issues = validate_review_summary(blank, summary)
    _expect(issues, "conclusion-oneLiner-missing")
    _expect(issues, "conclusion-verdict-missing")


def test_report_summary_must_be_a_dict():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["summary"] = "nope"
    _expect(validate_review_summary(broken, summary), "report-summary-not-dict")


def test_completion_section_must_exist():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    del broken["completion"]
    issues = validate_review_summary(broken, summary)
    _expect(issues, "completion-not-dict")


def test_conclusion_cross_fields_are_checked():
    report = _report()
    summary = _filled(report)

    verdict_broken = copy.deepcopy(report)
    verdict_broken["conclusion"]["verdict"] = "complete"
    _expect(
        validate_review_summary(verdict_broken, summary), "conclusion-verdict-mismatch"
    )

    quote_broken = copy.deepcopy(report)
    quote_broken["conclusion"]["mayQuotePassed"] = True
    _expect(
        validate_review_summary(quote_broken, summary),
        "conclusion-mayQuotePassed-mismatch",
    )

    exit_broken = copy.deepcopy(report)
    exit_broken["conclusion"]["exitCode"] = 3
    _expect(validate_review_summary(exit_broken, summary), "conclusion-exitCode-mismatch")


def test_positive_pass_claim_is_reported_when_quoting_is_false():
    report = _report()
    summary = _filled(report) + "\n审查通过，可以投板。\n"
    issues = validate_review_summary(report, summary)
    issue = _expect(issues, "summary-pass-claim")
    assert "审查通过" in issue["message"]


def test_negated_pass_wording_is_not_a_claim():
    report = _report()
    summary = _filled(report) + "\n不能写「审查通过」，也不许说可以投板；本板尚未通过。\n"
    issues = validate_review_summary(report, summary)
    assert "summary-pass-claim" not in _codes(issues)


def test_negation_does_not_reach_across_a_clause():
    """A negative earlier in the line must not license a later claim.

    Both cuts are measured: punctuation, and the contrast conjunction 「但」.
    Each of these lines contains a negation and a claim, and only the claim's
    own clause decides whether it is negated.
    """
    report = _report()
    cases = {
        "未完成 PCB 视觉复核；可以投板": "summary-pass-claim",
        "未完成 PCB 视觉复核但可以投板": "summary-pass-claim",
        "尚未逐页阅读；已与 X 手册核对": "datasheet-claim-forbidden",
        "未读手册但与 X 手册一致": "datasheet-claim-forbidden",
    }
    for line, code in cases.items():
        issues = validate_review_summary(report, _filled(report) + "\n" + line + "\n")
        _expect(issues, code)


def test_negation_does_not_reach_across_a_clause_for_crossview():
    report = _report(suspected=True)
    summary = _filled(report)
    for line in (
        "未完成逐脚核对，PCB 错版已确认",
        "未完成逐脚核对但 PCB 错版已确认",
    ):
        issues = validate_review_summary(report, summary + "\n" + line + "\n")
        _expect(issues, "crossview-confirmed-claim")


def test_direct_negation_still_exempts_the_claim():
    report = _report()
    summary = _filled(report) + (
        "\n本项未证实；不能写成已与手册核对；也不得写成与手册一致；"
        "无法确认与手册相符。\n"
        "不能据此认定可以投板；不得据此声称已与手册核对；"
        "不能直接说与手册一致；不得视为审查通过。\n"
    )
    codes = _codes(validate_review_summary(report, summary))
    assert "datasheet-claim-forbidden" not in codes, codes
    assert "summary-pass-claim" not in codes, codes


# ---------------------------------------------------------------------------
# 4. triage consistency
# ---------------------------------------------------------------------------


def test_manual_review_list_must_exist_and_name_the_same_slots():
    report = _report()
    summary = _filled(report)

    missing = copy.deepcopy(report)
    del missing["completion"]["manualReviewRequired"]
    _expect(validate_review_summary(missing, summary), "triage-manual-list-missing")

    not_a_list = copy.deepcopy(report)
    not_a_list["completion"]["manualReviewRequired"] = "w3"
    _expect(
        validate_review_summary(not_a_list, summary), "triage-manual-list-missing"
    )

    wrong_key = copy.deepcopy(report)
    wrong_key["completion"]["manualReviewRequired"] = [{"key": "not-the-manual-slot"}]
    _expect(validate_review_summary(wrong_key, summary), "triage-manual-list-keys")

    short = copy.deepcopy(report)
    short["completion"]["manualReviewRequired"] = []
    _expect(validate_review_summary(short, summary), "triage-manual-list-mismatch")


def test_manual_review_list_is_empty_when_nothing_needs_a_human():
    report = _report()
    report["warning_triage"][2] = dict(
        report["warning_triage"][2], text="GND 与 PGND 同名", verdict="有害"
    )
    report["completion"]["warningsPendingTriage"] = 0
    report["completion"]["warningsNeedsManual"] = 0
    report["completion"]["manualReviewRequired"] = []
    report["completion"]["verdictWhy"] = ["2 颗器件缺已核验手册事实"]
    report["conclusion"] = checkup.conclusion_section(report)
    summary = _filled(report).replace(
        "3. 复核那条 needs-manual warning。", "3. 无待人工项。", 1
    )
    assert validate_review_summary(report, summary) == []

    missing = copy.deepcopy(report)
    del missing["completion"]["manualReviewRequired"]
    _expect(validate_review_summary(missing, summary), "triage-manual-list-missing")


def test_non_dict_triage_slot_is_named():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["warning_triage"][2] = None
    issues = validate_review_summary(broken, summary)
    _expect(issues, "triage-slot-not-dict")


def test_measured_summary_triage_sentence_is_read():
    """The shape the real summary uses: `1 需人工看` has no measure word."""
    report = _report()
    summary = _filled(report).replace(
        "1. 2 条 warning 已分诊、待分诊 1 条。",
        "1. 2 条 warning 已分诊（3 条中 1 条待分诊 / 1 需人工看）。",
        1,
    )
    assert validate_review_summary(report, summary) == []

    broken = summary.replace("1 需人工看", "0 需人工看", 1)
    _expect(validate_review_summary(report, broken), "summary-manual-count-mismatch")


def test_stale_completion_counts_are_reported():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["completion"]["warningsPendingTriage"] = 0
    broken["completion"]["warningsNeedsManual"] = 0
    broken["completion"]["manualReviewRequired"] = []
    issues = validate_review_summary(broken, summary)
    _expect(issues, "triage-pending-count-mismatch")
    _expect(issues, "triage-manual-count-mismatch")
    _expect(issues, "triage-manual-list-mismatch")


def test_summary_triage_numbers_must_match_the_recomputation():
    report = _report()
    summary = _filled(report)
    broken = summary.replace("2 条 warning 已分诊", "5 条 warning 已分诊", 1)
    broken = broken.replace("待分诊 1 条", "待分诊 0 条", 1)
    issues = validate_review_summary(report, broken)
    _expect(issues, "summary-triage-closed-count-mismatch")
    _expect(issues, "summary-triage-pending-count-mismatch")


def test_pending_may_not_be_denied():
    report = _report()
    summary = _filled(report) + "\n全部已分诊。\n"
    _expect(validate_review_summary(report, summary), "summary-pending-denied")


def test_manual_debt_must_be_disclosed():
    report = _report()
    # The verdict sentence is not allowed to be the disclosure under test: this
    # report's own line says only 「待分诊」, so the text has to say it itself.
    report["completion"]["verdictWhy"] = ["1 条 warning 待分诊"]
    report["conclusion"] = checkup.conclusion_section(report)
    summary = _filled(report)
    hidden = summary.replace("待人工复核", "待人工看", 1)
    hidden = hidden.replace("needs-manual warning", "那条 warning", 1)
    assert "需人工" not in hidden and "人工复核" not in hidden
    issues = validate_review_summary(report, hidden)
    _expect(issues, "summary-manual-undisclosed")


def test_manual_count_claim_must_match():
    report = _report()
    summary = _filled(report).replace("待人工复核 1 条", "待人工复核 3 条", 1)
    _expect(validate_review_summary(report, summary), "summary-manual-count-mismatch")


def test_pending_alone_is_not_a_failure():
    report = _report()
    summary = _filled(report)
    assert report["completion"]["warningsPendingTriage"] == 1
    assert validate_review_summary(report, summary) == []


# ---------------------------------------------------------------------------
# 5. environment / evidence disclosure
# ---------------------------------------------------------------------------


def test_environment_must_be_read_only():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["environment"]["writeAllowed"] = True
    _expect(validate_review_summary(broken, summary), "environment-write-allowed")


def test_unexpected_next_action_is_reported():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["environment"]["allowedNextActions"] = [
        {"id": "apply-now", "mode": "write", "description": "直接改板"}
    ]
    _expect(
        validate_review_summary(broken, summary),
        "environment-next-action-unexpected",
    )


def test_environment_limitation_must_be_disclosed():
    report = _report()
    summary = _filled(report)
    code = report["environment"]["limitations"][0]["code"]
    broken = summary.replace(f"`{code}`", "`（被抹掉的限制）`", 1)
    issues = validate_review_summary(report, broken)
    _expect(issues, "environment-limitation-undisclosed")


def test_partial_disclosure_line_must_be_present():
    report = _report()
    summary = _filled(report)
    lines = summary.splitlines()
    kept = [line for line in lines if "`datasheet-evidence`" not in line]
    assert len(kept) == len(lines) - 1
    issues = validate_review_summary(report, "\n".join(kept) + "\n")
    _expect(issues, "summary-disclosure-undisclosed")


def test_stale_delivery_complete_is_not_accepted():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["evidence"]["delivery"] = dict(
        broken["evidence"]["delivery"], status="complete", requiredDisclosures=[]
    )
    issues = validate_review_summary(broken, summary)
    _expect(issues, "evidence-delivery-stale")
    _expect(issues, "evidence-delivery-disclosures-stale")


def test_stale_coverage_is_reported():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["evidence"]["coverage"] = dict(
        broken["evidence"]["coverage"], livePcb="ok"
    )
    _expect(validate_review_summary(broken, summary), "evidence-coverage-stale")


def test_channel_status_outside_the_frozen_vocabulary_is_reported():
    """``ok/failed/missing/unavailable/not-applicable`` is the whole vocabulary."""
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["evidence"]["channels"]["liveSchematic"]["status"] = "mystery"
    before = copy.deepcopy(broken)

    issues = validate_review_summary(broken, summary)

    issue = _expect(issues, "evidence-channel-status-invalid")
    assert issue["path"] == "report.evidence.channels.liveSchematic.status"
    assert "mystery" in issue["message"]
    # Pure, deterministic, and the report is not repaired in place.
    assert issues == validate_review_summary(broken, summary)
    assert broken == before


def test_invalid_channel_statuses_follow_the_frozen_channel_order():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    # Deliberately set them in the reverse of CHANNEL_ORDER.
    broken["evidence"]["channels"]["pcbImage"]["status"] = "bogus"
    broken["evidence"]["channels"]["liveSchematic"]["status"] = "bogus"
    broken["evidence"]["channels"]["livePcb"]["status"] = "bogus"

    codes = [
        (issue["code"], issue["path"])
        for issue in validate_review_summary(broken, summary)
        if issue["code"] == "evidence-channel-status-invalid"
    ]
    assert codes == [
        ("evidence-channel-status-invalid", "report.evidence.channels.liveSchematic.status"),
        ("evidence-channel-status-invalid", "report.evidence.channels.livePcb.status"),
        ("evidence-channel-status-invalid", "report.evidence.channels.pcbImage.status"),
    ]


def test_non_dict_channel_row_is_named_not_raised():
    report = _report()
    summary = _filled(report)
    broken = copy.deepcopy(report)
    broken["evidence"]["channels"]["liveSchematic"] = "not-a-row"
    before = copy.deepcopy(broken)

    issues = validate_review_summary(broken, summary)

    issue = _expect(issues, "evidence-channel-not-dict")
    assert issue["path"] == "report.evidence.channels.liveSchematic"
    assert "str" in issue["message"]
    # The row stays a string: the validator reports, it does not repair.
    assert broken == before
    assert broken["evidence"]["channels"]["liveSchematic"] == "not-a-row"


def test_missing_environment_and_evidence_sections_are_named():
    report = _report()
    del report["environment"]
    del report["evidence"]
    summary = _filled(report)
    issues = validate_review_summary(report, summary)
    _expect(issues, "environment-missing")
    _expect(issues, "summary-environment-heading-missing")
    _expect(issues, "evidence-missing")
    _expect(issues, "summary-evidence-heading-missing")


def test_unreadable_environment_and_evidence_rows_are_named():
    report = _report()
    summary = _filled(report)

    environment_broken = copy.deepcopy(report)
    environment_broken["environment"] = {
        "writeAllowed": False,
        "allowedNextActions": {"id": "offline-plan"},
        "limitations": [{"affects": ["livePcb"]}],
    }
    issues = validate_review_summary(environment_broken, summary)
    _expect(issues, "environment-next-actions-missing")
    _expect(issues, "environment-limitation-code-missing")

    environment_missing_rows = copy.deepcopy(report)
    environment_missing_rows["environment"] = {"writeAllowed": False}
    _expect(
        validate_review_summary(environment_missing_rows, summary),
        "environment-limitations-missing",
    )

    evidence_broken = copy.deepcopy(report)
    del evidence_broken["evidence"]["channels"]
    del evidence_broken["evidence"]["coverage"]
    del evidence_broken["evidence"]["delivery"]
    issues = validate_review_summary(evidence_broken, summary)
    _expect(issues, "evidence-channels-missing")
    _expect(issues, "evidence-coverage-missing")
    _expect(issues, "evidence-delivery-missing")


def test_focus_restore_failure_blocks_finalize_even_when_disclosed():
    """537C: a failed focus restore **blocks**; the disclosure is not a licence."""
    report = _report(focus_ok=False)
    summary = _filled(report)
    assert report["evidence"]["delivery"]["status"] == "partial"
    assert "live-focus-restore-failed" in summary  # the renderer wrote it down
    issues = validate_review_summary(report, summary)
    _expect(issues, "focus-not-restored")
    assert _codes(issues) == ["focus-not-restored"], issues


def test_absent_live_capture_owes_no_focus_disclosure():
    report = _report()
    channels = report["evidence"]["channels"]
    del report["evidence"]["liveCapture"]
    report["evidence"]["coverage"] = evidence_coverage(channels)
    report["evidence"]["delivery"] = evidence_delivery(channels, None)
    summary = _filled(report)
    assert "live-focus-restore-failed" not in summary
    assert validate_review_summary(report, summary) == []


def test_empty_live_capture_record_fails_closed():
    report = _report()
    channels = report["evidence"]["channels"]
    report["evidence"]["liveCapture"] = {}
    report["evidence"]["delivery"] = evidence_delivery(channels, {})
    summary = _filled(report)
    assert "live-identity-unverified" in summary
    _expect(validate_review_summary(report, summary), "focus-not-restored")


def test_unverified_identity_is_a_partial_disclosure_not_a_ban():
    report = _report(identity_verified=False)
    summary = _filled(report)
    assert report["evidence"]["delivery"]["status"] == "partial"
    codes = [
        row["code"] for row in report["evidence"]["delivery"]["requiredDisclosures"]
    ]
    assert "live-identity-unverified" in codes
    assert validate_review_summary(report, summary) == []


# ---------------------------------------------------------------------------
# 6. datasheet wording
# ---------------------------------------------------------------------------


def test_manual_claim_is_forbidden_while_the_channel_is_open():
    report = _report()
    summary = _filled(report) + "\n已与 U1 的手册核对，手册要求 10 µF。\n"
    issues = validate_review_summary(report, summary)
    _expect(issues, "datasheet-claim-forbidden")


def test_legitimate_missing_manual_disclosures_survive():
    """`尚未与手册核对` / `与手册不一致` / `未与手册核对` are disclosures, not claims."""
    report = _report()
    summary = _filled(report) + (
        "\n尚未与手册核对；与手册不一致；未与手册核对，待手册到货后按手册修改，"
        "先去要 PDF。\n"
    )
    issues = validate_review_summary(report, summary)
    assert "datasheet-claim-forbidden" not in _codes(issues), issues


def test_manual_claim_allowed_when_channel_is_closed_and_nothing_accepted():
    report = _report(channel_status={"datasheets": "ok"})
    report["evidence"]["coverage"] = evidence_coverage(report["evidence"]["channels"])
    report["evidence"]["delivery"] = evidence_delivery(
        report["evidence"]["channels"], report["evidence"]["liveCapture"]
    )
    summary = _filled(report) + "\n已与 U1 的手册核对，手册要求 10 µF。\n"
    # `datasheets` is ok, but the delivery is still partial (livePcb/pcbImage), so
    # the summary must have been filled from this same report — it was.
    codes = _codes(validate_review_summary(report, summary))
    assert "datasheet-claim-forbidden" not in codes, codes


def test_accepted_unknown_also_blocks_manual_claims():
    report = _report(channel_status={"datasheets": "ok"})
    report["evidence"]["coverage"] = evidence_coverage(report["evidence"]["channels"])
    report["evidence"]["delivery"] = evidence_delivery(
        report["evidence"]["channels"], report["evidence"]["liveCapture"]
    )
    report["completion"]["acceptedUnknown"] = 2
    report["conclusion"] = checkup.conclusion_section(report)
    summary = _filled(report) + "\n已与 U1 的手册核对。\n"
    _expect(validate_review_summary(report, summary), "datasheet-claim-forbidden")


# ---------------------------------------------------------------------------
# 7. cross-view suspected
# ---------------------------------------------------------------------------


def test_suspected_cross_view_must_say_suspected():
    report = _report(suspected=True)
    summary = _filled(report)
    assert "疑似" in summary
    assert validate_review_summary(report, summary) == []

    hidden = summary.replace("疑似错版", "跨视图问题", 1)
    _expect(validate_review_summary(report, hidden), "crossview-suspected-undisclosed")


def test_suspected_cross_view_may_not_be_upgraded_to_confirmed():
    report = _report(suspected=True)
    summary = _filled(report)
    broken = summary.replace("需人工核对", "已确认", 1)
    issues = validate_review_summary(report, broken)
    _expect(issues, "crossview-confirmed-claim")
    # Suspected is not re-read as confirmed anywhere: the report is untouched.
    assert report["pcb_review"]["boards"][0]["crossView"]["status"] == "suspected"


def test_no_suspected_section_asks_for_nothing():
    report = _report()
    assert "pcb_review" not in report
    summary = _filled(report)
    assert "crossview-suspected-undisclosed" not in _codes(
        validate_review_summary(report, summary)
    )


# ---------------------------------------------------------------------------
# 8. the machine-section sync (537D2b1): two sections, nothing else
# ---------------------------------------------------------------------------

SYNC_PREFIX = (
    "## 1. 连接状态\n\n"
    "已连接 `test` 工程；下面是第 2 节。\n\n"
    "## 2. 逐条问题（2 条）\n\n"
    "| # | 级别 | 规则 | 定位链 | 问题 | 分析 | 建议 |\n"
    "|---|---|---|---|---|---|---|\n"
    "| 0 | ERROR | decap-required-caps | C1、U1 | 去耦电容缺失 | 人工分析 | 人工建议 |\n"
)
STALE_ENVIRONMENT = (
    "## 审查环境与权限（environment）\n\n- 上一轮留下的旧 environment 段\n\n"
)
SYNC_BETWEEN = (
    "## 2b. 人工补充（不是机器段）\n\n"
    "人工结论：这一段一个字都不许动。\n\n"
)
STALE_EVIDENCE = "## 证据覆盖（evidence）\n\n- 上一轮留下的旧 evidence 段\n\n"
SYNC_SUFFIX = (
    "## 3. 待确认（本报告依赖的未知项）\n\n"
    "1. 等手册。\n\n"
    "## 4. 下一步（按优先级）\n\n"
    "1. 去要 PDF。\n"
)


def _authoritative_section(render, section: dict, heading: str, newline: str) -> str:
    """One machine section exactly as the shared renderer spells it."""
    lines = render(section, heading=heading)
    if not lines:
        return ""
    return newline.join(lines) + newline


def _sync_text() -> str:
    return (
        SYNC_PREFIX
        + STALE_ENVIRONMENT
        + SYNC_BETWEEN
        + STALE_EVIDENCE
        + SYNC_SUFFIX
    )


def test_sync_replaces_only_the_two_machine_sections():
    report = _report()
    text = _sync_text()

    out = synchronize_review_summary_sections(report, text)

    expected = (
        SYNC_PREFIX
        + _authoritative_section(
            render_environment_markdown,
            report["environment"],
            ENVIRONMENT_HEADING,
            "\n",
        )
        + SYNC_BETWEEN
        + _authoritative_section(
            render_evidence_markdown,
            report["evidence"],
            EVIDENCE_HEADING,
            "\n",
        )
        + SYNC_SUFFIX
    )
    assert out == expected
    # Said three ways, because "only those two" is the whole contract: the
    # prefix, the 2b analysis between them, and sections 3/4 are byte-identical.
    assert out.startswith(SYNC_PREFIX)
    assert SYNC_BETWEEN in out
    assert out.endswith(SYNC_SUFFIX)
    assert "上一轮留下的旧" not in out


def test_sync_uses_the_authoritative_rendering_verbatim():
    report = _report()
    out = synchronize_review_summary_sections(report, _sync_text())

    environment = render_environment_markdown(report["environment"])
    evidence = render_evidence_markdown(report["evidence"])
    assert environment and evidence
    # The block is the renderer's own lines, in order, not a second format.
    first = out.index(environment[0])
    assert out[first:].startswith("\n".join(environment))
    second = out.index(evidence[0])
    assert out[second:].startswith("\n".join(evidence))


def test_sync_is_idempotent_and_leaves_the_report_untouched():
    report = _report()
    before = copy.deepcopy(report)
    once = synchronize_review_summary_sections(report, _sync_text())
    twice = synchronize_review_summary_sections(report, once)

    assert twice == once
    assert report == before
    # An already-synced delivery (the acceptance fixture) is a no-op.
    filled = _filled(report)
    assert synchronize_review_summary_sections(report, filled) == filled


def test_sync_does_not_invent_a_missing_heading():
    report = _report()
    text = (
        "## 1. 连接状态\n\n人工内容\n\n"
        "## 3. 待确认\n\n等手册。\n\n"
        "## 4. 下一步\n\n去要 PDF。\n"
    )
    out = synchronize_review_summary_sections(report, text)

    assert out == text
    assert ENVIRONMENT_HEADING not in out
    assert EVIDENCE_HEADING not in out
    codes = _codes(validate_review_summary(report, out))
    assert "summary-environment-heading-missing" in codes
    assert "summary-evidence-heading-missing" in codes


def test_sync_never_guesses_a_missing_report_section():
    report = _report()
    del report["environment"]
    del report["evidence"]
    text = _sync_text()

    out = synchronize_review_summary_sections(report, text)

    assert out == text
    codes = _codes(validate_review_summary(report, out))
    assert "environment-missing" in codes
    assert "evidence-missing" in codes


def test_sync_never_raises_on_a_malformed_section():
    report = _report()
    text = _sync_text()

    for value in ([], "not-a-section", 0):
        report["environment"] = value
        report["evidence"] = value
        assert synchronize_review_summary_sections(report, text) == text

    # A nested field of the wrong shape makes the *shared renderer* raise; the
    # sync must not turn that into a traceback or a guessed/blank section. The
    # validator names the structural problem instead.
    report["environment"] = {
        "writeAllowed": False,
        "allowedNextActions": "not-a-list",
        "limitations": [],
    }
    report["evidence"] = {"channels": "not-a-dict"}
    assert synchronize_review_summary_sections(report, text) == text


def test_sync_keeps_crlf_and_the_bytes_outside_the_two_sections():
    report = _report()
    text = _sync_text().replace("\n", "\r\n")

    out = synchronize_review_summary_sections(report, text)

    expected = (
        SYNC_PREFIX
        + _authoritative_section(
            render_environment_markdown,
            report["environment"],
            ENVIRONMENT_HEADING,
            "\n",
        )
        + SYNC_BETWEEN
        + _authoritative_section(
            render_evidence_markdown,
            report["evidence"],
            EVIDENCE_HEADING,
            "\n",
        )
        + SYNC_SUFFIX
    ).replace("\n", "\r\n")
    assert out == expected
    assert "\n" not in out.replace("\r\n", "")
    assert synchronize_review_summary_sections(report, out) == out


def test_sync_bad_argument_types_are_returned_not_raised():
    assert synchronize_review_summary_sections(None, "text") == "text"
    assert synchronize_review_summary_sections({}, None) is None


# ---------------------------------------------------------------------------
# determinism, purity, and never raising
# ---------------------------------------------------------------------------


def test_same_inputs_give_the_same_list_and_inputs_are_untouched():
    report = _report(suspected=True)
    summary = _filled(report)
    report_before = copy.deepcopy(report)
    summary_before = str(summary)

    first = validate_review_summary(report, summary)
    second = validate_review_summary(report, summary)

    assert first == second
    assert report == report_before
    assert summary == summary_before
    for issue in first:
        assert set(issue) == {"code", "path", "message"}
        assert all(isinstance(value, str) for value in issue.values())


def test_a_broken_input_reports_in_a_fixed_order():
    report = _report()
    summary = _filled(report).replace("2 条 warning 已分诊", "9 条 warning 已分诊", 1)
    report["completion"]["warningsPendingTriage"] = 7
    first = _codes(validate_review_summary(report, summary))
    second = _codes(validate_review_summary(report, summary))
    assert first == second
    # The group order is the documented one: findings shape, then the text.
    assert first.index("triage-pending-count-mismatch") < first.index(
        "summary-triage-closed-count-mismatch"
    )


def test_bad_argument_types_are_named_not_raised():
    assert _codes(validate_review_summary(None, "x")) == ["report-not-dict"]
    assert _codes(validate_review_summary({}, None)) == ["summary-not-str"]


def test_garbage_inputs_never_raise():
    garbage_report = {
        "findings": "not a list",
        CHAINS_KEY: [None, 3, {"index": "zero"}],
        "warning_triage": {"not": "a list"},
        "completion": None,
        "environment": [],
        "evidence": {"channels": "nope"},
        "pcb_review": {"boards": [None, {"crossView": {"status": "suspected"}}]},
        "summary": "nope",
        "conclusion": "nope",
    }
    garbage_summary = (
        "## 2. 逐条问题（2 条）\n\n| # | a |\n|---|---|\n"
        "| (unclosed [ group | " + "|" * 50 + "\n" + "(((" * 40 + "\n"
        "**结论：\n"
        "## 1. 连接状态\n<!--\n## 3. 待确认\n## 4. 下一步\n"
    )
    issues = validate_review_summary(garbage_report, garbage_summary)
    assert isinstance(issues, list)
    assert issues
    for issue in issues:
        assert set(issue) == {"code", "path", "message"}


def test_split_markdown_row_is_the_inverse_of_the_renderer_cell():
    assert split_markdown_row("not a row") is None
    assert split_markdown_row("| a | b |") == [" a ", " b "]
    assert split_markdown_row("| a\\|b | c |") == [" a|b ", " c "]
    # A trailing backslash followed by the separator is NOT an escape.
    assert split_markdown_row("| a\\ | b |") == [" a\\ ", " b "]


def test_validator_does_not_import_the_cli():
    """A static guarantee, read from the AST so a docstring cannot fake it."""
    tree = ast.parse(inspect.getsource(reviewfinalize))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append((node.module or "") + "." + ".".join(
                alias.name for alias in node.names
            ))
    assert not [name for name in imported if "cli" in name.split(".")], imported


# ---------------------------------------------------------------------------
# 9. the raw evidence containers (537D2b1's last slice)
# ---------------------------------------------------------------------------
#
# ``evidence.channels[*]`` and ``evidence.liveCapture`` are the collectors' own
# record. ``reviewread``'s artifacts projection is deliberately **tolerant** — it
# skips anything that is not a list / not an object — but tolerance in a reader
# must not become silence in the gate: a channel whose ``artifacts`` is the
# string ``"bad"`` never said 「no artifacts」, it said something this ledger
# cannot read. These rows name that state and say exactly where it is.

CHANNEL_CONTAINER_FIELDS = ("artifacts", "errors", "steps")


@pytest.mark.parametrize("field", CHANNEL_CONTAINER_FIELDS)
def test_channel_container_field_must_be_a_list(field):
    report = _report()
    summary = _filled(report)
    report["evidence"]["channels"]["liveSchematic"][field] = "bad"

    issues = validate_review_summary(report, summary)

    row = _expect(issues, "evidence-channel-field-not-list")
    assert row["path"] == f"report.evidence.channels.liveSchematic.{field}"
    assert "list" in row["message"]
    assert "liveSchematic" in row["message"]
    # A container shape changes no coverage/delivery reading, so this is the
    # whole disagreement: nothing stale is invented beside it.
    assert _codes(issues) == ["evidence-channel-field-not-list"]


def test_channel_artifact_item_must_be_a_dict_and_the_index_is_named():
    report = _report()
    summary = _filled(report)
    report["evidence"]["channels"]["schematicImage"]["artifacts"] = [
        "bad",
        {"file": "canvas/p1.png", "kind": "image"},
        ["also-bad"],
    ]

    issues = validate_review_summary(report, summary)

    rows = [
        issue
        for issue in issues
        if issue["code"] == "evidence-channel-artifact-not-dict"
    ]
    assert [issue["path"] for issue in rows] == [
        "report.evidence.channels.schematicImage.artifacts[0]",
        "report.evidence.channels.schematicImage.artifacts[2]",
    ]
    assert all("dict" in issue["message"] for issue in rows)


@pytest.mark.parametrize("field", ["artifacts", "steps"])
def test_live_capture_container_field_must_be_a_list(field):
    report = _report()
    summary = _filled(report)
    report["evidence"]["liveCapture"][field] = "bad"

    issues = validate_review_summary(report, summary)

    row = _expect(issues, "evidence-live-capture-field-not-list")
    assert row["path"] == f"report.evidence.liveCapture.{field}"
    assert _codes(issues) == ["evidence-live-capture-field-not-list"]


def test_live_capture_artifact_item_must_be_a_dict():
    report = _report()
    summary = _filled(report)
    report["evidence"]["liveCapture"]["artifacts"] = ["bad"]

    issues = validate_review_summary(report, summary)

    row = _expect(issues, "evidence-live-capture-artifact-not-dict")
    assert row["path"] == "report.evidence.liveCapture.artifacts[0]"
    assert "dict" in row["message"]


def test_live_capture_capture_file_must_be_a_dict():
    report = _report()
    summary = _filled(report)
    report["evidence"]["liveCapture"]["captureFile"] = "bad"

    issues = validate_review_summary(report, summary)

    row = _expect(issues, "evidence-live-capture-file-not-dict")
    assert row["path"] == "report.evidence.liveCapture.captureFile"
    assert "captureFile" in row["message"]
    # The focus/identity reading is untouched by a container shape.
    assert _codes(issues) == ["evidence-live-capture-file-not-dict"]


def test_absent_container_fields_are_not_asked_for():
    """Missing fields keep the old compatibility: nothing must be back-filled."""
    report = _report()
    for row in report["evidence"]["channels"].values():
        for field in CHANNEL_CONTAINER_FIELDS:
            row.pop(field)
    report["evidence"]["liveCapture"].pop("artifacts")
    report["evidence"]["liveCapture"].pop("steps")
    summary = _filled(report)

    assert validate_review_summary(report, summary) == []


def test_live_capture_without_capture_file_still_validates():
    """The existing legal fixture has no ``captureFile``: that stays legal."""
    report = _report()
    assert "captureFile" not in report["evidence"]["liveCapture"]
    summary = _filled(report)

    assert validate_review_summary(report, summary) == []


def test_archive_pcb_board_readings_are_legal_artifact_metadata():
    """``_archive_pcb`` writes ``{title, components, copperLayers}``, no file."""
    report = _report()
    report["evidence"]["channels"]["archivePcb"]["artifacts"] = [
        {"title": "Board1", "components": 12, "copperLayers": 2}
    ]
    summary = _filled(report)

    assert validate_review_summary(report, summary) == []


def test_container_issues_come_in_channel_order_and_do_not_mutate():
    report = _report()
    summary = _filled(report)
    channels = report["evidence"]["channels"]
    channels["liveSchematic"]["artifacts"] = "bad"
    channels["livePcb"]["errors"] = "bad"
    channels["datasheets"]["steps"] = "bad"
    report["evidence"]["liveCapture"]["captureFile"] = "bad"
    before = copy.deepcopy(report)

    first = validate_review_summary(report, summary)
    second = validate_review_summary(report, summary)

    assert first == second
    assert report == before  # the raw record is read, never repaired
    paths = [
        issue["path"] for issue in first if issue["code"].startswith("evidence-")
    ]
    assert paths == [
        "report.evidence.channels.liveSchematic.artifacts",
        "report.evidence.channels.livePcb.errors",
        "report.evidence.channels.datasheets.steps",
        "report.evidence.liveCapture.captureFile",
    ]


def test_broken_containers_do_not_break_the_derivations():
    """A named issue is not a crash: the shared algorithms still answer."""
    report = _report()
    summary = _filled(report)
    channels = report["evidence"]["channels"]
    channels["liveSchematic"]["artifacts"] = "bad"
    channels["archivePcb"]["artifacts"] = ["bad"]
    report["evidence"]["liveCapture"]["artifacts"] = "bad"
    report["evidence"]["liveCapture"]["captureFile"] = "bad"

    assert isinstance(evidence_coverage(channels), dict)
    assert isinstance(
        evidence_delivery(channels, report["evidence"]["liveCapture"]), dict
    )
    issues = validate_review_summary(report, summary)
    assert {
        "evidence-channel-field-not-list",
        "evidence-channel-artifact-not-dict",
        "evidence-live-capture-field-not-list",
        "evidence-live-capture-file-not-dict",
    } <= set(_codes(issues))
