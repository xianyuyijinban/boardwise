"""离线几何渲染：`checkup --file` 每块板一张 ``canvas-<board>.svg``（189C）。

**它回答的问题，和它回答不了的问题。** 岳的实板反馈 ⑥：「R22 丝印压没压 EC3
焊盘」这类分歧，来回猜要很久，有张图三分钟就能对齐。离线档位（``checkup
--file``）此前不出任何图——`canvas_images` 一直是空列表，布局审美整节 skipped，
因为那条通道要连编辑器（``export.render``）。这个模块把**归档里已经解析出来的
几何**画成 SVG，于是没有编辑器也能有一张图。

口径写在图上、也写进 ``report.json``（:data:`CANVAS_NOTE`）：这是**几何渲染，
不是实物照片**。丝印压焊盘这类判定算的是**文字包围盒与焊盘相交**，没有建模
阻焊开窗裁切——「算出来压了」与实物没压可以同时成立。图不替规则下结论，它是给
**人**对照用的。

**坐标系**：``BoardGeometry`` 全部是 mil、**y 轴向上为正**（001 批实测，见
``docs/epru-format.md`` §4），SVG 的 y 向下——所以每张图都要 ``Y = max_y - y``，
漏掉这一步整块板会上下翻个个儿（任务书点名的第一坑）。

**只画什么**（不做 EDA 查看器）：板框、铺铜轮廓（半透明）、走线、焊盘、过孔、
丝印图元与丝印文字、器件本体轮廓与位号。两个视窗并排——左顶层、右底层，
**底层按 x 镜像**（板左↔右对调，上下方向与顶层一致，便于逐件对照）。配色**按层**
（不是每网一色：网名上百个，按层成本低且可复现），图例印在标题栏里。

**底层视窗里的文字也一起镜像**（字形：``rotate(a) scale(-1,1)``）。这不是装饰性选择：
文字与焊盘在同一套板面坐标里，规则量的是**文字包围盒**与焊盘相交——文字只镜像位置而
字形照正读的话，落墨范围会跑到锚点另一边，图就和规则说的对不上（实板上正是这种形状：
``pcb-silk-designator`` 报 R22 的位号丝印压在 EC3 的焊盘上，R22 的位号记录在
``BOT_SILK``）。镜不镜像的**字面**是正是反，取决于文件怎么存底层丝印，这里照抄不改写
（标题栏把这条口径写出来了）。

**finding 叠加**是这张图的用处所在：规则点到的东西（``target.component_ref`` /
``counterpart_ref`` / ``net_refs``）在本板上描边高亮并打 ``#n`` 标号，标题栏按
同样的编号列 ``#n 规则 id（严重度）→ 命中的对象``；找不到的对象**照实说找不到**
（一条 finding 可能点的是别的板/别的文档里的东西），不静默。

纯标准库，手写字符串拼 SVG：这条路径不能引入新依赖（与 ``engines/svgpreview``
同一条纪律——那张图存在的理由之一就是不需要任何图形库）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..core.geometry import BoardGeometry, PadGeometry, Point, PourShape

__all__ = [
    "CANVAS_KIND",
    "CANVAS_NOTE",
    "CanvasMark",
    "canvas_file_name",
    "marks_from_findings",
    "render_board_svg",
    "write_canvases",
]

#: 标识产物是什么——文件躺在盘上时它自己说得清。
CANVAS_KIND = "boardwise-canvas/1"

#: 口径。**每一条航线都带着它**（report.json 的每条 ``canvas_images[]`` 与图上标题栏
#: 各一份），因为这张图最容易被误读成「实物照片」或「规则的判决」。
CANVAS_NOTE = (
    "几何渲染（非实物照片）；丝印压焊盘类判定未建模阻焊开窗裁切，分歧以实物为准"
)

#: 离线档位 `canvas_images[]` 里 `source` 的取值：这张图是**几何画出来的**，
#: 与在线档位的 `export.render`（编辑器截图）不是同一个来源。
CANVAS_SOURCE = "geometry-render"

#: 版面（SVG 用户单位 = 像素）。mil 到像素的比例由 ``scale`` 给（默认 1:1）。
_MARGIN = 24.0
_PANEL_GAP = 40.0
_HEADER = 20.0
_LABEL_TOP = 14.0
_CAPTION_TOP = 16.0
_CAPTION_LINE = 15.0
_CAPTION_DESCENT = 8.0
_FONT_SIZE = 12.0
#: 图幅四周留的空白（mil）：板框贴着边不好看，也容易与视窗边框混。
_VIEW_PAD = 20.0
#: 丝印字号的兜底（mil）：记录里没给字号时用它，否则字会缩成不可见的一点。
_DEFAULT_FONT_SIZE = 24.0
#: 走线宽度的兜底像素：宽度读不出来（0）时画一根发丝，不假装知道它多宽。
_MIN_TRACK_PX = 0.8
#: **网**上的高亮画虚线、**器件/焊盘/丝印**上的画实线：一条 finding 点名的常常是
#: 一整条电源网（几十条走线加一大片铺铜），把它画成实心粗线会把半块板涂成高亮色，
#: 而两种主张本来就不是一件事——「这条网上有 finding」与「这颗件被点名」。
_NET_DASH = ' stroke-dasharray="7 4"'

_COLOURS = {
    "background": "#ffffff",
    "panel": "#fcfcfa",
    "frame": "#b6b6ae",
    "label": "#333333",
    "outline": "#111111",
    "top_copper": "#c0392b",
    "bottom_copper": "#1f6fb2",
    "inner_copper": "#7d3c98",
    "unknown_copper": "#9e9e9e",
    "top_silk": "#17804a",
    "bottom_silk": "#c17d0a",
    "body": "#6b7280",
    "hole": "#ffffff",
    "highlight": "#d81b60",
    "caption": "#222222",
    "grid": "#f0f0ec",
}


@dataclass(frozen=True)
class CanvasMark:
    """一条 finding 在这张图上的主张：哪条规则，要点亮什么。

    只带画图需要的东西（规则 id、严重度、要点亮的对象与网），不挟带 finding 的
    全文——图是给人对照的，正文在 report.json/report.md 里，两处不重复渲染同一段
    散文。``refs`` 是位号（器件/焊盘/丝印），``nets`` 是网名（走线/过孔/铜区）。
    """

    rule_id: str
    severity: str = ""
    refs: tuple[str, ...] = ()
    nets: tuple[str, ...] = ()


def marks_from_findings(findings: Iterable[Any]) -> list[CanvasMark]:
    """把规则写的 finding 读成画图用的标号，**用的就是下游读的那两个字段**。

    位号来自 ``engines.review.finding_refs``（结构化 ``target.component_ref`` 优先，
    没有才读散文——同一条读法 063 的分诊 key 也在用，图与分诊表不能各读各的），
    再加 ``target.counterpart_ref``（PCB 规则判的常常是**一对**：丝印压焊盘的两侧、
    去耦电容与它的 IC——只点亮一半的话「三分钟对齐」就对不齐）。
    """
    from .review import finding_refs

    marks: list[CanvasMark] = []
    for finding in findings:
        refs = list(finding_refs(finding))
        target = getattr(finding, "target", None)
        counterpart = str(getattr(target, "counterpart_ref", "") or "").strip()
        if counterpart and counterpart not in refs:
            refs.append(counterpart)
        nets: list[str] = []
        for net in getattr(target, "net_refs", None) or ():
            name = str(net or "").strip()
            if name and name not in nets:
                nets.append(name)
        marks.append(
            CanvasMark(
                rule_id=str(getattr(finding, "rule_id", "") or ""),
                severity=str(getattr(finding, "severity", "") or ""),
                refs=tuple(refs),
                nets=tuple(nets),
            )
        )
    return marks


def canvas_file_name(board_title: str) -> str:
    """``canvas-<board>.svg``，文件名里不带路径分隔符、不带 ``..``。

    板的标题来自文档自己的 ``META``（钉 4），可能带空格、斜杠、中文……一个带斜杠的
    标题会写到 ``--out`` 之外去，所以文件名的**不安全字符**在这里就换掉；标题本身
    原样写进 ``canvas_images[].board``，两处不混。
    """
    safe = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]+", "_", str(board_title or ""))
    safe = re.sub(r"\.{2,}", "_", safe).strip("._")
    return f"canvas-{safe or 'board'}.svg"


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Viewport:
    """一个视窗的坐标映射：**唯一**允许把 mil（y 向上）变成像素（y 向下）的地方。

    ``top`` 视窗原样；``bottom`` 视窗把 x 镜像（``max_x - x``），y 与顶层同向——
    于是两块视窗里同一个器件一上一下对齐，逐件对照不用转脖子。
    """

    view: str
    ox: float
    oy: float
    box: tuple[float, float, float, float]
    scale: float

    def x(self, value: float) -> float:
        span = (value - self.box[0]) if self.view == "top" else (self.box[2] - value)
        return self.ox + span * self.scale

    def y(self, value: float) -> float:
        return self.oy + (self.box[3] - value) * self.scale

    def px(self, value: float) -> float:
        return value * self.scale

    def rotate(self, angle: float) -> float:
        """板面角（度，y 向上、逆时针为正）→ SVG 的 ``rotate()`` 角（y 向下）。

        两者方向相反，所以是**取负**（顶层视窗用；底层视窗的角走
        :func:`_text_transform`，那里还要带镜像）。
        """
        return -float(angle)


def render_board_svg(
    board: BoardGeometry,
    *,
    title: str = "",
    marks: Sequence[CanvasMark] = (),
    scale: float = 1.0,
) -> str:
    """一块板的两个视窗 + 标题栏，一张 SVG 文档。

    ``marks`` 是本板 finding 的标号（:func:`marks_from_findings`）；空列表就是
    「本板没有 finding」，图上不开高亮、标题栏照写「无 finding 叠加」——**空与没画
    不是一回事**。

    两个视窗的一切（含文字字形）都是**同一套板面坐标的两种看法**：顶层原样、底层按 x
    镜像。文字跟着镜像是有意的——文字与焊盘同坐标，规则量的就是它们的相交，落墨范围
    必须和规则量的是同一块地方（见 :func:`_text_transform`）。镜像后文字读起来是正是
    反取决于文件怎么存底层丝印，标题栏写明这条口径，让人自己去编辑器核。
    """
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale!r}")
    marks = tuple(marks)
    box = _drawing_box(board)
    highlight = _Highlight(board, marks)

    panel_w = max(box[2] - box[0], 1.0) * scale
    panel_h = max(box[3] - box[1], 1.0) * scale
    left_x = _MARGIN
    right_x = _MARGIN + panel_w + _PANEL_GAP
    panel_y = _MARGIN + _HEADER
    #: 标题栏的行比小板宽得多，所以画布宽度取「两窗 + 边距」与一个下限的较大者：
    #: 这不是把图放大，是给说明文字留出不被裁掉的宽度（一块 100 mil 的合成小板上
    #: 说明文字本来就会比图宽）。
    width = max(_MARGIN * 2 + panel_w * 2 + _PANEL_GAP, 760.0)

    caption = _caption_lines(board, title, box, scale, marks, highlight)
    caption_h = _caption_height(len(caption))
    height = panel_y + panel_h + _MARGIN + caption_h

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="DejaVu Sans, Consolas, monospace" font-size="{_FONT_SIZE:g}">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" '
        f'fill="{_COLOURS["background"]}"/>',
    ]
    for view, ox in (("top", left_x), ("bottom", right_x)):
        viewport = _Viewport(view, ox, panel_y, box, scale)
        parts.append(
            f'<rect x="{ox:.2f}" y="{panel_y:.2f}" width="{panel_w:.2f}" '
            f'height="{panel_h:.2f}" fill="{_COLOURS["panel"]}" '
            f'stroke="{_COLOURS["frame"]}"/>'
        )
        parts.append(
            f'<text x="{ox:.2f}" y="{panel_y - 6:.2f}" fill="{_COLOURS["label"]}" '
            f'font-size="13">{escape(_panel_label(view))}</text>'
        )
        parts.extend(_panel(board, viewport, highlight))
    parts.extend(_caption(caption, panel_y + panel_h + _MARGIN))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_canvases(
    boards: Sequence[tuple[str, BoardGeometry]],
    *,
    out_dir: str | Path,
    marks: Sequence[Sequence[CanvasMark]] = (),
    notes: list[str] | None = None,
    scale: float = 1.0,
) -> list[dict]:
    """把每块板渲染进 ``out_dir``，返回 ``canvas_images[]`` 的条目列表。

    ``boards`` 是 ``(title, board)``，顺序与 ``pcb_review.boards[]`` 相同；
    ``marks`` 是同序的逐板标号（缺省即没有 finding 叠加）。

    **一块板渲染失败不带走其它板，也不带走报告**（任务书 §C 的降级要求）：失败的那
    块在列表里留一条 ``{board, error}`` 行、原因同时写进 ``notes``，其余照出。空板
    （一条几何都没有）不是异常，画出来是一张只有空框与说明的图——「这块板没有几何」
    本身就是要看见的事实。
    """
    out_path = Path(out_dir)
    images: list[dict] = []
    for index, (title, board) in enumerate(boards):
        board_marks = tuple(marks[index]) if index < len(marks) else ()
        name = canvas_file_name(title)
        try:
            svg = render_board_svg(board, title=title, marks=board_marks, scale=scale)
            out_path.mkdir(parents=True, exist_ok=True)
            # ``newline="\\n"``: without it Windows rewrites every line ending and the
            # ``bytes`` below (computed from the string) would not be the file's size.
            (out_path / name).write_text(svg, encoding="utf-8", newline="\n")
        except Exception as exc:  # noqa: BLE001 — 一条降级行，不是一个异常
            reason = f"{type(exc).__name__}: {exc}"
            images.append({"board": title, "source": CANVAS_SOURCE, "error": reason,
                           "note": CANVAS_NOTE})
            if notes is not None:
                notes.append(f"画布图：{title} 渲染失败（{reason}）：这一块没有图")
            continue
        images.append({
            "board": title,
            "page": title,
            "file": name,
            "source": CANVAS_SOURCE,
            "kind": CANVAS_KIND,
            "bytes": len(svg.encode("utf-8")),
            "findings": len(board_marks),
            "note": CANVAS_NOTE,
        })
    return images


def _panel_label(view: str) -> str:
    return "顶层 Top view" if view == "top" else "底层 Bottom view（x 镜像）"


# ---------------------------------------------------------------------------
# 一个视窗里的元素
# ---------------------------------------------------------------------------


def _panel(board: BoardGeometry, vp: _Viewport, highlight: "_Highlight") -> list[str]:
    """一个视窗的全部图元，**按下到上的绘制顺序**：铺铜 → 走线 → 焊盘/过孔 →
    丝印/本体 → 高亮 → 标号。顺序是有意的：丝印压焊盘这类分歧要看得见，丝印不能
    被铜盖住。"""
    parts: list[str] = []
    _pours(parts, board, vp, highlight)
    _tracks(parts, board, vp, highlight)
    _pads(parts, board, vp, highlight)
    _vias(parts, board, vp, highlight)
    _artwork(parts, board, vp, highlight)
    _texts(parts, board, vp, highlight)
    _outline(parts, board, vp)
    _markers(parts, board, vp, highlight)
    return parts


def _pours(parts, board, vp, highlight) -> None:
    for pour in board.pours:
        view = _pour_view(pour)
        if view != vp.view and view != "both":
            continue
        colour = _copper_colour(_pour_layer(pour), vp.view)
        path = _rings_path(pour, vp)
        if not path:
            continue
        hot = highlight.pour(pour)
        stroke = _COLOURS["highlight"] if hot else colour
        width = 2.0 if hot else 0.6
        parts.append(
            f'<path d="{path}" fill="{colour}" fill-opacity="0.22" '
            f'fill-rule="evenodd" stroke="{stroke}" stroke-width="{width:g}"'
            f'{_NET_DASH if hot else ""}/>'
        )


def _tracks(parts, board, vp, highlight) -> None:
    for track in board.tracks:
        view = _copper_view(track.layer_id)
        if view == "unknown":
            view = "both"
        if view != vp.view and view != "both":
            continue
        hot = highlight.track(track)
        colour = _COLOURS["highlight"] if hot else _copper_colour(track.layer_id, vp.view)
        width = max(vp.px(track.width), _MIN_TRACK_PX)
        if hot:
            width = max(width + 1.5, 2.0)
        parts.append(
            f'<line x1="{vp.x(track.start.x):.2f}" y1="{vp.y(track.start.y):.2f}" '
            f'x2="{vp.x(track.end.x):.2f}" y2="{vp.y(track.end.y):.2f}" '
            f'stroke="{colour}" stroke-width="{width:.2f}" stroke-linecap="round"'
            f'{_NET_DASH if hot else ""}/>'
        )


def _pads(parts, board, vp, highlight) -> None:
    for pad in board.pads:
        views = _pad_views(pad)
        if views is not None and vp.view not in views:
            continue
        # 层读不出的焊盘（``views is None``）两窗都画、画成灰色：把「我读不出它在
        # 哪一层」画成「它在顶层」是假读数。
        colour = _copper_colour(None if views is None else _pad_layer(vp.view), vp.view)
        hot = highlight.pad(pad)
        _pad_shape(parts, pad, vp, colour, hot)


def _pad_shape(parts, pad: PadGeometry, vp, colour: str, hot: bool) -> None:
    """一个焊盘：外形 + 孔。孔画成背景色，于是通孔盘一眼与贴片盘分开。"""
    cx, cy = vp.x(pad.x), vp.y(pad.y)
    w, h = max(float(pad.width), 0.0) * vp.scale, max(float(pad.height), 0.0) * vp.scale
    if w <= 0 or h <= 0:
        # 尺寸读不出来：画个点，别假装它有多大。
        r = 1.2
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:g}" fill="none" '
            f'stroke="{colour}" stroke-width="1"/>'
        )
        return
    stroke = _COLOURS["highlight"] if hot else colour
    stroke_width = 1.8 if hot else 0.5
    shape = str(pad.shape or "").upper()
    transform = (
        f' transform="rotate({vp.rotate(pad.angle):.3f} {cx:.2f} {cy:.2f})"'
        if float(pad.angle or 0.0) % 360
        else ""
    )
    if shape == "ELLIPSE":
        body = (f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{w / 2:.2f}" '
                f'ry="{h / 2:.2f}"')
    else:
        radius = min(w, h) / 2.0 if shape == "OVAL" else 0.0
        body = (f'<rect x="{cx - w / 2:.2f}" y="{cy - h / 2:.2f}" width="{w:.2f}" '
                f'height="{h:.2f}" rx="{radius:.2f}"')
    parts.append(f'{body} fill="{colour}" stroke="{stroke}" '
                 f'stroke-width="{stroke_width:g}"{transform}/>')
    hole = pad.hole_width if pad.hole_width is not None else pad.hole_diameter
    if hole:
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{max(float(hole), 0.0) * vp.scale / 2:.2f}" '
            f'fill="{_COLOURS["hole"]}"{transform}/>'
        )


def _vias(parts, board, vp, highlight) -> None:
    for via in board.vias:
        hot = highlight.via(via)
        colour = _COLOURS["highlight"] if hot else _copper_colour(1, vp.view)
        r = max(float(via.via_diameter or 0.0), 0.0) * vp.scale / 2.0
        if r <= 0:
            r = 1.5
        parts.append(
            f'<circle cx="{vp.x(via.x):.2f}" cy="{vp.y(via.y):.2f}" r="{r:.2f}" '
            f'fill="{colour}" stroke="{_COLOURS["highlight"] if hot else colour}" '
            f'stroke-width="{2.0 if hot else 0.4:g}"{_NET_DASH if hot else ""}/>'
        )
        hole = max(float(via.hole_diameter or 0.0), 0.0) * vp.scale / 2.0
        if hole > 0:
            parts.append(
                f'<circle cx="{vp.x(via.x):.2f}" cy="{vp.y(via.y):.2f}" r="{hole:.2f}" '
                f'fill="{_COLOURS["hole"]}"/>'
            )


def _artwork(parts, board, vp, highlight) -> None:
    """器件本体轮廓与标记（151/152 的 ``silk_shapes``）：只画属本视窗那一面的。

    画的是**封装文档里的图元**（板框层 48 的本体、49 的极性点），不是我们编的矩形；
    没有本体轮廓的器件退回它自己焊盘的包围盒，并且**画成虚线**——那是推导出来的框，
    不是文件画的框，两者不该长得一样。
    """
    bodies: set[str] = set()
    for shape in board.silk_shapes:
        face = _artwork_face(shape)
        if face is not None and face != vp.view:
            continue
        kind = str(getattr(shape, "layer_kind", "") or "")
        if kind not in ("TOP_SILK", "BOT_SILK", "COMPONENT_SHAPE", "COMPONENT_MARKING"):
            continue
        colour = _silk_colour(kind)
        hot = highlight.artwork(shape)
        points = [(vp.x(p.x), vp.y(p.y)) for p in shape.points]
        radius = float(getattr(shape, "radius", 0.0) or 0.0)
        if radius > 0 and points:
            parts.append(
                f'<circle cx="{points[0][0]:.2f}" cy="{points[0][1]:.2f}" '
                f'r="{vp.px(radius):.2f}" fill="none" '
                f'stroke="{_COLOURS["highlight"] if hot else colour}" '
                f'stroke-width="{2.0 if hot else max(vp.px(float(shape.width or 0.0)), 0.6):.2f}"/>'
            )
            continue
        if len(points) < 2:
            continue
        closed = _shape_closed(shape)
        points_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        # 填充图元半透明（0.35）：丝印油墨在实物上是盖住的，但画成不透明就把底下
        # 的焊盘糊掉了——「丝印压没压焊盘」正是要看两者**同时**在不在。
        tag = "polygon" if closed else "polyline"
        parts.append(
            f'<{tag} points="{points_text}" fill="{colour if shape.filled else "none"}" '
            f'fill-opacity="{0.35 if shape.filled else 0:g}" '
            f'stroke="{_COLOURS["highlight"] if hot else colour}" '
            f'stroke-width="{2.0 if hot else max(vp.px(float(shape.width or 0.0)), 0.6):.2f}"/>'
        )
        if kind == "COMPONENT_SHAPE":
            bodies.add(str(shape.component or ""))

    for component in board.components:
        designator = str(component.designator or "")
        if not designator or designator in bodies:
            continue
        if int(component.layer_id or 1) != (1 if vp.view == "top" else 2):
            continue
        box = _component_pad_box(board, designator)
        if box is None:
            continue
        hot = highlight.ref(designator)
        parts.append(
            f'<rect x="{vp.x(box[0]):.2f}" y="{vp.y(box[3]):.2f}" '
            f'width="{(box[2] - box[0]) * vp.scale:.2f}" '
            f'height="{(box[3] - box[1]) * vp.scale:.2f}" fill="none" '
            f'stroke="{_COLOURS["highlight"] if hot else _COLOURS["body"]}" '
            f'stroke-width="{2.0 if hot else 0.7:g}" stroke-dasharray="4 3"/>'
        )


def _texts(parts, board, vp, highlight) -> None:
    """丝印文字（位号 + 封装印字 + 板上自由文字）。

    **底层视窗里的文字是整个图形按 x 镜像的**（``rotate(a) scale(-1,1)``，见
    :func:`_text_transform`）：文字与焊盘在同一套坐标里，规则量的是文字包围盒与焊盘
    相交——文字跑反方向，图就和规则说的对不上（「R22 丝印压没压 EC3 焊盘」正是这种
    对不上）。把字形一起镜像之后，落墨范围与文件一致；至于读起来是正是反，取决于
    文件自己怎么存底层丝印（照抄，不猜）。
    """
    for text in board.silk_texts:
        kind = str(getattr(text, "layer_kind", "") or "")
        if kind not in ("TOP_SILK", "BOT_SILK"):
            continue
        if (1 if kind == "TOP_SILK" else 2) != (1 if vp.view == "top" else 2):
            continue
        body = str(text.text or "")
        if not body:
            continue
        size = float(text.font_size or 0.0) or _DEFAULT_FONT_SIZE
        hot = highlight.text(text)
        colour = _COLOURS["highlight"] if hot else _silk_colour(kind)
        x, y = vp.x(text.x), vp.y(text.y)
        anchor = _text_anchor(str(text.origin or ""))
        # 底层的 transform 自带 translate(锚点)，属性位置必须写 0,0：属性坐标在
        # transform 之内解释，写成 x,y 会先被 scale(-1,1) 翻成 -x 再平移，锚点落到
        # (0, 2y)——整层底面位号被甩出视窗（189C 落账时漏掉的洞）。
        ax, ay = (0.0, 0.0) if vp.view == "bottom" else (x, y)
        parts.append(
            f'<text x="{ax:.2f}" y="{ay:.2f}"{_text_transform(text, vp, x, y)} '
            f'font-size="{vp.px(size):.2f}" fill="{colour}" '
            f'font-weight="{700 if hot else 400}"{anchor}>{escape(body)}</text>'
        )


def _text_transform(text, vp: _Viewport, x: float, y: float) -> str:
    """一段文字的 ``transform`` 属性（空串＝不需要）。

    顶层视窗：板面逆时针角 ``a`` 在屏幕上成了 ``-a``（y 轴翻转），字形不镜像——这就是
    文件里那条墨迹的样子。

    底层视窗：**整块图形是 x 镜像的**，所以文字的落墨范围也要镜像，否则「文字在哪」
    与焊盘对不上。写成 ``rotate(a) scale(-1,1)`` 等价于整个平面按 x 镜像（推导：屏幕
    偏移应为 ``(-u·cos a + w·sin a, -u·sin a - w·cos a)``，``u`` 是字向、``w`` 是字高，
    而 ``scale(-1,1)`` 后再 ``rotate(a)`` 给出的正是这个）。读起来是正是反，取决于文件
    怎么存底层丝印，这里照抄不改写。
    """
    angle = float(getattr(text, "angle", 0.0) or 0.0) % 360
    if vp.view == "bottom":
        # 顺序要紧：SVG 的 transform 列表**从右往左**作用，所以是
        # 「先 scale（字形镜像）→ 再绕自己的锚点 rotate → 最后搬到锚点」，
        # 写成 rotate 在最前会把锚点也绕原点转走。
        parts = [f"translate({x:.2f} {y:.2f})"]
        if angle:
            parts.append(f"rotate({angle:.3f})")
        parts.append("scale(-1,1)")
        return ' transform="' + " ".join(parts) + '"'
    if angle:
        return f' transform="rotate({vp.rotate(angle):.3f} {x:.2f} {y:.2f})"'
    return ""


def _outline(parts, board, vp) -> None:
    outline = getattr(board, "outline", None)
    if outline is None or len(outline.points) < 2:
        return
    points = " ".join(f"{vp.x(p.x):.2f},{vp.y(p.y):.2f}" for p in outline.points)
    if getattr(outline, "closed", False):
        parts.append(
            f'<polygon points="{points}" fill="none" '
            f'stroke="{_COLOURS["outline"]}" stroke-width="2"/>'
        )
    else:
        # 未闭环的框照画（画成虚线）：它是文件里真实存在的记录，只是不可当板框用。
        parts.append(
            f'<polyline points="{points}" fill="none" '
            f'stroke="{_COLOURS["outline"]}" stroke-width="2" stroke-dasharray="6 4"/>'
        )


def _markers(parts, board, vp, highlight) -> None:
    """高亮对象的 ``#n`` 标号：图上一眼找到，标题栏按同一编号解释。"""
    for number, label, x, y in highlight.marker_points(board, vp):
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7" fill="none" '
            f'stroke="{_COLOURS["highlight"]}" stroke-width="1.4"/>'
        )
        parts.append(
            f'<text x="{x + 9:.2f}" y="{y - 3:.2f}" font-size="11" '
            f'fill="{_COLOURS["highlight"]}" font-weight="700">#{number}{escape(label)}</text>'
        )


