"""checkup's report-level assembly (025 batch 4): modules, AI slots, report.md.

Three pieces, and one rule they share: **say where a claim came from, and when a
grouping could not be made, say that instead of inventing one.**

* **`modules** — a multi-page project is grouped by page (an engineer's own
  split), a single-page one by connectivity (the only structure left). Neither is
  guessed: page attribution is read out of the archive's `SCH_PAGE` documents, and
  the connectivity pass runs on the **non-ground** net graph, because GND joins
  everything and a rule that puts every component in one module has named
  nothing.
* **`ai_slots`** — the three things 岳's architecture leaves to the model
  (025 §0): the parts it must WebSearch, the canvas images it must look at, and the
  summary it must write. The slots are a worklist, not an analysis: each entry
  says *what to check*, and the question marks the report's own numbers as
  something to confirm rather than to trust.
* **`render_report_markdown`** — `report.json` is the contract; the Markdown is
  what a human (and the model) actually reads. It renders only what the JSON
  already contains, in the same order, so the two cannot disagree.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..core.model import Component, DesignModel, is_ground_net
from ..core.parts import DESIGNATOR_CATEGORIES

#: How the components were grouped, per module and for the report header.
MODULE_BASIS_PAGE = "page"
MODULE_BASIS_CONNECTIVITY = "connectivity"
MODULE_BASIS_UNATTRIBUTED = "unattributed"

#: Where the page attribution came from. `archive` is the extra pass over the
#: archive's `SCH_PAGE` documents; `per-page` means the tier itself handed one
#: model per page; `unresolved` is the honest answer for the netlist tier, which
#: carries no page information at all.
PAGE_ATTRIBUTION_ARCHIVE = "archive"
PAGE_ATTRIBUTION_PER_PAGE = "per-page"
PAGE_ATTRIBUTION_UNRESOLVED = "unresolved"

#: The catch-all module's name — the parts and findings the grouping could not
#: place. Named for what it is, so a reader never mistakes it for a block.
UNATTRIBUTED_NAME = "未归属"

# --------------------------------------------------------------------------
# naming: conservative on purpose
# --------------------------------------------------------------------------

#: A main controller, by the part's own name (the library device name, the value
#: string, or the MPN — whichever carries it).
#:
#: Every alternative is **anchored** (`(?<![A-Za-z0-9])` … `(?![0-9])`): a family
#: name buried inside a longer code is not evidence of that family, and the
#: unanchored version of the regulator list below read `7895` out of the LCSC code
#: `C57895` (see `_part_text`).
_MCU_PATTERNS = re.compile(
    r"(?<![A-Za-z0-9])(STM32|GD32|CH32|CH58|ESP32|ESP8266|NRF5\d|ATMEGA|ATTINY|"
    r"RP2040|LPC\d{3}|ATSAM|HC32|APM32|BL7\d\d|MM32|N76E|STC\d|AC63)",
    re.IGNORECASE,
)

#: A voltage regulator / converter. This is the evidence for `电源` — **not**
#: "touches VCC/GND", which every module does and which would therefore name
#: every module 电源 (see `_name_cluster`).
_REGULATOR_PATTERNS = re.compile(
    r"(?<![A-Za-z0-9])(AMS1117|LM\d{2,4}|MP\d{4}|TPS\d{4,}|TLV\d+|XL\d{4}|SY\d{4}|"
    r"MT\d{4}|SPX\d+|HT7\d{3}|RT\d{4}|ME62\d\d|AP7\d\d\d|SGM\d{4}|MC34063|LDO|"
    r"REGULATOR|78L?\d{2}|79L?\d{2}|MP1584|MP2315|MP2145|SY8089|SY8205)(?![0-9])",
    re.IGNORECASE,
)

#: Parts whose names sit inside a regulator pattern but are **not** regulators.
#:
#: The `LM`/`TLV` families mix them: `LM317` is an adjustable regulator, `LM358` is
#: a dual op-amp — and a pattern wide enough to catch the first also caught the
#: second, which named a cluster of op-amps 电源 (found by a test, 2026-09-23). A
#: deny-list rather than a tighter family list, because the regulator names are
#: open-ended and the false friends are few.
_REGULATOR_FALSE_FRIENDS = re.compile(
    r"(?<![A-Za-z0-9])(LM358|LM324|LM393|LM339|LM741|LM747|LM386|LM833|LM158|"
    r"LM2902|LM2904|LM2901|LM35|LM75|LMV\d+|TLV906\d|TLV900\d)(?![0-9])",
    re.IGNORECASE,
)

#: An interface / connector part, by name.
_INTERFACE_PATTERNS = re.compile(
    r"(?<![A-Za-z0-9])(USB|TYPE-?C|CH340|CH341|CH342|CP210\d|FT232|FT2232|FE1\.1|"
    r"RJ45|HDMI|MAX232|SP3232|SN65HVD)",
    re.IGNORECASE,
)

#: Nets that mean "this cluster is where power comes in". Deliberately a *supply
#: input* list: VCC/GND are shared by everything and are therefore evidence about
#: the board, not about a block.
_POWER_INPUT_NET = re.compile(r"^(VIN|VBAT|VDC|PWR_?IN|DC_?IN|AC_?IN|VBUS|POWER)$", re.IGNORECASE)

#: Nets that mean "this cluster talks to something outside the board".
_INTERFACE_NET = re.compile(
    r"^(USB_?D[PM\+-]|D\+|D-|USB_?VBUS|USB_?CC\d?|RX|TX|TXD|RXD|SCL|SDA|MISO|MOSI|SCK)$",
    re.IGNORECASE,
)


def _part_text(component: Component) -> str:
    """Everything a part says about itself, for a pattern to look at.

    **The supplier code is deliberately absent.** An LCSC part number is
    `C` + digits, and on the ch340_golden fixture `C57895` contains `7895` — which
    an unanchored `78\\d{2}` regulator pattern happily read as a 7800-series
    regulator, naming a cluster of decoupling capacitors 电源. A supplier code is
    an *order* number, not a part name; the fields that can carry a real name are
    the four below (measured false positive, 2026-09-23).
    """
    name = str(component.props.get("device_name") or "")
    return " ".join(filter(None, [
        name, component.value or "", component.mpn or "", component.footprint or "",
    ]))


# --------------------------------------------------------------------------
# modules
# --------------------------------------------------------------------------


def _designator_category(component: Component) -> str:
    """The shelf category of a part, from its designator prefix (the repo table)."""
    prefix = re.match(r"[A-Za-z]+", component.designator or "")
    if not prefix:
        return ""
    return DESIGNATOR_CATEGORIES.get(prefix.group(0).upper(), "")


def page_attribution_from_archive(path) -> dict[str, dict]:
    """`{page_uuid: {title, components}}` from an archive's `SCH_PAGE` documents.

    Why this pass exists: `build_schematic_model` merges every page into one
    model — correctly, since a netlist-level review wants the whole design — and
    the per-page split is gone by the time a report sees it. Re-deriving it from
    the same record stream is cheap, read-only, and keeps the parser untouched.

    It is deliberately shallow: a `COMPONENT` record's `partId`, then the
    `Designator` attribute that **follows** it — the same positional join the
    parser's `_split_page` does, and it has to be positional: measured
    2026-09-23, the designator attribute's `parentId` is the instance's *container*
    id (`8d71fac2b1b4c91c`), never the `partId` the COMPONENT record carries, so a
    join on ids finds nothing at all. A page with no designator is reported with an
    empty list, which is a *reading* (a title-block-only page), not a failure.

    Never raises: an archive that cannot be read yields `{}`, and the caller
    reports `pageAttribution: unresolved` rather than an empty grouping that
    looks like "no pages".
    """
    from ..parsers.epru_stream import iter_epru_records, load_epru_text

    try:
        text, _meta = load_epru_text(path)
    except Exception:  # noqa: BLE001 — an unreadable archive is a caller-level fact
        return {}

    pages: dict[str, dict] = {}
    current: str | None = None
    current_part = False
    for record in iter_epru_records(text):
        body = record.body or {}
        if record.type == "DOCHEAD":
            current = str(body["uuid"]) if body.get("docType") == "SCH_PAGE" and body.get("uuid") else None
            current_part = False
            if current is not None:
                pages.setdefault(current, {"uuid": current, "title": "", "components": set()})
            continue
        if current is None:
            continue
        page = pages[current]
        if record.type == "META" and body.get("title") and not page["title"]:
            page["title"] = str(body["title"]).strip()
        elif record.type == "COMPONENT":
            current_part = True
        elif record.type == "ATTR":
            if str(body.get("key")) == "Designator" and current_part:
                value = str(body.get("value") or "").strip()
                if value:
                    page["components"].add(value)
                current_part = False
    return {uuid: {**page, "components": sorted(page["components"])} for uuid, page in pages.items()}


def _cluster_designators(model: DesignModel) -> list[list[str]]:
    """Connected components of the **non-ground** net graph, as designator lists.

    Ground nets are excluded on purpose: GND (and its aliases, via
    `is_ground_net`) touches nearly every part, so a union-find that includes it
    answers "one module" for any real board — a grouping that has told the reader
    nothing while looking like a result. What is left is the connectivity an
    engineer actually reasons about when splitting a single-page design.

    Deterministic: clusters are returned in first-designator order, and the
    designators inside each are sorted.
    """
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for component in model.components.values():
        find(component.designator)
    for name, net in model.nets.items():
        if is_ground_net(name):
            continue
        designators = [ref for ref, _pin in net.pins if ref in model.components]
        for other in designators[1:]:
            union(designators[0], other)

    clusters: dict[str, list[str]] = {}
    for designator in sorted(model.components):
        clusters.setdefault(find(designator), []).append(designator)
    return [sorted(members) for members in clusters.values()]


#: Categories whose parts are *passive* — excluded from the denominator when
#: asking "is this family a meaningful share of the cluster?". A cluster of a
#: hundred decoupling capacitors around one regulator is a power block, and the
#: ratio has to be measured against the parts that carry function, not against
#: the passives every block is padded with.
_PASSIVE_CATEGORIES = frozenset({"res", "cap", "ind"})

#: How much of a cluster's functional parts one family must be for its name to
#: be used. A single connector among forty parts does not make the region an
#: interface, and a lone LDO inside a whole-board blob does not make it a power
#: block — the ratio is what turns "contains" into "is", and when it fails the
#: cluster stays `未命名模块 N` (the conservative answer 025 §2 asks for).
FAMILY_DOMINANCE = 1 / 3


def _dominant(hits: int, functional: int) -> bool:
    """Is `hits` of `functional` parts enough to name the cluster after them?"""
    if hits <= 0:
        return False
    if functional <= 0:
        return False
    return hits / functional >= FAMILY_DOMINANCE


def _functional_parts(parts: list[Component]) -> list[Component]:
    """The cluster's non-passive parts (see `_PASSIVE_CATEGORIES`)."""
    return [part for part in parts if _designator_category(part) not in _PASSIVE_CATEGORIES]


