"""The architecture skeleton (task 044 M1) — deterministic chain scaffolding.

Why this exists: the ROBOT ctrl FOC blind review missed a **chain-level** defect
while every part-level rule passed. The U-phase shunt's top node goes straight to
an STM32 ADC pin with no bias network, so a bidirectional phase current cannot be
measured by a single-supply ADC — and no local rule can see that, because R4 is a
fine resistor, PA7 is a fine pin mapping, and the two-resistor topology is fine
too. The missing step is teleological: *what is this chain for, and does it close
end to end?* 岳's prescription is to force that step by making the review produce
an architecture artifact.

This module produces the **skeleton** of that artifact and nothing more. It is
deliberately not a rule and not an inference engine: it enumerates the four chain
families the task book names (§2), writes one block per chain with the members it
can *see* in the netlist, and leaves every question a tool cannot answer as an
explicit ``TODO`` slot with a fixed English key. The AI fills the slots and does
the consistency walk (see SKILL "架构走查"); a slot it cannot fill for the design
becomes a question for the engineer (§6), never a guess by the tool.

What it therefore refuses to decide: a rail's source, a rail's target voltage when
nothing in the project states one, an analog chain's quantity / range / polarity /
reference / gain / filter / source impedance, a chain's end-to-end consistency,
and any design-intent number. §6's *capability-mismatch questions* (regulator 5 A
vs a 2.62 A inductor) are **not** generated here either: they need the intent
slots filled first, and an engineer's answer to compare against.

Determinism is a contract, not a nicety: two runs on the same model produce
byte-identical markdown. Everything iterates in sorted order, nothing carries a
timestamp, and a chain's member list is sorted — a skeleton that varies between
runs cannot be diffed, and a diff is how a human reviews it (and how the intent
slots stay a living document).

Offline and self-contained: the model in, markdown and a count summary out. No
network, no clock, no randomness, no bridge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Component, DesignModel, is_ground_net
from .parts import PartLibrary, category_of, find_facts
from .power_domains import (
    domain_of,
    infer_net_domains,
    ldo_output_pin,
    voltage_from_net_name,
)

#: The file name the report points at (the CLI writes it beside report.json).
ARCH_FILE_NAME = "architecture.md"

#: The slot placeholder. One spelling, so a reader (or a test, or the AI) can
#: find every slot the same way and count what is still owed.
TODO = "TODO"

#: Chain families (task 044 §2). The intent block (§6) is a fifth list of slots.
KIND_POWER = "power"
KIND_ANALOG = "analog"
KIND_CONTROL = "control"
KIND_BUS = "bus"
KIND_INTENT = "intent"

#: Fixed slot vocabularies. English keys, because a machine parses the skeleton;
#: the section headings and prose are Chinese, because 岳 reads them.
POWER_SLOTS = ("voltage", "source")
ANALOG_SLOTS = (
    "quantity",          # 被测物理量
    "range",             # 量程
    "polarity",          # 极性：单向 / 双向
    "reference",         # 参考点
    "gainStage",         # 增益级
    "filter",            # 滤波
    "sourceImpedance",   # 源阻抗
    "consistency",       # 端到端自洽性（填完上面几项后这条链还成立吗）
)
CONTROL_SLOTS = (
    "endpointConsistency",   # 网名 vs 端点复用功能是否一致（TIM1 案的机械入口）
    "consistency",           # 端到端自洽性
)
BUS_SLOTS = (
    "completeness",          # 成员是否完整（终端/上下拉/收发器/方向）
    "consistency",
)
INTENT_SLOTS = (
    "targetVoltage",         # 目标电压
    "continuousCurrent",     # 连续电流
    "peakCurrent",           # 峰值电流
    "operatingCases",        # 关键工况
)

SLOT_VOCABULARY: dict[str, tuple[str, ...]] = {
    KIND_POWER: POWER_SLOTS,
    KIND_ANALOG: ANALOG_SLOTS,
    KIND_CONTROL: CONTROL_SLOTS,
    KIND_BUS: BUS_SLOTS,
    KIND_INTENT: INTENT_SLOTS,
}

#: Slot key -> the Chinese gloss printed beside it, so the AI (and 岳) knows what
#: is being asked without reading this module.
SLOT_LABELS: dict[str, str] = {
    "voltage": "电压",
    "source": "来源（哪颗器件/哪个接插件把它供起来的）",
    "quantity": "被测物理量",
    "range": "量程",
    "polarity": "极性（单向 / 双向）",
    "reference": "参考点（相对谁测）",
    "gainStage": "增益级",
    "filter": "滤波",
    "sourceImpedance": "源阻抗",
    "consistency": "端到端自洽性（这条链是干什么的、能不能闭合）",
    "endpointConsistency": "网名 vs 端点复用功能是否一致",
    "completeness": "成员完整性（终端 / 上下拉 / 收发器 / 方向）",
    "targetVoltage": "目标电压",
    "continuousCurrent": "连续电流",
    "peakCurrent": "峰值电流",
    "operatingCases": "关键工况",
}

#: Pin names that declare a **supply** pin. Used to decide which nets are rails —
#: never to decide a voltage (that is the domain inference's job, and a name is
#: not a declaration). Return pins are deliberately **not** here: a driver's
#: ``PGND1`` pins sit on the low-side shunt node (measured on the ROBOT board,
#: where `U+` = {U1.PA7, DRV1.PGND1, R4} — a current-sense chain, not a rail), and
#: reading that name as "this net is a power rail" buried the very chain task 043
#: was filed for.
_SUPPLY_PIN = re.compile(
    r"^(VDD|VDDA|VDDIO|DVDD|AVDD|VCC|VBAT|VREF\+?|VIN|VM|VBUS|V\+|VS)$",
    re.IGNORECASE,
)

#: Pin names that declare a **return** pin (ground side, exposed pad). A net whose
#: pins are *all* returns is a ground island that happens to have a project name
#: (`NET11` = the STM32's VSSA tied through R8): it is a reference, not a rail.
_RETURN_PIN = re.compile(
    r"^(VSS\d?|VSSA|GND\d?|AGND|PGND\d?|DGND|EP|PAD|VEE)",
    re.IGNORECASE,
)

#: A pin named like a GPIO port (``PA7``, ``PB12``, ``PC2``, ``PF0-OSC_IN``). A
#: part whose symbol names several pins this way is a **controller candidate** —
#: structural evidence, not a family-name guess. The shelf's own `category:
#: ic.mcu` is the stronger signal and wins when it is there.
_PORT_PIN = re.compile(r"^P[A-H]\d{1,2}(?![0-9])")

#: How many port-named pins make a part a controller candidate. A 4-pin regulator
#: cannot have four GPIO ports; anything that does is a processor-class part.
PORT_PIN_THRESHOLD = 4

#: A chain needs at least this many members: a net with one pin connects nothing.
MIN_CHAIN_MEMBERS = 2

#: Bus families, by net-name pattern (task 044 §2.4). Order matters only for the
#: report's own listing; a net matching two families is listed under both and the
#: AI decides (the golden board's `VBUS` is a rail *and* a USB signal name).
BUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CAN", re.compile(r"^CAN(_|[HL]$|[TR]X$)", re.IGNORECASE)),
    ("SPI", re.compile(
        r"^(SPI\d?(_?(SCK|CLK|MISO|MOSI|NSS|CS))?|SCK|SCLK|MISO|MOSI|NSS|NSCS|SS)$",
        re.IGNORECASE)),
    ("UART", re.compile(r"^(UART\d?|USART\d?|TX[A-Z]?\d?|RX[A-Z]?\d?|TXD|RXD)$", re.IGNORECASE)),
    ("I2C", re.compile(r"^((I2C|IIC)\d?(_?(SCL|SDA))?|SCL|SDA)$", re.IGNORECASE)),
    ("USB", re.compile(
        r"^(USB_?D[PMN]|D\+|D-|DN|DP|USB_?VBUS|VBUS|USB_?CC\d?|CC\d?|SBU\d?)$",
        re.IGNORECASE)),
)

#: Control-chain net names (task 044 §2.3): the MCU pin that should be driving a
#: gate/enable/communication line, plus the driver's own control pins.
CONTROL_PATTERN = re.compile(
    r"^(TIM\d+|PWM|GATE|G\d|EN(_?[A-Z0-9]+)?|IN[HL]?[A-Z]?|INH|NSLEEP|NFAULT|"
    r"NRESET|RESET|DIR|BRAKE|OCP|SLP|SLEEP|FOC_EN)",
    re.IGNORECASE,
)

#: Shelf categories that can legitimately be where a rail comes from. The list is
#: a *candidate* list: nothing here decides that the part actually feeds the rail.
_RAIL_SOURCE_CATEGORIES = frozenset({"ic.ldo", "ic.charger", "module"})

#: How many of a member's other nets to print per chain. A 64-pin MCU touches
#: dozens; the point is to show the local shape, not to re-print the netlist.
NEIGHBOUR_LIMIT = 6


@dataclass(frozen=True)
class ArchResult:
    """What :func:`generate_architecture` returns.

    ``markdown`` is the artifact itself (written to ``architecture.md``);
    ``section`` is the count summary the checkup report carries under
    ``architecture`` — the chains' names and members plus the per-board counts,
    so a machine can see what the AI was asked to walk without parsing prose.
    """

    markdown: str
    section: dict


@dataclass
class _Chain:
    """One chain's skeleton, before it is rendered."""

    kind: str
    board: str
    name: str
    members: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    slots: tuple[str, ...] = ()


