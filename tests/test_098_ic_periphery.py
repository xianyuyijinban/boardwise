"""098：第五种画法语法 `ic-periphery`——核心 IC 及其外围（离线半）。

这一批只做离线半：语法 + 编译器接入 + 场景 + SVG 预览（预览生成器在
`tools/098_previews.py`，真机落图归 099）。测试的分工，一句话一条：

1. **核心这条唯一不可推导的事实**（§一）：三来源 `modules[].core`（图纸自己的声明，
   新可选键）> intent `blocks[]`（合同）> 结构认（唯一严格最多脚）；三者冲突 →
   `circuit-invalid` 并列原文（谁错人裁），认不出 → `facts-missing` 点名两处可写处；
2. **角色判据**（§一）：`rail`/`gnd` 按 class 且读核心自己的脚，`bridge` 跨核心两个
   脚网、`shunt` 从一脚网回轨或地，簇按网交集分组（跨模块信号在核心自己的脚上出标签）；
3. **约束与义务**（§二）：`near`（挂脚件↔核心）、`adjacent`（同脚簇内相邻）、
   `left-of`/`right-of`（跨模块信号的**声明侧** + 图纸朝向）；义务 = `owned-branch`
   + `uniform-gnd`（**不**发 `direct-wire`：本语法的轨是供电引用，不是主干画法）；
4. **实测两处**（写进模块 docstring、理由钉在测试里）：(a) `near(挂脚件, 核心)` 这类
   pin 度量 kind 取的是两者共享网里 id 排序**第一个**——对 shunt 就是地，所以它量到的
   其实是整组的紧凑度；(b) 一网一成员的网络标签落在它那一脚的朝向上，而
   `_points_for_relation` 量不到网，所以声明侧靠**挂脚件**的侧向语句落进图里
   （编译器只会交出两个镜像候选，实测它们只差 compactness 一层）；
5. **场景**（§四）：CH340 样板、镜像、最小、多簇、核心歧义、混进模块的外人、长文字、
   窄区域、页级集成、核心来自 intent——每场景一条测试；
6. **零移动**（§四）：053b 21 / 056 18 / 088 14 / 088b 18 张既有场景的零移动在
   `evidence/098/scene_declaration.md` 里逐张申报（HEAD 树 vs 工作树逐文件 `cmp`）。

CircuitSpec / PresentationSpec / SymbolProfile 全部手写字面量，不建夹具文件；符号库
复用 053B 的 `library()`（同一颗 0402 只有一个定义），本批新增三颗形状：16 脚 SOP 的
核心、两脚晶振、四脚 USB 座。
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

import test_053b_drawcompiler as b053

from boardwise.core.circuitspec import (
    CIRCUIT_SPEC_VERSION,
    CircuitSpec,
    CircuitSpecError,
)
from boardwise.core.designintent import DesignIntent
from boardwise.core.geometry import transform_point
from boardwise.core.presentationspec import (
    GRAMMARS,
    PRESENTATION_SPEC_VERSION,
    PresentationSpec,
    PresentationSpecError,
)
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines import pagecompiler as pc
from boardwise.engines import readability
from boardwise.engines.grammar import base, ic_periphery
from boardwise.engines.grammar.base import (
    ADJACENT,
    DIRECT_WIRE,
    DrawingGrammar,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    UNIFORM_GND,
)

PROV = "verified_recipe"
AI = "ai_asserted"

#: 岳样板的两条供电。轨名用声明形态（`VCC`）是本仓库既有的命名约定。
RAIL = "VCC"
GND = "GND"
CORE = "U1"

#: 样板的四条跨模块信号：网名 →（`portRoles` 的方向，声明侧从该方向的
#: `sidePreferences` 读出）。UART 侧（TXD/RXD）朝 MCU、USB 数据对（D+/D−）朝 USB 座，
#: 两侧相反，所以两个方向名也必须不同——`PORT_DIRECTIONS` 里没有 bidirectional，
#: USB 数据对按"这个模块接口的另一端"记作 `load`。
SIGNALS: tuple[tuple[str, str, str], ...] = (
    ("TXD", "output", "left"),
    ("RXD", "input", "left"),
    ("D+", "load", "right"),
    ("D-", "load", "right"),
)

#: 样板每个信号对应的核心脚位（spec token）。
SIGNAL_TOKENS: dict[str, str] = {"TXD": "2", "RXD": "3", "D+": "14", "D-": "13"}

#: 长文字场景用同一张样板，只把网名与器件值换长（§四.7）。
LONG_SIGNALS: tuple[tuple[str, str, str], ...] = (
    ("TXD_TO_MCU_HOST", "output", "left"),
    ("RXD_FROM_MCU_HOST", "input", "left"),
    ("USB_DATA_PLUS_HOST", "load", "right"),
    ("USB_DATA_MINUS_HOST", "load", "right"),
)


# --------------------------------------------------------------- 器件库夹具


def pins(rows) -> list[SymbolPin]:
    return [
        SymbolPin(number=number, tip=tip, name=name, direction=direction)
        for number, name, tip, direction in rows
    ]


def other_side(direction: str) -> str:
    """对侧：左右互换、上下互换（镜像一颗符号时每个脚的朝向都走这一步）。"""
    return {
        "left": "right", "right": "left", "up": "down", "down": "up",
    }[direction]


#: 核心 IC 的脚位（手写形状，不是数据手册的复制）：地在下、电源在上、UART 与晶振在左、
#: V3 与 USB 数据对在右。**这个形状是画法的一部分**：挂脚件落在哪一侧，由它自己那一脚
#: 的朝向决定（`drawcompiler._branch_offset_direction`），所以样板把同类件放在同侧，
#: 整组才读得紧凑——实测 `near(挂脚件, 核心)` 量的是共享网里排第一的那个网（对 shunt
#: 就是地），它量到的正是"整组紧凑"。
CORE_PINS: tuple[tuple[str, str, tuple[float, float], str], ...] = (
    ("1", "GND", (0.0, -110.0), "down"),
    ("2", "TXD", (-110.0, 50.0), "left"),
    ("3", "RXD", (-110.0, 30.0), "left"),
    ("4", "XI", (-110.0, 10.0), "left"),
    ("5", "XO", (-110.0, -10.0), "left"),
    ("6", "SIG2", (-110.0, -30.0), "left"),
    ("7", "SIG3", (-110.0, -50.0), "left"),
    ("16", "VCC", (0.0, 110.0), "up"),
    ("14", "D+", (110.0, 40.0), "right"),
    ("13", "D-", (110.0, 20.0), "right"),
    ("15", "V3", (110.0, -60.0), "right"),
)


def core_symbol(ref: str = "SOIC-16-CORE", *, mirrored: bool = False) -> SymbolProfile:
    """16 脚 SOP 核心的**手写**形状：体 140x160，脚从体边再出 40。"""
    rows = (
        [
            (number, name, (-tip[0], tip[1]), other_side(direction))
            for number, name, tip, direction in CORE_PINS
        ]
        if mirrored else list(CORE_PINS)
    )
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-70.0, -80.0, 70.0, 80.0), pins=pins(rows),
    )


def cap(ref: str = "C0402") -> SymbolProfile:
    """0402 电容：脚 ±40——与 053B 的同一形状，直接复用它的定义。"""
    return b053.capacitor(ref)


def crystal(ref: str = "XTAL-2P") -> SymbolProfile:
    """两脚晶振：脚 ±40，体比 0402 长一点。"""
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-10.0, -25.0, 10.0, 25.0),
        pins=b053._pins((("1", (0.0, 40.0), "up"), ("2", (0.0, -40.0), "down"))),
    )


def usb_socket(ref: str = "USB-A-4P") -> SymbolProfile:
    """四脚 USB 座：脚朝画内竖排、体在脚右边（页级场景的第二个模块）。"""
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-30.0, -50.0, 30.0, 50.0),
        pins=b053._pins((
            ("1", (-50.0, 40.0), "left"),
            ("2", (-50.0, 10.0), "left"),
            ("3", (-50.0, -10.0), "left"),
            ("4", (-50.0, -40.0), "left"),
        )),
    )


def library(**overrides: SymbolProfile) -> dict[str, SymbolProfile]:
    """053B 的库 + 本批三颗形状 + 本批两条轨的旗标（库完整，免得顺带踩缺旗回退）。"""
    book = b053.library()
    for profile in (
        core_symbol(), crystal(), usb_socket(), b053.flag("PWR-VCC"),
        b053.flag("PWR-GND"),
    ):
        book[profile.symbol_ref] = profile
    book.update(overrides)
    return book


# ------------------------------------------------------------- 手写 spec 构造


def part(part_id: str, symbol: str, value: str = "", provenance: str = PROV) -> dict:
    return {
        "id": part_id, "symbolRef": symbol, "value": value, "provenance": provenance,
    }


def net(net_id: str, cls: str, members: list[str], provenance: str = PROV) -> dict:
    return {
        "id": net_id, "class": cls, "members": list(members), "provenance": provenance,
    }


def circuit(parts: list[dict], nets: list[dict], nc=None) -> CircuitSpec:
    payload: dict = {"parts": parts, "nets": nets}
    if nc:
        payload["nc"] = list(nc)
    return CircuitSpec.from_dict(payload)


def presentation(grammar_ref: str = "ic-periphery", **overrides) -> PresentationSpec:
    payload: dict = {"grammarRef": grammar_ref}
    payload.update(overrides)
    return PresentationSpec.from_dict(payload)


# ------------------------------------------------------------ 岳样板的构造


#: 样板的器件：核心 U1 + 晶振 X1 + 两颗负载电容 + 去耦 C3 + V3 电容 C4。
SAMPLE_PARTS: dict[str, tuple[str, str]] = {
    "U1": ("SOIC-16-CORE", "CH340G"),
    "X1": ("XTAL-2P", "12MHz"),
    "C1": ("C0402", "22pF"),
    "C2": ("C0402", "22pF"),
    "C3": ("C0402", "100nF"),
    "C4": ("C0402", "100nF"),
}

SAMPLE_MODULE_PARTS: tuple[str, ...] = ("U1", "X1", "C1", "C2", "C3", "C4")


def sample_circuit(
    *,
    signals=SIGNALS,
    values: dict[str, str] | None = None,
    rail: str = RAIL,
    gnd: str = GND,
    extra_parts: list[dict] | None = None,
    extra_nets: list[dict] | None = None,
    core_symbol_ref: str = "SOIC-16-CORE",
) -> CircuitSpec:
    """岳样板那条电路：核心 + 晶振簇 + 去耦 + V3 电容 + 四条跨模块信号。

    成员写成 `<位号>.<脚号>`，所以换网名不动电路（§四.7 的长网名场景正是这么用的）。
    """
    parts = []
    for part_id, (symbol, value) in sorted(SAMPLE_PARTS.items()):
        if part_id == CORE:
            symbol = core_symbol_ref
        parts.append(part(part_id, symbol, (values or {}).get(part_id, value)))
    parts.extend(extra_parts or [])
    nets = [
        net(rail, "power", ["U1.16", "C3.1"]),
        net(gnd, "gnd", ["U1.1", "C1.2", "C2.2", "C3.2", "C4.2"]),
        net("XI", "signal", ["U1.4", "X1.1", "C1.1"]),
        net("XO", "signal", ["U1.5", "X1.2", "C2.1"]),
        net("V3", "signal", ["U1.15", "C4.1"]),
    ]
    for net_id, _direction, _side in signals:
        nets.append(net(net_id, "signal", [f"U1.{SIGNAL_TOKENS[net_id]}"])
                    if net_id in SIGNAL_TOKENS
                    else net(net_id, "signal", [f"U1.{_signal_token(signals, net_id)}"]))
    nets.extend(extra_nets or [])
    return circuit(parts, nets)


def _signal_token(signals, net_id: str) -> str:
    """Long-named signals keep the same pins, in the same order (§四.7)."""
    return list(SIGNAL_TOKENS.values())[
        [name for name, _direction, _side in signals].index(net_id)
    ]


def sample_presentation(
    *,
    signals=SIGNALS,
    core: str | None = CORE,
    declared: bool = True,
    module_parts: tuple[str, ...] = SAMPLE_MODULE_PARTS,
    sides: dict[str, str] | None = None,
    port_roles: dict[str, str] | None = None,
    module_id: str = "serial",
    **overrides,
) -> PresentationSpec:
    """样板的意图：四条信号声明侧 + 可选的 `modules[].core`。"""
    payload: dict = {
        "sidePreferences": sides if sides is not None else {
            direction: side for _net, direction, side in signals
        },
        "portRoles": (
            {net_id: direction for net_id, direction, _side in signals}
            if port_roles is None else dict(port_roles)
        ),
    }
    if declared:
        payload["modules"] = [{
            "id": module_id, "parts": list(module_parts),
            "role": "the USB-serial bridge", "grammarRef": "ic-periphery",
            **({"core": core} if core else {}),
        }]
    payload.update(overrides)
    return presentation(**payload)


def sample(*, sides: dict[str, str] | None = None, core: str | None = CORE,
           declared: bool = True, **overrides):
    """（电路, 表现）——样板场景的唯一出处，预览器也用它。

    `overrides` 里带 `module_parts` / `signals` / `port_roles` 的给表现，其余给电路。
    """
    presentation_keys = {
        "module_parts", "signals", "port_roles", "module_id", "sides",
    }
    for_circuit = {
        key: value for key, value in overrides.items()
        if key not in presentation_keys
    }
    for_presentation = {
        key: value for key, value in overrides.items()
        if key in presentation_keys
    }
    return (
        sample_circuit(**for_circuit),
        sample_presentation(sides=sides, core=core, declared=declared,
                            **for_presentation),
    )


def flipped_sides() -> dict[str, str]:
    """声明侧整体换侧：UART 侧朝右、USB 侧朝左（§四.2 的镜像）。"""
    return {direction: other_side(side) for _net, direction, side in SIGNALS}


def minimal_group():
    """§四.3 的（电路, 表现）：核心 + 1 去耦，核心由结构认（不声明、无合同）。"""
    circuit_spec = circuit(
        [part("U1", "SOIC-16-CORE", "CH340G"), part("C3", "C0402", "100nF")],
        [
            net(RAIL, "power", ["U1.16", "C3.1"]),
            net(GND, "gnd", ["U1.1", "C3.2"]),
            net("SIG", "signal", ["U1.4"]),
        ],
    )
    sheet = sample_presentation(declared=False, core=None, module_parts=(),
                                signals=(), port_roles={})
    return circuit_spec, sheet


def two_clusters():
    """§四.4 的（电路, 表现）：两个 bridge 各自带 shunt。"""
    circuit_spec = circuit(
        [
            part("U1", "SOIC-16-CORE", "DUAL"),
            part("X1", "XTAL-2P", "12MHz"),
            part("X2", "XTAL-2P", "32kHz"),
            part("C1", "C0402", "22pF"),
            part("C2", "C0402", "15pF"),
        ],
        [
            net(RAIL, "power", ["U1.16"]),
            net(GND, "gnd", ["U1.1", "C1.2", "C2.2"]),
            net("A1", "signal", ["U1.4", "X1.1", "C1.1"]),
            net("B1", "signal", ["U1.5", "X1.2"]),
            net("A2", "signal", ["U1.6", "X2.1", "C2.1"]),
            net("B2", "signal", ["U1.7", "X2.2"]),
        ],
    )
    sheet = sample_presentation(declared=False, core=None, module_parts=(),
                                signals=(), port_roles={}, sidePreferences={})
    return circuit_spec, sheet


def sample_core_ambiguity():
    """§四.5 的（电路, 表现）：两颗多脚件、没有声明 → 核心认不出来。"""
    circuit_spec = circuit(
        [
            part("U1", "SOIC-16-CORE", "one IC"),
            part("U2", "SOIC-16-CORE", "another IC"),
            part("C3", "C0402", "100nF"),
        ],
        [
            net(RAIL, "power", ["U1.16", "C3.1"]),
            net(GND, "gnd", ["U1.1", "C3.2", "U2.1", "U2.16"]),
            net("SIG", "signal", ["U1.4", "U2.4"]),
        ],
    )
    sheet = sample_presentation(core=None, module_parts=("U1", "U2", "C3"))
    return circuit_spec, sheet


def compile_module(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec,
                   *, budget: dc.CompileBudget | None = None, intent=None):
    return dc.compile(
        circuit_spec, presentation_spec, library(),
        budget if budget is not None else dc.CompileBudget(),
        intent=intent,
    )


def bind(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec, *, intent=None):
    return grammar.bind(
        circuit_spec, presentation_spec, library(), grammar_name="ic-periphery",
        intent=intent,
    )


def best(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec):
    result = compile_module(circuit_spec, presentation_spec)
    assert result.ok, result.render_failures()
    assert result.candidates, result.render_failures()
    return result.candidates[0]


def checked(plan, circuit_spec: CircuitSpec, presentation_spec: PresentationSpec):
    return readability.check(
        plan, circuit_spec, presentation_spec, library(),
        page_box=None, keepouts=(),
    )


def clean(plan, circuit_spec: CircuitSpec, presentation_spec: PresentationSpec) -> None:
    result = checked(plan, circuit_spec, presentation_spec)
    assert result.hard_violations == [], [
        item.render() for item in result.hard_violations
    ]


# ------------------------------------------------------------------- 读图助手


def pin(plan, member: str):
    point = b053.pin_point(plan, member, library())
    assert point is not None, f"{member} is not placed by this plan"
    return point


def placed(plan, part_id: str):
    found = plan.part(part_id)
    assert found is not None, f"{part_id} is not placed by this plan"
    return found


def label_for(plan, net_id: str):
    found = [item for item in plan.labels if item.net == net_id]
    assert found, f"net {net_id} carries no label on this plan"
    return found[0]


def wire_for(plan, net_id: str) -> list:
    return [item for item in plan.segments if item.net == net_id]


def touches(segments, point) -> bool:
    for item in segments:
        points = list(item.points)
        for start, end in zip(points, points[1:]):
            if b053._on_segment(point, start, end):
                return True
    return False


def roles(result) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for binding in result.bindings:
        out.setdefault(binding.role, []).append(binding.part_id)
    return out


def constraint_pairs(result) -> list[tuple[str, str, str]]:
    return [(item.kind, item.subject, item.object) for item in result.constraints]


def constraint_for(result, kind: str, subject: str, object_: str):
    for item in result.constraints:
        if (item.kind, item.subject, item.object) == (kind, subject, object_):
            return item
    raise AssertionError(f"no {kind}({subject}, {object_}) in this binding")


def core_evidence(result) -> str:
    return next(
        item.evidence for item in result.bindings if item.role == "core"
    )


def core_body(plan, symbol_ref: str = "SOIC-16-CORE"):
    """The core's body box as drawn (its own profile through its own pose)."""
    profile = library()[symbol_ref]
    origin = placed(plan, CORE)
    corners = [
        transform_point(x, y, rotation=origin.rotation, mirror=origin.mirror,
                        ox=origin.x, oy=origin.y)
        for x in (profile.body[0], profile.body[2])
        for y in (profile.body[1], profile.body[3])
    ]
    return (
        min(point[0] for point in corners), min(point[1] for point in corners),
        max(point[0] for point in corners), max(point[1] for point in corners),
    )


