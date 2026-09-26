"""Schematic-side design model: SCH_PAGE -> components, pins, nets.

001/002 built the PCB-side parsers; this module is 005's addition for
schematic-only projects (the CH340G golden board has no PCB). It reads the
same ``.epru`` record stream (via :func:`iter_epru_records`, so the framing
stays in one place) and produces the regular
:class:`boardwise.core.model.DesignModel` contract, so ``compare`` and the
future generator work on one shape regardless of the source.

Encoding notes (measured on ``tests/fixtures/ch340_golden.epro2``, EasyEDA
Pro 3.2.149):

- A component instance is a ``COMPONENT`` record (``partId``, ``x``, ``y``,
  ``rotation``, ``isMirror``) followed in the stream by its ``ATTR`` records.
  ``Symbol`` names the SYMBOL document (uuid) that defines the symbol,
  ``Device`` the DEVICE document, ``Designator`` the instance designator.
  The linkage is pure stream adjacency — the attributes' ``parentId`` is the
  *symbol* uuid, not the instance's.
- A SYMBOL document defines pins: ``PIN`` records whose ``(x, y)`` is the
  connection point in symbol-local coordinates, with the pin number in a
  ``Pin Number`` ATTR whose ``parentId`` is ``"e<pin zIndex>"``.
- Wires: a ``WIRE`` head record followed by ``LINE`` segments; segments of
  one wire share a ``lineGroup``. A ``NET`` ATTR whose ``parentId`` is a
  ``lineGroup`` names that wire (usually empty — most nets are unnamed).
- Power symbols are component instances without a designator that carry a
  ``Global Net Name`` ATTR (``VCC``, ``GND``, ``+5V`` ...); their symbol pin
  names the net it touches. A *standalone* ``Global Net Name`` ATTR (one
  whose ``parentId`` is neither the instance's ``partId`` nor a symbol-scoped
  ``parentId``) is a positioned power flag: its ``(x, y)`` is a connection
  point carrying that net name.
- ``NO_CONNECT`` ATTRs mark pins as intentionally unconnected; their
  ``parentId`` is ``"<symbol uuid>-e<pin zIndex>"``.

Net names are resolved in this order: explicit ``NET`` label, power net
(symbol instance or standalone flag), then a deterministic fallback
(``NET1``, ``NET2``, ... assigned in a canonical cluster order) so the same
topology always yields the same names — golden-vs-candidate comparisons must
not depend on the editor's own auto-naming.

Known v0 limitations, recorded rather than hidden:

- Connectivity is endpoint-exact: a wire that *crosses* another, or that
  terminates in the middle of one (a T junction without a shared endpoint),
  is not detected. EasyEDA draws real junctions as shared endpoints.
- ``NO_CONNECT`` is keyed by symbol uuid, so if the same symbol is placed
  twice with different NC pins, both instances get the union. Not the case
  on this board.
"""

from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from boardwise.core.geometry import (
    COORD_PRECISION as _COORD_PRECISION,
)
from boardwise.core.geometry import transform_point as _transform_point
from boardwise.core.model import (
    BoardModel,
    BoardRef,
    Component,
    DesignModel,
    MultiBoardProjectError,
    Net,
    Pin,
    ProjectModel,
)

from .epru_stream import (
    ParseStats,
    iter_epru_records,
    load_epru_text,
)

#: Round coordinates to this many decimals before matching endpoints to pins.
#: The stream stores grid-snapped values; float parsing can add trailing
#: noise, and 6 decimals is far below any real grid step.
#: Re-exported: the transform and the rounding live in `core.geometry`
#: now, because `core` cannot import `parsers` but both need them.
COORD_PRECISION = _COORD_PRECISION

Point = tuple[float, float]


@dataclass
class _SymbolDef:
    """One SYMBOL library document.

    ``pins`` maps pin **number** -> (local point, ez key). ``pin_names`` maps
    the same numbers to the ``Pin Name`` attribute (``GND``, ``VBUS``, ``CC1``,
    …). The two are different identity systems for the same pin, and the
    second is what survives a library-symbol revision: measured 2026-09-14 on
    the golden board, where the file's USB-C symbol numbers its pins ``1..14``
    while the current library names the same physical contacts
    ``A1B12``/``B5``/``CC1`` — so a number-only identity is a false bank of
    differences, and the name is the stable key.
    """

    uuid: str
    title: str = ""
    pins: dict[str, tuple[Point, str]] = field(default_factory=dict)
    #: Pin number -> ``Pin Name`` attribute value (empty string when the
    #: symbol declares no name for that pin).
    pin_names: dict[str, str] = field(default_factory=dict)
    #: Pin number -> ``Pin Type`` (``Undefined``/``Power``/``Input``…).
    pin_types: dict[str, str] = field(default_factory=dict)


@dataclass
class _Instance:
    """One placed COMPONENT on a schematic page, with its trailing ATTRs."""

    part_id: str
    x: float
    y: float
    rotation: float
    is_mirror: bool
    z_index: Any = None
    attrs: dict[str, str] = field(default_factory=dict)
    #: The ``id`` of the ``COMPONENT`` record this placement was read from.
    #: It is what an attribute's ``parentId`` names when it belongs to this
    #: instance, and it is the only way to file an attribute that the editor
    #: wrote far away from its component (042 §WI-1) — "ATTR follows
    #: COMPONENT" is not a property of an incrementally saved document.
    record_id: str = ""
    #: The common ``parentId`` of the trailing attributes — the instance's
    #: container id in the original document. ``NO_CONNECT`` references pins
    #: through it (``"<container>-e<pin element id>"``).
    container_id: str = ""
    #: The ``SCH_PAGE`` document uuid this placement came from. Two pages are
    #: two coordinate systems (and, in a multi-board project, two boards), so
    #: every connectivity question is asked per page (040 §WI-1).
    page: str = ""


@dataclass
class _Page:
    """Everything the schematic pass needs from one ``SCH_PAGE`` document."""

    instances: list[_Instance] = field(default_factory=list)
    loose_attrs: list[dict[str, Any]] = field(default_factory=list)
    segments: dict[str, list[tuple[Point, Point]]] = field(default_factory=dict)


@dataclass(frozen=True)
class _LooseAttr:
    """A page-level ATTR together with the ``SCH_PAGE`` it was read from.

    *Loose* = it does not belong to the component before it: a ``NET`` label
    (its ``parentId`` is a wire group), a ``NO_CONNECT`` (a symbol pin), or a
    standalone ``Global Net Name`` flag. The page travels with it because both
    the flag's anchor and every coordinate lookup are page-local (040 §WI-1).
    """

    page: str
    body: dict[str, Any]


@dataclass
class _PageSplit:
    """One walk of the schematic records, ready for a page-scoped build.

    ``segments`` keeps **every** line group, graphics included: that is the raw
    drawing, and the replay path (:func:`collect_page_layout`) reads it as
    geometry. ``wire_groups`` names the subset a ``WIRE`` head owns — the only
    groups allowed to join a net (040 §WI-2; measured on the 毕设 board, where a
    header symbol's bracket graphic otherwise shorted three pins into one).

    ``pages`` maps a line group to its ``SCH_PAGE`` uuid, which is what lets
    the connectivity pass key its coordinate index by page. Group ids are
    uuids and every fixture measured carries each group on exactly one page, so
    the two structures cannot disagree.
    """

    instances: list[_Instance] = field(default_factory=list)
    loose: list[_LooseAttr] = field(default_factory=list)
    segments: dict[str, list[tuple[Point, Point]]] = field(default_factory=dict)
    wire_groups: set[str] = field(default_factory=set)
    pages: dict[str, str] = field(default_factory=dict)


def _page_y(stored: Any) -> float:
    """A stored page y -> **canvas** y. This is the one negation (task 010c).

    Measured 2026-09-18 (task 010c, M1): the `.epro2` stores y *opposite* to the
    editor's canvas — `stored_y = -canvas_y`, exact on 35 of 42 parts when the
    live `sch.geometry` of a project is compared against that same project's own
    file, and never the same sign. The canvas itself is y **up** (a two-marker
    test renders `y=700` at the page top, confirmed in the GUI).

    Since 010c's convention is "file space is canvas space", every coordinate a
    parser hands over is negated exactly here and nowhere else — callers work in
    canvas space and must not negate again.
    """
    return -float(stored or 0)


