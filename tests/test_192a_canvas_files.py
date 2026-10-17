"""192A-5/6/7：离线画布的文件名、非法字符、图注 Markdown。

**192A-5（撞名）**：``canvas_file_name`` 只保证单个标题安全，``write_canvases`` 原来
直接用它当文件名——两块同名板（同一个工程里复制粘贴出来的第二块板）于是**后者覆盖
前者**，而 ``canvas_images[]`` 里两行的 ``bytes`` 各写各的，报告说有两张图、盘上
只有一张。探针 ``.tmp_hole_5/probe_canvas.py`` 的 P2 就是这一幕。

**192A-6（控制字符）**：一条丝印文字或一块板的 META 标题带上 ``U+0001`` 这类 XML
**不允许出现**的字符（转义也不行），整张 SVG 就不是良构 XML——代价是这张图完全打不
开，不是「少一个字符」。出图前剔掉。

**192A-7（Markdown 混进 SVG）**：图注里写成了 ``**网**``，而 SVG 文本没有 Markdown，
读者看到的是一对字面星号。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from boardwise.core.geometry import (
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    PadGeometry,
    Point,
    SilkText,
)
from boardwise.engines.canvasrender import render_board_svg, write_canvases


def _pad(pid: str, comp: str, x: float = 0.0, y: float = 0.0) -> PadGeometry:
    return PadGeometry(id=pid, component=comp, x=x, y=y, width=40.0, height=20.0,
                       footprint_layer_id=1)


def _board(*pads: PadGeometry) -> BoardGeometry:
    board = BoardGeometry()
    board.pads = list(pads)
    return board


# ---------------------------------------------------------------------------
# 192A-5: two boards with one name
# ---------------------------------------------------------------------------


def test_two_boards_with_one_name_get_two_files(tmp_path: Path):
    """The file name is what the report points at, so it has to be one per board."""
    images = write_canvases(
        [("Power Board", _board(_pad("a", "U1"))),
         ("Power Board", _board(_pad("b", "U2"), _pad("c", "U2", 500, 500)))],
        out_dir=tmp_path,
        marks=[[], []],
    )
    files = [image["file"] for image in images]
    assert len(set(files)) == 2, f"两块同名板写了同一个文件：{files}"
    on_disk = sorted(path.name for path in tmp_path.glob("*.svg"))
    assert on_disk == sorted(files), "canvas_images[].file 与盘上的文件必须一一对应"
    for name in files:
        ET.fromstring((tmp_path / name).read_text(encoding="utf-8"))


def test_the_uuid_disambiguator_is_used_when_one_is_given(tmp_path: Path):
    """``keys`` is the board's own uuid: its last 6 digits, the way the editor says it."""
    images = write_canvases(
        [("Power Board", _board(_pad("a", "U1"))),
         ("Power Board", _board(_pad("b", "U2")))],
        out_dir=tmp_path,
        keys=["ab812fb7-0000-4000-8000-00000000abcd", "3e2ff784-0000-4000-8000-0000000c0ffe"],
    )
    assert images[0]["file"] == "canvas-Power_Board.svg", "第一块不用改名字"
    assert images[1]["file"] == "canvas-Power_Board-0c0ffe.svg"
    assert (tmp_path / images[1]["file"]).is_file()


def test_titles_that_sanitise_to_one_name_are_also_split(tmp_path: Path):
    """``"A B"`` and ``"A/B"`` are two titles; the sanitiser maps both to ``A_B``."""
    images = write_canvases(
        [("A B", _board(_pad("a", "U1"))), ("A/B", _board(_pad("b", "U2")))],
        out_dir=tmp_path,
    )
    assert len({image["file"] for image in images}) == 2


# ---------------------------------------------------------------------------
# 192A-6: characters XML cannot carry
# ---------------------------------------------------------------------------


def test_a_control_character_cannot_break_the_document():
    """A silk string with U+0001 is a fact about the file, not a reason to lose the图."""
    board = _board(_pad("a", "U1"))
    board.silk_texts = [
        SilkText(component="R1", text="ab\x01c", source="board", x=1.0, y=1.0,
                 layer_id=3, layer_kind="TOP_SILK", font_size=24.0,
                 origin="LEFT_BOTTOM"),
    ]
    svg = render_board_svg(board, title="ctrl\x02title")
    ET.fromstring(svg)
    assert "\x01" not in svg and "\x02" not in svg


def test_an_ordinary_title_and_text_survive_unchanged():
    """Stripping illegal characters must not touch anything else."""
    board = _board(_pad("a", "U1"))
    board.outline = BoardOutline(points=[Point(0, 0), Point(600, 0), Point(600, 400),
                                        Point(0, 400)], closed=True)
    board.silk_texts = [
        SilkText(component="R1", text='R1 <&">', source="board", x=10.0, y=10.0,
                 layer_id=3, layer_kind="TOP_SILK", font_size=24.0,
                 origin="LEFT_BOTTOM"),
    ]
    svg = render_board_svg(board, title="主板 A")
    ET.fromstring(svg)
    assert "主板 A" in svg and "R1 &lt;&amp;&quot;&gt;" in svg


# ---------------------------------------------------------------------------
# 192A-7: Markdown in a caption
# ---------------------------------------------------------------------------


def test_the_caption_carries_no_markdown():
    """SVG text has no Markdown: ``**网**`` is a pair of literal asterisks on screen."""
    board = _board(_pad("a", "U1"))
    board.components = [ComponentPlacement(id="c1", designator="U1", x=0.0, y=0.0, layer_id=1)]
    svg = render_board_svg(board, title="t")
    body = svg.split("</svg>")[0]
    for line in body.splitlines():
        if "<text" in line:
            assert "**" not in line, line
