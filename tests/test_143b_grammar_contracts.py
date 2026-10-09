"""143b：`grammar/` 目录七条洞的回归钉（H1–H7，来源 `outputs/143_dig/04/report.md`）。

一条一节，节名即洞号。每条都钉两件事：**修好的那一面**，以及**同一疾病的
同义拼写**（"修家族不修 witness" —— 只钉 witness 的测试正是这一批要治的病）。

约定与既有语法测试一致：电路/图纸全部手写字面量，符号库复用
`test_113_flyback_grammar.library()`，power-entry 复用 `test_088_power_entry`
的样板构造器。测试之间不共享可变状态。
"""

from __future__ import annotations

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import grammar as grammar_registry
from boardwise.engines.grammar import base, flyback, rc_lowpass
from boardwise.engines.grammar.base import (
    ABOVE,
    BELOW,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    GrammarError,
    GrammarObligation,
    LEFT_OF,
    RIGHT_OF,
    UNIFORM_GND,
)

import test_088_power_entry as t088
import test_113_flyback_grammar as t113

PROV = t113.PROV


# ------------------------------------------------------------------ 工具


def _add_part(circuit: CircuitSpec, part_id: str, pins: dict[str, list[str]],
              symbol: str = "C") -> CircuitSpec:
    """在既有电路上加一颗两脚件，并按 `pins` 把它挂到已存在的网上。"""
    payload = circuit.to_jsonable()
    payload["parts"].append(
        {"id": part_id, "symbolRef": symbol, "provenance": PROV}
    )
    for net_id, members in pins.items():
        for net in payload["nets"]:
            if net["id"] == net_id:
                net["members"].extend(members)
                break
        else:
            raise AssertionError(f"net {net_id} does not exist")
    return CircuitSpec.from_dict(payload)


def _rename_part(circuit: CircuitSpec, old: str, new: str) -> CircuitSpec:
    """只改位号：电路一个字不动（H1 的对照实验就是这么做的）。"""
    payload = circuit.to_jsonable()
    for part in payload["parts"]:
        if part["id"] == old:
            part["id"] = new
    for net in payload["nets"]:
        net["members"] = [
            new + member[len(old):] if member.startswith(old + ".") else member
            for member in net["members"]
        ]
    return CircuitSpec.from_dict(payload)


def _led_anode_on_the_output_rail() -> CircuitSpec:
    """光耦 LED 阳极直接并到输出轨（省掉串阻 R9）—— 报告 §H2 的现实触发。"""
    payload = t113.minimal_circuit().to_jsonable()
    payload["parts"] = [p for p in payload["parts"] if p["id"] != "R9"]
    for net in payload["nets"]:
        net["members"] = [m for m in net["members"] if not m.startswith("R9.")]
        if net["id"] == "VOUT":
            net["members"].append("U5.1")
        if net["id"] == "LED_A":
            net["members"] = [m for m in net["members"] if m != "U5.1"]
    payload["nets"] = [n for n in payload["nets"] if n["members"]]
    return CircuitSpec.from_dict(payload)


def _bind(circuit: CircuitSpec, presentation: PresentationSpec | None = None):
    return flyback.FlybackGrammar(t113.library()).bind(
        circuit, presentation or t113.minimal_presentation()
    )


def _detail(result) -> str:
    return " ".join(item.detail for item in result.failures)


def _state(circuit: CircuitSpec) -> flyback._State:
    return flyback._State(
        circuit,
        base.two_terminal_parts(circuit),
        base.nets_of_class(circuit, "power"),
        base.nets_of_class(circuit, "gnd"),
    )


# ==================================================================== H1
# flyback 的"没有隔离器件"诊断曾是无条件假报：第 4 个实参是空串，anchor
# 排除不掉变压器，报哪一条由位号字典序裁决。


