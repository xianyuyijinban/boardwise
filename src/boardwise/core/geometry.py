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
    "COPPER_LAYER_TYPES",
    "MIL_TO_MM",
    "MM_TO_MIL",
    "MULTI_LAYER_ID",
    "MULTI_LAYER_TYPES",
    "mil_to_mm",
    "Point",
    "BBox",
    "LayerInfo",
    "StackupEntry",
    "ComponentPlacement",
    "PadGeometry",
    "SilkShape",
    "SilkText",
    "SILK_LAYER_TYPES",
    "TrackSegment",
    "ViaGeometry",
    "PourShape",
    "ProhibitRegion",
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
#: ``"PLANE"`` joined in task 125a: an inner plane (内电层) is copper too.
#: Evidence: `tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2`, PCB
#: document "PCB1" (the 4-layer driver board), ``["LAYER",15]`` reads
#: ``{"layerId": 15, "layerType": "PLANE", "layerName": "Inner1", "use": true}``
#: and the same document's ``LAYER_PHYS`` stackup seats layer 15 between two
#: dielectrics (zIndex 1002, material 内层铜厚, thickness 0.598 mil = 0.5 oz).
COPPER_LAYER_TYPES: frozenset[str] = frozenset({"TOP", "BOTTOM", "SIGNAL", "PLANE"})

#: Layer id EasyEDA Pro writes for a pad that exists on **every** copper
#: layer — the editor's own "Multi-Layer" designation, and the normal spelling
#: on a through-hole pad (where it is what makes pin 1 square). It is a
#: *declaration*, so it is deliberately not in :data:`COPPER_LAYER_TYPES`: it is
#: not a layer a track can be drawn on, it is the set of them. Measured: 45 of
#: PCB3's 125 pads and 8 of PCB1's 430 carry it, and every one of them also
#: carries a ``hole`` — the two agree 45/45 and 8/8, which is why
#: :func:`boardwise.parsers.epru.pad_effective_layers` accepts **either** as the
#: barrel signal rather than insisting on one.
MULTI_LAYER_ID = 12

#: Layer types that carry copper on **every** copper layer at once — the
#: editor's "Multi-Layer" designation (the type of :data:`MULTI_LAYER_ID`).
#: Deliberately separate from :data:`COPPER_LAYER_TYPES`: a *track* cannot be
#: drawn on it, but a **filled region** can, and such a region is copper on
#: every layer. Measured: 级联多电平-主拓扑 carries 3 ``FILL`` records and
#: 级联多电平-驱动模块 4, all on layer 12, which 162b files with the pours
#: rather than with the non-copper artwork.
MULTI_LAYER_TYPES: frozenset[str] = frozenset({"MULTI"})


#: Layer types that carry **printed legend** (丝印) — the ink a fab prints on
#: the board. `LayerInfo.layer_type` carries these strings verbatim from the
#: document's ``LAYER`` table (measured: ``["LAYER",3]`` reads
#: ``{"layerName": "Top Silkscreen Layer", "layerType": "TOP_SILK"}`` on every
#: board fixture), so a reader never has to hard-code the ids 3/4 — a document
#: that renumbers its layers still classifies correctly.
SILK_LAYER_TYPES: frozenset[str] = frozenset({"TOP_SILK", "BOT_SILK"})