@dataclass
class _Rail:
    """One power rail's skeleton."""

    board: str
    net: str
    voltage: float | None = None
    voltage_source: str = ""
    voltage_why_not: str = ""
    source_candidates: list[str] = field(default_factory=list)
    loads: list[str] = field(default_factory=list)


def _part_text(component: Component) -> str:
    """A part's own name for pattern use — the same four fields the checkup
    naming uses, and deliberately **not** the supplier code (039's measured
    false positive: `C57895` reads as a 7800-series regulator)."""
    return " ".join(filter(None, [
        str(component.props.get("device_name") or ""),
        component.value or "",
        component.mpn or "",
        component.footprint or "",
    ]))


def _entry_for(component: Component, library: PartLibrary | None):
    """The shelf entry for a part, exact-match identity only (find_facts' rule)."""
    if library is None:
        return None
    entry = None
    if component.mpn:
        entry = find_facts(library, mpn=component.mpn)
    if entry is None and component.lcsc_part:
        entry = find_facts(library, lcsc=component.lcsc_part)
    return entry


def _controller_evidence(component: Component, library: PartLibrary | None) -> str:
    """Why this part may be a controller — or ``""`` when nothing says so.

    Two evidence sources, strongest first: the shelf's own classification
    (``category: ic.mcu``) and the symbol's pin names (several ``P<port><n>``
    pins). Both are facts about the project; neither is a family-name guess, and
    a part none of them fits simply is not a chain anchor — its identity stays
    unstated rather than being filled in by pattern luck.
    """
    entry = _entry_for(component, library)
    if entry is not None and entry.category == "ic.mcu":
        return f"货架 category=ic.mcu（{entry.key}）"
    ports = [pin.name for pin in component.pins if _PORT_PIN.match(pin.name or "")]
    if len(ports) >= PORT_PIN_THRESHOLD:
        return (
            f"符号里 {len(ports)} 个引脚用 P<端口><数字> 命名"
            f"（{', '.join(sorted(ports)[:4])}…）"
        )
    return ""


