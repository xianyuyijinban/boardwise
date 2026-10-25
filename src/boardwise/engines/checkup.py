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
from ..core.metaparams import (
    CONFIRMED as META_CONFIRMED,
    WARN_CONFLICT as META_WARN_CONFLICT,
    crosscheck as meta_crosscheck,
)
from ..core.model import Component, DesignModel, Net, is_ground_net
from ..core.parts import (
    DESIGNATOR_CATEGORIES,
    FACTS_TRUST_CANDIDATE,
    FACTS_TRUST_MACHINE,
    FACTS_TRUST_VERIFIED,
)
# 537C3a: the six-channel evidence ledger's shared renderer. `evidence.py` never
# imports this module back (it handles data and text only), so this edge is one
# way. The report's own `evidence` section is built in `cli.py` from the values
# that run actually collected; this module only prints it.
from .evidence import EVIDENCE_KEY, render_evidence_markdown

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
#:
#: The trailing `(?![0-9])` is what forces a digit-run alternative to end in
#: `\d*` rather than a fixed count: `STM32` is safe because the character after
#: it is a letter (`STM32F103`), but `LPC\d{3}` could never match `LPC1768` —
#: the lookahead sees the last digit and refuses, so that alternative was a
#: silent no-op (163b: a pattern that never matches is the same defect as a
#: pattern that matches too much, and it fails the same way — quietly). The
#: families whose names end in digits are therefore spelled `\d*`.
_MCU_PATTERNS = re.compile(
    r"(?<![A-Za-z0-9])(STM32|GD32|CH32|CH58|ESP32|ESP8266|NRF5\d*|ATMEGA|ATTINY|"
    r"RP2040|LPC\d*|ATSAM|HC32|APM32|BL7\d*|MM32|N76E\d*|STC\d*|AC63|"
    # 163b: the four families this table was missing. STM8/MSP430/EFM32 are
    # spelled to their family token (the following character is a letter or a
    # dash: `STM8S003`, `MSP430F149`, `EFM32TG`), and PIC needs `\d{2,}` —
    # bare `PIC` would match the word, while `PIC\d` alone could never match
    # `PIC16F877` for the lookahead reason above.
    r"STM8|MSP430|EFM32|PIC\d{2,})(?![0-9])",
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
#:
#: 163b added five more LM parts the wide `LM\d{2,4}` alternative swallowed, each
#: one a different answer to "what is this LM part":
#:
#: * `LM311` — a comparator (the LM311 family: 311/211/111);
#: * `LM335` — an analogue temperature sensor (the Zener-style sensor, `LM335Z`);
#:   note `LM35` was already denied and does **not** catch it: the trailing
#:   `(?![0-9])` refuses `LM35` inside `LM335`, exactly as designed;
#: * `LM4040`/`LM4041`/`LM4042` — shunt **voltage references** (and a reference is
#:   not a supply: it is a component *of* a supply);
#: * `LM2903` — a dual comparator (the industrial LM393);
#: * `LM321` — a single op-amp (`LM321`, the SOT-23 op-amp family).
#:
#: The list is not exhaustive and does not pretend to be: the test is the part's
#: own name, and a rule that reads a name as evidence has to be able to say which
#: names are not evidence.
_REGULATOR_FALSE_FRIENDS = re.compile(
    r"(?<![A-Za-z0-9])(LM358|LM324|LM393|LM339|LM741|LM747|LM386|LM833|LM158|"
    r"LM2902|LM2904|LM2901|LM35|LM75|LMV\d+|TLV906\d|TLV900\d|"
    r"LM311|LM335|LM4040|LM4041|LM4042|LM2903|LM321)(?![0-9])",
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


# --------------------------------------------------------------------------
# 537C2: the run's environment — version pair, write permission, limitations
# --------------------------------------------------------------------------

#: The report key the section lives under. One name, read by `report.md`,
#: `review-summary.md` and the console line, so the three cannot drift.
ENVIRONMENT_KEY = "environment"

#: The heading both Markdown products print. Deliberately **unnumbered**: the
#: review-summary's own section numbering (1 连接状态 / 2 逐条问题 / 3 待确认 /
#: 4 下一步) is what the SOP and `tests/test_069a` name, and inserting a new
#: 3 would renumber four sections a reader already knows.
ENVIRONMENT_HEADING = "## 审查环境与权限（environment）"

#: The four states of the version comparison. A plain string comparison: this
#: tool does not infer capability compatibility from semver ordering, so equal
#: strings are the only thing that may be called `match`.
CONNECTOR_VERSION_NOT_APPLICABLE = "not-applicable"
CONNECTOR_VERSION_MATCH = "match"
CONNECTOR_VERSION_MISMATCH = "mismatch"
CONNECTOR_VERSION_UNKNOWN = "unknown"

#: The tier ids the environment section has something tier-specific to say about.
#: They are the same ids `CHECKUP_TIERS` (in `cli.py`) spells; kept as literals so
#: this module does not import the CLI.
OFFLINE_TIER = "file"
PER_PAGE_TIER = "per-page"
NETLIST_TIER = "netlist"

#: Which conclusions a missing live connector touches. The image channels are
#: included because a version difference is exactly the case where the rendered
#: picture may be of a different capability set than the requested one.
LIVE_EVIDENCE_AFFECTS = ["liveSchematic", "livePcb"]
LIVE_EVIDENCE_AND_IMAGES_AFFECTS = ["liveSchematic", "livePcb", "schematicImage", "pcbImage"]

#: The **only** next steps a review may offer, in this order. Two of them are
#: offline/manual; the third requires an explicit task authorisation and an
#: identity check, and is still limited to the named test projects. Deliberately
#: no entry here names an apply against any project: `writeAllowed=false` is a
#: statement about *this review's* authorisation, and a next step that writes to
#: a real project is something a model must never be handed as a ready command.
ALLOWED_NEXT_ACTIONS: tuple[dict, ...] = (
    {
        "id": "offline-plan",
        "mode": "offline",
        "description": "生成离线 ChangePlan；不连接编辑器、不修改设计",
    },
    {
        "id": "engineer-manual",
        "mode": "manual",
        "description": "由工程师在编辑器中核对并手动修改",
    },
    {
        "id": "authorized-test-project",
        "mode": "explicit-authorization",
        "projects": ["test", "test2"],
        "description": "仅在任务明确授权且完成工程身份核对后，按测试工程流程执行",
    },
)


def _version_text(value: object) -> str | None:
    """A version as the section carries it: a non-empty string, or ``None``.

    ``None`` is not "zero" or "unknown string" — it is the honest "this side of
    the comparison was not read", which is what makes the status `unknown`
    instead of a fabricated `match`.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def connector_version_status(*, tier: str, expected: str | None, running: str | None) -> str:
    """The four-state comparison, decided in one place.

    The offline tier is answered **first**: it has no connector, so an empty
    running version there is not a mismatch and not an unknown — the comparison
    simply does not apply. Everything else needs both sides to be readable
    strings; equality is the only `match` this tool can honestly certify.
    """
    if tier == OFFLINE_TIER:
        return CONNECTOR_VERSION_NOT_APPLICABLE
    if not expected or not running:
        return CONNECTOR_VERSION_UNKNOWN
    return CONNECTOR_VERSION_MATCH if expected == running else CONNECTOR_VERSION_MISMATCH


def environment_limitations(
    *, tier: str, expected: str | None, running: str | None, status: str
) -> list[dict]:
    """What this run could not establish, as `{code, affects, message}` rows.

    The message says what the limitation **costs** (「不得当作已确认」), never
    that the board passed: a reader who sees a clean finding list must not be
    able to read these rows as a green light. One row per code — a `match` adds
    no version row at all, which is the difference between "verified equal" and
    "nothing to verify".
    """
    rows: list[dict] = []
    if tier == OFFLINE_TIER:
        rows.append({
            "code": "offline-no-live-evidence",
            "affects": list(LIVE_EVIDENCE_AFFECTS),
            "message": (
                "离线文件（--file）没有实时编辑器证据：原理图与 PCB 读数都来自归档，"
                "不是实时检查成功；受影响的实时结论不得当作已确认。"
            ),
        })
    elif status == CONNECTOR_VERSION_MISMATCH:
        rows.append({
            "code": "connector-version-mismatch",
            "affects": list(LIVE_EVIDENCE_AND_IMAGES_AFFECTS),
            "message": (
                f"连接器版本不一致：期望 {expected}，运行 {running}；两者只是字符串对拍"
                "（本工具不做 semver 推断），受影响的实时结论（含两张实时图）不得标 confirmed。"
            ),
        })
    elif status == CONNECTOR_VERSION_UNKNOWN:
        rows.append({
            "code": "connector-version-unverified",
            "affects": list(LIVE_EVIDENCE_AND_IMAGES_AFFECTS),
            "message": (
                f"连接器版本未核实：期望 {expected or '（未读到）'}，"
                f"运行 {running or '（未读到）'}；能力兼容性未证实，不能当成 match，"
                "受影响的实时结论不得当作已确认。"
            ),
        })
    if tier == PER_PAGE_TIER:
        rows.append({
            "code": "per-page-connectivity-limit",
            "affects": ["crossPageConnectivity", "archivePcb"],
            "message": (
                "逐页归档合并只按同名网拼接：同名网不构成已验证的跨页连接"
                "（agreement by name is not a verified connection），跨页连通性结论只能当待核；"
                "该档也没有整工程 PCB 归档，archivePcb 不存在。"
            ),
        })
    if tier == NETLIST_TIER:
        rows.append({
            "code": "connectivity-only-model",
            "affects": ["values", "mpn", "archivePcb"],
            "message": (
                "在线网表档（sch.netlist / sch.geometry）只有连通性：没有 Value / MPN，"
                "依赖元件参数与型号的结论不可得；也没有 PCB 归档，archivePcb 不存在。"
            ),
        })
    return rows


def _allowed_next_actions() -> list[dict]:
    """The frozen three, copied so a caller cannot mutate the constants."""
    return [
        dict(action, **({"projects": list(action["projects"])} if "projects" in action else {}))
        for action in ALLOWED_NEXT_ACTIONS
    ]


def environment_section(
    *, tier: str, source: dict | None, expected_connector_version: str = ""
) -> dict:
    """Assemble the ``environment`` section from the tier and the run's ``source``.

    The running version is read from ``source.connectorVersion`` — the same
    reading the report already carried before this section existed, so the two
    cannot disagree — and the expected one is passed in (the caller owns "which
    checkout would be installed"). ``writeAllowed`` is always ``false`` here:
    a review is a read, and this section states **this run's** authorisation, not
    the daemon's global configuration.
    """
    expected = _version_text(expected_connector_version)
    running = _version_text((source or {}).get("connectorVersion"))
    status = connector_version_status(tier=tier, expected=expected, running=running)
    return {
        "tier": tier,
        "expectedConnectorVersion": expected,
        "runningConnectorVersion": running,
        "connectorVersionStatus": status,
        "writeAllowed": False,
        "allowedNextActions": _allowed_next_actions(),
        "limitations": environment_limitations(
            tier=tier, expected=expected, running=running, status=status
        ),
    }


def _environment_status_label(status: str) -> str:
    return {
        CONNECTOR_VERSION_NOT_APPLICABLE: "离线，没有可对拍的运行连接器",
        CONNECTOR_VERSION_MATCH: "期望与运行逐字相同",
        CONNECTOR_VERSION_MISMATCH: "期望与运行不同，实时结论不得标 confirmed",
        CONNECTOR_VERSION_UNKNOWN: "任一侧版本缺失，能力兼容未证实",
    }.get(status, "")


def render_environment_markdown(
    environment: object, *, heading: str = ENVIRONMENT_HEADING
) -> list[str]:
    """The section as Markdown lines, shared by `report.md` and `review-summary.md`.

    **Empty in, empty out**: a report built before this section existed (or by a
    test that hand-builds one) renders exactly what it rendered before — the old
    rendering is the compatibility promise, so nothing here invents text for a
    missing section. Deliberately bullet-only: the review-summary's own row
    counting reads `|`-lines, and a table here would look like findings.
    """
    if not isinstance(environment, dict) or not environment:
        return []
    expected = environment.get("expectedConnectorVersion") or "（未读到）"
    running = environment.get("runningConnectorVersion") or "（未读到）"
    status = str(environment.get("connectorVersionStatus") or CONNECTOR_VERSION_UNKNOWN)
    # Rendered from the section's own value, not a second hard-coded `false`: a
    # renderer that always printed false would agree with a buggy section and
    # disagree with `report.json` the day the field moved.
    write_flag = "false" if environment.get("writeAllowed", False) is False else "true"
    lines = [
        heading,
        "",
        f"- 数据档（tier）：`{environment.get('tier') or '?'}`",
        f"- 连接器版本：期望 `{expected}` / 运行 `{running}` —— 状态 `{status}`"
        f"（{_environment_status_label(status)}）",
        # The scope of the claim is part of the claim: `writeAllowed=false` here
        # says *this review* is not authorised to write, and nothing else.
        f"- writeAllowed：`{write_flag}` —— 本次 review 不授权写（这是本次审查的授权状态，"
        "不是 daemon 的全局配置）",
        "- 允许的下一步（allowedNextActions）：",
    ]
    for action in environment.get("allowedNextActions") or []:
        projects = " / ".join(str(p) for p in (action.get("projects") or []))
        suffix = f"；projects：{projects}" if projects else ""
        lines.append(
            f"  - `{action.get('id')}`（{action.get('mode')}{suffix}）："
            f"{action.get('description')}"
        )
    limitations = environment.get("limitations") or []
    if limitations:
        lines.append("- 限制（limitations，逐条说明影响，不是通过）：")
        for row in limitations:
            affects = "、".join(str(a) for a in (row.get("affects") or []))
            lines.append(f"  - `{row.get('code')}`（影响：{affects}）—— {row.get('message')}")
    else:
        lines.append("- 限制（limitations）：无——本次环境没有未证实项")
    lines.append("")
    return lines


def environment_console_line(environment: object) -> str:
    """The one-line console summary of the same section, or ``''`` when absent.

    One line on purpose: the console is a checklist, and the details (messages,
    affects) are in the two Markdown products. It still names every field the
    contract requires — expected / running / status, the write flag, and the
    next-step ids — so a terminal reader needs no follow-up command.

    The write flag is **rendered from the section**, exactly like
    :func:`render_environment_markdown`: a hard-coded ``false`` here would agree
    with the JSON only for as long as the section happens to say false, and would
    silently diverge the day it says otherwise. One section, four renderings
    (JSON / report.md / review-summary.md / stdout) — none of them a second
    opinion.
    """
    if not isinstance(environment, dict) or not environment:
        return ""
    expected = environment.get("expectedConnectorVersion") or "(none)"
    running = environment.get("runningConnectorVersion") or "(none)"
    status = environment.get("connectorVersionStatus") or CONNECTOR_VERSION_UNKNOWN
    write_flag = "false" if environment.get("writeAllowed", False) is False else "true"
    next_ids = ",".join(
        str(action.get("id")) for action in (environment.get("allowedNextActions") or [])
    )
    codes = ",".join(
        str(row.get("code")) for row in (environment.get("limitations") or [])
    ) or "(none)"
    return (
        f"environment: expected={expected} running={running} status={status} "
        f"writeAllowed={write_flag} next={next_ids} limitations={codes}"
    )


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
    # 537C2: the environment between the findings and the worklist — a reader
    # who is about to fill 「分析/建议」 must first know what this run could not
    # see and that it was read-only. Additive: a hand-built report with no
    # `environment` keeps the skeleton exactly as it was.
    environment_lines = render_environment_markdown(report.get(ENVIRONMENT_KEY))
    if environment_lines:
        lines.append("\n")
        lines.extend(f"{line}\n" for line in environment_lines)
    # 537C3a: the same ledger, rendered by the same helper `report.md` uses. One
    # section, two files — the model filling 「分析/建议」 must be able to see what
    # the run did not collect before it writes a conclusion.
    evidence_lines = render_evidence_markdown(report.get(EVIDENCE_KEY))
    if evidence_lines:
        lines.append("\n")
        lines.extend(f"{line}\n" for line in evidence_lines)
    lines.append(
        "\n## 3. 待确认（本报告依赖的未知项）\n\n"
        "<!-- needs_datasheet 非空时逐条写：缺什么资料、找谁要。空着才允许写「通过」。 -->\n"
        "\n"
        f"{unreviewed_clearing_note(str(report.get('shelfPath') or ''))}\n"
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
#: "no MPN at all" and "the value cannot be known" are different problems.
UNKNOWN_REASON_NO_MPN = "无 MPN"
#: Reworded by 184 — the reason now says what the gate actually asks. Until 184 it
#: fired on "the MPN's value code does not decode, and that is not the same as the
#: value not existing"; the gate now asks whether the value can be known **at
#: all** (:func:`_value_decodable`), so the old parenthesis would be a lie: a part
#: that reaches this reason has no board ``Value`` to read *and* no MPN the
#: decoders can read.
UNKNOWN_REASON_UNDECODABLE = (
    "值不可知（MPN 里的值码解不出，板上 Value 也读不出；判定见 values.py）"
)
UNKNOWN_REASON_NO_SUPPLIER = "供应商字段为空"
#: 188B (186 中2): the entry is on the shelf with verified facts but **no
#: category**. `rules.facts._category_state` answers UNKNOWN for exactly that
#: shape, so the facts rules refuse a part the gate used to call judged — the
#: one thing "the shelf has this part" and "the shelf can judge it" must not
#: collapse into. The work it names is a shelf edit, not a datasheet hunt.
UNKNOWN_REASON_UNCATEGORISED = (
    "货架条目有 facts 但没分类（category 为空；规则按 category 认料，未分类一律 UNKNOWN）"
)

#: 522: the shelf's facts are machine-verified (521 checked every quote verbatim
#: on the page it names, and 522 let the calculation rules act on them) and no
#: human has confirmed them. The next act is a **signature**, not a datasheet:
#: the PDF is already in the shelf's provenance. This is the reason string the
#: third `unreviewedByClass` bucket is keyed on.
UNKNOWN_REASON_MACHINE_UNCONFIRMED = (
    "货架条目的 facts 是机器核验（证据链已过闸、未人工确认）——"
    "待人工确认 facts_trust 是否升到 verified"
)

#: Designator prefixes whose MPN is expected to carry an EIA value code, i.e. the
#: ones for which "the value cannot be known" is a real signal. An IC's MPN never
#: carries one, so asking a decoder about it would put every IC on the list.
_VALUE_CODE_PREFIXES = frozenset({"R", "C", "L", "RV", "RP", "RT", "FB"})


def _value_decodable(prefix: str, component: Component) -> bool:
    """Can this part's **value** be known at all? (task 184)

    The gate's predicate since 184, replacing the question it used to ask
    (``mpn_value_code`` returned ``None``). Why the old one was wrong: it read
    **one** of the two value decoders and had no view of the board at all, so a
    board whose ``Value`` fields were all present and all correct reported
    "cannot decode" for every resistor family the EIA whitelist does not spell
    — 34 of the 68 unreviewed parts on
    ``.tmp_bug98b/实板A.epro2`` (岳 2026-10-15 实板反馈), whose board
    values are all readable. UNKNOWN_REASON_UNDECODABLE now means what its name
    says: the value is genuinely unknowable.

    Three ways to know it, tried in this order:

    * the **board's own** ``Value`` field parses — by the parser of that part's
      quantity (:func:`parse_resistance_ohms` for R/RV/RP/RT/FB, the closest
      reader those have; :func:`parse_capacitance_farads` for C). A part whose
      board value is already a number needs no MPN reading to be judged; this is
      the branch the old gate could not see;
    * the **MPN** states an EIA value code (:func:`mpn_value_code`) — the
      whitelist's reading, unchanged;
    * the **MPN** is read by the resistance candidates system
      (:func:`mpn_resistance_candidates`), the several-shape family of
      043/046/048/071/184:
      a resistor spelling the whitelist refuses (``FRC0603F1000TS``, whose E-96
      field sits in front of a taping tail) is still a value a rule can use.
      This branch belongs to the parts whose **quantity is a resistance**, and
      nothing else (188a): it is not consulted for ``C``/``L`` (the capacitor
      side has no candidates entry and inventing one here would be a second
      decoder; ``L`` has no parser to check the reading against), nor for
      ``FB``/``RV``/``RT``, whose numbers are a 100 MHz impedance, a varistor
      voltage and a thermistor's R25 + **B constant** — a reading of those as
      ohms is a number nobody can defend. ``RP`` (a resistor network/array)
      keeps it: an array's declared value *is* a resistance, and the shelf
      writes it in ohms.

    ``MF52-103/3435`` is the witness for the ``RT`` half of that (188a): the
    candidates reader answers 34.3 MΩ out of the part's B constant ``3435``
    (an E-96 four-figure field by shape), and before 188a the gate cleared the
    part on it. The readers are untouched — the *gate* is what stopped asking a
    question that is not about this part (``7D471K``-class varistors and
    ``BRC2016T101K``-class beads are the same shape of false clear).

    ``L`` deliberately has no board-value branch: this module has no inductance
    parser (``parse_inductance`` does not exist), and reading an inductor's value
    with the resistance grammar would be inventing a number. An inductor is
    still covered by the MPN branches above.

    ``ERA16V100M5X7`` (an electrolytic whose MPN prints microfarads, so
    :func:`_foreign_unit_code` refuses it) is the witness for the first branch:
    the board's ``100uF`` is readable, and the refusal of the MPN reading is
    correct behaviour that stays.
    """
    from ..core.values import (
        mpn_resistance_candidates,
        mpn_value_code,
        parse_capacitance_farads,
        parse_resistance_ohms,
    )

    value = (component.value or "").strip()
    if value:
        parsed = None
        if prefix == "C":
            parsed = parse_capacitance_farads(value)
        elif prefix != "L":
            parsed = parse_resistance_ohms(value)
        if parsed is not None:
            return True
    mpn = (component.mpn or "").strip()
    if not mpn:
        return False
    if mpn_value_code(mpn) is not None:
        return True
    if prefix in ("C", "L", "FB", "RV", "RT"):
        return False
    return bool(mpn_resistance_candidates(mpn))


def _prefix_of(designator: str) -> str:
    match = re.match(r"[A-Za-z]+", designator or "")
    return match.group(0).upper() if match else ""


# --------------------------------------------------------------------------
# 517: the archive's own parameters (level 0) — no network call
# --------------------------------------------------------------------------

#: The quantity a part's ``kind`` reads its value code in — the narrow map
#: :func:`boardwise.core.metaparams.mpn_params` asks for. ``inductor`` is in
#: it to be **refused** (no inductance parser exists to ask), the same
#: discipline ``_value_decodable`` states for ``L``.
_META_KIND_OF_KIND: dict[str, str] = {
    "resistor": "resistor",
    "capacitor": "capacitor",
    "inductor": "inductor",
}


def _meta_kind_of(component: Component) -> str:
    """The ``metaparams`` kind for one component, or ``""`` (read nothing).

    Classified by the shared entry point (:func:`classify_part`) and mapped
    through the narrow table above: an IC, a connector, a thermistor and
    everything else this reader has no value grammar for read as ``""`` —
    asking a value-code question about a part whose quantity is not a
    resistance or a capacitance is the 188a false-clear shape.
    """
    from ..core.partkind import classify_part

    return _META_KIND_OF_KIND.get(classify_part(component, pin_floor=False).kind, "")


def _meta_archive_text(component: Component) -> str:
    """The archive string to read: ``LCSC Part Name``, then ``Type``.

    The two fields :data:`METADATA_TYPE_KEYS` established as the archive's
    declarations, in the same priority order 189B measured (the type was
    written in ``LCSC Part Name`` while ``Type`` was empty). ``Supplier
    Footprint`` is not read here: it names a package, not a parameter.
    """
    for key in ("LCSC Part Name", "Type"):
        text = str(component.props.get(key) or "").strip()
        if text:
            return text
    return ""


def _metadata_crosscheck(component: Component, kind: str) -> dict:
    """The three-way parameter agreement for one component (517).

    ``(rows, state)``: the per-parameter crosscheck rows from
    :func:`boardwise.core.metaparams.crosscheck` over the three sources, and
    the component's **overall** state — ``"confirmed"`` when the *value*
    parameter is confirmed by ≥2 sources agreeing, ``"warn"`` when any
    parameter's sources clash, ``"missing"`` when the archive states nothing
    at all, ``"unparseable"`` when the archive has a string but every token
    was refused. Missing and unparseable are **different answers** — the
    product's core requirement is that a parse failure never be counted as
    "the data does not exist".
    """
    archive_text = _meta_archive_text(component)
    rows = meta_crosscheck(
        archive_text,
        component.value or "",
        component.mpn or "",
        kind=kind,
    )
    if rows.get("value", None) is not None and rows["value"].state == META_CONFIRMED:
        state = "confirmed"
    elif any(row.state == META_WARN_CONFLICT for row in rows.values()):
        state = "warn"
    elif not archive_text:
        state = "missing"
    elif not rows:
        state = "unparseable"
    else:
        # The archive stated something readable (a tolerance, a power …) but
        # the value did not confirm: it is neither missing nor a conflict.
        state = "partial"
    return {"rows": rows, "state": state, "archive": archive_text}


def metadata_parameter_rows(model) -> list[dict]:
    """One row per passive whose parameters the archive confirmed (517).

    The trace for the rows :func:`unknown_parts` does **not** list because of
    their value (the gate's second shortening path, beside 192B ⑤'s
    declared-passive exemption): a part that leaves the datasheet worklist
    because two sources agreed on its value has to say so, with **which two**
    — the evidence is the deliverable, not a side effect. Read off the same
    predicate the gate applies, so the rows cannot disagree with the gate.
    """
    rows: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        if _prefix_of(designator) not in _VALUE_CODE_PREFIXES:
            continue
        kind = _meta_kind_of(component)
        if not kind:
            continue
        result = _metadata_crosscheck(component, kind)
        value_row = result["rows"].get("value")
        if value_row is None or value_row.state != META_CONFIRMED:
            continue
        rows.append({
            "designator": designator,
            "kind": kind,
            "archive": result["archive"],
            "value": value_row.readings.get("mpn", next(iter(value_row.readings.values()), 0.0)),
            "confirmedBy": list(value_row.agreeing),
            "readings": {
                param: {
                    "state": row.state,
                    "readings": row.readings,
                    "evidence": row.evidence,
                }
                for param, row in result["rows"].items()
            },
            **_board_field(
                boards,
                mpn=str(component.mpn or "").strip(),
                name=str(component.props.get("device_name") or component.value or ""),
                value=component.value,
            ),
        })
    return rows


def metadata_conflict_rows(model) -> list[dict]:
    """One row per passive whose parameter sources **clash** (517).

    Two readings that disagree — archive against board, archive against MPN,
    board against MPN — are a WARN with every reading written out, never a
    silent pick. Same walk, same predicate as :func:`metadata_parameter_rows`.
    """
    rows: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        if _prefix_of(designator) not in _VALUE_CODE_PREFIXES:
            continue
        kind = _meta_kind_of(component)
        if not kind:
            continue
        result = _metadata_crosscheck(component, kind)
        conflicts = {
            param: row
            for param, row in result["rows"].items()
            if row.state == META_WARN_CONFLICT
        }
        if not conflicts:
            continue
        rows.append({
            "designator": designator,
            "kind": kind,
            "archive": result["archive"],
            "boardValue": component.value,
            "mpn": str(component.mpn or "").strip(),
            "params": {
                param: {
                    "state": row.state,
                    "readings": row.readings,
                    "evidence": row.evidence,
                }
                for param, row in conflicts.items()
            },
            **_board_field(
                boards,
                mpn=str(component.mpn or "").strip(),
                name=str(component.props.get("device_name") or component.value or ""),
                value=component.value,
            ),
        })
    return rows


def _value_confirmed_by_metadata(component: Component) -> bool:
    """May the gate drop this part's 「值不可知」 reason on metadata evidence (517)?

    Exactly the confirmation rule, applied to the one parameter the gate is
    about: the **value** is confirmed when ≥2 of the three sources state it
    and agree. Two available and clashing is a WARN — it never silently
    clears, so this answers False for a conflict. One source alone confirms
    nothing either: a reading with nothing to check against is carried, not
    credited.
    """
    real_kind = _meta_kind_of(component)
    if not real_kind:
        return False
    result = _metadata_crosscheck(component, real_kind)
    value_row = result["rows"].get("value")
    return value_row is not None and value_row.state == META_CONFIRMED


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
    * **the value is not knowable** (`UNKNOWN_REASON_UNDECODABLE`, rewritten by
      184) — the part's board ``Value`` field does not parse *and* its MPN
      carries no value code the decoders can read (:func:`_value_decodable`,
      which asks the board's own parsers, the EIA whitelist and — for the
      prefixes whose quantity really is a resistance — the resistance
      candidates system; 188a keeps the last one off FB/RV/RT, whose numbers are
      not ohms). Restricted to prefixes whose MPN is *expected* to carry a code
      (R/C/L/…), because asking about an IC's MPN would list every IC on the
      board. Before 184 the signal was narrower — "``mpn_value_code``
      returned ``None``" — which listed every resistor family the whitelist does
      not spell, board value or no board value;
    * **no supplier part** — the part cannot be ordered or cross-checked by code.

    `question` is the same for all of them: the review's next step is "go and read
    the datasheet's typical application", whatever it was that made the part
    unfamiliar.

    **A thermistor is not asked for an EIA value code** (190, 岳 10-16 裁决).
    ``_VALUE_CODE_PREFIXES`` is the list of prefixes whose MPN is *expected* to
    carry a value code — ``R`` among them — and an NTC/PTC is placed at an ``R``
    designator with an MPN whose figures are a temperature curve
    (``HNTC0603-103F3450FA``), so 「值不可知」 was being filed about a part whose
    value this tool is not supposed to decode at all. ``classify_part`` says which
    parts those are; the reason is simply not recorded for them, and the other
    two identity signals (no MPN, no supplier) are untouched.
    """
    from ..core.partkind import KIND_THERMISTOR, classify_part

    out: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        reasons: list[str] = []
        prefix = _prefix_of(designator)
        mpn = (component.mpn or "").strip()
        if not mpn:
            reasons.append(UNKNOWN_REASON_NO_MPN)
        elif (
            prefix in _VALUE_CODE_PREFIXES
            and classify_part(component).kind != KIND_THERMISTOR
            and not _value_decodable(prefix, component)
            # 517: the archive's own parameters are the level-0 answer. A part
            # whose value ≥2 of the three sources (archive metadata / board
            # ``Value`` / MPN) state **and agree on** is a value the review can
            # use, so 「值不可知」 would be a lie about it — the reason is not
            # recorded, and the evidence rides in `metadataValueConfirmed[]`
            # / report.md. ``UNKNOWN_REASON_UNDECODABLE``'s own meaning is
            # untouched: it still names exactly 「MPN 值码解不出，板上 Value
            # 也读不出」, and this check is asked *beside* it, before the
            # reason is written, not instead of the decoders.
            and not _value_confirmed_by_metadata(component)
        ):
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
            **_board_field(
                boards,
                mpn=mpn,
                name=str(component.props.get("device_name") or component.value or ""),
                value=component.value,
            ),
        })
    return out


def board_titles(boards) -> list[str]:
    """The board titles a row's ``boards`` field names — **either shape** (191B).

    The canonical shape is a list of placement rows (``{"board", "mpn", "name",
    "value"}``); a bare list of titles is the shape every row used before 191B
    and is still what ``unknown_parts`` (among others) carries, so a reader that
    only needs "which boards" asks this function instead of assuming. An entry
    that is neither (a caller's garbage) is skipped rather than crashed on: the
    report must not lose a row because one field had the wrong type.
    """
    out: list[str] = []
    for item in boards or ():
        if isinstance(item, dict):
            title = str(item.get("board") or "")
        elif isinstance(item, str):
            title = item
        else:
            continue
        if title and title not in out:
            out.append(title)
    return out


def board_rows(
    boards, *, mpn: str = "", name: str = "", value: str = ""
) -> list[dict]:
    """A row's ``boards`` field normalized to the canonical rows (191B) — the
    compatibility read for the title-list shape.

    One shape for `unreviewed_parts[]` and `needs_datasheet[]` (187B's finding
    was that the two said "which boards" in two different shapes, so a reader
    had two cases to get right and a fold had one of them wrong): a list of
    ``{"board", "mpn", "name", "value"}``, **the placement's** identity per
    board. A title-list entry has no per-board identity of its own, so it is
    expanded with the row's own fields — which is what the 185-中1 fold did with
    them, and why an old report still reads the same.
    """
    out: list[dict] = []
    for item in boards or ():
        if isinstance(item, dict):
            row = {
                "board": str(item.get("board") or ""),
                "mpn": str(item.get("mpn") or ""),
                "name": str(item.get("name") or ""),
                "value": str(item.get("value") or ""),
            }
        elif isinstance(item, str):
            row = {"board": item, "mpn": mpn, "name": name, "value": value}
        else:
            continue
        if row not in out:
            out.append(row)
    return out


def _board_field(
    boards, *, mpn: str = "", name: str = "", value: str = ""
) -> dict:
    """``{"boards": [...]}`` for a multi-board model, ``{}`` for one board.

    Added, never renamed (the schema rule): a single-board report's rows are
    byte-for-byte what they were, and a project's rows say which board they are
    about. **191B**: the list is :func:`board_rows`' canonical shape — the same
    one `needs_datasheet[]` has carried since 185-中1 — and an old title list is
    still read (:func:`board_titles`, :func:`board_rows`).
    """
    rows = board_rows(boards, mpn=mpn, name=name, value=value)
    return {"boards": rows} if rows else {}


def unreviewed_counts_by_reason(unreviewed: list[dict] | None) -> dict[str, int]:
    """``{reason: rows carrying it}`` for one 未审器件 list (task 184).

    One aggregation over the section's own ``reasons``, so the summary cannot
    disagree with the rows below it: the numbers are counted from the report's
    list, never from a second walk of the model. A row can carry two reasons and
    is counted under each, exactly as the list itself reads; the keys are sorted
    so two runs of the same board write the same report.

    Why it exists (岳 2026-10-15, task 184): ``68`` unreviewed parts is one
    number for problems that need different work — 26 parts have no MPN at all,
    34 were on the list because the value decoder could not read their MPN, 26
    have no supplier. A reader deciding what to do next needs the split, and the
    report already carries it per row.
    """
    counts: dict[str, int] = {}
    for row in unreviewed or []:
        if not isinstance(row, dict):
            continue
        for reason in row.get("reasons") or []:
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


#: 186 §C: 184's per-reason count is one table of six reasons; the reader's
#: question is coarser and has an **opposite next step** per answer. Two classes:
#:
#: * 「工具读不懂」 — the value is genuinely unknowable to this project's
#:   decoders (``UNKNOWN_REASON_UNDECODABLE``) or the shelf entry itself cannot
#:   be read by a rule (``UNKNOWN_REASON_UNCATEGORISED``, 188B): more datasheets
#:   will not help; the work is a better reading (a decoder, the board's own
#:   ``Value``, or a ``category`` on the entry);
#: * 「真缺资料」 — the datasheet hunt itself is blocked (no MPN to search, no
#:   supplier code to look up, shelf has nothing): a PDF **is** the next step.
#:
#: A row may be in both when it carries both reasons; that is the same
#: counting rule :func:`unreviewed_counts_by_reason` uses, and for the same
#: reason — the rows below are the truth, and a row counted once in each class
#: it belongs to is not counted twice.
REASON_CLASS_UNDECODABLE = "工具读不懂"
REASON_CLASS_MISSING_MATERIAL = "真缺资料"
#: 522's third class: the shelf **has** the facts and a machine checked the
#: evidence chain (521's quotes-verbatim gate), so neither "fetch a datasheet"
#: nor "teach the tool to read" is the next act — a person reading the evidence
#: and signing it is. It is its own bucket rather than folded into 真缺资料
#: because sending a reader to hunt a PDF the shelf already holds is the mistake
#: 186 §A spent a batch killing.
REASON_CLASS_MACHINE_UNCONFIRMED = "机器核验待人工确认"

#: The order the three classes are printed in: the ones whose next step is **not**
#: "fetch a datasheet" go first, so a reader does not start hunting for a PDF
#: that would not have helped. 522's new bucket sits second — after the tool's own
#: reading gap (nothing a person can close by reading) and before the hunt.
CLASS_ORDER: tuple[str, ...] = (
    REASON_CLASS_UNDECODABLE,
    REASON_CLASS_MACHINE_UNCONFIRMED,
    REASON_CLASS_MISSING_MATERIAL,
)

# --------------------------------------------------------------------------
# 517: the metadata reading, **inside** the class split — the four answers the
# archive gave, counted separately because a parse failure is not "missing
# data" (the batch's core requirement).
# --------------------------------------------------------------------------

#: 517's four sub-answers, beneath 186 §C's two classes. One passive's archive
#: metadata read:
#:
#: * 「元数据已确认」 — ≥2 of the three sources (archive / board ``Value`` /
#:   MPN) state the value and agree. The gate already dropped these (the row
#:   is not in the list below at all); the count is the trace of what the
#:   archive bought;
#: * 「元数据冲突」 — ≥2 sources available and they disagree: a WARN, every
#:   reading written out, never a silent pick;
#: * 「元数据缺失」 — no archive string at all (no ``LCSC Part Name``, no
#:   ``Type``): the data genuinely does not exist in the archive;
#: * 「元数据不可解析」 — an archive string is there and **nothing** in it
#:   parsed. This is a *tool* failure, not missing data — counting it as
#:   「缺失」 would send the engineer hunting a datasheet for what is a
#:   parser gap, which is exactly the conflation this batch exists to end.
#:
#: A part the archive read but neither confirmed nor warned (a readable
#: tolerance, no readable value) lands in none of the four: it was never on
#: the value question's list.
META_STATE_CONFIRMED = "元数据已确认"
META_STATE_CONFLICT = "元数据冲突"
META_STATE_MISSING = "元数据缺失"
META_STATE_UNPARSEABLE = "元数据不可解析"

META_STATE_ORDER: tuple[str, ...] = (
    META_STATE_CONFIRMED, META_STATE_CONFLICT, META_STATE_MISSING,
    META_STATE_UNPARSEABLE,
)


def unreviewed_reason_class(reason: str) -> str:
    """Which class one reason belongs to (186 §C, 188B, 522).

    ``UNKNOWN_REASON_UNCATEGORISED`` joins the "read, do not hunt" class: the
    entry is on the shelf, so more datasheets change nothing — what is missing is
    a **class** on the entry (`category`), which is a reading of the shelf rather
    than a document to go and find.

    522 added the third answer, and it is a class of its own rather than a
    qualifier on either neighbour: ``UNKNOWN_REASON_MACHINE_UNCONFIRMED`` means
    the facts are on the shelf **and** a machine checked every quote against the
    page it names (521), so the outstanding work is a person's signature — not a
    document to fetch (真缺资料) and not a reader to improve (工具读不懂).
    """
    text = str(reason)
    if text == UNKNOWN_REASON_MACHINE_UNCONFIRMED:
        return REASON_CLASS_MACHINE_UNCONFIRMED
    return (
        REASON_CLASS_UNDECODABLE
        if text in (UNKNOWN_REASON_UNDECODABLE, UNKNOWN_REASON_UNCATEGORISED)
        else REASON_CLASS_MISSING_MATERIAL
    )


def unreviewed_classes(row: dict) -> list[str]:
    """The classes one 未审器件 row belongs to, in :data:`CLASS_ORDER` order.

    A row with no reasons at all — an IC whose only problem is "the shelf has
    no facts for it" — is :data:`REASON_CLASS_MISSING_MATERIAL`: the work it
    needs is a datasheet.
    """
    reasons = [str(reason) for reason in (row.get("reasons") or [])]
    classes = {unreviewed_reason_class(reason) for reason in reasons} or {
        REASON_CLASS_MISSING_MATERIAL
    }
    return [name for name in CLASS_ORDER if name in classes]


def facts_trust_counts(rows: list[dict] | None) -> dict[str, int]:
    """``{"verified": n, "machineVerified": n, "candidate": n}`` over report rows.

    522 §5.2: the three tiers, counted from the rows the report already carries
    (`unreviewed_parts[]` + `reviewedByShelf[]`) rather than from a second walk of
    the shelf — one source, so the section and the counts cannot disagree about
    the same part.

    The keys are **camelCase** and all three are always present, including the
    zeros: `completion.factsTrust.machineVerified >= 1` is the reading 522's
    acceptance quotes, and a missing key would make that check a `KeyError`
    instead of an honest 0. A row with no `factsTrust` (a report written before
    this batch, or a part on no shelf) contributes nothing — it is not a tier.

    A part can appear in **both** lists? No: the two lists are complements on
    :func:`shelf_judgement`, and 522 made `machine_verified` fail that gate, so a
    machine-verified row is in `unreviewed_parts[]` only. Counting over the union
    is therefore a plain sum, and the helper takes the caller's concatenation.
    """
    counts = {"verified": 0, "machineVerified": 0, "candidate": 0}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        tier = str(row.get("factsTrust") or "")
        if tier == FACTS_TRUST_VERIFIED:
            counts["verified"] += 1
        elif tier == FACTS_TRUST_MACHINE:
            counts["machineVerified"] += 1
        elif tier == FACTS_TRUST_CANDIDATE:
            counts["candidate"] += 1
    return counts


def unreviewed_counts_by_class(unreviewed: list[dict] | None) -> dict[str, int]:
    """``{class: rows in it}`` for one 未审器件 list (task 186 §C).

    Read from the same rows as :func:`unreviewed_counts_by_reason`, so the two
    tables cannot disagree; the counting rule is the same one — a row in both
    classes is counted in each, and the heading's number remains the number of
    parts.
    """
    counts: dict[str, int] = {}
    for row in unreviewed or []:
        if not isinstance(row, dict):
            continue
        for name in unreviewed_classes(row):
            counts[name] = counts.get(name, 0) + 1
    return {name: counts[name] for name in CLASS_ORDER if name in counts}


def _meta_state_of_component(component: Component) -> str | None:
    """Which of the four 517 answers one passive's archive gave, or ``None``.

    ``None`` — the part is not a value-code passive this reader reads (an IC,
    a connector, an inductor), so it is not in the metadata question at all
    and must not be counted in any of the four buckets.
    """
    if not _meta_kind_of(component):
        return None
    result = _metadata_crosscheck(component, _meta_kind_of(component))
    state = result["state"]
    return {
        "confirmed": META_STATE_CONFIRMED,
        "warn": META_STATE_CONFLICT,
        "missing": META_STATE_MISSING,
        "unparseable": META_STATE_UNPARSEABLE,
        "partial": None,
    }.get(state)


def metadata_state_counts(model) -> dict[str, int]:
    """The four 517 buckets over one model's **value-code passives** (517).

    Walked over the same placements the gate walks (:func:`_parts_with_boards`)
    and restricted to the same population the value question is about —
    ``_VALUE_CODE_PREFIXES`` designators that are not thermistors — so the four
    numbers cannot disagree with the gate they sit under. Confirmed parts are
    counted here **although they are not in `unreviewed_parts[]`**: the bucket
    is the trace of what the archive bought, and a count that only covered the
    rows below it could not state that.
    """
    from ..core.partkind import KIND_THERMISTOR, classify_part

    counts: dict[str, int] = {}
    for designator, component, _boards in _parts_with_boards(model):
        if _prefix_of(designator) not in _VALUE_CODE_PREFIXES:
            continue
        if classify_part(component).kind == KIND_THERMISTOR:
            continue
        state = _meta_state_of_component(component)
        if state is None:
            continue
        counts[state] = counts.get(state, 0) + 1
    return {name: counts[name] for name in META_STATE_ORDER if name in counts}


def metadata_state_counts_from_rows(
    rows: list[dict], confirmed_rows: list[dict]
) -> dict[str, int]:
    """The same four buckets for a **report** being re-gated (058's path).

    The re-gate re-reads no model, so it cannot re-walk placements; it reads
    the rows the run wrote — the confirmed trace and the conflict rows — and
    reconstructs the buckets from them. The missing/unparseable buckets cannot
    be recovered from a conflict-only section, so they are taken from the
    completion summary the run wrote (``metadataStateCounts``); a summary
    without the key (a pre-517 report) answers empty, and the honest
    degradation is fewer buckets rather than invented ones.
    """
    counts: dict[str, int] = {}
    for _row in confirmed_rows or []:
        counts[META_STATE_CONFIRMED] = counts.get(META_STATE_CONFIRMED, 0) + 1
    for _row in rows or []:
        counts[META_STATE_CONFLICT] = counts.get(META_STATE_CONFLICT, 0) + 1
    return {name: counts[name] for name in META_STATE_ORDER if name in counts}


#: The fixed line the 未审器件 section must carry (186 §C, P1). The accident it
#: answers: handing a PDF over looked like it closed the gate, and the reader
#: could not tell which action actually would. Named commands are the CLI's own
#: — `boardwise parts add <MPN> --lcsc <C码> --category <类别> --facts
#: <facts.json> --verified` closes it, and `boardwise need-datasheet` is the
#: *other* channel (the reviewer's own "cannot establish"), which makes this
#: section longer rather than emptying it.
#:
#: 188B added two things to that command line, both because the instruction was
#: incomplete rather than wrong:
#:
#: * **`--category <类别>`** — since 188B an entry with facts and no category no
#:   longer counts as judged (`rules.facts._category_state` answers UNKNOWN for
#:   it), so a reader following the old spelling would close the facts half of the
#:   gate and stay on this list;
#: * **where the C 码 comes from** — 立创商城 search. The reader who does not
#:   already know how to get a C-number is exactly the reader this line is for,
#:   and "search 立创商城" is the honest first step (the shelf's own
#:   `parts select` / `--resolve` come after it).
#:
#: 191A appended the **third** channel, and it is the one 186 could only write
#: about: `boardwise parts accept-unknown` (`--reason` required) records the
#: engineer's 「这颗的未知我接受」 in the design-intent contract, and the part
#: leaves this section for the report's own `accepted_unknown[]` — where the
#: reason, the who/when and the count in the verdict keep it from being a silent
#: pass. The earlier wording said this CLI had no such command; it has one now,
#: and a clearing instruction that omits the channel it *does* have sends the
#: reader back to the shuttered gate.
UNREVIEWED_CLEARING_NOTE = (
    "给 PDF ≠ 清闸。清闸 = 货架条目带**已核验 facts**"
    "（`boardwise parts add <MPN> --lcsc <C码> --category <类别> "
    "--facts <facts.json> --verified`；C 码来源：立创商城搜索）"
    "——喂 PDF（`parts fetch --file`）只写出 `facts_trust: candidate` 的候选，"
    "候选不驱动规则、也不清闸（`parts hunt --apply-facts` 过闸写 machine_verified，"
    "只驱动计算且待人工确认，见 docs/parts.md）；另一条通道是审查者自己标记未知"
    "（`boardwise need-datasheet`），它只会让本节变长，不会让它变空。"
    "**第三通道**（191A）：工程师明示接受这颗的未知——"
    "`boardwise parts accept-unknown <MPN|位号> --reason \"<为什么接受>\" "
    "[--board <板名>] [--intent <合同>]`，写进设计意图合同；"
    "该件从本节移到报告的 `accepted_unknown[]`（它不再挂在 `incomplete` 上，"
    "本轮 verdict 实际是多少看 `completion.verdict`——别的缺口还在时仍是 `incomplete`；"
    "但结论里一直写着「另有 N 颗工程师接受未审」），撤销加 `--revoke`。"
)


def unreviewed_clearing_note(shelf_path: str = "") -> str:
    """The clearing instruction, with **the shelf this run read** named (186-H2).

    The constant above says *what* clears the gate (verified facts on the shelf)
    and not *where* — which was enough while the answer was always the file
    beside the working directory, and wrong the moment the exe grew a shelf of
    its own: a reader who curated a file the review never opened had followed the
    instruction exactly and seen nothing change. So the report prints the path it
    read, and the write command that names the same file.

    ``shelf_path`` empty (a hand-built report, a caller that could not name one)
    returns the constant unchanged: the honest degradation is the older wording,
    not a `<该路径>` placeholder that never resolves to anything.
    """
    if not shelf_path:
        return UNREVIEWED_CLEARING_NOTE
    return (
        UNREVIEWED_CLEARING_NOTE
        + f"本次审查读的货架就是 {shelf_path}——"
        f"facts 要写进**这一架**才算数（`boardwise parts add <MPN> --lcsc <C码> "
        f"--category <类别> --facts <facts.json> --verified --library {shelf_path}`，"
        f"报告里这行是 `shelfPath`）。"
    )


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


#: Characters a file name may carry that an identity token never does: the
#: separator/hyphen/underscore/dot family, plus the spaces a hand-renamed
#: download picks up. Dropped on **both** sides of the loose comparison so
#: `OCP8201ASAD`, `OCP-8201-ASAD` and `ocp 8201 asad` are one token.
_IDENTITY_NOISE_RE = re.compile(r"[^0-9a-z]+")


def _identity_token(text: str) -> str:
    """The comparison form of an identity: lowercase, letters and digits only."""
    return _IDENTITY_NOISE_RE.sub("", (text or "").casefold())


def _local_datasheet(
    directory: Path | None, *needles: tuple[str, str]
) -> tuple[Path | None, str]:
    """``(PDF, which identity matched)`` — ``needles`` are ``(value, identity)``.

    Two passes, strongest reading first (task 186 §B):

    * the **literal** one — the lowercased value inside the lowercased file
      name, which is what this matcher has always done;
    * the **normalised** one — :func:`_identity_token` on both sides and the
      value inside the file *stem*, so a file named `OCP-8201-ASAD_v1.2.pdf`
      still answers for a device the board calls `OCP8201ASAD`. The value is
      compared against the whole normalised name as well as the stem, because
      the token that matters may span the dot (`ACME-8201 rev B.pdf`).

    The caller lists its needles in evidence order (MPN, C-number, device
    name) and the answer says **which one** hit: a document found under the
    device's name is weaker evidence than one found under its MPN, and a report
    that could not tell the two apart would be claiming the stronger one.
    """
    if directory is None:
        return None, ""
    folder = Path(directory)
    if not folder.is_dir():
        return None, ""
    wanted = [
        (value.strip(), value.strip().lower(), identity)
        for value, identity in needles
        if value and value.strip()
    ]
    if not wanted:
        return None, ""
    files = sorted(folder.glob("*.pdf"))
    for _, lowered, identity in wanted:
        for path in files:
            if lowered in path.name.lower():
                return path, identity
    for path in files:
        stem = _identity_token(path.stem)
        whole = _identity_token(path.name)
        for token, _, identity in wanted:
            token = _identity_token(token)
            if token and (token in stem or token in whole):
                return path, identity
    return None, ""


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


def shelf_can_drive_rules(entry: object | None) -> bool:
    """Can a rule act on this shelf entry? Facts **and** a category (188B).

    Two requirements, one answer. The facts half is 039's gate (a `candidate`
    leaves ``entry.facts`` None, so it reads as "no facts" here without this
    function knowing the field exists); the category half is 188B's
    tightening (186 中2) — `rules.facts._category_state` answers UNKNOWN for a
    verified entry whose `category` is empty, so "the shelf has this part" and
    "the shelf can judge it" are different claims and the gate must not credit
    the weaker one.

    **522: a machine-verified entry is not judged either.** Its facts *are* in
    ``entry.facts`` (the calculation rules read them), so the "no facts" half of
    this gate no longer catches it — and it must not close a review item on the
    strength of a machine's reading. This function's question is 「can the review
    stop here」, and for that tier the answer is no until a person signs the facts
    (see :func:`shelf_machine_unconfirmed`, which is how the row says so instead
    of pretending the shelf has nothing).
    """
    if entry is None or getattr(entry, "facts", None) is None:
        return False
    if getattr(entry, "facts_trust", "") == FACTS_TRUST_MACHINE:
        return False
    # 527D's sweep (H4): the class has a tier of its own now, and a
    # machine-granted class is exactly as unsigned as machine-granted facts —
    # the rules refuse to conclude from it (`_category_state`, `shelf_declaration`),
    # so "the review can stop here" is not true either. Without this the report
    # moved such a part out of `unreviewed_parts` into `reviewed_by_shelf` while
    # a rule was simultaneously answering UNKNOWN about the same part.
    if getattr(entry, "category_trust", "") == FACTS_TRUST_MACHINE:
        return False
    return bool(str(getattr(entry, "category", "") or "").strip())


def shelf_machine_unconfirmed(entry: object | None) -> bool:
    """522: are this entry's facts machine-verified and still unsigned?

    The one shape where the shelf has a complete, evidence-checked fact set that
    a person has not confirmed. It is **not** 「真缺资料」 — the PDF is in the
    entry's own provenance — and it is not 「工具读不懂」 either; it is the third
    class :data:`REASON_CLASS_MACHINE_UNCONFIRMED` exists for. A reader who is
    sent to fetch a datasheet the shelf already holds is the failure mode 186 §A
    spent a batch killing, so this is a named predicate rather than an inline
    comparison each caller re-spells.
    """
    return (
        entry is not None
        and getattr(entry, "facts_trust", "") == FACTS_TRUST_MACHINE
        and getattr(entry, "facts", None) is not None
    )


def shelf_judgement(entry: object | None) -> bool:
    """Did the **shelf** judge this part? One name for the gate above (188B)."""
    return shelf_can_drive_rules(entry)


def shelf_unusable_reason(entry: object) -> str:
    """Why the shelf cannot judge a part from this entry, in the entry's terms.

    Two answers, never one: "no facts recorded" is a curation task, "facts but no
    class" is a classification task, and a message that named the wrong one would
    send the reader to fetch a datasheet the shelf does not need.
    """
    if getattr(entry, "facts", None) is None:
        return (
            "货架没有可驱动规则的 facts"
            + (
                "（条目没有 facts）"
                if getattr(entry, "facts_verified", True)
                else "（候选条目未核验）"
            )
        )
    # 522: the third shape — facts are there and a machine checked the evidence,
    # and this function is still reached (see `shelf_can_drive_rules`: the tier
    # fails that gate on purpose). Reaching the categorisation line here would
    # tell the reader to classify a part whose real gap is a signature.
    if getattr(entry, "facts_trust", "") == FACTS_TRUST_MACHINE:
        return UNKNOWN_REASON_MACHINE_UNCONFIRMED
    return UNKNOWN_REASON_UNCATEGORISED


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
    * its shelf entry carries facts but **no `category`** (188B, 186 中2): the
      facts rules answer UNKNOWN for exactly that shape
      (`rules.facts._category_state`), so the shelf still cannot judge the part —
      and the row says so with its own reason
      (:data:`UNKNOWN_REASON_UNCATEGORISED`), whatever its designator is;
    * it has no MPN, or an MPN whose value code this project refuses, or no
      supplier part number — the three 025 identity signals, kept because they
      are also reasons a datasheet hunt cannot even start.

    …and **not** when the shelf can judge it: an entry resolved through the
    identity chain (:func:`boardwise.core.parts.resolve_facts` — MPN, then
    C-number, then the device name) that carries `facts` a rule may act on **and**
    a non-empty `category` (:func:`shelf_judgement`, which is that pair in one
    place). "The shelf cannot judge this part" is the section's own definition,
    and a part whose verified facts are on the shelf is judgeable whatever its
    board fields say — the 025 signals stay as the row's *reasons* on rows that
    are still unreviewed, but a part relisted only because of them, while the
    shelf holds the datasheet the reader was being sent to find, is the gate lying
    about the work left (task 186 §A: 喂 PDF 清不掉闸). `mayClaimPassed` (053)
    follows the same rule: it asks whether a part was left unjudged by the
    shelf, and this one was not.

    Each entry carries the three channels' real state, and the CLI only claims
    what it can measure: `engineer` (a local PDF in the datasheet folder —
    `parts fetch --file` puts one there, and the name step is what finds one
    filed under the device name), `lcsc` (the shelf entry's own
    `datasheetPdfUrl`/`datasheetUrl`, which is what `parts fetch` downloads),
    `official` (never the CLI's — it hands over the queries instead).
    """
    from ..core.parts import (
        FACTS_KEYS,
        IDENTITY_LCSC,
        IDENTITY_MPN,
        IDENTITY_NAME,
        is_ic_designator,
        resolve_facts,
    )

    known = {
        (entry["designator"], tuple(board_titles(entry.get("boards")))): entry
        for entry in unknown_parts(model)
    }
    folder = Path(datasheet_dir) if datasheet_dir else None
    out: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        # 190：位号前缀只是兜底。元数据/货架**声明**它是无源件（U 位号的 330 kΩ
        # 电阻）就不按 IC 问手册。**192B ⑤ 更正了这里的旧注释**：它曾说这条豁免
        # 「只会多问，不会少问」——判型读错时正相反，一颗目录名带「电容」的触摸
        # 按键芯片会就此静默掉出未审闸。现在豁免只给 ≤ MAX_PASSIVE_PINS 脚的件，
        # 且每一颗被豁免的件都在 `completion.declaredPassiveExempt` 与 report.md
        # 里留名（declared_passive_exemptions）。
        is_ic = is_ic_designator(designator) and not _declared_passive(component)
        name = str(component.props.get("device_name") or "").strip()
        entry = None
        matched_by = ""
        if library is not None:
            entry, matched_by = resolve_facts(
                library,
                mpn=(component.mpn or "").strip(),
                lcsc=(component.lcsc_part or "").strip(),
                name=name,
            )
        judged = shelf_judgement(entry)
        if judged:
            continue
        facts = {}
        if entry is not None:
            facts = entry.facts if entry.facts is not None else (entry.candidate_facts or {})
        # 188B (186 中2): "the shelf has this part" and "the shelf can judge it"
        # are different claims, and the second one needs a `category` as well as
        # facts — `rules.facts._category_state` answers UNKNOWN for a verified
        # entry with no category, so a part whose entry carries facts but no class
        # is still work the review cannot finish.
        uncategorised = bool(
            entry is not None
            and entry.facts is not None
            and not str(entry.category or "").strip()
        )
        no_driving_facts = not shelf_can_drive_rules(entry)
        # 522: the third class. The shelf holds a complete, evidence-checked fact
        # set nobody has signed — so the row stays (it is still an open item, and
        # §5.4 of the task book is explicit that this tier must not walk a part
        # out of the gate) but its reason names a **signature**, not a hunt.
        machine_unconfirmed = shelf_machine_unconfirmed(entry)
        reasons = list(known.get((designator, tuple(boards)), {}).get("reasons") or [])
        if not (is_ic and no_driving_facts) and not uncategorised and not reasons:
            continue
        if machine_unconfirmed and UNKNOWN_REASON_MACHINE_UNCONFIRMED not in reasons:
            reasons = reasons + [UNKNOWN_REASON_MACHINE_UNCONFIRMED]
        if uncategorised and UNKNOWN_REASON_UNCATEGORISED not in reasons:
            # Always named, whatever the 025 reasons say: it is the reason the
            # shelf cannot judge this part, which is what this section answers.
            reasons = reasons + [UNKNOWN_REASON_UNCATEGORISED]
        elif is_ic and no_driving_facts and not reasons:
            reasons = (
                [shelf_unusable_reason(entry)]
                if entry is not None
                else ["货架没有这颗料"]
            )
        mpn = (component.mpn or "").strip()
        manufacturer = (entry.manufacturer if entry is not None else "") or str(
            component.props.get("manufacturer") or ""
        )
        local, local_by = _local_datasheet(
            folder,
            (mpn, IDENTITY_MPN),
            (component.lcsc_part or "", IDENTITY_LCSC),
            (name, IDENTITY_NAME),
        )
        entry_url = (entry.datasheetPdfUrl if entry is not None else "") or ""
        page_url = (entry.datasheetUrl if entry is not None else "") or ""
        channels = {
            CHANNEL_ENGINEER: {
                "ok": local is not None,
                "detail": (
                    f"工作区有本地手册 {local.name}"
                    + (
                        "（按器件名匹配，证据弱于 MPN/供应商码）"
                        if local_by == IDENTITY_NAME
                        else ""
                    )
                    if local is not None
                    else f"{UNREVIEWED_DATASHEET_DIR}/ 下没有这颗料的 PDF"
                    "（工程师给手册用 `parts fetch --file`）"
                ),
                "path": str(local) if local is not None else "",
                "matchedBy": local_by,
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
            "shelfMatchedBy": matched_by,
            "factsVerified": (entry.facts_verified if entry is not None else None),
            # 522 §5.1: the tier beside the boolean. `factsVerified` keeps its
            # meaning (a person signed it) so every consumer written before this
            # batch is unchanged; `factsTrust` is the three-valued answer, and a
            # machine-verified row is visibly different from both a candidate and
            # a signed claim.
            "factsTrust": (
                getattr(entry, "facts_trust", "") if entry is not None else ""
            ),
            "factsPresent": sorted(facts),
            "missingFacts": (
                [key for key in FACTS_KEYS if key not in facts] if is_ic else []
            ),
            "channels": channels,
            **_board_field(
                boards,
                mpn=mpn,
                name=str(component.props.get("device_name") or component.value or ""),
                value=component.value,
            ),
        })
    return out


def reviewed_by_shelf(model: DesignModel, *, library: object | None = None) -> list[dict]:
    """The parts the shelf **judged** — the rows that left the 未审 list (188B).

    The complement of :func:`unreviewed_parts`, computed from the same chain and
    the same gate (:func:`shelf_judgement`), so the two lists cannot disagree
    about one part. It exists because a judged row used to vanish without trace:
    a part whose entry was found by **device name** — 186 §B's weaker step — left
    `unreviewed_parts`/`needs_datasheet` and the report never said the shelf had
    claimed anything about it, let alone how it had been identified. The report
    now carries this list (added, never a rename: `report["reviewedByShelf"]`),
    so "why is U3 not on the list?" is answerable from the JSON.

    ``matchedBy`` is the identity step that matched (:data:`IDENTITY_MPN` /
    :data:`IDENTITY_LCSC` / :data:`IDENTITY_NAME`), the same vocabulary
    `unreviewed_parts[].shelfMatchedBy` and `parts missing[].matchedBy` use. A
    part on no shelf is not here — nothing judged it — and neither is one whose
    entry has no facts or no category: those are :func:`unreviewed_parts`' rows.
    """
    from ..core.parts import resolve_facts

    if library is None:
        return []
    out: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        entry, matched_by = resolve_facts(
            library,
            mpn=(component.mpn or "").strip(),
            lcsc=(component.lcsc_part or "").strip(),
            name=str(component.props.get("device_name") or "").strip(),
        )
        if not shelf_judgement(entry):
            continue
        out.append({
            "designator": designator,
            "shelfKey": entry.key,
            "shelfMatchedBy": matched_by,
            "category": str(entry.category or ""),
            "factsVerified": bool(entry.facts_verified),
            # 522 §5.1: the same additive key as on `unreviewed_parts[]`. This
            # list is the judged half, so every row here is `verified` today; the
            # key is present anyway, because a reader joining the two lists must
            # not have to special-case one of them.
            "factsTrust": str(getattr(entry, "facts_trust", "") or ""),
            "factsPresent": sorted(entry.facts or {}),
            **_board_field(
                boards,
                mpn=str(component.mpn or "").strip(),
                name=str(component.props.get("device_name") or component.value or ""),
                value=component.value,
            ),
        })
    return out


# --------------------------------------------------------------------------
# accepted_unknown — 工程师明示「这颗的未知我接受」(191A)
# --------------------------------------------------------------------------

#: The four states one `accepted_unknown[]` row can carry (three until 192B ⑦).
#: One name per row, because they send the reader to different places and a row
#: that collapsed them would be unanswerable ("the contract says U7 — but is U7
#: even on this board, and on *which* board?"):
#:
#: * ``accepted`` — the acceptance moved this part off `unreviewed_parts` on this
#:   run: it is on the board, the shelf cannot judge it, and the engineer said so;
#: * ``not-unreviewed`` — the contract still carries the acceptance, but the part
#:   is not on this run's 未审 list (the shelf can judge it now, or the acceptance
#:   names a board the part is not on): nothing was skipped, so nothing is owed —
#:   the row and its reason stay visible because an acceptance is not deleted by
#:   a shelf update;
#: * ``stale`` — the part is **not on the drawing at all**. Same discipline as a
#:   stale intent slot: the entry keeps every byte, gains `stale: true`, and is
#:   reported rather than removed (189B's path, one section over);
#: * ``stale-elsewhere`` — the part is on the drawing, but **not on the board the
#:   acceptance names** (192B ⑦). It used to share ``stale``'s name *and* its
#:   label, so report.md printed 「stale（图纸上已没有）」 over a part sitting on
#:   two other boards — a sentence the reader can see is false one line above, in
#:   the same 未审 list (`.tmp_hole_sew3/probe10_board_scope_label.py`). The two
#:   send the reader to different places: 「图纸上没有」 is a contract entry to
#:   revoke, 「不在 Board9 上」 is a **board name to fix**. ``stale`` stays true for
#:   both (the acceptance does not apply to what it names), and the row's `why`
#:   carries the board names.
STATE_ACCEPTED = "accepted"
STATE_ACCEPTED_NOT_UNREVIEWED = "not-unreviewed"
STATE_ACCEPTED_STALE = "stale"
STATE_ACCEPTED_STALE_ELSEWHERE = "stale-elsewhere"

ACCEPTED_STATES: tuple[str, ...] = (
    STATE_ACCEPTED,
    STATE_ACCEPTED_NOT_UNREVIEWED,
    STATE_ACCEPTED_STALE,
    STATE_ACCEPTED_STALE_ELSEWHERE,
)

#: The two states whose rows carry ``stale: true`` — one acceptance scoped to a
#: board that no longer has the part, whatever the reason. The distinction above
#: is *where the reader goes next*; this one is *whether the acceptance applies*,
#: and both questions are asked of these rows.
STALE_ACCEPTED_STATES: tuple[str, ...] = (
    STATE_ACCEPTED_STALE, STATE_ACCEPTED_STALE_ELSEWHERE,
)


def _board_part_tokens(model) -> dict[str, set[str]]:
    """``{normalized token: board titles}`` for every placement on the board.

    The index the stale test reads, and only that: matching an acceptance against
    an 未审 **row** reads the row's own fields (it already carries `designator` /
    `mpn` / `boards`), while a contract entry whose token moved no row has no row
    to read — so "is this part still on the board?" is answered from the drawing.
    A token from a one-board model maps to an **empty set** ("no board names on
    this model"), which is not the same as "not on the board".
    """
    from ..core.designintent import part_token

    out: dict[str, set[str]] = {}
    for designator, component, boards in _parts_with_boards(model):
        for token in (part_token(designator), part_token(component.mpn)):
            if not token:
                continue
            out.setdefault(token, set()).update(boards)
    return out


def _accepted_matches_row(entry: object, row: dict) -> bool:
    """Does this acceptance name one of the row's tokens — and its board?"""
    from ..core.designintent import part_token

    token = part_token(getattr(entry, "part", ""))
    if not token or token not in {
        part_token(row.get("designator")), part_token(row.get("mpn"))
    }:
        return False
    scoped = str(getattr(entry, "board", "") or "")
    if not scoped:
        return True
    boards = [part_token(title) for title in board_titles(row.get("boards"))]
    # A row that names no board is a one-board model (040b's shape): the token is
    # the whole identity there, and refusing the match would silently disable
    # `--board` on every single-board project.
    return (not boards) or part_token(scoped) in boards


def _accepted_row(entry: object, row: dict, matched_by: str) -> dict:
    """One acceptance that moved a row: the row's own fields + the reason."""
    return {
        "part": str(getattr(entry, "part", "")),
        "state": STATE_ACCEPTED,
        "matchedBy": matched_by,
        "designator": row.get("designator", ""),
        "name": row.get("name", ""),
        "value": row.get("value", ""),
        "mpn": row.get("mpn", ""),
        "supplier": row.get("supplier", ""),
        "reasons": list(row.get("reasons") or []),
        "reason": str(getattr(entry, "reason", "")),
        "who": str(getattr(entry, "who", "")),
        "when": str(getattr(entry, "when", "")),
        "board": str(getattr(entry, "board", "") or ""),
        "stale": False,
        **_board_field(
            row.get("boards"),
            mpn=str(row.get("mpn") or ""),
            name=str(row.get("name") or ""),
            value=str(row.get("value") or ""),
        ),
    }


def _accepted_absent_row(entry: object, tokens: dict[str, set[str]]) -> dict:
    """One acceptance that moved **no** row — with which of the two reasons why."""
    from ..core.designintent import part_token

    token = part_token(getattr(entry, "part", ""))
    scoped = str(getattr(entry, "board", "") or "")
    boards = tokens.get(token)
    # 192B ⑦: three outcomes, and the middle one is *not* the same statement as
    # the first — 「图纸上没有这颗件」 and 「不在这块板上，但在另外两块上」 were one
    # row and one label until now, and the second sent the reader to revoke a
    # contract entry over a part they can see in the list above.
    if boards is None:
        state, stale = STATE_ACCEPTED_STALE, True
        why = "图纸上没有这颗件（合同里记着，只标 stale，不删）"
    elif scoped and boards and part_token(scoped) not in {part_token(name) for name in boards}:
        state, stale = STATE_ACCEPTED_STALE_ELSEWHERE, True
        why = (
            f"这颗件不在 {scoped} 上（在 {'、'.join(sorted(boards))}）——"
            "件还在图纸上，要改的是接受记录点名的板，不是把记录撤掉"
        )
    else:
        state, stale = STATE_ACCEPTED_NOT_UNREVIEWED, False
        why = "这颗件这一轮不在未审清单里（货架已能判，或它已被接受过）"
    return {
        "part": str(getattr(entry, "part", "")),
        "state": state,
        "matchedBy": "",
        "designator": "",
        "name": "",
        "value": "",
        "mpn": "",
        "supplier": "",
        "reasons": [],
        "reason": str(getattr(entry, "reason", "")),
        "who": str(getattr(entry, "who", "")),
        "when": str(getattr(entry, "when", "")),
        "board": scoped,
        "stale": stale,
        "why": why,
    }


def accepted_unknown_section(
    model,
    unreviewed: list[dict] | None,
    accepted: Iterable[object] | None,
) -> tuple[list[dict], list[dict]]:
    """``(unreviewed without the accepted parts, accepted_unknown rows)`` — 191A.

    The move the batch is about, in one function: an engineer's acceptance takes a
    part **out of** `unreviewed_parts` (so the datasheet gate no longer owes it,
    and `completion.verdict` may stop being `incomplete`) and **into** a section of
    its own, where the reason, the who, the when and — when the drawing moved under
    it — the `stale` mark are all still readable. Nothing is dropped silently: a
    contract entry that matched nothing still comes back as a row, saying which of
    the three states it is in.

    The pairing is by the row's own `designator`/`mpn` and the entry's `board`
    scope (:func:`_accepted_matches_row`), the *first* matching entry wins on a
    duplicated token, and the order of both lists is preserved — the report reads
    the way the two sources read.
    """
    rows: list[dict] = []
    remaining: list[dict] = []
    entries = list(accepted or [])
    if not entries:
        return list(unreviewed or []), []
    from ..core.designintent import part_token

    tokens = _board_part_tokens(model)
    used = [False] * len(entries)
    for row in unreviewed or []:
        found = None
        for index, entry in enumerate(entries):
            if used[index] or not _accepted_matches_row(entry, row):
                continue
            found = index
            break
        if found is None:
            remaining.append(row)
            continue
        used[found] = True
        entry = entries[found]
        matched_by = (
            "designator"
            if part_token(row.get("designator")) == part_token(getattr(entry, "part", ""))
            else "mpn"
        )
        rows.append(_accepted_row(entry, row, matched_by))
    for index, entry in enumerate(entries):
        if not used[index]:
            rows.append(_accepted_absent_row(entry, tokens))
    return remaining, rows


#: What the accepted-unknown section says the acceptance did to the verdict, per
#: verdict. Three sentences, because there are three outcomes and one of them is
#: **not** "the verdict left `incomplete`": an engineer may accept one part while
#: the board still owes a datasheet for another, and 192B ⑪ measured the section
#: claiming otherwise — 「它们不再让 `completion.verdict` 停在 `incomplete`」
#: printed two lines above a `verdict: incomplete` whose `verdictWhy` named the
#: other open items. The claim is now read from this run's own verdict.
ACCEPTED_VERDICT_CLAUSES: dict[str, str] = {
    "incomplete": (
        "——本轮 verdict **仍是** `incomplete`（还有别的缺口，见 `completion.verdictWhy`）："
        "这几颗自己的未知已经不欠了，是别的项把它按住的，"
    ),
    "complete-with-open-items": (
        "——接受让 verdict 不再因**这几颗**停在 `incomplete`，本轮值就是 "
        "`complete-with-open-items`（一颗没人判过的件是开口项，不是已结项）："
    ),
    "complete": (
        "——本轮 verdict 是 `complete`（这几颗并非决定它的项）："
    ),
}


def accepted_verdict_clause(completion: dict) -> str:
    """The accepted-section sentence about this run's own verdict (192B ⑪)."""
    verdict = str((completion or {}).get("verdict") or "")
    clause = ACCEPTED_VERDICT_CLAUSES.get(verdict)
    if clause is None:
        # A hand-built report with no `completion` section: say where to read the
        # answer instead of asserting one (the same rule as `_report_chains`'
        # fallback — a missing section is a reading, not a licence to guess).
        return "——它对本轮 verdict 的影响以 `completion.verdict` 为准（本报告无该节）："
    return clause


def part_on_board(model, token: str, board: str = "") -> bool:
    """Is ``token`` a designator or MPN of a placement on this board (191A)?

    The one reading `parts accept-unknown` uses to tell a typo from an acceptance
    that precedes the drawing: the same token rule and the same board scope the
    report pairs rows with, asked of the drawing directly. Public because the CLI
    is another layer and a private helper crossing that line is what
    `tests/test_layer_rules.py` refuses — and because the answer belongs to the
    engine that owns the walk (`_parts_with_boards`), not to the command.
    """
    from ..core.designintent import part_token

    wanted = part_token(token)
    if not wanted:
        return False
    scope = part_token(board)
    for designator, component, boards in _parts_with_boards(model):
        if wanted not in {part_token(designator), part_token(component.mpn)}:
            continue
        if scope and boards and scope not in {part_token(name) for name in boards}:
            continue
        return True
    return False


def accepted_unknown_counts(rows: list[dict] | None) -> dict:
    """``{state: rows}`` over one `accepted_unknown[]` list, sorted keys.

    Counted from the rows themselves (never from a second read of the contract),
    so the verdict, the conclusion and the section cannot disagree. `accepted` is
    the number the verdict's open items and the quotable conclusion use: it is the
    count of parts this run **skipped a judgement on** — a `not-unreviewed` entry
    skipped nothing, and a `stale` one is not on the board to skip.
    """
    counts = {state: 0 for state in ACCEPTED_STATES}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        state = str(row.get("state") or "")
        if state in counts:
            counts[state] += 1
    return dict(sorted(counts.items()))


def accepted_unknown_count(rows: list[dict] | None) -> int:
    """`len(accepted_unknown[])` — every row, whatever state (191A)."""
    return sum(1 for row in rows or [] if isinstance(row, dict))


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
    counted once by :func:`marked_parts`.

    A folded row keeps its designator under ``part``, the identity fields of the
    **first** placement it saw (185-中1: ``channels``/``mpn``/``supplier``/
    ``missingFacts``, unchanged; 190 adds ``shelfMatchedBy`` — the same key and
    the same meaning as ``unreviewed_parts[].shelfMatchedBy``, which 186 had put
    on the row and the fold was dropping), and — added by 185-中1 — a ``boards``
    list saying **which placements that one designator stands for**: ``{"board",
    "mpn", "name", "value"}`` per board. It exists because the fold is by
    designator, and a project's designator is not one part: measured on the 3-board
    fixture, 15 of the folded designators are on more than one board with
    **different** MPNs, names and values (`C2` is a no-MPN capacitor on one board
    and a code-bearing part on another). Reporting only the first one made the
    worklist read "one part, one datasheet" about a question that is really "two
    boards, two parts", while ``report.md`` said the opposite in another section
    (``conn-duplicate-designators``). The per-board rows are deduplicated, so two
    placements with identical identity on one board read as one line; ``boards``
    is empty for a model with no board identity at all (a plain ``DesignModel``),
    never omitted.

    **191B**: that dict shape is now the shape ``unreviewed_parts[].boards`` and
    the other part rows use too — one shape, one reader
    (:func:`board_rows` / :func:`board_titles`), and the old title list is still
    read for a report written before it.
    """
    seed_by_part: dict[str, dict] = {}
    boards_by_part: dict[str, list[dict]] = {}
    for row in unreviewed or []:
        if not isinstance(row, dict):
            continue
        part = str(row.get("designator") or "")
        if not part:
            continue
        seed_by_part.setdefault(part, row)
        placements = boards_by_part.setdefault(part, [])
        # 191B: the seed row's own `boards` is already the canonical dict shape
        # on a 191B report; `board_rows` is the compatibility read for a title
        # list (an older report, or a caller that built the seed by hand — the
        # 187B test does), which it expands with the row's identity exactly as
        # this fold did before.
        for placement in board_rows(
            row.get("boards"),
            mpn=str(row.get("mpn") or ""),
            name=str(row.get("name") or ""),
            value=str(row.get("value") or ""),
        ):
            if placement not in placements:
                placements.append(placement)

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
            # 190: the identity step that matched this part, carried through from
            # the `unreviewed_parts` row (186 put it there; the folded worklist
            # row was dropping it). Same name and same meaning as
            # `unreviewed_parts[].shelfMatchedBy` and `reviewedByShelf[].shelfMatchedBy`
            # — empty for a part on no shelf, and for the `marked` trigger a part
            # the reviewer wrote down before any reading existed.
            "shelfMatchedBy": (seed.get("shelfMatchedBy") or "") if seed is not None else "",
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
            "boards": list(boards_by_part.get(part) or []),
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
            "boards": list(boards_by_part.get(part) or []),
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
    declared_version: int | None = None,
) -> dict:
    """The report's `intent` section — what the contract answers and what it owes.

    Built from :func:`boardwise.core.designintent.merge`'s facts, so the section,
    the regenerated file and the rendered view are one arithmetic (the report only
    renders what the JSON says — its own rule since 025). ``missing`` is every slot
    the enumeration owes and the contract does not answer; ``required`` is the
    subset the design doc names as a *must* (a rail's voltage declaration, a
    signal's polarity), and each of those carries its `intent-missing` line.
    ``hints`` is the questions the document asks back. ``stale`` and
    ``staleEntries`` are the same marks in the two shapes their two readers need
    (189B ④): the count over ``section:identity`` strings, and the
    ``{section, object}`` rows report.md names a slot with.

    `facts` is ``None`` only when nothing could be enumerated *and* no contract was
    read — which the caller reports as an absent section rather than an empty one.
    """
    facts = facts or {}
    missing = list(facts.get("missing") or [])
    required = [row for row in missing if row.get("required")]
    hints = list(facts.get("hints") or [])
    # 189B ④: two readings of the same transition, and the *renderer* needs the
    # second one. :func:`boardwise.core.designintent.merge` files the mark twice —
    # ``stale`` as the ``section:identity`` strings a count is taken over, and
    # ``staleEntries`` as the ``{section, object}`` dicts a reader names a slot
    # with. Reading the strings here is what made a non-empty stale list take the
    # whole report down (``entry.get`` on a ``str``).
    stale = list(facts.get("stale") or [])
    stale_entries = list(facts.get("staleEntries") or [])
    # 192B ⑨: two different questions, and until now one name in `totals`.
    # :func:`~boardwise.core.designintent.merge` files ``stale`` as the entries it
    # marked **on this pass** and ``staleEntries`` as **every** entry that is
    # stale now (an old mark stays stale without being re-marked), so
    # ``len(stale)`` and ``len(staleEntries)`` are equal only the first time. The
    # section's heading counts the second, and `totals` used to carry the first
    # under the *same key name as the section's own list* — so report.md printed
    # 「图纸里已消失（stale，不删只标）1」 four lines above 「合同里记着、图纸里已没有
    # 的对象（5，不删只标）」, about one document (`.tmp_hole_5/runD`). Two names
    # now: `newlyStale` for this pass's marks, `staleTotal` for the standing set.
    added = list(facts.get("added") or [])
    extras = list(facts.get("extras") or [])
    # 189B ③: three states, not two. A contract that is on disk and cannot be
    # read (a schema this build refuses) is *not* a missing contract: the reader
    # sent to 「不存在」 goes looking at paths and uuids, which is the wrong desk.
    contract_state = (
        "unreadable" if read_error else ("read" if present else "absent")
    )
    return {
        "contract": {
            "file": contract_file,
            "present": bool(present),
            "readError": read_error,
            "state": contract_state,
            # 192B ⑩: two versions, because they were one word printed as one
            # number. `intentVersion` is what **this build** reads (the constant a
            # contract must match to be readable at all); `declaredIntentVersion`
            # is what the **file** declares, or ``None`` when there is no file to
            # declare anything — absent, or on disk and unreadable. report.md used
            # to print the build constant as 「契约版本：intentVersion N」 even for
            # a contract that does not exist, which reads as a statement about the
            # file.
            "intentVersion": contract_version,
            "declaredIntentVersion": declared_version,
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
            # 192B ⑨: `newlyStale` is what this regeneration marked;
            # `staleTotal` is every stale mark the section prints, which is what
            # the 「合同里记着、图纸里已没有的对象（N）」 heading says. Two names,
            # because one document was being described by two numbers under one
            # word (see the reading above).
            "newlyStale": len(stale),
            "staleTotal": len(stale_entries),
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
        "staleEntries": stale_entries,
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

    The contract's first bullet has **three** states, not two (189B ③): 读入 / 读不了
    （on disk, unreadable — `<原因>` is the reader's message, so the next move is a
    schema one） / 不存在（a file to create）. The two failures used to share one word
    and the shared word sent the reader after paths and uuids.
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
    # 192B ⑩: 「文件声明」 and 「本 build 读」 are two different sentences and used
    # to be one number — the build constant — printed as if it described the file.
    # A contract that is absent or unreadable declares nothing, and the line now
    # says so instead of quoting a version nobody wrote.
    declared = contract.get("declaredIntentVersion")
    if declared is None:
        # Wording matters here: the bullet above already says 「不存在」 for a
        # contract that is not on disk, and a second use of the same word for a
        # *different* state (read, but the caller handed no declared version) is
        # how the two got confused in the first place.
        declared_text = (
            "文件声明的版本没拿到（调用方没给）"
            if str(contract.get("state") or "") == "read"
            else "文件没声明（本次没有读入合同）"
        )
    else:
        declared_text = f"文件声明 `intentVersion {declared}`"
        if int(declared) != int(contract.get("intentVersion") or 0):
            declared_text += "（与本 build 能读的版本不同——读不下去时按读不了报）"
    lines.append(
        f"- 契约版本：{declared_text}；本 build 读 `intentVersion "
        f"{contract.get('intentVersion', 0)}`；"
        f"弱词：`{section.get('provenance') or '（无条目）'}`"
        + ("（**草稿**：" + "；".join((section.get("draftReasons") or [])[:2]) + "）"
           if section.get("draft") else "")
    )
    if section.get("draft"):
        lines.append(f"- {INTENT_DRAFT_NOTE}")
    # 192B ⑨: the delta line reports the **delta** and the **total** separately,
    # because they are different numbers about one document and the heading below
    # counts the total. Until this batch both were printed as 「stale」.
    if totals.get("addedEntries") or totals.get("newlyStale") or totals.get("unregisteredAnswers"):
        lines.append(
            f"- 重生成差量：新增 TODO 条目 {totals.get('addedEntries', 0)} · "
            f"本轮新标 stale {totals.get('newlyStale', 0)}"
            f"（stale 合计 {totals.get('staleTotal', 0)}，不删只标）· "
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
    stale_rows = stale_mark_rows(section)
    if stale_rows:
        lines.append(f"### 合同里记着、图纸里已没有的对象（{len(stale_rows)}，不删只标）")
        lines.append("")
        lines.extend(stale_rows)
        lines.append("")
    if totals.get("missing"):
        lines.append(
            f"- 其余 {totals.get('missing', 0) - len(required)} 槽仍是 TODO（欠账不是空白）："
            f"逐槽填进合同（`{path}`），填不出来就**显式问工程师**，不许编。"
        )
    lines.append(f"- {section.get('note', INTENT_NOTE)}")
    lines.append("")


def stale_mark_rows(section: dict) -> list[str]:
    """The `stale` list as report.md's bullets — **both** shapes of it (189B ④).

    The rows come from ``staleEntries`` (``{section, object}`` — the shape this
    renderer names a slot with, and the one 090's facts have carried all along as
    ``facts["staleEntries"]``; ``checkup`` used to read ``facts["stale"]``, the
    ``section:identity`` strings the count is taken over, and `entry.get` on a
    ``str`` took the whole report down). A report written by an older build — or
    by hand — carries the strings under ``stale`` with no ``staleEntries`` at all,
    and a re-gate re-renders that report: those rows print as the keys they are
    rather than vanishing, because a stale mark that silently stops being printed
    is the failure this section exists to prevent.
    """
    rows: list[str] = []
    for entry in section.get("staleEntries") or []:
        if isinstance(entry, dict):
            rows.append(
                f"- `{entry.get('object')}`（{entry.get('section')}）—— 值保留，只标 stale"
            )
        else:  # a hand-built row: print what there is instead of raising on it
            rows.append(f"- `{entry}` —— 值保留，只标 stale")
    if not rows:
        rows = [
            f"- `{key}` —— 值保留，只标 stale"
            for key in (section.get("stale") or [])
        ]
    return rows


def _render_guarded(lines: list[str], name: str, body) -> None:
    """Render one section of report.md; a section that raises costs its own (189B ④).

    The rules spend minutes before a report exists, so a rendering mistake must not
    turn that into zero output: the half-written section is dropped, a named error
    row takes its place, and the sections on either side still print. ``report.json``
    is written before ``report.md`` and stays complete either way — this is what
    keeps the two from failing together.

    Bounded on purpose: this is the *writing* stage, never the rule walk (a rule
    that raises is ``rules_errored``, and that path already reports rather than
    hides).
    """
    mark = len(lines)
    try:
        body()
    except Exception as exc:  # noqa: BLE001 — a report must still be written
        del lines[mark:]
        lines.append(
            f"> **{name} 节渲染失败：{type(exc).__name__}: {exc}**"
            " —— 本节的 Markdown 渲染不了；`report.json` 里这一节的读数仍是完整的，"
            "请按 JSON 读本节（其余各节照常）"
        )
        lines.append("")


# --------------------------------------------------------------------------
# warning triage (039 批② §WI-2)
# --------------------------------------------------------------------------

#: The verdict vocabulary the AI fills, one of these three and nothing else.
TRIAGE_VERDICTS = ("有益", "有害", "无害")

#: 537B: the fourth **answer** — deliberately not a fourth verdict. The three
#: words above answer 「这条警告说的是什么」, which needs the warning's own text; a
#: source that only returned totals (see :data:`ERC_TEXT_UNAVAILABLE`) cannot
#: answer it, so what a reviewer can honestly write against such a row is 「需要
#: 人工看」. It sits **beside** :data:`TRIAGE_VERDICTS` and not inside it, because
#: every reader of the three-word set (the 063 gate, the report's table, the
#: exit-code arithmetic) treats a member as a *closed* judgement — and this one is
#: not closed: the row stays in `completion.warningsPendingTriage` and is counted
#: a second time as `warningsNeedsManual`.
TRIAGE_UNJUDGEABLE = "needs-manual"

#: What `--verdict` accepts: the three words, then the one word that says a human
#: must look. argparse reads this list; the gate below keeps the two sets apart.
TRIAGE_VERDICT_CHOICES = (*TRIAGE_VERDICTS, TRIAGE_UNJUDGEABLE)


def triage_slot_text_missing(slot: dict) -> bool:
    """Whether this slot has no per-item text to judge — the 537B §2 criterion.

    Two readings, in this order:

    * an **empty** ``text`` is the statement itself: the host ERC answer is totals
      only (:data:`ERC_TEXT_UNAVAILABLE`), so its slot carries ``text: ""`` and a
      `textUnavailable` sentence saying why;
    * on a ``host-erc`` row a **missing** field means the same thing, because the
      source is the evidence — the host's answer has no items to put there. This
      is the follow-up the reviewer measured: with only the empty-field reading, a
      hand-trimmed `report.json` (delete `text`, keep the verdict) was judgeable
      again and cleared pending exactly like the seq 320 verdict did. The field is
      not a formality a caller can remove; on this source its absence *is* the
      「没有逐条文本」 statement.

    An absent field on any **other** slot is still not that statement: every slot
    :func:`warning_triage_slots` generates stamps the field (063 §1's public
    shape), so a dict without it and without a `host-erc` source is a report
    written before that shape existed or a count somebody built by hand — refusing
    a verdict there would change the meaning of slots this gate never met, and the
    three-word behaviour of 063/070 is a contract (537B §5).

    A `host-erc` row that *does* carry text (a future read interface, say) is not
    textless: the three words become admissible for it and nothing has to move.
    """
    slot = slot or {}
    if "text" in slot:
        return not str(slot.get("text") or "").strip()
    return str(slot.get("source") or "") == "host-erc"


def triage_verdict_is_admissible(slot: dict, verdict: str) -> bool:
    """**The one predicate**: may this verdict be recorded against this slot?

    Two doors, one rule (537B §2) — `boardwise triage` asks it *before* writing
    (so a refusal leaves both the report and the sidecar untouched), and
    :func:`merge_triage_sidecar` asks it while folding a sidecar back in (so a
    hand-edited `warning-triage.json` cannot do what the command refuses). The
    question is always asked of the **generated slot**, never of the sidecar's own
    `text` field — that field a hand edit also controls, and answering from it
    would hand the gate back to whoever is trying to get around it.

    * an empty verdict decides nothing; the merge treats it as "no decision to
      put back" and it is admissible here for exactly that reason;
    * :data:`TRIAGE_UNJUDGEABLE` is admissible everywhere: it is the honest answer
      to a row nobody can judge from the report alone;
    * a three-word verdict needs the slot's own text. Measured twice (025 §0,
      039 批②): the host's ERC answer is per-kind totals with no items, and the
      original session marked one of them 「有害」 anyway — seq 320 wrote the
      verdict, seq 435 read `pending = 0`, and no one had seen a warning. A count
      is not a warning, so a count cannot be judged;
    * a word outside :data:`TRIAGE_VERDICT_CHOICES` is not a judgement at all.

    Textlessness is read by :func:`triage_slot_text_missing` — an **empty** `text`
    field, which is what the generator writes for a row whose source gave no
    items.
    """
    verdict = str(verdict or "").strip()
    if not verdict:
        return True
    if verdict == TRIAGE_UNJUDGEABLE:
        return True
    if verdict not in TRIAGE_VERDICTS:
        return False
    return not triage_slot_text_missing(slot)


def triage_slot_is_manual(slot: dict) -> bool:
    """Whether a human still owes this row a look (537B §3)."""
    return str((slot or {}).get("verdict") or "").strip() == TRIAGE_UNJUDGEABLE


def triage_slot_is_closed(slot: dict) -> bool:
    """Whether this slot counts as **judged** — the read side of the same rule.

    One arithmetic for the count, the console line, `report.md` and
    `completion.verdictWhy`: a slot is closed only when it carries a member of
    :data:`TRIAGE_VERDICTS` *and* that verdict is admissible for it. A
    `needs-manual` row, an empty row, and a row somebody hand-edited to 「大概没事」
    are all still pending — an unknown word must not be read as an answer.
    """
    verdict = str((slot or {}).get("verdict") or "").strip()
    return verdict in TRIAGE_VERDICTS and triage_verdict_is_admissible(slot, verdict)

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
            # 516 C4: the rule id under the **snake_case** name the rest of the
            # JSON uses (`findings[].rule_id`), so a triage-slot reader does not
            # have to parse `evidence` for it. The DRC-derived rows still carry
            # the camelCase `ruleId`, and the label readers accept both.
            "rule_id": str(finding.get("rule_id") or ""),
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
    slots: list[dict], entries: list[dict] | None, refused: list[dict] | None = None
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

    **537B §4: a verdict is folded in only if :func:`triage_verdict_is_admissible`
    allows it for the generated slot.** A three-word judgement against a row with
    no text (the host ERC totals — `text` empty) is exactly what seq 320/435
    measured: written by hand into this file, it used to clear the pending count
    without anyone reading a warning. Such an entry is *refused* — not merged, and
    **not** `unmatched` either (its key does exist, so calling it a miss would be
    a false report) — and appended to ``refused`` when the caller asks for the
    list, which is how `checkup` says 「拒收 N 条」 in the report's `notes`. The
    entry stays in the sidecar: an audit trail is never edited from here.
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
        verdict = str(entry.get("verdict") or "").strip()
        if not verdict:
            continue  # a row with no decision is not one to put back
        if not triage_verdict_is_admissible(by_key[key], verdict):
            # Asked of the **slot**, not of the entry's own `text`: see the
            # predicate's docstring — a hand edit controls that field too.
            if refused is not None:
                refused.append(entry)
            continue
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


def merge_needs_datasheet_sidecar(
    unreviewed: list[dict] | None,
    marked: list[dict] | None,
    findings: list[dict] | None = None,
    *,
    designators: list[str] | None = None,
) -> tuple[list[dict], int, int]:
    """Fold ``needs-datasheet.json``'s marks into the worklist on a fresh run (516 A3).

    Returns ``(needs_datasheet, merged, unmatched)``. The datasheet sidecar is
    the reviewer's ⓪ 先问再判 marks — one row per ``(part, pin)``, written by
    ``boardwise need-datasheet`` — and the section is rebuilt from the board on
    every ``checkup``, so without this the marks would read as if nobody had
    marked anything (measured: 15 marks → re-run → ``reviewerMarked`` 0). This is
    the datasheet twin of :func:`merge_triage_sidecar`, and it takes the same
    position: match what still exists, **report** the rest, never delete.

    ``merged`` counts the marks whose ``part`` is a designator this report carries
    (the board may have changed under a mark), and those are the ones folded into
    :func:`needs_datasheet_section`; ``unmatched`` counts the rest — a designator
    that has disappeared, or a typo. An unmatched mark is **kept** in the sidecar
    as the audit trail; only its fold-in fails, and the caller names the count.

    When ``designators`` is empty the report has no designator list to match
    against (an old report, or a synthetic one), so every mark folds in rather
    than being dropped on a fact this function cannot see.
    """
    known = {str(name) for name in (designators or [])}
    rows = [dict(mark) for mark in (marked or []) if isinstance(mark, dict)]
    if known:
        matched = [row for row in rows if str(row.get("part") or "").strip() in known]
        unmatched = len(rows) - len(matched)
    else:
        matched = rows
        unmatched = 0
    section = needs_datasheet_section(unreviewed, matched, findings)
    return section, len(matched), unmatched


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
# 整板报告（154 / E 阶段收口棒 E4）—— 一键出的那一份
# --------------------------------------------------------------------------
#
# The pipeline already writes three files, and each has exactly one job:
# `report.json` is the contract (every machine detail), `report.md` is the ledger
# (complete and mechanical), `review-summary.md` is the skeleton the model fills.
# What was missing is the one xianyuyijinban reads: the ledger is **too verbose for a
# human** (岳 2026-10-11 体验反馈) — it prints one flat table of 160 findings with
# the whole location chain repeated in every row, and an ERROR there does not say
# in one glance 「which board, which designator, what is wrong」.
#
# This section is that file: ERC (schematic side) + DRC (offline geometry / host
# baseline) + module rules (grouped by module) + device rules, grouped
# 「板 → 模块/规则族」, sorted by **severity × module weight**, one human-readable
# line per finding, and one closing line that answers 「整工程能不能投板」. The
# machine detail stays in `report.json`; nothing here is derived that the JSON does
# not already carry (the ledger's own rule since 025).

#: The three weight tiers, smallest rank first. **PCB module-level is heaviest** —
#: 122 第二步「为什么是重中之重」: a green DRC only says 「能造」, the module layer
#: decides 「好不好活」 (noise, heat, EMI, lifetime), so its findings sort above
#: everything else and are what the closing verdict is read against.
WEIGHT_PCB_MODULE = "pcb-module"
WEIGHT_DEVICE = "device"
WEIGHT_GENERIC = "generic"

WEIGHT_RANK: dict[str, int] = {
    WEIGHT_PCB_MODULE: 0,
    WEIGHT_DEVICE: 1,
    WEIGHT_GENERIC: 2,
}

WEIGHT_LABELS: dict[str, str] = {
    WEIGHT_PCB_MODULE: "PCB 模块级",
    WEIGHT_DEVICE: "器件级",
    WEIGHT_GENERIC: "通用",
}

#: **The evidence for the order, written into the report head** — a reader must
#: not have to trust the sort, so each tier says why it sits where it does.
WEIGHT_WHY: dict[str, str] = {
    WEIGHT_PCB_MODULE: (
        "路线图第二步（按模块检查）＝重中之重：DRC 过只说明「能造」，模块级"
        "决定「好不好活」（噪声/发热/EMI/寿命）——权重最高"
    ),
    WEIGHT_DEVICE: (
        "路线图第三步（器件检查）＝收口：封装一致性/极性/丝印/降额，逐颗器件的"
        "物理可实现性——居中"
    ),
    WEIGHT_GENERIC: (
        "第一步 DRC 与原理图侧 ERC／连通性：门票与电路正确性——最轻"
    ),
}

#: 器件级 —— 路线图第三步的四条规则（E1/E2/E3 落地）。
_DEVICE_RULE_IDS: frozenset[str] = frozenset({
    "pcb-footprint-consistency",
    "pcb-polarity-orientation",
    "pcb-silk-designator",
    "pcb-derating-package",
})

#: PCB 侧但属第一步（DRC 规则集元审查）：落「通用」而不是「模块级」。
_GENERIC_PCB_RULE_IDS: frozenset[str] = frozenset({
    "pcb-drc-ruleset-out-of-reference",
})

#: The device family's own group name (one group per board, the four rules
#: together) — the roadmap's 第三步 read as a family rather than folded into a
#: module, because a part can be judged by two modules at once and the device
#: reading is about the *part*.
DEVICE_GROUP_NAME = "器件检查"

#: The catch-all group name, for findings whose rule family the table below does
#: not name. Named for what it is rather than left blank.
OTHER_GROUP_NAME = "其他规则"

#: The severity ranks the sort uses. ERROR first, then WARN, then INFO — the order
#: every other table in the report already prints in.
SEVERITY_RANK: dict[str, int] = {"ERROR": 0, "WARN": 1, "INFO": 2}

#: Rule id → family label, first match wins. Only used for grouping and for the
#: one-line summary's 「依据」; the finding's own `rule_id` is always printed too,
#: so a wrong or missing label never hides which rule spoke.
_RULE_FAMILIES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^pcb-foc-"), "FOC/功率驱动"),
    (re.compile(r"^pcb-regulator-"), "电源调节器"),
    (re.compile(r"^pcb-mcu-"), "MCU 最小系统"),
    (re.compile(r"^pcb-decap-distance$"), "电源去耦"),
    (re.compile(r"^pcb-component-spacing$"), "DFM 通用"),
    (re.compile(r"^pcb-component-off-board$"), "DFM 通用"),
    (re.compile(r"^pcb-track-ampacity$"), "载流（IPC-2221）"),
    (re.compile(r"^pcb-voltage-spacing$"), "安规间距（IPC-2221）"),
    (re.compile(r"^pcb-drc-ruleset-"), "DRC 规则集元审查"),
    (re.compile(r"^pcb-"), "PCB 通用几何"),
    (re.compile(r"^(param|sel)-"), "元件参数/选型"),
    (re.compile(r"^(conn|decap|shunt)-"), "原理图连通性"),
    (re.compile(r"^arch-"), "架构闭合/意图"),
)

#: How much of a finding's message the one-line summary keeps. The message is
#: often a full English sentence with the measurement spelled out; the ledger
#: below carries it whole, and this is the glance line.
ONELINE_MAX_CHARS = 120


def finding_weight(rule_id: str) -> str:
    """The weight tier of one finding, from its rule id ():data:`WEIGHT_RANK`).

    Three tiers, in the roadmap's own vocabulary:

    * **device** — the four 第三步 rules (:data:`_DEVICE_RULE_IDS`);
    * **generic** — everything else, *including* the schematic rules and the two
      PCB-side stage-1 readings (:data:`_GENERIC_PCB_RULE_IDS`);
    * **pcb-module** — every remaining ``pcb-`` rule: the second-step module
      packages (FOC / regulator / MCU) and the generic-layer geometry rules
      (去耦距离 / DFM 间距 / 载流 / 安规) — the whole 「按模块检查」 family.

    Read by prefix rather than by an exhaustive list, so a rule added to
    :data:`~boardwise.engines.pcbreview.BUILTIN_PCB_RULES` later is placed by what
    it *is* (a ``pcb-`` rule that is not one of the device/DRC-set exceptions is a
    module-level reading) instead of silently defaulting to 通用.
    """
    rid = str(rule_id or "")
    if rid in _DEVICE_RULE_IDS:
        return WEIGHT_DEVICE
    if rid in _GENERIC_PCB_RULE_IDS:
        return WEIGHT_GENERIC
    if rid.startswith("pcb-"):
        return WEIGHT_PCB_MODULE
    return WEIGHT_GENERIC


def rule_family(rule_id: str) -> str:
    """The family label of one rule — 「FOC/功率驱动」, 「器件检查」, ….

    The device rules answer with :data:`DEVICE_GROUP_NAME` before the pattern
    table is consulted (their ids also start with ``pcb-`` and would otherwise read
    as 「PCB 通用几何」). Anything the table does not name is
    :data:`OTHER_GROUP_NAME`, which is a reading rather than a guess.
    """
    rid = str(rule_id or "")
    if rid in _DEVICE_RULE_IDS:
        return DEVICE_GROUP_NAME
    for pattern, label in _RULE_FAMILIES:
        if pattern.search(rid):
            return label
    return OTHER_GROUP_NAME


def _first_sentence(text: str) -> str:
    """A message cut to its first sentence, for the one-line summary.

    The ledger prints the message whole; this keeps the glance line a glance. Split
    on the three sentence marks the rules actually use (``。`` ``；`` ``;``) and cap
    the length, adding an ellipsis rather than a silent truncation so a clipped
    line is visibly clipped.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    cut = len(flat)
    for mark in ("。", "；", "; "):
        position = flat.find(mark)
        if position != -1:
            cut = min(cut, position + (1 if mark != "; " else 0))
    clipped = flat[:cut].strip()
    if len(clipped) > ONELINE_MAX_CHARS:
        clipped = clipped[:ONELINE_MAX_CHARS].rstrip() + "…"
    return clipped


def finding_oneline(finding: dict) -> str:
    """One finding as the single readable line the integrated report prints.

    The four things 岳 asked an ERROR to carry (位号/网/问题/依据), in order:

    ``板 · 位号（网 …）—— 问题 〔规则族 / rule_id〕``

    The board is *not* part of this string — the caller prints it under the
    board's heading — so the string names what is left: the designator (or the net
    the finding names, when it names no part), the problem (the message's first
    sentence), and the basis (the family label and the rule id, which stays a
    machine token because that is what other tools match on). Nothing is invented:
    a finding with no refs reads 「（未点名位号）」 rather than borrowing one.
    """
    target = finding.get("target") or {}
    refs = [str(ref) for ref in (finding.get("refs") or []) if str(ref)]
    nets = [str(net) for net in (target.get("net_refs") or []) if str(net)]
    who = "、".join(refs) if refs else "（未点名位号）"
    if nets:
        who += f"（网 {'、'.join(nets)}）"
    problem = _first_sentence(str(finding.get("message") or "")) or "（规则没有给出文字说明）"
    rid = str(finding.get("rule_id") or "")
    return f"{who} —— {problem} 〔{rule_family(rid)} / {rid or '(无规则 id)'}〕"


def _board_links(report: dict) -> list[dict]:
    """The boards the integrated report is split by, in the report's own order.

    ``model.boards`` is the primary partition and its order is the order here. A
    PCB document (``pcb_review.boards[]``) is attached to a schematic board by its
    own ``boardUuid`` link (154); a document whose link is missing or names no
    schematic board is kept as its own entry rather than merged into a guessed one
    — 「板链读不出」 is a reading, and the section says so.

    Each entry is ``{title, pcb, uuid, components, copperLayers}``: ``title`` is
    the schematic board's, ``pcb`` the PCB document's (or ``""``), so a reader sees
    「Board1 / PCB1」 and the two name spaces are never conflated.

    A report with **no** board structure at all (a single ``.enet`` netlist carries
    no ``model.boards`` and no PCB document) gets one synthetic entry named for the
    project, so its findings are grouped by module/rule family instead of all
    landing in the unattributed bucket — 「no board partition」 is not the same
    statement as 「this finding belongs to no board」.
    """
    model = report.get("model") or {}
    model_boards = model.get("boards") or []
    pcb_boards = ((report.get("pcb_review") or {}).get("boards")) or []
    if not model_boards and not pcb_boards:
        source = report.get("source") or {}
        project = source.get("project") or {}
        title = (
            project.get("friendlyName") or project.get("name")
            or source.get("file") or "(本工程)"
        )
        return [{
            "title": str(title),
            "pcb": "",
            "uuid": "",
            "components": model.get("components"),
            "copperLayers": None,
        }]

    by_uuid: dict[str, dict] = {}
    for board in pcb_boards:
        uuid = str(board.get("boardUuid") or "")
        if uuid:
            by_uuid.setdefault(uuid, board)

    links: list[dict] = []
    claimed: set[int] = set()
    for board in model_boards:
        uuid = str(board.get("uuid") or "")
        pcb = by_uuid.get(uuid)
        if pcb is not None:
            claimed.add(id(pcb))
        links.append({
            "title": str(board.get("title") or uuid or "(unnamed board)"),
            "pcb": str((pcb or {}).get("title") or ""),
            "uuid": uuid,
            "components": board.get("components"),
            "copperLayers": (pcb or {}).get("copperLayers"),
            "outlineNote": (pcb or {}).get("outlineNote"),
            # 191C 遗留：`netIdNote` 和 `outlineNote` 是同一个披露通道的两句话
            # （「这块板的读数里丢了什么」），所以它跟着走同一条路——不过滤、不改写，
            # 一路带到人读的 report.md 与 board-report.md。
            "netIdNote": (pcb or {}).get("netIdNote"),
        })
    for board in pcb_boards:
        if id(board) in claimed:
            continue
        links.append({
            "title": str(board.get("title") or "(unnamed PCB)"),
            "pcb": str(board.get("title") or ""),
            "uuid": str(board.get("boardUuid") or ""),
            "components": board.get("components"),
            "copperLayers": board.get("copperLayers"),
            "outlineNote": board.get("outlineNote"),
            "netIdNote": board.get("netIdNote"),
        })
    return links


def _board_of_finding(
    finding: dict, links: list[dict], pcb_titles: set[str]
) -> tuple[int, str]:
    """``(index into links, why)``, or ``(-1, reason)`` when no *single* board claims it.

    A finding carries ``board`` in one of two name spaces: a schematic board title
    (``Board1``) for a stage-1/2/3 schematic finding, or a PCB document title
    (``PCB1``) for a ``pcb-`` finding (钉 4). Both are resolved to the same board
    link — the schematic title directly, the PCB title through the link table —
    so a ``PCB1`` finding lands under the same heading as the schematic ``Board1``
    findings instead of getting a second, unrelated section.

    **163b: titles are not identities.** Two PCB documents may share a title (a
    copy-paste is enough), and the title lookup returned the **first** match, so
    every finding of the second board was merged into the first: one board's
    heading carried another board's findings, with nothing in the report saying
    so. Three answers now, in order:

    * ``boardUuid`` on the finding — when it is there it decides, because a uuid
      is the one name that cannot collide, and a uuid the link table does not
      know is reported rather than falling through to a title that might match
      the wrong board;
    * the title, when **exactly one** link answers to it;
    * ``-1`` with the reason when several links answer — 「无法归因」 is a fact
      about the report, and picking the first is a silent guess. The caller
      renders those findings as unassigned rows with this sentence beside them.

    A finding with no board (a project-wide reading) falls to the last board only
    when there is exactly one; otherwise it is left ``-1`` and the caller reports it
    as a project-level row rather than guessing.
    """
    board = str(finding.get("board") or "")
    if board:
        uuid = str(finding.get("boardUuid") or finding.get("board_uuid") or "").strip()
        if uuid:
            named = [
                index for index, link in enumerate(links)
                if str(link.get("uuid") or "") == uuid
            ]
            if len(named) == 1:
                return named[0], ""
            return -1, (
                f"finding 的 boardUuid {uuid} 不在板链里（板链只有 "
                + "、".join(sorted(str(link.get('uuid') or '(no uuid)') for link in links))
                + "）—— 无法归因"
            )
        if board in pcb_titles:
            pcb_matches = [
                index for index, link in enumerate(links) if link.get("pcb") == board
            ]
            if len(pcb_matches) == 1:
                return pcb_matches[0], ""
            if len(pcb_matches) > 1:
                return -1, (
                    f"finding 的 board={board!r} 是 PCB 文档标题，板链里有 "
                    f"{len(pcb_matches)} 份同名 PCB —— 无法归因（按标题匹配会把它们并成一块板）"
                )
        title_matches = [
            index for index, link in enumerate(links) if link.get("title") == board
        ]
        if len(title_matches) == 1:
            return title_matches[0], ""
        if len(title_matches) > 1:
            return -1, (
                f"finding 的 board={board!r} 是原理图板名，板链里有 {len(title_matches)} "
                "块板同名 —— 无法归因"
            )
        return -1, (
            f"板链里没有一块板叫 {board!r}（原理图标题与 PCB 文档标题都对不上）"
            " —— 无法归因"
        )
    if len(links) == 1:
        return 0, ""
    return -1, "finding 没有 board，工程不止一块板 —— 工程级读数，不硬塞进某块板"


def _finding_module(finding: dict, board_title: str, modules: list[dict]) -> str:
    """The module name of a finding's refs **within its own board**, or ``""``.

    Reads the report's own ``modules[]`` — the same grouping the module table
    prints — and matches by designator. A module that states a board only claims
    findings of that board (the 040b rule), and a single-board report's modules
    carry no board field, so the check is skipped when it is empty rather than
    failing every match.
    """
    refs = set(str(ref) for ref in (finding.get("refs") or []) if str(ref))
    if not refs:
        return ""
    for module in modules:
        module_board = str(module.get("board") or "")
        if module_board and board_title and module_board != board_title:
            continue
        if refs & set(str(ref) for ref in (module.get("components") or [])):
            return str(module.get("name") or "")
    return ""


def _group_key(
    finding: dict, weight: str, board_title: str, modules: list[dict]
) -> str:
    """Which group one finding belongs to inside its board.

    The three tiers group differently on purpose, and the grouping says which
    question the finding answers:

    * **device** — one :data:`DEVICE_GROUP_NAME` group, because the roadmap's
      第三步 is a family about a *part*, and a part can sit in two modules;
    * **pcb-module** — the module the finding's refs fall in (「按模块分组」), or
      the rule family when the refs name no module (a board-frame or whole-net
      reading is nobody's module);
    * **generic** — the rule family (原理图连通性 / 元件参数/选型 / …), because a
      schematic reading's module is not what the reader is triaging.
    """
    if weight == WEIGHT_DEVICE:
        return DEVICE_GROUP_NAME
    if weight == WEIGHT_PCB_MODULE:
        module = _finding_module(finding, board_title, modules)
        return module or rule_family(str(finding.get("rule_id") or ""))
    return rule_family(str(finding.get("rule_id") or ""))


#: The closing line's two states, as words a reader can act on. Deliberately not
#: 「通过」: the report's own gate (`completion.verdict`) is what may be claimed,
#: and `mayClaimPassed` keeps its narrow meaning (053 §2.2).
VERDICT_CAN_SHIP = "可以投板"
VERDICT_CANNOT_CLAIM = "不能写「通过」"

#: The one `completion.verdict` that may be quoted as a pass (073/053's state
#: machine). Named once, because 188B derives `conclusion.mayQuotePassed` from it
#: — the boolean and the closing sentence must not disagree about which state
#: ships.
VERDICT_COMPLETE = "complete"


#: 516 C1: the short labels the closing sentence counts **rule families** with.
#: Only the ids the schematic side's ``rules.i18n.RULE_NAMES_ZH`` does not carry
#: (the PCB rules) live here; anything in neither map falls back to its own id, so
#: a new rule is named by its id rather than dropped from the summary.
RULE_FAMILY_LABELS_ZH: dict[str, str] = {
    "pcb-track-ampacity": "载流",
    "pcb-voltage-spacing": "间距",
    "pcb-keepout-violation": "禁布区",
    "pcb-component-spacing": "器件间距",
    "pcb-hs-diffpair-inventory": "高速差分对",
    "pcb-mcu-supply-groups": "MCU 供电",
    "pcb-mcu-reset-boot": "MCU 复位",
    "pcb-mcu-crystal-placement": "晶振布局",
    "pcb-mcu-crystal-keepout": "晶振禁布",
    "pcb-regulator-cap-distance": "稳压去耦距离",
    "pcb-regulator-fb-placement": "反馈取样布局",
    "pcb-foc-decap-proximity": "FOC 去耦",
    "pcb-foc-ground-plane": "FOC 地平面",
    "pcb-foc-gate-trace-width": "FOC 栅极线宽",
    "pcb-foc-track-corners": "FOC 走线转角",
    "pcb-foc-power-loop-area": "FOC 功率环路",
    "pcb-foc-ground-domains": "FOC 地分区",
    "pcb-foc-ground-tie": "FOC 地连接",
    "pcb-foc-return-path": "FOC 回流路径",
    "pcb-foc-thermal-via-style": "FOC 散热过孔",
    "pcb-foc-thermal-via-array": "FOC 散热阵列",
    "pcb-foc-thermal-exit-path": "FOC 散热出口",
}


def _rule_summary_label(rule_id: str) -> str:
    """A short label for one rule id in a closing sentence (516 C1)."""
    if not rule_id:
        return "未具名规则"
    from ..rules.i18n import RULE_NAMES_ZH

    return (
        RULE_FAMILY_LABELS_ZH.get(rule_id)
        or RULE_NAMES_ZH.get(rule_id)
        or rule_id
    )


def _rule_summary(report: dict, *, top: int = 3) -> str:
    """The top-N rule families among the report's **ERROR** findings (516 C1).

    ``oneLiner`` said 「先改 5 项 ERROR」 with no type, so a reader had to open the
    findings to learn whether the board was blocked by a netlist mistake or by
    copper. This counts the ERROR findings by rule family and returns
    「去耦电容 1、载流 4」-shaped prose, or ``''`` when there is no ERROR finding to
    count — the summary is an **addition** to the counts, never a substitute.
    """
    counts: collections.Counter = collections.Counter()
    for finding in report.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("severity") or "").upper() != "ERROR":
            continue
        counts[_rule_summary_label(str(finding.get("rule_id") or ""))] += 1
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    parts = [f"{label} {count}" for label, count in ordered[:top]]
    if len(ordered) > top:
        parts.append(f"另 {sum(count for _, count in ordered[top:])}")
    return "、".join(parts)