# ---------------------------------------------------------------------------
# 高亮：finding 点到的东西
# ---------------------------------------------------------------------------


class _Highlight:
    """本板 finding 的标号读成「点亮哪些对象」，并在画的过程中回答查询。

    一条 finding 点的对象可能**不在这块板上**（规则判的是别的文档，或位号只存在于
    schematic 视图里）。找不到就照实写出来（:meth:`missing_refs`，标题栏用），静默
    少画一个标记，读图的人会以为规则没点它。
    """

    def __init__(self, board: BoardGeometry, marks: Sequence[CanvasMark]) -> None:
        self.board = board
        self.marks = tuple(marks)
        self._refs: dict[str, list[int]] = {}
        self._nets: dict[str, list[int]] = {}
        for index, mark in enumerate(marks, start=1):
            for ref in mark.refs:
                self._refs.setdefault(ref, []).append(index)
            for net in mark.nets:
                self._nets.setdefault(net, []).append(index)
        self._designators = {str(c.designator or "") for c in board.components}

    # -- 查询 ---------------------------------------------------------

    def ref(self, designator: str) -> bool:
        return bool(designator) and designator in self._refs

    def numbers_for_ref(self, designator: str) -> list[int]:
        return self._refs.get(designator, [])

    def missing_refs(self) -> list[str]:
        """点到的位号里，本板没有的那几个（画不出高亮的）。"""
        return [ref for ref in self._refs if ref not in self._designators]

    def pad(self, pad: PadGeometry) -> bool:
        return self.ref(str(pad.component or ""))

    def track(self, track: Any) -> bool:
        return self.ref(str(track.net or "")) or self.net(str(track.net or ""))

    def via(self, via: Any) -> bool:
        return self.net(str(via.net or ""))

    def net(self, name: str) -> bool:
        return bool(name) and name in self._nets

    def pour(self, pour: Any) -> bool:
        return self.net(str(pour.net or ""))

    def artwork(self, shape: Any) -> bool:
        return self.ref(str(shape.component or ""))

    def text(self, text: Any) -> bool:
        return self.ref(str(text.text or "")) or self.ref(str(text.component or ""))

    # -- 标号落点 -----------------------------------------------------

    def marker_points(self, board: BoardGeometry, vp: _Viewport):
        """``(编号, 后缀, x, y)``：每个高亮对象一个标号，落在它的中心。

        器件的标号落在**器件原点**（或它焊盘包围盒的中心），网的标号落在该网在本板上
        铜的包围盒中心——一个网几十条走线时，逐个打标号只会糊成一团。

        标号只画在**对象所在的视窗**里（器件自己的面说了算；网跨两面，两窗都画过，
        两窗都给标号）。
        """
        out: list[tuple[int, str, float, float]] = []
        for index, mark in enumerate(self.marks, start=1):
            for ref in mark.refs:
                if ref not in self._designators:
                    continue
                component = board.component(ref)
                if component is not None:
                    face = 1 if vp.view == "top" else 2
                    if int(component.layer_id or 1) != face:
                        continue
                    box = (component.x, component.y, component.x, component.y)
                else:
                    box = _component_pad_box(board, ref)
                if box is None:
                    continue
                out.append((
                    index, "",
                    vp.x((box[0] + box[2]) / 2), vp.y((box[1] + box[3]) / 2),
                ))
            for net in mark.nets:
                box = _net_box(board, net)
                if box is None:
                    continue
                out.append((
                    index, "",
                    vp.x((box[0] + box[2]) / 2), vp.y((box[1] + box[3]) / 2),
                ))
        return out