def test_h1_a_missing_sense_resistor_is_reported_as_an_unread_primary_stage():
    """拆掉采样电阻（原边的事，与光耦无关）：诊断必须说清**哪一节读不出**。

    旧行为：报"no isolation barrier … Multi-net parts here: T1, U5" ——
    同一句话里否认隔离带又列出光耦，而且四种破坏（R5/D3/R7/U5）报同一条。
    """
    result = _bind(t113._without_part(t113.minimal_circuit(), "R5"))
    assert not result.ok
    assert result.failures[0].category == FAILURE_CIRCUIT_INVALID
    detail = _detail(result)
    assert "the primary stage and the winding ends" in detail
    assert "not read" in detail
    assert "isolation barrier" not in detail, (
        "拆采样电阻不是'没有隔离器件'：光耦还在，报隔离带缺失是假警报"
    )


def test_h1_the_diagnosis_does_not_depend_on_the_designator_order():
    """同一条破坏，只把变压器位号 `T1` 改成 `Z9`：诊断必须逐字相同。

    旧行为：`Z9` 让 `U4` 排到 anchor 前面，诊断从"没有隔离器件"换成
    "the chain does not close" —— 也就是"报哪一条"由字母序裁决。
    """
    broken = t113._without_part(t113.minimal_circuit(), "R5")
    renamed = _rename_part(broken, "T1", "Z9")
    first = _bind(broken)
    second = _bind(renamed)
    assert not first.ok and not second.ok
    assert first.failures[0].category == second.failures[0].category
    # 位号当然会出现在拒绝文里（"变压器形状的是 Z9"），也会出现在 `_listing`
    # 里；所以把位号抹平、并只比较**说法**那一段（页面上有什么的清单按位号排序，
    # 换个名字自然换位置，那不是诊断的差别）。
    assert first.failures[0].detail.split("What is on the page")[0] == (
        second.failures[0].detail.replace("Z9", "T1")
        .split("What is on the page")[0]
    )


def test_h1_a_missing_optocoupler_is_refused_because_the_barrier_is_absent():
    """真的拆掉光耦：这一条**才是**"没有隔离器件"，而且理由必须是隔离带本身。

    这条测试是 113 那条同名测试的加强版：113 里它断言 detail 里有
    "isolation barrier"，而修复前那句来自**无条件假报的分支**（见 H1），
    所以它当时是"因错误原因通过"——任何一条破坏都能让它绿。现在它钉的是
    分支本身：报隔离带缺失，就不许再报"某一节没读出"。
    """
    result = _bind(t113._without_part(t113.minimal_circuit(), "U5"))
    assert not result.ok
    assert result.failures[0].category == FAILURE_CIRCUIT_INVALID
    detail = _detail(result)
    assert "no part closes the feedback loop across the two ground families" in detail
    assert "PGND" in detail and "SEC_GND" in detail
    assert "not read" not in detail, (
        "没有隔离器件时链条本身是通的：诊断不该回头说某一节没读出"
    )


def test_h1_a_missing_rectifier_names_the_secondary_leg_as_unread():
    """拆整流管：原边读得出、副边读不出 —— 诊断必须说这两句。"""
    result = _bind(t113._without_part(t113.minimal_circuit(), "D3"))
    detail = _detail(result)
    assert "the primary stage and the winding ends" in detail
    assert "read; the secondary rectifier" in detail
    assert "not read" in detail
    assert "isolation barrier" not in detail


def test_h1_a_missing_divider_arm_names_the_feedback_leg_as_unread():
    """拆分压上臂：原边、副边都读得出，反馈链读不出。"""
    result = _bind(t113._without_part(t113.minimal_circuit(), "R7"))
    detail = _detail(result)
    assert "the secondary rectifier (winding → rectifier → output rail): read" in detail
    assert "the feedback chain (divider → error amplifier → LED cathode): not read" in detail
    assert "isolation barrier" not in detail


