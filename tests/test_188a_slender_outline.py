"""188a §4 — 极细长板框**只披露、不拒收**（187A 遗留 ①）。

187A 的 H1 只拦三种退化（零面积、平轴、重复顶点），留下的形状是「回程错开 0.9 mil
的 2000 mil 环」：它闭合成环、面积非零（900 mil²）、角点也够，于是照旧当板框量——
而 0.9 mil 的厚度正是拼合误差本身，量出来的「出板框」是拿错框的结果。要不要**拒收**
这种环是判定语义（窄板/细条灯板真存在，阈值取错会把合法板框判没），任务书给的判据
是**披露**：bbox 细长比超过 :data:`OUTLINE_SLENDER_ASPECT_RATIO`（20:1）时，报告在
``outlineNote`` 上加一句 INFO 请人工核对，板框照用、规则照跑。

合成板复用 ``test_183_bug98b_capsule_outline`` 的 ``.epru`` 文本构造器（同目录跨
import 是本仓既有做法）；没有任何真实工程容器进 fixtures（R4）。
"""

from __future__ import annotations

import pytest

import test_183_bug98b_capsule_outline as t183
from boardwise.engines.pcbreview import (
    OUTLINE_SLENDER_ASPECT_RATIO,
    _board_entry,
)
from boardwise.parsers.epru import parse_epru_text
from boardwise.rules.pcb.distance import BoardOffEdge
from boardwise.rules.pcb.base import PcbReviewContext

OFF_BOARD_RULE_ID = "pcb-component-off-board"
SLENDER = "板框极细长"


def _rect(width: float, height: float) -> list:
    points = [
        (0.0, 0.0), (width, 0.0), (width, -height), (0.0, -height), (0.0, 0.0),
    ]
    return t183.closed_ring_path(points)


def _board(rings: list[list], parts: list[tuple[str, float, float]] = ()):
    lines = [
        t183._line("DOCHEAD", "h_pcb", {
            "docType": "PCB", "uuid": "pcb1", "editVersion": "3.2.186",
        }),
    ]
    for index, ring in enumerate(rings):
        lines.append(t183._line("POLY", f"outline{index}", {
            "polyType": "BOARD_OUTLINE", "layerId": 11, "netName": "",
            "width": 10.0, "path": ring,
        }))
    for index, (designator, x, y) in enumerate(parts):
        lines += t183._component(f"c{index}", x, y, designator)
    return parse_epru_text("\n".join(lines))


def _note(board) -> str:
    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[]
    )
    return str(entry.get("outlineNote", ""))


def _off_board(board):
    return BoardOffEdge().check(PcbReviewContext(board=board))


def test_the_degenerate_ring_187a_left_standing_is_disclosed():
    """2000 x 0.9 mil 的环：板框**照用**，报告多一句人工核。

    修前（187A 之后）：这条环在报告里完全不提，量出来的 5 条「出板框」被当成真
    ERROR。修后：板框还在（``outline`` 非 None、规则照跑），只多一句披露——「拒收」
    不是本批的答案（细条灯板真存在），「不吭声」也不是。
    """
    board = _board([_rect(2000.0, 0.9)], parts=[("R1", 1000.0, -0.45)])
    assert board.outline is not None, "披露不是拒收：板框仍在"
    assert board.outline.closed is True
    # 2222:1 —— 任务书点名的那个数。
    assert _note(board) == f"{SLENDER}（2222:1）——细长板/拼板请人工确认拼合正确"
    # 规则照跑（这条环仍然被用来量），没有因为「细长」被抑制。
    findings = _off_board(board)
    assert all(
        finding.rule_id != OFF_BOARD_RULE_ID or finding.severity == "ERROR"
        for finding in findings
    ), findings


def test_the_threshold_is_20_and_sits_between_strip_boards_and_degenerate_rings():
    """20:1 的边界：真板与细条灯板不进，退化形态进。

    实板对照写在 ``OUTLINE_SLENDER_ASPECT_RATIO`` 的注释里：真板 1:1–4:1，细条
    灯板/拼条 10–20:1，2000 x 0.9 的退化环 2222:1。边界两侧各取一例（2000/99 =
    20.2:1 进，2000/101 = 19.8:1 不进）。
    """
    assert OUTLINE_SLENDER_ASPECT_RATIO == 20.0
    assert SLENDER not in _note(_board([_rect(2000.0, 1200.0)])), "真板 1.7:1"
    assert SLENDER not in _note(_board([_rect(2000.0, 500.0)])), "4:1"
    assert SLENDER not in _note(_board([_rect(2000.0, 101.0)])), "19.8:1 仍在阈值下"
    assert SLENDER in _note(_board([_rect(2000.0, 99.0)])), "20.2:1 越界"
    assert SLENDER in _note(_board([_rect(2000.0, 80.0)])), "25:1 的细条"
    # 正好 20:1 不披露（判据是 **超过** 20）。
    assert SLENDER not in _note(_board([_rect(2000.0, 100.0)])), "正好 20:1"


def test_the_disclosure_rides_last_and_does_not_replace_the_other_notes():
    """细长披露与别的 ``outlineNote`` 句并存，排在最后。

    板上有「完整板框 + 多余闭环（内槽/拼板）」时报告要说两件事（187A M2 的照跑
    披露 + 本批的细长披露）——两句都要在，且细长那句是对同一个环的形状补充说明，
    排在读数来源那几句之后。
    """
    board = _board(
        [_rect(2000.0, 80.0), t183.closed_ring_path([(300.0, -20.0), (400.0, -20.0), (400.0, -60.0), (300.0, -60.0), (300.0, -20.0)])]
    )
    note = _note(board)
    assert "多余记录未入环" in note, note
    assert SLENDER in note, note
    assert note.endswith("细长板/拼板请人工确认拼合正确"), note


def test_a_frame_that_did_not_read_is_not_given_the_slender_note():
    """没有环就没有这句话：未闭环/拼合失败走「没跑，不是全过」那几句。

    细长比是对**拿到的那一环**说的；环不在（或没闭合、退化到量不了）时报告说的事
    不一样，两者不许混在一份报告里（否则读者会以为量过一个不存在的框）。
    """
    board = _board([t183.closed_ring_path([(0.0, 0.0), (2000.0, 0.0)])])
    assert board.outline is not None and board.outline.closed is False
    note = _note(board)
    assert SLENDER not in note, note
    assert "板框未闭环" in note and "未运行" in note, note
    # 拼合失败（没有环）那一档同样没有这句话。
    failed = _board([
        t183.closed_ring_path([(0.0, 0.0), (600.0, 0.0), (600.0, -0.9)]),
        t183.closed_ring_path([(2000.0, 0.0), (2600.0, 0.0), (2600.0, -0.9)]),
    ])
    assert failed.outline is None
    assert SLENDER not in _note(failed), _note(failed)
