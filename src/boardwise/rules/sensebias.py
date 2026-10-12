"""采样链偏置电压检查（issue #76；岳裁 2026-10-12）。

岳的原话：「凡是采样，尤其是交流部分的采样，都要去查它有没有偏置电压。」
台架实证（ROBOT ctrl FOC 板）：低边分流直连 MCU ADC、没有偏置，上不了机；
飞线补一颗偏置电阻之后正常。这条规则就是把那次实证变成一次看得见的检查。

**识别什么**：一条采样链 = 一颗**毫欧级分流电阻**（值解析后 ≤
:data:`MAX_SHUNT_OHMS`，0Ω 跳线不算），它的一端网（采样节点）上**直接**坐着
MCU 的 ADC 候选脚或运放输入脚。中间隔着串阻/滤波的链（毕设 FOC 的 10mΩ 经
1k 进 TLV9062 那种）不在本条的范围里——"直达"是这个规则的名字，不是省略。

**分级（岳 2026-10-12 已裁，四级）**，判据按这个顺序读：

* **有偏置** → 过；但**低边 + 有偏置 + 无滤波**还要提一句补 RC（INFO）；
* **无偏置、采样节点不是地参考**（参照端是母线，还是相线串联那种两端都活的
  in-line 形态）→ **ERROR**：交流/双向电流的负半周把节点拉到参考地以下，
  负压直接怼在 MCU 输入脚上；
* **无偏置、低边分流直连 ADC** → **WARN**：窗口塌缩（台架实证那一档）；
* **无偏置、低边走运放输入** → **INFO** 提请注意：偏置可能由运放自己送进来
  （另一输入脚的 VREF/2 之类），图纸上读不出来，不判它缺偏置。

**ADC 脚知识分两级，evidence 里逐条写明依据等级**（task 176 的要求：不许假装
确定）：先查货架（该器件条目的 ``category == "ic.mcu"``，这是本仓库已有的
parts 库知识），没有就在 MPN/名称里找 MCU 家族标记，再配脚名形态
``P<口><号>``（``PA7``/``PB0``/``PC14-OSC32_IN`` 取前段，形态判断走
``core.pintable.port_pin_of`` 那一份实现）。货架里**没有**任何 ADC 通道表，
所以脚名表只说"这是一个 MCU 端口脚"，不说"这一脚真的带 ADC"——SWD 调试脚
（PA13/PA14/PA15/PB3/PB4）与名字带 OSC 的振荡器脚排除在外。

**pintable 这一路查过了，走不通**（task 176 点名要看）：本仓库确实有固件引脚表
这一件既有数据（``core.pintable``，``function`` 词表里就有 ``ADC``），但它是
**按项目手写的独立文件**（``inputs/<project>/pintable.json``，由
``boardwise pintable check`` 消费），既不从 ``.epro2`` 的 ``DesignModel`` 可达，
也没有任何规则接口把它带进走查；夹具工程一个 pintable 都没有。所以本条拿不到它，
按最小启发判，并把这句写进 evidence 的依据等级里——将来若 pintable 能挂到读法上，
升级点就是 :meth:`SamplingBias._mcu_basis` 一处。

**它是什么，不是什么**：这是一条 L1 无源启发（与同族的 ``shunt-sense-link``
同一层、同一形状），读位号前缀、值、网成员和货架条目，不读几何、不读数据手册。
"有没有偏置"是**存在性**判据：偏置源内阻与采样电阻的比值、偏置到底抬不抬得
起来，是 ``arch-sense-bias-closure`` 那条合同驱动的规则用 Thévenin 算术管的事，
本条只在消息里点它一句，不复算、不越权。与 ``shunt-sense-link`` 一样它是
legacy ``Rule``（没有四态协议），所以 :data:`boardwise.rules.unproven.
NET_MEMBERSHIP_RULES` 里没有它——焊死的网名它做不到报 UNKNOWN，只能像同族
那颗一样安静地不判（声明的缺口，见那个模块的注）。
"""

