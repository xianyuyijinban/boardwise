"""053 阶段 B 第一波：三种画法语法（052 §5 / 053 §三、§四）。

这一批只做**语法**：角色怎么绑、相对关系怎么表述、什么拓扑必须可见、绑不上时
怎么分类报告。坐标不在这一层——`RelativeConstraint` 类型里就没有放坐标的地方，
测试把这条钉住（字段名逐字比对），因为"语法表里不得出现场景专用常量"（053 §六）
靠的正是这里不存坐标。

测试的分工，一句话一条：

1. **正例**：每种语法的标准画法绑出来的角色/关系/义务逐项对；换符号（同一语法、
   不同 symbolRef）不改绑法——052 §5「不是为每颗芯片存一张固定坐标图」；
2. **facts-missing**：缺的事实点名（网 class 没写 / 没有 SymbolProfile / 引脚角色
   读不出 / 电源脚没接），并给出"去哪补"；
3. **circuit-invalid**：连接关系与语法拓扑不符时点名哪条（两臂并联、串联器件两端
   都没有到地支路、core 被短路、链跨了模块划分）；
4. **变体**：横排镜像（由 sidePreferences 驱动，不是场景常量）、多抽头 + 并联支路、
   多 C 并联 / R 换磁珠、EN/NR 支路；
5. **确定性**：同输入 → 同输出逐字节；**依据传递**：`ai_asserted` 的绑定在 evidence
   里带出 provenance（草稿态传递）。

CircuitSpec / PresentationSpec / SymbolProfile 全部手写字面量，不建夹具文件：这一批
判的是语法，夹具会把解析器的行为绑进来。
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec, PresentationSpecError
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import grammar
from boardwise.engines.grammar import base, ldo, rc_lowpass, voltage_divider
from boardwise.engines.grammar.base import (
    ABOVE,
    CONSTRAINT_KINDS,
    DIRECT_WIRE,
    FAILURE_CATEGORIES,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    HORIZONTAL_TAP,
    LEFT_OF,
    NEAR,
    OBLIGATION_KINDS,
    OWNED_BRANCH,
    PROVENANCE_UNSTATED,
    RIGHT_OF,
    SAME_COLUMN,
    SAME_ROW,
    UNIFORM_GND,
    VERTICAL_TAP,
    VISIBLE_TAP,
    DrawingGrammar,
    GrammarError,
    GrammarFailure,
    GrammarObligation,
    GrammarResult,
    RelativeConstraint,
    RoleBinding,
    refused_result,
    weakest_provenance,
)

PROV = "verified_recipe"
AI = "ai_asserted"


# --------------------------------------------------------------------- inputs


def _part(part_id: str, symbol: str = "R0402", value: str = "10k",
          provenance: str = PROV) -> dict:
    return {
        "id": part_id,
        "symbolRef": symbol,
        "value": value,
        "provenance": provenance,
    }


def _net(net_id: str, cls: str, members: list[str],
         provenance: str = PROV) -> dict:
    return {
        "id": net_id,
        "class": cls,
        "members": list(members),
        "provenance": provenance,
    }


def _circuit(parts: list[dict], nets: list[dict],
             nc: list[str] | None = None) -> CircuitSpec:
    payload: dict = {"parts": parts, "nets": nets}
    if nc:
        payload["nc"] = list(nc)
    return CircuitSpec.from_dict(payload)


def _presentation(grammar_ref: str = "", **overrides) -> PresentationSpec:
    payload: dict = {"grammarRef": grammar_ref}
    payload.update(overrides)
    return PresentationSpec.from_dict(payload)


def _divider_circuit(*, provenance: str = PROV) -> CircuitSpec:
    return _circuit(
        [_part("R1"), _part("R2")],
        [
            _net("VIN", "power", ["R1.1"], provenance),
            _net("TAP", "signal", ["R1.2", "R2.1"], provenance),
            _net("GND", "gnd", ["R2.2"], provenance),
        ],
    )


def _ladder_circuit() -> CircuitSpec:
    """R1-R2-R3 with two taps, plus C1 on the first tap (变体：多抽头 + 并联支路)."""
    return _circuit(
        [_part("R1"), _part("R2"), _part("R3"), _part("C1", "C0402", "100n")],
        [
            _net("VIN", "power", ["R1.1"]),
            _net("TAP1", "signal", ["R1.2", "R2.1", "C1.1"]),
            _net("TAP2", "signal", ["R2.2", "R3.1"]),
            _net("GND", "gnd", ["R3.2", "C1.2"]),
        ],
    )


def _rc_circuit(shunts: tuple[str, ...] = ("C1",), series: str = "R1",
                series_symbol: str = "R0402") -> CircuitSpec:
    parts = [_part(series, series_symbol)]
    members: list[str] = [f"{series}.1"]
    tap_members: list[str] = [f"{series}.2"]
    gnd_members: list[str] = []
    for index, shunt in enumerate(shunts):
        parts.append(_part(shunt, "C0402", "100n"))
        tap_members.append(f"{shunt}.1")
        gnd_members.append(f"{shunt}.2")
    return _circuit(
        parts,
        [
            _net("VIN", "power", members),
            _net("OUT", "signal", tap_members),
            _net("GND", "gnd", gnd_members),
        ],
    )


def _regulator_profile(*, symbol_ref: str = "AMS1117-3.3",
                       extra: tuple[tuple[str, str], ...] = ()) -> SymbolProfile:
    """A three-pin regulator, or one with EN/NR pins as well (变体)."""
    rows = [("1", "GND"), ("2", "VOUT"), ("3", "VIN"), *extra]
    pins = [
        SymbolPin(
            number=number,
            name=role,
            tip=(float(-40 + 20 * index), 0.0),
            direction="left" if index % 2 else "right",
            direction_source="body-box",
            electrical_role=role,
            role_source="pin-name",
        )
        for index, (number, role) in enumerate(rows)
    ]
    return SymbolProfile(
        symbol_ref=symbol_ref, title=symbol_ref,
        body=(-30.0, -40.0, 30.0, 40.0), pins=pins,
    )


def _ldo_circuit(symbol_ref: str = "AMS1117-3.3") -> CircuitSpec:
    return _circuit(
        [
            _part("U1", symbol_ref, "AMS1117-3.3"),
            _part("C1", "C0805", "10u"),
            _part("C2", "C0402", "100n"),
        ],
        [
            _net("VIN5", "power", ["U1.3", "C1.1"]),
            _net("3V3", "power", ["U1.2", "C2.1"]),
            _net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )


def _ldo_profiles(symbol_ref: str = "AMS1117-3.3",
                  profile: SymbolProfile | None = None,
                  caps: tuple[str, ...] = ("C0805", "C0402")) -> dict:
    """A complete library for the LDO tests: every symbol on the page.

    Complete on purpose — a test that means to prove *one* fact is missing should
    not also trip the library-gap refusal, which is a separate case
    (`test_ldo_without_any_symbol_profile_is_a_facts_missing_refusal`).
    """
    book = {name: _small_profile(name) for name in caps}
    book[symbol_ref] = profile or _regulator_profile(symbol_ref=symbol_ref)
    return book


def _small_profile(symbol_ref: str) -> SymbolProfile:
    """A two-pin passive profile, for tests that only need the library complete."""
    return SymbolProfile(
        symbol_ref=symbol_ref,
        pins=[
            SymbolPin(number="1", tip=(0.0, -20.0)),
            SymbolPin(number="2", tip=(0.0, 20.0)),
        ],
    )


def _ldo_circuit_with_aux() -> CircuitSpec:
    """The EN/NR variant: a pull-down on EN, a capacitor on NR."""
    return _circuit(
        [
            _part("U1", "AMS1117-ADJ"),
            _part("C1", "C0805", "10u"),
            _part("C2", "C0402", "100n"),
            _part("R2", "R0402", "10k"),
            _part("C3", "C0402", "10n"),
        ],
        [
            _net("VIN5", "power", ["U1.3", "C1.1"]),
            _net("3V3", "power", ["U1.2", "C2.1"]),
            _net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "R2.2", "C3.2"]),
            _net("EN", "signal", ["U1.4", "R2.1"]),
            _net("NR", "signal", ["U1.5", "C3.1"]),
        ],
    )


def _bind(spec_circuit: CircuitSpec, spec_presentation: PresentationSpec,
          profiles=None) -> GrammarResult:
    return grammar.bind(spec_circuit, spec_presentation, profiles)


def _kinds(result: GrammarResult, kind: str) -> list[RelativeConstraint]:
    return [item for item in result.constraints if item.kind == kind]


def _obligations(result: GrammarResult, kind: str) -> list[GrammarObligation]:
    return [item for item in result.obligations if item.kind == kind]


def _failures(result: GrammarResult, category: str) -> list[GrammarFailure]:
    return [item for item in result.failures if item.category == category]


# ---------------------------------------------------------- voltage-divider


def test_voltage_divider_binds_the_two_arms_the_tap_and_the_nets():
    result = _bind(_divider_circuit(), _presentation("voltage-divider"))

    assert result.ok is True
    assert result.failures == ()
    assert result.parts_of("upper_arm") == ("R1",)
    assert result.parts_of("lower_arm") == ("R2",)
    assert result.net_of("tap") == "TAP"
    assert result.net_of("in") == "VIN"
    assert result.net_of("gnd") == "GND"
    assert [item.role for item in result.bindings] == [
        "upper_arm", "lower_arm", "in", "gnd", "tap",
    ]

    # 053 §三：竖排同轴 + upper 上 lower 下 + 抽头中点水平引出。
    assert [(item.kind, item.subject, item.object) for item in result.constraints] == [
        (SAME_COLUMN, "R1", "R2"),
        (ABOVE, "R1", "R2"),
        (HORIZONTAL_TAP, "R1", "R2"),
    ]
    # 全链直连（电气序）+ 抽头可见。
    assert [item.nets for item in _obligations(result, DIRECT_WIRE)] == [
        ("VIN", "TAP", "GND")
    ]
    assert _obligations(result, VISIBLE_TAP) == [
        GrammarObligation(
            kind=VISIBLE_TAP,
            nets=("TAP",),
            reason="053 sec.3: the tap is directly visible (stub + label or "
                   "port), not absorbed by the upper/lower junction",
        )
    ]
    for binding in result.bindings:
        assert binding.evidence.endswith(f"provenance={PROV}"), binding.evidence


def test_voltage_divider_missing_net_classes_is_a_facts_missing_refusal():
    spec = _circuit(
        [_part("R1"), _part("R2")],
        [
            _net("VIN", "signal", ["R1.1"]),
            _net("TAP", "signal", ["R1.2", "R2.1"]),
            _net("GND", "signal", ["R2.2"]),
        ],
    )
    result = _bind(spec, _presentation("voltage-divider"))

    assert result.ok is False
    assert result.bindings == ()
    assert len(result.failures) == 2
    assert {item.category for item in result.failures} == {FAILURE_FACTS_MISSING}
    joined = " | ".join(item.detail for item in result.failures)
    assert "class 'gnd'" in joined and "class 'power'" in joined
    for item in result.failures:
        assert "nets[].class" in item.action


def test_voltage_divider_arms_in_parallel_is_circuit_invalid_and_names_them():
    spec = _circuit(
        [_part("R1"), _part("R2")],
        [
            _net("VIN", "power", ["R1.1", "R2.1"]),
            _net("GND", "gnd", ["R1.2", "R2.2"]),
        ],
    )
    result = _bind(spec, _presentation("voltage-divider"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "R1(GND,VIN)" in failure.detail and "R2(GND,VIN)" in failure.detail
    assert "parallel" in failure.detail
    assert failure.action


def test_voltage_divider_horizontal_variant_is_the_same_binding_with_other_kinds():
    presentation = _presentation(
        "voltage-divider",
        sidePreferences={"power": "left", "gnd": "right"},
    )
    result = _bind(_divider_circuit(), presentation)

    assert result.ok is True
    assert result.parts_of("upper_arm") == ("R1",)
    assert [item.kind for item in result.constraints] == [
        SAME_ROW, LEFT_OF, VERTICAL_TAP,
    ]
    assert "sidePreferences.power=left" in result.constraints[1].reason


def test_voltage_divider_multi_tap_ladder_with_a_parallel_branch():
    result = _bind(_ladder_circuit(), _presentation("voltage-divider"))

    assert result.ok is True
    assert result.parts_of("upper_arm") == ("R1",)
    assert result.parts_of("middle_arm") == ("R2",)
    assert result.parts_of("lower_arm") == ("R3",)
    assert result.parts_of("tap") == ("TAP1", "TAP2")
    assert result.parts_of("tap_branch") == ("C1",)

    # 每个抽头各自可见；链按电气序直连；并联支路归属抽头节点。
    assert [item.nets for item in _obligations(result, VISIBLE_TAP)] == [
        ("TAP1",), ("TAP2",),
    ]
    assert [item.nets for item in _obligations(result, DIRECT_WIRE)] == [
        ("VIN", "TAP1", "TAP2", "GND")
    ]
    assert [item.nets for item in _obligations(result, OWNED_BRANCH)] == [("TAP1",)]
    assert [(item.kind, item.subject, item.object) for item in result.constraints] == [
        (SAME_COLUMN, "R1", "R2"), (ABOVE, "R1", "R2"),
        (HORIZONTAL_TAP, "R1", "R2"),
        (SAME_COLUMN, "R2", "R3"), (ABOVE, "R2", "R3"),
        (HORIZONTAL_TAP, "R2", "R3"),
        (NEAR, "C1", "R1"),
    ]
    # 更长的阶梯优先绑定（多抽头是一次分压的更具体读法），支路不改链的选法；
    # 另一条读法（R1+C1）进 evidence，不被静默丢掉。
    assert "VIN→R1→TAP1→R2→TAP2→R3→GND" in result.bindings[0].evidence
    assert "other in→gnd chains found but not bound" in result.bindings[0].evidence
    assert "VIN→R1→TAP1→C1→GND" in result.bindings[0].evidence


def test_voltage_divider_chain_across_declared_modules_is_refused():
    presentation = _presentation(
        "voltage-divider",
        modules=[
            {"id": "m_left", "parts": ["R1"], "role": "bias"},
            {"id": "m_right", "parts": ["R2"], "role": "bias"},
        ],
    )
    result = _bind(_divider_circuit(), presentation)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "m_left" in failure.detail and "m_right" in failure.detail
    assert "modules[]" in failure.action


def test_voltage_divider_ai_asserted_facts_stay_visible_as_a_draft():
    result = _bind(_divider_circuit(provenance=AI), _presentation("voltage-divider"))

    assert result.ok is True  # 草稿也能绑，但必须看得出来
    assert all(f"provenance={AI}" in item.evidence for item in result.bindings)

    quiet = _circuit(
        [{"id": "R1", "symbolRef": "R0402"}, {"id": "R2", "symbolRef": "R0402"}],
        [
            {"id": "VIN", "class": "power", "members": ["R1.1"]},
            {"id": "TAP", "class": "signal", "members": ["R1.2", "R2.1"]},
            {"id": "GND", "class": "gnd", "members": ["R2.2"]},
        ],
    )
    silent = _bind(quiet, _presentation("voltage-divider"))
    assert silent.ok is True
    assert all(
        f"provenance={PROVENANCE_UNSTATED}" in item.evidence
        for item in silent.bindings
    )


# ----------------------------------------------------------------- rc-lowpass


def test_rc_lowpass_binds_the_trunk_and_the_branch_to_the_out_node():
    result = _bind(_rc_circuit(), _presentation("rc-lowpass"))

    assert result.ok is True
    assert result.parts_of("series") == ("R1",)
    assert result.parts_of("shunt") == ("C1",)
    assert result.net_of("in") == "VIN"
    assert result.net_of("out") == "OUT"
    assert result.net_of("gnd") == "GND"

    assert [(item.kind, item.subject, item.object) for item in result.constraints] == [
        (SAME_ROW, "R1", "C1"),
        (NEAR, "C1", "R1"),
    ]
    assert [item.nets for item in _obligations(result, DIRECT_WIRE)] == [
        ("VIN", "OUT"), ("OUT", "GND"),
    ]
    assert [item.nets for item in _obligations(result, OWNED_BRANCH)] == [("OUT",)]
    assert "hangs below the row" in result.constraints[0].reason


def test_rc_lowpass_without_a_branch_to_ground_is_circuit_invalid():
    spec = _circuit(
        [_part("R1"), _part("J1", "CONN-2P")],
        [
            _net("VIN", "power", ["R1.1"]),
            _net("OUT", "signal", ["R1.2"]),
            _net("GND", "gnd", ["J1.1"]),
        ],
    )
    result = _bind(spec, _presentation("rc-lowpass"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "R1(OUT,VIN)" in failure.detail
    assert "'out'" in failure.detail


def test_rc_lowpass_a_branch_that_does_not_return_to_ground_is_not_a_shunt():
    """挂在 out 上的两脚器件必须自己回到地：只到第三个网的不算支路（053 §三）。"""
    spec = _circuit(
        [_part("R1"), _part("C1", "C0402", "100n"), _part("J1", "CONN-2P")],
        [
            _net("VIN", "power", ["R1.1"]),
            _net("OUT", "signal", ["R1.2", "C1.1"]),
            _net("SENSE", "signal", ["C1.2"]),
            _net("GND", "gnd", ["J1.1"]),
        ],
    )
    result = _bind(spec, _presentation("rc-lowpass"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "R1(OUT,VIN)" in failure.detail
    assert "C1(OUT,SENSE)" in failure.detail
    assert "branch to ground" in failure.detail


def test_rc_lowpass_missing_rail_class_is_a_facts_missing_refusal():
    spec = _circuit(
        [_part("R1"), _part("C1", "C0402", "100n")],
        [
            _net("VIN", "signal", ["R1.1"]),
            _net("OUT", "signal", ["R1.2", "C1.1"]),
            _net("GND", "gnd", ["C1.2"]),
        ],
    )
    result = _bind(spec, _presentation("rc-lowpass"))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "class 'power'" in failure.detail
    assert "nets[].class" in failure.action


def test_rc_lowpass_binds_parallel_caps_and_a_ferrite_the_same_way():
    spec = _rc_circuit(shunts=("C1", "C2"), series="FB1", series_symbol="FB0603")
    result = _bind(spec, _presentation("rc-lowpass"))

    assert result.ok is True
    assert result.parts_of("series") == ("FB1",)
    assert result.parts_of("shunt") == ("C1", "C2")
    assert [item.kind for item in result.constraints] == [
        SAME_ROW, NEAR, SAME_ROW, NEAR,
    ]
    # 并联支路共用同一个归属节点与同一条地：义务只报一次，bindings 说明有几条。
    assert [item.nets for item in _obligations(result, OWNED_BRANCH)] == [("OUT",)]
    assert [item.nets for item in _obligations(result, DIRECT_WIRE)] == [
        ("VIN", "OUT"), ("OUT", "GND"),
    ]


# ----------------------------------------------------------------------- ldo


def test_ldo_binds_the_core_by_its_pin_roles_and_the_caps_by_their_nodes():
    result = _bind(_ldo_circuit(), _presentation("ldo"), _ldo_profiles())

    assert result.ok is True
    assert result.parts_of("core") == ("U1",)
    assert result.net_of("in") == "VIN5"
    assert result.net_of("out") == "3V3"
    assert result.net_of("gnd") == "GND"
    assert result.parts_of("in_caps") == ("C1",)
    assert result.parts_of("out_caps") == ("C2",)

    assert [(item.kind, item.subject, item.object) for item in result.constraints] == [
        (LEFT_OF, "C1", "U1"), (NEAR, "C1", "U1"),
        (RIGHT_OF, "C2", "U1"), (NEAR, "C2", "U1"),
    ]
    assert [item.nets for item in _obligations(result, DIRECT_WIRE)] == [("VIN5", "3V3")]
    assert [item.nets for item in _obligations(result, UNIFORM_GND)] == [("GND",)]
    assert [item.nets for item in _obligations(result, OWNED_BRANCH)] == [
        ("VIN5",), ("3V3",),
    ]
    core = result.bindings_for("core")[0]
    assert "VIN→spec pin 3 (matched by number)" in core.evidence
    assert "provenance=verified_recipe" in core.evidence


def test_ldo_without_any_symbol_profile_is_a_facts_missing_refusal():
    result = _bind(_ldo_circuit(), _presentation("ldo"), {})

    assert result.ok is False
    assert result.bindings == ()
    # 库缺口报一次，把缺 profile 的 part(symbolRef) 点名，而不是每个符号报一条。
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "U1(AMS1117-3.3)" in failure.detail
    assert "SymbolProfile" in failure.detail
    assert "from_parsed_symbol" in failure.action
    assert "never renumber pins" in failure.action


def test_ldo_profile_without_pin_roles_is_a_facts_missing_refusal():
    profile = SymbolProfile(
        symbol_ref="AMS1117-3.3",
        pins=[
            SymbolPin(number=str(index), name="", tip=(float(index), 0.0))
            for index in (1, 2, 3)
        ],
    )
    result = _bind(
        _ldo_circuit(),
        _presentation("ldo"),
        _ldo_profiles(profile=profile),
    )

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "no part maps VIN/VOUT/GND" in failure.detail
    assert "U1(AMS1117-3.3, 3V3/GND/VIN5)" in failure.detail


def test_ldo_unconnected_supply_pin_is_a_facts_missing_refusal():
    # U1.2 (VOUT) 没有被任何网提及，也没显式 NC。
    circuit = _circuit(
        [_part("U1", "AMS1117-3.3", "AMS1117-3.3"), _part("C1", "C0805", "10u")],
        [
            _net("VIN5", "power", ["U1.3", "C1.1"]),
            _net("GND", "gnd", ["U1.1", "C1.2"]),
        ],
    )
    result = _bind(circuit, _presentation("ldo"), _ldo_profiles(caps=("C0805",)))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert failure.subject == "U1"
    assert "VOUT pin" in failure.detail
    assert "<U1.2>" in failure.action
    assert "nc[]" in failure.action


def test_ldo_shorted_core_is_circuit_invalid():
    circuit = _circuit(
        [_part("U1", "AMS1117-3.3", "AMS1117-3.3"), _part("C1", "C0805", "10u")],
        [
            _net("VIN5", "power", ["U1.3", "U1.2", "C1.1"]),
            _net("GND", "gnd", ["U1.1", "C1.2"]),
        ],
    )
    result = _bind(circuit, _presentation("ldo"), _ldo_profiles(caps=("C0805",)))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "U1"
    assert "VIN and VOUT" in failure.detail
    assert "net VIN5" in failure.detail


def test_ldo_en_and_nr_variant_binds_the_auxiliary_branches():
    profile = _regulator_profile(
        symbol_ref="AMS1117-ADJ", extra=(("4", "EN"), ("5", "NR")),
    )
    result = _bind(
        _ldo_circuit_with_aux(),
        _presentation("ldo"),
        _ldo_profiles(symbol_ref="AMS1117-ADJ", profile=profile, caps=("C0805", "C0402", "C0402")),
    )

    assert result.ok is True
    assert result.parts_of("core") == ("U1",)
    assert result.parts_of("in_caps") == ("C1",)
    assert result.parts_of("out_caps") == ("C2",)
    assert result.parts_of("aux_branch") == ("R2", "C3")
    assert [item.nets for item in _obligations(result, OWNED_BRANCH)] == [
        ("VIN5",), ("3V3",), ("EN",), ("NR",),
    ]
    assert (NEAR, "R2", "U1") in [
        (item.kind, item.subject, item.object) for item in result.constraints
    ]
    assert "EN pin" in result.bindings_for("aux_branch")[0].evidence
    assert "NR pin" in result.bindings_for("aux_branch")[1].evidence


def test_ldo_without_caps_still_binds_the_trunk_and_the_ground_obligation():
    """电容是规则层的事，不是语法能不能绑的前提——语法只描述交进来的电路。

    代价说清楚：没有电容时，in/out 的左右只能由 sidePreferences 表达（约束的
    两端必须是器件），所以这一条不是漏绑，而是这一层没有器件可指。
    """
    circuit = _circuit(
        [_part("U1", "AMS1117-3.3", "AMS1117-3.3")],
        [
            _net("VIN5", "power", ["U1.3"]),
            _net("3V3", "power", ["U1.2"]),
            _net("GND", "gnd", ["U1.1"]),
        ],
    )
    result = _bind(circuit, _presentation("ldo"), _ldo_profiles(caps=()))

    assert result.ok is True
    assert result.parts_of("core") == ("U1",)
    assert result.parts_of("in_caps") == () and result.parts_of("out_caps") == ()
    assert result.constraints == ()
    assert [item.nets for item in _obligations(result, UNIFORM_GND)] == [("GND",)]
    assert [item.nets for item in _obligations(result, DIRECT_WIRE)] == [("VIN5", "3V3")]


def test_ldo_caps_are_collected_from_the_cores_own_module():
    presentation = _presentation(
        "ldo",
        modules=[
            {"id": "m_ldo", "parts": ["U1", "C2"], "role": "regulator"},
            {"id": "m_input", "parts": ["C1"], "role": "bulk"},
        ],
    )
    result = _bind(_ldo_circuit(), presentation, _ldo_profiles())

    assert result.ok is True
    # C1 与 U1 不在同一模块：它是那个模块的电容，不是这个 core 的 in_cap。
    assert result.parts_of("in_caps") == ()
    assert result.parts_of("out_caps") == ("C2",)
    assert [item.nets for item in _obligations(result, OWNED_BRANCH)] == [("3V3",)]


# ------------------------------------------------- 055 G1: duplicated role pins


#: The measured AMS1117 symbol (054 C3, LCSC C6186): GND/VOUT/VIN down the left
#: side and a **duplicate VOUT** (pin 4) on the right. The tips are the ones
#: `sch.component_pins` reported; the duplication is what 055 G1 is about.
def _duplicate_vout_profile(symbol_ref: str = "AMS1117-3.3-C6186") -> SymbolProfile:
    rows = (
        ("1", "GND", (-45.0, 10.0), "left"),
        ("2", "VOUT", (-45.0, 0.0), "left"),
        ("3", "VIN", (-45.0, -10.0), "left"),
        ("4", "VOUT", (45.0, 0.0), "right"),
    )
    return SymbolProfile(
        symbol_ref=symbol_ref, title=symbol_ref,
        body=(-35.5, -20.5, 35.5, 20.5),
        pins=[
            SymbolPin(
                number=number, name=role, tip=tip, direction=direction,
                direction_source="body-box", electrical_role=role,
                role_source="pin-name",
            )
            for number, role, tip, direction in rows
        ],
    )


def _duplicate_vout_circuit(*, out_members: list[str], nc: list[str] | None = None,
                            symbol_ref: str = "AMS1117-3.3-C6186") -> CircuitSpec:
    """The AMS1117 shape: which VOUT pin is wired, and which is an explicit NC."""
    return _circuit(
        [
            _part("U1", symbol_ref, "AMS1117-3.3"),
            _part("C1", "C0805", "10u"),
            _part("C2", "C0805", "22u"),
        ],
        [
            _net("VIN5", "power", ["U1.3", "C1.1"]),
            _net("3V3", "power", out_members),
            _net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
        nc=nc,
    )


def _duplicate_vout_profiles() -> dict:
    return _ldo_profiles(
        symbol_ref="AMS1117-3.3-C6186",
        profile=_duplicate_vout_profile(),
        caps=("C0805",),
    )


def test_role_pins_of_returns_every_pin_of_a_role_and_role_pins_the_first():
    """`role_pins` is a reading of "a" pin; the set is what a judgment may read."""
    profile = _duplicate_vout_profile()
    every = base.role_pins_of(profile)
    assert [pin.number for pin in every["VOUT"]] == ["2", "4"], "id-sorted"
    assert [pin.number for pin in every["VIN"]] == ["3"]
    assert sorted(every) == ["GND", "VIN", "VOUT"]
    assert base.role_pins(profile)["VOUT"].number == "2"


def test_a_role_is_connected_when_any_of_its_pins_is_a_net_member():
    """055 G1 (a): the duplicate VOUT wired, the left one NC — this used to be refused."""
    circuit_spec = _duplicate_vout_circuit(out_members=["U1.4", "C2.1"], nc=["U1.2"])
    result = _bind(circuit_spec, _presentation("ldo"), _duplicate_vout_profiles())

    assert result.ok is True
    assert result.parts_of("core") == ("U1",)
    assert result.net_of("out") == "3V3"
    assert result.parts_of("out_caps") == ("C2",)
    core = result.bindings_for("core")[0]
    assert "VOUT→spec pin 4 (matched by number)" in core.evidence
    assert "listed in nc[]" in core.evidence, (
        "the duplicate that was left alone is recorded as an explicit NC, not a gap"
    )
    assert "neither a net member nor an explicit nc" not in core.evidence


def test_the_left_duplicate_wired_and_the_right_one_nc_still_binds():
    """055 G1 (a), the other way round: nothing about the fix prefers one pin."""
    circuit_spec = _duplicate_vout_circuit(out_members=["U1.2", "C2.1"], nc=["U1.4"])
    result = _bind(circuit_spec, _presentation("ldo"), _duplicate_vout_profiles())

    assert result.ok is True
    assert result.net_of("out") == "3V3"
    core = result.bindings_for("core")[0]
    assert "VOUT→spec pin 2 (matched by number)" in core.evidence
    assert "listed in nc[]" in core.evidence


def test_both_duplicate_pins_on_one_net_are_one_node_not_a_short():
    """Both VOUT pins wired to 3V3: one role on one node — a bind, not a short."""
    circuit_spec = _duplicate_vout_circuit(
        out_members=["U1.2", "U1.4", "C2.1"]
    )
    result = _bind(circuit_spec, _presentation("ldo"), _duplicate_vout_profiles())

    assert result.ok is True
    assert result.net_of("out") == "3V3"
    assert "pins 2, 4 are all on net 3V3" in result.bindings_for("core")[0].evidence
    assert "one role, one node" in result.bindings_for("core")[0].evidence


def test_duplicate_pins_on_two_nets_are_refused_as_a_short_between_them():
    """The pins are one node inside the symbol: two nets is a contradiction."""
    circuit_spec = _circuit(
        [
            _part("U1", "AMS1117-3.3-C6186", "AMS1117-3.3"),
            _part("C1", "C0805", "10u"),
            _part("C2", "C0805", "22u"),
        ],
        [
            _net("VIN5", "power", ["U1.3", "C1.1"]),
            _net("3V3", "power", ["U1.2", "C2.1"]),
            _net("VA", "power", ["U1.4"]),
            _net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )
    result = _bind(circuit_spec, _presentation("ldo"), _duplicate_vout_profiles())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "U1"
    assert "VOUT" in failure.detail and "2, 4" in failure.detail
    assert "3V3" in failure.detail and "VA" in failure.detail


def test_every_duplicate_pin_nc_is_refused_naming_all_of_them():
    """A role whose every pin is NC has no node to bind — named, never silent."""
    circuit_spec = _duplicate_vout_circuit(
        out_members=["C2.1"], nc=["U1.2", "U1.4"]
    )
    result = _bind(circuit_spec, _presentation("ldo"), _duplicate_vout_profiles())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "U1"
    assert "every VOUT pin" in failure.detail
    assert "2, 4" in failure.detail
    assert "<U1.2>" in failure.action and "<U1.4>" in failure.action


def test_an_unmentioned_duplicate_is_still_a_facts_missing_refusal():
    """055 G1 (b) does not turn silence into a decision: NC must be written."""
    circuit_spec = _duplicate_vout_circuit(out_members=["C2.1"])
    result = _bind(circuit_spec, _presentation("ldo"), _duplicate_vout_profiles())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "VOUT pin" in failure.detail
    assert "nc[]" in failure.action


# ------------------------------------------------------------ cross-grammar


def _cases():
    """Every grammar's standard case, as (name, circuit, presentation, profiles)."""
    return [
        ("voltage-divider", _divider_circuit(), _presentation("voltage-divider"), None),
        ("rc-lowpass", _rc_circuit(), _presentation("rc-lowpass"), None),
        (
            "ldo",
            _ldo_circuit(),
            _presentation("ldo"),
            _ldo_profiles(),
        ),
    ]


