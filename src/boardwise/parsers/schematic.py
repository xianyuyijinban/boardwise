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
from boardwise.core.model import Component, DesignModel, Net, Pin

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
    #: The common ``parentId`` of the trailing attributes — the instance's
    #: container id in the original document. ``NO_CONNECT`` references pins
    #: through it (``"<container>-e<pin element id>"``).
    container_id: str = ""


@dataclass
class _Page:
    """Everything the schematic pass needs from one ``SCH_PAGE`` document."""

    instances: list[_Instance] = field(default_factory=list)
    loose_attrs: list[dict[str, Any]] = field(default_factory=list)
    segments: dict[str, list[tuple[Point, Point]]] = field(default_factory=dict)


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
    """
    out: list[Any] = []
    keep = False
    is_device = False
    for record in iter_epru_records(text, stats):
        if record.type == "DOCHEAD":
            doc_type = record.body.get("docType")
            keep = doc_type in ("SCH_PAGE", "SYMBOL", "DEVICE")
            is_device = doc_type == "DEVICE"
        if keep:
            out.append(record)
        elif is_device and record.type == "META":
            out.append(record)
    return out


def _collect_device_titles(records: list[Any]) -> dict[str, str]:
    """DEVICE doc uuid -> device title, from each document's ``META``."""
    return {
        uuid: meta["title"]
        for uuid, meta in _collect_device_meta(records).items()
        if meta.get("title")
    }


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
        out[uuid] = meta
    return out


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


def _split_page(records: list[Any]) -> tuple[list[_Instance], list[dict[str, Any]], dict[str, list[tuple[Point, Point]]]]:
    """Group page records into component instances, loose ATTRs, wire segments.

    A ``COMPONENT`` record owns the ATTR records that immediately follow it —
    except the page-level kinds whose ``parentId`` points elsewhere (``NET``
    labels point at a ``lineGroup``, ``NO_CONNECT`` at a symbol pin, a
    standalone ``Global Net Name`` at a flag uuid). Those are collected as
    *loose* attributes so they can be resolved page-wide.
    """
    instances: list[_Instance] = []
    loose: list[dict[str, Any]] = []
    segments: dict[str, list[tuple[Point, Point]]] = {}

    current: _Instance | None = None

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
        if body is None:
            current = None
            continue
        if record.type == "COMPONENT":
            current = _Instance(
                part_id=str(body.get("partId") or ""),
                x=float(body.get("x") or 0),
                y=_page_y(body.get("y")),
                rotation=float(body.get("rotation") or 0),
                is_mirror=bool(body.get("isMirror") or False),
                z_index=body.get("zIndex"),
            )
            instances.append(current)
            continue
        if record.type == "ATTR":
            if current is not None and owned_by_instance(body):
                value = body.get("value")
                key = str(body.get("key"))
                current.attrs[key] = "" if value is None else str(value)
                if not current.container_id and body.get("parentId"):
                    current.container_id = str(body.get("parentId"))
            else:
                loose.append(body)
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
            continue
        # Any other element ends the current attribute run.
        current = None
    return instances, loose, segments


def _collect_symbols(records: list[Any]) -> dict[str, _SymbolDef]:
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
        if current is not None and pin_open is not None and run_number:
            current.pins[run_number] = (pin_open, pin_ez or "")
            if run_name:
                current.pin_names[run_number] = run_name
            if run_type:
                current.pin_types[run_number] = run_type
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


