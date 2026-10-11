"""Tests for task 154: the integrated whole-board report (E 阶段收口棒 E4).

E 阶段的验收是「一键出整板报告（ERC+DRC+模块+器件）」，岳 2026-10-11 的体验反馈
是「机器账本身对人太啰嗦」——本棒把 ERC + DRC + 模块规则 + 器件规则合成一份，按
「板 → 模块/规则族」分组、按「严重度 × 模块权重」排序、每条一句话，最后一段回答
「整工程能不能投板」。

本文件按层钉：

* **词汇与分类**——`finding_weight`（三条权重档）与 `rule_family`（分组标签）是纯
  函数，先在这里钉死，一处改动在这里红，而不是在没人 diff 的报告里；
* **一句话摘要**——`finding_oneline`/`_first_sentence` 的位号/网/问题/依据四要素，
  以及「没有位号就写「未点名位号」而不是借一个」；
* **结论行**——`board_report_verdict` 读 `completion.verdict`（唯一权威闸）而不重算，
  缺手册/待分诊时**不许写「通过」**（口径对齐 `summary.mayClaimPassed`），无 completion
  节时退回窄义字段；
* **整合分组**——`board_report_section` 的板/模块/权重排序，PCB 文档经 `boardUuid`
  并到它对应的原理图板下（`PCB1` 的 finding 与 `Board1` 的 finding 同一节），不是
  两块板；
* **渲染**——`render_board_report` 的 Markdown 形状，以及它被印进 `report.md` 的
  **最前面**（`## 完成状态` 之前）；
* **真夹具锚点**——毕设FOC 1.0.0 / 1.1.0 与 ROBOT ctrl FOC 各跑一遍离线 checkup，
  钉 `board_report` 节、`board-report.md` 文件、以及三板上被验收时的那些数。

夹具一律只读。不连编辑器、不碰 daemon。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.checkup import (
    DEVICE_GROUP_NAME,
    SEVERITY_RANK,
    WEIGHT_DEVICE,
    WEIGHT_GENERIC,
    WEIGHT_PCB_MODULE,
    board_report_section,
    board_report_verdict,
    finding_oneline,
    finding_weight,
    render_board_report,
    render_report_markdown,
    rule_family,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"


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


def _finding(rule_id: str, *, severity: str = "INFO", refs=None, board="Board1",
             message="m", nets=None, level="L1-pcb-geometry") -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "level": level,
        "refs": list(refs or []),
        "board": board,
        "target": {"component_ref": (refs or [""])[0], "net_refs": list(nets or [])},
    }


def _synthetic_report() -> dict:
    """A two-board report, one PCB document each, with the shape the section reads."""
    findings = [
        # Board1 / PCB1: one module level, one device level, one schematic generic.
        _finding("pcb-foc-gate-trace-width", severity="WARN", refs=[], nets=["GHA"],
                 board="PCB1"),
        _finding("pcb-footprint-consistency", severity="ERROR", refs=["C17"],
                 board="PCB1", message="C17 封装尺寸码不符。"),
        _finding("conn-duplicate-designators", severity="ERROR", refs=["U1"],
                 board="Board1", message="U1 is duplicated."),
        # Board2 / PCB2: a device INFO only.
        _finding("pcb-derating-package", severity="INFO", refs=["R2"],
                 board="PCB2", message="R2 降额读数。"),
    ]
    return {
        "source": {},
        "model": {
            "boards": [
                {"uuid": "u1", "title": "Board1", "pages": ["p1"],
                 "components": 100, "nets": 50},
                {"uuid": "u2", "title": "Board2", "pages": ["p2"],
                 "components": 10, "nets": 5},
            ],
        },
        "pcb_review": {
            "boards": [
                {"title": "PCB1", "boardUuid": "u1", "components": 100,
                 "copperLayers": 4, "checksRun": []},
                {"title": "PCB2", "boardUuid": "u2", "components": 10,
                 "copperLayers": 2, "checksRun": []},
            ],
        },
        "modules": [
            {"name": "FOC", "board": "Board1", "components": ["C17", "U1"],
             "basis": "page", "findings": []},
            {"name": "M", "board": "Board2", "components": ["R2"],
             "basis": "page", "findings": []},
        ],
        "summary": {"errorCount": 2, "warnCount": 1, "infoCount": 1,
                    "errors": [{"section": "findings", "source": "rules"}] * 2},
        "completion": {"verdict": "incomplete", "verdictWhy": ["2 项 ERROR"],
                       "unreviewedParts": 0, "warningsPendingTriage": 0},
        "drc": {
            "schematic": {"checked": False, "reason": "no editor"},
            "pcb": {"checked": False, "reason": "no editor"},
            "ruleset": {"checked": False, "reason": "no editor"},
        },
        "findings": findings,
        "needs_datasheet": [],
    }


# ---------------------------------------------------------------------------
# vocabulary: the three weights and the family labels
# ---------------------------------------------------------------------------


def test_finding_weight_places_the_three_tiers():
    # 器件级 —— 第三步的四条规则（E1/E2/E3 落地）。
    for rule_id in (
        "pcb-footprint-consistency",
        "pcb-polarity-orientation",
        "pcb-silk-designator",
        "pcb-derating-package",
    ):
        assert finding_weight(rule_id) == WEIGHT_DEVICE
    # PCB 模块级 —— 第二步的模块规则包与通用层几何规则。
    for rule_id in ("pcb-foc-power-loop-area", "pcb-regulator-cap-distance",
                    "pcb-mcu-crystal-placement", "pcb-decap-distance",
                    "pcb-component-spacing", "pcb-track-ampacity",
                    "pcb-voltage-spacing"):
        assert finding_weight(rule_id) == WEIGHT_PCB_MODULE
    # 通用 —— 原理图侧，以及 PCB 侧属第一步的规则集元审查。
    for rule_id in ("conn-duplicate-designators", "decap-required-caps",
                    "param-rc-cutoff", "arch-nrst-closure",
                    "pcb-drc-ruleset-out-of-reference"):
        assert finding_weight(rule_id) == WEIGHT_GENERIC


def test_rule_family_labels_the_families_and_the_device_group():
    assert rule_family("pcb-foc-ground-tie") == "FOC/功率驱动"
    assert rule_family("pcb-regulator-fb-placement") == "电源调节器"
    assert rule_family("pcb-mcu-reset-boot") == "MCU 最小系统"
    assert rule_family("pcb-decap-distance") == "电源去耦"
    assert rule_family("pcb-component-spacing") == "DFM 通用"
    # 器件四条答 DEVICE_GROUP_NAME 先于模式表（它们的 id 也以 pcb- 开头）。
    for rule_id in ("pcb-footprint-consistency", "pcb-polarity-orientation",
                    "pcb-silk-designator", "pcb-derating-package"):
        assert rule_family(rule_id) == DEVICE_GROUP_NAME == "器件检查"
    assert rule_family("conn-duplicate-designators") == "原理图连通性"
    assert rule_family("some-unknown-rule") == "其他规则"


# ---------------------------------------------------------------------------
# the one-line summary
# ---------------------------------------------------------------------------


def test_finding_oneline_names_designator_net_problem_and_basis():
    finding = _finding(
        "pcb-voltage-spacing", severity="INFO", refs=["C17"], nets=["+24V"],
        message="net 'VCC' has no established voltage, so its spacing cannot be judged",
    )
    line = finding_oneline(finding)
    assert "C17" in line
    assert "网 +24V" in line
    assert "no established voltage" in line
    assert "安规间距（IPC-2221）" in line
    assert "pcb-voltage-spacing" in line
    # The board is the caller's heading, not part of the line.
    assert "Board1" not in line and "PCB1" not in line


def test_finding_oneline_says_unattributed_rather_than_borrowing_a_ref():
    line = finding_oneline(_finding("pcb-foc-gate-trace-width", refs=[], nets=["GHA"]))
    assert "（未点名位号）" in line
    assert "网 GHA" in line


def test_finding_oneline_cuts_to_the_first_sentence():
    long = _finding(
        "pcb-derating-package", refs=["R1"],
        message="第一句现象。第二句不该出现",
    )
    line = finding_oneline(long)
    assert "第一句现象。" in line
    assert "第二句" not in line
    # The English rules' own mark is "; " — also a cut point.
    english = _finding("conn-duplicate-designators", refs=["U1"],
                       message="U1 is duplicated; the model kept the first")
    assert "the model kept" not in finding_oneline(english)


# ---------------------------------------------------------------------------
# the closing verdict — read completion, never recompute it
# ---------------------------------------------------------------------------


def test_verdict_cannot_ship_when_errors_present():
    report = _synthetic_report()
    verdict = board_report_verdict(report)
    assert verdict["canShip"] is False
    assert "不能投板" in verdict["line"]
    assert verdict["completionVerdict"] == "incomplete"
    assert "不重算" in verdict["basis"]


def test_verdict_can_ship_only_when_completion_is_complete():
    report = _synthetic_report()
    report["summary"]["errorCount"] = 0
    report["summary"]["errors"] = []
    report["completion"] = {"verdict": "complete", "verdictWhy": []}
    verdict = board_report_verdict(report)
    assert verdict["canShip"] is True
    assert "可以投板" in verdict["line"]
    assert "complete" in verdict["line"]


def test_verdict_refuses_to_write_passed_with_unreviewed_or_untriaged():
    report = _synthetic_report()
    report["summary"]["errorCount"] = 0
    report["summary"]["errors"] = []
    report["completion"] = {
        "verdict": "incomplete",
        "verdictWhy": ["38 颗器件缺手册未审", "6 条 warning 待分诊"],
    }
    verdict = board_report_verdict(report)
    assert verdict["canShip"] is False
    assert "不能写「通过」" in verdict["line"]
    assert "缺手册" in verdict["line"]
    assert "待分诊" in verdict["line"]


def test_verdict_falls_back_to_the_narrow_field_without_a_completion_section():
    report = {
        "summary": {"errorCount": 0, "errors": [], "mayClaimPassed": False},
    }
    verdict = board_report_verdict(report)
    assert verdict["canShip"] is False
    assert "不能写「通过」" in verdict["line"]
    assert "窄义" in verdict["basis"]
    assert verdict["mayClaimPassed"] is False

    report["summary"]["mayClaimPassed"] = True
    verdict = board_report_verdict(report)
    assert verdict["canShip"] is True


# ---------------------------------------------------------------------------
# the integrated grouping
# ---------------------------------------------------------------------------


def test_board_report_merges_pcb_document_under_its_schematic_board():
    section = board_report_section(_synthetic_report())
    titles = [board["board"] for board in section["boards"]]
    assert titles == ["Board1", "Board2"]
    # The PCB document's title rides beside the schematic board's, not as a second
    # board of its own.
    assert section["boards"][0]["pcb"] == "PCB1"
    assert section["boards"][0]["copperLayers"] == 4
    # A PCB1 finding and a Board1 finding are in the same board section.
    rendered = render_board_report(_synthetic_report(), section)
    assert "### 板：Board1" in rendered
    assert "### 板：Board2" in rendered
    assert rendered.count("### 板：") == 2


def test_board_report_orders_groups_by_severity_then_weight():
    section = board_report_section(_synthetic_report())
    board_one = section["boards"][0]
    # Board1 holds: a module WARN, a device ERROR, a generic ERROR. Severity leads,
    # so the two ERROR-bearing groups come first; inside that tier the heavier
    # weight leads, so 器件检查 (device) precedes 原理图连通性 (generic).
    names = [group["name"] for group in board_one["groups"]]
    assert names[0] == DEVICE_GROUP_NAME
    assert names[1] == "原理图连通性"
    assert names[-1] == "FOC/功率驱动"
    severities = [
        min(SEVERITY_RANK.get(f["severity"].upper(), 9) for f in group["findings"])
        for group in board_one["groups"]
    ]
    assert severities == sorted(severities)
    # The device findings are one group named 器件检查.
    device = next(g for g in board_one["groups"] if g["weight"] == WEIGHT_DEVICE)
    assert device["name"] == DEVICE_GROUP_NAME
    assert device["counts"]["ERROR"] == 1


def test_board_report_carries_the_order_and_weights_in_the_head():
    section = board_report_section(_synthetic_report())
    assert section["weights"][0]["key"] == WEIGHT_PCB_MODULE
    assert section["weights"][0]["rank"] == 0
    assert "重中之重" in section["weights"][0]["why"]
    assert "权重" in section["order"]
    rendered = render_board_report(_synthetic_report(), section)
    assert "排序依据" in rendered
    assert "PCB 模块级" in rendered


def test_board_report_totals_and_drc_baseline_are_read_not_recomputed():
    section = board_report_section(_synthetic_report())
    assert section["totals"] == {"ERROR": 2, "WARN": 1, "INFO": 1}
    assert section["drc"]["erc"]["checked"] is False
    assert "no editor" in section["drc"]["pcb"]["summary"]


# ---------------------------------------------------------------------------
# rendering: the section leads report.md and stands on its own
# ---------------------------------------------------------------------------


def test_board_report_synthesizes_one_board_when_there_is_no_partition():
    """A plain `.enet` has no `model.boards`: still one board, still grouped."""
    report = {
        "model": {"components": 3},
        "source": {"file": "x.enet"},
        "findings": [_finding("param-rc-cutoff", refs=["R1"], board="")],
        "modules": [],
        "summary": {},
        "drc": {},
    }
    section = board_report_section(report)
    assert len(section["boards"]) == 1
    assert section["boards"][0]["pcb"] == ""
    assert section["boards"][0]["groups"]  # grouped by family, not unattributed
    assert section["unassigned"] == []
    assert "### 板：x.enet" in render_board_report(report, section)


def test_write_checkup_report_refreshes_the_integrated_section(tmp_path):
    """The re-gate commands mutate `completion`; the stored section must follow."""
    from boardwise.cli import _write_checkup_report

    report = _synthetic_report()
    report["board_report"] = {"stale": True}
    _write_checkup_report(tmp_path, report)
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert "stale" not in written["board_report"]
    assert written["board_report"]["verdict"]["canShip"] is False


def test_render_report_markdown_puts_the_integrated_report_first():
    report = _synthetic_report()
    report["board_report"] = board_report_section(report)
    text = render_report_markdown(report)
    assert "## 整板报告（一键：ERC + DRC + 模块 + 器件）" in text
    assert text.index("## 整板报告") < text.index("## 完成状态（completion）")


def test_render_board_report_renders_only_what_the_section_says():
    section = board_report_section(_synthetic_report())
    previous = board_report_section(_synthetic_report())
    # Two sections from the same report render byte-for-byte alike (deterministic).
    assert render_board_report(_synthetic_report(), section) == render_board_report(
        _synthetic_report(), previous
    )
    text = render_board_report(_synthetic_report(), section)
    assert text.startswith("## 整板报告")
    assert "### 板：Board1" in text
    assert "### 板：Board2" in text


# ---------------------------------------------------------------------------
# real fixtures — the three acceptance boards
# ---------------------------------------------------------------------------


def test_checkup_writes_the_integrated_report_for_foc_1_1_0(tmp_path, monkeypatch, capsys):
    report = _run_checkup(tmp_path, monkeypatch, FOC_110, "foc110")
    capsys.readouterr()
    assert "board_report" in report
    section = report["board_report"]
    # Three schematic boards, each with its PCB document merged in, in model order.
    assert [b["board"] for b in section["boards"]] == ["Board1", "Board2", "Board3"]
    assert [b["pcb"] for b in section["boards"]] == ["PCB1", "PCB2", "PCB3"]
    # The 1.0.0 wall-clock anchor: 毕设FOC 1.1.0 carries 50 ERROR.
    assert section["totals"]["ERROR"] == 50
    assert section["verdict"]["canShip"] is False
    # Every board has a 器件检查 group (E1/E2/E3 rules ran on each document).
    for board in section["boards"]:
        assert any(g["name"] == DEVICE_GROUP_NAME for g in board["groups"])
    # The standalone file exists and leads with the same section.
    board_md = (tmp_path / "foc110" / "board-report.md").read_text(encoding="utf-8")
    assert board_md.startswith("## 整板报告")
    assert "### 整工程能不能投板" in board_md


def test_checkup_integrated_report_carries_the_footprint_errors_on_foc_1_0_0(
    tmp_path, monkeypatch, capsys
):
    report = _run_checkup(tmp_path, monkeypatch, FOC_100, "foc100")
    capsys.readouterr()
    section = report["board_report"]
    board_one = section["boards"][0]
    assert board_one["board"] == "Board1" and board_one["pcb"] == "PCB1"
    device = next(g for g in board_one["groups"] if g["name"] == DEVICE_GROUP_NAME)
    footprint = [f for f in device["findings"]
                 if f["rule_id"] == "pcb-footprint-consistency"
                 and f["severity"] == "ERROR"]
    # E1's measured 1.0.0 catch: six 0805 parts placed on 0603 pads, as ERROR.
    assert len(footprint) == 6
    assert all(f["severity"] == "ERROR" for f in footprint)
    assert {"C17", "C8", "C98", "C99", "U3", "U7"} <= {
        ref for f in footprint for ref in f["refs"]
    }
    assert section["verdict"]["canShip"] is False
    assert "13 项 ERROR" in section["verdict"]["line"]


def test_checkup_integrated_report_refuses_passed_without_datasheets_on_robot(
    tmp_path, monkeypatch, capsys
):
    report = _run_checkup(tmp_path, monkeypatch, ROBOT, "robot")
    capsys.readouterr()
    section = report["board_report"]
    # ROBOT has no ERROR, but 38 unreviewed parts and 6 untriaged warnings — the
    # line must not say 「通过」.
    assert section["totals"]["ERROR"] == 0
    assert section["verdict"]["canShip"] is False
    assert "不能写「通过」" in section["verdict"]["line"]
    assert "缺手册" in section["verdict"]["line"]
    assert "待分诊" in section["verdict"]["line"]