def side_of_core(plan, point) -> str:
    """Which side of the core's own body a point sits on (left/right/inside)."""
    box = core_body(plan)
    if point[0] < box[0]:
        return "left"
    if point[0] > box[2]:
        return "right"
    return "inside"


# ============================================================ 1. 事实通道与注册


def test_the_core_key_is_optional_and_an_old_module_round_trips_byte_for_byte():
    """§五 加键纪律：可选、缺省不写出——旧文档的规范 JSON 里没有这个键。"""
    spec = sample_presentation(core=None)
    module = spec.to_jsonable()["modules"][0]

    assert "core" not in module
    assert spec.modules[0].core == ""
    again = PresentationSpec.from_dict(spec.to_jsonable())
    assert json.dumps(again.to_jsonable(), sort_keys=True) == json.dumps(
        spec.to_jsonable(), sort_keys=True
    )
    assert again.sha256() == spec.sha256()


def test_a_stated_core_survives_the_round_trip_and_changes_the_digest():
    spec = sample_presentation()
    module = spec.to_jsonable()["modules"][0]

    assert module["core"] == CORE
    again = PresentationSpec.from_dict(spec.to_jsonable())
    assert again.modules[0].core == CORE
    assert again.sha256() == spec.sha256()
    assert again.sha256() != sample_presentation(core=None).sha256()


