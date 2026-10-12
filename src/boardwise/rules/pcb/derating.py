"""降额的物理层：器件封装尺寸 vs 它实际承受的电压/功率（任务 153，E 阶段第三棒）。

路线图（``tasks/122-pcb-review-roadmap.md`` 第三步第 2 条）：「**降额的物理层**：
耐压/功率 ↔ 封装尺寸（岳的实例：RCD 电阻 0603 换 0805/1206 串联承担电压）」。
与第一条「封装一致性」的区别是那个问句：第一条问「这颗料和这块焊盘是不是
同一件事」，这一条问「**这颗料在这块板子上会不会被电打死**」——同一颗正确贴装的
0603，摆在 3.3 V 的上下拉上完全没问题，摆在 300 V 的母线上就是一颗迟早要飞的电阻。

为什么是**物理层**：电阻的阻值不决定它能承受多少电压。片式电阻的连续工作电压由
**封装尺寸**封顶——数据手册把它写成 ``Max. Working Voltage`` 一栏，并明说
「额定电压 = √(P·R) 或最大工作电压，**取小者**」（Yageo AC 系列 product
specification，Table 2 下方的 RATED VOLTAGE 段）。所以一颗 0603 的 100 kΩ 电阻
在 300 V 上：√(P·R)=√(0.1×100k)=100 V，而封装档只给 50 V——**先撞到的是封装**。
这就是「0603 换 0805/1206」这条工程动作的物理依据。

判定的两造，都是**声明事实**（架构决策 5：PCB 检查必须桥接原理图检查）
==================================================================

* **这颗电阻是谁**——原理图侧 ``Component.value``（板上写的 ``75k 1% 0603``）与
  器件库的 ``Type`` 词（``薄膜电阻``/``电阻``），加 PCB 侧 FOOTPRINT 文档的名字
  （``R0603``）里的**尺寸码**。**不从形状、焊盘数、位号字母猜器件类型**：
  位号 ``R`` 起头只是命名习惯，本规则的门是「值字段读得出欧姆」或「库件的 Type
  说的是电阻」（见 :func:`resistance_ohms_of`）。
* **它两端有多少伏**——由**两侧网名电压差**算出：每个网的电价来自 139 的双读机制
  （:func:`boardwise.rules.pcb.ipc.declared_voltages`：设计意图合同
  ``requirements.rails[net=…].voltage`` / ``targetVoltage`` 优先，其次是图纸自己的
  架构枚举），再补一条「地网按定义 0 V」（``pcb-voltage-spacing`` 的同一口径）。
  网名推不出电压 → **UNKNOWN**：不编数（见下）。
* **它的封装档是多少**——:data:`CHIP_RESISTOR_LIMITS`，每个尺寸码的
  （最大工作电压, 额定功率）都带出处，见 :data:`SOURCES`。

串联分压要认——岳点名的反面案例
================================

反激的 RCD 钳位电阻（``blocklib/specs/flyback_uc3845.circuit.json`` 的 ``R3``/``R15``，
两颗 ``75k 1% 0603``）**串在一起**承担钳位电压。一个只按「这颗件的两个脚在什么网上」
读电压的工具在这里会做两件错事：把整串的电压记到一颗头上（虚报越限），或者干脆
因为中间那个抽头网没有价而闭嘴（漏读结构）。本规则的做法是：

* **认结构**：中间节点上除了这两颗电阻**没有任何别的器件**的一条电阻链
  （:func:`series_strings`）就是一条串联串——「没有别的器件」是硬的：第三个东西
  挂在抽头上时，分压到底按不按阻值分就成了电路分析问题，本规则不猜。
* **分电压**：串两端的电压差按**阻值比例**分到每颗（75 kΩ + 75 kΩ 平分）。
  每颗的 **实际承受电压**先用它自己两个网的价（声明事实优先），自己两个网读不出价
  时才用分压份额。
* **报结构**：每条认出来的串出一条 INFO 读数（:meth:`DeratingPackage._series_readings`），
  写出成员、串两端、总电压、每颗分到多少——**认出来了、分了，才谈得上不误报**。
  串的一端没有价时这条读数如实说「总电压读不出，因为 <网> 没有价」并给出写下价的
  地址（``requirements.rails[net=…].voltage``，139 的通道），**不拿串的总电压去
  报任何一颗**。

反激那两颗的实际形态正是第三条：``R3`` 一端在 ``CLAMP``（钳位电容节点，没有价）、
``R15`` 一端在 ``HVDC``（311 V），串的总电压 = 311 V − V_CLAMP，**读不出**——
所以本规则对它们**零 verdict**（不报越限），只出一条说明结构的 INFO 读数。
把 311 V 记在 0603 头上是一句听起来像测量、其实是错的判决，本规则不做。

分级与阈值纪律（同 E1/E2 与 092 的那一套）
========================================

=======================  =======  ============================================
类别                     级别     判据
=======================  =======  ============================================
电阻封装耐压不足          WARN     该件实际承受电压 > 其封装档的典型最大工作电压
                                  （两个数都在，都带出处）
电阻封装功率不足          WARN     P = U²/R 粗估 > 其封装档的额定功率（70 °C）
串联分压结构读数          INFO     认出来的串联串：成员、串两端、总电压、各颗份额
本板读数小结              INFO     几颗电阻、几颗判了、几颗读不出（含要问的网名）
=======================  =======  ============================================

* **只有拿得准的越限才 WARN**：两个数（实际电压、封装档限值）都在 finding 里，
  说不清的一律 INFO（092 A2b 的口径）。
* **不发明降额标准**：比较就是「实际值 vs 数据手册那一栏」，**没有 80% 系数、
  没有温度修正、没有「典型封装 1 W」这类家用数字**。「典型」二字只在
  :data:`CHIP_RESISTOR_LIMITS` 的出处里出现，且指的是「同尺寸档跨厂商的
  保守下界」——每一档都写了它出自哪几份手册。
* **每颗器件至多一条 finding**（E1 的同一口径）：先判耐压、再判功率，第一条命中
  即出，第二条的比较作为证据行留在同一条 finding 里——一个缺陷不报两遍。
* 电容耐压**不在本规则**：原理图侧的 ``pwr-cap-voltage-rating`` 走 datasheet 事实库
  （092），不重复造。

读不到就 UNKNOWN，且不刷屏
==========================

大多数电阻的两个脚都不在电源网上（栅极、采样、上拉），它们的电压**本来就读不出**，
这是数据的事实不是缺陷：122 件的板子逐件出一条「读不出」会淹掉报告。所以读不出的
件**在小结里计数并点名**（含哪些网没有价，以及那批网要问价走 139 的
``intent-missing`` 名单），异常件（越限、以及在串里被分了压的）才有自己的 finding
——151/152 的同一口径。

板链读不出时，本规则**不替读者挑一块板**（164c 的 F3）
======================================================

「原理图的声明优先」这条的前提是**找得到本板的原理图页**，它由 PCB 文档自己声明的
``META.board`` 定位（:func:`schematic_board_of`），**绝不按位号重合度配板**（毕设FOC
的 Board1 与 Board3 共用 ``C1``…``R6``）。板链读不出时：

* 工程只有一块板 —— 用那一块（没有第二种可能，智能药箱 PCB1 就是这条）；
* 工程有多块板 —— **不判断**：每一颗的声明只读 PCB 文档自己的副本，小结点名
  「板链读不出、这一路未判断」（:func:`board_link_note`），判决行也带同一句话。

修前这里有个静默分支：``if uuid and uuid != …`` 在 uuid 为空时**恒假**，循环于是
命中遍历到的第一块带该位号的板——Board1 的 ``R48``（``0R``）就这样成了 PCB1 上
每一颗 ``R48`` 的声明。

**本模块不 NET、不碰 bridge、不读盘**（货架也不需要）：纯离线，读同一份 ``.epro2``
的两个视图（原理图模型 + PCB 文档的网表视图）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from .base import PcbReviewContext, PcbRule
from .footprint import chip_size_code
from .ipc import declared_voltages
from ...core.model import is_ground_net
from ...core.values import parse_resistance_ohms, states_package_size

__all__ = [
    "CHIP_RESISTOR_LIMITS",
    "ChipLimit",
    "DeratingPackage",
    "METRIC_SIZE_ALIASES",
    "RESISTOR_DESIGNATOR",
    "RESISTOR_TYPE_WORDS",
    "ResistiveEdge",
    "SOURCES",
    "SeriesString",
    "board_link_note",
    "chip_limit",
    "resistance_ohms_of",
    "schematic_board_of",
    "series_strings",
]


# ---------------------------------------------------------------------------
# the package tables, and where every number comes from
# ---------------------------------------------------------------------------

#: 每一条限值的**完整出处**（写进 finding 的证据行，读者不用去翻本文件）。
#:
#: 四条来源都是**厂商数据手册里的一栏**，不是谁算出来的降额系数：
#:
#: * ``yageo-ac`` —— Yageo AC 系列（车规厚膜片式电阻）product specification
#:   Feb 10 2012 V.2 的 Table 2 与 POWER RATING 段：0402 = 50 V / 1/16 W、
#:   0603 = 50 V / 1/10 W、0805 = 150 V / 1/8 W、1206 = 200 V / 1/4 W、
#:   1210 = 200 V / 1/2 W、1218 = 200 V / 1 W、2010 = 200 V / 3/4 W、
#:   2512 = 200 V / 1 W；同一份文档写着 **V = √(P·R) 或最大工作电压取小者**
#:   ——本规则的整个物理模型就是这一句。
#: * ``viking-rt`` —— Viking（光颉）RT 系列通用厚膜片式电阻的 Standard
#:   Electrical Specifications 表（RT-02 0402 1/16 W 50 V、RT-03 0603
#:   1/10 W 50 V、RT-05 0805 1/8 W 150 V、RT-06 1206 1/4 W 200 V、
#:   RT-10 1210 1/3 W 200 V、RT-0A 2010 3/4 W 200 V、RT-12 2512 1 W 200 V）。
#: * ``cinetech-rmc`` —— Cinetech RMC 系列通用厚膜片式电阻的 General
#:   Specifications 表（01005 1/32 W 15 V、0201 1/20 W 25 V、0402 1/16 W 50 V、
#:   0603 1/10 W 75 V）。**只用来补 01005/0201 这两档**——它们是唯一在公开
#:   手册里给得出数的小尺寸。
#: * ``vishay-mcx`` —— Vishay Beyschlag MCS/MCT/MCU/MCA professional thin film
#:   手册（document 28705）:「is limited to 50 V for 0402 and 75 V for 0603」
#:   ——0603 在薄膜工艺上给到 75 V，与厚膜的 50 V 相互印证**下界是薄的**。
#:
#: 一到多条来源同给一档时取**最保守的那一个**（电压取最小、功率取最小），
#: 并把所有给出这档的来源都列进 ``ChipLimit.sources``——一个把 1210 说成
#: 1/2 W（Yageo）和一个说 1/3 W（Viking）的分歧，本规则按能站住的那个数判。
SOURCES: dict[str, str] = {
    "yageo-ac": (
        "Yageo AC series (automotive grade thick film chip resistors), product "
        "specification Feb 10 2012 V.2, Table 2 'Max. Working Voltage' + the "
        "POWER RATING list; mirrored at "
        "https://pdf.datasheet.live/a85d625f/yageo.com/AC1206FR-10107RL.html "
        "— 0402 50 V/1/16 W, 0603 50 V/1/10 W, 0805 150 V/1/8 W, 1206 200 V/1/4 W, "
        "1210 200 V/1/2 W, 1218 200 V/1 W, 2010 200 V/3/4 W, 2512 200 V/1 W; "
        "the same page states the rated voltage as 'V = sqrt(P*R) or Maximum "
        "working voltage whichever is less'"
    ),
    "viking-rt": (
        "Viking (光颉/光碩) RT series general purpose thick film chip resistor, "
        "'Standard Electrical Specifications' table (distributor mirror "
        "https://www.mikasa-ltd.jp/pdf/VIKING_RESISTOR_MLCC.pdf) — "
        "RT-02 0402 1/16 W 50 V, RT-03 0603 1/10 W 50 V, RT-05 0805 1/8 W 150 V, "
        "RT-06 1206 1/4 W 200 V, RT-10 1210 1/3 W 200 V, RT-0A 2010 3/4 W 200 V, "
        "RT-12 2512 1 W 200 V"
    ),
    "cinetech-rmc": (
        "Cinetech RMC series thick film general purpose chip resistors, 'General "
        "Specifications' table, "
        "https://www.cinetech.com.tw/upload/2022/02/20220225154159.pdf — "
        "01005 1/32 W 15 V, 0201 1/20 W 25 V, 0402 1/16 W 50 V, 0603 1/10 W 75 V"
    ),
    "vishay-mcx": (
        "Vishay Beyschlag MCS 0402 / MCT 0603 / MCU 0805 / MCA 1206 professional "
        "thin film flat chip resistors, document 28705, "
        "https://www.vishay.com/docs/28705/mcx0x0xpro.pdf — working voltage "
        "'limited to 50 V for 0402 and 75 V for 0603'"
    ),
}

#: 片式电阻的**尺寸码 → （最大工作电压 V，额定功率 W，出处键）**。
#:
#: 键是**英制四位码**（立创的 FOOTPRINT 名字里出现的那一套，见
#: :func:`~boardwise.rules.pcb.footprint.chip_size_code`）；公制码先过
#: :data:`METRIC_SIZE_ALIASES` 归一。
#:
#: **每档取所有出处里最保守的那一个**（见 :data:`SOURCES` 的说明），出处键全部列出。
#: 表里没有的尺寸码 = 本规则**没有出处** = 不出 verdict（UNKNOWN，见小结）。
CHIP_RESISTOR_LIMITS: dict[str, "ChipLimit"] = {}


@dataclass(frozen=True)
class ChipLimit:
    """一个封装尺寸档的（最大工作电压, 额定功率）与它的出处。

    ``volts`` 是数据手册的 ``Max. Working Voltage``——连续直流/交流有效值工作电压
    的**上限**，与阻值无关的那一半（另一半是 √(P·R)）。
    ``watts`` 是 70 °C 环境下的额定功率（手册都给在 70 °C；超过 70 °C 要按降额
    曲线打折，本规则不套曲线——见模块 docstring 的「不发明降额标准」）。
    ``sources`` 是给出这一档的来源键（:data:`SOURCES`），按最保守取值的那些。
    """

    volts: float
    watts: float
    sources: tuple[str, ...] = ()

    def citation(self) -> str:
        """这一档的出处，念成一句能贴进证据的话。"""
        return "; ".join(SOURCES[key] for key in self.sources if key in SOURCES)

    def line(self) -> str:
        """这一档的读数一句话：``50 V / 0.1 W`` 与出处键。"""
        return (
            f"{self.volts:g} V max working voltage, {self.watts:g} W rated power "
            f"at 70 °C (source: {', '.join(self.sources) or 'unstated'})"
        )


def _limit(volts: float, watts: float, *sources: str) -> ChipLimit:
    return ChipLimit(volts=volts, watts=watts, sources=tuple(sources))


CHIP_RESISTOR_LIMITS.update(
    {
        # cinetech 是 01005/0201 这两档唯一的公开出处（Viking/Yageo 的表从 0402 起）
        "01005": _limit(15.0, 0.03125, "cinetech-rmc"),
        "0201": _limit(25.0, 0.05, "cinetech-rmc"),
        "0402": _limit(50.0, 0.0625, "yageo-ac", "viking-rt", "cinetech-rmc", "vishay-mcx"),
        # 0603：Yageo 与 Viking 都给 50 V，Vishay 的薄膜工艺给到 75 V，cinetech 给 75 V
        # ——取最保守的 50 V。
        "0603": _limit(50.0, 0.1, "yageo-ac", "viking-rt", "cinetech-rmc", "vishay-mcx"),
        "0805": _limit(150.0, 0.125, "yageo-ac", "viking-rt"),
        "1206": _limit(200.0, 0.25, "yageo-ac", "viking-rt"),
        # 1210：电压两处都是 200 V，功率 Yageo 说 1/2 W、Viking 说 1/3 W → 1/3 W。
        "1210": _limit(200.0, 1.0 / 3.0, "yageo-ac", "viking-rt"),
        "1218": _limit(200.0, 1.0, "yageo-ac"),
        "2010": _limit(200.0, 0.75, "yageo-ac", "viking-rt"),
        "2512": _limit(200.0, 1.0, "yageo-ac", "viking-rt"),
    }
)

#: 公制尺寸码 → 英制尺寸码。两种写法都在立创的库里出现（152 的 ``CHIP_SIZE_CODES``
#: 同时收了两套），而限值表按英制分档，所以这一层是**同一尺寸的另一种写法**的归一，
#: 不是猜测：``1608`` 是 1.6×0.8 mm，正是 ``0603``（0.06×0.03 in）。
#:
#: **故意不收 2016**（公制 2.0×1.6 mm）：它在英制里没有一一对应的尺寸档，
#: 认成 1206 或 0805 都是替厂商发明对应关系——宁可不判（UNKNOWN）。
METRIC_SIZE_ALIASES: dict[str, str] = {
    "1005": "0402",
    "1608": "0603",
    "2012": "0805",
    "3216": "1206",
    "3225": "1210",
}


def chip_limit(footprint_name: str) -> tuple[str, ChipLimit] | None:
    """``(尺寸码, 限值)``，认不出尺寸码或表里没这一档时 ``None``。

    尺寸码走 151 的 :func:`~boardwise.rules.pcb.footprint.chip_size_code`
    （``R0603`` → ``0603``、``C0805`` → ``0805``、``LED0805-R-RD`` → ``0805``），
    再过 :data:`METRIC_SIZE_ALIASES` 把公制写法归一。**认不出就说认不出**：
    通孔电阻（``RES-TH-17K8``）、``2016`` 这类没有对应档的尺寸码，都不猜。
    """
    code = chip_size_code(footprint_name)
    if code is None:
        return None
    code = METRIC_SIZE_ALIASES.get(code, code)
    limit = CHIP_RESISTOR_LIMITS.get(code)
    if limit is None:
        return None
    return code, limit


# ---------------------------------------------------------------------------
# is this part a resistor, and how many ohms
# ---------------------------------------------------------------------------

#: 器件库 ``Type`` 里说明「这颗件是电阻」的词（大小写不敏感）。实测来源：
#: 毕设FOC 1.0.0/1.1.0 的 ``薄膜电阻``、``合金电阻；贴片电阻``，ROBOT 的同款。
#: **不与电容词表共享**：``无极性电容`` 里没有这两个词，本规则就不认它是电阻。
RESISTOR_TYPE_WORDS: tuple[str, ...] = ("电阻", "resistor")

#: 位号是不是电阻族（``R12``/``R3``）。**这不是判定门，只是报告门的原料**：
#: 小结里把「位号像电阻、但值字段与库件都没说它是电阻」的件点名出来——那是
#: 一句事实（本规则没有判它），不是一条 verdict（151 的 ``unplaced`` 同一口径）。
RESISTOR_DESIGNATOR = re.compile(r"^R\d", re.IGNORECASE)

#: 值字段的切分符：空白、``/``、``,``、``;``。手册与工程写法都见过
#: （``75k 1% 0603``、``1R/0.5W``）。
_VALUE_SPLIT = re.compile(r"[\s/,;]+")


def resistance_ohms_of(value: str, footprint: str = "", type_word: str = "") -> float | None:
    """值字段 → 欧姆，读不出就说读不出。

    **两道门，都是声明事实**（模块 docstring 的「判定的两造」）：

    1. **整串读得出欧姆**（``10K``、``100kΩ``、``5mΩ``、``0Ω``、``1R``）——
       板上最常见的写法，最强的门：图上写着欧姆，这颗就是电阻（能不能读值另说）。
    2. **器件库的 ``Type`` 说了电阻**（:data:`RESISTOR_TYPE_WORDS`）——这时才允许
       :data:`_VALUE_SPLIT` 的**逐段回退读法**：值字段里夹了公差/尺寸/封装词
       （``75k 1% 0603`` 整串读不出，但第一段 ``75k`` 是 75 kΩ）时，把段读一遍，
       **恰好一段读得出**才认它。

    回退读法**只对第二道门开着**是有意的：``4N60 (600V 4A NMOS)`` 这种值字段里
    散着一堆数字的器件，没有库件说它是电阻时不许逐段去撞（撞上哪段都会把一颗
    MOS 认成电阻）。两道门之外的件**本规则不判**——位号 ``R`` 起头不是电气事实。

    **两处防坑，都是实测的模型层噪声：**

    * 段本身就是**封装尺寸码**（``0603``）时跳过——``0603`` 能读成 603 Ω，
      那是尺寸不是阻值（``core.values.states_package_size`` 是仓库自己那张表，
      这里问它而不是再写一遍）。
    * 值字段**等于封装名**时拒读（``R0603`` 能读成 0.0603 Ω）——那是模型层的
      一处噪声（值字段里存的是封装名），与 151 记的 ``footprint`` 存库件 id 同类。

    返回 ``None`` 与返回 ``0.0`` 是两件事：``0.0`` 是量出来的 0 Ω（跳线），
    ``None`` 是读不出（UNKNOWN）。调用方按这两件事分别处理。
    """
    text = str(value or "").strip()
    if not text:
        return None
    if footprint and text.lower() == str(footprint).strip().lower():
        return None
    if states_package_size(text):
        # A value field that *is* a bare package size is a size, not a value
        # (``0603`` reads as 603 Ω) — the same refusal 092's capacitor rating
        # reader makes before handing a token to the voltage parser (issue #72).
        return None
    whole = parse_resistance_ohms(text)
    if whole is not None:
        return whole
    if not any(word.lower() in str(type_word).lower() for word in RESISTOR_TYPE_WORDS):
        return None
    found: list[float] = []
    for token in _VALUE_SPLIT.split(text):
        token = token.strip()
        if not token or states_package_size(token):
            continue
        ohms = parse_resistance_ohms(token)
        if ohms is not None:
            found.append(ohms)
    if len(found) != 1:
        return None
    return found[0]


#: **欧姆的写法**（R 当小数点），``R5``/``1R5``/``10R``/``0R01`` 与裸的 ``0R``。
#:
#: 这是「这颗是电阻」这条门的一部分，**不是数值解码**：仓库的解码器
#: （``core.values.parse_resistance_ohms``）读得出 ``1R5``/``R5``/``R050``，
#: 却对**裸的 ``0R``** 返回 ``None``（实测；133c 的 0 Ω 单点接法在毕设FOC 上正是
#: 写成 ``0R``）。本规则**不另造一套数值解码**（不在规则里替 ``core.values``
#: 猜数）——只认「这是欧姆的写法」：于是这颗在**电压**那一路照样会被判，
#: **功率**那一路如实记成「阻值读不出」（UNKNOWN），与「0 Ω 跳线」也分得开。
_OHM_NOTATION = re.compile(r"^[0-9]*R[0-9]*$")


def _looks_like_ohms(value: str, footprint: str = "") -> bool:
    """值字段是**欧姆的写法**吗（不需要读得出数）。

    值字段等于封装名时拒答（``R0603`` 也匹配 ``_OHM_NOTATION``，那是模型层的
    噪声：字段里存的是封装名，见 :func:`resistance_ohms_of`）。
    """
    text = str(value or "").strip()
    if not text:
        return False
    if footprint and text.lower() == str(footprint).strip().lower():
        return False
    if parse_resistance_ohms(text) is not None:
        return True
    if _OHM_NOTATION.match(text) and any(ch.isdigit() for ch in text):
        return True
    return False


def _is_resistor(value: str, footprint: str, type_word: str) -> tuple[bool, str]:
    """``(是不是电阻, 凭什么)``——两条门，理由原样写进证据。

    门一：**值字段是欧姆的写法**（``10K``/``5mΩ``/``0R``）——图上写着欧姆，这颗
    就是电阻。门二：**器件库的 ``Type`` 说的是电阻**——值字段夹了公差/尺寸词而读不出
    整串时，靠它才允许逐段回退（见 :func:`resistance_ohms_of`）。
    **位号字母不是门**：``R`` 起头是命名习惯，不是电气事实（架构决策 5）。
    """
    value_text = str(value or "").strip()
    if _looks_like_ohms(value_text, footprint):
        return True, f"值字段是欧姆的写法（{value_text!r}）"
    if any(word.lower() in str(type_word).lower() for word in RESISTOR_TYPE_WORDS):
        return True, f"器件库 Type = {type_word!r} 说的是电阻"
    return False, ""


# ---------------------------------------------------------------------------
# series strings (the divider that must not be reported as a defect)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResistiveEdge:
    """网表里的一条**电阻边**：一颗两脚电阻 + 它两个脚各在哪两张网上。"""

    designator: str
    net_a: str
    net_b: str
    ohms: float | None = None


@dataclass
class SeriesString:
    """一条认出来的**串联电阻串**（≥2 颗，中间节点上只有这两颗电阻）。

    ``ends`` 是串的两个端点网（按 ``members`` 顺序的两个自由端）。``total`` 是串
    两端的电压差，读不出时 ``None``（``reason`` 说为什么）。``share`` 是每颗分到
    的电压（按阻值比例；有任何一颗阻值读不出时为 ``{}``）。
    """

    members: tuple[ResistiveEdge, ...]
    ends: tuple[str, str]
    total: float | None = None
    share: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def designators(self) -> tuple[str, ...]:
        return tuple(edge.designator for edge in self.members)


def series_strings(
    edges: list[ResistiveEdge], members_of_net: dict[str, frozenset[str]]
) -> list[SeriesString]:
    """从电阻边里找出所有**串联串**（纯函数，可单测）。

    一条串 = 一串首尾相接的电阻边，且**每一个中间节点**上：

    * 在电阻图里的度数恰好是 2（只有这条串的两颗电阻接着），且
    * 该网的**成员集合恰好是这两颗电阻的位号**（``members_of_net``）——
      第三个东西挂在抽头上就不是分压问题了，本规则不猜（模块 docstring）。

    两端的节点（度数 ≠ 2，或最后一个接不满条件的节点）就是串的端点。长度 ≥2 的
    才算串；**环**（每个节点度数都是 2、没有自由端）不算——环两端的电压差是 0，
    那不是分压。

    返回的 :class:`SeriesString` 已按阻值比例分好电压（端点的价由调用方另行填，
    见 :func:`boardwise.rules.pcb.derating.DeratingPackage._split`）。
    """
    incident: dict[str, list[int]] = {}
    for index, edge in enumerate(edges):
        for net in {edge.net_a, edge.net_b}:
            incident.setdefault(net, []).append(index)

    def _passable(net: str, first: int, second: int) -> bool:
        if len(incident.get(net, ())) != 2:
            return False
        wanted = frozenset({edges[first].designator, edges[second].designator})
        return len(wanted) == 2 and members_of_net.get(net) == wanted

    def _far(end_edge: int, net: str) -> str:
        edge = edges[end_edge]
        return edge.net_b if edge.net_a == net else edge.net_a

    used: set[int] = set()
    chains: list[list[int]] = []
    for start, edge in enumerate(edges):
        if start in used or edge.net_a == edge.net_b:
            continue
        used.add(start)
        chain = [start]
        # 从这里往两端各走一次，走不动为止。
        for net in (edge.net_a, edge.net_b):
            cursor, node = start, net
            while True:
                candidates = [
                    index for index in incident.get(node, ()) if index != cursor
                ]
                if len(candidates) != 1:
                    break
                nxt = candidates[0]
                if nxt in used or not _passable(node, cursor, nxt):
                    break
                used.add(nxt)
                chain.append(nxt)
                cursor, node = nxt, _far(nxt, node)
        chains.append(chain)

    out: list[SeriesString] = []
    for chain in chains:
        if len(chain) < 2:
            continue
        picked = [edges[index] for index in chain]
        counts: dict[str, int] = {}
        for picked_edge in picked:
            for net in {picked_edge.net_a, picked_edge.net_b}:
                counts[net] = counts.get(net, 0) + 1
        ends = tuple(net for net, count in counts.items() if count == 1)
        if len(ends) != 2:
            continue  # 环：没有自由端
        out.append(SeriesString(members=tuple(picked), ends=(ends[0], ends[1])))
    return out


# ---------------------------------------------------------------------------
# the board chain (164c, F3)
# ---------------------------------------------------------------------------


def schematic_board_of(ctx: PcbReviewContext) -> object | None:
    """这块 PCB 文档所属的**原理图板**，读不出就是 ``None``（151/153/153b 的同一路）。

    板链是 PCB 文档自己声明的 ``META.board``（在 ctx 里是
    :attr:`PcbReviewContext.board_uuid`），所以那一页**由文档自己的链找到**，
    **绝不按位号重合度配板**：毕设FOC 1.0.0 的 Board1 与 Board3 共用
    ``C1``…``R6`` 一大串位号，按位号配会答出另一块板。

    返回 ``None`` 是**一个正常答案**（「本板没有可读的原理图视图」），调用方据此
    退回 PCB 文档自己的声明并在证据里写明，不是错误。

    **164c 的 F3 修在这里**：板链读不出（``board_uuid`` 为空）时

    * 工程只有**一块**原理图板 —— 用那一块（没有第二种可能，这也是
      智能药箱 PCB1 的情形：它没声明 ``META.board``，工程里也只有一块板）；
    * 工程有**多块** —— **返回 ``None``**。

    修前的写法是 ``for board in boards: if uuid and uuid != …: continue``：uuid
    为空时这个条件**恒假**，于是循环静默命中**遍历到的第一块**带该位号的板——
    「板链读不出」被当成「就是它」。Board1 的 ``R48``（``0R``）就这样成了 PCB1
    每一颗叫做 ``R48`` 的件的声明。
    """
    model = getattr(ctx, "model", None)
    if model is None:
        return None
    boards = getattr(model, "boards", None)
    if boards is None:
        # 单板模型自己就是那一页（151/153 接受的同一种形状）。
        return model
    boards = list(boards)
    uuid = str(getattr(ctx, "board_uuid", "") or "")
    if not uuid:
        return boards[0] if len(boards) == 1 else None
    for board in boards:
        if str(getattr(getattr(board, "board", None), "uuid", "") or "") == uuid:
            return board
    return None


def board_link_note(ctx: PcbReviewContext) -> str:
    """「板链读不出、本规则未判断」那句话，板链读得出时是空串。

    只在**真的定位不到**时写：``boards`` 缺省（单板模型自己就是那一页）、工程只有
    一块板（没有第二种可能），都是能定位的情形。写不出的原因是「位号重合度」这条
    路的**反面**，所以也一并写在句子里——读者要能看出本规则拒绝了哪条错路。

    **降额（本模块）与极性（:mod:`boardwise.rules.pcb.polarity`）共用这一句**：
    164c 的 F3 是同一个洞在两个文件里逐字重复，所以修法也共用一份实现（极性那条
    规则 import 这个函数），免得下一次改动只修一半。
    """
    model = getattr(ctx, "model", None)
    if model is None:
        return ""
    boards = getattr(model, "boards", None)
    if boards is None:
        return ""
    boards = list(boards)
    if len(boards) <= 1:
        return ""
    uuid = str(getattr(ctx, "board_uuid", "") or "")
    if not uuid:
        return (
            f"**板链读不出**：本 PCB 文档没有声明 `META.board`（`board_uuid` 为空），"
            f"而这个工程有 {len(boards)} 块原理图板——无法定位本板的原理图页，"
            "所以**依赖原理图的那条判据这一路未判断**（降额是「原理图声明优先」，"
            "极性是「符号脚名给的极性脚」），只报 PCB 文档与库件这一侧读得到的读数"
            "（那侧的副本实测会漂，见下）；本规则**不按位号重合度配板**"
        )
    if not any(
        str(getattr(getattr(board, "board", None), "uuid", "") or "") == uuid
        for board in boards
    ):
        return (
            f"**板链读不出**：`board_uuid` = {uuid!r} 在这个工程的 {len(boards)} 块"
            "原理图板里都找不到对应的一块——无法定位本板的原理图页，"
            "所以**依赖原理图的那条判据这一路未判断**（降额是「原理图声明优先」，"
            "极性是「符号脚名给的极性脚」），只报 PCB 文档与库件这一侧读得到的读数；"
            "本规则**不按位号重合度配板**"
        )
    return ""


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


class DeratingPackage(PcbRule):
    """电阻的封装尺寸档 vs 它在这块板上实际承受的电压（任务 153）。

    =======================  =======  ============================================
    类别                     级别     判据
    =======================  =======  ============================================
    电阻封装耐压不足          WARN     实际承受电压 > 封装档的 Max. Working Voltage
    电阻封装功率不足          WARN     P = U²/R 粗估 > 封装档额定功率（70 °C）
    串联分压结构读数          INFO     认出来的串联串与它的分压份额
    本板读数小结              INFO     几颗电阻、几颗判了、几颗读不出（含网名）
    =======================  =======  ============================================

    **每颗器件至多一条 finding**（先耐压、后功率），**串联分压先认后分**（岳点名的
    反面案例，见模块 docstring）。所有判定都是「实际值 vs 手册那一栏」的两个数，
    没有降额系数、没有温度修正；读不出的件在小结里点名（UNKNOWN 纪律），
    不逐件刷屏（151/152 的同一口径）。
    """

    id = "pcb-derating-package"
    title = "电阻封装尺寸档的耐压/功率 vs 它两端实际承受的电压"
    level = "L2-facts"
    source = (
        "datasheet 封装档（四份手册交叉，每档取最保守值，出处见 derating.SOURCES）："
        "Yageo AC 系列 Table 2 + POWER RATING、Viking RT 系列、Cinetech RMC 系列、"
        "Vishay 28705；判定 = 实际电压/功率 vs 该档限值，两个数都出，"
        "**不套降额系数**——house rule（岳 2026-10-11 待裁）：不发明 80% 系数、"
        "不做温度修正、不编「典型封装 1 W」，同 092 的口径"
    )

    # -- the pass ---------------------------------------------------------

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        pcb_model = ctx.pcb_model
        if pcb_model is None:
            return []
        volts, _notes = self._voltages(ctx)
        priced_nets = set(volts)
        link_note = board_link_note(ctx)

        edges: list[ResistiveEdge] = []
        members_of_net: dict[str, frozenset[str]] = {
            str(net.name): frozenset(
                str(ref) for ref, _pin in (getattr(net, "pins", ()) or ())
            )
            for net in (getattr(pcb_model, "nets", {}) or {}).values()
        }

        readings: list[tuple[str, ResistiveEdge, str, str]] = []
        unpriced: list[tuple[str, tuple[str, ...]]] = []
        unidentified: list[str] = []
        jumper: list[str] = []
        divergent: list[str] = []
        for designator in sorted(getattr(pcb_model, "components", {}) or {}):
            placed = pcb_model.components[designator]
            schematic = self._schematic_component(ctx, designator)
            drawn = str(getattr(schematic, "value", "") or "")
            own = str(getattr(placed, "value", "") or "")
            # **原理图的声明优先，PCB 文档的值是回退**：图上的 Value 是工程师写下的
            # 「这颗是什么」，PCB 文档的同一字段是它的副本、实测会漂（毕设FOC 1.1.0
            # 的 R11/R25/R48/R49：原理图写 0R、PCB 文档写 10K；R31：原理图空、
            # PCB 写 150kΩ）——两造都写了且不同时，如实记进小结，不静默取一个。
            value = drawn or own
            if drawn and own and drawn != own:
                divergent.append(
                    f"{designator} (原理图 {drawn!r} vs PCB 文档 {own!r})"
                )
            footprint = str(getattr(placed, "footprint", "") or "")
            type_word = str((getattr(placed, "props", {}) or {}).get("Type") or "")
            pin_nets = self._pin_nets(pcb_model, designator)
            if len(pin_nets) != 2:
                continue
            is_resistor, why = _is_resistor(value, footprint, type_word)
            if not is_resistor:
                if RESISTOR_DESIGNATOR.match(str(designator)):
                    unidentified.append(
                        f"{designator} (value {value!r}, footprint {footprint!r})"
                    )
                continue
            ohms = resistance_ohms_of(value, footprint, type_word)
            first, second = (pin_nets[key] for key in sorted(pin_nets))
            edge = ResistiveEdge(
                designator=str(designator), net_a=first, net_b=second, ohms=ohms
            )
            if ohms is not None and ohms <= 0.0:
                # 0 Ω（跳线）不是电阻档的事：它两端的电压由铜箔决定，功率无从谈。
                jumper.append(f"{designator} (value {value!r})")
                continue
            edges.append(edge)
            readings.append((str(designator), edge, why, value))
            missing = tuple(
                net for net in (first, second) if net not in priced_nets
            )
            if missing:
                unpriced.append((str(designator), missing))

        strings = series_strings(edges, members_of_net)
        for string in strings:
            self._split(string, volts)

        findings: list[Finding] = []
        findings.extend(self._series_readings(ctx, strings, volts))
        findings.extend(self._verdicts(ctx, readings, strings, volts))
        findings.append(
            self._summary(
                ctx, readings, strings, unpriced, unidentified, jumper, divergent,
                volts, link_note,
            )
        )
        return findings

    # -- voltages ---------------------------------------------------------

    def _voltages(self, ctx: PcbReviewContext) -> tuple[dict[str, tuple[float, str]], list[str]]:
        """本板每个网的电价：``net -> (volts, where)``。

        走 139 的双读机制（:func:`boardwise.rules.pcb.ipc.declared_voltages`：
        合同 ``rails[].voltage``/``targetVoltage`` 优先，其次架构枚举），
        再补上「地网按定义 0 V」——``pcb-voltage-spacing`` 的同一口径，
        同一条事实不该有两份说法。
        """
        volts, notes = declared_voltages(ctx, ctx.model)
        for net in sorted((getattr(ctx.pcb_model, "nets", {}) or {})):
            name = str(net or "").strip()
            if not name or name in volts:
                continue
            if is_ground_net(name):
                volts[name] = (0.0, "ground net — the board's 0 V reference")
        return volts, notes

    @staticmethod
    def _pin_nets(pcb_model: object, designator: str) -> dict[str, str]:
        """这颗件的**脚号 → 网名**，从 PCB 文档自己的网表视图读（131c 的同一视图）。

        一个脚落在两张网上（不可能），或两个脚落在同一张网上（回路），都由调用方
        按「不是两颗脚的电阻」或「压差 0」处理。
        """
        out: dict[str, str] = {}
        for net in (getattr(pcb_model, "nets", {}) or {}).values():
            for ref, pin in getattr(net, "pins", ()) or ():
                if str(ref) == designator:
                    out.setdefault(str(pin), str(net.name))
        return out

    @staticmethod
    def _schematic_component(ctx: PcbReviewContext, designator: str) -> object | None:
        """这颗 PCB 位号在**本板对应的原理图板**上的那颗件（151/152 的同一路）。

        板链走 :func:`schematic_board_of`——读不出板链时退回手上那本
        ``components``（单板工程与测试走这条），**绝不按位号重合度配板**；
        **多板工程 + 没有板链 = 无页可答**（164c 的 F3，见下）。
        """
        page = schematic_board_of(ctx)
        if page is None:
            return None
        return (getattr(page, "components", {}) or {}).get(designator)

    @staticmethod
    def _split(string: SeriesString, volts: dict[str, tuple[float, str]]) -> None:
        """把串两端的电压差按阻值比例分到每颗（在 ``string`` 上原地填结果）。

        分量读得出才有份额：任何一颗阻值读不出，或者串两端有一端没有价，
        ``share`` 就空着，``notes`` 写清楚是哪一件读不出——分不出来就说分不出来，
        不按「平均分」代替（两颗不同值的串平均分是错的，而最短的那条错路就是它）。
        """
        first, second = string.ends
        unknown = [net for net in (first, second) if net not in volts]
        if unknown:
            string.notes.append(
                "串两端 " + " 与 ".join(repr(net) for net in (first, second))
                + f" 里 {', '.join(repr(net) for net in unknown)} 没有价，"
                "串的总电压读不出——本规则不拿它去报任何一颗（UNKNOWN）"
            )
            return
        string.total = abs(volts[first][0] - volts[second][0])
        if any(edge.ohms is None for edge in string.members):
            unreadable = [
                edge.designator for edge in string.members if edge.ohms is None
            ]
            string.notes.append(
                "串里 " + ", ".join(unreadable) + " 的阻值读不出，按阻值分不下来"
            )
            return
        total_ohms = sum(float(edge.ohms or 0.0) for edge in string.members)
        if total_ohms <= 0.0:
            string.notes.append("串的总阻值是 0，按阻值分不下来")
            return
        string.share = {
            edge.designator: string.total * float(edge.ohms or 0.0) / total_ohms
            for edge in string.members
        }

    # -- verdicts ---------------------------------------------------------

    def _verdicts(
        self,
        ctx: PcbReviewContext,
        readings: list[tuple[str, ResistiveEdge, str, str]],
        strings: list[SeriesString],
        volts: dict[str, tuple[float, str]],
    ) -> list[Finding]:
        """每颗电阻一条判定（先耐压、后功率），第一条命中即出。"""
        membership: dict[str, SeriesString] = {}
        for string in strings:
            for edge in string.members:
                membership.setdefault(edge.designator, string)

        findings: list[Finding] = []
        for designator, edge, why, value in readings:
            code_limit = chip_limit(self._footprint_name(ctx, designator))
            if code_limit is None:
                continue
            code, limit = code_limit
            volts_here, where, structure = self._part_volts(
                edge, membership.get(designator), volts
            )
            if volts_here is None:
                continue
            ohms = edge.ohms
            watts = None
            if ohms is not None and ohms > 0.0:
                watts = volts_here * volts_here / ohms
            over_volts = volts_here > limit.volts
            over_watts = watts is not None and watts > limit.watts
            if not over_volts and not over_watts:
                continue
            findings.append(
                self._one_finding(
                    ctx, designator, edge, value, why, code, limit, volts_here,
                    where, membership.get(designator), watts,
                )
            )
        return findings

    @staticmethod
    def _part_volts(
        edge: ResistiveEdge,
        string: SeriesString | None,
        volts: dict[str, tuple[float, str]],
    ) -> tuple[float | None, str, bool]:
        """``(这颗实际承受的电压, 这个数的出处, 是不是用的分压份额)``。

        **声明事实优先**：这颗自己的两个脚都有价时用它（两个网的电压差就是它两端
        的电压），出处写清是哪两个网、各自谁给的价。自己的脚读不出价时**才**用
        串联串按阻值分下来的份额（那是一条算出来的数，出处如实写「分压份额」）。
        两条路都走不通 → ``None``（UNKNOWN，不出 verdict）。
        """
        first, second = edge.net_a, edge.net_b
        if first in volts and second in volts:
            where = (
                f"{first!r} = {volts[first][0]:g} V ({volts[first][1]}) 与 "
                f"{second!r} = {volts[second][0]:g} V ({volts[second][1]}) 之差"
            )
            return abs(volts[first][0] - volts[second][0]), where, False
        if string is not None and edge.designator in string.share:
            first_end, second_end = string.ends
            where = (
                f"{string.designators()} 串联串（{first_end!r} = "
                f"{volts[first_end][0]:g} V 到 {second_end!r} = "
                f"{volts[second_end][0]:g} V，串总压 {string.total:g} V）里按 "
                f"{edge.ohms:g} Ω 分到的份额"
            )
            return string.share[edge.designator], where, True
        return None, "", False

    def _one_finding(
        self,
        ctx: PcbReviewContext,
        designator: str,
        edge: ResistiveEdge,
        value: str,
        why: str,
        code: str,
        limit: ChipLimit,
        volts_here: float,
        where: str,
        string: SeriesString | None,
        watts: float | None,
    ) -> Finding:
        """一颗电阻超封装档的 finding（两个数 + 两条出处，一个缺陷一条）。"""
        footprint = self._footprint_name(ctx, designator)
        over_volts = volts_here > limit.volts
        what = "封装耐压不足" if over_volts else "封装功率不足"
        if over_volts:
            verdict = (
                f"两端实际承受 {volts_here:g} V > 该封装档的最大工作电压 "
                f"{limit.volts:g} V"
            )
        else:
            verdict = (
                f"P = U²/R 粗估 {watts:.4g} W > 该封装档的额定功率 {limit.watts:g} W"
                "（70 °C）"
            )
        message = (
            f"{ctx.board_title} {designator} {what}：封装 {footprint!r}（尺寸码 "
            f"{code}）的档位是 {limit.line()}，而{verdict}"
            + (
                f"；这颗不是一颗件在扛——它在 {'+'.join(string.designators())} "
                "这条串联串里，电压已按阻值比例分到每颗，本规则不把整串的电压记在"
                "一颗头上"
                if string is not None
                else ""
            )
        )
        evidence = [
            f"designator {designator}: value {value!r}, footprint {footprint!r} "
            "（PCB 侧 FOOTPRINT 名字，物理封装以它为准）",
            f"recognised as a resistor because {why}",
            f"pads on {edge.net_a!r} and {edge.net_b!r}"
            + (
                f", parsed value {edge.ohms:g} Ω"
                if edge.ohms is not None
                else ", resistance unreadable (no power estimate)"
            ),
            f"voltage across the part: {volts_here:g} V — {where}",
            f"package limit for size code {code}: {limit.line()}",
            f"the limit's provenance: {limit.citation()}",
            "判据：实际值 vs 数据手册那一栏，两个数都在；**不套降额系数**"
            "（没有 80%、没有温度修正）——这是 092 A2b 的同一口径，"
            "本工具不发明降额标准",
        ]
        link_note = board_link_note(ctx)
        if link_note:
            evidence.append(link_note)
        if string is not None:
            evidence.append(
                "串联分压：本规则先把这一串电阻认出来（中间节点上没有第三个器件）、"
                "按阻值比例分压，再判每一颗——整串的电压记在一颗头上是错误判决"
                "（岳点名的反面案例）；串的成员是 "
                + "+".join(string.designators())
            )
        if over_volts:
            # The finding is the voltage row; the power row is the second
            # comparison, kept here rather than filed again (one defect, one
            # finding).
            other = (
                f"P = U²/R = {watts:.4g} W "
                f"{'>' if watts > limit.watts else '≤'} {limit.watts:g} W"
                if watts is not None
                else "阻值读不出，P = U²/R 无从估（不猜阻值）"
            )
            evidence.append(
                f"同一颗的另一条比较：{other} —— 每颗器件至多一条 finding，"
                "先耐压后功率，第二条留在证据里（一个缺陷不报两遍）"
            )
        else:
            evidence.append(
                f"同一颗的另一条比较：两端 {volts_here:g} V ≤ 该封装档的最大工作电压 "
                f"{limit.volts:g} V（未越限）—— 这条 finding 是功率那一行，"
                "每颗器件至多一条（先耐压、后功率）"
            )
        return Finding(
            rule_id=self.id,
            severity="WARN",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(
                component_ref=designator,
                net_refs=[edge.net_a, edge.net_b],
                counterpart_ref=(
                    next(
                        (
                            member
                            for member in string.designators()
                            if member != designator
                        ),
                        "",
                    )
                    if string is not None
                    else ""
                ),
            ),
        )

    # -- series readings (INFO) -------------------------------------------

    def _series_readings(
        self,
        ctx: PcbReviewContext,
        strings: list[SeriesString],
        volts: dict[str, tuple[float, str]],
    ) -> list[Finding]:
        """每条认出来的串联串一条 INFO 读数。

        **这是「不误报」的可审计那一半**：读者看得见本规则确实认出了结构、确实按
        阻值分了压，而不是把整串电压记在一颗头上或者干脆闭嘴。条数少（真实板上
        分压串屈指可数），逐条出；超过 :data:`SERIES_READING_CAP` 条时合并成一条
        计数行，避免报刷屏。
        """
        if not strings:
            return []
        lines = [self._series_line(string, volts) for string in strings]
        if len(lines) > SERIES_READING_CAP:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} 认出 {len(strings)} 条串联电阻串（超过"
                        f" {SERIES_READING_CAP} 条，合并计数）——分压结构逐条读数见"
                        "重建脚本；本规则不把整串电压记在单颗头上"
                    ),
                    evidence=lines[:SERIES_READING_CAP],
                )
            ]
        findings: list[Finding] = []
        for string, line in zip(strings, lines):
            members = string.designators()
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{ctx.board_title} 串联电阻串 {'+'.join(members)}："
                        + (
                            f"串两端 {string.ends[0]!r} 到 {string.ends[1]!r} 相差 "
                            f"{string.total:g} V，按阻值比例分到每颗——"
                            + "、".join(
                                f"{ref} {value:g} V"
                                for ref, value in sorted(string.share.items())
                            )
                            + "。整串的电压没有记在任何一颗头上（串联分压不是缺陷）"
                            if string.share
                            else "结构认出来了，但电压分不下来（见证据）"
                        )
                    ),
                    evidence=[line]
                    + [
                        "认结构的口径：中间节点上**除这两颗电阻外没有任何别的器件**"
                        "（第三个东西挂在抽头上，分压就不按阻值分了，本规则不猜）",
                        "分到的电压 = 串两端电压差 × 该颗阻值 / 串总阻值",
                        "岳点名的反面案例：把整串电压记在一颗头上（例如把 311 V 记在"
                        "一颗 0603 上）是错误判决；本规则先认结构、再按阻值分",
                    ],
                )
            )
        return findings

    @staticmethod
    def _series_line(string: SeriesString, volts: dict[str, tuple[float, str]]) -> str:
        """一条串的读数（证据行，也是超上限时合并行的内容）。"""
        members = ", ".join(
            f"{edge.designator} ({edge.net_a!r}-{edge.net_b!r}, "
            + (f"{edge.ohms:g} Ω)" if edge.ohms is not None else "resistance unreadable)")
            for edge in string.members
        )
        ends = " ↔ ".join(
            f"{net!r} = {volts[net][0]:g} V ({volts[net][1]})"
            if net in volts
            else f"{net!r} = (no stated voltage)"
            for net in string.ends
        )
        share = (
            ", ".join(f"{ref} → {value:g} V" for ref, value in sorted(string.share.items()))
            if string.share
            else "(not splittable)"
        )
        text = f"series string {'+'.join(string.designators())}: {members}; ends {ends}; shares {share}"
        for note in string.notes:
            text += f"; {note}"
        return text

    # -- naming helpers ---------------------------------------------------

    def _footprint_name(self, ctx: PcbReviewContext, designator: str) -> str:
        """这颗件在 PCB 上的封装名（物理封装的唯一来源是板子这一侧）。

        PCB 侧读不出名字时**退回原理图声明**（同一块板的那颗件，走
        :meth:`_schematic_component` 的板链）——这是 151 那条错配（原理图声明
        0805、板子摆 0603）同一根线上的事实：**物理封装以板子为准**，
        读不出才用声明的那个名字。
        """
        component = (getattr(ctx.pcb_model, "components", {}) or {}).get(designator)
        name = str(getattr(component, "footprint", "") or "") if component else ""
        if name:
            return name
        schematic = self._schematic_component(ctx, designator)
        return str(getattr(schematic, "footprint", "") or "") if schematic else ""

    # -- summary ----------------------------------------------------------

    def _summary(
        self,
        ctx: PcbReviewContext,
        readings: list[tuple[str, ResistiveEdge, str, str]],
        strings: list[SeriesString],
        unpriced: list[tuple[str, tuple[str, ...]]],
        unidentified: list[str],
        jumper: list[str],
        divergent: list[str],
        volts: dict[str, tuple[float, str]],
        link_note: str = "",
    ) -> Finding:
        """本板读数小结：几颗电阻、几颗判得了、几颗读不出（含要问的网名）。"""
        priced = [
            ref
            for ref, edge, _why, _value in readings
            if edge.net_a in volts and edge.net_b in volts
        ]
        unknown_packages = [
            ref
            for ref, _edge, _why, _value in readings
            if chip_limit(self._footprint_name(ctx, ref)) is None
        ]
        unknown_values = [
            ref for ref, edge, _why, _value in readings if edge.ohms is None
        ]
        wanted = sorted(
            {net for _ref, nets in unpriced for net in nets} - set(volts)
        )
        parts = [
            f"{ctx.board_title} 电阻降额读数：认出 {len(readings)} 颗电阻"
            f"（另有 0 Ω 跳线 {len(jumper)} 颗、位号像电阻但值与库件都没说是电阻的 "
            f"{len(unidentified)} 颗，本规则不判它们）",
            f"两脚都有价的 {len(priced)} 颗、封装档认得出的 "
            f"{len(readings) - len(unknown_packages)} 颗、串联串 {len(strings)} 条",
        ]
        evidence = [
            "判定的两造都是声明事实：值字段/库件 Type 说这是电阻（不看形状、不看"
            "位号字母、不看焊盘数），两侧网名电压由 139 的双读机制给价"
            "（合同 rails[].voltage / targetVoltage 优先，其次架构枚举），"
            "地网按定义 0 V",
            "封装档出处（每档取各手册最保守值）：" + " | ".join(SOURCES.values()),
            "本规则不发明降额标准：比较就是实际值 vs 手册那一栏，无 80% 系数、"
            "无温度修正；每颗器件至多一条 finding（先耐压、后功率）",
        ]
        if link_note:
            evidence.insert(0, link_note)
        if jumper:
            evidence.append("0 Ω 跳线（不是电阻档的事）：" + ", ".join(jumper))
        if unknown_packages:
            evidence.append(
                f"封装档认不出的 {len(unknown_packages)} 颗（通孔/无尺寸码/表里没这一"
                "档）本规则不出 verdict：" + ", ".join(unknown_packages)
            )
        if unknown_values:
            evidence.append(
                f"阻值读不出的 {len(unknown_values)} 颗（耐压那一路照判，功率那一路"
                "没有数）：" + ", ".join(unknown_values)
            )
        if unidentified:
            evidence.append(
                "位号像电阻但本规则没有认它（值字段不是欧姆写法，库件 Type 也没说"
                "电阻——本规则不从位号字母猜器件类型）：" + ", ".join(unidentified)
            )
        if divergent:
            evidence.append(
                f"两个视图的 Value 字段不一致的 {len(divergent)} 颗（原理图的声明优先，"
                "PCB 文档的值只在原理图没写时用作回退）："
                + ", ".join(divergent[:3])
                + (f" 等 {len(divergent)} 颗" if len(divergent) > 3 else "")
                + " ——实测这处漂移是**系统性**的：PCB 文档那一侧的 Value 字段多为占位值"
                "（毕设FOC 1.1.0 PCB1 的 45 颗里 23 颗写 100nF、20 颗写 10K），所以"
                "值只能以原理图的声明为准；本规则如实记下，不静默取一个"
            )
        if unpriced:
            evidence.append(
                f"两脚里至少一脚没有价的 {len(unpriced)} 颗：读不出的网 "
                + ", ".join(repr(net) for net in wanted)
                + " ——这些网的定价走 139 的 intent-missing 名单（"
                "requirements.rails[net=…].voltage），本规则不重复枚举、不猜电压"
            )
        else:
            evidence.append("本板每颗电阻的两个脚都在有价的网上（没有读不出的件）")
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message="；".join(parts),
            evidence=evidence,
        )


#: 串联串 INFO 读数逐条出的上限，超过则合并成一条计数行（E1/E2 的防刷屏口径）。
SERIES_READING_CAP = 8