# ---------------------------------------------------------------------------
# 标题栏
# ---------------------------------------------------------------------------


def _caption_lines(
    board: BoardGeometry,
    title: str,
    box: tuple[float, float, float, float],
    scale: float,
    marks: Sequence[CanvasMark],
    highlight: _Highlight,
) -> list[str]:
    """标题栏的每一行：这是什么、画了什么、**没画什么**、finding 编号。

    「没画什么」是这张图的诚实所在：内层铜、层读不出的铜区、非铜图元都在这里点名，
    免得读者把「图上没有」读成「板上没有」。

    尺寸**只报 mil**：`test_coordinate_guards` 钉死了「engines 里不做 mil↔mm 换算」
    （换算是解析器与 `canvas_pin_offsets` 的边界），而这张图的用户单位就是 mil
    （``scale=1`` 时 1 px = 1 mil）。mm 读数归报告，不归这张图。
    """
    lines = [
        f"{CANVAS_KIND}  board {title or '(未命名)'}  "
        f"{box[2] - box[0]:.0f} x {box[3] - box[1]:.0f} mil  "
        f"(1 px = {1 / scale:g} mil)  scale {scale:g}",
        "图层配色：板框黑；顶层铜 " + _COLOURS["top_copper"] + "、底层铜 "
        + _COLOURS["bottom_copper"] + "（铺铜半透明）；顶层丝印 " + _COLOURS["top_silk"]
        + "、底层丝印 " + _COLOURS["bottom_silk"] + "；层读不出的铜 "
        + _COLOURS["unknown_copper"] + "；finding 高亮 " + _COLOURS["highlight"],
        f"本板：器件 {len(board.components)}、焊盘 {len(board.pads)}、"
        f"走线 {len(board.tracks)}、过孔 {len(board.vias)}、铜区 {len(board.pours)}、"
        f"丝印图元 {len(board.silk_shapes)}、丝印文字 {len(board.silk_texts)}、"
        f"网 {len(board.nets)}",
        "finding 高亮：实线＝被点名的器件/焊盘/丝印，虚线＝被点名的**网**上的铜；"
        f"颜色 {_COLOURS['highlight']}，编号与下面的清单一一对应",
        "口径：" + CANVAS_NOTE,
        "底层视窗：位置与字形都按 x 镜像（板左↔右）——与规则量丝印/焊盘用的那套板面"
        "坐标一致，文字落墨范围才和焊盘对得上；因此底层丝印文字看上去可能是反的，"
        "本图不替文件改写文字方向（正反以编辑器底层视图为准）",
    ]
    lines.extend(_undrawn_lines(board))
    if marks:
        for index, mark in enumerate(marks, start=1):
            lines.append(_mark_line(index, mark, board))
    else:
        lines.append("finding 叠加：本板无 finding（图上不亮任何对象）")
    return lines


