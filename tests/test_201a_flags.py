"""201A：地/电源符号策略 —— 一地一符号，朝向由摆放决定。

本批把 `_Expression.style == "flag"` 的**地**网从「每只脚各挂一颗同名旗」改成
053 sec.7 / 088b 已经为「底轨」写下的那条形状：**地是一根轨道**（`_expression_style`
返回 `wire`），脚由轨道连成同一个节点（岳 060 的「重复脚默认接上」），而**一颗**
地符号挂在轨道远端（`_gnd_outlet_pin`）作为「这条网在这里接参考地」的标注。
电源轨（`power`）一个字没动，`gnd-outlet` 声明过的网仍归 088b 那条循环管。

验收（任务书 201A 的锚）：
- 合成页「一颗运放 + 两个 GND 脚 + 一个散热脚」：GND 旗数 N → 1，连通性不变
  （netlist 逐脚对拍，用**独立核验器** `readability.derive_netlist` 判分区）；
- 多域页（PGND/AGND）**绝不并地**：每个地网各一颗符号、各一个节点；
- 单脚地网（divider 三件套那种）与既有行为逐字一致；
- 旗仍竖直（069 sec.7），字形仍朝外（060 sec.3）。

规格与符号库全部本文件手写（053 §6 的纪律：不建夹具文件、绝不喂参考坐标）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability

import test_053b_drawcompiler as b053


ROOT = Path(__file__).resolve().parents[1]
DIVIDER = ROOT / "tests" / "fixtures" / "drawapply"


# ------------------------------------------------------------------ 符号库


def opamp(ref: str = "OPAMP-2GND-EP", *, across: bool = False) -> SymbolProfile:
    """一颗运放：两枚 GND 脚 + 一枚散热脚（任务书点名的合成件）。

    ``across=False``（默认）：三枚地脚都在**同一面**（下侧，真实封装里 8 脚运放
    的 GND 与裸露焊盘就是这么排的），轨道把它们直接连成一列。
    ``across=True``：两枚 GND 脚落在**对面**，中间隔着本体 —— 069 sec.2 当年正是
    为这种形状发明了「拆成两岛各打名字」，201A 把它改回 060 sec.2 的默认（重复脚
    接上）：轨道绕过本体把两脚连起来，符号仍然只有一颗。
    """
    if across:
        rows = (
            ("1", (70.0, 20.0), "right"),
            ("2", (-70.0, 20.0), "left"),
            ("3", (-70.0, -20.0), "left"),
            ("8", (-20.0, 60.0), "up"),
            ("4", (0.0, -60.0), "down"),
            ("11", (20.0, 60.0), "up"),
        )
    else:
        rows = (
            ("1", (70.0, 20.0), "right"),
            ("2", (-70.0, 20.0), "left"),
            ("3", (-70.0, -20.0), "left"),
            ("8", (0.0, 60.0), "up"),
            ("4", (-20.0, -60.0), "down"),
            ("11", (20.0, -60.0), "down"),
        )
    pins = [
        SymbolPin(
            number=number, tip=tip, name={"4": "GND", "11": "GND", "8": "V+"}.get(
                number, number
            ),
            direction=direction,
            electrical_role={"4": "GND", "11": "GND", "8": "V+"}.get(number, ""),
            role_source="pin-name",
        )
        for number, tip, direction in rows
    ]
    body = (-40.0, -35.0, 40.0, 35.0)
    if across:
        # The pad the far GND pin leaves through, so the body really sits between
        # the two ground pins (the shape 069 sec.2 was written for).
        body = (-40.0, -35.0, 40.0, 35.0)
    return SymbolProfile(symbol_ref=ref, title=ref, body=body, pins=pins)


def book(**overrides: SymbolProfile) -> dict[str, SymbolProfile]:
    library = b053.library()
    library["OPAMP-2GND-EP"] = opamp()
    library["OPAMP-GND-ACROSS"] = opamp("OPAMP-GND-ACROSS", across=True)
    for name in ("PWR-PGND", "PWR-AGND", "PWR-VCC"):
        library[name] = b053.flag(name)
    library.update(overrides)
    return library


# --------------------------------------------------------------- 手写 spec


def opamp_circuit(*, symbol: str = "OPAMP-2GND-EP", ground: str = "GND",
                  ground_cls: str = "gnd") -> object:
    """运放 + 一颗去耦电容：地网 4 只脚（两枚 GND + 一枚散热脚 + 电容脚）。"""
    return b053.circuit(
        [
            b053.part("U1", symbol, "OPA2GND"),
            b053.part("C1", "C0402", "100n"),
        ],
        [
            b053.net("VCC", "power", ["U1.8", "C1.1"]),
            b053.net(ground, ground_cls, ["U1.4", "U1.11", "C1.2"]),
            b053.net("INP", "signal", ["U1.3"]),
            b053.net("INN", "signal", ["U1.2"]),
            b053.net("OUT", "signal", ["U1.1"]),
        ],
    )


def opamp_presentation(**overrides) -> object:
    payload = {
        "modules": [
            {"id": "amp", "parts": ["U1", "C1"], "role": "the amplifier",
             "core": "U1"},
        ],
        "portRoles": {"INP": "input", "OUT": "output"},
    }
    payload.update(overrides)
    return b053.presentation("ic-periphery", **payload)


def compile_book(circuit, presentation, library=None, budget=None):
    result = dc.compile(
        circuit, presentation, library if library is not None else book(),
        budget if budget is not None else dc.CompileBudget(),
    )
    return result


def only_plan(circuit, presentation, library=None, budget=None):
    result = compile_book(circuit, presentation, library, budget)
    assert result.candidates, [f.detail for f in result.failures]
    return result.candidates[0]


def independent_check(plan, circuit, presentation, library=None):
    return readability.check(
        plan, circuit, presentation,
        library if library is not None else book(),
        page_box=None, grid=dc.DEFAULT_GRID,
    )


def derived_groups(plan, circuit, presentation, library=None) -> dict[str, set]:
    """The netlist the **checker** derives from the drawing alone."""
    derived = readability.derive_netlist(
        plan, library if library is not None else book()
    )
    out: dict[str, set] = {}
    for net in circuit.nets:
        out[net.id] = {derived.group_of(member) for member in net.members}
    return out


def symbols_of(plan, net_id: str) -> list:
    return [item for item in plan.power_symbols if item.net == net_id]


# ------------------------------------------------------------------- 验收


def test_one_opamp_ground_net_carries_exactly_one_symbol_and_stays_one_node():
    """任务书锚 1：合成页 GND 旗数 N → 1，且连通性逐脚不变。"""
    circuit = opamp_circuit()
    presentation = opamp_presentation()
    plan = only_plan(circuit, presentation)

    ground = symbols_of(plan, "GND")
    assert len(ground) == 1, (
        "one ground domain, one symbol: the three ground pads of the opamp and "
        "the capacitor's return are joined by the rail, not marked one by one "
        f"(got {[(s.symbol_ref, s.x, s.y) for s in plan.power_symbols]})"
    )
    assert len(symbols_of(plan, "VCC")) == 1

    # Connectivity, pad by pad, read out of the drawing by the independent layer.
    groups = derived_groups(plan, circuit, presentation)
    for net_id, members in (
        ("VCC", ("C1.1", "U1.8")),
        ("GND", ("C1.2", "U1.11", "U1.4")),
        ("INP", ("U1.3",)),
        ("INN", ("U1.2",)),
        ("OUT", ("U1.1",)),
    ):
        assert len(groups[net_id]) == 1, (
            f"net {net_id} must be one node in the drawing; the derivation found "
            f"{len(groups[net_id])}"
        )
        assert groups[net_id].pop() == tuple(sorted(members)), net_id

    checked = independent_check(plan, circuit, presentation)
    assert checked.hard_violations == [], [
        v.render() for v in checked.hard_violations
    ]


def test_ground_pads_on_opposite_faces_are_joined_by_the_rail_not_by_flags():
    """两枚地脚隔着本体也是**一颗**符号：轨道绕过去，而不是各打一颗（060 重复脚接上）。"""
    circuit = opamp_circuit(symbol="OPAMP-GND-ACROSS")
    presentation = opamp_presentation()
    plan = only_plan(circuit, presentation)

    assert len(symbols_of(plan, "GND")) == 1
    assert not [label for label in plan.labels if label.net == "GND"]
    groups = derived_groups(plan, circuit, presentation)
    assert len(groups["GND"]) == 1

    checked = independent_check(plan, circuit, presentation)
    assert checked.hard_violations == [], [
        v.render() for v in checked.hard_violations
    ]


def test_two_ground_domains_never_merge_into_one_symbol():
    """绝不并地：PGND 与 AGND 各一颗符号、各一个节点，符号还不是同一族。"""
    circuit = b053.circuit(
        [
            b053.part("U1", "OPAMP-2GND-EP", "OPA2GND"),
            b053.part("C1", "C0402", "100n"),
            b053.part("C2", "C0402", "100n"),
        ],
        [
            b053.net("VCC", "power", ["U1.8", "C1.1"]),
            b053.net("PGND", "gnd", ["U1.4", "U1.11", "C1.2"]),
            b053.net("AGND", "gnd", ["C2.2"]),
            b053.net("INP", "signal", ["U1.3"]),
            b053.net("INN", "signal", ["U1.2"]),
            b053.net("OUT", "signal", ["U1.1"]),
        ],
    )
    presentation = opamp_presentation()
    plan = only_plan(circuit, presentation)

    pgnd, agnd = symbols_of(plan, "PGND"), symbols_of(plan, "AGND")
    assert len(pgnd) == 1 and len(agnd) == 1, (
        "one symbol per ground net: "
        f"PGND={len(pgnd)} AGND={len(agnd)}"
    )
    assert pgnd[0].symbol_ref != agnd[0].symbol_ref, (
        "two domains must not be drawn with one glyph"
    )
    groups = derived_groups(plan, circuit, presentation)
    assert len(groups["PGND"]) == 1 and len(groups["AGND"]) == 1
    assert groups["PGND"] != groups["AGND"]


def test_a_single_pin_ground_net_is_unchanged_from_before():
    """单脚地网（divider 的 GND）与既有行为逐字一致：一颗旗，挂在脚上。"""
    circuit = b053.circuit(
        [b053.part("R1", "R0402", "10k"), b053.part("R2", "R0402", "10k")],
        [
            b053.net("VIN", "power", ["R1.1"]),
            b053.net("TAP", "signal", ["R1.2", "R2.1"]),
            b053.net("GND", "gnd", ["R2.2"]),
        ],
    )
    presentation = b053.presentation(
        "voltage-divider",
        modules=[{"id": "divider", "parts": ["R1", "R2"], "role": "divider"}],
        portRoles={"VIN": "input", "TAP": "output"},
        directWiringObligations=[
            {"nets": ["VIN", "TAP", "GND"], "note": "the whole ladder is wired"}
        ],
    )
    plan = only_plan(circuit, presentation)
    assert len(symbols_of(plan, "GND")) == 1
    assert len(plan.power_symbols) == 2  # VIN's rail flag and the ground's


def test_the_one_ground_symbol_stands_upright_and_hangs_away_from_its_pin():
    """069 sec.7 仍在：旗竖直（0/180），字形朝外挂在轨道远端。"""
    from boardwise.core.symbolprofile import flag_glyph_box

    circuit = opamp_circuit()
    presentation = opamp_presentation()
    plan = only_plan(circuit, presentation)
    symbol = symbols_of(plan, "GND")[0]
    assert symbol.rotation % 180.0 == 0.0, (
        f"a flag is vertical: {symbol.rotation}"
    )
    profile = book()[symbol.symbol_ref]
    box = flag_glyph_box(profile, rotation=symbol.rotation, anchor=(symbol.x, symbol.y))
    assert box is not None
    # The glyph is hung away from the pin it is reached from: the anchor sits on
    # the rail, and the glyph's box lies wholly on one side of it.
    assert box[1] >= symbol.y or box[3] <= symbol.y, (
        f"the glyph must hang to one side of its connection point: "
        f"box={box} anchor=({symbol.x}, {symbol.y})"
    )


def test_the_divider_fixture_compiles_with_one_ground_symbol_and_the_same_netlist():
    """既有夹具（tests/fixtures/drawapply/divider 三件套）逐条对拍。"""
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import drawapply

    circuit = CircuitSpec.load(DIVIDER / "divider.circuit.json")
    presentation = PresentationSpec.load(DIVIDER / "divider.presentation.json")
    library = drawapply.load_library(DIVIDER / "library.json")
    result = dc.compile(circuit, presentation, library, dc.CompileBudget())
    assert result.candidates, [f.detail for f in result.failures]
    plan = result.candidates[0]
    assert len(symbols_of(plan, "GND")) == 1
    derived = readability.derive_netlist(plan, library)
    for net in circuit.nets:
        assert len({derived.group_of(m) for m in net.members}) == 1, net.id


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