def test_the_spec_versions_are_not_bumped_by_an_optional_addition():
    """纯可选增量：升版本会把老文档一次全打回（§五）。"""
    assert PRESENTATION_SPEC_VERSION == 1
    assert CIRCUIT_SPEC_VERSION == 1


def test_the_module_schema_is_still_closed_and_names_the_key_it_refuses():
    with pytest.raises(PresentationSpecError) as caught:
        PresentationSpec.from_dict({
            "grammarRef": "ic-periphery",
            "modules": [{"id": "serial", "parts": ["U1"], "role": "the bridge",
                         "Core": "U1"}],
        })

    assert "Core" in str(caught.value)


def test_a_core_that_is_not_a_string_is_refused():
    with pytest.raises(PresentationSpecError) as caught:
        PresentationSpec.from_dict({
            "grammarRef": "ic-periphery",
            "modules": [{"id": "serial", "parts": ["U1"], "role": "the bridge",
                         "core": 7}],
        })

    assert "modules[0].core" in str(caught.value)


def test_ic_periphery_is_registered_on_every_face_a_grammar_must_be():
    """§五 注册面：实现名 / 类表 / 角色表 / spec 字面量 / 导出名。"""
    assert "ic-periphery" in grammar.NAMES
    assert grammar.NAMES == tuple(grammar._CLASSES)
    assert grammar.NAMES == tuple(grammar.ROLES_BY_GRAMMAR)
    assert grammar.NAMES == GRAMMARS
    assert grammar.NAMES[:4] == (
        "voltage-divider", "rc-lowpass", "ldo", "power-entry",
    ), "新语法追加在末尾：既有四个的名字与顺序不动"
    instance = grammar.grammar_for("ic-periphery", library())
    assert isinstance(instance, DrawingGrammar)
    assert instance.name == "ic-periphery"
    assert grammar.ROLES_BY_GRAMMAR["ic-periphery"] == (
        "core", "bridge", "shunt", "rail", "gnd",
    )
    assert "ic_periphery" in grammar.__all__


def test_the_spec_literal_and_the_implementation_name_are_one_string():
    spec = presentation()
    assert spec.grammar_ref == "ic-periphery"
    assert spec.grammar_ref in grammar.NAMES

    with pytest.raises(PresentationSpecError):
        presentation("ic_periphery")  # 拼法不一致就不是同一个字面量