def test_each_grammar_satisfies_the_protocol_and_carries_its_name():
    for name, _circuit_spec, _presentation_spec, _profiles in _cases():
        instance = grammar.grammar_for(name)
        assert isinstance(instance, DrawingGrammar)
        assert instance.name == name
    # 088 adds the fourth literal; this is a registration list, not a 053 claim.
    assert grammar.NAMES == ("voltage-divider", "rc-lowpass", "ldo", "power-entry")


def test_bind_is_deterministic_byte_for_byte():
    for name, circuit_spec, presentation_spec, profiles in _cases():
        first = _bind(circuit_spec, presentation_spec, profiles)
        second = _bind(
            type(circuit_spec).from_dict(circuit_spec.to_jsonable()),
            type(presentation_spec).from_dict(presentation_spec.to_jsonable()),
            dict(profiles) if profiles else None,
        )
        assert first == second
        assert repr(first) == repr(second)
        assert (
            json.dumps(first.to_jsonable(), sort_keys=True)
            == json.dumps(second.to_jsonable(), sort_keys=True)
        )


def test_the_result_types_carry_no_coordinates_and_keep_the_fixed_fields():
    """接口逐字：编译器批次消费的字段名，一个不多一个不少。"""
    assert [item.name for item in dataclasses.fields(RoleBinding)] == [
        "role", "part_id", "evidence",
    ]
    assert [item.name for item in dataclasses.fields(RelativeConstraint)] == [
        "kind", "subject", "object", "reason",
    ]
    assert [item.name for item in dataclasses.fields(GrammarObligation)] == [
        "kind", "nets", "reason",
    ]
    assert [item.name for item in dataclasses.fields(GrammarFailure)] == [
        "category", "detail", "action", "subject",
    ]
    assert [item.name for item in dataclasses.fields(GrammarResult)] == [
        "ok", "bindings", "constraints", "obligations", "failures",
    ]
    banned = {
        "x", "y", "rotation", "angle", "mirror", "dx", "dy", "points", "bbox",
        "wirepoints", "waypoints", "segments", "junctions", "primitiveid",
        "connectoraction", "at",
    }
    for cls in (RoleBinding, RelativeConstraint, GrammarObligation, GrammarResult):
        for field in dataclasses.fields(cls):
            assert field.name.lower() not in banned, f"{cls.__name__}.{field.name}"


