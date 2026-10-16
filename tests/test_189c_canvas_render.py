"""189C 离线几何渲染（`checkup --file` 每块板一张 `canvas-<board>.svg`）。

这批要钉住的是**图与人**之间那份契约，不是像素：

* 画出来的东西在场——板框、焊盘、位号文字、两个视窗；
* **y 轴翻转**（任务书点名的第一坑）：板上 y 大的（上方的）点在图上 y 小（上方），
  底层视窗只镜像 x、上下方向与顶层一致——两条都按坐标断言，不靠肉眼；
* finding 叠加：点到的对象描边/文字进入高亮色、角落按同一编号列规则 id；点到本板
  没有的位号时**照实说找不到**；
* 空板不炸、渲染失败降级成一行、板名带斜杠不许写到 `--out` 外面；
* 端到端：`checkup --file <有 PCB 的夹具>` 落盘 SVG 并在 `report.json` 的
  `canvas_images` 里点名，`report.md` 跟着链接过去。

合成小板（手搭 `BoardGeometry`）钉机制；真夹具（`级联多电平-主拓扑`）钉接线——
两者缺一：只搭合成板就不知道 CLI 那条路有没有接上，只跑夹具就不知道翻转方向对不对。
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from boardwise.cli import _cmd_checkup
from boardwise.core.geometry import (
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    PadGeometry,
    Point,
    PourShape,
    SilkShape,
    SilkText,
    TrackSegment,
    ViaGeometry,
)
from boardwise.engines.canvasrender import (
    CANVAS_KIND,
    CANVAS_NOTE,
    CANVAS_SOURCE,
    CanvasMark,
    canvas_file_name,
    marks_from_findings,
    render_board_svg,
    write_canvases,
)
from boardwise.rules.base import Finding, FindingTarget

FIXTURES = Path(__file__).resolve().parent / "fixtures"
#: A small real archive that **does** carry a PCB document (the ch340 golden has
#: none — that one is the "no board to draw" half, pinned by test_checkup_cli).
BOARD_FIXTURE = FIXTURES / "级联多电平-主拓扑_2026-09-27.epro2"

HIGHLIGHT = "#d81b60"


def _checkup_args(**overrides) -> argparse.Namespace:
    """`checkup` 的最小离线参数集（同 test_checkup_cli 的做法：不假造别的开关）。"""
    base = {"file": "", "project": "", "instance": "", "out": "checkup", "port": None}
    base.update(overrides)
    return argparse.Namespace(**base)


def _small_board() -> BoardGeometry:
    """一块合成小板：矩形板框 + 两颗器件 + 上下两面各一个焊盘 + 位号丝印。"""
    outline = BoardOutline(
        points=[Point(0, 0), Point(1000, 0), Point(1000, 800), Point(0, 800)],
        closed=True,
        segments=1,
    )
    components = [
        ComponentPlacement(id="c1", designator="R1", x=200.0, y=600.0, layer_id=1,
                           footprint="R0603", angle=0.0),
        ComponentPlacement(id="c2", designator="C2", x=800.0, y=200.0, layer_id=2,
                           footprint="C0603", angle=0.0),
    ]
    pads = [
        PadGeometry(id="p1", component="R1", net="VCC", x=150.0, y=600.0,
                    width=60.0, height=90.0, shape="RECT",
                    effective_layer_ids=[1]),
        PadGeometry(id="p2", component="C2", net="GND", x=850.0, y=200.0,
                    width=70.0, height=70.0, shape="ELLIPSE",
                    effective_layer_ids=[2]),
    ]
    silk_shapes = [
        SilkShape(id="s1", component="R1", kind="poly", layer_kind="COMPONENT_SHAPE",
                  face=1, points=[Point(150, 560), Point(250, 560), Point(250, 640),
                                  Point(150, 640)], width=8.0),
    ]
    silk_texts = [
        SilkText(component="R1", text="R1", source="designator", x=200.0, y=680.0,
                 angle=0.0, layer_kind="TOP_SILK", font_size=60.0, origin="LEFT_BOTTOM"),
        SilkText(component="C2", text="C2", source="designator", x=800.0, y=280.0,
                 angle=0.0, layer_kind="BOT_SILK", font_size=60.0, origin="LEFT_BOTTOM"),
    ]
    return BoardGeometry(
        components=components, pads=pads, silk_shapes=silk_shapes,
        silk_texts=silk_texts, outline=outline,
    )


def _circles(svg: str) -> list[tuple[float, float, float]]:
    """SVG 里每个圆的 ``(cx, cy, r)``——半径是这版测试里分辨「哪个圆是哪一颗器件」
    的抓手（两颗过孔给不同直径，于是不用猜）。"""
    return [
        (float(cx), float(cy), float(r))
        for cx, cy, r in re.findall(
            r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)"', svg
        )
    ]


def _panels(svg: str) -> list[tuple[float, float]]:
    """两个视窗的 ``(x, width)``，按横坐标排序（第一块是左边那块）。"""
    frames = [
        (float(x), float(w))
        for x, w in re.findall(
            r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="[\d.]+" '
            r'fill="#fcfcfa"',
            svg,
        )
    ]
    return sorted(frames)


# ---------------------------------------------------------------------------
# 画什么
# ---------------------------------------------------------------------------


def test_a_small_board_renders_its_outline_pads_and_designators():
    svg = render_board_svg(_small_board(), title="SYNTH")

    ET.fromstring(svg)  # 合法 XML：拼字符串最容易出的错就是没转义
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert CANVAS_KIND in svg and "SYNTH" in svg
    assert "顶层 Top view" in svg and "底层 Bottom view" in svg
    # 板框：四点一条闭环
    assert '<polygon points="' in svg
    # 器件外框（封装图元）与位号文字
    assert "COMPONENT_SHAPE" not in svg, "层名不进图，画的是图元本身"
    assert ">R1</text>" in svg and ">C2</text>" in svg
    # 两种焊盘形状：矩形与椭圆
    assert "<rect" in svg and "<ellipse" in svg
    # 图例与口径
    assert "图层配色" in svg
    assert CANVAS_NOTE in svg


def test_the_y_axis_is_flipped_so_high_on_the_board_is_high_in_the_picture():
    """板面 y 向上、SVG y 向下——这一步漏了就整块板上下翻个个儿。

    两颗过孔**直径不同**（60 与 30），所以 SVG 里哪个圆是哪一颗不用猜。
    """
    board = BoardGeometry(
        outline=BoardOutline(points=[Point(0, 0), Point(500, 0), Point(500, 1000),
                                     Point(0, 1000)], closed=True),
        vias=[
            ViaGeometry(id="low", x=100.0, y=0.0, via_diameter=60.0),
            ViaGeometry(id="high", x=100.0, y=1000.0, via_diameter=30.0),
        ],
    )
    svg = render_board_svg(board, title="FLIP")
    low = {cy for _cx, cy, r in _circles(svg) if r == 30.0}
    high = {cy for _cx, cy, r in _circles(svg) if r == 15.0}

    assert len(low) == 1 and len(high) == 1, "两个视窗里同一颗过孔的 cy 相同（只镜像 x）"
    # 板面 y=1000 的那颗在图上必须更靠上：SVG 的 y 向下，而板面 y 向上。
    assert min(high) < min(low)
    # 两窗的 cy 完全相同 ⇒ 底层视窗只镜像 x，不镜像上下。
    assert {cy for _cx, cy, r in _circles(svg) if r in (30.0, 15.0)} == low | high


def test_the_bottom_panel_mirrors_x():
    """底层视窗按 x 镜像：板左边的东西到右边，反之亦然。"""
    board = BoardGeometry(
        outline=BoardOutline(points=[Point(0, 0), Point(1000, 0), Point(1000, 500),
                                     Point(0, 500)], closed=True),
        vias=[
            ViaGeometry(id="left", x=0.0, y=0.0, via_diameter=40.0),
            ViaGeometry(id="right", x=1000.0, y=0.0, via_diameter=20.0),
        ],
    )
    svg = render_board_svg(board, title="MIRROR")
    panels = _panels(svg)
    assert len(panels) == 2, "两个视窗各一框"
    # 顶层视窗在左（标签在左侧那块框的左上角）
    assert svg.index("顶层 Top view") < svg.index("底层 Bottom view")

    order: list[tuple[float, float]] = []
    for ox, width in panels:
        inside = [
            (cx, r) for cx, _cy, r in _circles(svg) if ox <= cx <= ox + width
        ]
        left_via = [cx for cx, r in inside if r == 20.0]
        right_via = [cx for cx, r in inside if r == 10.0]
        assert len(left_via) == 1 and len(right_via) == 1, (ox, width, inside)
        order.append((left_via[0], right_via[0]))

    # 顶层：板面 x=0 的过孔在左；底层：它在右——同一个视窗内两者必须掉个个儿。
    assert order[0][0] < order[0][1]
    assert order[1][0] > order[1][1]


def test_bottom_silk_text_is_mirrored_with_the_panel_not_just_moved():
    """底层文字跟着视窗一起镜像：落墨范围必须和规则量的那块地方重合。

    实板形状（189C 的触发例）：``pcb-silk-designator`` 报 R22 的位号丝印压在 EC3 的
    焊盘上，而 R22 的位号记录在 ``BOT_SILK``——只镜像锚点、字形照正读，字就跑到锚点
    另一边去了，图会和规则顶牛。
    """
    svg = render_board_svg(_small_board(), title="TEXT")
    _top, bottom = _panels(svg)
    # C2 的位号在 BOT_SILK 上，只出现在底层（右）视窗，且带字形镜像
    assert svg.count(">C2</text>") == 1
    match = re.search(
        r'<text x="([\d.]+)" y="[\d.]+" transform="translate\([^)]*\) scale\(-1,1\)"'
        r'[^>]*>C2</text>',
        svg,
    )
    assert match, "底层文字要带 scale(-1,1)"
    assert bottom[0] <= float(match.group(1)) <= bottom[0] + bottom[1], "画在底层视窗里"
    # R1 的位号在顶层丝印上：不镜像（零角度时连 transform 都不需要）
    assert re.search(r'<text x="[\d.]+" y="[\d.]+" font-size="[\d.]+"[^>]*>R1</text>', svg)


def test_an_angled_bottom_text_keeps_its_anchor_and_mirrors_its_glyphs():
    """带角度的底层文字：transform 的**顺序**决定锚点跑不跑。

    SVG 的 ``transform`` 列表从右往左作用，所以必须是
    ``translate(锚点) rotate(角) scale(-1,1)``——把 ``rotate`` 放最前面会把锚点也
    绕原点转走（对照：顶层用 ``rotate(角, cx, cy)``，旋转中心写在参数里）。
    """
    board = BoardGeometry(
        outline=BoardOutline(points=[Point(0, 0), Point(400, 0), Point(400, 200),
                                     Point(0, 200)], closed=True),
        silk_texts=[SilkText(component="R9", text="R9", source="designator", x=100.0,
                             y=50.0, angle=90.0, layer_kind="BOT_SILK",
                             font_size=40.0, origin="LEFT_BOTTOM")],
    )
    svg = render_board_svg(board, title="ANGLED")
    match = re.search(r'<text x="([\d.]+)" y="([\d.]+)"( transform="[^"]*")?[^>]*>R9</text>', svg)

    assert match, "文字得画出来"
    transform = match.group(3) or ""
    assert 'transform="translate(' in transform
    assert "rotate(90.000)" in transform
    assert "scale(-1,1)" in transform
    assert transform.index("translate") < transform.index("rotate") < transform.index("scale")


def test_each_panel_draws_the_copper_of_its_own_side():
    """焊盘按 ``effective_layer_ids`` 分视窗：顶层盘只在左窗，底层盘只在右窗，
    通孔盘（两面）两窗都有。"""
    board = BoardGeometry(
        outline=BoardOutline(points=[Point(0, 0), Point(600, 0), Point(600, 200),
                                     Point(0, 200)], closed=True),
        pads=[
            PadGeometry(id="top", component="R1", x=100.0, y=100.0, width=60.0,
                        height=20.0, shape="RECT", effective_layer_ids=[1]),
            PadGeometry(id="bottom", component="R2", x=300.0, y=100.0, width=100.0,
                        height=20.0, shape="RECT", effective_layer_ids=[2]),
            PadGeometry(id="through", component="J1", x=500.0, y=100.0, width=30.0,
                        height=30.0, shape="RECT", effective_layer_ids=[1, 2]),
        ],
    )
    svg = render_board_svg(board, title="SIDES")
    panels = _panels(svg)
    assert len(panels) == 2
    # 每颗焊盘的 (宽, 高) 是分辨它们的抓手（60x20 顶层 / 100x20 底层 / 30x30 通孔）。
    shapes: list[set[tuple[float, float]]] = []
    for ox, width in panels:
        rects = {
            (float(w), float(h))
            for x, w, h in re.findall(
                r'<rect x="([-\d.]+)" y="[-\d.]+" width="([\d.]+)" height="([\d.]+)" rx=',
                svg,
            )
            if ox <= float(x) <= ox + width
        }
        shapes.append(rects)

    assert shapes[0] == {(30.0, 30.0), (60.0, 20.0)}, f"顶层窗：{shapes[0]}"
    assert shapes[1] == {(30.0, 30.0), (100.0, 20.0)}, f"底层窗：{shapes[1]}"


def test_a_net_highlight_on_copper_is_dashed_while_a_part_is_solid():
    """点到网的铜画虚线、点到的器件画实线：两种主张不一样，画法就不该一样。"""
    board = _small_board()
    board.tracks.append(
        TrackSegment(id="t1", net="VCC", layer_id=1, start=Point(150, 600),
                     end=Point(900, 600), width=20.0)
    )
    hot_net = render_board_svg(
        board, title="NET", marks=[CanvasMark(rule_id="pcb-voltage-spacing",
                                              refs=(), nets=("VCC",))]
    )
    hot_part = render_board_svg(
        board, title="PART", marks=[CanvasMark(rule_id="pcb-silk-over-pad",
                                               refs=("R1",))]
    )

    assert (
        f'stroke="{HIGHLIGHT}" stroke-width="21.50" stroke-linecap="round" '
        'stroke-dasharray="7 4"'
    ) in hot_net
    assert f'fill="{HIGHLIGHT}" font-weight="700">R1</text>' in hot_part



# ---------------------------------------------------------------------------
# finding 叠加
# ---------------------------------------------------------------------------


def test_a_highlighted_designator_is_drawn_in_the_finding_colour_and_listed():
    marks = [CanvasMark(rule_id="pcb-silk-over-pad", severity="WARN", refs=("R1",))]
    svg = render_board_svg(_small_board(), title="HOT", marks=marks)

    assert f'fill="{HIGHLIGHT}" font-weight="700">R1</text>' in svg, "点到的位号换色加粗"
    assert ">#1</text>" in svg, "图上打同一编号的标号"
    assert "#1 pcb-silk-over-pad WARN → R1" in svg, "角落列 finding id 与它点到的对象"
    # 没被点到的位号保持普通字重
    assert f'fill="{HIGHLIGHT}" font-weight="700">C2</text>' not in svg


def test_a_mark_whose_part_is_not_on_this_board_says_so():
    marks = [CanvasMark(rule_id="pcb-decap-distance", severity="WARN",
                        refs=("R1", "C99"), nets=("VCC",))]
    svg = render_board_svg(_small_board(), title="MISS", marks=marks)

    assert "（本板找不到：C99）" in svg
    assert "网：VCC" in svg


def test_a_board_with_no_finding_says_the_overlay_is_empty():
    svg = render_board_svg(_small_board(), title="COLD")

    assert "本板无 finding" in svg
    assert ">#1</text>" not in svg


def test_a_mark_can_highlight_a_whole_net():
    board = _small_board()
    board.tracks.append(
        TrackSegment(id="t1", net="VCC", layer_id=1, start=Point(150, 600),
                     end=Point(900, 600), width=20.0)
    )
    svg = render_board_svg(
        board, title="NET", marks=[CanvasMark(rule_id="pcb-voltage-spacing",
                                              severity="ERROR", nets=("VCC",))]
    )

    # 走线按高亮色描边（宽度也加粗了：默认 20 mil 是 stroke-width 20）
    hot_lines = re.findall(rf'<line [^>]*stroke="{HIGHLIGHT}" stroke-width="([\d.]+)"', svg)
    assert hot_lines, "网上的走线要进高亮色"
    assert "pcb-voltage-spacing ERROR" in svg


def test_marks_read_the_structured_target_and_its_counterpart():
    """位号来自 finding 自己的结构化字段，不靠从散文里猜（issue #13/#16）。"""
    finding = Finding(
        rule_id="pcb-silk-over-pad",
        severity="WARN",
        message="R22 的位号丝印压在 EC3 的焊盘上",
        level="L1-丝印",
        target=FindingTarget(component_ref="R22", counterpart_ref="EC3",
                             net_refs=["VCC"]),
    )
    marks = marks_from_findings([finding])

    assert len(marks) == 1
    assert marks[0].rule_id == "pcb-silk-over-pad"
    assert marks[0].refs == ("R22", "EC3")
    assert marks[0].nets == ("VCC",)