def _net_members(board: DesignModel, net_name: str) -> list[str]:
    """``["U1.21", "DRV1.6", "R4.2"]`` — the net's pins, sorted."""
    net = board.nets.get(net_name)
    if net is None:
        return []
    return sorted(f"{designator}.{pin}" for designator, pin in net.pins)


def _pin_name(board: DesignModel, designator: str, number: str) -> str:
    component = board.components.get(designator)
    if component is None:
        return ""
    for pin in component.pins:
        if pin.number == number:
            return pin.name or ""
    return ""


def _member_detail(board: DesignModel, entry: str) -> str:
    """``U1.21`` -> ``U1.21(PA7)``; the pin name is the endpoint-function evidence."""
    designator, _, number = entry.partition(".")
    name = _pin_name(board, designator, number)
    return f"{entry}({name})" if name else entry


def _neighbours(board: DesignModel, net_name: str, limit: int = NEIGHBOUR_LIMIT) -> list[str]:
    """Where each member's part goes *besides* this net — the local shape.

    This is what makes a chain's reference point visible without guessing it: for
    the ROBOT U-phase chain it prints ``R4→GND``, which is the evidence a reviewer
    needs to ask "and how does a negative half-cycle get through that?".
    """
    out: list[str] = []
    for entry in _net_members(board, net_name):
        designator = entry.partition(".")[0]
        component = board.components.get(designator)
        if component is None:
            continue
        others = sorted({pin.net for pin in component.pins if pin.net and pin.net != net_name})
        if not others:
            out.append(f"{designator}→（只接这张网）")
            continue
        shown = others[:limit]
        suffix = f"…(+{len(others) - limit})" if len(others) > limit else ""
        out.append(f"{designator}→{'、'.join(shown)}{suffix}")
    return out


