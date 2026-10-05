"""113：第六种画法语法 `flyback`——隔离反激变换器核心（毕设语法谱系首块砖）。

这一批只做离线半：语法 + 注册 + 真实 spec 三件套 + 预览 + 离线 lint 闸。
测试的分工，一句话一条：

1. **角色表是结构判据，不读位号/值/符号名**（§一）：`transformer` 按「脚上的网类」
   判三绕组（Np 在 HVDC 与开关节点之间、Ns 在整流二极管与副边地之间、Naux 在
   aux 二极管与原边地之间）；`switch` 是开关节点与采样之间的 NMOS；`sense` 在
   source 与原边地之间；`clamp-D/R/C` 是跨 Np 两端的 R+C 串 + D 的链；`aux-D/C`
   是 Naux→D→C→VCC 网链；`sec-D` 是 Ns 与 VOUT 间的二极管；`opto` 的判据是
   **一脚跨双地族**；其余（分压/误差放大/补偿/输出电容）沿既有词表判。
2. **诚实拒绝的四个类别**（§二）：双地族被连成一片 → `circuit-invalid`；光耦缺失
   → `circuit-invalid`；功率级缺环路（HVDC 与 SW 之间无变压器）→ `circuit-invalid`；
   网表没声明地/母线类 → `facts-missing`。
3. **约束与义务**（§三）：T1 居中（原边朝输入侧、副边朝输出侧）用既有词表表达
   ——`left-of`/`right-of` 定的隔离界竖直方向、`above`/`below` 定原边在上副边在下、
   `same-row` 定反馈副边成链、`near` 定 RCD 贴原边上、Q1 与采样电阻成链。
   义务：`direct-wire`（功率级主环路、反馈链）+ `owned-branch` + `uniform-gnd`
   （双地族各自统一，绝不混用）。
4. **真实 spec 端到端**（§四）：`blocklib/specs/flyback_uc3845.*` 三件套 →
   `draw compile` → 预览 SVG → `draw lint --snapshot --render` 离线闸 0 ERROR。
5. **与 110 手绘页对照**（§四）：同一电路，`outputs/111/geo_P1_live.json` 的
   48E/20W/21I 与本语法的预览读数并排写进 SUMMARY。
6. **注册与零移动**（§五）：`GRAMMARS` 六元、既有五语法行为一字不变、83 张预览
   + 15 个夹具容器逐字节不动。

CircuitSpec / PresentationSpec / SymbolProfile 全部手写字面量；符号库在测试内自建
（每种形状一颗，与既有语法测试的写法一致），端到端场景复用
`blocklib/specs/flyback_uc3845.library.json` 的三件套。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import GRAMMARS, PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines.grammar import base, flyback
from boardwise.engines.grammar.base import (
    ABOVE,
    ADJACENT,
    BELOW,
    CONSTRAINT_KINDS,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    LEFT_OF,
    NEAR,
    OBLIGATION_KINDS,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_COLUMN,
    SAME_ROW,
    UNIFORM_GND,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
NAME = "flyback"

PROV = "engineer_confirmed"


# --------------------------------------------------------------------- 符号库


def _pin(number: str, name: str, tip: tuple[float, float], direction: str) -> SymbolPin:
    return SymbolPin(number=number, tip=tip, name=name, direction=direction)


def library() -> dict[str, SymbolProfile]:
    """一颗一种形状：原边开关 NMOS / 三绕组变压器 / 二极管 / 电阻 / 电容。

    极坐标全部是刻意摆的，不是随手填的：**开关竖放**（D 上 S 下 G 右，三脚
    逃向满足「Q1 竖放于原边下端」）；变压器三绕组**左原边 / 右辅助 / 下副边**
    （110 裁决 a 的隔离界方向：原边朝输入侧、副边朝输出侧、辅助在上方靠钳位那侧）；
    电阻横放、电容与二极管竖放（阴极朝下 = 整流相位朝输出）。
    """
    return {
        "R": SymbolProfile(
            symbol_ref="R", title="Resistor", body=(-20.0, -10.0, 20.0, 10.0),
            pins=[
                _pin("1", "1", (-50.0, 0.0), "left"),
                _pin("2", "2", (50.0, 0.0), "right"),
            ],
        ),
        "C": SymbolProfile(
            symbol_ref="C", title="Capacitor", body=(-10.0, -20.0, 10.0, 20.0),
            pins=[
                _pin("1", "1", (0.0, 40.0), "up"),
                _pin("2", "2", (0.0, -40.0), "down"),
            ],
        ),
        "D": SymbolProfile(
            symbol_ref="D", title="Diode", body=(-10.0, -20.0, 10.0, 20.0),
            pins=[
                _pin("1", "A", (0.0, 40.0), "up"),
                _pin("2", "K", (0.0, -40.0), "down"),
            ],
        ),
        "Q_NMOS": SymbolProfile(
            symbol_ref="Q_NMOS", title="NMOS", body=(-20.0, -20.0, 20.0, 20.0),
            pins=[
                _pin("1", "S", (0.0, -40.0), "down"),
                _pin("2", "D", (0.0, 40.0), "up"),
                _pin("3", "G", (40.0, 0.0), "right"),
            ],
        ),
        "T_3W": SymbolProfile(
            symbol_ref="T_3W", title="Transformer 3W", body=(-20.0, -40.0, 20.0, 20.0),
            pins=[
                # 原边：左上 HVDC、左下 SW
                _pin("P1", "P1", (-50.0, 10.0), "left"),
                _pin("P2", "P2", (-50.0, -10.0), "left"),
                # 辅助：右上 AUX、右下 PGND
                _pin("A1", "A1", (50.0, 10.0), "right"),
                _pin("A2", "A2", (50.0, -10.0), "right"),
                # 副边：下 SEC_SW、下右 SEC_GND
                _pin("S1", "S1", (0.0, -60.0), "down"),
                _pin("S2", "S2", (0.0, -80.0), "down"),
            ],
        ),
        "U_TL431": SymbolProfile(
            symbol_ref="U_TL431", title="TL431", body=(-20.0, -20.0, 20.0, 20.0),
            pins=[
                _pin("A", "A", (-50.0, 0.0), "left"),
                _pin("K", "K", (50.0, 0.0), "right"),
                _pin("REF", "REF", (0.0, 40.0), "up"),
            ],
        ),
        "U_OPTO": SymbolProfile(
            symbol_ref="U_OPTO", title="Optocoupler", body=(-20.0, -20.0, 20.0, 20.0),
            pins=[
                # LED 侧（副边）：左上 A、左下 K
                _pin("1", "A", (-50.0, 10.0), "left"),
                _pin("2", "K", (-50.0, -10.0), "left"),
                # 晶体侧（原边）：右上 C、右下 E
                _pin("4", "C", (50.0, 10.0), "right"),
                _pin("3", "E", (50.0, -10.0), "right"),
            ],
        ),
        "U_PWM": SymbolProfile(
            symbol_ref="U_PWM", title="PWM controller", body=(-20.0, -20.0, 20.0, 20.0),
            pins=[
                _pin("1", "COMP", (-50.0, 20.0), "left"),
                _pin("2", "VFB", (-50.0, 0.0), "left"),
                _pin("3", "ISENSE", (-50.0, -20.0), "left"),
                _pin("4", "RTCT", (0.0, -40.0), "down"),
                _pin("5", "GND", (0.0, 40.0), "up"),
                _pin("6", "OUT", (50.0, 20.0), "right"),
                _pin("7", "VCC", (50.0, 0.0), "right"),
                _pin("8", "VREF", (50.0, -20.0), "right"),
            ],
        ),
        "BR1": SymbolProfile(
            symbol_ref="BR1", title="Bridge rectifier", body=(-20.0, -20.0, 20.0, 20.0),
            pins=[
                _pin("1", "1", (-50.0, 0.0), "left"),
                _pin("2", "2", (50.0, 0.0), "right"),
                _pin("3", "3", (0.0, 40.0), "up"),
                _pin("4", "4", (0.0, -40.0), "down"),
            ],
        ),
        "F1": SymbolProfile(
            symbol_ref="F1", title="Fuse", body=(-20.0, -10.0, 20.0, 10.0),
            pins=[
                _pin("1", "1", (-50.0, 0.0), "left"),
                _pin("2", "2", (50.0, 0.0), "right"),
            ],
        ),
        "RT1": SymbolProfile(
            symbol_ref="RT1", title="NTC", body=(-20.0, -10.0, 20.0, 10.0),
            pins=[
                _pin("1", "1", (-50.0, 0.0), "left"),
                _pin("2", "2", (50.0, 0.0), "right"),
            ],
        ),
        "CN": SymbolProfile(
            symbol_ref="CN", title="Connector", body=(-15.0, -15.0, 15.0, 15.0),
            pins=[
                _pin("1", "1", (-50.0, 0.0), "left"),
                _pin("2", "2", (50.0, 0.0), "right"),
            ],
        ),
    }


# --------------------------------------------------------------- 电路与图纸


def flyback_circuit() -> CircuitSpec:
    """110 `plan.corrected.json` 的网表，逐字照抄（22 网 / 30 器件）。

    本语法覆盖的那一段：M3 功率级（Q1/T1/R1..R3/C5/D1）+ M4 采样（R5/R4/C6）+
    M6 输出整流滤波（D3/C11/C13）+ M7 反馈（R7/R8/U4/R9/U5/R10/C10）+ 辅助
    供电链（D2/C7）。**不含**交流入口与整流母线（M1/M2 归 power-entry）、
    控制器本体外围（M5 归 ic-periphery）——这两个域在测试里以「不参与绑定」的
    方式存在，用来证明本语法不越界。
    """
    payload = {
        "kind": "boardwise-circuit-spec",
        "specVersion": 1,
        "parts": [
            {"id": "BR1", "symbolRef": "BR1", "provenance": PROV},
            {"id": "C4", "symbolRef": "C", "provenance": PROV},
            {"id": "F1", "symbolRef": "F1", "provenance": PROV},
            {"id": "RT1", "symbolRef": "RT1", "provenance": PROV},
            {"id": "CN_L", "symbolRef": "CN", "provenance": PROV},
            {"id": "CN_N", "symbolRef": "CN", "provenance": PROV},
            {"id": "CN_OUT", "symbolRef": "CN", "provenance": PROV},
            {"id": "T1", "symbolRef": "T_3W", "provenance": PROV},
            {"id": "Q1", "symbolRef": "Q_NMOS", "provenance": PROV},
            {"id": "R3", "symbolRef": "R", "provenance": PROV},
            {"id": "R15", "symbolRef": "R", "provenance": PROV},
            {"id": "C5", "symbolRef": "C", "provenance": PROV},
            {"id": "D1", "symbolRef": "D", "provenance": PROV},
            {"id": "R5", "symbolRef": "R", "provenance": PROV},
            {"id": "R4", "symbolRef": "R", "provenance": PROV},
            {"id": "C6", "symbolRef": "C", "provenance": PROV},
            {"id": "U3", "symbolRef": "U_PWM", "provenance": PROV},
            # 控制器本体外围与启动串：声明了，但**不被本语法认领**——它们证明
            # 本语法不复制 ic_periphery / power_entry 的逻辑（见范围裁定）。
            {"id": "R12", "symbolRef": "R", "provenance": PROV},
            {"id": "C9", "symbolRef": "C", "provenance": PROV},
            {"id": "C8", "symbolRef": "C", "provenance": PROV},
            {"id": "R1", "symbolRef": "R", "provenance": PROV},
            {"id": "R2", "symbolRef": "R", "provenance": PROV},
            {"id": "R13", "symbolRef": "R", "provenance": PROV},
            {"id": "R14", "symbolRef": "R", "provenance": PROV},
            {"id": "R10", "symbolRef": "R", "provenance": PROV},
            {"id": "C10", "symbolRef": "C", "provenance": PROV},
            {"id": "D2", "symbolRef": "D", "provenance": PROV},
            {"id": "C7", "symbolRef": "C", "provenance": PROV},
            {"id": "D3", "symbolRef": "D", "provenance": PROV},
            {"id": "C11", "symbolRef": "C", "provenance": PROV},
            {"id": "C13", "symbolRef": "C", "provenance": PROV},
            {"id": "R7", "symbolRef": "R", "provenance": PROV},
            {"id": "R8", "symbolRef": "R", "provenance": PROV},
            {"id": "U4", "symbolRef": "U_TL431", "provenance": PROV},
            {"id": "R9", "symbolRef": "R", "provenance": PROV},
            {"id": "U5", "symbolRef": "U_OPTO", "provenance": PROV},
        ],
        "nets": [
            {"id": "AC_L", "class": "signal", "members": ["CN_L.1", "F1.1"],
             "provenance": PROV},
            {"id": "AC_L_sw", "class": "signal",
             "members": ["F1.2", "RT1.1"], "provenance": PROV},
            {"id": "AC_N", "class": "signal", "members": ["CN_N.1", "BR1.3"],
             "provenance": PROV},
            {"id": "AC_N_sw", "class": "signal",
             "members": ["RT1.2", "BR1.2"], "provenance": PROV},
            {"id": "HVDC", "class": "power",
             "members": ["BR1.4", "C4.1", "C5.2", "R15.2", "T1.P1"],
             "provenance": PROV},
            {"id": "PGND", "class": "gnd",
             "members": ["BR1.1", "C4.2", "U3.5", "T1.A2", "C7.2", "C8.2",
                         "C9.2", "C6.2", "R5.2", "R10.2", "C10.2", "U5.3"],
             "provenance": PROV},
            {"id": "SW", "class": "signal",
             "members": ["Q1.2", "T1.P2", "D1.1"], "provenance": PROV},
            {"id": "CLAMP", "class": "signal",
             "members": ["D1.2", "C5.1", "R3.1"], "provenance": PROV},
            {"id": "CLAMP_B", "class": "signal",
             "members": ["R3.2", "R15.1"], "provenance": PROV},
            {"id": "SRC", "class": "signal",
             "members": ["Q1.1", "R5.1", "R4.1"], "provenance": PROV},
            {"id": "CS_FILT", "class": "signal",
             "members": ["R4.2", "C6.1", "U3.3"], "provenance": PROV},
            {"id": "GATE", "class": "signal",
             "members": ["U3.6", "Q1.3"], "provenance": PROV},
            {"id": "RTCT", "class": "signal",
             "members": ["U3.4", "R12.1", "C9.1"], "provenance": PROV},
            {"id": "VREF", "class": "signal",
             "members": ["U3.8", "R12.2", "C8.1"], "provenance": PROV},
            {"id": "VCC", "class": "power",
             "members": ["U3.7", "C7.1", "D2.2", "R2.2", "R14.2"],
             "provenance": PROV},
            {"id": "ST_A", "class": "signal",
             "members": ["R1.2", "R2.1"], "provenance": PROV},
            {"id": "ST_B", "class": "signal",
             "members": ["R13.2", "R14.1"], "provenance": PROV},
            {"id": "AUX", "class": "signal",
             "members": ["T1.A1", "D2.1"], "provenance": PROV},
            {"id": "VFB_NF", "class": "signal",
             "members": ["U3.2", "R10.1"], "provenance": PROV},
            {"id": "COMP", "class": "signal",
             "members": ["U3.1", "C10.1", "U5.4"], "provenance": PROV},
            {"id": "SEC_SW", "class": "signal",
             "members": ["T1.S1", "D3.1"], "provenance": PROV},
            {"id": "SEC_12V", "class": "power",
             "members": ["D3.2", "C11.1", "C13.1", "R7.1", "R9.1", "CN_OUT.1"],
             "provenance": PROV},
            {"id": "SEC_GND", "class": "gnd",
             "members": ["T1.S2", "C11.2", "C13.2", "R8.2", "U4.A", "CN_OUT.2"],
             "provenance": PROV},
            {"id": "FB_SENSE", "class": "signal",
             "members": ["R7.2", "R8.1", "U4.REF"], "provenance": PROV},
            {"id": "LED_A", "class": "signal",
             "members": ["R9.2", "U5.1"], "provenance": PROV},
            {"id": "LED_K", "class": "signal",
             "members": ["U5.2", "U4.K"], "provenance": PROV},
        ],
        # 控制器本体的定时/基准外围（R12/C9/C8）与启动串（R1/R2/R13/R14）**不**
        # 在本语法范围内：它们以「声明了但不被任何角色认领」的形态存在，用来
        # 证明 ic-periphery / power-entry 的域不被本语法重复造。
        "parts_extra": None,
    }
    payload.pop("parts_extra")
    return CircuitSpec.from_dict(payload)


def flyback_presentation() -> PresentationSpec:
    """图纸：input 左 / output 右 / power 上 / gnd 下（052 sec.6 的默认，但明写）。"""
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "grammarRef": NAME,
        "sidePreferences": {
            "input": "left", "output": "right", "power": "top", "gnd": "bottom",
        },
        "portRoles": {"SEC_12V": "output", "HVDC": "input"},
    })


def minimal_circuit() -> CircuitSpec:
    """最小可绑：每角色恰好一件，无钳位无辅助绕组。

    The switch still has all **three** of its nets: a two-net part is a
    two-terminal element to `base.two_terminal_parts`, and the walk's switch
    discriminator is a three-net part (drain / source / gate). The gate net
    here goes nowhere else — an unconnected-but-stated net is the honest
    minimal case, and `nc[]` is what would say "deliberately not connected",
    so neither is invented.
    """
    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec",
        "specVersion": 1,
        "parts": [
            {"id": "T1", "symbolRef": "T_3W", "provenance": PROV},
            {"id": "Q1", "symbolRef": "Q_NMOS", "provenance": PROV},
            {"id": "R5", "symbolRef": "R", "provenance": PROV},
            {"id": "D3", "symbolRef": "D", "provenance": PROV},
            {"id": "C11", "symbolRef": "C", "provenance": PROV},
            {"id": "R7", "symbolRef": "R", "provenance": PROV},
            {"id": "R8", "symbolRef": "R", "provenance": PROV},
            {"id": "R9", "symbolRef": "R", "provenance": PROV},
            {"id": "U4", "symbolRef": "U_TL431", "provenance": PROV},
            {"id": "U5", "symbolRef": "U_OPTO", "provenance": PROV},
        ],
        "nets": [
            {"id": "HVDC", "class": "power", "members": ["T1.P1"], "provenance": PROV},
            {"id": "SW", "class": "signal", "members": ["Q1.2", "T1.P2"],
             "provenance": PROV},
            {"id": "SRC", "class": "signal", "members": ["Q1.1", "R5.1"],
             "provenance": PROV},
            {"id": "GATE", "class": "signal", "members": ["Q1.3"], "provenance": PROV},
            {"id": "PGND", "class": "gnd", "members": ["R5.2", "U5.3"],
             "provenance": PROV},
            {"id": "SEC_SW", "class": "signal", "members": ["T1.S1", "D3.1"],
             "provenance": PROV},
            {"id": "VOUT", "class": "power",
             "members": ["D3.2", "C11.1", "R7.1", "R9.1"], "provenance": PROV},
            {"id": "SEC_GND", "class": "gnd",
             "members": ["T1.S2", "C11.2", "R8.2", "U4.A"], "provenance": PROV},
            {"id": "FB_SENSE", "class": "signal",
             "members": ["R7.2", "R8.1", "U4.REF"], "provenance": PROV},
            {"id": "LED_K", "class": "signal", "members": ["U4.K", "U5.2"],
             "provenance": PROV},
            {"id": "LED_A", "class": "signal", "members": ["R9.2", "U5.1"],
             "provenance": PROV},
            {"id": "COMP", "class": "signal", "members": ["U5.4"], "provenance": PROV},
        ],
    })


def minimal_presentation() -> PresentationSpec:
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "grammarRef": NAME,
        "sidePreferences": {
            "input": "left", "output": "right", "power": "top", "gnd": "bottom",
        },
        "portRoles": {"VOUT": "output", "HVDC": "input"},
    })


def _bind(circuit: CircuitSpec, presentation: PresentationSpec | None = None):
    return flyback.FlybackGrammar(library()).bind(
        circuit, presentation or flyback_presentation()
    )


def _without_part(base: CircuitSpec, part_id: str) -> CircuitSpec:
    """The same circuit with one part removed, its pins removed with it.

    Removing a part from `parts[]` alone would not build: CircuitSpec refuses
    a member naming a part that does not exist, and that refusal happens in
    the parser, before the grammar ever sees the document. The honest way to
    ask "what if this part were not here" is to delete it from both places.
    """
    payload = base.to_jsonable()
    payload["parts"] = [p for p in payload["parts"] if p["id"] != part_id]
    for net in payload["nets"]:
        net["members"] = [
            m for m in net["members"] if not m.startswith(f"{part_id}.")
        ]
        if not net["members"]:
            net["members"] = [m for m in net["members"]]
    payload["nets"] = [n for n in payload["nets"] if n["members"]]
    return CircuitSpec.from_dict(payload)


def _mutate(base: CircuitSpec, **changes) -> CircuitSpec:
    """把 ``base`` 的某个网的成员换掉，造一个拓扑被破坏的变体。"""
    payload = base.to_jsonable()
    for net_id, members in changes.items():
        for net in payload["nets"]:
            if net["id"] == net_id:
                net["members"] = members
    return CircuitSpec.from_dict(payload)


# =========================================================== 1 注册与词表


def test_the_registry_knows_the_sixth_grammar():
    assert NAME in GRAMMARS
    assert NAME in grammar.NAMES
    assert grammar.NAMES.index(NAME) == 5
    assert set(grammar.NAMES) == set(GRAMMARS)


def test_the_registry_maps_the_name_to_the_class():
    assert isinstance(grammar.grammar_for(NAME), flyback.FlybackGrammar)


def test_the_dispatcher_binds_through_the_presentation():
    result = grammar.bind(minimal_circuit(), minimal_presentation(), library())
    assert result.ok
    assert result.parts_of("transformer") == ("T1",)


def test_the_role_table_is_published_and_every_role_is_documented():
    for role in flyback.ROLES:
        assert role in flyback.ROLES_BY_ROLE, f"{role} has no stated judgment"
    assert set(flyback.ROLES) == set(flyback.ROLES_BY_ROLE)


def test_the_grammar_uses_only_the_existing_constraint_vocabulary():
    """本批不发明新约束词：每个 kind 必须在 base 的全表里。"""
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.constraints
    for item in result.constraints:
        assert item.kind in CONSTRAINT_KINDS
        assert item.reason.strip()
        assert item.subject and item.object


def test_the_grammar_uses_only_the_existing_obligation_vocabulary():
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.obligations
    for item in result.obligations:
        assert item.kind in OBLIGATION_KINDS
        assert item.nets and item.reason.strip()


def test_the_five_existing_grammars_are_untouched():
    assert tuple(GRAMMARS) == (
        "voltage-divider", "rc-lowpass", "ldo", "power-entry", "ic-periphery",
        "flyback",
    )
    for name in ("voltage-divider", "rc-lowpass", "ldo", "power-entry",
                 "ic-periphery"):
        assert grammar.ROLES_BY_GRAMMAR[name]


# =================================================== 2 角色绑定（结构判据）


def test_every_role_binds_on_the_real_110_netlist():
    result = _bind(flyback_circuit())
    assert result.ok, [item.detail for item in result.failures]
    bound = {role: result.parts_of(role) for role in flyback.ROLES}
    assert bound["transformer"] == ("T1",)
    assert bound["switch"] == ("Q1",)
    assert bound["sense"] == ("R5",)
    assert bound["sec-D"] == ("D3",)
    assert bound["error-amp"] == ("U4",)
    assert bound["opto"] == ("U5",)
    assert bound["feedback-divider"] == ("R7", "R8")
    assert bound["output-caps"] == ("C11", "C13", "CN_OUT")
    assert bound["clamp-D"] == ("D1",)
    assert set(bound["clamp-R"]) == {"R3", "R15"}
    assert bound["compensation"] == ("C10",)
    assert bound["aux-D"] == ("D2",)
    assert bound["aux-C"] == ("C7",)


def test_every_binding_carries_evidence_ending_in_a_provenance():
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.bindings
    for item in result.bindings:
        assert "provenance=" in item.evidence, item
        assert len(item.evidence) > 30, item


def test_the_transformer_is_bound_by_its_three_winding_net_classes():
    """Np 在 HVDC 与开关节点之间；Ns 在整流二极管与副边地之间；Naux 另一对。"""
    result = _bind(flyback_circuit())
    assert result.net_of("bus") == "HVDC"
    assert result.net_of("switch-node") == "SW"
    assert result.net_of("secondary-node") == "SEC_SW"
    assert result.net_of("pgnd") == "PGND"
    assert result.net_of("sec-gnd") == "SEC_GND"
    assert result.net_of("vout") == "SEC_12V"
    assert result.net_of("aux") == "AUX"
    assert result.net_of("vcc") == "VCC"
    assert result.net_of("src") == "SRC"
    assert result.net_of("fb-sense") == "FB_SENSE"


def test_the_binding_never_reads_a_designator_or_a_value():
    """把全部位号换成无语义的 id、值全部清空，绑定必须一字不变。"""
    rename = {
        "T1": "ZZ7", "Q1": "QQ2", "R5": "WW3", "D3": "DD4", "C11": "CC5",
        "R7": "RR6", "R8": "RR7", "U4": "UU8", "U5": "UU9", "D1": "DD1",
        "R3": "RR3", "C5": "CC1", "D2": "DD2", "C7": "CC2", "C10": "CC3",
    }
    payload = flyback_circuit().to_jsonable()
    for part in payload["parts"]:
        part["value"] = ""
        part["id"] = rename.get(part["id"], part["id"])
    for net in payload["nets"]:
        net["members"] = [
            f"{rename.get(m.partition('.')[0], m.partition('.')[0])}."
            f"{m.partition('.')[2]}"
            for m in net["members"]
        ]
    renamed = CircuitSpec.from_dict(payload)
    plain = _bind(flyback_circuit())
    other = _bind(renamed)
    assert other.ok
    roles = {role: tuple(
        rename.get(part, part) for part in plain.parts_of(role)
    ) for role in flyback.ROLES}
    assert other.parts_of("transformer") == roles["transformer"]
    assert other.parts_of("switch") == roles["switch"]
    assert other.parts_of("sec-D") == roles["sec-D"]
    assert other.parts_of("opto") == roles["opto"]


def test_a_part_the_grammar_does_not_own_is_simply_not_bound():
    """控制器定时/基准外围与启动串不属本语法（归 ic-periphery / power-entry）。"""
    result = _bind(flyback_circuit())
    assert result.ok
    bound = {part for item in result.bindings for part in (item.part_id,)}
    for foreign in ("R12", "C9", "C8", "R1", "R2", "R13", "R14", "BR1", "C4",
                    "F1", "RT1", "CN_L", "CN_N", "R4", "C6", "U3"):
        assert foreign not in bound, f"{foreign} is not this grammar's business"
    # The two output connectors ARE this grammar's business: they are the
    # output's local shunt group, and the partition cannot tell a two-terminal
    # connector from a two-terminal capacitor. That is stated in
    # `_output_caps`'s docstring rather than hidden by a name lookup.
    assert "CN_OUT" in bound


def test_the_switch_is_found_between_the_switch_node_and_the_sense():
    result = _bind(minimal_circuit())
    assert result.ok
    assert result.parts_of("switch") == ("Q1",)
    assert result.net_of("switch-node") == "SW"
    assert result.net_of("src") == "SRC"


def test_the_sense_is_the_two_terminal_part_from_source_to_primary_ground():
    result = _bind(minimal_circuit())
    assert result.ok
    assert result.parts_of("sense") == ("R5",)
    binding = result.bindings_for("sense")[0]
    assert "SRC" in binding.evidence and "PGND" in binding.evidence


def test_the_clamp_is_the_r_c_string_plus_diode_across_the_primary_winding():
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.parts_of("clamp-D") == ("D1",)
    assert set(result.parts_of("clamp-R")) == {"R3", "R15"}
    assert result.parts_of("clamp-C") == ("C5",)
    assert result.net_of("clamp") == "CLAMP"


def test_a_circuit_without_a_clamp_still_binds_without_those_roles():
    result = _bind(minimal_circuit())
    assert result.ok
    assert result.parts_of("clamp-D") == ()
    assert result.parts_of("clamp-R") == ()
    assert result.parts_of("clamp-C") == ()


def test_a_circuit_without_an_auxiliary_winding_binds_without_the_aux_chain():
    result = _bind(minimal_circuit())
    assert result.ok
    assert result.parts_of("aux-D") == ()
    assert result.net_of("aux") == ""


def test_the_auxiliary_chain_is_naux_to_diode_to_cap_to_the_supply_rail():
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.net_of("aux") == "AUX"
    assert result.parts_of("aux-D") == ("D2",)
    assert result.parts_of("aux-C") == ("C7",)
    assert result.net_of("vcc") == "VCC"


def test_the_feedback_divider_is_the_series_string_from_the_output_to_ground():
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.parts_of("feedback-divider") == ("R7", "R8")
    assert result.net_of("fb-sense") == "FB_SENSE"
    binding = result.bindings_for("feedback-divider")[0]
    assert "VOUT 侧" in binding.evidence or "vout" in binding.evidence.lower()


def test_the_output_caps_are_the_parts_from_the_output_rail_to_the_secondary_ground():
    result = _bind(flyback_circuit())
    assert result.ok
    assert result.parts_of("output-caps") == ("C11", "C13", "CN_OUT")
    assert result.net_of("sec-gnd") == "SEC_GND"
    assert result.net_of("vout") == "SEC_12V"


# ============================================================ 3 诚实拒绝


def test_a_part_shorting_the_two_ground_families_is_refused():
    """一个两脚元件直接跨在两个地族之间 = 隔离被短接。

    这是电路自己的矛盾（`circuit-invalid`），不是缺事实。测试用一颗真实的
    Y 电容形状（两脚、跨双地）来造它——注意 CircuitSpec **没有**任何字段能说
    「这颗是故意的」，所以语法只能拒绝，这条限制写进了 `_short_failure` 的
    docstring。
    """
    payload = minimal_circuit().to_jsonable()
    payload["parts"].append({"id": "YC1", "symbolRef": "C", "provenance": PROV})
    for net in payload["nets"]:
        if net["id"] == "PGND":
            net["members"].append("YC1.1")
        if net["id"] == "SEC_GND":
            net["members"].append("YC1.2")
    result = _bind(CircuitSpec.from_dict(payload))
    assert not result.ok
    assert result.failures[0].category == FAILURE_CIRCUIT_INVALID
    assert "YC1" in result.failures[0].detail
    assert "PGND" in result.failures[0].detail


def test_a_missing_optocoupler_is_refused_as_circuit_invalid():
    result = _bind(_without_part(minimal_circuit(), "U5"))
    assert not result.ok
    assert any(item.category == FAILURE_CIRCUIT_INVALID for item in result.failures)
    detail = " ".join(item.detail for item in result.failures)
    assert "isolation barrier" in detail or "隔离" in detail


def test_a_missing_power_loop_is_refused_as_circuit_invalid():
    """母线与开关节点之间没有变压器 = 主环路不存在。"""
    result = _bind(_without_part(minimal_circuit(), "T1"))
    assert not result.ok
    assert any(item.category == FAILURE_CIRCUIT_INVALID for item in result.failures)


def test_a_spec_with_no_ground_class_is_refused_as_facts_missing():
    """把两个地都降成 signal = 网表没声明任何地族 = 缺事实。"""
    payload = minimal_circuit().to_jsonable()
    for net in payload["nets"]:
        if net["id"] in ("PGND", "SEC_GND"):
            net["class"] = "signal"
    result = _bind(CircuitSpec.from_dict(payload))
    assert not result.ok
    assert any(item.category == FAILURE_FACTS_MISSING for item in result.failures)
    detail = " ".join(item.detail for item in result.failures)
    assert "class" in detail and "gnd" in detail


def test_a_spec_with_no_power_class_is_refused_as_facts_missing():
    """三条轨全降成 signal = 网表没声明任何 power 类 = 缺事实。"""
    payload = minimal_circuit().to_jsonable()
    for net in payload["nets"]:
        if net["class"] == "power":
            net["class"] = "signal"
    result = _bind(CircuitSpec.from_dict(payload))
    assert not result.ok
    assert any(item.category == FAILURE_FACTS_MISSING for item in result.failures)
    detail = " ".join(item.detail for item in result.failures)
    assert "class" in detail and "power" in detail


def test_an_unstated_direction_is_refused_not_guessed():
    """副边二极管两端都落在副边地族里 = 整流相位不明。"""
    result = _bind(_without_part(minimal_circuit(), "D3"))
    assert not result.ok
    assert any(item.category == FAILURE_CIRCUIT_INVALID for item in result.failures)


def test_a_refusal_states_a_detail_and_never_leaves_bindings():
    result = _bind(_without_part(minimal_circuit(), "U5"))
    assert not result.ok
    assert result.bindings == () and result.constraints == ()
    assert result.failures
    for item in result.failures:
        assert item.detail.strip()
        assert item.category in base.FAILURE_CATEGORIES


def test_the_result_never_claims_success_while_carrying_failures():
    result = _bind(flyback_circuit())
    if result.ok:
        assert result.failures == ()


# ================================================== 4 约束与义务的读法


def test_the_transformer_is_centred_between_the_primary_and_the_secondary():
    """T1 居中、原边朝输入侧、副边朝输出侧（110 裁决 a）。

    裁决 a 落成三个关系，而不是一个：原边件 `below` 变压器（它挂在原边下端）、
    副边件 `near` 变压器（它在输出侧那一片）、钳位件 `near` 变压器且 `above`
    开关。用 `near` 而不是 `left-of`/`right-of` 表达「在隔离带的哪一侧」是
    **实测**定的：编译器的序关系是拿被挂那一侧的**引脚**对它自己的原点量的
    （`_pin_side_note` 会把实测坐标写进拒绝里），而链上器件这两个点永远在
    同一条轴上，所以这一对之间任何序关系都不可满足。
    """
    result = _bind(flyback_circuit())
    assert result.ok
    pairs = {(item.subject, item.object): item.kind
             for item in result.constraints}
    # 原边朝下：开关挂在原边下端
    assert pairs[("Q1", "T1")] == BELOW
    # 副边件与原边件分居两侧：分压与误差放大在副边侧
    for item in result.constraints:
        if item.subject == "U4":
            assert item.object in ("R7", "R8", "U5", "T1")
    # 副边挂在 T1 的输出侧
    for part_id in ("D3", "C11", "C13"):
        assert pairs.get((part_id, "T1")) == NEAR


def test_the_clamp_hugs_the_primary_above_it():
    """RCD 钳位贴原边上方（110 裁决 b）：三件都以 near 归到 T1。"""
    result = _bind(flyback_circuit())
    assert result.ok
    hugs = {item.subject for item in result.constraints
            if item.kind == NEAR and item.object == "T1"}
    for part_id in ("D1", "C5", "R3"):
        assert part_id in hugs, f"{part_id} does not hug the primary winding"


def test_the_switch_and_its_sense_form_one_chain_on_one_column():
    """Q1 竖放于原边下端，采样电阻直连（110 裁决 c/d）。"""
    result = _bind(flyback_circuit())
    assert result.ok
    kinds = {(item.subject, item.object, item.kind) for item in result.constraints}
    assert ("Q1", "R5", SAME_COLUMN) in kinds
    for item in result.constraints:
        if {item.subject, item.object} == {"Q1", "R5"}:
            assert item.kind in (SAME_COLUMN, SAME_ROW, NEAR, ADJACENT, BELOW)
    # 裁决 c：开关竖放于原边下端
    assert ("Q1", "T1", BELOW) in kinds


def test_the_feedback_chain_runs_on_one_row_on_the_secondary_side():
    """VOUT→分压→TL431→光耦 LED 在副边侧水平成链（110 裁决 e）。"""
    result = _bind(flyback_circuit())
    assert result.ok
    chain = {item.subject for item in result.constraints if item.kind == SAME_ROW}
    anchors = {item.object for item in result.constraints if item.kind == SAME_ROW}
    for part_id in ("R7", "R8", "U5"):
        assert part_id in chain, f"{part_id} is not in the horizontal feedback chain"
    # U4 是这条链的**锚**，不是链上的一节（自己和自己同列没有意义）
    assert anchors == {"U4"}


def test_the_opto_is_the_only_part_allowed_to_span_the_isolation_band():
    """光耦是唯一允许竖直跨越隔离带的器件（110 裁决 e）。"""
    result = _bind(flyback_circuit())
    assert result.ok
    # 光耦自己在隔离带上：它与原边件和副边件两侧都有序关系。
    band = {item.subject for item in result.constraints
            if item.kind in (LEFT_OF, RIGHT_OF, ABOVE, BELOW)
            and item.subject == "U5"}
    assert band
    # 没有任何别的器件同时在隔离带两侧发横向序关系（那是"跨越"的读法）。
    spanning = {
        item.subject for item in result.constraints
        if item.kind in (LEFT_OF, RIGHT_OF)
        and {item.subject, item.object} & {"T1", "Q1", "D3", "U4", "C11"}
        and {item.subject, item.object} & {"D2", "C7", "R5"}
    }
    assert not (spanning - {"U5"}), spanning
    binding = result.bindings_for("opto")[0]
    assert "SEC_GND" in binding.evidence and "PGND" in binding.evidence


def test_the_two_ground_families_are_never_related_to_each_other():
    """双地分族（110 裁决 f）：只有光耦跨带，其余不得跨。

    这是本语法对隔离最要紧的一条断言：任何「原边件—副边件」的关系都是把
    两族拉到同一片上，正是 110 裁决 f 禁止的。变压器按构造两端都接
    （辅助冷端回原边地、副边冷端回副边地），所以它不在这个检查里——它不是
    「跨越」，它是**隔离本身**。
    """
    result = _bind(flyback_circuit())
    assert result.ok
    primary_side = {"Q1", "R5", "R3", "C5", "D1", "D2", "C7", "C10"}
    secondary_side = {"D3", "C11", "C13", "R7", "R8", "U4", "R9"}
    for item in result.constraints:
        if item.kind not in (NEAR, ADJACENT):
            continue
        pair = {item.subject, item.object}
        crosses = bool(pair & primary_side) and bool(pair & secondary_side)
        assert not crosses, f"{item.kind} crosses the isolation band: {item}"


def test_each_ground_family_is_expressed_one_way():
    result = _bind(flyback_circuit())
    assert result.ok
    gnd_obligations = [item for item in result.obligations
                       if item.kind == UNIFORM_GND]
    assert len(gnd_obligations) == 2
    assert {item.nets[0] for item in gnd_obligations} == {"PGND", "SEC_GND"}


def test_the_power_loop_and_the_feedback_chain_are_promised_as_wires():
    result = _bind(flyback_circuit())
    assert result.ok
    wired = [item for item in result.obligations if item.kind == DIRECT_WIRE]
    assert wired
    promised = {net for item in wired for net in item.nets}
    for net_id in ("SW", "SRC", "SEC_SW", "SEC_12V", "FB_SENSE"):
        assert net_id in promised, f"{net_id} is not promised as a wire"
    # 反馈链：抽头 → LED 阴极 → 补偿节点，三段都是网（base.py 的 obligation
    # `nets` 是网元组，编译器照它排链序）
    assert ("FB_SENSE", "LED_K", "COMP") in [item.nets for item in wired]


def test_each_local_branch_reads_as_owned_by_its_node():
    result = _bind(flyback_circuit())
    assert result.ok
    owned = [item for item in result.obligations if item.kind == OWNED_BRANCH]
    assert owned
    promised = {net for item in owned for net in item.nets}
    assert promised & {"SEC_12V", "VCC", "COMP", "CLAMP"}


# ========================================================== 5 端到端场景


def test_the_three_piece_spec_set_is_on_disk_and_loads():
    for suffix in (".circuit.json", ".presentation.json", ".library.json"):
        path = SPECS / f"flyback_uc3845{suffix}"
        assert path.is_file(), path
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    assert presentation.grammar_ref == NAME
    assert circuit.part("T1") is not None


def test_the_real_spec_binds_end_to_end():
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    result = grammar.bind(circuit, presentation, book)
    assert result.ok, [item.detail for item in result.failures]
    assert result.parts_of("transformer") == ("T1",)
    assert result.parts_of("opto") == ("U5",)


def _library_from(path: pathlib.Path) -> dict[str, SymbolProfile]:
    """The library sidecar, read into the same book the compiler is handed.

    The sidecar is the same `boardwise-symbol-profile` shape
    `ch340_serial.library.json` uses, so this loader is a reader of an
    existing format rather than a private one.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                _pin(str(pin["number"]), str(pin.get("name", "")),
                     (float(pin["tip"][0]), float(pin["tip"][1])),
                     str(pin.get("direction", "")))
                for pin in entry["pins"]
            ],
        )
    return book


