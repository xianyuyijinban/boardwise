"""Board-level geometry model for EasyEDA Pro (``.epro2`` / ``.epru``) inputs.

This module is the geometry counterpart of :mod:`boardwise.core.model`:

* :mod:`boardwise.core.model` — schematic intent (components, pins, nets).
* :mod:`boardwise.core.geometry` — physical copper (pads, tracks, vias, pours,
  board outline), produced by :mod:`boardwise.parsers.epru`.

**Units.** Every coordinate and dimension in this module is in **mils**
(1/1000 inch), because that is the unit EasyEDA Pro stores in ``.epru``
records (confirmed on the LLC fixture: a via with ``viaDiameter`` 39.37 is a
1.0 mm via, and the board outline is 6102.36 x 3149.61 = 155 x 80 mm).
Use :func:`mil_to_mm` to convert for reporting. Nothing here converts
implicitly, so a value read off a dataclass is always what the file said.

**Net indexing.** The central question for downstream review rules is
"which copper belongs to net X", so :class:`BoardGeometry` indexes every
element by net at construction time and exposes it as a first-class API
(:meth:`BoardGeometry.net`, :meth:`BoardGeometry.pads_for_net`, ...).
Elements with no net (mechanical outlines, silkscreen) are kept in the flat
lists but do not appear in the net index.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

from .model import is_ground_net

__all__ = [
    "MIL_TO_MM",
    "MM_TO_MIL",
    "mil_to_mm",
    "Point",
    "BBox",
    "LayerInfo",
    "ComponentPlacement",
    "PadGeometry",
    "TrackSegment",
    "ViaGeometry",
    "PourShape",
    "BoardOutline",
    "NetGeometry",
    "ParseStats",
    "BoardGeometry",
    "COORD_PRECISION",
    "transform_point",
]

#: 1 mil = 0.0254 mm.
MIL_TO_MM: float = 0.0254
#: 1 mm = 39.3700787... mil.
MM_TO_MIL: float = 1.0 / MIL_TO_MM


def mil_to_mm(value: float) -> float:
    """Convert a mil value to millimetres."""
    return value * MIL_TO_MM


#: Decimal places kept when rounding a coordinate. Coordinates are stored
#: exactly as measured, so this only trims float noise from a rotation.
COORD_PRECISION = 6


def transform_point(
    x: float, y: float, *, rotation: float, mirror: bool, ox: float, oy: float
) -> tuple[float, float]:
    """Symbol-local offset -> page coordinates, in **canvas** space.

    Mirroring flips across the vertical axis (``x -> -x``), then **rotation is
    counter-clockwise** in the y-up canvas frame. Both inputs are already canvas
    space (task 010c: a parser negates the stored y once at its boundary, so
    there is no second sign to apply here).

    **The rotation sign has now been argued four times; it is CCW. The
    distinction that keeps getting lost is between the *file's* angle and the
    *editor API's* angle — they are opposite.** Read this before touching it:

    * *2026-09-13 (pre-010c, an already-mirrored frame)* — calibrated "clockwise"
      against the editor's own netlist. Correct for that frame: the pipeline
      negated y afterwards, and a mirror flips a rotation's handedness.
    * *2026-09-18 (010c ruling 3)* — recognised that the old frame's "CW" **is**
      CCW on the real canvas, and made this function CCW. Correct.
    * *2026-09-19 (010c M4)* — the editor API was measured directly and turns
      **clockwise**: placing an AMS1117-3.3 at ``rotation=R`` and reading the pins
      back with ``sch.component_pins`` gives CW(R) for R = 90 and 270, with the
      pins' own rotation field corroborating (180/90/270 at R = 0/90/270).
      Appendix B read that as "this function must be CW". **That inference is
      wrong**, and it is wrong exactly where this note warns: ``R`` is the
      *editor API's* angle, not the file's.
    * *2026-09-19 (appendix B, reverted)* — the file's angle and the API's angle
      are **opposite by construction**; `engines/draw.py::_editor_rotation` is
      where that is undone (``R = -angle``). Told ``-angle``, the editor turns
      CW(-angle) = CCW(angle) — which is what this function computes. The pair is
      self-consistent either way; only the *pair* has to move together, and
      moving it breaks the golden.

    Why CCW is the file world's truth, independently of the API: this function is
    what `parsers/schematic.py` uses to land pin tips on the page, and the parser
    resolves pin-to-net by matching those tips against wire endpoints. Force it to
    CW and the golden board's own connectivity falls apart — measured, 27 tests,
    including `tests/test_calibration.py`, which compares a **netlist the real
    editor exported on 2026-09-13** against an independent parse of `.epro2` and
    is therefore grounded in the editor rather than in our own code. Under CW it
    reports every two-pin passive swapping pin 1 and pin 2
    (``+5V: golden='C4.2' candidate='C4.1'``); under CCW it is clean.

    Note also that ``CCW(t) ∘ M == M ∘ CW(t)``. Every ``mirror=True`` case is
    blind to this question, and the appendix B table's "mirror ✓ / CCW ✗" row
    compared ``M ∘ CCW`` against ``CCW ∘ M`` — the one comparison that identity
    forbids. Only ``mirror=False`` distinguishes the two, and only the golden
    can adjudicate it.

    Lives in ``core`` (moved here from ``parsers.schematic`` in 006c) because
    both the parsers and the engines need it and ``core`` can depend on
    neither: the previous home forced ``core/candidate.py`` to import a
    **private** name from ``parsers``, inverting the layering. Pure math, no
    parser state.
    """
    if mirror:
        x = -x
    rad = math.radians(rotation)
    cos_v, sin_v = math.cos(rad), math.sin(rad)
    # A plain tuple, **not** `Point`: this result is used as a dict key against
    # tuples elsewhere, and the dataclass would compare unequal to them. The
    # annotation says tuple so the next reader does not "tidy" it into Point.
    return (
        round(x * cos_v - y * sin_v + ox, COORD_PRECISION),
        round(x * sin_v + y * cos_v + oy, COORD_PRECISION),
    )


#: Layer types that carry copper (used by :attr:`LayerInfo.is_copper`).
COPPER_LAYER_TYPES: frozenset[str] = frozenset({"TOP", "BOTTOM", "SIGNAL"})


@dataclass(frozen=True)
class Point:
    """A 2D point in mils, in board coordinates."""

    x: float
    y: float

    @property
    def as_mm(self) -> tuple[float, float]:
        """Return ``(x_mm, y_mm)``."""
        return (self.x * MIL_TO_MM, self.y * MIL_TO_MM)

    def __iter__(self) -> Iterator[float]:
        yield self.x
        yield self.y


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in mils."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def as_mm(self) -> tuple[float, float, float, float]:
        """Return ``(min_x, min_y, max_x, max_y)`` in millimetres."""
        return tuple(v * MIL_TO_MM for v in (self.min_x, self.min_y, self.max_x, self.max_y))  # type: ignore[return-value]

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> "BBox | None":
        """Build a bbox from points, or ``None`` when the iterable is empty."""
        xs: list[float] = []
        ys: list[float] = []
        for p in points:
            xs.append(p.x)
            ys.append(p.y)
        if not xs:
            return None
        return cls(min(xs), min(ys), max(xs), max(ys))


@dataclass
class LayerInfo:
    """One layer definition from the PCB document (``LAYER`` records)."""

    layer_id: int
    name: str
    layer_type: str

    @property
    def is_copper(self) -> bool:
        """True for signal-carrying copper layers (Top / Bottom / Inner*n*)."""
        return self.layer_type in COPPER_LAYER_TYPES

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.name} (id={self.layer_id}, {self.layer_type})"


@dataclass
class ComponentPlacement:
    """A component instance placed on the board (``COMPONENT`` record)."""

    id: str
    designator: str | None = None
    x: float = 0.0
    y: float = 0.0
    #: Rotation in degrees. See :meth:`transform` for the convention used.
    angle: float = 0.0
    layer_id: int | None = None
    footprint: str | None = None
    value: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def position(self) -> Point:
        return Point(self.x, self.y)

    def transform(self, local_x: float, local_y: float) -> Point:
        """Map a footprint-local coordinate to board coordinates.

        Rotation convention: **y increases upwards** (right-handed, like a
        normal maths plot), so a positive ``angle`` rotates anti-clockwise.
        Inferred, not confirmed against editor rendering: every copper
        coordinate on the LLC fixture is negative in y and falls inside the
        board outline only under this reading (see ``docs/epru-format.md``).
        """
        a = math.radians(self.angle)
        cos_a = math.cos(a)
        sin_a = math.sin(a)
        return Point(
            self.x + local_x * cos_a - local_y * sin_a,
            self.y + local_x * sin_a + local_y * cos_a,
        )


@dataclass
class PadGeometry:
    """One pad of a placed component, in board coordinates.

    Pad shapes live in footprint (library) documents in footprint-local
    coordinates; the parser instantiates them per component and transforms
    them here. ``local_x`` / ``local_y`` keep the footprint-local values so a
    consumer can re-derive them.
    """

    id: str
    component: str | None = None
    component_id: str | None = None
    pin_number: str | None = None
    net: str | None = None
    layer_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    local_x: float = 0.0
    local_y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    shape: str = ""
    angle: float = 0.0
    hole_diameter: float | None = None
    plated: bool = False

    @property
    def center(self) -> Point:
        return Point(self.x, self.y)

    @property
    def is_smd(self) -> bool:
        """True when the pad has no hole (surface mount)."""
        return self.hole_diameter is None


@dataclass
class TrackSegment:
    """One straight copper track (``LINE`` record with a net)."""

    id: str
    net: str | None = None
    layer_id: int | None = None
    start: Point = Point(0.0, 0.0)
    end: Point = Point(0.0, 0.0)
    width: float = 0.0

    @property
    def length(self) -> float:
        """Segment length in mils."""
        return math.hypot(self.end.x - self.start.x, self.end.y - self.start.y)


@dataclass
class ViaGeometry:
    """One via (``VIA`` record)."""

    id: str
    net: str | None = None
    x: float = 0.0
    y: float = 0.0
    hole_diameter: float = 0.0
    via_diameter: float = 0.0
    via_type: str = ""
    unused_inner_layers: list[int] = field(default_factory=list)

    @property
    def center(self) -> Point:
        return Point(self.x, self.y)

    @property
    def annular_ring(self) -> float:
        """(via_diameter - hole_diameter) / 2, in mils."""
        return (self.via_diameter - self.hole_diameter) / 2.0


@dataclass
class PourShape:
    """A copper pour / filled region / polygon.

    ``kind`` distinguishes the three record types that carry area copper:

    * ``"fill"`` — ``FILL`` record, usually a real pour with a net.
    * ``"poly"`` — ``POLY`` record with ``polyType`` ``NORMAL``; often a
      copper region drawn by hand (net may be empty).
    * ``"poured"`` — ``POURED`` record, the *result* of pouring a region.
    """

    id: str
    net: str | None = None
    layer_id: int | None = None
    kind: str = ""
    points: list[Point] = field(default_factory=list)
    width: float = 0.0
    fill_style: str | None = None
    poly_type: str | None = None

    @property
    def bbox(self) -> BBox | None:
        return BBox.from_points(self.points)

    @property
    def area(self) -> float:
        """Shoelace area in square mils (0.0 for fewer than 3 points)."""
        if len(self.points) < 3:
            return 0.0
        total = 0.0
        for i, p in enumerate(self.points):
            q = self.points[(i + 1) % len(self.points)]
            total += p.x * q.y - q.x * p.y
        return abs(total) / 2.0


@dataclass
class BoardOutline:
    """The board outline (``POLY`` record with ``polyType`` ``BOARD_OUTLINE``)."""

    points: list[Point] = field(default_factory=list)
    source_id: str | None = None

    @property
    def bbox(self) -> BBox | None:
        return BBox.from_points(self.points)


@dataclass
class NetGeometry:
    """All copper belonging to one net — the unit review rules query."""

    name: str
    pads: list[PadGeometry] = field(default_factory=list)
    tracks: list[TrackSegment] = field(default_factory=list)
    vias: list[ViaGeometry] = field(default_factory=list)
    pours: list[PourShape] = field(default_factory=list)

    @property
    def is_ground(self) -> bool:
        """True for common ground net names (shared with the netlist model)."""
        return is_ground_net(self.name)

    @property
    def pad_count(self) -> int:
        return len(self.pads)

    @property
    def via_count(self) -> int:
        return len(self.vias)

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    @property
    def pour_count(self) -> int:
        return len(self.pours)

    @property
    def element_count(self) -> int:
        return len(self.pads) + len(self.tracks) + len(self.vias) + len(self.pours)

    @property
    def track_length(self) -> float:
        """Total track length in mils."""
        return sum(t.length for t in self.tracks)

    @property
    def pour_area(self) -> float:
        """Total pour area in square mils."""
        return sum(p.area for p in self.pours)

    @property
    def components(self) -> list[str]:
        """Sorted designators of components that have a pad on this net."""
        return sorted({p.component for p in self.pads if p.component})

    def bbox(self) -> BBox | None:
        """Bounding box of every element on this net, or ``None`` if empty."""
        pts: list[Point] = [p.center for p in self.pads]
        pts += [v.center for v in self.vias]
        for t in self.tracks:
            pts += [t.start, t.end]
        for pour in self.pours:
            pts += pour.points
        return BBox.from_points(pts)


@dataclass
class ParseStats:
    """What the parser saw — the audit trail for a parse run.

    ``records_by_type`` counts every record in the file (all documents).
    ``unknown_types`` counts record types this parser has never seen before
    (a signal that the format drifted); ``unconsumed_types`` counts known
    types inside the PCB document that carry no board geometry (RULE,
    PREFERENCE, ...). Neither is ever fatal — they are only counted.

    The two *drop* counters (task 020 §WI-1) count what a parse silently left
    behind, which used to leave no trace at all: a pin record whose ``Pin
    Number`` never arrived, and a placed component whose symbol document did
    not resolve (so it contributes no pins). ``schematic.py``'s
    ``_collect_symbols`` and the symbol lookups in ``build_schematic_model`` /
    ``build_pin_offsets`` are the only writers.
    """

    source: str = ""
    total_records: int = 0
    records_by_type: dict[str, int] = field(default_factory=dict)
    unknown_types: dict[str, int] = field(default_factory=dict)
    unconsumed_types: dict[str, int] = field(default_factory=dict)
    document_types: dict[str, int] = field(default_factory=dict)
    pcb_records: int = 0
    pads_without_net: int = 0
    empty_body_records: int = 0
    malformed_records: int = 0
    #: PIN records that closed without a ``Pin Number`` attribute. The pin is
    #: not in the symbol's pin map, so every connection it makes is invisible
    #: to the schematic model (measured: 14 on `llc_board.epro2`'s two symbol
    #: documents, 7 named pins each).
    pins_dropped_no_number: int = 0
    #: Components (and net-naming power flags) whose symbol document did not
    #: resolve, so they were modelled with no pins at all.
    components_without_symbol: int = 0
    edit_version: str | None = None
    editor_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view (keys sorted for stable output)."""
        return {
            "source": self.source,
            "total_records": self.total_records,
            "records_by_type": dict(sorted(self.records_by_type.items())),
            "unknown_types": dict(sorted(self.unknown_types.items())),
            "unconsumed_types": dict(sorted(self.unconsumed_types.items())),
            "document_types": dict(sorted(self.document_types.items())),
            "pcb_records": self.pcb_records,
            "pads_without_net": self.pads_without_net,
            "empty_body_records": self.empty_body_records,
            "malformed_records": self.malformed_records,
            "pins_dropped_no_number": self.pins_dropped_no_number,
            "components_without_symbol": self.components_without_symbol,
            "edit_version": self.edit_version,
            "editor_version": self.editor_version,
        }