def _is_bus_net(net_name: str) -> list[str]:
    """The bus families this net name matches (possibly none, possibly several)."""
    return [family for family, pattern in BUS_PATTERNS if pattern.search(net_name)]


def _is_return_only(board: DesignModel, net_name: str) -> bool:
    """True when every pin on the net is a return pin (a ground island).

    ``NET11`` on the ROBOT board is the STM32's ``VSSA`` tied through R8 — a
    reference, not a rail and not a chain. Its pins decide it; the name could not.
    """
    pins = board.nets.get(net_name).pins if net_name in board.nets else []
    names = [
        _pin_name(board, designator, number) for designator, number in pins
    ]
    return bool(names) and all(_RETURN_PIN.match(name or "") for name in names)


def _rails(board: DesignModel, library: PartLibrary | None) -> list[_Rail]:
    """The power tree's own view: which nets are rails, and what is on them.

    A net is a rail when something in the project says it is one:

    * a pin on it is named like a **supply** pin (``VDD``/``VCC``/``VIN``…), or
    * its name parses as a voltage (``+12V``), or
    * a shelf regulator's **output pin** sits on it.

    Ground nets are the *reference* and are returned by :func:`_ground_nets`; a
    net whose pins are all returns is a reference too and is skipped here. Both
    exclusions exist because a rail the tool invents swallows the chain it should
    have listed (see :data:`_SUPPLY_PIN`).
    """
    guesses = infer_net_domains(board, library) if library is not None else {}
    ldo_outputs: set[str] = set()
    if library is not None:
        for designator in sorted(board.components):
            component = board.components[designator]
            entry = _entry_for(component, library)
            if entry is None or entry.category != "ic.ldo":
                continue
            output_pin = ldo_output_pin(entry)
            if not output_pin:
                continue
            for pin in component.pins:
                if pin.number == output_pin and pin.net:
                    ldo_outputs.add(pin.net)
    rails: list[_Rail] = []
    for net_name in sorted(board.nets):
        if is_ground_net(net_name) or _is_return_only(board, net_name):
            continue
        evidence = [f"{net_name}：货架稳压器输出脚（{_ldo_output_note(board, library, net_name)}）"] if net_name in ldo_outputs else []
        candidates: list[str] = []
        for member in _net_members(board, net_name):
            designator = member.partition(".")[0]
            component = board.components.get(designator)
            if component is None:
                continue
            entry = _entry_for(component, library)
            category = entry.category if entry is not None else ""
            bucket = category_of(component.footprint or "", designator)
            # Candidates are listed by what the part *is*, not by where its pins
            # sit: a regulator touches the rail it feeds and the rail it drains,
            # and which side this is, is exactly the `source` slot's question.
            if category in _RAIL_SOURCE_CATEGORIES or bucket == "conn":
                label = category or bucket
                candidates.append(f"{designator}（{label}）")
            for pin in component.pins:
                if pin.net == net_name and pin.name and _SUPPLY_PIN.match(pin.name):
                    evidence.append(f"{designator}.{pin.number}({pin.name})")
        name_hit = voltage_from_net_name(net_name)
        if name_hit is not None:
            evidence.append(f"名称可解析：{name_hit[1]}")
        if not evidence:
            continue
        volts, source, why_not = domain_of(guesses, net_name)
        if volts is None:
            # The shelf is only needed for the *regulator* half of the domain
            # inference: a rail whose name parses (+5V) is evidence with or
            # without a library, and 044's golden-board test is exactly that case.
            name_only = voltage_from_net_name(net_name)
            if name_only is not None:
                volts, source, why_not = name_only[0], name_only[1], ""
        rails.append(_Rail(
            board="",
            net=net_name,
            voltage=volts,
            voltage_source=source,
            voltage_why_not=why_not,
            source_candidates=sorted(set(candidates)),
            loads=_net_members(board, net_name),
        ))
    return rails