from __future__ import annotations

import re

from ..core.model import Component, DesignModel, is_ground_net
from ..core.parts import is_ic_designator
from ..core.pintable import port_pin_of
from ..core.power_domains import infer_net_domains
from ..core.values import parse_capacitance_farads, parse_resistance_ohms
from .archclosure import _power_class, _resistor_like
from .base import Finding, FindingTarget
from .facts import FactsRule

LEVEL = "L1-connectivity"

#: 分流电阻的毫欧级上限。"毫欧级"这句话要有一个数：岳 2026-10-12 的实证锚是
#: R4/R5 两颗 100mΩ（ROBOT ctrl FOC，台架），毕设 FOC 驱动板是 10mΩ。0.5Ω 是从
#: 实测的 0.1Ω 往上留一档——夹具里 0.1Ω 之上的下一颗电阻是 100Ω，所以这条线落在
#: 哪里并不吃数据，它是一个**声明**（与 ``shunt-sense-link`` 的 50mΩ 各说各的：
#: 那条只看"检出连路没有"，本条要连 100mΩ 的板一起看）。
#:
#: evidence-boards: ProPrj_毕设FOC驱动板_2026-09-17
#: （ROBOT ctrl FOC 那一块没有评审集记录，声明不了；有记录的那块写在这里。）
MAX_SHUNT_OHMS = 0.5

#: MCU 家族标记（最小启发用）。第一级依据是货架条目的 ``category == "ic.mcu"``；
#: 货架没这条目时才退到这里：MPN 或名称里带家族标记 + 脚名是端口脚形态。
#: STM32 之外的家族写进来是因为这条判断与 STM32 无关——``PA7`` 这种脚名
#: 是国产 Cortex-M 家族共用的拼法。
MCU_FAMILY_TOKENS: tuple[str, ...] = (
    "STM32", "STM8", "GD32", "AT32", "APM32", "MM32", "HC32", "CH32",
    "LPC", "ATSAM", "ATMEGA", "ATTINY", "MSP430", "EFM32", "NRF5",
    "RP2040", "PIC16", "PIC18", "PIC24", "PIC32",
)

#: 端口脚里**不作 ADC 候选**的：SWD/JTAG 调试脚。理由是它们在这几个家族里
#: 是调试口专用，判成 ADC 输入会把一次"分流电阻画在调试脚上"说成"采样链偏置
#: 缺失"，两件事不一样。这是启发的一部分，不是数据手册的断言。
DEBUG_PINS: frozenset[str] = frozenset({"PA13", "PA14", "PA15", "PB3", "PB4"})

#: 运放输入脚的脚名形态：``IN+`` / ``IN-`` / ``INA+`` / ``VIN-`` / ``IA+``。
_OPAMP_INPUT = re.compile(r"^(?:V?IN[A-D]?|I[A-D])[+-]$")


def _port_pin(name: str | None) -> str:
    """脚名里的端口脚本体（``PA7``），不是端口脚时返回空串。

    形态判断走 :func:`boardwise.core.pintable.port_pin_of` —— 仓库里"什么是一个
    端口脚名"只有那一份实现（pintable 装载器、``.ioc`` 读者与交叉核对共用它），
    这里不再抄一份正则：本规则的脚名读法要与本仓库既有读法逐字一致，包括
    ``PC14-OSC32_IN`` 取前段这件事。
    """
    return port_pin_of(name or "")


def _is_opamp_input_name(name: str | None) -> bool:
    return bool(_OPAMP_INPUT.match((name or "").replace(" ", "").upper()))


class _Reach:
    """一个"采样节点上坐着谁"的读数：哪颗器件的哪一脚，以及依据等级。"""

    __slots__ = ("designator", "pin", "name", "kind", "basis")

    def __init__(self, designator, pin, name, kind, basis):
        self.designator = designator
        self.pin = pin
        self.name = name
        self.kind = kind  # "adc" | "opamp"
        self.basis = basis

    def where(self) -> str:
        return f"{self.designator} pin{self.pin}（{self.name}）"


