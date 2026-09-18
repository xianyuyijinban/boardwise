"""PCB board geometry from EasyEDA Pro project backups (``.epro2``).

This module builds the **copper** view of a board: outline, layers,
placements, pads, tracks, vias, pours. The record stream it reads — ZIP
containers, ``||``-separated line records, ``DOCHEAD`` document splitting — was
moved out to :mod:`boardwise.parsers.epru_stream` (006c, work item 4), because
the schematic parser needed the framing and had to import a private name from
*this* module to get it. Framing is now a shared, public, geometry-free layer;
what stays here is everything that knows what a pad or a track is.

Pad *shapes* live in the FOOTPRINT documents and are instantiated per
placement; DEVICE documents carry library metadata (Value / LCSC /
Manufacturer) joined to a placement through its ``Device`` attribute. The
connectivity view over the same stream lives in
:mod:`boardwise.parsers.epro2_model`, and one :func:`load_epro2_source` call
feeds both.

The framing names are re-exported below so existing importers keep working;
**new code should import them from :mod:`boardwise.parsers.epru_stream`**.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

# Framing lives in its own module now; re-exported for existing importers
# (cli, epro2_model, tests). New code imports from `epru_stream` directly.
from .epru_stream import (
    DEVICE_DOC_TYPE,
    KEPT_DOC_TYPES,
    KNOWN_RECORD_TYPES,
    FIELD_SEP,
    Document,
    EncryptedProjectError,
    EpruRecord,
    FOOTPRINT_DOC_TYPE,
    PCB_DOC_TYPE,
    ParseStats,
    iter_epru_records,
    load_epru_text,
    read_project_meta,
    split_documents,
)

from ..core.geometry import (
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    ParseStats,
    Point,
    PourShape,
    TrackSegment,
    ViaGeometry,
)

__all__ = [
    # PCB geometry — what this module is for.
    "Epro2Source",
    "PadTemplate",
    "PcbContext",
    "build_board_geometry",
    "collect_pcb_context",
    "extract_board",
    "load_epro2_source",
    "pad_net_key",
    "pad_templates",
    "parse_epro2",
    "parse_epru_text",
    # Framing, re-exported from `epru_stream` for existing importers.
    "DEVICE_DOC_TYPE",
    "Document",
    "EncryptedProjectError",
    "EpruRecord",
    "FOOTPRINT_DOC_TYPE",
    "KNOWN_RECORD_TYPES",
    "KEPT_DOC_TYPES",
    "PCB_DOC_TYPE",
    "ParseStats",
    "FIELD_SEP",
    "iter_epru_records",
    "load_epru_text",
    "read_project_meta",
    "split_documents",
]




#: Record types the board-geometry extractor actually consumes inside the
#: PCB document. Known-but-unconsumed types are counted separately so it is
#: obvious what else the format still carries.
CONSUMED_RECORD_TYPES: frozenset[str] = frozenset(
    {
        "ATTR", "COMPONENT", "DOCHEAD", "FILL", "LAYER", "LINE", "PAD_NET",
        "POLY", "POURED", "VIA",
    }
)







@dataclass
class Epro2Source:
    """The decoded documents of one ``.epro2`` backup.

    Produced once by :func:`load_epro2_source` and consumed by both
    :func:`build_board_geometry` (copper) and
    :func:`boardwise.parsers.epro2_model.build_design_model` (connectivity),
    so a single parse feeds both views of the same board.
    """

    source: str = ""
    stats: ParseStats = field(default_factory=ParseStats)
    documents: list[Document] = field(default_factory=list)
    project_meta: dict[str, Any] = field(default_factory=dict)
    # Derived views, built at most once. Hidden from repr/eq: they are a
    # cache, not part of the parsed payload.
    _footprints: dict[str, list[PadTemplate]] | None = field(
        default=None, repr=False, compare=False
    )
    _context: "PcbContext | None" = field(default=None, repr=False, compare=False)

    def documents_of_type(self, doc_type: str) -> list[Document]:
        return [d for d in self.documents if d.doc_type == doc_type]

    def first_document(self, doc_type: str) -> Document | None:
        for doc in self.documents:
            if doc.doc_type == doc_type:
                return doc
        return None

    def footprints(self) -> dict[str, list[PadTemplate]]:
        """Footprint uuid -> its pad shapes, built once and cached."""
        if self._footprints is None:
            self._footprints = {}
            for document in self.documents_of_type(FOOTPRINT_DOC_TYPE):
                if document.uuid:
                    self._footprints[document.uuid] = pad_templates(document)
        return self._footprints

    def pcb_context(self) -> "PcbContext | None":
        """Walk the PCB document once, returning everything derived from it.

        Returns ``None`` when the backup has no PCB document. The result is
        cached, so geometry and netlist views of the same board come from a
        single pass and never double-count anything on ``stats``.
        """
        if self._context is None:
            document = self.first_document(PCB_DOC_TYPE)
            if document is None:
                return None
            self.stats.pcb_records = len(document.records)
            self.stats.edit_version = document.edit_version
            self._context = collect_pcb_context(document, self.footprints(), self.stats)
        return self._context


@dataclass
class PadTemplate:
    """A pad shape as stored in a FOOTPRINT document (footprint-local)."""

    id: str
    num: str
    layer_id: int | None
    local_x: float
    local_y: float
    width: float
    height: float
    shape: str
    angle: float
    hole_diameter: float | None
    plated: bool


# --------------------------------------------------------------------------
# line-level decoding
# --------------------------------------------------------------------------






# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------


def _as_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float conversion; non-numeric payloads fall back."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return default


def _net_name(value: Any) -> str | None:
    """Normalise a net name: empty / missing becomes ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_points(path: Any) -> list[Point]:
    """Flatten an ``.epru`` ``path`` into a list of points.

    Handles the three shapes seen on the fixture:

    * ``[[x0, y0, "L", x1, y1, ...]]`` — FILL wraps the point list once.
    * ``[x0, y0, "L", x1, y1, ...]``   — POLY / POURED, flat.
    * ``["R", x, y, w, h, rotation, radius]`` — rectangle, expanded to 4 corners.

    ``"L"`` is a line-to command and is dropped. ``"ARC"`` carries
    ``[sweep, x, y]`` (inferred — the first value is an angle, not a
    coordinate), so the sweep is dropped and the point kept.
    """
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)):
        return []
    items: Sequence[Any] = path
    if items and isinstance(items[0], (list, tuple)):
        items = items[0]

    values: list[Any] = list(items)
    if not values:
        return []

    if values[0] == "R":
        nums = [_as_float(v) for v in values[1:]]
        if len(nums) < 4:
            return []
        x, y, w, h = nums[0], nums[1], nums[2], nums[3]
        # Height runs along -y: on the fixture the outline rectangle is
        # ["R", -1.811, -3.189, 6102.3622, 3149.6063, 0, 150] and all copper
        # sits at negative y, i.e. the board spans y = -3.19 .. -3152.80.
        return [
            Point(x, y),
            Point(x + w, y),
            Point(x + w, y - h),
            Point(x, y - h),
        ]

    points: list[Point] = []
    index = 0
    pending: list[float] = []
    while index < len(values):
        item = values[index]
        if isinstance(item, str):
            command = item.upper()
            if command == "ARC":
                # "ARC", <sweep>, x, y  -> keep (x, y), drop the sweep.
                index += 2
                continue
            index += 1  # "L" and anything else: keep reading numbers
            continue
        pending.append(_as_float(item))
        if len(pending) == 2:
            points.append(Point(pending[0], pending[1]))
            pending = []
        index += 1
    return points