def _name_cluster(designators: Iterable[str], model: DesignModel) -> tuple[str, str]:
    """`(name, basis)` for one connectivity cluster — or `('', '')` when unnamed.

    The rules look for *positive evidence* in the parts and nets, require it to be
    a meaningful share of the cluster (`FAMILY_DOMINANCE`), and record the
    evidence in `basis` so a reader can check the name rather than trust it.

    There is deliberately no "touches VCC/GND" rule: every cluster touches them,
    and a rule that matches everything names nothing. A cluster that fails every
    rule stays unnamed — `未命名模块 N`, which is a useful answer ("we did not
    recognise this block") rather than a guess.
    """
    refs = list(designators)
    parts = [model.components[ref] for ref in refs if ref in model.components]
    functional = _functional_parts(parts)

    def hits_of(pattern) -> list[str]:
        return [part.designator for part in functional if pattern.search(_part_text(part))]

    def regulator_hits() -> list[str]:
        """Regulator hits, minus the parts whose names only *look* like regulators."""
        return [
            part.designator for part in functional
            if _REGULATOR_PATTERNS.search(_part_text(part))
            and not _REGULATOR_FALSE_FRIENDS.search(_part_text(part))
        ]

    mcu_hits = hits_of(_MCU_PATTERNS)
    if _dominant(len(mcu_hits), len(functional)):
        return "MCU", (f"MCU：{len(mcu_hits)}/{len(functional)} 个功能器件命中主控家族"
                       f"（{_sample(mcu_hits, model)}）")

    power_hits = regulator_hits()
    if _dominant(len(power_hits), len(functional)):
        return "电源", (f"电源：{len(power_hits)}/{len(functional)} 个功能器件命中稳压器/转换器"
                        f"（{_sample(power_hits, model)}）")

    hits = hits_of(_INTERFACE_PATTERNS)
    if _dominant(len(hits), len(functional)):
        return "接口", (f"接口：{len(hits)}/{len(functional)} 个功能器件命中接口器件"
                        f"（{_sample(hits, model)}）")

    members = set(refs)
    member_nets = [
        name for name, net in model.nets.items()
        if name and not is_ground_net(name) and any(ref in members for ref, _pin in net.pins)
    ]
    for pattern, label in ((_POWER_INPUT_NET, "电源"), (_INTERFACE_NET, "接口")):
        hits = [name for name in member_nets if pattern.match(name)]
        if _dominant(len(hits), len(member_nets)):
            what = "电源输入网" if label == "电源" else "对外接口网"
            return label, (f"{label}：{len(hits)}/{len(member_nets)} 条非地网是{what}"
                           f"（{'、'.join(hits[:4])}）")

    connectors = [part.designator for part in functional
                  if _designator_category(part) == "conn"]
    if _dominant(len(connectors), len(functional)):
        return "接口", (f"接口：{len(connectors)}/{len(functional)} 个功能器件是连接器类"
                        f"（{'、'.join(connectors)}）")

    return "", ""


