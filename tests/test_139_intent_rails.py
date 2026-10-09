"""139（issue #65）：无电压电源网问一次、落契约、不再问。

岳裁定 2026-10-07：`VCC`/`VCCA`/`VREF` 这类**名字不带电压**的网，规则只出 UNKNOWN，
把「这网多少伏」的决定原样留回给每一次 run。本批把它变成一次性的机械动作：

1. **枚举**（`intent audit` / `core.railquery.audit_rails`）——一块板上一条一行，
   每行带「凭什么说它是电源」（网名写法 / 网上挂着的电源脚，**脚名本身也得是电源写法**
   ——`VOUT`/`VDD`/`VM` 算，光写个 `OUT`/`IN` 的脚不算：互感器、电流传感器、电阻的脚
   都这么写（实测证人见下）、以及**它已经不该被问**
   的五个理由。名字自带电压（`+5V`/`3V3`/`A5V`）、地网、派生轨（`VCC/2`）、
   架构枚举已定价（货架稳压器输出）、合同里已有答案——五种「settled」全部实测；
   `VCC` 在 ROBOT 板被货架定价 3.3 V、在 毕设FOC 板无价，就是这一族里最锋利的两刀。
2. **落契约**（`intent set-rail`）——把同一个值写进 `requirements.rails[net=…].voltage`
   **和** `.targetVoltage`（**双写、同值同 provenance**：`voltage` 是既定值语义、
   `targetVoltage` 是设计目标语义，`user_stated` 时两者同义——写一份只够一半读端，
   092 的 `rail_voltage` 原本只认后者，见组 5），走 `core.designintent` 的既有读/渲染函数
   （不许手写 JSON），别的键/条目/行序逐字不动（`role`、其它 rail、blocks、decisions 都钉住）。
3. **往返**——写 → 读 → 再 audit：同一条从 ask 落到 settled，且 settled 行
   **点名答案出处**（「不再问」要可核，不能只是一句沉默）。
4. **拒绝**——`3.3` 之外的读不出的值（`VDD`/`abc`/`5V 1A`）按名字拒（exit 2），
   因为这个槽是拿算术定价的：存一个谁也读不出来的字符串，这条轨就会永远地问下去。
5. **缝的对拍（139 收口）**——写手和读端必须是同一件事：`intent set-rail` 落完之后，
   `rules.railratings.rail_voltage` 必须读得出这条轨（两个键都由它读），不再报
   `intent-missing`。这条缝断在 064 与 139 手上各一次，证据
   `evidence/064/intent_slot_gap.txt`。

夹具一律手写内存构造（098/095 的纪律）：一个 `DesignModel` 七条网，四条该问、
三条不该问；词表的每一半都有实物证人——三块只读夹具 `ch340_golden`（电源网全有价，
一条都不问）、ROBOT ctrl FOC（`VCC` 有价 3.3 V、`VCCA` 无价）与 毕设FOC驱动板
（`VCC`/`VCCA`/`VREF` 无价），不新增夹具文件、不改 `blocklib/intents/` 既有契约
（合同是拷到 tmpdir 用的）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core.circuitspec import PROVENANCE_USER_STATED
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.railquery import (
    audit_rails,
    is_supply_name,
    name_states_volts,
    set_rail_voltage,
)
from boardwise.parsers.schematic import build_project_model

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"
ROBOT = ROOT / "tests" / "fixtures" / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
FOC = ROOT / "tests" / "fixtures" / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
SHELF = ROOT / "blocklib" / "parts.json"


# --------------------------------------------------------------- 内存夹具


def _board(nets: dict[str, list[tuple[str, str, str]]], title: str = "PCB1") -> DesignModel:
    """一块板：``{网名: [(位号, 脚号, 脚名), …]}``。脚名走 131a 的真表。"""
    model = DesignModel()
    model.raw = {}
    for net, pins in nets.items():
        for designator, number, pin_name in pins:
            component = model.components.get(designator)
            if component is None:
                component = Component(uid=f"u-{designator}", designator=designator)
                model.components[designator] = component
            component.pins.append(Pin(number=number, name=pin_name, net=net))
        model.nets[net] = Net(name=net, pins=[(d, n) for d, n, _ in pins])
    if title:
        # BoardModel 的 title 只在多板报告里出现过；这里用裸 DesignModel，
        # 板名留空也不改变任何断言（见 `_board_title` 的容错）。
        del title
    return model


#: 四条该问的网：两条靠名字（`VCC` 拼写 / `TVDD` 拼写）、两条靠电源脚
#: （`NET11` 上是 LDO 的 `VOUT`、`NET7` 上是半桥的 `VM`），外加三条不该问的：
#: `+5V`（名字自带）、`GND`（地）、`VCC/2`（派生轨）。
SAMPLE = _board({
    "VCC": [("U1", "16", "VDD"), ("C1", "1", "1")],
    "TVDD": [("U7", "1", "VCC")],
    "NET11": [("U2", "5", "VOUT")],
    "NET7": [("U3", "2", "VM")],
    "+5V": [("J1", "1", "V+")],
    "GND": [("C1", "2", "GND")],
    "VCC/2": [("R1", "2", "OUT")],
})


def contract(*rails: dict) -> di.DesignIntent:
    """一份内存合同：只写 ``rails``，其余缺省（schema 缺省即空）。"""
    return di.DesignIntent.from_dict(
        {"intentVersion": di.INTENT_VERSION, "requirements": {"rails": list(rails)}}
    )


def ask_nets(audit) -> list[str]:
    return [row.net for row in audit.ask]


def settled_nets(audit) -> list[str]:
    return [row.net for row in audit.settled]


# ------------------------------------------------------- 1. 枚举（测试组 1）


def test_audit_lists_only_unanswered_power_nets():
    """四条该问的（四条判定路径各一条：名字/名字/脚/脚），三条不该问的必须不在。"""
    audit = audit_rails(SAMPLE)
    assert ask_nets(audit) == ["NET11", "NET7", "TVDD", "VCC"]
    assert settled_nets(audit) == ["+5V", "GND", "VCC/2"]


def test_each_ask_row_names_its_evidence_and_its_key():
    """每一行都要能让人 3 秒核完：凭什么说它是电源、答案写进哪个键。"""
    rows = {row.net: row for row in audit_rails(SAMPLE).ask}
    assert "U2.5(VOUT)" in rows["NET11"].why, rows["NET11"].why
    assert rows["NET11"].members == ("U2.5(VOUT)",)
    assert rows["VCC"].write == "requirements.rails[net=VCC].voltage"
    assert "U1.16(VDD)" in rows["VCC"].why


def test_a_non_power_net_is_never_asked_about():
    """信号网不是轨：这条纪律来自 126c 的 92 条网教训（`CAN_RX` 不是缺电压的轨）。"""
    board = _board({"CAN_RX": [("U1", "10", "RXD")], "U+": [("R4", "2", "OUT")]})
    audit = audit_rails(board)
    assert audit.ask == [] and audit.settled == []


def test_name_vocabulary_is_the_documented_one():
    """词表钉死：名字读法与「自带电压」读法各有边界，`RECV` 之类不许混进来。"""
    for name in ("VCC", "VCCA", "VDD", "VDDA", "VDDIO", "DVDD", "TVDD", "VBAT",
                 "VBUS", "VM", "VEE", "VREF", "VREF+", "V+", "vcc"):
        assert is_supply_name(name), name
    for name in ("CAN_RX", "U+", "NET11", "RECV", "DRV_EN", "AGND_LDO", ""):
        assert not is_supply_name(name), name
    for name, expected in (("+5V", "+5V"), ("3V3", "3V3"), ("A5V", "5V"),
                           ("D5V", "5V"), ("VDD_3V3", "3V3"), ("VCC", ""),
                           ("NET11", "")):
        assert name_states_volts(name) == expected, name


def test_ground_and_derived_rails_are_settled_with_a_reason():
    """过滤掉的网必须**说为什么**被过滤——沉默的过滤等于让读者自己重新推一遍。"""
    rows = {row.net: row.settled_by for row in audit_rails(SAMPLE).settled}
    assert set(rows) == {"+5V", "GND", "VCC/2"}  # 三条都进了这张表，一条不少
    assert "0 V" in rows["GND"]
    assert "派生轨" in rows["VCC/2"]


# ------------------------------------------------ 2. 已在契约里的不重问（组 2）


def test_a_rail_the_contract_prices_is_never_asked_again():
    """岳裁定的核心：答过的不许再问，且要能指出答案在合同哪儿。"""
    document = contract({"net": "VCC", "voltage": "3.3V", "provenance": PROVENANCE_USER_STATED})
    audit = audit_rails(SAMPLE, document)
    assert "VCC" not in ask_nets(audit)
    row = next(r for r in audit.settled if r.net == "VCC")
    assert row.stated_voltage == "3.3V" and row.provenance == PROVENANCE_USER_STATED
    assert "requirements.rails[net=VCC].voltage" in row.settled_by


def test_target_voltage_also_settles_a_rail():
    """`targetVoltage` 是同一族必填槽（090 的 REQUIRED_SLOTS）：答了它同样不再问。"""
    document = contract({"net": "TVDD", "targetVoltage": "1.8V", "provenance": "verified_recipe"})
    assert "TVDD" not in ask_nets(audit_rails(SAMPLE, document))


def test_a_rail_with_no_contract_at_all_is_all_asked():
    """无合同是第一次审查的常态：那时全部按未答，不报错、不静默。"""
    audit = audit_rails(SAMPLE, None)
    assert ask_nets(audit) == ["NET11", "NET7", "TVDD", "VCC"]


def test_the_architecture_enumeration_settles_what_the_drawing_prices():
    """实测证人：**同名同族的 `VCC` 在两块真板上是两个答案**——这一条是这一族里最锋利的两刀。

    ROBOT 板：`VCC` 被图纸的稳压器定价 3.3 V（图纸自己说得出的答案，工程师不该被问）；
    毕设FOC 板：`VCC`/`VCCA`/`VREF` 全无价（那才是要问的名单）。CH340 板更极端：
    它的电源网**一条都不欠答案**（`+5V` 名字自带、`VCC` 被定价），清单为空也是正常结论。
    """
    from boardwise.core.parts import load_parts

    shelf = load_parts(SHELF)
    robot = build_project_model(ROBOT).boards[0]
    ch340 = build_project_model(GOLDEN).boards[0]
    foc = build_project_model(FOC).boards[0]

    robot_audit = audit_rails(robot, None, library=shelf)
    assert "VCC" not in ask_nets(robot_audit)
    row = next(r for r in robot_audit.settled if r.net == "VCC")
    assert "architecture.chains.rails" in row.settled_by and "3.3" in row.settled_by

    # 同一块板上的邻居 `VCCA` 没人定价：settled 的半边不吞掉 ask 的半边。
    assert "VCCA" in ask_nets(robot_audit)

    assert "VCC" in ask_nets(audit_rails(foc, None, library=shelf))

    ch340_audit = audit_rails(ch340, None, library=shelf)
    assert ch340_audit.ask == []


def test_a_stale_rail_entry_still_counts_as_answered():
    """图纸把轨挪走了 ≠ 工程师没答过：重问一遍正是裁定要治的病。"""
    document = contract({
        "net": "VCC", "voltage": "3.3V", "stale": True,
        "provenance": PROVENANCE_USER_STATED,
    })
    assert "VCC" not in ask_nets(audit_rails(SAMPLE, document))


# ------------------------------------------------------------ 3. 落契约（组 3）


def test_set_rail_writes_both_voltage_slots_and_touches_nothing_else():
    """只改 `voltage` + `targetVoltage` + `provenance`：`role`、其它槽、其它条目、行序、
    blocks/decisions 全部逐字不动——合同是工程师的文档，本命令只是书记。

    **双写**是这一批的正题：`voltage` 与 `targetVoltage` 是同一个答案的两种语义
    （既定值 / 设计目标），只写一个就有一族读端读不到（见组 5）。两键同值，`provenance`
    是**条目级**的一个字段，所以「同 provenance」= 这一条的外层那一份。
    """
    before = contract(
        {"net": "VCCA", "role": "analog", "source": "U9 输出", "provenance": "verified_recipe"},
        {"net": "+12V", "role": "bus", "provenance": PROVENANCE_USER_STATED},
    )
    raw = json.loads(di.render_json(before))
    raw["blocks"] = [{"id": "senseU", "kind": "current-sense", "provenance": "ai_asserted"}]
    raw["decisions"] = [{"subject": "R4", "decision": "0.1Ω 直采", "provenance": "user_stated"}]
    before = di.DesignIntent.from_dict(raw)

    after, changed = set_rail_voltage(before, "VCCA", "3.3V")
    assert "3.3V" in changed
    # 文案列出两个键——工程师要看得见答案写进了哪两个槽。
    assert "voltage = '3.3V'" in changed and "targetVoltage = '3.3V'" in changed
    body = json.loads(di.render_json(after))
    assert body["requirements"]["rails"][0] == {
        "net": "VCCA", "source": "U9 输出", "role": "analog",
        "voltage": "3.3V", "targetVoltage": "3.3V",
        "provenance": PROVENANCE_USER_STATED,
    }
    assert body["requirements"]["rails"][1] == raw["requirements"]["rails"][1]
    assert body["blocks"] == raw["blocks"] and body["decisions"] == raw["decisions"]
    assert before.rails[0].value("voltage") == "", "写入不得就地改调用方的文档"


def test_set_rail_writes_the_same_answer_and_provenance_into_both_slots():
    """双写往返的一半：两键都在、同值、同 provenance——一手写、两族读端都认。

    `set_rail_voltage` 的旧版只写 `voltage`，而 `rules.railratings.rail_voltage`
    只读 `targetVoltage`：工程师答完，规则继续报 `intent-missing`。这条测试钉的是
    **写手这一侧**（`evidence/064/intent_slot_gap.txt` 的第二半）。
    """
    after, _ = set_rail_voltage(di.DesignIntent(), "VCCA", "3.3V")
    entry = after.entry(di.SECTION_RAILS, "VCCA")
    assert entry is not None
    assert entry.value("voltage") == "3.3V"
    assert entry.value("targetVoltage") == "3.3V"
    assert entry.value("voltage") == entry.value("targetVoltage"), "同值"
    assert entry.provenance == PROVENANCE_USER_STATED


def test_set_rail_fills_the_other_key_of_an_entry_that_stated_only_one():
    """手写合同只写了 `targetVoltage`（092 语义）时，工程师答一次要把两键都补齐——
    否则「已答过」的那条轨在 139 的 audit 里照样是待问。"""
    before = contract({"net": "VCC", "targetVoltage": "5V", "provenance": "ai_asserted"})
    after, changed = set_rail_voltage(before, "VCC", "3.3V")
    entry = after.entry(di.SECTION_RAILS, "VCC")
    assert (entry.value("voltage"), entry.value("targetVoltage")) == ("3.3V", "3.3V")
    assert entry.provenance == PROVENANCE_USER_STATED
    assert "corrected" in changed, "覆盖了一个既有答案要说清「改过」"


def test_set_rail_creates_a_missing_entry_without_moving_the_others():
    """新建条目插在最前（与 `designintent.merge` 同序），已有行一位都不移；两键一起建。"""
    before = contract({"net": "VCC", "voltage": "3.3V", "provenance": "user_stated"})
    after, changed = set_rail_voltage(before, "TVDD", "1V8")
    assert "new entry" in changed
    body = json.loads(di.render_json(after))
    assert [row["net"] for row in body["requirements"]["rails"]] == ["TVDD", "VCC"]
    assert body["requirements"]["rails"][0]["provenance"] == PROVENANCE_USER_STATED
    assert body["requirements"]["rails"][0]["voltage"] == "1V8"
    assert body["requirements"]["rails"][0]["targetVoltage"] == "1V8"


def test_set_rail_keeps_the_rail_in_place_and_reports_the_correction():
    """改一个已答过的值要说清「改过」，不是静默覆盖——工程师要看见自己改了什么。"""
    before = contract({"net": "VCC", "voltage": "3.3V", "provenance": PROVENANCE_USER_STATED})
    after, changed = set_rail_voltage(before, "VCC", "5V")
    assert "3.3V" in changed and "5V" in changed and "corrected" in changed
    assert after.rails[0].value("voltage") == "5V"
    assert after.rails[0].value("targetVoltage") == "5V", "改过之后两键仍然同值"
    assert "targetVoltage" in changed, "改过的文案把两个键都写出来"


@pytest.mark.parametrize("bad", ["VDD", "abc", "5V 1A", "", "3.3V3V"])
def test_set_rail_refuses_a_value_it_cannot_price(bad):
    """读不出的值按名字拒：这个槽是算术定价的，存进去这条轨就永远问下去。"""
    with pytest.raises(di.DesignIntentError) as raised:
        set_rail_voltage(contract(), "VCC", bad)
    assert repr(bad) in str(raised.value) or "empty" in str(raised.value)


def test_set_rail_refuses_an_empty_net_name():
    with pytest.raises(di.DesignIntentError):
        set_rail_voltage(contract(), "  ", "3.3V")


# ------------------------------------------------------ 4. 端到端往返（组 4）


def test_cli_round_trip_ask_write_reaudit(tmp_path):
    """写 → 读 → 再 audit：这条从 ask 落到 settled，别的行一动不动。

    夹具用 ROBOT 板而不是 CH340：往返要的是一条**真的在 ask 里**的轨，而 CH340 的
    电源网全都有价（同名 `VCC` 在 ROBOT 上有价、在 毕设FOC 上无价，本测试取 ROBOT 的
    `VCCA`——它旁边那条被定价的 `VCC` 正好当「别的行一动不动」的证人）。
    """
    contract_path = tmp_path / "intent.json"
    contract_path.write_text(
        di.render_json(contract({"net": "VCC", "role": "logic",
                                 "provenance": "verified_recipe"})),
        encoding="utf-8",
    )
    project = tmp_path / "board.epro2"
    shutil.copyfile(ROBOT, project)

    first = _run(cli, ["intent", "audit", "--file", str(project),
                       "--intent", str(contract_path), "--json", str(tmp_path / "a1.json")])
    assert first == 0
    before = json.loads(di.render_json(di.DesignIntent.load(contract_path)))
    assert "VCCA" in _ask_of(tmp_path / "a1.json")

    assert _run(cli, ["intent", "set-rail", "VCCA", "--voltage", "3.3V",
                      "--file", str(contract_path)]) == 0
    assert _run(cli, ["intent", "audit", "--file", str(project),
                      "--intent", str(contract_path), "--json", str(tmp_path / "a2.json")]) == 0
    after = json.loads(di.render_json(di.DesignIntent.load(contract_path)))

    assert "VCCA" not in _ask_of(tmp_path / "a2.json")
    assert "VCCA" in _settled_of(tmp_path / "a2.json")
    # 新条目插在最前（`designintent.set_entry` 的序），已有那条一位都不动：
    # 逐字钉住它的 role 与 provenance。**两个电压键都在**（双写，139 收口）。
    assert after["requirements"]["rails"][0] == {
        "net": "VCCA", "voltage": "3.3V", "targetVoltage": "3.3V",
        "provenance": PROVENANCE_USER_STATED,
    }
    assert after["requirements"]["rails"][1] == before["requirements"]["rails"][0]
    assert set(before) == set(after)


def test_the_answer_set_rail_records_is_the_answer_the_rail_rules_read():
    """**缝的对拍**（139 收口）：`intent set-rail` 之后，092 的
    `rules.railratings.rail_voltage` 读得出这条轨——不再报 `intent-missing`。

    这正是 `evidence/064/intent_slot_gap.txt` 记的那处：064 与 139 两个代理各自撞上
    「写手写一个键、读端认另一个键」，于是工程师按自家命令答完电压，规则还在要答案。
    钉在**跨批的公共 API** 上（写手 + 读端两个函数），而不是各自半边，因为这个病只在
    缝上出现。rail_voltage 的第二个返回值是「证据从哪来」，它点名合同与那个键。
    """
    from boardwise.rules.railratings import rail_voltage

    updated, _ = set_rail_voltage(di.DesignIntent(), "VCCA", "3.3V")
    source = di.IntentSource(document=updated, path="mem://intent.json")

    volts, where, why = rail_voltage(source, {}, "VCCA")
    assert (volts, why) == (3.3, ""), (volts, where, why)
    assert "requirements.rails[net=VCCA].voltage = '3.3V'" in where, where
    assert "intent-missing" not in why


def test_cli_audit_without_a_contract_lists_everything(tmp_path):
    """没有合同 = 第一次审查：命令自己也要说「无合同」，不是默默当空文档。

    「无合同」改的是**合同的半边**：未定价的轨全部按未答列出来，图纸自己定了价的
    照样不问——那是另一条理由，与有没有合同无关。
    """
    project = tmp_path / "board.epro2"
    shutil.copyfile(ROBOT, project)
    report = tmp_path / "a.json"
    assert _run(cli, ["intent", "audit", "--file", str(project), "--json", str(report)]) == 0
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["intent"]["present"] is False
    assert "VCCA" in _ask_of(report)
    assert "VCC" not in _ask_of(report)


def test_cli_set_rail_creates_the_contract_when_it_is_absent(tmp_path):
    """第一次落答案 = 文件还不存在，这是正常首跑不是错误。"""
    contract_path = tmp_path / "deep" / "intent.json"
    assert _run(cli, ["intent", "set-rail", "VCC", "--voltage", "3.3V",
                      "--file", str(contract_path), "--json", str(tmp_path / "s.json")]) == 0
    document = di.DesignIntent.load(contract_path)
    assert document.rails[0].net == "VCC"
    assert document.rails[0].provenance == PROVENANCE_USER_STATED
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["sha256"] == document.sha256()


def test_cli_set_rail_refuses_an_unreadable_value_and_writes_nothing(tmp_path):
    """拒绝时一个字节都不许落盘——半份合同比没有合同更难读。"""
    contract_path = tmp_path / "intent.json"
    assert _run(cli, ["intent", "set-rail", "VCC", "--voltage", "VDD",
                      "--file", str(contract_path)]) == 2
    assert not contract_path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_audit_refuses_an_unreadable_project():
    """输入不可用 = exit 2（与 `parts missing` 同口径），与「有清单」无关。"""
    assert _run(cli, ["intent", "audit", "--file", "no-such-file.epro2"]) == 2


# --------------------------------------------------------------- 小工具


def _run(module, argv: list[str]) -> int:
    return module.main(argv)


def _ask_of(report: Path) -> list[str]:
    body = json.loads(report.read_text(encoding="utf-8"))
    return [row["net"] for board in body["boards"] for row in board["ask"]]


def _settled_of(report: Path) -> list[str]:
    body = json.loads(report.read_text(encoding="utf-8"))
    return [row["net"] for board in body["boards"] for row in board["settled"]]