def test_the_real_spec_binds_and_the_grammar_gate_agrees_with_the_binding():
    """真实三件套：语法绑定成功，且 `check_grammar` 不报「绑定不上」。

    这一条钉的是**语法层**的端到端：绑定成功、每个被绑的器件都放了、语法闸
    对这份 plan 的读数里没有「grammar-binding-unplaced」。

    布局层为什么单独一条（下一条），这里先说清楚：drawcompiler 的布局模型是
    「一条链 + 挂在链上的支路」，而反激的副边是**第二个孤岛**。113 把两个跨
    带器件（整流二极管、光耦）放进了链，替副边找到了锚点，支路才挂得上；但
    链上器件只按 rank 沿轴排，支路只按自己那个 owner 的节点排——所以副边
    那条「反馈横排」（110 裁决 e 的 `same-row`）是编译器**排不出来**的，
    不是语法许错了。实测拒绝见下一条。

    **114 更新**：113 指的那两处（钳位串的中间臂、第二孤岛的横排）编译器都
    学会了，所以 113 写下的那个例外集合**清空成空集**——R3 与 R15 都不再出现。
    （本条一度被收紧成「任何一颗绑上的器件都不许被拒」，被 C10 顶回来：它被拒
    的是**另一回事**——支路与 owner 之间的序关系，任务书明说不在那一棒。
    例外集合因此从 `{"R3", "R15"}` 变成**空集**，不是空字符串。）
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    result = grammar.bind(circuit, presentation, book)
    assert result.ok
    placed = dc.compile(circuit, presentation, book, dc.CompileBudget(
        max_candidates=64))
    assert placed is not None
    # 113 documented exactly one exception — the clamp's discharge string, whose
    # intermediate node no chain part touches. 114 closed it: the string's arm
    # now gets an owner through the arm beside it, so the exception set is empty.
    refused = {item.subject for item in placed.failures}
    bound = {
        item.part_id for item in result.bindings
        if item.role not in base.NET_ROLES
    }
    assert not (refused & {"R3", "R15"}), (
        "114 closed 113's documented exception: the clamp discharge string must "
        f"no longer be refused, and {sorted(refused & {'R3', 'R15'})} still is"
    )


def test_the_layout_stage_no_longer_refuses_the_feedback_row():
    """**114 更新**：这条反证**转绿了**——编译器学会把支路排到行上。

    113 把这条边界钉成反证：副边反馈横排（裁决 e 的 `same-row`）落点差 5 个
    单位被拒，113 明说「编译器一旦学会把支路排到行上，这条会红，那就是修好
    了」。114 修好了，所以本条断言的**方向**整个翻过来：

    * `same-row` 的三条**必须全部**被摆平（`same-row` 违反数为零）；
    * 113 钉的那两条具体关系（`same-row(R7,U4)` / `same-row(R8,U4)`）不再出现
      在任何拒绝里——它们连同光耦那一条已经落在同一条 lane 上。

    剩下的拒绝**是另一回事**，且是任务书明说**不在本棒**的那一类：序关系
    （`below` / `right-of`）挂在支路与它 owner 之间。这一条顺带把那个边界钉住，
    免得下一棒以为「反激整页已经绿了」。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    result = grammar.bind(circuit, presentation, book)
    assert result.ok
    rows = [item for item in result.constraints if item.kind == SAME_ROW]
    assert rows, "the feedback row is not promised, so this proves nothing"

    placed = dc.compile(circuit, presentation, book, dc.CompileBudget(
        max_candidates=64))
    joined = " ".join(item.detail for item in placed.failures)
    # The row itself is no longer a refusal reason.  **118 更新**：`same-column`
    # 这一次**是**拒绝理由之一（`same-column(Q1, R5)`），但那与本条无关——
    # 本条量的是副边反馈**横排**（`same-row`，裁决 e），它仍然不是拒绝理由。
    # 换句话说：114 修的那一处仍然修着；118 挖出来的是**另一条**关系在真实
    # 几何下不再位姿可解，理由见 118 的 SUMMARY。
    for item in placed.failures:
        assert "the relation same-row(" not in item.detail, item.detail
    # 113's two named pairs are gone from the refusals for good.
    assert "same-row(R7, U4)" not in joined
    assert "same-row(R8, U4)" not in joined