def test_the_kind_universes_are_exactly_what_is_documented():
    assert CONSTRAINT_KINDS == (
        "same-column", "same-row", "above", "below", "left-of", "right-of",
        "adjacent", "near", "horizontal-tap", "vertical-tap",
    )
    assert OBLIGATION_KINDS == (
        "direct-wire", "visible-tap", "owned-branch", "uniform-gnd", "gnd-outlet",
    )
    assert FAILURE_CATEGORIES == (
        "facts-missing", "circuit-invalid", "layout-unsat", "presentation-poor",
    )
    for _name, circuit_spec, presentation_spec, profiles in _cases():
        result = _bind(circuit_spec, presentation_spec, profiles)
        assert {item.kind for item in result.constraints} <= set(CONSTRAINT_KINDS)
        assert {item.kind for item in result.obligations} <= set(OBLIGATION_KINDS)


def test_the_role_tables_are_the_task_books_plus_the_documented_additions():
    assert voltage_divider.ROLES == (
        "upper_arm", "lower_arm", "tap", "in", "gnd",
    )
    assert rc_lowpass.ROLES == ("series", "shunt", "in", "out", "gnd")
    assert ldo.ROLES == ("core", "in_caps", "out_caps", "in", "out", "gnd")
    assert voltage_divider.EXTRA_ROLES == ("middle_arm", "tap_branch")
    assert rc_lowpass.ROLES and not getattr(rc_lowpass, "EXTRA_ROLES", ())
    assert ldo.EXTRA_ROLES == ("aux_branch",)

    for name, circuit_spec, presentation_spec, profiles in _cases():
        result = _bind(circuit_spec, presentation_spec, profiles)
        allowed = set(grammar.ROLES_BY_GRAMMAR[name])
        assert {item.role for item in result.bindings} <= allowed