def _pad_diameter(pad: dict[str, Any]) -> tuple[float, float, str]:
    """Return ``(width, height, shape)`` from a pad's ``defaultPad`` block."""
    block = pad.get("defaultPad") or {}
    shape = str(block.get("padType") or "")
    return _as_float(block.get("width")), _as_float(block.get("height")), shape


def _hole_diameter(pad: dict[str, Any]) -> float | None:
    """Return the pad hole diameter, or ``None`` for an SMD pad."""
    hole = pad.get("hole")
    if not isinstance(hole, dict):
        return None
    return _as_float(hole.get("width"), 0.0) or None


# --------------------------------------------------------------------------
# document-level extraction
# --------------------------------------------------------------------------


def pad_templates(document: Document) -> list[PadTemplate]:
    """Extract pad shapes from a FOOTPRINT document."""
    templates: list[PadTemplate] = []
    for record in document.records:
        if record.type != "PAD" or record.body is None:
            continue
        body = record.body
        width, height, shape = _pad_diameter(body)
        templates.append(
            PadTemplate(
                id=record.id or "",
                num=str(body.get("num") or ""),
                layer_id=body.get("layerId"),
                local_x=_as_float(body.get("centerX")),
                local_y=_as_float(body.get("centerY")),
                width=width,
                height=height,
                shape=shape,
                angle=_as_float(body.get("padAngle")),
                hole_diameter=_hole_diameter(body),
                plated=bool(body.get("plated", False)),
            )
        )
    return templates