def _sample(designators: list[str], model: DesignModel) -> str:
    """Up to four of the hitting designators, with the part name that matched."""
    shown = []
    for designator in designators[:4]:
        component = model.components.get(designator)
        name = str(component.props.get("device_name") or component.value or "") if component else ""
        shown.append(f"{designator}={name.strip()[:28]}" if name else designator)
    return "、".join(shown) + ("…" if len(designators) > 4 else "")


def modules_section(
    *,
    model: DesignModel,
    findings: list[dict],
    attribution: dict[str, dict] | None = None,
    attribution_source: str = PAGE_ATTRIBUTION_UNRESOLVED,
) -> tuple[list[dict], dict]:
    """The `modules` array, plus the header facts the caller reports.

    Returns `(modules, facts)`, where `facts` carries the counts a reader needs to
    judge the grouping (`basis`, `pageAttribution`, `pageCount`,
    `pagesWithComponents`, and any notes).

    Two grouping rules, chosen by what the data actually has:

    * **pages** — when at least two pages carry components. A multi-page
      schematic's page split is the designer's own structure; re-deriving it from
      connectivity instead would be inventing a second opinion.
    * **connectivity** — otherwise. A single-page design has no page split to
      honour, and the net graph is the only structure left.

    Either way, components that no page claims and findings that no module claims
    land in one `未归属` module rather than disappearing: an unattributed part is
    information, and a dropped one is a lie by omission.
    """
    facts: dict[str, Any] = {
        # `moduleBasis`, not `basis`: this dict is merged into the report's
        # `source` block, where a bare `basis` would read like the source's own.
        "moduleBasis": MODULE_BASIS_CONNECTIVITY,
        "pageAttribution": attribution_source,
        "notes": [],
    }
    modules: list[dict] = []
    placed: set[str] = set()
    refs_by_module: list[set[str]] = []

    pages_with_components = [
        page for page in (attribution or {}).values() if page.get("components")
    ] if attribution is not None else []

    if len(pages_with_components) >= 2:
        facts["moduleBasis"] = MODULE_BASIS_PAGE
        chosen = sorted(pages_with_components, key=lambda p: (p.get("title") or "", p["uuid"]))
        title_counts: dict[str, int] = {}
        for page in chosen:
            title = page.get("title") or page["uuid"]
            title_counts[title] = title_counts.get(title, 0) + 1
        ambiguous = model.duplicate_designators
        for page in chosen:
            components = [ref for ref in page["components"] if ref in model.components]
            missing = [ref for ref in page["components"] if ref not in model.components]
            placed.update(components)
            title = page.get("title") or page["uuid"]
            # Several pages really can carry the same title (measured on the 毕设
            # fixture: three pages all named "P1"), and two modules with one name
            # in one report is a reader trap — so a repeated title is spelled with
            # the page uuid, which is what distinguishes them everywhere else.
            name = f"{title}（{page['uuid'][:8]}）" if title_counts[title] > 1 else title
            notes: list[str] = []
            if missing:
                notes.append(f"页里有 {len(missing)} 个位号不在模型里（{missing[:4]}）")
            collisions = sorted(set(components) & set(ambiguous))
            if collisions:
                notes.append(
                    f"该页含 {len(collisions)} 个跨页重号位号（{'、'.join(collisions[:6])}）："
                    "模型按位号索引，跨页重号记在 model.duplicateDesignators"
                )
            modules.append({
                "name": name,
                "basis": MODULE_BASIS_PAGE,
                "components": components,
                "findings": [],
                "pages": [page["uuid"]],
                **({"note": "；".join(notes)} if notes else {}),
            })
            refs_by_module.append(set(components))
    else:
        facts["moduleBasis"] = MODULE_BASIS_CONNECTIVITY
        unnamed = 0
        clusters = _cluster_designators(model)
        for members in clusters:
            placed.update(members)
            name, basis = _name_cluster(members, model)
            if not name:
                unnamed += 1
                name, basis = f"未命名模块 {unnamed}", "连通性聚类：未命中任何命名特征（保守留白）"
            modules.append({
                "name": name,
                "basis": basis,
                "components": members,
                "findings": [],
            })
            refs_by_module.append(set(members))
        if attribution is None:
            facts["notes"].append(
                "本工程的页归属不可解（netlist tier 不含页信息），模块按非地网连通性聚类"
            )
        else:
            facts["notes"].append(
                f"页数带器件的只有 {len(pages_with_components)} 页，不足以按页分模块，"
                "改按非地网连通性聚类（地网把一切都连起来，用它聚类只会得到一块）"
            )
        if clusters and max(len(c) for c in clusters) >= 0.9 * max(len(model.components), 1):
            facts["notes"].append(
                f"其中最大一块含 {max(len(c) for c in clusters)}/{len(model.components)} 个器件："
                "非地网连通性基本连成一块，本节的划分信息量有限（要模块级结构得看画布与页结构）"
            )

    # The catch-all: parts the grouping left out, plus findings that point nowhere.
    unattributed_parts = [ref for ref in sorted(model.components) if ref not in placed]
    finding_modules: list[list[int]] = [[] for _ in modules]
    unmatched_findings: list[int] = []
    for index, finding in enumerate(findings):
        refs = set(finding.get("refs") or [])
        hits = [position for position, members in enumerate(refs_by_module) if refs & members]
        if hits:
            for position in hits:
                finding_modules[position].append(index)
        else:
            unmatched_findings.append(index)
    for position, module in enumerate(modules):
        module["findings"] = finding_modules[position]

    if unattributed_parts or unmatched_findings:
        modules.append({
            "name": UNATTRIBUTED_NAME,
            "basis": MODULE_BASIS_UNATTRIBUTED,
            "components": unattributed_parts,
            "findings": unmatched_findings,
            "note": (
                f"{len(unattributed_parts)} 个器件不在任何页/簇里；"
                f"{len(unmatched_findings)} 条 finding 的引用不在任何模块里"
                "（不是被丢弃，是分组没覆盖到）"
            ),
        })

    facts["moduleCount"] = len(modules)
    if attribution is not None:
        facts["pageCount"] = len(attribution)
        facts["pagesWithComponents"] = len(pages_with_components)
    return modules, facts


