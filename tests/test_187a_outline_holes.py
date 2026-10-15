"""187A —— 183 系三洞的收口：退化环、静默丢弃、护栏误吞。

183 的挖洞报告（agent-341，探针留在 ``C:\\Users\\xiangyu\\.tmp_hole183\\``）指了
三处，都是 **bug98-B 新读法自己带出来的**，本文件逐条钉住：

* **H1 退化环缺形状不变量**。描边中心线拼合这条路（``_capsule_frame``）和
  bug98-A 的开放折线拼合那条路，只要端点接得上就认成环——「出去再原路折回」
  的三段线中心线是 ``(0,0) -> (2000,0) -> (1000,0)``，shoelace 恰好 0，闭合、
  ``stitched=True``、面积为零，于是整板器件都「在板框外」，98 条那个假 ERROR
  风暴从新读法原路回来（probe3 / probe11）。现在两条路都过同一道形状不变量，
  不合就 ``outline=None`` + ``fragments=len(segments)``，走「板框没读出」的披露。
* **M1 fragments 静默丢弃**。capsule 分支把 ``fragments`` 写死 0，而
  ``if len(points) >= 3`` 这条把不合法记录悄悄扔掉：16 段描边 + 1 条畸形
  ``R`` 记录的报告说「17 段全部入环」（probe2 的 A 档），是谎话。现在
  ``fragments`` 实算、``_capsule_note`` 用实际入环段数，``入环段数 + fragments
  == 段数`` 这条不变量对随机段集合成立。
* **M2 护栏一刀切**。``BoardOutline.stitched is False`` 就抑制，把「完整板框 +
  多余闭合记录（内槽/拼板）」也吞了：外框矩形环 + 内槽小环 + 真出板 220 mil 的
  器件，修前只出 1 条 WARN、真 ERROR 消失（probe11 第二档）。现在解析器把
  「拿到的那一环是什么」摆在 ``fragment_kind`` 上（``stroke_piece`` = 描边碎片）
  ，规则只对这一档抑制，``extra_records`` 照跑并披露（bug98-A 的 max perimeter
  读法保留）。
* **M3 焊缝披露**：描边中心线的接缝**天生**不逐字相等（实板 16 处 0.001..0.011
  mil），所以枚举它们只说废话；0.05 mil 以上的错位才计，报告那行照旧印。

板的合成本文件复用 ``test_183_bug98b_capsule_outline`` 的 16 段描边夹具与
``_parse`` / ``board_text`` 构造器（同目录跨 import 是本仓既有做法），另加
bug98-A 那侧的开放折线形状。没有任何真实工程容器进 fixtures（R4）。
"""

from __future__ import annotations

import random

import pytest

import test_183_bug98b_capsule_outline as t183
from boardwise.core.geometry import BoardOutline, Point
from boardwise.engines.pcbreview import _board_entry
from boardwise.parsers.epru import (
    OUTLINE_CAPSULE_WELD_FLOOR_MIL,
    _is_board_shaped_ring,
    _stitch_outline,
)

#: 描述符串字面量——规则与解析器共用同一套词，改名就必须两边一起改，所以钉住。
STROKE_PIECE = "stroke_piece"
EXTRA_RECORDS = "extra_records"


def _entry(board) -> dict:
    return _board_entry(title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[])


def _note(board) -> str:
    return str(_entry(board).get("outlineNote", ""))


def _path(raw) -> tuple:
    return ("path", raw)


# ---------------------------------------------------------------------------
# H1：退化环不是板框（两条拼合路径都要拦）
# ---------------------------------------------------------------------------


def test_the_shape_invariant_refuses_the_three_degenerate_rings():
    """形状不变量本身：零面积、平轴、重复顶点——三种退化都答 False。

    「重复顶点」是**逐字相等**才算：1 mil 的拼合容差会在焊接时吞掉那半个 mil
    的错位，不会在环里留下一个零长边；所以这条只抓文件里真写了两遍的顶点，
    不会误伤任何真板框。
    """
    assert not _is_board_shaped_ring(
        [Point(0.0, 0.0), Point(2000.0, 0.0), Point(1000.0, 0.0)]
    ), "出去再原路折回：|shoelace| 恰好 0"
    assert not _is_board_shaped_ring(
        [Point(0.0, 0.0), Point(2000.0, 0.0), Point(0.0, 0.0)]
    ), "重复顶点 + 平轴"
    assert not _is_board_shaped_ring([Point(0.0, 0.0), Point(10.0, 0.0)]), "两个点不是环"
    assert not _is_board_shaped_ring([Point(0.0, 0.0), Point(10.0, 0.0), Point(10.0, 0.0)]), "零长边"
    square = [Point(0.0, 0.0), Point(500.0, 0.0), Point(500.0, -500.0), Point(0.0, -500.0)]
    assert _is_board_shaped_ring(square)