def test_the_dispatcher_takes_the_documents_choice_and_refuses_the_unknown():
    circuit_spec = _divider_circuit()
    chosen = grammar.bind(circuit_spec, _presentation("voltage-divider"))
    assert chosen.ok is True

    override = grammar.bind(
        _circuit(
            [_part("R1"), _part("R2")],
            [
                _net("VIN", "power", ["R1.1", "R2.1"]),
                _net("GND", "gnd", ["R1.2", "R2.2"]),
            ],
        ),
        _presentation("voltage-divider"),
        grammar_name="rc-lowpass",
    )
    assert override.ok is False  # 并联两臂按 RC 读：没有分跨 in/out 的串联器件
    assert {item.category for item in override.failures} == {FAILURE_CIRCUIT_INVALID}

    silent = grammar.bind(circuit_spec, _presentation(""))
    (failure,) = silent.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "grammarRef" in failure.detail
    assert "voltage-divider" in failure.action

    unknown = grammar.bind(
        circuit_spec, _presentation("voltage-divider"), grammar_name="buck-boost",
    )
    (failure,) = unknown.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert "'buck-boost'" in failure.detail
    assert "rc-lowpass" in failure.action

    # 文档层面更早一关：PresentationSpec 自己就拒绝未知语法（053 阶段 A），
    # 所以模型的输入根本走不到 dispatcher。
    with pytest.raises(PresentationSpecError, match="buck-boost"):
        _presentation("buck-boost")

    with pytest.raises(GrammarError, match="unknown grammar"):
        grammar.grammar_for("buck-boost")


