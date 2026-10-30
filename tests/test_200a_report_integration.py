"""Tests for task 200A: the report reads 主机 DRC → 模块 → 器件, one device ledger.

E5's contract (`tasks/200a_report_integration.md`):

* **reading order** — `report.md` prints 主机 DRC, then 模块, then the device big
  section; `board_report`'s groups read 通用门票 → PCB 模块 → 器件, and severity
  only sorts **inside** one layer. The reading order is its own key: `WEIGHT_RANK`
  keeps its importance meaning (PCB 模块级 heaviest) and is not reused as an order.
* **one device ledger** — `unreviewed_parts[]`, `accepted_unknown[]` and
  `needs_datasheet[]` merge into one row per `(board, ref)`; the same designator on
  two boards stays two rows, and an empty source invents no row and no heading.
* **two products, one renderer** — `report.md` and `board-report.md` print the same
  device rows, byte for byte (`render_part_section`), in the same order.
* **compatibility** — `report.json` keeps its top-level keys, the three source
  arrays, findings/severity/verdict/exit code, and gains **no** parallel JSON part
  list.

Synthetic reports pin the rules; `ch340_golden.epro2` pins the real CLI product
(exit 3 / incomplete is the coverage conclusion, never a pass).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.checkup import (
    DEVICE_GROUP_NAME,
    PART_SECTION_TITLE,
    READING_RANK,
    WEIGHT_DEVICE,
    WEIGHT_GENERIC,
    WEIGHT_PCB_MODULE,
    board_report_section,
    merged_part_rows,
    reading_layer,
    render_board_report,
    render_part_section,
    render_report_markdown,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"
GOLDEN = FIXTURES / "ch340_golden.epro2"


def _finding(rule_id: str, *, severity: str = "INFO", refs=None, board="Board1",
             message="m") -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "level": "L1-pcb-geometry",
        "refs": list(refs or []),
        "board": board,
        "target": {"component_ref": (refs or [""])[0], "net_refs": []},
    }


def _channels(ok: bool = False) -> dict:
    return {
        "engineer": {"ok": ok, "detail": "工作区没有这颗料的 PDF"},
        "lcsc": {"ok": bool(ok), "detail": "库条目没有任何 datasheet 链接"},
        "official": {"ok": None, "detail": "AI 走", "suggestedQueries": []},
    }


def _placement(board: str, *, mpn: str = "", value: str = "") -> dict:
    return {"board": board, "mpn": mpn, "name": "", "value": value}


def _device_data_rows(text: str) -> list[str]:
    """The device ledger's data rows — the section only, header dropped.

    The section ends at the next `## ` heading: `report.md` prints the findings
    table right after it, and a slice to end-of-file would collect that one too.
    """
    start = text.index(f"## {PART_SECTION_TITLE}")
    tail = text[start:]
    end = tail.find("\n## ", 1)
    if end >= 0:
        tail = tail[:end]
    rows = [line for line in tail.splitlines() if line.startswith("| ")]
    return rows[1:]


def _report() -> dict:
    """Two boards, a gate finding, a module finding and a device finding."""
    return {
        "source": {},
        "model": {
            "boards": [
                {"uuid": "u1", "title": "Board1", "pages": ["p1"],
                 "components": 10, "nets": 5},
                {"uuid": "u2", "title": "Board2", "pages": ["p2"],
                 "components": 4, "nets": 2},
            ],
        },
        "pcb_review": {
            "boards": [
                {"title": "PCB1", "boardUuid": "u1", "components": 10,
                 "copperLayers": 2, "checksRun": []},
                {"title": "PCB2", "boardUuid": "u2", "components": 4,
                 "copperLayers": 2, "checksRun": []},
            ],
        },
        "modules": [],
        "summary": {"errorCount": 1, "warnCount": 0, "infoCount": 2,
                    "errors": [{"section": "findings", "source": "rules"}]},
        "completion": {"verdict": "incomplete", "verdictWhy": ["1 颗器件缺手册未审"],
                       "unreviewedParts": 1, "warningsPendingTriage": 0},
        "drc": {
            "schematic": {"checked": False, "reason": "no editor"},
            "pcb": {"checked": False, "reason": "no editor"},
            "ruleset": {"checked": False, "reason": "no editor"},
        },
        # Gate INFO, module WARN, device ERROR — a severity-first sort would print
        # them in exactly the opposite order, so this fixture discriminates the
        # reading key from the importance key.
        "findings": [
            _finding("conn-duplicate-designators", severity="INFO", refs=["U1"]),
            _finding("pcb-foc-gate-trace-width", severity="WARN", refs=["R1"],
                     board="PCB1"),
            _finding("pcb-footprint-consistency", severity="ERROR", refs=["C17"],
                     board="PCB1"),
        ],
        "unreviewed_parts": [
            {
                "designator": "U1",
                "mpn": "LM358",
                "supplier": "C7955",
                "reasons": ["无 MPN"],
                "missingFacts": ["vds"],
                "factsPresent": ["vin"],
                "channels": _channels(),
                "shelfMatchedBy": "",
                "boards": [_placement("Board1", mpn="LM358", value="LM358"),
                           _placement("Board2", mpn="LM2904", value="LM2904")],
            },
        ],
        "accepted_unknown": [
            {
                "part": "U9",
                "state": "accepted",
                "designator": "U9",
                "mpn": "",
                "supplier": "",
                "reasons": ["无 MPN"],
                "reason": "工程师接受这颗的未知",
                "who": "岳翔宇",
                "when": "2026-10-30",
                "board": "Board2",
                "stale": False,
                "boards": [_placement("Board2")],
            },
        ],
        "needs_datasheet": [
            {
                "part": "U1",
                "pins": [],
                "trigger": "facts",
                "reason": "无 MPN",
                "dependentFindings": ["conn-duplicate-designators@U1"],
                "factSeed": True,
                "mpn": "LM358",
                "supplier": "C7955",
                "missingFacts": ["vds"],
                "channels": _channels(),
                "shelfMatchedBy": "",
                "boards": [_placement("Board1", mpn="LM358", value="LM358"),
                           _placement("Board2", mpn="LM2904", value="LM2904")],
            },
            {
                "part": "Q3",
                "pins": ["gate"],
                "trigger": "marked",
                "reason": "读不懂这里怎么接",
                "dependentFindings": [],
                "boards": [],
            },
        ],
    }


# ---------------------------------------------------------------------------
# reading order is its own key — WEIGHT_RANK keeps its importance meaning
# ---------------------------------------------------------------------------


def test_reading_layer_is_independent_of_weight_rank():
    # Importance: PCB module > device > generic (unchanged).
    assert reading_layer(WEIGHT_PCB_MODULE) == "pcb-module"
    assert reading_layer(WEIGHT_DEVICE) == "device"
    assert reading_layer(WEIGHT_GENERIC) == "gate"
    # Reading: gate first, then module, then device — the opposite emphasis.
    assert READING_RANK["gate"] < READING_RANK["pcb-module"] < READING_RANK["device"]
    # The weight ranks are NOT the reading ranks (no hijack of the semantics):
    # the heaviest tier by importance is the middle one by reading order.
    assert READING_RANK["pcb-module"] != 0
    assert WEIGHT_PCB_MODULE == "pcb-module" and WEIGHT_DEVICE == "device"


def test_board_report_groups_read_gate_then_module_then_device():
    section = board_report_section(_report())
    groups = section["boards"][0]["groups"]
    layers = [group["reading"] for group in groups]
    # The device ERROR is the strongest finding of Board1; it still comes last,
    # after the gate INFO and the module WARN — severity sorts inside a layer only.
    assert layers == ["gate", "pcb-module", "device"], layers
    assert groups[-1]["name"] == DEVICE_GROUP_NAME
    assert [group["readingLabel"] for group in groups] == ["通用门票", "PCB 模块", "器件"]
    assert section["order"].startswith("阅读顺序：通用门票 → PCB 模块 → 器件")
    assert [entry["key"] for entry in section["readingOrder"]] == [
        "gate", "pcb-module", "device",
    ]
    # Importance is still published, unchanged: PCB module is rank 0 there.
    assert section["weights"][0]["key"] == WEIGHT_PCB_MODULE
    assert section["weights"][0]["rank"] == 0


def test_board_report_sorts_severity_inside_one_reading_layer():
    report = _report()
    report["findings"] = [
        _finding("conn-duplicate-designators", severity="INFO", refs=["U1"]),
        _finding("param-rc-cutoff", severity="ERROR", refs=["C1"]),
    ]
    groups = board_report_section(report)["boards"][0]["groups"]
    # Both are gate rows; the ERROR leads inside the layer.
    assert [group["name"] for group in groups] == ["元件参数/选型", "原理图连通性"]
    assert [group["findings"][0]["severity"] for group in groups] == ["ERROR", "INFO"]


# ---------------------------------------------------------------------------
# the device big section: one row per (board, ref)
# ---------------------------------------------------------------------------


def test_merged_rows_never_merge_one_designator_across_boards():
    rows = merged_part_rows(_report())
    u1 = [row for row in rows if row["ref"] == "U1"]
    assert len(u1) == 2, "同一位号在两块板上是两颗料，不合并"
    assert [row["board"] for row in u1] == ["Board1", "Board2"]
    assert [row["mpn"] for row in u1] == ["LM358", "LM2904"]
    # The needs_datasheet `facts` row is the SAME placement: merged, not a 3rd row.
    assert all(row["needs"] for row in u1)
    # First-seen order follows the model's board order; a row with no board
    # identity (the reviewer mark) comes after the boards the model names.
    assert [row["board"] for row in rows] == ["Board1", "Board2", "Board2", ""]


def test_merged_rows_keep_unreviewed_reason_acceptance_and_unknown_state():
    rows = {(row["board"], row["ref"]): row for row in merged_part_rows(_report())}
    board1_u1 = rows[("Board1", "U1")]
    assert board1_u1["reasons"] == ["无 MPN"]
    assert board1_u1["missingFacts"] == ["vds"]
    assert board1_u1["factsPresent"] == ["vin"]
    assert board1_u1["needs"][0]["dependentFindings"] == [
        "conn-duplicate-designators@U1",
    ]
    board2_u9 = rows[("Board2", "U9")]
    assert board2_u9["accepted"][0]["reason"] == "工程师接受这颗的未知"
    assert board2_u9["accepted"][0]["who"] == "岳翔宇"
    # A reviewer mark with no unreviewed row still gets its own row (no board).
    assert rows[("", "Q3")]["needs"][0]["trigger"] == "marked"


def test_merged_rows_invent_nothing_for_empty_sources():
    report = _report()
    report["unreviewed_parts"] = []
    report["accepted_unknown"] = []
    report["needs_datasheet"] = []
    assert merged_part_rows(report) == []
    text = render_part_section(report)
    # One heading, a sentence saying nothing is owed — no table, no fake rows.
    assert text.count(PART_SECTION_TITLE) == 1
    assert "| 板 |" not in text
    assert "无" in text


def test_the_empty_ledger_still_owes_the_exemption_trail():
    """192B's counterexample: three empty sources + one exempted part.

    The empty ledger may not invent a row, but a part the classifier declined to
    question is a fact about this run, so it must still be named — in `report.md`
    and in the section both products share.
    """
    report = _report()
    report["unreviewed_parts"] = []
    report["accepted_unknown"] = []
    report["needs_datasheet"] = []
    report["declaredPassiveExempt"] = [
        {"designator": "U4", "kind": "resistor", "basis": "metadata", "pins": 2}
    ]
    assert merged_part_rows(report) == []
    text = render_part_section(report)
    assert text.count(PART_SECTION_TITLE) == 1
    assert "| 板 |" not in text
    assert "无" in text
    assert "**声明为无源件、未按 IC 问手册的件（1）**" in text
    assert "`U4`" in text
    markdown = render_report_markdown(report)
    assert "**声明为无源件、未按 IC 问手册的件（1）**" in markdown
    assert "`U4`" in markdown


def test_render_part_section_prints_each_row_once_with_all_three_states():
    text = render_part_section(_report())
    assert text.startswith(f"## {PART_SECTION_TITLE}")
    # One table row per (board, ref): U1 twice (two boards) + U9 + Q3.
    data_rows = _device_data_rows(text)
    assert len(data_rows) == 4, data_rows
    assert sum(1 for line in data_rows if line.split("|")[2].strip() == "U1") == 2
    for needle in ("无 MPN", "工程师接受这颗的未知", "岳翔宇", "读不懂这里怎么接",
                   "vds", "conn-duplicate-designators@U1"):
        assert needle in text, needle


# ---------------------------------------------------------------------------
# two products, one renderer
# ---------------------------------------------------------------------------


def test_report_md_and_board_report_md_share_the_device_rows():
    report = _report()
    report["board_report"] = board_report_section(report)
    report_md = render_report_markdown(report)
    board_md = render_board_report(report)
    assert PART_SECTION_TITLE in report_md and PART_SECTION_TITLE in board_md

    assert _device_data_rows(report_md) == _device_data_rows(board_md)
    assert _device_data_rows(report_md), "the device ledger must have rows"
    # Each product prints the ledger once (no duplicated heading).
    assert report_md.count(f"## {PART_SECTION_TITLE}") == 1
    assert board_md.count(f"## {PART_SECTION_TITLE}") == 1


def test_report_md_reads_host_drc_then_modules_then_devices():
    report = _report()
    report["modules"] = [
        {"name": "FOC", "board": "Board1", "components": ["U1"], "basis": "page",
         "findings": []},
    ]
    report["board_report"] = board_report_section(report)
    text = render_report_markdown(report)
    drc_at = text.index("## 主机 DRC")
    module_at = text.index("## 模块")
    device_at = text.index(f"## {PART_SECTION_TITLE}")
    assert drc_at < module_at < device_at
    # The embedded board report does not print the device ledger a second time.
    assert text.index("## 整板报告") < drc_at


# ---------------------------------------------------------------------------
# compatibility: the JSON keeps its shape, no parallel part list
# ---------------------------------------------------------------------------


def test_json_keeps_the_three_arrays_and_gains_no_part_list():
    report = _report()
    section = board_report_section(report)
    assert "parts" not in section and "deviceRows" not in section
    assert set(report) >= {"unreviewed_parts", "accepted_unknown", "needs_datasheet"}
    # The board_report section is the same one the JSON has always carried: the
    # ledger adds no key of its own (it is rendered from the three arrays).
    assert set(section) == {
        "order", "weights", "note", "drc", "boards", "unassigned", "totals",
        "verdict", "readingOrder",
    }


# ---------------------------------------------------------------------------
# real CLI product
# ---------------------------------------------------------------------------


def test_cli_golden_writes_the_ordered_report_and_the_same_device_rows(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    code = cli.main([
        "checkup", "--file", str(GOLDEN), "--out", str(out), "--library", str(SHELF),
    ])
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    # Every source array is still there, and still the JSON's own.
    assert report["unreviewed_parts"]
    assert "accepted_unknown" in report and "needs_datasheet" in report
    assert code == report["summary"]["exitCode"] == 3
    assert report["completion"]["verdict"] == "incomplete"

    report_md = (out / "report.md").read_text(encoding="utf-8")
    board_md = (out / "board-report.md").read_text(encoding="utf-8")
    assert report_md.index("## 主机 DRC") < report_md.index("## 模块") \
        < report_md.index(f"## {PART_SECTION_TITLE}")
    assert PART_SECTION_TITLE in board_md

    assert _device_data_rows(report_md) == _device_data_rows(board_md)
    # One row per (board, ref) over the real product, too.
    seen = set()
    for line in _device_data_rows(report_md):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        key = (cells[0], cells[1])
        assert key not in seen, f"duplicate device row: {key}"
        seen.add(key)
