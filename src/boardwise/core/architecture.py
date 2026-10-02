"""The architecture skeleton (task 044 M1) — deterministic chain scaffolding.

Why this exists: the ROBOT ctrl FOC blind review missed a **chain-level** defect
while every part-level rule passed. The U-phase shunt's top node goes straight to
an STM32 ADC pin with no bias network, so a bidirectional phase current cannot be
measured by a single-supply ADC — and no local rule can see that, because R4 is a
fine resistor, PA7 is a fine pin mapping, and the two-resistor topology is fine
too. The missing step is teleological: *what is this chain for, and does it close
end to end?* xianyuyijinban's prescription is to force that step by making the review produce
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
slots stay a living document). The contract is stated in two halves since 053
§2.2, because the artifact is now two files:

* the **skeleton** (``architecture.md``) is deterministic with respect to the
  **model** — it is generated and overwritten, so a hand edit there is lost;
* the **merged view** (``report.json``'s ``architecture`` section) is
  deterministic with respect to **(model + the design-intent file)** — the
  engineer-owned half, which this module only ever reads.

:data:`INTENT_FILE_NAME` is that second half. It is created once, as an all-TODO
template isomorphic to the skeleton, and never rewritten afterwards (052 §2.2's
measured defect was the opposite: a filled ``targetVoltage: 3.3V`` came back as
``TODO`` on the next run). Each slot is addressed by a stable id
``<projectUuid>/<boardUuid>/<sectionKey>/<slotKey>`` and carries the **signature**
of the object it is about (a rail's node set, a chain's member sequence, a bus
family's nets). When the drawing changes underneath a recorded answer, the slot
is marked :data:`STALE_MARK` in the merged view — not deleted, not overwritten,
and the run still reports.

Offline and self-contained: the model in, markdown and a count summary out. No
network, no clock, no randomness, no bridge.
"""

from __future__ import annotations

import hashlib
import os
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

#: The engineer-owned half of the pair (053 §2.2). ``architecture.md`` is
#: generated and rewritten on every run, so a hand-filled skeleton loses the fill
#: (052 §2.2 reproduces exactly that); the answers live here instead. This module
#: only ever **reads** it: absent, a caller writes :func:`render_intent_template`;
#: present, not one character of it is changed.
INTENT_FILE_NAME = "design-intent.md"

#: ``architecture.md``'s second line. The banner is the whole point of splitting
#: the two files: a reader who opens the generated file must be told, in the file
#: itself, where a hand-fill is safe.
BANNER = (
    "> **自动生成，手填无效——设计意图请填 `design-intent.md`**"
    "（生成器对该文件只读：不存在就建全 TODO 模板，存在则一字不改）。"
)

#: The mark the merged view carries on a slot whose recorded signature no longer
#: matches the drawing (053 §2.2). Explicit, never silent: the recorded value
#: stays exactly where it is, it is only flagged as needing a second look.
STALE_MARK = "stale: 图纸已变，此槽待复核"

#: The provenance spelling the intent file's `来源` column uses: who wrote the
#: answer, and when. Free text is the value; this is the *source* column, so a
#: `TODO` value with an `ai-proposal@…` source is still readable as a proposal.
PROVENANCE_KINDS = ("engineer", "ai-proposal", "ai-confirmed")


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
#: the section headings and prose are Chinese, because xianyuyijinban reads them.
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

