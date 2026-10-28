"""534：零核并联支路组（coreless decoupling / shunt bank）。

正式四岛分解里 `ch343_power=[C1,C3,C4]` 被 `ic-periphery` 以「无 core」
拒绝：这一组件的每一件都只有 2 脚，而文法只会画「挂在 core 上的外围」。这个缺口不是
CH343 的，而是文法缺少一条惯用法——**一组并联到地的去耦支路没有 core，也不该有**：

* C1：`+5V`(power) ↔ `GND`；C3：`V3`(signal，U1.4 的内部轨) ↔ `GND`；C4：`VCC` ↔ `GND`。

本用例钉住三件事：

1. **合法形态**：显式声明的 module（`modules[].parts`）、每件都是 `two_terminal_parts`
   （两脚、两网不同）、每件恰好一脚在同一 gnd、另一脚是 power 或 signal 的网。
   绑定用现有角色：每件 `shunt`、地 `gnd`、power 节点 `rail`、signal 节点 `out`；
   **没有 core 角色**，也不伪造 core。
2. **拒绝**：>2 脚（回落原来的 no-core 拒绝）、短接、双地端、组内两个地、无地（串信号路径）。
   一个都不静默。
3. **编译侧**：`drawcompiler` 只对「binding 里无 chain 且所有候选都是这种合法 shunt」放行
   free 行布局；其余无 owner 的 branch 仍按 `series string ... reaches no chain part` 拒绝。

全部用小型合成 CircuitSpec / PresentationSpec；集成用例用**生产的** `blocklib/specs`
里的真实 ch343 电路与库（在内存里裁成单岛），不读 `.tmp_534`。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler, pagecompiler
from boardwise.engines.grammar import ic_periphery
from boardwise.engines.grammar.base import (
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    OWNED_BRANCH,
    UNIFORM_GND,
    GrammarResult,
    RoleBinding,
)

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

CAP = "C0603-100nF-C1590"


def part(part_id: str, symbol: str = CAP, value: str = "100nF") -> dict:
    return {
        "id": part_id, "symbolRef": symbol, "value": value,
        "provenance": "engineer_confirmed",
    }


def net(net_id: str, cls: str, members: list[str], provenance: str = "verified_recipe") -> dict:
    return {
        "id": net_id, "class": cls, "members": list(members),
        "provenance": provenance,
    }


def circuit(parts: list[dict], nets: list[dict]) -> CircuitSpec:
    return CircuitSpec.from_dict({"parts": parts, "nets": nets})


def sheet(parts: tuple[str, ...], module_id: str = "dec", core: str = "") -> PresentationSpec:
    module: dict = {
        "id": module_id, "parts": list(parts), "grammarRef": "ic-periphery",
        "role": "supply decoupling, one branch per node",
    }
    if core:
        module["core"] = core
    return PresentationSpec.from_dict({"grammarRef": "ic-periphery", "modules": [module]})


def bind(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec):
    return ic_periphery.IcPeripheryGrammar().bind(circuit_spec, presentation_spec)


def roles(result) -> dict[str, str]:
    return {
        item.role: item.part_id
        for item in result.bindings
        if item.role not in ("shunt",)
    }


def shunts(result) -> list[str]:
    return sorted(item.part_id for item in result.bindings if item.role == "shunt")


def by_role(result, role: str) -> list[str]:
    return sorted(item.part_id for item in result.bindings if item.role == role)


# ------------------------------------------------------------ 合法：单支路 / 双支路


def test_one_capacitor_on_one_rail_is_a_coreless_shunt_group():
    """C4 的形状：一件，VCC(power) ↔ GND，没有 core。"""
    spec = circuit(
        [part("C4")],
        [net("VCC", "power", ["C4.1"]), net("GND", "gnd", ["C4.2"])],
    )
    result = bind(spec, sheet(("C4",), module_id="ch343_power"))

    assert result.ok, result.failures
    assert shunts(result) == ["C4"]
    assert by_role(result, "gnd") == ["GND"]
    assert by_role(result, "rail") == ["VCC"]
    # 没有 core 角色：这一组没有「别人挂在它身上」的那一件
    assert by_role(result, "core") == []
    # 每一条绑定都带证据，并落在两件实测/分区事实上
    for item in result.bindings:
        assert "provenance=" in item.evidence
    assert "engineer_confirmed" in result.bindings[-1].evidence


def test_two_capacitors_on_two_nodes_are_one_bank_not_a_core_plus_periphery():
    """C1(+5V, power) 与 C3(V3, signal 内部轨) 同地：两条并联支路，两个节点。"""
    spec = circuit(
        [part("C1"), part("C3")],
        [
            net("+5V", "power", ["C1.1"]),
            net("V3", "signal", ["C3.1"]),
            net("GND", "gnd", ["C1.2", "C3.2"]),
        ],
    )
    result = bind(spec, sheet(("C1", "C3"), module_id="ch343_power"))

    assert result.ok, result.failures
    assert shunts(result) == ["C1", "C3"]
    assert by_role(result, "gnd") == ["GND"]
    # power 节点用 rail，signal 内部轨按事实用 out（不改 class、不新增角色）
    assert by_role(result, "rail") == ["+5V"]
    assert by_role(result, "out") == ["V3"]
    assert by_role(result, "core") == []
    # 只承诺这一个地表达一致；没有 owned-branch（没有 core，就没有归属链）
    kinds = [item.kind for item in result.obligations]
    assert kinds == [UNIFORM_GND]
    assert result.obligations[0].nets == ("GND",)
    assert OWNED_BRANCH not in kinds


# ------------------------------------------------------------ 拒绝：形状不对，不静默


def test_a_part_with_more_than_two_pins_is_never_taken_as_a_branch():
    """>2 脚不是支路：这一组没有唯一多脚件，回落到原来的 facts-missing。"""
    spec = circuit(
        [part("U1", symbol="CH343G-C2844153", value="CH343G"),
         part("U2", symbol="CH343G-C2844153", value="CH343G")],
        [
            net("+5V", "power", ["U1.1", "U2.1"]),
            net("GND", "gnd", ["U1.2", "U2.2"]),
            net("TXD", "signal", ["U1.3", "U2.3"]),
        ],
    )
    result = bind(spec, sheet(("U1", "U2"), module_id="u1"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "the core of this drawing is not stated and cannot be derived" in (
        failure.detail
    )
    assert "highest pin count of 3" in failure.detail
    assert "modules[u1].core" in failure.action


def test_a_short_is_refused_as_a_short_not_as_a_missing_core():
    """两脚同网 = 短接，不是一条支路。"""
    spec = circuit(
        [part("C1")],
        [net("VCC", "power", ["C1.1", "C1.2"])],
    )
    result = bind(spec, sheet(("C1",), module_id="dec"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "short" in failure.detail
    assert "C1" in failure.subject


def test_a_part_with_both_ends_on_ground_is_refused():
    spec = circuit(
        [part("C1")],
        [
            net("GND", "gnd", ["C1.1"]),
            net("PGND", "gnd", ["C1.2"]),
        ],
    )
    result = bind(spec, sheet(("C1",), module_id="dec"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "both pins on nets of class 'gnd'" in failure.detail


def test_two_grounds_in_one_group_are_refused():
    spec = circuit(
        [part("C1"), part("C3")],
        [
            net("+5V", "power", ["C1.1"]),
            net("VCC", "power", ["C3.1"]),
            net("GND", "gnd", ["C1.2"]),
            net("PGND", "gnd", ["C3.2"]),
        ],
    )
    result = bind(spec, sheet(("C1", "C3"), module_id="dec"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "more than one net of class 'gnd'" in failure.detail


def test_a_branch_with_no_ground_end_is_a_series_path_and_is_refused():
    """C1 的 RAIL→MID 与 C3 的 MID→GND 是串联路径：C1 没有地端。"""
    spec = circuit(
        [part("C1"), part("C3")],
        [
            net("RAIL", "power", ["C1.1"]),
            net("MID", "signal", ["C1.2", "C3.1"]),
            net("GND", "gnd", ["C3.2"]),
        ],
    )
    result = bind(spec, sheet(("C1", "C3"), module_id="dec"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "series path" in failure.detail
    assert failure.subject == "C1"


# ------------------------------------------------- 编译侧 guard：只放行这一种无核 binding


def test_the_compiler_guard_reads_the_bank_from_the_binding_structure():
    spec = circuit(
        [part("C4")],
        [net("VCC", "power", ["C4.1"]), net("GND", "gnd", ["C4.2"])],
    )
    result = bind(spec, sheet(("C4",)))
    assert drawcompiler._coreless_shunt_parts(spec, result) == frozenset({"C4"})


def test_the_guard_refuses_a_binding_that_is_not_all_shunts():
    spec = circuit(
        [part("C4"), part("C5")],
        [
            net("VCC", "power", ["C4.1"]),
            net("GND", "gnd", ["C4.2", "C5.2"]),
            net("V3", "signal", ["C5.1"]),
        ],
    )
    result = bind(spec, sheet(("C4", "C5")))
    # 语法上合法，但把其中一条改成 bridge：guard 必须拒绝整组
    broken = GrammarResult(
        ok=True,
        bindings=tuple(
            item if item.part_id != "C5" else
            RoleBinding(role="bridge", part_id="C5", evidence="x")
            for item in result.bindings
        ),
        constraints=result.constraints,
        obligations=result.obligations,
    )
    assert drawcompiler._coreless_shunt_parts(spec, broken) == frozenset()


def test_the_guard_refuses_a_shunt_that_is_not_two_terminal():
    spec = circuit(
        [part("C4"), part("U1", symbol="CH343G-C2844153", value="CH343G")],
        [
            net("VCC", "power", ["C4.1", "U1.1"]),
            net("GND", "gnd", ["C4.2", "U1.2"]),
            net("TXD", "signal", ["U1.3"]),
        ],
    )
    binding = GrammarResult(
        ok=True,
        bindings=(
            RoleBinding(role="gnd", part_id="GND", evidence="x"),
            RoleBinding(role="shunt", part_id="C4", evidence="x"),
            RoleBinding(role="shunt", part_id="U1", evidence="x"),
        ),
    )
    assert drawcompiler._coreless_shunt_parts(spec, binding) == frozenset()


# ------------------------------------------------------ 集成：真实 ch343 的两个电容岛


def _library() -> dict[str, SymbolProfile]:
    payload = json.loads(
        (SPECS / "ch343_uart.library.json").read_text(encoding="utf-8")
    )
    return {
        profile.symbol_ref: profile
        for profile in (SymbolProfile.from_dict(e) for e in payload["profiles"])
    }


def _real_circuit() -> CircuitSpec:
    return CircuitSpec.from_dict(
        json.loads((SPECS / "ch343_uart.circuit.json").read_text(encoding="utf-8"))
    )


def _island(parts: tuple[str, ...], module_id: str):
    """真实电路在**内存里**裁成单岛，与 pagecompiler 的模块视图同一条裁法。"""
    whole = _real_circuit()
    full_sheet = PresentationSpec.from_dict({"modules": [{
        "id": module_id, "parts": list(parts), "grammarRef": "ic-periphery",
        "role": "one island of the ch343 page, cut out of the whole circuit",
    }]})
    module = full_sheet.modules[0]
    return pagecompiler._module_view(whole, full_sheet, module)


@pytest.mark.parametrize(
    ("module_id", "parts"),
    [
        ("ch343_power", ("C1", "C3", "C4")),
    ],
)
def test_the_real_decoupling_islands_compile_without_a_core(module_id, parts):
    sub_circuit, sub_sheet = _island(parts, module_id)
    result = drawcompiler.compile(sub_circuit, sub_sheet, _library())

    assert result.ok, result.render_failures()
    assert result.candidates, result.render_failures()
    plan = result.candidates[0]
    assert sorted(part.part_id for part in plan.parts) == sorted(parts)


def test_a_coreless_series_group_still_has_no_drawing():
    """反证：同样走无核路径的串联组在**编译**层仍被拒（guard 不是「无 owner 全放行」）。"""
    spec = circuit(
        [part("C1"), part("C3")],
        [
            net("RAIL", "power", ["C1.1"]),
            net("MID", "signal", ["C1.2", "C3.1"]),
            net("GND", "gnd", ["C3.2"]),
        ],
    )
    result = drawcompiler.compile(spec, sheet(("C1", "C3")), {})

    assert result.ok is False
    assert result.candidates == []
    assert result.failures
    assert result.failures[0].category == FAILURE_CIRCUIT_INVALID
    assert "series path" in result.failures[0].detail


def test_a_bank_that_leaves_a_part_of_the_circuit_out_is_not_a_bank():
    """534 缺口：组内器件必须**就是**本图全部器件，不是「都在本图里」。

    C1 (+5V→GND) 与 C3 (V3→GND) 单独看是完全合法的并联去耦支路；但电路里还有一枚
    未列入 `modules[].parts` 的 C5 (+5V→GND)。注释要求「the group's parts are all the
    parts of the drawing」，实现此前只查了 declared ⊇ scope_parts，于是这枚额外件逃过
    模块作用域、整组被当完整 coreless bank 静默接受。修好后必须回落到原来的
    no-core 拒绝，且不得把 C1/C3 绑成 shunt 组。
    """
    spec = circuit(
        [
            part("C1"), part("C3"), part("C5"),
        ],
        [
            net("+5V", "power", ["C1.1", "C5.1"]),
            net("V3", "signal", ["C3.1"]),
            net("GND", "gnd", ["C1.2", "C3.2", "C5.2"]),
        ],
    )
    result = bind(spec, sheet(("C1", "C3"), module_id="dec"))

    assert result.ok is False, (
        "a group that leaves C5 unbound behind the bank is not the whole drawing")
    assert shunts(result) == [], shunts(result)
    (failure,) = result.failures
    assert "C5" in failure.detail or "C5" in (failure.subject or "") or (
        "core" in failure.detail.lower()), failure.detail