def test_h1_a_deleted_transformer_is_not_reported_through_the_opto():
    """拆掉 T1：`U5` 也是四网件，但它不是"变压器形状"。

    旧的入口判据只数脚（`len(nets) >= 4`），于是 T1 不在时 `U5` 顶上，
    拒绝文会说"this circuit has a transformer-shaped part (U5)" —— 一件
    四脚光耦被说成变压器。
    """
    result = _bind(t113._without_part(t113.minimal_circuit(), "T1"))
    detail = _detail(result)
    assert "no transformer here" in detail
    assert "transformer-shaped" not in detail
    assert "U5" not in detail.split("What is on the page")[0]


def test_h1_the_anchor_shape_is_never_read_as_the_error_amplifier():
    """就算调用方不知道 anchor 是谁（空串），变压器也不许被当成误差放大器。

    旧洞的机制就是这个：`_isolation_device(..., "")` 的"空串=不排除任何件"只是
    注释里的意思，代码按 **id** 排除，于是什么都没排除，`T1` 成了"误差放大器"、
    `SW` 成了"LED 阴极"。现在的守卫是形状：四网及以上不是小信号放大器。
    """
    state = _state(t113.minimal_circuit())
    assert flyback._error_amp_for(state, "SEC_GND", "") == "U4"
    assert flyback._error_amp_for(state, "SEC_GND", "T1") == "U4"
    # 阴极也不能被读成变压器的绕线节点
    assert flyback._cathode_node(state, "U4", "SEC_GND", "FB_SENSE", "U5") == "LED_K"


# ==================================================================== H2
# `_error_amp_on` 少了孪生函数的守卫 + 空阴极不过滤 → 空网名进义务 + 幽灵 rank。


def test_h2_a_two_terminal_part_is_never_the_error_amplifier():
    """两脚件是 element，不是误差放大器 —— 两条孪生判据必须同一条守卫。

    旧行为：`LED_A` 并到输出轨后，输出电容 C11 被绑成 `error-amp`（`C11 < U4`
    的字母序裁决），第三条 direct-wire 义务写成 `('FB_SENSE', '')`。
    """
    for label, circuit in (
        ("LED anode on the output rail", _led_anode_on_the_output_rail()),
        ("a cap across LED_A..SEC_GND",
         _add_part(t113.minimal_circuit(), "C12",
                   {"LED_A": ["C12.1"], "SEC_GND": ["C12.2"]})),
    ):
        state = _state(circuit)
        on = flyback._error_amp_on(state, "SEC_GND", "U5", "T1")
        assert "C11" not in on and "C12" not in on, label
        assert on == ["U4"], label
        result = _bind(circuit)
        assert result.ok, label
        assert result.parts_of("error-amp") == ("U4",), label


def test_h2_no_obligation_ever_names_an_empty_net():
    """空网名不许进公开契约：义务里每个网名都必须是真网。"""
    for label, circuit in (
        ("baseline", t113.minimal_circuit()),
        ("LED anode on the output rail", _led_anode_on_the_output_rail()),
        ("a cap across LED_A..SEC_GND",
         _add_part(t113.minimal_circuit(), "C12",
                   {"LED_A": ["C12.1"], "SEC_GND": ["C12.2"]})),
        ("a cap across LED_K..VOUT",
         _add_part(t113.minimal_circuit(), "C12",
                   {"LED_K": ["C12.1"], "VOUT": ["C12.2"]})),
    ):
        result = _bind(circuit)
        assert result.ok, label
        for item in result.obligations:
            assert all(item.nets), f"{label}: {item.kind} {item.nets}"
            for net_id in item.nets:
                assert circuit.net(net_id) is not None, (
                    f"{label}: {item.kind} promises {net_id!r}, which this "
                    "circuit does not declare — that is the phantom net H2 put "
                    "into the compiler's chain rank"
                )