def test_a_refused_result_carries_no_bindings_and_the_contradictions_are_refused():
    refusals = [
        _bind(_divider_circuit(), _presentation("voltage-divider"), None),
        _bind(
            _circuit(
                [_part("R1"), _part("R2")],
                [
                    _net("VIN", "signal", ["R1.1"]),
                    _net("GND", "signal", ["R2.2"]),
                    _net("TAP", "signal", ["R1.2", "R2.1"]),
                ],
            ),
            _presentation("voltage-divider"),
        ),
    ]
    assert refusals[0].ok is True
    assert refusals[1].ok is False
    assert refusals[1].bindings == () and refusals[1].constraints == ()
    assert refusals[1].obligations == ()
    assert refusals[1].failures

    with pytest.raises(GrammarError, match="cannot be ok and carry failures"):
        GrammarResult(
            ok=True,
            failures=(
                GrammarFailure(
                    category=FAILURE_FACTS_MISSING, detail="something missing",
                ),
            ),
        )
    with pytest.raises(GrammarError, match="states no failure"):
        refused_result(())
    with pytest.raises(GrammarError, match="unknown constraint kind"):
        RelativeConstraint(kind="diagonal", subject="R1", object="R2", reason="x")
    with pytest.raises(GrammarError, match="unknown obligation kind"):
        GrammarObligation(kind="looks-nice", nets=("VIN",), reason="x")
    with pytest.raises(GrammarError, match="unknown failure category"):
        GrammarFailure(category="ugly", detail="x")
    with pytest.raises(GrammarError, match="names no net"):
        GrammarObligation(kind=DIRECT_WIRE, nets=(), reason="x")
    with pytest.raises(GrammarError, match="evidence is empty"):
        RoleBinding(role="tap", part_id="TAP", evidence="")
    with pytest.raises(GrammarError, match="object is empty"):
        RelativeConstraint(kind=NEAR, subject="C1", object="", reason="x")