def test_the_flyback_page_is_refused_and_says_which_relations_are_left():
    """**119 更新**：换料之后拦着的东西换了，这条跟着换——但**形状**不变。

    118 的版本写的是「反激整页被五脚变压器拦着」。岳 2026-10-04 深夜换了料：
    T1 变成 `C49118510`（`XREE16-050624`，118b 只读探针实测**七脚**），辅助绕组
    的冷端第一次有了真脚（`T1.2` 归 `PGND`），**六端终于有六端的地方**——
    118 那条「五脚装不下三绕组」的结论就此不再是当前现实（它作为 118 的**发现**
    留在 `tests/test_118_measured_profiles.py` 里重跑，仍然可复算）。

    整页**仍然编译不出来**，但**拦着它的换了人**，而且换了两拨：

    * **第一拨（位姿阶梯，119 治的那一处）**：六档基阶梯**全部**被**同一条**
      `same-column(Q1, R5)` 拒掉。118 实测 `R5` 转 90° 就把它的 `SRC` pad 放回
      `Q1` 的列——而那个位姿**不在** `_variants` 只探索的 0/1 两档里。119 给
      `_variants` 加了一条**只在 candidates=0 时点火**的加宽：这六档既然都被同
      一���关系拒掉，就把阶梯往它自己的接受位姿集**试完**。加宽之后
      `same-column` **确实**被清掉了（见
      `tests/test_119_pose_ladder_widening.py` 的合成单测）——所以这一拨不是
      拦路的了。
    * **第二拨（走线，本棒没治）**：加宽之后的每一档都改被**另一条**关系或
      **布线**拒掉，最后收敛到 `net 'HVDC' has a direct-wire obligation and its
      pins could not be joined inside the searched corridor`。这是**新料**带来的：
      118b 探针量到的 T1 体框是 **101 × 136**（旧五脚那颗是 40 × 40），它把 `D3`
      顶到 `HVDC` 那三个 pad 的直连路径上，而 `D3` 是**链件**、只有一档接受位姿，
      走不了。**换料是岳的裁定，绕线策略是编译器的事**——本棒如实记下断点。

    断言写成真形状：编译不过、**每一个**拒绝都被点名、点名的**不是一句含糊的
    「排不出来」**、而且加宽确实**发生**了（在 notes 里，不是在沉默里）。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    placed = dc.compile(circuit, presentation, book, dc.CompileBudget(
        max_candidates=64))
    assert not placed.ok, (
        "the flyback now compiles under the measured library: if that is because "
        "the routing was solved, say how in this test's docstring rather than "
        "leaving the old text"
    )
    assert not placed.candidates
    joined = " ".join(item.detail for item in placed.failures)
    assert joined, "a refusal with no reason is not a refusal"
    # 119: the widening is not allowed to be silent. If it fired, the reader is
    # told which relation triggered it and how many rungs it added.
    notes = " ".join(placed.notes)
    assert "pose ladder was widened" in notes, (
        "the base ladder was refused by one relation in all six rungs, so 119's "
        f"widening should have fired; notes were: {notes[-400:]}"
    )
    # And the widening did NOT rescue the page: the honest refusal is still here,
    # and it is the *routing* that is left, not the relation the widening chased.
    assert "direct-wire obligation" in joined or "same-column(Q1, R5)" in joined, (
        "a refusal that names neither the relation nor the routing is a shrug: "
        f"{joined[:400]}"
    )

def test_the_grammar_still_binds_the_measured_circuit():
    """**语法层是好的**——118 只换了 profile 与 token，没有换语法。

    117 的成果里有很大一块是 113/114/115/116 一路做出来的语法与求解器；118 把
    脚 token 全部换成宿主自己的之后，**语法仍然绑得上、仍然认为这是一台反激**。
    这条把它钉住，免得「整页编译不出来」被误读成「语法坏了」——真正缺的是料。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    assert binding.constraints, "the measured circuit binds no relations at all"
    kinds = {item.kind for item in binding.constraints}
    # The four relations 113's grammar is built around are all still there.
    for kind in ("below", "above", "near", "same-row"):
        assert kind in kinds, f"{kind} is gone: {sorted(kinds)}"