def test_a_stroked_out_and_back_frame_is_not_a_board():
    """probe3：三段描边「出去再原路折回」，中心线面积 0。

    修前：``stitched=True``、``fragments=0``、报告说「3 段全部入环」，而 5 颗
    器件（y=-300..-900）全部落在 y=0 这条线上 → 5 条假 ERROR。修后走「拼合
    失败」披露：``outline=None``、``fragments=3``、规则一条不出。
    """
    back = [
        ("line", (0.0, 0.0), (2000.0, 0.0)),
        ("line", (2000.0, 0.0), (1000.0, 0.0)),
        ("line", (1000.0, 0.0), (0.0, 0.0)),
    ]
    board = t183._parse(pieces=back)
    assert board.outline is None, "零面积环不许当板框（H1）"
    assert board.outline_fragments == 3
    assert t183._off_board(board) == []
    note = _note(board)
    assert "未运行" in note and "没跑" in note, note


def test_open_polylines_that_stitch_into_a_collinear_loop_are_not_a_board():
    """probe11 第一档：三条**开放**折线在 bug98-A 那条路上拼出同一个共线环。

    两条拼合路径都要过不变量——只堵 capsule 那条，开放折线这条会照样把
    ``{(0,0),(2000,0),(1000,0)}`` 交给「出板框」并淹出 5 条假 ERROR。
    """
    board = t183._parse(
        pieces=[
            _path([0.0, 0.0, "L", 2000.0, 0.0]),
            _path([2000.0, 0.0, "L", 1000.0, 0.0]),
            _path([1000.0, 0.0, "L", 0.0, 0.0]),
        ]
    )
    assert board.outline is None
    assert board.outline_fragments == 3
    assert t183._off_board(board) == []


def test_a_two_piece_out_and_back_never_reads_as_a_stitched_frame():
    """两段的「出去再回来」：修前是一环 2 点 + ``stitched=True``，现在是 None。

    2 点环连角点都不够，本来就被 ``MIN_OUTLINE_CORNERS`` 挡住不出结论；但它
    曾经以「拼合成功」的名义进报告（probe3 的 D 档）。
    """
    board = t183._parse(
        pieces=[
            ("line", (0.0, 0.0), (2000.0, 0.0)),
            ("line", (2000.0, 0.0), (0.0, 0.0)),
        ]
    )
    assert board.outline is None
    assert board.outline_fragments == 2


def test_the_good_frame_still_has_a_shape():
    """反向锚：真板框照样过不变量——16 段描边仍拼成 2000x1200 的环。"""
    outline = t183._parse().outline
    assert outline is not None and outline.stitched is True
    box = outline.bbox
    assert box is not None and box.max_x - box.min_x > 1900.0 and box.max_y - box.min_y > 1100.0


# ---------------------------------------------------------------------------
# M1：fragments 实算，入环段数 + fragments == 段数
# ---------------------------------------------------------------------------


def _used_records(outline) -> int:
    """解析器明说的**入环段数**：None→0；拼合环→note 开头的那个数；一环→1。

    note 的契约（「N 段描边板框…N 段全部入环」）由 test_183 钉着，这里读它只是
    把「入环段数」从报告里取回来做对账，不是规则在解析字符串。
    """
    if outline is None:
        return 0
    if not outline.stitched:
        return 1
    head = outline.note.split(" ", 1)[0]
    assert head.isdigit(), f"拼合环必须说清入环段数：{outline.note!r}"
    return int(head)


def test_a_dropped_closed_record_is_counted_not_silently_zero():
    """probe2 A：16 段描边 + 1 条畸形 ``R`` 记录（点数 < 3，静默丢弃的那条）。

    修前：``fragments=0``、note 说「17 段全部入环」——两个数都是假的。修后
    ``fragments=1``、note 说 16 段入环，报告再补一句「另有 1 段未入环…照跑」。
    """
    board = t183._parse(pieces=t183._PIECES + [_path(["R", 100.0, -100.0])])
    outline = board.outline
    assert outline is not None and outline.stitched is True
    assert outline.segments == 17
    assert board.outline_fragments == 1
    assert "16 段全部入环" in outline.note, outline.note
    assert "17 段全部入环" not in outline.note
    note = _note(board)
    assert "未入环" in note and "照跑" in note, note
    assert t183._off_board(board) == [], "板框本身仍是那 16 段拼出来的真框"