def _page_box(
    box: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """A stored bbox -> canvas bbox: ``[x0, y0, x1, y1] -> [x0, -y1, x1, -y0]``.

    The y range swaps ends, so a caller that reads ``box[1]`` as "the low edge"
    keeps meaning it.
    """
    x0, y0, x1, y1 = box
    return (x0, -y1, x1, -y0)


def _iter_schematic_records(text: str, stats: ParseStats) -> list[Any]:
    """Records of the schematic-relevant documents, in stream order.

    Collects every record of a ``SCH_PAGE`` or ``SYMBOL`` document *including*
    its ``DOCHEAD``, so the downstream groupers can see document boundaries.
    ``DEVICE`` documents contribute only their ``META`` (the device title the
    generator uses as a library-search keyword); everything else (PCB,
    FOOTPRINT, ...) is skipped after counting.

    ``SCH`` and ``BOARD`` documents contribute only their ``META`` too, and for
    one reason: they carry the board chain (040b §WI-1), which is

        ``SCH_PAGE.META.schematic`` → ``SCH.META.board`` → ``BOARD.META.title``

    — measured 2026-09-26 to hit on every real fixture (1 to 3 boards each) and
    to dangle exactly once, on the injected orphan page. Nothing else about those
    documents is read: their rules and their empty bodies are not part numbers.
    """
    out: list[Any] = []
    keep = False
    meta_only = False
    for record in iter_epru_records(text, stats):
        if record.type == "DOCHEAD":
            doc_type = record.body.get("docType")
            keep = doc_type in ("SCH_PAGE", "SYMBOL", "DEVICE")
            meta_only = doc_type in ("SCH", "BOARD")
            if keep or meta_only:
                out.append(record)
            continue
        if keep:
            out.append(record)
        elif meta_only and record.type == "META":
            out.append(record)
    return out


def _collect_device_titles(records: list[Any]) -> dict[str, str]:
    """DEVICE doc uuid -> device title, from each document's ``META``."""
    return {
        uuid: meta["title"]
        for uuid, meta in _collect_device_meta(records).items()
        if meta.get("title")
    }


#: The title a board gets when the container declares none: a project with no
#: ``BOARD`` document (every library-only or single-sheet export), and the folder
#: format's synthetic sample. One implicit board is what such a project is — not
#: a board we invented a name for.
IMPLICIT_BOARD_TITLE = "Board1"

#: The title of the group holding pages whose ``schematic`` reference dangles in
#: a project that has **more than one** board (040b §WI-0.2). ASCII and stable,
#: because it lands in a report and in a finding's ``board``: the report's own
#: prose says, in the reader's language, that these pages are in no board
#: document.
UNATTACHED_BOARD_TITLE = "unattached"


def board_partition(
    records: list[Any], *, project_meta: dict[str, Any] | None = None
) -> list[BoardRef]:
    """Group a project's ``SCH_PAGE`` documents into boards (040b §WI-1).

    The container states the chain itself, so this reads it rather than
    inferring one (039d had to match designator sets to guess the page↔board
    map — that guess is what this function replaces):

    * ``.epro2``: ``SCH_PAGE.META.schematic`` → ``SCH.META.board`` →
      ``BOARD.META.title``. Measured 2026-09-26 on six real fixtures: 100% hit
      (毕设 3 boards / 3 schematics / 4 pages, 高速电机控制器 2/2/3, the other
      four single-board), and the one dangling reference is the injected
      ``duplicate-designator`` orphan page.
    * eprj3 folder: the same chain lives in the index JSON —
      ``profile.sheets[page_uuid].schematic_uuid`` →
      ``profile.schematics[uuid].board`` → ``profile.boards[uuid].title`` (the
      official example's ``P1.esch2`` really does carry the sheet uuid in its
      ``SCH_PAGE`` DOCHEAD: ``ea6d0c40a1576515``). The 038 synthetic sample
      declares neither ``boards`` nor ``sheets``, so it lands on the implicit
      board — which is why the folder path must tolerate both.

    Boards come back in container order (``zIndex``, then uuid), each with its
    pages in stream order. A board with no page is kept: "this board has no
    schematic in the export" is a reading, and silently dropping it would make a
    three-board project look like a two-board one.

    Pages whose reference dangles are folded into the single board when there is
    exactly one, and otherwise land in :data:`UNATTACHED_BOARD_TITLE` — the
    report has to be able to say "this page is in no board document" instead of
    picking one (§WI-0.2).
    """
    page_uuids = [
        str(record.body.get("uuid") or "")
        for record in records
        if record.type == "DOCHEAD" and record.body.get("docType") == "SCH_PAGE"
    ]
    if str((project_meta or {}).get("format") or "") == "eprj3":
        boards, page_to_schematic = _board_chain_from_index(project_meta or {})
    else:
        boards, page_to_schematic = _board_chain_from_records(records)

    board_of_page: dict[str, str] = {}
    orphan_pages: list[str] = []
    for page_uuid in page_uuids:
        schematic = page_to_schematic.get(page_uuid)
        board_uuid = boards.get("schematic_board", {}).get(schematic or "")
        if board_uuid in boards["order"]:
            board_of_page[page_uuid] = board_uuid
        else:
            orphan_pages.append(page_uuid)

    if not boards["order"]:
        # No BOARD document at all (or a folder index without profile.boards):
        # one implicit board holds the project.
        return [
            BoardRef(uuid="", title=IMPLICIT_BOARD_TITLE, page_uuids=tuple(page_uuids))
        ]

    if orphan_pages and len(boards["order"]) == 1:
        for page_uuid in orphan_pages:
            board_of_page[page_uuid] = boards["order"][0]
        orphan_pages = []

    refs: list[BoardRef] = []
    for board_uuid in boards["order"]:
        pages = tuple(
            page_uuid for page_uuid in page_uuids if board_of_page.get(page_uuid) == board_uuid
        )
        refs.append(
            BoardRef(
                uuid=board_uuid,
                title=boards["titles"].get(board_uuid) or board_uuid,
                page_uuids=pages,
            )
        )
    if orphan_pages:
        refs.append(
            BoardRef(
                uuid="",
                title=UNATTACHED_BOARD_TITLE,
                page_uuids=tuple(orphan_pages),
            )
        )
    return refs


def _board_chain_from_records(
    records: list[Any],
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """The board chain as the ``.epro2`` record stream states it.

    Returns ``(boards, page_to_schematic)`` where ``boards`` is
    ``{"order": [...], "titles": {...}, "schematic_board": {...}}``.
    """
    order: list[str] = []
    titles: dict[str, str] = {}
    z_index: dict[str, Any] = {}
    schematic_board: dict[str, str] = {}
    page_to_schematic: dict[str, str | None] = {}
    doc_type = uuid = ""
    for record in records:
        if record.type == "DOCHEAD":
            doc_type = str(record.body.get("docType") or "")
            uuid = str(record.body.get("uuid") or "")
            continue
        if record.type != "META":
            continue
        body = record.body
        if doc_type == "BOARD":
            order.append(uuid)
            titles[uuid] = str(body.get("title") or "")
            z_index[uuid] = body.get("zIndex")
        elif doc_type == "SCH":
            schematic_board[uuid] = str(body.get("board") or "")
        elif doc_type == "SCH_PAGE":
            page_to_schematic[uuid] = body.get("schematic")
    # zIndex is the container's own board order; uuid breaks ties so two runs of
    # the same file never disagree.
    order.sort(key=lambda board_uuid: (
        z_index.get(board_uuid) if isinstance(z_index.get(board_uuid), (int, float)) else 10**6,
        board_uuid,
    ))
    return (
        {"order": order, "titles": titles, "schematic_board": schematic_board},
        page_to_schematic,
    )


def _board_chain_from_index(
    project_meta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """The same chain, as the folder format's index JSON states it (WI-0)."""
    profile = project_meta.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    boards_raw = profile.get("boards") or {}
    schematics_raw = profile.get("schematics") or {}
    sheets_raw = profile.get("sheets") or {}
    order: list[str] = []
    titles: dict[str, str] = {}
    z_index: dict[str, Any] = {}
    if isinstance(boards_raw, dict):
        for board_uuid, board in boards_raw.items():
            order.append(str(board_uuid))
            if isinstance(board, dict):
                titles[str(board_uuid)] = str(board.get("title") or "")
                z_index[str(board_uuid)] = board.get("zIndex")
    schematic_board: dict[str, str] = {}
    if isinstance(schematics_raw, dict):
        for schematic_uuid, schematic in schematics_raw.items():
            if isinstance(schematic, dict):
                schematic_board[str(schematic_uuid)] = str(schematic.get("board") or "")
    page_to_schematic: dict[str, str | None] = {}
    if isinstance(sheets_raw, dict):
        for sheet_uuid, sheet in sheets_raw.items():
            if isinstance(sheet, dict):
                page_to_schematic[str(sheet_uuid)] = sheet.get("schematic_uuid")
    order.sort(key=lambda board_uuid: (
        z_index.get(board_uuid) if isinstance(z_index.get(board_uuid), (int, float)) else 10**6,
        board_uuid,
    ))
    return (
        {"order": order, "titles": titles, "schematic_board": schematic_board},
        page_to_schematic,
    )


#: The DEVICE ``META.attributes`` keys the resolver needs, mapped to the
#: :class:`Component` field each one fills. Order matters: the first non-empty
#: value wins, and the fields are read in this order below.
DEVICE_ATTR_FIELDS: tuple[tuple[str, str], ...] = (
    ("Supplier Part", "lcsc_part"),
    ("Manufacturer Part", "mpn"),
    ("Manufacturer", "manufacturer"),
    ("Datasheet", "datasheet"),
    ("Supplier Footprint", "footprint"),
    ("Name", "name_template"),
)


def _collect_device_meta(records: list[Any]) -> dict[str, dict[str, str]]:
    """DEVICE doc uuid -> the library metadata that only the DEVICE has.

    Why this join exists (measured 2026-09-14, the 006b "library swap" root
    cause): a placed COMPONENT's own trailing ATTRs are a *partial copy* of
    the library device. When the schematic was saved with a stale local value
    or an empty field, the instance does **not** carry the truth — the DEVICE
    document does. U3 on the golden board is the worked example: its instance
    ATTRs say ``Value=1kΩ`` and ``Supplier Part=''`` while its DEVICE META
    says ``title=FRC0805J471 TS`` / ``Supplier Footprint=0805``. Resolving
    the placement from the instance alone therefore searched for a 1kΩ part
    of unspecified size and landed on a different library item — which is
    exactly the "库件替换" that put 0603 parts where the golden had 0402.

    The META is per-DEVICE, not per-instance, so two placements of the same
    device share one entry; the join key is the instance's ``Device`` attr
    (a DEVICE document uuid, confirmed 28/28 on the golden board in 005).

    ``is_part`` is 042 §WI-2's addition: ``"yes"`` when the library device
    declares a ``Designator`` template, ``"no"`` for a power symbol, a net flag
    or the page frame. It is the only fact in the record stream that says "this
    placement is supposed to have a name", which is what lets a parse say how
    many placements it could **not** name instead of silently dropping them
    (see :class:`boardwise.core.geometry.ParseStats`).
    """
    out: dict[str, dict[str, str]] = {}
    uuid = ""
    for record in records:
        if record.type == "DOCHEAD":
            uuid = str(record.body.get("uuid") or "") if record.body.get("docType") == "DEVICE" else ""
            continue
        if not uuid or record.type != "META":
            continue
        if uuid in out:
            continue
        body = record.body or {}
        attributes = body.get("attributes") or {}
        meta: dict[str, str] = {"title": str(body.get("title") or "").strip()}
        if isinstance(attributes, dict):
            for key, field in DEVICE_ATTR_FIELDS:
                value = attributes.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                # `"null"` is the editor's literal for "unset" (006 finding);
                # treat it as absent so a stale string cannot outrank a real value.
                if text and text != "null":
                    meta[field] = text
            # The DEVICE's own Symbol uuid is the library symbol *as saved in
            # the library*, which can differ from the instance's stale copy.
            symbol = str(attributes.get("Symbol") or "").strip()
            if symbol and symbol != "null":
                meta["symbol"] = symbol
            # Whether the *library* device is a part or a symbol (042 §WI-2):
            # a real part's META declares the designator it will be assigned
            # (``"R?"``/``"U?"``) and its ``Convert to PCB``/``Add into BOM``
            # flags, while a power symbol, a net flag and the page frame carry
            # only Symbol/Name/Description. Measured on all eight fixtures
            # (2026-09-26): every instance that ends up with no designator is
            # either the frame or a device with ``is_part == "no"``, and
            # ``llc_board.epro2``'s ``DC+`` flag is the case that defeats the
            # alternative title convention (``Ground-GND``/``Power-5V``) —
            # its title has no hyphen and both its ``Global Net Name`` and
            # ``Name`` attributes are empty strings.
            meta["is_part"] = "yes" if str(attributes.get("Designator") or "").strip() else "no"
        out[uuid] = meta
    return out


def _looks_like_a_nameless_part(
    inst: Any, device_meta: dict[str, dict[str, str]]
) -> bool:
    """Was this placement supposed to have a designator and did not get one?

    Called only for instances that arrive at the parts pass with no usable
    designator, and answers whether that is *expected*. ``False`` covers the
    three kinds of placement that legitimately have none:

    * the title-block frame (``zIndex`` absent) — a page, not a placement;
    * a power symbol or net flag — the library DEVICE declares no
      ``Designator`` template, and its ``Global Net Name``/``Name`` names the
      net it stands for;
    * the same when the DEVICE document is not in the file at all, judged by
      those two attributes instead.

    Everything else is a part the parse could not name, which is what
    042 §WI-2 counts. A missing DEVICE document counts as "unexplained" on
    purpose — "no library document" is not evidence of "not a part", and
    assuming it is would reproduce the silence being fixed. Measured
    2026-09-26 on all eight fixtures: 0 on the golden, llc, 药箱, 毕设 and
    synthetic eprj3 boards; 5 on ``robot_live.epro2`` and 67 on the 高速板
    **before** :func:`_split_page` filed the displaced attribute blocks — the
    parts the model was missing, to the count — and 0 on all eight after.
    """
    if inst.z_index is None:
        return False
    meta = device_meta.get((inst.attrs.get("Device") or "").strip())
    if meta is not None:
        return meta.get("is_part") == "yes"
    return not (
        (inst.attrs.get("Global Net Name") or "").strip()
        or (inst.attrs.get("Name") or "").strip()
    )


def _symbol_uuid_of(inst: Any, device_meta: dict[str, dict[str, str]]) -> str:
    """The instance's ``Symbol`` uuid, falling back to the DEVICE META (013).

    EasyEDA does not write the ``Symbol`` ATTR on early-placed basic parts
    (R/C/L/TP, old small-ticket instances): measured 2026-09-20 on the
    graduation board — 132 instances carry it, 25 do not, and those 25 are
    exactly the components that previously parsed out pin-less. Their DEVICE
    META ``attributes.Symbol`` is always present and points at a SYMBOL
    document with full PIN records, so the fallback resolves the library's
    own symbol. Instance-first on purpose: a *stale* instance copy (the 006b
    "library swap" lesson) is a placement-level fact that must not be
    overwritten by the library — the fallback only fires when the instance
    field is empty, which is "the editor never wrote it", not "the editor
    wrote an old one".
    """
    uuid = (inst.attrs.get("Symbol") or "").strip()
    if uuid:
        return uuid
    meta = device_meta.get((inst.attrs.get("Device") or "").strip(), {})
    return str(meta.get("symbol") or "").strip()


def resolve_component_identity(
    inst_attrs: dict[str, str], device_meta: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    """Merge one instance's attrs with its DEVICE META; report where each came from.

    **Instance wins where it has a value, META fills the gaps.** The instance
    is the *placement* (its Value may be a deliberate local override, which is
    legitimate), but an empty instance field must not shadow a populated
    library field — that gap is what made U3 unresolvable.

    Returns ``(fields, provenance)`` where ``fields`` uses the
    :class:`Component` field names and ``provenance`` lists
    ``"<field>=instance|device|<missing>"`` for every field, so the caller can
    report per-part fidelity instead of silently guessing.
    """
    fields: dict[str, str] = {}
    provenance: list[str] = []
    for attr_key, field in DEVICE_ATTR_FIELDS:
        raw = inst_attrs.get(attr_key)
        instance_value = str(raw).strip() if raw is not None else ""
        if instance_value and instance_value != "null":
            fields[field] = instance_value
            provenance.append(f"{field}=instance")
        elif device_meta.get(field):
            fields[field] = device_meta[field]
            provenance.append(f"{field}=device")
        else:
            fields[field] = ""
            provenance.append(f"{field}=missing")
    return fields, provenance


def _wire_head_groups(records: list[Any]) -> set[str]:
    """The line groups that are **wires**: the groups a ``WIRE`` record names.

    Measured 2026-09-26 (040 §WI-2) on all nine page-streams of the fixture set:
    a ``WIRE`` head carries the group id of its own ``LINE`` members in its ``id``
    (``WIRE id=3a042cc210e78826`` ⇢ ``LINE … lineGroup=3a042cc210e78826``), and
    **every** ``NET`` label's ``parentId`` is one of those groups — 0 exceptions,
    on the golden board (33 wire groups / 27 labels / 40 groups) and on the
    毕设 board (page ``40daf``: 60 / 58 / 163; page ``5f0f``: 226 / 204 / 445).
    The groups no head names are the graphics that come free with a placed
    symbol.

    The older form of this test — "the group of the next ``LINE`` record after a
    head" — reads the same file but **misses wires**: the golden board's
    ``C9.1 = GND`` wire (group ``53e74bed8853c849``) has two body-less ``LINE``
    placeholders between its head and its only real ``LINE``, so a scan that
    stops at the first ``LINE`` sees no group and drops that wire's connection
    (measured: 040 §WI-0, the regression that the 006b note did not catch). Both
    readings are kept, unioned: they agree on every measured stream, and the
    union stays correct if a future export writes a different id pair, which is
    exactly the failure mode 038 hit with PIN keys.

    Documents are **not** filtered here, deliberately: on all eight real
    fixtures every ``WIRE`` record sits inside its ``SCH_PAGE``, but the
    synthetic eprj3 page (``tests/fixtures/eprj3_synth``) stores the page's own
    elements after a ``SYMBOL`` section within the same glued stream, and a
    doc-type filter drops that page's only wire (measured: the 038 model test
    goes red). Nothing in this judgement needs the document — a head names its
    group wherever it sits.
    """
    groups: set[str] = set()
    pending = False
    for record in records:
        if record.type == "DOCHEAD":
            pending = False
            continue
        if record.type == "WIRE":
            if record.id:
                groups.add(str(record.id))  # a head names its own group
            pending = True
            continue
        if record.type != "LINE":
            # Every other kind of element is transparent to the head→line
            # pairing.
            continue
        if not record.body:
            # A body-less LINE carries no group and does not end the head's run.
            continue
        if pending:
            pending = False
            group = str(record.body.get("lineGroup") or "")
            if group:
                groups.add(group)
    return groups


def _split_page(records: list[Any], parse_stats: ParseStats | None = None) -> _PageSplit:
    """Group page records into component instances, loose ATTRs, wire segments.

    A ``COMPONENT`` record owns the ATTR records that immediately follow it —
    and, when they are not there, the ones that **name its record id**. The
    second half is 042 §WI-1, and it is not a refinement: EasyEDA Pro's
    incremental save inserts a changed ``COMPONENT`` back at its old ``ticket``
    position while its ATTRs are appended to the end of the document, so
    "ATTR follows COMPONENT" is a property of untouched parts only. Measured
    2026-09-26 on ``robot_live.epro2``: R4 / U8 / USB1 / SWD were read with no
    attributes at all (and with them C11, the 0603 capacitor whose own block
    was displaced, so the parse gave *its* designator to the component that had
    been drawn next to the block) — six parts mis-read on one page, silently,
    because a component with no Designator is simply not a part downstream.

    One ATTR is filed in this order:

    1. ``NET`` / ``NO_CONNECT`` — page-level, always loose: their ``parentId``
       is a wire group or a symbol pin, never a component.
    2. the **page frame** and ``Global Net Name`` — also page-level. The frame
       is the one ``COMPONENT`` with no ``zIndex`` (the same marker
       :func:`_fill_board_model` and :func:`collect_page_layout` use for "this
       is the page, not a placement"), and the attributes it names are the
       page's own metadata (``Width``/``Height``/``Page Size``/``@Page Name``).
       They stay in the loose list, which is where :func:`collect_page_layout`
       reads ``sheet_attrs`` from — attaching them would move a page's
       geometry onto an instance and change that reading for no gain (measured:
       it does, on the 高速板, whose two frames declare 1655x1170 and
       1170x825). ``Global Net Name`` keeps the rule it always had: loose
       unless the instance it follows claims it, because its ``parentId`` is a
       *library* template id (shared by every GND flag) or a container id.
    3. the record id its ``parentId`` names, when that id is a ``COMPONENT``
       drawn on the **same page** — the 042 half.
    4. the instance it follows, exactly as before.

    Step 4 is what leaves documents that do not parent ATTRs to components
    alone: the synthetic ``eprj3`` page (``tests/fixtures/eprj3_synth``)
    parents every ATTR to something else, and on the untouched parts of all
    eight real fixtures steps 3 and 4 agree — 042's regression tests assert that
    agreement on the fixture set rather than assuming it.

    ``parse_stats`` (task 042 §WI-1) counts the attributes that only step 3
    could place. It is optional so the four other callers keep their behaviour;
    :func:`build_project_model` is the one that passes it.

    Every instance and every loose attribute carries the ``SCH_PAGE`` it came
    from: a page is a coordinate system, and a multi-board project's pages are
    different boards, so nothing here may be pooled across them (040 §WI-1).
    The record-id index is page-checked for the same reason — a displaced
    block must not be moved onto another board by a parentId that matches its
    uuid there.
    """
    split = _PageSplit()
    split.wire_groups = _wire_head_groups(records)
    instances = split.instances
    loose = split.loose
    segments = split.segments
    page = ""

    # --- pass 1: every COMPONENT, so pass 2 can resolve a record id in either
    # direction. (The incremental save writes a displaced block *after* its
    # component as measured, but nothing in the format promises that, and a
    # lookup that only worked backwards would be a second silent drop.)
    for record in records:
        body = record.body
        if record.type == "DOCHEAD":
            if body is not None and body.get("docType") == "SCH_PAGE":
                page = str(body.get("uuid") or "")
            continue
        if record.type != "COMPONENT" or body is None:
            continue
        instance = _Instance(
            part_id=str(body.get("partId") or ""),
            x=float(body.get("x") or 0),
            y=_page_y(body.get("y")),
            rotation=float(body.get("rotation") or 0),
            is_mirror=bool(body.get("isMirror") or False),
            z_index=body.get("zIndex"),
            record_id=str(record.id or ""),
            page=page,
        )
        instances.append(instance)

    by_record_id: dict[str, _Instance] = {}
    for instance in instances:
        if instance.record_id:
            by_record_id.setdefault(instance.record_id, instance)

    # --- pass 2: the walk itself, unchanged except for step 3 above.
    page = ""
    current: _Instance | None = None
    next_instance = 0

    def owned_by_instance(attr: dict[str, Any]) -> bool:
        parent = attr.get("parentId")
        key = attr.get("key")
        if key == "NET":
            return False  # belongs to a wire group
        if key == "NO_CONNECT":
            return False  # belongs to a symbol pin
        if key == "Global Net Name":
            # A power symbol's net name travels with its instance — but its
            # parentId is the *library* part template id (shared by every
            # GND flag), or the instance's container id, never the instance
            # part id alone. Claim it when either matches; anything else is a
            # standalone page flag handled by position.
            if current is None:
                return False
            return parent in (current.part_id, current.container_id)
        return True

    for record in records:
        body = record.body
        if record.type == "DOCHEAD":
            # A new SCH_PAGE: its uuid is the page every record after it belongs
            # to (the grouper also ends the attribute run, as it always did).
            #
            # Any *other* document leaves the page as it is, deliberately. A
            # library document can sit **inside** a page's record run — measured
            # 2026-09-26 on the folder format, where a page file is
            # ``SCH_PAGE`` + the symbols it uses + the page's own components and
            # wires, and on all seven real ``.epro2`` fixtures the reverse also
            # holds (no ``COMPONENT`` and no grouped ``LINE`` ever sits in a
            # ``SYMBOL``/``DEVICE`` document). Blanking the page there would
            # orphan those instances from the page they are drawn on, which is
            # exactly what the board filter then sees as "this board has no
            # parts".
            if body.get("docType") == "SCH_PAGE":
                page = str(body.get("uuid") or "")
            current = None
            continue
        if body is None:
            current = None
            continue
        if record.type == "COMPONENT":
            current = instances[next_instance]  # pass 1 appended it in this order
            next_instance += 1
            continue
        if record.type == "ATTR":
            key = str(body.get("key"))
            named: _Instance | None = None
            if key not in ("NET", "NO_CONNECT", "Global Net Name"):
                candidate = by_record_id.get(str(body.get("parentId") or ""))
                if (
                    candidate is not None
                    and candidate.page == page
                    and candidate.z_index is not None
                ):
                    named = candidate
            if named is not None:
                owner = named
            elif current is not None and owned_by_instance(body):
                owner = current
            else:
                loose.append(_LooseAttr(page=page, body=body))
                continue
            value = body.get("value")
            owner.attrs[key] = "" if value is None else str(value)
            # The container id is the common parentId of the instance's own
            # ATTRs, and ``NO_CONNECT`` addresses a pin through it
            # (``"<container>-e<pin element id>"``). A rescued instance had no
            # attributes to take one from, so its first one must supply it.
            if not owner.container_id and body.get("parentId"):
                owner.container_id = str(body.get("parentId"))
            if parse_stats is not None and owner is not current:
                # Filed by the record id it names, not by its neighbour: this
                # is the only count that says "the document was edited, so
                # adjacency was not enough".
                parse_stats.attrs_attached_by_parent_id += 1
            continue
        if record.type == "ELE_PLACEHOLDER":
            # A placeholder is part of the element it precedes — it must NOT
            # end the current attribute run (measured: a power symbol's
            # Global Net Name attr comes after one).
            continue
        if record.type == "LINE":
            group = body.get("lineGroup")
            if group:
                start = (round(float(body.get("startX") or 0), COORD_PRECISION),
                         round(_page_y(body.get("startY")), COORD_PRECISION))
                end = (round(float(body.get("endX") or 0), COORD_PRECISION),
                       round(_page_y(body.get("endY")), COORD_PRECISION))
                segments.setdefault(str(group), []).append((start, end))
                split.pages.setdefault(str(group), page)
            continue
        # Any other element ends the current attribute run.
        current = None
    return split


def _collect_symbols(
    records: list[Any], parse_stats: ParseStats | None = None, *,
    pin_key: str = "zIndex",
) -> dict[str, _SymbolDef]:
    """Group SYMBOL documents into ``uuid -> pin number -> (point, ez key)``.

    Pin numbers are paired **by stream order**, not by ``parentId``: a ``PIN``
    record opens a run and the following ``Pin Number`` ATTR belongs to it.
    The parentId-based linkage looks tempting (``e<zIndex>``) but is measured
    unreliable — the resistor symbol ships ``PIN z=2`` with ``Pin Number``
    parented to ``e17`` — because those ids come from the original library
    document, which the export re-serialises.

    Each pin run also carries ``Pin Name`` and ``Pin Type`` ATTRs, and they
    arrive in an arbitrary order relative to ``Pin Number`` (measured: the
    USB-C symbol emits Pin Name first, then Pin Number, then Pin Type). So the
    run stays **open** until the next ``PIN`` record, and every ATTR that names
    the pin is attributed to the current run — a number is only written once
    the run closes, which is also why the runs are flushed at document
    boundaries. Getting this wrong silently attributes one pin's name to its
    neighbour, which is worse than an empty name because it looks like data.

    ``parse_stats`` (task 020 §WI-1) is where a run that closes **without** a
    number is counted. Such a pin is not in the symbol's pin map, so the whole
    pin — name, position and every connection it makes — is dropped; that used
    to be invisible. Counting changes nothing about the returned symbols.
    """
    symbols: dict[str, _SymbolDef] = {}
    current: _SymbolDef | None = None
    in_symbol = False
    pin_open: Point | None = None
    pin_ez: str | None = None
    run_number: str = ""
    run_name: str = ""
    run_type: str = ""

    def flush() -> None:
        """Commit the open pin run, if any, to the current symbol."""
        nonlocal pin_open, pin_ez, run_number, run_name, run_type
        if current is not None and pin_open is not None:
            if run_number:
                current.pins[run_number] = (pin_open, pin_ez or "")
                if run_name:
                    current.pin_names[run_number] = run_name
                if run_type:
                    current.pin_types[run_number] = run_type
            elif parse_stats is not None:
                # The run closed with a position but no number: the pin is
                # dropped (there is no key to file it under). Counted, never
                # guessed at — a name-only pin has no identity to key on.
                parse_stats.pins_dropped_no_number += 1
        pin_open, pin_ez, run_number, run_name, run_type = None, None, "", "", ""

    for record in records:
        if record.type == "DOCHEAD":
            flush()
            if current is not None and current.uuid:
                symbols.setdefault(current.uuid, current)
            in_symbol = record.body.get("docType") == "SYMBOL"
            current = _SymbolDef(uuid=str(record.body.get("uuid") or "")) if in_symbol else None
            continue
        if not in_symbol or current is None:
            continue
        body = record.body
        if record.type == "META":
            current.title = str(body.get("title") or "")
            continue
        if record.type == "PIN":
            flush()
            pin_open = (round(float(body.get("x") or 0), COORD_PRECISION),
                        round(_page_y(body.get("y")), COORD_PRECISION))
            # The key that ties a PIN to the attributes and NO_CONNECT parents
            # that reference it. V3 (`.epro2`) keys them by the *synthesised*
            # `e<zIndex>` (measured: 12 of the golden fixture's PIN rows have an
            # `id` that is NOT `e<zIndex>`, and its NO_CONNECT parents carry
            # `-e<zIndex>`); eprj3 keys them by the PIN row's own `id` (038 §1,
            # spec + example: `PIN id:"e1"` with `ATTR parentId:"e1"`).
            # Branching on the format is what the V3 regression demanded.
            if pin_key == "pin_id" and record.id:
                pin_ez = str(record.id)
            else:
                pin_ez = f"e{body.get('zIndex')}"
            continue
        if record.type == "ATTR" and pin_open is not None:
            key = body.get("key")
            value = str(body.get("value") or "").strip()
            if value and value != "null":
                if key == "Pin Number":
                    run_number = value
                elif key == "Pin Name":
                    run_name = value
                elif key == "Pin Type":
                    run_type = value
            continue
        if record.type == "ELE_PLACEHOLDER":
            continue  # part of the element stream, never a run boundary
    flush()
    if current is not None and current.uuid:
        symbols.setdefault(current.uuid, current)
    return symbols


class _UnionFind:
    """Minimal union-find over hashable nodes."""

    def __init__(self) -> None:
        self._parent: dict[Any, Any] = {}

    def find(self, node: Any) -> Any:
        self._parent.setdefault(node, node)
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:  # path compression
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def clusters(self) -> dict[Any, list[Any]]:
        groups: dict[Any, list[Any]] = {}
        for node in self._parent:
            groups.setdefault(self.find(node), []).append(node)
        return groups


def _stats_for(
    parse_stats: ParseStats | None, path: str | Path, meta: dict[str, Any]
) -> ParseStats:
    """One :class:`ParseStats` for this parse: the caller's, or a private one.

    A caller that wants to read what a parse dropped hands its own object in
    (task 020 §WI-1); the provenance fields are filled here because the source
    path and the editor version only exist *after* the file is decoded. A
    caller that does not care passes nothing and gets a throwaway — the
    counters then cost one integer increment per drop and are discarded, which
    is what every parse did before this existed.
    """
    if parse_stats is None:
        return ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    if not parse_stats.source:
        parse_stats.source = str(path)
    if not parse_stats.editor_version:
        parse_stats.editor_version = meta.get("editorVersion")
    return parse_stats


def _pin_key_for(meta: dict[str, Any]) -> str:
    """Which key ties a PIN to its attributes in *this* file's format.

    The container knows (``eprj3`` sets ``meta['format']``), and that is the whole
    reason this is a function rather than a constant: V3's `.epro2` files key pin
    attributes by the synthesised ``e<zIndex>`` (the golden fixture has 12 PIN rows
    whose own ``id`` differs from it, and every NO_CONNECT parent carries
    ``-e<zIndex>``), while eprj3 keys them by the PIN row's own ``id``. Switching
    the whole build to the eprj3 key broke V3 in the measurement this branch
    exists for, so the format decides and the V3 tests are the arbiter.
    """
    return "pin_id" if str(meta.get("format") or "") == "eprj3" else "zIndex"

def build_pin_offsets(
    path: str | Path, *, parse_stats: ParseStats | None = None
) -> dict[str, dict[str, Point]]:
    """Designator -> pin number -> *symbol-local* pin offset.

    The draw flow places every component unrotated and unmirrored, so a
    placed pin's page position is exactly ``placement + offset``. The
    offsets come from the golden file's own symbol definitions — the same
    library parts the connector places — which sidesteps the measured fact
    that ``sch_PrimitivePin.getAll()`` returns nothing for schematic pages
    (pins belong to symbols, not to the page primitive list).

    Coordinates are in the same units as the page (editor canvas units,
    1:1 with the file — measured). ``parse_stats`` counts the drops; see
    :func:`_stats_for`.
    """
    text, meta = load_epru_text(Path(path))
    stats = _stats_for(parse_stats, path, meta)
    records = _iter_schematic_records(text, stats)
    instances = _split_page(records).instances
    symbols = _collect_symbols(records, stats, pin_key=_pin_key_for(meta))
    device_meta = _collect_device_meta(records)

    offsets: dict[str, dict[str, Point]] = {}
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            continue
        # 013: early-placed parts carry no Symbol ATTR — fall back to the
        # DEVICE META so their pins resolve like everyone else's.
        symbol_def = symbols.get(_symbol_uuid_of(inst, device_meta))
        if symbol_def is None:
            stats.components_without_symbol += 1  # task 020 §WI-1: counted, not hidden
            continue
        offsets[designator] = {
            number: point for number, (point, _ez) in symbol_def.pins.items()
        }
    return offsets


@dataclass
class SymbolDetail:
    """Everything one ``SYMBOL`` document contributes, in one parse.

    A block template needs all of it at once — pin offsets to place the part's
    tips, pin *names* because that is the identity that survives a library
    revision, and the measured drawn extent to bound the part. Reading it
    through three separate helpers re-parsed the same file three times and
    let the three answers drift; this is the one shape they all come from.
    """

    uuid: str
    title: str = ""
    #: Pin number -> symbol-local offset (file coordinates).
    offsets: dict[str, Point] = field(default_factory=dict)
    pin_names: dict[str, str] = field(default_factory=dict)
    pin_types: dict[str, str] = field(default_factory=dict)
    #: Measured drawn extent (RECT/POLY/CIRCLE union), or ``None``.
    body: tuple[float, float, float, float] | None = None


def collect_part_devices(path: str | Path) -> dict[str, str]:
    """Designator -> the ``DEVICE`` document uuid the placement uses.

    The join the part harvest needs (008b): the schematic says *which device* is
    placed, and the DEVICE document's ``META`` then supplies the LCSC C-number,
    the MPN and the footprint. It goes through :func:`_split_page` rather than
    re-deriving "which ATTRs belong to this COMPONENT" — that rule has four
    clauses (an ATTR run ends at any other element, except ``ELE_PLACEHOLDER``
    and ``LINE``, and a body-less record ends it too) and a re-implementation
    that missed one of them silently attributed designators to the wrong device.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)
    instances = _split_page(records).instances

    out: dict[str, str] = {}
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        device = (inst.attrs.get("Device") or "").strip()
        if not designator or designator.endswith("?") or not device:
            continue
        out[designator] = device
    return dict(sorted(out.items()))


def collect_library_documents(path: str | Path) -> dict[str, tuple[str, str]]:
    """Document uuid -> ``(title, source)`` for the library documents.

    Both halves matter: the **title** is the library vocabulary name
    (``R0402`` — the thing a consumer must use, per 006b), and ``source`` is
    ``"<libraryDocUuid>|<libraryUuid>"``, the pair the library answers to. Only
    ``DEVICE``, ``FOOTPRINT`` and ``SYMBOL`` documents have either.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    out: dict[str, tuple[str, str]] = {}
    uuid = ""
    keep = False
    for record in iter_epru_records(text, stats):
        if record.type == "DOCHEAD":
            body = record.body or {}
            doc_type = str(body.get("docType") or "")
            keep = doc_type in ("DEVICE", "FOOTPRINT", "SYMBOL")
            uuid = str(body.get("uuid") or "") if keep else ""
            continue
        if not keep or not uuid or record.type != "META":
            continue
        body = record.body or {}
        out[uuid] = (str(body.get("title") or ""), str(body.get("source") or ""))
        keep = False  # one META per document
    return out


def collect_symbol_details(path: str | Path) -> dict[str, SymbolDetail]:
    """SYMBOL document uuid -> :class:`SymbolDetail`. One parse, all geometry.

    Symbols are included when they have pins *or* drawn geometry: a power flag
    has no pins but does have a glyph, and the annotation lint needs the glyph
    to predict the marker box.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)
    symbols = _collect_symbols(records, stats, pin_key=_pin_key_for(meta))

    extents: dict[str, tuple[float, float, float, float]] = {}

    def grow(uuid: str, box: tuple[float, float, float, float] | None) -> None:
        if not uuid or box is None:
            return
        previous = extents.get(uuid)
        extents[uuid] = box if previous is None else (
            min(previous[0], box[0]),
            min(previous[1], box[1]),
            max(previous[2], box[2]),
            max(previous[3], box[3]),
        )

    uuid = ""
    for record in records:
        if record.type == "DOCHEAD":
            uuid = (
                str(record.body.get("uuid") or "")
                if record.body.get("docType") == "SYMBOL"
                else ""
            )
            continue
        if not uuid or record.body is None:
            continue
        body = record.body
        if record.type == "RECT":
            try:
                x1, y1 = float(body["dotX1"]), float(body["dotY1"])
                x2, y2 = float(body["dotX2"]), float(body["dotY2"])
            except (KeyError, TypeError, ValueError):
                continue
            grow(uuid, (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
            continue
        if record.type == "POLY":
            points = body.get("points") or []
            try:
                xs = [float(p["x"]) for p in points]
                ys = [float(p["y"]) for p in points]
            except (KeyError, TypeError, ValueError):
                continue
            if xs and ys:
                grow(uuid, (min(xs), min(ys), max(xs), max(ys)))
            continue
        if record.type == "CIRCLE":
            try:
                cx, cy = float(body["centerX"]), float(body["centerY"])
                radius = float(body["radius"])
            except (KeyError, TypeError, ValueError):
                continue
            grow(uuid, (cx - radius, cy - radius, cx + radius, cy + radius))

    details: dict[str, SymbolDetail] = {}
    for key, symbol in symbols.items():
        box = extents.get(key)
        details[key] = SymbolDetail(
            uuid=key,
            title=symbol.title,
            offsets={number: point for number, (point, _ez) in symbol.pins.items()},
            pin_names=dict(symbol.pin_names),
            pin_types=dict(symbol.pin_types),
            body=None if box is None else _page_box(box),
        )
    for key, box in extents.items():
        details.setdefault(key, SymbolDetail(uuid=key, body=_page_box(box)))
    return details


def collect_symbol_defs(path: str | Path) -> dict[str, dict[str, tuple[float, float]]]:
    """SYMBOL document uuid -> pin number -> symbol-local pin offset.

    Public helper for the geometry-path candidate builder: the editor's
    ``sch.geometry`` dump does not expose pin primitives (measured), so pin
    positions on a placed page are ``component position + symbol offset``.
    Offsets are in file coordinates (y grows downward from the top-left
    page origin); see :func:`_transform_point` for the rotation convention.
    """
    return {
        uuid: dict(detail.offsets)
        for uuid, detail in collect_symbol_details(path).items()
        if detail.offsets
    }


def collect_part_placements(path: str | Path) -> dict[tuple[float, float], str]:
    """Page position (file coordinates) -> designator, for parts only.

    The geometry readback reports a part's X/Y in editor canvas units, which
    are 1:1 with the file except that the file's y axis is negated; callers
    convert before looking up. Positions are exact matches in practice —
    the editor stores the placed origin verbatim.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)
    instances = _split_page(records).instances
    out: dict[tuple[float, float], str] = {}
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            continue
        out[(round(float(inst.x), COORD_PRECISION), round(float(inst.y), COORD_PRECISION))] = (
            designator
        )
    return out


def build_project_model(
    path: str | Path, *, parse_stats: ParseStats | None = None
) -> ProjectModel:
    """Parse a schematic project into **one :class:`BoardModel` per board**.

    The boards come from the container's own chain (:func:`board_partition`), so
    a project that declares three boards yields three models and one that
    declares none yields one. Within a board, pages keep 040's page-scoped
    connectivity; across boards, nothing is shared — which is what makes the
    two ``U2``s of the 毕设 project both survive instead of the later one
    overwriting the earlier (040b §WI-2).

    ``parse_stats`` is the same caller-owned counter object
    ``build_schematic_model`` takes; every board's parse fills the same one.
    """
    text, meta = load_epru_text(Path(path))
    stats = _stats_for(parse_stats, path, meta)
    records = _iter_schematic_records(text, stats)

    split = _split_page(records, stats)
    symbols = _collect_symbols(records, stats, pin_key=_pin_key_for(meta))
    device_meta = _collect_device_meta(records)

    project = ProjectModel(source=str(path), project_raw={"project": dict(meta)})
    for ref in board_partition(records, project_meta=meta):
        board_model = BoardModel(board=ref)
        _fill_board_model(
            board_model, _board_slice(split, ref.page_uuids), symbols, device_meta, stats
        )
        project.boards.append(board_model)

    # One project-scoped fact per board: which of this board's designators other
    # boards also use, and in which order (so exactly one board reports it).
    cross = project.multi_board_designators()
    for board_model in project.boards:
        board_model.cross_board_designators = {
            designator: titles
            for designator, titles in cross.items()
            if board_model.board.title in titles
        }
    return project


def _board_slice(split: _PageSplit, page_uuids: tuple[str, ...]) -> _PageSplit:
    """The part of a project-wide :class:`_PageSplit` that belongs to one board."""
    pages = set(page_uuids)
    return _PageSplit(
        instances=[inst for inst in split.instances if inst.page in pages],
        loose=[item for item in split.loose if item.page in pages],
        segments={
            group: segs
            for group, segs in split.segments.items()
            if split.pages.get(group) in pages
        },
        wire_groups={
            group for group in split.wire_groups if split.pages.get(group) in pages
        },
        pages={
            group: page for group, page in split.pages.items() if page in pages
        },
    )


def build_schematic_model(
    path: str | Path, *, parse_stats: ParseStats | None = None
) -> DesignModel:
    """Parse a **single-board** schematic into a :class:`DesignModel`.

    The project's one board comes back as a :class:`BoardModel` (a
    :class:`DesignModel` with its board identity attached), so every existing
    consumer keeps its shape: the fields, the two repeat lists and the rules'
    input are what they were. A project with more than one board raises
    :class:`MultiBoardProjectError` — see :func:`build_project_model` for the
    entry point that handles those, and 040b §WI-2 for why a single model cannot.

    Raises the same errors :func:`boardwise.parsers.epru.load_epro2_source`
    raises for unreadable or encrypted inputs; the CLI turns those into exit
    code 2 instead of a traceback.

    ``parse_stats`` (task 020 §WI-1) is an optional caller-owned
    :class:`ParseStats` the parse fills in as it goes, so a caller can report
    what was dropped. The returned model is the same either way — the counters
    are the only difference.
    """
    project = build_project_model(path, parse_stats=parse_stats)
    if len(project.boards) > 1:
        raise MultiBoardProjectError(
            f"{path}: {len(project.boards)} boards "
            f"({', '.join(project.board_titles())}) — a project is not one "
            "model; use build_project_model()"
        )
    if not project.boards:
        return DesignModel()
    return project.boards[0]


def _fill_board_model(
    model: BoardModel,
    split: _PageSplit,
    symbols: dict[str, _SymbolDef],
    device_meta: dict[str, dict[str, str]],
    stats: ParseStats,
) -> None:
    """Fill one board's model from the records of its own pages (040b §WI-2).

    Everything below reads only ``split``, which
    :func:`build_project_model` has already narrowed to this board: that
    narrowing *is* the batch. The rules are 040's (page-scoped connectivity,
    wire-head-only groups) and the two repeat lists are 040's classification
    computed per board, so "same page", "same board, several pages" and "also on
    another board" are now three different readings instead of one.
    """
    instances, segments = split.instances, split.segments
    loose = [item.body for item in split.loose]

    components: dict[str, Component] = {}
    # designator -> {page uuid: placements seen}, so a designator that repeats
    # can be told apart **within this board**: twice on one page is a clash in
    # one netlist, once each on two pages is one board drawn on several sheets
    # (040 §WI-3; across boards it is not a repeat at all any more).
    placements_seen: dict[str, dict[str, int]] = {}
    # (instance, component, [(pin number, page point, ez key, pin name)])
    placed: list[tuple[_Instance, Component, list[tuple[str, Point, str, str]]]] = []

    # --- instances that carry a real designator become model components
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            # Power symbols and the title-block frame are not parts — but a
            # placement the *library* says is a part has to be reported when it
            # arrives here nameless, because that is exactly how 042's five
            # lost parts (and the 高速板's 67) were being dropped: no
            # designator, so no component, so nothing in the model and nothing
            # in the report (042 §WI-2).
            if _looks_like_a_nameless_part(inst, device_meta):
                stats.instances_without_designator += 1
            continue
        # 013: instance-first symbol uuid, DEVICE META as the fallback for
        # early-placed parts whose instance ATTR never carried one. Pin-less
        # components were the symptom: without the symbol document the pins
        # never instantiate, and every connection they make is lost.
        symbol_uuid = _symbol_uuid_of(inst, device_meta)
        meta = device_meta.get((inst.attrs.get("Device") or "").strip(), {})
        # Joined identity: the instance is the placement, the DEVICE META is
        # the library. See `resolve_component_identity` for why the empty
        # instance field must not shadow a populated library field.
        fields, provenance = resolve_component_identity(inst.attrs, meta)
        component = Component(
            uid=symbol_uuid or inst.part_id,
            designator=designator,
            value=(inst.attrs.get("Value") or "").strip(),
            footprint=fields.get("footprint", "") or (inst.attrs.get("Footprint") or "").strip(),
            lcsc_part=fields.get("lcsc_part", ""),
            manufacturer=fields.get("manufacturer", ""),
            mpn=fields.get("mpn", ""),
            datasheet=fields.get("datasheet", ""),
        )
        # The library device title (e.g. "CH340G") is what a keyword search
        # resolves when the part has no LCSC number of its own.
        device_name = meta.get("title", "")
        if device_name:
            component.props["device_name"] = device_name
        # Per-part fidelity, so a silent gap in the golden can never be
        # mistaken for a resolve that merely failed at placement time.
        component.props["identity_provenance"] = provenance
        component.props["device_uuid"] = (inst.attrs.get("Device") or "").strip()
        if meta.get("symbol"):
            component.props["library_symbol_uuid"] = meta["symbol"]
        # Which pages this designator was placed on. The assignment below keeps
        # only the last placement per designator (the "one designator, one
        # component" contract; 040b re-scopes it per board), and the two kinds
        # of repeat are not the same thing (040 §WI-3, measured on the 毕设
        # board: 30 refs repeat across three pages that are three boards) —
        # same page = two parts answer to one name in one netlist (a real
        # clash), different pages = another board numbering its own R1.
        pages_of = placements_seen.setdefault(designator, {})
        pages_of[inst.page] = pages_of.get(inst.page, 0) + 1
        components[designator] = component
        model.components[designator] = component
        symbol_def = symbols.get(symbol_uuid)
        pins: list[tuple[str, Point, str, str]] = []
        if symbol_def is not None:
            for number, (point, ez) in sorted(symbol_def.pins.items(), key=lambda kv: kv[0]):
                page_point = _transform_point(
                    point[0], point[1], rotation=inst.rotation,
                    mirror=inst.is_mirror, ox=inst.x, oy=inst.y,
                )
                pins.append((number, page_point, ez, symbol_def.pin_names.get(number, "")))
        else:
            # No symbol document behind this placement: the component is in the
            # model but carries no pins at all, so nothing it connects can be
            # checked. Counted (task 020 §WI-1) — the model itself is unchanged.
            stats.components_without_symbol += 1
        placed.append((inst, component, pins))

    # --- connectivity graph, page-scoped (040 §WI-1)
    #
    # Every key carries the page: a page is its own coordinate system, and in a
    # multi-board project its own board. Pooling them welded three boards'
    # netlists into one graph — the 毕设 board's "C115 has both pins on AGND"
    # and "U5 pin 5 is on AGND" were both that weld (039d), not the drawing.
    uf = _UnionFind()
    point_index: dict[tuple[str, Point], list[Any]] = {}

    # Only groups a WIRE head owns are wires (040 §WI-2). The rest of the
    # drawing — a placed symbol's own graphics — is not copper, and one such
    # segment (the 毕设 board's 46-unit vertical between its +24V and PGND
    # rails) was shorting a whole capacitor bank.
    for group in sorted(split.wire_groups):
        segs = segments.get(group) or []
        page = split.pages.get(group, "")
        for index, (start, end) in enumerate(segs):
            start_node = ("w", page, group, index, "s")
            end_node = ("w", page, group, index, "e")
            uf.find(start_node)
            uf.find(end_node)
            uf.union(start_node, end_node)  # segments of one wire are one net
            point_index.setdefault((page, start), []).append(start_node)
            point_index.setdefault((page, end), []).append(end_node)
    for nodes in point_index.values():
        for other in nodes[1:]:
            uf.union(nodes[0], other)  # wires touching at a point

    # --- no-connect pins: ``NO_CONNECT`` parents are
    # ``"<instance container id>-e<pin element id>"``; the container id is the
    # common parentId of that instance's trailing attributes.
    nc_set: set[tuple[str, str]] = set()
    for body in loose:
        if body.get("key") == "NO_CONNECT":
            parent = str(body.get("parentId") or "")
            if "-e" in parent:
                container, ez = parent.rsplit("-e", 1)
                nc_set.add((container, f"e{ez}"))

    pin_nodes: dict[tuple[str, str, str], Any] = {}
    for inst, component, pins in placed:
        for number, point, ez, _pin_name in pins:
            # (page, designator, number): the designator alone is not an
            # identity once two pages can hold it (040 §WI-1).
            key = (inst.page, component.designator, number)
            node = ("p",) + key
            pin_nodes[key] = node
            uf.find(node)
            if (inst.container_id, ez) in nc_set:
                continue  # NC pins stay off the connectivity graph
            touching = point_index.get((inst.page, point))
            if touching:
                uf.union(node, touching[0])

    # --- power pins and standalone power flags inject net names
    #
    # A flag's net name resolution order (measured against the editor's own
    # netlist 2026-09-13): the explicit ``Global Net Name`` value, then the
    # flag's ``Name`` attribute, then the *device title* — flag library
    # devices are titled ``Ground-GND`` / ``Power-VCC`` / ``Power-5V``, and
    # the half after the hyphen is exactly the net the editor assigns. The
    # last case covers the ten flags on this board whose GNN attribute is
    # empty and whose Name is blank: without the device title their nets
    # came out as deterministic ``NETn`` names while the editor called them
    # GND/+5V/VCC.
    def flag_net_name(inst: Any) -> str:
        # Flags are the instances WITHOUT a designator; a real part's own
        # Name/title (H1's '11-03P', U5's '33GB', the '={Value}' template)
        # must never leak into a net name — measured regression 2026-09-13.
        designator = (inst.attrs.get("Designator") or "").strip()
        if designator and not designator.endswith("?"):
            return ""
        gnn = (inst.attrs.get("Global Net Name") or "").strip()
        if gnn:
            return gnn
        name = (inst.attrs.get("Name") or "").strip()
        if name:
            return name
        title = device_meta.get((inst.attrs.get("Device") or "").strip(), {}).get("title", "")
        return title.split("-", 1)[1].strip() if "-" in title else ""

    forced: dict[Any, str] = {}
    for inst in instances:
        net_name = flag_net_name(inst)
        if not net_name:
            continue
        # 013: the same empty-Symbol-ATTR fallback as the parts pass — an
        # early-placed flag with no instance Symbol must still anchor its
        # net at the library symbol's pin position.
        symbol_def = symbols.get(_symbol_uuid_of(inst, device_meta))
        if symbol_def is None:
            # A flag with a net name but no symbol: it cannot anchor anything,
            # and every wire it was meant to name keeps its auto-name. Counted
            # with the parts pass (task 020 §WI-1) — one counter for "this
            # placement has no symbol behind it", whether it is a part or a flag.
            stats.components_without_symbol += 1
            continue
        for _number, (point, _ez) in symbol_def.pins.items():
            page_point = _transform_point(
                point[0], point[1], rotation=inst.rotation,
                mirror=inst.is_mirror, ox=inst.x, oy=inst.y,
            )
            for node in point_index.get((inst.page, page_point), []):
                forced.setdefault(uf.find(node), net_name)
    for item in split.loose:
        # Standalone power flags carry the net name and the point where it
        # attaches; both must be present to be usable. The page comes with the
        # attribute — the same coordinate on another page is another node.
        body = item.body
        if body.get("key") == "Global Net Name" and body.get("value"):
            x, y = body.get("x"), body.get("y")
            if x is None or y is None:
                continue
            flag_point = (round(float(x), COORD_PRECISION),
                          round(_page_y(y), COORD_PRECISION))
            for node in point_index.get((item.page, flag_point), []):
                forced.setdefault(uf.find(node), str(body["value"]))

    # --- name every cluster deterministically
    labels: dict[Any, str] = {}
    clusters = uf.clusters()
    explicit: dict[Any, str] = {}
    for root, nodes in clusters.items():
        # explicit NET label on any wire group of the cluster (the wire node is
        # ("w", page, group, index, end), so the group id is node[2])
        group_labels = sorted(
            {net_labels_of(segments, loose, g) for g in (n[2] for n in nodes if n[0] == "w")}
            - {""},
        )
        if group_labels:
            explicit[root] = group_labels[0]
        elif root in forced:
            explicit[root] = forced[root]
    # deterministic auto-names for the remaining clusters, in canonical order
    remaining = sorted(
        (root for root in clusters if root not in explicit),
        key=lambda root: min(sorted(str(n) for n in clusters[root])),
    )
    for index, root in enumerate(remaining, start=1):
        explicit[root] = f"NET{index}"
    labels = explicit

    # --- fill Pin.net and reverse-build nets
    nets: dict[str, Net] = {}
    for inst, component, pins in placed:
        for number, point, ez, pin_name in pins:
            # the pin's own page: the designator alone is ambiguous once two
            # pages can hold it (040 §WI-1).
            node = pin_nodes[(inst.page, component.designator, number)]
            name = labels.get(uf.find(node), "")
            is_nc = (inst.container_id, ez) in nc_set
            component.pins.append(
                Pin(number=number, name=pin_name, net=None if is_nc else (name or None))
            )
            if is_nc or not name:
                continue
            net = nets.setdefault(name, Net(name=name))
            member = (component.designator, number)
            if member not in net.pins:
                net.pins.append(member)
    model.nets = nets

    # --- how a repeated designator reads **within this board** (040 §WI-3, 040b)
    for designator in sorted(placements_seen):
        pages_of = placements_seen[designator]
        if sum(pages_of.values()) < 2:
            continue
        if any(count > 1 for count in pages_of.values()):
            # twice on one page: two parts, one name, one netlist — the clash
            # CONN-1 is about. (Defect dominates when both kinds are true.)
            model.duplicate_designators.append(designator)
        elif len(pages_of) > 1:
            # one placement per page, several pages of *this board*: one design
            # drawn across sheets, so the name still resolves to two parts in
            # one netlist. (Until 040b this bucket also held the cross-board
            # repeats, which is exactly what it must no longer do.)
            model.cross_page_designators[designator] = sorted(pages_of)


def net_labels_of(
    segments: dict[str, list[tuple[Point, Point]]],
    loose: list[dict[str, Any]],
    group: str,
) -> str:
    """The explicit ``NET`` label of one wire group (``""`` when unlabelled)."""
    for body in loose:
        if body.get("key") == "NET" and str(body.get("parentId") or "") == group:
            return str(body.get("value") or "").strip()
    return ""


# --------------------------------------------------------------------------
# 006b: golden page layout (replay input)
# --------------------------------------------------------------------------
#
# "Layout is data": the golden ``.epro2`` carries the human's own placement —
# every COMPONENT's x/y/rotation/mirror, every WIRE's line segments, every
# visibility choice for the net-name attributes. The replay generator
# (``engines.replay``) copies that geometry onto a fresh page instead of
# inventing one, so zoning / orientation / spacing are inherited rather than
# re-solved. This section extracts that data; nothing here changes the
# connectivity pass above.
#
# How a *wire* is told apart from a symbol's own graphics (both arrive as
# ``LINE`` records with a ``lineGroup``, measured on the golden fixture: 40
# groups, 128 lines, but only 33 ``WIRE`` heads):
#
# * each ``WIRE`` head owns the group of the **next** ``LINE`` record after it
#   — 33 heads -> 33 distinct groups, no group owned twice (measured);
# * the corroborating signature: every ``NET`` attribute's ``parentId`` is one
#   of those 33 groups (27/27 measured), and the seven leftover groups carry
#   neither a head nor a ``NET`` attribute (they are the short pin-lead
#   graphics that come free with a placed symbol).
#
# Both facts are asserted in the tests, so a future format change fails loudly
# instead of silently replaying symbol graphics as wires.


@dataclass
class PlacedPart:
    """One placed part on a golden page, in *file* coordinates."""

    designator: str
    x: float
    y: float
    rotation: float
    mirror: bool
    symbol_uuid: str = ""


@dataclass
class PlacedFlag:
    """One power / ground flag: the net name and where the human put it."""

    net: str
    kind: str  # 'Power' | 'Ground'
    x: float
    y: float
    rotation: float
    mirror: bool
    #: The flag symbol's library uuid — its drawn glyph is a measured symbol
    #: body (10..19 units from the anchor, measured), which is what the
    #: annotation lint needs to predict the rendered marker box.
    symbol_uuid: str = ""


@dataclass
class WireRun:
    """One wire polyline (a chained, branch-split run) in *file* coordinates."""

    group: str
    net: str
    points: list[Point]


@dataclass
class NetLabelAnchor:
    """One *visible* net-name label (``NET`` attribute with a value)."""

    net: str
    x: float
    y: float
    rotation: float


@dataclass
class PageLayout:
    """Everything the replay needs from one golden schematic page."""

    parts: list[PlacedPart] = field(default_factory=list)
    flags: list[PlacedFlag] = field(default_factory=list)
    wires: list[WireRun] = field(default_factory=list)
    labels: list[NetLabelAnchor] = field(default_factory=list)
    #: The sheet symbol's own declared geometry (``Width``/``Height``/
    #: ``Border``/``Title Block Position``/... , as strings). Read from the page
    #: frame's own attributes since 042 — see :func:`collect_page_layout`.
    sheet_attrs: dict[str, str] = field(default_factory=dict)
    #: The sheet element's anchor, file coordinates.
    sheet_origin: Point = (0.0, 0.0)
    #: Wire groups whose segments could not be chained (should be empty).
    notes: list[str] = field(default_factory=list)

    def wire_groups(self) -> int:
        return len(self.wires)


def _round_point(x: Any, y: Any) -> Point:
    return (round(float(x or 0), COORD_PRECISION), round(float(y or 0), COORD_PRECISION))


def _chain_segments(segments: list[tuple[Point, Point]]) -> list[list[Point]]:
    """Split a segment soup into polylines (one per branch-free run).

    Wires arrive as unordered ``LINE`` records that may share endpoints, and a
    net can branch (a T). A single editor wire primitive is a polyline, so a
    branch has to become several runs: edges are walked from every odd-degree
    node (and from whatever is left) until the walk runs out of unused edges.
    Deterministic: nodes and edges are processed in sorted order.
    """
    edges: list[tuple[Point, Point]] = []
    for a, b in segments:
        if a == b:
            continue  # zero-length placeholders exist in real exports
        edges.append((a, b))
    if not edges:
        return []

    adjacency: dict[Point, list[int]] = {}
    for index, (a, b) in enumerate(edges):
        adjacency.setdefault(a, []).append(index)
        adjacency.setdefault(b, []).append(index)

    degree = {node: len(inc) for node, inc in adjacency.items()}
    used: set[int] = set()
    runs: list[list[Point]] = []

    def walk(start: Point) -> list[Point]:
        run = [start]
        node = start
        while True:
            candidates = sorted(i for i in adjacency.get(node, []) if i not in used)
            if not candidates:
                break
            # Prefer the straight continuation so a crossing-free run stays
            # one polyline instead of turning at every shared node.
            straight = [
                i for i in candidates
                if (run[-2] if len(run) >= 2 else None) is not None
                and _collinear(run[-2], node, _other(edges[i], node))
            ]
            pick = straight[0] if straight else candidates[0]
            used.add(pick)
            a, b = edges[pick]
            node = b if a == node else a
            run.append(node)
        return run

    for node in sorted(degree, key=lambda p: (p[0], p[1])):
        if degree[node] % 2 == 1:
            runs.append(walk(node))
    for node in sorted(degree, key=lambda p: (p[0], p[1])):
        while any(i not in used for i in adjacency[node]):
            runs.append(walk(node))
    return [run for run in runs if len(run) >= 2]


def _other(edge: tuple[Point, Point], node: Point) -> Point:
    return edge[1] if edge[0] == node else edge[0]


def _collinear(a: Point, b: Point, c: Point) -> bool:
    return (abs(a[0] - b[0]) < 1e-9 and abs(b[0] - c[0]) < 1e-9) or (
        abs(a[1] - b[1]) < 1e-9 and abs(b[1] - c[1]) < 1e-9
    )


def _flag_kind(net: str, title: str) -> str:
    """``createNetFlag`` kind for a flag whose device title is ``title``.

    Measured titles on the golden board: ``Ground-GND``, ``Power-VCC``,
    ``Power-5V`` — the prefix names the flag family, the suffix the net.
    """
    family = title.split("-", 1)[0].strip().lower() if "-" in title else ""
    if family == "ground" or net.upper() in ("GND", "AGND", "PGND", "DGND"):
        return "Ground"
    return "Power"


#: The ATTR keys that describe the *sheet* rather than a part — page size, the
#: border, the title-block box, the drawing regions. They stay page-level in
#: ``_split_page`` (see step 2 there), which is why this reader still takes them
#: from the loose list: the page frame is the page, and pooling its geometry is
#: what ``sheet_attrs`` has always meant.
_SHEET_ATTR_KEYS: tuple[str, ...] = (
    "Width", "Height", "Border", "Size", "Page Size", "Blade Width",
    "Title Block", "Title Block Position", "Region Start",
    "X Region Count", "Y Region Count",
)


def collect_page_layout(path: str | Path) -> PageLayout:
    """Extract the golden page's *layout* (replay input) — task 006b.

    Reads the same ``SCH_PAGE`` records the connectivity pass reads, but keeps
    the geometry the model throws away: part origins and rotations, flag
    positions and orientations, wire polylines, and the anchors of the
    *visible* net labels. Coordinates stay in **file** space; the replay
    generator owns the file->canvas conversion.

    A flag's or a part's *identity* comes from the instance's own attributes,
    which is why 042's parentId rule shows up here as data and not as code: an
    instance whose attribute block was displaced now carries its
    ``Designator``/``Symbol``, so this reader sees the same parts the
    connectivity pass does instead of nameless orphans.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)
    split = _split_page(records)
    instances, segments = split.instances, split.segments
    # The layout is read as drawn geometry, so it takes the loose attributes as
    # plain bodies; only the connectivity pass needs their page (040 §WI-1).
    loose = [item.body for item in split.loose]
    device_titles = _collect_device_titles(records)

    layout = PageLayout()

    # --- parts, and the sheet element
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if designator and not designator.endswith("?"):
            layout.parts.append(
                PlacedPart(
                    designator=designator,
                    x=round(float(inst.x), COORD_PRECISION),
                    y=round(float(inst.y), COORD_PRECISION),
                    rotation=float(inst.rotation or 0.0),
                    mirror=bool(inst.is_mirror),
                    symbol_uuid=(inst.attrs.get("Symbol") or "").strip(),
                )
            )
            continue
        if inst.z_index is None:
            layout.sheet_origin = _round_point(inst.x, inst.y)
            continue
        net = (
            (inst.attrs.get("Global Net Name") or "").strip()
            or (inst.attrs.get("Name") or "").strip()
        )
        title = device_titles.get((inst.attrs.get("Device") or "").strip(), "")
        if not net and "-" in title:
            net = title.split("-", 1)[1].strip()
        if not net:
            continue
        layout.flags.append(
            PlacedFlag(
                net=net,
                kind=_flag_kind(net, title),
                x=round(float(inst.x), COORD_PRECISION),
                y=round(float(inst.y), COORD_PRECISION),
                rotation=float(inst.rotation or 0.0),
                mirror=bool(inst.is_mirror),
                symbol_uuid=(inst.attrs.get("Symbol") or "").strip(),
            )
        )

    # --- wire groups: owned by a WIRE head (see the section comment)
    net_by_group = {
        str(body.get("parentId")): str(body.get("value") or "").strip()
        for body in loose
        if body.get("key") == "NET" and body.get("parentId")
    }
    # The same judgement the connectivity pass makes (040 §WI-2): a group is a
    # wire when a WIRE head owns it. Reused rather than re-derived, so a wire
    # can never be a wire for one reader and a graphic for the other.
    wire_groups: set[str] = set(split.wire_groups)
    wire_groups.update(net_by_group)

    for group in sorted(wire_groups):
        raw = segments.get(group) or []
        if not raw:
            continue
        for run in _chain_segments(raw):
            layout.wires.append(WireRun(group=group, net=net_by_group.get(group, ""), points=run))
    if len(layout.wires) < len(wire_groups):
        layout.notes.append(
            f"{len(wire_groups) - len(layout.wires)} wire group(s) produced no polyline"
        )

    # --- visible net labels (an empty value renders nothing)
    for body in loose:
        if body.get("key") != "NET":
            continue
        value = str(body.get("value") or "").strip()
        if not value or body.get("x") is None or body.get("y") is None:
            continue
        layout.labels.append(
            NetLabelAnchor(
                net=value,
                x=round(float(body["x"]), COORD_PRECISION),
                y=round(_page_y(body["y"]), COORD_PRECISION),
                rotation=float(body.get("rotation") or 0.0),
            )
        )

    # --- the sheet's declared geometry (A4 / 1170 x 825 / border / ...)
    for body in loose:
        key = str(body.get("key") or "")
        if key in _SHEET_ATTR_KEYS:
            value = body.get("value")
            if value is not None:
                layout.sheet_attrs[key] = str(value)
    return layout


def collect_symbol_bodies(path: str | Path) -> dict[str, tuple[float, float, float, float]]:
    """SYMBOL document uuid -> **measured** drawn extent, symbol-local.

    The drawn symbol is real geometry in the library: a ``RECT`` for an IC
    body (measured: CH340G declares ``(-30, 45) -> (30, -45)``, the crystal
    ``(-20, 20) -> (20, -20)``) and ``POLY``/``CIRCLE`` for passives and
    indicators (a 0402 capacitor draws its plates and leads as four POLYs).
    The union of those records is the box a human sees.

    ``PIN`` records are deliberately *not* part of it: a pin is a connection
    point, and an IC's pin leads run well outside its body — bounding by pin
    extents instead makes the human's own decoupling capacitors "overlap" the
    chip they decouple (measured: 19 false ``BOX_OVERLAP`` rows on the golden
    page with a pin-extent box, none with the drawn extent).

    Coordinates are symbol-local, y up, exactly like
    :func:`collect_symbol_defs`. Read through :func:`collect_symbol_details`,
    which is the one parse all three answers come from.
    """
    return {
        uuid: detail.body
        for uuid, detail in collect_symbol_details(path).items()
        if detail.body is not None
    }