def board_report_verdict(report: dict) -> dict:
    """「整工程能不能投板」—— the closing line, from the report's **own** gate.

    Read, never recomputed (024's discipline): the answer is
    ``completion.verdict``, the one section that already states whether the review
    finished, and the blockers are its own ``verdictWhy``. This function exists so
    the integrated report can *print* that sentence, not so a second gate can be
    written beside it:

    * ERROR present → cannot ship, whatever else is true;
    * ``completion.verdict == "complete"`` → can ship (nothing owed: no ERROR, no
      part without a datasheet, no untriaged warning, no coverage gap);
    * anything else (``complete-with-open-items`` / ``incomplete``) → **cannot write
      「通过」**, with the reasons spelled out — 缺手册 (unreviewed/gated parts) and
      untriaged warnings are the two 岳 named, and the completion section's own
      ``verdictWhy`` already lists every blocker, so it is quoted rather than
      re-listed.

    A report with **no** ``completion`` section (a hand-built dict, an old report)
    falls back to the narrow field: ``summary.mayClaimPassed`` false, or any ERROR,
    means the pass may not be claimed, and the line says which reading it used.
    """
    summary = report.get("summary") or {}
    completion = report.get("completion")
    errors = int(summary.get("errorCount", 0) or 0)
    error_entries = summary.get("errors")
    error_entries = error_entries if isinstance(error_entries, list) else []
    blockers: list[str] = []
    if errors:
        blockers.append(f"{errors} 项 ERROR")
    elif error_entries:
        blockers.append(f"{len(error_entries)} 条 ERROR 条目（计数不可枚举）")

    if completion is None:
        may = summary.get("mayClaimPassed")
        can_ship = not blockers and bool(may)
        if can_ship:
            line = (
                f"{VERDICT_CAN_SHIP}：无 ERROR，且 `summary.mayClaimPassed` 为真"
                "（窄义：没有器件缺手册未审）——完整结论以 `completion.verdict` 为准"
            )
        else:
            if may is False:
                blockers.append("有器件缺手册未审（summary.mayClaimPassed 为假）")
            line = (
                f"{VERDICT_CANNOT_CLAIM}：{'；'.join(blockers) or '缺少 completion 节，无法给出完整结论'}"
            )
        return {
            "canShip": can_ship,
            "line": line,
            "blockers": blockers,
            "completionVerdict": "",
            "mayClaimPassed": may,
            "basis": "summary（无 completion 节：按窄义字段判）",
        }

    verdict = str(completion.get("verdict") or "")
    why = [str(reason) for reason in (completion.get("verdictWhy") or [])]
    if blockers:
        can_ship = False
        family = _rule_summary(report)
        line = (
            f"不能投板：先改 {'；'.join(blockers)}"
            + (f"（按规则：{family}）" if family else "")
            + "（逐条见下）"
        )
    elif verdict == VERDICT_COMPLETE:
        can_ship = True
        line = (
            f"{VERDICT_CAN_SHIP}：本工程无 ERROR、无缺手册未审、无待分诊、无覆盖缺口"
            "（completion.verdict = complete）"
        )
    else:
        can_ship = False
        line = (
            f"{VERDICT_CANNOT_CLAIM}（completion.verdict = {verdict or '未知'}）："
            + ("；".join(why) if why else "有待办项未清")
            + "——缺手册、有待分诊项时一律不许写「通过」"
            "（口径同 `summary.mayClaimPassed` 与 `completion.verdict`）"
        )
    return {
        "canShip": can_ship,
        "line": line,
        "blockers": blockers,
        "completionVerdict": verdict,
        "mayClaimPassed": summary.get("mayClaimPassed"),
        "basis": "completion.verdict / verdictWhy（唯一权威闸，本函数不重算）",
    }