@pytest.mark.parametrize("seed", range(6))
def test_used_records_plus_fragments_is_the_segment_count(seed):
    """不变量：**入环段数 + fragments == 段数**，对随机段集合成立。

    段集合 = 16 段描边夹具 + 随机 1..4 条杂记录，杂记录从四种「曾经被静默
    丢掉或被硬编码 0 吃掉」的形状里抽：畸形 ``R``、2 点自闭环、2 点开放折线、
    200x200 的整环小方框（拼板/内槽那种多余闭环）。三档归口都要闭幕：

    * ``outline is None`` → 一条没入环，``fragments`` 必须是段数本身；
    * 拼合环（capsule）→ note 明说入环几段；
    * 只认一环（fallback）→ 赢家是**一条**记录自己的环。
    """
    vocabulary = [
        ["R", 100.0, -100.0],
        [10.0, -10.0, "L", 10.0, -10.0],
        [500.0, -1100.0, "L", 1500.0, -1100.0],
        t183.closed_ring_path(
            [(900.0, -500.0), (1100.0, -500.0), (1100.0, -700.0), (900.0, -700.0), (900.0, -500.0)]
        ),
    ]
    rng = random.Random(seed)
    for _ in range(8):
        extra = [rng.choice(vocabulary) for _ in range(rng.randint(1, 4))]
        records = [_path(t183.piece_path(piece)) for piece in t183._PIECES] + [
            _path(raw) for raw in extra
        ]
        total = len(records)
        board = t183._parse(pieces=records)
        outline = board.outline
        fragments = board.outline_fragments
        assert 0 <= fragments <= total
        assert _used_records(outline) + fragments == total, (
            f"入环段数 + fragments 必须等于段数（total={total}）"
        )
        if outline is not None:
            assert outline.segments == total


# ---------------------------------------------------------------------------
# M2：护栏只对「描边碎片」抑制
# ---------------------------------------------------------------------------


def _cutout_board(off_board: bool = True):
    """外框矩形环（完整板框）+ 内槽小环（多余闭合记录）——probe11 第二档。"""
    outer = t183.closed_ring_path(
        [(0.0, 0.0), (2000.0, 0.0), (2000.0, -1200.0), (0.0, -1200.0), (0.0, 0.0)]
    )
    slot = t183.closed_ring_path(
        [(800.0, -500.0), (1200.0, -500.0), (1200.0, -700.0), (800.0, -700.0), (800.0, -500.0)]
    )
    return t183._parse(pieces=[_path(outer), _path(slot)], off_board=off_board)


def test_a_complete_frame_with_an_inner_slot_keeps_reporting_off_board_parts():
    """修前：1 条 WARN、真 ERROR 被吞（``stitched is False`` 一刀切）。

    外框是完整的闭环（max perimeter 拿到的就是它），内槽只是**多余记录**；
    器件 RZ 真的在 2200（越界 220 mil）——这句必须出得来。
    """
    board = _cutout_board(off_board=True)
    outline = board.outline
    assert outline is not None and outline.stitched is False
    assert outline.fragment_kind == EXTRA_RECORDS
    assert board.outline_fragments == 1

    findings = t183._off_board(board)
    assert [finding.severity for finding in findings] == ["ERROR"]
    assert findings[0].target is not None
    assert findings[0].target.component_ref == "RZ"
    assert findings[0].target.measurement == {"kind": "distance", "value": 220.0, "unit": "mil"}

    note = _note(board)
    assert "照跑" in note and "抑制" not in note, note


def test_the_inner_slot_alone_files_nothing_when_every_part_is_inside():
    """同一块板、器件全在内：照跑但零 ERROR——披露与判定互不冒充。"""
    board = _cutout_board(off_board=False)
    assert t183._off_board(board) == []
    note = _note(board)
    assert "照跑" in note and "未入环" in note, note


def _poisoned_stroke_board():
    """183 的碎片案：16 段描边里一段是三条腿的畸形描边 → capsule 读法弃权。"""
    pieces = t183._PIECES[:]
    pieces[9] = _path(t183.y_stroke_path((1000.0, -600.0), 100.0))
    return t183._parse(pieces=pieces)


def test_a_stroke_frame_that_fails_to_join_is_still_suppressed():
    """真碎片的判据是「赢家那一环自己是描边」——这条仍是 1 条 WARN、不出 ERROR。

    修前抑制得对，但理由（``stitched is False``）会把内槽那种完整板框一起吞；
    现在判据收在 ``fragment_kind == "stroke_piece"`` 上，这条案子的答案不变。
    """
    board = _poisoned_stroke_board()
    outline = board.outline
    assert outline is not None and outline.stitched is False
    assert outline.fragment_kind == STROKE_PIECE

    findings = t183._off_board(board)
    assert [finding.severity for finding in findings] == ["WARN"]
    assert findings[0].target is None
    assert "拼合失败" in findings[0].message and "抑制" in findings[0].message

    note = _note(board)
    assert "抑制" in note and "没跑" in note and "照跑" not in note, note


