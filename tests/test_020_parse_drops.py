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
3. **不多说**：正常样本（ch340 金色板）一个字都不加，`--json` 逐字节不变。

夹具只读：`llc_board.epro2`（实测丢 14 个脚：两份 SYMBOL 文档各 7 个有名脚，
Q1G/Q1S/Q2G/…）、`ch340_golden.epro2`（0）。

覆盖范围的**诚实说明**：这两个计数只有 `--view schematic` 会填。pcb 视图（缺省）
的模型来自 PCB 文档（`parsers/epro2_model.py`），根本不读 SYMBOL 文档，计数
"恒为 0"是结构决定的、不是量出来的——所以 `_load_model` 不往那里塞统计，
`cli._parse_drop_note` 也不把 0 当作"没丢东西"的证据来渲染。末尾两条测试把这条
边界也钉住，免得以后有人以为 pcb 视图的静默等于没丢。
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

#: Measured on `llc_board.epro2` (2026-09-22): the file carries the same
#: transistor-array SYMBOL document twice, and each copy ships 7 unnumbered
#: but *named* pins (Q1G/Q1S/Q2G/Q2S/Q3G/Q3S/Q4G). The assertion below is
#: `>= 1` on purpose — a library fix that numbers those pins must not turn this
#: file red; the *fact* under test is "counted and said out loud".
LLC_DROPPED_PINS_MEASURED = 14


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


def _write_backup(tmp_path: Path, name: str, records: list[str]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("board.epru", "\n".join(records))
    return path


def _symbol_doc(uuid: str, pins: list[tuple[float, float, int, str | None, str]]) -> list[str]:
    """A SYMBOL document. Each pin is ``(x, y, zIndex, number, name)``.

    ``number=None`` is the defect under test: the PIN record is there, its
    ``Pin Name`` is there, and the ``Pin Number`` never arrives.
    """
    out = [_doc_head("SYMBOL", uuid), _record("META", {"title": "SYNTH"})]
    for x, y, z, number, name in pins:
        out.append(_pin(x, y, z))
        if number is not None:
            out.append(_attr("Pin Number", number, f"{uuid}-e{z}"))
        out.append(_attr("Pin Name", name, f"{uuid}-e{z}"))
    return out


# --------------------------------------------------------------------------
# 1. 真实样本：llc 的原理图视图必须说话
# --------------------------------------------------------------------------


def test_the_llc_schematic_review_says_what_the_parse_dropped(capsys):
    code = cli.main(["review", str(LLC), "--view", "schematic"])
    out = capsys.readouterr().out

    assert code == 0
    # 前提：这份文件在原理图视图里确实解析出了东西（否则测的是别的事）。
    assert "(47 components" in out
    lines = _lines(out)
    assert lines[-1].startswith("note: ")
    assert "pin(s) dropped during parse (missing pin number)" in lines[-1]
    assert PARSE_DROP_NOTE_TAIL in lines[-1], "必须说出后果：覆盖不完整"
    # 计数是解析器自己数的，不是猜的：数字与实测一致，且 ≥1（任务书的底线）。
    reported = int(lines[-1].split("note: ")[1].split(" pin(s)")[0])
    assert reported == LLC_DROPPED_PINS_MEASURED
    assert reported >= 1
    # 一个器件都没丢符号，就不许提器件那半句。
    assert "component(s)" not in lines[-1]


def test_the_parse_count_is_what_the_parser_counts():
    # 同一个文件、同一个入口：独立数一遍，与 CLI 报的必须是同一个数。
    stats = ParseStats()
    build_schematic_model(LLC, parse_stats=stats)
    assert stats.pins_dropped_no_number == LLC_DROPPED_PINS_MEASURED
    assert stats.components_without_symbol == 0


def test_the_md_summary_carries_the_chinese_hint(tmp_path, capsys):
    md = tmp_path / "r.md"
    assert cli.main(["review", str(LLC), "--view", "schematic", "--md", str(md)]) == 0
    capsys.readouterr()
    text = md.read_text(encoding="utf-8")

    hint = parse_drop_hint(LLC_DROPPED_PINS_MEASURED, 0)
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


def test_the_console_note_joins_both_facts_and_omits_the_absent_one():
    # 两项都非 0：一句话说两件事，顺序 = 引脚、器件。
    both = _parse_drop_note(7, 3)
    assert both == (
        "note: 7 pin(s) dropped during parse (missing pin number) "
        "and 3 component(s) without a resolvable symbol" + PARSE_DROP_NOTE_TAIL
    )
    # 为 0 的项不出现，也不写 "0" —— 0 在这里不是证据（pcb 视图根本不填计数）。
    assert _parse_drop_note(0, 0) == ""
    assert "0 " not in _parse_drop_note(0, 3)
    assert "component(s)" not in _parse_drop_note(5, 0)
    # 中文侧同源：同样的取舍。
    assert parse_drop_hint(7, 3) == (
        "提示：解析中有7 个引脚因缺少引脚号被丢弃、3 个器件未能解析符号"
        "——审查覆盖不完整，结果可能漏报。"
    )
    assert parse_drop_hint(0, 0) == ""
    assert parse_drop_hint(0, 3).startswith("提示：解析中有3 个器件")


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
    # 缺省视图的模型来自 PCB 文档：它不读 SYMBOL 文档，所以这两个计数是**结构
    # 上**的 0（不是"量出来没丢"）。谁要改这条通路，先改这条测试。
    stats = ParseStats()
    model, board = cli._load_model(LLC, view="pcb", parse_stats=stats)
    assert model.components
    assert board is not None
    assert (stats.pins_dropped_no_number, stats.components_without_symbol) == (0, 0)
    assert stats.source == "", "pcb 视图不往这个 stats 里写任何东西"


def test_the_pcb_view_of_the_same_file_gets_no_note(capsys):
    # 同一份文件、缺省视图：丢脚确实存在（schematic 视图报 14），但 pcb 视图的
    # 报告没有漏掉任何它本该看到的东西——那句话在那里会是假的。
    code = cli.main(["review", str(LLC)])
    out = capsys.readouterr().out
    assert code == 0
    assert "note:" not in out