# ---------------------------------------------------------------------------
# 降级与落盘
# ---------------------------------------------------------------------------


def test_an_empty_board_renders_and_says_it_is_empty():
    svg = render_board_svg(BoardGeometry(), title="EMPTY")

    ET.fromstring(svg)
    assert "空板" in svg
    assert "本板：器件 0、焊盘 0" in svg


def test_write_canvases_returns_the_report_entry_and_writes_the_file(tmp_path):
    images = write_canvases(
        [("PCB1", _small_board())], out_dir=tmp_path,
        marks=[[CanvasMark(rule_id="pcb-silk-over-pad", refs=("R1",))]],
    )

    assert len(images) == 1
    image = images[0]
    assert image["board"] == "PCB1"
    assert image["file"] == "canvas-PCB1.svg"
    assert image["source"] == CANVAS_SOURCE
    assert image["kind"] == CANVAS_KIND
    assert image["findings"] == 1
    assert image["note"] == CANVAS_NOTE, "口径必须跟着图走"
    written = tmp_path / image["file"]
    assert written.is_file()
    assert image["bytes"] == len(written.read_bytes())


def test_a_board_title_with_a_separator_cannot_write_outside_out_dir(tmp_path):
    board = _small_board()
    images = write_canvases([("../../evil/PCB 1", board)], out_dir=tmp_path / "out")

    name = images[0]["file"]
    assert "/" not in name and "\\" not in name and ".." not in name
    assert name.startswith("canvas-") and name.endswith(".svg")
    assert (tmp_path / "out" / name).is_file()
    assert not (tmp_path / "evil").exists()


