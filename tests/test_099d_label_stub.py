"""099d：标签 stub 落点必须躲开别网导体（落图器缺陷，074 引线避让的同族病）。

099c 的真机现场：RXD 的 10 单位名 stub（(290,720)→(280,720)）跨度压住 V3 走线的拐角
(285,720)，宿主把两条线并成一个 primitive（坑 32），工程级网表把 V3 并进 RXD ——
一条真短路，apply 的双证回读拦下、没有保存。`draw apply` 补 stub 那段从来只按标签文字盒
的方向取点，**不检查别网导体**；本批补上：

* 候选 run 与别网导线做**内部相交 + 相接**（相接也要躲：在这个宿主里，落在别网线上与穿过
  它一样是同一个节点——074 的严格相交尺子多这一条），
* 再与已落件**引脚**（压住别人的脚 = 连接到别网）与**体框**（readability 的 wire-through-body）比，
* 命中就换方向（四方向轮询）→ 再换长度（10 → 5/15/20/30/40）→ 全不行**如实拒绝并点名**。

第一段直接钉这三个判断，第二段拿出货的 CH340 规格走一遍 `module_plan(label_stubs=True)`：
它必须在 099c 那个现场**落得下来**，且任何一条 stub 都不碰别网导体。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.changeplan import DRAW_MODULE_KIND
from boardwise.core.layoutplan import LayoutLabel
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines.drawapply import (
    LABEL_STUB_LENGTH,
    DrawPlanError,
    load_library,
    module_plan,
)

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _label(x, y, box):
    return LayoutLabel(net="RXD", text="RXD", x=x, y=y, bbox=box)


def _wire(net, points):
    from boardwise.engines.drawapply import _Built, PlanDrawWire
    built = _Built()
    built.wires.append(PlanDrawWire(net=net, points=list(points)))
    return built


def _free_built():
    from boardwise.engines.drawapply import _Built
    return _Built()


# ------------------------------------------------ 1. 避让：换向 / 换长 / 拒绝


def test_a_stub_that_would_land_on_a_foreign_wire_steps_aside():
    """偏好方向（左，10）压在别网线上 → 换向/换长，落点不碰任何别网导体。"""
    # 标签锚点 (290,720)，文字盒在左；一条别网导线横在左边同一行上。
    label = _label(290.0, 720.0, (258.0, 715.5, 282.0, 724.5))
    built = _wire("V3", [(170.0, 720.0), (285.0, 720.0)])
    stub, blockers = drawapply._place_label_stub(label, built, {}, ())
    assert stub is not None, blockers
    # 落点不是旧行为的 (280,720)
    assert stub != (280.0, 720.0)
    # 且这条 run 真的躲开了那条导线
    assert drawapply._label_stub_blocked(label, (290.0, 720.0), stub, built, {}, ()) is None


def test_the_preferred_run_is_reported_when_it_is_blocked():
    """被挡住的偏好方向要留下理由（拒绝文案的素材）。"""
    label = _label(290.0, 720.0, (258.0, 715.5, 282.0, 724.5))
    built = _wire("V3", [(170.0, 720.0), (285.0, 720.0)])
    _stub, blockers = drawapply._place_label_stub(label, built, {}, ())
    assert blockers, "the preferred direction was free — the fixture does not test 099d"
    assert "net V3's wire" in blockers[0]


def test_every_direction_blocked_is_refused_naming_the_blockers():
    """四方向 × 长度档全撞 → (None, 每方向一条点名)，绝不静默压上去。"""
    label = _label(0.0, 0.0, (-24.0, -4.5, 0.0, 4.5))
    built = drawapply._Built()
    # 四方向都放一条别网导线，长度档全部盖住
    for points in (
        [(0.0, 0.0), (-40.0, 0.0)], [(0.0, 0.0), (40.0, 0.0)],
        [(0.0, 0.0), (0.0, 40.0)], [(0.0, 0.0), (0.0, -40.0)],
    ):
        built.wires.append(drawapply.PlanDrawWire(net="V3", points=points))
    stub, blockers = drawapply._place_label_stub(label, built, {}, ())
    assert stub is None
    assert len(blockers) == 4, blockers
    assert all("net V3's wire" in line for line in blockers)


def test_a_stub_through_a_foreign_pin_is_blocked():
    """压住别人的脚 = 连到别网：与压住别人的线同罪。"""
    label = _label(0.0, 0.0, (-24.0, -4.5, 0.0, 4.5))
    built = _free_built()
    reason = drawapply._label_stub_blocked(
        label, (0.0, 0.0), (-10.0, 0.0), built, {}, (("U2", "4", (-10.0, 0.0)),),
    )
    assert reason is not None and "U2.4" in reason


def test_a_stub_through_a_foreign_body_is_blocked():
    """穿体框 = readability 的 wire-through-body，同样拒。"""
    label = _label(0.0, 0.0, (-24.0, -4.5, 0.0, 4.5))
    built = _free_built()
    reason = drawapply._label_stub_blocked(
        label, (0.0, 0.0), (-10.0, 0.0), built,
        {"C11": (-30.0, -10.0, -5.0, 10.0)}, (),
    )
    assert reason is not None and "C11" in reason


def test_its_own_net_and_its_own_pin_are_not_obstacles():
    """自己那张网的线、自己那根脚：允许（合并到同网不是缺陷）。"""
    label = _label(0.0, 0.0, (-24.0, -4.5, 0.0, 4.5))
    built = _wire("RXD", [(0.0, 0.0), (-10.0, 0.0)])
    assert drawapply._label_stub_blocked(
        label, (0.0, 0.0), (-10.0, 0.0), built, {}, (("U2", "3", (0.0, 0.0)),)
    ) is None


# ------------------------------------------- 2. 无碰撞 → 落点与今天逐字节相同


def test_a_free_stub_lands_exactly_where_057_put_it():
    """无碰撞：偏好方向 + 旧长度，落点与 057 的公式一字不差（零移动）。"""
    label = _label(290.0, 720.0, (258.0, 715.5, 282.0, 724.5))
    built = _free_built()
    stub, blockers = drawapply._place_label_stub(label, built, {}, ())
    assert blockers == []
    assert stub == (280.0, 720.0)
    assert stub == drawapply._label_stub(label)
    assert LABEL_STUB_LENGTH == 10.0


def test_a_box_reach_shorter_than_the_stub_caps_the_length():
    """055/057 的旧语义还在：盒子的自伸长度短于 10 时按盒来。"""
    label = _label(0.0, 0.0, (-5.0, -4.5, 0.0, 4.5))
    built = _free_built()
    stub, _blockers = drawapply._place_label_stub(label, built, {}, ())
    assert stub == (-5.0, 0.0)


# ------------------------------------------------ 3. 出货规格：099c 那个现场


def _ch340_layout():
    circuit = CircuitSpec.from_dict(json.loads(
        (SPECS / "ch340_serial.circuit.json").read_text(encoding="utf-8")))
    sheet = PresentationSpec.from_dict(json.loads(
        (SPECS / "ch340_serial.presentation.json").read_text(encoding="utf-8")))
    book = load_library(SPECS / "ch340_serial.library.json")
    result = dc.compile(circuit, sheet, book,
                        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)))
    assert result.ok, result.render_failures()
    return result.candidates[0], circuit, sheet, book


def _segments_touch(a, b, c, d) -> bool:
    """Two axis-aligned runs share at least one point (the test's own ruler).

    Deliberately independent of `drawapply._label_stub_blocked`: a check that asks
    the code under test whether it was right cannot fail when that code is
    disabled. For axis-aligned runs, "the inclusive bounding boxes intersect" *is*
    "they share a point", so this needs no case analysis.
    """
    return (
        min(a[0], b[0]) <= max(c[0], d[0]) and min(c[0], d[0]) <= max(a[0], b[0])
        and min(a[1], b[1]) <= max(c[1], d[1]) and min(c[1], d[1]) <= max(a[1], b[1])
    )


def _point_on(a, b, point) -> bool:
    return (
        min(a[0], b[0]) - 1e-9 <= point[0] <= max(a[0], b[0]) + 1e-9
        and min(a[1], b[1]) - 1e-9 <= point[1] <= max(a[1], b[1]) + 1e-9
    )


def test_the_ch340_page_builds_and_no_stub_touches_another_net():
    """099c 的现场：RXD 的 stub 不再压 V3 走线，整张页落得下来。"""
    layout, circuit, sheet, book = _ch340_layout()
    plan = module_plan(layout, circuit, sheet, book, label_stubs=True,
                       module_label="page serial")
    assert plan.change.kind == DRAW_MODULE_KIND
    stubs = [item for item in plan.change.draw_wires if item.purpose]
    assert {item.net for item in stubs} == {"TXD", "RXD", "D+", "D-"}, stubs
    # the 099c defect in one line: RXD's stub is no longer the 10-unit run that
    # sat on the V3 route's corner
    rxd = next(item for item in stubs if item.net == "RXD")
    assert rxd.points != [(290.0, 720.0), (280.0, 720.0)]

    foreign = [
        (item.points[index], item.points[index + 1], item.net)
        for item in plan.change.draw_wires if not item.purpose
        for index in range(len(item.points) - 1)
    ]
    pins = [
        (part.designator, number, point)
        for part in plan.change.draw_parts
        for number, point in drawapply.expected_pin_points(part).items()
    ]
    for stub in stubs:
        start, end = stub.points[0], stub.points[-1]
        for a, b, net in foreign:
            if net == stub.net:
                continue
            assert not _segments_touch(start, end, a, b), (stub.net, (start, end), net, (a, b))
        for part_id, pin, point in pins:
            if _point_on(start, end, point) and point != start:
                pytest.fail(f"{stub.net}'s stub runs through {part_id}.{pin} at {point}")


def test_a_label_with_no_free_stub_refuses_the_plan(monkeypatch):
    """没有自由 stub 时 `module_plan` 如实拒绝（exit 5 那条路），不是静默压上去。"""
    layout, circuit, sheet, book = _ch340_layout()
    monkeypatch.setattr(
        drawapply, "_place_label_stub",
        lambda label, built, bodies, pins: (None, ["left: it lands on net V3's wire"]),
    )
    with pytest.raises(DrawPlanError) as caught:
        module_plan(layout, circuit, sheet, book, label_stubs=True,
                    module_label="page serial")
    message = str(caught.value)
    assert "has no free name stub" in message
    assert "net V3's wire" in message


def test_a_boxed_in_label_is_refused_and_every_direction_is_named():
    """四方向（含长度档）全被别网导线堵死：`(None, 四条点名)`，一条都不许压上去。"""
    label = LayoutLabel(net="RXD", text="RXD", x=290.0, y=720.0,
                        bbox=(258.0, 715.5, 282.0, 724.5))
    blocked = drawapply._Built()
    for points in (
        [(285.0, 720.0), (170.0, 720.0)],       # left：同一条横线
        [(292.0, 720.0), (400.0, 720.0)],       # right：紧贴锚点右侧就起线
        [(290.0, 725.0), (290.0, 800.0)],       # up
        [(290.0, 715.0), (290.0, 600.0)],       # down
    ):
        blocked.wires.append(drawapply.PlanDrawWire(net="V3", points=points))
    stub, blockers = drawapply._place_label_stub(label, blocked, {}, ())
    assert stub is None
    assert len(blockers) == 4, blockers
    assert all("net V3's wire" in line for line in blockers)