def _ldo_output_note(board: DesignModel, library: PartLibrary | None, net_name: str) -> str:
    """Which shelf regulator's output pin sits on ``net_name`` (evidence text)."""
    if library is None:
        return "?"
    for designator in sorted(board.components):
        component = board.components[designator]
        entry = _entry_for(component, library)
        if entry is None or entry.category != "ic.ldo":
            continue
        output_pin = ldo_output_pin(entry)
        if not output_pin:
            continue
        for pin in component.pins:
            if pin.number == output_pin and pin.net == net_name:
                return f"{designator} {entry.mpn}"
    return "?"


def _ground_nets(board: DesignModel) -> list[str]:
    return sorted(name for name in board.nets if is_ground_net(name))


def _chains_and_rails(
    board: DesignModel, library: PartLibrary | None, board_title: str
) -> tuple[list[_Rail], list[_Chain], dict[str, list[str]], list[str]]:
    """One board's skeleton: rails, analog/control chains, bus groups, leftovers.

    The classification order is fixed and documented, so a net lands in exactly
    one place and a rerun cannot move it: **rail → bus → control → analog**. A net
    with no controller pin and no other claim (a stray ``NET7``, a mounting
    screw) is not a chain at all; it is counted and listed as unclassified rather
    than silently dropped.
    """
    rails = _rails(board, library)
    rail_names = {rail.net for rail in rails}
    controllers = {
        designator: evidence
        for designator, component in sorted(board.components.items())
        if (evidence := _controller_evidence(component, library))
    }

    buses: dict[str, list[str]] = {}
    control: list[_Chain] = []
    analog: list[_Chain] = []
    unclassified: list[str] = []
    for net_name in sorted(board.nets):
        members = _net_members(board, net_name)
        if (
            is_ground_net(net_name)
            or net_name in rail_names
            or _is_return_only(board, net_name)
        ):
            continue
        families = _is_bus_net(net_name)
        if families:
            for family in families:
                buses.setdefault(family, []).append(net_name)
            continue
        anchors = [
            f"{designator}.{pin}"
            for designator, pin in board.nets[net_name].pins
            if designator in controllers
            # A controller's *return* pin (VSSA, the exposed pad) is not a chain
            # anchor: `NET11` on the ROBOT board is the STM32's VSSA tied through
            # R8 — a star point, not a signal chain, and anchoring on it put a
            # ground island into the analog list.
            and not _RETURN_PIN.match(_pin_name(board, designator, pin) or "")
        ]
        if len(members) < MIN_CHAIN_MEMBERS:
            unclassified.append(net_name)
            continue
        if not anchors:
            unclassified.append(net_name)
            continue
        chain = _Chain(
            kind=KIND_CONTROL if CONTROL_PATTERN.match(net_name) else KIND_ANALOG,
            board=board_title,
            name=net_name,
            members=[_member_detail(board, member) for member in members],
            evidence=[
                f"锚点 {anchor}：{controllers[anchor.partition('.')[0]]}"
                for anchor in sorted(anchors)
            ] + [f"邻接 {item}" for item in _neighbours(board, net_name)],
            slots=CONTROL_SLOTS if CONTROL_PATTERN.match(net_name) else ANALOG_SLOTS,
        )
        (control if chain.kind == KIND_CONTROL else analog).append(chain)
    for rail in rails:
        rail.board = board_title
    return rails, [*control, *analog], buses, unclassified


