"""checkup's report-level assembly (025 batch 4): modules, AI slots, report.md.

Three pieces, and one rule they share: **say where a claim came from, and when a
grouping could not be made, say that instead of inventing one.**

* **`modules** — a multi-page project is grouped by page (an engineer's own
  split), a single-page one by connectivity (the only structure left). Neither is
  guessed: page attribution is read out of the archive's `SCH_PAGE` documents, and
  the connectivity pass runs on the **non-ground** net graph, because GND joins
  everything and a rule that puts every component in one module has named
  nothing.
* **`ai_slots`** — the three things xianyuyijinban's architecture leaves to the model
  (025 §0): the parts it must WebSearch, the canvas images it must look at, and the
  summary it must write. The slots are a worklist, not an analysis: each entry
  says *what to check*, and the question marks the report's own numbers as
  something to confirm rather than to trust.
* **`render_report_markdown`** — `report.json` is the contract; the Markdown is
  what a human (and the model) actually reads. It renders only what the JSON
  already contains, in the same order, so the two cannot disagree.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any, Iterable

from ..core.architecture import STALE_MARK
from ..core.designintent import INTENT_MISSING
from ..core.model import Component, DesignModel, Net, is_ground_net
from ..core.parts import DESIGNATOR_CATEGORIES

#: How the components were grouped, per module and for the report header.
MODULE_BASIS_PAGE = "page"
MODULE_BASIS_CONNECTIVITY = "connectivity"
MODULE_BASIS_UNATTRIBUTED = "unattributed"
#: The project level: each board is grouped by the two rules above (040b).
MODULE_BASIS_BOARD = "board"

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

    Why this pass exists: the model is keyed by designator, so the per-page
    split is gone by the time a report sees it. Since 040 the parser keeps the
    pages *apart* in connectivity (three pages of a multi-board project are
    three boards, not one welded netlist), but the model still carries no page
    field — 040b's work — so a report that wants to say "which page is this
    module on" re-derives it here. Re-deriving it from the same record stream is
    cheap, read-only, and keeps the parser untouched.

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


def _model_components(model) -> dict[str, Component]:
    """A model's components, whether it is one board or a project (040b).

    For a project the boards are merged **by name, first board wins** — the shape
    these readers ask for ("is this name here", "how big is this"). Anything that
    needs the per-board truth takes a board model instead: the module grouping
    does exactly that.
    """
    from ..core.model import ProjectModel

    if not isinstance(model, ProjectModel):
        return model.components
    merged: dict[str, Component] = {}
    for board_model in model.boards:
        for designator, component in board_model.components.items():
            merged.setdefault(designator, component)
    return merged


def _model_nets(model) -> dict[str, Net]:
    """A model's nets, merged **by name** for a project (040b).

    A net name that exists on two boards is one entry here, because every reader
    of this helper matches nets by name (the warning triage asks "which module is
    this net in"). Net *instances* stay per board in the model.
    """
    from ..core.model import ProjectModel

    if not isinstance(model, ProjectModel):
        return model.nets
    merged: dict[str, Net] = {}
    for board_model in model.boards:
        for name, net in board_model.nets.items():
            existing = merged.get(name)
            if existing is None:
                merged[name] = Net(name=name, pins=list(net.pins))
                continue
            for pin in net.pins:
                if pin not in existing.pins:
                    existing.pins.append(pin)
    return merged


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

    components = _model_components(model)
    for component in components.values():
        find(component.designator)
    for name, net in _model_nets(model).items():
        if is_ground_net(name):
            continue
        designators = [ref for ref, _pin in net.pins if ref in components]
        for other in designators[1:]:
            union(designators[0], other)

    clusters: dict[str, list[str]] = {}
    for designator in sorted(components):
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
    components = _model_components(model)
    parts = [components[ref] for ref in refs if ref in components]
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
    components = _model_components(model)
    for designator in designators[:4]:
        component = components.get(designator)
        name = str(component.props.get("device_name") or component.value or "") if component else ""
        shown.append(f"{designator}={name.strip()[:28]}" if name else designator)
    return "、".join(shown) + ("…" if len(designators) > 4 else "")


def _board_fact(board_model) -> dict:
    """One board's line in the report's `boards` list (the schema's board entry)."""
    return {
        "uuid": board_model.board.uuid,
        "title": board_model.board.title,
        "pages": list(board_model.board.page_uuids),
        "components": len(board_model.components),
        "nets": len(board_model.nets),
    }


def modules_section(
    *,
    model: DesignModel,
    findings: list[dict],
    attribution: dict[str, dict] | None = None,
    attribution_source: str = PAGE_ATTRIBUTION_UNRESOLVED,
    basis: str | None = None,
    board: str = "",
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

    ``board`` names the board whose findings this call may claim (040b): a
    project's per-board pass skips findings another board produced, so nothing is
    listed twice and nothing lands in a board's `未归属` just because it was
    judged next door.

    040b: on a **project** the rule is applied **per board** — a board's pages
    are its own, and connectivity does not cross boards — so every module carries
    the board it belongs to. The *choice* between the two rules stays a
    project-level one (``basis`` carries it in, decided once from the project's
    own page evidence): a board with a single drawn page must not lose that page
    as its structure just because the board next to it has three. A finding is
    matched to modules **of its own board** when it states one: two boards can
    both hold a ``U2``, and a Board1 finding about ``U2`` must not be attached to
    Board3's part of the same name.

    Either way, components that no page claims and findings that no module claims
    land in one `未归属` module rather than disappearing: an unattributed part is
    information, and a dropped one is a lie by omission.
    """
    from ..core.model import ProjectModel

    if isinstance(model, ProjectModel) and len(model.boards) == 1:
        # A one-board project is one board: 040b adds a field to its modules and
        # changes nothing else about them, so a single-board report's notes,
        # basis and module names are what they were (WI-4).
        board_model = model.boards[0]
        modules, facts = modules_section(
            model=board_model,
            findings=findings,
            attribution=attribution,
            attribution_source=attribution_source,
            basis=basis,
            board=board_model.board.title,
        )
        for module in modules:
            # The board rides on the module whenever there *is* a project to
            # attribute (the renderer/console only print it when there are
            # several); a plain model's modules stay exactly as they were.
            module["board"] = board_model.board.title
        facts["boards"] = [_board_fact(board_model)]
        return modules, facts

    if isinstance(model, ProjectModel):
        all_pages_with_components = [
            page
            for page in (attribution or {}).values()
            if page.get("components")
        ]
        project_basis = (
            MODULE_BASIS_PAGE
            if len(all_pages_with_components) >= 2
            else MODULE_BASIS_CONNECTIVITY
        )
        modules: list[dict] = []
        facts: dict[str, Any] = {
            "moduleBasis": MODULE_BASIS_BOARD,
            "insideBoardBasis": project_basis,
            "pageAttribution": attribution_source,
            "boards": [_board_fact(board_model) for board_model in model.boards],
            "notes": [],
        }
        pages_seen = 0
        pages_with_components = 0
        for board_model in model.boards:
            board_pages = set(board_model.board.page_uuids)
            board_attribution = (
                {
                    page_uuid: page
                    for page_uuid, page in (attribution or {}).items()
                    if page_uuid in board_pages
                }
                if attribution
                else None
            )
            board_modules, board_facts = modules_section(
                model=board_model,
                findings=findings,
                attribution=board_attribution,
                attribution_source=attribution_source,
                basis=project_basis,
                board=board_model.board.title,
            )
            for module in board_modules:
                module["board"] = board_model.board.title
                if module.get("basis") == MODULE_BASIS_UNATTRIBUTED:
                    module["name"] = f"{board_model.board.title}/{UNATTRIBUTED_NAME}"
            modules.extend(board_modules)
            pages_seen += board_facts.get("pageCount", 0)
            pages_with_components += board_facts.get("pagesWithComponents", 0)
            facts["notes"].extend(
                f"{board_model.board.title}: {note}" for note in board_facts["notes"]
            )
        facts["moduleCount"] = len(modules)
        # Two pages called "P1" on two *different* boards are still a reader trap
        # once they sit in one list (measured: this fixture's three pages are all
        # titled P1). Each board's own disambiguation cannot see across boards, so
        # the project level re-checks: the board title first, the page uuid as the
        # last resort.
        merged_names = collections.Counter(module["name"] for module in modules)
        for module in modules:
            if merged_names[module["name"]] > 1:
                module["name"] = f"{module['board']}/{module['name']}"
        still_shared = collections.Counter(module["name"] for module in modules)
        for module in modules:
            if still_shared[module["name"]] > 1 and module.get("pages"):
                module["name"] = f"{module['name']}@{module['pages'][0][:8]}"
        if attribution is not None:
            facts["pageCount"] = pages_seen
            facts["pagesWithComponents"] = pages_with_components
        facts["notes"].append(
            f"本工程有 {len(model.boards)} 块板（{'、'.join(model.board_titles())}）："
            "模块按板再按页/连通性划分，findings 带板归属"
        )
        return modules, facts

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

    use_pages = (
        basis == MODULE_BASIS_PAGE
        if basis is not None
        else len(pages_with_components) >= 2
    )
    if use_pages and pages_with_components:
        facts["moduleBasis"] = MODULE_BASIS_PAGE
        chosen = sorted(pages_with_components, key=lambda p: (p.get("title") or "", p["uuid"]))
        title_counts: dict[str, int] = {}
        for page in chosen:
            title = page.get("title") or page["uuid"]
            title_counts[title] = title_counts.get(title, 0) + 1
        # Both kinds of repeat leave one placement out of the model, so both
        # make a page's ref list ambiguous — the model's own list is exactly
        # "this name does not resolve to one placement" within its board
        # (040 §WI-3; 040b scoped it per board).
        ambiguous = model.repeated_designators()
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
                    f"该页含 {len(collisions)} 个重号位号（{'、'.join(collisions[:6])}）："
                    "模型按位号索引，同名跨板记在 model.crossBoardDesignators"
                    "（该板与其他板同名），同名同板跨页记在同板模型的 crossPageDesignators"
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
        if board and finding.get("board") and finding["board"] != board:
            # Another board's finding: not this board's business, and *not*
            # "unattributed" either — attributing it here would double-count it.
            continue
        refs = set(finding.get("refs") or [])
        hits = [
            position
            for position, members in enumerate(refs_by_module)
            if refs & members
            # 040b: a finding that states its board only matches modules of that
            # board. Two boards can both hold a `U2`, and attaching a Board1
            # claim about it to Board3's part would be a wrong attribution that
            # looks like a fact.
            and (
                not finding.get("board")
                or not modules[position].get("board")
                or finding["board"] == modules[position]["board"]
            )
        ]
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
# the location chain (issue #69 条 1): 工程 → 板 → 页 → 器件/网 → 问题
# --------------------------------------------------------------------------
#
# A finding used to carry a `board` and a `refs` list, which is enough to *find*
# the line in `report.json` and nothing else: a hardware engineer reading
# `report.md` cannot answer "which page of which board is U5 on" without opening
# the editor. The chain below is the four links a reader needs, assembled from
# what the report **already knows** — the project's own boards, the archive's page
# attribution and the module grouping — and from nothing else.
#
# The one rule: **a link that cannot be derived is reported as missing, never
# invented.** `page: None` is a reading ("this tier carries no page information"),
# not a placeholder for a guess. A chain with a hole is printed with the hole
# visible (see :func:`chain_text`), because a silently shortened chain reads like
# a complete one.

#: The chain's links, in order. Rendered into both `report.md` and
#: `review-summary.md`, and asserted by name in the tests.
CHAIN_LINKS = ("project", "board", "page", "refs")

#: What a link reads when the report cannot derive it. Deliberately a word rather
#: than a dash: "—" in a table can be mistaken for "nothing to report", while
#: this says the report does not know.
CHAIN_UNKNOWN = "未标注"


def _chain_project(source: dict) -> str:
    """The project link: the report's own project name, or its file, or unknown.

    Prefers `friendlyName` (what a human calls it) over the uuid, and falls back
    to the file it read so an offline `--file` run still names something. An
    archive that carries no project metadata and was read from stdin has nothing:
    that is ``CHAIN_UNKNOWN``, not the file name.
    """
    project = source.get("project") or {}
    name = (
        project.get("friendlyName")
        or project.get("name")
        or source.get("file")
        or ""
    )
    return str(name) if name else CHAIN_UNKNOWN


def _chain_board(finding: dict, boards: list[dict]) -> str:
    """The board link: the finding's own `board`, or the project's single board.

    A PCB finding names its board (`PCB1`); a schematic finding names the board
    its module lives on. A project with exactly one board needs no lookup — there
    is no second candidate to confuse the reader with.
    """
    board = str(finding.get("board") or "")
    if board:
        return board
    if len(boards) == 1:
        return str(boards[0].get("title") or "")
    return CHAIN_UNKNOWN


def _page_label(uuid: str, page: dict, titles: dict[str, int]) -> str:
    """One page's name: `title (uuid8)` when the title is not unique in this report.

    Three pages all titled `P1` is measured on the 毕设 fixture, and a chain that
    said `P1` three times would not be a location at all — the uuid tail is what
    makes the page addressable, exactly as it did for the module names (040b).
    """
    title = str(page.get("title") or uuid)
    return f"{title}（{uuid[:8]}）" if titles.get(title, 0) > 1 else title


def _chain_pages(
    refs: list[str], modules: list[dict], attribution: dict[str, dict] | None,
    board: str = "",
) -> list[str]:
    """The page links of one finding: every page its refs land on.

    Two readings, in this order:

    * **the report's own modules** (preferred) — they already decided the
      designer's page split and hold `pages[]` per module, so the chain cannot
      disagree with the module table printed above it in `report.md`;
    * **the archive's attribution alone** — what is left when a caller passes the
      pages without the grouping (the weaker but still honest reading: a page
      that lists the designator is a page the part is on).

    `board` narrows both readings to that board's own pages when the finding
    names one. It matters: a `conn-duplicate-designators` finding about `C1`
    ("placed on more than one board") matches modules of **both** boards, and
    printing Board2's page under a `Board1 →` link sends the reader to the wrong
    sheet for a finding that is about Board1's placement. A finding that names no
    board gets every page its refs are on — there is nothing to narrow by.

    Either way a page with no components (a title-block-only page) never claims
    a finding, and an unresolved tier (no pages at all) returns nothing, which
    the caller renders as the missing link rather than an empty string.
    """
    if not refs:
        return []
    wanted = set(refs)
    titles: dict[str, int] = {}
    for uuid, page in (attribution or {}).items():
        title = str(page.get("title") or uuid)
        titles[title] = titles.get(title, 0) + 1
    if modules:
        names: list[str] = []
        for module in modules:
            if board and module.get("board") and module["board"] != board:
                continue
            if not set(module.get("components") or []) & wanted:
                continue
            for uuid in module.get("pages") or []:
                name = _page_label(uuid, (attribution or {}).get(uuid) or {}, titles)
                if name not in names:
                    names.append(name)
        return names
    return [
        _page_label(uuid, page, titles)
        for uuid, page in (attribution or {}).items()
        if set(page.get("components") or []) & wanted
    ]


def finding_chains(
    report: dict, *, attribution: dict[str, dict] | None = None,
    modules: list[dict] | None = None,
) -> list[dict]:
    """One location chain per finding, in the report's own `findings[]` order.

    The four links of issue #69's chain, each rendered as a one-line string the
    Markdown and the `review-summary.md` skeleton can print verbatim:

    ``工程 → 板 → 页（可缺） → 器件/网 → 问题``

    `attribution` is `page_attribution_from_archive`'s `{page_uuid: {title,
    components}}` — the caller already has it (it built `modules` from it), and
    passing it in is what lets a page be **named** rather than only its uuid
    quoted. `modules` is the report's own `modules[]`; without it the page link
    is derived from `attribution` alone by matching designators, which is the
    weaker reading and still honest.

    A finding with no `refs` and no `target.component_ref` (a PCB spacing
    measurement between two parts the rule did not name) still gets all four
    keys — the chain exists, the device link reads `CHAIN_UNKNOWN`, and the
    report says so rather than dropping the row.
    """
    source = report.get("source") or {}
    boards = source.get("boards") or []
    findings = report.get("findings") or []
    module_list = modules if modules is not None else (report.get("modules") or [])
    project = _chain_project(source)
    rows: list[dict] = []
    for index, finding in enumerate(findings):
        target = finding.get("target") or {}
        refs = [str(ref) for ref in (finding.get("refs") or []) if str(ref)]
        component = str(target.get("component_ref") or "")
        if component and component not in refs:
            refs = [component, *refs]
        net_refs = [str(net) for net in (target.get("net_refs") or []) if str(net)]
        board = _chain_board(finding, boards)
        pages = _chain_pages(refs, module_list, attribution, board)
        device = "、".join(refs) if refs else CHAIN_UNKNOWN
        if net_refs:
            device = f"{device}（网 {'、'.join(net_refs)}）"
        problem = str(finding.get("message") or "").strip() or CHAIN_UNKNOWN
        rows.append({
            "index": index,
            "rule_id": str(finding.get("rule_id") or ""),
            "severity": str(finding.get("severity") or ""),
            "project": project,
            "board": board,
            "page": "、".join(pages) if pages else CHAIN_UNKNOWN,
            "refs": device,
            "problem": problem,
            "missing": [
                link for link, value in (
                    ("project", project), ("board", board),
                    ("page", "、".join(pages) if pages else CHAIN_UNKNOWN),
                    ("refs", device),
                )
                if value == CHAIN_UNKNOWN
            ],
        })
    return rows


#: The findings key the report carries, under the name the pre-chain schema used.
#: Kept as an alias because three older readers and several tests use it; the
#: report's own name is the new one (issue #69 条 1).
CHAINS_KEY = "location_chains"
FINDING_CHAINS_KEY = CHAINS_KEY


def _report_chains(report: dict) -> list[dict]:
    """The report's location chains, reading the key under either name.

    ``report.json`` names the section ``location_chains``; a report built by this
    engine always carries it. The fallback to ``finding_chains`` keeps a
    hand-built report dict (the shape the 025d tests build) rendering exactly as
    it did — a missing section is a reading, and it is derived on the spot from
    the same function rather than being an empty table.
    """
    chains = report.get(CHAINS_KEY)
    if isinstance(chains, list):
        return chains
    return finding_chains(report)


def chain_text(row: dict) -> str:
    """One chain as the single line both renderings print.

    The page link is optional *in the data* (a netlist tier has none) but never
    optional in the **line**: it is printed as `页:（本档无页信息）` rather than
    dropped, so a reader can tell "no page on this board" from "the report did
    not look". A chain with any other missing link says so at the end too.
    """
    page = row.get("page") or ""
    if page == CHAIN_UNKNOWN:
        page = "（本档无页信息）"
    line = (
        f"{row.get('project') or CHAIN_UNKNOWN} → {row.get('board') or CHAIN_UNKNOWN} "
        f"→ 页:{page} → {row.get('refs') or CHAIN_UNKNOWN}"
    )
    missing = [link for link in (row.get("missing") or []) if link != "page"]
    if missing:
        line += f" 〔缺 {'、'.join(missing)}〕"
    return line


#: The skeleton header `review-summary.md` carries (issue #69 条 1 的 AI 侧机械化).
#: Every line here is load-bearing: the SOP says the model fills the two blanks and
#: nothing else, so the header is what makes "补全骨架" an instruction rather than
#: a request to start from nothing.
REVIEW_SUMMARY_HEADER = """\
<!-- 本文件由 `boardwise checkup` 生成骨架：定位链已按机器账预填，
     「分析」「建议」两栏留空给 AI 填。收尾必须补全（docs/review-sop.md §3.1），
     工程师只看这一份。删掉这两段注释前先读那份 SOP。 -->

# 审查总结 · {project}

**结论：{conclusion}**（退出码 {exit_code}）
数据来源：{tier} — {tier_label}

## 1. 连接状态（开工第一句必须报，见 docs/review-sop.md §3.0）

<!-- AI 在这里写一行：连上了哪个工程/哪个窗口；没连上写清楚怎么修。 -->

## 2. 逐条问题（{count} 条）

| # | 级别 | 规则 | 定位链（工程 → 板 → 页 → 器件/网） | 问题 | 分析 | 建议 |
|---|---|---|---|---|---|---|
"""

#: The two columns the model fills. Kept as constants so the skeleton, the SOP
#: and the tests all name the same two words.
REVIEW_SUMMARY_BLANK_ANALYSIS = "<!-- 分析：为什么是问题、根因在哪 -->"
REVIEW_SUMMARY_BLANK_ADVICE = "<!-- 建议：怎么改/怎么确认 -->"


def render_review_summary(report: dict, chains: list[dict]) -> str:
    """The `review-summary.md` **skeleton**: one prefilled row per finding.

    Not the summary — issue #69 splits the two outputs on purpose: `report.json`
    / `report.md` are the machine's ledger and stay complete and mechanical, while
    this file is the one an engineer reads, and it is only useful once the model
    has filled the two blank columns. What the machine contributes is the part
    that must not drift: **the location chain**, prefilled verbatim from the same
    derivation `report.md` renders, so the two cannot disagree about where a
    problem is.

    Every finding gets a row even when its chain has holes — the row prints which
    links are missing (see :func:`chain_text`), because "the tool could not say
    where this is" is itself something the model must answer rather than skip.
    """
    source = report.get("source") or {}
    summary = report.get("summary") or {}
    project = source.get("project") or {}
    title = (
        project.get("friendlyName") or project.get("name")
        or source.get("file") or "(unknown)"
    )
    lines = [
        REVIEW_SUMMARY_HEADER.format(
            project=title,
            conclusion=summary.get("conclusion") or summary.get("exitCode", 0),
            exit_code=summary.get("exitCode", 0),
            tier=source.get("tier") or "",
            tier_label=source.get("tierLabel") or "",
            count=len(chains),
        )
    ]
    if not chains:
        lines.append("| — | — | — | — | 本次审查没有 finding | — | — |\n")
    for row in chains:
        lines.append(
            f"| {row['index']} | {_cell(row['severity'])} | {_cell(row['rule_id'])} "
            f"| {_cell(chain_text(row))} | {_cell(row['problem'])} "
            f"| {REVIEW_SUMMARY_BLANK_ANALYSIS} | {REVIEW_SUMMARY_BLANK_ADVICE} |\n"
        )
    lines.append(
        "\n## 3. 待确认（本报告依赖的未知项）\n\n"
        "<!-- needs_datasheet 非空时逐条写：缺什么资料、找谁要。空着才允许写「通过」。 -->\n"
        "\n## 4. 下一步（按优先级）\n\n"
        "<!-- 1. / 2. / 3. …工程师照着做就行，别写「建议进一步分析」。 -->\n"
    )
    return "".join(lines)


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


def _parts_with_boards(model) -> list[tuple[str, Component, list[str]]]:
    """``(designator, component, board titles)`` — one row per **placement** (040b).

    A project yields one row per board placement rather than one per name: two
    boards can hold two *different* parts under one name (the 毕设 project's `U2`
    is a 2x6 header on Board3 and a 28-pin part on Board1), and a single merged
    row would have to pick one part's MPN to describe both. A plain model yields
    one row per component with no boards — the shape before 040b.
    """
    from ..core.model import ProjectModel

    if not isinstance(model, ProjectModel):
        return [
            (designator, component, [])
            for designator, component in sorted(model.components.items())
        ]
    rows: list[tuple[str, Component, list[str]]] = []
    for board_model in model.boards:
        for designator, component in sorted(board_model.components.items()):
            rows.append((designator, component, [board_model.board.title]))
    return rows


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
    for designator, component, boards in _parts_with_boards(model):
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
            **_board_field(boards),
        })
    return out


def _board_field(boards: list[str]) -> dict:
    """``{"boards": [...]}`` for a multi-board model, ``{}`` for one board.

    Added, never renamed (the schema rule): a single-board report's rows are
    byte-for-byte what they were, and a project's rows say which board they are
    about.
    """
    return {"boards": boards} if boards else {}


# --------------------------------------------------------------------------
# 未审器件 — the promoted section (039 批② §WI-1)
# --------------------------------------------------------------------------

#: The three acquisition channels xianyuyijinban named, in the order the SOP tries them.
CHANNEL_ENGINEER = "engineer"
CHANNEL_LCSC = "lcsc"
CHANNEL_OFFICIAL = "official"

#: Why the official-site channel is empty in the report. The CLI does not search
#: the web; the AI does, and the report gives it the queries to start from.
OFFICIAL_CHANNEL_DETAIL = (
    "CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名"
)

UNREVIEWED_DATASHEET_DIR = ".tmp_datasheets"


def _local_datasheet(directory: Path | None, *needles: str) -> Path | None:
    """A local PDF whose file name carries one of ``needles`` (case-insensitive)."""
    if directory is None:
        return None
    folder = Path(directory)
    if not folder.is_dir():
        return None
    wanted = [needle.strip().lower() for needle in needles if needle and needle.strip()]
    for path in sorted(folder.glob("*.pdf")):
        name = path.name.lower()
        if any(needle in name for needle in wanted):
            return path
    return None


def suggested_queries(mpn: str, manufacturer: str = "", value: str = "") -> list[str]:
    """The query words to hand the AI when it has to go to the vendor's site."""
    text = (mpn or "").strip()
    if not text:
        # No MPN to search on: the honest query is about the marking on the part.
        text = (value or "").strip() or "(没有 MPN)"
        return [f"{text} datasheet pdf", f"{text} 数据手册 规格书"]
    queries = [f"{text} datasheet pdf", f"{text} 数据手册"]
    if manufacturer:
        queries.append(f"{manufacturer} {text} datasheet")
        site = manufacturer.split("(")[0].strip()
        if site and site.isascii():
            queries.append(f"{text} site:{site.lower()}.com")
    return queries


def unreviewed_parts(
    model: DesignModel,
    *,
    library: object | None = None,
    datasheet_dir: str | Path | None = UNREVIEWED_DATASHEET_DIR,
) -> list[dict]:
    """The 「未审器件」 section: parts whose review cannot be finished yet.

    `unknown_parts` (025) listed the parts a model must look up, by identity
    signals. This is that list **promoted**, because xianyuyijinban's first instruction is a
    gate rather than a worklist: a part the shelf cannot judge stops the review,
    and the report has to say which channel could still supply its datasheet.

    A part is here when any of these holds:

    * it is an **IC by designation** and the shelf gives no facts that a rule may
      act on — no entry at all, an entry with no facts, or a **candidate** whose
      `facts_verified` is false (039 批①'s gate: an unverified claim does not
      drive rules, so it does not close this item either);
    * it has no MPN, or an MPN whose value code this project refuses, or no
      supplier part number — the three 025 identity signals, kept because they
      are also reasons a datasheet hunt cannot even start.

    Each entry carries the three channels' real state, and the CLI only claims
    what it can measure: `engineer` (a local PDF in the datasheet folder —
    `parts fetch --file` puts one there), `lcsc` (the shelf entry's own
    `datasheetPdfUrl`/`datasheetUrl`, which is what `parts fetch` downloads),
    `official` (never the CLI's — it hands over the queries instead).
    """
    from ..core.parts import FACTS_KEYS, find_facts, is_ic_designator

    known = {
        (entry["designator"], tuple(entry.get("boards") or [])): entry
        for entry in unknown_parts(model)
    }
    folder = Path(datasheet_dir) if datasheet_dir else None
    out: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        is_ic = is_ic_designator(designator)
        entry = None
        if library is not None:
            if (component.mpn or "").strip():
                entry = find_facts(library, mpn=component.mpn)
            if entry is None and (component.lcsc_part or "").strip():
                entry = find_facts(library, lcsc=component.lcsc_part)
        facts = {}
        if entry is not None:
            facts = entry.facts if entry.facts is not None else (entry.candidate_facts or {})
        gated = bool(entry is not None and not entry.facts_verified)
        no_driving_facts = entry is None or entry.facts is None
        reasons = list(known.get((designator, tuple(boards)), {}).get("reasons") or [])
        if not (is_ic and no_driving_facts) and not reasons:
            continue
        if is_ic and no_driving_facts and not reasons:
            reasons = (
                ["货架没有可驱动规则的 facts"
                 + ("（候选条目未核验）" if gated else "（条目没有 facts）")]
                if entry is not None
                else ["货架没有这颗料"]
            )
        mpn = (component.mpn or "").strip()
        manufacturer = (entry.manufacturer if entry is not None else "") or str(
            component.props.get("manufacturer") or ""
        )
        local = _local_datasheet(folder, mpn, component.lcsc_part or "")
        entry_url = (entry.datasheetPdfUrl if entry is not None else "") or ""
        page_url = (entry.datasheetUrl if entry is not None else "") or ""
        channels = {
            CHANNEL_ENGINEER: {
                "ok": local is not None,
                "detail": (
                    f"工作区有本地手册 {local.name}" if local is not None
                    else f"{UNREVIEWED_DATASHEET_DIR}/ 下没有这颗料的 PDF"
                    "（工程师给手册用 `parts fetch --file`）"
                ),
                "path": str(local) if local is not None else "",
            },
            CHANNEL_LCSC: {
                "ok": bool(entry_url or page_url),
                "detail": (
                    "库条目自带 PDF 链接，`parts fetch` 可直接下载" if entry_url
                    else "库条目只有商品页链接（PDF 链接要回商品页取）" if page_url
                    else "库条目没有任何 datasheet 链接"
                ),
                "datasheetPdfUrl": entry_url,
                "datasheetUrl": page_url,
                "shelfKey": entry.key if entry is not None else "",
            },
            CHANNEL_OFFICIAL: {
                "ok": None,
                "by": "ai",
                "detail": OFFICIAL_CHANNEL_DETAIL,
                "suggestedQueries": suggested_queries(mpn, manufacturer, component.value),
            },
        }
        out.append({
            "designator": designator,
            "name": str(component.props.get("device_name") or component.value or ""),
            "value": component.value,
            "footprint": component.footprint,
            "mpn": mpn,
            "supplier": component.lcsc_part,
            "reasons": reasons,
            "question": UNKNOWN_PART_QUESTION,
            "isIc": is_ic,
            "onShelf": entry is not None,
            "shelfKey": entry.key if entry is not None else "",
            "factsVerified": (entry.facts_verified if entry is not None else None),
            "factsPresent": sorted(facts),
            "missingFacts": (
                [key for key in FACTS_KEYS if key not in facts] if is_ic else []
            ),
            "channels": channels,
            **_board_field(boards),
        })
    return out


# --------------------------------------------------------------------------
# needs_datasheet — ⓪ 先问再判: what the report still depends on (058, issue #8)
# --------------------------------------------------------------------------

#: The two triggers a `needs_datasheet[]` entry can carry. `facts` is the seed
#: `checkup` computes by itself — the shelf has nothing a rule may act on, so
#: the *report* already knows this part is a question. `marked` is the
#: reviewer's own claim that **they** cannot establish what a device or a pin
#: does, entered before any verdict through `boardwise need-datasheet`.
TRIGGER_FACTS = "facts"
TRIGGER_MARKED = "marked"

#: The fixed first line of the report.md section while it is non-empty. This is
#: the whole gate 058 exists for: issue #8's review judged an FB/ICG pair with
#: no datasheet, and the two judgements were both wrong the next day. A report
#: that still depends on an unread datasheet must not be readable as a pass.
NEEDS_DATASHEET_BLOCK = "本节非空期间，本报告不得宣称审查通过。"

#: What a marked row means, spelled for the report's reader.
MARKED_ENTRY_NOTE = (
    "审查者标记：这些管脚/器件的作用无法从图纸与手上资料建立；"
    "资料到位前，只能写「无法确认（等资料）」，不许写「通过/不符合」"
)


def dependent_findings(findings: list[dict] | None, part: str) -> list[str]:
    """The `findings[]` rows that name ``part``, as ``<rule_id>@<part>`` refs.

    Read out of the finding's own `refs` (the designators its evidence names —
    ``engines/review.finding_refs``) plus its plan target, the same two sources
    the Chinese summary reads, so "a finding about U7" means one thing in this
    report. Derived here rather than stored on the finding: the rule engine is
    untouched (058 §二 — this is a reading of what a rule already wrote).
    """
    out: list[str] = []
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        named = [str(ref) for ref in (finding.get("refs") or [])]
        target = finding.get("target")
        if isinstance(target, dict):
            component_ref = str(target.get("component_ref") or "")
            if component_ref and component_ref not in named:
                named.insert(0, component_ref)
        if part not in named:
            continue
        ref = f"{finding.get('rule_id')}@{part}"
        if ref not in out:
            out.append(ref)
    return out


def marked_parts(entries: list[dict] | None) -> list[str]:
    """The distinct parts **the reviewer** marked, in report order.

    Exactly the number `completion.needsDatasheet` reports and the number
    `summary.conclusion` says out loud: one per part whatever the number of
    pins, so a part that is also a facts seed is counted once (058 §二).
    """
    out: list[str] = []
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("trigger") != TRIGGER_MARKED:
            continue
        part = str(entry.get("part") or "")
        if part and part not in out:
            out.append(part)
    return out


def needs_datasheet_section(
    unreviewed: list[dict] | None,
    marked: list[dict] | None,
    findings: list[dict] | None = None,
) -> list[dict]:
    """The `needs_datasheet[]` section — the ⓪ 先问再判 worklist (058 §二).

    One section, two triggers, so the review has **one** list of what it depends
    on instead of a facts-only gate that a reviewer walking around `checkup`
    never meets (issue #8's缺口① and ②):

    * **facts** — every `unreviewed_parts[]` row carried over as it stands
      (`channels` included; that section itself is untouched, 053's narrow
      discipline). `checkup` writes these by itself.
    * **marked** — pin-level rows the reviewer wrote down (``{"part","pin",
      "reason"}``; an empty ``pin`` means the whole part: see
      ``boardwise.cli._cmd_need_datasheet``). They are folded into **one entry
      per part** here, because the gate is per part and one datasheet answers
      every pin of it.

    When a part is hit by both triggers the marked entry wins — the reviewer's
    own words are the more specific claim — and carries ``factSeed: true`` so
    the seed (its channels, MPN, missing facts) is not lost; the part is then
    counted once by :func:`marked_parts`. A facts row copied here keeps its
    designator under ``part``; everything else about it is unchanged.
    """
    seed_by_part: dict[str, dict] = {}
    for row in unreviewed or []:
        if not isinstance(row, dict):
            continue
        part = str(row.get("designator") or "")
        if part:
            seed_by_part.setdefault(part, row)

    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for mark in marked or []:
        if not isinstance(mark, dict):
            continue
        part = str(mark.get("part") or "").strip()
        if not part:
            continue
        if part not in grouped:
            grouped[part] = []
            order.append(part)
        grouped[part].append(mark)

    def _seed_fields(seed: dict | None) -> dict:
        return {
            "channels": (seed.get("channels") or {}) if seed is not None else {},
            "mpn": (seed.get("mpn") or "") if seed is not None else "",
            "supplier": (seed.get("supplier") or "") if seed is not None else "",
            "missingFacts": list(seed.get("missingFacts") or []) if seed is not None else [],
        }

    out: list[dict] = []
    for part, seed in seed_by_part.items():
        if part in grouped:
            continue  # marked wins; the seed's fields travel on that entry
        out.append({
            "part": part,
            "pins": [],
            "trigger": TRIGGER_FACTS,
            "reason": "；".join(str(reason) for reason in (seed.get("reasons") or [])),
            "dependentFindings": dependent_findings(findings, part),
            "factSeed": True,
            **_seed_fields(seed),
        })
    for part in order:
        pins: list[str] = []
        reasons: list[str] = []
        whole_part = False
        for mark in grouped[part]:
            pin = str(mark.get("pin") or "").strip()
            if not pin:
                whole_part = True
            elif pin not in pins:
                pins.append(pin)
            reason = str(mark.get("reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        seed = seed_by_part.get(part)
        out.append({
            "part": part,
            "pins": [] if whole_part else pins,
            "trigger": TRIGGER_MARKED,
            "reason": "；".join(reasons),
            "dependentFindings": dependent_findings(findings, part),
            "factSeed": seed is not None,
            **_seed_fields(seed),
        })
    return out


# --------------------------------------------------------------------------
# intent — the DesignIntent contract's own section (090 A1)
# --------------------------------------------------------------------------

#: The wording a missing **required** slot is reported with. It is deliberately
#: in `facts-missing`'s family — the drawing compiler's own token for "a fact the
#: compiler needed was not stated" — because it says the same thing about a
#: different consumer: a question the contract owes, never a repair the tool made
#: up. Every line names the slot, the file and the key to write it in.
#:
#: The string itself is imported above from `core.designintent`, its one home
#: since 091 A2a: a *rule* reports the same token now (`rules.params`, when a
#: contradiction has no machine value to take its direction from), and `rules` may
#: not import `engines` (006c's layer table). It stays in this namespace too, which
#: is where the report's own readers import it from.

#: The wording a **hint** is reported with: not a required slot, but a statement
#: the document's own facts say it needs and does not have. The first one is the
#: ROBOT ctrl FOC bias hole (F1) — a bidirectional current-sense signal with no
#: closure declaration. A1 only wires the question; A3 turns it into a rule.
INTENT_HINT_CLOSURE = "closure-undeclared"

#: What the section says about the contract's own posture, once, above the lists.
INTENT_NOTE = (
    "工具只校验与提问，永不改写：本节点名缺哪一句、写进哪个文件哪个键；"
    "填的人是工程师或模型。缺槽**不**抬 verdict（A1 只报告，评级归 A2/A3）——"
    "重生成契约用 `boardwise arch <export> --intent <path>`（已有答案逐字节保留）。"
)

#: What an entry whose provenance is the draft default means for a reader, stated
#: in the section rather than left to the reader's memory of 052 §4.
INTENT_DRAFT_NOTE = (
    "弱词 `ai_asserted` = AI 猜的：它可以当提示，**不许**当作判违规的尺子"
    "（052 §4：未确认的声明只能以明确标注的草稿出门）。"
)


def intent_section(
    *,
    facts: dict | None,
    contract_file: str = "",
    present: bool = False,
    read_error: str = "",
    regenerate: str = "",
    project_uuid: str = "",
    contract_version: int = 0,
) -> dict:
    """The report's `intent` section — what the contract answers and what it owes.

    Built from :func:`boardwise.core.designintent.merge`'s facts, so the section,
    the regenerated file and the rendered view are one arithmetic (the report only
    renders what the JSON says — its own rule since 025). ``missing`` is every slot
    the enumeration owes and the contract does not answer; ``required`` is the
    subset the design doc names as a *must* (a rail's voltage declaration, a
    signal's polarity), and each of those carries its `intent-missing` line.
    ``hints`` is the questions the document asks back.

    `facts` is ``None`` only when nothing could be enumerated *and* no contract was
    read — which the caller reports as an absent section rather than an empty one.
    """
    facts = facts or {}
    missing = list(facts.get("missing") or [])
    required = [row for row in missing if row.get("required")]
    hints = list(facts.get("hints") or [])
    stale = list(facts.get("stale") or [])
    added = list(facts.get("added") or [])
    extras = list(facts.get("extras") or [])
    return {
        "contract": {
            "file": contract_file,
            "present": bool(present),
            "readError": read_error,
            "intentVersion": contract_version,
            "regenerate": regenerate,
        },
        "projectUuid": project_uuid,
        "provenance": str(facts.get("provenance") or ""),
        "draft": bool(facts.get("draft")),
        "draftReasons": list(facts.get("draftReasons") or []),
        "totals": {
            "slots": int(facts.get("slots") or 0),
            "filled": int(facts.get("filled") or 0),
            "missing": len(missing),
            "requiredMissing": len(required),
            "staleEntries": len(stale),
            "addedEntries": len(added),
            "unregisteredAnswers": len(extras),
            "hints": len(hints),
        },
        "missing": missing,
        "required": required,
        "intentMissing": [intent_missing_line(row, contract_file) for row in required],
        "requiredNote": INTENT_MISSING_NOTE,
        "hints": [{**hint, "line": intent_hint_line(hint, contract_file)} for hint in hints],
        "stale": stale,
        "added": added,
        "unregistered": extras,
        "unmapped": list(facts.get("unmapped") or []),
        "note": INTENT_NOTE,
    }


#: What `intent-missing` means, spelled for the reader of report.md.
INTENT_MISSING_NOTE = (
    "`intent-missing`（与 `facts-missing` 同族）：这些是**必填槽**，合同里没有声明；"
    "工具不会替人补，也不会因此拒绝读合同——它只点名缺哪一句、该写进哪个文件哪个键。"
)


def intent_missing_line(row: dict, contract_file: str) -> str:
    """One missing required slot, as the line a reader acts on.

    Names three things (`facts-missing`'s own discipline): **which slot** (with its
    stable id, so a machine can find it), **which file**, and **which key** to
    write. Nothing is invented to fill the gap.
    """
    where = contract_file or "（合同路径见 checkup 的 intent.contract.file）"
    label = f"（{row['label']}）" if row.get("label") else ""
    return (
        f"{INTENT_MISSING}: {row.get('where', '')} 的 `{row.get('key', '')}`{label} 没声明 —— "
        f"写进 `{where}` 的 `{row.get('write', '')}`（槽位 id `{row.get('id', '')}`）；"
        "工具只提问，不改写"
    )


def intent_hint_line(hint: dict, contract_file: str) -> str:
    """One hint, as the line a reader acts on — the F1 wiring's own wording."""
    where = contract_file or "（合同路径见 checkup 的 intent.contract.file）"
    return (
        f"{hint.get('token', INTENT_HINT_CLOSURE)}: {hint.get('where', '')} 缺闭合声明 "
        f"`{hint.get('missing', '')}` —— 写进 `{where}` 的 `{hint.get('write', '')}`；"
        f"{hint.get('why', '')}（提示不阻拦：升级为规则归 A3）"
    )


def render_intent_markdown(lines: list[str], section: dict) -> None:
    """Append the report.md rendering of the `intent` section (090 §三).

    Renders the section's own numbers and lines, in its own order — the
    `report.json` is the contract and the Markdown is what a human reads, so the
    two must not be able to disagree. Long lists are summarised by count with a
    pointer, never truncated silently: every required slot and every hint is
    printed in full, because those are the ones a reader has to act on.
    """
    totals = section.get("totals") or {}
    contract = section.get("contract") or {}
    lines.append(
        f"## 设计意图合同（intent）—— {totals.get('slots', 0)} 槽 / 已填 "
        f"{totals.get('filled', 0)} / 缺 {totals.get('missing', 0)}"
        f"（必填缺 {totals.get('requiredMissing', 0)}）"
    )
    lines.append("")
    path = contract.get("file") or "（未指定）"
    if contract.get("readError"):
        lines.append(f"- 合同：`{path}` —— **读不了**：{contract['readError']}（本次按全 TODO 报告，文件一个字没动）")
    elif contract.get("present"):
        lines.append(f"- 合同：`{path}`（本次读入：槽位与答案以它为准）")
    else:
        lines.append(
            f"- 合同：`{path}` **不存在**（本报告的槽位清单来自当前工程的枚举；"
            "A1 不自动建文件——要生成/重生成契约："
            f"`{contract.get('regenerate') or 'boardwise arch <export> --intent <path>'}`）"
        )
    lines.append(
        f"- 契约版本：`intentVersion {contract.get('intentVersion', 0)}`；"
        f"弱词：`{section.get('provenance') or '（无条目）'}`"
        + ("（**草稿**：" + "；".join((section.get("draftReasons") or [])[:2]) + "）"
           if section.get("draft") else "")
    )
    if section.get("draft"):
        lines.append(f"- {INTENT_DRAFT_NOTE}")
    if totals.get("addedEntries") or totals.get("staleEntries") or totals.get("unregisteredAnswers"):
        lines.append(
            f"- 重生成差量：新增 TODO 条目 {totals.get('addedEntries', 0)} · "
            f"图纸里已消失（stale，不删只标）{totals.get('staleEntries', 0)} · "
            f"枚举已不再问、但合同里还答着的槽 {totals.get('unregisteredAnswers', 0)}"
        )
    lines.append("")
    required = section.get("required") or []
    if required:
        lines.append(f"### 必填槽没声明（{len(required)}）—— `{INTENT_MISSING}`")
        lines.append("")
        lines.append(section.get("requiredNote") or INTENT_MISSING_NOTE)
        lines.append("")
        for row in section.get("intentMissing") or []:
            lines.append(f"- {row}")
        lines.append("")
    hints = section.get("hints") or []
    if hints:
        lines.append(f"### 闭合声明提示（{len(hints)}）")
        lines.append("")
        for hint in hints:
            lines.append(f"- {hint.get('line') or intent_hint_line(hint, contract.get('file') or '')}")
        lines.append("")
    if section.get("stale"):
        lines.append(f"### 合同里记着、图纸里已没有的对象（{len(section['stale'])}，不删只标）")
        lines.append("")
        for entry in section["stale"]:
            lines.append(f"- `{entry.get('object')}`（{entry.get('section')}）—— 值保留，只标 stale")
        lines.append("")
    if totals.get("missing"):
        lines.append(
            f"- 其余 {totals.get('missing', 0) - len(required)} 槽仍是 TODO（欠账不是空白）："
            f"逐槽填进合同（`{path}`），填不出来就**显式问工程师**，不许编。"
        )
    lines.append(f"- {section.get('note', INTENT_NOTE)}")
    lines.append("")


# --------------------------------------------------------------------------
# warning triage (039 批② §WI-2)
# --------------------------------------------------------------------------

#: The verdict vocabulary the AI fills, one of these three and nothing else.
TRIAGE_VERDICTS = ("有益", "有害", "无害")

#: Why the host's ERC warnings arrive without text — measured twice now (025 §0
#: on 2026-09-23, and again by the 039 批② probe on 2026-09-25): the answer is
#: `[{type: 'warn', count: n}]` for *every* page of a project, and the per-item
#: detail lives in the editor's bottom panel, which has no read interface.
ERC_TEXT_UNAVAILABLE = (
    "主机 ERC 只回按 kind 的合计（逐页一致 ⇒ 该计数是 host-wide，不是页内计数）；"
    "逐条文本在编辑器底部面板，连接器没有读取接口（039 批② 真机 probe，"
    "证据 outputs/039c_erc_probe.txt）"
)


def _is_warning_kind(kind: str) -> bool:
    text = (kind or "").lower()
    return "warn" in text


def _leaf_severity(leaf: dict) -> str:
    return str(leaf.get("severity") or "").lower()


def _walk_leafs_with_ref(group: dict, ref: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = [
        (f"{ref}.leafs[{index}]", leaf) for index, leaf in enumerate(group.get("leafs") or [])
    ]
    for index, child in enumerate(group.get("children") or []):
        out.extend(_walk_leafs_with_ref(child, f"{ref}.children[{index}]"))
    return out


def triage_identity(
    target: dict | None,
    refs: list[str] | None,
) -> list[str]:
    """The identity tokens of one `boardwise-rule` slot — structured first.

    Priority (issue #13, 岳's first recommendation): the finding's **structured**
    target (016) before the `refs` heuristic, because the heuristic reads prose
    through an allow-list of prefixes and therefore *leaks* — a finding whose
    evidence is empty and whose designator prefix is not on that list arrives
    with ``refs == []`` and the key degenerates to no identity at all. Measured
    on the real board: `EC1`/`EC3` (prefix `EC` missing) and a board spelled
    `xR67` (the token's prefix reads as `xR`) each produced *ten* findings
    sharing one degenerate key, and one `triage` command then wrote one verdict
    into all of them.

    The shape: ``component_ref`` first (the part the rule is about, in the
    model's own spelling), then the finding's pin refs and net refs, each
    sorted and tagged (``pin:8``, ``net:NET178``) so they cannot be read as
    designators. Everything the rule says structurally is used — a rule that
    reports per pin (``decap-required-caps``) or per net has its pins and nets
    *in the key*, which is what keeps two of its findings on one part apart
    without falling back to the uniqueness suffix. Only a finding with no
    structured identity at all falls back to ``refs`` (the 063 recipe, kept so
    keys that were already unique and stable — `xtal-load-caps:R7` — do not
    move under an existing sidecar).
    """
    target = target if isinstance(target, dict) else {}
    component = str(target.get("component_ref") or "").strip()
    pins = sorted(
        {str(pin).strip() for pin in (target.get("pin_refs") or []) if str(pin).strip()}
    )
    nets = sorted(
        {str(net).strip() for net in (target.get("net_refs") or []) if str(net).strip()}
    )
    if component:
        return [component, *[f"pin:{pin}" for pin in pins], *[f"net:{net}" for net in nets]]
    if pins or nets:
        return [*[f"pin:{pin}" for pin in pins], *[f"net:{net}" for net in nets]]
    return [str(ref) for ref in (refs or [])]


def triage_key(
    entry: dict,
    *,
    label: str = "",
    rule_id: str = "",
    refs: list[str] | None = None,
    target: dict | None = None,
) -> str:
    """The stable identity of one `warning_triage[]` slot — what the sidecar matches on.

    One recipe per source (063 §1), because a warning is identified by different
    things depending on where the report learned about it:

    * ``host-erc:<severity>`` — the host's counts have no per-item identity
      beyond their kind, so the kind *is* the identity;
    * ``pcb-drc:<severity>:<label>:<net>`` — a leaf is identified by its rule
      name (``ruleName``/``errorType``) and the net it names, which is what
      stays put when the explanation text or the leaf order moves;
    * ``boardwise-rule:<rule_id>:<identity>`` — a finding is identified by the
      structured ``target`` when it has one, and by the designators its prose
      names when it does not (see :func:`triage_identity`, issue #13).

    ``label``, ``rule_id``, ``refs`` and ``target`` are the ingredients the
    **source** data carries and the slot itself does not (its public shape is
    unchanged — 063 §1 adds `key` and nothing else), so the generator hands them
    over. Computed **once**, here, and then stamped onto the slot: the merge and
    the `triage` command read ``entry["key"]`` and never recompute it, which is
    what keeps a key from drifting away from the row it names.
    """
    source = str(entry.get("source") or "")
    severity = str(entry.get("severity") or "")
    if source == "host-erc":
        return f"host-erc:{severity}"
    if source == "pcb-drc":
        net = str((entry.get("attribution") or {}).get("net") or "")
        return ":".join(("pcb-drc", severity, label, net))
    if source == "boardwise-rule":
        return f"boardwise-rule:{rule_id}:{','.join(triage_identity(target, refs))}"
    # A source this batch does not know about (a future slot maker): its own
    # source and text still make a unique, stable key rather than a silent
    # collision with the finding recipe above.
    return ":".join((source or "(no source)", severity, str(entry.get("text") or "")))


#: What the uniqueness pass appends to the 2nd, 3rd … slot that still shares an
#: identity after every structured field has been used: `…#2`, `…#3`. Plain and
#: deterministic on purpose — the same board re-run produces the same keys, so a
#: verdict written against `…#2` lands on it again (issue #13).
TRIAGE_KEY_SUFFIX = "#"


def triage_order(slot: dict, target: dict | None) -> tuple[str, str, str, str]:
    """The **stable** sort key the uniqueness pass orders colliding slots by.

    Issue #13, 岳's third recommendation: a collision must not be silent, and
    the suffix that resolves it must be a function of the input alone — so the
    order is the finding's own structured identity first (`component_ref`,
    `pin_refs`, `net_refs` — the same fields :func:`triage_identity` reads) and
    the slot's text last, which is what separates two host/PCB rows that share a
    key. Rows that tie on all four keep their report order (``sorted`` is
    stable), so the ordering is total for any input.
    """
    target = target if isinstance(target, dict) else {}
    return (
        str(target.get("component_ref") or ""),
        ",".join(sorted(str(pin) for pin in (target.get("pin_refs") or []))),
        ",".join(sorted(str(net) for net in (target.get("net_refs") or []))),
        str(slot.get("text") or ""),
    )


def disambiguate_triage_keys(
    pending: list[tuple[str, tuple[str, str, str, str], dict]],
) -> tuple[list[dict], list[str]]:
    """``(slots, collided_keys)`` — suffix the slots that still share a key.

    063 made a key the slot's identity; #13 measured what happens when two slots
    claim the same one: they are one warning as far as `boardwise triage` can
    tell, so a single verdict is written into both. The structured identity
    (:func:`triage_identity`) removes the collisions this codebase can see
    coming; this pass is the **assertion** that none is left, and it is loud
    rather than silent either way — the returned ``collided_keys`` are what the
    report's own `notes` say out loud (issue #13: 撞车曾是 bug，不许再静默).

    ``pending`` is ``[(key, order, slot), …]`` in report order, ``order`` from
    :func:`triage_order`. The first slot of a colliding group keeps the plain
    key and the rest get ``#2``/``#3`` … in that stable order; the slot dicts
    handed in are not mutated.
    """
    groups: dict[str, list[int]] = {}
    for index, (key, _order, _slot) in enumerate(pending):
        groups.setdefault(key, []).append(index)

    slots = [slot for _key, _order, slot in pending]
    collided: list[str] = []
    for key, indices in groups.items():
        if len(indices) < 2:
            continue
        collided.append(key)
        ordered = sorted(indices, key=lambda index: pending[index][1])
        for position, index in enumerate(ordered[1:], start=2):
            slots[index] = {**slots[index], "key": f"{key}{TRIAGE_KEY_SUFFIX}{position}"}
    return slots, sorted(collided)


def disambiguated_triage_keys(slots: list[dict]) -> list[str]:
    """The base keys :func:`disambiguate_triage_keys` had to suffix, sorted.

    Read back off the generated slots so the caller can put the collision in the
    report's `notes` without threading a second return value through
    :func:`warning_triage_slots` (whose list-of-slots return is a contract).
    """
    bases: list[str] = []
    for slot in slots:
        key = str(slot.get("key") or "")
        base, separator, tail = key.rpartition(TRIAGE_KEY_SUFFIX)
        if separator and base and tail.isdigit() and base not in bases:
            bases.append(base)
    return sorted(bases)


def warning_triage_slots(
    *,
    model: DesignModel,
    drc: dict,
    findings: list[dict],
    modules: list[dict],
) -> list[dict]:
    """The `warning_triage` slots: one row per warning the report knows about.

    Three sources, because the report learns about warnings three ways, and each
    one can say something different:

    * **host ERC** (`drc.schematic`) — counts per kind, host-wide, no text. One
      row per warning kind, `text` empty and `textUnavailable` saying why;
    * **PCB DRC leaves** (`drc.pcb.groups`) — real per-item text and often a net,
      so the module attribution is *measured* where the data allows it;
    * **boardwise findings** with severity `WARN` — full text plus refs, so the
      module attribution is exact.

    What the rule engine was told is left `""`: `verdict` (one of
    :data:`TRIAGE_VERDICTS`) and `reason` are the AI's to fill, per xianyuyijinban's step ②.

    Every row carries a `key` (:func:`triage_key`, 063 §1): the row's stable
    identity, so `boardwise triage` can write a verdict back into it and
    `checkup` can put that verdict back after a re-run (issue #12: the slots were
    the one AI channel with no way back in). The key is computed here and never
    recomputed — a re-generated slot that keeps its key keeps its verdict.

    **No two rows leave here with the same key** (issue #13). The finding recipe
    reads the structured target first (:func:`triage_identity`) so the collision
    the issue measured — two `param-value-mpn-match` findings on `EC1`/`EC3`
    sharing one degenerate key, one `triage` command writing into both — cannot
    be built; whatever identity is still duplicated after that (two PCB leaves
    of one rule on no net, genuinely identical rows) goes through
    :func:`disambiguate_triage_keys`, which suffixes `#2`/`#3` in a stable order
    instead of letting two judgements become one. Callers put the collision in
    the report's `notes` via :func:`disambiguated_triage_keys`.
    """
    module_of: dict[str, str] = {}
    for module in modules:
        for designator in module.get("components") or []:
            module_of.setdefault(designator, module.get("name", ""))
    net_modules: dict[str, str] = {}
    for name, net in (_model_nets(model) or {}).items():
        for designator, _pin in net.pins:
            module = module_of.get(designator)
            if module:
                net_modules.setdefault(name, module)

    pending: list[tuple[str, tuple[str, str, str, str], dict]] = []

    def add_row(key: str, slot: dict, target: dict | None = None) -> None:
        """One row, with the two things the row itself does not carry: its key
        (stamped, never recomputed) and the sort order the uniqueness pass needs."""
        pending.append((key, triage_order(slot, target), {"key": key, **slot}))

    schematic = drc.get("schematic") or {}
    if schematic.get("checked") and not schematic.get("countsKnown") is False:
        # The per-kind counts live under `totals` in the section `drc.py` builds
        # (`counts` is the *per-page* array); falling back keeps this working if a
        # future section carries the flat map under the other name.
        per_kind = schematic.get("totals") or schematic.get("counts") or {}
        for kind, count in sorted(per_kind.items()):
            if not _is_warning_kind(kind):
                continue
            slot = {
                "source": "host-erc",
                "severity": kind,
                "count": count,
                "text": "",
                "textUnavailable": ERC_TEXT_UNAVAILABLE,
                "attribution": {"scope": "host-wide", "page": None, "module": None},
                "verdict": "",
                "reason": "",
                "evidence": [
                    f"drc.schematic.totals[{kind!r}] = {count}",
                    f"pagesChecked={schematic.get('pagesChecked')}, "
                    f"countsBasis={schematic.get('countsBasis')}",
                ],
            }
            add_row(triage_key(slot), slot)
    pcb = drc.get("pcb") or {}
    for group in pcb.get("groups") or []:
        for ref, leaf in _walk_leafs_with_ref(group, f"drc.pcb.groups[{group.get('index')}]"):
            severity = _leaf_severity(leaf)
            if severity and not _is_warning_kind(severity):
                continue  # an error stays an error: the errors section owns it
            net = str(leaf.get("net") or "")
            label = leaf.get("ruleName") or leaf.get("errorType") or "(no rule name)"
            explanation = str(leaf.get("explanation") or "")
            slot = {
                "source": "pcb-drc",
                "severity": severity or "unknown",
                "severitySource": leaf.get("severitySource") or "",
                "count": 1,
                "text": f"{label}：{explanation}" if explanation else str(label),
                "textUnavailable": "",
                "attribution": {
                    "scope": "leaf",
                    "page": None,
                    "net": net,
                    "module": net_modules.get(net) if net else None,
                },
                "verdict": "",
                "reason": "",
                "evidence": [ref, f"globalIndex={leaf.get('globalIndex')}"],
            }
            add_row(triage_key(slot, label=str(label)), slot)
    for index, finding in enumerate(findings):
        if str(finding.get("severity") or "").upper() != "WARN":
            continue
        refs = [str(ref) for ref in (finding.get("refs") or [])]
        target = finding.get("target")
        module = next((module_of[ref] for ref in refs if ref in module_of), None)
        slot = {
            "source": "boardwise-rule",
            "severity": "WARN",
            "count": 1,
            "text": str(finding.get("message") or ""),
            "textUnavailable": "",
            "attribution": {
                "scope": "finding",
                "page": None,
                "net": "",
                "module": module,
            },
            "verdict": "",
            "reason": "",
            "evidence": [f"findings[{index}] rule {finding.get('rule_id')}", *refs],
        }
        add_row(
            triage_key(
                slot, rule_id=str(finding.get("rule_id") or ""), refs=refs, target=target
            ),
            slot,
            target,
        )
    slots, _collided = disambiguate_triage_keys(pending)
    return slots


def merge_triage_sidecar(
    slots: list[dict], entries: list[dict] | None
) -> tuple[list[dict], int, int]:
    """Put the sidecar's verdicts back onto freshly generated `warning_triage[]` slots.

    Returns ``(slots, merged, unmatched)``. This is the answer to issue #12's
    second half: the slots are regenerated from the board on every `checkup`, so
    what the AI decided about a warning is *not* derivable and has to be kept
    beside the report (`warning-triage.json`) and folded back in here. Matching is
    by ``key`` alone (063 §2 — `source`/`text` are in the sidecar so a human can
    read it, never to match on), and a slot that keeps its key keeps its verdict.

    ``merged`` counts the entries that actually carried a verdict and landed on a
    slot; ``unmatched`` counts the sidecar's entries whose key has no slot this
    time — a warning that disappeared, or one the tinkerer renamed. Those are
    **reported, never deleted**: the sidecar is the audit trail of what was
    judged, and a re-run of `checkup` is not the place to forget a judgement. An
    entry whose verdict is empty counts as neither: its key landed, but there is
    no decision in it to fold in.
    """
    by_key: dict[str, dict] = {}
    for slot in slots:
        key = str(slot.get("key") or "")
        if key:
            by_key.setdefault(key, slot)

    decisions: dict[str, dict] = {}
    unmatched = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            unmatched += 1
            continue
        key = str(entry.get("key") or "")
        if not key or key not in by_key:
            unmatched += 1
            continue
        if not str(entry.get("verdict") or "").strip():
            continue  # a row with no decision is not one to put back
        decisions[key] = entry

    out: list[dict] = []
    for slot in slots:
        entry = decisions.get(str(slot.get("key") or ""))
        verdict = str((entry or {}).get("verdict") or "").strip()
        if entry is None or not verdict:
            out.append(slot)
            continue
        out.append({
            **slot,
            "verdict": verdict,
            "reason": str(entry.get("reason") or "").strip(),
        })
    return out, len(decisions), unmatched


def order_modules_by_warnings(
    modules: list[dict], findings: list[dict]
) -> list[dict]:
    """「警告所在模块优先」— warning-bearing modules first, rest in place.

    The order is stable and the count is written onto each module
    (`warningFindings`), so the reordering is checkable rather than a vibe. Only
    *attributable* warnings can move a module: the host's ERC counts are
    host-wide with no items (measured — see :data:`ERC_TEXT_UNAVAILABLE`), so a
    report where those are the only warnings keeps the grouping's own order and
    says so.
    """
    ordered: list[dict] = []
    for module in modules:
        warning_indices = [
            index
            for index in module.get("findings") or []
            if index < len(findings)
            and str(findings[index].get("severity") or "").upper() == "WARN"
        ]
        ordered.append({**module, "warningFindings": warning_indices})
    with_warnings = [module for module in ordered if module["warningFindings"]]
    without = [module for module in ordered if not module["warningFindings"]]
    return [*with_warnings, *without]


# --------------------------------------------------------------------------
# layout aesthetics (039 批② §WI-3) — off unless the switch says otherwise
# --------------------------------------------------------------------------

#: The five axes, the same ruler the roadmap's M2 drawing-readability rubric
#: uses: review data today is the yardstick for generated drawings tomorrow.
LAYOUT_AXES: tuple[tuple[str, str, str], ...] = (
    ("topology", "拓扑可辨", "一眼能不能看出这块电路在做什么、各个功能块在哪里"),
    ("flow", "流向明确", "电源/信号是否有一个清楚的方向，有没有说不清的回头线"),
    ("text", "文字可读", "位号、数值、注释够不够大、清不清楚，有没有重叠或被线压住"),
    ("grouping", "分组合理", "同一功能的器件是否聚在一起，模块之间有没有留白与边界"),
    ("netlabels", "网络标识规范", "关键网络有没有可读的标签、命名是否一致，地与电源是否用符号而不是长线"),
)

LAYOUT_SCALE = "1–5 分（1 = 不可读，5 = 清晰）；只评「看得懂」，不评电气正确性"

LAYOUT_VISION_RULE = (
    "本节必须由具备视觉判断力的模型填写。模型不具备时，把 skipped 写成理由、五轴 score 保持 "
    "null —— 禁止编分数：弱模型假装看出好坏比不评更害人。"
)


def layout_review_section(*, source: str, pages: list[dict]) -> dict:
    """The `layout_review` section, present **only when the switch is on**.

    The CLI leaves every axis empty on purpose (`score: null`, `evidence: ""`):
    the numbers are the model's judgement, and what the tool contributes is the
    ruler, the pages to look at, and the discipline about not inventing scores.
    """
    return {
        "enabled": True,
        "source": source,
        "scale": LAYOUT_SCALE,
        "axes": [
            {"key": key, "name": name, "question": question, "score": None, "evidence": ""}
            for key, name, question in LAYOUT_AXES
        ],
        "pages": [
            {
                "page": page.get("page") or page.get("pageUuid") or "",
                "file": page.get("file") or "",
                "bytes": page.get("bytes"),
                **({"error": page.get("error")} if page.get("error") else {}),
            }
            for page in pages
        ],
        "visionRequired": LAYOUT_VISION_RULE,
        "skipped": None,
        "note": (
            "五轴与路线图 M2 的绘制可读性标尺同一把尺：今天的审查数据就是将来生成绘制的评测标尺。"
            "评分是给用户看的体检结论，不是投板门禁。"
        ),
    }


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

【本报告依赖的未知项】（needs_datasheet；**这一节空着才允许写"通过"**）
  - <位号/管脚>：<为什么解释不了> —— 需要：<哪份手册的哪一节，或找谁要>
  - 清单非空时，依赖它的条目只能写「无法确认（等资料）」，不许写「通过/不符合」

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
    Chinese, because the reader is xianyuyijinban (and the model, which fills the summary
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
    # The conclusion is the *report's own*, computed where the sections were
    # built (039 批②): when parts are unreviewed it says exactly that, and
    # nothing on that line claims a pass.
    verdict = summary.get("conclusion") or (
        "无 ERROR" if not errors else f"{errors} 项 ERROR"
    )
    if summary.get("countsIncomplete") and "计数不完整" not in verdict:
        verdict += "（计数不完整：有主机答复不能枚举）"

    project = source.get("project") or {}
    title = project.get("friendlyName") or project.get("name") or source.get("file") or "(unknown)"
    boards = model.get("boards") or []
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
    ]
    if len(boards) > 1:
        # 040b: the totals above are sums over the boards; without this line
        # "155 器件" would read as one netlist's worth.
        lines.append(
            "- 板："
            + "、".join(
                f"`{board['title']}`（{len(board['pages'])} 页 / "
                f"{board['components']} 器件 / {board['nets']} 网）"
                for board in boards
            )
        )
    lines.append("")
    if source.get("notes"):
        lines.append("> " + "；".join(str(note) for note in source["notes"]))
        lines.append("")

    # --- 053 §2.2: the complete statement first, because it is the answer to the
    # one question a reader has ("is this done?"), and because 052 §2.2 measured
    # that `summary.mayClaimPassed` was being read as exactly that answer.
    completion = report.get("completion") or {}
    if completion:
        scope = completion.get("scope") or {}
        architecture_slots = completion.get("architectureSlots") or {}
        versions = completion.get("sourceVersions") or {}
        coverage = completion.get("coverage") or {}
        lines.append("## 完成状态（completion）")
        lines.append("")
        lines.append(
            f"**verdict：`{completion.get('verdict')}`**"
            + ("（" + "；".join(completion.get("verdictWhy") or []) + "）"
               if completion.get("verdictWhy")
               else "（无 ERROR、无未审、无 stale、无待分诊、无覆盖缺口）")
        )
        lines.append("")
        lines.append(
            f"- 检查范围：{scope.get('rules', '?')} 条规则 / {scope.get('boards', '?')} 块板"
            f" / {scope.get('pages', '?')} 页"
        )
        lines.append(
            f"- 欠账：ERROR {completion.get('errors', 0)} · 未审器件 "
            f"{completion.get('unreviewedParts', 0)} · 待分诊 warning "
            f"{completion.get('warningsPendingTriage', 0)} · 架构槽位 stale "
            f"{architecture_slots.get('stale', 0)}（槽位 {architecture_slots.get('total', 0)}，"
            f"已填 {architecture_slots.get('filled', 0)}，TODO {completion.get('openTodos', 0)}）"
        )
        # #30's gate, rendered from the section's own numbers — `render only what
        # the JSON says`, and absent (not "all clean") when the section is older
        # than the gate and has no `coverage` key at all.
        if coverage:
            lines.append(
                "- 覆盖：解析"
                + ("不完整" if coverage.get("parseIncomplete") else "完整")
                + ("（空模型：归档读不出内容）" if coverage.get("modelEmpty") else "")
                + f" · 少页 {coverage.get('pagesDropped', 0)}"
                # 132 (#30⑥): board-level empty boards, named like the JSON does.
                + (
                    f" · 空板 {coverage.get('boardsEmpty', 0)}"
                    + (
                        "（" + "、".join(coverage.get("boardsEmptyNames") or []) + "）"
                        if coverage.get("boardsEmptyNames") else ""
                    )
                    if coverage.get("boardsEmpty") else ""
                )
                + f" · 规则 withheld 结论 {coverage.get('rulesRefused', 0)}"
                + f" · 解析丢弃记录 {coverage.get('recordsDropped', 0)}"
                + f" · 规则报错 {len(coverage.get('rulesErrored') or [])}"
                + (
                    "（" + "、".join(coverage.get("rulesErrored") or []) + "）"
                    if coverage.get("rulesErrored") else ""
                )
                # 126d: rendered from the section's own number like every other
                # coverage field, and absent (not "clean") when the section is
                # older than the gate. It is worded as its own item rather than
                # folded into the line above because it is the one coverage field
                # that gates `incomplete` rather than `complete-with-open-items`.
                + (" · **PCB 版面未审（pcbReviewMissing）**"
                   if coverage.get("pcbReviewMissing") else "")
            )
        lines.append(
            f"- 源版本：ruleset `{versions.get('ruleset', '?')}` · rulebody "
            f"`{versions.get('rulebody') or 'unavailable (frozen, no source)'}`"
        )
        lines.append(
            "- 注意：`summary.mayClaimPassed` 是**窄义**字段（只回答「有没有器件缺手册未审」）；"
            "完整结论以本节的 `verdict` 为准。"
        )
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

    # --- the datasheet gate: what could not be reviewed at all (039 批② §WI-1).
    unreviewed = report.get("unreviewed_parts") or []
    lines.append(f"## 未审器件（{len(unreviewed)}）")
    lines.append("")
    if not unreviewed:
        lines.append("无：每个器件都有货架事实或身份信息，规则能判。")
    else:
        lines.append(
            "本节非空时**不得宣称审查通过**：只能说 DRC/连接性已审，"
            f"{len(unreviewed)} 颗器件缺手册未审。三通道（工程师给 / 立创找 / 官网搜）逐条列在下面。"
        )
        lines.append("")
        lines.append("| 位号 | MPN | 供应商 | 缺哪些 fact | 工程师给 | 立创找 | 官网搜 |")
        lines.append("|---|---|---|---|---|---|---|")
        for part in unreviewed:
            channels = part.get("channels") or {}
            lines.append(
                f"| {_cell(part.get('designator'))} | {_cell(part.get('mpn'))} "
                f"| {_cell(part.get('supplier'))} "
                f"| {_cell('、'.join(part.get('missingFacts') or []) or '—')} "
                f"| {_channel_cell(channels.get('engineer'))} "
                f"| {_channel_cell(channels.get('lcsc'))} "
                f"| {_channel_cell(channels.get('official'))} |"
            )
        lines.append("")
        for part in unreviewed:
            channels = part.get("channels") or {}
            official = (channels.get("official") or {}).get("suggestedQueries") or []
            if official:
                lines.append(
                    f"- `{part.get('designator')}` 官网通道建议查询词："
                    + "；".join(f"`{query}`" for query in official)
                )
        lines.append("")
        lines.append(f"每个器件问同一件事：{UNKNOWN_PART_QUESTION}")
    lines.append("")

    # --- 058 ⓪: what the report still depends on. It sits right after 未审器件
    # because it *contains* that section (the facts trigger) plus the reviewer's
    # own marks, and because its fixed first line is a gate the reader must meet
    # before the DRC tables below. Existing sections keep their order and wording.
    needs = report.get("needs_datasheet") or []
    facts_rows = [entry for entry in needs if entry.get("trigger") == TRIGGER_FACTS]
    marked_rows = [entry for entry in needs if entry.get("trigger") == TRIGGER_MARKED]
    lines.append(
        f"## 本报告依赖的未知项（needs_datasheet：facts {len(facts_rows)} 条 / "
        f"审查者标记 {len(marked_rows)} 项）"
    )
    lines.append("")
    if not needs:
        lines.append(
            "无：没有规则判不了的器件，也没有审查者标记的未知管脚。本节为空，"
            "报告才有资格谈「通过」——完整的结论仍以 `completion.verdict` 为准。"
        )
    else:
        lines.append(NEEDS_DATASHEET_BLOCK)
        lines.append("")
        if facts_rows:
            lines.append(f"### facts 触发（规则判不了的器件，{len(facts_rows)} 条）")
            lines.append("")
            lines.append(
                "| 位号 | MPN | 供应商 | 缺哪些 fact | 为什么在清单上 | 依赖的 findings "
                "| 工程师给 | 立创找 | 官网搜 |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|")
            for entry in facts_rows:
                channels = entry.get("channels") or {}
                lines.append(
                    f"| {_cell(entry.get('part'))} | {_cell(entry.get('mpn'))} "
                    f"| {_cell(entry.get('supplier'))} "
                    f"| {_cell('、'.join(entry.get('missingFacts') or []) or '—')} "
                    f"| {_cell(entry.get('reason') or '—')} "
                    f"| {_cell('、'.join(entry.get('dependentFindings') or []) or '—')} "
                    f"| {_channel_cell(channels.get('engineer'))} "
                    f"| {_channel_cell(channels.get('lcsc'))} "
                    f"| {_channel_cell(channels.get('official'))} |"
                )
            lines.append("")
        if marked_rows:
            lines.append(f"### 审查者标记（读不懂的管脚，{len(marked_rows)} 项）")
            lines.append("")
            lines.append(
                "| 位号 | 管脚 | 为什么解释不了 | 依赖的 findings "
                "| 工程师给 | 立创找 | 官网搜 |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for entry in marked_rows:
                channels = entry.get("channels") or {}
                pins = "、".join(str(pin) for pin in (entry.get("pins") or []))
                lines.append(
                    f"| {_cell(entry.get('part'))} | {_cell(pins or '（整颗器件）')} "
                    f"| {_cell(entry.get('reason') or '（没写理由）')} "
                    f"| {_cell('、'.join(entry.get('dependentFindings') or []) or '—')} "
                    f"| {_channel_cell(channels.get('engineer'))} "
                    f"| {_channel_cell(channels.get('lcsc'))} "
                    f"| {_channel_cell(channels.get('official'))} |"
                )
            lines.append("")
            lines.append(MARKED_ENTRY_NOTE)
            lines.append("")
        lines.append(
            "同一器件两源命中时按 marked 展示（该条 `factSeed: true`），计数只算一次；"
            f"每个器件问同一件事：{UNKNOWN_PART_QUESTION}"
        )
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

    # 123: the rule set the DRC above was measured against. Rendered right after
    # the DRC sections and not at the end, because it is the premise those
    # sections' conclusions rest on — a leaf count with no rule set is half an
    # answer, and the reader should meet the rule before the verdict.
    ruleset = drc.get("ruleset") or {}
    lines.append("")
    if not ruleset.get("checked"):
        lines.append(f"- PCB DRC 规则集：**未读** —— {ruleset.get('reason')}")
    else:
        lines.append(
            f"- PCB DRC 规则集：`{ruleset.get('ruleSetName') or '(unnamed)'}`"
            + (f"（默认 `{ruleset.get('defaultRuleSetName')}`）" if ruleset.get("defaultRuleSetName") else "")
            + (f"，实时 DRC {'开着' if ruleset.get('realTimeDrcStatus') else '未开'}")
        )
        lines.append(
            f"  - 大类：{'、'.join(ruleset.get('ruleset', {}).get('configCategories') or []) or '（读不到）'}"
        )
        audit = ruleset.get("metaAudit") or {}
        if audit.get("available") is not True:
            lines.append(f"  - 元审查：**没有跑** —— {audit.get('reason')}")
        else:
            lines.append(
                f"  - 元审查：{audit.get('keysChecked')} 键 —— "
                f"匹配 {audit.get('within')}、超界 {audit.get('outside')}、"
                f"偏离（无害侧）{audit.get('offReference')}、**没读到 {audit.get('unreadable')}**"
                f"（参考表 `{audit.get('referenceFile')}`）"
            )
            if audit.get("missingCategories"):
                lines.append(
                    f"  - 少的大类：{'、'.join(audit['missingCategories'])}"
                    "（不是「这些类别没有规则」，是这份读数可能不完整）"
                )
            rows = [c for c in (audit.get("checks") or []) if c.get("status") != "within"]
            if rows:
                lines.append("")
                lines.append("| 键 | 读到的 | 参考值 | 差 | 状态 | 说明 |")
                lines.append("|---|---|---|---|---|---|")
                for entry in rows:
                    unit = entry.get("unit") or ""
                    actual = entry.get("actual")
                    actual_text = "（没读到）" if actual is None else f"{actual}{unit}"
                    expected = entry.get("expected")
                    expected_text = "—" if expected is None else f"{expected}{unit}"
                    lines.append(
                        f"| {_cell(entry.get('label'))} "
                        f"| {_cell(actual_text)} "
                        f"| {_cell(expected_text)} "
                        f"| {_cell(entry.get('delta'))} | {_cell(entry.get('status'))} "
                        f"| {_cell(entry.get('why') or entry.get('note') or entry.get('whyUnreadable'))} |"
                    )
                lines.append("")
    for note in ruleset.get("notes") or []:
        lines.append(f"  - {note}")
    lines.append("")

    lines.append("## 模块")
    lines.append("")
    if not modules:
        lines.append("（没有可分组的结构。）")

    def _render_module(module: dict, heading: str) -> None:
        components = "、".join(module.get("components") or []) or "（无）"
        lines.append(f"{heading} {module.get('name')}（{len(module.get('components') or [])} 器件）")
        lines.append("")
        lines.append(f"- 依据：{module.get('basis')}")
        if len(boards) > 1 and module.get("board"):
            lines.append(f"- 板：{module['board']}")
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

    if len(boards) > 1:
        # Per board first (040b §WI-4): a project's modules never mix boards, and
        # the heading is what says so.
        for board in boards:
            lines.append(f"### {board['title']}")
            lines.append("")
            for module in modules:
                if module.get("board") == board["title"]:
                    _render_module(module, "####")
    else:
        for module in modules:
            _render_module(module, "###")

    lines.append(f"## 规则 findings（{len(findings)}）")
    lines.append("")
    if not findings:
        lines.append("无。")
    else:
        chains = _report_chains(report)
        if any(row["missing"] for row in chains):
            # A gap in the chain is a fact about the reading, not a formatting
            # choice: the `page` link is absent on tiers that carry no page
            # information **and** on PCB-side findings (a board of the layout has
            # no schematic page), and any *other* missing link means this run
            # could not say where the problem is. Either way the reader is told
            # here rather than left to notice an empty cell (issue #69 条 1).
            gaps: dict[str, int] = collections.Counter(
                link for row in chains for link in row["missing"]
            )
            tally = "、".join(f"{link} {gaps[link]} 条" for link in sorted(gaps))
            # The parenthetical says *why* the page link is often the missing one, so
            # the reader does not read 「缺 page」 as a defect of the run: a PCB
            # finding is about a board of the layout, which has no schematic page.
            because = (
                "（这一档的模型不带页信息、或该 finding 属于 PCB 板——板面没有原理图页）"
                if set(gaps) == {"page"} else ""
            )
            lines.append(
                f"> 有 {sum(1 for row in chains if row['missing'])}/{len(chains)} 条 finding "
                "的定位链不完整，缺的那一环在表里写成「未标注」——逐条看得见，不静默省略。"
                f"本次缺：{tally}{because}"
            )
            lines.append("")
        if len(boards) > 1:
            # One extra column when the project has more than one board: a finding's
            # board is otherwise only in the JSON, and a reader scanning the table
            # cannot tell Board1's `U2` finding from Board3's.
            lines.append("| # | 级别 | 规则 | 板 | 位号 | 定位链 | 说明 |")
            lines.append("|---|---|---|---|---|---|---|")
            for index, finding in enumerate(findings):
                lines.append(
                    f"| {index} | {_cell(finding.get('severity'))} | {_cell(finding.get('rule_id'))} "
                    f"| {_cell(finding.get('board'))} "
                    f"| {_cell('、'.join(finding.get('refs') or []))} "
                    f"| {_cell(chain_text(chains[index]))} | {_cell(finding.get('message'))} |"
                )
        else:
            lines.append("| # | 级别 | 规则 | 位号 | 定位链 | 说明 |")
            lines.append("|---|---|---|---|---|---|")
            for index, finding in enumerate(findings):
                lines.append(
                    f"| {index} | {_cell(finding.get('severity'))} | {_cell(finding.get('rule_id'))} "
                    f"| {_cell('、'.join(finding.get('refs') or []))} "
                    f"| {_cell(chain_text(chains[index]))} | {_cell(finding.get('message'))} |"
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

    # --- xianyuyijinban's step ②: the triage slots (039 批② §WI-2).
    triage = report.get("warning_triage") or []
    lines.append(f"## 警告分诊（{len(triage)}）")
    lines.append("")
    if not triage:
        lines.append("没有需要分诊的警告（主机 ERC 无 warn 计数、PCB DRC 无 warn 级叶子、规则无 WARN）。")
    else:
        lines.append(
            "逐条填 `verdict`（" + " / ".join(TRIAGE_VERDICTS) + "）与 `reason`（xianyuyijinban的审查三步之②）："
            "用 `boardwise triage --out <本目录> --key <key> --verdict "
            + "|".join(TRIAGE_VERDICTS) + " --reason …` 写回（key 见下表，它是这条警告的身份；"
            "判决同时写进 `warning-triage.json`，所以重跑 `checkup` 不会丢）。"
            "主机 ERC 的条目**没有逐条文本**——它的答复只有按 kind 的合计（见 drc.schematic），"
            "逐条详情在编辑器底部面板且没有读取接口。"
        )
        lines.append("")
        lines.append("| # | key | 来源 | 级别 | 计数 | 归属模块 | 文本 | verdict | 理由 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for index, entry in enumerate(triage):
            attribution = entry.get("attribution") or {}
            module = attribution.get("module") or (
                "（host-wide，无逐条归属）" if attribution.get("scope") == "host-wide" else "—"
            )
            text = entry.get("text") or f"（无逐条文本：{entry.get('textUnavailable', '')}）"
            lines.append(
                f"| {index} | {_cell(entry.get('key'))} | {_cell(entry.get('source'))} "
                f"| {_cell(entry.get('severity'))} "
                f"| {_cell(entry.get('count'))} | {_cell(module)} | {_cell(text)} "
                f"| {_cell(entry.get('verdict') or '（待填）')} | {_cell(entry.get('reason') or '（待填）')} |"
            )
    lines.append("")

    layout = report.get("layout_review")
    if layout:
        lines.append("## 布局审美（五轴，1–5 分）")
        lines.append("")
        lines.append(f"- 开关：on（来源 `{layout.get('source')}`）—— {layout.get('scale')}")
        lines.append(f"- 纪律：{layout.get('visionRequired')}")
        if layout.get("skipped"):
            lines.append(f"- **本模型跳过**：{layout['skipped']}")
        lines.append("")
        lines.append("| 轴 | 问题 | 分数 | 证据 |")
        lines.append("|---|---|---|---|")
        for axis in layout.get("axes") or []:
            lines.append(
                f"| {_cell(axis.get('name'))} | {_cell(axis.get('question'))} "
                f"| {_cell(axis.get('score') if axis.get('score') is not None else '（待填）')} "
                f"| {_cell(axis.get('evidence') or '（待填）')} |"
            )
        pages = layout.get("pages") or []
        lines.append("")
        lines.append(f"- 逐页画布图（{len(pages)}）：" + (
            "、".join(
                f"[{page.get('page') or '?'}]({page['file']})" if page.get("file")
                else f"{page.get('page') or '?'}（{page.get('error') or '无图'}）"
                for page in pages
            ) or "无"
        ))
        lines.append(f"- {layout.get('note', '')}")
        lines.append("")

    # --- 044 M1 / 053 §2.2: the merged view (skeleton ⊕ design intent). The
    # skeleton file is generated and cannot be filled by hand; the answers live in
    # `design-intent.md`, and this section is where a reader sees them together
    # with the `stale` marks the drawing change produced.
    architecture = report.get("architecture") or {}
    if architecture:
        intent = architecture.get("intent") or {}
        arch_slots = architecture.get("slots") or []
        arch_totals = architecture.get("totals") or {}
        filled_rows = [slot for slot in arch_slots if slot.get("filled") or slot.get("stale")]
        lines.append(f"## 架构骨架 ⊕ 设计意图（合并视图）—— {len(arch_slots)} 槽")
        lines.append("")
        lines.append(f"- 骨架：`{architecture.get('file')}`（自动生成，手填无效）")
        lines.append(
            f"- 设计意图：`{intent.get('file')}`（工程师所有，生成器只读）——"
            + ("本次读入并合并" if intent.get("present")
               else "本次不存在，已建全 TODO 模板")
            + f"；projectUuid `{intent.get('projectUuid', '')}`"
        )
        lines.append(
            f"- 槽位：合计 {arch_totals.get('slots', 0)} / 已填 {arch_totals.get('filled', 0)} / "
            f"**stale {arch_totals.get('stale', 0)}** / 待填 {arch_totals.get('todoSlots', 0)}"
        )
        lines.append(
            f"- 骨架计数：{arch_totals.get('rails', 0)} 轨 / {arch_totals.get('analogChains', 0)} 模拟链 / "
            f"{arch_totals.get('controlChains', 0)} 控制链 / {arch_totals.get('buses', 0)} 总线类"
        )
        if filled_rows:
            stale_count = arch_totals.get("stale", 0)
            lines.append("")
            lines.append("| 槽位 | 值 | 来源 | 状态 |")
            lines.append("|---|---|---|---|")
            for slot in filled_rows:
                if slot.get("stale"):
                    state = slot.get("staleReason") or "stale"
                elif slot.get("orphan"):
                    state = "图纸里已无此对象（不删，只标）"
                else:
                    state = "已填"
                lines.append(
                    f"| `{_cell(slot.get('id'))}` | {_cell(slot.get('value'))} "
                    f"| {_cell(slot.get('source') or '—')} | {_cell(state)} |"
                )
            if stale_count:
                lines.append("")
                lines.append(
                    f"> **{stale_count} 个槽位的图纸已变（`{STALE_MARK}`）**："
                    "记录的值一个字没动，只是标出来待复核——复核完把 `design-intent.md` "
                    "里那行的 `sig=` 换成报告 `architecture.slots[]` 给的新值即可。"
                )
        if arch_totals.get("todoSlots"):
            lines.append("")
            lines.append(
                f"- 其余 {arch_totals.get('todoSlots')} 槽仍是 `TODO`（欠账不是空白）："
                f"逐槽填进 `design-intent.md`（填不出来就**显式问工程师**，不许编）。"
            )
        lines.append("")

    # --- 090 A1: the fourth contract's own section. It sits right after the
    # merged view because the two answer different halves of one question: the
    # architecture section says what the *skeleton* owes (the `design-intent.md`
    # channel), this one what the *contract* answers and still owes.
    intent_section_report = report.get("intent")
    if intent_section_report:
        render_intent_markdown(lines, intent_section_report)

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


def _channel_cell(channel: dict | None) -> str:
    """One acquisition channel as a table cell: yes/no/unknown, plus the short why."""
    if not channel:
        return "—"
    state = channel.get("ok")
    if state is True:
        mark = "有"
    elif state is False:
        mark = "没有"
    else:
        mark = "未（AI 走）"
    detail = str(channel.get("detail") or "")
    return f"{mark} —— {detail}" if detail else mark


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