def _mark_line(index: int, mark: CanvasMark, board: BoardGeometry) -> str:
    """标题栏里的一行 finding：编号（图上的 ``#n``）、规则、点到的对象。

    点到的位号**本板没有**时照实写「本板找不到」——那正是要看见的事（规则点的是别的
    文档，或位号只在原理图视图里），画空了不说，读图的人会以为规则没点它。
    """
    severity = f" {mark.severity}" if mark.severity else ""
    refs = "、".join(mark.refs) or "(未点名对象)"
    parts = [f"#{index} {mark.rule_id}{severity} → {refs}"]
    missing = [ref for ref in mark.refs if board.component(ref) is None]
    if missing:
        parts.append("（本板找不到：" + "、".join(missing) + "）")
    if mark.nets:
        parts.append("网：" + "、".join(mark.nets))
    return "  ".join(parts)


def _undrawn_lines(board: BoardGeometry) -> list[str]:
    """没画进图里的东西，逐类点名（数出来的，不是估的）。"""
    lines: list[str] = []
    inner_tracks = sum(1 for t in board.tracks if _copper_view(t.layer_id) == "inner")
    inner_pours = sum(1 for p in board.pours if _copper_view(_pour_layer(p)) == "inner")
    inner_pads = sum(1 for p in board.pads if _pad_views(p) == ("inner",))
    unknown_pours = sum(1 for p in board.pours if _pour_layer(p) is None)
    unknown_pads = sum(1 for p in board.pads if _pad_views(p) is None)
    unknown_tracks = sum(1 for t in board.tracks if _copper_view(t.layer_id) == "unknown")
    skipped: dict[str, int] = {}
    for shape in board.silk_shapes:
        kind = str(getattr(shape, "layer_kind", "") or "(层读不出)")
        if kind not in ("TOP_SILK", "BOT_SILK", "COMPONENT_SHAPE", "COMPONENT_MARKING"):
            skipped[kind] = skipped.get(kind, 0) + 1
    if inner_tracks or inner_pours or inner_pads:
        lines.append(
            f"未画（本图只画顶层/底层两个视窗）：非表层走线 {inner_tracks}、"
            f"非表层铜区 {inner_pours}（内层与 Multi 层都算在内）、只在内层的焊盘 {inner_pads}"
        )
    if unknown_pours or unknown_pads or unknown_tracks:
        lines.append(
            f"层读不出的铜（画成灰色、两窗都画）：铜区 {unknown_pours}、焊盘 {unknown_pads}、"
            f"走线 {unknown_tracks}"
            "（POURED 没有父 POUR 时层号读不出，见 core.geometry.PourShape）"
        )
    if skipped:
        named = "、".join(f"{kind} {count}" for kind, count in sorted(skipped.items()))
        lines.append(f"未画的非铜图元（只画丝印 3/4、本体 48、标记 49）：{named}")
    if board.non_copper_shapes:
        lines.append(
            f"未画的非铜多边形 {len(board.non_copper_shapes)} 个"
            "（阻焊开窗等——本图不画阻焊，这也是「丝印算出来压了、实物没压」的那个差）"
        )
    if board.prohibit_regions:
        lines.append(f"未画的禁布区 {len(board.prohibit_regions)} 个")
    if not board.components and not board.pads and not board.tracks:
        lines.append("本板没有可画的几何（空板）：图上的空框是「什么都没有」，不是渲染失败")
    return lines