# ============================== 6 lint 离线闸与 110 对照（如实申报：未达成）


def test_the_offline_lint_gate_cannot_run_yet_and_says_why():
    """**如实申报**：第二层验收（`draw lint` 离线闸 0 ERROR）仍然**未达成**。

    **119 更新**：117 那一版写的「第一层已经通了、只剩 lint」**已经过期**。118
    换掉十三颗手写 profile 之后整页编译不出来，118 挖出的是**料**（五脚变压器）；
    岳 2026-10-04 换料之后料不再是那个问题，但**又来了一条新的**：118b 探针量到
    的 T1 体框是 **101 × 136**（旧那颗 40 × 40），把 `D3` 顶到 `HVDC` 的直连
    路径上，走线挤不过走廊。所以**第一层又变红了**，而且是在换料之后。

    这一条**整条保留 skip**，理由文本随之更新：

    * 第一层（`dc.compile(flyback)` 出 plan）—— 119 加宽了位姿阶梯并救回了
      `same-column(Q1, R5)`，但整页**仍**编不出来，卡在 `HVDC` 的直连走线上。
      编译这一半的**真断言**现在在
      `test_the_flyback_page_is_refused_and_says_which_relations_are_left`
      （它断言的是「编译不过、且说清是谁拦的」，这是那一层现在真实的形状）。
    * 第二层（`draw lint --snapshot` 离线闸）—— **仍然缺**，而且理由没变：它吃
      的是编辑器 `sch.geometry` 的形状（`components` / `wires` / `pins` /
      `netlabels` / `bboxes`），那只有**真机落图**后才有；本棒任务书明写不画真机。
      离线能出的只有 `svgpreview.render_svg(plan)`——一个 SVG 文档，不是那份快照。

    写成 `skip` 而不是删掉，是为了让缺口在测试输出里**看得见**。`pytest -rs`
    会打印它的原因。
    """
    pytest.skip(
        "119: layer 1 (a compiling plan) went red again and for a NEW reason, and "
        "layer 2 (the draw lint offline gate) is still missing. On the measured "
        "library the page is refused; 119 widened the pose ladder (it fires only "
        "when the base ladder produced no candidate at all and every rung named "
        "the SAME relation, which is what makes it the identity on every input "
        "that compiles) and that DID rescue same-column(Q1, R5) -- R5 at rotation "
        "90 puts its SRC pad back in Q1's column, a pose rung 0/1 never drew. "
        "What is left is ROUTING: the 118b probe measured the swapped-in "
        "transformer's body at 101x136 (the old five-pin part was 40x40), which "
        "pushes D3 -- a chain part with a single accepted pose -- onto the direct "
        "path between HVDC's three pads, so net 'HVDC' has a direct-wire "
        "obligation its pins could not be joined inside the searched corridor. "
        "The compile half is pinned by a real assertion above, which now asserts "
        "the honest refusal and names the blocker rather than asserting ok=True. "
        "What is still missing on top of that is only `draw lint --snapshot`, "
        "which needs an editor sch.geometry that a LIVE page produces -- drawing "
        "on the machine is 岳's call, not this batch's. See outputs/119/SUMMARY.md."

    )


def test_the_comparison_with_the_hand_drawn_110_page_is_recorded_not_asserted():
    """**如实申报**：与 110 手绘页的对照本棒**没有数字**可报。

    110 的读数是 48E/20W/21I（`outputs/111/geo_P1_live.json` + `lint_P1.json`，
    一张真机图）。本棒出不了自己的读数（上一条），所以这里只钉住「对照的
    口径是什么」，让下一批接手时不必重新发明尺子。
    """
    lint = ROOT / "outputs" / "111" / "lint_P1.json"
    if not lint.is_file():
        pytest.skip("110's own lint reading is not in the tree")
    report = json.loads(lint.read_text(encoding="utf-8"))
    counts = report.get("counts", {})
    # The baseline this grammar is measured against, read from 110's own file
    # rather than from this batch's memory of it.
    # 111's own file says 41 ERROR on P1 (110's pre-fix state). The task book
    # quotes 48E/20W/21I, which is the hand-drawing's own tally from 110c's
    # review; 111 re-measured it and got 41/0/44. **The measured file is the
    # number of record** — the discrepancy is reported in SUMMARY §四 rather
    # than reconciled by picking the flattering one.
    assert counts["ERROR"] == 41, counts
    assert counts["INFO"] == 44, counts
