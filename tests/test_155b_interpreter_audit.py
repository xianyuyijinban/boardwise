"""Tests for task 155b: 岳裁④⑤ —— 两条「解释器有问题」的核查。

**本批次不改 ``src/``**：两条核查的结论都是「文件如此，解析器读对了」。
这个文件把结论钉成可重跑的断言，证据在 ``outputs/155b/recon_e1*.txt`` /
``recon_e2.txt``（SYMBOL 原文片段另存 ``outputs/155b/e2_symbol_<版>.txt``）。

④ **Board3 的 R1-R6 是不是「摆在底层、解析器看不见」**（岳 2026-10-11 疑）
=========================================================================

结论：**证伪**。1.1.0 夹具的 ``PCB3`` 文档里**真的没有** R1-R6——

* 原始记录面：``PCB3`` 只有 33 条 ``COMPONENT``，33 条都带
  ``ATTR key="Designator"``；33 个位号里既没有 R1…R6，任何记录类型的任何字段
  里也搜不到这六个名字；
* 解析器面：``collect_pcb_context`` / ``build_design_model`` / ``extract_board``
  三条路口径一致，都是 **33/33**——一个不漏；
* **底层件解析器看得见**：``PCB3`` 的 ``layerId=2``（底面）器件是
  ``R18``/``R43``/``R8``，三颗都在 model 与几何里；``PCB1`` 的底面四颗
  ``C14``/``R17``/``U4``/``U6``（``parsers/epru.py::pad_effective_layers``
  docstring 里点名的那一组）同样一颗不漏。**没有任何一方丢过底层件。**
* 所以 E1 的 6 条 ERROR 是**读文件读对了**：原理图 ``Board3`` 声明 39 颗、
  ``PCB3`` 只实现 33 颗，差的正是 ``R1``…``R6``（原理图侧全是 ``0805`` /
  ``0805W8J0100T5E``）。文件里没有这六颗 → 该去编辑器确认 Board3 底面的是
  「画了没导出的备份」还是「岳记错了板」。

⑤ **NCD0805R1 的 LED 极性「是不是解释器读反了」**（岳的质疑）
=================================================================

结论：**证伪**（不是解释器）。同一颗料在两版里引用的 SYMBOL 文档 uuid 相同
（``8a24a32599584ee3a2f628a7c2c0e930``），内容**只差两行**：

=======================  ==============  ==============
记录                     1.0.0           1.1.0
=======================  ==============  ==============
``ATTR e7`` Pin Number   ``"1"``         ``"2"``
``ATTR e13`` Pin Number  ``"2"``         ``"1"``
=======================  ==============  ==============

其余记录（两条 ``PIN``、Pin Name ``e6='+'``/``e12='-'``、全部 ``POLY`` 几何）
**逐字节相同**。也就是说 1/2 脚号是**在文件里被换过**，画在符号上的
「``+`` 在右、``-`` 在左」两版一模一样。两个解析器各自都与自己那份文件一致
（原理图侧 ``build_project_model``、PCB 侧 ``symbol_pin_names`` 读出同一张表）。

而且换的不只是符号：两版的封装是**两个文档**（``LED0805-R-RD`` /
``LED0805-RD``），焊盘编号也同步换了（1.0.0 的 pad 1 在 +x，1.1.0 的 pad 1
在 −x）。所以**物理结果没变**：两版里 ``+`` 都落在 +x 侧的焊盘上，``LED1``
都保持「负极 → GND、正极 → $1N66613」。这是**编号约定的变更**，不是装反的 LED。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from boardwise.engines.pcbreview import _pcb_documents, run_pcb_review
from boardwise.parsers.epro2_model import build_design_model, symbol_pin_names
from boardwise.parsers.epru import extract_board, load_epro2_source, pad_templates
from boardwise.parsers.schematic import build_project_model

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"

RULE_ID = "pcb-footprint-consistency"
LED_SYMBOL_UUID = "8a24a32599584ee3a2f628a7c2c0e930"
LED_DEVICE_UUID = "788ed24ffd054dc3b4e3023e74c9684d"

#: ``PCB3`` 的 33 个位号——从原始 ``ATTR key="Designator"`` 记录里读出来的全集。
PCB3_DESIGNATORS = frozenset(
    {
        "C1", "C10", "C11", "C115", "C116", "C12", "C13", "C2", "C3", "C4",
        "C5", "C6", "C7", "C8", "C9", "CN3", "D2", "Q1", "Q2", "Q3", "Q4",
        "Q7", "Q8", "R18", "R43", "R8", "SCREW1", "SCREW2", "SCREW3",
        "SCREW4", "U1", "U14", "U2",
    }
)


# ---------------------------------------------------------------------------
# helpers — the raw record face, read exactly the way the parser reads it
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _source(path: Path):
    return load_epro2_source(path)


@lru_cache(maxsize=4)
def _review(path: Path):
    """``run_pcb_review`` over all 25 rules — cached, it is the slow call."""
    return run_pcb_review(path, model=build_project_model(path))


@lru_cache(maxsize=4)
def _schematic(path: Path):
    return build_project_model(path)


def _document(source, title: str):
    for doc_title, _board_uuid, document in _pcb_documents(source):
        if doc_title == title:
            return document
    raise AssertionError(f"no PCB document titled {title!r}")


def _raw_placements(document) -> dict[str, dict]:
    """位号 → 原始 ``COMPONENT`` 记录读数（id / layerId / x / y / angle）。

    走的是 ``parsers/epru.py::collect_pcb_context`` 的同一份记录流：
    ``COMPONENT`` 建位姿、``ATTR key="Designator"`` 按 ``parentId`` 挂上去
    （epru.py:1015-1057），字段名与那里逐字一致（``angle`` 缺了就取
    ``rotation``）。**不按 ``layerId`` 过滤**——这正是要证明的那一点。
    """
    by_id: dict[str, str] = {}
    for record in document.records:
        if record.type == "ATTR" and record.body is not None:
            if record.body.get("key") == "Designator":
                by_id[str(record.body.get("parentId"))] = str(record.body.get("value"))
    out: dict[str, dict] = {}
    for record in document.records:
        if record.type != "COMPONENT" or record.body is None:
            continue
        designator = by_id.get(record.id or "")
        if not designator:
            continue
        angle = record.body.get("angle")
        if angle is None:
            angle = record.body.get("rotation")
        out[designator] = {
            "id": record.id or "",
            "layerId": record.body.get("layerId"),
            "x": record.body.get("x"),
            "y": record.body.get("y"),
            "angle": angle,
        }
    return out


def _raw_component_count(document) -> int:
    return sum(1 for r in document.records if r.type == "COMPONENT")


def _board_layers(document, source) -> dict[str, object]:
    board = extract_board(
        document, source.footprints(), source.stats, source.footprint_artwork()
    )
    return {c.designator: c.layer_id for c in board.components}


def _rows_for(findings, title: str) -> list:
    return [f for f in findings if getattr(f, "board", None) == title]


def _footprint_of(source, uuid: str):
    for document in source.documents_of_type("FOOTPRINT"):
        if document.uuid != uuid:
            continue
        title = ""
        for record in document.records:
            if record.type == "META" and record.body is not None:
                title = str(record.body.get("title") or "")
        return title, {p.num: p for p in pad_templates(document)}
    raise AssertionError(f"no FOOTPRINT document {uuid}")


def _device_attrs(source, uuid: str) -> dict:
    for document in source.documents_of_type("DEVICE"):
        if document.uuid != uuid:
            continue
        for record in document.records:
            if record.type == "META" and record.body is not None:
                return dict(record.body.get("attributes") or {})
    raise AssertionError(f"no DEVICE document {uuid}")


def _symbol_records(source, uuid: str) -> list[tuple[str, str, dict]]:
    for document in source.documents_of_type("SYMBOL"):
        if document.uuid != uuid:
            continue
        return [
            (record.type, str(record.id or ""), dict(record.body or {}))
            for record in document.records
        ]
    raise AssertionError(f"no SYMBOL document {uuid}")


def _pin_rows(source, key: str) -> dict[str, str]:
    return {
        rid: body.get("value")
        for rtype, rid, body in _symbol_records(source, LED_SYMBOL_UUID)
        if rtype == "ATTR" and body.get("key") == key
    }


def _mpn_pins(path: Path) -> set[tuple[str, str]]:
    """原理图侧读出的 ``NCD0805R1`` 的 ``(脚号, 脚名)`` 集合（跨全部板）。"""
    return {
        (p.number, p.name)
        for board in _schematic(path).boards
        for c in (getattr(board, "components", {}) or {}).values()
        if str(getattr(c, "mpn", "") or "") == "NCD0805R1"
        for p in c.pins
    }


# ---------------------------------------------------------------------------
# ④ — PCB3 的原始记录面：R1-R6 根本不在文件里
# ---------------------------------------------------------------------------


def test_pcb3_raw_records_carry_33_components_and_33_designators():
    """``PCB3`` 的原始 COMPONENT 与 Designator 都是 33 条，一个都没缺名字。"""
    document = _document(_source(FOC_110), "PCB3")
    assert _raw_component_count(document) == 33
    raw = _raw_placements(document)
    assert set(raw) == PCB3_DESIGNATORS
    assert len(raw) == 33


def test_pcb3_raw_stream_contains_no_record_naming_any_of_r1_to_r6():
    """``PCB3`` 的**任何记录的任何字段值**都不等于 R1…R6——一条都没有。

    这一步比「数 COMPONENT」严：它排除了「器件藏在别的记录类型里」「Designator
    挂在别的 parentId 上」「名字写在别的字段里」这三类解释。
    """
    document = _document(_source(FOC_110), "PCB3")
    wanted = {"R1", "R2", "R3", "R4", "R5", "R6"}
    for record in document.records:
        if record.body is not None and record.body.get("key") == "Designator":
            assert str(record.body.get("value")) not in wanted
    blob = "\n".join(
        json.dumps(record.body, ensure_ascii=False, sort_keys=True)
        for record in document.records
        if record.body is not None
    )
    for name in sorted(wanted):
        assert f'"Designator", "value": "{name}"' not in blob

    # 每个字段的**值**（含列表元素）都不等于这六个名字
    for record in document.records:
        if not isinstance(record.body, dict):
            continue
        for key, value in record.body.items():
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if isinstance(candidate, str):
                    assert candidate not in wanted, (record.type, key, candidate)


def test_parser_sees_every_pcb3_component_and_the_bottom_layer_ones_too():
    """三条解析路口径一致 33/33，且底面（``layerId=2``）的三颗一颗不漏。

    ``R18``/``R43``/``R8`` 是 ``PCB3`` 摆在**底面**的器件——如果解析器按
    ``COMPONENT.layerId`` 过滤，它们会先消失。实测原始面、model 面、几何面的
    底面集合完全相同，且 model 的 uid 与原始记录的 id 一一对应。
    """
    source = _source(FOC_110)
    document = _document(source, "PCB3")
    raw = _raw_placements(document)
    model = build_design_model(source, document)
    layers = _board_layers(document, source)

    assert len(raw) == len(model.components) == len(layers) == 33
    assert set(model.components) == set(layers) == set(raw)

    raw_bottom = {ref for ref, row in raw.items() if row["layerId"] == 2}
    assert raw_bottom == {"R18", "R43", "R8"}
    assert {ref for ref, layer in layers.items() if layer == 2} == raw_bottom
    assert {c.uid for c in model.components.values()} == {
        row["id"] for row in raw.values()
    }


def test_parser_sees_pcb1_bottom_layer_components_named_in_the_epru_docstring():
    """``PCB1`` 的底面四颗（``C14``/``R17``/``U4``/``U6``）同样在解析器里。

    这四颗正是 ``parsers/epru.py::pad_effective_layers`` docstring 点名的例子
    （底面器件的 SMD 焊盘自身仍写着 ``layerId=1``，面在 ``COMPONENT.layerId``）。
    """
    source = _source(FOC_110)
    document = _document(source, "PCB1")
    raw = _raw_placements(document)
    layers = _board_layers(document, source)
    assert len(raw) == 105
    assert {ref for ref, row in raw.items() if row["layerId"] == 2} == {
        "C14", "R17", "U4", "U6"
    }
    assert {ref for ref, layer in layers.items() if layer == 2} == {
        "C14", "R17", "U4", "U6"
    }


def test_foc_100_is_the_control_case_with_no_bottom_layer_parts():
    """对照：1.0.0 两块板**没有**底面器件（``layerId`` 全是 1）。

    有了这条，「解析器看不见底层件」这个假设在 1.0.0 上根本没有可观察对象，
    它只能来自 1.1.0 的 PCB1/PCB3——而那两块都证明解析器看得见。
    """
    source = _source(FOC_100)
    seen: dict[str, int] = {}
    for title in ("PCB1", "PCB2"):
        raw = _raw_placements(_document(source, title))
        seen[title] = len(raw)
        assert {row["layerId"] for row in raw.values()} == {1}
    assert seen == {"PCB1": 122, "PCB2": 10}


# ---------------------------------------------------------------------------
# ④ — 规则面：E1 那 6 条 ERROR 是「读文件读对了」
# ---------------------------------------------------------------------------


def test_e1_reports_the_six_declared_but_unplaced_resistors_on_pcb3():
    findings, section = _review(FOC_110)
    assert section is not None
    pcb3 = _rows_for([f for f in findings if f.rule_id == RULE_ID], "PCB3")
    errors = [f for f in pcb3 if f.severity == "ERROR"]
    assert len(errors) == 6
    assert {f.target.component_ref for f in errors} == {
        "R1", "R2", "R3", "R4", "R5", "R6"
    }
    assert all("没摆" in f.message for f in errors)

    summary = [f for f in pcb3 if "封装对账" in f.message]
    assert len(summary) == 1
    assert "比了 33 个两边都有的器件" in summary[0].message
    assert "原理图有而 PCB 没摆 6 个" in summary[0].message
    assert "PCB 摆而原理图没有 0 个" in summary[0].message


def test_the_six_do_not_leak_onto_pcb1_even_though_board1_shares_the_names():
    """``Board1``/``PCB1`` 也有 R1…R6，但那条 6 ERROR 只挂在 ``PCB3`` 上。"""
    findings, _section = _review(FOC_110)
    pcb1 = _rows_for([f for f in findings if f.rule_id == RULE_ID], "PCB1")
    assert [f for f in pcb1 if f.severity == "ERROR" and "没摆" in f.message] == []
    summary = [f for f in pcb1 if "封装对账" in f.message]
    assert len(summary) == 1
    assert "原理图有而 PCB 没摆 0 个" in summary[0].message


# ---------------------------------------------------------------------------
# ⑤ — LED 的符号脚号：文件里真的被换过
# ---------------------------------------------------------------------------


def test_the_led_symbol_pin_numbers_are_swapped_in_the_file_itself():
    """两版的 ``Pin Number`` 记录原文：``e7`` 1↔2、``e13`` 2↔1。"""
    assert _pin_rows(_source(FOC_100), "Pin Number") == {"e7": "1", "e13": "2"}
    assert _pin_rows(_source(FOC_110), "Pin Number") == {"e7": "2", "e13": "1"}


def test_the_plus_minus_names_and_the_drawing_are_byte_identical():
    """``+``/``-`` 两个 Pin Name 与全部图元记录逐字节相同——换的只是脚号。

    这是这条裁定的关键：如果连 ``+``/``-`` 画在哪只脚上都变了，那就是另一个
    故事（重画符号）；实测 ``e6='+'``/``e12='-'`` 两版一致，两条 ``PIN`` 的
    坐标与所有 ``POLY`` 的每一个字段都相等。
    """
    one = {
        rid: (rtype, body)
        for rtype, rid, body in _symbol_records(_source(FOC_100), LED_SYMBOL_UUID)
    }
    two = {
        rid: (rtype, body)
        for rtype, rid, body in _symbol_records(_source(FOC_110), LED_SYMBOL_UUID)
    }
    assert _pin_rows(_source(FOC_100), "Pin Name") == {"e6": "+", "e12": "-"}
    assert _pin_rows(_source(FOC_110), "Pin Name") == {"e6": "+", "e12": "-"}

    assert set(one) == set(two)
    differing = {rid for rid in one if one[rid] != two[rid]}
    # 只有两条 Pin Number 与文档头/尾的元数据（DOCHEAD id 为空 / META）不同
    assert differing == {"e7", "e13", "", "META"}
    assert one[""][0] == two[""][0] == "DOCHEAD"
    assert one["META"][0] == two["META"][0] == "META"

    # 两条 Pin Number 除 value 外每个字段都相同
    for rid in ("e7", "e13"):
        left, right = dict(one[rid][1]), dict(two[rid][1])
        assert left.pop("value") != right.pop("value")
        assert left == right

    # 图元与 PIN 记录逐字节相同（两版的画法没动）
    drawn = [rid for rid in one if one[rid][0] in ("PIN", "POLY", "FILL", "CIRCLE")]
    assert len(drawn) == 8  # 6 条 POLY + 2 条 PIN
    for rid in drawn:
        assert one[rid][1] == two[rid][1], rid
    assert one["e5"][1]["x"] == two["e5"][1]["x"] == 20
    assert one["e11"][1]["x"] == two["e11"][1]["x"] == -20


def test_both_parsers_read_each_file_faithfully():
    """原理图解析器与 PCB 侧解析器各自读出自己那份文件的脚号，没有「读反」。"""
    assert _mpn_pins(FOC_100) == {("1", "+"), ("2", "-")}
    assert _mpn_pins(FOC_110) == {("1", "-"), ("2", "+")}

    # PCB 侧：同一张表（symbol_pin_names 是 build_design_model 填 Pin.name 的源）
    assert symbol_pin_names(_source(FOC_100))[LED_SYMBOL_UUID] == {"1": "+", "2": "-"}
    assert symbol_pin_names(_source(FOC_110))[LED_SYMBOL_UUID] == {"1": "-", "2": "+"}

    # 两个 DEVICE 是同一条记录的两个版本：符号指针相同、封装指针不同
    attrs_one = _device_attrs(_source(FOC_100), LED_DEVICE_UUID)
    attrs_two = _device_attrs(_source(FOC_110), LED_DEVICE_UUID)
    assert attrs_one["Symbol"] == attrs_two["Symbol"] == LED_SYMBOL_UUID
    assert attrs_one["Manufacturer Part"] == attrs_two["Manufacturer Part"] == "NCD0805R1"
    assert attrs_one["Footprint"] != attrs_two["Footprint"]


def test_the_footprint_pads_are_renumbered_in_lockstep_so_the_plus_stays_put():
    """焊盘编号同步换过：两版里 ``+`` 那只脚都落在 **+x 侧**的焊盘上。

    符号侧 ``+`` 画在 ``x=+20``（``PIN e5``）、``-`` 画在 ``x=-20``（``PIN e11``），
    两版一致；封装侧 1.0.0 的 pad 1 在 ``x=+41.35``、1.1.0 的 pad 1 在
    ``x=-43.312``——所以「``+`` 对应哪个 pad 号」也换了，物理朝向没动。
    """
    one, two = _source(FOC_100), _source(FOC_110)
    title_one, pads_one = _footprint_of(
        one, _device_attrs(one, LED_DEVICE_UUID)["Footprint"]
    )
    title_two, pads_two = _footprint_of(
        two, _device_attrs(two, LED_DEVICE_UUID)["Footprint"]
    )
    assert title_one == "LED0805-R-RD"
    assert title_two == "LED0805-RD"

    assert (pads_one["1"].local_x, pads_one["2"].local_x) == (41.35, -41.35)
    assert pads_two["1"].local_x < 0 < pads_two["2"].local_x

    # 「正极那一侧」两版都是 +x：1.0.0 的 + 是 pad 1，1.1.0 的 + 是 pad 2
    assert pads_one["1"].local_x > 0
    assert pads_two["2"].local_x > 0


def test_led1_keeps_the_same_physical_wiring_in_both_revisions():
    """``LED1`` 的**名字→网络**映射两版相同：``+``→``$1N66613``、``-``→``GND``。

    脚号换了、PAD_NET 里的脚号也跟着换，但物理连接没变——所以这不是一颗装反的
    LED，只是两版之间「哪只脚叫 1」的定义变了。
    """
    for path, first, second in (
        (FOC_100, "LED1", "LED4"),
        (FOC_110, "LED1", "LED2"),
    ):
        source = _source(path)
        model = build_design_model(source, _document(source, "PCB1"))
        assert {p.name: p.net for p in model.components[first].pins} == {
            "+": "$1N66613", "-": "GND"
        }
        assert {p.name: p.net for p in model.components[second].pins} == {
            "+": "$1N66624", "-": "AGND"
        }


def test_the_polarity_rule_stays_silent_on_the_numbering_change():
    """E2 的输入是**每一版自己的**符号——所以它不报「标记与极性脚不符」。

    两版的丝印上都没有 ``+``/``-`` 印字，规则按「装反了没有」的口径不该出
    ERROR；两版各跑一次，ERROR 都是 0。这条把「规则没错」钉住。
    """
    for path in (FOC_100, FOC_110):
        findings, _section = _review(path)
        assert [
            f
            for f in findings
            if f.rule_id == "pcb-polarity-orientation" and f.severity == "ERROR"
        ] == [], path.name