def _caption(lines: Sequence[str], top: float) -> list[str]:
    out: list[str] = []
    for index, line in enumerate(lines):
        out.append(
            f'<text x="8" y="{top + _CAPTION_TOP + index * _CAPTION_LINE:.2f}" '
            f'fill="{_COLOURS["caption"]}" font-size="12">{escape(line)}</text>'
        )
    return out


def _caption_height(count: int) -> float:
    return _CAPTION_TOP + max(count - 1, 0) * _CAPTION_LINE + _CAPTION_DESCENT


# ---------------------------------------------------------------------------
# 几何小工具（全部纯读；视图口径集中在这里）
# ---------------------------------------------------------------------------


def _copper_view(layer_id: int | None) -> str:
    """一层铜落在哪个视窗：``top`` / ``bottom`` / ``both`` / ``inner`` / ``unknown``。"""
    if layer_id is None:
        return "unknown"
    if layer_id in (1, 2):
        return "top" if layer_id == 1 else "bottom"
    return "inner"


def _copper_colour(layer_id: int | None, view: str) -> str:
    kind = _copper_view(layer_id)
    if kind == "unknown":
        return _COLOURS["unknown_copper"]
    if kind == "inner":
        return _COLOURS["inner_copper"]
    return _COLOURS["top_copper"] if view == "top" else _COLOURS["bottom_copper"]