def test_weakest_provenance_is_the_one_an_evidence_string_prints():
    assert weakest_provenance("verified_recipe", "engineer_confirmed") == (
        "engineer_confirmed"
    )
    assert weakest_provenance("engineer_confirmed", "ai_asserted") == "ai_asserted"
    assert weakest_provenance("verified_recipe", "") == PROVENANCE_UNSTATED
    assert weakest_provenance() == PROVENANCE_UNSTATED


def test_a_failure_states_its_reason_and_an_action_where_one_exists():
    cases = [
        _bind(
            _circuit(
                [_part("R1"), _part("R2")],
                [
                    _net("VIN", "signal", ["R1.1"]),
                    _net("TAP", "signal", ["R1.2", "R2.1"]),
                    _net("GND", "signal", ["R2.2"]),
                ],
            ),
            _presentation("voltage-divider"),
        ),
        _bind(
            _circuit(
                [_part("R1")],
                [
                    _net("VIN", "power", ["R1.1"]),
                    _net("OUT", "signal", ["R1.2"]),
                ],
            ),
            _presentation("rc-lowpass"),
            None,
        ),
    ]
    for result in cases:
        assert result.ok is False
        for failure in result.failures:
            assert failure.detail
            assert failure.category in FAILURE_CATEGORIES
    assert all(item.action for item in cases[0].failures)