# --------------------------------------------------------------------------
# AI slots
# --------------------------------------------------------------------------

#: The question every `unknown_parts` entry asks. One template, so the model's
#: worklist is uniform — the *reason* differs per entry and travels beside it.
UNKNOWN_PART_QUESTION = "核对该器件周边配置是否符合规格书典型应用（去耦/上下拉/限流/耐压），并确认可用型号"

#: Why a part is on the list. Reported per entry so the model can prioritise:
#: "no MPN at all" and "an MPN this decoder refuses" are different problems.
UNKNOWN_REASON_NO_MPN = "无 MPN"
UNKNOWN_REASON_UNDECODABLE = "MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在）"
UNKNOWN_REASON_NO_SUPPLIER = "供应商字段为空"

#: Designator prefixes whose MPN is expected to carry an EIA value code, i.e. the
#: ones for which "the decoder refused it" is a real signal. An IC's MPN never
#: carries one, so asking a decoder about it would put every IC on the list.
_VALUE_CODE_PREFIXES = frozenset({"R", "C", "L", "RV", "RP", "RT", "FB"})


def _prefix_of(designator: str) -> str:
    match = re.match(r"[A-Za-z]+", designator or "")
    return match.group(0).upper() if match else ""


def unknown_parts(model: DesignModel) -> list[dict]:
    """The parts a model must look up before its review means anything.

    Three signals, each reported (`reasons`) rather than collapsed:

    * **no MPN** — nothing to search for;
    * **an MPN whose value code the decoder refuses** (`rules/values.py`, the
      whitelist task 015 built) — restricted to prefixes whose MPN is *expected*
      to carry one (R/C/L/…), because asking about an IC's MPN would list every
      IC on the board;
    * **no supplier part** — the part cannot be ordered or cross-checked by code.

    `question` is the same for all of them: the review's next step is "go and read
    the datasheet's typical application", whatever it was that made the part
    unfamiliar.
    """
    from ..rules.values import mpn_value_code

    out: list[dict] = []
    for designator in sorted(model.components):
        component = model.components[designator]
        reasons: list[str] = []
        mpn = (component.mpn or "").strip()
        if not mpn:
            reasons.append(UNKNOWN_REASON_NO_MPN)
        elif _prefix_of(designator) in _VALUE_CODE_PREFIXES and mpn_value_code(mpn) is None:
            reasons.append(UNKNOWN_REASON_UNDECODABLE)
        if not (component.lcsc_part or "").strip():
            reasons.append(UNKNOWN_REASON_NO_SUPPLIER)
        if not reasons:
            continue
        out.append({
            "designator": designator,
            "name": str(component.props.get("device_name") or component.value or ""),
            "value": component.value,
            "footprint": component.footprint,
            "mpn": mpn,
            "supplier": component.lcsc_part,
            "reasons": reasons,
            "question": UNKNOWN_PART_QUESTION,
        })
    return out