def pad_net_key(record: EpruRecord) -> tuple[str, str, str | None] | None:
    """Return ``(component_id, pin_number, pad_id)`` for a ``PAD_NET`` record.

    The published V3 schema puts those three in the body; 3.2.x documents
    carry the same triple inside the id array. Both are accepted, so this is
    the single place that knows how a pad is tied to a net.
    """
    body = record.body or {}
    comp_id = body.get("componentId")
    pin = body.get("padNum")
    pad_id = body.get("padId")
    if comp_id is None or pin is None:
        parts = parse_id_tuple(record)
        if len(parts) < 4:
            return None
        comp_id, pin, pad_id = parts[1], parts[2], parts[3]
    return str(comp_id), str(pin), None if pad_id is None else str(pad_id)


def parse_id_tuple(record: EpruRecord) -> list[str]:
    """Decode a JSON-array record id such as ``["PAD_NET", comp, pin, pad]``."""
    raw = record.id
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except ValueError:
        return []
    return [str(v) for v in decoded] if isinstance(decoded, list) else [str(decoded)]


def build_pads(
    placements: list[ComponentPlacement],
    footprints: dict[str, list[PadTemplate]],
    pad_nets_by_pad: dict[tuple[str, str], str | None],
    pad_nets_by_pin: dict[tuple[str, str], str | None],
    stats: ParseStats,
) -> list[PadGeometry]:
    """Instantiate footprint pads at their placed, rotated positions."""
    pads: list[PadGeometry] = []
    for comp in placements:
        templates = footprints.get(comp.footprint or "", [])
        for template in templates:
            net = pad_nets_by_pad.get((comp.id, template.id))
            if net is None:
                net = pad_nets_by_pin.get((comp.id, template.num))
            if net is None:
                stats.pads_without_net += 1
            point = comp.transform(template.local_x, template.local_y)
            pads.append(
                PadGeometry(
                    id=template.id,
                    component=comp.designator,
                    component_id=comp.id,
                    pin_number=template.num or None,
                    net=net,
                    layer_id=template.layer_id,
                    x=point.x,
                    y=point.y,
                    local_x=template.local_x,
                    local_y=template.local_y,
                    width=template.width,
                    height=template.height,
                    shape=template.shape,
                    angle=template.angle,
                    hole_diameter=template.hole_diameter,
                    plated=template.plated,
                )
            )
    return pads


@dataclass
class PcbContext:
    """Everything one walk of the PCB document yields.

    Geometry (:func:`extract_board`) and connectivity
    (``boardwise.parsers.epro2_model.build_design_model``) are two views of
    the same data, so both read from a single :class:`PcbContext` instead of
    walking the document twice.
    """

    layers: dict[int, LayerInfo] = field(default_factory=dict)
    placements: list[ComponentPlacement] = field(default_factory=list)
    by_id: dict[str, ComponentPlacement] = field(default_factory=dict)
    pads: list[PadGeometry] = field(default_factory=list)
    tracks: list[TrackSegment] = field(default_factory=list)
    vias: list[ViaGeometry] = field(default_factory=list)
    pours: list[PourShape] = field(default_factory=list)
    outline: BoardOutline | None = None
    #: (component id, pad id) -> net name, as written by ``PAD_NET``.
    pad_nets_by_pad: dict[tuple[str, str], str | None] = field(default_factory=dict)
    #: (component id, pin number) -> net name. First writer wins.
    pad_nets_by_pin: dict[tuple[str, str], str | None] = field(default_factory=dict)
    #: Component id -> DEVICE document uuid, from the ``Device`` attribute.
    #: The join key into the library metadata (Value / LCSC / Manufacturer);
    #: resolved 47/47 on the LLC fixture.
    device_ids: dict[str, str] = field(default_factory=dict)


