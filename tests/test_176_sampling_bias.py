"""176: 采样链偏置电压检查（issue #76）的行为锚点。

钉死三件事：

* **真机锚**：ROBOT ctrl FOC 夹具的两条链（R4→U1.21/PA7、R5→U1.24/PB0）必须
  各出一条 WARN，且**只有**这两条；
* **四级语义**：交流/双向无偏置 ERROR、低边直连 ADC 无偏置 WARN、有偏置过
  （低边有偏置无滤波再补一条 INFO）——合成的板逐档验；
* **不误报**：夹具里带偏置/走运放的那些板（毕设 FOC 1.0.0/1.1.0、llc、
  CH340 golden、智能药箱、高速电机控制器）一条都不许出。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.review import BUILTIN_RULES, run_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.sensebias import SamplingBias

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
RULE_ID = "path-sampling-bias"


# ---------------------------------------------------------------------------
# tiny boards and shelves (same shapes as test_094)
# ---------------------------------------------------------------------------


def _part(
    designator: str, *, value: str = "", mpn: str = "", lcsc: str = "", pins=()
) -> Component:
    """One component; a pin is ``(number, net)`` or ``(number, name, net)``."""
    resolved = []
    for pin in pins:
        if len(pin) == 2:
            number, net = pin
            resolved.append(Pin(str(number), "", net))
        else:
            number, name, net = pin
            resolved.append(Pin(str(number), str(name), net))
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        lcsc_part=lcsc,
        pins=resolved,
    )


def _model_of(components: dict, nets: dict) -> DesignModel:
    model = DesignModel()
    model.components.update(components)
    model.nets = {name: Net(name, list(pins)) for name, pins in nets.items()}
    return model


def _mcu(designator: str = "U1", *, mpn: str = "STM32G431RBT6") -> Component:
    return _part(
        designator,
        mpn=mpn,
        pins=[("21", "PA7", "ISNS"), ("1", "VDD", "VCC"), ("15", "VSS", "GND")],
    )


def _low_side_board(*, shunt="R4", foreign=(), nets_extra=None):
    """一颗 100mΩ 从 GND 到 `ISNS`，`ISNS` 上直连一颗 STM32 的 PA7。"""
    components = {
        "R4": _part(shunt, value="100mΩ", pins=[("1", "1", "GND"), ("2", "2", "ISNS")]),
        "U1": _mcu(),
    }
    nets = {
        "GND": [("R4", "1"), ("U1", "15")],
        "ISNS": [("R4", "2"), ("U1", "21")],
        "VCC": [("U1", "1")],
    }
    for comp, pins in foreign:
        components[comp.designator] = comp
        for pin in pins:
            nets.setdefault(pin[1], []).append((comp.designator, pin[0]))
    for name, pins in (nets_extra or {}).items():
        nets.setdefault(name, []).extend(pins)
    return _model_of(components, nets)


def _bias_resistor(from_net: str = "ISNS", to_net: str = "3V3") -> tuple:
    comp = _part("R10", value="1k", pins=[("1", "1", from_net), ("2", "2", to_net)])
    return (comp, [("1", from_net), ("2", to_net)])


def _filter_cap() -> tuple:
    comp = _part("C10", value="100nF", pins=[("1", "1", "ISNS"), ("2", "2", "GND")])
    return (comp, [("1", "ISNS"), ("2", "GND")])


# ---------------------------------------------------------------------------
# the real fixture: the acceptance anchor
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def robot_findings():
    return SamplingBias().check(build_project_model(ROBOT).boards[0])


def test_the_robot_control_board_files_exactly_two_warns(robot_findings):
    """岳 2026-10-12 的取证拓扑：R4/R5 两颗 100mΩ 下端落地、上端直连
    U1.21(PA7)/U1.24(PB0)，无运放、无偏置、无 RC、无串阻。"""
    assert len(robot_findings) == 2, [f.message for f in robot_findings]
    assert {f.severity for f in robot_findings} == {"WARN"}
    assert {f.rule_id for f in robot_findings} == {RULE_ID}

    pairs = {f.target.component_ref: f for f in robot_findings}
    assert set(pairs) == {"R4", "R5"}

    r4 = pairs["R4"]
    assert r4.target.net_refs == ["U+"]
    assert r4.target.pin_refs == ["2"]
    assert "U1 pin21（PA7）" in r4.message
    assert "U+ 成员：DRV1.6, R4.2, U1.21" in r4.evidence
    assert any("ic.stm32g431rbt6" in e and "category=ic.mcu" in e for e in r4.evidence)

    r5 = pairs["R5"]
    assert r5.target.net_refs == ["W+"]
    assert "U1 pin24（PB0）" in r5.message
    assert any("W+ 成员" in e for e in r5.evidence)


def test_the_robot_board_gets_them_through_the_engine_too():
    """注册生效的证据：走 :func:`run_review` 的整轮复盘也恰好这两条。"""
    findings = [
        f for f in run_review(build_project_model(ROBOT)) if f.rule_id == RULE_ID
    ]
    assert len(findings) == 2
    assert {f.board for f in findings} == {"Board1"}
    assert {f.severity for f in findings} == {"WARN"}


def test_the_rule_is_a_builtin_and_has_a_chinese_name():
    from boardwise.rules.i18n import RULE_NAMES_ZH

    assert RULE_ID in {rule.id for rule in BUILTIN_RULES}
    assert RULE_ID in RULE_NAMES_ZH


# ---------------------------------------------------------------------------
# the four tiers, synthesised
# ---------------------------------------------------------------------------


def test_low_side_direct_to_adc_without_bias_is_a_warn():
    findings = SamplingBias().check(_low_side_board())
    assert len(findings) == 1
    f = findings[0]
    assert (f.rule_id, f.severity) == (RULE_ID, "WARN")
    assert f.target.component_ref == "R4"
    # 三条风险机制都要说人话（issue #76 的原文口径）
    assert "窗口塌缩" in f.message
    assert "偏置" in f.message and "VREF/2" in f.message
    assert "上不了机" in f.message


def test_low_side_with_bias_and_no_filter_is_an_info():
    model = _low_side_board(foreign=[_bias_resistor()])
    findings = SamplingBias().check(model)
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "滤波" in findings[0].message
    assert any("R10" in e and "3V3" in e for e in findings[0].evidence)


def test_low_side_with_bias_and_filter_says_nothing():
    model = _low_side_board(foreign=[_bias_resistor(), _filter_cap()])
    assert SamplingBias().check(model) == []


def test_a_filter_without_a_bias_is_still_a_warn():
    """滤波不解决偏置：窗口该塌缩还是塌缩，而且消息得如实报出那处滤波。"""
    model = _low_side_board(foreign=[_filter_cap()])
    findings = SamplingBias().check(model)
    assert [f.severity for f in findings] == ["WARN"]
    assert "滤波不解决偏置" in findings[0].message
    assert "C10" in findings[0].message
    assert "没有到地的滤波电容" not in findings[0].message


def test_an_ac_chain_without_bias_is_an_error():
    """相线串联采样：两端都活（谁都不接地），直连 ADC 又没偏置 —— 负半周把
    节点拉到参考地以下，这一档是 ERROR，不是 WARN。"""
    model = _model_of(
        {
            "R8": _part(
                "R8", value="10mΩ", pins=[("1", "1", "SHA"), ("2", "2", "IA+")]
            ),
            "U1": _part(
                "U1", mpn="STM32G431RBT6", pins=[("23", "PA1", "IA+")]
            ),
            "U2": _part("U2", mpn="DRV8350SRTVR", pins=[("6", "SHA", "SHA")]),
        },
        {
            "IA+": [("R8", "2"), ("U1", "23")],
            "SHA": [("R8", "1"), ("U2", "6")],
        },
    )
    findings = SamplingBias().check(model)
    assert [f.severity for f in findings] == ["ERROR"]
    assert "负压" in findings[0].message
    assert findings[0].target.component_ref == "R8"


def test_a_bus_referenced_chain_without_bias_is_an_error():
    """参照端是 power-class 母线 → 同样是不接地参考的那一档。"""
    model = _model_of(
        {
            "R6": _part(
                "R6", value="5mΩ", pins=[("1", "1", "+24V"), ("2", "2", "ISNS")]
            ),
            "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "ISNS")]),
        },
        {
            "ISNS": [("R6", "2"), ("U1", "21")],
            "+24V": [("R6", "1")],
        },
    )
    findings = SamplingBias().check(model)
    assert [f.severity for f in findings] == ["ERROR"]
    assert "母线" in findings[0].message


def test_low_side_into_an_opamp_input_is_an_info_not_a_warn():
    """走运放的链，偏置可能由运放自己送进来 —— 图纸上读不出来，只提请注意。"""
    model = _model_of(
        {
            "R8": _part(
                "R8", value="10mΩ", pins=[("1", "1", "PGND"), ("2", "2", "IA+")]
            ),
            "U3": _part(
                "U3", mpn="TLV9062IDR", pins=[("3", "INA+", "IA+"), ("8", "VCC", "VCC")]
            ),
        },
        {
            "IA+": [("R8", "2"), ("U3", "3")],
            "PGND": [("R8", "1")],
            "VCC": [("U3", "8")],
        },
    )
    findings = SamplingBias().check(model)
    assert [f.severity for f in findings] == ["INFO"]
    assert any("货架条目 category=ic.opamp" in e for e in findings[0].evidence)
    assert "确认" in findings[0].message


# ---------------------------------------------------------------------------
# what it refuses to call a chain
# ---------------------------------------------------------------------------


def test_a_zero_ohm_jumper_is_not_a_shunt():
    model = _model_of(
        {
            "R1": _part("R1", value="0Ω", pins=[("1", "1", "GND"), ("2", "2", "ISNS")]),
            "U1": _mcu(),
        },
        {"GND": [("R1", "1"), ("U1", "15")], "ISNS": [("R1", "2"), ("U1", "21")]},
    )
    assert SamplingBias().check(model) == []


def test_a_shunt_that_reaches_no_input_is_not_a_chain():
    model = _model_of(
        {
            "R1": _part("R1", value="10mΩ", pins=[("1", "1", "PGND"), ("2", "2", "IA+")]),
            "U9": _part("U9", mpn="PZ2.54-2x6", pins=[("9", "9", "IA+")]),
        },
        {"PGND": [("R1", "1")], "IA+": [("R1", "2"), ("U9", "9")]},
    )
    assert SamplingBias().check(model) == []


def test_a_port_shaped_pin_on_a_non_mcu_is_not_an_adc_candidate():
    """脚名长得像 PA7 不够：器件得先是 MCU（货架 category，或家族标记）。"""
    model = _model_of(
        {
            "R1": _part("R1", value="10mΩ", pins=[("1", "1", "GND"), ("2", "2", "ISNS")]),
            "U9": _part("U9", mpn="FOOBAR123", pins=[("21", "PA7", "ISNS")]),
        },
        {"GND": [("R1", "1")], "ISNS": [("R1", "2"), ("U9", "21")]},
    )
    assert SamplingBias().check(model) == []


def test_the_two_adc_evidence_routes_are_both_spelled_out():
    """依据等级不许含糊：货架说有 category，最小启发说有家族标记。"""
    shelf = PartLibrary(parts=[PartEntry(
        key="ic.acmemcu", mpn="ACME1", lcsc="C1", category="ic.mcu", facts={},
    )])
    model = _model_of(
        {
            "R1": _part("R1", value="10mΩ", pins=[("1", "1", "GND"), ("2", "2", "ISNS")]),
            "U5": _part("U5", mpn="ACME1", pins=[("21", "PA7", "ISNS")]),
        },
        {"GND": [("R1", "1")], "ISNS": [("R1", "2"), ("U5", "21")]},
    )
    shelf_findings = SamplingBias(library=shelf).check(model)
    assert [f.severity for f in shelf_findings] == ["WARN"]
    assert any("货架条目 ic.acmemcu" in e for e in shelf_findings[0].evidence)

    # 同一块板，货架里没有这条目 → 退到家族标记那一路，evidence 说清楚。
    heuristic = SamplingBias(library=PartLibrary()).check(
        _low_side_board_with_unknown_mcu()
    )
    assert [f.severity for f in heuristic] == ["WARN"]
    assert any("MCU 家族标记 STM32" in e and "最小启发" in e
               for e in heuristic[0].evidence)


def _low_side_board_with_unknown_mcu() -> DesignModel:
    return _model_of(
        {
            "R4": _part("R4", value="100mΩ", pins=[("1", "1", "GND"), ("2", "2", "ISNS")]),
            "U1": _part("U1", mpn="STM32F999ZXX", pins=[("21", "PA7", "ISNS")]),
        },
        {"GND": [("R4", "1")], "ISNS": [("R4", "2"), ("U1", "21")]},
    )


# ---------------------------------------------------------------------------
# the negative anchors: boards that already carry a bias / an amplifier
# ---------------------------------------------------------------------------

#: Fixtures whose sense chains are biased or go through an op-amp. None of them
#: may file a finding — this is the half the ruling calls 「有偏置过」, and the
#: half a loose rule would turn into noise.
BIASED_FIXTURES = [
    "ProPrj_毕设FOC驱动板_2026-09-17.epro2",
    "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2",
    "ProPrj_高速电机控制器_2026-09-16.epro2",
    "ProPrj_智能药箱_2026-09-17.epro2",
    "llc_board.epro2",
    "ch340_golden.epro2",
    "毕设滤波采样_2026-09-27.epro2",
]


@pytest.mark.parametrize("name", BIASED_FIXTURES)
def test_no_finding_on_boards_that_are_not_this_defect(name):
    project = build_project_model(FIXTURES / name)
    hits = [
        f for board in project.boards
        for f in SamplingBias().check(board)
    ]
    assert hits == [], [f.message for f in hits]