#: The `conclusion` section's keys, in the order they are written (185 A, 188B).
#: 185's five, plus `mayQuotePassed` — the one boolean a script may gate on
#: (188B 低4): `verdict` is the full state machine, and "may this be quoted as a
#: pass?" is the single question `exitCode 0` gets wrong. Nothing else goes in:
#: the section exists so a caller has **one** place to read a verdict from, and
#: every extra key is one more thing to keep in sync.
CONCLUSION_KEYS = (
    "verdict", "exitCode", "mayClaimPassed", "mayQuotePassed", "oneLiner", "blockers",
)


def conclusion_section(report: dict, *, verdict: dict | None = None) -> dict:
    """The report's **one authoritative conclusion** — every field read, none recomputed.

    185 A. The report has carried its verdict in five places for a while, and each
    of them answers a slightly different question:

    * ``completion.verdict`` — did the review finish;
    * ``summary.exitCode`` — what the process exits with;
    * ``summary.mayClaimPassed`` — the **narrow** datasheet question (053 §2.2);
    * the first sentence of ``board-report.md`` — the sentence a human is told to
      read first (154's :func:`board_report_verdict`);
    * ``completion.verdictWhy`` — why, in clauses.

    An AI reporting to an engineer, or a script deciding whether to fail CI, had
    to know which of the five to trust and when they disagree. This section is
    that decision, made once, in the one place every report is written
    (:func:`boardwise.cli._write_checkup_report`).

    **Every field is a read**, which is the whole point:

    * ``oneLiner`` is the verdict dict's ``line`` — the string
      :func:`render_board_report` prints as the closing line of
      ``board-report.md``. **Same function, not the same call** (188B 低6): the
      CLI passes the section's own verdict dict in, so this section reuses
      `board_report_section`'s call, while `render_board_report` — rendering the
      Markdown a person reads — makes its **own** call to the same function. The
      two agree because :func:`board_report_verdict` is a pure read of the report
      (deterministic, and asserted verbatim in `tests/test_185_conclusion.py`
      from *three* independent recomputations), not because one call answered
      twice. One generator, several readers — not a second sentence written
      beside the first;
    * ``blockers`` is ``completion.verdictWhy`` as it stands. The one exception is
      a report with **no** ``completion`` section at all (a hand-built dict, a
      report from before 053), where there is no ``verdictWhy`` to quote and the
      narrow reasons :func:`board_report_verdict` derived are used instead — still
      that one function's own list, never a re-derivation here;
    * ``mayQuotePassed`` (188B 低4) is ``verdict == "complete"``, and nothing else:
      the single boolean a script or an AI may gate on before saying a board
      passed. ``exitCode`` answers a different question — 0 also covers
      ``complete-with-open-items`` and a clean-looking run that could not state
      its state is 3 — so 「exitCode 0 ≠ 可投板」 is a rule, not a nuance
      (`docs/review-sop.md`).

    Additive by construction: the five older readings keep their names, meanings
    and places, and the sixth is derived from the first. Nothing in the verdict
    arithmetic reads this section.
    """
    summary = report.get("summary") or {}
    completion = report.get("completion") or {}
    info = verdict if isinstance(verdict, dict) else board_report_verdict(report)
    if completion:
        blockers = [str(reason) for reason in (completion.get("verdictWhy") or [])]
    else:
        blockers = [str(reason) for reason in (info.get("blockers") or [])]
    state = str(completion.get("verdict") or info.get("completionVerdict") or "")
    return {
        "verdict": state,
        "exitCode": summary.get("exitCode"),
        "mayClaimPassed": summary.get("mayClaimPassed"),
        "mayQuotePassed": state == VERDICT_COMPLETE,
        "oneLiner": str(info.get("line") or ""),
        "blockers": blockers,
    }