def test_h2_every_reading_carries_the_cathode_its_own_opto_drives():
    """半截 reading 不再产生：阴极读不出就不发 reading；发出来的阴极必须在光耦脚上。"""
    for label, circuit in (
        ("baseline", t113.minimal_circuit()),
        ("LED anode on the output rail", _led_anode_on_the_output_rail()),
        ("a cap across LED_K..SEC_GND",
         _add_part(t113.minimal_circuit(), "C12",
                   {"LED_K": ["C12.1"], "SEC_GND": ["C12.2"]})),
    ):
        state = _state(circuit)
        readings = flyback._readings(state)
        assert readings, label
        for reading in readings:
            assert reading.led_cathode, f"{label}: an empty cathode got out"
            assert reading.led_cathode in state.part_nets[reading.opto], (
                f"{label}: {reading.led_cathode} is not one of {reading.opto}'s nets"
            )


def test_h2_the_reading_key_names_the_roles_that_used_to_tie():
    """两条不同的 reading 不许有同一个 key —— 否则排序的稳定性就是位号序。"""
    for label, circuit in (
        ("baseline", t113.minimal_circuit()),
        ("a cap across LED_A..SEC_GND",
         _add_part(t113.minimal_circuit(), "C12",
                   {"LED_A": ["C12.1"], "SEC_GND": ["C12.2"]})),
        ("a cap across LED_K..SEC_GND",
         _add_part(t113.minimal_circuit(), "C12",
                   {"LED_K": ["C12.1"], "SEC_GND": ["C12.2"]})),
    ):
        readings = flyback._readings(_state(circuit))
        keys = [flyback._reading_key(reading) for reading in readings]
        assert len(set(keys)) == len(keys), f"{label}: two readings share a key"


def test_h2_the_obligation_constructor_refuses_an_empty_net_name():
    """契约本身也要挡：构造期就炸，而不是等编译器给幽灵网排 rank。"""
    with pytest.raises(GrammarError):
        GrammarObligation(kind=DIRECT_WIRE, nets=("A", ""), reason="x")
    with pytest.raises(GrammarError):
        GrammarObligation(kind=UNIFORM_GND, nets=("",), reason="x")
    # 正常的那条照旧成立（这条守卫只管空网名）。
    assert GrammarObligation(
        kind=DIRECT_WIRE, nets=("A", "B"), reason="x").nets == ("A", "B")


# ==================================================================== H3
# LED 阴极并一颗两脚件 → 整条合法反激被 circuit-invalid 拒收。


def test_h3_a_compensation_capacitor_on_the_led_does_not_erase_the_reading():
    """`VOUT—C—LED_K` 与 `LED_K—C—SEC_GND` 都是合法反激，必须绑得上。

    旧行为：阴极判据是"没有两脚件把它拉到 gnd/power"，于是这两颗常见补偿电容
    让阴极读成 `""`、reading 归零，整条语法拒收（还引 H1 的假诊断）。
    """
    for label, pins in (
        ("VOUT—C—LED_K", {"VOUT": ["C12.1"], "LED_K": ["C12.2"]}),
        ("LED_K—C—SEC_GND", {"LED_K": ["C12.1"], "SEC_GND": ["C12.2"]}),
        ("VOUT—R—LED_K (a pull-up)", {"VOUT": ["R20.1"], "LED_K": ["R20.2"]}),
    ):
        symbol = "R" if "R—" in label else "C"
        part_id = "R20" if symbol == "R" else "C12"
        circuit = _add_part(t113.minimal_circuit(), part_id, pins, symbol=symbol)
        result = _bind(circuit)
        assert result.ok, f"{label}: {_detail(result)}"
        assert result.parts_of("error-amp") == ("U4",), label
        cull = [item.nets for item in result.obligations
                if item.kind == DIRECT_WIRE]
        assert ("FB_SENSE", "LED_K") in cull, label