def test_canvas_file_name_keeps_chinese_and_ascii_titles():
    assert canvas_file_name("PCB1") == "canvas-PCB1.svg"
    assert canvas_file_name("主板 A") == "canvas-主板_A.svg"
    assert canvas_file_name("") == "canvas-board.svg"


def test_a_render_failure_becomes_a_row_and_a_note_not_an_exception(
    tmp_path, monkeypatch
):
    from boardwise.engines import canvasrender

    def boom(*_args, **_kwargs):
        raise RuntimeError("no room for a picture")

    monkeypatch.setattr(canvasrender, "render_board_svg", boom)
    notes: list[str] = []
    images = canvasrender.write_canvases(
        [("PCB1", _small_board()), ("PCB2", _small_board())],
        out_dir=tmp_path, notes=notes,
    )

    assert [image.get("error") for image in images] == [
        "RuntimeError: no room for a picture",
        "RuntimeError: no room for a picture",
    ]
    assert all(image["board"] in ("PCB1", "PCB2") for image in images)
    assert len(notes) == 2 and "渲染失败" in notes[0]
    assert not list(tmp_path.glob("canvas-*")), "失败不许留半个文件"


def test_the_caption_discloses_what_is_not_drawn():
    board = _small_board()
    board.tracks.append(
        TrackSegment(id="t_inner", net="VCC", layer_id=15, start=Point(0, 0),
                     end=Point(100, 0), width=10.0)
    )
    board.pours.append(
        PourShape(id="fill12", net="GND", layer_id=12, kind="fill",
                  points=[Point(0, 0), Point(100, 0), Point(100, 100)])
    )
    board.non_copper_shapes.append(
        PourShape(id="mask", net=None, layer_id=6, kind="poly",
                  points=[Point(0, 0), Point(50, 0), Point(50, 50)])
    )
    svg = render_board_svg(board, title="KINDS")

    assert "非表层走线 1" in svg
    assert "非表层铜区 1" in svg
    assert "未画的非铜多边形 1 个" in svg
    assert "阻焊" in svg, "口径那条差（阻焊开窗没建模）要在图上"


