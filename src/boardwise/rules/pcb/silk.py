"""丝印：位号可读、不压焊盘、方向一致（任务 152，E 阶段第二棒 · 规则族 B）。

路线图（``tasks/122-pcb-review-roadmap.md`` 第三步第 4 条）：「丝印：位号可读、
不压焊盘、方向一致」；通用层第 9 项 DFM 里也点名「丝印压焊盘、极性标记」。

**数据形态先实测清楚（这是本规则的地基，也是它和 151 最大的不同）**
=================================================================

板上要印的位号**不在 PCB 文档里以图形形式存在**，它是一条 **``ATTR`` 记录**：

.. code-block:: jsonc

   {"type":"ATTR", "id":"…", "parentId":"<COMPONENT id>"}||
   {"key":"Designator", "value":"C1", "layerId":3, "x":4455, "y":-1165,
    "angle":810, "fontSize":45, "strokeWidth":6, "origin":"LEFT_BOTTOM",
    "valueVisible":true, "mirror":false}

也就是说**位号文字自己带着坐标、角度、字号、层与「显示与否」**，与它命名的那颗
器件通过 ``parentId`` 相连。实测三块验收板 + llc 夹具：

===================  ===========  ==============================================
板                   位号记录数    与 COMPONENT 数
===================  ============  =============================================
毕设FOC 1.0.0 PCB1   122           122（一一对应）
毕设FOC 1.0.0 PCB2   10            10
毕设FOC 1.1.0 PCB1   105           105
ROBOT ctrl FOC PCB1  50            49（**多一条**：parentId 不指向本板的任何
                                    COMPONENT，见 ``source="designator-unparented"``）
===================  ============  =============================================

``angle`` 是**度**，与 :meth:`ComponentPlacement.transform` 同一套约定（y 向上、
正角逆时针），两边的旋转可以逐字比较。文件里的原始值会累积整圈（实测 810 /
1710 / 2250 = 90°/270°/90°），所以解析器做了 ``mod 360`` 并把原值留在
``stored_angle``——**不约化的数字不是方向**。

字号 ``fontSize`` 实测全是 45 mil（板上的位号统一 1.143 mm），``origin`` 全是
``LEFT_BOTTOM``。

**宽度两态：实测优先、估算降级（任务 172，岳 2026-10-11 裁）**
=============================================================

``.epru`` 不带字形宽度，所以**离线**只有一条路：按「字符数 × 字宽比 × 字号」估。
本规则的做法见 :data:`ADVANCE_BAND`：**用一条带（最窄 0.4 / 常用 0.6 / 最宽 0.8）
量三次**，只有**在最窄的那一档就已经压上**才报 WARN（那是无论字形怎么设计都成立
的压焊盘）；只有宽档才压上的降为 INFO 测量行。这是任务书「阈值没谱的就出测量行
（INFO），别编阈值」的落点。

**岳 2026-10-11 裁：宽度要实测，测不到就明说降级，不许拿估算当实测。** 于是本规则
多了第二种宽度来源：

* :data:`MEASURED_WIDTH` —— 宿主给的 primitive **bbox**（EasyEDA Pro 的
  ``getPrimitivesBBox``，参考 easyeda-agent 的 ``pcbSilkAlign``：
  ``eda.pcb_Primitive.getPrimitivesBBox([attrId])`` 量每条位号 ATTR）。这时宽度是
  **读数**，一整条带都不需要，一次相交判定就够；
* :data:`ESTIMATED_WIDTH` —— 上面那条带。**每条终结于估算数字的 evidence 都必须
  出现「估算值」三个字**，就是这一条把两态钉开：报告里不允许出现一个看起来像读数
  的估算数字。

实测盒是宿主给的**轴对齐** ink 盒（``minX/minY/maxX/maxY``），所以 0°/90°/180°/
270° 的位号上它与文字盒等价，而**斜置**位号上它是外接矩形（比字大）——这一条写进
evidence，不藏起来。谁给实测盒不归本规则管：:class:`SilkDesignator` 收一个
``measured`` 映射，键是 ``(板名, 位号文字)``，值是四角或 ``(minX, minY, maxX,
maxY)``——**按板名分键是必须的**，同一个工程里 ``C1`` 在多块板上各有一份，
按位号文字单键会把 A 板的读数贴到 B 板的几何上。

分级阶梯（与 :mod:`boardwise.rules.pcb.polarity` 同一套口径）
============================================================

=======================  =======  =============================================
类别                     级别     判据
=======================  =======  =============================================
位号丝印压焊盘            WARN     位号文字盒与**同面的焊盘**相交：有宿主实测
                                  bbox 时按读数判（172）；没有时要在**最窄**字宽
                                  档下就相交（量出叠加深度）
位号被器件本体压住        WARN     位号文字盒**整体落进**另一个器件本体轮廓内
                                  （完全看不见）
位号丝印被关掉            INFO     ``valueVisible=false``——「是不是忘了打开」
                                  文件答不了（同 151 的 DNP 缺口），只出读数
位号方向分布              INFO     同面文字方向的分布（含与多数方向相反/斜置的
                                  那些）——**方向上没有可查的阈值**，出读数不判
本板丝印小结              INFO     几个位号、几个可读、压焊盘的几个、宽度实测/
                                  估算各几个（172 的两态盘账）
=======================  =======  =============================================

WARN 与 INFO 的分界是同一条：**几何硬事实（相交/包含）报 WARN，需要判断意图或
没有可查阈值的报 INFO**。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from .base import PcbReviewContext, PcbRule

__all__ = [
    "ADVANCE_BAND",
    "DEFAULT_ADVANCE",
    "ESTIMATED_WIDTH",
    "MEASURED_WIDTH",
    "NARROW_ADVANCE",
    "WIDE_ADVANCE",
    "WIDTH_SOURCE_LABEL",
    "SilkDesignator",
    "box_overlaps",
    "measured_corners",
    "pad_polygon",
    "polygon_gap",
    "text_box",
]


#: 位号丝印的字形宽度带（字宽 = 比例 × 字号）。
#:
#: **这不是标准里查来的数，是「文件里没有」这件事的诚实表达。** ``.epru`` 只写
#: ``fontSize``，不写字形步进（advance），默认矢量字体的步进比没有任何一处记录。
#: 所以本规则**用一条带量三次**，而不是挑一个数当阈值：
#:
#: * :data:`NARROW_ADVANCE` = 0.4 —— 报 WARN 的门槛：最窄字形下仍压上焊盘，
#:   说明**无论字形怎么设计**这串字都压在焊盘上；
#: * :data:`DEFAULT_ADVANCE` = 0.6 —— 报数时用的中间值（等宽 CJK 与拉丁
#:   矢量字的常用区间中值）；
#: * :data:`WIDE_ADVANCE` = 0.8 —— 宽字形的上界；只有宽档才压上 → 降 INFO。
#:
#: 一条旁证（不是证明）：毕设FOC 1.1.0 的板上自带三个 ``CLK``/``DIO``/``GND``
#: 自由文字，``fontSize`` 50、相邻两个的锚点相距 95 mil；三字符若按 0.7 的比例
#: 就是 105 mil，会互相压住——设计者不会把自己的标注画叠，所以真实步进比
#: 0.7 小。这条读数是把上界收到 0.8 的依据，**不是把带收窄成一条线的依据**。
ADVANCE_BAND: tuple[float, float, float] = (0.4, 0.6, 0.8)
NARROW_ADVANCE = 0.4
DEFAULT_ADVANCE = 0.6
WIDE_ADVANCE = 0.8

#: 文字宽度的两种来源（任务 172）。**不是同一种东西，报告里必须分开**：
#:
#: * :data:`MEASURED_WIDTH` —— 宿主 primitive bbox 的读数；
#: * :data:`ESTIMATED_WIDTH` —— :data:`ADVANCE_BAND` 里那条带的估算（默认值，
#:   也是离线 ``--file`` 路径上唯一的来源：没有宿主可问）。
MEASURED_WIDTH = "measured"
ESTIMATED_WIDTH = "estimated"

#: 两态在报告里的字样。``ESTIMATED_WIDTH`` 那个必须是「估算值」——这是本批
#: 「不许拿估算当实测」的落点，测试逐字钉它。
WIDTH_SOURCE_LABEL = {
    MEASURED_WIDTH: "实测（宿主 primitive bbox）",
    ESTIMATED_WIDTH: "估算值（字宽比带，非读数）",
}

#: 位号文字在板上的面：顶层丝印 ↔ 顶层铜，底层丝印 ↔ 底层铜。
FACE_OF_SILK = {"TOP_SILK": 1, "BOT_SILK": 2}

#: 器件**本体轮廓**所在层（EasyEDA 的「元件外形层」，实测 id 48）。
BODY_KIND = "COMPONENT_SHAPE"


def measured_corners(value) -> list:
    """把一条宿主实测盒规范成四个板坐标角点。

    收两种写法，都是调用方容易拿到的东西：

    * ``(minX, minY, maxX, maxY)`` —— 宿主 ``getPrimitivesBBox`` 的原始形状
      （轴对齐）；
    * 四个点（``(x, y)`` 或带 ``.x``/``.y`` 的对象）—— 已经算好的盒子。

    形状不对就 ``ValueError``：一条读不懂的实测盒必须当场炸，不能悄悄退化成
    估算（那正是本批要消灭的混同）。
    """
    from ...core.geometry import Point

    if (
        isinstance(value, (tuple, list))
        and len(value) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        min_x, min_y, max_x, max_y = (float(v) for v in value)
        return [
            Point(min_x, min_y),
            Point(max_x, min_y),
            Point(max_x, max_y),
            Point(min_x, max_y),
        ]
    points = [Point(*_as_xy(p)) for p in value]
    if len(points) != 4:
        raise ValueError(f"a measured text box needs 4 corners, got {len(points)}")
    return points


def text_box(text, advance: float = DEFAULT_ADVANCE):
    """位号文字的旋转盒（四角，板坐标）。宽的模型在 :class:`SilkText` 上。"""
    return text.corners(advance)


def pad_polygon(pad, samples: int = 0) -> list:
    """把一只焊盘变成可做相交判定的多边形。

    ``RECT`` 一类直边焊盘取四角（含焊盘自身角度），是**精确**的。
    椭圆/圆形焊盘取**内接圆**——用圆心加一个半径 ``min(width, height)/2`` 的
    圆来做判定（:func:`polygon_gap` 认这种两元组）。取内接而不是外接是**故意的**：
    宁可少报一个边角擦过，也不拿一个比焊盘大的形状去报压焊盘（假警报的代价见 126
    钉 6）。实测板上的椭圆形焊盘都是正圆（``ELLIPSE`` 98.425 × 98.425 之类），
    内接圆在这类焊盘上是精确的。
    """
    shape = str(getattr(pad, "shape", "") or "").upper()
    half_w = float(getattr(pad, "width", 0.0)) / 2.0
    half_h = float(getattr(pad, "height", 0.0)) / 2.0
    if shape in ("ELLIPSE", "CIRCLE", "OVAL"):
        return ("circle", float(getattr(pad, "x", 0.0)), float(getattr(pad, "y", 0.0)), min(half_w, half_h))
    angle = float(getattr(pad, "angle", 0.0))
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    cx, cy = float(getattr(pad, "x", 0.0)), float(getattr(pad, "y", 0.0))
    corners = []
    for lx, ly in ((-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)):
        corners.append(
            (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)
        )
    return corners


def _as_xy(value) -> tuple[float, float]:
    if hasattr(value, "x") and hasattr(value, "y"):
        return float(value.x), float(value.y)
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], (int, float)):
        return float(value[0]), float(value[1])
    return float(value[0]), float(value[1])


def _edges(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    axes: list[tuple[float, float]] = []
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey)
        if length > 1e-9:
            axes.append((-ey / length, ex / length))
    return axes


def polygon_gap(a, b) -> float:
    """两个凸形状之间的**最小间隙**（mil）：负 = 相交，其绝对值为叠加深度。

    ``a``/``b`` 各是「凸多边形（点列）」或 ``("circle", cx, cy, r)``。
    多边形全靠**分离轴**（SAT）——旋转矩形之间这是精确的；圆对多边形用
    「圆心到多边形的最短距离 − r」，同样是精确的。

    返回的是**最深的那个方向上的穿透量**（所有分离轴里最小的间隙，负值）。
    两个形状分离时返回最小间隙本身，可以直接当「还差多少 mil 才压上」用——
    本规则只用它的符号与量值，不用它做任何阈值判断。
    """
    a_is_circle = isinstance(a, tuple) and a and a[0] == "circle"
    b_is_circle = isinstance(b, tuple) and b and b[0] == "circle"
    if a_is_circle and b_is_circle:
        ax, ay, ar = a[1], a[2], a[3]
        bx, by, br = b[1], b[2], b[3]
        return math.hypot(bx - ax, by - ay) - (ar + br)
    if a_is_circle or b_is_circle:
        circle, poly = (a, b) if a_is_circle else (b, a)
        return _circle_polygon_gap(circle[1], circle[2], circle[3], poly)
    return _polygon_polygon_gap(a, b)


def _polygon_polygon_gap(a: list, b: list) -> float:
    points_a = [_as_xy(p) for p in a]
    points_b = [_as_xy(p) for p in b]
    best = -1.0e18
    for points in (points_a, points_b):
        for ax, ay in _edges(points):
            proj_a = [x * ax + y * ay for x, y in points_a]
            proj_b = [x * ax + y * ay for x, y in points_b]
            overlap = min(max(proj_a), max(proj_b)) - max(min(proj_a), min(proj_b))
            best = max(best, -overlap)
    return best


def _circle_polygon_gap(cx: float, cy: float, radius: float, poly: list) -> float:
    """圆对凸多边形的间隙（负 = 相交）。

    圆心到多边形的**带符号距离**：圆心在多边形内时取「到最近边的距离的负值」，
    在外时取正值；再减去半径就是间隙。圆心在多边形内部的情形（文字盒盖住整只
    焊盘）就是这里最负的那一档——正是「彻底压上」该有的读数。
    """
    points = [_as_xy(p) for p in poly]
    distance = min(
        _segment_distance(cx, cy, points[i], points[(i + 1) % len(points)])
        for i in range(len(points))
    )
    if _point_in_polygon(cx, cy, points):
        distance = -distance
    return distance - radius


def _point_in_polygon(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    """Pure even-odd containment, with **no on-edge rule**.

    Unlike :func:`boardwise.core.measure.point_in_polygon` — which snaps any point
    within 1e-9 of an edge to 「inside」 via an explicit segment-distance check —
    a point exactly on an edge gets the raw even-odd answer here, and that answer
    is direction-dependent: the half-open ``(y0 > y) != (y1 > y)`` convention
    reads bottom/left edges as inside and top/right as outside (measured
    2026-10-12, 177 audit). Exact-edge hits are measure-zero in practice; what
    this implementation promises is only 「no snap band」.

    **177 钉界：这份不是副本，差异是故意的，别再提「三份副本」的 bug。** The
    measure side's tolerance exists because copper touching copper *is*
    connected; ink grazing a pad corner is not ink over the pad, and a 1e-9
    magnetic band would smear that distinction. Its ``(x, y, points)`` signature
    serves this file's ``_as_xy`` pipeline and is not interchangeable with the
    ``(Point, list[Point])`` public form.
    """
    inside = False
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            x_cross = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < x_cross:
                inside = not inside
    return inside


def _segment_distance(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def box_overlaps(corners: list, pad) -> float:
    """文字盒压不压这只焊盘：返回最小间隙（负 = 压上，绝对值为深度）。"""
    return polygon_gap([_as_xy(c) for c in corners], pad_polygon(pad))


@dataclass
class _Hit:
    """一次压焊盘命中：哪只脚、叠加多深（估算法三个字宽模型各量一次）。

    ``measured`` 非 ``None`` 时是 :data:`MEASURED_WIDTH` 那一档的读数——那时
    ``depths`` 是空的（一整条带都不需要），两个字段恒有一个有值，绝不混着报。
    """

    component: str = ""
    pin: str = ""
    depths: dict[float, float] = field(default_factory=dict)
    measured: float | None = None

    @property
    def worst(self) -> float:
        values = list(self.depths.values())
        if self.measured is not None:
            values.append(self.measured)
        return min(values) if values else 0.0

    def line(self) -> str:
        """这条命中的量值（估算法那三档 / 那一档实测读数）。"""
        parts = []
        if self.measured is not None:
            parts.append(f"实测 → {self.measured:.1f} mil")
        parts.extend(f"字宽比 {a:g} → {d:.1f} mil" for a, d in sorted(self.depths.items()))
        return " / ".join(parts)


class SilkDesignator(PcbRule):
    """位号丝印：压焊盘、被本体压住、被关掉、方向分布（任务 152）。

    每条 finding 都把 5 件事说全：哪块板 / 哪个位号（或哪一组）/ 量出什么 /
    判据是什么 / 后果是什么。见模块 docstring 的分级阶梯。

    ``measured``（任务 172）是**宿主实测的文字盒**，键 ``(板名, 位号文字)``、
    值是 :func:`measured_corners` 收的两种写法之一。给了就用读数、不给就用
    :data:`ADVANCE_BAND` 估——两条路在每条 evidence 里分别带「实测（宿主
    primitive bbox）」/「估算值（字宽比带，非读数）」字样，读报告的人不必猜。
    """

    id = "pcb-silk-designator"
    title = "位号丝印不压焊盘、不被器件本体压住、方向一致"
    level = "L1-pcb-geometry"
    source = (
        "house rule（压焊盘判据「0 间隙」待裁；文字宽度岳 2026-10-11 裁："
        "**实测优先、估算降级**——宿主 primitive bbox（getPrimitivesBBox）可用时用"
        "读数，测不到时退到字宽比带 [0.4, 0.6, 0.8] 并在 evidence 里逐条标"
        "「估算值」（.epru 不带字形步进））；压焊盘判据 = 同面焊盘与文字盒相交"
        "（0 间隙，非工艺限值）"
    )

    def __init__(self, measured=None):
        #: ``(board_title, designator text) -> 实测盒``。按板名分键：同一工程里
        #: ``C1`` 在多块板上各有一份，单键会把 A 板的读数贴到 B 板上。
        self.measured = dict(measured or {})

    # -- width provenance (172) -------------------------------------------

    def _measured_box(self, ctx, text):
        """这条位号的宿主实测盒（四角），没测到就是 ``None``。"""
        value = self.measured.get((ctx.board_title, text.text))
        if value is None:
            return None
        return measured_corners(value)

    def _measured_note(self, ctx, text, corners) -> str:
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        line = (
            f"宽度来源：{WIDTH_SOURCE_LABEL[MEASURED_WIDTH]}——"
            f"实测盒 ({min(xs):.3f}, {min(ys):.3f})–({max(xs):.3f}, {max(ys):.3f}) mil，"
            f"是宿主给的**轴对齐** ink 盒（读数，不是模型）"
        )
        if abs((float(text.angle) % 90.0)) > 1e-6:
            line += (
                f"；这条位号斜置 {text.angle:g}°，轴对齐盒是它的外接矩形（比字大）"
                "——外接方向只会**多报**不会漏报"
            )
        return line

    def _estimate_note(self, text) -> str:
        return (
            f"宽度来源：{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]}——.epru 不带字形步进，"
            f"文字盒按 字符数 × 字宽比 × fontSize({text.font_size:g} mil) 估，"
            "字宽比只测到「这条压不压得上」，测不到「这串字到底多宽」"
        )

    # -- the pass ---------------------------------------------------------

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        designators = [t for t in board.silk_texts if t.source == "designator"]
        orphans = [t for t in board.silk_texts if t.source == "designator-unparented"]

        findings: list[Finding] = []
        findings.extend(self._over_pads(ctx, designators))
        findings.extend(self._covered(ctx, designators))
        findings.extend(self._hidden(ctx, designators))
        findings.extend(self._directions(ctx, designators))
        findings.extend(self._orphans(ctx, orphans))
        findings.append(self._summary(ctx, designators))
        return findings

    # -- 1) designator ink over a pad -------------------------------------

    def _over_pads(self, ctx, designators) -> list[Finding]:
        findings: list[Finding] = []
        wide_only: list[tuple[str, list[_Hit]]] = []
        for text in designators:
            if not text.visible or not text.text or text.font_size <= 0:
                continue
            face = FACE_OF_SILK.get(str(text.layer_kind or ""))
            if face is None:
                continue
            # 172: 实测优先。有读数就不跑那条带——一整条三档的估算在读数面前
            # 没有信息量，混在一起报反而让人分不清哪个数是量出来的。
            measured_box = self._measured_box(ctx, text)
            hits: list[_Hit] = []
            for pad in ctx.board.pads:
                if face not in (pad.effective_layer_ids or []):
                    continue
                hit = _Hit(component=str(pad.component or ""), pin=str(pad.pin_number or ""))
                if measured_box is not None:
                    gap = polygon_gap([_as_xy(c) for c in measured_box], pad_polygon(pad))
                    if gap < 0:
                        hit.measured = -gap
                else:
                    for advance in ADVANCE_BAND:
                        gap = box_overlaps(text_box(text, advance), pad)
                        if gap < 0:
                            hit.depths[advance] = -gap
                if hit.measured is not None or hit.depths:
                    hits.append(hit)
            if not hits:
                continue
            if measured_box is not None:
                findings.append(
                    self._over_pad_warn(ctx, text, hits, MEASURED_WIDTH, measured_box)
                )
                continue
            robust = [h for h in hits if NARROW_ADVANCE in h.depths]
            if robust:
                findings.append(self._over_pad_warn(ctx, text, robust, ESTIMATED_WIDTH))
            else:
                wide_only.append((str(text.text), hits))
        if wide_only:
            findings.append(self._over_pad_wide(ctx, wide_only))
        return findings

    def _over_pad_warn(self, ctx, text, hits: list[_Hit], source: str, measured_box=None) -> Finding:
        worst = max(hits, key=lambda h: h.worst)
        lines = [
            f"{h.component} pin {h.pin}: 叠加深度（{WIDTH_SOURCE_LABEL[source]}）{h.line()}"
            for h in sorted(hits, key=lambda h: h.component)
        ]
        if source == MEASURED_WIDTH:
            verdict = (
                f"{len(hits)} 只焊盘被压（最深的 {worst.component} pin {worst.pin}、"
                f"{worst.worst:.1f} mil），宿主实测的文字盒就直接相交（不是估算出来的）"
            )
            criteria = (
                "判据：**宿主实测**的文字盒（getPrimitivesBBox 的轴对齐 ink 盒）与"
                "**同面**焊盘的实例化几何相交，0 间隙——不是工艺限值，是「压上」这件事"
                "本身。宽度是读数，所以不需要字宽比带"
            )
        else:
            verdict = (
                f"{len(hits)} 只焊盘被压（最深的 {worst.component} pin {worst.pin}、"
                f"{worst.worst:.1f} mil），最窄字宽档（{NARROW_ADVANCE:g}）下就已经压上"
            )
            criteria = (
                "判据：**估算值**文字盒（字符数 × 字宽比 × fontSize，按角度旋转）与"
                "**同面**焊盘的实例化几何相交，0 间隙——不是工艺限值，是「压上」这件事"
                "本身。三档字宽比都量了，这里报的是最窄档也压上的"
            )
        return Finding(
            rule_id=self.id,
            severity="WARN",
            level=self.level,
            message=f"{ctx.board_title} {text.text} 的位号丝印压在焊盘上：{verdict}",
            evidence=lines
            + [
                f"位号记录：layer {text.layer_id}（{text.layer_kind}），锚点 "
                f"({text.x:.1f}, {text.y:.1f})，角度 {text.angle:g}°"
                f"（文件原值 {text.stored_angle:g}），fontSize {text.font_size:g} mil，"
                f"origin {text.origin or '(空)'}，文字 {text.text!r}",
                (
                    self._measured_note(ctx, text, measured_box)
                    if source == MEASURED_WIDTH
                    else self._estimate_note(text)
                ),
                criteria,
                "焊盘几何取**内接**形状（椭圆焊盘取内接圆），所以这个叠加深度是保守"
                "下限；阻焊开窗比焊盘大 2.008 mil（本工程 SOLDER 规则实测值），"
                "真实压上的面积只会更大",
            ],
            target=FindingTarget(
                component_ref=str(text.text),
                measurement=self._measurement(worst.worst),
            ),
        )

    def _over_pad_wide(self, ctx, entries: list[tuple[str, list[_Hit]]]) -> Finding:
        """只有宽字形模型才压上焊盘的位号——**一条**汇总测量行（不判缺陷）。

        逐条出一条会把 40 个位号的噪声塞进报告；而它们的结论是一致的（「取决于
        字形多宽，本规则不判」），所以按板汇总一行，把每个位号的量值都列出来。
        """
        lines: list[str] = []
        for name, hits in sorted(entries):
            for hit in sorted(hits, key=lambda h: h.component):
                # 这条汇总行只出现在估算那一态（有实测盒的位号走 WARN 那条路），
                # 所以来源字样是恒定的「估算值」——逐行写出来，不给读者留猜测。
                lines.append(
                    f"{name} → {hit.component} pin {hit.pin}: "
                    f"叠加深度（{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]}）{hit.line()}"
                )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{ctx.board_title} 有 {len(entries)} 个位号**在宽字形模型下**压到焊盘"
                f"（最窄档 {NARROW_ADVANCE:g} 量不出相交）：{len(lines)} 处，"
                "压不压取决于字形实际多宽，本规则不判"
            ),
            evidence=lines
            + [
                f"宽度来源：{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]}——.epru 不带字形步进，"
                "本规则只能用字宽比带 "
                + " / ".join(f"{a:g}" for a in ADVANCE_BAND)
                + " 量；这条是测量行，不是缺陷判定的落点（任务书纪律：阈值没谱的"
                "只出测量行）。要判的话先把字形步进钉死，再把这条升级成 WARN 即可"
                "——那是一次口径变更，改一行",
                "这条之所以还是估算：宿主 primitive bbox（getPrimitivesBBox）没有"
                "给出这些位号的实测盒（任务 172）——一旦给出，实测盒会直接取代这条带，"
                "这条汇总行也随之消失",
            ],
        )

    # -- 2) designator covered by a neighbour's body ----------------------

    def _covered(self, ctx, designators) -> list[Finding]:
        bodies: list[tuple[str, int, list]] = []
        for shape in ctx.board.silk_shapes:
            if str(shape.layer_kind or "") != BODY_KIND:
                continue
            component = str(shape.component or "")
            placement = ctx.board.component(component)
            face = int(getattr(placement, "layer_id", 1) or 1) if placement else 1
            polygon = self._shape_polygon(shape)
            if polygon:
                bodies.append((component, face, polygon))
        if not bodies:
            return []

        findings: list[Finding] = []
        partial: list[str] = []
        for text in designators:
            if not text.visible or not text.text or text.font_size <= 0:
                continue
            face = FACE_OF_SILK.get(str(text.layer_kind or ""))
            if face is None:
                continue
            # 172: 「整体落进别人本体」也吃宽度，所以同样实测优先。估算档取
            # **最宽**——这里问的是「完全看不见」，宽松估计才不会漏报。
            measured_box = self._measured_box(ctx, text)
            if measured_box is not None:
                box = measured_box
                width_note = self._measured_note(ctx, text, measured_box)
            else:
                box = text_box(text, WIDE_ADVANCE)
                width_note = (
                    f"宽度来源：{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]}——本规则用**最宽**"
                    f"字宽档（{WIDE_ADVANCE:g}）估这串字占多宽（.epru 不带字形步进）"
                )
            for component, body_face, polygon in bodies:
                if component == text.component or body_face != face:
                    continue
                points = [_as_xy(p) for p in polygon]
                inside = sum(1 for corner in box if _point_in_polygon(corner.x, corner.y, points))
                if inside == 0:
                    continue
                if inside < len(box):
                    partial.append(
                        f"{text.text} 落在 {component} 本体轮廓内 {inside}/4 角"
                        f"（宽度{MEASURED_WIDTH if measured_box is not None else '估算值'}）"
                    )
                    continue
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="WARN",
                        level=self.level,
                        message=(
                            f"{ctx.board_title} {text.text} 的位号丝印被 {component} 的"
                            "器件本体完全压住（文字盒整体落进对方的本体轮廓内）："
                            "摆完之后板上看不见这个位号"
                        ),
                        evidence=[
                            f"designator text {text.text!r} box at "
                            f"({text.x:.1f}, {text.y:.1f}) angle {text.angle:g}°, "
                            f"fontSize {text.font_size:g} mil, {text.layer_kind}",
                            f"{component} body outline on layer {BODY_KIND} covers it "
                            f"（该器件在{'顶层' if body_face == 1 else '底层'}）",
                            width_note,
                            "判据：文字盒四角全部落在另一个器件的本体轮廓多边形内"
                            "——「完全看不见」是硬事实，所以这条报 WARN 而不是测量行",
                            "本体轮廓取 FOOTPRINT 文档的 COMPONENT_SHAPE 层图元"
                            "（实测 id 48），按 COMPONENT 位姿实例化；它是器件的"
                            "占位外形，比实物本体略大，所以「落进轮廓内」是保守读数",
                        ],
                        target=FindingTarget(component_ref=str(text.text)),
                    )
                )
        if partial:
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} 有 {len(partial)} 处位号丝印**部分**落在别的"
                        "器件本体轮廓内（没被完全盖住，仍看得见一部分）：本规则不判"
                    ),
                    evidence=partial
                    + [
                        "「完全盖住」（4 角全在内）报 WARN、「部分盖住」只出这条"
                        "测量行——后者字还看得见，是密度与可读性的取舍，没有可查的"
                        "阈值（实测毕设FOC 1.0.0 的 PCB1 最多到 2/4 角，没有一处 4/4）",
                        "每行末尾的「宽度实测/估算值」就是这条计数所用的盒子来源："
                        "有宿主实测盒的按读数（轴对齐 ink 盒），没有的按**最宽**字宽档 "
                        f"{WIDE_ADVANCE:g} 估——估算出来的角点计数在这里不许冒充读数",
                    ],
                )
            )
        return findings

    @staticmethod
    def _shape_polygon(shape) -> list:
        """把一个图元展开成多边形：圆（带半径的单点）按 24 边形展开。"""
        points = list(shape.points)
        if shape.radius is not None and len(points) == 1:
            cx, cy = points[0].x, points[0].y
            return [
                (
                    cx + shape.radius * math.cos(2 * math.pi * i / 24),
                    cy + shape.radius * math.sin(2 * math.pi * i / 24),
                )
                for i in range(24)
            ]
        return points if len(points) >= 3 else []

    # -- 3) designators switched off --------------------------------------

    def _hidden(self, ctx, designators) -> list[Finding]:
        hidden = sorted(t.text for t in designators if not t.visible and t.text)
        if not hidden:
            return []
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"{ctx.board_title} 有 {len(hidden)} 个位号的丝印被关掉"
                    f"（``valueVisible=false``）：板上不会印出这些位号——"
                    "本规则只报读数，不判「是不是忘了打开」"
                ),
                evidence=[
                    "位号：" + ", ".join(hidden),
                    "实测：毕设FOC 1.1.0 的 PCB1 是 105 个位号里关掉 100 个；"
                    "1.0.0 的 PCB1 关掉 31 个（螺钉类位号被关掉是常见做法）",
                    "判据是位号 ATTR 记录自己的 ``valueVisible`` 字段——那是设计者"
                    "开关的直接读数，不是推断；但**「有意关掉」与「忘了打开」在这个"
                    "字段上无法区分**，设计意图合同里也没有 DNP/可读性字段"
                    "（与 151 的 DNP 缺口同一条），所以按 UNKNOWN 纪律出测量行",
                ],
            )
        ]

    # -- 4) direction distribution ----------------------------------------

    def _directions(self, ctx, designators) -> list[Finding]:
        per_face: dict[str, list[tuple[str, float]]] = {}
        for text in designators:
            if not text.visible or not text.text:
                continue
            kind = str(text.layer_kind or "")
            if kind not in FACE_OF_SILK:
                continue
            per_face.setdefault(kind, []).append((text.text, round(text.angle, 1) % 360.0))
        if not per_face:
            return []
        findings: list[Finding] = []
        for kind, entries in sorted(per_face.items()):
            buckets: dict[int, list[str]] = {}
            off_axis: list[str] = []
            for name, angle in entries:
                snapped = int(round(angle / 90.0)) * 90 % 360
                if abs((angle - snapped + 180) % 360 - 180) > 1.0:
                    off_axis.append(f"{name}({angle:g}°)")
                    snapped = min((0, 90, 180, 270), key=lambda q: abs((angle - q + 180) % 360 - 180))
                buckets.setdefault(snapped, []).append(name)
            distribution = ", ".join(
                f"{angle}°×{len(buckets[angle])}" for angle in sorted(buckets)
            )
            opposing = []
            if 0 in buckets and 180 in buckets:
                opposing = sorted(buckets[0] + buckets[180])
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} {kind}（{len(entries)} 个位号）文字方向分布："
                        f"{distribution}"
                        + (f"；另有 {len(off_axis)} 个斜置：{', '.join(sorted(off_axis))}" if off_axis else "")
                        + (
                            f"；其中 {len(opposing)} 个落在 0°/180° 两个相反方向上"
                            if opposing
                            else ""
                        )
                    ),
                    evidence=[
                        "位号文字方向跟着器件旋转走（EasyEDA 的位号角度与 COMPONENT "
                        "角度同一套单位与约定），所以同一面上混着 0/90/180/270 本身"
                        "是正常的——**「方向一致」到什么程度算合格，本规则没有可查的"
                        "阈值**，故只出分布读数、不判（任务书纪律）",
                        "斜置（不是 90° 整数倍）的位号实测集中在螺钉类器件上"
                        "（ROBOT 的 SCREW 是 34°/55°/315°/325°），它们本就随手摆",
                    ],
                )
            )
        return findings

    # -- 5) stray designator records --------------------------------------

    def _orphans(self, ctx, orphans) -> list[Finding]:
        if not orphans:
            return []
        placed = {
            str(getattr(c, "designator", "") or "") for c in getattr(ctx.board, "components", ())
        }
        lines = []
        duplicates = []
        for t in orphans:
            lines.append(
                f"{t.text!r} on layer {t.layer_id} at ({t.x:.1f}, {t.y:.1f})，"
                f"parentId {t.component_id!r} 不指向本板任何 COMPONENT"
                + ("，valueVisible=false" if not t.visible else "")
            )
            if t.text in placed:
                duplicates.append(t.text)
        if duplicates:
            lines.append(
                "其中 "
                + ", ".join(sorted(duplicates))
                + " 与板上真正的器件同名——这是**同一条位号的两份记录**"
                "（实测 ROBOT 的 R6：真正那条挂在 COMPONENT 上且可见，"
                "孤儿那条挂在不是 COMPONENT 的元素 id 上且被关掉），"
                "是编辑器改件时留下的旧记录"
            )
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"{ctx.board_title} 有 {len(orphans)} 条位号记录找不到它命名的器件"
                    "（``parentId`` 不指向本板的任何 COMPONENT）："
                    + (
                        f"其中 {len(duplicates)} 条与板上现有的器件同名，是同一条位号的"
                        "重复记录"
                        if duplicates
                        else "板上会印出一个没有对应器件的位号"
                    )
                ),
                evidence=lines
                + [
                    "实测：ROBOT ctrl FOC 的 PCB1 有 50 条位号记录、49 个 COMPONENT"
                    "——多出来的那一条是 R6 的旧副本。这条只出读数：孤儿记录不影响"
                    "真正的位号（那条挂在 COMPONENT 上、照常显示），但它说明文件里"
                    "有一处没人清掉的残留",
                ],
            )
        ]

    # -- summary ----------------------------------------------------------

    def _summary(self, ctx, designators) -> Finding:
        visible = [t for t in designators if t.visible and t.text]
        hidden = [t for t in designators if not t.visible and t.text]
        # 172: 两态的盘账。哪几个位号的宽度是量出来的、哪几个是估的，在这一行
        # 报出来——读者不必翻每条 evidence 才知道这份报告有多少是读数。
        measured = [t for t in visible if self._measured_box(ctx, t) is not None]
        estimated = len(visible) - len(measured)
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{ctx.board_title} 丝印读数：{len(designators)} 个位号记录"
                f"（显示 {len(visible)}、关掉 {len(hidden)}），"
                f"板上焊盘 {len(ctx.board.pads)} 只、器件本体轮廓 "
                f"{sum(1 for s in ctx.board.silk_shapes if s.layer_kind == BODY_KIND)} 个；"
                f"文字宽度：{WIDTH_SOURCE_LABEL[MEASURED_WIDTH]} {len(measured)} 个、"
                f"{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]} {estimated} 个"
            ),
            evidence=[
                "位号文字来自 PCB 文档自己的 ``ATTR key=Designator`` 记录"
                "（带 x/y/角度/字号/层/显示开关），不是 FOOTPRINT 渲染出来的——"
                "这一点是实测的，也是本规则能存在的前提",
                (
                    "文字宽度是**两态**的（任务 172）：实测那一态用宿主的 primitive "
                    "bbox（getPrimitivesBBox），是读数；估算那一态用字宽比带 "
                    + " / ".join(f"{a:g}" for a in ADVANCE_BAND)
                    + "，是模型。每条 evidence 都写着自己属于哪一态——"
                    "报告里不出现「看起来像读数的估算值」"
                ),
                (
                    f"本板实测 {len(measured)} 个位号、"
                    f"估算 {estimated} 个："
                    + (
                        "本板没有可读的位号丝印（没有可量的字、也没有可估的字），"
                        "所以这一行的两个 0 是「没有对象」，不是「测了没测到」"
                        if not visible
                        else "全部位号都有宿主实测盒，宽度这一项整份报告没有估算数字"
                        if estimated == 0
                        else "没测到的那些按估算降级（宿主未给出 bbox，或这条位号不在"
                        "可测的焦点板上）——降级是明说的，不是悄悄当实测用"
                    )
                ),
                "板载自由文字（``source='board'``，实测 PCB1 的 CLK/DIO/GND）与"
                "封装自带印字（``source='footprint'``，极性标记）不在本规则的位号"
                "口径里——前者不是位号，后者归 pcb-polarity-orientation",
            ],
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _measurement(value: float):
        from .distance import _measurement, _mil

        return _measurement("distance", _mil(value))
