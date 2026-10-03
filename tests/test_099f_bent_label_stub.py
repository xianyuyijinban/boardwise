"""099f：stub 阶梯加折线档——直线出不去时，先旁移一格再向标签侧出。

099e 落成之后唯一的视觉瑕疵：RXD 的网名被画在符号边上（(292.5,-720)，与另外三条
`D+/D−/TXD` 所在的那一侧相反）。原因不是落图器乱放，而是**左向直线档根本出不去**——
V3 走线的拐角 (285,720) 距 RXD 脚端只有 5 单位，把整条左行占满；四个直线方向里唯一
空着的是"朝符号里"那一格。本批给阶梯加**折线候选**，顺序是：

1. **标签自己那一侧的直线**（057 的档，也是第一候选 ⇒ 无碰撞时落点与今天逐字节相同）；
2. **折线**：旁移一格（上/下，两格档）再沿标签侧走同一套长度档 —— 名字回到标签盒那一侧；
3. **其余三向的直线**（名字在别的侧面，但总比不画强）；
4. 全不行 → 如实拒绝并逐形状点名。

折线的**每一段**都过 `_label_stub_blocked`（别网导线穿/接/共线、别件引脚、别件体框），
拐角上蹭到任何东西也算——那种位置在宿主里就是一个节点。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutLabel
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines.drawapply import LABEL_STUB_STEPS, PlanDrawWire, load_library

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

#: 099e 的现场：RXD 脚端 (290,720)，标签盒在左，V3 走线独占左边同一行。
RXD = LayoutLabel(net="RXD", text="RXD", x=290.0, y=720.0,
                  bbox=(258.0, 715.5, 282.0, 724.5))
V3_ROUTE = PlanDrawWire(
    net="V3", points=[(170.0, 710.0), (170.0, 720.0), (285.0, 720.0),
                      (285.0, 710.0), (290.0, 710.0)],
)


def _built(*wires) -> drawapply._Built:
    built = drawapply._Built()
    built.wires.extend(wires)
    return built


def _segments(points):
    return list(zip(points, points[1:]))


# ------------------------------------------------- 1. 直线被堵 → 折线胜出


def test_the_bent_run_wins_when_every_straight_run_out_is_blocked():
    """099e 的现场：直线全堵 ⇒ 折线落位，且名字回到标签那一侧。"""
    stub, blockers = drawapply._place_label_stub(RXD, _built(V3_ROUTE), {}, ())
    assert stub is not None, blockers
    assert len(stub) == 3, stub
    anchor, corner, far = stub
    assert anchor == (290.0, 720.0)
    assert corner[1] == anchor[1] + LABEL_STUB_STEPS[0]      # 先旁移一格
    assert far[1] == corner[1] and far[0] == corner[0] - 10.0  # 再向左 10（标签侧）
    for head, tail in _segments(stub):
        assert drawapply._label_stub_blocked(
            RXD, head, tail, _built(V3_ROUTE), {}, ()) is None


def test_a_free_straight_run_is_still_the_first_candidate():
    """零移动：没有碰撞时，第一候选仍是标签侧的直线档（057 的落点）。"""
    stub, blockers = drawapply._place_label_stub(RXD, _built(), {}, ())
    assert blockers == []
    assert stub == ((290.0, 720.0), (280.0, 720.0))
    assert stub[-1] == drawapply._label_stub(RXD)


def test_a_straight_run_on_another_side_loses_to_the_bent_one():
    """另一侧的直线（名字会跑到引脚别的面）排在折线**之后**。"""
    # 左边被占、右边 10 单位空着；折线仍应当先胜出
    built = _built(PlanDrawWire(net="V3", points=[(285.0, 720.0), (170.0, 720.0)]))
    stub, _blockers = drawapply._place_label_stub(RXD, built, {}, ())
    assert stub is not None
    assert len(stub) == 3 and stub[-1][1] != stub[0][1]


# ------------------------------------------------- 2. 折线两段各自查


def test_the_far_leg_of_the_bent_run_is_checked_too():
    """拐角干净、远端那一段撞上别网导线 ⇒ 这条折线整条不算（不许画一半）。"""
    # 移一格后要走的横线 (290,725)-(280,725) 上放一条别网导线
    built = _built(
        PlanDrawWire(net="V3", points=[(285.0, 720.0), (170.0, 720.0)]),
        PlanDrawWire(net="XI", points=[(280.0, 725.0), (180.0, 725.0)]),
    )
    stub, blockers = drawapply._place_label_stub(RXD, built, {}, ())
    # 要么换到别的形状（下移一格），要么如实拒绝；绝不给出穿过 XI 的折线
    if stub is not None:
        for head, tail in _segments(stub):
            assert drawapply._label_stub_blocked(
                RXD, head, tail, built, {}, ()) is None, (stub, head, tail)
    else:
        assert any("XI" in line for line in blockers), blockers


def test_the_corner_of_the_bent_run_is_checked_too():
    """拐角压在别件引脚上 ⇒ 这条折线不算（拐角在宿主里就是一个节点）。"""
    built = _built(PlanDrawWire(net="V3", points=[(285.0, 720.0), (170.0, 720.0)]))
    pins = [("U9", "2", (290.0, 725.0))]
    stub, blockers = drawapply._place_label_stub(RXD, built, {}, pins)
    if stub is not None:
        assert stub[1] != (290.0, 725.0), stub
    else:
        assert blockers


# ------------------------------------------------- 3. 折线也全撞 → 拒绝


def test_every_bent_run_blocked_is_refused_and_named():
    """两条折线也被堵死 ⇒ 如实拒绝，点名里要能看到折线形状。"""
    built = _built(
        PlanDrawWire(net="V3", points=[(285.0, 720.0), (170.0, 720.0)]),  # 左行
        PlanDrawWire(net="V3", points=[(290.0, 725.0), (290.0, 800.0)]),  # 上折线
        PlanDrawWire(net="V3", points=[(290.0, 715.0), (290.0, 600.0)]),  # 下折线
        PlanDrawWire(net="V3", points=[(292.0, 720.0), (400.0, 720.0)]),  # 右
    )
    stub, blockers = drawapply._place_label_stub(RXD, built, {}, ())
    assert stub is None
    assert len(blockers) == 6, blockers            # 4 直线 + 2 折线，各一条
    # 折线的形状名写成 "<旁移方向> <步长> then <标签侧> <长度>"（两段一眼看得出来）
    assert sum(1 for line in blockers if " then " in line) == 2, blockers
    assert all("net V3's wire" in line for line in blockers)


# ------------------------------------------------- 4. 出货规格：网名回到标签侧


def test_the_ch340_page_names_rxd_on_the_label_side_again():
    """出货规格：RXD 落成折线，网名回到标签盒那一侧（与 D+/D−/TXD 同侧）。"""
    circuit = CircuitSpec.from_dict(json.loads(
        (SPECS / "ch340_serial.circuit.json").read_text(encoding="utf-8")))
    sheet = PresentationSpec.from_dict(json.loads(
        (SPECS / "ch340_serial.presentation.json").read_text(encoding="utf-8")))
    book = load_library(SPECS / "ch340_serial.library.json")
    result = dc.compile(circuit, sheet, book,
                        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)))
    assert result.ok, result.render_failures()
    plan = drawapply.module_plan(result.candidates[0], circuit, sheet, book,
                                 label_stubs=True, module_label="page serial")
    stubs = {item.net: item.points for item in plan.change.draw_wires if item.purpose}
    assert set(stubs) == {"TXD", "RXD", "D+", "D-"}

    # 另外三条是 10 单位直线；RXD 是折线，且**远端比锚点更靠左**——名字回到标签那一侧
    for net in ("TXD", "D+", "D-"):
        anchor, far = stubs[net]
        assert far[0] < anchor[0] and far[1] == anchor[1], (net, stubs[net])
    anchor, corner, far = stubs["RXD"]
    assert far[0] < anchor[0], stubs["RXD"]
    assert far[1] != anchor[1], stubs["RXD"]
    # 折线确实只旁移一格 —— 与另三条同一个标签侧
    assert abs(corner[1] - anchor[1]) == LABEL_STUB_STEPS[0]
