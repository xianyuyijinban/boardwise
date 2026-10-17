"""190S 底层丝印文字的延伸方向：真机定标 → 离线口径。

**定标**（编辑器 3.2.186，2026-10-17，`pcb.place_component` 放下、`pcb.geometry
--bboxIds` 逐 id 量宿主自己的 ink 盒、`sys.get_document_source` 读该条 ATTR 记录）：
顶层记录的盒子=原样沿 ``angle`` 方向从锚点伸出；**底层记录是同一只盒子按 x 镜像**
（锚点在板坐标里，方向角是「底层视图角」）。12 次放置（{顶,底} × {0°,90°,180°,270°}
各一颗 0603，再补 4 颗底层做第二个样本）全部落在同一条规律上，见 ``A_TABLE``。

这条规律要同时解释夹具上的两个极端：实板A 的 29 条底层位号（记录角全是 0°）
**29/29** 需要文字朝记录角的 ``-u`` 走；毕设FOC 的 3 条（记录角全是 90°）**0/3**。
镜像帧给出的正是这两个数（0°→-u、90°→+u），而「一律 +u」的老模型一个都对不上。

本文件钉三件事：①``corners()`` 复现 A 表那 12 只盒子；②两面之差就是 x 取反；
③实板A 在场时，标定后的盒子不再报「R22 压 EC3」（老模型恰好报这一条）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from boardwise.core.geometry import SilkText
from boardwise.parsers.epru import parse_epro2
from boardwise.rules.pcb.silk import (
    DEFAULT_ADVANCE,
    FACE_OF_SILK,
    box_overlaps,
    text_box,
)

#: 实板A（企业归档，只读；本仓库只以「实板A」称呼它，绝不写它的文件名/型号）。
#: **按位置找，不按名字**：`.tmp_bug98b/` 里那一份 `.epro2`；不在场就跳过那两条。
def _field_board() -> Path | None:
    directory = Path(__file__).resolve().parents[1] / ".tmp_bug98b"
    if not directory.is_dir():
        return None
    boards = sorted(directory.glob("*.epro2"))
    return boards[0] if len(boards) == 1 else None


REAL_BOARD = _field_board()

#: A 表：12 次真机放置的原始读数。``box`` 是宿主 ``pcb.geometry`` 给的轴对齐 ink 盒
#: （minx, miny, maxx, maxy，mil），``width`` 是同一只盒子的**字向**跨度（实测值，
#: 顶/底两面都是 0°/90°/180°/270°，所以字向跨度就是盒子的一个边长）。宽度按实测喂进去
#: 是有意的：这条测试要证的是方向、锚点和字身侧，不是字形步进（宿主实测：同一 45 mil
#: 字号下字符 ink 宽并不相等，"R"=23.1、"1"=17.9、"4"=30.1）。
A_TABLE = [
    dict(name="top 0", text="R1", layer_kind="TOP_SILK", x=-57.531, y=34.008, angle=0.0,
         box=(-57.531, 34.008, -16.531, 79.008), width=41.0),
    dict(name="top 90", text="R2", layer_kind="TOP_SILK", x=365.992, y=-57.531, angle=90.0,
         box=(320.992, -57.531, 365.992, -5.531), width=52.0),
    dict(name="top 180", text="R3", layer_kind="TOP_SILK", x=857.531, y=-34.008,
         angle=180.0, box=(805.531, -79.008, 857.531, -34.008), width=52.0),
    dict(name="top 270", text="R4", layer_kind="TOP_SILK", x=1234.008, y=57.531,
         angle=-90.0, box=(1234.008, 4.331, 1279.008, 57.531), width=53.2),
    dict(name="bottom 0", text="R5", layer_kind="BOT_SILK", x=-57.531, y=565.992,
         angle=180.0, box=(-57.531, 520.992, -5.531, 565.992), width=52.0),
    dict(name="bottom 90", text="R6", layer_kind="BOT_SILK", x=434.008, y=542.469,
         angle=90.0, box=(434.008, 542.469, 479.008, 593.269), width=50.8),
    dict(name="bottom 180", text="R7", layer_kind="BOT_SILK", x=857.531, y=634.008,
         angle=0.0, box=(805.531, 634.008, 857.531, 679.008), width=52.0),
    dict(name="bottom 270", text="R8", layer_kind="BOT_SILK", x=1165.992, y=657.531,
         angle=-90.0, box=(1120.992, 605.531, 1165.992, 657.531), width=52.0),
    dict(name="bottom 0 b", text="R9", layer_kind="BOT_SILK", x=-57.531, y=1165.992,
         angle=180.0, box=(-57.531, 1120.992, -6.731, 1165.992), width=50.8),
    dict(name="bottom 90 b", text="R10", layer_kind="BOT_SILK", x=434.008, y=1142.469,
         angle=90.0, box=(434.008, 1142.469, 479.008, 1212.369), width=69.9),
    dict(name="bottom 180 b", text="R11", layer_kind="BOT_SILK", x=857.531, y=1234.008,
         angle=0.0, box=(798.631, 1234.008, 857.531, 1279.008), width=58.9),
    dict(name="bottom 270 b", text="R12", layer_kind="BOT_SILK", x=1165.992, y=1257.531,
         angle=-90.0, box=(1120.992, 1187.631, 1165.992, 1257.531), width=69.9),
]

FONT = 45.0
#: 12 条记录全部 ``origin: LEFT_BOTTOM``、``mirror: false``、``reverse: false``、
#: ``strokeWidth: 6``，实测如此（``outputs/190s/live/A_pcb_source_12.txt``）。
ORIGIN = "LEFT_BOTTOM"


def _advance(row) -> float:
    """该行的字宽比：把宿主的实测字向跨度折成 ``corners()`` 要的那个参数。"""
    return row["width"] / (len(row["text"]) * FONT)


def _row_text(row, source="designator", **overrides) -> SilkText:
    return SilkText(
        text=row["text"],
        source=source,
        x=row["x"],
        y=row["y"],
        angle=row["angle"],
        layer_id=3 if row["layer_kind"] == "TOP_SILK" else 4,
        layer_kind=row["layer_kind"],
        font_size=FONT,
        origin=ORIGIN,
        mirror=False,
        reverse=False,
        visible=True,
        **overrides,
    )


def _bbox(points) -> tuple[float, float, float, float]:
    return (
        min(p.x for p in points),
        min(p.y for p in points),
        max(p.x for p in points),
        max(p.y for p in points),
    )


def _same_box(got, want, tol=1e-6) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(got, want))


@pytest.mark.parametrize("row", A_TABLE, ids=[r["name"] for r in A_TABLE])
def test_corners_reproduces_the_host_box_of_every_calibrated_placement(row):
    """``corners()`` 必须复现宿主自己的 ink 盒——12 条，一条不落。

    这条同时钉住三件事：锚点是盒子的哪个角、盒子朝哪边伸、字身在基线的哪一侧。
    宽度用实测值折出来的 ``advance``，所以比较的是**整只盒子**而不只是方向。
    """
    text = _row_text(row)
    box = _bbox(text.corners(_advance(row)))
    assert _same_box(box, row["box"]), f"{row['name']}: {box} != {row['box']}"


@pytest.mark.parametrize("row", [r for r in A_TABLE if r["layer_kind"] == "BOT_SILK"],
                         ids=[r["name"] for r in A_TABLE if r["layer_kind"] == "BOT_SILK"])
def test_a_bottom_record_is_the_top_box_reflected_in_x(row):
    """底层记录 = 同一只盒子按 x 镜像（锚点不动），这就是定标结论本身。

    反过来写也一样：把底层记录的层改成顶层，得到的盒子必须是它关于锚点的 x 镜像
    ——老模型（一律沿 angle 方向伸出）给不出这个关系。
    """
    bottom = _row_text(row)
    top = dataclasses.replace(bottom, layer_kind="TOP_SILK", layer_id=3)
    assert bottom.mirrored_frame is True and top.mirrored_frame is False
    advance = _advance(row)
    bottom_box = _bbox(bottom.corners(advance))
    top_box = _bbox(top.corners(advance))
    mirrored = (2.0 * row["x"] - top_box[2], top_box[1],
                2.0 * row["x"] - top_box[0], top_box[3])
    assert _same_box(bottom_box, mirrored), f"{row['name']}: {bottom_box} vs {mirrored}"
    # 记录角是 0° 或 180° 时，盒子正好沿**记录角的 -u** 走（180-A ≡ A+180 只有这两角
    # 成立）：实板A 的 29 条底层位号记录角全是 0°，所以「29/29 朝 -u」。
    if row["angle"] == 0.0:
        assert bottom_box[2] == row["x"] and bottom_box[0] < row["x"]
    elif row["angle"] == 180.0:
        assert bottom_box[0] == row["x"] and bottom_box[2] > row["x"]


def test_a_top_record_is_not_reflected_and_a_footprint_frame_is_not_either():
    """顶层记录不镜像；封装自带印字（锚点由器件位姿求出）两面的帧都不是这一路。"""
    row = A_TABLE[0]
    assert _row_text(row).mirrored_frame is False
    assert _row_text(A_TABLE[4]).mirrored_frame is True
    # 自由文字与位号同一族记录、同一层，跟着走
    assert _row_text(A_TABLE[4], source="board").mirrored_frame is True
    # 封装印字：锚点由 ComponentPlacement.transform 求出，角度已与器件位姿合成
    assert _row_text(A_TABLE[4], source="footprint").mirrored_frame is False


def test_other_origins_keep_their_meaning_on_the_bottom_face():
    """镜像只翻 x，不改 origin 的含义：RIGHT / CENTER / TOP 仍按同一套算。"""
    base = dict(text="R22", source="designator", x=100.0, y=50.0, angle=0.0,
                layer_kind="BOT_SILK", layer_id=4, font_size=45.0, visible=True)
    left = _bbox(SilkText(origin="LEFT_BOTTOM", **base).corners(0.6))
    right = _bbox(SilkText(origin="RIGHT_BOTTOM", **base).corners(0.6))
    top = _bbox(SilkText(origin="LEFT_TOP", **base).corners(0.6))
    assert left[2] == 100.0 and left[0] < 100.0  # 字向朝 -x，起点在锚点
    assert right[0] == 100.0 and right[2] > 100.0
    assert left[0] < left[2] and (left[1], left[3]) == (50.0, 95.0)
    assert (top[1], top[3]) == (5.0, 50.0)


@pytest.mark.skipif(not REAL_BOARD.exists(), reason="实板A 只在有归档的机器上在场")
def test_real_board_stops_reporting_a_designator_over_a_neighbours_pad():
    """实板A：标定后**没有**一条底层位号压在别人的同面焊盘上。

    老模型（把底层记录的层当顶层算，即未定标的那一版）恰好报一条：R22 的位号丝印压
    EC3 pin 2、20.2 mil——工程当场否掉的那条。这里把两版都算一遍，因为「修好了」这句话
    要有对照物。
    """
    board = parse_epro2(REAL_BOARD)
    hits = {"calibrated": [], "pre_190s": []}
    lowered = 0
    for text in board.silk_texts:
        if text.source != "designator" or text.layer_kind != "BOT_SILK":
            continue
        if not text.visible or not text.text or text.font_size <= 0:
            continue
        face = FACE_OF_SILK[text.layer_kind]
        old_text = dataclasses.replace(text, layer_kind="TOP_SILK")
        for label, model in (("calibrated", text), ("pre_190s", old_text)):
            for pad in board.pads:
                if face not in (pad.effective_layer_ids or []):
                    continue
                if str(pad.component or "") == str(text.component or ""):
                    continue
                gap = box_overlaps(text_box(model, DEFAULT_ADVANCE), pad)
                if gap < 0:
                    hits[label].append(
                        (text.text, str(pad.component), str(pad.pin_number),
                         round(-gap, 1))
                    )
        if text.mirrored_frame:
            lowered += 1
    assert lowered > 0
    assert hits["calibrated"] == [], hits["calibrated"]
    assert [(a, b) for a, b, _c, _d in hits["pre_190s"]] == [("R22", "EC3")], hits["pre_190s"]


@pytest.mark.skipif(not REAL_BOARD.exists(), reason="实板A 只在有归档的机器上在场")
def test_real_board_bottom_boxes_never_move_further_from_their_own_part():
    """标定**不会**把任何一条底层位号的盒子推离它自己的器件。

    逐条比「盒子到自己器件最近的同面焊盘」的距离：30 条里 27 条原地不动（锚点没动，
    盒子的那一侧本来就贴着自家焊盘），另外 3 条显著靠近（C33 27.3→16.7、U9 81.5→27.5、
    P7 135.6→81.6 mil）——没有一条变远。这就是「底层位号的盒子该落在自家焊盘附近」
    这条 A 表预测，用整块实板量出来的样子。
    """
    from boardwise.rules.pcb.silk import pad_polygon, polygon_gap

    board = parse_epro2(REAL_BOARD)
    closer, same, further = [], [], []
    for text in board.silk_texts:
        if text.source != "designator" or text.layer_kind != "BOT_SILK":
            continue
        if not text.visible or not text.text or text.font_size <= 0:
            continue
        old_text = dataclasses.replace(text, layer_kind="TOP_SILK")

        def own_gap(model):
            best = None
            box = [(p.x, p.y) for p in text_box(model, DEFAULT_ADVANCE)]
            for pad in board.pads:
                if 2 not in (pad.effective_layer_ids or []):
                    continue
                if str(pad.component or "") != str(text.component or ""):
                    continue
                gap = polygon_gap(box, pad_polygon(pad))
                best = gap if best is None else min(best, gap)
            return best

        before, after = own_gap(old_text), own_gap(text)
        if before is None or after is None:
            continue
        if after < before - 1e-6:
            closer.append(text.text)
        elif after > before + 1e-6:
            further.append(text.text)
        else:
            same.append(text.text)
    assert further == [], further
    # 192A 把底层焊盘的局部 y 翻转后，P7 两种帧下离自家焊盘同为 61.2 mil，
    # 从 closer 移到 same（3 -> 2）；further == [] 这条不变式不动。
    assert len(closer) == 2, (len(closer), closer)
    assert len(same) + len(closer) + len(further) == 30
