"""527：``IntentSource`` 转发三个需求小节，否则合同被静默读成空。

来源是 v0.5.17 的实板复验报告 §3：`core/designintent.py` 的 `IntentSource` 类文档说
「consumer 和规则都拿 IntentSource」，而 `rules/pcb/ipc.py` 的读端是
`getattr(intent, "rails", None)` / `getattr(intent, "signals", None)` —— 那是**裸
`DesignIntent`** 的字段名。于是同一个合同两种载体给出两个答案：

    PcbReviewContext(intent=document)        → 五条轨全定价（`checkup` 走的就是这条）
    PcbReviewContext(intent=IntentSource(…)) → `getattr` 拿不到 rails → 空表

**为什么这是缺陷而不是「文档写错了」**：空 rails 是**合法状态**（一块没有合同的板），
所以两条路都读不出错误 —— 规则只会把每个网报成 UNKNOWN，而 UNKNOWN 的原因文案是
「没人给它定价」，不是「你给的载体类型不对」。一个按文档办事的调用者（合成上下文写的
测试、外部 consumer）因此拿到一份看起来正常的空结论。

修法只有一条：把 PCB 规则按名字问的三个小节转给 `document`，让两种载体的答案逐字相同。
本文件钉的就是这个「逐字相同」，不是「能读到东西」——`declared_voltages` 的返回值带着
**出处字符串**，出处必须也一样，否则两个载体给出的是两句不同的话。
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise.core.designintent import IntentSource
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.ipc import declared_currents, declared_voltages

#: 一份手写合同：两条电源轨（一条带峰值电流）+ 一条带 `range` 的信号网。三样都要能
#: 从**两种载体**读出来，所以三个小节都得被转发，而不只是报告点名的 `rails`。
CONTRACT = {
    "intentVersion": 1,
    "requirements": {
        "rails": [
            {"net": "HV", "voltage": "311V", "provenance": "user_stated"},
            {
                "net": "SEC_12V",
                "voltage": "12V",
                "peakCurrent": "2A",
                "provenance": "user_stated",
            },
        ],
        "signals": [
            {
                "net": "FB_SENSE",
                "range": "±0.5A",
                "kind": "current-sense",
                "polarity": "bidirectional",
                "provenance": "user_stated",
            }
        ],
        "buses": [],
    },
    "blocks": [],
    "decisions": [],
}


def _contract(tmp_path: Path) -> IntentSource:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(CONTRACT), encoding="utf-8")
    return IntentSource.load(path)


def test_the_three_requirement_sections_forward_to_the_document(tmp_path):
    source = _contract(tmp_path)
    assert source.rails == source.document.rails
    assert source.signals == source.document.signals
    assert source.buses == source.document.buses
    # 不是空表的三连等：转发一个 `[]` 也能过上面三条。
    assert [rail.net for rail in source.rails] == ["HV", "SEC_12V"]
    assert [signal.net for signal in source.signals] == ["FB_SENSE"]


def test_declared_voltages_answers_the_same_for_both_carriers(tmp_path):
    source = _contract(tmp_path)
    carrier = PcbReviewContext(board=None, intent=source)
    bare = PcbReviewContext(board=None, intent=source.document)

    carrier_volts, carrier_notes = declared_voltages(carrier, None)
    bare_volts, bare_notes = declared_voltages(bare, None)

    assert carrier_volts == bare_volts
    assert carrier_notes == bare_notes
    # `HV` 是合同写的、且没有任何架构枚举能覆盖它：出处字符串必须逐字来自合同那一条。
    assert carrier_volts["HV"][0] == 311.0
    assert "requirements.rails[net=HV].voltage" in carrier_volts["HV"][1]


def test_declared_currents_answers_the_same_for_both_carriers(tmp_path):
    source = _contract(tmp_path)
    carrier = PcbReviewContext(board=None, intent=source)
    bare = PcbReviewContext(board=None, intent=source.document)

    assert declared_currents(carrier) == declared_currents(bare)
    # 两条来路都要读到：`peakCurrent` 走 rail、`range` 走 signal（各自的解析器不同）。
    assert declared_currents(carrier)["SEC_12V"][0] == 2.0
    assert declared_currents(carrier)["FB_SENSE"][0] == 0.5


def test_no_contract_and_a_bare_intent_still_read_as_empty():
    """转发不许把 `None` 变成一份假合同：没有合同就是没有（钉 6）。"""
    for ctx in (
        PcbReviewContext(board=None, intent=None),
        # 一个不是 `IntentSource`、也没有这些小节的裸对象：`getattr` 的既有行为不变。
        PcbReviewContext(board=None, intent=object()),
    ):
        assert declared_voltages(ctx, None) == ({}, [])
        assert declared_currents(ctx) == {}