def _silk_colour(layer_kind: str) -> str:
    """丝印/本体图元的颜色：**按层**（顶层丝印、底层丝印、本体与标记各一色）。

    配色按层而不是按网：这块板上百个网，一网一色既读不出信息也画不出图例；
    层只有几个，颜色本身就是「这是哪一面」的读数。
    """
    if layer_kind == "BOT_SILK":
        return _COLOURS["bottom_silk"]
    if layer_kind == "TOP_SILK":
        return _COLOURS["top_silk"]
    return _COLOURS["body"]


def _pour_layer(pour: PourShape) -> int | None:
    return getattr(pour, "layer_id", None)


def _pour_view(pour: PourShape) -> str:
    """铜区落哪个视窗；层读不出的（``None``）**两窗都画**并画成灰的。"""
    kind = _copper_view(_pour_layer(pour))
    return "both" if kind == "unknown" else kind


def _pad_views(pad: PadGeometry) -> tuple[str, ...] | None:
    """焊盘出现在哪些视窗，或 ``None``（层读不出）。

    读的是 :attr:`PadGeometry.effective_layer_ids`——**铜实际在哪一层**（127b）。
    没人读过的焊盘（合成板、手写的）退回封装自己的层号：那是 127b 之前的旧读法，
    这里用它只是为了让手写的板也画得出来，读不出就 ``None``、画成灰色。
    """
    layers = pad.effective_layer_ids
    if layers is None:
        foot = pad.footprint_layer_id
        if foot is None:
            return None
        layers = [1, 2] if foot == 12 else [foot]
    views: list[str] = []
    for layer in layers:
        kind = _copper_view(layer)
        if kind in ("top", "bottom") and kind not in views:
            views.append(kind)
    if views:
        return tuple(views)
    return ("inner",) if layers else None