#: Slot key -> the Chinese gloss printed beside it, so the AI (and xianyuyijinban) knows what
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
    so a machine can see what the AI was asked to walk without parsing prose. It
    is the **merged view** since 053 §2.2: ``section["slots"]`` is the skeleton's
    slots with the design-intent file's answers merged in (a filled slot carries
    its value and source, a TODO stays `TODO`, a slot whose object changed carries
    :data:`STALE_MARK`).

    ``intent_markdown`` is the paired ``design-intent.md`` — the all-TODO template
    a caller writes **only when that file does not exist yet**, and ``intent_present``
    says whether the merge had a file to read at all.
    """

    markdown: str
    section: dict
    intent_markdown: str = ""
    intent_present: bool = False


# ---------------------------------------------------------------------------
# 053 §2.2 — the stable slot id, the object signature, and the intent file
# ---------------------------------------------------------------------------


def _part(text: str) -> str:
    """One slash-free segment of a stable slot id.

    The id's whole contract is that a consumer can split it on ``/`` and find the
    project, the board, the section and the slot — so a title that happens to
    contain a slash (or whitespace) is folded to ``_`` rather than allowed to
    invent an extra segment. This is a *fixing* of the id, not a rename: the same
    title always folds the same way, so the id stays stable across runs.
    """
    folded = re.sub(r"\s+", "_", str(text or "").replace("/", "_"))
    return folded or "_"


def _project_uuid(model: object, given: str = "") -> tuple[str, str]:
    """``(projectUuid, where it came from)`` for the slot ids.

    The live tiers read the real one out of `doc.list`'s focused project
    (`source.project.projectUuid`), which is the answer to prefer — it is the
    editor's own identity and it survives a file being renamed. An offline tier
    has no such number, so the model's source file name is folded into a stable
    digest instead: ``file-<12 hex>``. A digest rather than the name itself,
    because an id has to survive odd characters; the human-readable file name is
    kept beside it in the template's metadata (`projectSource`).
    """
    if given:
        return _part(given), "doc.list 的 focusedProject.projectUuid"
    source = str(getattr(model, "source", "") or "")
    name = os.path.basename(source)
    if name:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        return f"file-{digest}", f"离线档按文件名折叠（{name}）"
    return "project", "无来源（空模型）"


def _board_uuid(board: object, title: str) -> str:
    """The container's board uuid, or the board title when it has none.

    A project with no ``BOARD`` document gets an *implicit* board whose
    :class:`~boardwise.core.model.BoardRef.uuid` is empty (040b), and a plain
    single-board model has no board ref at all; the title is the honest stand-in
    in both cases, and it is what the report's own `model.boards[]` names.
    """
    ref = getattr(board, "board", None)
    uuid = getattr(ref, "uuid", "") if ref is not None else ""
    return _part(uuid or title)


def object_signature(members: list[str]) -> str:
    """``sha256:<16 hex>`` over an object's members — the stale test's fingerprint.

    What is hashed is the *shape of the object the slot is about*, never the
    slot's own key: a rail's node set (its pins, sorted), a chain's member
    sequence (sorted, designator and pin name included, because a symbol rename is
    a drawing change too), a bus family's nets. The digest is truncated to 16 hex
    because it is compared for equality by a human eyeballing a diff, not by an
    adversary — and it is digests rather than the members themselves so that a
    slot row stays one line of markdown.
    """
    digest = hashlib.sha256("|".join(members).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def _slot_record(
    *,
    project_uuid: str,
    board_uuid: str,
    title: str,
    kind: str,
    obj: str,
    key: str,
    signature: str,
) -> dict:
    """One skeleton slot, before the intent file is merged into it.

    ``sectionKey`` is ``<kind>:<object>`` (``power:U+``, ``analog:U+``,
    ``intent:U+``…), which keeps the id's documented four segments while still
    naming *which* rail or chain the slot belongs to. The kinds are disjoint by
    construction — a rail is never also listed as a chain (044 §2's fixed
    classification order) — so `<kind>:<object>` is unique within a board.
    """
    section_key = f"{kind}:{obj}"
    return {
        "id": f"{project_uuid}/{board_uuid}/{section_key}/{key}",
        "board": title,
        "boardUuid": board_uuid,
        "section": section_key,
        "sectionKind": kind,
        "object": obj,
        "key": key,
        "label": SLOT_LABELS.get(key, ""),
        "value": TODO,
        "source": "",
        "filled": False,
        "stale": False,
        "staleReason": "",
        "orphan": False,
        "signature": signature,
        "recordedSignature": "",
    }


def _cells(line: str) -> list[str]:
    """A markdown table row's cells, honouring ``\\|`` as a literal pipe."""
    placeholder = "\x00"
    row = line.strip().replace("\\|", placeholder)
    if not row.startswith("|"):
        return []
    cells = [cell.replace(placeholder, "|").strip() for cell in row.split("|")]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def parse_intent(text: str) -> dict[str, dict]:
    """``design-intent.md`` -> ``{slot id: {value, source, signature}}``.

    Deliberately forgiving, because the file belongs to a human: only rows whose
    first cell looks like a four-segment slot id are read, an unknown extra column
    is ignored, and a value of ``TODO``/empty counts as unfilled rather than as an
    answer. A row whose `sig=` cell is empty records *no* signature — the merge
    then cannot claim the slot is current, so it simply leaves it unflagged
    instead of calling it stale on a guess.
    """
    out: dict[str, dict] = {}
    for line in str(text or "").splitlines():
        cells = _cells(line)
        if len(cells) < 4:
            continue
        slot_id = cells[0]
        if slot_id.count("/") != 3 or ":" not in slot_id:
            continue
        value = cells[2]
        source = cells[3]
        signature = cells[4] if len(cells) > 4 else ""
        if signature.startswith("sig="):
            signature = signature[4:].strip()
        out[slot_id] = {
            "value": "" if value == TODO else value,
            "source": "" if source == TODO else source,
            "signature": "" if signature in (TODO, "—", "-") else signature,
        }
    return out


