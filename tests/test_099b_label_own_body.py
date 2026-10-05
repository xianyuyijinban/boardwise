"""099b：标签压「自己那颗器件」的体框合法，以及回退不再锚点居中。

099 的真机落图在离线编译那一步被可读性硬闸拒了，根因是三处：

1. `_label_at` 四方向全被占时回退到**以锚点为中心的盒**——紧凑符号（脚端距画出体框
   只有 9.5 单位，短于标签盒半宽 12）上它必然压自己那颗器件的体框；
2. 可读性检查器把那枚标签算成**外来文字**（net label 不带所属 part），于是"压自己
   器件"也被拒；
3. 器件文字（位号/值）的侧梯把**别的器件的脚端包围盒**当墙——那个盒子的角根本没画
   东西，却以 1.5 单位之差把核心的文字挤到自己引脚标签的那一侧。

这三处都改在 099b。测试分四段钉住它们，最后一段是**出货的 CH340 规格真能编译**：
`blocklib/specs/ch340_serial.*` 一个字不动，四条信号标签落在核心体框之外。

第一段的负例是"同一枚标签换一个 part_id"——除了归属以外一切不变，所以多出来的那条
违规只能归因到豁免本身（053 阶段 B 的惯例：一张图只改一处，多出来的正好是那处）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec, SpecNet, SpecPart
from boardwise.core.layoutplan import (
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutSource,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile, SymbolPose
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability
from boardwise.engines.drawapply import load_library

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

#: 一张两器件的图：U1 是"核心"，C3 是挂在它右侧 60 单位处的去耦电容。
CORE = "PAD-16"
CAP = "CAP-2P"
HASH = "b" * 64


def _core_profile(*, pin_length: float | None = 10.0) -> SymbolProfile:
    """16 脚、脚端在 ±40、体框 ±30.5 的核心——099 实测那颗 CH340G 的形状。"""
    rows = []
    for index in range(8):
        rows.append((str(index + 1), "L%d" % (index + 1), (-40.0, 35.0 - index * 10.0), "left"))
    for index in range(8):
        rows.append((str(index + 9), "R%d" % (index + 1), (40.0, -35.0 + index * 10.0), "right"))
    return SymbolProfile(
        symbol_ref=CORE, title=CORE, body=(-30.5, -45.5, 30.5, 45.5),
        pins=[
            SymbolPin(number=number, name=name, tip=tip, direction=direction,
                      length=pin_length)
            for number, name, tip, direction in rows
        ],
    )


def _cap_profile(*, pin_length: float | None = 10.0) -> SymbolProfile:
    """0603 电容：脚端 ±20、体框 ±8.5（竖放时半宽 8.5）。"""
    return SymbolProfile(
        symbol_ref=CAP, title=CAP, body=(-10.5, -8.5, 10.5, 8.5),
        pins=[
            SymbolPin(number="1", name="1", tip=(-20.0, 0.0), direction="left",
                      length=pin_length),
            SymbolPin(number="2", name="2", tip=(20.0, 0.0), direction="right",
                      length=pin_length),
        ],
    )


def _checker_case(*, owner: str):
    """核心在 (0,0)、电容在 (475,715)；标签盒压在核心体框左边缘上。

    标签锚点是核心 2 号脚的脚端 (-40, 25)，盒向右伸进体框 2.5 单位——099 现场
    被拒的那 2.5 单位，一模一样。
    """
    plan = LayoutPlan(
        source=LayoutSource(),
        parts=[
            LayoutPart(part_id="U1", symbol_ref=CORE, symbol_hash=HASH, x=0.0, y=0.0,
                       reference="U1"),
            LayoutPart(part_id="C3", symbol_ref=CAP, symbol_hash=HASH, x=475.0,
                       y=715.0, rotation=90.0, mirror=True, reference="C3"),
        ],
        labels=[LayoutLabel(
            net="RXD", text="RXD", x=-40.0, y=25.0,
            bbox=(-52.0, 20.5, -28.0, 29.5), part_id=owner,
        )],
    )
    circuit = CircuitSpec(
        parts=[
            SpecPart(id="U1", symbol_ref=CORE, value="CH340G"),
            SpecPart(id="C3", symbol_ref=CAP, value="100nF"),
        ],
        nets=[
            SpecNet(id="VCC", cls="power", members=["U1.16", "C3.1"]),
            SpecNet(id="GND", cls="gnd", members=["U1.1", "C3.2"]),
            SpecNet(id="RXD", cls="signal", members=["U1.3"]),
        ],
    )
    return plan, circuit, {CORE: _core_profile(), CAP: _cap_profile()}


def _violations(plan, circuit, book):
    return readability.check(plan, circuit, PresentationSpec(), book).hard_violations


# ------------------------------------------------------- D2：标签的归属豁免


def test_a_label_over_its_own_parts_body_is_not_a_violation():
    """099b：标签压自己那颗器件的体框 = 那颗器件自己的文字，不是外来文字。"""
    plan, circuit, book = _checker_case(owner="U1")
    overlaps = [item for item in _violations(plan, circuit, book)
                if item.kind == readability.KIND_TEXT_OVERLAP]
    assert overlaps == []


def test_the_same_label_attributed_to_another_part_is_still_refused():
    """同一枚盒、只换归属：自己那颗的豁免不适用于**别人**的体框。"""
    plan, circuit, book = _checker_case(owner="C3")
    found = [item for item in _violations(plan, circuit, book)
             if item.kind == readability.KIND_TEXT_OVERLAP]
    assert [item.objects for item in found] == [("labels[0]", "parts[U1]")]
    assert "lands on the drawn body of parts[U1]" in found[0].evidence


def test_an_unowned_label_over_a_body_is_still_refused():
    """没有归属的标签（抽头 stub 端、页边界）保持原样：照拒。"""
    plan, circuit, book = _checker_case(owner="")
    found = [item for item in _violations(plan, circuit, book)
             if item.kind == readability.KIND_TEXT_OVERLAP]
    assert [item.objects for item in found] == [("labels[0]", "parts[U1]")]


# ------------------------------------------------ D1：回退落在引脚朝向那一侧


def _occupied_around(point, *, net="RXD"):
    """把锚点四邻全堵上：preferred=left 与其余三个方向**每一格**都撞车。

    每个挡块正好盖住一个候选盒（候选盒按 `_label_at` 自己的偏移造：水平
    ``±(text_width/2 + TEXT_GAP)``、垂直 ``±(TEXT_SIZE/2 + TEXT_GAP)``）。

    **117 更新**：`_label_at` 的阶梯从「每方向一格」改成「每方向
    :data:`drawcompiler.TEXT_ESCALATION_STEPS` 格」（旗名在一格上放不下时，
    两格三格常常是空的——反激整页的八个 `text-overlap` 就是这么来的）。所以
    「四个方向都被占」必须按**新的判据**造：**每一格**都被占，测试量的仍然是
    同一件事——真的无处可去时，盒子落回引脚自己的逃逸那一侧、且不把锚点包在
    里面。只堵第一格的话，117 之后第二格是空的，量到的就不再是「无处可去」
    而是「试得太少」，而这两条测试的**本意是前者**。
    """
    half_x = dc.text_width(net) / 2.0 + dc.TEXT_GAP
    half_y = dc.TEXT_SIZE / 2.0 + dc.TEXT_GAP
    boxes = []
    for rung in range(1, dc.TEXT_ESCALATION_STEPS + 1):
        for dx, dy in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)):
            reach_x = half_x * rung if dx else half_x
            reach_y = half_y * rung if dy else half_y
            x = point[0] + dx * reach_x
            y = point[1] + dy * reach_y
            boxes.append((x - half_x, y - half_y, x + half_x, y + half_y))
    return boxes


def _candidate_boxes(point, *, net="RXD"):
    """`_label_at` 会依次试的盒，**按它自己的顺序**：方向优先、格次之。

    顺序不是装饰——回退取的是**第一个**候选（`_label_at` 里的 `fallback`），
    所以这个列表的第一项必须与 `_label_at` 试的第一格是同一个盒子，否则
    下面两条断言量的就不是「回退落在哪」。
    """
    half_x = dc.text_width(net) / 2.0 + dc.TEXT_GAP
    half_y = dc.TEXT_SIZE / 2.0 + dc.TEXT_GAP
    out = []
    for dx, dy in ((-1.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        for rung in range(1, dc.TEXT_ESCALATION_STEPS + 1):
            reach_x = half_x * rung if dx else half_x
            reach_y = half_y * rung if dy else half_y
            x = point[0] + dx * reach_x
            y = point[1] + dy * reach_y
            out.append(dc.font_text_box(net, x=x, y=y))
    return out


def test_a_label_whose_every_direction_is_occupied_lands_on_the_pins_own_side():
    point = (-40.0, 25.0)
    occupied = _occupied_around(point)
    # 前提：四个方向确实全被占（否则这条测试测的不是回退）
    assert all(
        any(dc._overlaps(candidate, blocker) for blocker in occupied)
        for candidate in _candidate_boxes(point)
    )
    label = dc._label_at("RXD", point, (-1.0, 0.0), occupied)
    assert label.bbox == pytest.approx(_candidate_boxes(point)[0])


def test_the_anchor_centred_box_is_no_longer_produced():
    """旧回退（以锚点为中心）的判据：盒子把锚点包在**里面**，且横向跨到锚点右侧。"""
    point = (-40.0, 25.0)
    occupied = _occupied_around(point)
    label = dc._label_at("RXD", point, (-1.0, 0.0), occupied)
    inside = (label.bbox[0] < point[0] < label.bbox[2]
              and label.bbox[1] < point[1] < label.bbox[3])
    assert not inside, label.bbox
    # 外侧：盒子整体在锚点左边，近边只差一个 TEXT_GAP
    assert label.bbox[2] == pytest.approx(point[0] - dc.TEXT_GAP)


# --------------------------------- 器件文字只看"画出来的东西"（本批真正解封的那处）


def test_pin_tips_are_not_a_wall_for_a_neighbouring_text():
    """脚端包围盒的角不是墙：有实测脚长的器件，邻字只避它的体框与脚线段。"""
    walls = dc._text_walls(_cap_profile(), SymbolPose(rotation=90, mirror=True),
                           (475.0, 715.0))
    bodies = [box for box in walls if box[2] - box[0] > 2.0 and box[3] - box[1] > 2.0]
    assert bodies == [(466.5, 704.5, 483.5, 725.5)]
    # 加上脚线段（1 单位粗），包围盒的空角不再出现
    assert (466.5, 695.0, 483.5, 735.0) not in walls
    assert len(walls) == 3, walls


def test_a_profile_that_states_no_pin_length_keeps_the_whole_box():
    """没说脚画多长 = 没量过的范围（052 §4），整个器件盒照旧当墙。"""
    walls = dc._text_walls(_cap_profile(pin_length=None),
                           SymbolPose(rotation=90, mirror=True), (475.0, 715.0))
    assert walls == [(466.5, 695.0, 483.5, 735.0)]


# --------------------------------------------- 文档带归属、几何摘要不带


def test_the_geometry_digest_ignores_which_part_a_label_names():
    """归属不是位置：写进文档（读回来还要按同一张图检查），不进 geometry 摘要。"""
    source = LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH)
    parts = [LayoutPart(part_id="U1", symbol_ref=CORE, symbol_hash=HASH, x=0.0,
                        y=0.0, reference="U1")]
    plan = LayoutPlan(source=source, parts=parts, labels=[
        LayoutLabel(net="RXD", text="RXD", x=0.0, y=0.0,
                    bbox=(0.0, 0.0, 10.0, 10.0), part_id="U1"),
    ])
    unowned = LayoutPlan(source=LayoutSource(circuit_sha256=HASH,
                                             presentation_sha256=HASH),
                         parts=parts, labels=[
        LayoutLabel(net="RXD", text="RXD", x=0.0, y=0.0,
                    bbox=(0.0, 0.0, 10.0, 10.0)),
    ])
    assert plan.geometry_sha256() == unowned.geometry_sha256()
    assert plan.to_jsonable()["labels"][0]["partId"] == "U1"
    assert "partId" not in unowned.to_jsonable()["labels"][0]
    assert LayoutPlan.from_dict(plan.to_jsonable()).labels[0].part_id == "U1"


# ------------------------------------------------------------- 出货规格本身


def test_the_ch340_specs_compile_with_their_labels_outside_the_core():
    """099 §二 的规格一个字不动：有候选、零硬违规、四条标签落在核心体框之外。"""
    circuit = CircuitSpec.from_dict(json.loads(
        (SPECS / "ch340_serial.circuit.json").read_text(encoding="utf-8")))
    sheet = PresentationSpec.from_dict(json.loads(
        (SPECS / "ch340_serial.presentation.json").read_text(encoding="utf-8")))
    book = load_library(SPECS / "ch340_serial.library.json")
    result = dc.compile(circuit, sheet, book,
                        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)))
    assert result.ok, result.render_failures()
    plan = result.candidates[0]
    assert plan.evidence.hard_violations == []

    core = plan.part("U1")
    profile = book[core.symbol_ref]
    body = dc._body_box(profile, SymbolPose(int(core.rotation), core.mirror),
                        (core.x, core.y))
    signals = {"TXD", "RXD", "D+", "D-"}
    labels = [item for item in plan.labels if item.net in signals]
    assert {item.net for item in labels} == signals
    for label in labels:
        assert label.part_id == "U1"
        assert label.bbox[2] <= body[0], (label.net, label.bbox, body)