def _render_board(
    board: DesignModel,
    library: PartLibrary | None,
    title: str,
    lines: list[str],
    section_board: dict,
    section_chains: dict,
) -> None:
    """Append one board's five sections, and fill the machine summary in place."""
    rails, chains, buses, unclassified = _chains_and_rails(board, library, title)
    control = [chain for chain in chains if chain.kind == KIND_CONTROL]
    analog = [chain for chain in chains if chain.kind == KIND_ANALOG]

    lines.append(f"## 板：{title}（{len(board.components)} 器件 / {len(board.nets)} 网）")
    lines.append("")
    grounds = _ground_nets(board)
    lines.append(f"参考地（{len(grounds)}）：" + ("、".join(f"`{net}`" for net in grounds) or "（无）"))
    references = sorted(
        name for name in board.nets
        if not is_ground_net(name) and _is_return_only(board, name)
    )
    if references:
        lines.append(
            f"参考地候选（{len(references)}，名字不是 GND，但上面全是回路脚）："
            + "、".join(f"`{net}`" for net in references)
        )
    controllers = {
        designator: evidence
        for designator, component in sorted(board.components.items())
        if (evidence := _controller_evidence(component, library))
    }
    if controllers:
        lines.append(
            "控制器候选（"
            + str(len(controllers))
            + "）："
            + "；".join(f"`{designator}` — {evidence}" for designator, evidence in controllers.items())
        )
    else:
        lines.append(
            "控制器候选：**无**（本板没有货架标为 `ic.mcu`、也没有 ≥4 个端口命名引脚的器件）——"
            "链级走查以别处的控制器为准，跨板链在这里只能留 " + TODO
        )
    lines.append("")

    # --- 1. power tree
    lines.append(f"### 1. 电源树（{len(rails)} 轨）")
    lines.append("")
    if not rails:
        lines.append("（没有可识别的电源轨：没有电压名、也没有供电引脚命名的网。）")
        lines.append("")
    for rail in rails:
        lines.append(f"#### 轨 `{rail.net}`")
        if rail.voltage is not None:
            lines.append(f"- voltage: {rail.voltage:g} V（{rail.voltage_source}）")
        else:
            lines.append(f"- voltage: {TODO}（{rail.voltage_why_not}）")
        lines.append(f"- source: {TODO}")
        lines.append(
            "- sourceCandidates: "
            + ("、".join(rail.source_candidates) if rail.source_candidates else "（无候选：没有任何器件声明自己是源）")
        )
        lines.append(
            f"- loads（{len(rail.loads)}）："
            + ("、".join(f"`{item}`" for item in rail.loads) or "（无）")
        )
        lines.append("")

    # --- 2. analog chains
    lines.append(f"### 2. 模拟链（{len(analog)} 条）")
    lines.append("")
    lines.append(
        "判定口径：**非电源非地**、≥2 个成员、且至少有 1 个成员接在控制器候选的引脚上"
        "（控制器候选 = 货架 `category: ic.mcu`，或符号里 ≥4 个引脚用 `P<端口><数字>` 命名）。"
        "工具只列链与槽位；量程/极性/参考点这些**必须由 AI 或工程师给**。"
    )
    lines.append("")
    if not analog:
        lines.append("（没有符合口径的模拟链。）")
        lines.append("")
    for chain in analog:
        lines.append(f"#### 链 `{chain.name}`（{len(chain.members)} 成员）")
        lines.append("- members: " + " — ".join(f"`{member}`" for member in chain.members))
        for item in chain.evidence:
            lines.append(f"- evidence: {item}")
        for slot in chain.slots:
            lines.append(f"- {slot}: {TODO}  # {SLOT_LABELS.get(slot, '')}")
        lines.append("")

    # --- 3. control chains
    lines.append(f"### 3. 控制链（{len(control)} 条）")
    lines.append("")
    lines.append(
        "判定口径：网名命中控制特征（`TIM`/`PWM`/`GATE`/`EN`/`IN`/`INH`/`FAULT`/`SLEEP`/`RESET`…），"
        "且接入控制器候选引脚。`endpointConsistency` 就是 TIM1 那类案子的机械入口："
        "网名说它是什么功能，端点引脚说它是什么功能，两者要对得上。"
    )
    lines.append("")
    if not control:
        lines.append("（没有符合口径的控制链。）")
        lines.append("")
    for chain in control:
        lines.append(f"#### 链 `{chain.name}`（{len(chain.members)} 成员）")
        lines.append("- members: " + " — ".join(f"`{member}`" for member in chain.members))
        for item in chain.evidence:
            lines.append(f"- evidence: {item}")
        for slot in chain.slots:
            lines.append(f"- {slot}: {TODO}  # {SLOT_LABELS.get(slot, '')}")
        lines.append("")

    # --- 4. buses
    lines.append(f"### 4. 总线表（{len(buses)} 类）")
    lines.append("")
    if not buses:
        lines.append("（没有命中已知协议网名的网。）")
        lines.append("")
    for family in sorted(buses):
        lines.append(f"#### {family}（{len(buses[family])} 网）")
        for net_name in sorted(buses[family]):
            members = _net_members(board, net_name)
            lines.append(
                f"- `{net_name}`：" + "、".join(f"`{member}`" for member in members)
            )
        for slot in BUS_SLOTS:
            lines.append(f"- {slot}: {TODO}  # {SLOT_LABELS.get(slot, '')}")
        lines.append("")

    # --- 5. intent slots (§6)
    lines.append(f"### 5. 设计意图槽位（{len(rails) + len(chains)} 条对象）")
    lines.append("")
    lines.append(
        "这些数只存在于工程师脑中：工具推不出来，AI 也不许编。"
        "**推断不了的显式问工程师**，答后把这里固化成审查基准（活文档）：以后 finding 以它为尺，"
        "需求变了就改这里。"
    )
    lines.append("")
    lines.append("| 对象 | " + " | ".join(INTENT_SLOTS) + " |")
    lines.append("|---|" + "---|" * len(INTENT_SLOTS))
    for rail in rails:
        lines.append(f"| 轨 `{rail.net}` | " + " | ".join(TODO for _ in INTENT_SLOTS) + " |")
    for chain in chains:
        label = "模拟链" if chain.kind == KIND_ANALOG else "控制链"
        lines.append(
            f"| {label} `{chain.name}` | "
            + " | ".join(TODO for _ in INTENT_SLOTS) + " |"
        )
    lines.append("")

    # --- the leftovers, counted rather than dropped
    if unclassified:
        lines.append(
            f"### 附：未归类非电源网（{len(unclassified)}）"
        )
        lines.append("")
        lines.append(
            "这些网既不在电源树上，也没有控制器引脚（或只有 1 个成员），所以没进上面任何一节；"
            "它们由规则引擎与模块走查覆盖，这里只登记名字，不猜用途："
        )
        lines.append("")
        lines.append("、".join(f"`{net}`" for net in unclassified))
        lines.append("")

    section_board.update({
        "title": title,
        "components": len(board.components),
        "nets": len(board.nets),
        "rails": len(rails),
        "analogChains": len(analog),
        "controlChains": len(control),
        "buses": len(buses),
        "unclassifiedNets": len(unclassified),
    })
    section_chains["rails"].extend(
        {
            "board": title,
            "net": rail.net,
            "voltage": rail.voltage,
            "loads": len(rail.loads),
            "sourceCandidates": list(rail.source_candidates),
        }
        for rail in rails
    )
    section_chains["analog"].extend(
        {"board": title, "net": chain.name, "members": list(chain.members)}
        for chain in analog
    )
    section_chains["control"].extend(
        {"board": title, "net": chain.name, "members": list(chain.members)}
        for chain in control
    )
    section_chains["bus"].extend(
        {"board": title, "family": family, "nets": sorted(buses[family])}
        for family in sorted(buses)
    )