def merge_intent(slots: list[dict], records: dict[str, dict] | None) -> tuple[list[dict], dict]:
    """skeleton slots ⊕ the intent file's answers — 053 §2.2's merged view.

    Three rules, and each one exists because the alternative is silent loss:

    * a recorded value goes in with its source; a `TODO` stays `TODO`;
    * a recorded signature that no longer equals the object's current one marks
      the slot :data:`STALE_MARK` — **the recorded value stays exactly as written**
      (no delete, no overwrite), and the caller is told, not blocked;
    * a recorded row whose object is **gone from the drawing** is listed too
      (``orphan: true``, marked stale) instead of being dropped, because a slot
      that silently disappears is the failure mode this whole file exists to stop.

    Returns ``(merged slots, counts)``; the counts are what the report's
    ``architecture`` section and the completion verdict read.
    """
    records = records or {}
    known: set[str] = set()
    merged: list[dict] = []
    filled = 0
    stale = 0
    for slot in slots:
        entry = dict(slot)
        known.add(entry["id"])
        record = records.get(entry["id"])
        if record:
            if record["value"]:
                entry["value"] = record["value"]
                entry["filled"] = True
            entry["source"] = record["source"]
            entry["recordedSignature"] = record["signature"]
            if record["signature"] and record["signature"] != entry["signature"]:
                entry["stale"] = True
                entry["staleReason"] = STALE_MARK
        filled += 1 if entry["filled"] else 0
        stale += 1 if entry["stale"] else 0
        merged.append(entry)
    for slot_id in sorted(records):
        if slot_id in known:
            continue
        record = records[slot_id]
        parts = slot_id.split("/")
        if len(parts) != 4:
            continue  # not a slot id: nothing to place it against
        _, _, section_key, key = parts
        kind = section_key.split(":", 1)[0]
        merged.append({
            "id": slot_id,
            "board": "",
            "boardUuid": parts[1],
            "section": section_key,
            "sectionKind": kind,
            "object": section_key.split(":", 1)[1] if ":" in section_key else "",
            "key": key,
            "label": SLOT_LABELS.get(key, ""),
            "value": record["value"] or TODO,
            "source": record["source"],
            "filled": bool(record["value"]),
            "stale": True,
            "staleReason": STALE_MARK + "（图纸里已无此对象——不删，只标）",
            "orphan": True,
            "signature": "",
            "recordedSignature": record["signature"],
        })
        filled += 1 if record["value"] else 0
        stale += 1
    return merged, {
        "slots": len(merged),
        "filled": filled,
        "stale": stale,
        "orphans": sum(1 for entry in merged if entry["orphan"]),
    }