def _pad_layer(view: str) -> int:
    """视窗 → 该视窗的那一层铜（1 顶 / 2 底），只用于取配色。"""
    return 1 if view == "top" else 2


def _artwork_face(shape: Any) -> str | None:
    """图元的物理面：记录自己的 ``face``，否则按层名读。"""
    face = getattr(shape, "face", None)
    if face in (1, 2):
        return "top" if face == 1 else "bottom"
    kind = str(getattr(shape, "layer_kind", "") or "")
    if kind == "TOP_SILK":
        return "top"
    if kind == "BOT_SILK":
        return "bottom"
    return None


def _shape_closed(shape: Any) -> bool:
    """闭合图元画 ``polygon``，开放图元画 ``polyline``。

    ``kind == "fill"`` 是编辑器存出来的填充轮廓（必闭合）；``poly`` 的闭合只按首尾
    点是否重合读——不重合作闭合是编出来的边，会把「这个框没画完」盖掉。
    """
    if str(getattr(shape, "kind", "") or "") == "fill":
        return True
    points = getattr(shape, "points", None) or []
    if len(points) < 3:
        return False
    return bool(
        abs(points[0].x - points[-1].x) < 1e-6 and abs(points[0].y - points[-1].y) < 1e-6
    )


def _rings_path(pour: PourShape, vp: _Viewport) -> str:
    """铜区的 ``d``：给了孔洞环就用 ``evenodd`` 挖出来，只有轮廓就画轮廓。"""
    rings = [ring for ring in (getattr(pour, "rings", None) or []) if len(ring) >= 3]
    if not rings:
        rings = [pour.points] if len(pour.points) >= 3 else []
    pieces: list[str] = []
    for ring in rings:
        points = [(vp.x(p.x), vp.y(p.y)) for p in ring]
        pieces.append(
            "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points) + " Z"
        )
    return " ".join(pieces)