# ---------------------------------------------------------------------------
# 端到端：checkup --file
# ---------------------------------------------------------------------------


def test_checkup_file_writes_a_canvas_svg_and_names_it_in_the_report(tmp_path):
    out = tmp_path / "out"

    assert _cmd_checkup(_checkup_args(file=str(BOARD_FIXTURE), out=str(out))) in (0, 1, 3)

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    images = report["ai_slots"]["canvas_images"]
    assert len(images) == len(report["pcb_review"]["boards"]) >= 1
    image = images[0]
    assert image["board"] == report["pcb_review"]["boards"][0]["title"]
    assert image["file"] == f"canvas-{image['board']}.svg"
    assert image["source"] == "geometry-render"
    assert image["note"] == CANVAS_NOTE
    assert "阻焊" in image["note"]
    # 逐板的 finding 数＝该板自己的 findings 条数（合并进 findings[] 之前那份索引）
    assert image["findings"] == len(report["pcb_review"]["boards"][0]["findings"])
    svg = (out / image["file"]).read_text(encoding="utf-8")
    assert CANVAS_KIND in svg and "顶层 Top view" in svg
    assert image["bytes"] == len(svg.encode("utf-8"))
    # report.md 的链接与规范一致的相对名
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert f"[{image['board']}]({image['file']})" in markdown
    assert "几何渲染" in markdown


def test_the_offline_canvas_note_still_says_offline_when_there_is_no_board(tmp_path):
    """没有 PCB 文档的归档：图仍然一张都没有，说明里必须写明是**离线**的那条。"""
    out = tmp_path / "out"

    assert _cmd_checkup(
        _checkup_args(file=str(FIXTURES / "ch340_golden.epro2"), out=str(out))
    ) == 3

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["ai_slots"]["canvas_images"] == []
    assert "离线" in report["ai_slots"]["canvas_images_note"]
    assert not list(out.glob("canvas-*"))