@dataclass
class BoardGeometry:
    """Parsed board geometry, indexed by net.

    Flat element lists (``pads`` / ``tracks`` / ``vias`` / ``pours``) hold
    everything in file order; ``nets`` holds the same objects grouped by net
    name. :meth:`net` never raises — an unknown net name returns an empty
    :class:`NetGeometry`, which is what review rules want when they ask
    "does this net have any copper at all?".
    """

    source: str = ""
    name: str | None = None
    edit_version: str | None = None
    layers: dict[int, LayerInfo] = field(default_factory=dict)
    components: list[ComponentPlacement] = field(default_factory=list)
    pads: list[PadGeometry] = field(default_factory=list)
    tracks: list[TrackSegment] = field(default_factory=list)
    vias: list[ViaGeometry] = field(default_factory=list)
    pours: list[PourShape] = field(default_factory=list)
    outline: BoardOutline | None = None
    nets: dict[str, NetGeometry] = field(default_factory=dict)
    stats: ParseStats = field(default_factory=ParseStats)

    def __post_init__(self) -> None:
        # Nets are derived from the flat lists, so a caller can build a
        # BoardGeometry by hand and still get a working net index.
        if not self.nets:
            self.nets = index_by_net(self.pads, self.tracks, self.vias, self.pours)

    # -- net queries -----------------------------------------------------

    def net(self, name: str) -> NetGeometry:
        """Return the :class:`NetGeometry` for ``name`` (empty if unknown)."""
        return self.nets.get(name, NetGeometry(name=name))

    def has_net(self, name: str) -> bool:
        return name in self.nets

    def net_names(self) -> list[str]:
        """All net names that carry at least one geometric element."""
        return sorted(self.nets)

    def pads_for_net(self, name: str) -> list[PadGeometry]:
        return self.net(name).pads

    def tracks_for_net(self, name: str) -> list[TrackSegment]:
        return self.net(name).tracks

    def vias_for_net(self, name: str) -> list[ViaGeometry]:
        return self.net(name).vias

    def pours_for_net(self, name: str) -> list[PourShape]:
        return self.net(name).pours

    def track_length_for_net(self, name: str) -> float:
        """Total track length on ``name``, in mils (0.0 if unknown net)."""
        return self.net(name).track_length

    def nets_sorted_by_copper(self) -> list[NetGeometry]:
        """Nets ordered by element count, descending — useful for reporting."""
        return sorted(self.nets.values(), key=lambda n: n.element_count, reverse=True)

    # -- structural queries ---------------------------------------------

    def layer(self, layer_id: int) -> LayerInfo | None:
        return self.layers.get(layer_id)

    def layer_name(self, layer_id: int | None) -> str:
        """Human-readable layer name, falling back to ``"layer <id>"``."""
        if layer_id is None:
            return "unknown"
        info = self.layers.get(layer_id)
        return info.name if info else f"layer {layer_id}"

    def copper_layers(self) -> list[LayerInfo]:
        """Copper layers defined in this document, ordered by layer id."""
        return [self.layers[k] for k in sorted(self.layers) if self.layers[k].is_copper]

    def component(self, designator: str) -> ComponentPlacement | None:
        for comp in self.components:
            if comp.designator == designator:
                return comp
        return None

    def pads_for_component(self, designator: str) -> list[PadGeometry]:
        return [p for p in self.pads if p.component == designator]

    def bbox(self) -> BBox | None:
        """Bounding box of all geometry (outline included), or ``None``."""
        pts: list[Point] = []
        if self.outline:
            pts += self.outline.points
        pts += [p.center for p in self.pads]
        pts += [v.center for v in self.vias]
        for t in self.tracks:
            pts += [t.start, t.end]
        for pour in self.pours:
            pts += pour.points
        return BBox.from_points(pts)

    def summary(self) -> dict[str, Any]:
        """Small JSON-serialisable summary for CLI / report output."""
        bbox = self.bbox()
        return {
            "source": self.source,
            "name": self.name,
            "edit_version": self.edit_version,
            "components": len(self.components),
            "pads": len(self.pads),
            "tracks": len(self.tracks),
            "vias": len(self.vias),
            "pours": len(self.pours),
            "nets": len(self.nets),
            "bbox_mil": None if bbox is None else [bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y],
            "bbox_mm": None if bbox is None else list(bbox.as_mm),
        }


def index_by_net(
    pads: Sequence[PadGeometry] = (),
    tracks: Sequence[TrackSegment] = (),
    vias: Sequence[ViaGeometry] = (),
    pours: Sequence[PourShape] = (),
) -> dict[str, NetGeometry]:
    """Group copper elements by net name, skipping elements without a net."""
    nets: dict[str, NetGeometry] = {}
    for pad in pads:
        if pad.net:
            nets.setdefault(pad.net, NetGeometry(name=pad.net)).pads.append(pad)
    for track in tracks:
        if track.net:
            nets.setdefault(track.net, NetGeometry(name=track.net)).tracks.append(track)
    for via in vias:
        if via.net:
            nets.setdefault(via.net, NetGeometry(name=via.net)).vias.append(via)
    for pour in pours:
        if pour.net:
            nets.setdefault(pour.net, NetGeometry(name=pour.net)).pours.append(pour)
    return nets