def _component_pad_box(
    board: BoardGeometry, designator: str
) -> tuple[float, float, float, float] | None:
    pads = [p for p in board.pads if p.component == designator]
    if not pads:
        return None
    xs = [p.x for p in pads]
    ys = [p.y for p in pads]
    return (min(xs), min(ys), max(xs), max(ys))


def _net_box(board: BoardGeometry, net: str) -> tuple[float, float, float, float] | None:
    geometry = board.net(net)
    points: list[Point] = [p.center for p in geometry.pads]
    points += [v.center for v in geometry.vias]
    for track in geometry.tracks:
        points += [track.start, track.end]
    for pour in geometry.pours:
        points += list(pour.points)
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _text_anchor(origin: str) -> str:
    """记录里的 ``origin`` → SVG 的 ``text-anchor``。

    只有水平那一半映射得过来：``*_BOTTOM`` 的**竖直**语义已经被画法本身表达了——
    SVG 的 ``y`` 就是基线，字身在它上方；而板坐标系 y 向上，``LEFT_BOTTOM`` 的字身
    同样在锚点上方。两边的约定一致，所以不需要额外的 baseline 属性。
    """
    upper = origin.upper()
    if "RIGHT" in upper:
        return ' text-anchor="end"'
    if "CENTER" in upper or "MIDDLE" in upper:
        return ' text-anchor="middle"'
    return ""


def _drawing_box(board: BoardGeometry) -> tuple[float, float, float, float]:
    """图幅：**所有画得出来的几何的并集**（板框优先当基准，但不裁掉板外的东西）。

    刻意用并集而不是板框的包围盒：``pcb-component-off-board`` 那类 finding 点的正是
    板外的东西，按板框裁掉就等于把要看的证据裁掉了。
    """
    xs: list[float] = []
    ys: list[float] = []
    outline = getattr(board, "outline", None)
    if outline is not None:
        xs += [p.x for p in outline.points]
        ys += [p.y for p in outline.points]
    for pad in board.pads:
        half = max(float(pad.width or 0.0), float(pad.height or 0.0)) / 2.0
        xs += [pad.x - half, pad.x + half]
        ys += [pad.y - half, pad.y + half]
    for via in board.vias:
        r = max(float(via.via_diameter or 0.0), 0.0) / 2.0
        xs += [via.x - r, via.x + r]
        ys += [via.y - r, via.y + r]
    for track in board.tracks:
        xs += [track.start.x, track.end.x]
        ys += [track.start.y, track.end.y]
    for pour in board.pours:
        xs += [p.x for p in pour.points]
        ys += [p.y for p in pour.points]
    for shape in board.silk_shapes:
        radius = float(getattr(shape, "radius", 0.0) or 0.0)
        for point in shape.points:
            xs += [point.x - radius, point.x + radius]
            ys += [point.y - radius, point.y + radius]
    for text in board.silk_texts:
        xs.append(text.x)
        ys.append(text.y)
    if not xs or not ys:
        return (0.0, 0.0, 1.0, 1.0)
    return (
        min(xs) - _VIEW_PAD,
        min(ys) - _VIEW_PAD,
        max(xs) + _VIEW_PAD,
        max(ys) + _VIEW_PAD,
    )
