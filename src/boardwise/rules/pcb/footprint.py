"""封装一致性：原理图声明的封装 vs PCB 实际摆的 FOOTPRINT（任务 151，E 阶段第一棒）。

路线图（``tasks/122-pcb-review-roadmap.md`` 第三步「器件检查」）的第一项。一件
投板级的事：**BOM 按原理图声明的封装买的件，要贴到 PCB 上那个 FOOTPRINT 的焊盘
上**。两边对不上，板子造出来就是贴不上——所以这一条不查电气，只查「这颗料和这块
焊盘是不是同一件事」。

架构决策 5 的落点（岳 2026-10-07 裁：「PCB 检查必须桥接原理图检查」）
=================================================================

本模块**不猜器件、不看形状**：判定的两造都是**声明事实**——

* 原理图侧 = ``ctx.model`` 里这块板的 :class:`~boardwise.core.model.Component`
  的 ``footprint`` 字段（``DEVICE`` 库件的 ``Supplier Footprint``，退化为实例
  ``Footprint`` 属性；见 ``parsers/schematic.py::DEVICE_ATTR_FIELDS``）。这是工程
  师在原理图上**声明的封装**，也是 BOM 上写的那个名字；
* PCB 侧 = 落到板上的 **FOOTPRINT 文档**：名字取文档 ``META.title``，焊盘取文档里
  的 ``PAD`` 记录按 COMPONENT 位姿实例化后的几何（``parsers/epru.py``）。

两边**不是一套词汇**，这一点是本模块的全部难点，也是它不做「字符串相等就判错」的
原因（那样在毕设FOC 1.0.0 上会报出 100+ 条假 ERROR）。实测三块验收板的词汇对照：

===========================  ==========================================  ============
原理图声明（Supplier Footprint）  PCB FOOTPRINT 文档 title                 谁写的
===========================  ==========================================  ============
``0603``                      ``C0603`` / ``R0603``                       立创商城料号族
``0805``                      ``C0805`` / ``LED0805-R-RD``                同上
``DFN(5x6)``                  ``PDFN-8_L5.8-W5.1-P1.27-LS6.1-BL``         厂商 + 立创内部
``SO-8``                      ``PG-DSO-8_L5.0-W4.0-P1.27-LS6.0-BL``       英飞凌 + 立创内部
``LQFP-64(10x10)``            ``LQFP-64_L10.0-W10.0-P0.50-LS12.0-BL``     一致
``-,D5xL11mm``                ``CAP-TH_BD5.0-P2.00-D0.8-FD``              同上
===========================  ==========================================  ============

所以判定走**可比 token**，不比整串：

1. **焊盘数**（最硬，直接量出来的）：原理图这只器件声明的引脚数（
   ``Component.pins`` 的不同编号数） vs PCB 上这个 FOOTPRINT 实例化出的焊盘数
   （``board.pads`` 里属于该位号的不同 ``pin_number`` 数）。这是「买回来的封装
   脚数不对」，量出来的东西，不受词汇影响。
2. **芯片尺寸码**：``0603``/``0805``/``1206``/``2512``/``1008``… 这类立创芯片封装
   的**四位数尺寸码**，两边名字里都出现时逐字比较（``C0603`` 里的 ``0603`` 也算）。
   对不上就是实物尺寸不同——**毕设FOC 1.0.0 上的真实历史问题就是这一条**
   （见 :data:`CHIP_SIZE_CODES` 的注释）。
3. **封装族**：把封装名里认得出的**族词**（``SOIC``/``SOP``/``DSO`` 归一为
   SOIC 一族，``DFN``/``PDFN``/``QFN`` 归为一族……见 :data:`PACKAGE_FAMILIES`）
   两边都认得出时比较（``SOIC-8`` vs ``TSSOP-16`` 会在这里报出来）。**刻意不从
   名字里读脚数**：``SOT-23-5`` 的 23、``TO-252`` 的 252、``DFN(5x6)`` 的 5
   都不是脚数，从名字猜脚数会在这三个上全猜错——脚数走上面那条焊盘数的硬读法。
4. **尺寸数**：两边名字里都有的长度数（``2.5``/``5``/``1.25``）——这是**弱证据**，
   只用来判「一致」，不用来判错（两个不相干的封装也可能共享一个数字）。
5. 以上都无从比较（一边没声明、或两边没有共同的可比 token）→ **INFO**，把两个
   字符串原样写出来并说明无从比较——UNKNOWN 纪律（126 钉 6），不猜。

**命名与几何**：尺寸码/封装族比的是**名字**，焊盘数比的是**几何**。名字里看不出来
的东西（例如同一个 ``C0402`` 名字在工程库里对应两套不同焊盘几何）另立 WARN：
:data:`AMBIGUOUS_NAME_WARN` 那一路——「同名封装但 pad 尺寸实测不是同一件事」，
原理图侧的名字**不指向唯一一个物理封装**，那是个提醒而不是缺陷。

**器件缺失**（原理图有、PCB 没放 / 反之）走既有 conn 类口径
=================================================================

``conn-library-pins``（``rules/facts.py``）的口径是：**对称漂移，两个方向都报，
ERROR**。这里照办，但按 **板** 对齐（PCB 文档的 ``META.board`` 指向原理图
:class:`~boardwise.core.model.BoardRef` 的 uuid，见
:func:`boardwise.engines.pcbreview._pcb_documents`），所以一块板上「原理图有、
PCB 没放」的器件只在本板报一次；本项目里同名位号在别的板上是另一颗件（040b §WI-2），
不跨板重复报。

每个器件**至多一条** finding：焊盘数 → 尺寸码 → 封装族 依次判，第一条命中即出，
避免一个缺陷被报两遍。

本模块**不 NET 任何东西、不碰 bridge**：纯离线，读同一份 ``.epro2`` 的两个视图。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from .base import PcbReviewContext, PcbRule
from .distance import _measurement, _mil

__all__ = [
    "AMBIGUOUS_NAME_WARN",
    "CHIP_SIZE_CODES",
    "DO_214_OUTLINES",
    "PACKAGE_FAMILIES",
    "FootprintConsistency",
    "NAMELESS_FOOTPRINTS",
    "chip_size_code",
    "dimension_tokens",
    "package_family",
    "tokenize",
]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

#: **芯片封装的尺寸码**（英制四位码），立创商城的 ``Supplier Footprint`` 与立创
#: 内部的 FOOTPRINT title 都用它标尺寸。两边名字里都出现、且不同 → 实物尺寸不同。
#:
#: 毕设FOC 1.0.0 上的**真实历史问题**就是这一条：``C17`` / ``C8`` / ``C98`` /
#: ``C99`` 四颗电容在原理图上声明的是 ``0805``，PCB 上摆的是 ``C0603``
#: （实测焊盘 31.496 × 35.433 mil，而这块板自己的 ``C0805`` 焊盘是
#: 55.512 × 53.150 mil）——按 BOM 买 0805 的件回来，贴不到 0603 的焊盘上。
#: 手艺上它是「画原理图时抄了隔壁那颗、摆板时换了封装」这一类错，肉眼很难在
#: 122 个器件里看出来。
#:
#: 表里同时收英制（``0603`` = 0.06×0.03 in）与对应的公制码（``1608`` =
#: 1.6×0.8 mm），因为两种写法都在立创的库里出现；收进来的是**尺寸族**，
#: 不是某一家厂商的型号。**收进去的每一码都能在封装的尺寸码位置上出现**——
#: ``1008``（电感）与 ``2512``（电阻/保险丝）是同族的更大尺寸，不是型号。
CHIP_SIZE_CODES: frozenset[str] = frozenset(
    {
        # 英制
        "01005", "0201", "0402", "0603", "0805", "1206", "1210", "1218",
        "1812", "2010", "2512", "1008",
        # 公制（与上面同尺寸的另一种写法）
        "1005", "1608", "2012", "3216", "3225", "2016",
    }
)

#: 封装**族词** → 归一后的族。判定的是**能不能用同一套 land pattern 贴**
#: （fit 族），不是「这两个封装完全等价」，所以 1.27 mm 间距的 SOIC 家族
#: （``SO``/``SOIC``/``SOP``/``DSO``，英飞凌的 ``PG-DSO-8`` 就是 SOIC-8）归一为
#: 一族；``DFN``/``PDFN``/``QFN``/``WQFN`` 这一组归为一族（都是无引线四边/两边
#: 焊盘 + 可选中散热焊盘）。间距真的不同的族（``SOIC`` vs ``TSSOP``/``MSOP``，
#: ``LQFP`` vs ``QFN``）**不归一**——那两个贴不上同一块焊盘。
#:
#: 这张表是**三块验收板的词汇对照**加常用封装名拼出来的：毕设FOC 1.0.0 的
#: ``DFN(5x6)`` ↔ ``PDFN-8_…``、ROBOT 的 ``SO-8`` ↔ ``PG-DSO-8_…`` 都必须
#: 认成同族，否则规则第一天就报假错。表里没有的词 = 认不出 = 不比较（INFO），
#: 不许猜。
PACKAGE_FAMILIES: dict[str, str] = {
    # 1.27 mm 间距小外形
    "SO": "soic", "SOIC": "soic", "SOICW": "soic", "SOP": "soic",
    "SOW": "soic", "DSO": "soic", "SOJ": "soic",
    # 细间距小外形（0.65 / 0.5 mm）
    "MSOP": "msop", "SSOP": "ssop", "TSSOP": "tssop", "HTSSOP": "tssop",
    "QSOP": "ssop",
    # 无引线（两边/四边焊盘）
    "DFN": "dfn-qfn", "PDFN": "dfn-qfn", "QFN": "dfn-qfn", "PQFN": "dfn-qfn",
    "UDFN": "dfn-qfn", "VQFN": "dfn-qfn", "WQFN": "dfn-qfn", "SON": "dfn-qfn",
    # 四边翼形引线
    "LQFP": "lqfp", "TQFP": "lqfp", "QFP": "lqfp", "PQFP": "lqfp",
    # 通孔
    "DIP": "dip", "PDIP": "dip", "SIP": "dip", "HDIP": "dip",
    # 小外形二极管/三极管
    "SOT": "sot", "SOD": "sod", "DPAK": "to", "D2PAK": "to", "TO": "to",
    # 二极管外形（JEDEC DO-214 ↔ SMA/SMB/SMC 是同一批东西的两种写法）
    "SMA": "sma", "SMB": "smb", "SMC": "smc",
    # 球栅阵列
    "BGA": "bga", "LFBGA": "bga", "TFBGA": "bga", "WLCSP": "bga", "CSP": "bga",
    # 晶振 / 振荡器
    "XTAL": "xtal", "CRYSTAL": "xtal", "OSC": "xtal",
}

#: JEDEC ``DO-214`` 外形名 → 对应的 ``SM*`` 名字，两者是同一种二极管封装的两种
#: 写法（1.1.0 的原理图写 ``DO-214AB``、PCB 写 ``SMC_…``）。只认这三个带字母
#: 后缀的全名：``DO-214`` 单独出现、或后缀不在表里，都**不认**——那可能是别的
#: 外形，认错会把不一致说成一致。
DO_214_OUTLINES: dict[str, str] = {"AB": "smc", "AA": "smb", "AC": "sma"}

#: 原理图侧「没声明封装」的写法。``-`` 是实测值（ROBOT 的 ``U5`` 声明 ``-``，
#: PCB 上摆的是 ``热焊盘``），``null``/``None`` 是库件属性的占位（
#: ``parsers/epro2_model.py::_NULL_LITERALS`` 的同一套写法）。
NAMELESS_FOOTPRINTS: frozenset[str] = frozenset({"", "-", "null", "none", "n/a", "na"})

#: 库件 uuid 的样子：16 / 32 位十六进制，或用 ``_`` 接起来的两段（
#: ``308cffdb9f930ec1_c4dc0f6ef1616584702a893414cd16c7`` 是实测的螺丝封装 id）。
#:
#: 它出现在**原理图侧 ``Component.footprint``** 里是模型层的一处噪声：llc 板上
#: ``C1``/``C2``/``C5``/``C6`` 的 footprint 字段实测值是
#: ``'0733d61b8033ac9c'``——那是库件 uuid，不是封装名（``parsers/schematic.py``
#: 在 DEVICE 库件没写 ``Supplier Footprint`` 时退化为实例的 ``Footprint`` 属性，
#: 而那几个实例的该属性存的是 id）。本规则**不修模型层**，只认出来并如实说
#: 「这一侧没有封装名可比」——拿它去和 PCB 的名字比对，会拿 uuid 里的十六进制
#: 片段当尺寸数，报出一堆看着像测量的废话。
LIBRARY_ID_RE = re.compile(
    r"^(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{32})(?:_(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{32}))*$"
)

#: 「同名封装、实测焊盘几何却是两件事」这一 WARN 的口径说明（写进 finding）。
AMBIGUOUS_NAME_WARN = (
    "同一个封装名在本工程库里对应文档不止一个、且实测焊盘几何不同——"
    "名字不指向唯一一个物理封装，按 BOM 备料时无法确定买哪一种"
)

_TOKEN_RE = re.compile(r"[A-Za-z]+|[0-9]+(?:\.[0-9]+)?")


def tokenize(name: str) -> list[str]:
    """把封装名切成 token：字母段与数字段各自成 token，顺序保留。

    ``"C0603"`` → ``["C", "0603"]``；``"SOIC-8_L4.9-W3.9-P1.27-LS6.0-BL"`` →
    ``["SOIC", "8", "L", "4.9", "W", "3.9", "P", "1.27", "LS", "6.0", "BL"]``。
    切法就是「字母一串、数字一串」，没有别的理解——封装名的写法太杂，任何
    更聪明的切法都是在替厂商发明语法。
    """
    return _TOKEN_RE.findall(str(name or ""))


def _normalize_code(token: str) -> str:
    """尺寸码的规范写法：纯数字的四位码去掉前导零以外的差异。

    ``"0603"`` 与 ``"603"`` 是同尺寸的两种写法（立创的库里两种都见过），
    所以编码前补零到四位。非四位数一律原样返回，由 :data:`CHIP_SIZE_CODES`
    决定它算不算尺寸码。
    """
    if token.isdigit() and len(token) < 4:
        return token.zfill(4)
    return token


def chip_size_code(name: str) -> str | None:
    """名字里出现的**芯片尺寸码**，没有则 ``None``。

    只认 :data:`CHIP_SIZE_CODES` 里的码——``C0603`` 的 ``0603``、
    ``LED0805-R-RD`` 的 ``0805``、``L1008`` 的 ``1008`` 都算。名字里同时出现
    两个码（少见）取第一个，因为立创的写法是「前缀 + 尺寸码 + 后缀」。
    """
    for token in tokenize(name):
        if _normalize_code(token) in CHIP_SIZE_CODES:
            return _normalize_code(token)
    return None


def package_family(name: str) -> str | None:
    """名字里的**封装族**，认不出则 ``None``。

    只认 :data:`PACKAGE_FAMILIES` 里的族词，取**第一个**出现的
    （``SOIC-8_L4.9-…`` → ``soic``，``PG-DSO-8_L5.0-…`` → ``soic`` 因为
    ``PG`` 不在表里而 ``DSO`` 在）。**刻意不从这里读脚数**：``SOT-23-5`` 的
    23 是族名的一部分、``TO-252`` 的 252 是外形代号、``DFN(5x6)`` 的 5 是毫米
    外形——从名字里猜脚数的规则会在这三个上全猜错，而脚数本来就有一条硬读法
    （焊盘数，见 :class:`FootprintConsistency`），所以名字这一路只判族。

    ``DO-214`` 那一路单独看：JEDEC 的 ``DO-214AB`` / ``AA`` / ``AC`` 分别是
    ``SMC`` / ``SMB`` / ``SMA`` 三种二极管外形（1.1.0 的原理图写
    ``DO-214AB``，PCB 写 ``SMC_L6.9-W5.9-LS7.9-BI``，是同一个东西的两种
    写法），所以名字里出现 ``DO-214AB`` 时按 ``smc`` 认。**只认这三个带字母
    后缀的全名**——光看到 ``DO`` 或 ``214`` 不认，那可能是别的东西。
    """
    tokens = [token.upper() for token in tokenize(name)]
    for index, token in enumerate(tokens):
        if token == "DO" and index + 2 < len(tokens) and tokens[index + 1] == "214":
            outline = DO_214_OUTLINES.get(tokens[index + 2])
            if outline is not None:
                return outline
        family = PACKAGE_FAMILIES.get(token)
        if family is not None:
            return family
    return None


def dimension_tokens(name: str) -> set[float]:
    """名字里的**尺寸数**（弱证据）：所有带小数点的数，加所有 ≥2 的整数。

    带小数点的数（``2.54``/``1.25``/``L2.5``）几乎必然是尺寸——立创的封装名里
    小数点只用来写毫米。整数要求 ≥2（``1`` 太常见）且不超过四位。

    **芯片尺寸码不算尺寸数**（``C0603`` 的 ``0603``、``L1008`` 的 ``1008``）：
    那是 :func:`chip_size_code` 那条硬证据管的，混进这里会把 ``0805`` 说成
    「两边共有的尺寸数 805」——一句看起来像测量、其实是巧合的话。尺寸数是弱
    证据，**只用来判「一致」，不用来判错**，所以它宁可少收一点。
    """
    out: set[float] = set()
    for token in tokenize(name):
        if "." in token:
            try:
                out.add(float(token))
            except ValueError:  # pragma: no cover — the regex already guarantees it
                continue
        elif (
            token.isdigit()
            and 2 <= int(token)
            and len(token) <= 4
            and _normalize_code(token) not in CHIP_SIZE_CODES
        ):
            out.add(float(int(token)))
    return out


# ---------------------------------------------------------------------------
# one pair's reading
# ---------------------------------------------------------------------------

#: 一条对账结果的状态。``"n/a"`` 不是「通过」：它是「无从比较」（UNKNOWN 纪律）。
VERDICT_PAD_COUNT = "pad-count"
VERDICT_SIZE_CODE = "size-code"
VERDICT_PACKAGE = "package"
VERDICT_AGREE = "agree"
VERDICT_UNDECIDABLE = "undecidable"


@dataclass
class _Footprint:
    """PCB 侧一个 FOOTPRINT 的读数：名字、文档、焊盘几何。"""

    #: ``META.title``，也就是 PCB 实际摆的封装名（``C0603``）。``""`` = 读不出。
    name: str = ""
    #: ``ATTR key="Footprint"`` 指向的 FOOTPRINT 文档 uuid（``""`` = 压根没指定）。
    uuid: str = ""
    #: ``(pin_number, width, height, local_x, local_y)``，按编号排序。
    pads: tuple[tuple[str, float, float, float, float], ...] = ()

    def pin_numbers(self) -> set[str]:
        return {pad[0] for pad in self.pads if pad[0]}

    def geometry_key(self) -> tuple:
        """实测几何的指纹——「同名封装」到底是不是同一件事靠它判。"""
        return tuple(
            sorted(
                (num, round(width, 3), round(height, 3), round(x, 3), round(y, 3))
                for num, width, height, x, y in self.pads
            )
        )

    def pad_span(self) -> float:
        """焊盘中心两两最大距离（mil）——「间距」的量，也是 0603/0805 的分水岭。"""
        span = 0.0
        for left in self.pads:
            for right in self.pads:
                dx = left[3] - right[3]
                dy = left[4] - right[4]
                span = max(span, (dx * dx + dy * dy) ** 0.5)
        return span

    def pad_size_line(self) -> str:
        """焊盘尺寸的一句话描述（Evidence 用）。"""
        if not self.pads:
            return "no pad instantiated"
        widths = [pad[1] for pad in self.pads]
        heights = [pad[2] for pad in self.pads]
        return (
            f"{len(self.pads)} pad(s), size {min(widths):.3f}×{min(heights):.3f}"
            f"…{max(widths):.3f}×{max(heights):.3f} mil, span {self.pad_span():.3f} mil"
        )


@dataclass
class _Verdict:
    """一条对账的结论：状态 + 结构化的两造 + 证据行。"""

    designator: str
    state: str
    severity: str | None
    sch_name: str = ""
    pcb: _Footprint = field(default_factory=_Footprint)
    sch_pins: int = 0
    #: 原理图那颗件的 MPN——尺寸码不符时用它做第二份证据（``CC0805KRX7R9BB104``
    #: 自己就写着 0805），让读者能分辨「是 PCB 摆错了」还是「原理图抄错了」。
    mpn: str = ""
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    def state_label(self) -> str:
        """这条结论在报告里叫什么（finding 前缀用的同一套词）。"""
        return {
            VERDICT_PAD_COUNT: "焊盘数不符",
            VERDICT_SIZE_CODE: "封装尺寸码不符",
            VERDICT_PACKAGE: "封装族不符",
            VERDICT_AGREE: "一致",
            VERDICT_UNDECIDABLE: "无从比较",
            "no-pcb-footprint": "PCB 侧读不出封装",
        }.get(self.state, self.state)


def _describe(name: str) -> str:
    """把封装名念成一句话，空的就是「没声明」。"""
    text = str(name or "").strip()
    return repr(text) if text else "(空——没有声明封装)"


def _compare_names(sch_name: str, pcb_name: str) -> tuple[str, str]:
    """只比名字：``(状态, 说明)``。状态 ∈ 尺寸码不符 / 族不符 / 一致 / 无从比较。

    顺序就是优先级：尺寸码比封装族硬（``0805`` vs ``C0603`` 是实物尺寸不同，
    封装族两边都是 ``None``），封装族比尺寸数硬（尺寸数是弱证据，只判一致）。
    """
    sch_code, pcb_code = chip_size_code(sch_name), chip_size_code(pcb_name)
    if sch_code and pcb_code and sch_code != pcb_code:
        return (
            VERDICT_SIZE_CODE,
            f"原理图声明尺寸码 {sch_code}，PCB 摆的是 {pcb_code}",
        )

    sch_family, pcb_family = package_family(sch_name), package_family(pcb_name)
    if sch_family and pcb_family and sch_family != pcb_family:
        return (
            VERDICT_PACKAGE,
            f"原理图声明的封装族 {sch_family} ≠ PCB 的 {pcb_family}",
        )

    if sch_code and pcb_code:
        return VERDICT_AGREE, f"尺寸码 {sch_code} 一致"

    if sch_family and pcb_family:
        return VERDICT_AGREE, f"封装族 {sch_family} 一致"

    shared = dimension_tokens(sch_name) & dimension_tokens(pcb_name)
    if shared:
        return (
            VERDICT_AGREE,
            "两边共有的尺寸数 "
            + ", ".join(f"{value:g}" for value in sorted(shared))
            + "（弱证据：尺寸数只用来判一致，不用来判错）",
        )

    sch_tokens = dimension_tokens(sch_name)
    pcb_tokens = dimension_tokens(pcb_name)
    if not sch_tokens or not pcb_tokens:
        return (
            VERDICT_UNDECIDABLE,
            "两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），"
            "本规则不比较",
        )
    return (
        VERDICT_UNDECIDABLE,
        "两边都写了尺寸数但没有交集（"
        + ", ".join(f"{v:g}" for v in sorted(sch_tokens))
        + " vs "
        + ", ".join(f"{v:g}" for v in sorted(pcb_tokens))
        + "）；尺寸数是弱证据，不足以判错",
    )


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


class FootprintConsistency(PcbRule):
    """原理图声明的封装与 PCB 实际摆的 FOOTPRINT 对账（任务 151）。

    Finding 只有五类，每类都有确定的证据来源：

    ===================  =======  ==============================================
    类别                 级别     判据
    ===================  =======  ==============================================
    焊盘数不符           ERROR    原理图声明的引脚数 ≠ PCB FOOTPRINT 实例化出的
                                  焊盘数（都从模型/几何量出来，与命名无关）
    尺寸码不符           ERROR    两边名字里的芯片尺寸码不同（``0805`` vs ``0603``）
    封装族不符           ERROR    两边认得出的封装族不同（``SOIC-8`` vs ``TSSOP-16``）
    同名封装几何不一     WARN     同一个封装名在本工程库里对应两套以上实测焊盘几何
    器件缺失             ERROR    原理图这块板有、PCB 没放（或反之）——conn 类口径
    ===================  =======  ==============================================

    另有 INFO 两类：**无从比较**（UNKNOWN 纪律，逐条列出并原样写出两个名字）与
    **本板对账小结**（一致/各不符类的条数，一条一处，避免 122 个器件刷屏——
    对齐件的清单看 ``target`` 与小结行，异常件才有自己的 finding）。

    对账**按板**：PCB 文档的 ``META.board`` 指向原理图 ``BoardRef.uuid``
    （:func:`boardwise.engines.pcbreview._pcb_documents` 把它读进
    :attr:`PcbReviewContext.board_uuid`），所以多板工程里 ``C1`` 只在它自己那
    块板上和自己的原理图板比，不会跨板串味（040b §WI-2）。板链读不出来时
    （PCB 文档的 META 没有 ``board``、或调用方没给带 ``boards`` 的模型）本规则
    **只报 INFO 说明读不出板链**，不猜、不按名号相似度硬配。

    没有任何阈值需要岳裁定：焊盘数/尺寸码/封装族都是**相等/不等**的判定，
    不涉及「多少 mil 算近」这类度数。
    """

    id = "pcb-footprint-consistency"
    title = "原理图声明的封装与 PCB 实际摆的 FOOTPRINT 一致"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10-11 待裁）：原理图 'Supplier Footprint' vs PCB FOOTPRINT 文档 title"

    # -- context plumbing -------------------------------------------------

    @staticmethod
    def _schematic_board(ctx: PcbReviewContext) -> tuple[object | None, str]:
        """这块 PCB 文档对应哪个原理图板：``(BoardModel | None, 读不出来的原因)``。

        三条路，按可靠性：

        1. PCB 文档的 ``META.board``（在 ctx 里是 ``board_uuid``）+ 调用方给的
           项目模型（有 ``boards``）→ 按 uuid 精确命中。这是**声明事实**，不是
           猜——实测三块验收板 6 个 PCB 文档全部命中（毕设FOC 1.0.0 的
           ``PCB1``/``PCB2``、1.1.0 的 ``PCB3``/``PCB1``/``PCB2``、ROBOT 的
           ``PCB1``）。
        2. 调用方直接给了一块板的模型（``DesignModel``/``BoardModel``，没有
           ``boards``）→ 就用它。单板工程与测试走这条路。
        3. 多板项目但 uuid 对不上 → 拒绝，报原因。**绝不按位号相似度硬配**：
           毕设FOC 的 Board1 与 Board3 共用 ``C1``…``R6`` 一大串位号，按重合度
           配板会把两块的 ``R1`` 当成同一颗，造出一串假「器件缺失」。
        """
        model = ctx.model
        if model is None:
            return None, "调用方没有给原理图模型"
        boards = getattr(model, "boards", None)
        if boards is None:
            return model, ""
        uuid = str(getattr(ctx, "board_uuid", "") or "")
        if uuid:
            for board in boards:
                if str(getattr(getattr(board, "board", None), "uuid", "") or "") == uuid:
                    return board, ""
            return None, (
                f"工程里有 {len(boards)} 块板，没有一块的 uuid 等于 PCB 文档 "
                f"META.board 写的 {uuid!r}"
            )
        return None, "PCB 文档的 META 没有 board 字段，读不出它属于哪块原理图板"

    @staticmethod
    def _board_title(sch_board: object) -> str:
        """这块原理图板的标题，读不出来就说明读不出来。

        调用方给的模型可能是**一块板**（``BoardModel``，带 ``board`` 标题）也可
        能只是一份 :class:`~boardwise.core.model.DesignModel`（测试与单板路径），
        后者没有板名——那就说 ``(未命名板)``，不许拿项目名或 ``board_title`` 替。
        """
        ref = getattr(sch_board, "board", None)
        return str(getattr(ref, "title", "") or "") or "(未命名板)"

    def _pcb_footprint(self, board, pcb_model, designator: str) -> _Footprint:
        """PCB 侧一个位号的 FOOTPRINT 读数（名字 + 文档 + 实例化焊盘几何）。

        名字与文档 uuid 从 ``pcb_model`` 读（``Component.footprint`` 是
        ``META.title``，``props["Footprint"]`` 是文档 uuid）；焊盘几何从
        ``board.pads`` 读——那里是**摆到板上的**坐标，不是库里的局部坐标。
        """
        component = (getattr(pcb_model, "components", {}) or {}).get(designator)
        props = getattr(component, "props", {}) or {} if component is not None else {}
        pads = tuple(
            sorted(
                (
                    str(pad.pin_number or ""),
                    round(float(pad.width), 3),
                    round(float(pad.height), 3),
                    round(float(pad.local_x), 3),
                    round(float(pad.local_y), 3),
                )
                for pad in getattr(board, "pads", ())
                if str(getattr(pad, "component", "")) == designator
            )
        )
        return _Footprint(
            name=str(getattr(component, "footprint", "") or "") if component else "",
            uuid=str(props.get("Footprint") or ""),
            pads=pads,
        )

    # -- the pass ---------------------------------------------------------

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        pcb_model = ctx.pcb_model
        if board is None or pcb_model is None:
            return []

        findings: list[Finding] = []
        sch_board, why = self._schematic_board(ctx)

        # --- 同名封装几何不一（纯 PCB 侧事实，板链读不出来也能量） ---------
        findings.extend(self._ambiguous_names(board, pcb_model))

        if sch_board is None:
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{ctx.board_title}：封装对账未做——{why}。"
                        "本规则按板对齐（PCB 文档 META.board ↔ 原理图 BoardRef.uuid），"
                        "读不出板链就不猜、不按位号相似度硬配，"
                        "避免把别的板的同名器件当成这一块的"
                    ),
                    evidence=[
                        f"board uuid read from the PCB document: "
                        f"{getattr(ctx, 'board_uuid', '') or '(none)'}",
                        f"why: {why}",
                    ],
                )
            )
            return findings

        sch_components = getattr(sch_board, "components", {}) or {}
        pcb_components = getattr(pcb_model, "components", {}) or {}
        sch_refs = {name for name in sch_components if str(name or "").strip()}
        pcb_refs = {name for name in pcb_components if str(name or "").strip()}

        # --- 器件缺失：conn 类口径，对称漂移，两个方向都报 -----------------
        for designator in sorted(sch_refs - pcb_refs):
            component = sch_components[designator]
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"{designator} 在原理图 {self._board_title(sch_board)} 上有、"
                        f"PCB {ctx.board_title} 上没摆：这块板没有实现原理图的这颗件"
                        "（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报）"
                    ),
                    evidence=[
                        f"{designator} declared by the schematic board "
                        f"{self._board_title(sch_board)} (footprint "
                        f"{_describe(getattr(component, 'footprint', ''))}, "
                        f"{len(getattr(component, 'pins', ()) or ())} pin(s) declared)",
                        f"{designator} has no COMPONENT record in PCB document "
                        f"{ctx.board_title}",
                    ],
                    target=FindingTarget(component_ref=str(designator)),
                )
            )
        for designator in sorted(pcb_refs - sch_refs):
            footprint = self._pcb_footprint(board, pcb_model, designator)
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"{designator} 在 PCB {ctx.board_title} 上、原理图 "
                        f"{self._board_title(sch_board)} 上没有：板子摆了一颗原理图不认的件"
                        "（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报）"
                    ),
                    evidence=[
                        f"{designator} placed on PCB document {ctx.board_title} "
                        f"(footprint {_describe(footprint.name)}, "
                        f"{footprint.pad_size_line()})",
                        f"{designator} is not declared by the schematic board "
                        f"{self._board_title(sch_board)}",
                    ],
                    target=FindingTarget(component_ref=str(designator)),
                )
            )

        # --- 逐件对账 -------------------------------------------------------
        counters: dict[str, int] = {
            VERDICT_PAD_COUNT: 0, VERDICT_SIZE_CODE: 0, VERDICT_PACKAGE: 0,
            VERDICT_AGREE: 0, VERDICT_UNDECIDABLE: 0, "no-pcb-footprint": 0,
            "unplaced": len(sch_refs - pcb_refs),
            "undeclared": len(pcb_refs - sch_refs),
        }
        for designator in sorted(sch_refs & pcb_refs):
            sch_component = sch_components[designator]
            footprint = self._pcb_footprint(board, pcb_model, designator)
            verdict = self._one_pair(
                designator, str(getattr(sch_component, "footprint", "") or ""),
                sch_component, footprint, ctx.board_title,
            )
            counters[verdict.state] = counters.get(verdict.state, 0) + 1
            if verdict.severity is not None:
                findings.append(self._finding(ctx, verdict))

        findings.append(self._summary(ctx, sch_board, counters))
        return findings

    # -- one pair ---------------------------------------------------------

    def _one_pair(
        self,
        designator: str,
        sch_name: str,
        sch_component: object,
        footprint: _Footprint,
        board_title: str,
    ) -> _Verdict:
        """一个位号的两造：先焊盘数（几何），再名字（尺寸码 → 封装族）。"""
        sch_pins = {
            str(getattr(pin, "number", "") or "")
            for pin in (getattr(sch_component, "pins", ()) or ())
            if str(getattr(pin, "number", "") or "")
        }
        mpn = str(getattr(sch_component, "mpn", "") or "")
        pcb_pins = footprint.pin_numbers()
        base = [
            f"designator {designator}",
            f"schematic declares footprint {_describe(sch_name)} with "
            f"{len(sch_pins)} pin(s)"
            + (f": {', '.join(sorted(sch_pins))}" if sch_pins else ""),
            f"schematic part identity: value "
            f"{str(getattr(sch_component, 'value', '') or '')!r}, MPN "
            f"{str(getattr(sch_component, 'mpn', '') or '')!r}, LCSC "
            f"{str(getattr(sch_component, 'lcsc_part', '') or '')!r}",
            f"PCB {board_title} footprint document {footprint.uuid or '(none)'} "
            f"reads title {_describe(footprint.name)}; "
            f"{footprint.pad_size_line()}"
            + (f"; pad numbers {', '.join(sorted(pcb_pins))}" if pcb_pins else ""),
        ]

        # 1) 焊盘数——量出来的，先判。封装文档不在备份里（0 个焊盘实例）时不判：
        #    那不是「焊盘数不符」，是「读不出这只封装」，走 INFO（别重复报）。
        if pcb_pins and sch_pins and len(pcb_pins) != len(sch_pins):
            extra = sorted(pcb_pins - sch_pins)
            missing = sorted(sch_pins - pcb_pins)
            detail = (
                f"原理图声明 {len(sch_pins)} 个引脚，PCB 的 FOOTPRINT 只实例化出 "
                f"{len(pcb_pins)} 个焊盘"
            )
            if missing:
                detail += f"；原理图有而焊盘上没有的脚：{', '.join(missing)}"
            if extra:
                detail += f"；焊盘上有而原理图没声明的脚：{', '.join(extra)}"
            return _Verdict(
                designator=designator, state=VERDICT_PAD_COUNT, severity="ERROR",
                sch_name=sch_name, pcb=footprint, sch_pins=len(sch_pins),
                mpn=mpn, detail=detail, evidence=base,
            )

        # 2) 原理图没声明封装 / PCB 侧读不出──分别说清楚，不比较
        if str(sch_name or "").strip().lower() in NAMELESS_FOOTPRINTS:
            return _Verdict(
                designator=designator, state=VERDICT_UNDECIDABLE, severity="INFO",
                sch_name=sch_name, pcb=footprint, sch_pins=len(sch_pins),
                mpn=mpn, detail=(
                    "原理图没有声明封装（字段是 "
                    f"{_describe(sch_name)}），没有可比的对造"
                ),
                evidence=base,
            )
        if not footprint.name:
            if not footprint.uuid:
                reason = (
                    "PCB 上这颗器件压根没有指定封装（COMPONENT 没有 "
                    "ATTR key='Footprint'），板子上没有它的焊盘"
                )
            else:
                reason = (
                    f"PCB 声明的封装文档 {footprint.uuid} 不在这份备份里"
                    "（FOOTPRINT 文档没随工程带出），读不出封装名"
                )
            return _Verdict(
                designator=designator, state="no-pcb-footprint", severity="INFO",
                sch_name=sch_name, pcb=footprint, sch_pins=len(sch_pins),
                mpn=mpn, detail=reason, evidence=base,
            )

        # 2b) 原理图那一侧写的不是封装名，是个**库件 id**（模型层噪声，见
        #     LIBRARY_ID_RE）——比不了，说清楚是哪一类的比不了。
        if LIBRARY_ID_RE.match(str(sch_name or "").strip()):
            return _Verdict(
                designator=designator, state=VERDICT_UNDECIDABLE, severity="INFO",
                sch_name=sch_name, pcb=footprint, sch_pins=len(sch_pins),
                mpn=mpn, detail=(
                    f"原理图这一侧的 footprint 字段写的是库件 id "
                    f"{str(sch_name).strip()!r}，不是封装名——模型层在库件没写 "
                    "Supplier Footprint 时退化为实例的 Footprint 属性，而那几个"
                    "实例的该属性存的是 id；本规则不拿 id 里的十六进制片段当尺寸"
                    "数比，如实记成没有可比的对造"
                ),
                evidence=base,
            )

        # 3) 名字
        state, detail = _compare_names(sch_name, footprint.name)
        severity = {
            VERDICT_SIZE_CODE: "ERROR",
            VERDICT_PACKAGE: "ERROR",
            VERDICT_AGREE: None,
            VERDICT_UNDECIDABLE: "INFO",
        }[state]
        if state == VERDICT_AGREE:
            # 名字一致时把两边的可比 token 留成证据（一致也是读数，092 纪律）
            base.append(f"names agree on the comparable token: {detail}")
        return _Verdict(
            designator=designator, state=state, severity=severity,
            sch_name=sch_name, pcb=footprint, sch_pins=len(sch_pins),
            mpn=mpn, detail=detail, evidence=base,
        )

    # -- finding ----------------------------------------------------------

    def _finding(self, ctx, verdict: _Verdict) -> Finding:
        """把一条对账结论变成 finding。每条 finding 都把 5 件事说全：
        哪块板 / 哪个位号 / 原理图声明什么 / PCB 实摆什么 / 差在哪。"""
        message = (
            f"{ctx.board_title} {verdict.designator} {verdict.state_label()}："
            f"{verdict.detail}。原理图声明 {_describe(verdict.sch_name)}，"
            f"PCB 实摆 {_describe(verdict.pcb.name)}"
        )
        evidence = list(verdict.evidence)
        if verdict.state == VERDICT_PAD_COUNT:
            evidence.append(
                "焊盘数是从模型与几何各自量出来的（原理图 Component.pins 的"
                "不同编号数；PCB board.pads 里属于该位号的不同 pin_number 数），"
                "与封装名的写法无关。注意带散热焊盘的封装：DRV8313 的 "
                "HTSSOP-28 原理图符号把 EP 记成一个脚（29 个），PCB 的 "
                "HTSSOP-28_…-EP 也实例化 29 个焊盘，两边相等，不报"
            )
        if verdict.state == VERDICT_SIZE_CODE:
            evidence.append(
                f"实测后果：PCB 摆的封装 {verdict.pcb.name!r} 的焊盘是 "
                f"{verdict.pcb.pad_size_line()}——与原理图声明的尺寸码不是同"
                "一个实物尺寸，按 BOM 买回来的件贴不上"
            )
            mpn_code = chip_size_code(
                str(getattr(verdict, "mpn", "") or "")
            )
            if mpn_code:
                evidence.append(
                    f"同一侧的第二份证据：这颗件的 MPN "
                    f"{getattr(verdict, 'mpn', '')!r} 里也写着尺寸码 {mpn_code}，"
                    "与原理图声明的封装字段指向同一个实物尺寸——不一致的是 PCB "
                    "摆的那个焊盘，不是原理图那一边"
                )
        if verdict.state == VERDICT_PACKAGE:
            evidence.append(
                "族词归一按「能不能用同一套 land pattern 贴」分（SO/SOIC/SOP/DSO "
                "一族，DFN/PDFN/QFN/WQFN 一族，DO-214AB/AA/AC ↔ SMC/SMB/SMA）；"
                "间距真的不同的族不归一。族词认不出的封装名不在这里报，"
                "走「无从比较」的 INFO"
            )
        return Finding(
            rule_id=self.id,
            severity=verdict.severity or "INFO",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(
                component_ref=verdict.designator,
                measurement=(
                    _measurement("distance", _mil(verdict.pcb.pad_span()))
                    if verdict.pcb.pads else None
                ),
            ),
        )

    # -- ambiguous names (WARN) -------------------------------------------

    def _ambiguous_names(self, board, pcb_model) -> list[Finding]:
        """同名封装、实测焊盘几何却是两件事 → WARN（每块板一条）。

        只在**这块板真的用了**的封装里找：工程库里的闲置文档不是这块板的事实。
        """
        by_name: dict[str, dict[object, list[str]]] = {}
        for component in getattr(board, "components", ()):
            designator = str(getattr(component, "designator", "") or "")
            if not designator:
                continue
            footprint = self._pcb_footprint(board, pcb_model, designator)
            if not footprint.name or not footprint.pads:
                continue
            by_name.setdefault(footprint.name, {}).setdefault(
                footprint.geometry_key(), []
            ).append(designator)

        findings: list[Finding] = []
        for name in sorted(by_name):
            variants = by_name[name]
            if len(variants) < 2:
                continue
            lines = [
                f"{name!r} → " + ", ".join(sorted(refs)) + ": "
                + self._geometry_line(geometry)
                for geometry, refs in sorted(variants.items(), key=lambda kv: str(kv[1]))
            ]
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="WARN",
                    level=self.level,
                    message=(
                        f"PCB 上封装名 {name!r} 对应 {len(variants)} 套不同的实测"
                        f"焊盘几何：{AMBIGUOUS_NAME_WARN}"
                    ),
                    evidence=lines + [
                        "判据是**实例化到板上的焊盘几何**（编号 + 尺寸 + 局部坐标"
                        "四舍五入到 0.001 mil）——同一个封装名在工程库里对应两个"
                        "FOOTPRINT 文档且几何不同时才会命中；几何相同的重名文档"
                        "（1.1.0 的 C0603 三个文档）不报",
                    ],
                )
            )
        return findings

    @staticmethod
    def _geometry_line(geometry: tuple) -> str:
        widths = [pad[1] for pad in geometry]
        heights = [pad[2] for pad in geometry]
        return (
            f"{len(geometry)} pad(s) {min(widths):.3f}×{min(heights):.3f}…"
            f"{max(widths):.3f}×{max(heights):.3f} mil"
        )

    # -- summary ----------------------------------------------------------

    def _summary(self, ctx, sch_board, counters: dict[str, int]) -> Finding:
        compared = sum(
            counters.get(state, 0)
            for state in (VERDICT_AGREE, VERDICT_PAD_COUNT, VERDICT_SIZE_CODE,
                          VERDICT_PACKAGE, VERDICT_UNDECIDABLE, "no-pcb-footprint")
        )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{ctx.board_title} 封装对账（原理图 {self._board_title(sch_board)}）："
                f"比了 {compared} 个两边都有的器件——"
                f"一致 {counters.get(VERDICT_AGREE, 0)}，"
                f"焊盘数不符 {counters.get(VERDICT_PAD_COUNT, 0)}，"
                f"尺寸码不符 {counters.get(VERDICT_SIZE_CODE, 0)}，"
                f"封装族不符 {counters.get(VERDICT_PACKAGE, 0)}，"
                f"无从比较 {counters.get(VERDICT_UNDECIDABLE, 0)}，"
                f"PCB 侧读不出封装 {counters.get('no-pcb-footprint', 0)}；"
                f"另：原理图有而 PCB 没摆 "
                f"{counters.get('unplaced', 0)} 个，PCB 摆而原理图没有 "
                f"{counters.get('undeclared', 0)} 个"
            ),
            evidence=[
                "对账口径：原理图 Component.footprint（DEVICE 库件的 "
                "Supplier Footprint，退化为实例 Footprint 属性）vs PCB "
                "FOOTPRINT 文档 META.title + 实例化焊盘几何",
                "一致的件不逐个出 finding（122 个器件会刷屏），异常件各有自己的"
                "finding，各条的数目在这条里对得上",
                "两边不是一套词汇（原理图写立创商城/厂商的 Supplier Footprint，"
                "PCB 写立创内部的 FOOTPRINT title），所以不比整串，只比尺寸码 / "
                "封装族 / 尺寸数，比不出来的如实记成「无从比较」",
            ],
        )