def test_h3_the_cathode_is_the_taps_partner_not_the_untied_net():
    """判据本身：阴极 = 误差放大器的非地非电源网里**不是分压抽头**的那个。

    抽头是分压两臂的交点（`_divider_strings` 已经读出来了），所以它按"就是
    抽头"排除；旧实现用"有没有两脚件拉到 gnd/power"当抽头的替身，那个替身
    在阴极上并一颗旁路/补偿件时就同时命中抽头**和阴极**。
    """
    for label, pins in (
        ("plain", None),
        ("VOUT—C—LED_K", {"VOUT": ["C12.1"], "LED_K": ["C12.2"]}),
        ("LED_K—C—SEC_GND", {"LED_K": ["C12.1"], "SEC_GND": ["C12.2"]}),
    ):
        circuit = t113.minimal_circuit()
        if pins:
            circuit = _add_part(circuit, "C12", pins)
        state = _state(circuit)
        assert flyback._cathode_node(state, "U4", "SEC_GND", "FB_SENSE", "U5") == (
            "LED_K"), label
        assert flyback._cathode_candidates(state, "U4", "SEC_GND", ("FB_SENSE",)) == (
            ["LED_K"]), label


# ==================================================================== H4
# flyback 硬编码 in_side/out_side，sidePreferences 整条被忽略还伪造出处。


MIRROR = PresentationSpec.from_dict({
    "kind": "boardwise-presentation-spec",
    "specVersion": 1,
    "grammarRef": "flyback",
    "sidePreferences": {
        "input": "right", "output": "left", "power": "bottom", "gnd": "top",
    },
    "portRoles": {"VOUT": "output", "HVDC": "input"},
})


def _kinds(result) -> dict[tuple[str, str], str]:
    return {(item.subject, item.object): item.kind for item in result.constraints}


def test_h4_the_default_page_is_unchanged():
    """默认声明（input left / output right / gnd bottom）下，约束一个字不变。

    H4 的修法要把侧向接到 `sidePreferences`，而"默认行为不变"是硬要求：
    这条把默认页的全部关系钉成一张表。
    """
    result = _bind(t113.minimal_circuit(), t113.minimal_presentation())
    assert result.ok
    assert _kinds(result) == {
        ("Q1", "T1"): BELOW,
        ("Q1", "R5"): base.SAME_COLUMN,
        ("R5", "Q1"): BELOW,
        ("C11", "D3"): BELOW,
        ("C11", "T1"): base.NEAR,
        ("D3", "T1"): base.NEAR,
        ("U5", "U4"): LEFT_OF,
        ("R7", "U4"): base.NEAR,
        ("R8", "U4"): base.NEAR,
    }


def test_h4_a_mirrored_declaration_mirrors_the_drawing():
    """图纸声明镜像时，方向必须跟着声明走（这是岳裁的横向布局前置）。

    旧行为：约束列表与理由字符串逐字相同（声明被整条忽略），而理由还写着
    "per sidePreferences" —— 伪造出处。
    """
    default = _bind(t113.minimal_circuit(), t113.minimal_presentation())
    mirror = _bind(t113.minimal_circuit(), MIRROR)
    assert default.ok and mirror.ok
    assert _kinds(mirror) == {
        ("Q1", "T1"): ABOVE,
        ("Q1", "R5"): base.SAME_COLUMN,
        ("R5", "Q1"): ABOVE,
        ("C11", "D3"): ABOVE,
        ("C11", "T1"): base.NEAR,
        ("D3", "T1"): base.NEAR,
        ("U5", "U4"): RIGHT_OF,
        ("R7", "U4"): base.NEAR,
        ("R8", "U4"): base.NEAR,
    }


def test_h4_a_reason_that_cites_sidepreferences_cites_the_declaration():
    """理由里写 'per sidePreferences' 的，必须引的是**这张图纸**声明的侧。

    镜像页上不许再出现 `output side 'right'` / `gnd='bottom'` 这类句子：那正是
    "证据伪造出处"的形状。
    """
    mirror = _bind(t113.minimal_circuit(), MIRROR)
    assert mirror.ok
    cited = [item for item in (*mirror.constraints, *mirror.obligations)
             if "sidePreferences" in item.reason]
    assert cited
    for item in cited:
        assert "sidePreferences" in item.reason
    joined = " ".join(item.reason for item in cited)
    assert "sidePreferences.gnd='top'" in joined
    assert "power side 'bottom'" in joined
    assert "output side 'left'" in joined
    assert "gnd='bottom'" not in joined
    assert "power side 'top'" not in joined
    assert "output side 'right'" not in joined