#: Layer types carrying the *other* per-placement artwork a footprint document
#: holds: the body/courtyard outline (``COMPONENT_SHAPE``), the component
#: marking layer (``COMPONENT_MARKING`` — where EasyEDA draws the pin-1 dot),
#: the pad solder areas (``PIN_SOLDERING``) and the pin-floating layer.
#: Measured on 毕设FOC 1.0.0: ``C0603`` keeps its body rectangle on layer 48,
#: its pin-1 dot on 49, its two solder areas on 50 and its silk on 3.
ARTWORK_LAYER_TYPES: frozenset[str] = frozenset(
    {"COMPONENT_SHAPE", "COMPONENT_MARKING", "PIN_SOLDERING", "PIN_FLOATING"}
)


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
class StackupEntry:
    """One physical stackup layer, from a ``LAYER_PHYS`` record.

    The ``LAYER`` table of an EasyEDA Pro document defines every layer the
    *editor* knows — including all 32 possible inner signal layers on a
    2-layer board — so it cannot say which copper actually exists. The
    ``LAYER_PHYS`` table is the fabrication truth: one record per physical
    layer (copper or dielectric), ordered by ``z_index``. Evidence: on the
    毕设FOC fixture's "PCB1" document the copper entries are layers
    1 / 15 / 16 / 2 at zIndex 1000 / 1002 / 1004 / 9000 with dielectrics
    361 / 362 / 363 between them; on the older LLC fixture the same layout
    uses the legacy zIndex scale (copper at 4 and 6, ``FR4`` at 5), so only
    the *ordering* is meaningful, never the magnitude.

    ``thickness`` is in **mils** like every other dimension here (1 oz
    outer copper reads 1.378 mil = 35 µm; the LLC core reads 59.449 mil ≈
    1.51 mm). ``material`` is the free-text string the file carries
    (``"FR4"``, ``"外层铜厚1oz"``, ...), kept verbatim for reporting.
    """

    layer_id: int
    z_index: int
    material: str = ""
    thickness: float = 0.0


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

    **``layer_id`` is what the footprint says; ``effective_layer_ids`` is where
    the copper physically is** (task 127b). They are not the same fact, and
    conflating them is what made a bottom-side part's SMD pads read as top
    copper. Measured on the 毕设FOC fixture: PCB1 places U4 / U6 / R17 / C14 on
    the **bottom** (``COMPONENT.layerId == 2``), yet all 28 of their SMD pads
    carry ``layerId == 1`` — the footprint's own hardcoded layer, which is 1 for
    a top SMD and is not rewritten when the part is flipped to the other face.
    A rule that measured those pads as top copper produced six **top x bottom**
    pairs at 0.0 mil "touching" on a board whose host DRC is clean: the copper
    they were comparing lives on opposite faces of a 1.6 mm board.

    ``effective_layer_ids`` is the reading the rules and the clearance engine
    use:

    * a **through-hole** pad (one with a hole of any shape — :attr:`has_hole`),
      or any pad whose ``layer_id`` is :data:`MULTI_LAYER_ID`, occupies **every
      copper layer** — its barrel is continuous and its lands exist on both
      faces;
    * an **SMD** pad occupies the face its **component** is on
      (``ComponentPlacement.layer_id``), falling back to the footprint's
      ``layer_id`` when the placement carries none.

    It is written by the parser (which knows the placement and the document's
    stackup) and is **empty by default**, so a hand-built pad falls back to the
    previous behaviour rather than silently claiming an empty layer set. The
    empty set is "this pad's physical layers were never established", never
    "this pad has no copper".

    **The hole's shape (162b).** ``.epru`` writes a pad's hole as
    ``hole: {"holeType": ..., "width": ..., "height": ...}``, and two types
    occur on the fixtures: ``ROUND`` (1155 pads, 1146 of them with
    ``width == height`` and 9 with two different extents — a USB shield hole at
    126 x 118.1102 mil) and ``SLOT`` (141 pads, always two different extents:
    ``width`` the **long** axis, up to 86.62 x 47.24 mil). Before 162b only
    ``width`` was read and reported as ``hole_diameter``, so a slot pad was
    described as a circle of the slot's length and its second dimension was
    unreadable.

    Three fields now carry the hole, each with one meaning:

    * :attr:`hole_width` / :attr:`hole_height` — the hole's extents along the
      record's own ``width`` / ``height`` axes. **These are the two dimensions
      of the hole**, for every shape.
    * :attr:`hole_type` — ``holeType`` verbatim (``"ROUND"`` / ``"SLOT"``, and
      ``""`` when the record did not say).
    * :attr:`hole_diameter` — ``width``, which is the hole's diameter, and
      ``None`` **exactly when the record says ``SLOT``**. The field is
      deliberately **narrowed, not deprecated**: every round hole keeps the
      value it always had, and the one place it stops claiming a diameter is
      the one place the file itself says there is no circle. A consumer that
      wants "is there a hole at all" asks :attr:`has_hole`, not this.

    The barrel reading (:attr:`effective_layer_ids`, and the fallback in
    :func:`boardwise.core.measure._element_layers`) keys on :attr:`has_hole`,
    so a **slot** pad is still a plated barrel spanning the copper stackup.
    """

    id: str
    component: str | None = None
    component_id: str | None = None
    pin_number: str | None = None
    net: str | None = None
    layer_id: int | None = None
    effective_layer_ids: list[int] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    local_x: float = 0.0
    local_y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    shape: str = ""
    angle: float = 0.0
    hole_diameter: float | None = None
    #: 162b: the hole's extents along the record's ``width`` / ``height`` axes.
    #: For a ``SLOT`` that is the long and the short axis; for a round hole both
    #: equal :attr:`hole_diameter`. ``None`` when the pad has no hole block at
    #: all.
    hole_width: float | None = None
    hole_height: float | None = None
    #: 162b: the record's own ``holeType``, verbatim (``"ROUND"`` / ``"SLOT"`` /
    #: ``""`` when the file did not say).
    hole_type: str = ""
    #: R2-2: the footprint PAD record's ``plated`` (是否金属化孔壁) — ``True``,
    #: ``False`` (NPTH) or ``None`` when the record did not say. The parser's
    #: reading decides :attr:`effective_layer_ids` (an NPTH pad is no barrel);
    #: the ``False`` default only matters for a hand-built pad, which never
    #: reaches that reading (its effective layers stay empty).
    plated: bool | None = False

    @property
    def center(self) -> Point:
        return Point(self.x, self.y)

    @property
    def has_hole(self) -> bool:
        """True when the pad has a hole of **any** shape (round or slot).

        The through-hole signal, and the one the barrel reading uses. It is not
        :attr:`hole_diameter`: since 162b that field is ``None`` for a slot,
        which is still a plated barrel. A hole is not necessarily a *plated*
        barrel: :attr:`plated` ``False`` is an NPTH, whose copper the parser
        reads as its land only (R2-2).
        """
        return self.hole_width is not None or self.hole_diameter is not None

    @property
    def is_smd(self) -> bool:
        """True when the pad has no hole (surface mount)."""
        return not self.has_hole

    def effective_layers(self) -> set[int]:
        """The copper layers this pad physically occupies.

        :attr:`effective_layer_ids` when the parser established it, otherwise
        **the empty set** — the "never guessed" discipline the rest of
        :mod:`boardwise.core.measure` follows for an unclassifiable element. A
        caller that has not got a stackup (a synthetic board, an old file) gets
        an absent answer and says so, rather than a plausible-looking one.
        """
        return set(self.effective_layer_ids)


@dataclass
class SilkShape:
    """One **graphic primitive** of a placement's non-copper artwork (task 152).

    The PCB document carries no silkscreen of its own beyond free text: a
    footprint's legend, body outline and pin-1 dot live in its **FOOTPRINT**
    document (source of truth per :func:`boardwise.parsers.epru.pad_templates`'s
    sibling) and are instantiated per placement exactly like pads. This is that
    instantiated primitive, in **both** frames:

    * ``points`` — board coordinates (the placement transform already applied),
      so a rule can intersect it with pads and other placed artwork;
    * ``local_points`` — footprint-local, so a rule can ask what the *footprint*
      declares (which side its polarity mark is on) independently of how this
      instance happens to be rotated.

    ``layer_id`` is the **footprint's own** layer id (3 = top silk, 48 = body,
    49 = marking, ...) and ``layer_kind`` is the reading of that id through the
    running document's ``LAYER`` table — the same "declared vs effective"
    distinction :class:`PadGeometry` makes, and for the same reason: the layer
    table is the only thing that says what id 3 *means*, and hard-coding it
    would be a guess about the document rather than a reading of it.

    **``layer_kind`` is the layer the artwork is actually drawn on (162b).** A
    footprint stores its legend on its library layers, so every part says
    ``layerId: 3`` however it is mounted; a part flipped to the bottom face
    prints its silk on the **bottom** silkscreen. Measured on llc: 12 of 47
    placements are on the bottom and carry 64 silk primitives that 152 reported
    as ``TOP_SILK``. Where the document defines the counterpart layer, the
    reading is renamed ``BOT_SILK`` (``effective_layer_id`` 4) and the library's
    own spelling is kept in :attr:`declared_layer_kind`; where it defines none,
    the kind stays and :attr:`face` still states the physical side. This mirrors
    :class:`PadGeometry`, except that there the *consumer* field
    (``effective_layer_ids``) is a new one — here consumers have always read
    ``layer_kind``, so it is ``layer_kind`` that takes the physical truth.

    ``kind`` is the record type it came from (``"poly"`` / ``"fill"`` /
    ``"circle"`` / ``"rect"`` / ``"line"``). ``radius`` is set for a
    ``CIRCLE`` primitive (measured: the pin-1 dot is a 2.36 mil circle) and
    ``None`` otherwise; ``arc_count`` counts the ``ARC`` segments inside
    ``path`` that were chorded (their endpoints are kept, their sweep dropped —
    the same reading ``epru._path_points`` documents for copper polygons).
    """

    id: str = ""
    component: str | None = None
    component_id: str | None = None
    #: Record type of the primitive: ``poly`` / ``fill`` / ``circle`` / ``rect`` / ``line``.
    kind: str = ""
    #: Footprint-local layer id, and the layer the primitive is **drawn on**.
    layer_id: int | None = None
    layer_kind: str = ""
    #: 162b: what the ``LAYER`` table calls :attr:`layer_id` — the library-side
    #: spelling of the same fact, kept so the face correction stays auditable.
    #: Equal to :attr:`layer_kind` for a top placement and for every
    #: side-agnostic layer.
    declared_layer_kind: str = ""
    #: 162b: the layer id :attr:`layer_kind` was read from (4 where a bottom
    #: placement's top-silk artwork was renamed).
    effective_layer_id: int | None = None
    #: 162b: the board face the primitive is physically on — ``1`` top, ``2``
    #: bottom, ``None`` when neither the layer's own spelling nor the placement
    #: states one (a board-level ``DOCUMENT`` / ``MULTI`` annotation). Set for
    #: the per-placement layers the id cannot express a face for
    #: (``COMPONENT_SHAPE`` / ``COMPONENT_MARKING`` / ...), which is the fact
    #: the silk rule reconstructs from the placement on its own.
    face: int | None = None
    points: list[Point] = field(default_factory=list)
    local_points: list[Point] = field(default_factory=list)
    width: float = 0.0
    filled: bool = False
    radius: float | None = None
    arc_count: int = 0
    #: Free text, for a silk ``STRING`` primitive inside a footprint (the
    #: ``"+"`` / ``"-"`` polarity marks). Empty for polygons.
    text: str = ""

    @property
    def bbox(self) -> BBox | None:
        return BBox.from_points(self.points)

    @property
    def local_bbox(self) -> BBox | None:
        return BBox.from_points(self.local_points)

    @property
    def is_silk(self) -> bool:
        """True when this primitive is **printed legend** (layer type TOP/BOT_SILK)."""
        return self.layer_kind in SILK_LAYER_TYPES

    def centroid(self, local: bool = False) -> Point | None:
        """Mean of the vertices (``None`` when there are none).

        **Not** the area centroid of a filled polygon and **not** a substitute
        for one: it is the reading this model uses to place a primitive for
        comparison, and it is stated as such so a reader does not mistake it
        for a physical centre of mass. A single-point primitive (a chorded
        circle kept as its centre) returns that point, which is exactly what
        the pin-1 dot needs.
        """
        points = self.local_points if local else self.points
        if not points:
            return None
        return Point(
            sum(p.x for p in points) / len(points),
            sum(p.y for p in points) / len(points),
        )


@dataclass
class SilkText:
    """One instantiated piece of silkscreen **text** (task 152).

    Three sources, all normalised here so a rule reads one shape:

    * ``source == "designator"`` — the placement's own ``Designator`` attribute
      (an ``ATTR`` record with ``key="Designator"``). **Measured, and this is
      the fact the whole silk rule rests on**: a placed component's designator
      is *not* derived from the FOOTPRINT document at render time — the PCB
      document carries its own ``ATTR`` record with the text's own
      ``x``/``y``/``angle``/``fontSize``/``layerId``/``valueVisible``. On
      毕设FOC 1.0.0 that is 122 designator records for 122 placements, all on
      layer 3, all ``fontSize`` 45, all ``origin`` ``LEFT_BOTTOM``; 91 of them
      ``valueVisible``.
    * ``source == "footprint"`` — a ``STRING`` record **inside a FOOTPRINT
      document** (instantiated per placement like :class:`PadGeometry`). These
      are the footprint's own printed marks — the ``"+"`` / ``"-"`` polarity
      signs and ``"1"``/``"2"``/``"3"`` pin labels; measured on the library
      footprints ``CONN-TH_XT30UPB-M`` / ``CONN-TH_XT60PW-M`` / ``R_3386P``.
    * ``source == "board"`` — a ``STRING`` record directly in the PCB document:
      free text the designer drew on the board (measured: the three labels
      ``CLK`` / ``DIO`` / ``GND`` next to PCB1's programming header, at
      ``fontSize`` 40–50, rotated to the connector's axis).

    ``angle`` is in **degrees, in the same frame and convention as
    :meth:`ComponentPlacement.transform`** (y-up, positive = anticlockwise) —
    the two are directly comparable, which is what lets a rule ask whether a
    designator still points the same way as the part it names. The raw stored
    value is kept in :attr:`stored_angle` because EasyEDA accumulates whole
    turns (measured values include 810, 1710, 2250 — i.e. 90°, 270°, 90°), and
    a reader that printed the raw number without reducing it would report
    nonsense; the reduction is done in the parser, once, and both numbers are
    kept so the reduction is auditable.

    ``mirror``/``reverse`` are the record's own flags, carried verbatim;
    ``visible`` is ``valueVisible`` (a designator record with ``false`` is a
    designator the designer switched **off** — the board carries no designator
    for that part).
    """

    component: str | None = None
    component_id: str | None = None
    text: str = ""
    source: str = ""
    #: Board-frame anchor (for ``designator``/``board`` sources this is the
    #: record's own x/y; for a footprint ``STRING`` it is the transformed point).
    x: float = 0.0
    y: float = 0.0
    #: Footprint-local anchor; identical to ``x``/``y`` for a PCB-document record.
    local_x: float = 0.0
    local_y: float = 0.0
    #: Reduced rotation (mod 360) in degrees, and the raw stored value.
    angle: float = 0.0
    stored_angle: float = 0.0
    layer_id: int | None = None
    layer_kind: str = ""
    #: 162b: the library-side spelling of :attr:`layer_id`, for a footprint's own
    #: printed mark instantiated on a **flipped** part: its ``layer_kind`` is the
    #: layer the mark is really printed on (``BOT_SILK`` on a bottom placement)
    #: while this keeps the layer the library declared (``TOP_SILK``). Equal to
    #: :attr:`layer_kind` for a designator / board text, whose record already
    #: carries its physical layer.
    declared_layer_kind: str = ""
    font_size: float = 0.0
    stroke_width: float = 0.0
    origin: str = ""
    mirror: bool = False
    reverse: bool = False
    visible: bool = True
    font_family: str = ""

    @property
    def is_silk(self) -> bool:
        return self.layer_kind in SILK_LAYER_TYPES

    def corners(self, advance: float) -> list[Point]:
        """The text's **frame**: the origin-anchored box, rotated onto the board.

        The box is ``len(text) * advance * font_size`` wide and
        ``font_size`` tall, anchored at :attr:`origin` (for every designator on
        the measured boards that is ``LEFT_BOTTOM``) and rotated by
        :attr:`angle` — so the box runs from the anchor along the text
        direction, rising by the font size across it.

        **The width is a model, not a reading, which is why it is a parameter
        and not a constant here.** ``.epru`` carries no glyph advance, so the
        parser cannot know it and does not claim to; the caller states the
        ratio it uses. See :data:`boardwise.rules.pcb.silk.ADVANCE_BAND` for
        the band the rule measures with and why an overlap is only reported
        when it survives the narrowest end of that band.
        """
        width = len(self.text) * advance * self.font_size
        height = self.font_size
        origin = str(self.origin or "LEFT_BOTTOM").upper()
        if "RIGHT" in origin:
            x0, x1 = -width, 0.0
        elif "CENTER" in origin:
            x0, x1 = -width / 2.0, width / 2.0
        else:  # LEFT_*
            x0, x1 = 0.0, width
        if "TOP" in origin:
            y0, y1 = -height, 0.0
        elif "MIDDLE" in origin:
            y0, y1 = -height / 2.0, height / 2.0
        else:  # *_BOTTOM
            y0, y1 = 0.0, height
        rad = math.radians(self.angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        out: list[Point] = []
        for lx, ly in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            out.append(
                Point(
                    self.x + lx * cos_a - ly * sin_a,
                    self.y + lx * sin_a + ly * cos_a,
                )
            )
        return out


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

    ``kind`` distinguishes the four record types that carry area copper:

    * ``"fill"`` — ``FILL`` record, usually a real pour with a net.
    * ``"poly"`` — ``POLY`` record with ``polyType`` ``NORMAL``; often a
      copper region drawn by hand (net may be empty).
    * ``"pour"`` — ``POUR`` record (131f): the pour **region** as the editor
      holds it — the user's own outline, with its ``netName`` and ``layerId``,
      in board coordinates. Distinct from ``"poured"``, which is the result.
    * ``"poured"`` — ``POURED`` record: the *result* of pouring, i.e. the
      copper that actually exists after clearance voids were cut. 135 parses
      its ``pourFill`` polygons into board coordinates (§ ``POURED_SCALE``).

    **Why both a ``"pour"`` and a ``"poured"`` exist.** ``POUR`` is the
    *intent* (the outline the user drew, net and layer and nothing else);
    ``POURED`` is the *result* (that outline minus everything the pour engine
    had to keep clear, possibly as several disjoint islands). A consumer that
    wants to know whether copper is really there wants the result; one that
    wants to know what the designer meant wants the region. See
    :func:`boardwise.core.measure.pour_connectivity` for which one wins where.
    """

    id: str
    net: str | None = None
    layer_id: int | None = None
    kind: str = ""
    points: list[Point] = field(default_factory=list)
    width: float = 0.0
    fill_style: str | None = None
    poly_type: str | None = None
    #: 135: for ``kind == "poured"``, the id of the pour **region** this
    #: result was poured from — the ``POUR`` record's own ``id``, decoded out
    #: of the ``POURED`` id tuple. ``None`` when the region is not in the file
    #: (the ``e-xxxx`` parents), which is exactly the case where this result
    #: is the only description of that copper. :func:`boardwise.core.measure.
    #: _poured_supersedes` reads it to drop the superseded region.
    poured_from: str | None = None
    #: R2-1: the shape as **copper presence** — ``[outline, void, void, ...]``
    #: with every ``ARC`` expanded (:func:`boardwise.parsers.epru._path_rings`).
    #: Filled for ``"poured"`` islands and ``"fill"`` records, empty for the
    #: other kinds and for a hand-built shape. :attr:`points` is untouched (the
    #: first ring's vertices with arcs as chords, what every reader since 125
    #: measures), so this is a second view, not a correction of the first: a
    #: reader that asks 「is there copper at this point」 needs the voids, which
    #: :attr:`points` never had.
    rings: list[list[Point]] = field(default_factory=list)

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
class ProhibitRegion:
    """A copper-prohibition region — a ``REGION`` record (162b).

    EasyEDA's 禁止布线 / 铜禁布区: an area the designer marked as off-limits to
    the thing :attr:`prohibit_types` names. The class carries the record's own
    fields and no reading of what they forbid; that reading lives in the one
    rule that consumes these, ``pcb-keepout-violation`` (R2-1,
    :mod:`boardwise.rules.pcb.keepout`).

    Measured on ``ProPrj_高速电机控制器_2026-09-16.epro2`` — the only board
    fixture with any, six of them in the PCB document:

    .. code-block:: jsonc

       {"regionType": "PROHIBIT", "prohibitType": ["COPPER"], "name": "PROHIBIT",
        "layerId": 2, "width": 0.2, "locked": false, "groupId": 0,
        "path": [["CIRCLE", 1768.425, -370, 93.8415]]}     // r = 93.84 mil

    so the shape arrives as the same ``"CIRCLE"`` / ``"R"`` / polyline ``path``
    forms the artwork reader knows (five circles and one rectangle there), in
    **board coordinates** like every other geometry here. ``path`` is wrapped
    one level (``[[...]]``), which is why this is read with
    :func:`boardwise.parsers.epru._artwork_path` and not ``_path_points``: the
    circle form must survive as a centre **plus** its radius rather than
    collapse to a point. The other fixture with one, ``毕设滤波采样``, carries
    it in a document this parser drops, so only the six above reach a board.
    """

    id: str = ""
    #: The record's own ``name`` — ``"PROHIBIT"`` on the measured board.
    name: str = ""
    layer_id: int | None = None
    #: ``regionType`` verbatim (``"PROHIBIT"``), and ``prohibitType`` verbatim as
    #: the list the file writes (``["COPPER"]``). Kept as strings: which
    #: prohibited thing this region is about is the record's statement, not a
    #: reading this model makes.
    region_type: str = ""
    prohibit_types: list[str] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    #: Set for a ``CIRCLE`` region (the centre is ``points[0]``), ``None`` for
    #: the polygonal forms — exactly as :class:`SilkShape.radius` works.
    radius: float | None = None
    width: float = 0.0
    #: R2-1: a polygonal region's rings with arcs expanded (the outline first);
    #: empty for a ``CIRCLE`` region, whose shape is ``points[0]`` + ``radius``.
    rings: list[list[Point]] = field(default_factory=list)

    @property
    def bbox(self) -> BBox | None:
        return BBox.from_points(self.points)


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

    Task 042 §WI-1 adds two more, and they answer two different questions about
    the same walk. ``attrs_attached_by_parent_id`` says **how the attributes
    arrived**: a count of the ones filed by the record id they name rather than
    by the component they follow, which is non-zero exactly when the document
    has been incrementally saved (see ``schematic._split_page``).
    ``instances_without_designator`` says **what is still unnamed**: a placed
    component that the library device says is a part, that carries no usable
    designator, and that is neither the page frame nor a net flag. Before 042
    that number was 5 on ``robot_live.epro2`` and 67 on the 高速板, and nothing
    reported it — the parts simply were not in the model.
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
    #: ATTRs filed by the record id they name rather than by the component they
    #: follow — the count of what only the parentId rule could place (task 042
    #: §WI-1). Never counted for the page-level kinds (``NET`` /
    #: ``NO_CONNECT`` / ``Global Net Name``), whose parentId is not a component.
    attrs_attached_by_parent_id: int = 0
    #: Placed components the library calls a part that ended up with no
    #: usable designator, so the model drops them. Excludes the page frame
    #: and the net flags, which have no designator by design (task 042 §WI-2).
    instances_without_designator: int = 0
    #: ``POURED`` records whose parent id resolved to a ``POUR`` in the same
    #: document, so the result polygon could inherit that region's net and
    #: layer (task 135). The complement —
    #: :attr:`poured_orphans` — is the headless half.
    poured_with_parent: int = 0
    #: ``POURED`` records whose id names an element that is **not in the file**.
    #: Measured on every board fixture: 毕设FOC 1.0.0 splits 27 / 24, 1.1.0
    #: 33 / 22, llc 0 / 4. These are pours the editor has already replaced
    #: (an inner-layer plane it re-pours writes a fresh ``POURED`` and drops
    #: the region), so the *copper* is real and parses — but the net is not
    #: recoverable from the parent link and is left ``None``.
    poured_orphans: int = 0
    #: ``POURED`` records whose ``pourFill`` array held no ``fill: true``
    #: polygon (only stroked outlines, or nothing at all), so no copper came
    #: out of them. Not a drop of the record — it is counted as a pour with
    #: an empty ``points``.
    poured_without_fill: int = 0
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
            "attrs_attached_by_parent_id": self.attrs_attached_by_parent_id,
            "instances_without_designator": self.instances_without_designator,
            "poured_with_parent": self.poured_with_parent,
            "poured_orphans": self.poured_orphans,
            "poured_without_fill": self.poured_without_fill,
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
    "does this net have any copper at all?". ``non_copper_shapes`` and
    ``prohibit_regions`` (162b) are deliberately **outside** all of that: they
    are not copper, so they are neither net-indexed nor counted in
    :meth:`bbox`.
    """

    source: str = ""
    name: str | None = None
    edit_version: str | None = None
    layers: dict[int, LayerInfo] = field(default_factory=dict)
    #: Physical stackup from ``LAYER_PHYS``, ordered by ``z_index``. Empty
    #: for hand-built boards and files old enough to lack the table; readers
    #: must fall back to :meth:`copper_layers` in that case (task 125a).
    stackup: list[StackupEntry] = field(default_factory=list)
    components: list[ComponentPlacement] = field(default_factory=list)
    pads: list[PadGeometry] = field(default_factory=list)
    tracks: list[TrackSegment] = field(default_factory=list)
    vias: list[ViaGeometry] = field(default_factory=list)
    #: **Copper** polygons only (162b): ``FILL`` / ``POLY`` / ``POUR`` /
    #: ``POURED`` records on a copper layer. A polygon on a solder-mask,
    #: assembly or custom layer is not copper and lives in
    #: :attr:`non_copper_shapes` instead — measured, filing them here made
    #: llc's summary report 137 pours where 32 polygons are copper (105 of the
    #: 137 were a single board's bottom solder-mask openings as ``POLY``).
    #: Every net-indexed consumer reads this list, so the index and the summary
    #: now agree on what a pour is.
    pours: list[PourShape] = field(default_factory=list)
    #: 162b: the board's **non-copper** area polygons — the ones a review of
    #: copper must not mistake for copper. Same records and shape as
    #: :attr:`pours`, so a consumer that wants "was there a polygon here at all"
    #: can look in both; deliberately **not** net-indexed (no net of a
    #: non-copper polygon is copper's business).
    non_copper_shapes: list[PourShape] = field(default_factory=list)
    #: 162b: copper-prohibition regions (``REGION`` records). Consumed since
    #: R2-1 by ``pcb-keepout-violation``.
    prohibit_regions: list[ProhibitRegion] = field(default_factory=list)
    outline: BoardOutline | None = None
    #: 152: the placement artwork that is **not copper** — footprint silkscreen,
    #: body/courtyard outlines and component-marking primitives, instantiated
    #: at each placement (see :class:`SilkShape`). Empty for a hand-built board
    #: and for a backup whose FOOTPRINT documents were not carried out with it.
    silk_shapes: list[SilkShape] = field(default_factory=list)
    #: 152: every piece of silkscreen **text** on the board — each placement's
    #: ``Designator`` attribute, the printed marks carried by the footprint
    #: documents, and free text drawn in the PCB document (see
    #: :class:`SilkText`). Unlike the copper lists this one is **not** net-indexed:
    #: legend has no net, and pretending it had one is what the net index exists
    #: to avoid.
    silk_texts: list[SilkText] = field(default_factory=list)
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

    # -- 152: legend ----------------------------------------------------

    def silk_shapes_for(self, designator: str) -> list[SilkShape]:
        """The artwork primitives of one placement (silkscreen, body, marking)."""
        return [s for s in self.silk_shapes if s.component == designator]

    def silk_texts_for(self, designator: str) -> list[SilkText]:
        """Every piece of legend belonging to one placement: its own designator
        record plus any printed mark its footprint carries.

        The two are **not** interchangeable and the caller can tell them apart
        by :attr:`SilkText.source` — a ``"designator"`` is the board's own
        record for the part (so it carries ``visible``), a ``"footprint"`` is
        the library's printed mark (so it carries the footprint's intent).
        """
        return [t for t in self.silk_texts if t.component == designator]

    def designator_text(self, designator: str) -> SilkText | None:
        """The placement's own designator record, or ``None`` when it has none."""
        for text in self.silk_texts:
            if text.component == designator and text.source == "designator":
                return text
        return None

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
            "non_copper_shapes": len(self.non_copper_shapes),
            "prohibit_regions": len(self.prohibit_regions),
            "silk_shapes": len(self.silk_shapes),
            "silk_texts": len(self.silk_texts),
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
