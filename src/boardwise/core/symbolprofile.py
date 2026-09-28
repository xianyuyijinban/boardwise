"""SymbolProfile: the geometry of one library symbol, as the parser can give it.

The fourth contract of 053 stage A (the other three are
:mod:`~boardwise.core.circuitspec`, :mod:`~boardwise.core.presentationspec` and
:mod:`~boardwise.core.layoutplan`). A CircuitSpec says "R1 is a 10k resistor";
this says where that symbol's pins actually are, how big its body is, which
poses it may be drawn in and which pins mean what electrically. It is the one
input to the drawing compiler that comes from a **file** rather than from
someone's intent.

Offline by construction: 053 sec.2 puts the source at "解析器已读的 SYMBOL 文档
(.epro2 夹具/库导出)，不进编辑器". So :func:`from_parsed_symbol` takes the
`SymbolDetail` a parser already produced and maps it — it does not parse, and it
does not import `boardwise.parsers` (the layering rule: `core` is the bottom).

**What the parser does not give is left empty, never invented.** Two facts are
worth naming here because a reader will look for them:

* **A pin's direction is derived, and says so.** A real `PIN` record carries
  ``rotation`` and ``length``, but `SymbolDetail.offsets` keeps only the tip
  point, so the pin's own orientation is dropped before this module sees it.
  The direction is therefore *derived* from where the tip sits relative to the
  body box — and each pin records that its direction came from
  :data:`DIRECTION_SOURCE_BODY` rather than from the file, so nothing downstream
  can mistake a derivation for a measurement.
* **Text geometry is absent.** `collect_symbol_details` reads RECT / POLY /
  CIRCLE to bound the drawn extent and nothing else; a symbol's ``Designator`` /
  ``Pin Name`` ATTR records (which do carry x, y, align and fontSize) are not
  exposed. So :attr:`SymbolProfile.texts` comes back **empty** from a parsed
  symbol: the reference/value default positions are not claimed, and the text
  boxes a LayoutPlan must carry are computed by the compiler, not read here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "DIRECTIONS",
    "DIRECTION_SOURCE_BODY",
    "DEFAULT_POSES",
    "FLAG_GLYPH_ROTATION_OFFSET",
    "POSE_ROTATIONS",
    "POSES_SOURCE_DECLARED",
    "POSES_SOURCE_UNRESTRICTED",
    "ROLE_BY_PIN_NAME",
    "ROLE_SOURCE_PIN_NAME",
    "SYMBOL_PROFILE_KIND",
    "SYMBOL_PROFILE_VERSION",
    "Box",
    "SymbolPin",
    "SymbolPose",
    "SymbolProfile",
    "SymbolProfileError",
    "SymbolText",
    "check_box",
    "flag_glyph_box",
    "from_parsed_symbol",
    "role_of_pin",
    "role_siblings",
]

#: An axis-aligned box in canvas units (0.01 in), as ``(min_x, min_y, max_x,
#: max_y)`` — the same plain shape `SymbolDetail.body` uses for a symbol's drawn
#: extent. Deliberately not `core.geometry.BBox`, which is declared in *mils*:
#: one canvas unit is 10 mil, and a shared type would invite exactly the
#: conversion bug this paragraph exists to prevent.
Box = tuple[float, float, float, float]

SYMBOL_PROFILE_KIND = "boardwise-symbol-profile"

#: Same rule as `changeplan.PLAN_VERSION`: a stated version this build does not
#: have is refused rather than guessed at.
SYMBOL_PROFILE_VERSION = 1

#: The rotations a symbol is drawn in, in degrees (052 sec.6's "有限合法姿态").
POSE_ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)

#: Which way a pin points, measured *outward* from the body: the direction the
#: escape stub leaves in. Empty means the profile cannot tell.
DIRECTIONS: tuple[str, ...] = ("left", "right", "up", "down")

#: Where a pin's direction came from. Only one value today: derived from the tip
#: against the body box. Named per pin so a later parser that reads the PIN
#: row's own ``rotation`` can say so without this field silently changing
#: meaning.
DIRECTION_SOURCE_BODY = "body-box"

#: Where the allowed pose set came from. A parsed symbol file states no pose
#: restriction (there is no such field), so the default set is *assumed*, not
#: read — and it says so, because "all poses allowed" and "the file allows all
#: poses" are different claims.
POSES_SOURCE_UNRESTRICTED = "unrestricted-default"
POSES_SOURCE_DECLARED = "declared"

#: Where an electrical role came from.
ROLE_SOURCE_PIN_NAME = "pin-name"

#: The rotation a flag profile's **glyph box** is measured at, relative to the
#: rotation the editor is given — see :func:`flag_glyph_box`.
FLAG_GLYPH_ROTATION_OFFSET = 180.0

#: The pin-name tokens this build maps to a role, and nothing else.
#:
#: Conservative on purpose (052 sec.5 asks for "引脚名推断", not for guessing):
#: only exact, unambiguous supply / port names are mapped, matched
#: case-insensitively. A name that is not here gets no role — a wrong role is
#: worse than an absent one, because the drawing reads it. Single-letter names
#: ("A", "K" on an LED, but also an address pin) and numbered forms ("IN1") are
#: deliberately left out; the raw `name` is carried for whoever wants them.
ROLE_BY_PIN_NAME: dict[str, str] = {
    "GND": "GND", "AGND": "GND", "DGND": "GND", "GNDA": "GND", "VSS": "GND",
    "GROUND": "GND",
    "VIN": "VIN", "VCC": "VIN", "VDD": "VIN", "VBUS": "VIN", "VBAT": "VIN",
    "VS": "VIN",
    "VOUT": "VOUT", "VOUTA": "VOUT",
    "IN": "IN", "OUT": "OUT", "EN": "EN", "NR": "NR",
}

#: Every pose permitted when nothing says otherwise: four rotations, mirrored or
#: not. Mirror legality is *unstated* by the file, not granted by it. Built from
#: `SymbolPose`, so it is defined below that class — the name is resolved when a
#: profile is constructed, not when this module is read.

_JSON_KEYS = (
    "kind",
    "profileVersion",
    "symbolRef",
    "title",
    "body",
    "pins",
    "poses",
    "poseSource",
    "texts",
    "source",
    "notes",
)
_PIN_KEYS = (
    "number",
    "name",
    "tip",
    "direction",
    "directionSource",
    "electricalRole",
    "roleSource",
    "pinType",
    "length",
)
_TEXT_KEYS = ("kind", "x", "y", "bbox")


class SymbolProfileError(ValueError):
    """The profile is not one this build can use."""


@dataclass(frozen=True)
class SymbolPose:
    """One legal pose: a rotation and whether the symbol is mirrored.

    Frozen because it is used as a dictionary/set member and because a pose is a
    value — the drawing either uses it or does not.
    """

    rotation: int = 0
    mirror: bool = False

    def label(self) -> str:
        """``"90"`` or ``"90+mirror"`` — the spelling a report can print."""
        return f"{self.rotation}+mirror" if self.mirror else str(self.rotation)

    def to_jsonable(self) -> dict[str, Any]:
        return {"rotation": self.rotation, "mirror": self.mirror}


#: Every pose permitted when nothing says otherwise: four rotations, mirrored or
#: not. Mirror legality is *unstated* by a symbol file, not granted by it, which
#: is why a parsed profile records :data:`POSES_SOURCE_UNRESTRICTED` — see
#: :func:`from_parsed_symbol`.
DEFAULT_POSES: tuple[SymbolPose, ...] = tuple(
    SymbolPose(rotation=rotation, mirror=mirror)
    for rotation in POSE_ROTATIONS
    for mirror in (False, True)
)



@dataclass
class SymbolPin:
    """One pin: its number, its **tip**, and how it points.

    ``tip`` is the connection end — the point a wire lands on, which is what
    `SymbolDetail.offsets` measured — not the point where the pin meets the
    body. The tool needs the tip (wiring) and the direction (escape), so both
    are here; the pin's length is not derivable from them and stays ``None``.
    """

    number: str
    tip: tuple[float, float]
    #: The symbol's own ``Pin Name`` — the identity that survives a library
    #: revision (measured 2026-09-14: a symbol numbering its pins 1..14 against
    #: library names A1B12/CC1), which is why it is carried beside the number.
    name: str = ""
    direction: str = ""
    direction_source: str = ""
    #: A free string — VIN / VOUT / GND / IN / OUT / EN / NR (052 sec.5). Empty
    #: when the name is not one this build maps.
    electrical_role: str = ""
    role_source: str = ""
    #: The symbol's own ``Pin Type`` (``Undefined`` / ``Power`` / ``Input``…),
    #: verbatim. Carried rather than folded into the role because it is a
    #: measured fact and the role is an inference.
    pin_type: str = ""
    #: The pin's drawn length. **Never filled today**: `SymbolDetail` exposes
    #: tips only, though the file's own ``PIN`` rows carry ``length``. Left here
    #: with its honest ``None`` so the gap is visible rather than assumed away.
    length: float | None = None


@dataclass
class SymbolText:
    """One piece of text the symbol itself places (reference, value, …).

    Coordinates and box are all optional because a symbol need not state either:
    `Designator`'s x/y came back ``None`` on the golden fixture, and the parser
    exposes no ATTR geometry at all, so :func:`from_parsed_symbol` produces no
    texts. A caller that has them fills them; a caller that does not must not
    guess a box, because the readability contract measures overlap against it.
    """

    kind: str
    x: float | None = None
    y: float | None = None
    bbox: Box | None = None


@dataclass
class SymbolProfile:
    """One symbol's geometry and its inferred roles."""

    symbol_ref: str
    title: str = ""
    #: The drawn extent (RECT/POLY/CIRCLE union), or ``None`` when the parser
    #: found none. Used for body/collision checks; pin tips sit outside it.
    body: Box | None = None
    pins: list[SymbolPin] = field(default_factory=list)
    poses: list[SymbolPose] = field(default_factory=lambda: list(DEFAULT_POSES))
    pose_source: str = POSES_SOURCE_DECLARED
    texts: list[SymbolText] = field(default_factory=list)
    #: Where this profile came from ("parsed-symbol:<uuid>", a file path, …).
    source: str = ""
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ derived

    def pin(self, number: str) -> SymbolPin | None:
        """The pin with this number, or ``None``."""
        for item in self.pins:
            if item.number == number:
                return item
        return None

    def pin_numbers(self) -> list[str]:
        return [item.number for item in self.pins]

    def role_pins(self, role: str) -> list[SymbolPin]:
        """Every pin carrying this electrical role."""
        return [item for item in self.pins if item.electrical_role == role]

    def allows(self, rotation: float, mirror: bool = False) -> bool:
        """May the symbol be drawn at this pose?"""
        return any(
            pose.rotation == rotation and pose.mirror == mirror for pose in self.poses
        )

    def canonical_json(self) -> str:
        """Sorted, whitespace-free JSON of the **geometry** (see `geometry_hash`).

        Pins are re-sorted by number here rather than taken in list order: the
        order a file happens to emit its pins in is not geometry (049 measured
        the same symbol emitted in different orders by two container formats),
        so two profiles of one symbol must hash alike.
        """
        payload = {
            "symbolRef": self.symbol_ref,
            "body": list(self.body) if self.body else None,
            "pins": [
                {
                    "number": pin.number,
                    "name": pin.name,
                    "tip": list(pin.tip),
                    "direction": pin.direction,
                }
                for pin in sorted(self.pins, key=lambda item: _pin_sort_key(item.number))
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)

    def geometry_hash(self) -> str:
        """The hash a LayoutPlan records for this symbol's geometry.

        Exactly: symbol_ref, body box, and each pin's number, name, tip and
        direction. **Excluded on purpose** — the title, notes and source (where
        the profile came from, not what it says); the electrical role and its
        source (an inference from a name table: a better table must not
        invalidate a plan that is geometrically identical); the pose set (a
        statement about legality, not a coordinate); the texts (the parser
        produces none, and a text box is a layout decision). A hash whose domain
        is not written down cannot be reasoned about when it changes.
        """
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "kind": SYMBOL_PROFILE_KIND,
            "profileVersion": SYMBOL_PROFILE_VERSION,
            "symbolRef": self.symbol_ref,
            "title": self.title,
            "body": list(self.body) if self.body else None,
            "pins": [
                {
                    "number": pin.number,
                    "name": pin.name,
                    "tip": list(pin.tip),
                    "direction": pin.direction,
                    "directionSource": pin.direction_source,
                    "electricalRole": pin.electrical_role,
                    "roleSource": pin.role_source,
                    "pinType": pin.pin_type,
                    "length": pin.length,
                }
                for pin in self.pins
            ],
            "poses": [pose.to_jsonable() for pose in self.poses],
            "poseSource": self.pose_source,
            "texts": [
                {
                    "kind": text.kind,
                    "x": text.x,
                    "y": text.y,
                    "bbox": list(text.bbox) if text.bbox else None,
                }
                for text in self.texts
            ],
            "source": self.source,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> SymbolProfile:
        root = _object(payload, "$")
        _check_keys(root, _JSON_KEYS, "$")
        version = root.get("profileVersion", SYMBOL_PROFILE_VERSION)
        if version != SYMBOL_PROFILE_VERSION:
            raise SymbolProfileError(
                f"$.profileVersion is {version!r}, this build reads "
                f"{SYMBOL_PROFILE_VERSION}"
            )
        kind = root.get("kind")
        if kind is not None and kind != SYMBOL_PROFILE_KIND:
            raise SymbolProfileError(
                f"$.kind is {kind!r}, expected {SYMBOL_PROFILE_KIND!r}"
            )
        pins = _pins_from(root.get("pins"))
        _refuse_shared_tips(pins)
        poses = _poses_from(root.get("poses"), root.get("poseSource"))
        texts = _texts_from(root.get("texts"))
        profile = cls(
            symbol_ref=_text(root.get("symbolRef"), "$.symbolRef", required=True),
            title=_text(root.get("title"), "$.title"),
            body=check_box(root.get("body"), "$.body"),
            pins=pins,
            poses=poses,
            pose_source=str(root.get("poseSource") or POSES_SOURCE_DECLARED),
            texts=texts,
            source=_text(root.get("source"), "$.source"),
            notes=_text_list(root.get("notes"), "$.notes"),
        )
        _check_pose_source(profile)
        return profile

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> SymbolProfile:
        """Read a profile file. Every failure is a :class:`SymbolProfileError`."""
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise SymbolProfileError(f"{source}: cannot be read ({exc})") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise SymbolProfileError(f"{source}: is not JSON ({exc})") from exc
        try:
            return cls.from_dict(payload)
        except SymbolProfileError as exc:
            raise SymbolProfileError(f"{source}: {exc}") from exc


# -------------------------------------------------------------- flag glyphs


def flag_glyph_box(
    profile: SymbolProfile, *, rotation: float, anchor: tuple[float, float]
) -> Box | None:
    """The page box a rail/ground **flag**'s glyph occupies, or ``None``.

    A flag profile is a symbol with no pins: its origin *is* the connection point
    (a pin-less profile is how the compiler identifies a flag), and its ``body``
    is 053B's convention — the glyph's extent taken **away from the pin** the
    flag names. Every library this repo ships states it that way
    (``(-6, 0, 6, 18)`` for ``PWR-GND`` and for every ``PWR-<rail>``).

    The editor's own power symbols do not all hang that way, and that is the fact
    this function exists for. Read out of an export's own SYMBOL documents
    (``Ground-GND`` carries ``BBOX (-10, 0, 10, -19)``: connection at the top of
    the stem, bars running *below* it; ``Power-VCC`` and ``Power-5V`` carry
    ``(-5, 10, 5, 0)`` and ``(-5, 10, 5, 5)``: a bar *above* the connection), the
    two families hang on opposite sides. So the box a drawing must reserve is not
    the profile's box at the rotation the editor is given, but the box that hangs
    away from the pin — :data:`FLAG_GLYPH_ROTATION_OFFSET` from it. The evidence
    and the read-back are in ``tools/060_flag_glyph_evidence.py``.

    One function for the compiler's occupancy, the page compiler's extents and
    the SVG preview, because all three draw this one box: a preview that computed
    its own would be self-consistent and wrong, which is exactly how six batches
    of upside-down flags stayed invisible (`outputs/057_live/e1b/render.png`).
    """
    if profile.body is None:
        return None
    from .geometry import transform_point

    x0, y0, x1, y1 = profile.body
    angle = rotation + FLAG_GLYPH_ROTATION_OFFSET
    corners = [
        transform_point(
            x, y, rotation=angle, mirror=False, ox=anchor[0], oy=anchor[1],
        )
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


# ------------------------------------------------- one role, several pins


def role_of_pin(pin: SymbolPin) -> str:
    """The electrical role this pin plays: the profile's own, else its pin name."""
    role = (pin.electrical_role or "").strip()
    if role:
        return role
    return ROLE_BY_PIN_NAME.get((pin.name or "").strip().upper(), "")


def role_siblings(profile: SymbolProfile, token: str) -> tuple[SymbolPin, ...]:
    """Every **other** pin of `profile` that plays the same role as `token` does.

    060 sec.2: a symbol may carry one role on several pins — the measured AMS1117
    draws VOUT on both sides of its body, one of them the pad that carries the
    heat. Those pins are **one node inside the symbol**, so connecting one
    connects the role, and an empty pad beside a wired one is a shape an engineer
    does not draw. The ruling is that they are all connected by default, and
    `nc[]` is the explicit exception.

    Both halves of that live here, because both halves have to mean the same
    thing: the compiler wires the siblings it finds, and the readability checker
    expects them on the role's node. Two implementations would eventually
    disagree about which pins are "the same role", and the disagreement would
    show up as a drawing that is wired correctly and reported as an undeclared
    short.
    """
    if not token:
        return ()
    here = None
    for pin in profile.pins:
        if token in (pin.number, pin.name):
            here = pin
            break
    if here is None:
        return ()
    role = role_of_pin(here)
    if not role:
        return ()
    return tuple(
        pin for pin in profile.pins
        if pin is not here and role_of_pin(pin) == role
    )


# ------------------------------------------------------------------ extract


def from_parsed_symbol(symbol: Any, *, source: str = "") -> SymbolProfile:
    """Map a parser `SymbolDetail` into a :class:`SymbolProfile`.

    Takes the object, not a path: `core` may not import `parsers`, and the
    `SymbolDetail` a parser produced is a plain value — ``uuid``, ``title``,
    ``offsets`` (pin number -> tip), ``pin_names``, ``pin_types`` and ``body``.

    Everything the parser does not expose is left empty and the gap is written
    into `notes`; nothing here computes a fact the file did not state. The two
    exceptions are named, derived and labelled:

    * each pin's **direction** comes from its tip against the body box, and the
      pin records :data:`DIRECTION_SOURCE_BODY`;
    * each pin's **electrical role** comes from :data:`ROLE_BY_PIN_NAME`, and the
      pin records :data:`ROLE_SOURCE_PIN_NAME`.

    A library symbol whose pins cannot be told apart (two pins sharing one tip)
    is refused: 053 sec.2 makes that the entry point for "禁止换脚号迁就版式" —
    a symbol that cannot be wired as drawn must be swapped for a compatible one
    or reported as a capability boundary, never bent into fitting.
    """
    offsets = getattr(symbol, "offsets", None)
    if not isinstance(offsets, dict):
        raise SymbolProfileError(
            "expected a parser SymbolDetail (an object with `.offsets`: pin "
            f"number -> tip), got {type(symbol).__name__}"
        )
    symbol_ref = str(getattr(symbol, "uuid", "") or "")
    if not symbol_ref:
        raise SymbolProfileError(
            "the parsed symbol carries no uuid, so a profile built from it could "
            "not say which symbol it describes"
        )
    names = _attr_map(symbol, "pin_names")
    types = _attr_map(symbol, "pin_types")
    body = check_box(getattr(symbol, "body", None), "symbol.body")

    pins: list[SymbolPin] = []
    for number in sorted(offsets, key=_pin_sort_key):
        tip = _point(offsets[number], f"symbol.offsets[{number!r}]")
        name = names.get(number, "")
        role = ROLE_BY_PIN_NAME.get(name.strip().upper(), "")
        direction = _direction(tip, body)
        pins.append(SymbolPin(
            number=str(number),
            tip=tip,
            name=name,
            direction=direction,
            # Only a pin the geometry actually answered names its source: a pin
            # sitting on or inside the body has no direction, and claiming one
            # came from the box would be claiming an answer that was not given.
            direction_source=DIRECTION_SOURCE_BODY if direction else "",
            electrical_role=role,
            role_source=ROLE_SOURCE_PIN_NAME if role else "",
            pin_type=types.get(number, ""),
        ))
    _refuse_shared_tips(pins)

    notes = [
        "poses: the symbol file states no pose restriction, so every rotation "
        "and both mirror states are assumed allowed "
        f"({POSES_SOURCE_UNRESTRICTED}); a polarised symbol must narrow this "
        "explicitly",
        "texts: the parser exposes no symbol text records (collect_symbol_details "
        "reads RECT/POLY/CIRCLE only), so no reference/value position or text box "
        "is claimed here",
        "pin length: not available (SymbolDetail exposes tips only, though the "
        "file's PIN rows carry `length`)",
    ]
    return SymbolProfile(
        symbol_ref=symbol_ref,
        title=str(getattr(symbol, "title", "") or ""),
        body=body,
        pins=pins,
        poses=list(DEFAULT_POSES),
        pose_source=POSES_SOURCE_UNRESTRICTED,
        texts=[],
        source=source or f"parsed-symbol:{symbol_ref}",
        notes=notes,
    )


def _attr_map(symbol: Any, name: str) -> dict[str, str]:
    value = getattr(symbol, name, None)
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _pin_sort_key(number: Any) -> tuple[int, int, str]:
    """Natural order, so ``1 < 2 < 10`` and letters follow numbers.

    The file's own pin order is a formatting artifact — 049 measured the same
    library symbol emitting its pins in different orders across two container
    formats — so a profile sorts. Without this, two parses of one symbol would
    hash differently for no electrical reason.
    """
    text = str(number).strip()
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def _direction(tip: tuple[float, float], body: Box | None) -> str:
    """Which way a pin points, from its tip against the body box.

    The tip is the connection end, so it sits outside the drawn body and the
    outward direction is the axis on which it left:

    * strictly left/right/below/above the box -> that side;
    * outside on two axes (a corner) -> the axis it overshoots further;
    * on or inside the box -> "" (a zero-length or interior pin: the geometry
      does not say, and guessing would put the escape stub inside the body).

    Derived, never read: a real ``PIN`` row carries ``rotation``, which
    `SymbolDetail` drops. The caller is told by each pin's
    ``direction_source``.
    """
    if body is None:
        return ""
    x, y = tip
    min_x, min_y, max_x, max_y = body
    overshoot = {
        "left": min_x - x,
        "right": x - max_x,
        "down": min_y - y,
        "up": y - max_y,
    }
    outward = {side: gap for side, gap in overshoot.items() if gap > 0}
    if not outward:
        return ""
    return max(outward, key=lambda side: outward[side])


def _refuse_shared_tips(pins: Iterable[SymbolPin]) -> None:
    """Two pins on one tip is a symbol that cannot be wired as drawn.

    Refused here rather than at the wire because this is the *entry point* for
    the failure 053 sec.2 names: a symbol whose pin mapping does not fit wants a
    compatible symbol or an honest capability boundary, and the one repair that
    is forbidden is renumbering pins to make the layout work.
    """
    seen: dict[tuple[float, float], str] = {}
    for pin in pins:
        key = (round(pin.tip[0], 6), round(pin.tip[1], 6))
        if key in seen:
            raise SymbolProfileError(
                f"pins {seen[key]!r} and {pin.number!r} share the tip at "
                f"({pin.tip[0]:g}, {pin.tip[1]:g}) — the symbol cannot be wired as "
                "drawn; use a symbol whose pin mapping has been verified, or "
                "report the capability boundary (053 sec.2). Renumbering the pins "
                "to fit the drawing is forbidden"
            )
        seen[key] = pin.number


# ------------------------------------------------------------------ readers


def _pins_from(value: Any) -> list[SymbolPin]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SymbolProfileError(f"$.pins must be a list, got {value!r}")
    out: list[SymbolPin] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        spot = f"pins[{index}]"
        body = _object(item, spot)
        _check_keys(body, _PIN_KEYS, spot)
        number = _text(body.get("number"), f"{spot}.number", required=True)
        if number in seen:
            raise SymbolProfileError(f"{spot}.number is {number!r}, already used")
        seen.add(number)
        direction = str(body.get("direction") or "")
        if direction not in ("", *DIRECTIONS):
            raise SymbolProfileError(
                f"{spot}.direction is {direction!r}; expected one of "
                f"{', '.join(DIRECTIONS)}, or empty when it is not known"
            )
        length = body.get("length")
        if length is not None:
            length = _number(length, f"{spot}.length")
        out.append(SymbolPin(
            number=number,
            tip=_point(body.get("tip"), f"{spot}.tip"),
            name=_text(body.get("name"), f"{spot}.name"),
            direction=direction,
            direction_source=str(body.get("directionSource") or ""),
            electrical_role=_text(body.get("electricalRole"), f"{spot}.electricalRole"),
            role_source=str(body.get("roleSource") or ""),
            pin_type=_text(body.get("pinType"), f"{spot}.pinType"),
            length=length,
        ))
    return out


def _poses_from(value: Any, source: Any) -> list[SymbolPose]:
    if value is None:
        if source is not None:
            raise SymbolProfileError(
                "$.poseSource is stated but $.poses is absent — the source "
                "describes a set that is not there"
            )
        return list(DEFAULT_POSES)
    if not isinstance(value, list) or not value:
        raise SymbolProfileError(
            f"$.poses must be a non-empty list of poses, got {value!r} — a symbol "
            "that may be drawn in no pose cannot be placed"
        )
    out: list[SymbolPose] = []
    for index, item in enumerate(value):
        spot = f"poses[{index}]"
        body = _object(item, spot)
        _check_keys(body, ("rotation", "mirror"), spot)
        rotation = body.get("rotation")
        if isinstance(rotation, bool) or rotation not in POSE_ROTATIONS:
            raise SymbolProfileError(
                f"{spot}.rotation is {rotation!r}; expected one of "
                f"{', '.join(str(item) for item in POSE_ROTATIONS)}"
            )
        mirror = body.get("mirror", False)
        if not isinstance(mirror, bool):
            raise SymbolProfileError(f"{spot}.mirror must be a boolean, got {mirror!r}")
        pose = SymbolPose(rotation=int(rotation), mirror=mirror)
        if pose in out:
            raise SymbolProfileError(f"{spot} repeats the pose {pose.label()!r}")
        out.append(pose)
    return out


def _check_pose_source(profile: SymbolProfile) -> None:
    if profile.pose_source not in (POSES_SOURCE_DECLARED, POSES_SOURCE_UNRESTRICTED):
        raise SymbolProfileError(
            f"$.poseSource is {profile.pose_source!r}; expected "
            f"{POSES_SOURCE_DECLARED!r} (a caller narrowed the set) or "
            f"{POSES_SOURCE_UNRESTRICTED!r} (nothing said, so every pose is "
            "assumed allowed)"
        )
    if (
        profile.pose_source == POSES_SOURCE_UNRESTRICTED
        and sorted((pose.rotation, pose.mirror) for pose in profile.poses)
        != sorted((pose.rotation, pose.mirror) for pose in DEFAULT_POSES)
    ):
        raise SymbolProfileError(
            "$.poses narrows the set but $.poseSource says "
            f"{POSES_SOURCE_UNRESTRICTED!r} — say {POSES_SOURCE_DECLARED!r} when a "
            "caller chose the set, so a reader can tell an assumption from a "
            "decision"
        )


def _texts_from(value: Any) -> list[SymbolText]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SymbolProfileError(f"$.texts must be a list, got {value!r}")
    out: list[SymbolText] = []
    for index, item in enumerate(value):
        spot = f"texts[{index}]"
        body = _object(item, spot)
        _check_keys(body, _TEXT_KEYS, spot)
        x = body.get("x")
        y = body.get("y")
        out.append(SymbolText(
            kind=_text(body.get("kind"), f"{spot}.kind", required=True),
            x=None if x is None else _number(x, f"{spot}.x"),
            y=None if y is None else _number(y, f"{spot}.y"),
            bbox=check_box(body.get("bbox"), f"{spot}.bbox"),
        ))
    return out


# ------------------------------------------------------------------ helpers


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SymbolProfileError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise SymbolProfileError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise SymbolProfileError(f"{where} must be a string, got {value!r}")
    if required and not value.strip():
        raise SymbolProfileError(f"{where} is empty")
    return value.strip()


def _text_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SymbolProfileError(f"{where} must be a list of strings, got {value!r}")
    return list(value)


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SymbolProfileError(
            f"{where} must be a number in canvas units, got {value!r}"
        )
    return float(value)


def _point(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) < 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float))
               for item in value[:2])
    ):
        raise SymbolProfileError(f"{where} must be [x, y] in canvas units, got {value!r}")
    return (float(value[0]), float(value[1]))


def check_box(value: Any, where: str, error: type[ValueError] = SymbolProfileError) -> Box | None:
    """Validate ``[minX, minY, maxX, maxY]`` (canvas units), or ``None``/absent.

    Public because :mod:`~boardwise.core.layoutplan` measures text and glyph
    boxes in the same units and with the same rules — one validator, so a
    LayoutPlan cannot accept a box a SymbolProfile would refuse.

    ``error`` is the caller's exception: each module raises its own type, and a
    refusal has to arrive as the error the caller's callers catch.
    """
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, (int, float))
               for item in value)
    ):
        raise error(
            f"{where} must be [minX, minY, maxX, maxY] in canvas units, got {value!r}"
        )
    box = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    if box[2] < box[0] or box[3] < box[1]:
        raise error(
            f"{where} is {value!r} — maxX/maxY are below minX/minY, which is not a box"
        )
    return box


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise SymbolProfileError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)}"
        )