#: The Chinese skeleton the model fills and hands to the user. A constant, not a
#: prompt: the *structure* of a good answer ("what is the verdict, why, what next")
#: belongs in the tool (025 §0), and what the model contributes is the judgement,
#: not the layout.
SUMMARY_TEMPLATE = """\
【结论先行】这台板子<可以直接投板 / 需要先改 N 处 / 问题较多建议重审>：
  主机 ERC <warn/error 计数>，PCB DRC <分组计数>，boardwise 规则 <ERROR/WARN/INFO 计数>。

【错误与归因】（逐条说清是哪一类，不要合并成一句）
  - <位号/规则>: <现象> —— 归因：<设计意图不符 / 器件选型 / 布局布线 / 网表与实物不一致>
  - ...

【警告提醒】（不阻塞投板，但要有人知道）
  - <位号/规则>: <现象> —— 建议：<改 / 可接受，理由>

【建议动作】（给用户的下一步，按优先级）
  1. 先改 <条目>：<怎么做>
  2. 再确认 <条目>：<找谁/查什么>
  3. 存疑项：<unknown_parts 里需要查规格书的器件，逐条写结论>

<可选一段：读画布图看到的问题（摆放、位号可读性、网络标识、区分度）>
"""


def summary_template() -> str:
    """The `ai_slots.summary_template` — see :data:`SUMMARY_TEMPLATE`."""
    return SUMMARY_TEMPLATE


