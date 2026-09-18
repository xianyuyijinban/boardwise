"""Block templates and board specs — the data contract of the 008 generator.

Task 008's architecture says a page is built by **placing blocks and replaying
each block's own geometry**; nothing about the layout is left to a model
(``docs/architecture.md``, "The model-freedom boundary"). This module is the
shape of the two JSON documents that carry that intent, plus the validation
that makes them checkable:

* a **block template** — one file per block, self-contained: its origin and
  bounding box, the parts it places, the symbol geometry they need, the wires
  and flags it replays, the parameters that hold its numbers, and the ports it
  offers to the rest of the page;
* a **board spec** — which templates to place, where, with which parameter
  values, and how their ports are wired together by name.

Coordinate space, stated once because this project has paid for the mistake
twice: **every coordinate inside a block template is a block-local file
coordinate**, i.e. the golden page's file-space value minus
:attr:`BlockTemplate.origin_file`. ``origin_file`` is kept so the block can be
put back where it came from (that is what makes the round-trip test possible).
Nothing here speaks canvas: the one file→canvas conversion stays in
:func:`boardwise.engines.generate.canvas_pin_offsets` and in
:mod:`boardwise.engines.replay` (the 006c constitution, guarded by
``tests/test_coordinate_guards.py``).

Validation is deliberately strict and loud:

* an unknown key is an error, not a silently ignored field — the whole point of
  a template is that a human can read it and know it says what it means;
* a parameter names a **constraint** from :data:`CONSTRAINTS`, and every value
  (the template's default and any the board spec assigns) is checked against it;
* an unknown constraint is an error. Falling back to "no constraint" would make
  a typo'd constraint name indistinguishable from a deliberate one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import is_ground_net

#: Written into every template and spec so a stale file fails loudly instead of
#: being read with today's rules.
BLOCK_TEMPLATE_KIND = "boardwise-block-template"
BOARD_SPEC_KIND = "boardwise-board-spec"
SCHEMA_VERSION = 1

#: Provenance kinds a block may declare. The three are the architecture's three
#: template sources (008 constitution item 3).
PROVENANCE_KINDS = ("textbook", "datasheet-extract", "board-extract")

#: Net classes a port may declare. ``power`` and ``gnd`` are named by flags;
#: ``signal`` is named by a label (岳翔宇's rule: never an I/O port).
NET_CLASSES = ("power", "signal", "gnd")

#: The role a **power / ground** port plays in the supply tree (task 008c,
#: item 4). Exactly two, and only on one of those two classes: the tree counts
#: sources, so a ``direction`` on a signal port would read as a claim about
#: power, and the loader rejects it rather than guessing which was meant.
PORT_DIRECTIONS = ("source", "sink")

#: What a board spec may cite as the authority for one of its fields. The
#: vocabulary is closed for the same reason the pin table's functions are: the
#: closed-book gate asks *which declared input* justifies a field, and an
#: invented kind would let "some unspecified source" through.
REFERENCE_KINDS = ("intent", "pintable", "datasheet", "part", "textbook")

Point = tuple[float, float]


class BlockError(ValueError):
    """A template or spec is malformed. Always names the offending field."""


# --------------------------------------------------------------------------
# parameter constraints — the executable half of `params`
# --------------------------------------------------------------------------

#: A resistor written either as an SI quantity (``10k``, ``2.2kΩ``, ``470Ω``) or
#: in the R-notation (``4R7``). Units are optional because a schematic value
#: field routinely omits them; the point of the check is to reject *nonsense*,
#: not to disambiguate ``5.1K`` (the constraint name already says which it is).
_RESISTOR_RE = re.compile(
    r"^(?P<int>[0-9]+)R(?P<frac>[0-9]+)$"
    r"|^(?P<num>[0-9]*\.?[0-9]+)\s*(?P<prefix>m|k|K|M|G|R|meg)?\s*(?P<unit>Ω|ohm|Ohm|OHM|R)?$"
)
#: A capacitance: the farad unit is required, because ``5.1K`` and ``100nF``
#: differ exactly by it and a constraint that accepts both checks nothing.
_CAPACITOR_RE = re.compile(
    r"^(?P<num>[0-9]*\.?[0-9]+)\s*(?P<prefix>p|n|u|µ|μ|m|k|K)?\s*(?P<unit>F|f)$"
)
_FREQUENCY_RE = re.compile(
    r"^(?P<num>[0-9]*\.?[0-9]+)\s*(?P<prefix>k|K|M|G)?\s*(?P<unit>Hz|hz)?$"
)


def _check_quantity(value: str, pattern: re.Pattern[str], what: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return f"is empty; a {what} value is required"
    return None if pattern.match(text) else f"is not a {what} value: {value!r}"


def _check_free_text(value: str) -> str | None:
    return None


def _check_resistor(value: str) -> str | None:
    return _check_quantity(value, _RESISTOR_RE, "resistor")


def _check_capacitor(value: str) -> str | None:
    return _check_quantity(value, _CAPACITOR_RE, "capacitor")


def _check_frequency(value: str) -> str | None:
    return _check_quantity(value, _FREQUENCY_RE, "frequency")


#: The constraint registry. A parameter's ``constraint`` must name one of these;
#: the checker returns ``None`` when the value is acceptable and a reason
#: otherwise, and the reason is shown to whoever wrote the offending JSON.
CONSTRAINTS: dict[str, Any] = {
    "free_text": _check_free_text,
    "resistor_value": _check_resistor,
    "capacitor_value": _check_capacitor,
    "frequency": _check_frequency,
}


def check_constraint(name: str, value: str) -> str | None:
    """Validate ``value`` against the named constraint.

    An unknown constraint name is an error (``None`` is never returned for
    one): a typo'd constraint that silently validates nothing is worse than no
    constraint at all, because the template then *claims* a check it does not
    perform.
    """
    checker = CONSTRAINTS.get(name)
    if checker is None:
        raise BlockError(
            f"unknown constraint {name!r}; known: {', '.join(sorted(CONSTRAINTS))}"
        )
    return checker(value)


# --------------------------------------------------------------------------
# readers
# --------------------------------------------------------------------------


def _as_point(value: Any, where: str) -> Point:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        return (float(value[0]), float(value[1]))
    raise BlockError(f"{where}: expected [x, y], got {value!r}")


def _as_box(value: Any, where: str) -> tuple[float, float, float, float]:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        x0, y0, x1, y1 = (float(v) for v in value)
        if x0 > x1 or y0 > y1:
            raise BlockError(f"{where}: box is not (min, max) ordered: {value!r}")
        return (x0, y0, x1, y1)
    raise BlockError(f"{where}: expected [x0, y0, x1, y1], got {value!r}")


def _as_str(value: Any, where: str, *, allow_empty: bool = True) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BlockError(f"{where}: expected a string, got {type(value).__name__}")
    text = value.strip()
    if not text and not allow_empty:
        raise BlockError(f"{where}: must not be empty")
    return text


def _as_float(value: Any, where: str, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlockError(f"{where}: expected a number, got {value!r}")
    return float(value)


def _as_bool(value: Any, where: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise BlockError(f"{where}: expected true/false, got {value!r}")
    return value


def _as_list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BlockError(f"{where}: expected a list, got {type(value).__name__}")
    return value


def _as_evidence(value: Any, where: str) -> list[str]:
    """A list of reference ids, as the evidence one spec field carries.

    Duplicates are refused rather than collapsed: writing the same citation
    twice is nearly always a copy-paste, and the closed-book gate counting it
    twice would make one authority look like two.
    """
    seen: set[str] = set()
    ids: list[str] = []
    for piece in _as_list(value, where):
        name = _as_str(piece, f"{where} entry", allow_empty=False)
        if name in seen:
            raise BlockError(f"{where}: {name!r} is cited twice")
        seen.add(name)
        ids.append(name)
    return ids


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise BlockError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)}"
        )


def _require(body: dict[str, Any], key: str, where: str) -> Any:
    if key not in body:
        raise BlockError(f"{where}: missing required key {key!r}")
    return body[key]


# --------------------------------------------------------------------------
# block template
# --------------------------------------------------------------------------


@dataclass
class BlockPort:
    """One interface of a block.

    ``role`` is the port's identity *inside the block* and ``net`` is the net
    name the block's own geometry carries at that position. A template cut out
    of a board has nothing to go on but what is at the boundary, so there the
    two are equal — the cut tool does not invent roles (task 008a, work item 2).
    A hand-authored template may name them differently; the board spec's
    connections are what tie a role to a page-level net.

    ``position`` is a block-local file coordinate: the label / flag anchor the
    interface is drawn at. It is **required on a block that carries geometry**
    and **forbidden on one that does not** (2026-09-17 ruling):

    * a ``board-extract`` has geometry, and there the position must be the
      measured anchor — the port names a point that the cut actually saw;
    * a ``datasheet-extract`` / ``textbook`` block has no geometry, so it has no
      measured point to name. Writing one down would be inventing a coordinate,
      and the assembler synthesises the anchor instead (see
      :mod:`boardwise.engines.assemble`). ``[0, 0]`` is not "no position", it is
      a claim that the anchor is at the block origin — which is a lie unless
      something is actually drawn there.

    The last three fields are how two blocks say whether they may be joined,
    added in 008c item 4 and optional, so every template written before them
    still loads. They are what turns "this net looks wrong" into a question the
    checker can answer without a model in the loop:

    * ``direction`` (``"source"`` / ``"sink"``) — only on a power / ground port.
      A net must have exactly one source, so this is the one field the supply
      tree cannot judge without.
    * ``voltage`` — only on a **power** port: the rail's nominal value, written
      the way the design writes it (``"3V3"``, ``"5V"``). Compared as an exact
      string, because two spellings of one rail are two rails until someone
      proves otherwise.
    * ``level`` — only on a **signal** port: the IO domain it speaks. A net that
      joins two different domains needs a level shifter in between, and the
      checker can only say which side is wrong if both sides say something.

    A template with none of them is not invalid — it is *silent*, and the three
    gates that read them answer "cannot tell" for it rather than passing it.
    """

    role: str
    net: str
    net_class: str
    #: ``None`` on a block with no geometry: there is no measured anchor, and the
    #: assembler synthesises one. Never ``None`` on a ``board-extract``.
    position: Point | None
    direction: str = ""
    voltage: str = ""
    level: str = ""

    @property
    def is_signal(self) -> bool:
        return self.net_class == "signal"

    @property
    def is_source(self) -> bool:
        return self.direction == "source"

    @property
    def is_sink(self) -> bool:
        return self.direction == "sink"


@dataclass
class BlockParam:
    """One number the block leaves open, plus the rule that must accept it.

    ``provenance`` exists for the same reason the golden overrides sidecar has
    one: when a template's default is the *corrected* value rather than the one
    the source board recorded, a reader has to be able to see on whose authority
    (task 006b §G.3 — the fixture is evidence and is never edited).
    """

    name: str
    role: str
    default: str
    constraint: str
    provenance: str = ""


@dataclass
class BlockSymbol:
    """A library symbol's geometry — what one ``SYMBOL`` document contributes.

    ``offsets`` are pin-number -> symbol-local offset, ``body`` the measured
    drawn extent (RECT/POLY/CIRCLE union, **not** the pin extents — see
    :func:`boardwise.parsers.schematic.collect_symbol_bodies` for the
    measurement that forced that), and ``pin_names`` the library's own names.
    """

    uuid: str
    offsets: dict[str, Point] = field(default_factory=dict)
    body: tuple[float, float, float, float] | None = None
    pin_names: dict[str, str] = field(default_factory=dict)


@dataclass
class DeviceBinding:
    """How the connector should resolve the part on the shelf.

    The four resolution fields mirror :meth:`PlacementStep.resolution` and are
    tried in the same order (explicit uuid pair → lcsc → keyword). 008b will add
    a curated-library key in front of them; nothing here needs to change for
    that, which is why the binding is an object rather than four loose fields.
    """

    lcsc: str = ""
    keyword: str = ""
    device_uuid: str = ""
    library_uuid: str = ""
    #: The package the placement must *prove* it has (`lib_Footprint.get`). A
    #: mismatch is reported as a problem, which is what turns "we asked for a
    #: 0402" into a measurement.
    expect_footprint: str = ""
    #: The library device title (``Res_0402``), used when only a keyword is
    #: available and as the human-readable identity in reports.
    name: str = ""
    provenance: str = ""


@dataclass
class BlockComponent:
    """One part the block places, with its placement and its electrical pins."""

    ref: str
    symbol: str
    x: float
    y: float
    rotation: float = 0.0
    mirror: bool = False
    device: DeviceBinding = field(default_factory=DeviceBinding)
    footprint: str = ""
    #: Component property -> parameter name. ``{"value": "cc_pull"}`` means
    #: "this part's Value comes from the block parameter ``cc_pull``".
    params: dict[str, str] = field(default_factory=dict)
    #: ``[{number, name, net}]`` — the electrical facts. ``net`` uses the
    #: block's *local* net names; the assembler rewrites them per the spec's
    #: connections.
    pins: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TemplateWire:
    """One replayed wire run, block-local, with its net name (``""`` = unnamed)."""

    net: str
    points: list[Point]


@dataclass
class TemplateFlag:
    """One power / ground flag the block replays."""

    net: str
    kind: str  # 'Power' | 'Ground'
    x: float
    y: float
    rotation: float = 0.0
    mirror: bool = False
    symbol: str = ""


@dataclass
class TemplateLabel:
    """One visible signal-name anchor the block replays."""

    net: str
    x: float
    y: float
    rotation: float = 0.0


@dataclass
class BlockTemplate:
    """One block: parts, geometry, numbers and interfaces — all block-local."""

    name: str
    description: str
    provenance_kind: str
    provenance_source: str
    provenance_note: str
    origin_file: Point
    bbox_file: tuple[float, float, float, float]
    components: list[BlockComponent]
    symbols: dict[str, BlockSymbol]
    interface: list[BlockPort]
    params: list[BlockParam]
    wires: list[TemplateWire]
    flags: list[TemplateFlag]
    labels: list[TemplateLabel]
    path: str = ""
    notes: list[str] = field(default_factory=list)

    def param(self, name: str) -> BlockParam | None:
        for item in self.params:
            if item.name == name:
                return item
        return None

    def port(self, role: str) -> BlockPort | None:
        for item in self.interface:
            if item.role == role:
                return item
        return None

    def designators(self) -> list[str]:
        return [component.ref for component in self.components]


_TEMPLATE_KEYS = (
    "kind",
    "version",
    "name",
    "description",
    "provenance",
    "origin_file",
    "bbox_file",
    "notes",
    "interface",
    "params",
    "symbols",
    "components",
    "geometry",
)


def load_block_template(path: str | Path, *, port_meta: Any = None) -> BlockTemplate:
    """Read and validate a block template file.

    ``port_meta`` folds the port-metadata sidecar (:mod:`core.portmeta`) into the
    parsed document **before** validation, so the class rules for
    ``direction`` / ``voltage`` / ``level`` have exactly one enforcement point.
    Without it the file is read exactly as the board produced it, which is what
    keeps ``--recut`` byte-reproducible.
    """
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BlockError(f"{file}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise BlockError(f"{file}: not JSON: {exc}") from exc
    if port_meta is not None and port_meta.merge(raw):
        try:
            template = template_from_json(raw, where=str(file))
        except BlockError as exc:
            # Named so a rule broken by the sidecar does not read as one broken
            # by the file: the two live in different places and are edited by
            # different hands.
            raise BlockError(f"{exc} (with port metadata from {port_meta.path})") from exc
    else:
        template = template_from_json(raw, where=str(file))
    template.path = str(file)
    return template


def template_from_json(raw: Any, *, where: str = "<block>") -> BlockTemplate:
    """Validate one parsed block template. Pure; used by the loader and tests."""
    if not isinstance(raw, dict):
        raise BlockError(f"{where}: expected a JSON object")
    # `kind` is read before the key census: passing a board spec where a block
    # template belongs is the likeliest mistake, and "expected
    # 'boardwise-block-template', got 'boardwise-board-spec'" says so, where the
    # key census would only list the spec's keys as unknown.
    kind = _as_str(_require(raw, "kind", where), f"{where}.kind")
    if kind != BLOCK_TEMPLATE_KIND:
        raise BlockError(
            f"{where}.kind: expected {BLOCK_TEMPLATE_KIND!r}, got {kind!r}"
        )
    _check_keys(raw, _TEMPLATE_KEYS, where)
    version = raw.get("version")
    if version != SCHEMA_VERSION:
        raise BlockError(
            f"{where}.version: expected {SCHEMA_VERSION}, got {version!r}"
        )

    provenance = _require(raw, "provenance", where)
    if not isinstance(provenance, dict):
        raise BlockError(f"{where}.provenance: expected an object")
    _check_keys(provenance, ("kind", "source", "designators", "note"), f"{where}.provenance")
    prov_kind = _as_str(provenance.get("kind"), f"{where}.provenance.kind", allow_empty=False)
    if prov_kind not in PROVENANCE_KINDS:
        raise BlockError(
            f"{where}.provenance.kind: expected one of {', '.join(PROVENANCE_KINDS)}, "
            f"got {prov_kind!r}"
        )

    origin = _as_point(_require(raw, "origin_file", where), f"{where}.origin_file")
    bbox = _as_box(_require(raw, "bbox_file", where), f"{where}.bbox_file")

    # --- symbols
    symbols: dict[str, BlockSymbol] = {}
    raw_symbols = _require(raw, "symbols", where)
    if not isinstance(raw_symbols, dict):
        raise BlockError(f"{where}.symbols: expected an object keyed by symbol uuid")
    for uuid, body in raw_symbols.items():
        spot = f"{where}.symbols[{uuid}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("offsets", "body", "pin_names"), spot)
        if not uuid:
            raise BlockError(f"{spot}: the symbol uuid must not be empty")
        offsets: dict[str, Point] = {}
        for number, point in (_require(body, "offsets", spot) or {}).items():
            offsets[str(number)] = _as_point(point, f"{spot}.offsets[{number}]")
        names = {
            str(number): _as_str(name, f"{spot}.pin_names[{number}]")
            for number, name in (body.get("pin_names") or {}).items()
        }
        box = body.get("body")
        symbols[uuid] = BlockSymbol(
            uuid=uuid,
            offsets=offsets,
            body=None if box is None else _as_box(box, f"{spot}.body"),
            pin_names=names,
        )
    if not symbols:
        raise BlockError(f"{where}.symbols: a block with no symbol geometry cannot be drawn")

    # --- params
    params: list[BlockParam] = []
    seen_params: set[str] = set()
    for index, body in enumerate(_as_list(raw.get("params"), f"{where}.params")):
        spot = f"{where}.params[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("name", "role", "default", "constraint", "provenance"), spot)
        name = _as_str(_require(body, "name", spot), f"{spot}.name", allow_empty=False)
        if name in seen_params:
            raise BlockError(f"{spot}: duplicate parameter name {name!r}")
        seen_params.add(name)
        constraint = _as_str(
            _require(body, "constraint", spot), f"{spot}.constraint", allow_empty=False
        )
        if constraint not in CONSTRAINTS:
            raise BlockError(
                f"{spot}.constraint: unknown constraint {constraint!r}; known: "
                f"{', '.join(sorted(CONSTRAINTS))}"
            )
        default = _as_str(body.get("default"), f"{spot}.default")
        reason = check_constraint(constraint, default)
        if reason is not None:
            raise BlockError(f"{spot}.default {reason}")
        params.append(
            BlockParam(
                name=name,
                role=_as_str(body.get("role"), f"{spot}.role"),
                default=default,
                constraint=constraint,
                provenance=_as_str(body.get("provenance"), f"{spot}.provenance"),
            )
        )

    # --- components
    components: list[BlockComponent] = []
    seen_refs: set[str] = set()
    for index, body in enumerate(_as_list(_require(raw, "components", where), f"{where}.components")):
        spot = f"{where}.components[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(
            body, ("ref", "symbol", "placement", "device", "footprint", "params", "pins"), spot
        )
        ref = _as_str(_require(body, "ref", spot), f"{spot}.ref", allow_empty=False)
        if ref in seen_refs:
            raise BlockError(f"{spot}: duplicate ref {ref!r} inside one block")
        seen_refs.add(ref)
        symbol = _as_str(_require(body, "symbol", spot), f"{spot}.symbol", allow_empty=False)
        if symbol not in symbols:
            raise BlockError(f"{spot}.symbol: {symbol!r} is not in this block's symbols")

        placement = _require(body, "placement", spot)
        if not isinstance(placement, dict):
            raise BlockError(f"{spot}.placement: expected an object")
        _check_keys(placement, ("x", "y", "rotation", "mirror"), f"{spot}.placement")

        device_body = body.get("device") or {}
        if not isinstance(device_body, dict):
            raise BlockError(f"{spot}.device: expected an object")
        _check_keys(
            device_body,
            ("lcsc", "keyword", "device_uuid", "library_uuid", "expect_footprint", "name", "provenance"),
            f"{spot}.device",
        )
        device = DeviceBinding(
            lcsc=_as_str(device_body.get("lcsc"), f"{spot}.device.lcsc"),
            keyword=_as_str(device_body.get("keyword"), f"{spot}.device.keyword"),
            device_uuid=_as_str(device_body.get("device_uuid"), f"{spot}.device.device_uuid"),
            library_uuid=_as_str(device_body.get("library_uuid"), f"{spot}.device.library_uuid"),
            expect_footprint=_as_str(
                device_body.get("expect_footprint"), f"{spot}.device.expect_footprint"
            ),
            name=_as_str(device_body.get("name"), f"{spot}.device.name"),
            provenance=_as_str(device_body.get("provenance"), f"{spot}.device.provenance"),
        )

        binds: dict[str, str] = {}
        for prop, param_name in (body.get("params") or {}).items():
            text = _as_str(param_name, f"{spot}.params[{prop}]", allow_empty=False)
            if text not in seen_params:
                raise BlockError(
                    f"{spot}.params[{prop}]: {text!r} is not a parameter of this block"
                )
            binds[str(prop)] = text

        pins: list[dict[str, str]] = []
        for pin_index, pin in enumerate(_as_list(body.get("pins"), f"{spot}.pins")):
            pin_spot = f"{spot}.pins[{pin_index}]"
            if not isinstance(pin, dict):
                raise BlockError(f"{pin_spot}: expected an object")
            _check_keys(pin, ("number", "name", "net"), pin_spot)
            number = _as_str(_require(pin, "number", pin_spot), f"{pin_spot}.number", allow_empty=False)
            if number not in symbols[symbol].offsets:
                raise BlockError(
                    f"{pin_spot}: pin {number!r} of symbol {symbol!r} has no offset"
                )
            pins.append(
                {
                    "number": number,
                    "name": _as_str(pin.get("name"), f"{pin_spot}.name"),
                    "net": _as_str(pin.get("net"), f"{pin_spot}.net"),
                }
            )
        components.append(
            BlockComponent(
                ref=ref,
                symbol=symbol,
                x=_as_float(_require(placement, "x", f"{spot}.placement"), f"{spot}.placement.x"),
                y=_as_float(_require(placement, "y", f"{spot}.placement"), f"{spot}.placement.y"),
                rotation=_as_float(placement.get("rotation"), f"{spot}.placement.rotation"),
                mirror=_as_bool(placement.get("mirror"), f"{spot}.placement.mirror"),
                device=device,
                footprint=_as_str(body.get("footprint"), f"{spot}.footprint"),
                params=binds,
                pins=pins,
            )
        )
    if not components:
        raise BlockError(f"{where}.components: a block with no parts places nothing")

    # --- interface
    interface: list[BlockPort] = []
    seen_roles: set[str] = set()
    for index, body in enumerate(_as_list(raw.get("interface"), f"{where}.interface")):
        spot = f"{where}.interface[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(
            body,
            ("role", "net", "net_class", "position", "direction", "voltage", "level"),
            spot,
        )
        role = _as_str(_require(body, "role", spot), f"{spot}.role", allow_empty=False)
        if role in seen_roles:
            raise BlockError(f"{spot}: duplicate port role {role!r}")
        seen_roles.add(role)
        net_class = _as_str(
            _require(body, "net_class", spot), f"{spot}.net_class", allow_empty=False
        )
        if net_class not in NET_CLASSES:
            raise BlockError(
                f"{spot}.net_class: expected one of {', '.join(NET_CLASSES)}, got {net_class!r}"
            )
        direction = _as_str(body.get("direction"), f"{spot}.direction")
        if direction and direction not in PORT_DIRECTIONS:
            raise BlockError(
                f"{spot}.direction: expected one of {', '.join(PORT_DIRECTIONS)}, "
                f"got {direction!r}"
            )
        voltage = _as_str(body.get("voltage"), f"{spot}.voltage")
        level = _as_str(body.get("level"), f"{spot}.level")
        # One knob per job: a rail's magnitude is `voltage` and a signal's domain
        # is `level`, and putting either on the wrong class would mean the power
        # tree and the level check could disagree about one port.
        if net_class == "signal":
            if direction:
                raise BlockError(
                    f"{spot}.direction: {direction!r} is a claim about power; a "
                    "signal port says which domain it speaks with `level`"
                )
            if voltage:
                raise BlockError(
                    f"{spot}.voltage: {voltage!r} names a rail; a signal port says "
                    "which domain it speaks with `level`"
                )
        elif net_class == "power":
            if level:
                raise BlockError(
                    f"{spot}.level: {level!r} names an IO domain; a power rail is "
                    "named by `voltage`"
                )
        elif level or voltage:
            raise BlockError(
                f"{spot}: a ground port carries neither `voltage` nor `level` "
                "(only `direction`), got "
                f"{'level' if level else 'voltage'}={level or voltage!r}"
            )
        interface.append(
            BlockPort(
                role=role,
                net=_as_str(body.get("net"), f"{spot}.net") or role,
                net_class=net_class,
                # Whether a position is *required* or *forbidden* depends on
                # whether the block carries geometry, which is parsed below —
                # the split check runs once both are known.
                position=(
                    _as_point(body["position"], f"{spot}.position")
                    if "position" in body
                    else None
                ),
                direction=direction,
                voltage=voltage,
                level=level,
            )
        )

    # --- geometry
    geometry = _require(raw, "geometry", where)
    if not isinstance(geometry, dict):
        raise BlockError(f"{where}.geometry: expected an object")
    _check_keys(geometry, ("wires", "flags", "labels"), f"{where}.geometry")

    wires: list[TemplateWire] = []
    for index, body in enumerate(_as_list(geometry.get("wires"), f"{where}.geometry.wires")):
        spot = f"{where}.geometry.wires[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("net", "points"), spot)
        points = [
            _as_point(point, f"{spot}.points[{i}]")
            for i, point in enumerate(_as_list(_require(body, "points", spot), f"{spot}.points"))
        ]
        if len(points) < 2:
            raise BlockError(f"{spot}: a wire run needs at least two points")
        wires.append(TemplateWire(net=_as_str(body.get("net"), f"{spot}.net"), points=points))

    flags: list[TemplateFlag] = []
    for index, body in enumerate(_as_list(geometry.get("flags"), f"{where}.geometry.flags")):
        spot = f"{where}.geometry.flags[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("net", "kind", "x", "y", "rotation", "mirror", "symbol"), spot)
        kind = _as_str(_require(body, "kind", spot), f"{spot}.kind", allow_empty=False)
        if kind not in ("Power", "Ground"):
            raise BlockError(f"{spot}.kind: expected 'Power' or 'Ground', got {kind!r}")
        net = _as_str(_require(body, "net", spot), f"{spot}.net", allow_empty=False)
        flags.append(
            TemplateFlag(
                net=net,
                kind=kind,
                x=_as_float(_require(body, "x", spot), f"{spot}.x"),
                y=_as_float(_require(body, "y", spot), f"{spot}.y"),
                rotation=_as_float(body.get("rotation"), f"{spot}.rotation"),
                mirror=_as_bool(body.get("mirror"), f"{spot}.mirror"),
                symbol=_as_str(body.get("symbol"), f"{spot}.symbol"),
            )
        )

    labels: list[TemplateLabel] = []
    for index, body in enumerate(_as_list(geometry.get("labels"), f"{where}.geometry.labels")):
        spot = f"{where}.geometry.labels[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("net", "x", "y", "rotation"), spot)
        labels.append(
            TemplateLabel(
                net=_as_str(_require(body, "net", spot), f"{spot}.net", allow_empty=False),
                x=_as_float(_require(body, "x", spot), f"{spot}.x"),
                y=_as_float(_require(body, "y", spot), f"{spot}.y"),
                rotation=_as_float(body.get("rotation"), f"{spot}.rotation"),
            )
        )

    # --- the geometry/position split (2026-09-17 ruling)
    #
    # A port's position is the anchor a name is drawn at, and where that anchor
    # *comes from* depends on whether the block has geometry to have measured it
    # in. Getting this wrong is silent in both directions: a board-extract
    # without a position would have its port named at a synthesised point
    # instead of the one the cut actually saw, and a geometry-less block with a
    # position would carry a coordinate nobody measured — which is exactly what
    # `[0, 0]` was, and it looked like data.
    has_geometry = bool(wires or flags or labels)
    for index, port in enumerate(interface):
        spot = f"{where}.interface[{index}]"
        if has_geometry:
            if port.position is None:
                raise BlockError(
                    f"{spot}.position: {port.role!r} is on a block that carries "
                    f"geometry ({len(wires)} wire run(s), {len(flags)} flag(s), "
                    f"{len(labels)} label(s)), so its anchor is a measured point "
                    "and must be written down. A board-extract's ports name where "
                    "the cut actually drew them."
                )
        elif port.position is not None:
            raise BlockError(
                f"{spot}.position: {port.role!r} is on a block with no geometry, "
                f"so there is no measured anchor to name — got "
                f"{list(port.position)}. Writing a coordinate here would be a "
                "claim nobody measured ([0, 0] is not 'no position', it is 'the "
                "anchor is at the block origin'); the assembler synthesises the "
                "anchor for a geometry-less block instead. Remove the field."
            )

    return BlockTemplate(
        name=_as_str(_require(raw, "name", where), f"{where}.name", allow_empty=False),
        description=_as_str(raw.get("description"), f"{where}.description"),
        provenance_kind=prov_kind,
        provenance_source=_as_str(provenance.get("source"), f"{where}.provenance.source"),
        provenance_note=_as_str(provenance.get("note"), f"{where}.provenance.note"),
        origin_file=origin,
        bbox_file=bbox,
        components=components,
        symbols=symbols,
        interface=interface,
        params=params,
        wires=wires,
        flags=flags,
        labels=labels,
        notes=[_as_str(n, f"{where}.notes[]") for n in _as_list(raw.get("notes"), f"{where}.notes")],
    )


def _port_to_json(port: BlockPort) -> dict[str, Any]:
    """One port, with the optional fields written **only when set**.

    Writing them unconditionally would make every template produced by the cut
    tool today differ from the one it produced yesterday for no reason; writing
    them conditionally is what keeps the round-trip byte-stable. ``position``
    joins them for the same reason: a geometry-less block has none, and writing
    ``[0, 0]`` for it is precisely the lie the 2026-09-17 ruling forbids.
    """
    body: dict[str, Any] = {
        "role": port.role,
        "net": port.net,
        "net_class": port.net_class,
    }
    if port.position is not None:
        body["position"] = [port.position[0], port.position[1]]
    if port.direction:
        body["direction"] = port.direction
    if port.voltage:
        body["voltage"] = port.voltage
    if port.level:
        body["level"] = port.level
    return body


def template_to_json(template: BlockTemplate) -> dict[str, Any]:
    """Serialise a template back to the on-disk shape.

    Round-trips with :func:`template_from_json` for everything the loader keeps,
    which is what the cut tool's tests assert — a template that cannot be
    re-read is not a template.
    """
    return {
        "kind": BLOCK_TEMPLATE_KIND,
        "version": SCHEMA_VERSION,
        "name": template.name,
        "description": template.description,
        "provenance": {
            "kind": template.provenance_kind,
            "source": template.provenance_source,
            "designators": [c.ref for c in template.components],
            "note": template.provenance_note,
        },
        "origin_file": [template.origin_file[0], template.origin_file[1]],
        "bbox_file": list(template.bbox_file),
        "notes": list(template.notes),
        "interface": [_port_to_json(port) for port in template.interface],
        "params": [
            {
                "name": param.name,
                "role": param.role,
                "default": param.default,
                "constraint": param.constraint,
                "provenance": param.provenance,
            }
            for param in template.params
        ],
        "symbols": {
            uuid: {
                "offsets": {n: [p[0], p[1]] for n, p in sorted(symbol.offsets.items())},
                "body": None if symbol.body is None else list(symbol.body),
                "pin_names": {n: v for n, v in sorted(symbol.pin_names.items())},
            }
            for uuid, symbol in sorted(template.symbols.items())
        },
        "components": [
            {
                "ref": component.ref,
                "symbol": component.symbol,
                "placement": {
                    "x": component.x,
                    "y": component.y,
                    "rotation": component.rotation,
                    "mirror": component.mirror,
                },
                "device": {
                    "lcsc": component.device.lcsc,
                    "keyword": component.device.keyword,
                    "device_uuid": component.device.device_uuid,
                    "library_uuid": component.device.library_uuid,
                    "expect_footprint": component.device.expect_footprint,
                    "name": component.device.name,
                    "provenance": component.device.provenance,
                },
                "footprint": component.footprint,
                "params": dict(component.params),
                "pins": [dict(pin) for pin in component.pins],
            }
            for component in template.components
        ],
        "geometry": {
            "wires": [
                {"net": wire.net, "points": [[x, y] for x, y in wire.points]}
                for wire in template.wires
            ],
            "flags": [
                {
                    "net": flag.net,
                    "kind": flag.kind,
                    "x": flag.x,
                    "y": flag.y,
                    "rotation": flag.rotation,
                    "mirror": flag.mirror,
                    "symbol": flag.symbol,
                }
                for flag in template.flags
            ],
            "labels": [
                {
                    "net": label.net,
                    "x": label.x,
                    "y": label.y,
                    "rotation": label.rotation,
                }
                for label in template.labels
            ],
        },
    }


def net_class_of(net: str, flag_kinds: dict[str, str]) -> str:
    """The interface class of a net: ``gnd`` / ``power`` / ``signal``.

    Ground by name (:func:`boardwise.core.model.is_ground_net`), power when a
    flag on that net is a ``Power`` flag, signal otherwise. Derived from what
    the board actually says — no name heuristics beyond the one the model
    already owns.
    """
    if is_ground_net(net):
        return "gnd"
    if flag_kinds.get(net) == "Power":
        return "power"
    return "signal"


# --------------------------------------------------------------------------
# board spec
# --------------------------------------------------------------------------


@dataclass
class BlockInstance:
    """One template placed on the page, at a position in file coordinates."""

    id: str
    template_path: str
    template: BlockTemplate
    at: Point
    note: str = ""
    #: Reference ids declared in the spec (`BoardSpec.references`) that say why
    #: **this block is here at all**. Empty means nothing declares it, which the
    #: closed-book gate reports rather than accepting.
    evidence: list[str] = field(default_factory=list)

    @property
    def origin_at_cut(self) -> Point:
        return self.template.origin_file


@dataclass
class BlockConnection:
    """One page-level net, and the ports that are on it."""

    net: str
    ports: list[tuple[str, str]]  # (block id, port role)
    #: Reference ids saying where the decision to join these ports came from.
    evidence: list[str] = field(default_factory=list)


@dataclass
class SpecReference:
    """One declared input a spec is allowed to justify its fields from.

    The closed-book gate (008c item 4) asks every block, every parameter value
    and every connection to name such a thing. It is deliberately not a free
    citation: the kind comes from :data:`REFERENCE_KINDS`, and each kind says
    which field carries its identity — a file for `intent` / `pintable` /
    `datasheet`, a shelf key for `part`, and nothing but a name for `textbook`.
    """

    id: str
    kind: str
    path: str = ""
    #: The key the reference names when there is no file to point at: a part's
    #: key in the curated library, or a textbook topology's name.
    ref: str = ""
    #: Where inside it ("page 5", "§ Typical Application"), or what it is.
    note: str = ""


# ---------------------------------------------------------------------------
# Per-instance designators (008c item 6)
# ---------------------------------------------------------------------------

#: How far apart two instances of the same template number their parts: an
#: instance's designator is the template's, with the numeric part offset by
#: ``ordinal * DESIGNATOR_STRIDE``. Ordinal 0 is the template's own numbering
#: verbatim, so a spec with one instance per template produces exactly what
#: 008a produced.
#:
#: The stride is a *policy*, and it is stated rather than hidden because it has
#: a limit: a template needing more than 100 refs of one letter prefix in a
#: single page cannot be offset safely, and the collision is caught by
#: `assemble._check_designators` rather than silently producing two parts that
#: claim the same name.
DESIGNATOR_STRIDE = 100

_DESIGNATOR = re.compile(r"^(?P<prefix>[A-Za-z]+)(?P<number>\d+)$")


def derive_designator(ref: str, ordinal: int) -> str:
    """The page designator of a template ref, in instance ``ordinal``.

    Deterministic, and deliberately narrow: a ref that is not ``letters +
    digits`` is **refused** rather than mangled into something the editor would
    accept — a designator derived from a shape nobody has seen is exactly the
    silent invention the rest of this codebase refuses to make.
    """
    if ordinal < 0:
        raise BlockError(f"derive_designator: ordinal {ordinal} is negative")
    if ordinal == 0:
        return ref
    match = _DESIGNATOR.match(ref)
    if match is None:
        raise BlockError(
            f"derive_designator: {ref!r} is not a letter-plus-digit designator, so "
            f"instance {ordinal} cannot be given a derived one"
        )
    return f"{match['prefix']}{int(match['number']) + ordinal * DESIGNATOR_STRIDE}"


def template_identity(block: BlockInstance) -> str:
    """What makes two instances "the same block".

    The **resolved template path** when the spec was loaded from a file, which is
    the artifact's identity. A hand-built `BlockInstance` (tests, future callers)
    has no path, so its template's name stands in — a weaker key, and the reason
    this is named and documented rather than inlined.
    """
    return block.template_path or f"<name:{block.template.name}>"


def instance_ordinals(spec: BoardSpec) -> dict[str, int]:
    """block id -> its ordinal among the instances of its own template.

    Refuses duplicate block ids. `load_board_spec` already does, so this is a
    safety net for hand-built specs — and it earns its keep: every helper here is
    keyed by id, so a duplicate would silently *overwrite* the first block's
    entry and report a clash between two names that are actually the same one.
    """
    seen_ids: set[str] = set()
    seen: dict[str, int] = {}
    ordinals: dict[str, int] = {}
    for block in spec.blocks:
        if block.id in seen_ids:
            raise BlockError(
                f"two blocks share the id {block.id!r}; instances of one template "
                "must have distinct ids, because every page name is keyed by it"
            )
        seen_ids.add(block.id)
        key = template_identity(block)
        ordinals[block.id] = seen.get(key, 0)
        seen[key] = ordinals[block.id] + 1
    return ordinals


def designator_map(spec: BoardSpec) -> dict[str, dict[str, str]]:
    """``block id -> {template ref: page ref}`` for every block in a spec.

    The one place the derivation is applied, so the assembler, the clash check
    and (later) the BOM all read the same answer.
    """
    ordinals = instance_ordinals(spec)
    return {
        block.id: {
            component.ref: derive_designator(component.ref, ordinals[block.id])
            for component in block.template.components
        }
        for block in spec.blocks
    }


def repeated_templates(spec: BoardSpec) -> dict[str, list[str]]:
    """``template identity -> block ids`` for the templates used more than once."""
    grouped: dict[str, list[str]] = {}
    for block in spec.blocks:
        grouped.setdefault(template_identity(block), []).append(block.id)
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}


@dataclass
class BoardSpec:
    """A page: which blocks, where, with what numbers, wired how."""

    name: str
    description: str
    provenance_kind: str
    provenance_source: str
    provenance_note: str
    blocks: list[BlockInstance]
    connections: list[BlockConnection]
    #: ``"<block id>.<param name>"`` -> value. Anything not listed keeps the
    #: template's default.
    params: dict[str, str]
    #: The page the assembly targets; a fallback for hosts that expose no
    #: measurable sheet bbox (the draw flow measures the live page first).
    sheet_attrs: dict[str, str]
    sheet_origin: Point
    #: ``"<block id>.<param name>"`` -> reference ids saying where that value
    #: came from. Parallel to `params` rather than folded into it, because the
    #: values existed before the evidence did and no spec should have to be
    #: rewritten to grow a citation. A key missing here is a violation, not a
    #: default: a number nobody can account for is exactly what this is for.
    param_evidence: dict[str, list[str]] = field(default_factory=dict)
    #: Every source this page is allowed to cite. Nothing outside this list can
    #: justify a field — which is what makes "where did that come from?" a
    #: machine-checkable question instead of a matter of trust.
    references: list[SpecReference] = field(default_factory=list)
    path: str = ""
    notes: list[str] = field(default_factory=list)

    def instance(self, block_id: str) -> BlockInstance | None:
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None

    def reference(self, ref_id: str) -> SpecReference | None:
        for item in self.references:
            if item.id == ref_id:
                return item
        return None

    def parameter_value(self, block_id: str, param_name: str) -> str:
        """The value a parameter takes: the spec's assignment, else the default.

        Raises when either name is unknown — a spec that names a parameter the
        template does not have is a typo, and silently ignoring it would leave
        the block running on a default the author never chose.
        """
        block = self.instance(block_id)
        if block is None:
            raise BlockError(f"params: no block {block_id!r} in this spec")
        param = block.template.param(param_name)
        if param is None:
            raise BlockError(
                f"block {block_id!r}: no parameter {param_name!r}; it has "
                f"{', '.join(p.name for p in block.template.params) or '(none)'}"
            )
        if f"{block_id}.{param_name}" in self.params:
            value = self.params[f"{block_id}.{param_name}"]
            reason = check_constraint(param.constraint, value)
            if reason is not None:
                raise BlockError(
                    f"params[{block_id}.{param_name}] {reason} "
                    f"(constraint {param.constraint})"
                )
            return value
        return param.default


_SPEC_KEYS = (
    "kind",
    "version",
    "name",
    "description",
    "provenance",
    "sheet",
    "notes",
    "blocks",
    "connections",
    "params",
    "references",
    "param_evidence",
)


def load_board_spec(
    path: str | Path, *, port_meta: Any = None
) -> BoardSpec:
    """Read and validate a board spec, resolving its template paths.

    Template paths are relative to the **spec file**, so a spec and its blocks
    can be moved together without rewriting either. ``port_meta`` is passed down
    to every template it loads (see :func:`load_block_template`).
    """
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BlockError(f"{file}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise BlockError(f"{file}: not JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise BlockError(f"{file}: expected a JSON object")
    # See the note in `template_from_json`: the kind is read first so that
    # "you handed me a block template" is the message, not a list of keys.
    kind = _as_str(_require(raw, "kind", str(file)), f"{file}.kind")
    if kind != BOARD_SPEC_KIND:
        raise BlockError(f"{file}.kind: expected {BOARD_SPEC_KIND!r}, got {kind!r}")
    _check_keys(raw, _SPEC_KEYS, str(file))
    if raw.get("version") != SCHEMA_VERSION:
        raise BlockError(f"{file}.version: expected {SCHEMA_VERSION}, got {raw.get('version')!r}")

    provenance = _require(raw, "provenance", str(file))
    if not isinstance(provenance, dict):
        raise BlockError(f"{file}.provenance: expected an object")
    _check_keys(provenance, ("kind", "source", "note"), f"{file}.provenance")
    prov_kind = _as_str(provenance.get("kind"), f"{file}.provenance.kind", allow_empty=False)
    if prov_kind not in PROVENANCE_KINDS:
        raise BlockError(
            f"{file}.provenance.kind: expected one of {', '.join(PROVENANCE_KINDS)}, "
            f"got {prov_kind!r}"
        )

    blocks: list[BlockInstance] = []
    seen_ids: set[str] = set()
    for index, body in enumerate(_as_list(_require(raw, "blocks", str(file)), f"{file}.blocks")):
        spot = f"{file}.blocks[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("id", "template", "at", "note", "evidence"), spot)
        block_id = _as_str(_require(body, "id", spot), f"{spot}.id", allow_empty=False)
        if block_id in seen_ids:
            raise BlockError(f"{spot}: duplicate block id {block_id!r}")
        seen_ids.add(block_id)
        template_rel = _as_str(_require(body, "template", spot), f"{spot}.template", allow_empty=False)
        template_path = (file.parent / template_rel).resolve()
        template = load_block_template(template_path, port_meta=port_meta)
        # `at` defaults to where the block was cut from, so a spec that only
        # wants "put everything back" does not have to restate the origins.
        at = (
            template.origin_file
            if body.get("at") is None
            else _as_point(body["at"], f"{spot}.at")
        )
        blocks.append(
            BlockInstance(
                id=block_id,
                template_path=str(template_path),
                template=template,
                at=at,
                note=_as_str(body.get("note"), f"{spot}.note"),
                evidence=_as_evidence(body.get("evidence", []), f"{spot}.evidence"),
            )
        )
    if not blocks:
        raise BlockError(f"{file}.blocks: a board with no blocks draws nothing")

    connections: list[BlockConnection] = []
    for index, body in enumerate(_as_list(raw.get("connections"), f"{file}.connections")):
        spot = f"{file}.connections[{index}]"
        if not isinstance(body, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(body, ("net", "ports", "evidence"), spot)
        net = _as_str(_require(body, "net", spot), f"{spot}.net", allow_empty=False)
        ports: list[tuple[str, str]] = []
        for port_index, entry in enumerate(_as_list(_require(body, "ports", spot), f"{spot}.ports")):
            port_spot = f"{spot}.ports[{port_index}]"
            if not (isinstance(entry, list) and len(entry) == 2):
                raise BlockError(f"{port_spot}: expected [block id, port role]")
            block_id = _as_str(entry[0], f"{port_spot}[0]", allow_empty=False)
            role = _as_str(entry[1], f"{port_spot}[1]", allow_empty=False)
            instance = next((b for b in blocks if b.id == block_id), None)
            if instance is None:
                raise BlockError(f"{port_spot}: no block {block_id!r} in this spec")
            if instance.template.port(role) is None:
                raise BlockError(
                    f"{port_spot}: block {block_id!r} has no port {role!r}; it has "
                    f"{', '.join(p.role for p in instance.template.interface) or '(none)'}"
                )
            ports.append((block_id, role))
        if len(ports) < 2:
            raise BlockError(
                f"{spot}: a connection needs at least two ports; an internal net is "
                "not a connection"
            )
        connections.append(
            BlockConnection(
                net=net,
                ports=ports,
                evidence=_as_evidence(body.get("evidence", []), f"{spot}.evidence"),
            )
        )

    references: list[SpecReference] = []
    seen_refs: set[str] = set()
    for index, item in enumerate(_as_list(raw.get("references"), f"{file}.references")):
        spot = f"{file}.references[{index}]"
        if not isinstance(item, dict):
            raise BlockError(f"{spot}: expected an object")
        _check_keys(item, ("id", "kind", "path", "ref", "note"), spot)
        ref_id = _as_str(_require(item, "id", spot), f"{spot}.id", allow_empty=False)
        if ref_id in seen_refs:
            raise BlockError(f"{spot}: duplicate reference id {ref_id!r}")
        seen_refs.add(ref_id)
        ref_kind = _as_str(_require(item, "kind", spot), f"{spot}.kind", allow_empty=False)
        if ref_kind not in REFERENCE_KINDS:
            raise BlockError(
                f"{spot}.kind: expected one of {', '.join(REFERENCE_KINDS)}, got {ref_kind!r}"
            )
        path = _as_str(item.get("path"), f"{spot}.path")
        ref = _as_str(item.get("ref"), f"{spot}.ref")
        note = _as_str(item.get("note"), f"{spot}.note")
        # Each kind names exactly where its identity lives, so a citation can
        # always be resolved to something checkable rather than to a phrase.
        if ref_kind in ("intent", "pintable", "datasheet") and not path:
            raise BlockError(f"{spot}: a {ref_kind} reference names the file it is")
        if ref_kind == "part" and not ref:
            raise BlockError(f"{spot}: a part reference names the shelf key it cites")
        if ref_kind == "textbook" and not note:
            raise BlockError(
                f"{spot}: a textbook reference names the topology it follows "
                "(no page to point at, so the name is the citation)"
            )
        references.append(
            SpecReference(id=ref_id, kind=ref_kind, path=path, ref=ref, note=note)
        )

    param_evidence = {
        key: _as_evidence(value, f"{file}.param_evidence[{key}]")
        for key, value in (raw.get("param_evidence") or {}).items()
    }

    params = {
        _as_str(key, f"{file}.params key", allow_empty=False): _as_str(
            value, f"{file}.params[{key}]"
        )
        for key, value in (raw.get("params") or {}).items()
    }

    sheet = raw.get("sheet") or {}
    if not isinstance(sheet, dict):
        raise BlockError(f"{file}.sheet: expected an object")
    _check_keys(sheet, ("attrs", "origin"), f"{file}.sheet")
    sheet_attrs = {
        _as_str(key, f"{file}.sheet.attrs key"): _as_str(value, f"{file}.sheet.attrs[{key}]")
        for key, value in (sheet.get("attrs") or {}).items()
    }
    sheet_origin = (
        (0.0, 0.0)
        if sheet.get("origin") is None
        else _as_point(sheet["origin"], f"{file}.sheet.origin")
    )

    spec = BoardSpec(
        name=_as_str(_require(raw, "name", str(file)), f"{file}.name", allow_empty=False),
        description=_as_str(raw.get("description"), f"{file}.description"),
        provenance_kind=prov_kind,
        provenance_source=_as_str(provenance.get("source"), f"{file}.provenance.source"),
        provenance_note=_as_str(provenance.get("note"), f"{file}.provenance.note"),
        blocks=blocks,
        connections=connections,
        params=params,
        param_evidence=param_evidence,
        references=references,
        sheet_attrs=sheet_attrs,
        sheet_origin=sheet_origin,
        path=str(file),
        notes=[_as_str(n, f"{file}.notes[]") for n in _as_list(raw.get("notes"), f"{file}.notes")],
    )
    # Every assigned parameter must name a real block and a real parameter —
    # checked up front so the failure names the spec, not a later caller.
    for key in params:
        head, _, tail = key.partition(".")
        if not tail:
            raise BlockError(
                f"{file}.params[{key}]: keys are '<block id>.<parameter name>'"
            )
        spec.parameter_value(head, tail)
    # An evidence key that names no parameter is either a typo or evidence for a
    # value nobody assigned; both hide the thing the evidence is there to prove.
    for key in param_evidence:
        if key not in params:
            raise BlockError(
                f"{file}.param_evidence[{key}]: there is no such parameter value "
                "in `params` to justify"
            )
    return spec


__all__ = [
    "BLOCK_TEMPLATE_KIND",
    "BOARD_SPEC_KIND",
    "BlockComponent",
    "BlockConnection",
    "BlockError",
    "BlockInstance",
    "BlockParam",
    "BlockPort",
    "BlockSymbol",
    "BlockTemplate",
    "BoardSpec",
    "CONSTRAINTS",
    "DESIGNATOR_STRIDE",
    "DeviceBinding",
    "NET_CLASSES",
    "PORT_DIRECTIONS",
    "PROVENANCE_KINDS",
    "REFERENCE_KINDS",
    "SCHEMA_VERSION",
    "SpecReference",
    "TemplateFlag",
    "TemplateLabel",
    "TemplateWire",
    "check_constraint",
    "derive_designator",
    "designator_map",
    "instance_ordinals",
    "load_block_template",
    "load_board_spec",
    "net_class_of",
    "repeated_templates",
    "template_identity",
    "template_from_json",
    "template_to_json",
]