def generate_architecture(
    model: DesignModel | object, *, library: PartLibrary | None = None
) -> ArchResult:
    """The architecture skeleton for one board or a whole project.

    A :class:`~boardwise.core.model.ProjectModel` is walked **per board**, the way
    ``run_review`` and ``checkup``'s modules do it: each board gets its own five
    sections, because two boards are two netlists and a chain that crosses them
    cannot be stated from one model. A plain model (one board, an ``.enet``
    export) produces exactly one board section.

    ``library`` is optional and only ever *adds* evidence (the shelf's
    ``ic.mcu`` classification and its regulators' output voltages). Without it the
    skeleton is still generated — with more `TODO`s, which is the honest answer
    when the shelf is not readable.
    """
    from .model import ProjectModel

    boards: list[tuple[str, DesignModel]] = []
    if isinstance(model, ProjectModel):
        boards = [
            (board_model.board.title or f"Board{i + 1}", board_model)
            for i, board_model in enumerate(model.boards)
        ]
    else:
        boards = [("Board1", model)]

    lines: list[str] = [
        "# 架构骨架（architecture.md）",
        "",
        "> 工具只列**骨架与槽位**，判不出来的一律留 `" + TODO + "`——填槽与自洽性走查是 AI 的活"
        "（SKILL「架构走查」）；推断不了的设计意图要**显式问工程师**，不许编。",
        "> 生成器：`boardwise arch`（044 M1）。确定性输出：同输入逐字节相同。",
        "> 槽位键（英文）是给机器解析用的，" + TODO + " 是**欠账**不是空白。",
        "",
    ]
    section_boards: list[dict] = []
    section_chains: dict[str, list] = {
        "rails": [], "analog": [], "control": [], "bus": [],
    }
    for title, board in boards:
        section_board: dict = {}
        if len(boards) > 1:
            lines.append(f"<!-- board: {title} -->")
            lines.append("")
        _render_board(board, library, title, lines, section_board, section_chains)
        section_boards.append(section_board)

    totals = {
        key: sum(board[key] for board in section_boards)
        for key in ("rails", "analogChains", "controlChains", "buses", "unclassifiedNets")
    }
    # Every slot the AI owes, counted one way: chains and rails each carry their
    # own slots plus an intent block, and each bus family carries its own.
    todo_slots = (
        len(section_chains["rails"]) * (len(POWER_SLOTS) + len(INTENT_SLOTS))
        + len(section_chains["analog"]) * (len(ANALOG_SLOTS) + len(INTENT_SLOTS))
        + len(section_chains["control"]) * (len(CONTROL_SLOTS) + len(INTENT_SLOTS))
        + len(section_chains["bus"]) * len(BUS_SLOTS)
    )

    section = {
        "file": ARCH_FILE_NAME,
        "boards": section_boards,
        "totals": {**totals, "intentObjects": totals["rails"] + totals["analogChains"] + totals["controlChains"], "todoSlots": todo_slots},
        "slotKeys": {kind: list(slots) for kind, slots in SLOT_VOCABULARY.items()},
        "chains": section_chains,
        "generator": "boardwise.core.architecture（044 M1：骨架；能力失配质疑见任务书 §6，未在本切片生成）",
    }
    return ArchResult(markdown="\n".join(lines).rstrip("\n") + "\n", section=section)