class SamplingBias(FactsRule):
    """一条采样链该有偏置电压——交流/双向的那一半没有就是 ERROR。

    与 ``shunt-sense-link`` 同一族的 L1 启发（同样的位号/值/网成员读法），
    区别是它问的问题从"分流电阻有没有连进 IC"变成了"连进去的那个节点有没有
    偏置"，也就是岳 2026-10-12 那句话。它继承 :class:`FactsRule` 只为货架
    管线（器件条目 → ``category``、以及 ``infer_net_domains`` 要的 shelf），
    **不**取四态协议：认知边界与同族那颗一样，在模块 docstring 里写明了。

    每一条链（一颗分流电阻 × 一个采样节点）最多出一条 finding；一条都没问题的
    板一个字都不出（"有偏置过"就是过，不是"查过且没事"的测量行——本条是
    legacy ``Rule``，没有四态可说）。
    """

    id = "path-sampling-bias"
    title = "A shunt-sampling chain that reaches an MCU input carries a bias"
    level = LEVEL
    source = (
        "岳 2026-10-12 裁定（issue #76：凡是采样、尤其是交流部分的采样，都要去查"
        "它有没有偏置电压）；台架实证 ROBOT ctrl FOC（无偏置上不了机，飞线补偏置"
        "电阻后正常）。ADC 脚知识：货架条目 category=ic.mcu 优先，退最小启发"
        "（MCU 家族标记 + 脚名 P<口><号>），依据等级逐条写在 evidence 里"
    )

    # ------------------------------------------------------------- the walk

    def check(self, model: DesignModel) -> list[Finding]:
        guesses = infer_net_domains(model, self.library)
        findings: list[Finding] = []
        for key in sorted(model.components):
            comp = model.components[key]
            if not self._is_shunt(comp):
                continue
            nets = sorted(
                {pin.net for pin in comp.pins if pin.net is not None}
            )
            # 分流电阻是一个两端的元件；一端悬空或三端以上的，本条不猜它的形态。
            if len(nets) != 2:
                continue
            for sense, reference in ((nets[0], nets[1]), (nets[1], nets[0])):
                reach = self._reaches(model, sense, shunt=comp.designator)
                if not reach:
                    continue
                row = self._row(model, guesses, comp, sense, reference, reach)
                if row is not None:
                    findings.append(row)
        return findings

    # ------------------------------------------------------- identification

    def _is_shunt(self, comp: Component) -> bool:
        """毫欧级分流电阻：R 位号 + 值读得出来且落在 (0, :data:`MAX_SHUNT_OHMS`]。"""
        if not comp.designator.startswith("R"):
            return False
        ohms = parse_resistance_ohms(comp.value or "")
        # 0Ω 是跳线不是分流电阻（``shunt-sense-link`` 早就这么判）；读不出来的
        # 值（空值、``1%`` 之类的残文）也是"读不出"，不是"零欧"。
        if ohms is None or ohms <= 0:
            return False
        return ohms <= MAX_SHUNT_OHMS

    def _entry_category(self, comp: Component) -> str:
        entry = self.entry_for(comp)
        return str(getattr(entry, "category", "") or "") if entry else ""

    def _part_text(self, comp: Component) -> str:
        return " ".join(
            str(part or "") for part in (comp.mpn, comp.value, comp.designator)
        ).upper()

    def _mcu_basis(self, comp: Component) -> str:
        """这颗器件算不算 MCU——依据等级原样返回，判不出来时返回空串。

        第一级：货架条目自己说 ``category == "ic.mcu"``（本仓库已有的 parts 库
        知识，最强）。第二级：MPN/名称里有家族标记（最小启发）。都不成立就
        不认——"脚名长得像 PA7" 单独不足以把一颗料判成 MCU。
        """
        entry = self.entry_for(comp)
        category = str(getattr(entry, "category", "") or "") if entry else ""
        if category == "ic.mcu":
            return (
                f"货架条目 {getattr(entry, 'key', '') or comp.mpn} 的 category=ic.mcu"
                "（parts 库知识）"
            )
        text = self._part_text(comp)
        for token in MCU_FAMILY_TOKENS:
            if token in text:
                if category:
                    return (
                        f"MPN/名称里的 MCU 家族标记 {token}（最小启发；货架条目 "
                        f"{getattr(entry, 'key', '') or comp.mpn} 的 category="
                        f"{category}，不是 ic.mcu——按家族名判，不按货架）"
                    )
                return (
                    f"MPN/名称里的 MCU 家族标记 {token}（最小启发，parts 库里没有"
                    "这条目）"
                )
        return ""

    def _reaches(
        self, model: DesignModel, sense: str, *, shunt: str
    ) -> list[_Reach]:
        """采样节点网 ``sense`` 上直接坐着的 MCU ADC 候选脚 / 运放输入脚。"""
        node = model.nets.get(sense)
        if node is None:
            return []
        found: list[_Reach] = []
        for designator, pin_number in sorted(node.pins):
            if designator == shunt:
                continue
            comp = model.components.get(designator)
            if comp is None:
                continue
            pin = next(
                (p for p in comp.pins if p.number == pin_number), None
            )
            if pin is None:
                continue
            name = pin.name or ""
            token = _port_pin(name)
            if token and token not in DEBUG_PINS and "OSC" not in name.upper():
                basis = self._mcu_basis(comp)
                if basis:
                    found.append(
                        _Reach(
                            designator,
                            pin_number,
                            name,
                            "adc",
                            f"{basis}；脚名 {name} 是 P<口><号> 形态的 ADC 候选脚"
                            "——本仓库没有数据手册 ADC 通道表，这里只说它是 MCU "
                            "端口脚，不说这一脚真的带 ADC",
                        )
                    )
                    continue
            if _is_opamp_input_name(name):
                category = self._entry_category(comp)
                # 运放这一路也要求它是 IC 位号（仓库里"什么位号算 IC"只有
                # `core.parts.is_ic_designator` 一份答案），或者货架说它是运放：
                # 排针上一脚叫 `IN+` 是接线端子，不是放大器输入。
                if not (is_ic_designator(comp.designator) or category == "ic.opamp"):
                    continue
                if category == "ic.opamp":
                    basis = f"货架条目 category={category}（parts 库知识）"
                elif category:
                    basis = (
                        f"货架条目 category={category}（不是 ic.opamp），"
                        "位号是 IC；脚名按最小启发读"
                    )
                else:
                    basis = "货架里没有这条目（最小启发：位号是 IC + 只看符号脚名）"
                found.append(
                    _Reach(
                        designator,
                        pin_number,
                        name,
                        "opamp",
                        f"{basis}；脚名 {name} 是运放输入脚的形态",
                    )
                )
        return found

    # ------------------------------------------------------- bias / filter

    def _foreign_parts(
        self, model: DesignModel, net: str, *, shunt: str
    ) -> list[tuple[Component, str | None]]:
        """网上的外来器件：``[(component, 它在这一网之外的那一脚的网), …]``。"""
        node = model.nets.get(net)
        if node is None:
            return []
        out: list[tuple[Component, str | None]] = []
        seen: set[str] = set()
        for designator, _pin_number in sorted(node.pins):
            if designator == shunt or designator in seen:
                continue
            seen.add(designator)
            comp = model.components.get(designator)
            if comp is None:
                continue
            far = next((p.net for p in comp.pins if p.net != net), None)
            out.append((comp, far))
        return out

    def _divider_mid(self, model: DesignModel, guesses: dict, net: str) -> str:
        """``net`` 是不是一个分压中点——是则返回一句依据，否则空串。

        「一只到 power-class 轨 + 一只到地」的配对（``arch-sense-bias-closure``
        定价的那种形态）。判据共用 :func:`_power_class`，所以"什么是 power-class
        轨"在这条规则和那条规则里是同一个定义。
        """
        to_rail = ""
        to_ground = ""
        for comp, far in self._foreign_parts(model, net, shunt=""):
            if not _resistor_like(self, comp):
                continue
            if far and is_ground_net(far):
                to_ground = to_ground or f"{comp.designator}（{comp.value}）→ {far}"
            else:
                because = _power_class(guesses, far)
                if because:
                    to_rail = to_rail or (
                        f"{comp.designator}（{comp.value}）→ {far}（{because}）"
                    )
        if to_rail and to_ground:
            return f"分压中点：{to_rail} + {to_ground}"
        return ""

    def _bias(self, model: DesignModel, guesses: dict, sense: str, *, shunt: str) -> str:
        """采样节点上的偏置来源——一句话，没有就空串。

        「有偏置」只判**有没有把节点抬离地**：一只外来电阻（不是分流电阻自己）
        远端落在 power-class 轨上（串阻直接接轨），或远端是一个分压中点。
        远端只落到地/别的信号网的电阻是负载/串阻，不是偏置，不算。
        """
        for comp, far in self._foreign_parts(model, sense, shunt=shunt):
            if not _resistor_like(self, comp):
                continue
            if not far or is_ground_net(far):
                continue
            because = _power_class(guesses, far)
            if because:
                return (
                    f"{comp.designator}（{comp.value}）从 {sense} 接到 {far}"
                    f"（power-class 轨，依据：{because}）"
                )
            mid = self._divider_mid(model, guesses, far)
            if mid:
                return (
                    f"{comp.designator}（{comp.value}）从 {sense} 接到分压中点 {far}"
                    f"（{mid}）"
                )
        return ""

    def _filter(self, model: DesignModel, sense: str, *, shunt: str) -> str:
        """采样节点上到地的滤波电容——一句话，没有就空串。"""
        for comp, far in self._foreign_parts(model, sense, shunt=shunt):
            if far is None or not is_ground_net(far):
                continue
            entry = self.entry_for(comp)
            category = str(getattr(entry, "category", "") or "")
            is_cap = (
                category == "capacitor"
                if category
                else parse_capacitance_farads(comp.value or "") is not None
            )
            if is_cap:
                return f"{comp.designator}（{comp.value}）从 {sense} 到 {far}"
        return ""

    # -------------------------------------------------------------- the row

    def _row(
        self,
        model: DesignModel,
        guesses: dict,
        comp: Component,
        sense: str,
        reference: str,
        reach: list[_Reach],
    ) -> Finding | None:
        shunt = comp.designator
        value = comp.value or ""
        bias = self._bias(model, guesses, sense, shunt=shunt)
        filt = self._filter(model, sense, shunt=shunt)
        rail_because = _power_class(guesses, reference)
        ground_referenced = is_ground_net(reference)
        adc = [r for r in reach if r.kind == "adc"]
        kinds = "、".join(r.where() for r in reach)
        members = ", ".join(
            f"{des}.{pin}"
            for des, pin in sorted(
                (model.nets.get(sense).pins if model.nets.get(sense) else [])
            )
        )

        if bias:
            if not (ground_referenced and not filt):
                return None  # 有偏置、低边又补了滤波：过。
            severity = "INFO"
            message = (
                f"{shunt}（{value}）的采样节点 {sense} 有偏置（{bias}），"
                f"但节点上没有到地的滤波电容。偏置链是慢的、这个节点是有开关噪声的，"
                "零点会跟着抖——校准余量被噪声吃掉，采出来的电流在小信号段不可信。"
                "修法：在采样节点补一颗到地的 RC 滤波（时间常数按开关频率与电流环"
                f"带宽取）。这条链的走向：{sense} 上坐着 {kinds}。"
            )
        elif not ground_referenced:
            severity = "ERROR"
            where = (
                f"参照端 {reference} 是 power-class 母线（{rail_because}）"
                if rail_because
                else f"参照端 {reference} 既不是地、也不是可定价的母线（两端都活的"
                "相线串联形态）"
            )
            message = (
                f"{shunt}（{value}）的采样节点 {sense} 没有偏置，而且它不接地参考"
                f"（{where}），却直接坐着 {kinds}。交流/双向电流的负半周会把节点"
                "拉到参考地以下——负压直接怼在 MCU/运放输入脚上，超出绝对最大"
                "额定值是损坏级，不只是量程里少读一段。台架实证（岳 2026-10-12，"
                "issue #76）：ROBOT ctrl FOC 板无偏置上不了机，飞线补偏置电阻后正常。"
                "修法：把该节点偏置到 ADC 参考中点（如 VREF/2）后再进输入脚；"
                "偏置源内阻与采样电阻的比值是否真的闭合，由 arch-sense-bias-closure "
                "用 Thévenin 算术判——本条只查「有没有画」。"
            )
        elif adc:
            severity = "WARN"
            message = (
                f"{shunt}（{value}）是低边分流，采样节点 {sense} 直连 "
                f"{kinds}，整条链上量不到偏置电压（"
                + (
                    "网上没有到轨的电阻或分压中点把节点抬离地，也没有到地的滤波电容"
                    if not filt
                    else f"网上没有把节点抬离地的电阻；已有到地的滤波（{filt}），"
                    "但滤波不解决偏置"
                )
                + "）。低边分流的采样窗口只有 0 ~ I×R 的单极性那一段："
                "电流反向时窗口塌缩到地，负半周读不出来，零点又没有校准余量。"
                "台架实证（岳 2026-10-12，issue #76）：ROBOT ctrl FOC 板就是这样"
                "上不了机，飞线补一颗偏置电阻后正常。修法：把采样节点偏置到 ADC "
                "参考中点（如 VREF/2），偏置源内阻要远小于采样电阻——闭合与否由 "
                "arch-sense-bias-closure 算，本条只查有没有画。"
                "启发式边界：分流电阻按「R 位号 + 值 ≤ "
                f"{MAX_SHUNT_OHMS:g}Ω」认，ADC 脚按货架 category 或脚名表认，"
                "都写在 evidence 里。"
            )
        else:
            severity = "INFO"
            message = (
                f"{shunt}（{value}）的采样节点 {sense} 直连 {kinds}，网上查不到偏置。"
                "运放自己可能已经把偏置送进来了（另一输入脚接 VREF/2 之类的参考），"
                "但那不画在这个采样节点上，离线读不出来——所以这一条只是提请注意，"
                "不是判它缺偏置。请确认该运放的参考/偏置来源；若没有，这条链同样会"
                "在负半周把节点拉出运放的输入共模范围。"
            )

        evidence = [
            f"{shunt}（{value}）@ {sense} / {reference}（{sense} 侧是采样节点）",
        ]
        if model.nets.get(sense) is not None:
            evidence.append(f"{sense} 成员：{members or '（网里没有成员）'}")
        for item in reach:
            evidence.append(f"{item.where()} @ {sense} —— {item.basis}")
        if bias:
            evidence.append(f"偏置：{bias}；滤波：{filt or '节点上没有到地的电容'}")
        else:
            evidence.append(
                "偏置：网上没有把该节点抬离地的电阻（到轨串阻或分压中点都没有）；"
                f"滤波：{filt or '节点上没有到地的电容'}"
            )
        return Finding(
            rule_id=self.id,
            severity=severity,
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(
                component_ref=shunt,
                pin_refs=[
                    p.number for p in comp.pins if p.net == sense
                ],
                net_refs=[sense],
            ),
        )