def collect_pcb_context(
    document: Document,
    footprints: dict[str, list[PadTemplate]],
    stats: ParseStats,
) -> PcbContext:
    """Walk one PCB document once, returning everything derived from it.

    Unknown record types are counted on ``stats.unconsumed_types`` and
    skipped; nothing here raises on unexpected payloads.
    """
    context = PcbContext()
    # Element id -> net, so POURED regions can borrow the net of the region
    # they were poured from.
    net_by_element: dict[str, str | None] = {}

    for record in document.records:
        body = record.body
        if body is None:
            continue  # empty body: nothing to read

        rtype = record.type
        if rtype == "LAYER":
            try:
                layer_id = int(parse_id_tuple(record)[1])
            except (IndexError, ValueError):
                continue
            context.layers[layer_id] = LayerInfo(
                layer_id=layer_id,
                name=str(body.get("layerName") or ""),
                layer_type=str(body.get("layerType") or ""),
            )
        elif rtype == "COMPONENT":
            # Older documents use "angle"; the published V3 schema names the
            # same field "rotation" (plus a separate "isMirror" flag).
            angle = body.get("angle")
            if angle is None:
                angle = body.get("rotation")
            placement = ComponentPlacement(
                id=record.id or "",
                x=_as_float(body.get("x")),
                y=_as_float(body.get("y")),
                angle=_as_float(angle),
                layer_id=body.get("layerId"),
                attrs=dict(body.get("attrs") or {}),
            )
            context.placements.append(placement)
            context.by_id[placement.id] = placement
        elif rtype == "ATTR":
            # Attributes hang off components (Designator / Value / Footprint)
            # but also off pads, pours and the document itself; only the ones
            # with a known component parent are interesting here.
            target = context.by_id.get(str(body.get("parentId")))
            if target is not None:
                key = body.get("key")
                value = body.get("value")
                if key == "Designator":
                    target.designator = None if value is None else str(value)
                elif key == "Value":
                    target.value = None if value is None else str(value)
                elif key == "Footprint":
                    # The value is the FOOTPRINT document uuid, not a name.
                    target.footprint = None if value is None else str(value)
                elif key == "Device":
                    # The value is the DEVICE document uuid: the join key to
                    # library metadata (Value / LCSC / Manufacturer).
                    if value is not None:
                        context.device_ids[target.id] = str(value)
        elif rtype == "PAD_NET":
            key = pad_net_key(record)
            if key is not None:
                comp_id, pin, pad_id = key
                net = _net_name(body.get("padNet"))
                if pad_id is not None:
                    context.pad_nets_by_pad[(comp_id, pad_id)] = net
                context.pad_nets_by_pin.setdefault((comp_id, pin), net)
        elif rtype == "VIA":
            net = _net_name(body.get("netName"))
            context.vias.append(
                ViaGeometry(
                    id=record.id or "",
                    net=net,
                    x=_as_float(body.get("centerX")),
                    y=_as_float(body.get("centerY")),
                    hole_diameter=_as_float(body.get("holeDiameter")),
                    via_diameter=_as_float(body.get("viaDiameter")),
                    via_type=str(body.get("viaType") or ""),
                    unused_inner_layers=list(body.get("unusedInnerLayers") or []),
                )
            )
        elif rtype == "LINE":
            net = _net_name(body.get("netName"))
            if net is not None and record.id:
                net_by_element.setdefault(record.id, net)
            context.tracks.append(
                TrackSegment(
                    id=record.id or "",
                    net=net,
                    layer_id=body.get("layerId"),
                    start=Point(_as_float(body.get("startX")), _as_float(body.get("startY"))),
                    end=Point(_as_float(body.get("endX")), _as_float(body.get("endY"))),
                    width=_as_float(body.get("width")),
                )
            )
        elif rtype in ("FILL", "POLY", "POURED"):
            if rtype == "POURED":
                # POURED stores the *result* of a pour. Its path is NOT in
                # board coordinates (measured: all points sit in a small local
                # range, e.g. y = 22..78 on a board spanning y = 208..790), so
                # feeding it into a bbox would corrupt every geometry query.
                # Keep the record (it is real copper) but leave points empty.
                path = None
                parts = parse_id_tuple(record)
                net = net_by_element.get(parts[1]) if len(parts) >= 2 else None
            else:
                path = body.get("path")
                net = _net_name(body.get("netName"))
                if net is not None and record.id:
                    net_by_element.setdefault(record.id, net)
            points = _path_points(path)
            poly_type = body.get("polyType")
            if (
                rtype != "POURED"
                and poly_type == "BOARD_OUTLINE"
                and context.outline is None
            ):
                context.outline = BoardOutline(points=points, source_id=record.id)
                continue
            context.pours.append(
                PourShape(
                    id=record.id or "",
                    net=net,
                    layer_id=body.get("layerId"),
                    kind={"FILL": "fill", "POLY": "poly", "POURED": "poured"}[rtype],
                    points=points,
                    width=_as_float(body.get("width")),
                    fill_style=body.get("fillStyle"),
                    poly_type=poly_type,
                )
            )
        elif rtype != "DOCHEAD":
            stats.unconsumed_types[rtype] = stats.unconsumed_types.get(rtype, 0) + 1

    context.pads = build_pads(
        context.placements,
        footprints,
        context.pad_nets_by_pad,
        context.pad_nets_by_pin,
        stats,
    )
    return context