def test_the_grammar_module_carries_no_scenario_specific_constant():
    """053 §六：语法表里不许出现场景专用常量（位号/值/封装/网名一个都不许）。

    查的是**代码里的字符串**：docstring 是给人读的说明、举例不算常量，所以走 `ast`
    取非 docstring 的 `Constant` 节点，而不是拿文本 grep 一遍（088 的钉法）。
    """
    source = pathlib.Path(ic_periphery.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(
            body[0].value, ast.Constant
        ):
            docstrings.add(id(body[0].value))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    comments = [line for line in source.splitlines() if line.strip().startswith("#")]
    for token in ("U1", "X1", "C1", "C115", "XI", "XO", "V3", "TXD", "RXD", "D+",
                  "D-", "VCC", "CH340", "SOIC", "12MHz", "22pF", "100nF", "XTAL",
                  "USB"):
        assert not any(token in value for value in literals), token
        assert not any(token in line for line in comments), token
    for value in literals:
        assert not re.search(r"scene\s*\d", value, re.IGNORECASE), value


def test_the_signal_and_side_vocabulary_is_the_specs_own():
    """语法不新增词汇：方向名来自 `PORT_DIRECTIONS`，侧名来自 `SIDES`。"""
    from boardwise.core.circuitspec import PORT_DIRECTIONS
    from boardwise.core.presentationspec import SIDES

    assert base.LEFT_OF == "left-of" and base.RIGHT_OF == "right-of"
    assert base.NEAR == "near" and base.ADJACENT == "adjacent"
    assert base.OWNED_BRANCH == "owned-branch" and base.UNIFORM_GND == "uniform-gnd"
    for _net, direction, side in SIGNALS:
        assert direction in PORT_DIRECTIONS
        assert side in SIDES
    assert "at-end" not in base.CONSTRAINT_KINDS, (
        "本语法不新增 kind：簇内相邻用 088b 实测过的 adjacent，信号朝向用既有的"
        "left-of/right-of"
    )


# ==================================================== 2. 核心三来源（§一/§三）


def test_scene_10_the_core_is_read_from_the_declaration_when_the_sheet_states_one():
    spec, pres = sample()
    result = bind(spec, pres)

    assert result.ok, result.failures
    assert roles(result)["core"] == [CORE]
    assert "modules[].core" in core_evidence(result)
    assert "modules[serial].core" in core_evidence(result)


def test_the_core_is_read_from_the_partition_when_nobody_states_one():
    """不声明、也没合同：唯一严格最多脚的结构认——判据写在 evidence 里。"""
    spec, pres = sample(declared=False, core=None)
    result = bind(spec, pres)

    assert result.ok, result.failures
    assert roles(result)["core"] == [CORE]
    evidence = core_evidence(result)
    assert "the partition" in evidence
    assert "9 stated pins" in evidence
    assert "more than every other part here" in evidence


def test_scene_10_the_intent_names_the_core_and_the_evidence_carries_the_contract():
    """§四.10：不给 `modules[].core`，核心来自合同 `blocks[]`，证据带合同出处。"""
    document = DesignIntent.from_dict({
        "blocks": [{
            "id": "serial", "kind": "usb-serial",
            "parts": ["U1", "X1", "C1"],
            "provenance": PROV,
        }],
    })
    spec, pres = sample(declared=False, core=None)
    result = bind(spec, pres, intent=document)

    assert result.ok, result.failures
    assert roles(result)["core"] == [CORE]
    evidence = core_evidence(result)
    assert "intent blocks[]" in evidence
    assert "blocks[id='serial'].parts" in evidence
    assert "['U1', 'X1', 'C1']" in evidence
    assert "kind='usb-serial'" in evidence
    assert f"provenance={PROV}" in evidence


def test_scene_10_the_intent_is_decisive_where_the_partition_cannot_read_a_core():
    """结构读不出（并列）时，合同是唯一说话的那一源，绑定照常成。"""
    spec = circuit(
        [
            part("U1", "SOIC-16-CORE", "CH340G"),
            part("U2", "SOIC-16-CORE", "CH340G"),
            part("C1", "C0402", "22pF"),
        ],
        [
            net(RAIL, "power", ["U1.16", "C1.1"]),
            net(GND, "gnd", ["U1.1", "C1.2", "U2.1", "U2.16"]),
            net("XI", "signal", ["U1.4"]),
            net("SIG2", "signal", ["U2.4"]),
        ],
    )
    sheet = presentation(modules=[{
        "id": "serial", "parts": ["U1", "U2", "C1"], "role": "two ICs",
        "grammarRef": "ic-periphery",
    }])
    document = DesignIntent.from_dict({
        "blocks": [{"id": "serial", "parts": ["U1", "C1"], "provenance": PROV}],
    })

    unstated = bind(spec, sheet)
    assert unstated.ok is False
    assert [item.category for item in unstated.failures] == [FAILURE_FACTS_MISSING]

    stated = bind(spec, sheet, intent=document)
    assert stated.ok, stated.failures
    assert roles(stated)["core"] == ["U1"]


def test_an_ai_asserted_contract_core_is_carried_out_and_marked_a_draft():
    """052 §4：照猜可以画，但不许被当成要求读——最弱依据一路带进 evidence。"""
    document = DesignIntent.from_dict({
        "blocks": [{"id": "serial", "parts": ["U1"], "provenance": AI}],
    })
    spec, pres = sample(declared=False, core=None)
    result = bind(spec, pres, intent=document)

    assert result.ok, result.failures
    assert roles(result)["core"] == [CORE]
    evidence = core_evidence(result)
    assert f"provenance={AI}" in evidence
    assert base.PROVENANCE_AI == AI


def test_a_contract_this_grammar_cannot_read_is_refused_not_ignored():
    from boardwise.engines.grammar.base import GrammarError

    spec, pres = sample(declared=False, core=None)
    with pytest.raises(GrammarError):
        bind(spec, pres, intent={"blocks": []})


def test_two_sources_that_disagree_are_refused_with_both_originals():
    """三来源冲突：并列原文，谁也不替谁裁判（§一）。"""
    spec = circuit(
        [
            part("U1", "SOIC-16-CORE", "declared one"),
            part("U2", "SOIC-16-CORE", "structural one"),
            part("C1", "C0402", "22pF"),
            part("C2", "C0402", "22pF"),
        ],
        [
            net(RAIL, "power", ["U1.16", "U2.16", "C1.1"]),
            net(GND, "gnd", ["U1.1", "U2.1", "C1.2", "C2.2"]),
            net("XI", "signal", ["U1.4", "U2.4", "C2.1"]),
            net("V3", "signal", ["U2.15"]),
            net("SIG2", "signal", ["U2.6"]),
        ],
    )
    # 图纸说 U1（4 个已连脚）是核心，而结构认的是唯一严格最多脚的 U2（5 个已连脚）。
    sheet = sample_presentation(
        core="U1", module_parts=("U1", "U2", "C1", "C2"),
    )
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "modules[serial].core = 'U1'" in failure.detail
    assert "the partition gives U2" in failure.detail
    assert "a person says which" in failure.detail
    assert "reconcile" in failure.action


def test_the_intent_and_the_partition_must_agree_too():
    """合同与结构也是同一件事实的两种说法：不一致同样并列原文。"""
    spec = circuit(
        [
            part("U1", "SOIC-16-CORE", "CH340G"),
            part("U2", "SOIC-16-CORE", "CH340G"),
            part("C1", "C0402", "22pF"),
        ],
        [
            net(RAIL, "power", ["U1.16", "C1.1"]),
            net(GND, "gnd", ["U1.1", "C1.2", "U2.1", "U2.16"]),
            net("XI", "signal", ["U1.4"]),
            net("V3", "signal", ["U1.15", "U2.4"]),
        ],
    )
    sheet = presentation(modules=[{
        "id": "serial", "parts": ["U1", "U2", "C1"], "role": "one IC",
        "grammarRef": "ic-periphery",
    }])
    document = DesignIntent.from_dict({
        "blocks": [{"id": "other", "parts": ["U2"], "provenance": PROV}],
    })
    result = bind(spec, sheet, intent=document)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "intent blocks[] says the core is 'U2'" in failure.detail
    assert "the partition says the core is 'U1'" in failure.detail


def test_a_declared_core_this_circuit_does_not_declare_is_circuit_invalid():
    spec, pres = sample(core="U9")
    result = bind(spec, pres)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "U9"
    assert "does not declare it" in failure.detail
    assert "U1=9" in failure.detail
    assert "write 'U9' as a part of the circuit" in failure.action


def test_a_declared_core_that_is_not_a_multi_pin_part_is_circuit_invalid():
    """声明的 core 不是多脚件：点名它实际是什么（§三）。"""
    spec = circuit(
        [part("U1", "C0402", "22pF"), part("C1", "C0402", "100nF")],
        [
            net(RAIL, "power", ["U1.1", "C1.1"]),
            net(GND, "gnd", ["U1.2", "C1.2"]),
        ],
    )
    sheet = sample_presentation(core="U1", module_parts=("U1", "C1"))
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "U1"
    assert "2 stated pin(s)" in failure.detail
    assert "1→" + RAIL in failure.detail and "2→" + GND in failure.detail
    assert "the part this drawing is really arranged around" in failure.action


def test_a_declared_core_outside_the_module_that_declares_it_is_refused():
    spec, pres = sample(core="U1", module_parts=("X1", "C1", "C2", "C3", "C4"))
    result = bind(spec, pres)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "modules[serial].parts does not list it" in failure.detail
    assert "add 'U1' to modules[serial].parts" in failure.action


def test_a_core_the_partition_cannot_read_names_both_places_to_write_it():
    """§三 第一条措辞：并列/无多脚件且无声明 → facts-missing 点名两处。"""
    spec = circuit(
        [part("U1", "SOIC-16-CORE", "one"), part("U2", "SOIC-16-CORE", "another")],
        [
            net(RAIL, "power", ["U1.16", "U2.16"]),
            net(GND, "gnd", ["U1.1", "U2.1"]),
            net("XI", "signal", ["U1.4", "U2.4"]),
        ],
    )
    sheet = sample_presentation(core=None, module_parts=("U1", "U2"))
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "2 parts share the highest pin count of 3" in failure.detail
    assert "which of them the others hang off is not in the partition" in (
        failure.detail
    )
    assert "modules[serial].core" in failure.action
    assert "intent blocks[]" in failure.action


def test_a_group_of_two_pin_parts_only_has_no_core_and_says_so():
    """一个粒子全是外围形状：没有多脚件，所以也没有核心（同样的 facts-missing）。"""
    spec = circuit(
        [part("U1", "C0402", "22pF"), part("U2", "C0402", "22pF")],
        [
            net(RAIL, "power", ["U1.1", "U2.1"]),
            net(GND, "gnd", ["U1.2", "U2.2"]),
        ],
    )
    sheet = sample_presentation(core=None, module_parts=("U1", "U2"))
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "every part here is the shape a peripheral has" in failure.detail
    assert "a peripheral is what hangs off a core" in failure.detail


# ============================================================ 3. 角色判据（§一）


def test_the_roles_are_read_from_the_partition_and_the_core_owns_them():
    spec, pres = sample()
    result = bind(spec, pres)

    assert result.ok, result.failures
    bound = roles(result)
    assert bound["core"] == [CORE]
    assert bound["rail"] == [RAIL]
    assert bound["gnd"] == [GND]
    assert bound["bridge"] == ["X1"]
    assert sorted(bound["shunt"]) == ["C1", "C2", "C3", "C4"]
    # As in 088: `rail` being a net role is the claim; being the *last* entry
    # was an accident of the table's size, and 113 appended to it (see
    # base.NET_ROLES's own comment).
    assert "rail" in base.NET_ROLES and not base.is_net_role("bridge")


def test_a_bridge_is_a_part_across_two_of_the_cores_pins_and_a_shunt_returns():
    """bridge 跨两个核心脚网（都不碰轨/地）；shunt 从一脚网回轨或地——两条都真成立。"""
    spec, pres = sample()
    result = bind(spec, pres)
    bindings = {item.part_id: item.evidence for item in result.bindings}

    assert "role=bridge" in bindings["X1"]
    assert "XI" in bindings["X1"] and "XO" in bindings["X1"]
    assert "role=shunt" in bindings["C1"]
    assert RAIL in bindings["C4"] and GND in bindings["C4"]
    assert "cluster" in bindings["C1"] and "cluster" in bindings["C4"]
    assert "core pins this part reads off: XI, XO" in bindings["X1"]
    assert "core pins this part reads off: GND, XI" in bindings["C1"], (
        "evidence 要点名这颗件真的读到了核心的哪几只脚网（曾经写成读 pin 号的集合，"
        "于是永远是 none——实测抓到的）"
    )


def test_a_decoupling_capacitor_across_the_rail_and_the_ground_is_a_shunt():
    """跨轨↔地的去耦也是 shunt（岳样板第三条支路）：两个网都是核心的脚网时按供电端读。"""
    spec, pres = sample()
    result = bind(spec, pres)
    evidence = next(
        item.evidence for item in result.bindings if item.part_id == "C3"
    )

    assert "role=shunt" in evidence
    assert "VCC" in evidence and GND in evidence
    assert "V3" not in evidence.split("cluster")[0]


def test_the_clusters_are_grouped_by_shared_pin_nets_and_not_by_any_name():
    """簇是结构可推的：晶振与共享它脚网的电容一簇，去耦与 V3 各自成簇。"""
    spec, pres = sample()
    result = bind(spec, pres)
    bindings = {item.part_id: item.evidence for item in result.bindings}

    assert "{C1, C2, X1} share the pin net(s) XI, XO" in bindings["X1"]
    assert "{C1, X1} share the pin net(s) XI" in bindings["C1"]
    assert "{C2, X1} share" in bindings["C2"] and "XO" in bindings["C2"]
    assert "stands in a cluster of its own" in bindings["C3"]
    assert "stands in a cluster of its own" in bindings["C4"]


def test_the_constraints_are_the_local_group_the_cluster_and_the_declared_sides():
    spec, pres = sample()
    result = bind(spec, pres)
    pairs = constraint_pairs(result)

    for part_id in ("X1", "C1", "C2", "C3", "C4"):
        assert (NEAR, part_id, CORE) in pairs
    assert (ADJACENT, "X1", "C1") in pairs
    assert (ADJACENT, "X1", "C2") not in pairs, (
        "另一颗负载电容挂在晶振的另一只脚上，与它不同行——实测：adjacent 的判据是"
        "两点只差沿画法轴那一段，而两只脚本身就差一个脚距，这个 kind 在这里不成立；"
        "簇的归属写在 evidence 的 cluster 节里"
    )
    for net_id, _direction, side in SIGNALS:
        kind = LEFT_OF if side == "left" else RIGHT_OF
        assert (kind, net_id, CORE) in pairs
    # 图纸朝向：脚朝哪一侧，挂脚件就落在哪一侧（两侧各有件，各说各话）。
    assert (LEFT_OF, "X1", CORE) in pairs
    assert (LEFT_OF, "C1", CORE) in pairs
    assert (LEFT_OF, "C2", CORE) in pairs
    assert (RIGHT_OF, "C4", CORE) in pairs
    assert not any(
        kind in ("above", "below") for kind, _s, _o in pairs
    ), "竖向的脚（电源脚上的去耦电容）不发明左右"


def test_the_part_side_statement_says_which_pin_and_which_way_it_leaves():
    """朝向语句的理由写清：核心的哪只脚、符号怎么画它、于是件落在哪一侧。"""
    spec, pres = sample()
    result = bind(spec, pres)

    reason = constraint_for(result, LEFT_OF, "C1", CORE).reason
    assert "SymbolProfile 'SOIC-16-CORE'" in reason
    assert "4" in reason and "XI" in reason and "leaves left" in reason
    assert "reads on the side its pin leaves by" in reason
    assert "098 sec.2" in reason


def test_the_obligations_are_the_owned_branches_and_one_ground_style():
    spec, pres = sample()
    result = bind(spec, pres)

    assert [(item.kind, item.nets) for item in result.obligations] == [
        (OWNED_BRANCH, (RAIL,)),
        (UNIFORM_GND, (GND,)),
    ]
    assert DIRECT_WIRE not in [item.kind for item in result.obligations], (
        "§二：本语法的轨是供电引用（旗/标签照 069 既有规则走），不是主干画法——"
        "它不承诺实体线，power-entry 才承诺"
    )
    owned = result.obligation_for(OWNED_BRANCH)
    assert "X1" in owned.reason and CORE in owned.reason


def test_the_declared_side_of_a_signal_is_what_the_kind_says():
    """声明侧驱动 kind：同一张电路，换侧就换 kind（语法不发明方向）。"""
    spec = sample_circuit()
    stated = bind(spec, sample_presentation())
    flipped = bind(spec, sample_presentation(sides=flipped_sides()))

    for net_id, _direction, side in SIGNALS:
        assert (LEFT_OF if side == "left" else RIGHT_OF, net_id, CORE) in (
            constraint_pairs(stated)
        )
    for net_id, _direction, side in SIGNALS:
        assert (LEFT_OF if side == "right" else RIGHT_OF, net_id, CORE) in (
            constraint_pairs(flipped)
        )


def test_a_signal_with_no_declared_direction_gets_no_orientation():
    """缺省不是声明（052 §4）：没写 portRoles 的网，语法一个 kind 都不发。"""
    spec = sample_circuit()
    pres = sample_presentation(port_roles={})
    result = bind(spec, pres)

    assert result.ok, result.failures
    names = {name for name, _direction, _side in SIGNALS}
    assert not any(
        item.kind in (LEFT_OF, RIGHT_OF) and item.subject in names
        for item in result.constraints
    )
    assert "no declared direction" in core_evidence(result)


def test_the_reading_of_a_drawings_orientation_is_stated_in_the_evidence():
    """图纸朝向写成证据：声明侧与符号自己的脚一致 → 按符号画；不一致 → 转过来画。"""
    spec = sample_circuit()
    plain = bind(spec, sample_presentation())
    flipped = bind(spec, sample_presentation(sides=flipped_sides()))

    for result, word in ((plain, "as the symbol has it"), (flipped, "turned round")):
        evidence = core_evidence(result)
        assert "the drawing's orientation" in evidence
        assert word in evidence


def test_declared_sides_that_no_single_orientation_can_hold_are_said_not_guessed():
    """两个声明互不相容（脚都在同一侧却说两侧）：写进证据，不拒绝。

    实测理由：声明侧是关于**页面**的话（哪个模块在哪一边），单独编译一个模块没有页面
    可以对照；把互不相容的声明判成电路错误就是 R2 的假警报。
    """
    spec = sample_circuit()
    sides = {direction: side for _net, direction, side in SIGNALS}
    sides["output"] = "right"  # TXD 的脚在左侧，却说它朝右
    result = bind(spec, sample_presentation(sides=sides))

    assert result.ok, result.failures
    evidence = core_evidence(result)
    assert "cannot be read from the declared cross-module signals" in evidence
    assert "a person's call" in evidence


def test_the_core_binding_carries_the_weakest_fact_and_not_a_false_draft():
    """052 §4：最弱依据要看得见，但"没写 provenance"不等于草稿。

    实测抓到的：核心那一行曾经把声明的空 provenance 也算进最弱链，于是每一张
    "图纸自己声明核心"的图都被读成 unstated。
    """
    spec, pres = sample()
    stated = bind(spec, pres)
    assert "provenance=verified_recipe" in core_evidence(stated)
    assert "provenance=unstated" not in core_evidence(stated)

    document = DesignIntent.from_dict({
        "blocks": [{"id": "serial", "parts": ["U1"], "provenance": AI}],
    })
    drafted = bind(spec, sample_presentation(declared=False, core=None),
                   intent=document)
    assert "provenance=ai_asserted" in core_evidence(drafted)


def test_bind_is_deterministic_byte_for_byte():
    spec, pres = sample()
    first, second = bind(spec, pres), bind(
        CircuitSpec.from_dict(spec.to_jsonable()),
        PresentationSpec.from_dict(pres.to_jsonable()),
    )

    assert first == second
    assert json.dumps(first.to_jsonable(), sort_keys=True) == json.dumps(
        second.to_jsonable(), sort_keys=True
    )


# ============================================================ 4. 拒绝措辞（§三）


def test_a_part_of_the_module_with_no_pin_of_the_core_is_circuit_invalid():
    """§三 第三条：模块里一颗两脚件不碰任何核心脚网 → 点名它实际连着谁。"""
    spec = sample_circuit(
        extra_parts=[part("R9", "R0402", "10k")],
        extra_nets=[
            net("SENSE", "signal", ["R9.1"]),
            net("BIAS", "signal", ["R9.2"]),
        ],
    )
    sheet = sample_presentation(
        module_parts=(*SAMPLE_MODULE_PARTS, "R9")
    )
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "R9"
    assert "touches no pin net of the core" in failure.detail
    assert "1→SENSE, 2→BIAS" in failure.detail
    assert "another module's parts are that module's business" in failure.detail
    assert "leave R9 to the module it belongs to" in failure.action


def test_a_part_of_another_module_is_not_read_as_a_stray():
    """别的模块的件由那个模块负责：不在本模块 parts 里就不点名。"""
    spec = sample_circuit(
        extra_parts=[part("R9", "R0402", "10k")],
        extra_nets=[
            net("SENSE", "signal", ["R9.1"]),
            net("BIAS", "signal", ["R9.2"]),
        ],
    )
    result = bind(spec, sample_presentation())

    assert result.ok, result.failures
    assert "R9" not in roles(result).get("shunt", [])
    assert "R9" not in roles(result).get("bridge", [])


def test_the_signals_of_a_partial_page_slice_are_still_read():
    """页级切片后，只有一个成员的核心网仍然是这张图的跨模块信号。"""
    spec = sample_circuit()
    full = bind(spec, sample_presentation())
    assert sorted(
        item.subject for item in full.constraints
        if item.kind in (LEFT_OF, RIGHT_OF) and item.subject in SIGNAL_TOKENS
    ) == sorted(SIGNAL_TOKENS)

    # 只留核心与晶振簇：C3/C4 与它们的网整条拿走，D+/D− 仍各只有核心那一个成员。
    trimmed = circuit(
        [
            part("U1", "SOIC-16-CORE", "CH340G"),
            part("X1", "XTAL-2P", "12MHz"),
            part("C1", "C0402", "22pF"),
            part("C2", "C0402", "22pF"),
        ],
        [
            net(RAIL, "power", ["U1.16"]),
            net(GND, "gnd", ["U1.1", "C1.2", "C2.2"]),
            net("XI", "signal", ["U1.4", "X1.1", "C1.1"]),
            net("XO", "signal", ["U1.5", "X1.2", "C2.1"]),
            net("TXD", "signal", ["U1.2"]),
            net("RXD", "signal", ["U1.3"]),
            net("D+", "signal", ["U1.14"]),
            net("D-", "signal", ["U1.13"]),
        ],
    )
    sheet = sample_presentation(module_parts=("U1", "X1", "C1", "C2"))
    result = bind(trimmed, sheet)

    assert result.ok, result.failures
    assert sorted(roles(result)["shunt"]) == ["C1", "C2"]
    assert sorted(
        item.subject for item in result.constraints
        if item.kind in (LEFT_OF, RIGHT_OF) and item.subject in SIGNAL_TOKENS
    ) == sorted(SIGNAL_TOKENS)


def test_a_missing_class_is_facts_missing_one_per_class():
    spec = sample_circuit()
    payload = spec.to_jsonable()
    for net_body in payload["nets"]:
        if net_body["id"] == GND:
            net_body["class"] = "signal"
    result = bind(CircuitSpec.from_dict(payload), sample_presentation())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "no net of class 'gnd'" in failure.detail
    assert "nets[].class" in failure.action


def test_a_supply_the_core_does_not_touch_is_facts_missing_naming_the_core():
    """类在页面上有、但核心不碰它：点名核心自己的脚，而不是笼统说缺类。"""
    spec = circuit(
        [
            part("U1", "SOIC-16-CORE", "CH340G"),
            part("C1", "C0402", "22pF"),
            part("CN1", "C0402", "22pF"),
        ],
        [
            net(RAIL, "power", ["CN1.1"]),
            net(GND, "gnd", ["U1.1", "C1.2"]),
            net("XI", "signal", ["U1.4", "C1.1"]),
            net("V3", "signal", ["U1.15"]),
        ],
    )
    result = bind(spec, sample_presentation(module_parts=("U1", "C1")))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert failure.subject == CORE
    assert "sits on no net of class 'power'" in failure.detail
    assert "the supply exists on this page, but not on this part" in failure.detail
    assert "state U1's supply pin" in failure.action


# ============================================================ 5. 场景（§四）


def test_scene_1_the_sample_compiles_into_a_cluster_two_supplies_and_four_labels():
    """§四.1：晶振簇（bridge + 两 shunt 相邻、贴 XI/XO 侧）+ 去耦贴 VCC 脚 +
    V3 电容贴 V3 脚 + 四条信号标签朝向正确 + 可读性零硬违规。"""
    spec, pres = sample()
    result = compile_module(spec, pres)

    assert result.ok, result.render_failures()
    plan = result.candidates[0]
    clean(plan, spec, pres)
    assert plan.evidence.grammar_findings == []
    assert sorted(item.text for item in plan.labels) == sorted(
        name for name, _direction, _side in SIGNALS
    ), "四条跨模块信号各出一张标签，别的网都是画出来的线"

    xi_pin = pin(plan, "U1.4")
    crystal = pin(plan, "X1.1")
    load = pin(plan, "C1.1")
    assert crystal[1] == load[1] == xi_pin[1], "三条都挂在 XI 这一行上"
    assert abs(crystal[0] - xi_pin[0]) < abs(load[0] - xi_pin[0]), (
        "晶振比负载电容更贴核心那只脚（adjacent 的那句话）"
    )
    assert side_of_core(plan, crystal) == "left"
    assert pin(plan, "C3.1")[0] == pin(plan, "U1.16")[0], "去耦贴电源脚"
    assert pin(plan, "C3.1")[1] > pin(plan, "U1.16")[1], "而且在电源脚的外侧"
    assert pin(plan, "C4.1")[1] == pin(plan, "U1.15")[1], "V3 电容与 V3 脚同一行"
    assert side_of_core(plan, pin(plan, "C4.1")) == "right"


def test_scene_1_the_four_signal_labels_land_on_the_sides_the_sheet_declares():
    """四条标签的朝向：声明侧（UART 朝 MCU、USB 数据对朝 USB 座）就是图上那一侧。

    实测：一网一成员的网络标签画在它那一脚的脚尖上，脚尖朝哪一侧由核心的**姿态**
    决定——所以声明侧是靠"件的侧向语句"把姿态定下来的（见语法 docstring）。
    """
    spec, pres = sample()
    plan = best(spec, pres)

    landed: dict[str, str] = {}
    for net_id, _direction, side in SIGNALS:
        label = label_for(plan, net_id)
        assert label.text == net_id
        landed[net_id] = side_of_core(plan, (label.x, label.y))
        assert landed[net_id] == side, net_id
    assert {item.text for item in plan.labels} == set(landed)
    assert {
        name for name, _direction, side in SIGNALS if side == "left"
    } == {name for name, side in landed.items() if side == "left"}
    assert {
        name for name, _direction, side in SIGNALS if side == "right"
    } == {name for name, side in landed.items() if side == "right"}


def test_scene_1_every_label_sits_on_the_core_pin_that_carries_it():
    """标签的锚点就是核心自己那只脚的脚尖：一网一成员就是"在这只脚上出一张标签"。"""
    spec, pres = sample()
    plan = best(spec, pres)

    for net_id, token in SIGNAL_TOKENS.items():
        label = label_for(plan, net_id)
        assert (label.x, label.y) == pin(plan, f"{CORE}.{token}"), net_id


def test_scene_1_the_wired_nets_touch_every_pin_they_name():
    """线画出来的网（XI/XO/V3/两条供电）真的连到自己的每一个成员脚上。"""
    spec, pres = sample()
    plan = best(spec, pres)

    for net_id, members in (
        ("XI", ("U1.4", "X1.1", "C1.1")),
        ("XO", ("U1.5", "X1.2", "C2.1")),
        ("V3", ("U1.15", "C4.1")),
        (RAIL, ("U1.16", "C3.1")),
        (GND, ("U1.1", "C1.2", "C2.2", "C3.2", "C4.2")),
    ):
        segments = wire_for(plan, net_id)
        assert segments, f"{net_id} is drawn as a conductor"
        for member in members:
            assert touches(segments, pin(plan, member)), member


def test_scene_1_the_rail_carries_its_069_flag_and_the_ground_one_style():
    """轨照 069 既有规则出旗（本语法不承诺实体线，但旗照常）；地一套样式到底。"""
    spec, pres = sample()
    plan = best(spec, pres)
    flags = [item for item in plan.power_symbols if item.net == RAIL]
    grounds = [item for item in plan.power_symbols if item.net == GND]

    assert len(flags) == 1 and flags[0].symbol_ref == "PWR-VCC"
    assert grounds and {item.symbol_ref for item in grounds} == {"PWR-GND"}
    assert flags[0].rotation in (0.0, 180.0) and all(
        item.rotation in (0.0, 180.0) for item in grounds
    ), "069 §7 / R9：旗竖直"
    assert plan.evidence.grammar_findings == []


def test_scene_2_flipping_the_declared_sides_turns_the_cluster_and_the_labels():
    """§四.2：sidePreferences 换侧 → 标签朝向与簇位置同步镜像。"""
    spec = sample_circuit()
    plain = sample_presentation()
    mirrored = sample_presentation(sides=flipped_sides())
    right, left = best(spec, plain), best(spec, mirrored)

    assert placed(right, CORE).mirror is False
    assert placed(left, CORE).mirror is True, "换侧后核心以转过来的姿态度量"
    assert pin(right, "X1.1")[0] < 0 < pin(left, "X1.1")[0], (
        "晶振簇跟着换到另一侧"
    )
    for net_id, _direction, side in SIGNALS:
        assert side_of_core(right, _label_anchor(right, net_id)) == side, net_id
        assert side_of_core(left, _label_anchor(left, net_id)) == (
            other_side(side)
        ), net_id
    clean(left, spec, mirrored)
    clean(right, spec, plain)


def _label_anchor(plan, net_id: str):
    label = label_for(plan, net_id)
    return (label.x, label.y)


def test_scene_2_the_mirrored_drawing_is_the_same_group_turned_round():
    """镜像不是另一张图：器件、标签数、义务一个不变，说话的那几个 kind 翻转。"""
    spec = sample_circuit()
    plain = sample_presentation()
    mirrored = sample_presentation(sides=flipped_sides())
    right, left = best(spec, plain), best(spec, mirrored)

    assert sorted(item.part_id for item in right.parts) == sorted(
        item.part_id for item in left.parts
    )
    assert len(right.labels) == len(left.labels) == 4
    assert [(item.kind, item.nets)
            for item in bind(spec, plain).obligations] == [
        (item.kind, item.nets) for item in bind(spec, mirrored).obligations
    ]
    for net_id, _direction, side in SIGNALS:
        kind = LEFT_OF if side == "left" else RIGHT_OF
        assert kind in [
            item.kind for item in bind(spec, plain).constraints
            if item.subject == net_id
        ]
        assert other_side_kind(kind) in [
            item.kind for item in bind(spec, mirrored).constraints
            if item.subject == net_id
        ]


def other_side_kind(kind: str) -> str:
    return RIGHT_OF if kind == LEFT_OF else LEFT_OF


def test_scene_3_the_minimal_group_is_a_core_and_one_decoupling_capacitor():
    """§四.3：核心 + 1 去耦；核心由结构认（不声明、无合同）。"""
    spec, pres = minimal_group()
    result = bind(spec, pres)
    assert result.ok, result.failures
    assert roles(result)["core"] == ["U1"]
    assert roles(result)["shunt"] == ["C3"]

    plan = best(spec, pres)
    assert len(plan.parts) == 2
    clean(plan, spec, pres)
    assert pin(plan, "C3.1")[0] == pin(plan, "U1.16")[0]
    assert [(item.kind, item.nets) for item in result.obligations] == [
        (OWNED_BRANCH, (RAIL,)), (UNIFORM_GND, (GND,)),
    ]


def test_scene_4_two_bridges_each_keep_their_own_cluster():
    """§四.4：两个 bridge 各自带 shunt（运放级形状预演）——簇间不许串。"""
    spec, pres = two_clusters()
    result = bind(spec, pres)

    assert result.ok, result.failures
    assert sorted(roles(result)["bridge"]) == ["X1", "X2"]
    assert sorted(roles(result)["shunt"]) == ["C1", "C2"]
    pairs = constraint_pairs(result)
    assert (ADJACENT, "X1", "C1") in pairs
    assert (ADJACENT, "X2", "C2") in pairs
    assert (ADJACENT, "X1", "C2") not in pairs
    assert (ADJACENT, "X2", "C1") not in pairs, "两簇之间不许串成一句相邻"
    bindings = {item.part_id: item.evidence for item in result.bindings}
    assert "{C1, X1}" in bindings["X1"]
    assert "{C2, X2}" in bindings["X2"]

    plan = best(spec, pres)
    clean(plan, spec, pres)
    assert plan.evidence.grammar_findings == []
    assert len(plan.parts) == 5


def test_scene_5_two_multi_pin_parts_with_no_declaration_are_facts_missing():
    """§四.5：核心歧义（两颗多脚件、无声明）→ facts-missing 点名声明处。"""
    spec, sheet = sample_core_ambiguity()
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "2 parts share the highest pin count of 3" in failure.detail
    assert "modules[serial].core" in failure.action
    assert "intent blocks[]" in failure.action


def test_scene_6_a_foreign_two_terminal_part_inside_the_module_is_refused():
    """§四.6：不碰核心网的两脚件混进模块 → circuit-invalid 点名。"""
    spec = sample_circuit(
        extra_parts=[part("R7", "R0402", "1k")],
        extra_nets=[
            net("LEDA", "signal", ["R7.1"]),
            net("LEDK", "signal", ["R7.2"]),
        ],
    )
    sheet = sample_presentation(module_parts=(*SAMPLE_MODULE_PARTS, "R7"))
    result = bind(spec, sheet)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "R7"
    assert "1→LEDA, 2→LEDK" in failure.detail
    assert "state R7's connections" in failure.action


def test_scene_7_long_values_and_long_net_names_stay_off_the_wires():
    """§四.7：长值/长网名不压线不穿体。"""
    spec = sample_circuit(
        signals=LONG_SIGNALS,
        values={"C1": "22pF/50V NPO", "C2": "22pF/50V NPO",
                "C3": "100nF/50V X7R", "C4": "100nF/50V X7R"},
    )
    pres = sample_presentation(signals=LONG_SIGNALS)
    plan = best(spec, pres)

    assert {item.text for item in plan.texts} >= {
        "22pF/50V NPO", "100nF/50V X7R", "CH340G",
    }
    assert {item.text for item in plan.labels} == {
        name for name, _direction, _side in LONG_SIGNALS
    }
    clean(plan, spec, pres)
    assert plan.evidence.grammar_findings == []


def test_scene_8_a_narrow_region_is_refused_with_the_measured_size_and_an_action():
    """§四.8：窄区域 → layout-unsat 如实拒绝。"""
    spec, pres = sample()
    result = compile_module(
        spec, pres, budget=dc.CompileBudget(page_box=(0.0, 0.0, 300.0, 200.0))
    )

    assert result.ok is False
    assert result.rejected, "a refusal has to say which variants were built and lost"
    failures = [
        item for item in result.failures
        if item.category == dc.FAILURE_LAYOUT_UNSAT
    ]
    assert failures
    assert "canvas units" in failures[0].detail
    assert "300 x 200" in failures[0].detail
    assert "enlarge the region" in failures[0].action


# ------------------------------------------------------- 9. 页级集成（§四.9）

PAGE_BOX = (0.0, 0.0, 1169.0, 826.0)


def page_circuit() -> CircuitSpec:
    """CH340 模块 + USB 座模块同页：D+/D− 跨模块、VBUS 是页面上的同一条轨。"""
    spec = sample_circuit()
    payload = spec.to_jsonable()
    payload["parts"].append(part("J1", "USB-A-4P", "USB"))
    for net_body in payload["nets"]:
        if net_body["id"] == RAIL:
            net_body["members"].append("J1.1")
        elif net_body["id"] == GND:
            net_body["members"].append("J1.4")
        elif net_body["id"] == "D+":
            net_body["members"].append("J1.2")
        elif net_body["id"] == "D-":
            net_body["members"].append("J1.3")
    return CircuitSpec.from_dict(payload)


def page_presentation(*, main_path: bool = False) -> PresentationSpec:
    """两个模块 +（可选）一条 mainPath 流：USB 供电给串口桥。"""
    return PresentationSpec.from_dict({
        "grammarRef": "ic-periphery",
        "sidePreferences": {direction: side for _n, direction, side in SIGNALS},
        "portRoles": {net_id: direction for net_id, direction, _side in SIGNALS},
        "modules": [
            {
                "id": "serial", "parts": list(SAMPLE_MODULE_PARTS),
                "role": "the USB-serial bridge", "grammarRef": "ic-periphery",
                "core": CORE,
            },
            {
                "id": "usb", "parts": ["J1"], "role": "the USB socket",
                "grammarRef": "ic-periphery",
                "presentation": {"sidePreferences": {"load": "left"}},
            },
        ],
        "flow": [{"from": "usb", "to": "serial", "mainPath": main_path}],
    })


def test_scene_9_cross_module_signals_are_named_at_both_ends_and_the_ground_flags():
    """§四.9：CH340 模块 + USB 座模块同页——D+/D− 跨模块走标签，供电走旗。

    没有 mainPath 边时，跨模块的网按 069 / 053 §7 的既有规则表达：电源与地是总线
    （旗），别的网各端署自己的名字（标签）。**069 v3 的行为一行未改**。
    """
    result = pc.compile_page(
        page_circuit(), page_presentation(), library(),
        pc.PageCompileBudget(page_box=PAGE_BOX),
    )

    assert result.ok, "\n".join(item.render() for item in result.failures)
    page = result.pages[0]
    kinds = page.port_kinds()
    assert kinds[RAIL] == {pc.PAGE_PORT_FLAG}, "电源是总线，两端出旗"
    assert kinds[GND] == {pc.PAGE_PORT_FLAG}, "地是旗（069 §7）"
    assert kinds["D+"] == {pc.PAGE_PORT_LABEL}
    assert kinds["D-"] == {pc.PAGE_PORT_LABEL}
    assert page.verdict != "fail"
    assert all(module.ok for module in result.modules.values()), (
        "两个模块各自都能编译"
    )


def test_scene_9_a_main_path_edge_draws_the_pairing_nets_as_whole_wires():
    """同一条边上标了 mainPath：电源轨走整条线（069 v3 的例外），地仍是旗。

    实测：`main_path_wire` 的例外是**边**级的——这条边上跨过去的每个网（这里还有
    D+/D−）都画成整条线，不是只有电源轨。069 v3 的例外没有被本批改动。
    """
    result = pc.compile_page(
        page_circuit(), page_presentation(main_path=True), library(),
        pc.PageCompileBudget(page_box=PAGE_BOX),
    )

    assert result.ok, "\n".join(item.render() for item in result.failures)
    page = result.pages[0]
    kinds = page.port_kinds()
    assert kinds[RAIL] == {pc.PAGE_PORT_WIRE}
    assert kinds["D+"] == {pc.PAGE_PORT_WIRE}
    assert kinds["D-"] == {pc.PAGE_PORT_WIRE}
    assert kinds[GND] == {pc.PAGE_PORT_FLAG}, "例外只对电源轨迹开，地永远不例外"
    rail_wires = wire_for(page.plan, RAIL)
    assert rail_wires, "rail 是画出来的导体，不是一个名字"
    rail_ports = [
        item for module in page.modules for item in module.ports if item.net == RAIL
    ]
    assert len(rail_ports) == 2 and all(
        touches(rail_wires, (item.x, item.y)) for item in rail_ports
    ), "rail 从一端的 port 通到另一端的 port"
    assert page.verdict != "fail"


def test_scene_9_the_page_slice_carries_the_declared_core():
    """页级切片必须带上 `modules[].core`（098 的编译器接入那处）。

    理由与 088b 的 `branchOrder`、088 的 `openInterfaces[].part` 相同：切片一丢，
    页里的模块就按结构读，而独立编译的同一条电路按声明读——同一张图两种画法。
    """
    circuit_spec, presentation_spec = page_circuit(), page_presentation()
    module = presentation_spec.module("serial")
    local_circuit, local_presentation = pc._module_view(
        circuit_spec, presentation_spec, module
    )

    assert local_presentation.modules[0].core == CORE
    assert local_presentation.modules[0].id == "serial"
    assert local_presentation.port_roles["D+"] == "load"
    local_result = dc.compile(
        local_circuit, local_presentation, library(), dc.CompileBudget()
    )
    assert local_result.ok, local_result.render_failures()
    assert placed(local_result.candidates[0], CORE).mirror is False

    # 切片之后 D+/D− 只剩核心那一个成员——它们仍是这张图的跨模块信号。
    assert local_circuit.net("D+").members == ["U1.14"]
    assert "J1" not in [item.id for item in local_circuit.parts]


def test_scene_9_the_usb_module_is_drawn_by_its_own_declared_side():
    """第二个模块的说明书：它的 USB 数据对外朝左（侧向由它自己的模块覆盖声明）。"""
    circuit_spec, presentation_spec = page_circuit(), page_presentation()
    module = presentation_spec.module("usb")
    local_circuit, local_presentation = pc._module_view(
        circuit_spec, presentation_spec, module
    )
    result = dc.compile(local_circuit, local_presentation, library(), dc.CompileBudget())

    assert result.ok, result.render_failures()
    plan = result.candidates[0]
    assert [item.part_id for item in plan.parts] == ["J1"]
    assert plan.labels, "USB 座自己的数据线在它的模块里也出标签"