def _drc_baseline(report: dict) -> dict:
    """The ERC + DRC baseline the integrated report opens with, read from `drc`.

    Only the numbers the `drc` section already states: the host ERC counts (or why
    they are unknown), the PCB DRC leaf/group totals (or the reason it did not run),
    and the rule-set name the DRC was measured against. Nothing is summed afresh —
    a baseline that disagreed with `drc` would be worse than none.
    """
    drc = report.get("drc") or {}
    schematic = drc.get("schematic") or {}
    pcb = drc.get("pcb") or {}
    ruleset = drc.get("ruleset") or {}
    erc: dict = {"checked": bool(schematic.get("checked"))}
    if erc["checked"]:
        if schematic.get("countsKnown") is False:
            erc["countsKnown"] = False
            erc["passed"] = schematic.get("passed")
            erc["summary"] = f"主机只回 boolean（passed={schematic.get('passed')}），无逐项计数"
        else:
            erc["countsKnown"] = True
            counts = {
                kind: schematic.get(kind)
                for kind in ("fatalError", "error", "warn")
                if kind in schematic
            }
            erc["counts"] = counts
            erc["summary"] = "，".join(f"{k} {v}" for k, v in counts.items()) or "无计数"
        erc["note"] = str(schematic.get("note") or "")
    else:
        erc["summary"] = f"未检查 —— {schematic.get('reason') or '（无原因）'}"
    pcb_drc: dict = {"checked": bool(pcb.get("checked"))}
    if pcb_drc["checked"]:
        totals = pcb.get("totals") or {}
        pcb_drc["leafs"] = totals.get("leafs", 0)
        pcb_drc["groups"] = len(pcb.get("groups") or [])
        pcb_drc["truncated"] = bool(pcb.get("truncated"))
        pcb_drc["summary"] = (
            f"{totals.get('leafs', 0)} 条 / {len(pcb.get('groups') or [])} 组"
            + ("（答复被截断，总数不可知）" if pcb.get("truncated") else "")
        )
    else:
        pcb_drc["summary"] = f"未检查 —— {pcb.get('reason') or '（无原因）'}"
    return {
        "erc": erc,
        "pcb": pcb_drc,
        "ruleset": {
            "checked": bool(ruleset.get("checked")),
            "name": str(ruleset.get("ruleSetName") or ""),
            "summary": (
                f"`{ruleset.get('ruleSetName') or '(unnamed)'}`"
                if ruleset.get("checked")
                else f"未读 —— {ruleset.get('reason') or '（无原因）'}"
            ),
        },
    }