def test_h4_both_horizontal_directions_are_read_not_just_the_output():
    """输入侧也得读：它出现在主环义务的理由里（旧行为里 `in_side` 只进文案）。"""
    result = _bind(t113.minimal_circuit(), MIRROR)
    primary = [item for item in result.obligations
               if item.kind == DIRECT_WIRE and "HVDC" in item.nets]
    assert primary
    assert "input side 'right'" in primary[0].reason


# ==================================================================== H5
# power_entry 放行空 direction → 体电容被当成入口终结者。


def _power_entry(interfaces: list[dict]):
    payload = t088.inlet_circuit().to_jsonable()
    payload["openInterfaces"] = interfaces
    return CircuitSpec.from_dict(payload)


def _bind_entry(circuit):
    return grammar_registry.grammar_for("power-entry").bind(
        circuit, t088.inlet_presentation()
    )


def test_h5_an_entry_without_a_direction_is_not_an_entry():
    """`direction` 缺省为空 = "图纸没说"，不是 input。

    旧行为：`if item.direction and ...` 让空串短路，于是把一颗体电容写成 `part`
    就等于把它绑成入口、真连接器降级成 shunt，evidence 还凭空打印
    `direction=input`（`_claim_note` 同样凭空补 input）。
    """
    circuit = _power_entry([{
        "net": t088.RAIL, "role": "rail", "part": "C115", "provenance": t088.PROV,
    }])
    result = _bind_entry(circuit)
    assert not result.ok
    assert result.failures[0].category == FAILURE_FACTS_MISSING
    detail = result.failures[0].detail
    assert "no direction that means the supply enters here" in detail
    assert "input" in detail and "source" in detail
    assert result.bindings == ()


def test_h5_the_refusal_names_the_missing_half_not_the_part():
    """缺的那一半要说对：part 写了、direction 没写 → 让读者去写 direction。"""
    circuit = _power_entry([{
        "net": t088.RAIL, "role": "rail", "part": "CN1", "provenance": t088.PROV,
    }])
    result = _bind_entry(circuit)
    assert not result.ok
    detail = result.failures[0].detail
    assert "no direction that means the supply enters here" in detail
    assert "no part" not in detail, "part 写了，说'没有 part'会把人引到已经写好的地方"
    assert "direction=" in detail


def test_h5_a_declared_entry_still_binds_and_the_evidence_quotes_it():
    """有 direction 的正常入口照旧（这条是回归）。"""
    result = _bind_entry(t088.inlet_circuit())
    assert result.ok
    assert result.parts_of("entry") == ("CN1",)
    evidence = result.bindings_for("entry")[0].evidence
    assert "direction=input" in evidence
    assert "direction=unspecified" not in evidence


def test_h5_no_evidence_invents_a_direction():
    """整条语法里不许再出现 `direction or 'input'` 这种替身。"""
    source = (base.__file__.replace("base.py", "power_entry.py"))
    text = open(source, encoding="utf-8").read()
    assert "direction or 'input'" not in text
    assert "direction or \"input\"" not in text


# ==================================================================== H6
# rc-lowpass 两颗 shunt 挂不同地族时，第二颗的证据伪造地网名。


def _two_family_lowpass() -> CircuitSpec:
    """`VIN—R1—OUT`，`C1/C3→GNDA`，`C2→GNDB`。"""
    return CircuitSpec.from_dict({
        "parts": [{"id": p, "symbolRef": "R", "provenance": PROV}
                  for p in ("R1", "C1", "C2", "C3")],
        "nets": [
            {"id": "VIN", "class": "power", "members": ["R1.1"], "provenance": PROV},
            {"id": "OUT", "class": "signal",
             "members": ["R1.2", "C1.1", "C2.1", "C3.1"], "provenance": PROV},
            {"id": "GNDA", "class": "gnd", "members": ["C1.2", "C3.2"],
             "provenance": PROV},
            {"id": "GNDB", "class": "gnd", "members": ["C2.2"], "provenance": PROV},
        ],
    })


