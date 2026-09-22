"""review 空板视图提示（任务 019）——全离线，用**真实夹具**：

`.epro2` 的 `--view` 缺省是 `pcb`。只画了原理图的导出在 pcb 视图里就是
"0 components, 0 nets" + "board: 0 pads, 0 tracks, 0 vias"，018 之前这句话就是
全部——读的人没有理由知道该加 `--view schematic`，只会以为导出是空的（016 场景 6
的教训 B，Kimi 自己踩过）。这里钉两件事：**该说的时候说**（控制台一行英文 +
`--md` 中文摘要里一句中文），**不该说的时候一个字都不加**（`--json` 逐字节不变）。

夹具是现成的、不许动：
- `EMPTY_PCB = tests/fixtures/ch340_golden.epro2`：真实的原理图导出，pcb 视图
  0 器件 0 网络 0 铜，schematic 视图 17 器件 13 网络——同一个文件、两种视图，
  正好是提示要解释的那种落差；
- `FILLED_PCB = tests/fixtures/llc_board.epro2`：pcb 视图 47 器件 117 焊盘，
  有内容时必须闭嘴。

`.enet` 的"全空"用例在 tmp_path 里现写一个空网表：`.enet` 没有视图可选，空就是
真空，给它一句"请加 `--view schematic`"是彻头彻尾的错话——这也是唯一能触发
"后缀条件"的用例（有内容的文件是被"有内容"挡住的，不是被后缀挡住的）。
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise import cli
from boardwise.cli import EMPTY_PCB_VIEW_NOTE, _pcb_view_read_nothing
from boardwise.core.geometry import BoardGeometry, PadGeometry
from boardwise.core.model import DesignModel
from boardwise.engines.review import render_json
from boardwise.rules.i18n import EMPTY_PCB_VIEW_HINT, summary_section

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
EMPTY_PCB = FIXTURES / "ch340_golden.epro2"
FILLED_PCB = FIXTURES / "llc_board.epro2"


def _empty_enet(tmp_path: Path) -> Path:
    """A netlist with no components at all — an empty `.enet` is empty for real."""
    path = tmp_path / "empty.enet"
    path.write_text(
        json.dumps(
            {
                "version": "2.0.0",
                "components": {},
                "designRule": {},
                "differentialPair": {},
                "netClass": {},
                "equalLengthNetGroup": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def _lines(out: str) -> list[str]:
    return out.rstrip("\n").split("\n")


# --------------------------------------------------------------------------
# 1. 触发：`.epro2` + 缺省 view + 全空
# --------------------------------------------------------------------------


def test_the_console_says_why_the_pcb_view_read_nothing(capsys):
    code = cli.main(["review", str(EMPTY_PCB)])
    out = capsys.readouterr().out

    assert code == 0
    # 前提：这份文件在 pcb 视图里确实是全空的（否则这个测试什么也没钉住）。
    assert "(0 components, 0 nets)" in out
    assert "board: 0 pads, 0 tracks, 0 vias" in out
    assert EMPTY_PCB_VIEW_NOTE in out
    assert "--view schematic" in EMPTY_PCB_VIEW_NOTE, "提示必须说出该加什么参数"
    # 空跑时这一行是读者唯一要照做的东西：排在最后，不许被"written to"之类挤在中间。
    assert _lines(out)[-1] == EMPTY_PCB_VIEW_NOTE


def test_the_note_is_last_even_when_the_reports_are_written(tmp_path, capsys):
    md = tmp_path / "r.md"
    json_path = tmp_path / "r.json"
    code = cli.main(["review", str(EMPTY_PCB), "--json", str(json_path), "--md", str(md)])
    out = capsys.readouterr().out

    assert code == 0
    assert f"JSON report written to {json_path}" in out
    assert f"Markdown report written to {md}" in out
    assert _lines(out)[-1] == EMPTY_PCB_VIEW_NOTE


def test_latest_on_an_empty_backup_gets_the_note_too(tmp_path, capsys):
    # `--latest` picks a path itself; the hint must not depend on the file being
    # spelled on the command line.
    root = tmp_path / "lc"
    root.mkdir()
    picked = root / "empty_backup.epro2"
    picked.write_bytes(EMPTY_PCB.read_bytes())

    code = cli.main(["review", "--latest", str(root)])
    out = capsys.readouterr().out

    assert code == 0
    assert str(picked) in out
    assert _lines(out)[-1] == EMPTY_PCB_VIEW_NOTE


# --------------------------------------------------------------------------
# 2. `--md`：中文摘要里那一句
# --------------------------------------------------------------------------


def test_the_md_summary_carries_the_chinese_hint(tmp_path, capsys):
    md = tmp_path / "r.md"
    assert cli.main(["review", str(EMPTY_PCB), "--md", str(md)]) == 0
    capsys.readouterr()
    text = md.read_text(encoding="utf-8")

    assert EMPTY_PCB_VIEW_HINT in text
    assert "`--view schematic`" in text
    # 位置：在中文摘要节里、在"没有发现问题"这句结论之后（它解释的正是这句话），
    # 且报告开头仍是 018/test_cli 钉死的字节。
    assert text.startswith("# boardwise review report")
    summary_at = text.index("## 中文摘要")
    assert summary_at < text.index("- 没有发现问题。") < text.index(EMPTY_PCB_VIEW_HINT)
    # 英文正文一行没动，中文提示不混进英文报告体。
    assert "No findings." in text
    assert text.index(EMPTY_PCB_VIEW_HINT) < text.index("No findings.")


def test_the_summary_section_reads_the_hint_as_its_own_paragraph():
    # 单独成段：紧贴列表写的话 markdown 会把它并进上一个列表项。
    text = summary_section([], {"ERROR": 0, "WARN": 0, "INFO": 0}, hint="提示：X")
    assert text.split("\n") == [
        "## 中文摘要",
        "",
        "共 0 条发现：0 错误 / 0 警告 / 0 提示",
        "",
        "- 没有发现问题。",
        "",
        "提示：X",
        "",
    ]
    # 不触发时与 018 的输出逐字节一致（既有测试读的就是这个形状）。
    assert summary_section(
        ["- 行一"], {"ERROR": 1, "WARN": 0, "INFO": 0}
    ) == summary_section(["- 行一"], {"ERROR": 1, "WARN": 0, "INFO": 0}, hint="")


# --------------------------------------------------------------------------
# 3. `--json`：一个字节都不变
# --------------------------------------------------------------------------


def test_the_json_report_is_the_untouched_empty_report(tmp_path, capsys):
    json_path = tmp_path / "r.json"
    md = tmp_path / "r.md"
    assert (
        cli.main(["review", str(EMPTY_PCB), "--json", str(json_path), "--md", str(md)])
        == 0
    )
    capsys.readouterr()
    raw = json_path.read_text(encoding="utf-8")

    # 全空模型跑出来的发现是空的，所以报告就是引擎对空列表的渲染——键不多不少。
    assert raw == render_json([])
    assert "提示" not in raw and "note:" not in raw
    payload = json.loads(raw)
    assert set(payload) == {"summary", "findings"}
    assert payload == {"summary": {"ERROR": 0, "WARN": 0, "INFO": 0}, "findings": []}


def test_the_json_is_byte_identical_with_and_without_the_markdown(tmp_path, capsys):
    plain = tmp_path / "plain.json"
    both = tmp_path / "both.json"
    assert cli.main(["review", str(EMPTY_PCB), "--json", str(plain)]) == 0
    assert (
        cli.main(["review", str(EMPTY_PCB), "--json", str(both), "--md", str(tmp_path / "r.md")])
        == 0
    )
    capsys.readouterr()
    assert plain.read_bytes() == both.read_bytes()


# --------------------------------------------------------------------------
# 4. 不触发：逐条钉住触发条件的三个合取项
# --------------------------------------------------------------------------


def test_a_schematic_review_of_the_same_file_gets_no_note(tmp_path, capsys):
    md = tmp_path / "r.md"
    code = cli.main(["review", str(EMPTY_PCB), "--view", "schematic", "--md", str(md)])
    out = capsys.readouterr().out
    text = md.read_text(encoding="utf-8")

    assert code == 0
    # 同一个文件在 schematic 视图里有内容——这就是提示存在的理由。
    assert "(17 components, 13 nets)" in out
    assert EMPTY_PCB_VIEW_NOTE not in out
    assert EMPTY_PCB_VIEW_HINT not in text


def test_a_board_the_pcb_view_can_read_gets_no_note(capsys):
    code = cli.main(["review", str(FILLED_PCB)])
    out = capsys.readouterr().out

    assert code == 0
    assert "(47 components, 25 nets)" in out
    assert "0 pads" not in out
    assert EMPTY_PCB_VIEW_NOTE not in out


def test_an_empty_enet_never_gets_the_view_note(tmp_path, capsys):
    # `.enet` 没有视图可选：空网表就是空网表，指路 `--view schematic` 是错话。
    code = cli.main(["review", str(_empty_enet(tmp_path))])
    out = capsys.readouterr().out

    assert code == 0
    assert "(0 components, 0 nets)" in out
    assert EMPTY_PCB_VIEW_NOTE not in out


def test_the_predicate_needs_all_three_conditions():
    empty = DesignModel()
    no_copper = BoardGeometry()
    with_copper = BoardGeometry(pads=[PadGeometry(id="pad1")])

    # 三条件齐备才触发（大小写后缀也算 .epro2，同 `--latest`）。
    assert _pcb_view_read_nothing(Path("b.epro2"), "pcb", empty, no_copper) is True
    assert _pcb_view_read_nothing(Path("B.EPRO2"), "pcb", empty, no_copper) is True
    # 铜在、网表空：不是"视图没读到"，是这块板真的没有网表——不能说错话。
    assert _pcb_view_read_nothing(Path("b.epro2"), "pcb", empty, with_copper) is False
    assert _pcb_view_read_nothing(Path("b.epro2"), "schematic", empty, no_copper) is False
    assert _pcb_view_read_nothing(Path("b.enet"), "pcb", empty, None) is False