def board_report_section(
    report: dict, *, modules: list[dict] | None = None
) -> dict:
    """The `board_report` section — the integrated, human-first whole-board report.

    The answer to E 阶段的验收「一键出整板报告（ERC+DRC+模块+器件）」and to 岳's
    2026-10-11 体验反馈 that the machine ledger is too verbose. It re-reads the
    report's own sections (`drc`, `findings`, `modules`, `summary`, `completion`)
    and arranges them the way a person triages a board:

    * **per board** (``links`` order = ``model.boards`` order), with the PCB
      document's title shown beside the schematic board's when the link is known;
    * **per module / rule family** inside a board — the device rules as one
      :data:`DEVICE_GROUP_NAME` group, module-level PCB findings by their module,
      everything else by rule family;
    * **sorted by severity × module weight** — severity first (ERROR → WARN →
      INFO), then weight (:data:`WEIGHT_RANK`: 模块级 > 器件级 > 通用) inside a
      severity tier, so an ERROR is never buried under a pile of module-level INFO
      measurement rows and a module-level ERROR leads its tier. The exact key is
      written into the head (`order`) so the sort is checkable, not a vibe;
    * one human-readable line per finding (:func:`finding_oneline`) — the machine
      detail stays in `findings[]`;
    * a closing verdict (:func:`board_report_verdict`) answering 「整工程能不能投板」.

    ``modules`` overrides the report's own grouping when a caller has it (the CLI
    does); otherwise ``report["modules"]`` is used, and a report with none groups by
    rule family alone rather than inventing modules.
    """
    module_list = modules if modules is not None else (report.get("modules") or [])
    findings = report.get("findings") or []
    links = _board_links(report)
    pcb_titles = {link["pcb"] for link in links if link.get("pcb")}

    # One bucket per board link, plus a project-level bucket for findings no board
    # claims. A bucket holds ``(weight, severity, report order, finding)`` tuples so
    # the sort and the grouping read off one list.
    buckets: list[dict[str, list]] = [
        {"rows": []} for _ in links
    ]
    unassigned: list[dict] = []
    for index, finding in enumerate(findings):
        weight = finding_weight(str(finding.get("rule_id") or ""))
        position, why = _board_of_finding(finding, links, pcb_titles)
        row = (weight, str(finding.get("severity") or ""), index, finding)
        if position < 0:
            unassigned.append(
                {"index": index, "weight": weight, "finding": finding, "why": why}
            )
            continue
        buckets[position]["rows"].append(row)

    def _group_rows(rows: list, board_title: str) -> list[dict]:
        groups: dict[str, list] = {}
        for weight, severity, index, finding in rows:
            key = _group_key(finding, weight, board_title, module_list)
            groups.setdefault(key, []).append((weight, severity, index, finding))
        out: list[dict] = []
        for name, members in groups.items():
            # The sort key is **severity first, module weight second** — the two
            # axes named in `order`, and the reason an ERROR is never buried under
            # a pile of module-level INFO measurement rows. `rule_id` and the
            # report's own index break the remaining ties so the order is total
            # and the same report always renders the same way.
            members.sort(
                key=lambda item: (
                    SEVERITY_RANK.get(item[1].upper(), 9),
                    WEIGHT_RANK.get(item[0], 9),
                    str(item[3].get("rule_id") or ""),
                    item[2],
                )
            )
            # The group's *label* tier is its **heaviest** finding's: a module
            # group that holds one module-level reading is labelled 模块级 even if
            # its other rows are generic. It does not decide the order — the best
            # (severity, weight) pair inside the group does.
            best_weight = min((WEIGHT_RANK.get(m[0], 9) for m in members), default=9)
            weight_key = next(
                (m[0] for m in members if WEIGHT_RANK.get(m[0], 9) == best_weight),
                WEIGHT_GENERIC,
            )
            best_severity = min(
                (SEVERITY_RANK.get(m[1].upper(), 9) for m in members), default=9
            )
            out.append({
                "name": name,
                "weight": weight_key,
                "weightLabel": WEIGHT_LABELS.get(weight_key, weight_key),
                "counts": _severity_counts([m[3] for m in members]),
                "findings": [
                    {
                        "index": m[2],
                        "severity": str(m[3].get("severity") or ""),
                        "rule_id": str(m[3].get("rule_id") or ""),
                        "level": str(m[3].get("level") or ""),
                        "board": str(m[3].get("board") or board_title),
                        "refs": [str(ref) for ref in (m[3].get("refs") or [])],
                        "line": finding_oneline(m[3]),
                    }
                    for m in members
                ],
                "_sort": (best_severity, best_weight, name),
            })
        out.sort(key=lambda group: group["_sort"])
        for group in out:
            group.pop("_sort", None)
        return out

    board_sections: list[dict] = []
    for index, link in enumerate(links):
        rows = buckets[index]["rows"]
        groups = _group_rows(rows, link["title"])
        board_sections.append({
            "board": link["title"],
            "pcb": link["pcb"],
            "components": link["components"],
            "copperLayers": link["copperLayers"],
            "outlineNote": link.get("outlineNote"),
            "netIdNote": link.get("netIdNote"),
            "counts": _severity_counts([row[3] for row in rows]),
            "groups": groups,
        })

    return {
        "order": "严重度（ERROR → WARN → INFO）× 模块权重（同级内 PCB 模块级 > 器件级 > 通用）",
        "weights": [
            {
                "key": key,
                "label": WEIGHT_LABELS[key],
                "rank": WEIGHT_RANK[key],
                "why": WEIGHT_WHY[key],
            }
            for key in (WEIGHT_PCB_MODULE, WEIGHT_DEVICE, WEIGHT_GENERIC)
        ],
        "note": (
            "本表给人读：ERC + DRC + 模块规则 + 器件规则合成一份，按「板 → 模块/规则族」"
            "分组，每条一句话（位号/网/问题/依据）。机器细节（完整 message、evidence、"
            "定位链、规则等级）留在 `report.json` 的 findings[]，本表一个字都不新增结论。"
        ),
        "drc": _drc_baseline(report),
        "boards": board_sections,
        "unassigned": [
            {
                "index": entry["index"],
                "weight": entry["weight"],
                "severity": str(entry["finding"].get("severity") or ""),
                "rule_id": str(entry["finding"].get("rule_id") or ""),
                "board": str(entry["finding"].get("board") or ""),
                "why": entry.get("why") or "",
                "line": finding_oneline(entry["finding"]),
            }
            for entry in unassigned
        ],
        "totals": _severity_counts(findings),
        "verdict": board_report_verdict(report),
    }