def render_intent_template(
    slots: list[dict],
    *,
    project_uuid: str,
    project_source: str = "",
) -> str:
    """The first ``design-intent.md``: isomorphic to the skeleton, all TODO.

    Written by a caller **only when the file does not exist** (:func:`parse_intent`
    is the other half). The signature column is this file's metadata area: it
    records what the object looked like when the row was created, which is what
    makes :data:`STALE_MARK` possible later without the tool ever editing the row.
    """
    lines: list[str] = [
        "# 设计意图（design-intent.md）",
        "",
        "> 这份文件**归工程师所有**：生成器对它只读——不存在时建一份全 TODO 模板，存在则**一字不改**。"
        "归档骨架在 `" + ARCH_FILE_NAME + "`（自动生成，手填无效）。",
        "> 值格式：自由文本；来源标注写在同一行的「来源」列（"
        + " / ".join(f"`{kind}@2026-09-27`" for kind in PROVENANCE_KINDS) + "）。",
        "> 稳定 ID：`<projectUuid>/<boardUuid>/<sectionKey>/<slotKey>`；"
        "`sectionKey` = `<节>:<对象>`（节：power / analog / control / bus / intent）。",
        "> 「sig=」列是该槽**关联对象的签名**（电源树节点集 / 链路器件序列 / 总线成员集）。"
        "图纸一变，checkup 会把该槽标 `" + STALE_MARK + "`，但**不会改写这一行**——"
        "复核完，把这一行的 sig 换成报告里 `architecture.slots[]` 给的新值即可。",
        "> 填不了的**显式写「不适用」，别留空**；值里不要写 `|`（表格分隔符），要写就写 `\\|`。",
        "",
        f"projectUuid: {project_uuid}",
        f"projectSource: {project_source or '（未知）'}",
        f"generator: boardwise.core.architecture（044 M1 骨架 / 053 §2.2 意图合并）",
        "",
    ]
    boards: dict[str, list[dict]] = {}
    for slot in slots:
        boards.setdefault(slot["board"] or "（板未知）", []).append(slot)
    if not slots:
        lines.append("（这份模型没有任何槽位：没有电源轨、没有链、没有命中协议网名的网。）")
        lines.append("")
    for title, board_slots in boards.items():
        board_uuid = board_slots[0]["boardUuid"]
        lines.append(f"## 板：{title}（boardUuid `{board_uuid}`）")
        lines.append("")
        lines.append("| 稳定 ID | 槽位 | 值 | 来源 | sig= |")
        lines.append("|---|---|---|---|---|")
        for slot in board_slots:
            label = f"{slot['key']} · {slot['label']}" if slot["label"] else slot["key"]
            lines.append(
                f"| {slot['id']} | {slot['object']} · {label} | {TODO} | {TODO} "
                f"| sig={slot['signature']} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


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


def controller_evidence(component: Component, library: PartLibrary | None) -> str:
    """Why this part may be a controller — or ``""`` when nothing says so.

    Two evidence sources, strongest first: the shelf's own classification
    (``category: ic.mcu``) and the symbol's pin names (several ``P<port><n>``
    pins). Both are facts about the project; neither is a family-name guess, and
    a part none of them fits simply is not a chain anchor — its identity stays
    unstated rather than being filled in by pattern luck.

    Public since 093 A3a: the architecture walk is no longer the only reader.
    ``arch-nrst-closure`` asks the same question — "is this a controller?" — and
    a second recogniser would be a second answer to it (the two-enumerators
    defect 090 §二 warns about). ``library=None`` (the caller has no shelf in
    hand) leaves only the symbol evidence, which is what this reading always
    did with no library.
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
        if (evidence := controller_evidence(component, library))
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
    section_slots: list[dict],
    *,
    project_uuid: str,
) -> None:
    """Append one board's five sections, and fill the machine summary in place.

    ``section_slots`` collects one record per slot in the same order the document
    writes them (power tree → analog → control → bus → intent), each with its
    stable id and the signature of the object it is about — 053 §2.2's join key,
    which is what lets the intent file's answers be merged back in without ever
    parsing prose.
    """
    rails, chains, buses, unclassified = _chains_and_rails(board, library, title)
    control = [chain for chain in chains if chain.kind == KIND_CONTROL]
    analog = [chain for chain in chains if chain.kind == KIND_ANALOG]
    board_uuid = _board_uuid(board, title)

    def add_slot(kind: str, obj: str, key: str, signature: str) -> None:
        section_slots.append(_slot_record(
            project_uuid=project_uuid, board_uuid=board_uuid, title=title,
            kind=kind, obj=obj, key=key, signature=signature,
        ))

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
        if (evidence := controller_evidence(component, library))
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
        # The slot's signature is the rail's node set — what "this rail" means
        # structurally, so a drawing that re-wires it flags the recorded answer.
        rail_signature = object_signature(rail.loads)
        for key in POWER_SLOTS:
            add_slot(KIND_POWER, rail.net, key, rail_signature)

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
        _chain_slots(chain, add_slot)

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
        _chain_slots(chain, add_slot)

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
        # A bus family's signature is its net set: adding or losing a member net
        # is a change the recorded completeness judgement has to hear about.
        family_signature = object_signature(sorted(buses[family]))
        for slot in BUS_SLOTS:
            add_slot(KIND_BUS, family, slot, family_signature)

    # --- 5. intent slots (§6)
    lines.append(f"### 5. 设计意图槽位（{len(rails) + len(chains)} 条对象）")
    lines.append("")
    lines.append(
        "这些数只存在于工程师脑中：工具推不出来，AI 也不许编。"
        "**推断不了的显式问工程师**，答后把答案写进 `" + INTENT_FILE_NAME + "`"
        "（这份骨架是自动生成的，手填无效）：以后 finding 以它为尺，需求变了就改那里。"
    )
    lines.append("")
    lines.append("| 对象 | " + " | ".join(INTENT_SLOTS) + " |")
    lines.append("|---|" + "---|" * len(INTENT_SLOTS))
    rail_signatures = {rail.net: object_signature(rail.loads) for rail in rails}
    chain_signatures = {chain.name: object_signature(chain.members) for chain in chains}
    for rail in rails:
        lines.append(f"| 轨 `{rail.net}` | " + " | ".join(TODO for _ in INTENT_SLOTS) + " |")
        for key in INTENT_SLOTS:
            add_slot(KIND_INTENT, rail.net, key, rail_signatures[rail.net])
    for chain in chains:
        label = "模拟链" if chain.kind == KIND_ANALOG else "控制链"
        lines.append(
            f"| {label} `{chain.name}` | "
            + " | ".join(TODO for _ in INTENT_SLOTS) + " |"
        )
        for key in INTENT_SLOTS:
            add_slot(KIND_INTENT, chain.name, key, chain_signatures[chain.name])
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


def _chain_slots(chain: "_Chain", add_slot) -> None:
    """Register one chain's own slots (``analog:U+`` → ``quantity``/``range``/…).

    The chain's *design-intent* row (``intent:U+`` → ``targetVoltage``/…) is
    registered by the §5 loop instead, where the document writes it — one object,
    two kinds of question, two stable ids, one place each.
    """
    signature = object_signature(chain.members)
    kind = KIND_CONTROL if chain.kind == KIND_CONTROL else KIND_ANALOG
    for key in chain.slots:
        add_slot(kind, chain.name, key, signature)


def generate_architecture(
    model: DesignModel | object,
    *,
    library: PartLibrary | None = None,
    intent_text: str | None = None,
    project_uuid: str = "",
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

    ``intent_text`` is the **raw text of the directory's** ``design-intent.md``,
    or ``None`` when that file does not exist yet (053 §2.2). It is read, never
    written: the merged view in ``section["slots"]`` is a pure function of
    ``(model, intent_text)``, so two runs over the same pair produce the same
    bytes *and* the same answer to "did the drawing move under this slot?".
    ``project_uuid`` is the live tier's ``focusedProject.projectUuid``; offline it
    is derived from the model's source file (see :func:`_project_uuid`).
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
    project_uuid, project_source = _project_uuid(model, project_uuid)

    lines: list[str] = [
        "# 架构骨架（architecture.md）",
        "",
        BANNER,
        "> 工具只列**骨架与槽位**，判不出来的一律留 `" + TODO + "`——填槽与自洽性走查是 AI 的活"
        "（SKILL「架构走查」）；推断不了的设计意图要**显式问工程师**，不许编。",
        "> 生成器：`boardwise arch`（044 M1）。骨架对**模型**确定：同输入逐字节相同；"
        "报告里的合并视图（骨架 ⊕ " + INTENT_FILE_NAME + "）对**（模型 + 意图文件）**确定。",
        "> 槽位键（英文）是给机器解析用的，" + TODO + " 是**欠账**不是空白。",
        "",
    ]
    section_boards: list[dict] = []
    section_chains: dict[str, list] = {
        "rails": [], "analog": [], "control": [], "bus": [],
    }
    section_slots: list[dict] = []
    for title, board in boards:
        section_board: dict = {}
        if len(boards) > 1:
            lines.append(f"<!-- board: {title} -->")
            lines.append("")
        _render_board(
            board, library, title, lines, section_board, section_chains,
            section_slots, project_uuid=project_uuid,
        )
        section_boards.append(section_board)

    totals = {
        key: sum(board[key] for board in section_boards)
        for key in ("rails", "analogChains", "controlChains", "buses", "unclassifiedNets")
    }
    merged_slots, counts = merge_intent(section_slots, parse_intent(intent_text or ""))
    # Every slot the AI owes, counted one way: chains and rails each carry their
    # own slots plus an intent block, and each bus family carries its own. The
    # merged view is what is counted, so a filled slot lowers `todoSlots` — that
    # number is the *outstanding* work, not the skeleton's size (`slots` is that).
    todo_slots = counts["slots"] - counts["filled"]

    section = {
        "file": ARCH_FILE_NAME,
        "intent": {
            "file": INTENT_FILE_NAME,
            "present": intent_text is not None,
            "projectUuid": project_uuid,
            "projectSource": project_source,
            "filled": counts["filled"],
            "stale": counts["stale"],
            "orphans": counts["orphans"],
        },
        "boards": section_boards,
        "totals": {
            **totals,
            "intentObjects": totals["rails"] + totals["analogChains"] + totals["controlChains"],
            "slots": counts["slots"],
            "filled": counts["filled"],
            "stale": counts["stale"],
            "todoSlots": todo_slots,
        },
        "slots": merged_slots,
        "slotKeys": {kind: list(slots) for kind, slots in SLOT_VOCABULARY.items()},
        "chains": section_chains,
        "generator": "boardwise.core.architecture（044 M1：骨架；053 §2.2：设计意图合并视图）",
    }
    return ArchResult(
        markdown="\n".join(lines).rstrip("\n") + "\n",
        section=section,
        intent_markdown=render_intent_template(
            section_slots, project_uuid=project_uuid, project_source=project_source,
        ),
        intent_present=intent_text is not None,
    )
