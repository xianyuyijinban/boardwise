"""极性与方向：极性器件在 PCB 上的方向标记（任务 152，E 阶段第二棒 · 规则族 A）。

路线图（``tasks/122-pcb-review-roadmap.md`` 第三步第 3 条）：「极性器件方向标记、
同类器件方向统一（生产工艺）」。这两条问的是**同一件事的两个侧面**——一颗有极性
的件装到板上，装配的人能不能看出哪头是正极；一批同样的件，是不是都朝着同一个方向。

架构决策 5 的落点（岳 2026-10-07 裁：「PCB 检查必须桥接原理图检查」）
=================================================================

**「这颗件是有极性的」不是从形状猜的**，两个来源都是**声明事实**：

1. **原理图符号的引脚名**（``ctx.model`` 那块板的 ``Component.pins[].name``）——
   工程师画在符号上的名字。实测三块验收板上的极性写法只有三种，各自含义明确：
   ``+``/``-``（LED、电容、电池、连接器）、``K``/``A``（二极管阴极/阳极）、
   ``C``/``A``（部分 LED 符号的阴极/阳极）。**认这两种成对出现**才算极性：
   只有 ``A`` 一个、或只有 ``K`` 一个的符号不认（那是「名字里有个字母」，
   不是「这头是阳极」）。
2. **DEVICE 库件的 ``Type`` / ``Polarity`` 属性**（``ctx.pcb_model.props``，见下）——
   库件的类型词（``TVS`` / ``聚合物`` / ``发光二极管``…）与极性词（``单向``/``双向``）。
   ``Polarity == 双向`` 的件（实测：两颗 SMCJ 系列 TVS）**方向不敏感**——双向
   器件反过来装电气上等价，所以本规则明确**不判**它，并在证据里写明这一条。

   为什么从 ``ctx.pcb_model`` 取而不是 ``ctx.model``：**同一份 DEVICE 文档，
   两个视图的读取面不同**。原理图解析器只把 ``Supplier Part``/``Manufacturer Part``/
   ``Manufacturer``/``Datasheet``/``Supplier Footprint``/``Name`` 六个字段升成
   一手字段（``parsers/schematic.py::DEVICE_ATTR_FIELDS``），``Type`` 与
   ``Polarity`` 不在其中；PCB 侧模型把整张 ``attributes`` 映射原样放进
   ``Component.props``（``parsers/epro2_model.py::build_design_model``）。
   DEVICE 文档是**同一个库件**，两个视图读的是同一份声明，所以这不是「换了一个
   数据源」，而是「同一个数据源的另一半字段」。**这是模型层的一处读取面缺口**，
   与 151 §4 记的模型层噪声同类，本批不修模型、只如实记（见交卷报告）。

**方向标记**读的是**印在板上的图元**：``board.silk_shapes``（FOOTPRINT 文档的
POLY/FILL/CIRCLE，按 COMPONENT 位姿实例化）里落到**丝印层**（``TOP_SILK``/
``BOT_SILK``，按运行文档自己的 ``LAYER`` 表判读，不写死 3/4）的那些，加
``board.silk_texts`` 里 ``source == "footprint"`` 的印刷文字（``+`` / ``-`` /
``*`` / ``1`` —— 实测库里的 ``CONN-TH_XT30UPB-M`` 就带着 ``+``/``-`` 两个丝印字）。

**丝印层与 marking 层是两件事，本规则不混**：footprint 上还有一层
``COMPONENT_MARKING``（实测 id 49），EasyEDA 每个封装都在**1 脚角上**画一个
2.36 mil 的小圆点。它是**编辑器内部的标记层，不是印在板上的丝印**（Gerber 的
丝印只有 ``TOP_SILK``/``BOT_SILK`` 两层），所以它**不能算方向标记**，只作为
「这颗件的 1 脚在哪一头」的读数出现在证据里。

判据（每条 finding 都能追到一个量出来的东西）
=============================================

* **极性标记与极性脚不符（ERROR）**：封装自己在丝印上写了 ``+``/``-``，原理图
  也声明了哪只脚是 ``+``/``-``，两边却对不上——按丝印装件会装反。**这是本规则
  唯一一条不需要任何约定就能判死的**：封装说「这头是正极」，原理图说「正极是
  另一只脚」。
* **极性器件没有印刷方向标记（ERROR）**：丝印层上的图元在**换脚操作**下不变——
  换脚 = 绕两只极性脚的中点转 180°，也就是「把这颗件反着装」这个物理动作。若画
  的图在 180° 旋转下与自身重合，则装反的板与装对的板**看起来一模一样**，装配的人
  无从判断。判据是**图元级**的集合比较（见 :func:`unpaired_elements`），不是
  逐点比对——逐点比对会被「丝印正好从 1 脚角上穿过」这种巧合骗过去（实测
  ``C0603`` 的 1 脚圆点与丝印拐角只差 0.004 mil）。
* **同类极性器件方向不统一（WARN）**：同一块板上、同一个**封装名**、都在同一个面上
  的多颗极性件，方向必须一致（任务书原文：同封装同朝向是生产工艺要求）。判据是
  每颗件的**极性轴在板坐标里的方向**（由两只极性脚的实际焊盘中心算出，含面）。
  方向不一致 = 同一种料在板上的朝向不同。
* **原理图没有声明极性脚（INFO）**：库件说这有极性（``Type`` 是 ``聚合物`` 等），
  但符号脚名只有 ``1``/``2``。此时丝印上的标记**无法与原理图核对**——这是
  一句话说清的事实缺口（UNKNOWN 纪律，126 钉 6），不猜、不替代。
* **本板读数小结（INFO）**：几颗极性件、几种封装、几个方向、有没有对不上的。

阈值
====

本规则的常数只有两个，都不是「多少 mil 算近」这类度数：

* :data:`MARK_SNAP_MIL`（0.5 mil）——**图元集合比较**时判「两个图元是不是同一个
  位置」的容差。它对齐的是文件自己的舍入尺度（实测成对的丝印线中心相距
  0.003–0.006 mil，而同一封装里手抖画出的两笔可以差 0.47 mil），不是工艺尺寸。
* 极性脚的判定表 :data:`POLARITY_PAIRS`——声明词表，不是阈值。

所以 ``source`` 写 house rule（待裁）：没有一条是从标准里查出来的限值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from .base import PcbReviewContext, PcbRule

__all__ = [
    "MARK_SNAP_MIL",
    "POLARITY_PAIRS",
    "POLARIZED_TYPE_WORDS",
    "MarkReading",
    "Polarity",
    "PolarityOrientation",
    "POLARITY_NAME_TABLE",
    "axis_direction",
    "polarity_of_component",
    "polarity_of_library",
    "resolve_polarity",
    "unpaired_elements",
]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

#: 符号脚名的**极性词表**：``(成对的脚名集合, 哪只脚是正极, 哪只脚是负极, 器件类别)``。
#:
#: 判读方式是「**成对出现**才认」：一对名字里两只脚都在，才说这颗件有极性；单只
#: ``A``、单只 ``K`` 不认（USB-C 的 ``A5``/``B1A12`` 是名字里带字母，不是阳极；
#: 实测三块板上没有单字母脚名被误认）。表里三类写法的来源都是实测：
#:
#: * ``+`` / ``-`` —— 毕设FOC 1.0.0 的 ``LED1``/``LED4``（``('1','+'),('2','-')``）、
#:   1.1.0 的 ``LED1``/``LED2``（``('1','-'),('2','+')``，同一颗料的符号在
#:   1.1.0 里换过编号）、``CN3``（``XT30PW-M`` 的 ``('-','+')``）。
#: * ``K`` / ``A`` —— 两颗 SMCJ 系列 TVS（``D1``/``D2``）。
#: * ``C`` / ``A`` —— 1.0.0 的 ``LED5``（``LED_0603`` 符号）。
POLARITY_PAIRS: tuple[tuple[frozenset[str], str, str, str], ...] = (
    (frozenset({"+", "-"}), "+", "-", "polarized"),
    (frozenset({"K", "A"}), "A", "K", "diode"),
    (frozenset({"C", "A"}), "A", "C", "led"),
)

#: 带「正负两向」写法的脚名，长一点的写法归一到这里（``V+`` → ``+``）。
POLARITY_NAME_TABLE: dict[str, str] = {
    "V+": "+", "V-": "-", "+V": "+", "-V": "-",
    "ANODE": "A", "CATHODE": "K",
}

#: **DEVICE 库件 ``Type`` 里说明「这颗件有极性」的词**。只收明确的器件类别词：
#: 二级管族（二极管/发光二极管/稳压二极管/整流/TVS/桥堆）、电解电容族
#: （电解/钽/聚合物/超级电容/固态电容）、光耦。命中即认「有极性」，**但脚名
#: 仍是判方向脚的唯一来源**——``Type`` 只说「有极性」，不说「哪只脚是正极」，
#: 所以只出 INFO，不出方向 verdict。
POLARIZED_TYPE_WORDS: tuple[str, ...] = (
    "二极管", "发光二极管", "稳压二极管", "整流", "TVS", "桥堆", "光耦",
    "电解", "钽", "聚合物", "超级电容", "固态电容",
)

#: 「两颗图元算同一个位置」的容差（mil）。见模块 docstring「阈值」一节。
#:
#: **0.05 mil 是量出来的分界，不是拍的**：三块验收板 + llc 夹具上，同一个封装里
#: 真正互为镜像的两笔丝印，落点差实测集中在 **0.0005–0.01 mil**（文件自己的舍入），
#: 而「画的明显是另一笔」的落点差从 **0.466 mil 起跳**（``SMC_L6.9-W5.9`` 把二极管
#: 符号画了两遍、第二遍偏 0.47 mil；``C0603`` 的一个副本偏 0.64 mil）。阈值放在
#: 这个空档里。**取紧的一侧是有意的**：偏紧会把画得糙但对称的封装读成「有方向
#: 标记」——那是漏报一个缺陷，而不是报一个假警报（假警报的代价见 126 钉 6 的
#: 同一套纪律）。
MARK_SNAP_MIL = 0.05

#: 丝印层的 layer type（与 :data:`boardwise.core.geometry.SILK_LAYER_TYPES` 同一份
#: 事实，这里再写一遍是为了让本模块不依赖导入顺序就能说清自己读哪一层）。
SILK_KINDS = frozenset({"TOP_SILK", "BOT_SILK"})

#: marking 层（EasyEDA 的「元件标记层」，实测 id 49）——**不是印在板上的丝印**，
#: 只用来读「1 脚在哪一头」。见模块 docstring。
MARKING_KINDS = frozenset({"COMPONENT_MARKING"})

#: 板坐标的面：位号/丝印在顶层丝印 ↔ 顶层铜；底层同理。
FACE_OF_SILK = {"TOP_SILK": 1, "BOT_SILK": 2}


# ---------------------------------------------------------------------------
# the schematic-side fact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Polarity:
    """一颗极性件的**声明事实**：哪只脚是正极、谁说的。"""

    kind: str = ""
    #: 符号声明的脚号（``None`` = 只说「有极性」，没说哪只脚）。
    plus_pin: str | None = None
    minus_pin: str | None = None
    #: 这个结论是谁说的：``"symbol pin names"`` 或 ``"device library type"``。
    declared_by: str = ""
    #: 双向器件（TVS 一类）：反过来装电气等价，方向标记不是必须。
    orientation_sensitive: bool = True
    #: 声明原样（脚名对 / 库件类型词 / Polarity 属性值），写进证据用。
    declaration: str = ""


def polarity_of_component(component: object) -> Polarity | None:
    """从**原理图符号的脚名**判一颗件的极性，判不出则 ``None``。

    判读顺序就是 :data:`POLARITY_PAIRS` 的顺序：先 ``+``/``-``，再 ``K``/``A``，
    再 ``C``/``A``。名字先做三件事：去空白、转大写、过一遍
    :data:`POLARITY_NAME_TABLE`（``V+`` → ``+``）。

    只认**成对**出现的名字（见模块 docstring）。两条以上规则同时命中时取第一条
    ——实测没有这种件，取第一条是因为顺序固定、可复现，而不是因为哪条更对。
    """
    pins = list(getattr(component, "pins", ()) or ())
    names: dict[str, list[str]] = {}
    for pin in pins:
        raw = str(getattr(pin, "name", "") or "").strip().upper()
        if not raw:
            continue
        normalised = POLARITY_NAME_TABLE.get(raw, raw)
        names.setdefault(normalised, []).append(str(getattr(pin, "number", "") or ""))
    for wanted, plus, minus, kind in POLARITY_PAIRS:
        if not wanted <= set(names):
            continue
        plus_pins = [n for n in names[plus] if n]
        minus_pins = [n for n in names[minus] if n]
        if not plus_pins or not minus_pins:
            continue
        return Polarity(
            kind=kind,
            plus_pin=plus_pins[0],
            minus_pin=minus_pins[0],
            declared_by="symbol pin names",
            declaration=(
                f"符号脚名 {plus!r} → pin {plus_pins[0]}，"
                f"{minus!r} → pin {minus_pins[0]}"
            ),
        )
    return None


def polarity_of_library(props: dict, designator: str = "") -> Polarity | None:
    """从 **DEVICE 库件属性**判极性：``Type`` 的类型词 + ``Polarity`` 属性值。

    这是 :func:`polarity_of_component` 断不出时的**第二来源**，两个结论都不是
    形状推断：

    * ``Polarity`` 属性写着「双向」→ **方向不敏感**（实测：SMCJ 系列 TVS 写成
      ``双向``）；写着「单向」→ 有极性且方向敏感。
    * ``Type`` 命中 :data:`POLARIZED_TYPE_WORDS` → 有极性（种类明确，脚号未知）。

    返回的 :class:`Polarity` 在这条路上 ``plus_pin``/``minus_pin`` 都是 ``None``
    ——**库件类型词只说「这颗件有极性」，不说「哪只脚是正极」**，所以走这条路的
    件只出 INFO，不出方向 verdict。
    """
    attributes = props or {}
    polarity_word = str(attributes.get("Polarity") or "").strip()
    type_word = str(attributes.get("Type") or "").strip()
    if "双向" in polarity_word:
        return Polarity(
            kind="bidirectional",
            declared_by="device library type",
            orientation_sensitive=False,
            declaration=f"库件 Polarity 属性 = {polarity_word!r}（双向器件，方向不敏感）",
        )
    if polarity_word or any(word in type_word for word in POLARIZED_TYPE_WORDS):
        return Polarity(
            kind="polarized",
            declared_by="device library type",
            declaration=(
                f"库件 Type = {type_word!r}"
                + (f"，Polarity = {polarity_word!r}" if polarity_word else "")
            ),
        )
    return None


# ---------------------------------------------------------------------------
# the PCB-side reading
# ---------------------------------------------------------------------------


def _rot180(x: float, y: float, cx: float, cy: float) -> tuple[float, float]:
    return (2.0 * cx - x, 2.0 * cy - y)


@dataclass
class MarkReading:
    """一颗件在板上的方向标记读数（全部量出来的）。"""

    designator: str = ""
    #: 参与比较的印刷图元数（丝印层的图形 + footprint 印字）。
    marked_elements: int = 0
    #: 在换脚（绕极性脚中点转 180°）下**找不到配对**的图元描述。
    unpaired: list[str] = field(default_factory=list)
    #: 这些无配对图元的重心，在封装局部坐标里相对轴中点的投影；正 = 靠 plus 脚。
    side: float = 0.0
    #: marking 层（非丝印）的 1 脚圆点落在哪只脚一侧。
    dot_pin: str | None = None
    dot_distance: float | None = None
    #: 封装自带的 ``+`` / ``-`` 丝印字（局部坐标），以及各自最近的脚。
    plus_marks: list[tuple[float, float]] = field(default_factory=list)
    minus_marks: list[tuple[float, float]] = field(default_factory=list)
    plus_mark_pin: str | None = None
    minus_mark_pin: str | None = None
    notes: list[str] = field(default_factory=list)


def _element_key(shape_or_text: object) -> tuple:
    """图元比较用的键：层种类 + 图元种类。**位置另比**。"""
    layer_kind = str(getattr(shape_or_text, "layer_kind", "") or "")
    kind = str(getattr(shape_or_text, "kind", "") or getattr(shape_or_text, "source", "") or "")
    return (layer_kind, kind)


def resolve_polarity(schematic: object | None, props: dict, designator: str = "") -> Polarity | None:
    """把两个来源的极性事实合成一条（任务 152 的入口）。

    合成规则，两条都有出处，都不是推断：

    1. **库件说这器件是双向的（``Polarity: 双向``），方向就不敏感**——反过来装
       电气等价，方向标记不是必须。这一条**压过符号脚名**：实测两颗 SMCJ 系列
       TVS 的符号脚名写着 ``K``/``A``（看起来是按单向画的），而库件属性写着
       ``双向``；按符号判会把它们报成「极性器件没有方向标记」，那是个假警报。
    2. 否则符号脚名说话（它说得出**哪只脚是正极**，库件类型词说不出）。
    3. 两者都没有 → ``None``（不猜）。

    ``declaration`` 里把两个来源的原话都留着，读的人自己看得见是按哪一条判的。
    """
    from_symbol = polarity_of_component(schematic) if schematic is not None else None
    from_library = polarity_of_library(props, designator)
    if from_library is not None and not from_library.orientation_sensitive:
        return Polarity(
            kind="bidirectional",
            plus_pin=from_symbol.plus_pin if from_symbol else None,
            minus_pin=from_symbol.minus_pin if from_symbol else None,
            declared_by="device library type",
            orientation_sensitive=False,
            declaration=from_library.declaration
            + (
                f"；同时符号脚名写着 {from_symbol.declaration}——双向器件的方向不敏感，"
                "本规则不判"
                if from_symbol
                else ""
            ),
        )
    if from_symbol is not None:
        if from_library is not None:
            return Polarity(
                kind=from_symbol.kind,
                plus_pin=from_symbol.plus_pin,
                minus_pin=from_symbol.minus_pin,
                declared_by=from_symbol.declared_by,
                declaration=f"{from_symbol.declaration}；库件侧：{from_library.declaration}",
            )
        return from_symbol
    return from_library


def unpaired_elements(elements: list[tuple], center: tuple[float, float], tolerance: float = MARK_SNAP_MIL) -> list[tuple]:
    """在「绕 ``center`` 转 180°」这个操作下**找不到配对**的图元。

    ``elements`` 是 ``(key, x, y, description, payload)`` 五元组列表；``key``
    由 :func:`_element_key` 给出（层种类 + 图元种类），所以「丝印线上的一笔」只
    会跟另一笔丝印线配对，不会跟 marking 层的圆点配对。

    判据是**图元级**的：拿到一个图元，把它绕 ``center`` 转 180°，在同类图元里
    找有没有落点相距 ``tolerance`` 以内的——**看的是这个图元整体在哪儿，不是它
    有几个顶点**。逐顶点比对会在实测的 ``C0603`` 上翻车：它的 1 脚圆点
    ``(-31.5, -15.75)`` 与丝印拐角 ``(-31.496, -15.748)`` 只差 0.004 mil，两者
    会互相「配对」成功，于是「有 1 脚标记」这件事被抹掉。

    返回无配对的那些图元（原样，含描述），顺序与输入一致。
    """
    out: list[tuple] = []
    cx, cy = center
    for key, x, y, description, payload in elements:
        rx, ry = _rot180(x, y, cx, cy)
        paired = False
        for other_key, ox, oy, _other_description, _other_payload in elements:
            if other_key != key:
                continue
            if math.hypot(ox - rx, oy - ry) <= tolerance:
                paired = True
                break
        if not paired:
            out.append((key, x, y, description, payload))
    return out


def axis_direction(pads: list[object], polarity: Polarity | None) -> tuple[float, float] | None:
    """极性轴方向：从**负极脚**指向**正极脚**的单位向量，都在板坐标里。

    有声明脚号时用声明的两只脚；没有声明时退回「pad 1 → pad 2」（脚号本身也是
    封装声明的轴）。两只脚的中心重合（单脚件、零脚件）时返回 ``None``——量不出
    方向就说量不出，不拿位姿角度硬充。
    """
    by_pin = {str(getattr(p, "pin_number", "")): p for p in pads}
    plus = minus = None
    if polarity is not None and polarity.plus_pin and polarity.minus_pin:
        plus = by_pin.get(str(polarity.plus_pin))
        minus = by_pin.get(str(polarity.minus_pin))
    if plus is None or minus is None:
        ordered = sorted(
            (p for p in pads if str(getattr(p, "pin_number", ""))),
            key=lambda p: str(getattr(p, "pin_number", "")),
        )
        if len(ordered) < 2:
            return None
        minus, plus = ordered[0], ordered[1]
    dx = float(getattr(plus, "x", 0.0)) - float(getattr(minus, "x", 0.0))
    dy = float(getattr(plus, "y", 0.0)) - float(getattr(minus, "y", 0.0))
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    return (dx / length, dy / length)


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


class PolarityOrientation(PcbRule):
    """极性器件在 PCB 上的方向标记与方向统一性（任务 152）。

    ==========================  =======  ==========================================
    类别                        级别     判据
    ==========================  =======  ==========================================
    极性标记与极性脚不符        ERROR    封装丝印写了 ``+``/``-``，且原理图声明了极性
                                         脚，两边对不上（按丝印装件会装反）
    极性器件无印刷方向标记      ERROR    丝印层图元在「换脚」180° 旋转下与自身重合
                                         ——装反的板与装对的板长得一样
    同类极性器件方向不统一      WARN     同一块板、同一封装名、同一面的多颗极性件，
                                         极性轴在板坐标里的方向不一致
    原理图没有声明极性脚        INFO     库件说有极性，符号脚名只有 1/2 —— 丝印标记
                                         无从与原理图核对（UNKNOWN，不猜）
    本板极性读数小结            INFO     几颗极性件、几种封装、几个方向
    ==========================  =======  ==========================================

    逐件的读数（标记在图元的哪一头、marking 层 1 脚圆点在哪一头）不逐条出
    finding——那是每颗极性件都有的行，122 件的板会刷屏；它们在**方向不统一**
    与**本板小结**两处被引用，异常件（对不上 / 没标记 / 无从核对）才各有自己的
    finding（151 的同一口径）。
    """

    id = "pcb-polarity-orientation"
    title = "极性器件在 PCB 上的方向标记、标记与极性脚一致、同类器件方向统一"
    level = "L1-pcb-geometry"
    source = (
        "house rule（岳 2026-10-11 待裁）：极性判读词表（符号脚名 +/-、K/A、C/A 与 "
        "DEVICE Type/Polarity）+ 图元级换脚不对称判据（容差 0.5 mil，对齐文件舍入）"
    )

    # -- context plumbing -------------------------------------------------

    @staticmethod
    def _schematic_component(ctx: PcbReviewContext, designator: str) -> object | None:
        """这颗 PCB 位号在**本板对应的原理图板**上的那颗件（151 的同一路）。

        板链走 ``PcbReviewContext.board_uuid``（PCB 文档 ``META.board`` →
        原理图 ``BoardRef.uuid``）；读不出板链时退回项目模型的手上那本
        ``components``（单板工程与测试走这条），**绝不按位号重合度配板**——
        毕设FOC 的 Board1 与 Board3 共用 ``C1``…``R6`` 一大串位号。
        """
        model = ctx.model
        if model is None:
            return None
        boards = getattr(model, "boards", None)
        if boards is None:
            return (getattr(model, "components", {}) or {}).get(designator)
        uuid = str(getattr(ctx, "board_uuid", "") or "")
        for board in boards:
            if uuid and str(getattr(getattr(board, "board", None), "uuid", "") or "") != uuid:
                continue
            found = (getattr(board, "components", {}) or {}).get(designator)
            if found is not None:
                return found
        return None

    # -- the pass ---------------------------------------------------------

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        pcb_components = getattr(ctx.pcb_model, "components", {}) or {}

        readings: list[tuple[str, Polarity, MarkReading, object | None]] = []
        unnameable: list[tuple[str, Polarity, str]] = []
        for designator in sorted(
            {str(getattr(c, "designator", "") or "") for c in getattr(board, "components", ())}
        ):
            if not designator:
                continue
            schematic = self._schematic_component(ctx, designator)
            props = getattr(pcb_components.get(designator), "props", {}) or {}
            polarity = resolve_polarity(schematic, props, designator)
            if polarity is None or not polarity.orientation_sensitive:
                continue
            reading = self._read_mark(board, designator, polarity)
            readings.append((designator, polarity, reading, schematic))
            if polarity.plus_pin is None:
                unnameable.append((designator, polarity, str(polarity.declaration)))

        findings: list[Finding] = []
        findings.extend(self._mismatch(ctx, readings))
        findings.extend(self._no_mark(ctx, readings))
        findings.extend(self._inconsistent(ctx, readings))
        findings.extend(self._unnameable(ctx, unnameable))
        findings.append(self._summary(ctx, readings, unnameable))
        return findings

    # -- one part's reading -----------------------------------------------

    def _read_mark(self, board, designator: str, polarity: Polarity) -> MarkReading:
        """量一颗件在板上的方向标记（全部在**封装局部坐标**里比）。

        局部坐标是关键：封装对「哪一头是正极」的声明是**封装自己的属性**，
        与这一颗实例摆成什么角度无关。要比的也是「这颗件的封装有没有把两头
        区分开」，所以先把所有东西拉回封装自己的坐标系。
        """
        pads = board.pads_for_component(designator)
        reading = MarkReading(designator=designator)
        by_pin = {str(getattr(p, "pin_number", "")): p for p in pads}

        plus_pad = by_pin.get(str(polarity.plus_pin)) if polarity.plus_pin else None
        minus_pad = by_pin.get(str(polarity.minus_pin)) if polarity.minus_pin else None
        if plus_pad is not None and minus_pad is not None:
            cx = (plus_pad.local_x + minus_pad.local_x) / 2.0
            cy = (plus_pad.local_y + minus_pad.local_y) / 2.0
            dx = plus_pad.local_x - minus_pad.local_x
            dy = plus_pad.local_y - minus_pad.local_y
            length = math.hypot(dx, dy) or 1.0
            ux, uy = dx / length, dy / length
        else:
            # 没有声明脚号：轴中点 = 全部焊盘中心的均值，投影轴 = pad1→pad2。
            if not pads:
                reading.notes.append("这颗件在板上没有焊盘，方向标记无从测量")
                return reading
            cx = sum(p.local_x for p in pads) / len(pads)
            cy = sum(p.local_y for p in pads) / len(pads)
            ordered = sorted(pads, key=lambda p: str(getattr(p, "pin_number", "")))
            ux, uy = (1.0, 0.0)
            if len(ordered) >= 2:
                dx = ordered[1].local_x - ordered[0].local_x
                dy = ordered[1].local_y - ordered[0].local_y
                length = math.hypot(dx, dy) or 1.0
                ux, uy = dx / length, dy / length

        elements: list[tuple] = []
        for shape in board.silk_shapes_for(designator):
            if str(shape.layer_kind or "") not in SILK_KINDS:
                continue
            centre = shape.centroid(local=True)
            if centre is None:
                continue
            elements.append(
                (
                    _element_key(shape),
                    centre.x,
                    centre.y,
                    f"{shape.kind} on {shape.layer_kind or 'unclassified layer'} "
                    f"at ({centre.x:.1f}, {centre.y:.1f}) local",
                    shape,
                )
            )
        for text in board.silk_texts_for(designator):
            if text.source != "footprint" or text.layer_kind not in SILK_KINDS:
                continue
            elements.append(
                (
                    _element_key(text),
                    text.local_x,
                    text.local_y,
                    f"printed text {text.text!r} at ({text.local_x:.1f}, "
                    f"{text.local_y:.1f}) local",
                    text,
                )
            )
            if text.text == "+":
                reading.plus_marks.append((text.local_x, text.local_y))
            elif text.text in ("-", "－", "_"):
                reading.minus_marks.append((text.local_x, text.local_y))
        reading.marked_elements = len(elements)

        unpaired = unpaired_elements(elements, (cx, cy))
        reading.unpaired = [entry[3] for entry in unpaired]
        if unpaired:
            # 投影：正 = 无配对图元整体偏向 plus 脚那一头。
            reading.side = sum(
                ((entry[1] - cx) * ux + (entry[2] - cy) * uy) for entry in unpaired
            ) / len(unpaired)

        # marking 层（非丝印）的 1 脚圆点：只作读数，不算方向标记。
        for shape in board.silk_shapes_for(designator):
            if str(shape.layer_kind or "") not in MARKING_KINDS:
                continue
            centre = shape.centroid(local=True)
            if centre is None:
                continue
            nearest, distance = None, None
            for pin, pad in sorted(by_pin.items()):
                gap = math.hypot(pad.local_x - centre.x, pad.local_y - centre.y)
                if distance is None or gap < distance:
                    nearest, distance = pin, gap
            reading.dot_pin, reading.dot_distance = nearest, distance
            break

        if reading.plus_marks and by_pin:
            reading.plus_mark_pin = self._nearest_pin(reading.plus_marks[0], by_pin)
        if reading.minus_marks and by_pin:
            reading.minus_mark_pin = self._nearest_pin(reading.minus_marks[0], by_pin)
        return reading

    @staticmethod
    def _nearest_pin(point: tuple[float, float], by_pin: dict) -> str | None:
        nearest, distance = None, None
        for pin, pad in sorted(by_pin.items()):
            gap = math.hypot(pad.local_x - point[0], pad.local_y - point[1])
            if distance is None or gap < distance:
                nearest, distance = pin, gap
        return nearest

    # -- findings ---------------------------------------------------------

    def _mismatch(self, ctx, readings) -> list[Finding]:
        """封装自己写的 ``+``/``-`` 丝印，与原理图声明的极性脚对不上 → ERROR。

        这是本规则唯一不需要任何约定的一条：两边都是**声明**——封装说「丝印的
        ``+`` 在这头」，原理图说「``+`` 是那只脚」。对不上就是这颗件的丝印会
        把装配引到反的方向去。
        """
        findings: list[Finding] = []
        for designator, polarity, reading, _sch in readings:
            if polarity.plus_pin is None:
                continue
            problems: list[str] = []
            plus_sign = "+"
            if reading.plus_mark_pin and reading.plus_mark_pin != str(polarity.plus_pin):
                problems.append(
                    f"丝印 {plus_sign!r} 字压在 pin {reading.plus_mark_pin} 一侧，"
                    f"而原理图的 {plus_sign} 脚是 pin {polarity.plus_pin}"
                )
            if reading.minus_mark_pin and reading.minus_mark_pin != str(polarity.minus_pin):
                problems.append(
                    f"丝印 '-' 字压在 pin {reading.minus_mark_pin} 一侧，"
                    f"而原理图的 - 脚是 pin {polarity.minus_pin}"
                )
            if not problems:
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} {designator} 丝印极性标记与原理图极性脚不符："
                        + "；".join(problems)
                        + "——按丝印装件会把这颗件装反"
                    ),
                    evidence=[
                        f"designator {designator}, footprint {self._footprint_name(ctx, designator)}",
                        f"schematic polarity: {polarity.declaration} "
                        f"（来源：{polarity.declared_by}）",
                        f"footprint silkscreen + mark at local "
                        f"{reading.plus_marks[0] if reading.plus_marks else '(none)'}"
                        f" → nearest pad pin {reading.plus_mark_pin}",
                        f"footprint silkscreen - mark at local "
                        f"{reading.minus_marks[0] if reading.minus_marks else '(none)'}"
                        f" → nearest pad pin {reading.minus_mark_pin}",
                        "判据：封装自带的 +/− 丝印字是**封装自己的声明**（不是形状推断），"
                        "原理图的极性脚是**符号脚名**的声明；两边都是声明事实，"
                        "所以这条不需要任何约定就能判死",
                    ],
                    target=FindingTarget(component_ref=designator),
                )
            )
        return findings

    def _no_mark(self, ctx, readings) -> list[Finding]:
        """丝印层图元在换脚下与自身重合 → 装配无从判断方向 → ERROR。"""
        findings: list[Finding] = []
        for designator, polarity, reading, _sch in readings:
            if reading.marked_elements == 0:
                detail = (
                    "这颗件在板上没有落在丝印层的图元（封装没画丝印，或丝印画在"
                    "本规则不认的层上）"
                )
            elif not reading.unpaired:
                detail = (
                    f"{reading.marked_elements} 个丝印层图元在「绕两只极性脚中点"
                    "转 180°」下全部找得到配对——把件反着装，板子看起来一模一样"
                )
            else:
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} {designator} 是极性器件却没有印刷方向标记："
                        f"{detail}"
                    ),
                    evidence=[
                        f"designator {designator}, footprint {self._footprint_name(ctx, designator)}",
                        f"polarity: {polarity.declaration}（来源：{polarity.declared_by}）",
                        f"silk-layer primitives compared: {reading.marked_elements}",
                        f"marking-layer pin-1 dot (not printed legend): pin "
                        f"{reading.dot_pin} at {reading.dot_distance:.1f} mil"
                        if reading.dot_distance is not None
                        else "marking-layer pin-1 dot: none",
                        "判据：换脚 = 绕两只极性脚的中点转 180°，也就是「把这颗件反着"
                        "装」这个物理动作；图元级比较，见 unpaired_elements 的说明",
                    ],
                    target=FindingTarget(component_ref=designator),
                )
            )
        return findings

    def _inconsistent(self, ctx, readings) -> list[Finding]:
        """同一块板、同一封装名、同一面的多颗极性件，方向是否一致 → INFO（岳 2026-10-11 裁：方向不统一只提醒、不算问题，故从 WARN 降为 INFO）。"""
        groups: dict[tuple[str, int], list[tuple[str, Polarity, MarkReading, float]]] = {}
        for designator, polarity, reading, _sch in readings:
            placement = ctx.board.component(designator)
            if placement is None:
                continue
            direction = axis_direction(ctx.board.pads_for_component(designator), polarity)
            if direction is None:
                continue
            angle = round(math.degrees(math.atan2(direction[1], direction[0])) % 360.0, 1)
            name = self._footprint_name(ctx, designator)
            face = int(getattr(placement, "layer_id", 1) or 1)
            groups.setdefault((name, face), []).append((designator, polarity, reading, angle))

        findings: list[Finding] = []
        for (name, face), members in sorted(groups.items()):
            if len(members) < 2:
                continue
            angles = {angle for _d, _p, _r, angle in members}
            if len(angles) < 2:
                continue
            reference = members[0][3]
            lines = []
            for designator, polarity, _reading, angle in members:
                delta = round((angle - reference) % 360.0, 1)
                lines.append(
                    f"{designator}: 极性轴 {angle}°（相对 {members[0][0]} 差 {delta}°）"
                    + (
                        f"，极性脚 {polarity.plus_pin}(+) / {polarity.minus_pin}(-)"
                        if polarity.plus_pin
                        else "，原理图没有声明极性脚（轴按 pad1→pad2 算）"
                    )
                )
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} 上 {len(members)} 颗极性器件共用封装 "
                        f"{name!r}（{self._face_name(face)}），方向却有 "
                        f"{len(angles)} 种：{sorted(angles)}"
                        "——同封装同朝向是生产工艺习惯，不统一只作提醒（岳 2026-10-11 裁：降 INFO）"
                    ),
                    evidence=lines
                    + [
                        "方向 = 极性轴在板坐标里的方向（由两只极性脚的实际焊盘中心"
                        "算出，含 180° 与 90° 两种差；同一面内比较，跨面不比——"
                        "底面器件在板坐标里是同一个平面内的旋转，物理上却是翻过来的",
                        "分组键是**封装名**（工程师说的「同封装」），不是封装文档 uuid："
                        "同一个名字在本工程库里可能对应不止一个文档（151 的 WARN "
                        "就是这条），而位号视角看的是名字",
                        "本规则的 source 是 house rule 待裁：任务书把「同封装同朝向」"
                        "定为生产工艺要求，但**方向差多少算不统一**没有标准可查，"
                        "这里一律按「有差就报」",
                    ],
                )
            )
        return findings

    def _unnameable(self, ctx, unnameable) -> list[Finding]:
        """库件说有极性、符号脚名却只有 1/2 → 丝印标记无从与原理图核对（INFO）。"""
        if not unnameable:
            return []
        lines = [
            f"{designator}: {declaration}（封装 {self._footprint_name(ctx, designator)}）"
            for designator, _polarity, declaration in unnameable
        ]
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"{ctx.board_title} 有 {len(unnameable)} 颗极性器件的原理图侧"
                    "**没有声明哪只脚是正极**（符号脚名只有 1/2）：丝印上的方向标记"
                    "无法与原理图核对，装配只能靠丝印本身——这是原理图符号的事实缺口，"
                    "本规则如实记下、不猜"
                ),
                evidence=lines
                + [
                    "判极性走的是 DEVICE 库件的 Type 词（声明事实），不是形状推断；"
                    "但**哪只脚是正极**只有符号脚名说得出来，库件类型词不说",
                    "后果：本规则对这几颗件只能报读数，不能判「标记与极性脚一致」",
                ],
            )
        ]

    def _summary(self, ctx, readings, unnameable) -> Finding:
        named = [r for r in readings if r[1].plus_pin is not None]
        footprints = sorted({self._footprint_name(ctx, d) for d, _p, _r, _s in readings})
        marked = [r for r in readings if r[2].unpaired]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{ctx.board_title} 极性器件读数：{len(readings)} 颗极性器件"
                f"（其中 {len(named)} 颗原理图声明了极性脚、"
                f"{len(unnameable)} 颗只有库件类型词），"
                f"涉及 {len(footprints)} 种封装名，"
                f"量出印刷方向标记的 {len(marked)} 颗"
            ),
            evidence=[
                "极性来源：①原理图符号脚名（+/-、K/A、C/A 三种写法，成对才认）"
                "②DEVICE 库件的 Type 词与 Polarity 属性；Polarity 写着「双向」的器件"
                "（实测两颗 SMCJ TVS）方向不敏感，本规则不判",
                "方向标记读的是**丝印层**图元（TOP_SILK/BOT_SILK，按本文档自己的"
                "LAYER 表判读）；marking 层（实测 id 49）的 1 脚圆点**不是印在板上的"
                "丝印**，只作为「1 脚在哪一头」的读数",
                "封装名清单：" + (", ".join(footprints) if footprints else "(无)"),
                "没有极性器件的板（实测 ROBOT ctrl FOC）这条报 0 颗——这是读数，"
                "不是「跳过」",
            ],
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _footprint_name(ctx, designator: str) -> str:
        component = (getattr(ctx.pcb_model, "components", {}) or {}).get(designator)
        name = str(getattr(component, "footprint", "") or "") if component else ""
        if name:
            return name
        placement = ctx.board.component(designator) if ctx.board else None
        uuid = str(getattr(placement, "footprint", "") or "") if placement else ""
        return uuid or "(未指定封装)"

    @staticmethod
    def _face_name(face: int) -> str:
        return {1: "顶层", 2: "底层"}.get(int(face), f"层 {face}")