def extract_board(
    document: Document,
    footprints: dict[str, list[PadTemplate]],
    stats: ParseStats,
) -> BoardGeometry:
    """Turn one PCB document into a :class:`BoardGeometry`."""
    context = collect_pcb_context(document, footprints, stats)
    return BoardGeometry(
        source=stats.source,
        edit_version=stats.edit_version,
        layers=context.layers,
        components=context.placements,
        pads=context.pads,
        tracks=context.tracks,
        vias=context.vias,
        pours=context.pours,
        outline=context.outline,
        stats=stats,
    )


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------






def load_epro2_source(path: str | Path) -> Epro2Source:
    """Decode an ``.epro2`` backup into its documents, once.

    This is the single-parse entry point: the returned :class:`Epro2Source`
    can be turned into board geometry (:func:`build_board_geometry`) **and**
    into a netlist model
    (:func:`boardwise.parsers.epro2_model.build_design_model`) without
    reading the file twice.
    """
    source_path = Path(path)
    text, meta = load_epru_text(source_path)
    stats = ParseStats(source=str(source_path), editor_version=meta.get("editorVersion"))
    documents = split_documents(text, stats)
    return Epro2Source(source=str(source_path), stats=stats, documents=documents, project_meta=meta)


def build_board_geometry(source: Epro2Source) -> BoardGeometry:
    """Build :class:`BoardGeometry` from an already-decoded :class:`Epro2Source`."""
    context = source.pcb_context()
    name = str(source.project_meta.get("title") or "") or None
    if context is None:
        # No PCB document in this backup: return an empty board rather than
        # raising, so batch runs survive. stats shows what was seen.
        return BoardGeometry(source=source.source, name=name, stats=source.stats)

    return BoardGeometry(
        source=source.source,
        name=name,
        edit_version=source.stats.edit_version,
        layers=context.layers,
        components=context.placements,
        pads=context.pads,
        tracks=context.tracks,
        vias=context.vias,
        pours=context.pours,
        outline=context.outline,
        stats=source.stats,
    )


def parse_epru_text(text: str, *, source: str = "<text>", project_meta: dict[str, Any] | None = None) -> BoardGeometry:
    """Parse decoded ``.epru`` text into a :class:`BoardGeometry`.

    This is the testable core of :func:`parse_epro2`: hand it any ``.epru``
    payload, including hand-written synthetic ones.
    """
    meta = project_meta or {}
    stats = ParseStats(source=source, editor_version=meta.get("editorVersion"))
    documents = split_documents(text, stats)
    src = Epro2Source(source=source, stats=stats, documents=documents, project_meta=meta)
    board = build_board_geometry(src)
    board.name = str(meta.get("title") or "") or board.name
    return board


def parse_epro2(path: str | Path) -> BoardGeometry:
    """Parse an EasyEDA Pro ``.epro2`` project backup into board geometry.

    The ``.epru`` member is matched by extension because zip entry names may
    be mojibake'd. When several ``.epru`` members exist the largest one is
    used (the project document stream; others are library stubs).
    """
    return build_board_geometry(load_epro2_source(path))