def build_pin_offsets(path: str | Path) -> dict[str, dict[str, Point]]:
    """Designator -> pin number -> *symbol-local* pin offset.

    The draw flow places every component unrotated and unmirrored, so a
    placed pin's page position is exactly ``placement + offset``. The
    offsets come from the golden file's own symbol definitions — the same
    library parts the connector places — which sidesteps the measured fact
    that ``sch_PrimitivePin.getAll()`` returns nothing for schematic pages
    (pins belong to symbols, not to the page primitive list).

    Coordinates are in the same units as the page (editor canvas units,
    1:1 with the file — measured).
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)
    instances, _loose, _segments = _split_page(records)
    symbols = _collect_symbols(records)

    offsets: dict[str, dict[str, Point]] = {}
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            continue
        symbol_def = symbols.get((inst.attrs.get("Symbol") or "").strip())
        if symbol_def is None:
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
    instances, _loose, _segments = _split_page(records)

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
    symbols = _collect_symbols(records)

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
    instances, _loose, _segments = _split_page(records)
    out: dict[tuple[float, float], str] = {}
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            continue
        out[(round(float(inst.x), COORD_PRECISION), round(float(inst.y), COORD_PRECISION))] = (
            designator
        )
    return out


def build_schematic_model(path: str | Path) -> DesignModel:
    """Parse a schematic-only ``.epro2`` into a :class:`DesignModel`.

    Raises the same errors :func:`boardwise.parsers.epru.load_epro2_source`
    raises for unreadable or encrypted inputs; the CLI turns those into exit
    code 2 instead of a traceback.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)

    instances, loose, segments = _split_page(records)
    symbols = _collect_symbols(records)
    device_meta = _collect_device_meta(records)

    model = DesignModel()
    components: dict[str, Component] = {}
    # (instance, component, [(pin number, page point, ez key, pin name)])
    placed: list[tuple[_Instance, Component, list[tuple[str, Point, str, str]]]] = []

    # --- instances that carry a real designator become model components
    for inst in instances:
        designator = (inst.attrs.get("Designator") or "").strip()
        if not designator or designator.endswith("?"):
            continue  # power symbols and the title-block frame are not parts
        symbol_uuid = (inst.attrs.get("Symbol") or "").strip()
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
        placed.append((inst, component, pins))

    # --- connectivity graph
    uf = _UnionFind()
    point_index: dict[Point, list[Any]] = {}

    for group, segs in segments.items():
        for index, (start, end) in enumerate(segs):
            start_node = ("w", group, index, "s")
            end_node = ("w", group, index, "e")
            uf.find(start_node)
            uf.find(end_node)
            uf.union(start_node, end_node)  # segments of one wire are one net
            point_index.setdefault(start, []).append(start_node)
            point_index.setdefault(end, []).append(end_node)
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

    pin_nodes: dict[tuple[str, str], Any] = {}
    for inst, component, pins in placed:
        for number, point, ez, _pin_name in pins:
            node = ("p", component.designator, number)
            pin_nodes[(component.designator, number)] = node
            uf.find(node)
            if (inst.container_id, ez) in nc_set:
                continue  # NC pins stay off the connectivity graph
            touching = point_index.get(point)
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
        symbol_def = symbols.get((inst.attrs.get("Symbol") or "").strip())
        if symbol_def is None:
            continue
        for _number, (point, _ez) in symbol_def.pins.items():
            page_point = _transform_point(
                point[0], point[1], rotation=inst.rotation,
                mirror=inst.is_mirror, ox=inst.x, oy=inst.y,
            )
            for node in point_index.get(page_point, []):
                forced.setdefault(uf.find(node), net_name)
    for body in loose:
        # Standalone power flags carry the net name and the point where it
        # attaches; both must be present to be usable.
        if body.get("key") == "Global Net Name" and body.get("value"):
            x, y = body.get("x"), body.get("y")
            if x is None or y is None:
                continue
            flag_point = (round(float(x), COORD_PRECISION),
                          round(_page_y(y), COORD_PRECISION))
            for node in point_index.get(flag_point, []):
                forced.setdefault(uf.find(node), str(body["value"]))

    # --- name every cluster deterministically
    labels: dict[Any, str] = {}
    clusters = uf.clusters()
    explicit: dict[Any, str] = {}
    for root, nodes in clusters.items():
        # explicit NET label on any wire group of the cluster
        group_labels = sorted(
            {net_labels_of(segments, loose, g) for g in (n[1] for n in nodes if n[0] == "w")}
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
            node = pin_nodes[(component.designator, number)]
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
    return model


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
    #: ``Border``/``Title Block Position``/... , as strings).
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


def collect_page_layout(path: str | Path) -> PageLayout:
    """Extract the golden page's *layout* (replay input) — task 006b.

    Reads the same ``SCH_PAGE`` records the connectivity pass reads, but keeps
    the geometry the model throws away: part origins and rotations, flag
    positions and orientations, wire polylines, and the anchors of the
    *visible* net labels. Coordinates stay in **file** space; the replay
    generator owns the file->canvas conversion.
    """
    text, meta = load_epru_text(Path(path))
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = _iter_schematic_records(text, stats)
    instances, loose, segments = _split_page(records)
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
    page_records = [
        record
        for record in records
        if record.type != "DOCHEAD" or record.body.get("docType") == "SCH_PAGE"
    ]
    net_by_group = {
        str(body.get("parentId")): str(body.get("value") or "").strip()
        for body in loose
        if body.get("key") == "NET" and body.get("parentId")
    }
    wire_groups: set[str] = set()
    for index, record in enumerate(page_records):
        if record.type != "WIRE":
            continue
        for follower in page_records[index + 1:]:
            body = follower.body or {}
            if follower.type == "LINE":
                group = str(body.get("lineGroup") or "")
                if group:
                    wire_groups.add(group)
                break
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
        if key in ("Width", "Height", "Border", "Size", "Page Size", "Blade Width",
                   "Title Block", "Title Block Position", "Region Start",
                   "X Region Count", "Y Region Count"):
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