def _severity_counts(findings: list[dict]) -> dict[str, int]:
    """``{ERROR, WARN, INFO}`` over a finding list, zero-filled."""
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for finding in findings:
        severity = str(finding.get("severity") or "").upper()
        counts[severity] = counts.get(severity, 0) + 1
    return counts


#: The standalone file name the integrated report is written to (`--out`), beside
#: `report.json` / `report.md` / `review-summary.md`. The same section is embedded
#: at the top of `report.md` (see :func:`render_report_markdown`); this is the
#: 「只想要那一份」 form of it.
BOARD_REPORT_FILE = "board-report.md"


def render_board_report(report: dict, section: dict | None = None) -> str:
    """The `board_report` section as the Markdown a person reads.

    The same renderer feeds the leading section of `report.md` (via
    :func:`render_report_markdown`) **and** the standalone `board-report.md` file
    — one function, so the embedded copy and the file cannot disagree. It renders
    only what the section already says.
    """
    section = section if isinstance(section, dict) else board_report_section(report)
    lines: list[str] = []
    lines.append("## 整板报告（一键：ERC + DRC + 模块 + 器件）")
    lines.append("")
    verdict = section.get("verdict") or {}
    lines.append(f"### 整工程能不能投板：{verdict.get('line', '（无结论）')}")
    lines.append("")
    lines.append(f"- 排序依据：{section.get('order', '')}")
    for weight in section.get("weights") or []:
        lines.append(f"  - **{weight.get('label')}**（rank {weight.get('rank')}）：{weight.get('why')}")
    lines.append(f"- {section.get('note', '')}")
    lines.append("")

    drc = section.get("drc") or {}
    erc = drc.get("erc") or {}
    pcb = drc.get("pcb") or {}
    ruleset = drc.get("ruleset") or {}
    lines.append("### 基线（ERC / DRC）")
    lines.append("")
    lines.append(f"- 原理图 ERC：{'已查' if erc.get('checked') else '未查'} —— {erc.get('summary', '')}")
    if erc.get("note"):
        lines.append(f"  - {erc['note']}")
    lines.append(f"- PCB DRC：{'已查' if pcb.get('checked') else '未查'} —— {pcb.get('summary', '')}")
    lines.append(
        f"- PCB DRC 规则集：{'已读' if ruleset.get('checked') else '未读'} —— {ruleset.get('summary', '')}"
    )
    lines.append("")

    boards = section.get("boards") or []
    if not boards:
        lines.append("（本工程没有可分组的结构。）")
        lines.append("")
    for board in boards:
        heading = board.get("board") or "(unnamed board)"
        detail: list[str] = []
        if board.get("pcb"):
            detail.append(f"PCB 文档 `{board['pcb']}`")
        if board.get("components") is not None:
            detail.append(f"{board['components']} 器件")
        if board.get("copperLayers") is not None:
            detail.append(f"{board['copperLayers']} 铜层")
        counts = board.get("counts") or {}
        detail.append(
            f"{counts.get('ERROR', 0)} ERROR / {counts.get('WARN', 0)} WARN / "
            f"{counts.get('INFO', 0)} INFO"
        )
        lines.append(f"### 板：{heading}" + (f"（{'，'.join(detail)}）" if detail else ""))
        if board.get("outlineNote"):
            # bug98：板框没读出/未闭环/有碎段/含容差焊缝——「没跑」必须写在
            # 人读的报告上，不是只埋在 report.json。
            lines.append(f"> ⚠️ {board['outlineNote']}")
        if board.get("netIdNote"):
            # 191C 遗留（191A 交付）：KiCad 裸 `(net N)` 查不到名字 → 保留成
            # `net#N` 并计数披露。和上一条同一个道理、同一个位置：**按网名读的
            # 检查**（差分对清单、按轨分档）看不见那些网，这句话只埋在
            # report.json 里，读 Markdown 的人就以为那些网的名字是完整的。
            lines.append(f"> ⚠️ {board['netIdNote']}")
        lines.append("")
        for group in board.get("groups") or []:
            gcounts = group.get("counts") or {}
            lines.append(
                f"#### {group.get('name')}（{group.get('weightLabel')}）"
                f"—— {gcounts.get('ERROR', 0)} ERROR / {gcounts.get('WARN', 0)} WARN / "
                f"{gcounts.get('INFO', 0)} INFO"
            )
            lines.append("")
            for entry in group.get("findings") or []:
                lines.append(
                    f"- **{_cell(entry.get('severity'))}** `{_cell(entry.get('board'))}` · "
                    f"{_cell(entry.get('line'))}"
                )
            lines.append("")
    unassigned = section.get("unassigned") or []
    if unassigned:
        lines.append(f"### 不归属任何板（{len(unassigned)}）")
        lines.append("")
        lines.append(
            "这些 finding 没有被任何一块板认领：有的是工程级读数（多板工程），有的是板链里"
            "有同名板、或板名对不上（163b：同名不硬猜，逐条写出为什么归不了）。"
        )
        lines.append("")
        for entry in unassigned:
            reason = f"（{_cell(entry.get('why'))}）" if entry.get("why") else ""
            lines.append(
                f"- **{_cell(entry.get('severity'))}** `{_cell(entry.get('board')) or '工程级'}` · "
                f"{_cell(entry.get('line'))}{reason}"
            )
        lines.append("")
    totals = section.get("totals") or {}
    lines.append(
        f"**整工程合计：{totals.get('ERROR', 0)} ERROR / {totals.get('WARN', 0)} WARN / "
        f"{totals.get('INFO', 0)} INFO**"
    )
    lines.append("")
    return "\n".join(lines)


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

    **A renderer that raises must not erase the review (189B ④).** The sections are
    appended to one list, and this wrapper keeps that list: a section that dies
    mid-way leaves every section before it in place, plus a named row saying what
    failed and where the complete reading still is (`report.json`, which
    :func:`boardwise.cli._write_checkup_report` writes first). The rules ran for
    minutes and their findings are in the body above the break — an empty file
    with a traceback on stderr is the one outcome this must never be.
    """
    lines: list[str] = []
    try:
        _render_report_markdown(lines, report)
    except Exception as exc:  # noqa: BLE001 — the report body must survive
        lines.append("")
        lines.append(
            f"> **报告渲染中断：{type(exc).__name__}: {exc}** —— 本行以上各节是"
            "`report.json` 里已经有的读数（照常可信）；中断点以下各节没有渲染出来，"
            "请直接读 `report.json`（它是权威，`report.md` 只是它的渲染）"
        )
        lines.append("")
    return "\n".join(lines)


def _render_report_markdown(lines: list[str], report: dict) -> None:
    """The body of :func:`render_report_markdown`, appending into ``lines``."""
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
    lines.extend([
        "# boardwise checkup 报告",
        "",
        f"**结论：{verdict}**（退出码 {exit_code}）",
        "",
        f"- 工程：`{title}`" + (f"（{project.get('projectUuid')}）" if project.get("projectUuid") else ""),
        f"- 数据来源：`{source.get('tier')}` — {source.get('tierLabel', '')}",
        f"- 模型：{model.get('components', '?')} 器件 / {model.get('nets', '?')} 网"
        + (f"，位号 {'、'.join(model.get('designators') or [])}" if model.get("designators") else ""),
        f"- 计数：{errors} ERROR / {warnings} WARN / {summary.get('infoCount', 0)} INFO",
    ])
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
    # 537C2: what the run's environment could and could not establish, before the
    # findings — "no ERROR" means something different when the reading was an
    # offline archive against an unverified connector. Additive: no section, no
    # text (the pre-537C2 hand-built reports render as before).
    _render_guarded(
        lines,
        "审查环境与权限（environment）",
        lambda: lines.extend(render_environment_markdown(report.get(ENVIRONMENT_KEY))),
    )
    # 537C3a: the six-channel evidence ledger, next to the environment because it
    # answers the same reader's next question — "what did this run actually
    # collect?" — before any conclusion is read. Additive: no section, no text,
    # so a hand-built (or pre-537C3a) report renders as before.
    _render_guarded(
        lines,
        "证据覆盖（evidence）",
        lambda: lines.extend(render_evidence_markdown(report.get(EVIDENCE_KEY))),
    )

    # --- 154 / E4: the integrated whole-board report, first, because it is the
    # one section a person reads end to end (ERC + DRC + module + device, grouped
    # by board → module/family, sorted by severity × weight, one line each, closing
    # with 「整工程能不能投板」). The ledger below keeps every machine detail; this is
    # the glance. It renders only what `board_report` (or the report's own sections,
    # when a hand-built dict carries no such key) already says.
    # 189B ④: it is another renderer over the same dict — the one section whose
    # shape `render_report_markdown` does not own — so it gets the same guard: a
    # dead board report costs this section, not the ledger below it.
    _render_guarded(
        lines,
        "整板报告（board-report）",
        lambda: lines.append(render_board_report(report).rstrip()),
    )
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
            # 537B §3: the pending count above already includes these rows (they
            # are *not* closed); this says how many of them need a human to look,
            # which is the next action a reader has — same number as
            # `completion.warningsNeedsManual` and the console line.
            + (
                f" · 待人工复核 {TRIAGE_UNJUDGEABLE} "
                f"{completion.get('warningsNeedsManual', 0)}"
                if completion.get("warningsNeedsManual") else ""
            )
            # 191A: the engineer's accepted-unknown parts are **not** a debt, but
            # they are read beside the row they left, so the ledger says the number
            # rather than leaving a reader to reconstruct it from the section.
            + (
                f" · 工程师接受未审 {completion.get('acceptedUnknown', 0)}"
                if completion.get("acceptedUnknown") else ""
            )
            + (
                # 192B ⑦: two kinds of stale, both counted here, and the sentence
                # says which — 「不在图纸上」 and 「不在这块板上」 are different
                # places to look, and the second is not a part to go and revoke.
                f"（另有 {completion.get('acceptedUnknownStale', 0)} 条指向的件"
                "已不在图纸上"
                + (
                    f"，{completion.get('acceptedUnknownStaleElsewhere', 0)} 条只在"
                    "别的板上（板名要改）"
                    if completion.get("acceptedUnknownStaleElsewhere") else ""
                )
                + "）"
                if completion.get("acceptedUnknownStale") else ""
            )
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
    from ..core.parts import IDENTITY_NAME

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
        # 186 §C (P1): the action that actually clears the gate, spelled with the
        # CLI's own commands. Feeding a PDF is the step that *looked* like it
        # cleared the gate and does not — a reader that has to guess is the
        # accident this line exists for. 186-H2 added **which shelf** to that
        # instruction: the write has to land in the file this run read.
        lines.append("")
        lines.append(unreviewed_clearing_note(str(report.get("shelfPath") or "")))
        # 184: the总 number is one number for different problems. Printed from the
        # rows below (or, for a hand-built report, from the section itself), never
        # recomputed from the model — the ledger may not say more than the JSON.
        counts = summary.get("unreviewedByReason")
        if not isinstance(counts, dict):
            counts = unreviewed_counts_by_reason(unreviewed)
        if counts:
            lines.append("")
            lines.append(
                "按原因计数："
                + " · ".join(f"{reason} {count}" for reason, count in counts.items())
            )
        # 186 §C: the same rows, split by what the reader has to do next. A row
        # in both classes is named in both lists and counted once in each — the
        # question "how many parts" is the heading's number, not these.
        by_class = summary.get("unreviewedByClass")
        if not isinstance(by_class, dict):
            by_class = unreviewed_counts_by_class(unreviewed)
        if by_class:
            lines.append("")
            lines.append(
                "按性质分栏（同一器件两类都沾的，两边都列）："
                + " · ".join(
                    f"{name} {by_class.get(name, 0)}" for name in CLASS_ORDER
                )
            )
            for name in CLASS_ORDER:
                members = [part for part in unreviewed if name in unreviewed_classes(part)]
                lines.append(
                    f"- **{name}**（{len(members)}）："
                    + ("、".join(f"`{part.get('designator')}`" for part in members) or "无")
                )
            lines.append("")
            lines.append(
                "两类的下一步相反：「工具读不懂」不是缺资料——再喂 PDF 也没用，"
                "要补的是读法（板上 `Value` / 解码器）；「真缺资料」才轮到去要手册。"
            )
            # 517: the metadata reading, **inside** the class split. The four
            # buckets are walked over the model's passives (not the rows above:
            # confirmed parts are not in `unreviewed_parts[]` any more — that
            # is the point), so they come from the report's own sections.
            meta_counts = report.get("metadataStateCounts")
            if isinstance(meta_counts, dict) and meta_counts:
                lines.append("")
                lines.append(
                    "归档元数据（LCSC Part Name / Type，零网络）："
                    + " · ".join(
                        f"{name} {meta_counts[name]}" for name in META_STATE_ORDER
                        if name in meta_counts
                    )
                )
                lines.append(
                    "「已确认」= 归档/板上 Value/MPN 至少两路一致，已不再要手册；"
                    "「冲突」= 两路读数打架（逐路读数见 `metadataValueConflicts[]`）；"
                    "「缺失」= 归档字段为空；「不可解析」= 有字段但没读出来——"
                    "**这是读法缺口，不是缺资料**，两类分开计数。"
                )
            # 517: the confirmed parts' evidence — which two sources agreed.
            # A part that left the gate has to be findable, or the shortening
            # is exactly the silent green light the section forbids.
            confirmed_meta = report.get("metadataValueConfirmed") or []
            if confirmed_meta:
                lines.append("")
                lines.append(
                    f"**归档元数据确认、未要手册的件（{len(confirmed_meta)}）**："
                )
                for row in confirmed_meta:
                    lines.append(
                        f"- `{row.get('designator')}` 值 "
                        f"{row.get('value', 0):g}（确认依据："
                        + " + ".join(row.get("confirmedBy") or [])
                        + f"；归档：{row.get('archive') or '—'}）"
                    )
            conflicts_meta = report.get("metadataValueConflicts") or []
            if conflicts_meta:
                lines.append("")
                lines.append(
                    f"**元数据冲突（{len(conflicts_meta)}）**——逐路读数，先核对再动手："
                )
                for row in conflicts_meta:
                    for param, detail in (row.get("params") or {}).items():
                        readings = "、".join(
                            f"{name}={value:g}" for name, value in detail["readings"].items()
                        )
                        lines.append(
                            f"- `{row.get('designator')}` {param}：{readings}"
                            f"（归档：{row.get('archive') or '—'}；"
                            f"板上：{row.get('boardValue') or '—'}；"
                            f"MPN：{row.get('mpn') or '—'}）"
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
        # 188B (186 中1): a row whose shelf entry was found by **device name** —
        # 186 §B's weaker identity step — says so before the reader acts on it.
        # Read from the rows' own `shelfMatchedBy`, never re-resolved: the
        # engineer-channel cell above can say "按器件名匹配" about a *local PDF*,
        # which is a different claim about a different thing.
        by_name = [
            str(part.get("designator"))
            for part in unreviewed
            if part.get("shelfMatchedBy") == IDENTITY_NAME
        ]
        if by_name:
            lines.append("")
            lines.append(
                "**货架⇢按器件名匹配（弱证据）**："
                + "、".join(f"`{name}`" for name in by_name)
                + "——货架上这颗料是拿**器件名**找到的（MPN 与 C 码都没对上），"
                "身份比 MPN/C 码命中弱一档：核 facts 时把身份一并核了"
                "（行里的 `shelfMatchedBy` 就是这个读数，`name` 即按器件名）。"
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
    # 192B ⑤: the exemption's trace, printed whether or not the section above is
    # empty — a part this pass took *off* the gate is exactly the reading a reader
    # has to be able to see, and it is the one row that would otherwise leave no
    # mark at all (it neither is, nor ever was, in `unreviewed_parts`).
    exempt_rows = report.get("declaredPassiveExempt") or []
    if exempt_rows:
        lines.append("")
        lines.append(
            f"**声明为无源件、未按 IC 问手册的件（{len(exempt_rows)}）**："
            + "、".join(f"`{row.get('designator')}`" for row in exempt_rows)
            + f"——位号像 IC，但元数据/货架声明它是无源件（190 的豁免只给 ≤ "
            f"{MAX_PASSIVE_PINS} 脚的件）。判型读法与脚数见 `report.json` 的 "
            "`declaredPassiveExempt[]`（`kind` / `basis` / `pins`）；判型读错时"
            "这条就是它的留痕，而不是它无声消失。"
        )
    lines.append("")

    # --- 191A: the accepted-unknown list, right after 未审器件 because it is the
    # other half of that section's answer ("these parts left the list — and here
    # is who said they could"). Rendered from the rows' own fields, always
    # printed when non-empty (a report that hid it would be the silent green
    # light this batch exists to prevent), and silent by absence when the
    # contract accepted nothing.
    accepted_rows = report.get("accepted_unknown") or []
    if accepted_rows:
        counts = accepted_unknown_counts(accepted_rows)
        lines.append(f"## 工程师接受未审（accepted_unknown：{len(accepted_rows)}）")
        lines.append("")
        lines.append(
            "这些件**这一轮没有判**：工程师明示「这颗的未知我接受」，理由写在下面。"
            f"其中 {counts.get(STATE_ACCEPTED, 0)} 颗本轮真的从「未审器件」里移了出来"
            + accepted_verdict_clause(report.get("completion") or {})
            + "但报告把数量和理由一直说在明面上，**不算「审过了」**。"
        )
        lines.append("")
        lines.append("| 位号/令牌 | 状态 | MPN | 理由 | 谁 | 何时 |")
        lines.append("|---|---|---|---|---|---|")
        state_labels = {
            STATE_ACCEPTED: "本轮接受（已从 未审 移出）",
            STATE_ACCEPTED_NOT_UNREVIEWED: "不在本轮未审清单",
            STATE_ACCEPTED_STALE: "stale（图纸上已没有）",
            # 192B ⑦: the label alone would say the same false sentence the two
            # states shared, so this row's own `why` is appended to the cell
            # below — the board names are the whole content of the reading.
            STATE_ACCEPTED_STALE_ELSEWHERE: "stale-elsewhere（件在别的板上）",
        }
        for row in accepted_rows:
            state_text = state_labels.get(str(row.get("state")), row.get("state"))
            if (
                str(row.get("state")) == STATE_ACCEPTED_STALE_ELSEWHERE
                and row.get("why")
            ):
                state_text = f"{state_text}：{row['why']}"
            lines.append(
                f"| {_cell(row.get('part'))} "
                f"| {_cell(state_text)} "
                f"| {_cell(row.get('mpn') or '—')} "
                f"| {_cell(row.get('reason') or '—')} "
                f"| {_cell(row.get('who') or '—')} "
                f"| {_cell(row.get('when') or '—')} |"
            )
        lines.append("")
        stale_rows = [row for row in accepted_rows if row.get("stale")]
        if stale_rows:
            # 189B's discipline, one section over: the entry is kept and marked,
            # never removed, and the reader is told why it no longer says anything
            # about this board.
            lines.append(
                f"**合同里记着、图纸里已没有的件（{len(stale_rows)}，不删只标）**："
                + "、".join(f"`{row.get('part')}`" for row in stale_rows)
                + "——撤销用 `boardwise parts accept-unknown <MPN|位号> --reason … "
                "--revoke`（合同里那几条值保留，只标 `stale`）。"
            )
            lines.append("")
        orphans = [
            row for row in accepted_rows
            if str(row.get("state")) == STATE_ACCEPTED_NOT_UNREVIEWED
        ]
        if orphans:
            lines.append(
                f"另有 {len(orphans)} 条接受记录本轮没派上用场（那些件不在本轮未审清单里）："
                + "、".join(f"`{row.get('part')}`" for row in orphans)
                + "——合同里的条目继续保留，货架更新不会替工程师删掉他的判断。"
            )
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
        # 185-中1: the fold is by designator, and a project's designator is not
        # one part. Only the rows where that matters are spelled out — one line
        # per designator that stands for more than one placement — because the
        # reader deciding "how many datasheets do I still owe" has to see it, and
        # the table above cannot say it without one row per board.
        multi = [entry for entry in needs if len(entry.get("boards") or []) > 1]
        if multi:
            lines.append("")
            lines.append("**同一份清单按位号折叠，下列位号出现在多块板上（板上身份各不相同）：**")
            lines.append("")
            for entry in multi:
                placements = "；".join(
                    f"{row.get('board') or '(单板)'}"
                    f"（MPN {row.get('mpn') or '无'}，name {row.get('name') or '无'}，"
                    f"value {row.get('value') or '无'}）"
                    for row in entry["boards"]
                )
                lines.append(f"- `{entry.get('part')}`：{placements}")
            lines.append("")
            lines.append(
                "一份手册答不了两块板上两颗不同的料——这是**清单条数按位号去重**"
                "（`completion.needsDatasheetTotal`）而不是按板计数的原因，"
                "报「还差几份手册」时按位号乘板数算。"
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
            + "|".join(TRIAGE_VERDICT_CHOICES) + " --reason …` 写回（key 见下表，它是这条警告的身份；"
            "判决同时写进 `warning-triage.json`，所以重跑 `checkup` 不会丢）。"
            "主机 ERC 的条目**没有逐条文本**——它的答复只有按 kind 的合计（见 drc.schematic），"
            "逐条详情在编辑器底部面板且没有读取接口。"
        )
        lines.append("")
        lines.append(
            "**`text` 为空的槽位不能用上面三个词关闭**（那三个词要有警告自己的文本才成立）："
            f"它们只能标 `{TRIAGE_UNJUDGEABLE} --reason …`，标完**仍计入** "
            "`completion.warningsPendingTriage`，并在本表后面单列成「需人工复核」。"
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
        # 537B §3: the rows a human owes a look, rendered from `completion`'s own
        # list so this table and the gate are one arithmetic (the console line and
        # `verdictWhy` read the same count).
        manual = (report.get("completion") or {}).get("manualReviewRequired") or []
        if manual:
            lines.append("")
            lines.append(
                f"**需人工复核（{TRIAGE_UNJUDGEABLE}）{len(manual)} 条** —— 这些槽位没有逐条文本，"
                "三词判决对它们不成立；它们仍计入 `completion.warningsPendingTriage`，"
                "要人去编辑器底部面板/画布上逐条看："
            )
            lines.append("")
            lines.append("| key | 来源 | 计数 | 理由 |")
            lines.append("|---|---|---|---|")
            for row in manual:
                lines.append(
                    f"| {_cell(row.get('key'))} | {_cell(row.get('source'))} "
                    f"| {_cell(row.get('count'))} | {_cell(row.get('reason'))} |"
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
        _render_guarded(
            lines,
            "intent",
            lambda: render_intent_markdown(lines, intent_section_report),
        )

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
            # 189C: a geometry rendering is named by its **board** (the PCB document's
            # own title); an online screenshot is named by its page. The board key is
            # read first so an entry that carries both says the more specific one.
            label = image.get("board") or image.get("page") or image.get("pageUuid")
            if image.get("file"):
                detail = f"（{image.get('bytes', '?')} B）"
                if image.get("source") == "geometry-render":
                    detail = (
                        f"（几何渲染，{image.get('findings', 0)} 条 finding 叠加，"
                        f"{image.get('bytes', '?')} B）"
                    )
                lines.append(f"- [{label}]({image['file']}){detail}")
            else:
                lines.append(f"- {label}：取图失败 —— {image.get('error')}")
        note = str(slots.get("canvas_images_note") or "")
        if note:
            lines.append("")
            lines.append(note)
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
    label = (
        entry.get("ruleName")
        or entry.get("rule_id")
        or entry.get("ruleId")
        or entry.get("kind")
        or ""
    )
    net = f" net {entry['net']}" if entry.get("net") else ""
    detail = f" —— {entry['detail']}" if entry.get("detail") else ""
    return f"- `{entry.get('severity')}` {number}x {label}{net}（{entry.get('ref')}）{detail}"


def _walk_leafs(group: dict) -> list[dict]:
    """Every leaf under a mapped group, in tree order."""
    out: list[dict] = list(group.get("leafs") or [])
    for child in group.get("children") or []:
        out.extend(_walk_leafs(child))
    return out


#: The pin count above which 190's declared-passive exemption does **not** apply
#: (192B ⑤). The exemption exists for the U-designated **two-pin** resistor 190
#: measured (``FRC1206J334 TS`` asked for a decoupling capacitor because its
#: designator letter was the only readable signal); a part with three or more
#: pins is not a chip resistor whatever its words say.
MAX_PASSIVE_PINS = 2


def _declared_passive(component) -> bool:
    """元数据或货架**声明**这颗是无源件（电阻/电容/电感/热敏）——190 未审闸的豁免条件。

    **192B ⑤：豁免只给 ≤ :data:`MAX_PASSIVE_PINS` 脚的件。** 190 的注释断言这条豁免
    不会少问——假话，而反例就是它自己引的那类料：立创目录名里带
    「电容」的触摸按键**芯片**（``TTP223``）被这条读成 capacitor，于是一颗真 IC
    静默掉出了未审闸（`.tmp_hole_sew3/probe6_declared_passive_leak.py`）。判型那边
    192B ① 已按「芯片/单片机/运放」优先判 IC 修掉这一类；这里加的是**反向守卫**，
    两个方向都要有：脚数 ≥ 3 的件一律不豁免，豁免造成的静默必须留在报告里
    （:func:`declared_passive_exemptions`，`completion.declaredPassiveExempt`，
    report.md 一行列位号）。

    脚数读不出（模型只读到一个占位件、调用方自己造的合成模型）时按 0 算，
    仍走豁免——「没数到」不是「数到很多脚」，与 127b 的脚地板同一条纪律。
    """
    from ..core.partkind import (
        KIND_CAPACITOR,
        KIND_INDUCTOR,
        KIND_RESISTOR,
        KIND_THERMISTOR,
        classify_part,
    )

    pins = len(getattr(component, "pins", ()) or ())
    if pins > MAX_PASSIVE_PINS:
        return False
    kind = classify_part(component, pin_floor=False)
    return kind.declared and kind.kind in (
        KIND_RESISTOR, KIND_CAPACITOR, KIND_INDUCTOR, KIND_THERMISTOR,
    )


def declared_passive_exemptions(model) -> list[dict]:
    """The parts 190's exemption took off the datasheet gate, with the reading (192B ⑤).

    One row per exempted placement: the designator, the kind the declaration gave
    it, that reading's basis/reason and its pin count. It exists because the
    exemption is the one path in this section that makes the gate **shorter**
    rather than longer, and a shorter gate with no trace is exactly the silent
    green light the section forbids: the count rides in
    ``completion.declaredPassiveExempt`` and report.md prints the designators.

    Read off the same predicate :func:`unreviewed_parts` applies, over the same
    placements (:func:`_parts_with_boards`), so the trace cannot disagree with
    what the gate did.
    """
    from ..core.partkind import classify_part
    from ..core.parts import is_ic_designator

    rows: list[dict] = []
    for designator, component, boards in _parts_with_boards(model):
        if not is_ic_designator(designator) or not _declared_passive(component):
            continue
        read = classify_part(component, pin_floor=False)
        rows.append({
            "designator": designator,
            "kind": read.kind,
            "basis": read.basis,
            "reason": read.reason,
            "pins": len(getattr(component, "pins", ()) or ()),
            "value": component.value,
            "footprint": component.footprint,
            **_board_field(
                boards,
                mpn=str(component.mpn or "").strip(),
                name=str(component.props.get("device_name") or component.value or ""),
                value=component.value,
            ),
        })
    return rows