def test_a_stroked_frame_with_a_stray_closed_record_is_still_a_piece():
    """描边框旁边多一个**完整闭环**记录：赢家仍是描边 → 仍按碎片抑制。

    这是判据刻意比「全部记录都可读成描边」更严的一档：那个半径 100 的小方框
    本身不是描边（四条边近似等长，``_capsule_centerline`` 答 None），但拿到手的
    环是不是**描边**才是「这是不是碎片」的直接证据——描边框没拼成时拿到的额
    外记录不该把 15 条假 ERROR 放出来。
    """
    stray = t183.closed_ring_path(
        [(900.0, -500.0), (1000.0, -500.0), (1000.0, -600.0), (900.0, -600.0), (900.0, -500.0)]
    )
    board = t183._parse(pieces=t183._PIECES + [_path(stray)])
    outline = board.outline
    assert outline is not None and outline.fragment_kind == STROKE_PIECE
    assert [finding.severity for finding in t183._off_board(board)] == ["WARN"]


def test_an_outline_without_the_new_field_asks_no_question():
    """手搓/反序列化出来的 ``BoardOutline`` 不带 ``fragment_kind``：不抑制。

    旧字段（``stitched``）单独出现时说明不了「那一环是什么」，规则照跑——这是
    与 bug98-B 之前同一个答案，护栏的收窄不靠猜。
    """
    outline = BoardOutline(
        points=[Point(0.0, 0.0), Point(10.0, 0.0), Point(10.0, -10.0), Point(0.0, -10.0)],
        source_id="x",
        segments=16,
        closed=True,
        stitched=False,
    )
    assert outline.fragment_kind is None
    board = t183._parse()
    board.outline = outline
    board.outline_fragments = 15
    findings = t183._off_board(board)
    assert len(findings) == 5, "没有碎片证据时按所选闭环照跑（5 颗器件在空环外）"
    assert all(finding.severity == "ERROR" for finding in findings)


# ---------------------------------------------------------------------------
# M3：描边接缝只在超过地板值时才算焊缝
# ---------------------------------------------------------------------------


def test_the_capsule_weld_floor_is_a_stated_number():
    """0.05 mil：实板 16 处接缝是 0.001..0.011（五个数量级之上留足余量）。"""
    assert OUTLINE_CAPSULE_WELD_FLOOR_MIL == 0.05


def test_the_natural_capsule_seams_are_not_welds():
    """好板框的接缝是中心线读法**天生**带出来的，不该报成 15 处焊接风险。"""
    board = t183._parse()
    assert board.outline is not None and board.outline.tolerance_welds == 0
    assert "容差焊缝" not in _note(board)


def test_a_mislocated_piece_shows_up_as_a_weld():
    """一段整体错位 0.9 mil：两端接缝都超地板值 → 2 处，报告点名人工核。"""
    pieces = t183._PIECES[:]
    piece = pieces[9]
    pieces[9] = ("line", (piece[1][0] + 0.9, piece[1][1]), (piece[2][0] + 0.9, piece[2][1]))
    board = t183._parse(pieces=pieces)
    outline = board.outline
    assert outline is not None and outline.stitched is True
    assert outline.tolerance_welds == 2
    note = _note(board)
    assert "容差焊缝" in note and "2" in note, note


def test_a_doubled_piece_record_is_counted_not_dropped():
    """同一条描边重复写两遍：描边读法一律弃权（有记录没入环），计数必须是真的。

    重复件与原件端点逐字相同，于是 capsule 读法**不是**「全部记录都进了环」而
    拒绝整条路（``used != len(lines)``，bug98-B 既有行为：一条读不准就整条不认），
    回到 bug98-A 的 max perimeter，拿到一段描边 → 仍按碎片抑制。要点是
    ``fragments`` 实算 16、而不是从前那个写死的 0。
    """
    board = t183._parse(pieces=t183._PIECES + [t183._PIECES[9]])
    outline = board.outline
    assert outline is not None and outline.stitched is False
    assert outline.fragment_kind == STROKE_PIECE
    assert outline.segments == 17
    assert board.outline_fragments == 16
    assert _used_records(outline) + board.outline_fragments == 17
    assert [finding.severity for finding in t183._off_board(board)] == ["WARN"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