def _bind_lowpass(circuit: CircuitSpec):
    return rc_lowpass.RcLowpassGrammar().bind(
        circuit, PresentationSpec.from_dict({"grammarRef": "rc-lowpass"})
    )


def test_h6_a_shunt_is_bound_to_the_ground_it_is_actually_on():
    """一个候选一个地网：绑进来的 shunt 必须真的在这条地网上。

    旧行为：`_shunts` 收"任一 gnd 类网"的并集，`_return_net` 再挑一个，
    于是 `C2`（在 GNDB）的 evidence 说"to ground GNDA" —— 报告层造假。
    """
    result = _bind_lowpass(_two_family_lowpass())
    assert result.ok
    assert result.net_of("gnd") == "GNDA"
    assert sorted(result.parts_of("shunt")) == ["C1", "C3"]
    for binding in result.bindings_for("shunt"):
        assert f"to ground GNDA" in binding.evidence
        assert "GNDB" not in binding.evidence.split("other low-pass readings")[0]


def test_h6_the_other_family_becomes_a_named_runner_up_not_a_forged_ground():
    """第二个地族的分支是"另一条读法"，写进 runners-up，而不是被谎报成 GNDA。"""
    result = _bind_lowpass(_two_family_lowpass())
    joined = " ".join(binding.evidence for binding in result.bindings)
    assert "other low-pass readings found but not bound" in joined
    assert "C2" in joined and "GNDB" in joined


def test_h6_parallel_shunts_on_one_family_still_bind_together():
    """053 sec.3 "多 C 并联" 不回归：同一族的两颗电容仍一起绑。"""
    result = _bind_lowpass(_two_family_lowpass())
    assert sorted(result.parts_of("shunt")) == ["C1", "C3"]
    assert ("OUT", "GNDA") in [item.nets for item in result.obligations
                               if item.kind == DIRECT_WIRE]


# ==================================================================== H7
# 副边族 `uniform-gnd` 的"never reads as the primary's"没有任何一层核验。


def test_h7_the_uniform_gnd_promise_says_what_is_checked_and_what_is_not():
    """承诺里没被核验的那半句必须**写明没被核验**（本批的二选一：降级）。

    理由：核验器 `drawcompiler._uniform_gnd_finding` 一次只看一个网，编译器
    的 `gnd_flag` 又给所有 gnd 类网同一颗符号 —— 那半句既没人核、也没有实现
    路径。要真核得上，得改 `drawcompiler.py`（不在本批地盘），所以这里选
    "把承诺从契约里降级"并写明理由。
    """
    result = _bind(t113.flyback_circuit())
    assert result.ok
    uniform = [item for item in result.obligations if item.kind == UNIFORM_GND]
    assert len(uniform) == 2
    assert {item.nets[0] for item in uniform} == {"PGND", "SEC_GND"}
    secondary = [item for item in uniform if item.nets[0] == "SEC_GND"][0]
    assert "unchecked" in secondary.reason
    assert "_uniform_gnd_finding" in secondary.reason
    assert "gnd_flag" in secondary.reason
    # 那半句仍在（它是图纸必须做到的），但它**与"没人核"绑在一起出现**：
    # 这就是本批选的"降级"——把没兑现的承诺写明白，而不是留着当已兑现的。
    assert "never reads as the primary's" in secondary.reason
    assert "Nothing checks it today and nothing can" in secondary.reason


def test_h7_both_families_are_still_promised_separately():
    """两条义务、各管一族 —— 088b 的一条出口规则的双方言版本，别被合并掉。"""
    result = _bind(t113.flyback_circuit())
    uniform = [item for item in result.obligations if item.kind == UNIFORM_GND]
    assert [item.nets for item in uniform] == [("PGND",), ("SEC_GND",)]