# --------------------------------------------------------------------------
# report.md
# --------------------------------------------------------------------------


def _cell(text: Any) -> str:
    """One Markdown table cell: no pipes, no newlines."""
    return str("" if text is None else text).replace("|", "\\|").replace("\n", " ").strip()


def render_report_markdown(report: dict) -> str:
    """`report.json` → the human-readable report (025 §2 阶段 E).

    Renders **only** what the JSON already says, in the JSON's own order, so the
    two cannot disagree — and so a reader who spots a gap here can find it there.
    Chinese, because the reader is 岳 (and the model, which fills the summary
    slot); the machine keys (tier ids, rule ids, designators) stay as they are,
    since those are what other tools match on.
    """
    source = report.get("source") or {}
    model = report.get("model") or {}
    summary = report.get("summary") or {}
    drc = report.get("drc") or {}
    modules = report.get("modules") or []
    findings = report.get("findings") or []
    slots = report.get("ai_slots") or {}

    errors = summary.get("errorCount", 0)
    warnings = summary.get("warnCount", 0)
    exit_code = summary.get("exitCode", 0)
    verdict = "无 ERROR" if not errors else f"{errors} 项 ERROR"
    if summary.get("countsIncomplete"):
        verdict += "（计数不完整：有主机答复不能枚举）"

    project = source.get("project") or {}
    title = project.get("friendlyName") or project.get("name") or source.get("file") or "(unknown)"
    lines: list[str] = [
        "# boardwise checkup 报告",
        "",
        f"**结论：{verdict}**（退出码 {exit_code}）",
        "",
        f"- 工程：`{title}`" + (f"（{project.get('projectUuid')}）" if project.get("projectUuid") else ""),
        f"- 数据来源：`{source.get('tier')}` — {source.get('tierLabel', '')}",
        f"- 模型：{model.get('components', '?')} 器件 / {model.get('nets', '?')} 网"
        + (f"，位号 {'、'.join(model.get('designators') or [])}" if model.get("designators") else ""),
        f"- 计数：{errors} ERROR / {warnings} WARN / {summary.get('infoCount', 0)} INFO",
        "",
    ]
    if source.get("notes"):
        lines.append("> " + "；".join(str(note) for note in source["notes"]))
        lines.append("")

    # --- errors first: the reader's next action lives here.
    lines.append("## 错误（ERROR）")
    lines.append("")
    if not summary.get("errors"):
        lines.append("无。")
    else:
        for entry in summary["errors"]:
            lines.append(_summary_bullet(entry))
    lines.append("")

    lines.append("## 主机 DRC")
    lines.append("")
    schematic = drc.get("schematic") or {}
    if schematic.get("checked"):
        if schematic.get("countsKnown") is False:
            lines.append(f"- 原理图 ERC：主机只回 boolean（passed={schematic.get('passed')}），未给计数")
        else:
            counts = "，".join(
                f"{kind} {schematic[kind]}" for kind in ("fatalError", "error", "warn")
                if kind in schematic
            ) or "无计数"
            lines.append(
                f"- 原理图 ERC：{counts}"
                f"（{schematic.get('pagesChecked')}/{schematic.get('pageCount')} 页，"
                f"计数口径 `{schematic.get('countsBasis')}`）"
            )
        lines.append(f"  - {schematic.get('note', '')}")
        for note in schematic.get("notes") or []:
            lines.append(f"  - {note}")
    else:
        lines.append(f"- 原理图 ERC：**未检查** —— {schematic.get('reason')}")

    pcb = drc.get("pcb") or {}
    if pcb.get("checked"):
        totals = pcb.get("totals") or {}
        lines.append(
            f"- PCB DRC：{totals.get('leafs', 0)} 条 / {len(pcb.get('groups') or [])} 组"
            + ("（答复被截断，总数不可知）" if pcb.get("truncated") else "")
        )
        if pcb.get("groups"):
            lines.append("")
            lines.append("| 组 | 规则 | 网络 | 说明 |")
            lines.append("|---|---|---|---|")
            for group in pcb["groups"]:
                for leaf in _walk_leafs(group):
                    lines.append(
                        f"| {_cell(group.get('name'))} | {_cell(leaf.get('ruleName') or leaf.get('errorType'))} "
                        f"| {_cell(leaf.get('net'))} | {_cell(leaf.get('explanation'))} |"
                    )
            lines.append("")
    else:
        lines.append(f"- PCB DRC：**未检查** —— {pcb.get('reason')}")
        lines.append("")
    for note in pcb.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## 模块")
    lines.append("")
    if not modules:
        lines.append("（没有可分组的结构。）")
    for module in modules:
        components = "、".join(module.get("components") or []) or "（无）"
        lines.append(f"### {module.get('name')}（{len(module.get('components') or [])} 器件）")
        lines.append("")
        lines.append(f"- 依据：{module.get('basis')}")
        if module.get("pages"):
            lines.append(f"- 页：{'、'.join(module['pages'])}")
        lines.append(f"- 器件：{components}")
        if module.get("findings"):
            lines.append("- findings：" + "、".join(
                f"[{index}] {findings[index].get('rule_id')}" for index in module["findings"]
                if index < len(findings)
            ))
        if module.get("note"):
            lines.append(f"- 注：{module['note']}")
        lines.append("")

    lines.append(f"## 规则 findings（{len(findings)}）")
    lines.append("")
    if not findings:
        lines.append("无。")
    else:
        lines.append("| # | 级别 | 规则 | 位号 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for index, finding in enumerate(findings):
            lines.append(
                f"| {index} | {_cell(finding.get('severity'))} | {_cell(finding.get('rule_id'))} "
                f"| {_cell('、'.join(finding.get('refs') or []))} | {_cell(finding.get('message'))} |"
            )
    lines.append("")

    lines.append("## 警告（WARN）")
    lines.append("")
    if not summary.get("warnings"):
        lines.append("无。")
    else:
        for entry in summary["warnings"]:
            lines.append(_summary_bullet(entry))
    lines.append("")

    lines.append("## AI 槽位（要模型做的三件事）")
    lines.append("")
    unknown = slots.get("unknown_parts") or []
    lines.append(f"### 1. 需要查规格书的器件（{len(unknown)}）")
    lines.append("")
    if not unknown:
        lines.append("无：每个器件都有型号与供应商字段。")
    else:
        lines.append("| 位号 | 名称 | 值 | 封装 | MPN | 供应商 | 为什么要查 |")
        lines.append("|---|---|---|---|---|---|---|")
        for part in unknown:
            lines.append(
                f"| {_cell(part.get('designator'))} | {_cell(part.get('name'))} | {_cell(part.get('value'))} "
                f"| {_cell(part.get('footprint'))} | {_cell(part.get('mpn'))} | {_cell(part.get('supplier'))} "
                f"| {_cell('；'.join(part.get('reasons') or []))} |"
            )
        lines.append("")
        lines.append(f"每个器件问同一件事：{UNKNOWN_PART_QUESTION}")
    lines.append("")

    images = slots.get("canvas_images") or []
    lines.append(f"### 2. 画布图（{len(images)}）")
    lines.append("")
    if not images:
        lines.append(f"无图。{slots.get('canvas_images_note', '')}")
    else:
        for image in images:
            if image.get("file"):
                lines.append(f"- [{image.get('page') or image.get('pageUuid')}]({image['file']})"
                             f"（{image.get('bytes', '?')} B）")
            else:
                lines.append(f"- {image.get('page') or image.get('pageUuid')}：取图失败 —— {image.get('error')}")
    lines.append("")

    lines.append("### 3. 总结模板（原样留槽，由模型填写）")
    lines.append("")
    lines.append("```text")
    lines.append(str(slots.get("summary_template", "")).rstrip())
    lines.append("```")
    lines.append("")

    lines.append("## 元数据")
    lines.append("")
    lines.append(f"- 生成时间：{report.get('generatedAt')}")
    lines.append(f"- report schema：`{report.get('schema')}`")
    lines.append(f"- tier：`{source.get('tier')}`；pageAttribution：`{source.get('pageAttribution')}`")
    lines.append(f"- 宿主：{source.get('hostVersion') or '(未知)'}；connector：{source.get('connectorVersion') or '(未知)'}")
    lines.append(f"- --file：{source.get('file') or '(无，在线路径)'}")
    for attempt in source.get("attempts") or []:
        lines.append(
            f"- attempt `{attempt.get('tier')}`：{'ok' if attempt.get('ok') else 'failed'}"
            + (f"，{attempt.get('ms')} ms" if attempt.get("ms") is not None else "")
            + (f"，{attempt.get('bytes')} B" if attempt.get("bytes") is not None else "")
            + (f"，{attempt.get('code')}" if attempt.get("code") else "")
        )
    for key, label in (("modules", "模块"), ("ai_slots", "AI 槽位"), ("reportMd", "report.md"),
                       ("canvasImages", "画布图")):
        if key in (report.get("pending") or {}):
            lines.append(f"- 待办（{label}）：{report['pending'][key]}")
    lines.append("")
    return "\n".join(lines)


def _summary_bullet(entry: dict) -> str:
    """One summary entry as a bullet: what it is, plus the reference to check it at."""
    count = entry.get("count")
    number = "计数未知" if count is None else str(count)
    label = entry.get("ruleName") or entry.get("ruleId") or entry.get("kind") or ""
    net = f" net {entry['net']}" if entry.get("net") else ""
    detail = f" —— {entry['detail']}" if entry.get("detail") else ""
    return f"- `{entry.get('severity')}` {number}x {label}{net}（{entry.get('ref')}）{detail}"


def _walk_leafs(group: dict) -> list[dict]:
    """Every leaf under a mapped group, in tree order."""
    out: list[dict] = list(group.get("leafs") or [])
    for child in group.get("children") or []:
        out.extend(_walk_leafs(child))
    return out
