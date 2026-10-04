"""109 A4 提案器：一份 intent 文档 → 一份 PresentationSpec 草稿（模块清单 + flow + 角色分工）。

A 主线最后一棒。今天语法是**逐条**读合同的（095 的 branchOrder 三来源、098 的 core
三来源），本批把合同**一次**变成一张可以改的全图草稿——**草稿=提案**：它走与手写规格
完全相同的封闭 schema 加载/校验通道，正确性仍由既有编译链裁决。

一句话一条规矩（任务书 §提案规则四条 + §验收形状五条，逐条对应下面的测试组）：

1. **模块清单**是声明出来的封闭映射：`block.id→module.id`、`block.parts→module.parts`、
   `block.kind→module.grammarRef`（表在 `intentproposer.KIND_GRAMMARS`，成员来自语法
   注册表与 `designintent.KIND_CURRENT_SENSE`）；**表外 kind 不猜**——模块仍在、
   `grammarRef` 空、报告点名（测试组 2）；
2. **core 提案**按 098 的来源顺序（`modules[].core` 不存在，草稿是产物 → intent 声明 →
   结构），**冲突不替裁**：该字段留空 + 两源原文并列（098 同款措辞），不静默选边（测试组 4）；
3. **flow 提案**从 blocks 的 parts **共网**推邻接，**方向只从声明的 kind 角色表给**；
   给不出方向的候选边标注 `underdetermined` 而不是猜；`mainPath` 只在唯一一条贯穿链
   **且每条边的跨网唯一且不是地**时可判定，判不出就全不标（测试组 5/6）；
4. **角色分工**（bulk/TVS）：合同声明了才抄——顺序取自**既有消费路径**（`power-entry`
   自己读出的那一条），它不写就回退三来源、写了必须同值（测试组 7）；`decisions` 是引用
   不是解释，绝不从值/封装推（053 §6 红线）；
5. **R3**：合同里任何元素没被读、没被用上，报告里点名（测试组 8）。

夹具一律**手写字面量**（098 的纪律：不建夹具文件），power-entry 那一张复用 088 的
`test_088_power_entry.inlet_circuit()`（连接器 + 三条支路只有一处定义）。合同照 095 的做法
**内存构造**，机器人那一条用 **shipped 案例文件** `blocklib/intents/robot-ctrl-foc.intent.json`。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import test_088_power_entry as base088

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core.circuitspec import CIRCUIT_SPEC_VERSION, CircuitSpec
from boardwise.core.presentationspec import (
    GRAMMARS,
    PresentationModule,
    PresentationSpec,
    main_path_wire,
)
from boardwise.engines import grammar as grammar_module
from boardwise.engines import intentproposer as ip
from boardwise.engines.grammar import ic_periphery

ROOT = Path(__file__).resolve().parents[1]
FOC_CONTRACT = ROOT / "blocklib" / "intents" / "robot-ctrl-foc.intent.json"

PROV = "verified_recipe"


# --------------------------------------------------------------- 夹具与工具


def contract(**sections) -> di.DesignIntent:
    """一份内存合同：只写这一段测试关心的段，其余缺省（schema 缺省即空）。"""
    body = {"intentVersion": di.INTENT_VERSION}
    body.update(sections)
    return di.DesignIntent.from_dict(body)


def block(block_id: str, kind: str = "", parts=(), **rest) -> dict:
    body: dict = {"id": block_id}
    if kind:
        body["kind"] = kind
    if parts:
        body["parts"] = list(parts)
    body.update(rest)
    return body


def decision(subject: str, text: str, **rest) -> dict:
    body: dict = {"subject": subject, "decision": text}
    body.update(rest)
    return body


#: 机器人合同那块板的**手写形状**：入口连接器 + 入口模块的第二颗多脚件 + MCU +
#: 两条相电流分流。网名照导出档（`VCC`/`GND`/`VCCA`/`U+`/`W+`），器件的名字照合同
#: 的 `blocks[].parts`——合同说的是哪几颗件，这一张就说那几颗件连成什么。
def robot_circuit() -> CircuitSpec:
    def part(part_id: str, symbol: str, value: str) -> dict:
        return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}

    def net(net_id: str, cls: str, members: list[str]) -> dict:
        return {"id": net_id, "class": cls, "members": members, "provenance": PROV}

    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec",
        "specVersion": CIRCUIT_SPEC_VERSION,
        "parts": [
            part("USB1", "USB-A-C1", "USB-A"),
            part("U4", "AMS1117-C1", "AMS1117-3.3"),
            part("U1", "STM32-C1", "STM32F103"),
            part("R4", "R0603-C1", "0.1Ω"),
            part("R5", "R0603-C1", "0.1Ω"),
        ],
        "nets": [
            net("VCC", "power", ["USB1.1", "U4.1", "U1.1"]),
            net("GND", "gnd", ["USB1.4", "U4.2", "U1.2", "R4.2", "R5.2"]),
            net("VCCA", "power", ["U4.3", "U1.5"]),
            net("U+", "signal", ["U1.3", "R4.1"]),
            net("W+", "signal", ["U1.4", "R5.1"]),
        ],
        "openInterfaces": [
            {"net": "VCC", "direction": "input", "role": "rail", "part": "USB1",
             "provenance": PROV},
        ],
    })


def robot_proposal() -> ip.Proposal:
    return ip.propose(di.DesignIntent.load(FOC_CONTRACT), robot_circuit())


def module_of(proposal: ip.Proposal, module_id: str) -> PresentationModule:
    module = proposal.spec.module(module_id)
    assert module is not None, [item.id for item in proposal.spec.modules]
    return module


def row_of(proposal: ip.Proposal, module_id: str) -> dict:
    for row in proposal.report["modules"]:
        if row["id"] == module_id:
            return row
    raise AssertionError(f"no report row for {module_id}: {proposal.report['modules']}")


def edges(proposal: ip.Proposal) -> set[tuple[str, str, bool]]:
    return {
        (edge.from_module, edge.to_module, edge.main_path)
        for edge in proposal.spec.flow
    }


# ============================================ 1. 机器人合同 → 三模块 + flow（①）


def test_the_robot_contract_becomes_its_three_modules():
    """shipped 合同（`robot-ctrl-foc.intent.json`）出的草稿：inlet 是 power-entry 模块、
    senseU/senseW 各成模块、各自的 core 是 U1（两个来源同值）。"""
    proposal = robot_proposal()

    assert [module.id for module in proposal.spec.modules] == [
        "inlet", "senseU", "senseW",
    ]
    inlet = module_of(proposal, "inlet")
    assert (inlet.parts, inlet.grammar_ref) == (["USB1", "U4"], "power-entry")
    for module_id, shunt in (("senseU", "R4"), ("senseW", "R5")):
        module = module_of(proposal, module_id)
        assert module.parts == [shunt, "U1"]
        assert module.grammar_ref == "ic-periphery"
        assert module.core == "U1", row_of(proposal, module_id)["notes"]


def test_the_robot_draft_has_the_flow_the_contract_implies():
    """flow：共网推邻接，方向从 kind 角色表给——inlet 是源，两条采样链是受端。"""
    proposal = robot_proposal()

    assert edges(proposal) == {
        ("inlet", "senseU", False), ("inlet", "senseW", False),
    }
    assert [item["pair"] for item in proposal.report["flow"]["undetermined"]] == [
        ["senseU", "senseW"],
    ]


def test_the_draft_round_trips_through_the_closed_schema_and_the_file_channel(tmp_path):
    """草稿=提案：它必须逐字节过封闭 schema 的加载/校验通道，写盘读回也不动一个字节。"""
    proposal = robot_proposal()
    payload = proposal.spec.to_jsonable()

    assert PresentationSpec.from_dict(payload).to_jsonable() == payload
    path = tmp_path / "draft.presentation.json"
    proposal.spec.dump(path)
    first = path.read_text(encoding="utf-8")
    assert PresentationSpec.load(path).to_jsonable() == payload
    proposal.spec.dump(tmp_path / "again.presentation.json")
    assert (tmp_path / "again.presentation.json").read_text(encoding="utf-8") == first


# ============================================ 2. 表外 kind 不猜（②）


def test_a_kind_outside_the_declared_table_is_not_guessed():
    """表外 kind：模块仍在、`grammarRef` 空、报告点名（由人或模型补），绝不猜一个语法。"""
    proposal = ip.propose(contract(blocks=[
        block("front", "buck", ["U1", "L1", "C1"]),
    ]))

    module = module_of(proposal, "front")
    assert module.parts == ["U1", "L1", "C1"]
    assert module.grammar_ref == ""
    row = row_of(proposal, "front")
    assert row["status"] == "unmapped-kind"
    assert "buck" in " ".join(row["notes"])
    assert "grammar" in " ".join(row["notes"])


def test_the_declared_tables_are_closed_and_read_from_their_sources():
    """两张表是声明出来的封闭集合，成员来自语法注册表与合同词表——不是场景常量。"""
    assert set(ip.KIND_GRAMMARS.values()) <= set(GRAMMARS)
    assert set(GRAMMARS) <= set(ip.KIND_GRAMMARS), "字面就是语法名的 kind 也在表里"
    assert ip.KIND_GRAMMARS[di.KIND_CURRENT_SENSE] == ic_periphery.NAME
    assert set(ip.KIND_FLOW_ROLES.values()) <= set(ip.FLOW_ROLES)
    assert ip.KIND_FLOW_ROLES == {
        "power-entry": ip.FLOW_SOURCE,
        di.KIND_CURRENT_SENSE: ip.FLOW_SINK,
    }
    proposal = ip.propose(contract(blocks=[block("b", "ldo", ["U1"])]))
    assert proposal.report["kindGrammars"] == dict(ip.KIND_GRAMMARS)
    assert proposal.report["kindFlowRoles"] == dict(ip.KIND_FLOW_ROLES)


# ============================================ 3. core 的两源与冲突（③）


def conflict_circuit() -> CircuitSpec:
    """U1 四个脚、U2 六个脚、R4 两个脚：结构说 U2，合同的一块说 U1（同模块内）。"""
    def part(part_id: str) -> dict:
        return {"id": part_id, "symbolRef": part_id + "-C1", "provenance": PROV}

    def net(net_id: str, cls: str, members: list[str]) -> dict:
        return {"id": net_id, "class": cls, "members": members, "provenance": PROV}

    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec",
        "specVersion": CIRCUIT_SPEC_VERSION,
        "parts": [part("U1"), part("U2"), part("R4")],
        "nets": [
            net("VCC", "power", ["U1.1", "U2.1"]),
            net("GND", "gnd", ["U1.2", "U2.2", "R4.1"]),
            net("SIG", "signal", ["U1.3", "R4.2"]),
            net("N4", "signal", ["U1.4"]),
            net("N3", "signal", ["U2.3"]),
            net("N5", "signal", ["U2.4"]),
            net("N6", "signal", ["U2.5"]),
            net("N7", "signal", ["U2.6"]),
        ],
    })


def conflict_contract() -> di.DesignIntent:
    return contract(blocks=[
        block("sub", di.KIND_CURRENT_SENSE, ["U1", "R4"]),
        block("wide", di.KIND_CURRENT_SENSE, ["U1", "U2", "R4"]),
    ])


def test_a_core_two_sources_disagree_about_is_left_empty_with_both_originals():
    """③ 声明与结构不一致 → 该字段留空 + notes 并列两源原文（098 同款措辞），不选边。"""
    proposal = ip.propose(conflict_contract(), conflict_circuit())

    assert module_of(proposal, "wide").core == ""
    notes = " ".join(row_of(proposal, "wide")["notes"])
    assert "blocks[id='sub'].parts" in notes, notes
    assert "the partition" in notes, notes
    assert "U1" in notes and "U2" in notes, notes
    assert "disagree" in notes, notes
    # 两源同值的那一组照写（`sub` 的声明与它自己的结构都是 U1）。
    assert module_of(proposal, "sub").core == "U1"


def test_the_098_consumption_path_reaches_the_same_refusal_on_the_same_input():
    """提案器不替裁的那个字段，098 的既有阅读也不替裁：同输入同结论（都不选边）。"""
    circuit = conflict_circuit()
    document = conflict_contract()
    wide = PresentationSpec(
        modules=[PresentationModule(
            id="wide", parts=["U1", "U2", "R4"], role=di.KIND_CURRENT_SENSE,
            grammar_ref=ic_periphery.NAME,
        )],
        grammar_ref=ic_periphery.NAME,
    )
    binding = grammar_module.grammar_for(ic_periphery.NAME).bind(
        circuit, wide, intent=document
    )

    assert binding.ok is False
    detail = " ".join(item.detail for item in binding.failures)
    assert "U1" in detail and "U2" in detail, detail
    assert "disagree" in detail, detail


def test_the_core_the_draft_writes_is_the_one_the_098_path_binds():
    """写了必须同值：草稿里那个 core，与 098 在同一个模块上绑出来的核心逐字相同。"""
    circuit = robot_circuit()
    proposal = ip.propose(di.DesignIntent.load(FOC_CONTRACT), circuit)

    for module_id in ("senseU", "senseW"):
        module = module_of(proposal, module_id)
        single = PresentationSpec(
            modules=[PresentationModule(
                id=module_id, parts=list(module.parts), role=module.role,
                grammar_ref=ic_periphery.NAME,
            )],
            grammar_ref=ic_periphery.NAME,
        )
        binding = grammar_module.grammar_for(ic_periphery.NAME).bind(
            circuit, single, intent=di.DesignIntent.load(FOC_CONTRACT)
        )
        assert binding.ok is True, binding.render_failures()
        assert binding.parts_of("core") == (module.core,) == ("U1",)


def test_the_core_is_read_from_the_two_sources_and_names_which_one_answered():
    """只有结构答话时也照写（来源顺序里的第三源），报告里点明是哪一源。"""
    proposal = ip.propose(
        contract(blocks=[block("sense", di.KIND_CURRENT_SENSE, ["U1", "R4"])]),
        conflict_circuit(),
    )

    assert module_of(proposal, "sense").core == "U1"
    notes = " ".join(row_of(proposal, "sense")["notes"])
    assert "partition" in notes or "blocks[" in notes, notes


def test_the_core_is_not_written_into_a_module_whose_grammar_does_not_read_it():
    """`core` 是 ic-periphery 的事实：grammarRef 不是它的模块不写这个字段，但报告要说。"""
    proposal = ip.propose(
        contract(blocks=[block("inlet", "power-entry", ["CN1", "U1"])]),
        inlet_with_mcu(),
    )

    inlet = module_of(proposal, "inlet")
    assert inlet.core == ""
    assert "ic-periphery" in " ".join(row_of(proposal, "inlet")["notes"])


def inlet_with_mcu() -> CircuitSpec:
    """一条轨 + 一颗多脚件：「结构认得出核心」与「这个模块的语法不读它」两件事分开。"""
    def part(part_id: str, symbol: str) -> dict:
        return {"id": part_id, "symbolRef": symbol, "provenance": PROV}

    def net(net_id: str, cls: str, members: list[str]) -> dict:
        return {"id": net_id, "class": cls, "members": members, "provenance": PROV}

    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec",
        "specVersion": CIRCUIT_SPEC_VERSION,
        "parts": [part("CN1", "XT30PW-M"), part("U1", "STM32-C1")],
        "nets": [
            net("+24V", "power", ["CN1.1", "U1.1"]),
            net("GND", "gnd", ["CN1.2", "U1.2", "U1.3"]),
        ],
        "openInterfaces": [
            {"net": "+24V", "direction": "input", "role": "rail", "part": "CN1",
             "provenance": PROV},
        ],
    })


# ============================================ 4. flow 的方向与 mainPath（④）


def two_module_circuit(*, gnd_crossing: bool) -> CircuitSpec:
    """两块、跨一条网：`VIN` 唯一共享（正向），或只有地共享（负向）。"""
    def nets() -> list[dict]:
        def net(net_id: str, cls: str, members: list[str]) -> dict:
            return {"id": net_id, "class": cls, "members": members, "provenance": PROV}

        if gnd_crossing:
            return [
                net("VIN_IN", "power", ["J1.1"]),
                net("VIN_MCU", "power", ["U9.1"]),
                net("GND", "gnd", ["J1.2", "U9.2"]),
            ]
        return [
            net("VIN", "power", ["J1.1", "U9.1"]),
            net("PGND", "gnd", ["J1.2"]),
            net("AGND", "gnd", ["U9.2"]),
        ]

    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec",
        "specVersion": CIRCUIT_SPEC_VERSION,
        "parts": [
            {"id": "J1", "symbolRef": "XT30PW-M", "provenance": PROV},
            {"id": "U9", "symbolRef": "STM32-C1", "provenance": PROV},
        ],
        "nets": nets(),
        "openInterfaces": [
            {"net": "VIN_IN" if gnd_crossing else "VIN", "direction": "input",
             "role": "rail", "part": "J1", "provenance": PROV},
        ],
    })


def test_a_flow_direction_no_role_entry_decides_is_named_not_guessed():
    """④ 方向给不出来就标 `underdetermined`（带两块各自的 kind），绝不猜一个方向。"""
    proposal = robot_proposal()
    undetermined = proposal.report["flow"]["undetermined"]

    assert len(undetermined) == 1
    row = undetermined[0]
    assert row["pair"] == ["senseU", "senseW"]
    assert row["kinds"] == ["current-sense", "current-sense"]
    assert row["roles"] == [ip.FLOW_SINK, ip.FLOW_SINK]
    assert row["nets"], "the crossing the pair shares has to be named"
    assert "sink" in row["why"]
    assert ("senseU", "senseW", False) not in edges(proposal)
    assert ("senseW", "senseU", False) not in edges(proposal)


def test_a_pair_whose_kind_states_no_role_is_named_too():
    proposal = ip.propose(contract(blocks=[
        block("inlet", "power-entry", ["J1"]),
        block("front", "buck", ["U9"]),
    ]), two_module_circuit(gnd_crossing=False))

    row = proposal.report["flow"]["undetermined"][0]
    assert row["pair"] == ["inlet", "front"]
    assert row["roles"] == [ip.FLOW_SOURCE, ""]
    assert "no flow role" in row["why"], row["why"]


def test_a_main_path_is_marked_only_when_the_chain_and_its_crossing_are_decidable():
    """唯一一条贯穿链、且每条边的跨网唯一且不是地 → 标；判不出就全不标。"""
    decided = ip.propose(contract(blocks=[
        block("inlet", "power-entry", ["J1"]),
        block("sense", di.KIND_CURRENT_SENSE, ["U9"]),
    ]), two_module_circuit(gnd_crossing=False))

    assert edges(decided) == {("inlet", "sense", True)}
    assert main_path_wire(decided.spec, "power", ["inlet", "sense"]) is True
    assert decided.report["flow"]["mainPath"]

    crossing_gnd = ip.propose(contract(blocks=[
        block("inlet", "power-entry", ["J1"]),
        block("sense", di.KIND_CURRENT_SENSE, ["U9"]),
    ]), two_module_circuit(gnd_crossing=True))

    assert edges(crossing_gnd) == {("inlet", "sense", False)}
    assert main_path_wire(crossing_gnd.spec, "gnd", ["inlet", "sense"]) is False
    assert "mainPath" in crossing_gnd.report["flow"]["mainPath"]

    robot = robot_proposal()
    assert all(not edge.main_path for edge in robot.spec.flow)
    assert robot.report["flow"]["mainPath"]


# ============================================ 5. 角色分工：顺序取自既有消费路径（规则 4）


TVS_DECISION = {
    "subject": "D1",
    "decision": "入口 TVS 贴连接器，泄放浪涌尖峰",
    "rationale": "尖峰要在它到达后级支路之前泄掉",
    "provenance": "user_stated",
}


def inlet_contract(*decisions) -> di.DesignIntent:
    return contract(
        blocks=[block("inlet", "power-entry", ["CN1", "D1", "C115", "C116"])],
        decisions=list(decisions),
    )


def bind_power_entry(circuit: CircuitSpec, presentation: PresentationSpec, document):
    return grammar_module.grammar_for("power-entry").bind(
        circuit, presentation, intent=document
    )


def test_the_branch_order_the_contract_states_is_written_and_the_drawing_does_not_move():
    """合同声明的泄放支路 → 草稿写出 `branchOrder`；写与不写，语法读出同一条顺序。"""
    circuit = base088.inlet_circuit()
    document = inlet_contract(TVS_DECISION)
    proposal = ip.propose(document, circuit)

    module = module_of(proposal, "inlet")
    assert module.branch_order == ["D1", "C115", "C116"]
    assert module.grammar_ref == "power-entry"
    assert module.role == "power-entry"

    declared = bind_power_entry(circuit, proposal.spec, document)
    undeclared = bind_power_entry(
        circuit,
        PresentationSpec(
            modules=[PresentationModule(
                id="inlet", parts=list(module.parts), role=module.role,
                grammar_ref="power-entry",
            )],
            grammar_ref="power-entry",
        ),
        document,
    )

    assert declared.ok is True and undeclared.ok is True
    order = [item.part_id for item in declared.bindings_for("shunt")]
    assert order == [item.part_id for item in undeclared.bindings_for("shunt")]
    assert order == ["D1", "C115", "C116"]


def test_without_a_contract_statement_the_order_field_stays_empty():
    """合同没说 → 字段留空（回退语法自己的三来源），草稿与 088b 的图纸一样不声明顺序。"""
    circuit = base088.inlet_circuit()
    proposal = ip.propose(inlet_contract(), circuit)

    assert module_of(proposal, "inlet").branch_order == []
    binding = bind_power_entry(circuit, proposal.spec, inlet_contract())
    assert binding.ok is True
    assert [item.part_id for item in binding.bindings_for("shunt")] == [
        "C115", "C116", "D1",
    ]


def test_a_claim_about_a_part_outside_any_module_moves_nothing():
    """decisions 是**引用**不是解释：subject 不是这个模块的支路（或 prose 不说泄放类）
    → 一个字都不抄，报告里点名（R3）。"""
    circuit = base088.inlet_circuit()
    proposal = ip.propose(
        inlet_contract(
            dict(TVS_DECISION, subject="C99"),
            decision("C115", "体电容，提供浪涌电流"),
        ),
        circuit,
    )

    assert module_of(proposal, "inlet").branch_order == []
    unread = " ".join(proposal.report["unread"])
    assert "C99" in unread
    assert "C115" in unread


# ============================================ 6. R3：没被读的都要点名（⑤）


def test_every_element_the_contract_states_is_used_or_named():
    """⑤ 空 parts 的块、没人读的 decision、没人读的键（requires/feeds）、整段 requirements
    ——报告里逐条点名，绝不静默丢掉。"""
    document = contract(
        requirements={
            "rails": [{"net": "VCC", "targetVoltage": "3.3V", "provenance": PROV}],
        },
        blocks=[
            block("sense", di.KIND_CURRENT_SENSE, ["U1", "R4"],
                  requires=["bias-reference"], feeds=["U1.adc"]),
            block("empty", di.KIND_CURRENT_SENSE),
        ],
        decisions=[
            decision("U1", "MCU 选型", provenance="user_stated"),
            decision("CN1", "入口连接器", value="XT30"),
        ],
    )
    proposal = ip.propose(document, conflict_circuit())
    unread = "\n".join(proposal.report["unread"])

    assert "blocks[id='empty']" in unread, unread
    assert "requires" in unread and "feeds" in unread, unread
    assert "decisions[subject='U1']" in unread, unread
    assert "decisions[subject='CN1']" in unread, unread
    assert "value" in unread, unread
    assert "requirements" in unread, unread
    assert proposal.report["reads"]["blocks"][0]["used"], proposal.report["reads"]
    assert "requirements" in proposal.report["reads"]


def test_only_the_blocks_and_the_decisions_that_were_read_are_reported_as_read():
    """读过的元素照实记「读到哪去」，没读的照实记「为什么没读」——两个方向都写。"""
    proposal = ip.propose(di.DesignIntent.load(FOC_CONTRACT), robot_circuit())
    rows = {row["id"]: row for row in proposal.report["reads"]["blocks"]}

    assert rows["inlet"]["used"] == "modules[inlet]"
    assert rows["senseU"]["used"] == "modules[senseU]"
    # The robot contract's blocks state `feeds` and no `requires`: the row lists the
    # keys it actually carries and no consumer reads, nothing more.
    assert rows["senseU"]["unused"] == ["feeds"]
    assert rows["inlet"]["unused"] == []
    decisions = proposal.report["reads"]["decisions"]
    assert [row["subject"] for row in decisions] == ["R4"]
    # 机器人合同唯一那条决策说的是「0.1Ω 直采」，一个泄放类词都没有：绘制侧没读它。
    assert decisions[0]["used"] == ""
    assert decisions[0]["unused"] == ["value"]
    assert "clamping" in decisions[0]["why"], decisions[0]


# ============================================ 7. 没有电路时的一半：明说，不猜


def test_without_a_circuit_the_netlist_halves_are_named_not_guessed():
    """`--circuit` 缺席时：模块清单照出，flow/core/顺序三件需要网表的事**留空并明说**。"""
    proposal = ip.propose(di.DesignIntent.load(FOC_CONTRACT))

    assert [module.id for module in proposal.spec.modules] == [
        "inlet", "senseU", "senseW",
    ]
    assert proposal.spec.flow == []
    assert all(module.core == "" for module in proposal.spec.modules)
    assert all(module.branch_order == [] for module in proposal.spec.modules)
    everything = "\n".join(
        proposal.notes
        + proposal.report["notes"]
        + [note for row in proposal.report["modules"] for note in row["notes"]]
        + [proposal.report["flow"]["mainPath"]]
    )
    assert "--circuit" in everything or "netlist" in everything, everything
    assert proposal.report["flow"]["undetermined"] == []


# ============================================ 8. CLI


def write_inputs(tmp_path, document, circuit_spec) -> tuple[Path, Path]:
    intent = tmp_path / "board.intent.json"
    circuit = tmp_path / "board.circuit.json"
    document.dump(intent)
    circuit.write_text(
        json.dumps(circuit_spec.to_jsonable(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return intent, circuit


def test_draw_propose_writes_a_draft_the_schema_loads(tmp_path, capsys):
    circuit = robot_circuit()
    intent, circuit_path = write_inputs(
        tmp_path, di.DesignIntent.load(FOC_CONTRACT), circuit
    )
    draft = tmp_path / "draft.json"
    report = tmp_path / "proposal.json"

    code = cli.main([
        "draw", "propose",
        "--intent", str(intent), "--circuit", str(circuit_path),
        "--out", str(draft), "--json", str(report),
    ])
    printed = capsys.readouterr()

    assert code == 0, printed.out + printed.err
    spec = PresentationSpec.load(draft)
    assert [module.id for module in spec.modules] == ["inlet", "senseU", "senseW"]
    assert spec.sha256() == robot_proposal().spec.sha256()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["command"] == "propose"
    assert [row["pair"] for row in payload["flow"]["undetermined"]] == [
        ["senseU", "senseW"],
    ]
    assert "senseU" in printed.out


def test_draw_propose_prints_the_draft_when_no_out_is_given(tmp_path, capsys):
    intent, circuit_path = write_inputs(
        tmp_path, di.DesignIntent.load(FOC_CONTRACT), robot_circuit()
    )

    code = cli.main([
        "draw", "propose", "--intent", str(intent), "--circuit", str(circuit_path),
    ])
    printed = capsys.readouterr()

    assert code == 0, printed.out + printed.err
    payload = json.loads(printed.out.split("  draft:\n", 1)[1])
    assert PresentationSpec.from_dict(payload).to_jsonable() == payload
    assert payload["kind"] == "boardwise-presentation-spec"


def test_draw_propose_says_so_when_an_input_cannot_be_read(tmp_path, capsys):
    """R3 的输入侧：点了名的合同/电路读不了 → 点名 + 非 0，绝不悄悄当成空合同。"""
    _, circuit_path = write_inputs(
        tmp_path, di.DesignIntent.load(FOC_CONTRACT), robot_circuit()
    )
    missing = tmp_path / "not-there.intent.json"

    code = cli.main([
        "draw", "propose", "--intent", str(missing), "--circuit", str(circuit_path),
    ])
    printed = capsys.readouterr()
    assert code == 2, printed.out + printed.err
    assert "not-there.intent.json" in printed.err

    intent, _ = write_inputs(
        tmp_path, di.DesignIntent.load(FOC_CONTRACT), robot_circuit()
    )
    code = cli.main([
        "draw", "propose", "--intent", str(intent),
        "--circuit", str(tmp_path / "not-there.circuit.json"),
    ])
    printed = capsys.readouterr()
    assert code == 2, printed.out + printed.err
    assert "not-there.circuit.json" in printed.err


def test_draw_propose_refuses_when_no_block_can_become_a_module(tmp_path, capsys):
    intent, circuit_path = write_inputs(
        tmp_path, contract(blocks=[block("empty", "ldo")]), robot_circuit()
    )
    draft = tmp_path / "never.json"

    code = cli.main([
        "draw", "propose", "--intent", str(intent), "--circuit", str(circuit_path),
        "--out", str(draft),
    ])
    printed = capsys.readouterr()

    assert code == 5, printed.out + printed.err
    assert "blocks[id='empty']" in printed.out + printed.err
    assert not draft.exists(), "a refusal writes no draft"


def test_the_legacy_draw_invocation_still_parses_beside_the_new_subcommand():
    """`draw propose` 是新词族的一员，059 的旧调用（无位置参数）一个字不动。"""
    from boardwise.cli import build_parser

    parsed = build_parser().parse_args(
        ["draw", "propose", "--intent", "a.json", "--circuit", "b.json"]
    )
    assert (parsed.command, parsed.draw_command) == ("draw", "propose")
    assert parsed.intent == "a.json" and parsed.circuit == "b.json"
    legacy = build_parser().parse_args(["draw", "--spec", "x.json", "--from", "y.epro2"])
    assert legacy.draw_command is None
    assert legacy.spec == "x.json" and legacy.from_file == "y.epro2"


# ============================================ 9. 语法表里没有场景常量（053 §6）


#: 场景常量：位号、值、封装、网名——本批新增的模块里一个都不许出现（088 的 AST 钉法）。
SCENARIO_TOKENS = frozenset({
    "CN1", "D1", "C115", "C116", "USB1", "U1", "U2", "U4", "U9", "R4", "R5",
    "J1", "VCC", "GND", "VCCA", "+24V", "+12V", "VIN", "U+", "W+",
    "0.1Ω", "330uF", "SMCJ28CA", "AMS1117", "XT30PW-M", "STM32F103", "R0603",
    "robot-ctrl-foc",
})


def test_the_proposer_carries_no_scenario_specific_constant():
    source = Path(ip.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ):
                docstrings.add(id(body[0].value))
    literals = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    offenders = sorted(literals & SCENARIO_TOKENS)
    assert offenders == [], f"a scenario constant reached the proposer: {offenders}"


def test_the_proposer_imports_nothing_from_above_its_layer():
    """006c 的层表：`engines` 可以读 core / parsers / rules，本模块只读 core 与自己的层。"""
    source = Path(ip.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    heads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            name = (node.module or "").split(".")[0]
            heads.add(name or "<sibling>")
    assert heads <= {"core", "grammar", "<sibling>"}, heads
