"""解析丢脚/丢符号的可观测化（任务 020 §WI-1）——真实夹具 + 合成最小用例。

背景（上游 issue 对照审计 §2）：原理图解析器有三条**静默丢弃**路径，此前零计数
零告警——缺 `Pin Number` 的 PIN 记录（`_collect_symbols.flush` 的 `and run_number`
硬门槛）与 `symbol_def is None` 的三处 `continue`（`build_pin_offsets`、
`build_schematic_model` 的器件段与电源旗标段）。症状与"某 USB-C 库件把 VBUS 写成
无名号脚"完全一致：恒定漏连、报告照旧说"共 N 条发现"，读的人只能理解成"都查过
了"。这里钉三件事：

1. **计到数**：两条路径分别累加到 `ParseStats.pins_dropped_no_number` /
   `components_without_symbol`；
2. **说出来**：控制台一行英文 note（同 019 的接法）+ `--md` 中文摘要一句
   （`rules.i18n.parse_drop_hint`），两句话都**只报非 0 的项**；
3. **不多说**：正常样本一个字都不加，`--json` 逐字节不变。

**049 起计数变了，口径没变（本节 2026-09-27 修订）**：`llc_board.epro2` 的 14 个脚
**不是**"文件里没有脚号"——原始记录里两份 module SYMBOL 文档各有一整块 `Pin Number`
ATTR 被增量保存追加到了文档**末尾**（`parentId` 指回各自 PIN 记录），020 当时只按流
顺序配对，于是 7 个脚丢号、吸收那一块的那个脚还被写错号。049 按 `parentId` 归档后这
14 个脚全部读到（`tests/test_049_parser_defects.py` 钉形状）。所以：
**真实夹具现在一个都不丢**，这份文件的计数断言从 14 改成 0，"计到数 / 说出来"这两条
性质改由**合成流**承载（下面 §2 的 `_unnumbered` 现场：一份真正没有任何 `Pin Number`
ATTR 的 PIN 记录，也就是唯一还该被丢掉、该被报出来的形状）。

**086 起计数器有三个，console 也说三件事（本节 2026-09-30 补）**：`ParseStats` 里一直
还有第三个丢弃计数器 `instances_without_designator`（042 §WI-2），085 把它接进了
`coverage.recordsDropped`，但 `_parse_drop_note` 仍只带两个参数——于是那块 67 颗器件
的板在 JSON 报告里记着"丢了记录"，控制台却一个字不说。086 给 `_parse_drop_note` 补上
第三参与第三种子句。它和前两个不是一回事：丢的是**整颗器件**，它根本不在模型里，所以
每条读模型的规则都看不见它（见 §2 末的钉子）。前两个计数器的断言与零语义原样不动。

覆盖范围的**诚实说明**：这两个计数只有 `--view schematic` 会填。pcb 视图的模型来自
PCB 文档（`parsers/epro2_model.py`），根本不读 SYMBOL 文档，计数"恒为 0"是结构决定的、
不是量出来的——所以 `_load_model` 不往那里塞统计，`cli._parse_drop_note` 也不把 0 当作
"没丢东西"的证据来渲染。末尾两条测试把这条边界也钉住，免得以后有人以为 pcb 视图的
静默等于没丢。（047 起 `review` 对文件的缺省视图是 schematic，这条边界要靠**显式**
`--view pcb` 才碰得到。）
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from boardwise import cli
from boardwise.cli import PARSE_DROP_NOTE_TAIL, _parse_drop_note
from boardwise.core.geometry import ParseStats
from boardwise.engines.review import render_json, run_review
from boardwise.parsers.schematic import build_schematic_model
from boardwise.rules.i18n import parse_drop_hint

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
LLC = FIXTURES / "llc_board.epro2"
CH340 = FIXTURES / "ch340_golden.epro2"

#: Measured on `llc_board.epro2` (2026-09-22, re-measured 2026-09-27): the file
#: carries the same transistor-array SYMBOL document twice, and each copy ships 7
#: pins whose numbers are appended to the **end** of the document. 020 read those
#: as "unnumbered" and counted 14 drops; 049 files them by `parentId` and reads
#: all 14. The number below is therefore the count 049 *recovered*, not a count
#: the parser drops — pinned so that a regression that starts dropping them again
#: fails here by name.
LLC_RECOVERED_PINS_MEASURED = 14


def _lines(out: str) -> list[str]:
    return out.rstrip("\n").split("\n")


# --------------------------------------------------------------------------
# 合成最小用例：手写一份 .epru 流，装进真 ZIP（解析器只认 .epro2 归档）
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    """One `.epru` line: a JSON envelope, `||`, a JSON body, `|`."""
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _doc_head(doc_type: str, uuid: str) -> str:
    return _record(
        "DOCHEAD",
        {"docType": doc_type, "uuid": uuid, "editVersion": "3.2.149"},
    )


def _attr(key: str, value, parent: str) -> str:
    return _record("ATTR", {"key": key, "value": value, "parentId": parent})


def _pin(x: float, y: float, z: int) -> str:
    return _record("PIN", {"x": x, "y": y, "zIndex": z})


def _component(part_id: str, symbol: str, designator: str) -> list[str]:
    return [
        _record("COMPONENT", {"partId": part_id, "x": 100, "y": 200, "rotation": 0}),
        _attr("Designator", designator, symbol),
        _attr("Symbol", symbol, symbol),
        _attr("Device", "dev-" + designator, symbol),
    ]


def _nameless_part(part_id: str, symbol: str, z_index: int = 5) -> list[str]:
    """A placement the library says is a part, arriving with no designator.

    042 §WI-2's shape: no ``Designator`` ATTR, and no ``DEVICE META`` document in
    the file to say "this placement is not a part" either — so
    ``_looks_like_a_nameless_part`` answers yes and the instance is counted. A
    ``zIndex`` is required (the title-block frame has none, and a page is not a
    part). Unlike the two counters above, this one is not a pin-level defect:
    the whole component never enters the model, so no rule reading the model
    can see it.
    """
    return [
        _record(
            "COMPONENT",
            {"partId": part_id, "x": 300, "y": 400, "rotation": 0, "zIndex": z_index},
        ),
        _attr("Symbol", symbol, symbol),
        _attr("Device", "dev-nameless", symbol),
    ]


def _write_backup(tmp_path: Path, name: str, records: list[str]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("board.epru", "\n".join(records))
    return path


def _symbol_doc(uuid: str, pins: list[tuple[float, float, int, str | None, str]]) -> list[str]:
    """A SYMBOL document. Each pin is ``(x, y, zIndex, number, name)``.

    ``number=None`` is the defect under test: the PIN record is there, its
    ``Pin Name`` is there, and the ``Pin Number`` never arrives. (Since 049 a
    ``Pin Number`` that arrives somewhere else in the document is still found
    by its ``parentId`` — see ``tests/test_049_parser_defects.py`` — so this is
    now the *only* shape that drops a pin, and therefore the shape every drop
    test in this file builds.)
    """
    out = [_doc_head("SYMBOL", uuid), _record("META", {"title": "SYNTH"})]
    for x, y, z, number, name in pins:
        out.append(_pin(x, y, z))
        if number is not None:
            out.append(_attr("Pin Number", number, f"{uuid}-e{z}"))
        out.append(_attr("Pin Name", name, f"{uuid}-e{z}"))
    return out


def _unnumbered(tmp_path: Path, name: str = "two_unnumbered_pins.epro2") -> Path:
    """A board whose symbol has two pins with no ``Pin Number`` anywhere.

    The `Pin Name` is present and the position is present — what is missing is
    the identity, which is why the pin has to be dropped rather than guessed at.
    """
    return _write_backup(
        tmp_path,
        name,
        [
            _doc_head("SCH_PAGE", "page1"),
            *_component("part1", "sym1", "Q1"),
            *_symbol_doc(
                "sym1",
                [
                    (0.0, 0.0, 1, "1", "G1"),      # numbered: kept
                    (10.0, 0.0, 2, None, "Q1S"),   # no Pin Number anywhere: dropped
                    (20.0, 0.0, 3, None, "Q2G"),   # ditto
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------
# 1. 真实样本：llc 的 14 个脚现在读得到，所以它不再报丢脚
# --------------------------------------------------------------------------


def test_the_llc_schematic_review_reads_the_pins_the_file_carries(capsys):
    """049 re-reading of this test's subject: the file's 14 "unnumbered" pins
    were numbered all along, in a block appended to the end of each module
    SYMBOL document. The review says nothing about dropping now — and the
    recovered pins are *on nets*, which is the whole point ("dropped" meant
    "silently unconnected").
    """
    code = cli.main(["review", str(LLC), "--view", "schematic"])
    out = capsys.readouterr().out

    assert code == 0
    assert "(47 components" in out
    assert "note:" not in out, "every pin of this board is read now"

    stats = ParseStats()
    model = build_schematic_model(LLC, parse_stats=stats)
    assert stats.pins_dropped_no_number == 0
    # U9 is the module: 10 pins, names and nets, where 020 could read only 3.
    pins = {pin.number: (pin.name, pin.net) for pin in model.components["U9"].pins}
    assert len(pins) == 10, "the 7 pins 020 counted as dropped are back"
    assert pins["3"] == ("Q1G", "CHG") and pins["4"] == ("Q1S", "CHS")
    assert LLC_RECOVERED_PINS_MEASURED == 14


def test_the_parse_count_is_what_the_parser_counts(tmp_path):
    # 同一个文件、同一个入口：独立数一遍，与 CLI 报的必须是同一个数。
    stats = ParseStats()
    build_schematic_model(LLC, parse_stats=stats)
    assert stats.pins_dropped_no_number == 0
    assert stats.components_without_symbol == 0

    # 计数本身没有被拆掉：合成流里那两个真没脚号的脚照样数、照样报。
    stats = ParseStats()
    model = build_schematic_model(_unnumbered(tmp_path), parse_stats=stats)
    assert stats.pins_dropped_no_number == 2
    assert [pin.number for pin in model.components["Q1"].pins] == ["1"]


def test_the_md_summary_carries_the_chinese_hint(tmp_path, capsys):
    md = tmp_path / "r.md"
    path = _unnumbered(tmp_path)
    assert cli.main(["review", str(path), "--view", "schematic", "--md", str(md)]) == 0
    capsys.readouterr()
    text = md.read_text(encoding="utf-8")

    hint = parse_drop_hint(2, 0)
    assert hint in text
    assert "审查覆盖不完整，结果可能漏报" in hint
    # 位置：中文摘要节内、"没有发现问题"结论之后（它解释的正是这句话）；报告开头
    # 与英文正文仍是 018 钉死的形状。
    assert text.startswith("# boardwise review report")
    assert text.index("## 中文摘要") < text.index("- 没有发现问题。") < text.index(hint)
    assert text.index(hint) < text.index("No findings.")
    # 中文摘要说"共 N 条发现"，英文正文一行没动。
    assert "共 0 条发现" in text


# --------------------------------------------------------------------------
# 2. 合成最小用例：缺 Pin Number 的 PIN 记录
# --------------------------------------------------------------------------


def test_a_pin_without_a_number_is_counted_not_silently_dropped(tmp_path, capsys):
    path = _write_backup(
        tmp_path,
        "one_unnumbered_pin.epro2",
        [
            _doc_head("SCH_PAGE", "page1"),
            *_component("part1", "sym1", "Q1"),
            *_symbol_doc(
                "sym1",
                [
                    (0.0, 0.0, 1, "1", "G1"),      # numbered: kept
                    (10.0, 0.0, 2, None, "Q1S"),   # no Pin Number: dropped
                ],
            ),
        ],
    )

    stats = ParseStats()
    model = build_schematic_model(path, parse_stats=stats)

    assert stats.pins_dropped_no_number == 1
    assert stats.components_without_symbol == 0
    # 解析结果本身没变：编号的那个脚还在，没编号的那个（照旧）不在。
    assert [pin.number for pin in model.components["Q1"].pins] == ["1"]

    code = cli.main(["review", str(path), "--view", "schematic"])
    out = capsys.readouterr().out
    assert code == 0
    assert _lines(out)[-1] == (
        "note: 1 pin(s) dropped during parse (missing pin number)" + PARSE_DROP_NOTE_TAIL
    )


def test_a_component_without_a_resolvable_symbol_is_counted(tmp_path, capsys):
    # 器件引用的 symbol uuid 在文件里没有对应文档：以前整器无声无脚。
    path = _write_backup(
        tmp_path,
        "missing_symbol.epro2",
        [
            _doc_head("SCH_PAGE", "page1"),
            *_component("part1", "sym-missing", "U1"),
            *_component("part2", "sym1", "U2"),
            *_symbol_doc("sym1", [(0.0, 0.0, 1, "1", "OUT")]),
        ],
    )

    stats = ParseStats()
    model = build_schematic_model(path, parse_stats=stats)

    assert stats.components_without_symbol == 1
    assert stats.pins_dropped_no_number == 0
    assert model.components["U1"].pins == []  # 现象原样保留：就是没脚
    assert [pin.number for pin in model.components["U2"].pins] == ["1"]

    code = cli.main(["review", str(path), "--view", "schematic"])
    out = capsys.readouterr().out
    assert code == 0
    assert _lines(out)[-1] == (
        "note: 1 component(s) without a resolvable symbol" + PARSE_DROP_NOTE_TAIL
    )


def test_the_console_note_joins_all_three_facts_and_omits_the_absent_ones():
    # 三项都非 0：一句话说三件事，顺序 = 引脚、符号、位号。
    every = _parse_drop_note(7, 3, 11)
    assert every == (
        "note: 7 pin(s) dropped during parse (missing pin number) "
        "and 3 component(s) without a resolvable symbol "
        "and 11 component(s) dropped during parse (no usable designator)"
        + PARSE_DROP_NOTE_TAIL
    )
    # 两位数（085 边界②里那张 67 颗器件的板：只有它有话可说，照样说得出来）。
    assert _parse_drop_note(0, 0, 67) == (
        "note: 67 component(s) dropped during parse (no usable designator)"
        + PARSE_DROP_NOTE_TAIL
    )
    # 为 0 的项不出现，也不写 "0" —— 0 在这里不是证据（pcb 视图根本不填计数）。
    assert _parse_drop_note(0, 0) == ""
    assert _parse_drop_note(0, 0, 0) == ""
    assert "0 " not in _parse_drop_note(0, 3)
    assert "component(s)" not in _parse_drop_note(5, 0)
    assert "0 " not in _parse_drop_note(5, 0, 2)
    assert "pin(s)" not in _parse_drop_note(0, 0, 4)
    # 中文侧同源：同一组三个计数、同样的取舍（086 起中英都是三项）。
    assert parse_drop_hint(7, 3) == (
        "提示：解析中有7 个引脚因缺少引脚号被丢弃、3 个器件未能解析符号"
        "——审查覆盖不完整，结果可能漏报。"
    )
    assert parse_drop_hint(0, 0) == ""
    assert parse_drop_hint(0, 3).startswith("提示：解析中有3 个器件")
    assert parse_drop_hint(0, 0, 67) == (
        "提示：解析中有67 个器件因无可用位号被丢弃——审查覆盖不完整，结果可能漏报。"
    )
    assert "0 个" not in parse_drop_hint(5, 0, 2)


def test_a_part_with_no_usable_designator_now_says_so_on_the_console(tmp_path, capsys):
    """085 边界②：一个整颗从模型里消失的器件，console 此前**一个字都不说**。

    085 把第三个计数器接进了 ``coverage.recordsDropped``（JSON 报告里看得见），
    但 console 这一行仍只有两个计数器，于是那块 67 颗器件的板在报告里被标成
    丢记录、在控制台上却一片安静。现在第三种子句接上了，实测：只有位号这一项
    非 0 时，最后一行就是它自己。
    """
    path = _write_backup(
        tmp_path,
        "nameless_part.epro2",
        [
            _doc_head("SCH_PAGE", "page1"),
            *_component("part1", "sym1", "Q1"),
            *_nameless_part("part2", "sym1"),
            *_symbol_doc("sym1", [(0.0, 0.0, 1, "1", "G1")]),
        ],
    )

    stats = ParseStats()
    model = build_schematic_model(path, parse_stats=stats)

    # 计数：只有第三个非 0，另两个照旧是 0。
    assert stats.instances_without_designator == 1
    assert (stats.pins_dropped_no_number, stats.components_without_symbol) == (0, 0)
    # 后果：整颗器件不在模型里（不是「没脚」，是「没有这个器件」）。
    assert list(model.components) == ["Q1"]

    code = cli.main(["review", str(path), "--view", "schematic"])
    out = capsys.readouterr().out
    assert code == 0
    assert _lines(out)[-1] == (
        "note: 1 component(s) dropped during parse (no usable designator)"
        + PARSE_DROP_NOTE_TAIL
    )

    # 中文摘要侧是同一组计数（086 起中英同口径）：md 里这句话钉的是 cli.py
    # 中文调用点的接线——它曾经缺席而 console 有，两侧同源是本批钉的东西。
    md = tmp_path / "r.md"
    assert cli.main(["review", str(path), "--view", "schematic", "--md", str(md)]) == 0
    assert "1 个器件因无可用位号被丢弃" in md.read_text(encoding="utf-8")


def test_a_synthetic_backup_with_both_defects_says_both(tmp_path, capsys):
    path = _write_backup(
        tmp_path,
        "both.epro2",
        [
            _doc_head("SCH_PAGE", "page1"),
            *_component("part1", "sym-missing", "U1"),
            *_component("part2", "sym1", "U2"),
            *_symbol_doc(
                "sym1",
                [
                    (0.0, 0.0, 1, "1", "A"),
                    (10.0, 0.0, 2, None, "B"),
                ],
            ),
        ],
    )
    stats = ParseStats()
    build_schematic_model(path, parse_stats=stats)
    assert (stats.pins_dropped_no_number, stats.components_without_symbol) == (1, 1)

    assert cli.main(["review", str(path), "--view", "schematic"]) == 0
    out = capsys.readouterr().out
    assert _lines(out)[-1] == (
        "note: 1 pin(s) dropped during parse (missing pin number) "
        "and 1 component(s) without a resolvable symbol" + PARSE_DROP_NOTE_TAIL
    )


# --------------------------------------------------------------------------
# 3. 不多说：正常样本 + `--json` 逐字节不变
# --------------------------------------------------------------------------


def test_a_healthy_export_gets_no_note_at_all(tmp_path, capsys):
    md = tmp_path / "r.md"
    code = cli.main(["review", str(CH340), "--view", "schematic", "--md", str(md)])
    out = capsys.readouterr().out
    text = md.read_text(encoding="utf-8")

    assert code == 0
    assert "(17 components, 13 nets)" in out
    assert "note:" not in out
    assert "提示：解析中有" not in text
    assert "审查覆盖不完整" not in text


def test_the_json_report_is_the_untouched_for_findings_render(tmp_path, capsys):
    # `--json` 只渲染 findings，本次改动不碰它：文件必须等于"同一个模型跑一遍
    # run_review + render_json"的字节，且不含任何 note/提示字样。
    json_path = tmp_path / "r.json"
    md = tmp_path / "r.md"
    code = cli.main(
        ["review", str(LLC), "--view", "schematic", "--json", str(json_path), "--md", str(md)]
    )
    capsys.readouterr()
    raw = json_path.read_text(encoding="utf-8")

    assert code == 0
    expected = render_json(run_review(build_schematic_model(LLC)))
    assert raw == expected
    assert "note:" not in raw and "提示" not in raw
    payload = json.loads(raw)
    assert set(payload) == {"summary", "findings"}


def test_the_json_is_byte_identical_with_and_without_the_markdown(tmp_path, capsys):
    plain = tmp_path / "plain.json"
    both = tmp_path / "both.json"
    assert cli.main(["review", str(LLC), "--view", "schematic", "--json", str(plain)]) == 0
    assert (
        cli.main(
            ["review", str(LLC), "--view", "schematic", "--json", str(both),
             "--md", str(tmp_path / "r.md")]
        )
        == 0
    )
    capsys.readouterr()
    assert plain.read_bytes() == both.read_bytes()


# --------------------------------------------------------------------------
# 4. 覆盖范围的边界（诚实钉住，不是许愿）
# --------------------------------------------------------------------------


def test_the_pcb_view_never_fills_the_drop_counters():
    # pcb 视图的模型来自 PCB 文档：它不读 SYMBOL 文档，所以这两个计数是**结构
    # 上**的 0（不是"量出来没丢"）。谁要改这条通路，先改这条测试。
    stats = ParseStats()
    model, board = cli._load_model(LLC, view="pcb", parse_stats=stats)
    assert model.components
    assert board is not None
    assert (stats.pins_dropped_no_number, stats.components_without_symbol) == (0, 0)
    assert stats.source == "", "pcb 视图不往这个 stats 里写任何东西"


def test_the_pcb_view_of_the_same_file_gets_no_note(capsys):
    # 同一份文件、显式 pcb 视图：pcb 视图的报告没有漏掉任何它本该看到的东西
    # ——那句话在那里会是假的。（049 前这条注释说"schematic 视图报 14"，现在两侧
    # 都是 0：schematic 侧因为脚号被按 parentId 找回来了，pcb 侧一如既往。）
    code = cli.main(["review", str(LLC), "--view", "pcb"])
    out = capsys.readouterr().out
    assert code == 0
    assert "note:" not in out
